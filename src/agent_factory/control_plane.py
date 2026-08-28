"""Authenticated controls and the durable Autonomous Mission scheduling fence."""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from .autonomous_mission import (
    AutonomousMissionService,
    MissionControlFenceConflictError,
    MissionDisposition,
    MissionVersionConflictError,
)
from .storage import SQLiteStorage


ROLE_ACTIONS = {
    "mission_owner": {
        "approve",
        "reject",
        "pause",
        "resume",
        "cancel",
        "recompose",
        "release",
        "emergency_stop",
    },
    "operations_owner": {
        "pause",
        "resume",
        "cancel",
        "emergency_stop",
        "enable",
        "drain",
        "quarantine",
        "replace",
        "retire",
    },
    "security_reviewer": {"quarantine", "release"},
}


class MissionControlAction(StrEnum):
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    STOP = "STOP"
    RETRY_CURRENT_TASK = "RETRY_CURRENT_TASK"


class MissionOperationKind(StrEnum):
    INFERENCE = "INFERENCE"
    COMMAND = "COMMAND"
    INSTALLATION = "INSTALLATION"
    SERVICE_OPERATION = "SERVICE_OPERATION"
    NEXT_WORK_ITEM = "NEXT_WORK_ITEM"
    WORKER_TOOL = "WORKER_TOOL"


@dataclass(frozen=True)
class MissionControlCommand:
    mission_id: int
    command_id: str
    action: MissionControlAction
    actor: str
    reason: str
    expected_mission_version: int
    expected_fencing_token: int
    expected_backlog_revision_id: int | None = None
    expected_execution_epoch_id: int | None = None
    child_job_id: int | None = None

    def __post_init__(self) -> None:
        if int(self.mission_id) <= 0:
            raise ValueError("Mission id must be positive")
        if int(self.expected_mission_version) <= 0:
            raise ValueError("Expected mission version must be positive")
        if int(self.expected_fencing_token) <= 0:
            raise ValueError("Expected fencing token must be positive")
        for value, label in (
            (self.command_id, "Control command id"),
            (self.actor, "Control actor"),
            (self.reason, "Control reason"),
        ):
            if not str(value).strip():
                raise ValueError(f"{label} is required")
        for value, label in (
            (self.expected_backlog_revision_id, "Expected backlog revision id"),
            (self.expected_execution_epoch_id, "Expected execution epoch id"),
            (self.child_job_id, "Child job id"),
        ):
            if value is not None and int(value) <= 0:
                raise ValueError(f"{label} must be positive")
        if (
            self.action is MissionControlAction.RETRY_CURRENT_TASK
            and self.child_job_id is None
        ):
            raise ValueError("Retry requires the current child job id")


@dataclass(frozen=True)
class MissionControlFence:
    mission_id: int
    mission_version: int
    phase: str
    disposition: str
    fencing_token: int
    backlog_revision_id: int | None
    execution_epoch_id: int | None
    updated_by_command_id: str
    updated_at: str

    @property
    def scheduling_allowed(self) -> bool:
        return self.disposition == MissionDisposition.RUNNING.value


@dataclass(frozen=True)
class MissionControlResult:
    command_row_id: int
    mission_id: int
    command_id: str
    action: MissionControlAction
    mission_version: int
    phase: str
    disposition: str
    fencing_token: int
    child_job_id: int | None
    logical_attempt: int | None
    active_operations: int
    releasing_operations: int
    duplicate: bool
    occurred_at: str


@dataclass(frozen=True)
class MissionOperationLease:
    id: int
    operation_id: str
    mission_id: int
    execution_epoch_id: int | None
    child_job_id: int | None
    operation_kind: MissionOperationKind
    fencing_token: int
    status: str
    release_reason: str | None
    started_at: str
    terminal_at: str | None


@dataclass(frozen=True)
class MissionRetrySettlement:
    id: int
    retry_request_id: int
    child_job_id: int
    failed_state_id: int
    ready_state_id: int
    next_logical_attempt: int
    command_id: str
    created_at: str


class MissionControlCommandConflictError(ValueError):
    """A command or operation identity was reused with different scope."""


class MissionSchedulingFencedError(PermissionError):
    """A new operation attempted to cross a persisted pause/stop fence."""


