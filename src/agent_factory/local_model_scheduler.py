"""Mission control admission boundary for local inference operations.

AF-AMM-015 introduces the durable pause/stop fence used by the later global GPU
queue. AF-AMM-024 extends this module with capacity and fairness; this guard is
already process-restart safe because admission is persisted in SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .control_plane import (
    MissionControlFenceService,
    MissionOperationKind,
    MissionOperationLease,
)
from .storage import SQLiteStorage


@dataclass(frozen=True)
class LocalInferenceFenceBinding:
    mission_id: int
    execution_epoch_id: int
    child_job_id: int
    fencing_token: int
    role: str
    provider_id: str
    model: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.mission_id, "Mission id"),
            (self.execution_epoch_id, "Execution epoch id"),
            (self.child_job_id, "Child job id"),
            (self.fencing_token, "Mission fencing token"),
        ):
            if int(value) <= 0:
                raise ValueError(f"{label} must be positive")
        for value, label in (
            (self.role, "Inference role"),
            (self.provider_id, "Inference provider id"),
            (self.model, "Inference model"),
        ):
            if not str(value).strip():
                raise ValueError(f"{label} is required")


class LocalInferenceControlGuard:
    """Acquire and release one fence-bound local inference operation."""

    def __init__(self, storage: SQLiteStorage):
        self.control = MissionControlFenceService(storage)

    def begin(
        self,
        binding: LocalInferenceFenceBinding,
        *,
        request_id: str,
        request: dict[str, Any] | None = None,
    ) -> MissionOperationLease:
        return self.control.begin_operation(
            operation_id=request_id,
            mission_id=binding.mission_id,
            execution_epoch_id=binding.execution_epoch_id,
            child_job_id=binding.child_job_id,
            operation_kind=MissionOperationKind.INFERENCE,
            expected_fencing_token=binding.fencing_token,
            request={
                "role": binding.role,
                "provider_id": binding.provider_id,
                "model": binding.model,
                **dict(request or {}),
            },
        )

    def finish(
        self, request_id: str, *, reason: str = "Local inference completed"
    ) -> MissionOperationLease:
        return self.control.finish_operation(request_id, reason=reason)
