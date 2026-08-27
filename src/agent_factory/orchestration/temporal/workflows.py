from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from .models import (
        ActivityResult,
        AgentFactoryJobInput,
        AutonomousApprovalRevalidationInput,
        AutonomousApprovalRevalidationResult,
        AutonomousBacklogApprovalNotice,
        AutonomousMissionActivityScope,
        AutonomousPlanningActivityInput,
        AutonomousPlanningActivityResult,
        AutonomousPlanningCommand,
        AutonomousMissionWorkflowInput,
        AutonomousMissionWorkflowState,
        DemoWorkflowInput,
        StageActivityInput,
        WorkflowState,
        WorkflowStatus,
    )
    from .policies import fast_transient_policy, llm_policy, policy_for_provider


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
        self._request: AutonomousMissionWorkflowInput | None = None
        self._planning_commands: list[AutonomousPlanningCommand] = []
        self._approval_notices: list[AutonomousBacklogApprovalNotice] = []
        self._seen_planning_commands: set[str] = set()
        self._seen_approval_notices: set[str] = set()

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
            "proposed_backlog_revision_id": state.proposed_backlog_revision_id,
            "proposal_verification_id": state.proposal_verification_id,
            "proposal_revision_count": state.proposal_revision_count,
            "active_execution_epoch_id": state.active_execution_epoch_id,
            "current_checkpoint_id": state.current_checkpoint_id,
            "current_work_item_stable_id": state.current_work_item_stable_id,
            "completed_items": state.completed_items,
            "total_items": state.total_items,
            "percent": percent,
            "last_activity": state.last_activity,
            "last_activity_at": state.last_activity_at,
        }

    @workflow.signal(name="request_autonomous_planning")
    async def request_autonomous_planning(
        self, command: AutonomousPlanningCommand
    ) -> None:
        if command.command_id in self._seen_planning_commands:
            return
        self._seen_planning_commands.add(command.command_id)
        self._planning_commands.append(command)

    @workflow.signal(name="autonomous_backlog_approved")
    async def autonomous_backlog_approved(
        self, notice: AutonomousBacklogApprovalNotice
    ) -> None:
        if notice.notice_id in self._seen_approval_notices:
            return
        self._seen_approval_notices.add(notice.notice_id)
        self._approval_notices.append(notice)

    def _activity_scope(self) -> AutonomousMissionActivityScope:
        request = self._request
        state = self._state()
        if request is None or state.temporal_first_run_id is None:
            raise RuntimeError("Autonomous Mission Workflow scope is unavailable")
        return AutonomousMissionActivityScope(
            mission_id=request.mission_id,
            mission_identity=request.mission_identity,
            mission_key=request.mission_key,
            project_id=request.project_id,
            workspace=request.workspace,
            database=request.database,
            temporal_workflow_id=state.temporal_workflow_id,
            temporal_first_run_id=state.temporal_first_run_id,
        )

    def _touch(self, summary: str) -> None:
        state = self._state()
        state.last_activity = summary[:512]
        state.last_activity_at = workflow.now().isoformat()

    async def _run_planning_activity(
        self, command: AutonomousPlanningCommand
    ) -> AutonomousPlanningActivityResult:
        request = self._request
        if request is None:
            raise RuntimeError("Autonomous Mission Workflow input is unavailable")
        return await workflow.execute_activity(
            "run_autonomous_planning",
            AutonomousPlanningActivityInput(
                scope=self._activity_scope(), command=command
            ),
            result_type=AutonomousPlanningActivityResult,
            start_to_close_timeout=timedelta(
                seconds=request.planning_activity_timeout_seconds
            ),
            heartbeat_timeout=timedelta(
                seconds=request.heartbeat_timeout_seconds
            ),
            retry_policy=llm_policy(),
        )

    async def _revalidate_approval_activity(
        self, notice: AutonomousBacklogApprovalNotice
    ) -> AutonomousApprovalRevalidationResult:
        request = self._request
        if request is None:
            raise RuntimeError("Autonomous Mission Workflow input is unavailable")
        return await workflow.execute_activity(
            "revalidate_autonomous_approval",
            AutonomousApprovalRevalidationInput(
                scope=self._activity_scope(), notice=notice
            ),
            result_type=AutonomousApprovalRevalidationResult,
            start_to_close_timeout=timedelta(
                seconds=request.fast_activity_timeout_seconds
            ),
            retry_policy=fast_transient_policy(),
        )

    def _apply_planning_result(
        self, result: AutonomousPlanningActivityResult
    ) -> None:
        state = self._state()
        state.mission_version = result.mission_version
        state.phase = result.phase
        state.disposition = result.disposition
        state.proposed_backlog_revision_id = result.proposed_revision_id
        state.proposed_backlog_revision_digest = result.proposed_revision_digest
        state.proposal_verification_id = result.verification_id
        state.proposal_pipeline_run_id = result.pipeline_run_id
        state.proposal_revision_count = result.proposal_revision_count
        state.workflow_status = (
            WorkflowStatus.WAITING.value
            if result.ready_for_approval
            else WorkflowStatus.NEEDS_ATTENTION.value
        )
        self._touch(result.summary)

    def _apply_approval_result(
        self, result: AutonomousApprovalRevalidationResult
    ) -> None:
        state = self._state()
        state.mission_version = result.mission_version
        state.phase = result.phase
        state.disposition = result.disposition
        if result.approved:
            state.active_backlog_revision_id = result.revision_id
            state.active_backlog_revision_digest = result.revision_digest
            state.active_execution_epoch_id = result.execution_epoch_id
            state.workflow_status = WorkflowStatus.WAITING.value
        else:
            state.workflow_status = WorkflowStatus.WAITING.value
        self._touch(result.reason)

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
        self._request = request
        self.state = AutonomousMissionWorkflowState.from_input(
            request,
            workflow_id=info.workflow_id,
            run_id=info.run_id,
            started_at=workflow.now().isoformat(),
        )
        self.state.workflow_status = WorkflowStatus.WAITING.value
        self._touch("Waiting for explicit bounded planning or persisted approval")
        while True:
            if self.state.phase == "APPROVED":
                # AF-AMM-014 begins environment discovery. AF-AMM-013 must stop
                # here so approval can never fall through into execution.
                await workflow.wait_condition(lambda: False)
            await workflow.wait_condition(
                lambda: bool(self._planning_commands or self._approval_notices)
            )
            if self._planning_commands:
                command = self._planning_commands.pop(0)
                self.state.workflow_status = WorkflowStatus.RUNNING.value
                self._touch(
                    f"Executing bounded planning command {command.command_id}"
                )
                try:
                    result = await self._run_planning_activity(command)
                except ActivityError as exc:
                    self.state.workflow_status = WorkflowStatus.NEEDS_ATTENTION.value
                    self._touch(
                        "Planning command was rejected or failed: " + str(exc)
                    )
                else:
                    self._apply_planning_result(result)
                continue

            notice = self._approval_notices.pop(0)
            self.state.workflow_status = WorkflowStatus.RUNNING.value
            self._touch("Revalidating persisted backlog approval authority")
            try:
                approval = await self._revalidate_approval_activity(notice)
            except ActivityError as exc:
                self.state.workflow_status = WorkflowStatus.NEEDS_ATTENTION.value
                self._touch("Approval revalidation failed: " + str(exc))
            else:
                self._apply_approval_result(approval)


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
