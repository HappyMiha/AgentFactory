"""Immutable Autonomous Mission backlog revisions and active projections."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .autonomous_mission import AutonomousMission, AutonomousMissionService
from .backlog import BacklogProposal, ProposedItem
from .storage import SQLiteStorage


class BacklogRevisionOrigin(StrEnum):
    HUMAN = "HUMAN"
    AGENT_MATERIAL = "AGENT_MATERIAL"
    TECHNICAL_SUBTASK = "TECHNICAL_SUBTASK"


class BacklogImpactClassification(StrEnum):
    VALID = "VALID"
    STALE = "STALE"
    PARTIALLY_AFFECTED = "PARTIALLY_AFFECTED"
    REMOVED = "REMOVED"
    NEW = "NEW"


class BacklogItemStatus(StrEnum):
    DONE = "DONE"
    RUNNING = "RUNNING"
    READY = "READY"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    STALE = "STALE"
    PROPOSED = "PROPOSED"


ITEM_STATE_TRANSITIONS = {
    BacklogItemStatus.PROPOSED: frozenset(
        {
            BacklogItemStatus.READY,
            BacklogItemStatus.RUNNING,
            BacklogItemStatus.BLOCKED,
            BacklogItemStatus.FAILED,
        }
    ),
    BacklogItemStatus.READY: frozenset(
        {
            BacklogItemStatus.RUNNING,
            BacklogItemStatus.BLOCKED,
            BacklogItemStatus.FAILED,
        }
    ),
    BacklogItemStatus.RUNNING: frozenset(
        {
            BacklogItemStatus.DONE,
            BacklogItemStatus.FAILED,
            BacklogItemStatus.BLOCKED,
        }
    ),
    BacklogItemStatus.BLOCKED: frozenset(
        {BacklogItemStatus.READY, BacklogItemStatus.RUNNING, BacklogItemStatus.FAILED}
    ),
    BacklogItemStatus.FAILED: frozenset(
        {BacklogItemStatus.READY, BacklogItemStatus.RUNNING, BacklogItemStatus.BLOCKED}
    ),
    BacklogItemStatus.STALE: frozenset(
        {BacklogItemStatus.READY, BacklogItemStatus.RUNNING, BacklogItemStatus.BLOCKED}
    ),
    BacklogItemStatus.DONE: frozenset(),
}

NON_INVALIDATING_FIELDS = frozenset(
    {"priority", "labels", "review_notes", "assigned_role"}
)
GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{7,64}$")


@dataclass(frozen=True)
class BacklogRevision:
    id: int
    identity: str
    mission_id: int
    revision_number: int
    parent_revision_id: int | None
    origin: BacklogRevisionOrigin
    created_by: str
    rationale: str
    schema_version: int
    source_sha256: str
    revision_digest: str
    items: tuple[ProposedItem, ...]
    created_at: str


@dataclass(frozen=True)
class BacklogImpact:
    stable_id: str
    classification: BacklogImpactClassification
    changed_fields: tuple[str, ...]
    prior_item_digest: str | None
    current_item_digest: str | None
    rationale: str


@dataclass(frozen=True)
class BacklogItemProjection:
    revision_id: int
    item_id: int
    item: ProposedItem
    status: BacklogItemStatus
    persisted_status: BacklogItemStatus
    sequence: int
    attempt_count: int
    validation_result: dict[str, Any]
    git_commit_sha: str | None
    checkpoint_id: int | None
    execution_epoch_id: int | None
    epoch_superseded: bool
    evidence: tuple[dict[str, Any], ...]
    impact: BacklogImpactClassification


@dataclass(frozen=True)
class BacklogItemStateEvidence:
    state_id: int
    revision_id: int
    item_id: int
    stable_id: str
    sequence: int
    status: BacklogItemStatus
    attempt_count: int
    validation_result: dict[str, Any]
    git_commit_sha: str | None
    checkpoint_id: int | None
    execution_epoch_id: int | None
    epoch_superseded: bool
    evidence: tuple[dict[str, Any], ...]
    carried_from_state_id: int | None
    actor: str
    command_id: str
    reason: str
    created_at: str


class BacklogCommandConflictError(ValueError):
    """Raised when a backlog command key is rebound to other input."""


class BacklogRevisionService:
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
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{label} is required")
        return normalized

    def _replay(self, command_id: str, request_digest: str) -> dict[str, Any] | None:
        row = self.storage.db.execute(
            "SELECT request_digest,result_json FROM autonomous_backlog_commands "
            "WHERE command_id=?",
            (command_id,),
        ).fetchone()
        if not row:
            return None
        if row["request_digest"] != request_digest:
            raise BacklogCommandConflictError(
                f"Backlog command {command_id!r} is already bound to another request"
            )
        return json.loads(row["result_json"])

    def _record_command(
        self,
        *,
        mission_id: int,
        command_id: str,
        command_type: str,
        actor: str,
        request_digest: str,
        result: dict[str, Any],
    ) -> None:
        self.storage.db.execute(
            """INSERT INTO autonomous_backlog_commands(
                   identity,mission_id,command_id,command_type,actor,
                   request_digest,result_json
               ) VALUES(?,?,?,?,?,?,?)""",
            (
                self.storage._identity("autonomous-backlog-command"),
                mission_id,
                command_id,
                command_type,
                actor,
                request_digest,
                self._json(result),
            ),
        )

    def create_revision(
        self,
        *,
        mission_id: int,
        proposal: BacklogProposal,
        origin: BacklogRevisionOrigin | str,
        created_by: str,
        command_id: str,
        rationale: str,
        parent_revision_id: int | None = None,
    ) -> BacklogRevision:
        origin = BacklogRevisionOrigin(origin)
        created_by = self._required(created_by, "Revision author")
        command_id = self._required(command_id, "Command id")
        rationale = self._required(rationale, "Revision rationale")
        if not proposal.items:
            raise ValueError("A backlog revision cannot be empty")
        snapshot = proposal.to_dict()
        revision_digest = self._digest(snapshot)
        request = {
            "type": "create_revision",
            "mission_id": mission_id,
            "origin": origin.value,
            "created_by": created_by,
            "parent_revision_id": parent_revision_id,
            "revision_digest": revision_digest,
            "rationale": rationale,
        }
        request_digest = self._digest(request)
        replay = self._replay(command_id, request_digest)
        if replay:
            return self.get_revision(int(replay["revision_id"]))

        with self.storage.db:
            self.storage._begin_immediate()
            replay = self._replay(command_id, request_digest)
            if replay:
                return self.get_revision(int(replay["revision_id"]))
            mission = self.storage.db.execute(
                "SELECT id FROM autonomous_missions WHERE id=?", (mission_id,)
            ).fetchone()
            if not mission:
                raise KeyError(f"Unknown Autonomous Mission: {mission_id}")
            latest = self.storage.db.execute(
                """SELECT * FROM autonomous_backlog_revisions
                   WHERE mission_id=? ORDER BY revision_number DESC LIMIT 1""",
                (mission_id,),
            ).fetchone()
            if parent_revision_id is None and latest:
                parent_revision_id = int(latest["id"])
            parent = None
            if parent_revision_id is not None:
                parent = self.storage.db.execute(
                    "SELECT * FROM autonomous_backlog_revisions WHERE id=?",
                    (parent_revision_id,),
                ).fetchone()
                if not parent or int(parent["mission_id"]) != mission_id:
                    raise ValueError("Parent backlog revision belongs to another mission")
            existing = self.storage.db.execute(
                """SELECT * FROM autonomous_backlog_revisions
                   WHERE mission_id=? AND revision_digest=?""",
                (mission_id, revision_digest),
            ).fetchone()
            if existing:
                if (
                    existing["origin"] != origin.value
                    or self._optional_id(existing["parent_revision_id"])
                    != parent_revision_id
                ):
                    raise ValueError(
                        "Identical backlog content already exists with different provenance"
                    )
                revision_id = int(existing["id"])
                self._record_command(
                    mission_id=mission_id,
                    command_id=command_id,
                    command_type="create_revision",
                    actor=created_by,
                    request_digest=request_digest,
                    result={"revision_id": revision_id},
                )
                return self.get_revision(revision_id)

            revision_number = int(latest["revision_number"]) + 1 if latest else 1
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_backlog_revisions(
                       identity,mission_id,revision_number,parent_revision_id,origin,
                       created_by,rationale,schema_version,source_sha256,snapshot_json,
                       revision_digest,item_count
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-backlog-revision"),
                    mission_id,
                    revision_number,
                    parent_revision_id,
                    origin.value,
                    created_by,
                    rationale,
                    proposal.schema_version,
                    proposal.source_sha256,
                    self._json(snapshot),
                    revision_digest,
                    len(proposal.items),
                ),
            )
            revision_id = int(cursor.lastrowid)
            current_rows: dict[str, Any] = {}
            for item in proposal.items:
                document = item.to_dict()
                item_digest = self._digest(document)
                item_cursor = self.storage.db.execute(
                    """INSERT INTO autonomous_backlog_items(
                           identity,revision_id,stable_id,kind,executable,title,
                           description,parent_stable_id,dependencies_json,priority,
                           acceptance_criteria_json,validation_method_json,
                           required_components_json,required_infrastructure_json,
                           expected_artifacts_json,definition_of_done_json,
                           assigned_role,source_references_json,review_notes_json,
                           labels_json,item_digest
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        self.storage._identity("autonomous-backlog-item"),
                        revision_id,
                        item.stable_id,
                        item.kind,
                        int(item.executable),
                        item.title,
                        item.description,
                        item.parent_id,
                        self._json(item.dependencies),
                        item.priority,
                        self._json(item.acceptance_criteria),
                        self._json(item.validation_method),
                        self._json(item.required_components),
                        self._json(item.required_infrastructure),
                        self._json(item.expected_artifacts),
                        self._json(item.definition_of_done),
                        item.assigned_role,
                        self._json(item.source_references),
                        self._json(item.review_notes),
                        self._json(item.labels),
                        item_digest,
                    ),
                )
                current_rows[item.stable_id] = {
                    "id": int(item_cursor.lastrowid),
                    "item": item,
                    "document": document,
                    "digest": item_digest,
                }

            prior_rows = self._revision_item_rows(parent_revision_id)
            all_ids = sorted(set(prior_rows) | set(current_rows))
            impact_counts = {classification.value: 0 for classification in BacklogImpactClassification}
            for stable_id in all_ids:
                prior = prior_rows.get(stable_id)
                current = current_rows.get(stable_id)
                classification, changed_fields, impact_reason = self._classify_impact(
                    prior, current
                )
                impact_counts[classification.value] += 1
                self.storage.db.execute(
                    """INSERT INTO autonomous_backlog_impacts(
                           identity,revision_id,prior_revision_id,stable_id,
                           classification,changed_fields_json,prior_item_digest,
                           current_item_digest,rationale
                       ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        self.storage._identity("autonomous-backlog-impact"),
                        revision_id,
                        parent_revision_id,
                        stable_id,
                        classification.value,
                        self._json(changed_fields),
                        prior["digest"] if prior else None,
                        current["digest"] if current else None,
                        impact_reason,
                    ),
                )
                if current:
                    self._create_initial_state(
                        item_id=int(current["id"]),
                        classification=classification,
                        changed_fields=changed_fields,
                        prior=prior,
                        actor=created_by,
                        command_id=command_id,
                    )
            self._record_command(
                mission_id=mission_id,
                command_id=command_id,
                command_type="create_revision",
                actor=created_by,
                request_digest=request_digest,
                result={"revision_id": revision_id},
            )
            self.storage._event(
                "autonomous_backlog.revision_created",
                "autonomous_backlog_revision",
                revision_id,
                {
                    "mission_id": mission_id,
                    "revision_number": revision_number,
                    "parent_revision_id": parent_revision_id,
                    "origin": origin.value,
                    "created_by": created_by,
                    "command_id": command_id,
                    "revision_digest": revision_digest,
                    "item_count": len(proposal.items),
                    "impact_counts": impact_counts,
                },
            )
        return self.get_revision(revision_id)

    @staticmethod
    def _optional_id(value: Any) -> int | None:
        return int(value) if value is not None else None

    def _revision_item_rows(self, revision_id: int | None) -> dict[str, dict[str, Any]]:
        if revision_id is None:
            return {}
        result: dict[str, dict[str, Any]] = {}
        for row in self.storage.db.execute(
            "SELECT * FROM autonomous_backlog_items WHERE revision_id=?",
            (revision_id,),
        ):
            state = self._latest_state(int(row["id"]))
            item = self._row_item(row)
            result[item.stable_id] = {
                "id": int(row["id"]),
                "item": item,
                "document": item.to_dict(),
                "digest": str(row["item_digest"]),
                "state": state,
            }
        return result

    @staticmethod
    def _classify_impact(
        prior: dict[str, Any] | None, current: dict[str, Any] | None
    ) -> tuple[BacklogImpactClassification, tuple[str, ...], str]:
        if prior is None:
            return BacklogImpactClassification.NEW, (), "Stable item is new in this revision"
        if current is None:
            return (
                BacklogImpactClassification.REMOVED,
                (),
                "Stable item is absent from this revision",
            )
        changed = tuple(
            sorted(
                key
                for key in set(prior["document"]) | set(current["document"])
                if prior["document"].get(key) != current["document"].get(key)
            )
        )
        if not changed:
            return BacklogImpactClassification.VALID, (), "Item contract is unchanged"
        prior_state = prior.get("state")
        prior_status = str(prior_state["status"]) if prior_state else "PROPOSED"
        material = set(changed) - NON_INVALIDATING_FIELDS
        if prior_status == BacklogItemStatus.DONE.value and material:
            return (
                BacklogImpactClassification.STALE,
                changed,
                "Completed work changed in implementation-significant fields",
            )
        return (
            BacklogImpactClassification.PARTIALLY_AFFECTED,
            changed,
            "Item changed without invalidating accepted implementation evidence",
        )

    def _create_initial_state(
        self,
        *,
        item_id: int,
        classification: BacklogImpactClassification,
        changed_fields: tuple[str, ...],
        prior: dict[str, Any] | None,
        actor: str,
        command_id: str,
    ) -> None:
        prior_state = prior.get("state") if prior else None
        carry = bool(
            prior_state
            and (
                classification is BacklogImpactClassification.VALID
                or (
                    classification is BacklogImpactClassification.PARTIALLY_AFFECTED
                    and set(changed_fields).issubset(NON_INVALIDATING_FIELDS)
                )
            )
        )
        if classification is BacklogImpactClassification.STALE:
            status = BacklogItemStatus.STALE
        elif carry:
            status = BacklogItemStatus(prior_state["status"])
        else:
            status = BacklogItemStatus.PROPOSED
        self.storage.db.execute(
            """INSERT INTO autonomous_backlog_item_states(
                   identity,item_id,sequence,status,attempt_count,
                   validation_result_json,git_commit_sha,checkpoint_id,
                   execution_epoch_id,evidence_json,carried_from_state_id,
                   actor,command_id,reason
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self.storage._identity("autonomous-backlog-item-state"),
                item_id,
                1,
                status.value,
                int(prior_state["attempt_count"]) if carry else 0,
                str(prior_state["validation_result_json"]) if carry else "{}",
                prior_state["git_commit_sha"] if carry else None,
                prior_state["checkpoint_id"] if carry else None,
                prior_state["execution_epoch_id"] if carry else None,
                str(prior_state["evidence_json"]) if carry else "[]",
                int(prior_state["id"]) if carry else None,
                actor,
                command_id,
                f"Revision impact: {classification.value}",
            ),
        )

    def get_revision(self, revision_id: int) -> BacklogRevision:
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_backlog_revisions WHERE id=?", (revision_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown backlog revision: {revision_id}")
        items = tuple(
            self._row_item(item)
            for item in self.storage.db.execute(
                """SELECT * FROM autonomous_backlog_items
                   WHERE revision_id=? ORDER BY id""",
                (revision_id,),
            )
        )
        return BacklogRevision(
            id=int(row["id"]),
            identity=str(row["identity"]),
            mission_id=int(row["mission_id"]),
            revision_number=int(row["revision_number"]),
            parent_revision_id=self._optional_id(row["parent_revision_id"]),
            origin=BacklogRevisionOrigin(row["origin"]),
            created_by=str(row["created_by"]),
            rationale=str(row["rationale"]),
            schema_version=int(row["schema_version"]),
            source_sha256=str(row["source_sha256"]),
            revision_digest=str(row["revision_digest"]),
            items=items,
            created_at=str(row["created_at"]),
        )

    def list_revisions(self, mission_id: int) -> tuple[BacklogRevision, ...]:
        return tuple(
            self.get_revision(int(row["id"]))
            for row in self.storage.db.execute(
                """SELECT id FROM autonomous_backlog_revisions
                   WHERE mission_id=? ORDER BY revision_number""",
                (mission_id,),
            )
        )

    def impacts(self, revision_id: int) -> tuple[BacklogImpact, ...]:
        return tuple(
            BacklogImpact(
                stable_id=str(row["stable_id"]),
                classification=BacklogImpactClassification(row["classification"]),
                changed_fields=tuple(json.loads(row["changed_fields_json"])),
                prior_item_digest=row["prior_item_digest"],
                current_item_digest=row["current_item_digest"],
                rationale=str(row["rationale"]),
            )
            for row in self.storage.db.execute(
                """SELECT * FROM autonomous_backlog_impacts
                   WHERE revision_id=? ORDER BY stable_id""",
                (revision_id,),
            )
        )

    def activate_revision(
        self,
        revision_id: int,
        *,
        actor: str,
        command_id: str,
        expected_mission_version: int,
        reason: str,
    ) -> AutonomousMission:
        revision = self.get_revision(revision_id)
        mission = self.missions.get(revision.mission_id)
        actor = self._required(actor, "Activation actor")
        if revision.origin is BacklogRevisionOrigin.AGENT_MATERIAL:
            raise PermissionError(
                "Agent-generated material revisions require exact human approval"
            )
        if revision.origin is BacklogRevisionOrigin.HUMAN:
            if actor != revision.created_by:
                raise PermissionError(
                    "A human-authored revision must be activated by its author"
                )
        elif revision.parent_revision_id != mission.active_backlog_revision_id:
            raise PermissionError(
                "A technical subtask revision must extend the active revision"
            )
        return self.missions.set_active_backlog_revision(
            revision.mission_id,
            revision.id,
            actor=actor,
            command_id=command_id,
            expected_version=expected_mission_version,
            reason=reason,
        )

    def record_item_state(
        self,
        *,
        mission_id: int,
        stable_id: str,
        target: BacklogItemStatus | str,
        actor: str,
        command_id: str,
        expected_sequence: int,
        reason: str,
        validation_result: dict[str, Any] | None = None,
        git_commit_sha: str | None = None,
        checkpoint_id: int | None = None,
        evidence: tuple[dict[str, Any], ...] = (),
        attempt_count: int | None = None,
    ) -> BacklogItemProjection:
        mission = self.missions.get(mission_id)
        revision_id = mission.active_backlog_revision_id
        if revision_id is None:
            raise ValueError("Mission has no active backlog revision")
        actor = self._required(actor, "State actor")
        command_id = self._required(command_id, "Command id")
        reason = self._required(reason, "State reason")
        target = BacklogItemStatus(target)
        execution_epoch_id = mission.active_execution_epoch_id
        validation_result = dict(validation_result or {})
        evidence = tuple(dict(value) for value in evidence)
        if git_commit_sha is not None:
            git_commit_sha = git_commit_sha.strip().lower()
            if not GIT_SHA_PATTERN.fullmatch(git_commit_sha):
                raise ValueError("Git commit must be a hexadecimal commit SHA")
        if target is BacklogItemStatus.DONE:
            if validation_result.get("ok") is not True:
                raise ValueError("DONE requires an accepted validation result")
            if not git_commit_sha or not evidence:
                raise ValueError("DONE requires a committed SHA and acceptance evidence")
        request = {
            "type": "record_item_state",
            "mission_id": mission_id,
            "revision_id": revision_id,
            "stable_id": stable_id,
            "target": target.value,
            "actor": actor,
            "expected_sequence": expected_sequence,
            "reason": reason,
            "validation_result": validation_result,
            "git_commit_sha": git_commit_sha,
            "checkpoint_id": checkpoint_id,
            "execution_epoch_id": execution_epoch_id,
            "evidence": evidence,
            "attempt_count": attempt_count,
        }
        request_digest = self._digest(request)
        replay = self._replay(command_id, request_digest)
        if replay:
            return self.item(revision_id, stable_id)
        with self.storage.db:
            self.storage._begin_immediate()
            replay = self._replay(command_id, request_digest)
            if replay:
                return self.item(revision_id, stable_id)
            current_mission = self.missions.get(mission_id)
            if current_mission.active_backlog_revision_id != revision_id:
                raise ValueError("Active backlog revision changed before state update")
            if current_mission.active_execution_epoch_id != execution_epoch_id:
                raise ValueError("Active execution epoch changed before state update")
            item_row = self.storage.db.execute(
                """SELECT * FROM autonomous_backlog_items
                   WHERE revision_id=? AND stable_id=?""",
                (revision_id, stable_id),
            ).fetchone()
            if not item_row:
                raise KeyError(f"Unknown active backlog item: {stable_id}")
            if not bool(item_row["executable"]):
                raise ValueError("Container backlog items do not execute directly")
            current = self._latest_state(int(item_row["id"]))
            if not current:
                raise RuntimeError("Backlog item is missing its initial state")
            actual_sequence = int(current["sequence"])
            if actual_sequence != expected_sequence:
                raise ValueError(
                    f"Backlog item sequence conflict: expected {expected_sequence}, "
                    f"current {actual_sequence}"
                )
            source = BacklogItemStatus(current["status"])
            if target not in ITEM_STATE_TRANSITIONS[source]:
                raise ValueError(
                    f"Invalid backlog item transition: {source.value} -> {target.value}"
                )
            if target is BacklogItemStatus.RUNNING:
                if not mission.scheduling_allowed:
                    raise ValueError("Mission execution is fenced")
                blocked_by = self._unsatisfied_dependencies(item_row)
                if blocked_by:
                    raise ValueError(
                        f"Backlog item {stable_id} is blocked by dependencies: "
                        f"{blocked_by}"
                    )
            elif target is BacklogItemStatus.READY:
                blocked_by = self._unsatisfied_dependencies(item_row)
                if blocked_by:
                    raise ValueError(
                        f"Backlog item {stable_id} is blocked by dependencies: "
                        f"{blocked_by}"
                    )
            next_attempt_count = (
                int(attempt_count)
                if attempt_count is not None
                else int(current["attempt_count"])
                + (1 if target is BacklogItemStatus.RUNNING else 0)
            )
            if next_attempt_count < int(current["attempt_count"]):
                raise ValueError("Attempt count cannot decrease")
            state = self.storage.db.execute(
                """INSERT INTO autonomous_backlog_item_states(
                       identity,item_id,sequence,status,attempt_count,
                       validation_result_json,git_commit_sha,checkpoint_id,
                       execution_epoch_id,evidence_json,actor,command_id,reason
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-backlog-item-state"),
                    item_row["id"],
                    actual_sequence + 1,
                    target.value,
                    next_attempt_count,
                    self._json(validation_result),
                    git_commit_sha,
                    checkpoint_id,
                    execution_epoch_id,
                    self._json(evidence),
                    actor,
                    command_id,
                    reason,
                ),
            )
            state_id = int(state.lastrowid)
            self._record_command(
                mission_id=mission_id,
                command_id=command_id,
                command_type="record_item_state",
                actor=actor,
                request_digest=request_digest,
                result={
                    "revision_id": revision_id,
                    "stable_id": stable_id,
                    "state_id": state_id,
                    "sequence": actual_sequence + 1,
                },
            )
            self.storage._event(
                f"autonomous_backlog.item_{target.value.lower()}",
                "autonomous_backlog_item",
                int(item_row["id"]),
                {
                    "mission_id": mission_id,
                    "revision_id": revision_id,
                    "stable_id": stable_id,
                    "previous_status": source.value,
                    "resulting_status": target.value,
                    "attempt_count": next_attempt_count,
                    "actor": actor,
                    "command_id": command_id,
                    "reason": reason,
                    "git_commit_sha": git_commit_sha,
                    "checkpoint_id": checkpoint_id,
                    "execution_epoch_id": execution_epoch_id,
                },
            )
        return self.item(revision_id, stable_id)

    def item(self, revision_id: int, stable_id: str) -> BacklogItemProjection:
        projections = self.items(revision_id)
        for projection in projections:
            if projection.item.stable_id == stable_id:
                return projection
        raise KeyError(f"Unknown backlog item {stable_id!r} in revision {revision_id}")

    def items(self, revision_id: int) -> tuple[BacklogItemProjection, ...]:
        revision = self.get_revision(revision_id)
        mission = self.missions.get(revision.mission_id)
        rows = self.storage.db.execute(
            "SELECT * FROM autonomous_backlog_items WHERE revision_id=? ORDER BY id",
            (revision_id,),
        ).fetchall()
        states = {str(row["stable_id"]): self._latest_state(int(row["id"])) for row in rows}
        epoch_ids = {
            int(state["execution_epoch_id"])
            for state in states.values()
            if state is not None and state["execution_epoch_id"] is not None
        }
        superseded_epochs = {
            int(row["superseded_epoch_id"])
            for row in self.storage.db.execute(
                "SELECT superseded_epoch_id FROM autonomous_epoch_supersessions"
            )
            if int(row["superseded_epoch_id"]) in epoch_ids
        }
        executable = {str(row["stable_id"]): bool(row["executable"]) for row in rows}
        impact_rows = {
            str(row["stable_id"]): BacklogImpactClassification(row["classification"])
            for row in self.storage.db.execute(
                "SELECT stable_id,classification FROM autonomous_backlog_impacts WHERE revision_id=?",
                (revision_id,),
            )
        }
        result: list[BacklogItemProjection] = []
        for row in rows:
            stable_id = str(row["stable_id"])
            state = states[stable_id]
            if not state:
                raise RuntimeError(f"Backlog item {stable_id} has no state evidence")
            persisted = BacklogItemStatus(state["status"])
            effective = persisted
            if (
                mission.active_backlog_revision_id == revision_id
                and bool(row["executable"])
                and persisted is BacklogItemStatus.PROPOSED
            ):
                dependencies = tuple(json.loads(row["dependencies_json"]))
                ready = all(
                    not executable.get(dependency, False)
                    or (
                        states.get(dependency) is not None
                        and states[dependency]["status"] == BacklogItemStatus.DONE.value
                    )
                    for dependency in dependencies
                )
                effective = (
                    BacklogItemStatus.READY if ready else BacklogItemStatus.BLOCKED
                )
            result.append(
                BacklogItemProjection(
                    revision_id=revision_id,
                    item_id=int(row["id"]),
                    item=self._row_item(row),
                    status=effective,
                    persisted_status=persisted,
                    sequence=int(state["sequence"]),
                    attempt_count=int(state["attempt_count"]),
                    validation_result=json.loads(state["validation_result_json"]),
                    git_commit_sha=state["git_commit_sha"],
                    checkpoint_id=self._optional_id(state["checkpoint_id"]),
                    execution_epoch_id=self._optional_id(state["execution_epoch_id"]),
                    epoch_superseded=(
                        self._optional_id(state["execution_epoch_id"])
                        in superseded_epochs
                    ),
                    evidence=tuple(json.loads(state["evidence_json"])),
                    impact=impact_rows[stable_id],
                )
            )
        return tuple(result)

    def active_items(self, mission_id: int) -> tuple[BacklogItemProjection, ...]:
        revision_id = self.missions.get(mission_id).active_backlog_revision_id
        if revision_id is None:
            return ()
        return self.items(revision_id)

    def item_history(
        self, revision_id: int, stable_id: str
    ) -> tuple[BacklogItemStateEvidence, ...]:
        item = self.storage.db.execute(
            """SELECT id FROM autonomous_backlog_items
               WHERE revision_id=? AND stable_id=?""",
            (revision_id, stable_id),
        ).fetchone()
        if not item:
            raise KeyError(f"Unknown backlog item {stable_id!r} in revision {revision_id}")
        rows = self.storage.db.execute(
            """SELECT s.*,
                      CASE WHEN x.id IS NULL THEN 0 ELSE 1 END AS epoch_superseded
                 FROM autonomous_backlog_item_states s
                 LEFT JOIN autonomous_epoch_supersessions x
                   ON x.superseded_epoch_id=s.execution_epoch_id
                WHERE s.item_id=? ORDER BY s.sequence""",
            (item["id"],),
        ).fetchall()
        return tuple(
            BacklogItemStateEvidence(
                state_id=int(row["id"]),
                revision_id=revision_id,
                item_id=int(row["item_id"]),
                stable_id=stable_id,
                sequence=int(row["sequence"]),
                status=BacklogItemStatus(row["status"]),
                attempt_count=int(row["attempt_count"]),
                validation_result=json.loads(row["validation_result_json"]),
                git_commit_sha=row["git_commit_sha"],
                checkpoint_id=self._optional_id(row["checkpoint_id"]),
                execution_epoch_id=self._optional_id(row["execution_epoch_id"]),
                epoch_superseded=bool(row["epoch_superseded"]),
                evidence=tuple(json.loads(row["evidence_json"])),
                carried_from_state_id=self._optional_id(
                    row["carried_from_state_id"]
                ),
                actor=str(row["actor"]),
                command_id=str(row["command_id"]),
                reason=str(row["reason"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        )

    def progress(self, mission_id: int) -> dict[str, Any]:
        items = tuple(item for item in self.active_items(mission_id) if item.item.executable)
        completed = sum(item.status is BacklogItemStatus.DONE for item in items)
        total = len(items)
        mission = self.missions.get(mission_id)
        revision = (
            self.get_revision(mission.active_backlog_revision_id)
            if mission.active_backlog_revision_id is not None
            else None
        )
        return {
            "mission_id": mission_id,
            "active_revision_id": revision.id if revision else None,
            "active_revision_number": revision.revision_number if revision else None,
            "completed": completed,
            "total": total,
            "percent": round((completed / total) * 100, 2) if total else 0.0,
        }

    def _latest_state(self, item_id: int):
        return self.storage.db.execute(
            """SELECT * FROM autonomous_backlog_item_states
               WHERE item_id=? ORDER BY sequence DESC LIMIT 1""",
            (item_id,),
        ).fetchone()

    def _unsatisfied_dependencies(self, item_row: Any) -> tuple[str, ...]:
        blocked: list[str] = []
        for stable_id in json.loads(item_row["dependencies_json"]):
            dependency = self.storage.db.execute(
                """SELECT id,executable FROM autonomous_backlog_items
                   WHERE revision_id=? AND stable_id=?""",
                (item_row["revision_id"], stable_id),
            ).fetchone()
            if not dependency:
                blocked.append(str(stable_id))
                continue
            if not bool(dependency["executable"]):
                continue
            state = self._latest_state(int(dependency["id"]))
            if not state or state["status"] != BacklogItemStatus.DONE.value:
                blocked.append(str(stable_id))
        return tuple(blocked)

    @staticmethod
    def _row_item(row: Any) -> ProposedItem:
        return ProposedItem(
            stable_id=str(row["stable_id"]),
            kind=str(row["kind"]),
            title=str(row["title"]),
            description=str(row["description"]),
            parent_id=row["parent_stable_id"],
            dependencies=tuple(json.loads(row["dependencies_json"])),
            acceptance_criteria=tuple(json.loads(row["acceptance_criteria_json"])),
            source_references=tuple(json.loads(row["source_references_json"])),
            review_notes=tuple(json.loads(row["review_notes_json"])),
            labels=tuple(json.loads(row["labels_json"])),
            priority=str(row["priority"]),
            validation_method=tuple(json.loads(row["validation_method_json"])),
            required_components=tuple(json.loads(row["required_components_json"])),
            required_infrastructure=tuple(
                json.loads(row["required_infrastructure_json"])
            ),
            expected_artifacts=tuple(json.loads(row["expected_artifacts_json"])),
            definition_of_done=tuple(json.loads(row["definition_of_done_json"])),
            assigned_role=str(row["assigned_role"]),
        )
