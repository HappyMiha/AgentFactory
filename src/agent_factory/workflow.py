"""Deterministic, review-gated workflow orchestration."""

from __future__ import annotations

import json

from .config import config_path_for_workspace, load_yaml
from .models import Budget, Status, WorkItem
from .registry import AgentRegistry
from .reviewers import ReviewerRouter, ReviewSubject
from .runtime import AgentRuntime, ExecutionMode
from .storage import SQLiteStorage
from .token_failover import (
    configured_coding_chain,
    exhausted_providers_for_run,
    record_exhausted_providers,
)
from .workflow_contracts import parse_stage_verdict, validate_workflow


class WorkflowEngine:
    def __init__(
        self,
        storage: SQLiteStorage,
        registry: AgentRegistry | None = None,
        runtime: AgentRuntime | None = None,
    ):
        self.storage = storage
        self.registry = registry or AgentRegistry()
        self.runtime = runtime or AgentRuntime()
        self.reviewers = ReviewerRouter(storage, self.registry)

    def workflow(self, workflow_id: str) -> dict:
        document = load_yaml(
            config_path_for_workspace("workflows", self.runtime.workspace)
        )
        workflow = next(
            (entry for entry in document.get("workflows", []) if entry.get("id") == workflow_id),
            None,
        )
        if workflow is None:
            raise KeyError(f"Unknown workflow: {workflow_id}")
        validate_workflow(workflow)
        return workflow

    def run(
        self,
        workflow_id: str,
        task: WorkItem,
        mode: ExecutionMode | str = ExecutionMode.SIMULATION,
    ) -> int:
        mode = ExecutionMode(mode)
        workflow = self.workflow(workflow_id)
        stages = validate_workflow(workflow)
        run_id = self.storage.start_run(task.project_id, task.id, workflow_id)
        self.storage.event(
            "workflow.mode.selected",
            "run",
            run_id,
            {
                "mode": mode.value,
                "fallback_allowed": mode is ExecutionMode.SIMULATION,
            },
        )
        context: dict[str, str] = {
            "work_item": json.dumps(task.to_dict(), sort_keys=True, default=str)
        }
        completed: set[str] = set()
        produced: dict[str, ReviewSubject] = {}
        try:
            for stage in stages:
                missing = set(stage.get("depends_on", [])) - completed
                if missing:
                    raise RuntimeError(
                        f"Stage {stage['id']} is missing dependencies: {sorted(missing)}"
                    )
                reviewer_pool = stage.get("reviewer_pool")
                if reviewer_pool:
                    reviewed_stages = stage.get("review_of", [])
                    if isinstance(reviewed_stages, str):
                        reviewed_stages = [reviewed_stages]
                    subjects = [produced[stage_id] for stage_id in reviewed_stages]
                    placeholder = self.registry.get(stage["agent"])
                    agent = self.reviewers.select(
                        run_id=run_id,
                        stage=stage["id"],
                        candidate_ids=list(reviewer_pool),
                        subjects=subjects,
                        required_role=placeholder.role,
                        excluded_provider_ids=exhausted_providers_for_run(
                            self.storage, run_id
                        ),
                    )
                    context[f"{stage['id']}:review_assignment"] = json.dumps(
                        {
                            "reviewer": {
                                "agent_id": agent.id,
                                "provider": agent.provider,
                                "model": agent.model_identity,
                            },
                            "subjects": [
                                {
                                    "stage": subject.stage,
                                    "artifact_id": subject.artifact_id,
                                    "producer": subject.producer.id,
                                    "provider": subject.producer.provider,
                                    "model": subject.producer.model_identity,
                                }
                                for subject in subjects
                            ],
                        },
                        sort_keys=True,
                    )
                else:
                    agent = self.registry.get(stage["agent"])
                coding_chain = (
                    configured_coding_chain(stage, self.registry.list())
                    if stage.get("token_exhaustion_fallback_agents")
                    else (agent,)
                )
                exhausted_providers = exhausted_providers_for_run(
                    self.storage, run_id
                )
                available_chain = tuple(
                    candidate
                    for candidate in coding_chain
                    if candidate.provider.casefold() not in exhausted_providers
                )
                if not available_chain:
                    raise RuntimeError(
                        f"No coding worker with token capacity remains for stage {stage['id']}"
                    )
                agent = available_chain[0]
                fallback_agents = available_chain[1:]
                if not agent.enabled:
                    raise RuntimeError(f"Required agent is disabled: {agent.id}")
                child = WorkItem(
                    id=task.id,
                    title=f"{task.title}: {stage['name']}",
                    description=task.description,
                    project_id=task.project_id,
                    inputs={
                        **task.inputs,
                        "stage": stage["id"],
                        "stage_contract": stage["contract"],
                        "artifact_name": stage["artifact"],
                    },
                    expected_outputs=[stage["artifact"]],
                    acceptance_criteria=stage.get("acceptance_criteria", []),
                    permissions=agent.permissions,
                    budget=Budget(**stage.get("budget", {})),
                    status=Status.RUNNING,
                )
                result = self.runtime.run(
                    agent,
                    child,
                    context,
                    mode=mode,
                    token_exhaustion_fallback_agents=fallback_agents,
                )
                record_exhausted_providers(
                    self.storage,
                    run_id=run_id,
                    stage_id=stage["id"],
                    exhausted=result.metadata.get("token_exhausted_providers", []),
                )
                if not result.ok:
                    raise RuntimeError(result.error or f"Provider failed at stage {stage['id']}")
                selected_agent_id = str(
                    result.metadata.get("selected_agent_id", agent.id)
                )
                agent = self.registry.get(selected_agent_id)
                verdict = parse_stage_verdict(stage, result)
                labeled_content = f"[execution_mode={mode.value}]\n{result.content}"
                artifact_id = self.storage.add_artifact(
                    run_id,
                    stage["id"],
                    agent.id,
                    result.provider,
                    labeled_content,
                )
                produced[stage["id"]] = ReviewSubject(
                    stage=stage["id"], artifact_id=artifact_id, producer=agent
                )
                if reviewer_pool:
                    self.storage.complete_reviewer_assignment(
                        run_id=run_id,
                        stage=stage["id"],
                        review_artifact_id=artifact_id,
                        verdict=verdict.verdict,
                    )
                context[stage["id"]] = result.content
                context[f"{stage['id']}:verdict"] = verdict.verdict
                completed.add(stage["id"])
            self.storage.create_approval_gate(run_id)
        except Exception as exc:
            self.storage.finish_run(run_id, "failed", event_payload={"error": str(exc)})
            raise
        return run_id
