from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from .models import (
        ActivityResult,
        AgentFactoryJobInput,
        AutonomousMissionWorkflowInput,
        AutonomousMissionWorkflowState,
        DemoWorkflowInput,
        StageActivityInput,
        WorkflowState,
        WorkflowStatus,
    )
    from .policies import fast_transient_policy, policy_for_provider


@workflow.defn(name="AgentFactoryJobWorkflow")
class AgentFactoryJobWorkflow:
    """Deterministic orchestration for one existing AgentFactory workflow run."""

    def __init__(self) -> None:
        self.state = WorkflowState()
        self._paused = False
        self._cancel_requested = False
        self._active_activity: Any = None

    @workflow.query(name="get_status")
    def get_status(self) -> dict[str, Any]:
        return self.state.to_dict()

    @workflow.query(name="get_progress")
    def get_progress(self) -> dict[str, Any]:
        return {
            "completed": self.state.completed_tasks,
            "total": self.state.total_tasks,
            "phase": self.state.phase,
            "last_progress": self.state.last_progress,
            "repair_iteration": self.state.repair_iteration,
        }

    @workflow.query(name="get_current_task")
    def get_current_task(self) -> dict[str, Any]:
        return {
            "task_id": self.state.current_task_id,
            "agent": self.state.current_agent,
            "attempt": self.state.attempt,
        }

    @workflow.signal(name="pause")
    async def pause(self) -> None:
        self._paused = True
        self.state.status = WorkflowStatus.PAUSED
        self.state.last_progress = "Pause requested; no new activity will start"

    @workflow.signal(name="resume")
    async def resume(self) -> None:
        self._paused = False
        if not self._cancel_requested:
            self.state.status = WorkflowStatus.RUNNING
            self.state.last_progress = "Workflow resumed"

    @workflow.signal(name="cancel")
    async def cancel(self) -> None:
        self._cancel_requested = True
        self.state.status = WorkflowStatus.CANCELLING
        self.state.last_progress = "Cancellation requested"
        if self._active_activity is not None:
            self._active_activity.cancel()

    async def _wait_until_runnable(self) -> None:
        if self._cancel_requested:
            raise asyncio.CancelledError
        if self._paused:
            await workflow.wait_condition(
                lambda: not self._paused or self._cancel_requested
            )
        if self._cancel_requested:
            raise asyncio.CancelledError
        self.state.status = WorkflowStatus.RUNNING

    async def _fast_activity(
        self,
        name: str,
        argument: Any,
        job: AgentFactoryJobInput,
        *,
        result_type: type = ActivityResult,
    ) -> Any:
        await self._wait_until_runnable()
        self._active_activity = workflow.start_activity(
            name,
            argument,
            result_type=result_type,
            start_to_close_timeout=timedelta(
                seconds=job.fast_activity_timeout_seconds
            ),
            retry_policy=fast_transient_policy(),
        )
        try:
            return await self._active_activity
        finally:
            self._active_activity = None

    async def _stage_activity(
        self, request: StageActivityInput
    ) -> ActivityResult:
        await self._wait_until_runnable()
        job = request.job
        self._active_activity = workflow.start_activity(
            "execute_agentfactory_stage",
            request,
            result_type=ActivityResult,
            start_to_close_timeout=timedelta(
                seconds=job.llm_activity_timeout_seconds
            ),
            heartbeat_timeout=timedelta(seconds=job.heartbeat_timeout_seconds),
            retry_policy=policy_for_provider(str(request.stage.get("provider", ""))),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        try:
            return await self._active_activity
        finally:
            self._active_activity = None

    async def _persist_failure(
        self, job: AgentFactoryJobInput, summary: str, failure_class: str
    ) -> None:
        try:
            await workflow.execute_activity(
                "fail_agentfactory_job",
                {
                    "job": {
                        "job_id": job.job_id,
                        "run_id": job.run_id,
                        "project_id": job.project_id,
                        "task_id": job.task_id,
                        "workspace": job.workspace,
                        "database": job.database,
                        "workflow_definition_id": job.workflow_definition_id,
                        "mode": job.mode,
                        "fast_activity_timeout_seconds": job.fast_activity_timeout_seconds,
                        "llm_activity_timeout_seconds": job.llm_activity_timeout_seconds,
                        "heartbeat_timeout_seconds": job.heartbeat_timeout_seconds,
                        "max_repair_iterations": job.max_repair_iterations,
                    },
                    "summary": summary,
                    "failure_class": failure_class,
                },
                result_type=ActivityResult,
                start_to_close_timeout=timedelta(
                    seconds=job.fast_activity_timeout_seconds
                ),
                retry_policy=fast_transient_policy(),
            )
        except Exception:  # noqa: BLE001 - preserve the original workflow failure
            workflow.logger.exception("Could not persist AgentFactory failure state")

    @workflow.run
    async def run(self, job: AgentFactoryJobInput) -> dict[str, Any]:
        info = workflow.info()
        self.state = WorkflowState(
            job_id=job.job_id,
            run_id=job.run_id,
            project_id=job.project_id,
            task_id=job.task_id,
            temporal_workflow_id=info.workflow_id,
            started_at=workflow.now().isoformat(),
        )
        try:
            self.state.phase = "validation"
            self.state.last_progress = "Validating persisted AgentFactory job"
            await self._fast_activity("validate_agentfactory_job", job, job)

            self.state.phase = "planning"
            self.state.last_progress = "Loading reviewed workflow and project context"
            context = await self._fast_activity(
                "load_agentfactory_context", job, job, result_type=dict
            )
            stages = list(context["stages"])
            self.state.total_tasks = len(stages)

            for ordinal, stage in enumerate(stages, start=1):
                repair_iteration = 0
                failure_summary = ""
                while True:
                    self.state.phase = "development"
                    self.state.current_task_id = str(stage["id"])
                    self.state.current_agent = str(stage["agent"])
                    self.state.repair_iteration = repair_iteration
                    self.state.last_progress = (
                        f"Running {stage['name']}"
                        if repair_iteration == 0
                        else f"Repairing {stage['name']} (iteration {repair_iteration})"
                    )
                    result = await self._stage_activity(
                        StageActivityInput(
                            job=job,
                            stage=stage,
                            ordinal=ordinal,
                            repair_iteration=repair_iteration,
                            failure_summary=failure_summary,
                        )
                    )
                    if result.passed:
                        self.state.completed_tasks = ordinal
                        self.state.last_progress = result.summary
                        break

                    failure_summary = result.summary
                    repair_iteration += 1
                    self.state.repair_iteration = repair_iteration
                    if repair_iteration > job.max_repair_iterations:
                        self.state.status = WorkflowStatus.NEEDS_ATTENTION
                        self.state.phase = "failed"
                        self.state.last_progress = (
                            "Maximum repair iterations exceeded: " + failure_summary
                        )
                        await self._persist_failure(
                            job,
                            self.state.last_progress,
                            result.failure_class or "INTERNAL",
                        )
                        return self.state.to_dict()
                    self.state.status = WorkflowStatus.RETRYING
                    self.state.phase = "repair"

            self.state.phase = "final_validation"
            self.state.current_task_id = None
            self.state.current_agent = None
            self.state.last_progress = "Persisting final evidence and approval gate"
            final = await self._fast_activity("finalize_agentfactory_job", job, job)
            self.state.status = WorkflowStatus.WAITING
            self.state.phase = "awaiting_approval"
            self.state.last_progress = final.summary
            return self.state.to_dict()
        except asyncio.CancelledError:
            self.state.status = WorkflowStatus.CANCELLED
            self.state.phase = "cancelled"
            self.state.last_progress = "Workflow and active activity cancelled"
            await self._persist_failure(job, self.state.last_progress, "CANCELLED")
            raise
        except Exception as exc:
            self.state.status = WorkflowStatus.FAILED
            self.state.phase = "failed"
            self.state.last_progress = f"{type(exc).__name__}: {exc}"
            await self._persist_failure(job, self.state.last_progress, "INTERNAL")
            raise


@workflow.defn(name="AutonomousMissionWorkflow")
class AutonomousMissionWorkflow:
    """Long-lived identifier-only parent for one Autonomous Mission."""

    def __init__(self) -> None:
        self.state: AutonomousMissionWorkflowState | None = None

    def _state(self) -> AutonomousMissionWorkflowState:
        if self.state is None:
            raise RuntimeError("Autonomous Mission Workflow has not initialized")
        return self.state

    @workflow.query(name="get_mission_status")
    def get_mission_status(self) -> dict[str, Any]:
        return self._state().to_dict()

    @workflow.query(name="get_mission_progress")
    def get_mission_progress(self) -> dict[str, Any]:
        state = self._state()
        percent = (
            round((state.completed_items / state.total_items) * 100, 2)
            if state.total_items
            else 0.0
        )
        return {
            "mission_id": state.mission_id,
            "mission_version": state.mission_version,
            "active_backlog_revision_id": state.active_backlog_revision_id,
            "active_execution_epoch_id": state.active_execution_epoch_id,
            "current_checkpoint_id": state.current_checkpoint_id,
            "current_work_item_stable_id": state.current_work_item_stable_id,
            "completed_items": state.completed_items,
            "total_items": state.total_items,
            "percent": percent,
            "last_activity": state.last_activity,
            "last_activity_at": state.last_activity_at,
        }

    @workflow.query(name="get_current_role")
    def get_current_role(self) -> dict[str, Any]:
        state = self._state()
        return {
            "mission_id": state.mission_id,
            "current_work_item_stable_id": state.current_work_item_stable_id,
            "role": state.current_role,
            "model": state.current_model,
        }

    @workflow.query(name="get_environment_status")
    def get_environment_status(self) -> dict[str, Any]:
        state = self._state()
        return {
            "mission_id": state.mission_id,
            "phase": state.phase,
            "disposition": state.disposition,
            "environment_status": state.environment_status,
            "active_execution_epoch_id": state.active_execution_epoch_id,
            "current_checkpoint_id": state.current_checkpoint_id,
            "last_activity": state.last_activity,
            "last_activity_at": state.last_activity_at,
        }

    @workflow.run
    async def run(
        self, request: AutonomousMissionWorkflowInput
    ) -> dict[str, Any]:
        info = workflow.info()
        self.state = AutonomousMissionWorkflowState.from_input(
            request,
            workflow_id=info.workflow_id,
            run_id=info.run_id,
            started_at=workflow.now().isoformat(),
        )
        # AF-AMM-013 adds domain hydration and AF-AMM-014 adds child scheduling.
        # This parent deliberately waits without polling or loading domain payloads.
        await workflow.wait_condition(lambda: False)
        return self.state.to_dict()


@workflow.defn(name="TemporalDemoWorkflow")
class TemporalDemoWorkflow:
    def __init__(self) -> None:
        self._continue_requested = False
        self._phase = "starting"

    @workflow.query(name="demo_phase")
    def demo_phase(self) -> str:
        return self._phase

    @workflow.signal(name="continue_demo")
    async def continue_demo(self) -> None:
        self._continue_requested = True

    @workflow.run
    async def run(self, request: DemoWorkflowInput) -> dict[str, Any]:
        timeout = timedelta(seconds=request.activity_timeout_seconds)
        heartbeat = timedelta(seconds=request.heartbeat_timeout_seconds)
        await workflow.execute_activity(
            "inspect_demo_workspace",
            request,
            result_type=ActivityResult,
            start_to_close_timeout=timeout,
            retry_policy=fast_transient_policy(),
        )
        marker = await workflow.execute_activity(
            "write_demo_marker",
            request,
            result_type=ActivityResult,
            start_to_close_timeout=timeout,
            retry_policy=fast_transient_policy(),
        )
        if request.wait_before_command:
            self._phase = "waiting_before_command"
            await workflow.wait_condition(lambda: self._continue_requested)
        self._phase = "running_command"
        command = await workflow.execute_activity(
            "run_demo_command",
            request,
            result_type=ActivityResult,
            start_to_close_timeout=timeout,
            heartbeat_timeout=heartbeat,
            retry_policy=fast_transient_policy(),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        if not command.passed:
            return {
                "status": "repair_required",
                "failure_class": command.failure_class,
                "summary": command.summary,
            }
        validation = await workflow.execute_activity(
            "validate_demo_result",
            request,
            result_type=ActivityResult,
            start_to_close_timeout=timeout,
            retry_policy=fast_transient_policy(),
        )
        self._phase = "completed"
        return {
            "status": "completed" if validation.passed else "repair_required",
            "marker": marker.artifacts[0] if marker.artifacts else None,
            "summary": validation.summary,
        }
