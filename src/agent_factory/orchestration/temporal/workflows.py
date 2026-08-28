from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.exceptions import ActivityError, ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    from .models import (
        ActivityResult,
        AgentFactoryJobInput,
        AutonomousApprovalRevalidationInput,
        AutonomousApprovalRevalidationResult,
        AutonomousBacklogApprovalNotice,
        AutonomousChildPreparationInput,
        AutonomousChildPreparationResult,
        AutonomousChildControlNotice,
        AutonomousChildReconciliationInput,
        AutonomousChildReconciliationResult,
        AutonomousExecutionPreparationInput,
        AutonomousExecutionPreparationResult,
        AutonomousEpochHandoffCommand,
        AutonomousEpochHandoffCompletionInput,
        AutonomousEpochHandoffCompletionResult,
        AutonomousEpochHandoffPreparationInput,
        AutonomousEpochHandoffPreparationResult,
        AutonomousChildEpochHandoffNotice,
        AutonomousMissionActivityScope,
        AutonomousMissionControlActivityInput,
        AutonomousMissionControlCommand,
        AutonomousMissionControlResult,
        AutonomousMissionControlSnapshotInput,
        AutonomousMissionControlSnapshotResult,
        AutonomousMissionCompletionInput,
        AutonomousMissionCompletionResult,
        AutonomousPlanningActivityInput,
        AutonomousPlanningActivityResult,
        AutonomousPlanningCommand,
        AutonomousMissionWorkflowInput,
        AutonomousMissionWorkflowState,
        AutonomousRetrySettlementInput,
        AutonomousRetrySettlementResult,
        DemoWorkflowInput,
        StageActivityInput,
        WorkflowState,
        WorkflowStatus,
    )
    from .policies import fast_transient_policy, llm_policy, policy_for_provider


class _AutonomousRetryRequested(Exception):
    """Internal deterministic child safe-boundary control flow."""


class _AutonomousEpochHandoffRequested(Exception):
    """Internal deterministic child epoch-supersession boundary."""


