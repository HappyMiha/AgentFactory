from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .storage import SQLiteStorage
from .workflow_contracts import validate_workflow


@dataclass(frozen=True)
class MutationReservation:
    id: int
    status: str
    result: dict[str, Any] | None
    execute: bool


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
        operation: str,
        idempotency_key: str,
        request: dict[str, Any],
    ) -> MutationReservation:
        row, created = self.storage.reserve_workflow_mutation(
            run_id=run_id,
            stage_key=stage_key,
            operation=operation,
            idempotency_key=idempotency_key,
            request=request,
        )
        result = json.loads(row["result_json"]) if row["result_json"] else None
        return MutationReservation(
            id=int(row["id"]),
            status=str(row["status"]),
            result=result,
            execute=created,
        )

    def complete_mutation(self, mutation_id: int, result: dict[str, Any]) -> None:
        self.storage.complete_workflow_mutation(mutation_id, result)
