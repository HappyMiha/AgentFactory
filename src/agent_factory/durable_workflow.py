from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable

from .storage import SQLiteStorage
from .workflow_contracts import validate_workflow


class OperationClass(StrEnum):
    PROVIDER_CALL = "provider_call"
    COMMAND = "command"
    INSTALLATION = "installation"
    SERVICE = "service"
    MODEL_LIFECYCLE = "model_lifecycle"
    WORKTREE = "worktree"
    GIT_INTEGRATION = "git_integration"
    GITHUB = "github"
    CHECKPOINT = "checkpoint"
    REVISION_TRANSITION = "revision_transition"
    EPOCH_TRANSITION = "epoch_transition"


class OperationLifecycle(StrEnum):
    RESERVED = "reserved"
    RUNNING = "running"
    UNKNOWN = "unknown"
    RETRY_READY = "retry_ready"
    COMPLETED = "completed"
    FAILED = "failed"
    RECONCILED = "reconciled"
    NEEDS_ATTENTION = "needs_attention"


class ReconciliationPolicy(StrEnum):
    VERIFY_THEN_RETRY = "verify_then_retry"
    VERIFY_ONLY = "verify_only"
    IDEMPOTENT_REPLAY = "idempotent_replay"
    MANUAL = "manual"


class ObservationStatus(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    CONFLICT = "conflict"
    INDETERMINATE = "indeterminate"


class OperationJournalIntegrityError(RuntimeError):
    """Raised when immutable operation evidence is not canonical or digest-valid."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OperationObservation:
    status: ObservationStatus
    actual: dict[str, Any]
    evidence: dict[str, Any]
    reason: str

    @classmethod
    def present(
        cls,
        actual: dict[str, Any],
        *,
        evidence: dict[str, Any] | None = None,
        reason: str = "The requested effect is present in actual state",
    ) -> "OperationObservation":
        return cls(ObservationStatus.PRESENT, actual, evidence or {}, reason)

    @classmethod
    def absent(
        cls,
        *,
        evidence: dict[str, Any] | None = None,
        reason: str = "The requested effect is absent from actual state",
    ) -> "OperationObservation":
        return cls(ObservationStatus.ABSENT, {}, evidence or {}, reason)

    @classmethod
    def conflict(
        cls,
        actual: dict[str, Any],
        *,
        evidence: dict[str, Any] | None = None,
        reason: str = "Actual state conflicts with the requested effect",
    ) -> "OperationObservation":
        return cls(ObservationStatus.CONFLICT, actual, evidence or {}, reason)

    @classmethod
    def indeterminate(
        cls,
        *,
        evidence: dict[str, Any] | None = None,
        reason: str = "Actual state could not be determined safely",
    ) -> "OperationObservation":
        return cls(ObservationStatus.INDETERMINATE, {}, evidence or {}, reason)


@dataclass(frozen=True)
class MissionOperationEvent:
    id: int
    operation_id: int
    sequence: int
    event_key: str
    lifecycle: OperationLifecycle
    result: dict[str, Any]
    result_digest: str
    evidence: dict[str, Any]
    evidence_digest: str
    decision: str
    created_at: str


@dataclass(frozen=True)
class MissionOperation:
    id: int
    identity: str
    mission_id: int
    operation_key: str
    operation_class: OperationClass
    request: dict[str, Any]
    request_digest: str
    reconciliation_policy: ReconciliationPolicy
    mission_version: int
    backlog_revision_id: int | None
    execution_epoch_id: int | None
    checkpoint_id: int | None
    child_job_id: int | None
    stable_item_id: str | None
    control_fencing_token: int
    actor: str
    created_at: str
    latest_event: MissionOperationEvent

    @property
    def execute(self) -> bool:
        return self.latest_event.lifecycle in {
            OperationLifecycle.RESERVED,
            OperationLifecycle.RETRY_READY,
        }

    @property
    def terminal(self) -> bool:
        return self.latest_event.lifecycle in {
            OperationLifecycle.COMPLETED,
            OperationLifecycle.FAILED,
            OperationLifecycle.RECONCILED,
            OperationLifecycle.NEEDS_ATTENTION,
        }


@dataclass(frozen=True)
class MissionOperationReservation:
    operation: MissionOperation
    created: bool
    execute: bool


@dataclass(frozen=True)
class MutationReservation:
    id: int
    status: str
    result: dict[str, Any] | None
    execute: bool
    request_digest: str
    result_digest: str | None
    evidence: dict[str, Any]
    reconciliation_policy: str


class MissionOperationJournal:
    """Append-only reservation and reconciliation protocol for mission effects."""

    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    @staticmethod
    def _optional_id(value: Any) -> int | None:
        return int(value) if value is not None else None

    @staticmethod
    def _enum_value(value: StrEnum | str) -> str:
        return str(getattr(value, "value", value))

    @staticmethod
    def _decode_canonical(
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
            raise OperationJournalIntegrityError(f"{label} must be a JSON object")
        if canonical_json(value) != payload:
            raise OperationJournalIntegrityError(f"{label} is not canonical JSON")
        if canonical_digest(value) != digest:
            raise OperationJournalIntegrityError(f"{label} digest does not match")
        return value

    def _event_from_row(self, row: Any) -> MissionOperationEvent:
        result = self._decode_canonical(
            str(row["result_json"]),
            str(row["result_digest"]),
            label="Mission operation result",
        )
        evidence = self._decode_canonical(
            str(row["evidence_json"]),
            str(row["evidence_digest"]),
            label="Mission operation evidence",
        )
        return MissionOperationEvent(
            id=int(row["id"]),
            operation_id=int(row["operation_id"]),
            sequence=int(row["sequence"]),
            event_key=str(row["event_key"]),
            lifecycle=OperationLifecycle(str(row["lifecycle"])),
            result=result,
            result_digest=str(row["result_digest"]),
            evidence=evidence,
            evidence_digest=str(row["evidence_digest"]),
            decision=str(row["decision"]),
            created_at=str(row["created_at"]),
        )

    def _operation_from_row(self, row: Any) -> MissionOperation:
        request = self._decode_canonical(
            str(row["request_json"]),
            str(row["request_digest"]),
            label="Mission operation request",
        )
        event_row = self.storage.db.execute(
            """SELECT * FROM autonomous_mission_operation_events
                WHERE operation_id=? ORDER BY sequence DESC LIMIT 1""",
            (row["id"],),
        ).fetchone()
        if not event_row:
            raise OperationJournalIntegrityError(
                f"Mission operation {row['id']} has no lifecycle event"
            )
        return MissionOperation(
            id=int(row["id"]),
            identity=str(row["identity"]),
            mission_id=int(row["mission_id"]),
            operation_key=str(row["operation_key"]),
            operation_class=OperationClass(str(row["operation_class"])),
            request=request,
            request_digest=str(row["request_digest"]),
            reconciliation_policy=ReconciliationPolicy(
                str(row["reconciliation_policy"])
            ),
            mission_version=int(row["mission_version"]),
            backlog_revision_id=self._optional_id(row["backlog_revision_id"]),
            execution_epoch_id=self._optional_id(row["execution_epoch_id"]),
            checkpoint_id=self._optional_id(row["checkpoint_id"]),
            child_job_id=self._optional_id(row["child_job_id"]),
            stable_item_id=(
                str(row["stable_item_id"])
                if row["stable_item_id"] is not None
                else None
            ),
            control_fencing_token=int(row["control_fencing_token"]),
            actor=str(row["actor"]),
            created_at=str(row["created_at"]),
            latest_event=self._event_from_row(event_row),
        )

    def get(self, operation_id: int) -> MissionOperation:
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_mission_operations WHERE id=?",
            (operation_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown mission operation: {operation_id}")
        return self._operation_from_row(row)

    def list_for_mission(self, mission_id: int) -> tuple[MissionOperation, ...]:
        return tuple(
            self._operation_from_row(row)
            for row in self.storage.db.execute(
                """SELECT * FROM autonomous_mission_operations
                    WHERE mission_id=? ORDER BY id""",
                (mission_id,),
            )
        )

    def events(self, operation_id: int) -> tuple[MissionOperationEvent, ...]:
        self.get(operation_id)
        return tuple(
            self._event_from_row(row)
            for row in self.storage.db.execute(
                """SELECT * FROM autonomous_mission_operation_events
                    WHERE operation_id=? ORDER BY sequence""",
                (operation_id,),
            )
        )

    def reserve(
        self,
        *,
        mission_id: int,
        operation_key: str,
        operation_class: OperationClass | str,
        request: dict[str, Any],
        reconciliation_policy: ReconciliationPolicy | str,
        actor: str,
        expected_mission_version: int | None = None,
        expected_backlog_revision_id: int | None = None,
        expected_execution_epoch_id: int | None = None,
        expected_checkpoint_id: int | None = None,
        expected_fencing_token: int | None = None,
        child_job_id: int | None = None,
        stable_item_id: str | None = None,
    ) -> MissionOperationReservation:
        if not operation_key.strip():
            raise ValueError("Mission operation key is required")
        if not actor.strip():
            raise ValueError("Mission operation actor is required")
        operation_type = OperationClass(self._enum_value(operation_class))
        policy = ReconciliationPolicy(self._enum_value(reconciliation_policy))
        request_json = canonical_json(request)
        request_digest = canonical_digest(request)

        existing = self.storage.db.execute(
            """SELECT * FROM autonomous_mission_operations
                WHERE mission_id=? AND operation_key=?""",
            (mission_id, operation_key),
        ).fetchone()
        if existing:
            operation = self._operation_from_row(existing)
            supplied_scope = {
                "mission_version": expected_mission_version,
                "backlog_revision_id": expected_backlog_revision_id,
                "execution_epoch_id": expected_execution_epoch_id,
                "checkpoint_id": expected_checkpoint_id,
                "control_fencing_token": expected_fencing_token,
                "child_job_id": child_job_id,
                "stable_item_id": stable_item_id,
            }
            mismatched_scope = [
                name
                for name, value in supplied_scope.items()
                if value is not None and getattr(operation, name) != value
            ]
            if (
                operation.operation_class != operation_type
                or operation.request_digest != request_digest
                or operation.reconciliation_policy != policy
                or mismatched_scope
            ):
                raise ValueError(
                    "Mission operation key was already bound to a different request"
                )
            return MissionOperationReservation(
                operation=operation,
                created=False,
                execute=operation.execute,
            )

        scope = self.storage.db.execute(
            """SELECT mission.version,mission.disposition,
                      mission.active_backlog_revision_id,
                      mission.active_execution_epoch_id,
                      mission.current_checkpoint_id,fence.fencing_token,
                      fence.disposition AS fence_disposition
                 FROM autonomous_missions mission
                 JOIN autonomous_mission_control_fences fence
                   ON fence.mission_id=mission.id
                WHERE mission.id=?""",
            (mission_id,),
        ).fetchone()
        if not scope:
            raise KeyError(f"Unknown autonomous mission: {mission_id}")
        if (
            scope["disposition"] != "RUNNING"
            or scope["fence_disposition"] != "RUNNING"
        ):
            raise PermissionError(
                "Mission operation cannot be reserved while scheduling is fenced"
            )
        actual_scope = {
            "mission_version": int(scope["version"]),
            "backlog_revision_id": self._optional_id(
                scope["active_backlog_revision_id"]
            ),
            "execution_epoch_id": self._optional_id(
                scope["active_execution_epoch_id"]
            ),
            "checkpoint_id": self._optional_id(scope["current_checkpoint_id"]),
            "control_fencing_token": int(scope["fencing_token"]),
        }
        expectations = {
            "mission_version": expected_mission_version,
            "backlog_revision_id": expected_backlog_revision_id,
            "execution_epoch_id": expected_execution_epoch_id,
            "checkpoint_id": expected_checkpoint_id,
            "control_fencing_token": expected_fencing_token,
        }
        stale = [
            name
            for name, expected in expectations.items()
            if expected is not None and actual_scope[name] != expected
        ]
        if stale:
            raise PermissionError(
                f"Mission operation scope is stale: {', '.join(sorted(stale))}"
            )
        with self.storage.db:
            self.storage._begin_immediate()
            cursor = self.storage.db.execute(
                """INSERT OR IGNORE INTO autonomous_mission_operations(
                       identity,mission_id,operation_key,operation_class,
                       request_json,request_digest,reconciliation_policy,
                       mission_version,backlog_revision_id,execution_epoch_id,
                       checkpoint_id,child_job_id,stable_item_id,
                       control_fencing_token,actor
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("mission-operation"),
                    mission_id,
                    operation_key,
                    operation_type.value,
                    request_json,
                    request_digest,
                    policy.value,
                    actual_scope["mission_version"],
                    actual_scope["backlog_revision_id"],
                    actual_scope["execution_epoch_id"],
                    actual_scope["checkpoint_id"],
                    child_job_id,
                    stable_item_id,
                    actual_scope["control_fencing_token"],
                    actor,
                ),
            )
            if cursor.rowcount != 1:
                concurrent = self.storage.db.execute(
                    """SELECT * FROM autonomous_mission_operations
                        WHERE mission_id=? AND operation_key=?""",
                    (mission_id, operation_key),
                ).fetchone()
                if not concurrent:
                    raise RuntimeError(
                        "Mission operation reservation was not persisted"
                    )
                operation = self._operation_from_row(concurrent)
                if (
                    operation.operation_class != operation_type
                    or operation.request_digest != request_digest
                    or operation.reconciliation_policy != policy
                ):
                    raise ValueError(
                        "Mission operation key was already bound to a different request"
                    )
                return MissionOperationReservation(
                    operation=operation,
                    created=False,
                    execute=operation.execute,
                )
            operation_id = int(cursor.lastrowid)
            self._append_unlocked(
                operation_id,
                event_key=f"{operation_key}:reserved",
                lifecycle=OperationLifecycle.RESERVED,
                result={},
                evidence={"request_digest": request_digest},
                decision="Stable operation key and pre-operation scope reserved",
                expected_from=None,
            )
        operation = self.get(operation_id)
        return MissionOperationReservation(
            operation=operation,
            created=True,
            execute=True,
        )

    def _append_unlocked(
        self,
        operation_id: int,
        *,
        event_key: str,
        lifecycle: OperationLifecycle,
        result: dict[str, Any],
        evidence: dict[str, Any],
        decision: str,
        expected_from: set[OperationLifecycle] | None,
    ) -> MissionOperationEvent:
        if not event_key.strip():
            raise ValueError("Mission operation event key is required")
        if not decision.strip():
            raise ValueError("Mission operation decision is required")
        result_json = canonical_json(result)
        result_digest = canonical_digest(result)
        evidence_json = canonical_json(evidence)
        evidence_digest = canonical_digest(evidence)
        operation_scope = self.storage.db.execute(
            """SELECT mission_id,operation_class,operation_key,request_digest
                 FROM autonomous_mission_operations WHERE id=?""",
            (operation_id,),
        ).fetchone()
        if not operation_scope:
            raise KeyError(f"Unknown mission operation: {operation_id}")
        existing = self.storage.db.execute(
            """SELECT * FROM autonomous_mission_operation_events
                WHERE operation_id=? AND event_key=?""",
            (operation_id, event_key),
        ).fetchone()
        if existing:
            event = self._event_from_row(existing)
            if (
                event.lifecycle != lifecycle
                or event.result_digest != result_digest
                or event.evidence_digest != evidence_digest
                or event.decision != decision
            ):
                raise ValueError(
                    "Mission operation event key was already bound differently"
                )
            return event
        previous = self.storage.db.execute(
            """SELECT * FROM autonomous_mission_operation_events
                WHERE operation_id=? ORDER BY sequence DESC LIMIT 1""",
            (operation_id,),
        ).fetchone()
        if expected_from is None:
            if previous:
                raise ValueError("Initial mission operation event already exists")
            sequence = 1
        else:
            if not previous:
                raise OperationJournalIntegrityError(
                    f"Mission operation {operation_id} has no reservation event"
                )
            prior = self._event_from_row(previous)
            if prior.lifecycle not in expected_from:
                raise ValueError(
                    f"Mission operation {operation_id} is {prior.lifecycle.value}"
                )
            sequence = prior.sequence + 1
        cursor = self.storage.db.execute(
            """INSERT INTO autonomous_mission_operation_events(
                   identity,operation_id,sequence,event_key,lifecycle,
                   result_json,result_digest,evidence_json,evidence_digest,decision
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                self.storage._identity("mission-operation-event"),
                operation_id,
                sequence,
                event_key,
                lifecycle.value,
                result_json,
                result_digest,
                evidence_json,
                evidence_digest,
                decision,
            ),
        )
        event_id = int(cursor.lastrowid)
        self.storage._event(
            f"mission.operation.{lifecycle.value}",
            "autonomous_mission_operation",
            operation_id,
            {
                "mission_id": int(operation_scope["mission_id"]),
                "operation_id": operation_id,
                "operation_class": str(operation_scope["operation_class"]),
                "operation_key": str(operation_scope["operation_key"]),
                "request_digest": str(operation_scope["request_digest"]),
                "event_id": event_id,
                "sequence": sequence,
                "event_key": event_key,
                "result_digest": result_digest,
                "evidence_digest": evidence_digest,
            },
        )
        return self._event_from_row(
            self.storage.db.execute(
                "SELECT * FROM autonomous_mission_operation_events WHERE id=?",
                (event_id,),
            ).fetchone()
        )

    def _append(
        self,
        operation_id: int,
        *,
        event_key: str,
        lifecycle: OperationLifecycle,
        result: dict[str, Any] | None,
        evidence: dict[str, Any] | None,
        decision: str,
        expected_from: set[OperationLifecycle],
    ) -> MissionOperation:
        self.get(operation_id)
        with self.storage.db:
            self.storage._begin_immediate()
            self._append_unlocked(
                operation_id,
                event_key=event_key,
                lifecycle=lifecycle,
                result=result or {},
                evidence=evidence or {},
                decision=decision,
                expected_from=expected_from,
            )
        return self.get(operation_id)

    def start(self, operation_id: int, *, event_key: str) -> MissionOperation:
        operation = self._append(
            operation_id,
            event_key=event_key,
            lifecycle=OperationLifecycle.RUNNING,
            result={},
            evidence={},
            decision="External mutation execution started after durable reservation",
            expected_from={
                OperationLifecycle.RESERVED,
                OperationLifecycle.RETRY_READY,
            },
        )
        if (
            operation.latest_event.lifecycle != OperationLifecycle.RUNNING
            and not operation.terminal
        ):
            raise ValueError(
                "Start event key belongs to an earlier mutation attempt"
            )
        return operation

    def complete(
        self,
        operation_id: int,
        *,
        event_key: str,
        result: dict[str, Any],
        evidence: dict[str, Any],
    ) -> MissionOperation:
        return self._append(
            operation_id,
            event_key=event_key,
            lifecycle=OperationLifecycle.COMPLETED,
            result=result,
            evidence=evidence,
            decision="External mutation completed with durable result and evidence",
            expected_from={OperationLifecycle.RUNNING},
        )

    def fail(
        self,
        operation_id: int,
        *,
        event_key: str,
        result: dict[str, Any],
        evidence: dict[str, Any],
    ) -> MissionOperation:
        return self._append(
            operation_id,
            event_key=event_key,
            lifecycle=OperationLifecycle.FAILED,
            result=result,
            evidence=evidence,
            decision="External mutation failed with a known terminal result",
            expected_from={OperationLifecycle.RUNNING},
        )

    def mark_unknown(
        self,
        operation_id: int,
        *,
        event_key: str,
        evidence: dict[str, Any],
    ) -> MissionOperation:
        return self._append(
            operation_id,
            event_key=event_key,
            lifecycle=OperationLifecycle.UNKNOWN,
            result={},
            evidence=evidence,
            decision="Completion is unknown; actual state must be observed before retry",
            expected_from={
                OperationLifecycle.RESERVED,
                OperationLifecycle.RUNNING,
                OperationLifecycle.RETRY_READY,
            },
        )

    def prepare_retry(
        self,
        operation_id: int,
        *,
        event_key: str,
        evidence: dict[str, Any],
    ) -> MissionOperation:
        return self._append(
            operation_id,
            event_key=event_key,
            lifecycle=OperationLifecycle.RETRY_READY,
            result={},
            evidence=evidence,
            decision="Actual state proves the mutation can be retried safely",
            expected_from={
                OperationLifecycle.RESERVED,
                OperationLifecycle.UNKNOWN,
            },
        )

    def reconcile_unknown(
        self,
        operation_id: int,
        *,
        event_key: str,
        observer: Callable[[MissionOperation], OperationObservation],
    ) -> MissionOperation:
        operation = self.get(operation_id)
        if operation.latest_event.lifecycle != OperationLifecycle.UNKNOWN:
            existing = self.storage.db.execute(
                """SELECT 1 FROM autonomous_mission_operation_events
                    WHERE operation_id=? AND event_key=?""",
                (operation_id, event_key),
            ).fetchone()
            if existing:
                return operation
            raise ValueError(
                f"Mission operation {operation_id} is "
                f"{operation.latest_event.lifecycle.value}"
            )
        try:
            observation = observer(operation)
        except Exception as exc:  # Observation failures must fail closed.
            observation = OperationObservation.indeterminate(
                evidence={"observer_error": type(exc).__name__},
                reason="The reconciliation observer failed",
            )
        if not isinstance(observation, OperationObservation):
            observation = OperationObservation.indeterminate(
                evidence={"observer_result": type(observation).__name__},
                reason="Operation observer returned an invalid result",
            )
        else:
            try:
                status = ObservationStatus(
                    str(getattr(observation.status, "value", observation.status))
                )
            except ValueError:
                status = ObservationStatus.INDETERMINATE
            if (
                status != observation.status
                or not isinstance(observation.actual, dict)
                or not isinstance(observation.evidence, dict)
                or not isinstance(observation.reason, str)
            ):
                observation = OperationObservation.indeterminate(
                    evidence={"observer_result": "malformed"},
                    reason="Operation observer returned malformed evidence",
                )
        evidence = {
            **observation.evidence,
            "observation_status": observation.status.value,
            "reason": observation.reason,
        }
        if observation.status == ObservationStatus.PRESENT:
            lifecycle = OperationLifecycle.RECONCILED
            result = observation.actual
            decision = "Actual state proves the mutation completed; result was adopted"
        elif (
            observation.status == ObservationStatus.ABSENT
            and operation.reconciliation_policy
            in {
                ReconciliationPolicy.VERIFY_THEN_RETRY,
                ReconciliationPolicy.IDEMPOTENT_REPLAY,
            }
        ):
            lifecycle = OperationLifecycle.RETRY_READY
            result = {}
            decision = "Actual state proves no effect exists; retry is safe"
        else:
            lifecycle = OperationLifecycle.NEEDS_ATTENTION
            result = observation.actual
            decision = "Actual state does not authorize an automatic retry"
        return self._append(
            operation_id,
            event_key=event_key,
            lifecycle=lifecycle,
            result=result,
            evidence=evidence,
            decision=decision,
            expected_from={OperationLifecycle.UNKNOWN},
        )


class DurableWorkflowExecution:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    def start(
        self,
        *,
        project_id: int,
        task_id: int,
        workflow: dict[str, Any],
        version: str,
    ) -> int:
        stages = validate_workflow(workflow)
        if not version.strip():
            raise ValueError("Workflow version is required")
        return self.storage.start_durable_run(
            project_id=project_id,
            task_id=task_id,
            workflow_id=str(workflow["id"]),
            workflow_version=version,
            definition=workflow,
            stages=list(stages),
        )

    def resume(self, run_id: int) -> dict[str, Any]:
        run = self.storage.durable_run(run_id)
        stages = self.storage.durable_stages(run_id)
        succeeded = {row["stage_key"] for row in stages if row["status"] == "succeeded"}
        ready = [
            row
            for row in stages
            if row["status"] == "pending"
            and set(json.loads(row["dependencies_json"])) <= succeeded
        ]
        return {
            "run": run,
            "stages": stages,
            "next_stage": ready[0] if ready else None,
            "waiting_approval": [
                row for row in stages if row["status"] == "waiting_approval"
            ],
        }

    def transition_stage(
        self, run_id: int, stage_key: str, target: str, payload: dict[str, Any]
    ) -> None:
        self.storage.transition_durable_stage(run_id, stage_key, target, payload)

    def reserve_mutation(
        self,
        *,
        run_id: int,
        stage_key: str,
        operation: OperationClass | str,
        idempotency_key: str,
        request: dict[str, Any],
        reconciliation_policy: ReconciliationPolicy | str | None = None,
    ) -> MutationReservation:
        row, created = self.storage.reserve_workflow_mutation(
            run_id=run_id,
            stage_key=stage_key,
            operation=str(getattr(operation, "value", operation)),
            idempotency_key=idempotency_key,
            request=request,
            reconciliation_policy=(
                str(getattr(reconciliation_policy, "value", reconciliation_policy))
                if reconciliation_policy is not None
                else None
            ),
        )
        result = json.loads(row["result_json"]) if row["result_json"] else None
        evidence = (
            json.loads(row["evidence_json"]) if row["evidence_json"] else {}
        )
        return MutationReservation(
            id=int(row["id"]),
            status=str(row["status"]),
            result=result,
            execute=created or str(row["status"]) == "retry_ready",
            request_digest=str(row["request_digest"]),
            result_digest=(
                str(row["result_digest"])
                if row["result_digest"] is not None
                else None
            ),
            evidence=evidence,
            reconciliation_policy=str(row["reconciliation_policy"]),
        )

    def start_mutation(self, mutation_id: int) -> None:
        self.storage.transition_workflow_mutation(mutation_id, "running")

    def mark_mutation_unknown(
        self, mutation_id: int, evidence: dict[str, Any]
    ) -> None:
        self.storage.transition_workflow_mutation(
            mutation_id,
            "unknown",
            evidence=evidence,
        )

    def complete_mutation(
        self,
        mutation_id: int,
        result: dict[str, Any],
        evidence: dict[str, Any] | None = None,
    ) -> None:
        self.storage.complete_workflow_mutation(mutation_id, result, evidence)