@workflow.defn(name="AgentFactoryJobWorkflow")
class AgentFactoryJobWorkflow:
    """Deterministic orchestration for one existing AgentFactory workflow run."""

    def __init__(self) -> None:
        self.state = WorkflowState()
        self._paused = False
        self._cancel_requested = False
        self._active_activity: Any = None
        self._autonomous_job: AgentFactoryJobInput | None = None
        self._mission_control_token = 1
        self._retry_notice: AutonomousChildControlNotice | None = None
        self._epoch_handoff_notice: AutonomousChildEpochHandoffNotice | None = None

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

    @workflow.signal(name="autonomous_mission_control_applied")
    async def autonomous_mission_control_applied(
        self, notice: AutonomousChildControlNotice
    ) -> None:
        job = self._autonomous_job
        context = job.autonomous_context if job is not None else None
        if (
            context is None
            or notice.mission_id != context.mission_id
            or notice.child_job_id != context.child_job_id
        ):
            return
        if notice.fencing_token < self._mission_control_token:
            return
        self._mission_control_token = notice.fencing_token
        context.control_fencing_token = notice.fencing_token
        if notice.action in {"PAUSE", "STOP"}:
            self._paused = True
            self.state.status = (
                WorkflowStatus.STOPPED
                if notice.action == "STOP"
                else WorkflowStatus.PAUSED
            )
            self.state.last_progress = (
                f"Mission {notice.action.lower()} persisted; waiting after the "
                "current atomic operation"
            )
        elif notice.action == "RESUME":
            self._paused = False
            self.state.status = WorkflowStatus.RUNNING
            self.state.last_progress = "Mission control fence resumed child execution"
        elif notice.action == "RETRY_CURRENT_TASK":
            self._retry_notice = notice
            self.state.status = WorkflowStatus.RETRYING
            self.state.last_progress = (
                "Retry requested; retiring this strategy at the next safe boundary"
            )

    @workflow.signal(name="autonomous_epoch_handoff_requested")
    async def autonomous_epoch_handoff_requested(
        self, notice: AutonomousChildEpochHandoffNotice
    ) -> None:
        job = self._autonomous_job
        context = job.autonomous_context if job is not None else None
        if (
            context is None
            or notice.mission_id != context.mission_id
            or notice.child_job_id != context.child_job_id
            or notice.stopped_fencing_token < self._mission_control_token
        ):
            return
        self._mission_control_token = notice.stopped_fencing_token
        context.control_fencing_token = notice.stopped_fencing_token
        self._epoch_handoff_notice = notice
        self._paused = False
        self.state.status = WorkflowStatus.SUPERSEDED
        self.state.last_progress = (
            "Epoch handoff requested; retiring at the next atomic safe boundary"
        )

    async def _wait_until_runnable(self) -> None:
        if self._cancel_requested:
            raise asyncio.CancelledError
        if self._paused:
            await workflow.wait_condition(
                lambda: (
                    not self._paused
                    or self._cancel_requested
                    or self._retry_notice is not None
                    or self._epoch_handoff_notice is not None
                )
            )
        if self._cancel_requested:
            raise asyncio.CancelledError
        if self._epoch_handoff_notice is not None:
            raise _AutonomousEpochHandoffRequested
        if self._retry_notice is not None:
            raise _AutonomousRetryRequested
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
            result = await self._active_activity
        finally:
            self._active_activity = None
        await self._wait_until_runnable()
        return result

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
            result = await self._active_activity
        finally:
            self._active_activity = None
        await self._wait_until_runnable()
        return result

    async def _persist_failure(
        self, job: AgentFactoryJobInput, summary: str, failure_class: str
    ) -> None:
        try:
            await workflow.execute_activity(
                "fail_agentfactory_job",
                {
                    "job": job.to_dict(),
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
        self._autonomous_job = job
        if job.autonomous_context is not None:
            self._mission_control_token = (
                job.autonomous_context.control_fencing_token
            )
        try:
            self.state.phase = "validation"
            self.state.last_progress = "Validating persisted AgentFactory job"
            validation_activity = (
                "validate_autonomous_child_job"
                if job.autonomous_context is not None
                else "validate_agentfactory_job"
            )
            await self._fast_activity(validation_activity, job, job)

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
                            control_fencing_token=(
                                self._mission_control_token
                                if job.autonomous_context is not None
                                else None
                            ),
                        )
                    )
                    if result.failure_class == "EPOCH_HANDOFF_REQUESTED":
                        raise _AutonomousEpochHandoffRequested
                    if result.failure_class == "RETRY_REQUESTED":
                        self.state.status = WorkflowStatus.RETRYING
                        self.state.phase = "retry_requested"
                        self.state.last_progress = result.summary
                        return self.state.to_dict()
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
            autonomous = job.autonomous_context is not None
            self.state.last_progress = (
                "Persisting autonomous validation, review, and integration evidence"
                if autonomous
                else "Persisting final evidence and approval gate"
            )
            final = await self._fast_activity(
                (
                    "finalize_autonomous_child_job"
                    if autonomous
                    else "finalize_agentfactory_job"
                ),
                job,
                job,
            )
            self.state.status = (
                WorkflowStatus.COMPLETED
                if autonomous
                else WorkflowStatus.WAITING
            )
            self.state.phase = (
                "autonomous_completed" if autonomous else "awaiting_approval"
            )
            self.state.last_progress = final.summary
            return self.state.to_dict()
        except _AutonomousEpochHandoffRequested:
            self.state.status = WorkflowStatus.SUPERSEDED
            self.state.phase = "epoch_superseded"
            self.state.last_progress = (
                "Autonomous child stopped at an authorized epoch safe boundary"
            )
            await self._persist_failure(
                job, self.state.last_progress, "EPOCH_HANDOFF"
            )
            return self.state.to_dict()
        except _AutonomousRetryRequested:
            self.state.status = WorkflowStatus.RETRYING
            self.state.phase = "retry_requested"
            self.state.last_progress = (
                "Autonomous strategy stopped at a safe boundary for logical retry"
            )
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
        self._active_child: Any = None
        self._control_handlers = 0
        self._seen_control_payloads: dict[
            str, AutonomousMissionControlCommand
        ] = {}
        self._handoff_handlers = 0
        self._active_handoff_commands: set[str] = set()
        self._seen_handoff_payloads: dict[
            str, AutonomousEpochHandoffCommand
        ] = {}

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
            "current_child_job_id": state.current_child_job_id,
            "current_child_workflow_id": state.current_child_workflow_id,
            "current_work_item_stable_id": state.current_work_item_stable_id,
            "control_fencing_token": state.control_fencing_token,
            "last_control_command_id": state.last_control_command_id,
            "last_control_action": state.last_control_action,
            "pending_retry_child_job_id": state.pending_retry_child_job_id,
            "pending_retry_logical_attempt": (
                state.pending_retry_logical_attempt
            ),
            "pending_epoch_handoff_command_id": (
                state.pending_epoch_handoff_command_id
            ),
            "pending_epoch_handoff_action": state.pending_epoch_handoff_action,
            "last_epoch_handoff_command_id": state.last_epoch_handoff_command_id,
            "last_epoch_handoff_action": state.last_epoch_handoff_action,
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

    async def _apply_control_command(
        self, command: AutonomousMissionControlCommand
    ) -> None:
        seen = self._seen_control_payloads.get(command.command_id)
        if seen == command:
            return
        if seen is None:
            self._seen_control_payloads[command.command_id] = command
        self._control_handlers += 1
        try:
            try:
                result = await workflow.execute_activity(
                    "apply_autonomous_mission_control",
                    AutonomousMissionControlActivityInput(
                        scope=self._activity_scope(), command=command
                    ),
                    result_type=AutonomousMissionControlResult,
                    start_to_close_timeout=timedelta(
                        seconds=(
                            self._request.fast_activity_timeout_seconds
                            if self._request is not None
                            else 120
                        )
                    ),
                    retry_policy=fast_transient_policy(),
                )
            except ActivityError as exc:
                self._touch(
                    f"Mission control command {command.command_id} rejected: {exc}"
                )
                return
            state = self._state()
            if result.fencing_token < state.control_fencing_token:
                self._touch(
                    f"Ignored out-of-order control result {result.command_id} "
                    f"at superseded fence token {result.fencing_token}"
                )
                return
            state.mission_version = result.mission_version
            state.phase = result.phase
            state.disposition = result.disposition
            state.control_fencing_token = result.fencing_token
            state.last_control_command_id = result.command_id
            state.last_control_action = result.action
            if result.action == "PAUSE":
                state.workflow_status = WorkflowStatus.PAUSED.value
            elif result.action == "STOP":
                state.workflow_status = WorkflowStatus.STOPPED.value
            elif result.action == "RESUME":
                state.workflow_status = WorkflowStatus.RUNNING.value
            else:
                state.workflow_status = WorkflowStatus.RETRYING.value
                state.pending_retry_child_job_id = result.child_job_id
                state.pending_retry_logical_attempt = result.logical_attempt
            self._touch(
                f"Mission control {result.action.lower()} persisted at fence "
                f"token {result.fencing_token}"
            )
            if (
                self._active_child is not None
                and state.current_child_job_id is not None
            ):
                try:
                    await self._active_child.signal(
                        "autonomous_mission_control_applied",
                        AutonomousChildControlNotice(
                            mission_id=state.mission_id,
                            child_job_id=state.current_child_job_id,
                            command_id=result.command_id,
                            action=result.action,
                            mission_version=result.mission_version,
                            fencing_token=result.fencing_token,
                            logical_attempt=result.logical_attempt,
                        ),
                    )
                except Exception:  # Child may have closed at the same safe boundary.
                    self._touch(
                        "Mission control persisted after the active child closed"
                    )
        finally:
            self._control_handlers -= 1

    @workflow.signal(name="control_autonomous_mission")
    async def control_autonomous_mission(
        self, command: AutonomousMissionControlCommand
    ) -> None:
        await self._apply_control_command(command)

    @workflow.signal(name="pause_autonomous_mission")
    async def pause_autonomous_mission(
        self, command: AutonomousMissionControlCommand
    ) -> None:
        if command.action != "PAUSE":
            return
        await self._apply_control_command(command)

    @workflow.signal(name="resume_autonomous_mission")
    async def resume_autonomous_mission(
        self, command: AutonomousMissionControlCommand
    ) -> None:
        if command.action != "RESUME":
            return
        await self._apply_control_command(command)

    @workflow.signal(name="stop_autonomous_mission")
    async def stop_autonomous_mission(
        self, command: AutonomousMissionControlCommand
    ) -> None:
        if command.action != "STOP":
            return
        await self._apply_control_command(command)

    @workflow.signal(name="retry_current_task")
    async def retry_current_task(
        self, command: AutonomousMissionControlCommand
    ) -> None:
        if command.action != "RETRY_CURRENT_TASK":
            return
        await self._apply_control_command(command)

    async def _apply_epoch_handoff_command(
        self, command: AutonomousEpochHandoffCommand
    ) -> None:
        seen = self._seen_handoff_payloads.get(command.command_id)
        state = self._state()
        if seen == command and (
            command.command_id in self._active_handoff_commands
            or state.last_epoch_handoff_command_id == command.command_id
        ):
            return
        if seen is None:
            self._seen_handoff_payloads[command.command_id] = command
        self._active_handoff_commands.add(command.command_id)
        self._handoff_handlers += 1
        try:
            request = self._request
            if request is None:
                raise RuntimeError("Autonomous Mission Workflow input is unavailable")
            try:
                prepared = await workflow.execute_activity(
                    "prepare_autonomous_epoch_handoff",
                    AutonomousEpochHandoffPreparationInput(
                        scope=self._activity_scope(), command=command
                    ),
                    result_type=AutonomousEpochHandoffPreparationResult,
                    start_to_close_timeout=timedelta(
                        seconds=request.fast_activity_timeout_seconds
                    ),
                    retry_policy=fast_transient_policy(),
                )
            except ActivityError as exc:
                self._touch(
                    f"Epoch handoff command {command.command_id} rejected: {exc}"
                )
                return

            state = self._state()
            state.mission_version = prepared.stopped_mission_version
            state.disposition = "STOPPED"
            state.control_fencing_token = prepared.stopped_fencing_token
            state.pending_epoch_handoff_command_id = prepared.command_id
            state.pending_epoch_handoff_action = prepared.action
            state.last_control_command_id = f"{prepared.command_id}:safe-boundary"
            state.last_control_action = "STOP"
            state.workflow_status = WorkflowStatus.STOPPED.value
            self._touch(
                "Epoch handoff persisted; waiting for the active child safe boundary"
            )

            child_handle = self._active_child
            if (
                child_handle is not None
                and prepared.child_job_id is not None
                and state.current_child_job_id == prepared.child_job_id
            ):
                try:
                    await child_handle.signal(
                        "autonomous_epoch_handoff_requested",
                        AutonomousChildEpochHandoffNotice(
                            mission_id=prepared.mission_id,
                            child_job_id=prepared.child_job_id,
                            command_id=prepared.command_id,
                            stopped_mission_version=(
                                prepared.stopped_mission_version
                            ),
                            stopped_fencing_token=(
                                prepared.stopped_fencing_token
                            ),
                        ),
                    )
                except Exception:
                    self._touch(
                        "Epoch handoff persisted after the active child closed"
                    )
                await workflow.wait_condition(
                    lambda: self._active_child is not child_handle
                )

            try:
                completed = await workflow.execute_activity(
                    "complete_autonomous_epoch_handoff",
                    AutonomousEpochHandoffCompletionInput(
                        scope=self._activity_scope(),
                        command_id=prepared.command_id,
                    ),
                    result_type=AutonomousEpochHandoffCompletionResult,
                    start_to_close_timeout=timedelta(
                        seconds=request.fast_activity_timeout_seconds
                    ),
                    retry_policy=fast_transient_policy(),
                )
            except ActivityError as exc:
                state.workflow_status = WorkflowStatus.NEEDS_ATTENTION.value
                self._touch(
                    f"Epoch handoff {command.command_id} awaits recovery: {exc}"
                )
                return

            state.mission_version = completed.mission_version
            state.phase = completed.phase
            state.disposition = completed.disposition
            state.control_fencing_token = completed.fencing_token
            state.active_backlog_revision_id = (
                completed.selected_backlog_revision_id
            )
            state.active_backlog_revision_digest = (
                completed.selected_backlog_revision_digest
            )
            state.active_execution_epoch_id = completed.result_execution_epoch_id
            state.current_checkpoint_id = completed.selected_checkpoint_id
            state.execution_authorization_id = (
                completed.execution_authorization_id
            )
            state.current_child_job_id = None
            state.current_child_workflow_id = None
            state.current_work_item_stable_id = None
            state.current_role = None
            state.current_model = None
            state.pending_retry_child_job_id = None
            state.pending_retry_logical_attempt = None
            state.pending_epoch_handoff_command_id = None
            state.pending_epoch_handoff_action = None
            state.last_epoch_handoff_command_id = completed.command_id
            state.last_epoch_handoff_action = completed.action
            state.last_control_command_id = f"{completed.command_id}:resume"
            state.last_control_action = "RESUME"
            state.workflow_status = WorkflowStatus.RUNNING.value
            self._touch(
                f"Epoch handoff activated execution epoch "
                f"{completed.result_execution_epoch_id}"
            )
        finally:
            self._handoff_handlers -= 1
            self._active_handoff_commands.discard(command.command_id)

    @workflow.signal(name="restart_from_checkpoint")
    async def restart_from_checkpoint(
        self, command: AutonomousEpochHandoffCommand
    ) -> None:
        if command.action != "RESTART_FROM_CHECKPOINT":
            return
        await self._apply_epoch_handoff_command(command)

    @workflow.signal(name="apply_backlog_revision")
    async def apply_backlog_revision(
        self, command: AutonomousEpochHandoffCommand
    ) -> None:
        if command.action != "APPLY_BACKLOG_REVISION":
            return
        await self._apply_epoch_handoff_command(command)

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

    async def _read_control_activity(
        self,
    ) -> AutonomousMissionControlSnapshotResult:
        request = self._request
        if request is None:
            raise RuntimeError("Autonomous Mission Workflow input is unavailable")
        return await workflow.execute_activity(
            "read_autonomous_mission_control_fence",
            AutonomousMissionControlSnapshotInput(scope=self._activity_scope()),
            result_type=AutonomousMissionControlSnapshotResult,
            start_to_close_timeout=timedelta(
                seconds=request.fast_activity_timeout_seconds
            ),
            retry_policy=fast_transient_policy(),
        )

    def _apply_control_snapshot(
        self, snapshot: AutonomousMissionControlSnapshotResult
    ) -> None:
        state = self._state()
        state.mission_version = snapshot.mission_version
        state.phase = snapshot.phase
        state.disposition = snapshot.disposition
        state.control_fencing_token = snapshot.fencing_token
        state.active_backlog_revision_id = snapshot.backlog_revision_id
        state.active_execution_epoch_id = snapshot.execution_epoch_id

    async def _wait_until_mission_runnable(self) -> None:
        state = self._state()
        if (
            self._control_handlers
            or self._handoff_handlers
            or state.disposition != "RUNNING"
        ):
            await workflow.wait_condition(
                lambda: (
                    self._control_handlers == 0
                    and self._handoff_handlers == 0
                    and self._state().disposition == "RUNNING"
                )
            )
        state.workflow_status = WorkflowStatus.RUNNING.value

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
            state.backlog_approval_id = result.approval_id
            state.execution_authorization_id = result.authorization_id
            state.workflow_status = WorkflowStatus.WAITING.value
        else:
            state.workflow_status = WorkflowStatus.WAITING.value
        self._touch(result.reason)

    async def _enter_development_activity(
        self,
    ) -> AutonomousExecutionPreparationResult:
        request = self._request
        state = self._state()
        if (
            request is None
            or state.backlog_approval_id is None
            or state.execution_authorization_id is None
        ):
            raise RuntimeError("Approved mission authority is unavailable")
        return await workflow.execute_activity(
            "enter_autonomous_development",
            AutonomousExecutionPreparationInput(
                scope=self._activity_scope(),
                expected_mission_version=state.mission_version,
                expected_fencing_token=state.control_fencing_token,
                approval_id=state.backlog_approval_id,
                authorization_id=state.execution_authorization_id,
                command_id=(
                    f"{state.temporal_workflow_id}:environment:"
                    f"v{state.mission_version}"
                ),
            ),
            result_type=AutonomousExecutionPreparationResult,
            start_to_close_timeout=timedelta(
                seconds=request.fast_activity_timeout_seconds
            ),
            retry_policy=fast_transient_policy(),
        )

    async def _prepare_child_activity(
        self,
    ) -> AutonomousChildPreparationResult:
        request = self._request
        state = self._state()
        if request is None:
            raise RuntimeError("Autonomous Mission Workflow input is unavailable")
        return await workflow.execute_activity(
            "prepare_autonomous_child_job",
            AutonomousChildPreparationInput(
                scope=self._activity_scope(),
                expected_mission_version=state.mission_version,
                expected_fencing_token=state.control_fencing_token,
                execution_mode=request.autonomous_child_execution_mode,
                workflow_definition_id=(
                    request.autonomous_child_workflow_definition_id
                ),
                fast_activity_timeout_seconds=(
                    request.fast_activity_timeout_seconds
                ),
                llm_activity_timeout_seconds=(
                    request.planning_activity_timeout_seconds
                ),
                heartbeat_timeout_seconds=request.heartbeat_timeout_seconds,
                max_repair_iterations=(
                    request.autonomous_child_max_repair_iterations
                ),
                command_id=(
                    f"{state.temporal_workflow_id}:prepare-child:"
                    f"v{state.mission_version}:"
                    f"f{state.control_fencing_token}"
                ),
            ),
            result_type=AutonomousChildPreparationResult,
            start_to_close_timeout=timedelta(
                seconds=request.fast_activity_timeout_seconds
            ),
            retry_policy=fast_transient_policy(),
        )

    async def _reconcile_child_activity(
        self, child_job_id: int
    ) -> AutonomousChildReconciliationResult:
        request = self._request
        state = self._state()
        if request is None:
            raise RuntimeError("Autonomous Mission Workflow input is unavailable")
        return await workflow.execute_activity(
            "reconcile_autonomous_child_job",
            AutonomousChildReconciliationInput(
                scope=self._activity_scope(),
                child_job_id=child_job_id,
                expected_mission_version=state.mission_version,
                expected_fencing_token=state.control_fencing_token,
                command_id=(
                    f"{state.temporal_workflow_id}:reconcile-child:"
                    f"{child_job_id}:v{state.mission_version}"
                ),
            ),
            result_type=AutonomousChildReconciliationResult,
            start_to_close_timeout=timedelta(
                seconds=request.fast_activity_timeout_seconds
            ),
            retry_policy=fast_transient_policy(),
        )

    async def _complete_mission_activity(
        self,
    ) -> AutonomousMissionCompletionResult:
        request = self._request
        state = self._state()
        if request is None:
            raise RuntimeError("Autonomous Mission Workflow input is unavailable")
        return await workflow.execute_activity(
            "complete_autonomous_mission",
            AutonomousMissionCompletionInput(
                scope=self._activity_scope(),
                expected_mission_version=state.mission_version,
                expected_fencing_token=state.control_fencing_token,
                command_id=(
                    f"{state.temporal_workflow_id}:complete:"
                    f"v{state.mission_version}"
                ),
            ),
            result_type=AutonomousMissionCompletionResult,
            start_to_close_timeout=timedelta(
                seconds=request.fast_activity_timeout_seconds
            ),
            retry_policy=fast_transient_policy(),
        )

    async def _settle_retry_activity(
        self, child_job_id: int
    ) -> AutonomousRetrySettlementResult:
        request = self._request
        state = self._state()
        if request is None or state.last_control_command_id is None:
            raise RuntimeError("Retry control command is unavailable")
        return await workflow.execute_activity(
            "settle_autonomous_child_retry",
            AutonomousRetrySettlementInput(
                scope=self._activity_scope(),
                child_job_id=child_job_id,
                command_id=(
                    f"{state.last_control_command_id}:settle-child:"
                    f"{child_job_id}"
                ),
            ),
            result_type=AutonomousRetrySettlementResult,
            start_to_close_timeout=timedelta(
                seconds=request.fast_activity_timeout_seconds
            ),
            retry_policy=fast_transient_policy(),
        )

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
                if not request.post_approval_execution_enabled:
                    await workflow.wait_condition(lambda: False)
                try:
                    self._apply_control_snapshot(
                        await self._read_control_activity()
                    )
                except ActivityError as exc:
                    self.state.workflow_status = (
                        WorkflowStatus.NEEDS_ATTENTION.value
                    )
                    self._touch("Control fence synchronization failed: " + str(exc))
                    await workflow.wait_condition(lambda: False)
                await self._wait_until_mission_runnable()
                self.state.workflow_status = WorkflowStatus.RUNNING.value
                self.state.environment_status = "DISCOVERING"
                self._touch("Starting authorized environment orchestration")
                try:
                    environment = await self._enter_development_activity()
                except ActivityError as exc:
                    self.state.workflow_status = (
                        WorkflowStatus.NEEDS_ATTENTION.value
                    )
                    self.state.environment_status = "UNKNOWN"
                    self._touch(
                        "Environment orchestration failed: " + str(exc)
                    )
                    await workflow.wait_condition(lambda: False)
                self.state.mission_version = environment.mission_version
                self.state.phase = environment.phase
                self.state.disposition = environment.disposition
                self.state.control_fencing_token = environment.fencing_token
                self.state.environment_status = environment.environment_status
                self._touch(environment.summary)
                continue

            if self.state.phase == "DEVELOPMENT":
                await self._wait_until_mission_runnable()
                self.state.workflow_status = WorkflowStatus.RUNNING.value
                self._touch("Selecting the next dependency-ready backlog item")
                try:
                    prepared = await self._prepare_child_activity()
                    self.state.completed_items = prepared.completed_items
                    self.state.total_items = prepared.total_items
                    if prepared.all_complete:
                        await self._wait_until_mission_runnable()
                        completed = await self._complete_mission_activity()
                        self.state.mission_version = completed.mission_version
                        self.state.phase = completed.phase
                        self.state.disposition = completed.disposition
                        self.state.completed_items = completed.completed_items
                        self.state.total_items = completed.total_items
                        self.state.workflow_status = WorkflowStatus.COMPLETED.value
                        self._touch(completed.summary)
                        return self.state.to_dict()
                    if prepared.blocked or prepared.job is None:
                        self.state.workflow_status = (
                            WorkflowStatus.NEEDS_ATTENTION.value
                        )
                        self._touch(prepared.summary)
                        await workflow.wait_condition(lambda: False)

                    self.state.current_child_job_id = prepared.child_job_id
                    self.state.current_child_workflow_id = (
                        prepared.child_workflow_id
                    )
                    self.state.current_work_item_stable_id = (
                        prepared.stable_item_id
                    )
                    self.state.current_role = prepared.role
                    self.state.current_model = prepared.model
                    self._touch(prepared.summary)
                    await self._wait_until_mission_runnable()
                    if (
                        prepared.job is None
                        or prepared.job.autonomous_context is None
                    ):
                        raise RuntimeError(
                            "Prepared child omitted its autonomous control context"
                        )
                    prepared.job.autonomous_context.control_fencing_token = (
                        self.state.control_fencing_token
                    )
                    self._active_child = await workflow.start_child_workflow(
                        "AgentFactoryJobWorkflow",
                        prepared.job,
                        id=prepared.child_workflow_id,
                        task_queue=info.task_queue,
                        result_type=dict,
                        static_summary=(
                            f"Autonomous item {prepared.stable_item_id}"
                        ),
                        static_details=(
                            f"Mission {self.state.mission_id}, child job "
                            f"{prepared.child_job_id}"
                        ),
                    )
                    try:
                        child_result = await self._active_child
                    finally:
                        self._active_child = None
                    child_status = child_result.get("status")
                    if child_status == WorkflowStatus.RETRYING.value:
                        if (
                            prepared.child_job_id is None
                            or self.state.pending_retry_child_job_id
                            != prepared.child_job_id
                        ):
                            raise RuntimeError(
                                "Child requested retry without matching control command"
                            )
                        settled = await self._settle_retry_activity(
                            prepared.child_job_id
                        )
                        self.state.pending_retry_child_job_id = None
                        self.state.pending_retry_logical_attempt = None
                        self.state.current_child_job_id = None
                        self.state.current_child_workflow_id = None
                        self.state.current_work_item_stable_id = None
                        self.state.current_role = None
                        self.state.current_model = None
                        self.state.workflow_status = WorkflowStatus.RUNNING.value
                        self._touch(settled.summary)
                        continue
                    if child_status == WorkflowStatus.SUPERSEDED.value:
                        await workflow.wait_condition(
                            lambda: self._handoff_handlers == 0
                        )
                        continue
                    if child_status != WorkflowStatus.COMPLETED.value:
                        self.state.workflow_status = (
                            WorkflowStatus.NEEDS_ATTENTION.value
                        )
                        self._touch(
                            "Autonomous child did not produce accepted completion"
                        )
                        await workflow.wait_condition(lambda: False)
                    if prepared.child_job_id is None:
                        raise RuntimeError(
                            "Prepared child result omitted its persisted job id"
                        )
                    await self._wait_until_mission_runnable()
                    reconciled = await self._reconcile_child_activity(
                        prepared.child_job_id
                    )
                except (ActivityError, ChildWorkflowError) as exc:
                    if (
                        self._handoff_handlers
                        or self.state.pending_epoch_handoff_command_id is not None
                    ):
                        await workflow.wait_condition(
                            lambda: self._handoff_handlers == 0
                        )
                        continue
                    self.state.workflow_status = (
                        WorkflowStatus.NEEDS_ATTENTION.value
                    )
                    self._touch("Autonomous child orchestration failed: " + str(exc))
                    await workflow.wait_condition(lambda: False)

                self.state.mission_version = reconciled.mission_version
                self.state.current_checkpoint_id = reconciled.checkpoint_id
                self.state.completed_items = reconciled.completed_items
                self.state.total_items = reconciled.total_items
                self.state.current_child_job_id = None
                self.state.current_child_workflow_id = None
                self.state.current_work_item_stable_id = None
                self.state.current_role = None
                self.state.current_model = None
                self.state.workflow_status = WorkflowStatus.RUNNING.value
                self._touch(reconciled.summary)
                continue

            if self.state.phase == "COMPLETED":
                self.state.workflow_status = WorkflowStatus.COMPLETED.value
                return self.state.to_dict()

            await workflow.wait_condition(
                lambda: bool(self._planning_commands or self._approval_notices)
            )
            if self._planning_commands:
                command = self._planning_commands.pop(0)
                await self._wait_until_mission_runnable()
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
