from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from temporalio import activity
from temporalio.exceptions import ApplicationError

from ...config import config_path_for_workspace, load_yaml
from ...models import Budget, ProviderResult, Status, WorkItem
from ...providers import ProcessSupervisor
from ...registry import AgentRegistry
from ...reviewers import ReviewerRouter, ReviewSubject
from ...runtime import AgentRuntime, ExecutionMode
from ...storage import SQLiteStorage
from ...workflow_contracts import PASSING_VERDICTS, StageContractError, parse_stage_verdict, validate_workflow
from .models import ActivityResult, AgentFactoryJobInput, DemoWorkflowInput, StageActivityInput
from .policies import classify_error
from .settings import TemporalSettings

LOGGER = logging.getLogger(__name__)
MARKER_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


class AgentFactoryActivities:
    """Temporal activity adapters over the existing AgentFactory services."""

    def __init__(self, settings: TemporalSettings | None = None):
        self.settings = settings or TemporalSettings.from_env()

    @staticmethod
    def _storage(job: AgentFactoryJobInput) -> SQLiteStorage:
        return SQLiteStorage(Path(job.database).expanduser().resolve())

    @staticmethod
    def _correlation(job: AgentFactoryJobInput, activity_name: str) -> str:
        info = activity.info()
        return (
            f"[job={job.job_id}] [project={job.project_id}] "
            f"[workflow={info.workflow_id}] [task={job.task_id}] "
            f"[activity={activity_name}] [attempt={info.attempt}]"
        )

    @activity.defn(name="validate_agentfactory_job")
    async def validate_job(self, job: AgentFactoryJobInput) -> ActivityResult:
        workspace = Path(job.workspace).expanduser().resolve()
        if not workspace.is_dir():
            raise ApplicationError(
                f"Workspace does not exist: {workspace}",
                type="CONFIGURATION",
                non_retryable=True,
            )
        storage = self._storage(job)
        try:
            task = storage.get_task(job.task_id)
            run = storage.db.execute(
                "SELECT * FROM workflow_runs WHERE id=?", (job.run_id,)
            ).fetchone()
            if not run:
                raise ApplicationError(
                    f"Unknown AgentFactory run {job.run_id}",
                    type="CONFIGURATION",
                    non_retryable=True,
                )
            if (
                task.project_id != job.project_id
                or int(run["project_id"]) != job.project_id
                or int(run["task_id"]) != job.task_id
            ):
                raise ApplicationError(
                    "Temporal job scope does not match the persisted run",
                    type="CONFIGURATION",
                    non_retryable=True,
                )
            storage.event(
                "workflow.temporal.validated",
                "run",
                job.run_id,
                {"job_id": job.job_id, "task_id": job.task_id},
            )
            return ActivityResult(True, summary="Persisted job and workspace validated")
        finally:
            storage.close()

    @activity.defn(name="load_agentfactory_context")
    async def load_project_context(self, job: AgentFactoryJobInput) -> dict[str, Any]:
        workspace = Path(job.workspace).expanduser().resolve()
        storage = self._storage(job)
        try:
            task = storage.get_task(job.task_id)
            document = load_yaml(config_path_for_workspace("workflows", workspace))
            definition = next(
                (
                    item
                    for item in document.get("workflows", [])
                    if item.get("id") == job.workflow_definition_id
                ),
                None,
            )
            if definition is None:
                raise ApplicationError(
                    f"Unknown workflow definition: {job.workflow_definition_id}",
                    type="CONFIGURATION",
                    non_retryable=True,
                )
            stages = [dict(stage) for stage in validate_workflow(definition)]
            registry = AgentRegistry(workspace=workspace)
            for stage in stages:
                agent = registry.get(str(stage["agent"]))
                stage["provider"] = agent.provider
            return {
                "task": {
                    "id": task.id,
                    "title": task.title,
                    "description": task.description,
                    "acceptance_criteria": list(task.acceptance_criteria),
                },
                "workflow_id": str(definition["id"]),
                "stages": stages,
            }
        except (KeyError, ValueError, TypeError) as exc:
            raise ApplicationError(
                str(exc), type="CONFIGURATION", non_retryable=True
            ) from exc
        finally:
            storage.close()

    @staticmethod
    def _artifact_result(storage: SQLiteStorage, mutation: Any) -> ActivityResult | None:
        if mutation["status"] != "completed" or not mutation["result_json"]:
            return None
        value = json.loads(str(mutation["result_json"]))
        return ActivityResult.from_dict(value)

    @staticmethod
    def _stage_label(request: StageActivityInput) -> str:
        stage_id = str(request.stage["id"])
        return (
            stage_id
            if request.repair_iteration == 0
            else f"{stage_id}:repair:{request.repair_iteration}"
        )

    def _stage_agent(
        self,
        storage: SQLiteStorage,
        registry: AgentRegistry,
        request: StageActivityInput,
    ):
        stage = request.stage
        reviewer_pool = stage.get("reviewer_pool")
        if not reviewer_pool:
            return registry.get(str(stage["agent"]))
        subjects: list[ReviewSubject] = []
        for reviewed_stage in stage.get("review_of", []):
            row = storage.db.execute(
                """SELECT * FROM artifacts
                     WHERE run_id=? AND stage=? ORDER BY id DESC LIMIT 1""",
                (request.job.run_id, reviewed_stage),
            ).fetchone()
            if not row:
                raise ApplicationError(
                    f"Stage {stage['id']} is missing reviewed artifact {reviewed_stage}",
                    type="INTERNAL",
                )
            subjects.append(
                ReviewSubject(
                    stage=str(reviewed_stage),
                    artifact_id=int(row["id"]),
                    producer=registry.get(str(row["agent_id"])),
                )
            )
        placeholder = registry.get(str(stage["agent"]))
        return ReviewerRouter(storage, registry).select(
            run_id=request.job.run_id,
            stage=self._stage_label(request),
            candidate_ids=list(reviewer_pool),
            subjects=subjects,
            required_role=placeholder.role,
        )

    @staticmethod
    def _stage_context(storage: SQLiteStorage, job: AgentFactoryJobInput) -> dict[str, Any]:
        task = storage.get_task(job.task_id)
        context: dict[str, Any] = {
            "work_item": json.dumps(task.to_dict(), sort_keys=True, default=str)
        }
        for row in storage.db.execute(
            "SELECT stage,content FROM artifacts WHERE run_id=? ORDER BY id", (job.run_id,)
        ):
            context[str(row["stage"])] = str(row["content"])
        return context

    async def _run_agent_with_heartbeat(
        self,
        runtime: AgentRuntime,
        agent: Any,
        item: WorkItem,
        context: dict[str, Any],
        mode: str,
        job: AgentFactoryJobInput,
        stage_label: str,
    ) -> ProviderResult:
        cancel_event = threading.Event()
        execution = asyncio.create_task(
            asyncio.to_thread(
                runtime.run,
                agent,
                item,
                context,
                None,
                mode=ExecutionMode(mode),
                cancel_event=cancel_event,
            )
        )
        try:
            while not execution.done():
                activity.heartbeat(
                    {
                        "job_id": job.job_id,
                        "run_id": job.run_id,
                        "task_id": job.task_id,
                        "stage": stage_label,
                        "progress": "agent process running",
                    }
                )
                done, _ = await asyncio.wait(
                    {execution}, timeout=self.settings.heartbeat_interval_seconds
                )
                if done:
                    break
            return await execution
        except asyncio.CancelledError:
            cancel_event.set()
            try:
                await asyncio.wait_for(
                    asyncio.shield(execution),
                    timeout=self.settings.cancellation_grace_seconds,
                )
            except Exception:  # noqa: BLE001 - cleanup remains bounded
                pass
            raise

    @activity.defn(name="execute_agentfactory_stage")
    async def execute_stage(self, request: StageActivityInput) -> ActivityResult:
        job = request.job
        stage = request.stage
        stage_label = self._stage_label(request)
        key = f"temporal:{job.job_id}:{stage_label}"
        storage = self._storage(job)
        LOGGER.info("%s stage started", self._correlation(job, "execute_stage"))
        try:
            mutation, _created = storage.reserve_workflow_mutation(
                run_id=job.run_id,
                stage_key="workflow",
                operation="provider_call",
                idempotency_key=key,
                request={
                    "stage": stage_label,
                    "agent": stage["agent"],
                    "mode": job.mode,
                    "repair_iteration": request.repair_iteration,
                },
            )
            if completed := self._artifact_result(storage, mutation):
                return completed

            existing = storage.db.execute(
                """SELECT id,content,provider FROM artifacts
                     WHERE run_id=? AND stage=? ORDER BY id DESC LIMIT 1""",
                (job.run_id, stage_label),
            ).fetchone()
            if existing:
                result = ActivityResult(
                    True,
                    summary="Recovered already-persisted stage artifact",
                    artifacts=[f"artifact:{int(existing['id'])}"],
                    metadata={"provider": existing["provider"], "recovered": True},
                )
                storage.complete_workflow_mutation(int(mutation["id"]), result.to_dict())
                return result

            workspace = Path(job.workspace).expanduser().resolve()
            registry = AgentRegistry(workspace=workspace)
            runtime = AgentRuntime(workspace=workspace)
            agent = self._stage_agent(storage, registry, request)
            task = storage.get_task(job.task_id)
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
                    "repair_iteration": request.repair_iteration,
                    "failure_summary": request.failure_summary,
                },
                expected_outputs=[str(stage["artifact"])],
                acceptance_criteria=list(stage.get("acceptance_criteria", [])),
                permissions=list(agent.permissions),
                budget=Budget(**stage.get("budget", {})),
                status=Status.RUNNING,
            )
            provider_result = await self._run_agent_with_heartbeat(
                runtime,
                agent,
                child,
                self._stage_context(storage, job),
                job.mode,
                job,
                stage_label,
            )
            if not provider_result.ok:
                message = provider_result.error or "Agent provider failed"
                failure_class, retryable = classify_error(
                    message, provider_result.metadata
                )
                if failure_class == "CANCELLED" or provider_result.metadata.get("cancelled"):
                    raise asyncio.CancelledError
                raise ApplicationError(
                    message[:4000],
                    type=failure_class,
                    non_retryable=not retryable,
                )

            passed = True
            failure_class: str | None = None
            summary = ""
            verdict = ""
            try:
                parsed = parse_stage_verdict(stage, provider_result)
                verdict = parsed.verdict
                summary = parsed.summary or f"Stage {stage['id']} passed"
            except StageContractError as exc:
                message = str(exc)
                passed = False
                summary = message
                failure_class = (
                    "TEST_FAILURE"
                    if any(token in message.casefold() for token in ("fail", "blocked", "not_aligned"))
                    else "AGENT_ERROR"
                )
                try:
                    payload = json.loads(provider_result.content)
                    verdict = str(payload.get("verdict", "")).upper()
                    if verdict in PASSING_VERDICTS:
                        failure_class = "AGENT_ERROR"
                except (json.JSONDecodeError, AttributeError):
                    pass

            artifact_id = storage.add_artifact(
                job.run_id,
                stage_label,
                agent.id,
                provider_result.provider,
                f"[execution_mode={job.mode}]\n{provider_result.content}",
            )
            result = ActivityResult(
                True,
                passed=passed,
                exit_code=provider_result.metadata.get("returncode"),
                summary=summary[:2000],
                stdout_ref=f"artifact:{artifact_id}",
                artifacts=[f"artifact:{artifact_id}"],
                metadata={
                    "agent": agent.id,
                    "provider": provider_result.provider,
                    "verdict": verdict,
                    "stage": stage_label,
                },
                failure_class=failure_class,
            )
            storage.complete_workflow_mutation(int(mutation["id"]), result.to_dict())
            return result
        except asyncio.CancelledError:
            row = storage.db.execute(
                "SELECT status FROM workflow_runs WHERE id=?", (job.run_id,)
            ).fetchone()
            if row and row["status"] in {"running", "awaiting_approval"}:
                storage.finish_run(
                    job.run_id,
                    "failed",
                    event_payload={"cancelled": True, "stage": stage_label},
                )
            raise
        finally:
            storage.close()

    @activity.defn(name="finalize_agentfactory_job")
    async def finalize_job(self, job: AgentFactoryJobInput) -> ActivityResult:
        storage = self._storage(job)
        try:
            gate = storage.db.execute(
                "SELECT id FROM approval_gates WHERE run_id=?", (job.run_id,)
            ).fetchone()
            gate_id = int(gate["id"]) if gate else storage.create_approval_gate(job.run_id)
            return ActivityResult(
                True,
                summary="Workflow evidence is waiting for Founder approval",
                artifacts=[f"approval:{gate_id}"],
                metadata={"approval_gate_id": gate_id},
            )
        finally:
            storage.close()

    @activity.defn(name="fail_agentfactory_job")
    async def fail_job(self, payload: dict[str, Any]) -> ActivityResult:
        job = AgentFactoryJobInput(**payload["job"])
        storage = self._storage(job)
        try:
            row = storage.db.execute(
                "SELECT status FROM workflow_runs WHERE id=?", (job.run_id,)
            ).fetchone()
            if row and row["status"] in {"running", "awaiting_approval"}:
                storage.finish_run(
                    job.run_id,
                    "failed",
                    event_payload={
                        "failure_class": payload.get("failure_class", "INTERNAL"),
                        "summary": str(payload.get("summary", ""))[:2000],
                    },
                )
            return ActivityResult(True, summary="Failure persisted")
        finally:
            storage.close()

    @activity.defn(name="inspect_demo_workspace")
    async def inspect_demo_workspace(self, request: DemoWorkflowInput) -> ActivityResult:
        workspace = Path(request.workspace).expanduser().resolve()
        if not workspace.is_dir():
            raise ApplicationError(
                "Demo workspace is unavailable", type="CONFIGURATION", non_retryable=True
            )
        return ActivityResult(True, summary=f"Workspace inspected: {workspace.name}")

    @activity.defn(name="write_demo_marker")
    async def write_demo_marker(self, request: DemoWorkflowInput) -> ActivityResult:
        if not MARKER_PATTERN.fullmatch(request.marker):
            raise ApplicationError(
                "Invalid demo marker", type="CONFIGURATION", non_retryable=True
            )
        destination = (
            Path(request.workspace).resolve()
            / ".agent-factory"
            / "temporal-demo"
            / f"{request.marker}.txt"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("AgentFactory Temporal demo\n", encoding="utf-8")
        return ActivityResult(
            True,
            summary="Idempotent demo marker written",
            artifacts=[str(destination)],
        )

    @staticmethod
    def _command(
        command: list[str], workspace: Path, cancel_event: threading.Event
    ) -> tuple[int, str, str]:
        supervisor = ProcessSupervisor()
        proc = supervisor.spawn(
            command,
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        while proc.poll() is None:
            if cancel_event.is_set():
                supervisor.cancel_tree(proc)
                break
            time.sleep(0.05)
        stdout, stderr = proc.communicate(timeout=5)
        return int(proc.returncode or 0), stdout[-20_000:], stderr[-20_000:]

    @activity.defn(name="run_demo_command")
    async def run_demo_command(self, request: DemoWorkflowInput) -> ActivityResult:
        info = activity.info()
        if info.attempt <= request.fail_attempts:
            raise ApplicationError(
                f"Controlled transient failure on attempt {info.attempt}",
                type="TRANSIENT",
            )
        if not request.command:
            raise ApplicationError(
                "Demo command is empty", type="CONFIGURATION", non_retryable=True
            )
        cancel_event = threading.Event()
        running = asyncio.create_task(
            asyncio.to_thread(
                self._command,
                list(request.command),
                Path(request.workspace).resolve(),
                cancel_event,
            )
        )
        try:
            while not running.done():
                activity.heartbeat({"marker": request.marker, "progress": "command running"})
                await asyncio.wait({running}, timeout=self.settings.heartbeat_interval_seconds)
            exit_code, stdout, stderr = await running
        except asyncio.CancelledError:
            cancel_event.set()
            try:
                await asyncio.wait_for(
                    asyncio.shield(running), self.settings.cancellation_grace_seconds
                )
            except Exception:  # noqa: BLE001
                pass
            raise
        return ActivityResult(
            True,
            passed=exit_code == 0,
            exit_code=exit_code,
            summary="Demo command completed" if exit_code == 0 else "Demo command failed",
            metadata={"stdout": stdout, "stderr": stderr},
            failure_class=None if exit_code == 0 else "BUILD_ERROR",
        )

    @activity.defn(name="validate_demo_result")
    async def validate_demo_result(self, request: DemoWorkflowInput) -> ActivityResult:
        marker = (
            Path(request.workspace).resolve()
            / ".agent-factory"
            / "temporal-demo"
            / f"{request.marker}.txt"
        )
        passed = marker.is_file() and marker.read_text(encoding="utf-8") == "AgentFactory Temporal demo\n"
        return ActivityResult(
            True,
            passed=passed,
            summary="Demo marker validated" if passed else "Demo marker validation failed",
            failure_class=None if passed else "TEST_FAILURE",
        )