class MissionControlFenceService:
    """Durable admission fence checked at every autonomous operation boundary."""

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
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    @staticmethod
    def _optional_id(value: Any) -> int | None:
        return int(value) if value is not None else None

    @classmethod
    def _fence_from_row(cls, row: Any) -> MissionControlFence:
        return MissionControlFence(
            mission_id=int(row["mission_id"]),
            mission_version=int(row["mission_version"]),
            phase=str(row["phase"]),
            disposition=str(row["disposition"]),
            fencing_token=int(row["fencing_token"]),
            backlog_revision_id=cls._optional_id(row["backlog_revision_id"]),
            execution_epoch_id=cls._optional_id(row["execution_epoch_id"]),
            updated_by_command_id=str(row["updated_by_command_id"]),
            updated_at=str(row["updated_at"]),
        )

    def current(self, mission_id: int) -> MissionControlFence:
        """Return a projection reconciled against the authoritative mission row."""

        with self.storage.db:
            self.storage._begin_immediate()
            mission = self.storage.db.execute(
                "SELECT * FROM autonomous_missions WHERE id=?", (mission_id,)
            ).fetchone()
            if not mission:
                raise KeyError(f"Unknown Autonomous Mission: {mission_id}")
            row = self.storage.db.execute(
                "SELECT * FROM autonomous_mission_control_fences WHERE mission_id=?",
                (mission_id,),
            ).fetchone()
            if not row:
                self.storage.db.execute(
                    """INSERT INTO autonomous_mission_control_fences(
                           mission_id,fencing_token,mission_version,phase,
                           disposition,backlog_revision_id,execution_epoch_id,
                           updated_by_command_id
                       ) VALUES(?,1,?,?,?,?,?,?)""",
                    (
                        mission_id,
                        int(mission["version"]),
                        str(mission["phase"]),
                        str(mission["disposition"]),
                        mission["active_backlog_revision_id"],
                        mission["active_execution_epoch_id"],
                        f"control-fence-created:{mission_id}",
                    ),
                )
                row = self.storage.db.execute(
                    "SELECT * FROM autonomous_mission_control_fences WHERE mission_id=?",
                    (mission_id,),
                ).fetchone()
            authoritative = (
                int(mission["version"]),
                str(mission["phase"]),
                str(mission["disposition"]),
                self._optional_id(mission["active_backlog_revision_id"]),
                self._optional_id(mission["active_execution_epoch_id"]),
            )
            projected = (
                int(row["mission_version"]),
                str(row["phase"]),
                str(row["disposition"]),
                self._optional_id(row["backlog_revision_id"]),
                self._optional_id(row["execution_epoch_id"]),
            )
            if authoritative != projected:
                token = int(row["fencing_token"])
                scope_changed = (
                    authoritative[2] != projected[2]
                    or authoritative[4] != projected[4]
                )
                if scope_changed:
                    token += 1
                    self.storage.db.execute(
                        """UPDATE autonomous_mission_operation_leases
                              SET status='RELEASING',
                                  release_reason='Mission control scope changed'
                            WHERE mission_id=? AND status='ACTIVE'""",
                        (mission_id,),
                    )
                self.storage.db.execute(
                    """UPDATE autonomous_mission_control_fences
                          SET fencing_token=?,mission_version=?,phase=?,disposition=?,
                              backlog_revision_id=?,execution_epoch_id=?,
                              updated_by_command_id=?,updated_at=CURRENT_TIMESTAMP
                        WHERE mission_id=?""",
                    (
                        token,
                        *authoritative,
                        f"control-fence-reconciled:v{authoritative[0]}",
                        mission_id,
                    ),
                )
                row = self.storage.db.execute(
                    "SELECT * FROM autonomous_mission_control_fences WHERE mission_id=?",
                    (mission_id,),
                ).fetchone()
        return self._fence_from_row(row)

    def assert_allows(
        self,
        mission_id: int,
        *,
        expected_fencing_token: int,
        execution_epoch_id: int | None,
    ) -> MissionControlFence:
        fence = self.current(mission_id)
        if fence.fencing_token != int(expected_fencing_token):
            raise MissionControlFenceConflictError(
                mission_id, int(expected_fencing_token), fence.fencing_token
            )
        if not fence.scheduling_allowed:
            raise MissionSchedulingFencedError(
                f"Mission {mission_id} is {fence.disposition}; no new operation may start"
            )
        if fence.execution_epoch_id != execution_epoch_id:
            raise MissionSchedulingFencedError(
                "Mission execution epoch changed before operation admission"
            )
        return fence

    @staticmethod
    def _operation_from_row(row: Any) -> MissionOperationLease:
        return MissionOperationLease(
            id=int(row["id"]),
            operation_id=str(row["operation_id"]),
            mission_id=int(row["mission_id"]),
            execution_epoch_id=(
                int(row["execution_epoch_id"])
                if row["execution_epoch_id"] is not None
                else None
            ),
            child_job_id=(
                int(row["child_job_id"])
                if row["child_job_id"] is not None
                else None
            ),
            operation_kind=MissionOperationKind(row["operation_kind"]),
            fencing_token=int(row["fencing_token"]),
            status=str(row["status"]),
            release_reason=row["release_reason"],
            started_at=str(row["started_at"]),
            terminal_at=row["terminal_at"],
        )

    def begin_operation(
        self,
        *,
        operation_id: str,
        mission_id: int,
        execution_epoch_id: int | None,
        child_job_id: int | None,
        operation_kind: MissionOperationKind | str,
        expected_fencing_token: int,
        request: dict[str, Any] | None = None,
    ) -> MissionOperationLease:
        operation_id = str(operation_id).strip()
        if not operation_id:
            raise ValueError("Mission operation id is required")
        kind = MissionOperationKind(operation_kind)
        document = {
            "operation_id": operation_id,
            "mission_id": int(mission_id),
            "execution_epoch_id": execution_epoch_id,
            "child_job_id": child_job_id,
            "operation_kind": kind.value,
            "fencing_token": int(expected_fencing_token),
            "request": dict(request or {}),
        }
        request_digest = self._digest(document)
        existing = self.storage.db.execute(
            "SELECT * FROM autonomous_mission_operation_leases WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if existing:
            if existing["request_digest"] != request_digest:
                raise MissionControlCommandConflictError(
                    f"Operation {operation_id!r} is already bound to another scope"
                )
        self.assert_allows(
            mission_id,
            expected_fencing_token=expected_fencing_token,
            execution_epoch_id=execution_epoch_id,
        )
        with self.storage.db:
            self.storage._begin_immediate()
            existing = self.storage.db.execute(
                "SELECT * FROM autonomous_mission_operation_leases WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if existing:
                if existing["request_digest"] != request_digest:
                    raise MissionControlCommandConflictError(
                        f"Operation {operation_id!r} is already bound to another scope"
                    )
            mission = self.storage.db.execute(
                "SELECT disposition,active_execution_epoch_id FROM autonomous_missions WHERE id=?",
                (mission_id,),
            ).fetchone()
            fence = self.storage.db.execute(
                "SELECT * FROM autonomous_mission_control_fences WHERE mission_id=?",
                (mission_id,),
            ).fetchone()
            if not mission or not fence:
                raise KeyError(f"Unknown Autonomous Mission: {mission_id}")
            if (
                mission["disposition"] != MissionDisposition.RUNNING.value
                or fence["disposition"] != MissionDisposition.RUNNING.value
            ):
                raise MissionSchedulingFencedError(
                    "Mission scheduling changed before operation admission"
                )
            if int(fence["fencing_token"]) != int(expected_fencing_token):
                raise MissionControlFenceConflictError(
                    mission_id,
                    int(expected_fencing_token),
                    int(fence["fencing_token"]),
                )
            if self._optional_id(mission["active_execution_epoch_id"]) != execution_epoch_id:
                raise MissionSchedulingFencedError(
                    "Mission execution epoch changed before operation admission"
                )
            if existing:
                return self._operation_from_row(existing)
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_mission_operation_leases(
                       identity,operation_id,mission_id,execution_epoch_id,
                       child_job_id,operation_kind,fencing_token,request_digest,status
                   ) VALUES(?,?,?,?,?,?,?,?,'ACTIVE')""",
                (
                    self.storage._identity("autonomous-operation-lease"),
                    operation_id,
                    mission_id,
                    execution_epoch_id,
                    child_job_id,
                    kind.value,
                    expected_fencing_token,
                    request_digest,
                ),
            )
            lease_id = int(cursor.lastrowid)
            self.storage._event(
                "autonomous_mission.operation_started",
                "autonomous_mission_operation",
                lease_id,
                {
                    "mission_id": mission_id,
                    "child_job_id": child_job_id,
                    "operation_id": operation_id,
                    "operation_kind": kind.value,
                    "fencing_token": expected_fencing_token,
                },
            )
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_mission_operation_leases WHERE id=?",
            (lease_id,),
        ).fetchone()
        return self._operation_from_row(row)

    def finish_operation(
        self, operation_id: str, *, reason: str = "Atomic operation finished"
    ) -> MissionOperationLease:
        with self.storage.db:
            self.storage._begin_immediate()
            row = self.storage.db.execute(
                "SELECT * FROM autonomous_mission_operation_leases WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown mission operation: {operation_id}")
            status = str(row["status"])
            if status in {"FINISHED", "RELEASED"}:
                return self._operation_from_row(row)
            target = "RELEASED" if status == "RELEASING" else "FINISHED"
            terminal_at = self._timestamp()
            self.storage.db.execute(
                """UPDATE autonomous_mission_operation_leases
                      SET status=?,release_reason=COALESCE(release_reason,?),terminal_at=?
                    WHERE id=?""",
                (target, reason, terminal_at, int(row["id"])),
            )
            self.storage._event(
                "autonomous_mission.operation_released"
                if target == "RELEASED"
                else "autonomous_mission.operation_finished",
                "autonomous_mission_operation",
                int(row["id"]),
                {
                    "mission_id": int(row["mission_id"]),
                    "operation_id": operation_id,
                    "operation_kind": str(row["operation_kind"]),
                    "fencing_token": int(row["fencing_token"]),
                    "reason": reason,
                },
            )
        updated = self.storage.db.execute(
            "SELECT * FROM autonomous_mission_operation_leases WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        return self._operation_from_row(updated)

    def operation_leases(
        self, mission_id: int, *, active_only: bool = False
    ) -> tuple[MissionOperationLease, ...]:
        suffix = " AND status IN ('ACTIVE','RELEASING')" if active_only else ""
        rows = self.storage.db.execute(
            "SELECT * FROM autonomous_mission_operation_leases "
            f"WHERE mission_id=?{suffix} ORDER BY id",
            (mission_id,),
        )
        return tuple(self._operation_from_row(row) for row in rows)

    @staticmethod
    def _target_disposition(action: MissionControlAction) -> MissionDisposition:
        targets = {
            MissionControlAction.PAUSE: MissionDisposition.PAUSED,
            MissionControlAction.RESUME: MissionDisposition.RUNNING,
            MissionControlAction.STOP: MissionDisposition.STOPPED,
        }
        try:
            return targets[action]
        except KeyError as exc:
            raise ValueError(f"Control action {action.value} has no disposition") from exc

    @classmethod
    def _control_request(
        cls, command: MissionControlCommand
    ) -> dict[str, Any]:
        if command.action is MissionControlAction.RETRY_CURRENT_TASK:
            return {
                "type": "retry_current_task",
                "mission_id": command.mission_id,
                "actor": command.actor.strip(),
                "expected_version": command.expected_mission_version,
                "reason": command.reason.strip(),
                "expected_fencing_token": command.expected_fencing_token,
                "control_action": command.action.value,
                "expected_backlog_revision_id": (
                    command.expected_backlog_revision_id
                ),
                "expected_execution_epoch_id": (
                    command.expected_execution_epoch_id
                ),
                "child_job_id": command.child_job_id,
            }
        return {
            "type": "transition_disposition",
            "mission_id": command.mission_id,
            "actor": command.actor.strip(),
            "expected_version": command.expected_mission_version,
            "reason": command.reason.strip(),
            "target_phase": None,
            "target_disposition": cls._target_disposition(command.action).value,
            "expected_fencing_token": command.expected_fencing_token,
            "control_action": command.action.value,
            "expected_backlog_revision_id": command.expected_backlog_revision_id,
            "expected_execution_epoch_id": command.expected_execution_epoch_id,
            "child_job_id": command.child_job_id,
        }

    def _result_from_row(self, row: Any, *, duplicate: bool) -> MissionControlResult:
        counts = {
            str(value["status"]): int(value["count"])
            for value in self.storage.db.execute(
                """SELECT status,COUNT(*) AS count
                     FROM autonomous_mission_operation_leases
                    WHERE mission_id=? AND status IN ('ACTIVE','RELEASING')
                    GROUP BY status""",
                (int(row["mission_id"]),),
            )
        }
        return MissionControlResult(
            command_row_id=int(row["id"]),
            mission_id=int(row["mission_id"]),
            command_id=str(row["command_id"]),
            action=MissionControlAction(row["action"]),
            mission_version=int(row["result_mission_version"]),
            phase=str(row["result_phase"]),
            disposition=str(row["result_disposition"]),
            fencing_token=int(row["result_fencing_token"]),
            child_job_id=self._optional_id(row["child_job_id"]),
            logical_attempt=self._optional_id(row["result_logical_attempt"]),
            active_operations=counts.get("ACTIVE", 0),
            releasing_operations=counts.get("RELEASING", 0),
            duplicate=duplicate,
            occurred_at=str(row["created_at"]),
        )

    def _existing_control(
        self, command: MissionControlCommand, request_digest: str
    ) -> MissionControlResult | None:
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_mission_control_commands WHERE command_id=?",
            (command.command_id,),
        ).fetchone()
        if not row:
            return None
        if row["request_digest"] != request_digest:
            raise MissionControlCommandConflictError(
                f"Control command {command.command_id!r} is already bound"
            )
        return self._result_from_row(row, duplicate=True)

    def apply(self, command: MissionControlCommand) -> MissionControlResult:
        request = self._control_request(command)
        request_digest = self._digest(request)
        if replay := self._existing_control(command, request_digest):
            return replay
        mission = self.missions.get(command.mission_id)
        fence = self.current(command.mission_id)
        if mission.mission_owner != command.actor.strip():
            raise PermissionError("Only the authenticated mission owner may control it")
        if mission.version != command.expected_mission_version:
            raise MissionVersionConflictError(
                mission.id, command.expected_mission_version, mission.version
            )
        if fence.fencing_token != command.expected_fencing_token:
            raise MissionControlFenceConflictError(
                mission.id, command.expected_fencing_token, fence.fencing_token
            )
        if (
            command.expected_backlog_revision_id
            != mission.active_backlog_revision_id
        ):
            raise PermissionError("Control command backlog revision is stale")
        if (
            command.expected_execution_epoch_id
            != mission.active_execution_epoch_id
        ):
            raise PermissionError("Control command execution epoch is stale")
        if command.child_job_id is not None:
            child = self.storage.db.execute(
                "SELECT * FROM autonomous_child_jobs WHERE id=?",
                (command.child_job_id,),
            ).fetchone()
            if (
                not child
                or int(child["mission_id"]) != mission.id
                or int(child["backlog_revision_id"])
                != mission.active_backlog_revision_id
                or int(child["execution_epoch_id"])
                != mission.active_execution_epoch_id
            ):
                raise PermissionError("Control command child scope is stale")
        active_child = self.storage.db.execute(
            """SELECT job.id FROM autonomous_child_jobs job
                 LEFT JOIN autonomous_child_reconciliations reconciliation
                   ON reconciliation.child_job_id=job.id
                 LEFT JOIN autonomous_mission_retry_requests retry
                   ON retry.child_job_id=job.id
                WHERE job.mission_id=?
                  AND job.backlog_revision_id=?
                  AND job.execution_epoch_id=?
                  AND reconciliation.id IS NULL
                  AND retry.id IS NULL
                ORDER BY job.id LIMIT 1""",
            (
                mission.id,
                mission.active_backlog_revision_id,
                mission.active_execution_epoch_id,
            ),
        ).fetchone()
        if active_child and command.child_job_id != int(active_child["id"]):
            raise PermissionError(
                "Control command does not identify the active child"
            )
        if (
            command.action is MissionControlAction.RESUME
            and self.storage.db.execute(
                """SELECT 1 FROM autonomous_mission_operation_leases
                    WHERE mission_id=? AND status='RELEASING' LIMIT 1""",
                (mission.id,),
            ).fetchone()
        ):
            raise PermissionError(
                "Mission cannot resume before stop/retry operations reach a safe boundary"
            )
        if command.action is MissionControlAction.RETRY_CURRENT_TASK:
            return self._apply_retry(command, request_digest)
        self.missions.transition_disposition(
            mission.id,
            self._target_disposition(command.action),
            actor=command.actor,
            command_id=command.command_id,
            expected_version=command.expected_mission_version,
            reason=command.reason,
            expected_fencing_token=command.expected_fencing_token,
            control_action=command.action.value,
            expected_backlog_revision_id=command.expected_backlog_revision_id,
            expected_execution_epoch_id=command.expected_execution_epoch_id,
            child_job_id=command.child_job_id,
        )
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_mission_control_commands WHERE command_id=?",
            (command.command_id,),
        ).fetchone()
        if not row:
            raise RuntimeError("Mission control transition lacks command evidence")
        return self._result_from_row(row, duplicate=False)

    def _apply_retry(
        self, command: MissionControlCommand, request_digest: str
    ) -> MissionControlResult:
        if command.child_job_id is None:
            raise ValueError("Retry requires the current child job id")
        with self.storage.db:
            self.storage._begin_immediate()
            if replay := self._existing_control(command, request_digest):
                return replay
            mission = self.storage.db.execute(
                "SELECT * FROM autonomous_missions WHERE id=?", (command.mission_id,)
            ).fetchone()
            fence = self.storage.db.execute(
                "SELECT * FROM autonomous_mission_control_fences WHERE mission_id=?",
                (command.mission_id,),
            ).fetchone()
            child = self.storage.db.execute(
                "SELECT * FROM autonomous_child_jobs WHERE id=?",
                (command.child_job_id,),
            ).fetchone()
            if not mission or not fence or not child:
                raise KeyError("Mission retry scope is unavailable")
            if str(mission["mission_owner"]) != command.actor.strip():
                raise PermissionError("Only the mission owner may retry a task")
            if int(mission["version"]) != command.expected_mission_version:
                raise MissionVersionConflictError(
                    command.mission_id,
                    command.expected_mission_version,
                    int(mission["version"]),
                )
            if int(fence["fencing_token"]) != command.expected_fencing_token:
                raise MissionControlFenceConflictError(
                    command.mission_id,
                    command.expected_fencing_token,
                    int(fence["fencing_token"]),
                )
            if str(mission["disposition"]) != MissionDisposition.RUNNING.value:
                raise MissionSchedulingFencedError(
                    "Retry requires a running mission at a safe boundary"
                )
            if (
                int(child["mission_id"]) != command.mission_id
                or self._optional_id(mission["active_backlog_revision_id"])
                != int(child["backlog_revision_id"])
                or self._optional_id(mission["active_execution_epoch_id"])
                != int(child["execution_epoch_id"])
                or command.expected_backlog_revision_id
                != int(child["backlog_revision_id"])
                or command.expected_execution_epoch_id
                != int(child["execution_epoch_id"])
            ):
                raise PermissionError("Retry child is outside the active mission scope")
            if self.storage.db.execute(
                "SELECT 1 FROM autonomous_child_delivery_completions WHERE child_job_id=?",
                (command.child_job_id,),
            ).fetchone():
                raise ValueError("An accepted completed item cannot be retried")
            state = self.storage.db.execute(
                """SELECT * FROM autonomous_backlog_item_states
                    WHERE item_id=? ORDER BY sequence DESC LIMIT 1""",
                (int(child["backlog_item_id"]),),
            ).fetchone()
            if not state or str(state["status"]) != "RUNNING":
                raise ValueError("Only the active running backlog item can be retried")
            next_token = int(fence["fencing_token"]) + 1
            next_attempt = int(child["logical_attempt"]) + 1
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_mission_control_commands(
                       identity,mission_id,command_id,action,actor,reason,
                       expected_mission_version,expected_fencing_token,
                       expected_backlog_revision_id,
                       expected_execution_epoch_id,child_job_id,
                       request_digest,result_mission_version,
                       result_fencing_token,result_phase,result_disposition,
                       result_logical_attempt
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-control-command"),
                    command.mission_id,
                    command.command_id,
                    command.action.value,
                    command.actor.strip(),
                    command.reason.strip(),
                    command.expected_mission_version,
                    command.expected_fencing_token,
                    command.expected_backlog_revision_id,
                    command.expected_execution_epoch_id,
                    command.child_job_id,
                    request_digest,
                    command.expected_mission_version,
                    next_token,
                    str(mission["phase"]),
                    str(mission["disposition"]),
                    next_attempt,
                ),
            )
            command_row_id = int(cursor.lastrowid)
            self.storage.db.execute(
                """UPDATE autonomous_mission_control_fences
                      SET fencing_token=?,updated_by_command_id=?,
                          updated_at=CURRENT_TIMESTAMP
                    WHERE mission_id=?""",
                (next_token, command.command_id, command.mission_id),
            )
            self.storage.db.execute(
                """UPDATE autonomous_mission_operation_leases
                      SET status='RELEASING',
                          release_reason='Current task retry requested'
                    WHERE mission_id=? AND child_job_id=? AND status='ACTIVE'""",
                (command.mission_id, command.child_job_id),
            )
            retry = self.storage.db.execute(
                """INSERT INTO autonomous_mission_retry_requests(
                       identity,mission_id,child_job_id,backlog_item_id,
                       stable_item_id,previous_logical_attempt,
                       next_logical_attempt,control_command_id,fencing_token
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-retry-request"),
                    command.mission_id,
                    command.child_job_id,
                    int(child["backlog_item_id"]),
                    str(child["stable_item_id"]),
                    int(child["logical_attempt"]),
                    next_attempt,
                    command_row_id,
                    next_token,
                ),
            )
            retry_id = int(retry.lastrowid)
            self.storage._event(
                "autonomous_mission.retry_requested",
                "autonomous_mission_retry",
                retry_id,
                {
                    "mission_id": command.mission_id,
                    "child_job_id": command.child_job_id,
                    "stable_item_id": str(child["stable_item_id"]),
                    "previous_logical_attempt": int(child["logical_attempt"]),
                    "next_logical_attempt": next_attempt,
                    "fencing_token": next_token,
                    "command_id": command.command_id,
                },
            )
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_mission_control_commands WHERE id=?",
            (command_row_id,),
        ).fetchone()
        return self._result_from_row(row, duplicate=False)

    def settle_retry(
        self, child_job_id: int, *, command_id: str
    ) -> MissionRetrySettlement:
        existing = self.storage.db.execute(
            """SELECT settlement.*,retry.next_logical_attempt
                 FROM autonomous_mission_retry_settlements settlement
                 JOIN autonomous_mission_retry_requests retry
                   ON retry.id=settlement.retry_request_id
                WHERE settlement.child_job_id=?""",
            (child_job_id,),
        ).fetchone()
        if existing:
            if str(existing["command_id"]) != command_id:
                raise MissionControlCommandConflictError(
                    "Retry settlement already uses another command"
                )
            return self._settlement_from_row(existing)
        retry = self.storage.db.execute(
            "SELECT * FROM autonomous_mission_retry_requests WHERE child_job_id=?",
            (child_job_id,),
        ).fetchone()
        child = self.storage.db.execute(
            "SELECT * FROM autonomous_child_jobs WHERE id=?", (child_job_id,)
        ).fetchone()
        if not retry or not child:
            raise KeyError(f"Child job {child_job_id} has no retry request")
        if self.storage.db.execute(
            "SELECT 1 FROM autonomous_child_delivery_completions WHERE child_job_id=?",
            (child_job_id,),
        ).fetchone():
            raise ValueError("An accepted completed item cannot be retried")

        from .backlog_revisions import BacklogItemStatus, BacklogRevisionService

        revisions = BacklogRevisionService(self.storage)
        projection = revisions.item(
            int(child["backlog_revision_id"]), str(child["stable_item_id"])
        )
        failed_state_id: int
        if projection.status is BacklogItemStatus.RUNNING:
            projection = revisions.record_item_state(
                mission_id=int(child["mission_id"]),
                stable_id=str(child["stable_item_id"]),
                target=BacklogItemStatus.FAILED,
                actor=str(child["prepared_by"]),
                command_id=f"{command_id}:failed",
                expected_sequence=projection.sequence,
                reason="Supersede the current strategy at its retry boundary",
                attempt_count=projection.attempt_count,
                evidence=(
                    {
                        "kind": "retry_request",
                        "retry_request_id": int(retry["id"]),
                        "child_job_id": child_job_id,
                    },
                ),
            )
        if projection.status is BacklogItemStatus.FAILED:
            failed = self.storage.db.execute(
                """SELECT id FROM autonomous_backlog_item_states
                    WHERE item_id=? AND sequence=?""",
                (int(child["backlog_item_id"]), projection.sequence),
            ).fetchone()
            failed_state_id = int(failed["id"])
            projection = revisions.record_item_state(
                mission_id=int(child["mission_id"]),
                stable_id=str(child["stable_item_id"]),
                target=BacklogItemStatus.READY,
                actor=str(child["prepared_by"]),
                command_id=f"{command_id}:ready",
                expected_sequence=projection.sequence,
                reason="Ready the backlog item for its next logical strategy attempt",
                attempt_count=projection.attempt_count,
                evidence=(
                    {
                        "kind": "retry_request",
                        "retry_request_id": int(retry["id"]),
                        "next_logical_attempt": int(retry["next_logical_attempt"]),
                    },
                ),
            )
        elif projection.status is BacklogItemStatus.READY:
            failed = self.storage.db.execute(
                """SELECT id FROM autonomous_backlog_item_states
                    WHERE item_id=? AND status='FAILED'
                    ORDER BY sequence DESC LIMIT 1""",
                (int(child["backlog_item_id"]),),
            ).fetchone()
            if not failed:
                raise RuntimeError("Retry-ready item lacks its failed strategy state")
            failed_state_id = int(failed["id"])
        else:
            raise ValueError(
                f"Retry cannot settle backlog item in {projection.status.value}"
            )
        ready = self.storage.db.execute(
            """SELECT id FROM autonomous_backlog_item_states
                WHERE item_id=? AND sequence=?""",
            (int(child["backlog_item_id"]), projection.sequence),
        ).fetchone()
        ready_state_id = int(ready["id"])
        run = self.storage.db.execute(
            "SELECT status FROM workflow_runs WHERE id=?", (int(child["run_id"]),)
        ).fetchone()
        if run and str(run["status"]) in {"running", "awaiting_approval"}:
            self.storage.finish_run(
                int(child["run_id"]),
                "failed",
                event_payload={
                    "retry_requested": True,
                    "retry_request_id": int(retry["id"]),
                    "next_logical_attempt": int(retry["next_logical_attempt"]),
                },
            )
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_mission_retry_settlements(
                       identity,retry_request_id,child_job_id,failed_state_id,
                       ready_state_id,command_id
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-retry-settlement"),
                    int(retry["id"]),
                    child_job_id,
                    failed_state_id,
                    ready_state_id,
                    command_id,
                ),
            )
            settlement_id = int(cursor.lastrowid)
            self.storage._event(
                "autonomous_mission.retry_settled",
                "autonomous_mission_retry",
                int(retry["id"]),
                {
                    "mission_id": int(retry["mission_id"]),
                    "child_job_id": child_job_id,
                    "next_logical_attempt": int(retry["next_logical_attempt"]),
                    "failed_state_id": failed_state_id,
                    "ready_state_id": ready_state_id,
                    "command_id": command_id,
                },
            )
        row = self.storage.db.execute(
            """SELECT settlement.*,retry.next_logical_attempt
                 FROM autonomous_mission_retry_settlements settlement
                 JOIN autonomous_mission_retry_requests retry
                   ON retry.id=settlement.retry_request_id
                WHERE settlement.id=?""",
            (settlement_id,),
        ).fetchone()
        return self._settlement_from_row(row)

    @staticmethod
    def _settlement_from_row(row: Any) -> MissionRetrySettlement:
        return MissionRetrySettlement(
            id=int(row["id"]),
            retry_request_id=int(row["retry_request_id"]),
            child_job_id=int(row["child_job_id"]),
            failed_state_id=int(row["failed_state_id"]),
            ready_state_id=int(row["ready_state_id"]),
            next_logical_attempt=int(row["next_logical_attempt"]),
            command_id=str(row["command_id"]),
            created_at=str(row["created_at"]),
        )


