"""Local inspection plus evidence-writing authoritative mission recovery."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping

from .durable_workflow import (
    MissionOperation,
    MissionOperationJournal,
    ObservationStatus,
    OperationClass,
    OperationJournalIntegrityError,
    OperationLifecycle,
    OperationObservation,
    canonical_digest,
    canonical_json,
)
from .mission_checkpoints import MissionCheckpointService
from .storage import SQLiteStorage
from .worktrees import (
    GitOperationReconciler,
    WorktreeManager,
    WorktreeReconciliation,
)


@dataclass(frozen=True)
class RecoverySnapshot:
    run_id: int
    run_status: str
    stages: tuple[dict[str, Any], ...]
    lease: dict[str, Any] | None
    hermes_session: dict[str, Any] | None
    context: dict[str, Any] | None
    worktree: dict[str, Any] | None
    pending_approvals: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class OrphanReport:
    provider_process_ids: tuple[int, ...]
    hermes_session_ids: tuple[int, ...]
    worktree_paths: tuple[str, ...]
    worktree_reconciliation: WorktreeReconciliation | None


class MissionRecoveryDisposition(StrEnum):
    RESUME_SAFE = "RESUME_SAFE"
    RECONCILE_REQUIRED = "RECONCILE_REQUIRED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True)
class MissionRecoveryDecision:
    sequence: int
    decision_type: str
    operation_id: int | None
    decision: dict[str, Any]
    decision_digest: str
    created_at: str


@dataclass(frozen=True)
class AuthoritativeMissionRecovery:
    id: int
    mission_id: int
    recovery_key: str
    mission_version: int
    disposition: MissionRecoveryDisposition
    replay_safe: bool
    snapshot: dict[str, Any]
    snapshot_digest: str
    integrity: dict[str, Any]
    integrity_digest: str
    actor: str
    created_at: str
    decisions: tuple[MissionRecoveryDecision, ...]


class LocalRecoveryService:
    """Reconstruct authority without invoking, cleaning, or mutating external state."""

    def __init__(
        self,
        storage: SQLiteStorage,
        *,
        process_alive: Callable[[int], bool] | None = None,
    ):
        self.storage = storage
        self.process_alive = process_alive or self._process_alive
        self.operation_journal = MissionOperationJournal(storage)
        self.checkpoints = MissionCheckpointService(storage)

    @staticmethod
    def _process_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except (OSError, ValueError):
            return False
        return True

    def snapshot(self, run_id: int) -> RecoverySnapshot:
        run = self.storage.durable_run(run_id)
        stages = tuple(dict(row) for row in self.storage.durable_stages(run_id))
        lease = self.storage.db.execute(
            """SELECT l.*,a.id AS assignment_id,a.agent_id,a.runtime,a.status AS assignment_status
                 FROM assignments a JOIN leases l ON l.assignment_id=a.id
                WHERE a.task_id=? ORDER BY l.id DESC LIMIT 1""",
            (run["task_id"],),
        ).fetchone()
        hermes = self.storage.db.execute(
            "SELECT * FROM hermes_acp_sessions WHERE run_id=? ORDER BY id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        context = self.storage.db.execute(
            "SELECT * FROM execution_context_packages WHERE run_id=? ORDER BY id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        worktree = self.storage.db.execute(
            """SELECT w.* FROM worktrees w JOIN assignments a ON a.id=w.assignment_id
                WHERE a.task_id=? ORDER BY w.id DESC LIMIT 1""",
            (run["task_id"],),
        ).fetchone()
        approvals: list[dict[str, Any]] = []
        for row in self.storage.db.execute(
            """SELECT id,status,stage_id,request_digest FROM scoped_execution_approvals
                WHERE run_id=? AND status IN ('pending','approved') ORDER BY id""",
            (run_id,),
        ):
            approvals.append({"kind": "stage", **dict(row)})
        for row in self.storage.db.execute(
            "SELECT id,status FROM approval_gates WHERE run_id=? AND status='pending' ORDER BY id",
            (run_id,),
        ):
            approvals.append({"kind": "founder", **dict(row)})
        delivery = self.storage.db.execute(
            "SELECT github_gate_id FROM coding_delivery_runs WHERE run_id=? ORDER BY id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if delivery and delivery["github_gate_id"] is not None:
            gate = self.storage.db.execute(
                "SELECT id,status,plan_hash FROM github_mutation_gates WHERE id=? AND status='pending'",
                (delivery["github_gate_id"],),
            ).fetchone()
            if gate:
                approvals.append({"kind": "github", **dict(gate)})
        return RecoverySnapshot(
            run_id, str(run["status"]), stages,
            dict(lease) if lease else None, dict(hermes) if hermes else None,
            dict(context) if context else None, dict(worktree) if worktree else None,
            tuple(approvals),
        )

    def detect_orphans(
        self,
        *,
        repository: Path | None = None,
        worktrees: WorktreeManager | None = None,
    ) -> OrphanReport:
        provider_ids = tuple(
            int(row["id"])
            for row in self.storage.db.execute(
                """SELECT id,pid FROM provider_execution_attempts
                    WHERE status IN ('claimed','running') AND pid IS NOT NULL ORDER BY id"""
            )
            if not self.process_alive(int(row["pid"]))
        )
        hermes_ids = tuple(
            int(row["id"])
            for row in self.storage.db.execute(
                """SELECT h.id,h.process_pid,h.status,w.status AS worker_status
                     FROM hermes_acp_sessions h
                     JOIN worker_sessions w ON w.id=h.worker_session_id
                    WHERE h.status IN ('running','suspended') ORDER BY h.id"""
            )
            if (
                row["process_pid"] is None
                or not self.process_alive(int(row["process_pid"]))
                or row["worker_status"] in {"succeeded", "failed", "cancelled"}
            )
        )
        reconciliation = None
        if repository is not None or worktrees is not None:
            if repository is None or worktrees is None:
                raise ValueError("Repository and worktree manager must be supplied together")
            reconciliation = worktrees.reconcile(repository)
        return OrphanReport(
            provider_ids, hermes_ids,
            reconciliation.orphaned_paths if reconciliation else (),
            reconciliation,
        )

    def verify_restore(self) -> dict[str, Any]:
        integrity = self.storage.integrity_check()
        foreign_keys = [tuple(row) for row in self.storage.db.execute("PRAGMA foreign_key_check")]
        return {
            "ok": integrity["ok"] and not foreign_keys,
            "database": integrity["messages"],
            "artifacts": integrity["evidence"],
            "audit": integrity["audit"],
            "foreign_keys": foreign_keys,
        }

    def record_inspection(
        self,
        *,
        run_id: int | None,
        snapshot: RecoverySnapshot | None = None,
        orphans: OrphanReport | None = None,
    ) -> int:
        if run_id is not None and snapshot is None:
            snapshot = self.snapshot(run_id)
        if snapshot is not None and snapshot.run_id != run_id:
            raise ValueError("Recovery snapshot belongs to another run")
        orphans = orphans or self.detect_orphans()
        integrity = self.verify_restore()
        document = {
            "snapshot": asdict(snapshot) if snapshot else None,
            "provider_process_ids": orphans.provider_process_ids,
            "hermes_session_ids": orphans.hermes_session_ids,
            "worktree_paths": orphans.worktree_paths,
            "integrity": integrity,
        }
        payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        existing = self.storage.db.execute(
            "SELECT id FROM recovery_inspections WHERE snapshot_digest=?", (digest,)
        ).fetchone()
        if existing:
            return int(existing["id"])
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO recovery_inspections(
                       identity,run_id,snapshot_json,snapshot_digest,integrity_json,
                       orphan_provider_processes_json,orphan_hermes_sessions_json,
                       orphan_worktrees_json
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("recovery-inspection"), run_id,
                    json.dumps(asdict(snapshot) if snapshot else None, sort_keys=True),
                    digest, json.dumps(integrity, sort_keys=True),
                    json.dumps(orphans.provider_process_ids),
                    json.dumps(orphans.hermes_session_ids),
                    json.dumps(orphans.worktree_paths),
                ),
            )
            inspection_id = int(cursor.lastrowid)
            self.storage._event("recovery.inspected", "recovery_inspection", inspection_id, {
                "run_id": run_id, "snapshot_digest": digest,
                "integrity_ok": integrity["ok"], "destructive_action": False,
            })
        return inspection_id

    @staticmethod
    def _operation_summary(operation: MissionOperation) -> dict[str, Any]:
        return {
            "id": operation.id,
            "operation_key": operation.operation_key,
            "operation_class": operation.operation_class.value,
            "request_digest": operation.request_digest,
            "reconciliation_policy": operation.reconciliation_policy.value,
            "mission_version": operation.mission_version,
            "backlog_revision_id": operation.backlog_revision_id,
            "execution_epoch_id": operation.execution_epoch_id,
            "checkpoint_id": operation.checkpoint_id,
            "child_job_id": operation.child_job_id,
            "stable_item_id": operation.stable_item_id,
            "control_fencing_token": operation.control_fencing_token,
            "lifecycle": operation.latest_event.lifecycle.value,
            "result_digest": operation.latest_event.result_digest,
            "evidence_digest": operation.latest_event.evidence_digest,
            "event_sequence": operation.latest_event.sequence,
        }

    @staticmethod
    def _recovery_json(
        payload: str,
        digest: str,
        *,
        label: str,
    ) -> dict[str, Any]:
        try:
            value = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise OperationJournalIntegrityError(
                f"{label} is not valid JSON"
            ) from exc
        if not isinstance(value, dict):
            raise OperationJournalIntegrityError(f"{label} must be an object")
        if canonical_json(value) != payload or canonical_digest(value) != digest:
            raise OperationJournalIntegrityError(
                f"{label} is not canonical digest-bound evidence"
            )
        return value

    def _load_mission_recovery(self, row: Any) -> AuthoritativeMissionRecovery:
        snapshot = self._recovery_json(
            str(row["snapshot_json"]),
            str(row["snapshot_digest"]),
            label="Mission recovery snapshot",
        )
        integrity = self._recovery_json(
            str(row["integrity_json"]),
            str(row["integrity_digest"]),
            label="Mission recovery integrity evidence",
        )
        decisions: list[MissionRecoveryDecision] = []
        for decision_row in self.storage.db.execute(
            """SELECT * FROM autonomous_mission_recovery_decisions
                WHERE recovery_id=? ORDER BY sequence""",
            (row["id"],),
        ):
            document = self._recovery_json(
                str(decision_row["decision_json"]),
                str(decision_row["decision_digest"]),
                label="Mission recovery decision",
            )
            decisions.append(
                MissionRecoveryDecision(
                    sequence=int(decision_row["sequence"]),
                    decision_type=str(decision_row["decision_type"]),
                    operation_id=(
                        int(decision_row["operation_id"])
                        if decision_row["operation_id"] is not None
                        else None
                    ),
                    decision=document,
                    decision_digest=str(decision_row["decision_digest"]),
                    created_at=str(decision_row["created_at"]),
                )
            )
        return AuthoritativeMissionRecovery(
            id=int(row["id"]),
            mission_id=int(row["mission_id"]),
            recovery_key=str(row["recovery_key"]),
            mission_version=int(row["mission_version"]),
            disposition=MissionRecoveryDisposition(str(row["disposition"])),
            replay_safe=bool(row["replay_safe"]),
            snapshot=snapshot,
            snapshot_digest=str(row["snapshot_digest"]),
            integrity=integrity,
            integrity_digest=str(row["integrity_digest"]),
            actor=str(row["actor"]),
            created_at=str(row["created_at"]),
            decisions=tuple(decisions),
        )

    def get_mission_recovery(
        self, mission_id: int, recovery_key: str
    ) -> AuthoritativeMissionRecovery:
        row = self.storage.db.execute(
            """SELECT * FROM autonomous_mission_recoveries
                WHERE mission_id=? AND recovery_key=?""",
            (mission_id, recovery_key),
        ).fetchone()
        if not row:
            raise KeyError(
                f"Unknown recovery {recovery_key!r} for mission {mission_id}"
            )
        return self._load_mission_recovery(row)

    def _observe_checkpoint_operation(
        self, operation: MissionOperation
    ) -> OperationObservation:
        request = operation.request
        checkpoint_id = request.get("checkpoint_id") or request.get(
            "target_checkpoint_id"
        )
        checkpoint_key = request.get("checkpoint_key")
        checkpoint_digest = request.get("checkpoint_digest")
        if checkpoint_id is not None:
            row = self.storage.db.execute(
                """SELECT * FROM autonomous_mission_checkpoints
                    WHERE id=? AND mission_id=?""",
                (int(checkpoint_id), operation.mission_id),
            ).fetchone()
        elif isinstance(checkpoint_key, str) and checkpoint_key.strip():
            row = self.storage.db.execute(
                """SELECT * FROM autonomous_mission_checkpoints
                    WHERE checkpoint_key=? AND mission_id=?""",
                (checkpoint_key, operation.mission_id),
            ).fetchone()
        else:
            return OperationObservation.indeterminate(
                evidence={"required": ["checkpoint_id", "checkpoint_key"]},
                reason="Checkpoint intent lacks a stable checkpoint identity",
            )
        if not row:
            return OperationObservation.absent(
                evidence={"checkpoint_id": checkpoint_id},
                reason="Journaled checkpoint does not exist",
            )
        actual = {
            "checkpoint_id": int(row["id"]),
            "checkpoint_key": str(row["checkpoint_key"]),
            "checkpoint_digest": str(row["checkpoint_digest"]),
            "backlog_revision_id": int(row["backlog_revision_id"]),
            "execution_epoch_id": int(row["execution_epoch_id"]),
        }
        if (
            checkpoint_digest is not None
            and str(checkpoint_digest) != actual["checkpoint_digest"]
        ):
            return OperationObservation.conflict(
                actual,
                evidence={"observer": "checkpoint-ledger"},
                reason="Checkpoint identity exists with a different digest",
            )
        try:
            self.checkpoints.verify_checkpoint(int(row["id"]), verify_git=True)
        except Exception as exc:
            return OperationObservation.conflict(
                actual,
                evidence={
                    "observer": "checkpoint-ledger",
                    "integrity_error": type(exc).__name__,
                },
                reason="Checkpoint exists but its durable evidence is invalid",
            )
        return OperationObservation.present(
            actual,
            evidence={"observer": "checkpoint-ledger"},
            reason="Checkpoint exists and its canonical evidence verifies",
        )

    def _observe_revision_transition(
        self, operation: MissionOperation
    ) -> OperationObservation:
        target = operation.request.get("target_backlog_revision_id")
        if target is None:
            target = operation.request.get("backlog_revision_id")
        if target is None:
            return OperationObservation.indeterminate(
                evidence={"field": "target_backlog_revision_id"},
                reason="Revision transition lacks a target revision",
            )
        target_id = int(target)
        row = self.storage.db.execute(
            """SELECT mission.active_backlog_revision_id,revision.revision_digest
                 FROM autonomous_missions mission
                 LEFT JOIN autonomous_backlog_revisions revision
                   ON revision.id=? AND revision.mission_id=mission.id
                WHERE mission.id=?""",
            (target_id, operation.mission_id),
        ).fetchone()
        if not row or row["revision_digest"] is None:
            return OperationObservation.absent(
                evidence={"target_backlog_revision_id": target_id},
                reason="Target backlog revision does not exist in mission scope",
            )
        active = (
            int(row["active_backlog_revision_id"])
            if row["active_backlog_revision_id"] is not None
            else None
        )
        actual = {
            "active_backlog_revision_id": active,
            "target_backlog_revision_id": target_id,
            "target_revision_digest": str(row["revision_digest"]),
        }
        if active == target_id:
            return OperationObservation.present(
                actual,
                evidence={"observer": "mission-revision-pointer"},
                reason="Mission active revision equals the requested target",
            )
        if active == operation.backlog_revision_id:
            return OperationObservation.absent(
                evidence=actual,
                reason="Mission remains on the pre-operation revision",
            )
        return OperationObservation.conflict(
            actual,
            evidence={"observer": "mission-revision-pointer"},
            reason="Mission active revision moved to a different authority",
        )

    def _observe_epoch_transition(
        self, operation: MissionOperation
    ) -> OperationObservation:
        target = operation.request.get("target_execution_epoch_id")
        if target is None:
            target = operation.request.get("execution_epoch_id")
        if target is None:
            return OperationObservation.indeterminate(
                evidence={"field": "target_execution_epoch_id"},
                reason="Epoch transition lacks a target epoch",
            )
        target_id = int(target)
        row = self.storage.db.execute(
            """SELECT mission.active_execution_epoch_id,epoch.epoch_number,
                      epoch.epoch_branch
                 FROM autonomous_missions mission
                 LEFT JOIN autonomous_mission_execution_epochs epoch
                   ON epoch.id=? AND epoch.mission_id=mission.id
                WHERE mission.id=?""",
            (target_id, operation.mission_id),
        ).fetchone()
        if not row or row["epoch_number"] is None:
            return OperationObservation.absent(
                evidence={"target_execution_epoch_id": target_id},
                reason="Target execution epoch does not exist in mission scope",
            )
        active = (
            int(row["active_execution_epoch_id"])
            if row["active_execution_epoch_id"] is not None
            else None
        )
        actual = {
            "active_execution_epoch_id": active,
            "target_execution_epoch_id": target_id,
            "target_epoch_number": int(row["epoch_number"]),
            "target_epoch_branch": str(row["epoch_branch"]),
        }
        if active == target_id:
            return OperationObservation.present(
                actual,
                evidence={"observer": "mission-epoch-pointer"},
                reason="Mission active epoch equals the requested target",
            )
        if active == operation.execution_epoch_id:
            return OperationObservation.absent(
                evidence=actual,
                reason="Mission remains on the pre-operation epoch",
            )
        return OperationObservation.conflict(
            actual,
            evidence={"observer": "mission-epoch-pointer"},
            reason="Mission active epoch moved to a different authority",
        )

    def _active_task(
        self,
        mission_id: int,
        revision_id: int | None,
        epoch_id: int | None,
    ) -> dict[str, Any] | None:
        if revision_id is None or epoch_id is None:
            return None
        row = self.storage.db.execute(
            """SELECT child.id AS child_job_id,child.stable_item_id,
                      child.logical_attempt,child.task_id,child.run_id,
                      child.child_workflow_id,state.status AS item_status,
                      state.sequence AS item_state_sequence
                 FROM autonomous_child_jobs child
                 LEFT JOIN autonomous_backlog_item_states state
                   ON state.id=(
                       SELECT latest.id
                         FROM autonomous_backlog_item_states latest
                        WHERE latest.item_id=child.backlog_item_id
                        ORDER BY latest.sequence DESC LIMIT 1
                   )
                WHERE child.mission_id=?
                  AND child.backlog_revision_id=?
                  AND child.execution_epoch_id=?
                  AND state.status='RUNNING'
                ORDER BY child.id DESC LIMIT 1""",
            (mission_id, revision_id, epoch_id),
        ).fetchone()
        return dict(row) if row else None

    def reconstruct_mission(
        self,
        mission_id: int,
        *,
        recovery_key: str,
        actor: str,
        reconcilers: Mapping[
            OperationClass | str,
            Callable[[MissionOperation], OperationObservation],
        ]
        | None = None,
        git_reconciler: GitOperationReconciler | None = None,
    ) -> AuthoritativeMissionRecovery:
        """Persist one authoritative restart decision after actual-state checks."""

        if not recovery_key.strip():
            raise ValueError("Mission recovery key is required")
        if not actor.strip():
            raise ValueError("Mission recovery actor is required")
        existing = self.storage.db.execute(
            """SELECT * FROM autonomous_mission_recoveries
                WHERE mission_id=? AND recovery_key=?""",
            (mission_id, recovery_key),
        ).fetchone()
        if existing:
            return self._load_mission_recovery(existing)
        mission = self.storage.db.execute(
            """SELECT mission.*,fence.fencing_token,
                      fence.mission_version AS fence_mission_version,
                      fence.phase AS fence_phase,
                      fence.disposition AS fence_disposition,
                      fence.backlog_revision_id AS fence_backlog_revision_id,
                      fence.execution_epoch_id AS fence_execution_epoch_id
                 FROM autonomous_missions mission
                 JOIN autonomous_mission_control_fences fence
                   ON fence.mission_id=mission.id
                WHERE mission.id=?""",
            (mission_id,),
        ).fetchone()
        if not mission:
            raise KeyError(f"Unknown autonomous mission: {mission_id}")
        mission_version = int(mission["version"])
        revision_id = (
            int(mission["active_backlog_revision_id"])
            if mission["active_backlog_revision_id"] is not None
            else None
        )
        epoch_id = (
            int(mission["active_execution_epoch_id"])
            if mission["active_execution_epoch_id"] is not None
            else None
        )
        checkpoint_id = (
            int(mission["current_checkpoint_id"])
            if mission["current_checkpoint_id"] is not None
            else None
        )
        decisions: list[tuple[str, int | None, dict[str, Any]]] = [
            (
                "STATE_RECONSTRUCTED",
                None,
                {
                    "mission_version": mission_version,
                    "backlog_revision_id": revision_id,
                    "execution_epoch_id": epoch_id,
                    "checkpoint_id": checkpoint_id,
                    "fencing_token": int(mission["fencing_token"]),
                },
            )
        ]
        integrity = self.verify_restore()
        fence_authority_scope = (
            mission["fence_disposition"] == mission["disposition"]
            and mission["fence_phase"] == mission["phase"]
            and mission["fence_backlog_revision_id"]
            == mission["active_backlog_revision_id"]
            and mission["fence_execution_epoch_id"]
            == mission["active_execution_epoch_id"]
            and int(mission["fence_mission_version"]) <= mission_version
        )
        fence_exact = (
            fence_authority_scope
            and int(mission["fence_mission_version"]) == mission_version
        )
        preexecution_phase = str(mission["phase"]) in {
            "DRAFT",
            "SPECIFICATION_ANALYSIS",
            "BACKLOG_GENERATION",
            "WAITING_FOR_BACKLOG_APPROVAL",
            "APPROVED",
            "ENVIRONMENT_DISCOVERY",
            "ENVIRONMENT_BOOTSTRAP",
        }
        integrity["control_fence"] = {
            "ok": (
                fence_authority_scope
                or (
                    preexecution_phase
                    and mission["fence_disposition"] == mission["disposition"]
                )
            ),
            "exact": fence_exact,
            "authority_scope": fence_authority_scope,
            "preexecution_compatibility": (
                preexecution_phase and not fence_authority_scope
            ),
        }

        revision_row = (
            self.storage.db.execute(
                """SELECT id,identity,revision_number,revision_digest
                    FROM autonomous_backlog_revisions WHERE id=? AND mission_id=?""",
                (revision_id, mission_id),
            ).fetchone()
            if revision_id is not None
            else None
        )
        epoch_row = (
            self.storage.db.execute(
                """SELECT id,identity,epoch_number,base_backlog_revision_id,
                          base_git_commit_sha,epoch_branch,origin,
                          temporal_workflow_id,temporal_first_run_id
                     FROM autonomous_mission_execution_epochs
                    WHERE id=? AND mission_id=?""",
                (epoch_id, mission_id),
            ).fetchone()
            if epoch_id is not None
            else None
        )
        checkpoint = None
        checkpoint_ok = checkpoint_id is None
        if checkpoint_id is not None:
            try:
                checkpoint = self.checkpoints.verify_checkpoint(
                    checkpoint_id,
                    verify_git=True,
                )
                checkpoint_ok = True
                decisions.append(
                    (
                        "CHECKPOINT_VERIFIED",
                        None,
                        {
                            "checkpoint_id": checkpoint.id,
                            "checkpoint_digest": checkpoint.checkpoint_digest,
                            "git_commit_sha": checkpoint.git_commit_sha,
                        },
                    )
                )
            except Exception as exc:
                integrity["checkpoint"] = {
                    "ok": False,
                    "checkpoint_id": checkpoint_id,
                    "error": type(exc).__name__,
                }
        integrity.setdefault(
            "checkpoint",
            {"ok": checkpoint_ok, "checkpoint_id": checkpoint_id},
        )

        git = git_reconciler or GitOperationReconciler()
        git_required = checkpoint is not None or epoch_row is not None
        git_observation: OperationObservation | None = None
        if checkpoint is not None:
            git_observation = git.observe_authority(
                repository=Path(checkpoint.git_worktree_path),
                commit_sha=checkpoint.git_commit_sha,
                branch=checkpoint.git_branch,
            )
        elif epoch_row is not None:
            configuration = json.loads(str(mission["configuration_json"]))
            repository_value = configuration.get("repository_path")
            if isinstance(repository_value, str) and repository_value.strip():
                git_observation = git.observe_authority(
                    repository=Path(repository_value),
                    commit_sha=str(epoch_row["base_git_commit_sha"]),
                    branch=str(epoch_row["epoch_branch"]),
                )
            else:
                git_observation = OperationObservation.indeterminate(
                    evidence={"field": "configuration.repository_path"},
                    reason="Mission repository authority is not configured",
                )
        git_ok = (
            not git_required
            or (
                git_observation is not None
                and git_observation.status == ObservationStatus.PRESENT
            )
        )
        integrity["git_authority"] = {
            "ok": git_ok,
            "required": git_required,
            "status": (
                git_observation.status.value if git_observation is not None else None
            ),
            "reason": git_observation.reason if git_observation is not None else None,
        }
        if git_ok and git_required and git_observation is not None:
            decisions.append(
                (
                    "GIT_AUTHORITY_VERIFIED",
                    None,
                    {
                        "status": git_observation.status.value,
                        "actual": git_observation.actual,
                    },
                )
            )

        model_lease_row = self.storage.db.execute(
            """SELECT id,operation_id,execution_epoch_id,child_job_id,
                      fencing_token,request_digest,status,started_at
                 FROM autonomous_mission_operation_leases
                WHERE mission_id=? AND operation_kind='INFERENCE'
                  AND status IN ('ACTIVE','RELEASING')
                ORDER BY id DESC LIMIT 1""",
            (mission_id,),
        ).fetchone()
        model_lease = dict(model_lease_row) if model_lease_row else None
        decisions.append(
            (
                "MODEL_LEASE_RECONSTRUCTED",
                None,
                {
                    "active": model_lease is not None,
                    "operation_id": (
                        model_lease["operation_id"] if model_lease else None
                    ),
                    "status": model_lease["status"] if model_lease else None,
                },
            )
        )

        configured_handlers = {
            OperationClass(str(getattr(kind, "value", kind))): handler
            for kind, handler in (reconcilers or {}).items()
        }
        default_handlers: dict[
            OperationClass, Callable[[MissionOperation], OperationObservation]
        ] = {
            OperationClass.WORKTREE: git.observe,
            OperationClass.GIT_INTEGRATION: git.observe,
            OperationClass.CHECKPOINT: self._observe_checkpoint_operation,
            OperationClass.REVISION_TRANSITION: self._observe_revision_transition,
            OperationClass.EPOCH_TRANSITION: self._observe_epoch_transition,
        }
        default_handlers.update(configured_handlers)
        global_integrity_ok = (
            bool(integrity.get("ok"))
            and bool(integrity["control_fence"]["ok"])
            and checkpoint_ok
            and git_ok
        )
        journal_ok = True
        try:
            operations = list(self.operation_journal.list_for_mission(mission_id))
        except OperationJournalIntegrityError as exc:
            operations = []
            journal_ok = False
            integrity["operation_journal"] = {
                "ok": False,
                "error": type(exc).__name__,
            }
        operation_replay_safe = journal_ok
        for operation in operations:
            lifecycle = operation.latest_event.lifecycle
            recovery_event = operation.latest_event.event_key.startswith(
                f"{recovery_key}:operation:{operation.id}:"
            )
            if recovery_event:
                recovered_decision_type = {
                    OperationLifecycle.UNKNOWN: "OPERATION_MARKED_UNKNOWN",
                    OperationLifecycle.RETRY_READY: "OPERATION_RETRY_READY",
                    OperationLifecycle.RECONCILED: "OPERATION_RECONCILED",
                    OperationLifecycle.NEEDS_ATTENTION: "OPERATION_BLOCKED",
                }.get(lifecycle)
                if recovered_decision_type is not None:
                    decisions.append(
                        (
                            recovered_decision_type,
                            operation.id,
                            {
                                "lifecycle": lifecycle.value,
                                "recovered_from_partial_recovery": True,
                                "evidence_digest": (
                                    operation.latest_event.evidence_digest
                                ),
                            },
                        )
                    )
            elif lifecycle == OperationLifecycle.NEEDS_ATTENTION:
                decisions.append(
                    (
                        "OPERATION_BLOCKED",
                        operation.id,
                        {
                            "lifecycle": lifecycle.value,
                            "evidence_digest": operation.latest_event.evidence_digest,
                        },
                    )
                )
            if lifecycle == OperationLifecycle.RUNNING:
                operation = self.operation_journal.mark_unknown(
                    operation.id,
                    event_key=(
                        f"{recovery_key}:operation:{operation.id}:mark-unknown"
                    ),
                    evidence={
                        "recovery_key": recovery_key,
                        "prior_lifecycle": lifecycle.value,
                    },
                )
                lifecycle = operation.latest_event.lifecycle
                decisions.append(
                    (
                        "OPERATION_MARKED_UNKNOWN",
                        operation.id,
                        {"prior_lifecycle": "running"},
                    )
                )
            if lifecycle == OperationLifecycle.RESERVED and global_integrity_ok:
                operation = self.operation_journal.prepare_retry(
                    operation.id,
                    event_key=(
                        f"{recovery_key}:operation:{operation.id}:reserved-retry"
                    ),
                    evidence={
                        "recovery_key": recovery_key,
                        "protocol": "no side effect may begin before running",
                    },
                )
                lifecycle = operation.latest_event.lifecycle
                decisions.append(
                    (
                        "OPERATION_RETRY_READY",
                        operation.id,
                        {"reason": "reservation had not entered running"},
                    )
                )
            elif lifecycle == OperationLifecycle.RESERVED:
                operation = self.operation_journal.mark_unknown(
                    operation.id,
                    event_key=(
                        f"{recovery_key}:operation:{operation.id}:unsafe-reservation"
                    ),
                    evidence={
                        "recovery_key": recovery_key,
                        "integrity_ok": False,
                    },
                )
                lifecycle = operation.latest_event.lifecycle
                decisions.append(
                    (
                        "OPERATION_MARKED_UNKNOWN",
                        operation.id,
                        {"prior_lifecycle": "reserved", "integrity_ok": False},
                    )
                )
            if lifecycle == OperationLifecycle.UNKNOWN:
                handler = default_handlers.get(operation.operation_class)
                if not global_integrity_ok:
                    handler = lambda _operation: OperationObservation.indeterminate(
                        evidence={"global_integrity_ok": False},
                        reason="Global mission authority failed verification",
                    )
                elif handler is None:
                    handler = lambda _operation: OperationObservation.indeterminate(
                        evidence={
                            "operation_class": _operation.operation_class.value,
                            "handler_configured": False,
                        },
                        reason="No typed reconciliation handler is configured",
                    )
                operation = self.operation_journal.reconcile_unknown(
                    operation.id,
                    event_key=(
                        f"{recovery_key}:operation:{operation.id}:reconcile"
                    ),
                    observer=handler,
                )
                lifecycle = operation.latest_event.lifecycle
                if lifecycle == OperationLifecycle.RECONCILED:
                    decision_type = "OPERATION_RECONCILED"
                elif lifecycle == OperationLifecycle.RETRY_READY:
                    decision_type = "OPERATION_RETRY_READY"
                else:
                    decision_type = "OPERATION_BLOCKED"
                decisions.append(
                    (
                        decision_type,
                        operation.id,
                        {
                            "lifecycle": lifecycle.value,
                            "evidence_digest": operation.latest_event.evidence_digest,
                        },
                    )
                )
            if lifecycle in {
                OperationLifecycle.UNKNOWN,
                OperationLifecycle.RUNNING,
                OperationLifecycle.RESERVED,
                OperationLifecycle.NEEDS_ATTENTION,
            }:
                operation_replay_safe = False
        integrity["operation_journal"] = {
            "ok": journal_ok,
            "operation_count": len(operations),
            "replay_safe": operation_replay_safe,
        }

        operations = (
            list(self.operation_journal.list_for_mission(mission_id))
            if journal_ok
            else []
        )
        service_operations = [
            operation
            for operation in operations
            if operation.operation_class == OperationClass.SERVICE
        ]
        service_manifest = (
            checkpoint.document.get("service_manifest")
            if checkpoint is not None
            else None
        )
        required_services = {
            "manifest": service_manifest,
            "operations": [
                {
                    "operation_id": operation.id,
                    "service": operation.request.get("service")
                    or operation.request.get("service_name")
                    or operation.request.get("service_id"),
                    "desired_state": operation.request.get("desired_state")
                    or operation.request.get("expected_state"),
                    "lifecycle": operation.latest_event.lifecycle.value,
                    "result_digest": operation.latest_event.result_digest,
                }
                for operation in service_operations
            ],
        }
        decisions.append(
            (
                "SERVICES_RECONSTRUCTED",
                None,
                {
                    "manifest_present": service_manifest is not None,
                    "operation_count": len(service_operations),
                },
            )
        )

        active_task = self._active_task(mission_id, revision_id, epoch_id)
        temporal_row = self.storage.db.execute(
            """SELECT sequence,workflow_id,run_id,first_run_id,workflow_build_id,
                      accepted_mutation_count
                 FROM autonomous_mission_temporal_runs
                WHERE mission_id=? ORDER BY sequence DESC LIMIT 1""",
            (mission_id,),
        ).fetchone()
        snapshot = {
            "mission": {
                "id": mission_id,
                "identity": str(mission["identity"]),
                "mission_key": str(mission["mission_key"]),
                "version": mission_version,
                "phase": str(mission["phase"]),
                "disposition": str(mission["disposition"]),
            },
            "control_fence": {
                "fencing_token": int(mission["fencing_token"]),
                "mission_version": int(mission["fence_mission_version"]),
                "disposition": str(mission["fence_disposition"]),
            },
            "active_backlog_revision": (
                dict(revision_row) if revision_row is not None else None
            ),
            "active_execution_epoch": (
                dict(epoch_row) if epoch_row is not None else None
            ),
            "active_task": active_task,
            "last_committed_checkpoint": (
                {
                    "id": checkpoint.id,
                    "checkpoint_key": checkpoint.checkpoint_key,
                    "checkpoint_digest": checkpoint.checkpoint_digest,
                    "sequence": checkpoint.sequence,
                    "git_commit_sha": checkpoint.git_commit_sha,
                    "git_branch": checkpoint.git_branch,
                    "git_worktree_path": checkpoint.git_worktree_path,
                }
                if checkpoint is not None
                else None
            ),
            "git_authority": (
                {
                    "status": git_observation.status.value,
                    "actual": git_observation.actual,
                    "evidence": git_observation.evidence,
                    "reason": git_observation.reason,
                }
                if git_observation is not None
                else {"status": "not_required"}
            ),
            "model_lease": model_lease,
            "required_services": required_services,
            "operations": [self._operation_summary(item) for item in operations],
            "temporal_run": dict(temporal_row) if temporal_row else None,
        }
        authority_ok = global_integrity_ok and journal_ok and operation_replay_safe
        if not authority_ok:
            disposition = MissionRecoveryDisposition.NEEDS_ATTENTION
            replay_safe = False
        elif str(mission["phase"]) == "COMPLETED":
            disposition = MissionRecoveryDisposition.COMPLETED
            replay_safe = False
        elif str(mission["disposition"]) == "PAUSED":
            disposition = MissionRecoveryDisposition.PAUSED
            replay_safe = False
        elif str(mission["disposition"]) == "STOPPED":
            disposition = MissionRecoveryDisposition.STOPPED
            replay_safe = False
        elif str(mission["disposition"]) == "RUNNING":
            disposition = MissionRecoveryDisposition.RESUME_SAFE
            replay_safe = True
        else:
            disposition = MissionRecoveryDisposition.NEEDS_ATTENTION
            replay_safe = False
        if not authority_ok:
            decisions.append(
                (
                    "INTEGRITY_FAILED",
                    None,
                    {
                        "database_ok": bool(integrity.get("ok")),
                        "control_fence_ok": bool(integrity["control_fence"]["ok"]),
                        "checkpoint_ok": checkpoint_ok,
                        "git_ok": git_ok,
                        "operation_journal_ok": journal_ok,
                        "operation_replay_safe": operation_replay_safe,
                    },
                )
            )
        decisions.append(
            (
                "RESUME_ALLOWED" if replay_safe else "RESUME_BLOCKED",
                None,
                {
                    "disposition": disposition.value,
                    "replay_safe": replay_safe,
                },
            )
        )

        snapshot_json = canonical_json(snapshot)
        snapshot_digest = canonical_digest(snapshot)
        integrity_json = canonical_json(integrity)
        integrity_digest = canonical_digest(integrity)
        with self.storage.db:
            self.storage._begin_immediate()
            existing = self.storage.db.execute(
                """SELECT * FROM autonomous_mission_recoveries
                    WHERE mission_id=? AND recovery_key=?""",
                (mission_id, recovery_key),
            ).fetchone()
            if existing:
                return self._load_mission_recovery(existing)
            current = self.storage.db.execute(
                "SELECT version FROM autonomous_missions WHERE id=?",
                (mission_id,),
            ).fetchone()
            if not current or int(current["version"]) != mission_version:
                raise PermissionError(
                    "Mission changed while authoritative recovery was reconstructed"
                )
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_mission_recoveries(
                       identity,mission_id,recovery_key,mission_version,
                       disposition,replay_safe,snapshot_json,snapshot_digest,
                       integrity_json,integrity_digest,actor
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("mission-recovery"),
                    mission_id,
                    recovery_key,
                    mission_version,
                    disposition.value,
                    replay_safe,
                    snapshot_json,
                    snapshot_digest,
                    integrity_json,
                    integrity_digest,
                    actor,
                ),
            )
            recovery_id = int(cursor.lastrowid)
            for sequence, (decision_type, operation_id, document) in enumerate(
                decisions,
                start=1,
            ):
                decision_json = canonical_json(document)
                decision_digest = canonical_digest(document)
                decision_cursor = self.storage.db.execute(
                    """INSERT INTO autonomous_mission_recovery_decisions(
                           identity,recovery_id,sequence,decision_type,
                           operation_id,decision_json,decision_digest
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (
                        self.storage._identity("mission-recovery-decision"),
                        recovery_id,
                        sequence,
                        decision_type,
                        operation_id,
                        decision_json,
                        decision_digest,
                    ),
                )
                self.storage._event(
                    "mission.recovery.decision",
                    "autonomous_mission_recovery",
                    recovery_id,
                    {
                        "mission_id": mission_id,
                        "recovery_id": recovery_id,
                        "decision_id": int(decision_cursor.lastrowid),
                        "sequence": sequence,
                        "decision_type": decision_type,
                        "operation_id": operation_id,
                        "decision_digest": decision_digest,
                    },
                )
            self.storage._event(
                "mission.recovery.persisted",
                "autonomous_mission_recovery",
                recovery_id,
                {
                    "mission_id": mission_id,
                    "recovery_key": recovery_key,
                    "mission_version": mission_version,
                    "disposition": disposition.value,
                    "replay_safe": replay_safe,
                    "snapshot_digest": snapshot_digest,
                    "integrity_digest": integrity_digest,
                },
            )
        return self.get_mission_recovery(mission_id, recovery_key)
