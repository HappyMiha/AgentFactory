"""Per-stage approval orchestration for mutable live worker execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .models import ExecutionApproval
from .policy import ControlPlanePolicy, PolicyOutcome, PolicyRequest
from .storage import SQLiteStorage


@dataclass(frozen=True)
class LiveStageGate:
    approval_id: int
    request: PolicyRequest
    status: str


class LiveStageExecution:
    """Own the wait, decision envelope, and dependency-ready continuation."""

    def __init__(self, storage: SQLiteStorage):
        self.storage = storage
        self.policy = ControlPlanePolicy(storage)

    def request_approval(
        self,
        request: PolicyRequest,
        *,
        requested_by: str,
        ttl_seconds: int = 900,
    ) -> LiveStageGate:
        if request.run_id is None:
            raise ValueError("Live stage approval requires a durable run")
        stage = self.storage.db.execute(
            """SELECT s.status,r.task_id
                 FROM workflow_stages s
                 JOIN workflow_runs r ON r.id=s.run_id
                WHERE s.run_id=? AND s.stage_key=?""",
            (request.run_id, request.stage_id),
        ).fetchone()
        if not stage:
            raise KeyError(
                f"Unknown live stage {request.stage_id} for run {request.run_id}"
            )
        if int(stage["task_id"]) != request.task_id:
            raise PermissionError("Live stage belongs to another task")
        if str(stage["status"]) != "running":
            raise ValueError("A live approval can only be requested by a running stage")
        decision = self.policy.evaluate(request)
        if decision.outcome is PolicyOutcome.DENY:
            raise PermissionError(decision.reason)
        if decision.outcome is not PolicyOutcome.REQUIRE_APPROVAL:
            raise ValueError("The live execution request does not require approval")
        approval_id = self.storage.request_scoped_approval(
            request=request.canonical(),
            requested_by=requested_by,
            ttl_seconds=ttl_seconds,
        )
        self.storage.transition_durable_stage(
            request.run_id,
            request.stage_id,
            "waiting_approval",
            {
                "approval_id": approval_id,
                "request_digest": request.digest,
                "runtime_id": request.runtime_id,
                "worker_id": request.worker_id,
            },
        )
        return LiveStageGate(approval_id, request, "pending")

    def decide(
        self,
        approval_id: int,
        decision: str,
        *,
        actor: str,
        note: str = "",
    ) -> ExecutionApproval | None:
        self.storage.decide_scoped_approval(
            approval_id, decision, actor=actor, note=note
        )
        if decision == "rejected":
            return None
        row = self.storage.db.execute(
            "SELECT * FROM scoped_execution_approvals WHERE id=?", (approval_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown scoped approval: {approval_id}")
        return ExecutionApproval(
            gate_id=approval_id,
            provider=str(row["runtime_id"]),
            agent_id=str(row["worker_id"]),
            task_id=int(row["task_id"]),
            approved_by=str(row["decided_by"] or actor),
            run_id=int(row["run_id"]) if row["run_id"] is not None else None,
            stage_id=str(row["stage_id"]),
            runtime_id=str(row["runtime_id"]),
            worktree_id=(
                str(row["worktree_id"])
                if row["worktree_id"] is not None
                else None
            ),
            permissions=tuple(json.loads(row["permissions_json"])),
            request_digest=str(row["request_digest"]),
        )

    def complete_stage(
        self, run_id: int, stage_id: str, payload: dict[str, Any]
    ) -> str | None:
        self.storage.transition_durable_stage(run_id, stage_id, "succeeded", payload)
        stages = self.storage.durable_stages(run_id)
        succeeded = {
            str(row["stage_key"])
            for row in stages
            if str(row["status"]) == "succeeded"
        }
        ready = next(
            (
                row
                for row in stages
                if str(row["status"]) == "pending"
                and set(json.loads(row["dependencies_json"])) <= succeeded
            ),
            None,
        )
        if ready is None:
            return None
        next_stage = str(ready["stage_key"])
        self.storage.transition_durable_stage(
            run_id,
            next_stage,
            "running",
            {"advanced_from": stage_id, "reason": "dependency_ready"},
        )
        return next_stage