class HumanControlPlaneService:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    def act(
        self,
        *,
        tenant_id: str,
        actor: str,
        role: str,
        action: str,
        target_type: str,
        target_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not all(
            value.strip()
            for value in (tenant_id, actor, role, action, target_type, target_id)
        ):
            raise ValueError("authenticated action scope is required")
        if action not in ROLE_ACTIONS.get(role, set()):
            raise PermissionError("role is not authorized for this action")
        if action == "retire" and (payload or {}).get("irreversible") is not True:
            raise PermissionError(
                "irreversible retirement requires explicit confirmation"
            )
        identity = f"control-action-{secrets.token_hex(12)}"
        body = payload or {}
        self.storage.db.execute(
            """INSERT INTO control_plane_actions(
                   identity,tenant_id,actor,role,action,target_type,target_id,
                   payload_json,outcome
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                identity,
                tenant_id,
                actor,
                role,
                action,
                target_type,
                target_id,
                json.dumps(body, sort_keys=True),
                "accepted",
            ),
        )
        self.storage.db.commit()
        self.storage._event(
            "control_plane.action",
            target_type,
            target_id,
            {
                "tenant_id": tenant_id,
                "actor": actor,
                "role": role,
                "action": action,
                "control_action": identity,
            },
        )
        self.storage.db.commit()
        return {
            "identity": identity,
            "tenant_id": tenant_id,
            "actor": actor,
            "role": role,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "outcome": "accepted",
        }

    def list_actions(self, tenant_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.storage.db.execute(
                "SELECT * FROM control_plane_actions WHERE tenant_id=? ORDER BY id",
                (tenant_id,),
            )
        ]
