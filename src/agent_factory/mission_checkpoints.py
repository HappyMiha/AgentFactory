"""Immutable execution epochs and reconstructible Autonomous Mission checkpoints."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from .autonomous_mission import (
    AutonomousMission,
    AutonomousMissionService,
    MissionDisposition,
    MissionPhase,
    MissionVersionConflictError,
)
from .storage import SQLiteStorage


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
EXECUTION_PHASES = frozenset(
    {
        MissionPhase.APPROVED,
        MissionPhase.ENVIRONMENT_DISCOVERY,
        MissionPhase.ENVIRONMENT_BOOTSTRAP,
        MissionPhase.DEVELOPMENT,
        MissionPhase.VALIDATION,
        MissionPhase.INTEGRATION,
        MissionPhase.FINAL_VALIDATION,
    }
)


class ExecutionEpochOrigin(StrEnum):
    INITIAL = "INITIAL"
    CHECKPOINT_RESTART = "CHECKPOINT_RESTART"
    BACKLOG_REVISION_RESTART = "BACKLOG_REVISION_RESTART"
    RECOVERY = "RECOVERY"


class MissionCheckpointType(StrEnum):
    BACKLOG_APPROVED = "BACKLOG_APPROVED"
    ENVIRONMENT_BOOTSTRAPPED = "ENVIRONMENT_BOOTSTRAPPED"
    ARCHITECTURE_BASELINE = "ARCHITECTURE_BASELINE"
    WORK_ITEM_ACCEPTED = "WORK_ITEM_ACCEPTED"
    REPAIR_ACCEPTED = "REPAIR_ACCEPTED"
    BACKLOG_REVISION_APPLIED = "BACKLOG_REVISION_APPLIED"
    INTEGRATION_MILESTONE = "INTEGRATION_MILESTONE"
    FINAL_VALIDATION = "FINAL_VALIDATION"
    MANUAL = "MANUAL"


class CheckpointIntegrityError(RuntimeError):
    """Raised when durable checkpoint state no longer matches its digest or Git root."""


@dataclass(frozen=True)
class TemporalRunReference:
    id: int
    execution_epoch_id: int
    sequence: int
    workflow_id: str
    run_id: str
    previous_run_id: str | None
    workflow_build_id: str | None
    metadata: dict[str, Any]
    metadata_digest: str
    command_id: str
    created_at: str


@dataclass(frozen=True)
class MissionExecutionEpoch:
    id: int
    identity: str
    mission_id: int
    epoch_number: int
    base_backlog_revision_id: int
    base_backlog_revision_digest: str
    base_checkpoint_id: int | None
    base_checkpoint_digest: str | None
    base_git_commit_sha: str
    epoch_branch: str
    origin: ExecutionEpochOrigin
    temporal_workflow_id: str
    temporal_first_run_id: str
    temporal_chain_metadata: dict[str, Any]
    temporal_chain_metadata_digest: str
    supersedes_epoch_id: int | None
    activation_mission_version: int
    created_by: str
    reason: str
    created_at: str
    temporal_runs: tuple[TemporalRunReference, ...]
    is_active: bool
    superseded_by_epoch_id: int | None
    superseded_at: str | None


@dataclass(frozen=True)
class MissionCheckpoint:
    id: int
    identity: str
    checkpoint_key: str
    mission_id: int
    execution_epoch_id: int
    sequence: int
    checkpoint_type: MissionCheckpointType
    reason: str
    created_by: str
    created_at: str
    backlog_revision_id: int
    backlog_revision_digest: str
    git_commit_sha: str
    git_branch: str
    git_worktree_path: str
    checkpoint_digest: str
    document: dict[str, Any]
    is_current: bool
    epoch_superseded: bool
    restart_base_for_epoch_ids: tuple[int, ...]


class MissionCheckpointService:
    """Own epoch activation and content-addressed checkpoint history."""

    def __init__(self, storage: SQLiteStorage):
        self.storage = storage
        self.missions = AutonomousMissionService(storage)

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

    @classmethod
    def _digest(cls, value: Any) -> str:
        return hashlib.sha256(cls._json(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _required(value: str, label: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError(f"{label} is required")
        return normalized

    @staticmethod
    def _optional_id(value: Any) -> int | None:
        return int(value) if value is not None else None

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    @staticmethod
    def _sha256(value: str, label: str) -> str:
        normalized = str(value).strip().lower()
        if not SHA256_PATTERN.fullmatch(normalized):
            raise ValueError(f"{label} must be a lowercase SHA-256 digest")
        return normalized

    @staticmethod
    def _commit(value: str, label: str = "Git commit") -> str:
        normalized = str(value).strip().lower()
        if not COMMIT_PATTERN.fullmatch(normalized):
            raise ValueError(f"{label} must be a complete hexadecimal commit SHA")
        return normalized

    @staticmethod
    def _git(path: Path, *arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(path), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise CheckpointIntegrityError(
                f"Git checkpoint verification failed: {detail or arguments[0]}"
            )
        return result.stdout.strip()

    def _repository(self, mission: AutonomousMission) -> Path:
        configured = mission.configuration.repository_path
        if not configured:
            raise ValueError("Autonomous execution requires a configured repository path")
        repository = Path(configured).expanduser().resolve()
        if not repository.is_dir():
            raise ValueError(f"Configured repository does not exist: {repository}")
        self._git(repository, "rev-parse", "--git-dir")
        return repository

    def _resolve_commit(
        self,
        mission: AutonomousMission,
        commit_sha: str,
        *,
        worktree_path: str | None = None,
        require_clean_head: bool,
    ) -> tuple[str, Path]:
        requested = self._commit(commit_sha)
        repository = self._repository(mission)
        worktree = (
            Path(worktree_path).expanduser().resolve()
            if worktree_path is not None
            else repository
        )
        if not worktree.is_dir():
            raise CheckpointIntegrityError(
                f"Checkpoint worktree does not exist: {worktree}"
            )
        resolved = self._git(worktree, "rev-parse", "--verify", f"{requested}^{{commit}}")
        resolved = self._commit(resolved, "Resolved Git commit")
        self._git(repository, "cat-file", "-e", f"{resolved}^{{commit}}")
        if require_clean_head:
            head = self._commit(self._git(worktree, "rev-parse", "HEAD"), "Git HEAD")
            if head != resolved:
                raise CheckpointIntegrityError(
                    "A checkpoint commit must be the authoritative worktree HEAD"
                )
            if self._git(worktree, "status", "--porcelain", "--untracked-files=normal"):
                raise CheckpointIntegrityError(
                    "A dirty worktree cannot become an authoritative checkpoint"
                )
        return resolved, worktree

    def _revision(self, mission_id: int, revision_id: int):
        row = self.storage.db.execute(
            """SELECT id,mission_id,revision_number,revision_digest
                 FROM autonomous_backlog_revisions WHERE id=?""",
            (revision_id,),
        ).fetchone()
        if not row or int(row["mission_id"]) != mission_id:
            raise ValueError("Backlog revision does not belong to this mission")
        return row

    def _epoch_replay(
        self, command_id: str, request_digest: str
    ) -> MissionExecutionEpoch | None:
        mission = self.missions._command_replay(command_id, request_digest)
        if mission is None:
            return None
        epoch_id = mission.active_execution_epoch_id
        if epoch_id is None:
            raise RuntimeError("Epoch command replay is missing its active epoch result")
        return self.get_epoch(epoch_id)

    def _checkpoint_replay(
        self, command_id: str, request_digest: str
    ) -> MissionCheckpoint | None:
        mission = self.missions._command_replay(command_id, request_digest)
        if mission is None:
            return None
        checkpoint_id = mission.current_checkpoint_id
        if checkpoint_id is None:
            raise RuntimeError("Checkpoint command replay is missing its checkpoint result")
        return self.get_checkpoint(checkpoint_id)

    def create_epoch(
        self,
        mission_id: int,
        *,
        expected_mission_version: int,
        expected_backlog_revision_id: int,
        expected_active_epoch_id: int | None,
        actor: str,
        command_id: str,
        reason: str,
        epoch_branch: str,
        temporal_workflow_id: str,
        temporal_run_id: str,
        temporal_chain_metadata: dict[str, Any] | None = None,
        workflow_build_id: str | None = None,
        origin: ExecutionEpochOrigin | str = ExecutionEpochOrigin.INITIAL,
        base_checkpoint_id: int | None = None,
        base_git_commit_sha: str | None = None,
    ) -> MissionExecutionEpoch:
        """Create and atomically activate the next append-only execution epoch."""

        actor = self._required(actor, "Epoch actor")
        command_id = self._required(command_id, "Command id")
        reason = self._required(reason, "Epoch reason")
        epoch_branch = self._required(epoch_branch, "Epoch branch")
        temporal_workflow_id = self._required(
            temporal_workflow_id, "Temporal workflow id"
        )
        temporal_run_id = self._required(temporal_run_id, "Temporal run id")
        origin = ExecutionEpochOrigin(origin)
        build_id = (
            self._required(workflow_build_id, "Workflow build id")
            if workflow_build_id is not None
            else None
        )
        metadata = dict(temporal_chain_metadata or {})
        reserved = {
            "workflow_id": temporal_workflow_id,
            "first_run_id": temporal_run_id,
            "workflow_build_id": build_id,
        }
        for key, expected in reserved.items():
            if key in metadata and metadata[key] != expected:
                raise ValueError(f"Temporal metadata cannot override {key}")
            metadata[key] = expected
        metadata_digest = self._digest(metadata)
        revision = self._revision(mission_id, expected_backlog_revision_id)

        checkpoint_row = None
        base_checkpoint_digest = None
        if base_checkpoint_id is not None:
            checkpoint_row = self.storage.db.execute(
                "SELECT * FROM autonomous_mission_checkpoints WHERE id=?",
                (base_checkpoint_id,),
            ).fetchone()
            if not checkpoint_row or int(checkpoint_row["mission_id"]) != mission_id:
                raise ValueError("Base checkpoint does not belong to this mission")
            base_checkpoint_digest = str(checkpoint_row["checkpoint_digest"])
            checkpoint_commit = str(checkpoint_row["git_commit_sha"])
            if (
                base_git_commit_sha is not None
                and self._commit(base_git_commit_sha) != checkpoint_commit
            ):
                raise ValueError("Base commit does not match the selected checkpoint")
            normalized_commit = checkpoint_commit
        else:
            if base_git_commit_sha is None:
                raise ValueError("The initial epoch requires a base Git commit")
            normalized_commit = self._commit(base_git_commit_sha)

        request = {
            "type": "create_execution_epoch",
            "mission_id": mission_id,
            "expected_mission_version": expected_mission_version,
            "expected_backlog_revision_id": expected_backlog_revision_id,
            "expected_active_epoch_id": expected_active_epoch_id,
            "actor": actor,
            "reason": reason,
            "epoch_branch": epoch_branch,
            "origin": origin.value,
            "base_checkpoint_id": base_checkpoint_id,
            "base_checkpoint_digest": base_checkpoint_digest,
            "base_git_commit_sha": normalized_commit,
            "temporal_workflow_id": temporal_workflow_id,
            "temporal_run_id": temporal_run_id,
            "temporal_chain_metadata_digest": metadata_digest,
        }
        request_digest = self._digest(request)
        replay = self._epoch_replay(command_id, request_digest)
        if replay:
            return replay

        mission = self.missions.get(mission_id)
        if checkpoint_row is None:
            normalized_commit, _ = self._resolve_commit(
                mission, normalized_commit, require_clean_head=True
            )
        else:
            self.verify_checkpoint(base_checkpoint_id)

        with self.storage.db:
            self.storage._begin_immediate()
            replay = self._epoch_replay(command_id, request_digest)
            if replay:
                return replay
            row = self.storage.db.execute(
                "SELECT * FROM autonomous_missions WHERE id=?", (mission_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown Autonomous Mission: {mission_id}")
            actual_version = int(row["version"])
            if actual_version != expected_mission_version:
                raise MissionVersionConflictError(
                    mission_id, expected_mission_version, actual_version
                )
            if self._optional_id(row["active_backlog_revision_id"]) != (
                expected_backlog_revision_id
            ):
                raise ValueError("Active backlog revision changed before epoch activation")
            current_epoch_id = self._optional_id(row["active_execution_epoch_id"])
            if current_epoch_id != expected_active_epoch_id:
                raise ValueError("Active execution epoch changed before activation")
            phase = MissionPhase(row["phase"])
            if phase not in EXECUTION_PHASES:
                raise ValueError(
                    "Execution epochs require an approved, non-completed mission phase"
                )
            latest = self.storage.db.execute(
                """SELECT id,epoch_number FROM autonomous_mission_execution_epochs
                   WHERE mission_id=? ORDER BY epoch_number DESC LIMIT 1""",
                (mission_id,),
            ).fetchone()
            epoch_number = int(latest["epoch_number"]) + 1 if latest else 1
            if epoch_number == 1:
                if expected_active_epoch_id is not None or base_checkpoint_id is not None:
                    raise ValueError("Epoch 1 cannot supersede historical execution")
                if origin is not ExecutionEpochOrigin.INITIAL:
                    raise ValueError("Epoch 1 must use INITIAL origin")
            else:
                if expected_active_epoch_id is None or base_checkpoint_id is None:
                    raise ValueError("A later epoch requires the active predecessor and checkpoint")
                if not latest or int(latest["id"]) != expected_active_epoch_id:
                    raise ValueError("Only the latest active epoch can be superseded")
                if origin is ExecutionEpochOrigin.INITIAL:
                    raise ValueError("Restart epochs require a non-initial origin")
                checkpoint_row = self.storage.db.execute(
                    "SELECT * FROM autonomous_mission_checkpoints WHERE id=?",
                    (base_checkpoint_id,),
                ).fetchone()
                if (
                    not checkpoint_row
                    or int(checkpoint_row["mission_id"]) != mission_id
                    or str(checkpoint_row["checkpoint_digest"])
                    != base_checkpoint_digest
                    or str(checkpoint_row["git_commit_sha"]) != normalized_commit
                ):
                    raise ValueError("Base checkpoint changed before epoch activation")

            created_at = self._timestamp()
            result_version = actual_version + 1
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_mission_execution_epochs(
                       identity,mission_id,epoch_number,base_backlog_revision_id,
                       base_backlog_revision_digest,base_checkpoint_id,
                       base_checkpoint_digest,base_git_commit_sha,epoch_branch,origin,
                       temporal_workflow_id,temporal_first_run_id,
                       temporal_chain_metadata_json,temporal_chain_metadata_digest,
                       supersedes_epoch_id,activation_mission_version,created_by,
                       reason,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-mission-epoch"),
                    mission_id,
                    epoch_number,
                    expected_backlog_revision_id,
                    revision["revision_digest"],
                    base_checkpoint_id,
                    base_checkpoint_digest,
                    normalized_commit,
                    epoch_branch,
                    origin.value,
                    temporal_workflow_id,
                    temporal_run_id,
                    self._json(metadata),
                    metadata_digest,
                    expected_active_epoch_id,
                    result_version,
                    actor,
                    reason,
                    created_at,
                ),
            )
            epoch_id = int(cursor.lastrowid)
            run_metadata = {
                "chain": metadata,
                "epoch_number": epoch_number,
                "mission_id": mission_id,
            }
            self.storage.db.execute(
                """INSERT INTO autonomous_epoch_temporal_runs(
                       identity,execution_epoch_id,sequence,workflow_id,run_id,
                       previous_run_id,workflow_build_id,metadata_json,
                       metadata_digest,command_id,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-epoch-temporal-run"),
                    epoch_id,
                    1,
                    temporal_workflow_id,
                    temporal_run_id,
                    None,
                    build_id,
                    self._json(run_metadata),
                    self._digest(run_metadata),
                    f"{command_id}:temporal-run:1",
                    created_at,
                ),
            )
            if expected_active_epoch_id is not None:
                self.storage.db.execute(
                    """INSERT INTO autonomous_epoch_supersessions(
                           identity,mission_id,superseded_epoch_id,
                           superseding_epoch_id,selected_checkpoint_id,actor,
                           command_id,reason,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        self.storage._identity("autonomous-epoch-supersession"),
                        mission_id,
                        expected_active_epoch_id,
                        epoch_id,
                        base_checkpoint_id,
                        actor,
                        command_id,
                        reason,
                        created_at,
                    ),
                )
            self.missions._insert_state_version(
                mission_id=mission_id,
                version=result_version,
                phase=phase,
                disposition=MissionDisposition(row["disposition"]),
                configuration_json=str(row["configuration_json"]),
                configuration_digest=str(row["configuration_digest"]),
                active_backlog_revision_id=expected_backlog_revision_id,
                active_execution_epoch_id=epoch_id,
                current_checkpoint_id=(
                    base_checkpoint_id
                    if base_checkpoint_id is not None
                    else self._optional_id(row["current_checkpoint_id"])
                ),
                actor=actor,
                command_id=command_id,
                reason=reason,
            )
            updated = self.storage.db.execute(
                """UPDATE autonomous_missions
                      SET active_execution_epoch_id=?,current_checkpoint_id=?,
                          version=?,updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND version=?""",
                (
                    epoch_id,
                    base_checkpoint_id
                    if base_checkpoint_id is not None
                    else row["current_checkpoint_id"],
                    result_version,
                    mission_id,
                    actual_version,
                ),
            )
            if updated.rowcount != 1:
                raise MissionVersionConflictError(
                    mission_id, expected_mission_version, actual_version + 1
                )
            self.missions._insert_command(
                mission_id=mission_id,
                command_id=command_id,
                command_type="create_execution_epoch",
                actor=actor,
                expected_version=expected_mission_version,
                request_digest=request_digest,
                result_version=result_version,
            )
            if expected_active_epoch_id is not None:
                self.storage._event(
                    "autonomous_mission.execution_epoch_superseded",
                    "autonomous_mission_execution_epoch",
                    expected_active_epoch_id,
                    {
                        "mission_id": mission_id,
                        "superseded_epoch_id": expected_active_epoch_id,
                        "superseding_epoch_id": epoch_id,
                        "selected_checkpoint_id": base_checkpoint_id,
                        "actor": actor,
                        "command_id": command_id,
                        "reason": reason,
                    },
                )
            self.storage._event(
                "autonomous_mission.execution_epoch_activated",
                "autonomous_mission_execution_epoch",
                epoch_id,
                {
                    "mission_id": mission_id,
                    "epoch_id": epoch_id,
                    "epoch_number": epoch_number,
                    "backlog_revision_id": expected_backlog_revision_id,
                    "backlog_revision_digest": revision["revision_digest"],
                    "base_checkpoint_id": base_checkpoint_id,
                    "base_git_commit_sha": normalized_commit,
                    "epoch_branch": epoch_branch,
                    "origin": origin.value,
                    "temporal_workflow_id": temporal_workflow_id,
                    "temporal_first_run_id": temporal_run_id,
                    "actor": actor,
                    "command_id": command_id,
                    "version": result_version,
                },
            )
        return self.get_epoch(epoch_id)

    def temporal_runs(self, epoch_id: int) -> tuple[TemporalRunReference, ...]:
        return tuple(
            TemporalRunReference(
                id=int(row["id"]),
                execution_epoch_id=int(row["execution_epoch_id"]),
                sequence=int(row["sequence"]),
                workflow_id=str(row["workflow_id"]),
                run_id=str(row["run_id"]),
                previous_run_id=row["previous_run_id"],
                workflow_build_id=row["workflow_build_id"],
                metadata=json.loads(row["metadata_json"]),
                metadata_digest=str(row["metadata_digest"]),
                command_id=str(row["command_id"]),
                created_at=str(row["created_at"]),
            )
            for row in self.storage.db.execute(
                """SELECT * FROM autonomous_epoch_temporal_runs
                   WHERE execution_epoch_id=? ORDER BY sequence""",
                (epoch_id,),
            )
        )

    def get_epoch(self, epoch_id: int) -> MissionExecutionEpoch:
        row = self.storage.db.execute(
            """SELECT e.*,m.active_execution_epoch_id,
                      s.superseding_epoch_id,s.created_at AS superseded_at
                 FROM autonomous_mission_execution_epochs e
                 JOIN autonomous_missions m ON m.id=e.mission_id
                 LEFT JOIN autonomous_epoch_supersessions s
                   ON s.superseded_epoch_id=e.id
                WHERE e.id=?""",
            (epoch_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown mission execution epoch: {epoch_id}")
        return MissionExecutionEpoch(
            id=int(row["id"]),
            identity=str(row["identity"]),
            mission_id=int(row["mission_id"]),
            epoch_number=int(row["epoch_number"]),
            base_backlog_revision_id=int(row["base_backlog_revision_id"]),
            base_backlog_revision_digest=str(row["base_backlog_revision_digest"]),
            base_checkpoint_id=self._optional_id(row["base_checkpoint_id"]),
            base_checkpoint_digest=row["base_checkpoint_digest"],
            base_git_commit_sha=str(row["base_git_commit_sha"]),
            epoch_branch=str(row["epoch_branch"]),
            origin=ExecutionEpochOrigin(row["origin"]),
            temporal_workflow_id=str(row["temporal_workflow_id"]),
            temporal_first_run_id=str(row["temporal_first_run_id"]),
            temporal_chain_metadata=json.loads(row["temporal_chain_metadata_json"]),
            temporal_chain_metadata_digest=str(
                row["temporal_chain_metadata_digest"]
            ),
            supersedes_epoch_id=self._optional_id(row["supersedes_epoch_id"]),
            activation_mission_version=int(row["activation_mission_version"]),
            created_by=str(row["created_by"]),
            reason=str(row["reason"]),
            created_at=str(row["created_at"]),
            temporal_runs=self.temporal_runs(epoch_id),
            is_active=self._optional_id(row["active_execution_epoch_id"]) == epoch_id,
            superseded_by_epoch_id=self._optional_id(row["superseding_epoch_id"]),
            superseded_at=row["superseded_at"],
        )

    def list_epochs(self, mission_id: int) -> tuple[MissionExecutionEpoch, ...]:
        return tuple(
            self.get_epoch(int(row["id"]))
            for row in self.storage.db.execute(
                """SELECT id FROM autonomous_mission_execution_epochs
                   WHERE mission_id=? ORDER BY epoch_number""",
                (mission_id,),
            )
        )

    def active_epoch(self, mission_id: int) -> MissionExecutionEpoch | None:
        epoch_id = self.missions.get(mission_id).active_execution_epoch_id
        return self.get_epoch(epoch_id) if epoch_id is not None else None

    @classmethod
    def _manifest_reference(
        cls, version: str | None, digest: str | None, label: str
    ) -> dict[str, str] | None:
        if version is None and digest is None:
            return None
        if version is None or digest is None:
            raise ValueError(f"{label} version and digest must be supplied together")
        return {
            "version": cls._required(version, f"{label} version"),
            "digest": cls._sha256(digest, f"{label} digest"),
        }

    @classmethod
    def _content_references(
        cls, values: tuple[dict[str, Any], ...], label: str
    ) -> tuple[dict[str, Any], ...]:
        normalized: list[dict[str, Any]] = []
        for index, value in enumerate(values):
            if not isinstance(value, dict):
                raise TypeError(f"{label} reference {index} must be an object")
            reference = dict(value)
            if "digest" not in reference:
                raise ValueError(f"{label} reference {index} requires a digest")
            reference["digest"] = cls._sha256(
                str(reference["digest"]), f"{label} reference digest"
            )
            normalized.append(reference)
        return tuple(sorted(normalized, key=cls._json))

    @staticmethod
    def _stable_ids(values: tuple[str, ...], label: str) -> tuple[str, ...]:
        normalized = tuple(sorted({str(value).strip() for value in values}))
        if any(not value for value in normalized):
            raise ValueError(f"{label} cannot contain blank stable ids")
        if len(normalized) != len(values):
            raise ValueError(f"{label} must contain unique stable ids")
        return normalized

    def _validate_work_partition(
        self,
        revision_id: int,
        completed: tuple[str, ...],
        pending: tuple[str, ...],
        current_work_item: str | None,
    ) -> None:
        rows = self.storage.db.execute(
            """SELECT i.id,i.stable_id,
                      (SELECT s.status FROM autonomous_backlog_item_states s
                        WHERE s.item_id=i.id ORDER BY s.sequence DESC LIMIT 1) AS status
                 FROM autonomous_backlog_items i
                WHERE i.revision_id=? AND i.executable=1""",
            (revision_id,),
        ).fetchall()
        executable = {str(row["stable_id"]) for row in rows}
        completed_set = set(completed)
        pending_set = set(pending)
        if completed_set & pending_set:
            raise ValueError("Completed and pending work-item sets must be disjoint")
        if completed_set | pending_set != executable:
            missing = sorted(executable - completed_set - pending_set)
            unknown = sorted((completed_set | pending_set) - executable)
            raise ValueError(
                "Checkpoint work-item partition does not cover the active revision: "
                f"missing={missing}, unknown={unknown}"
            )
        accepted = {str(row["stable_id"]) for row in rows if row["status"] == "DONE"}
        if completed_set != accepted:
            raise ValueError(
                "Checkpoint completed work does not match accepted backlog state: "
                f"expected={sorted(accepted)}, received={sorted(completed_set)}"
            )
        if current_work_item is not None and current_work_item not in executable:
            raise ValueError("Current work item is not in the active executable backlog")

    def record_checkpoint(
        self,
        mission_id: int,
        *,
        expected_mission_version: int,
        expected_backlog_revision_id: int,
        expected_execution_epoch_id: int,
        actor: str,
        command_id: str,
        reason: str,
        checkpoint_type: MissionCheckpointType | str,
        git_commit_sha: str,
        git_branch: str,
        git_worktree_path: str,
        completed_work_items: tuple[str, ...],
        pending_work_items: tuple[str, ...],
        current_work_item: str | None = None,
        architecture_version: str | None = None,
        architecture_digest: str | None = None,
        environment_manifest_version: str | None = None,
        environment_manifest_digest: str | None = None,
        role_model_assignments: dict[str, str] | None = None,
        artifacts: tuple[dict[str, Any], ...] = (),
        memory_context: tuple[dict[str, Any], ...] = (),
        service_manifest_version: str | None = None,
        service_manifest_digest: str | None = None,
        validation_state: dict[str, Any] | None = None,
    ) -> MissionCheckpoint:
        """Append a canonical checkpoint and move only the mission checkpoint pointer."""

        actor = self._required(actor, "Checkpoint actor")
        command_id = self._required(command_id, "Command id")
        reason = self._required(reason, "Checkpoint reason")
        checkpoint_type = MissionCheckpointType(checkpoint_type)
        requested_commit = self._commit(git_commit_sha)
        git_branch = self._required(git_branch, "Checkpoint Git branch")
        worktree = str(Path(git_worktree_path).expanduser().resolve())
        completed = self._stable_ids(completed_work_items, "Completed work items")
        pending = self._stable_ids(pending_work_items, "Pending work items")
        current = (
            self._required(current_work_item, "Current work item")
            if current_work_item is not None
            else None
        )
        architecture = self._manifest_reference(
            architecture_version, architecture_digest, "Architecture"
        )
        environment = self._manifest_reference(
            environment_manifest_version,
            environment_manifest_digest,
            "Environment manifest",
        )
        services = self._manifest_reference(
            service_manifest_version, service_manifest_digest, "Service manifest"
        )
        artifact_refs = self._content_references(artifacts, "Artifact")
        memory_refs = self._content_references(memory_context, "Memory/context")
        validation = dict(validation_state or {})
        validation_digest = self._digest(validation)
        mission = self.missions.get(mission_id)
        assignments = (
            {
                str(role).strip(): str(model).strip()
                for role, model in role_model_assignments.items()
            }
            if role_model_assignments is not None
            else dict(mission.configuration.role_models)
        )
        if mission.configuration.default_model and "default" not in assignments:
            assignments["default"] = mission.configuration.default_model
        if any(not role or not model for role, model in assignments.items()):
            raise ValueError("Role/model assignments cannot contain blank values")
        assignments = dict(sorted(assignments.items()))
        assignments_digest = self._digest(assignments)
        revision = self._revision(mission_id, expected_backlog_revision_id)
        epoch = self.get_epoch(expected_execution_epoch_id)
        if epoch.mission_id != mission_id:
            raise ValueError("Execution epoch does not belong to this mission")

        request = {
            "type": "record_mission_checkpoint",
            "mission_id": mission_id,
            "expected_mission_version": expected_mission_version,
            "expected_backlog_revision_id": expected_backlog_revision_id,
            "expected_execution_epoch_id": expected_execution_epoch_id,
            "actor": actor,
            "reason": reason,
            "checkpoint_type": checkpoint_type.value,
            "git_commit_sha": requested_commit,
            "git_branch": git_branch,
            "git_worktree_path": worktree,
            "current_work_item": current,
            "completed_work_items": completed,
            "pending_work_items": pending,
            "architecture": architecture,
            "environment_manifest": environment,
            "role_model_assignments_digest": assignments_digest,
            "artifacts": artifact_refs,
            "memory_context": memory_refs,
            "service_manifest": services,
            "validation_state_digest": validation_digest,
        }
        request_digest = self._digest(request)
        replay = self._checkpoint_replay(command_id, request_digest)
        if replay:
            return replay

        resolved_commit, resolved_worktree = self._resolve_commit(
            mission,
            requested_commit,
            worktree_path=worktree,
            require_clean_head=True,
        )
        actual_branch = self._git(
            resolved_worktree, "symbolic-ref", "--quiet", "--short", "HEAD"
        )
        if actual_branch != git_branch:
            raise CheckpointIntegrityError(
                f"Checkpoint branch mismatch: expected {git_branch}, current {actual_branch}"
            )
        if epoch.epoch_branch != git_branch:
            raise ValueError("Checkpoint branch must be the active epoch branch")

        with self.storage.db:
            self.storage._begin_immediate()
            replay = self._checkpoint_replay(command_id, request_digest)
            if replay:
                return replay
            row = self.storage.db.execute(
                "SELECT * FROM autonomous_missions WHERE id=?", (mission_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown Autonomous Mission: {mission_id}")
            actual_version = int(row["version"])
            if actual_version != expected_mission_version:
                raise MissionVersionConflictError(
                    mission_id, expected_mission_version, actual_version
                )
            if self._optional_id(row["active_backlog_revision_id"]) != (
                expected_backlog_revision_id
            ):
                raise ValueError("Active backlog revision changed before checkpoint")
            if self._optional_id(row["active_execution_epoch_id"]) != (
                expected_execution_epoch_id
            ):
                raise ValueError("Only the active execution epoch can checkpoint")
            self._validate_work_partition(
                expected_backlog_revision_id, completed, pending, current
            )
            sequence = int(
                self.storage.db.execute(
                    """SELECT COALESCE(MAX(sequence),0)+1
                         FROM autonomous_mission_checkpoints
                        WHERE execution_epoch_id=?""",
                    (expected_execution_epoch_id,),
                ).fetchone()[0]
            )
            created_at = self._timestamp()
            identity = self.storage._identity("autonomous-mission-checkpoint")
            checkpoint_key = (
                f"{str(row['mission_key'])}-E{epoch.epoch_number:04d}-C{sequence:06d}"
            )
            document = {
                "schema_version": 1,
                "checkpoint_id": identity,
                "checkpoint_key": checkpoint_key,
                "sequence": sequence,
                "checkpoint_type": checkpoint_type.value,
                "reason": reason,
                "created_by": actor,
                "created_at": created_at,
                "mission": {
                    "id": mission_id,
                    "identity": str(row["identity"]),
                    "key": str(row["mission_key"]),
                    "version_before_checkpoint": actual_version,
                },
                "execution_epoch": {
                    "id": epoch.id,
                    "identity": epoch.identity,
                    "number": epoch.epoch_number,
                    "branch": epoch.epoch_branch,
                },
                "backlog_revision": {
                    "id": expected_backlog_revision_id,
                    "number": int(revision["revision_number"]),
                    "digest": str(revision["revision_digest"]),
                },
                "current_work_item": current,
                "completed_work_items": list(completed),
                "pending_work_items": list(pending),
                "git": {
                    "commit_sha": resolved_commit,
                    "branch": git_branch,
                    "worktree_path": str(resolved_worktree),
                    "authoritative_state": "COMMITTED_CLEAN_HEAD",
                },
                "architecture": architecture,
                "environment_manifest": environment,
                "role_model_assignments": assignments,
                "role_model_assignments_digest": assignments_digest,
                "artifacts": list(artifact_refs),
                "memory_context": list(memory_refs),
                "service_manifest": services,
                "validation_state": validation,
                "validation_state_digest": validation_digest,
            }
            checkpoint_digest = self._digest(document)
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_mission_checkpoints(
                       identity,checkpoint_key,mission_id,execution_epoch_id,
                       sequence,checkpoint_type,reason,created_by,created_at,
                       backlog_revision_id,backlog_revision_digest,
                       current_work_item_stable_id,completed_work_items_json,
                       pending_work_items_json,git_commit_sha,git_branch,
                       git_worktree_path,architecture_version,architecture_digest,
                       environment_manifest_version,environment_manifest_digest,
                       role_model_assignments_json,role_model_assignments_digest,
                       artifacts_json,memory_context_json,service_manifest_version,
                       service_manifest_digest,validation_state_json,
                       validation_state_digest,document_json,checkpoint_digest
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    identity,
                    checkpoint_key,
                    mission_id,
                    expected_execution_epoch_id,
                    sequence,
                    checkpoint_type.value,
                    reason,
                    actor,
                    created_at,
                    expected_backlog_revision_id,
                    revision["revision_digest"],
                    current,
                    self._json(completed),
                    self._json(pending),
                    resolved_commit,
                    git_branch,
                    str(resolved_worktree),
                    architecture["version"] if architecture else None,
                    architecture["digest"] if architecture else None,
                    environment["version"] if environment else None,
                    environment["digest"] if environment else None,
                    self._json(assignments),
                    assignments_digest,
                    self._json(artifact_refs),
                    self._json(memory_refs),
                    services["version"] if services else None,
                    services["digest"] if services else None,
                    self._json(validation),
                    validation_digest,
                    self._json(document),
                    checkpoint_digest,
                ),
            )
            checkpoint_id = int(cursor.lastrowid)
            result_version = actual_version + 1
            self.missions._insert_state_version(
                mission_id=mission_id,
                version=result_version,
                phase=MissionPhase(row["phase"]),
                disposition=MissionDisposition(row["disposition"]),
                configuration_json=str(row["configuration_json"]),
                configuration_digest=str(row["configuration_digest"]),
                active_backlog_revision_id=expected_backlog_revision_id,
                active_execution_epoch_id=expected_execution_epoch_id,
                current_checkpoint_id=checkpoint_id,
                actor=actor,
                command_id=command_id,
                reason=reason,
            )
            updated = self.storage.db.execute(
                """UPDATE autonomous_missions
                      SET current_checkpoint_id=?,version=?,updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND version=?""",
                (checkpoint_id, result_version, mission_id, actual_version),
            )
            if updated.rowcount != 1:
                raise MissionVersionConflictError(
                    mission_id, expected_mission_version, actual_version + 1
                )
            self.missions._insert_command(
                mission_id=mission_id,
                command_id=command_id,
                command_type="record_mission_checkpoint",
                actor=actor,
                expected_version=expected_mission_version,
                request_digest=request_digest,
                result_version=result_version,
            )
            self.storage._event(
                "autonomous_mission.checkpoint_created",
                "autonomous_mission_checkpoint",
                checkpoint_id,
                {
                    "mission_id": mission_id,
                    "checkpoint_id": checkpoint_id,
                    "checkpoint_key": checkpoint_key,
                    "checkpoint_type": checkpoint_type.value,
                    "checkpoint_digest": checkpoint_digest,
                    "execution_epoch_id": expected_execution_epoch_id,
                    "epoch_number": epoch.epoch_number,
                    "backlog_revision_id": expected_backlog_revision_id,
                    "git_commit_sha": resolved_commit,
                    "actor": actor,
                    "command_id": command_id,
                    "version": result_version,
                },
            )
        return self.verify_checkpoint(checkpoint_id)

    def get_checkpoint(self, checkpoint_id: int) -> MissionCheckpoint:
        row = self.storage.db.execute(
            """SELECT c.*,m.current_checkpoint_id,
                      CASE WHEN s.id IS NULL THEN 0 ELSE 1 END AS epoch_superseded
                 FROM autonomous_mission_checkpoints c
                 JOIN autonomous_missions m ON m.id=c.mission_id
                 LEFT JOIN autonomous_epoch_supersessions s
                   ON s.superseded_epoch_id=c.execution_epoch_id
                WHERE c.id=?""",
            (checkpoint_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown mission checkpoint: {checkpoint_id}")
        restart_bases = tuple(
            int(value["id"])
            for value in self.storage.db.execute(
                """SELECT id FROM autonomous_mission_execution_epochs
                   WHERE base_checkpoint_id=? ORDER BY epoch_number""",
                (checkpoint_id,),
            )
        )
        return MissionCheckpoint(
            id=int(row["id"]),
            identity=str(row["identity"]),
            checkpoint_key=str(row["checkpoint_key"]),
            mission_id=int(row["mission_id"]),
            execution_epoch_id=int(row["execution_epoch_id"]),
            sequence=int(row["sequence"]),
            checkpoint_type=MissionCheckpointType(row["checkpoint_type"]),
            reason=str(row["reason"]),
            created_by=str(row["created_by"]),
            created_at=str(row["created_at"]),
            backlog_revision_id=int(row["backlog_revision_id"]),
            backlog_revision_digest=str(row["backlog_revision_digest"]),
            git_commit_sha=str(row["git_commit_sha"]),
            git_branch=str(row["git_branch"]),
            git_worktree_path=str(row["git_worktree_path"]),
            checkpoint_digest=str(row["checkpoint_digest"]),
            document=json.loads(row["document_json"]),
            is_current=self._optional_id(row["current_checkpoint_id"]) == checkpoint_id,
            epoch_superseded=bool(row["epoch_superseded"]),
            restart_base_for_epoch_ids=restart_bases,
        )

    def list_checkpoints(self, mission_id: int) -> tuple[MissionCheckpoint, ...]:
        return tuple(
            self.get_checkpoint(int(row["id"]))
            for row in self.storage.db.execute(
                """SELECT id FROM autonomous_mission_checkpoints
                   WHERE mission_id=? ORDER BY created_at,id""",
                (mission_id,),
            )
        )

    def verify_checkpoint(
        self, checkpoint_id: int, *, verify_git: bool = True
    ) -> MissionCheckpoint:
        """Fail closed unless the canonical record and referenced Git commit still agree."""

        checkpoint = self.get_checkpoint(checkpoint_id)
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_mission_checkpoints WHERE id=?", (checkpoint_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown mission checkpoint: {checkpoint_id}")
        document_json = self._json(checkpoint.document)
        if document_json != str(row["document_json"]):
            raise CheckpointIntegrityError("Checkpoint document is not canonical JSON")
        if self._digest(checkpoint.document) != checkpoint.checkpoint_digest:
            raise CheckpointIntegrityError("Checkpoint document digest does not match")
        document = checkpoint.document
        expected_scalars = {
            "checkpoint_id": checkpoint.identity,
            "checkpoint_key": checkpoint.checkpoint_key,
            "sequence": checkpoint.sequence,
            "checkpoint_type": checkpoint.checkpoint_type.value,
            "reason": checkpoint.reason,
            "created_by": checkpoint.created_by,
            "created_at": checkpoint.created_at,
        }
        if any(document.get(key) != value for key, value in expected_scalars.items()):
            raise CheckpointIntegrityError("Checkpoint envelope does not match stored columns")
        mission_doc = document.get("mission", {})
        epoch_doc = document.get("execution_epoch", {})
        revision_doc = document.get("backlog_revision", {})
        git_doc = document.get("git", {})
        if (
            mission_doc.get("id") != checkpoint.mission_id
            or epoch_doc.get("id") != checkpoint.execution_epoch_id
            or revision_doc.get("id") != checkpoint.backlog_revision_id
            or revision_doc.get("digest") != checkpoint.backlog_revision_digest
            or git_doc.get("commit_sha") != checkpoint.git_commit_sha
            or git_doc.get("branch") != checkpoint.git_branch
            or git_doc.get("worktree_path") != checkpoint.git_worktree_path
            or git_doc.get("authoritative_state") != "COMMITTED_CLEAN_HEAD"
        ):
            raise CheckpointIntegrityError(
                "Checkpoint canonical state does not match its indexed projection"
            )
        mission_row = self.storage.db.execute(
            "SELECT identity,mission_key FROM autonomous_missions WHERE id=?",
            (checkpoint.mission_id,),
        ).fetchone()
        state_row = self.storage.db.execute(
            """SELECT version FROM autonomous_mission_state_versions
               WHERE mission_id=? AND current_checkpoint_id=?
               ORDER BY version LIMIT 1""",
            (checkpoint.mission_id, checkpoint.id),
        ).fetchone()
        if (
            not mission_row
            or mission_doc.get("identity") != mission_row["identity"]
            or mission_doc.get("key") != mission_row["mission_key"]
            or not state_row
            or not isinstance(mission_doc.get("version_before_checkpoint"), int)
            or mission_doc.get("version_before_checkpoint") + 1
            != int(state_row["version"])
        ):
            raise CheckpointIntegrityError(
                "Checkpoint mission identity or state-version evidence does not match"
            )
        completed = document.get("completed_work_items")
        pending = document.get("pending_work_items")
        if (
            not isinstance(completed, list)
            or not isinstance(pending, list)
            or document.get("current_work_item")
            != row["current_work_item_stable_id"]
            or self._json(completed) != row["completed_work_items_json"]
            or self._json(pending) != row["pending_work_items_json"]
        ):
            raise CheckpointIntegrityError(
                "Checkpoint work-item projection does not match canonical state"
            )
        assignments = document.get("role_model_assignments")
        validation = document.get("validation_state")
        if not isinstance(assignments, dict) or not isinstance(validation, dict):
            raise CheckpointIntegrityError(
                "Checkpoint assignments and validation state must be objects"
            )
        if self._digest(assignments) != document.get("role_model_assignments_digest"):
            raise CheckpointIntegrityError("Role/model assignment digest does not match")
        if self._digest(validation) != document.get("validation_state_digest"):
            raise CheckpointIntegrityError("Validation-state digest does not match")
        if document.get("role_model_assignments_digest") != row[
            "role_model_assignments_digest"
        ] or document.get("validation_state_digest") != row["validation_state_digest"]:
            raise CheckpointIntegrityError("Checkpoint nested digests do not match columns")
        if (
            self._json(assignments) != row["role_model_assignments_json"]
            or self._json(validation) != row["validation_state_json"]
            or self._json(document.get("artifacts", [])) != row["artifacts_json"]
            or self._json(document.get("memory_context", []))
            != row["memory_context_json"]
        ):
            raise CheckpointIntegrityError(
                "Checkpoint content-addressed projections do not match canonical state"
            )
        for label, values in (
            ("artifact", document.get("artifacts", [])),
            ("memory/context", document.get("memory_context", [])),
        ):
            if not isinstance(values, list):
                raise CheckpointIntegrityError(f"Checkpoint {label} references must be a list")
            for value in values:
                if not isinstance(value, dict) or not SHA256_PATTERN.fullmatch(
                    str(value.get("digest", ""))
                ):
                    raise CheckpointIntegrityError(
                        f"Checkpoint {label} reference is not content addressed"
                    )
        for label, value in (
            ("architecture", document.get("architecture")),
            ("environment manifest", document.get("environment_manifest")),
            ("service manifest", document.get("service_manifest")),
        ):
            if value is not None and (
                not isinstance(value, dict)
                or not str(value.get("version", "")).strip()
                or not SHA256_PATTERN.fullmatch(str(value.get("digest", "")))
            ):
                raise CheckpointIntegrityError(
                    f"Checkpoint {label} reference is incomplete"
                )
        projection_references = (
            (
                document.get("architecture"),
                row["architecture_version"],
                row["architecture_digest"],
            ),
            (
                document.get("environment_manifest"),
                row["environment_manifest_version"],
                row["environment_manifest_digest"],
            ),
            (
                document.get("service_manifest"),
                row["service_manifest_version"],
                row["service_manifest_digest"],
            ),
        )
        for reference, version, digest in projection_references:
            if reference is None:
                if version is not None or digest is not None:
                    raise CheckpointIntegrityError(
                        "Checkpoint manifest projection has unexpected state"
                    )
            elif reference.get("version") != version or reference.get("digest") != digest:
                raise CheckpointIntegrityError(
                    "Checkpoint manifest projection does not match canonical state"
                )
        revision = self._revision(
            checkpoint.mission_id, checkpoint.backlog_revision_id
        )
        if str(revision["revision_digest"]) != checkpoint.backlog_revision_digest:
            raise CheckpointIntegrityError("Referenced backlog revision digest changed")
        epoch = self.get_epoch(checkpoint.execution_epoch_id)
        if epoch.mission_id != checkpoint.mission_id:
            raise CheckpointIntegrityError("Referenced execution epoch changed scope")
        if (
            epoch_doc.get("identity") != epoch.identity
            or epoch_doc.get("number") != epoch.epoch_number
            or epoch_doc.get("branch") != epoch.epoch_branch
        ):
            raise CheckpointIntegrityError("Referenced execution epoch does not match")
        if verify_git:
            mission = self.missions.get(checkpoint.mission_id)
            repository = self._repository(mission)
            resolved = self._commit(
                self._git(
                    repository,
                    "rev-parse",
                    "--verify",
                    f"{checkpoint.git_commit_sha}^{{commit}}",
                ),
                "Resolved checkpoint commit",
            )
            if resolved != checkpoint.git_commit_sha:
                raise CheckpointIntegrityError("Checkpoint Git commit resolution changed")
        return checkpoint
