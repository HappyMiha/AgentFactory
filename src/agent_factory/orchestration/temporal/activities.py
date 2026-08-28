from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from temporalio import activity
from temporalio.exceptions import ApplicationError

from ...autonomous_authorization import (
    AutonomousAuthorizationService,
    PlanningAction,
)
from ...autonomous_backlog_approval import AutonomousBacklogApprovalService
from ...autonomous_mission import (
    AutonomousMissionService,
    MissionControlFenceConflictError,
    MissionDisposition,
    MissionPhase,
)
from ...autonomous_planning import AutonomousPlanningService
from ...autonomous_planning_pipeline import (
    AutonomousPlanningPipelineService,
    PlanningPipelineFailedError,
    PlanningPipelineRun,
    PlanningProviderInvoker,
    RuntimePlanningInvoker,
)
from ...autonomous_proposal_verifier import (
    AutonomousProposalVerificationService,
    ProposalReadinessReport,
)
from ...backlog_revisions import BacklogRevisionService
from ...coding_delivery import AutonomousCodingDeliveryService
from ...config import config_path_for_workspace, load_yaml
from ...control_plane import (
    MissionControlAction,
    MissionControlCommand,
    MissionControlFenceService,
    MissionOperationKind,
    MissionSchedulingFencedError,
)
from ...local_model_scheduler import (
    LocalInferenceControlGuard,
    LocalInferenceFenceBinding,
)
from ...mission_checkpoints import (
    EpochHandoffNotReadyError,
    MissionCheckpointService,
)
from ...models import (
    Agent,
    Budget,
    ProviderCapabilities,
    ProviderExecutionAuthorization,
    ProviderResult,
    Status,
    WorkItem,
)
from ...providers import ProcessSupervisor
from ...registry import AgentRegistry
from ...reviewers import ReviewerRouter, ReviewSubject
from ...runtime import AgentRuntime, ExecutionMode
from ...storage import SQLiteStorage
from ...workflow_contracts import (
    PASSING_VERDICTS,
    StageContractError,
    parse_stage_verdict,
    validate_workflow,
)
from .models import (
    ActivityResult,
    AgentFactoryJobInput,
    AutonomousApprovalRevalidationInput,
    AutonomousApprovalRevalidationResult,
    AutonomousChildJobContext,
    AutonomousChildPreparationInput,
    AutonomousChildPreparationResult,
    AutonomousChildReconciliationInput,
    AutonomousChildReconciliationResult,
    AutonomousExecutionPreparationInput,
    AutonomousExecutionPreparationResult,
    AutonomousEpochHandoffCompletionInput,
    AutonomousEpochHandoffCompletionResult,
    AutonomousEpochHandoffPreparationInput,
    AutonomousEpochHandoffPreparationResult,
    AutonomousMissionActivityScope,
    AutonomousMissionControlActivityInput,
    AutonomousMissionControlResult,
    AutonomousMissionControlSnapshotInput,
    AutonomousMissionControlSnapshotResult,
    AutonomousMissionCompletionInput,
    AutonomousMissionCompletionResult,
    AutonomousPlanningActivityInput,
    AutonomousPlanningActivityResult,
    AutonomousRetrySettlementInput,
    AutonomousRetrySettlementResult,
    AutonomousTemporalRunRegistrationInput,
    AutonomousTemporalRunRegistrationResult,
    DemoWorkflowInput,
    StageActivityInput,
)
from .policies import classify_error
from .settings import TemporalSettings

LOGGER = logging.getLogger(__name__)
MARKER_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


class _FencedPlanningInvoker:
    """Re-check mission control before every role inference in one Activity."""

    def __init__(
        self,
        storage: SQLiteStorage,
        delegate: PlanningProviderInvoker,
    ):
        self.control = MissionControlFenceService(storage)
        self.delegate = delegate

    def invoke(self, request: Any) -> ProviderResult:
        while True:
            fence = self.control.current(request.mission_id)
            if fence.disposition == MissionDisposition.RUNNING.value:
                operation_id = (
                    f"planning:{request.run_id}:{request.assignment.role_id}:"
                    f"attempt-{request.attempt_number}:token-{fence.fencing_token}"
                )
                try:
                    self.control.begin_operation(
                        operation_id=operation_id,
                        mission_id=request.mission_id,
                        execution_epoch_id=fence.execution_epoch_id,
                        child_job_id=None,
                        operation_kind=MissionOperationKind.INFERENCE,
                        expected_fencing_token=fence.fencing_token,
                        request={
                            "role": request.assignment.role_id,
                            "provider_id": request.assignment.provider_id,
                            "model": request.assignment.model,
                            "planning_attempt": request.attempt_number,
                        },
                    )
                    break
                except (
                    MissionControlFenceConflictError,
                    MissionSchedulingFencedError,
                ):
                    continue
            if fence.disposition not in {
                MissionDisposition.PAUSED.value,
                MissionDisposition.STOPPED.value,
            }:
                raise PermissionError(
                    f"Planning is fenced by mission disposition {fence.disposition}"
                )
            activity.heartbeat(
                {
                    "mission_id": request.mission_id,
                    "planning_run_id": request.run_id,
                    "role": request.assignment.role_id,
                    "progress": (
                        f"waiting at mission {fence.disposition.lower()} fence"
                    ),
                    "fencing_token": fence.fencing_token,
                }
            )
            time.sleep(0.05)
        try:
            return self.delegate.invoke(request)
        finally:
            self.control.finish_operation(
                operation_id, reason="Planning role inference boundary completed"
            )


class AgentFactoryActivities:
    """Temporal activity adapters over the existing AgentFactory services."""

    def __init__(
        self,
        settings: TemporalSettings | None = None,
        *,
        autonomous_planning_invoker: PlanningProviderInvoker | None = None,
        autonomous_provider_capabilities: Mapping[
            str, ProviderCapabilities
        ] | None = None,
    ):
        self.settings = settings or TemporalSettings.from_env()
        self.autonomous_planning_invoker = autonomous_planning_invoker
        self.autonomous_provider_capabilities = dict(
            autonomous_provider_capabilities or {}
        )

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

    @staticmethod
    def _autonomous_storage(scope: AutonomousMissionActivityScope) -> SQLiteStorage:
        return SQLiteStorage(Path(scope.database).expanduser().resolve())

    @staticmethod
    def _assert_autonomous_scope(
        scope: AutonomousMissionActivityScope,
        missions: AutonomousMissionService,
    ):
        mission = missions.get(scope.mission_id)
        actual = (
            mission.identity,
            mission.mission_key,
            mission.project_id,
        )
        expected = (
            scope.mission_identity,
            scope.mission_key,
            scope.project_id,
        )
        if actual != expected:
            raise PermissionError(
                "Temporal mission scope does not match persisted mission identity"
            )
        return mission

    def _planning_runtime(
        self, scope: AutonomousMissionActivityScope
    ) -> tuple[PlanningProviderInvoker, dict[str, ProviderCapabilities]]:
        if self.autonomous_planning_invoker is not None:
            return (
                self.autonomous_planning_invoker,
                dict(self.autonomous_provider_capabilities),
            )
        runtime = AgentRuntime(workspace=Path(scope.workspace).expanduser().resolve())
        capabilities = {
            provider_id: provider.capabilities
            for provider_id, provider in runtime.providers.items()
        }
        return RuntimePlanningInvoker(runtime), capabilities

    def _register_autonomous_temporal_run_sync(
        self, request: AutonomousTemporalRunRegistrationInput
    ) -> AutonomousTemporalRunRegistrationResult:
        storage = self._autonomous_storage(request.scope)
        try:
            missions = AutonomousMissionService(storage)
            self._assert_autonomous_scope(request.scope, missions)
            registered = MissionCheckpointService(storage).register_mission_temporal_run(
                request.scope.mission_id,
                mission_identity=request.scope.mission_identity,
                mission_key=request.scope.mission_key,
                project_id=request.scope.project_id,
                sequence=request.chain_sequence,
                workflow_id=request.scope.temporal_workflow_id,
                run_id=request.run_id,
                previous_run_id=request.previous_run_id,
                first_run_id=request.first_run_id,
                mission_version=request.mission_version,
                phase=request.phase,
                disposition=request.disposition,
                active_backlog_revision_id=(
                    request.active_backlog_revision_id
                ),
                active_execution_epoch_id=request.active_execution_epoch_id,
                current_checkpoint_id=request.current_checkpoint_id,
                control_fencing_token=request.control_fencing_token,
                workflow_build_id=request.workflow_build_id,
                rollover_reason=request.rollover_reason,
                previous_run_history_event_count=(
                    request.previous_run_history_event_count
                ),
                previous_run_safe_boundary_count=(
                    request.previous_run_safe_boundary_count
                ),
                accepted_mutation_count=request.accepted_mutation_count,
            )
            return AutonomousTemporalRunRegistrationResult(
                mission_id=registered.mission_id,
                registration_id=registered.id,
                run_id=registered.run_id,
                chain_sequence=registered.sequence,
                workflow_build_id=registered.workflow_build_id,
                run_digest=registered.run_digest,
                duplicate=registered.duplicate,
                registered_at=registered.registered_at,
            )
        finally:
            storage.close()

    @activity.defn(name="register_autonomous_temporal_run")
    async def register_autonomous_temporal_run(
        self, request: AutonomousTemporalRunRegistrationInput
    ) -> AutonomousTemporalRunRegistrationResult:
        try:
            return await asyncio.to_thread(
                self._register_autonomous_temporal_run_sync, request
            )
        except (KeyError, PermissionError, ValueError, RuntimeError) as exc:
            raise ApplicationError(
                str(exc)[:4000], type="CONFIGURATION", non_retryable=True
            ) from exc

    def _autonomous_capabilities(
        self, scope: AutonomousMissionActivityScope
    ) -> dict[str, ProviderCapabilities]:
        if self.autonomous_provider_capabilities:
            return dict(self.autonomous_provider_capabilities)
        runtime = AgentRuntime(workspace=Path(scope.workspace).expanduser().resolve())
        return {
            provider_id: provider.capabilities
            for provider_id, provider in runtime.providers.items()
        }

    @staticmethod
    def _planning_phase_steps(
        action: PlanningAction, phase: MissionPhase
    ) -> tuple[MissionPhase, ...]:
        if action is PlanningAction.ANALYZE:
            if phase is MissionPhase.DRAFT:
                return (
                    MissionPhase.SPECIFICATION_ANALYSIS,
                    MissionPhase.BACKLOG_GENERATION,
                )
            if phase is MissionPhase.SPECIFICATION_ANALYSIS:
                return (MissionPhase.BACKLOG_GENERATION,)
            if phase is MissionPhase.BACKLOG_GENERATION:
                return ()
            raise PermissionError(
                "ANALYZE requires a draft or active analysis/generation phase"
            )
        if phase is not MissionPhase.WAITING_FOR_BACKLOG_APPROVAL:
            raise PermissionError(
                "REGENERATE_BACKLOG requires the durable backlog approval wait"
            )
        return (MissionPhase.BACKLOG_GENERATION,)

    @staticmethod
    def _planning_activity_result(
        missions: AutonomousMissionService,
        revisions: BacklogRevisionService,
        run: PlanningPipelineRun,
        report: ProposalReadinessReport,
        request: AutonomousPlanningActivityInput,
        *,
        duplicate: bool = False,
    ) -> AutonomousPlanningActivityResult:
        result_version = (
            report.mission_result_version
            if report.mission_result_version is not None
            else report.expected_mission_version
        )
        result_mission = missions.get(request.scope.mission_id, version=result_version)
        revision = revisions.get_revision(report.revision_id)
        lineage = revisions.revision_lineage(revision.id)
        ready = bool(report.ready)
        summary = (
            f"Proposal revision {revision.revision_number} is durably waiting "
            "for exact human approval"
            if ready
            else (
                f"Proposal revision {revision.revision_number} is blocked by "
                "verification"
            )
        )
        return AutonomousPlanningActivityResult(
            mission_id=result_mission.id,
            mission_version=result_mission.version,
            phase=result_mission.phase.value,
            disposition=result_mission.disposition.value,
            command_id=request.command.command_id,
            requested_action=request.command.requested_action,
            manifest_id=request.command.manifest_id,
            planning_authorization_id=request.command.planning_authorization_id,
            pipeline_run_id=run.id,
            verification_id=report.id,
            verification_status=report.status.value,
            proposed_revision_id=revision.id,
            proposed_revision_digest=revision.revision_digest,
            parent_revision_id=revision.parent_revision_id,
            proposal_revision_count=len(lineage),
            ready_for_approval=ready,
            summary=summary,
            occurred_at=report.created_at,
            duplicate=duplicate,
        )

    def _run_autonomous_planning_sync(
        self, request: AutonomousPlanningActivityInput
    ) -> AutonomousPlanningActivityResult:
        storage = self._autonomous_storage(request.scope)
        try:
            invoker, capabilities = self._planning_runtime(request.scope)
            missions = AutonomousMissionService(storage)
            planning = AutonomousPlanningService(storage, capabilities)
            authorizations = AutonomousAuthorizationService(storage, capabilities)
            pipeline = AutonomousPlanningPipelineService(
                storage, _FencedPlanningInvoker(storage, invoker), capabilities
            )
            verifier = AutonomousProposalVerificationService(storage)
            revisions = BacklogRevisionService(storage)
            self._assert_autonomous_scope(request.scope, missions)
            command = request.command
            action = PlanningAction(command.requested_action)
            historical = missions.get(
                request.scope.mission_id,
                version=command.expected_mission_version,
            )
            if historical.disposition is not MissionDisposition.RUNNING:
                raise PermissionError(
                    "Planning cannot start while mission scheduling is fenced"
                )
            if historical.mission_owner != command.actor:
                raise PermissionError(
                    "Only the authenticated mission owner may request planning"
                )
            steps = self._planning_phase_steps(action, historical.phase)
            verification_version = command.expected_mission_version + len(steps)
            pipeline_command_id = f"{command.command_id}:pipeline"
            verification_command_id = f"{command.command_id}:verification"

            verification_row = storage.db.execute(
                "SELECT id FROM autonomous_proposal_verifications WHERE command_id=?",
                (verification_command_id,),
            ).fetchone()
            if verification_row:
                report = verifier.get(int(verification_row["id"]))
                run = pipeline.get_run(report.pipeline_run_id)
                if (
                    report.mission_id != request.scope.mission_id
                    or report.manifest_id != command.manifest_id
                    or report.expected_mission_version != verification_version
                    or run.planning_authorization_id
                    != command.planning_authorization_id
                    or run.requested_action is not action
                    or run.command_id != pipeline_command_id
                    or run.created_by != command.actor
                ):
                    raise ValueError(
                        "Planning Activity command is already bound to another proposal"
                    )
                return self._planning_activity_result(
                    missions,
                    revisions,
                    run,
                    report,
                    request,
                    duplicate=True,
                )

            manifest = planning.get_manifest(command.manifest_id)
            if (
                manifest.mission_id != request.scope.mission_id
                or manifest.created_by != command.actor
                or manifest.stale
            ):
                raise PermissionError(
                    "Planning manifest is not a fresh owner-authored mission manifest"
                )
            role_models = {
                assignment.role_id: assignment.model
                for assignment in manifest.assignments
            }
            provider_ids = tuple(
                sorted({assignment.provider_id for assignment in manifest.assignments})
            )
            existing_run = storage.db.execute(
                "SELECT id FROM autonomous_planning_pipeline_runs WHERE command_id=?",
                (pipeline_command_id,),
            ).fetchone()
            if not existing_run:
                authorizations.assert_planning_authority(
                    request.scope.mission_id,
                    command.planning_authorization_id,
                    planning_request_id=manifest.proposal_key,
                    requested_action=action,
                    role_models=role_models,
                    provider_ids=provider_ids,
                    actor=command.actor,
                )

            next_version = command.expected_mission_version
            for ordinal, target in enumerate(steps, start=1):
                missions.transition_phase(
                    request.scope.mission_id,
                    target,
                    actor=command.actor,
                    command_id=f"{command.command_id}:phase:{ordinal}",
                    expected_version=next_version,
                    reason=(
                        "Execute explicit bounded local planning request "
                        f"{command.command_id}"
                    ),
                )
                next_version += 1

            run = pipeline.execute(
                request.scope.mission_id,
                manifest_id=manifest.id,
                planning_authorization_id=command.planning_authorization_id,
                actor=command.actor,
                command_id=pipeline_command_id,
                max_attempts_per_role=command.max_attempts_per_role,
            )
            report = verifier.verify_and_present(
                run.id,
                actor=command.actor,
                command_id=verification_command_id,
                expected_mission_version=verification_version,
            )
            return self._planning_activity_result(
                missions, revisions, run, report, request
            )
        finally:
            storage.close()

    @activity.defn(name="run_autonomous_planning")
    async def run_autonomous_planning(
        self, request: AutonomousPlanningActivityInput
    ) -> AutonomousPlanningActivityResult:
        running = asyncio.create_task(
            asyncio.to_thread(self._run_autonomous_planning_sync, request)
        )
        try:
            while not running.done():
                activity.heartbeat(
                    {
                        "mission_id": request.scope.mission_id,
                        "command_id": request.command.command_id,
                        "manifest_id": request.command.manifest_id,
                        "progress": "bounded local planning roles running",
                    }
                )
                await asyncio.wait(
                    {running}, timeout=self.settings.heartbeat_interval_seconds
                )
            return await running
        except (KeyError, PermissionError, ValueError) as exc:
            raise ApplicationError(
                str(exc)[:4000], type="CONFIGURATION", non_retryable=True
            ) from exc
        except PlanningPipelineFailedError as exc:
            raise ApplicationError(
                str(exc)[:4000], type="AGENT_ERROR", non_retryable=True
            ) from exc

    def _revalidate_autonomous_approval_sync(
        self, request: AutonomousApprovalRevalidationInput
    ) -> AutonomousApprovalRevalidationResult:
        storage = self._autonomous_storage(request.scope)
        try:
            missions = AutonomousMissionService(storage)
            mission = self._assert_autonomous_scope(request.scope, missions)

            def denied(reason: str) -> AutonomousApprovalRevalidationResult:
                return AutonomousApprovalRevalidationResult(
                    mission_id=mission.id,
                    mission_version=mission.version,
                    phase=mission.phase.value,
                    disposition=mission.disposition.value,
                    approved=False,
                    notice_matches_authority=False,
                    reason=reason,
                    occurred_at=mission.updated_at,
                )

            row = storage.db.execute(
                "SELECT id FROM autonomous_backlog_approvals "
                "WHERE mission_id=? ORDER BY id DESC LIMIT 1",
                (mission.id,),
            ).fetchone()
            if not row:
                return denied(
                    "Approval Signal did not resolve to persisted approval authority"
                )
            approvals = AutonomousBacklogApprovalService(
                storage, self.autonomous_provider_capabilities
            )
            approval = approvals.get(int(row["id"]))
            epoch = approvals.checkpoints.get_epoch(approval.execution_epoch_id)
            authorization = approvals.authorizations.get_authorization(
                approval.authorization_id
            )
            revision = BacklogRevisionService(storage).get_revision(
                approval.revision_id
            )
            checks = {
                "phase": mission.phase is MissionPhase.APPROVED,
                "disposition": mission.disposition is MissionDisposition.RUNNING,
                "mission_version": mission.version
                == approval.result_mission_version,
                "revision": mission.active_backlog_revision_id
                == approval.revision_id,
                "revision_digest": revision.revision_digest
                == approval.revision_digest,
                "epoch": mission.active_execution_epoch_id
                == approval.execution_epoch_id,
                "epoch_active": epoch.is_active,
                "epoch_revision": epoch.base_backlog_revision_id
                == approval.revision_id
                and epoch.base_backlog_revision_digest
                == approval.revision_digest,
                "workflow": epoch.temporal_workflow_id
                == request.scope.temporal_workflow_id,
                "first_run": epoch.temporal_first_run_id
                == request.scope.temporal_first_run_id,
                "authorization": authorization.mission_id == mission.id
                and authorization.backlog_revision_id == approval.revision_id
                and authorization.execution_epoch_id == epoch.id
                and not authorization.revoked,
            }
            failed = tuple(name for name, passed in checks.items() if not passed)
            if failed:
                return denied(
                    "Persisted approval authority failed revalidation: "
                    + ", ".join(failed)
                )

            notice = request.notice
            claimed = {
                "approval": (
                    notice.claimed_approval_id,
                    approval.id,
                ),
                "revision": (
                    notice.claimed_revision_id,
                    approval.revision_id,
                ),
                "digest": (
                    notice.claimed_revision_digest,
                    approval.revision_digest,
                ),
                "epoch": (
                    notice.claimed_execution_epoch_id,
                    approval.execution_epoch_id,
                ),
            }
            notice_matches = all(
                value is None or value == authoritative
                for value, authoritative in claimed.values()
            )
            return AutonomousApprovalRevalidationResult(
                mission_id=mission.id,
                mission_version=mission.version,
                phase=mission.phase.value,
                disposition=mission.disposition.value,
                approved=True,
                notice_matches_authority=notice_matches,
                reason=(
                    "Persisted approval, completion, epoch, and authorization "
                    "were revalidated independently of Signal claims"
                ),
                occurred_at=approval.created_at,
                approval_id=approval.id,
                revision_id=approval.revision_id,
                revision_digest=approval.revision_digest,
                execution_epoch_id=approval.execution_epoch_id,
                authorization_id=approval.authorization_id,
            )
        finally:
            storage.close()

    @activity.defn(name="revalidate_autonomous_approval")
    async def revalidate_autonomous_approval(
        self, request: AutonomousApprovalRevalidationInput
    ) -> AutonomousApprovalRevalidationResult:
        try:
            return await asyncio.to_thread(
                self._revalidate_autonomous_approval_sync, request
            )
        except (KeyError, PermissionError, ValueError) as exc:
            raise ApplicationError(
                str(exc)[:4000], type="CONFIGURATION", non_retryable=True
            ) from exc

    def _read_autonomous_control_fence_sync(
        self, request: AutonomousMissionControlSnapshotInput
    ) -> AutonomousMissionControlSnapshotResult:
        storage = self._autonomous_storage(request.scope)
        try:
            missions = AutonomousMissionService(storage)
            self._assert_autonomous_scope(request.scope, missions)
            fence = MissionControlFenceService(storage).current(
                request.scope.mission_id
            )
            return AutonomousMissionControlSnapshotResult(
                mission_id=fence.mission_id,
                mission_version=fence.mission_version,
                phase=fence.phase,
                disposition=fence.disposition,
                fencing_token=fence.fencing_token,
                backlog_revision_id=fence.backlog_revision_id,
                execution_epoch_id=fence.execution_epoch_id,
                occurred_at=fence.updated_at,
            )
        finally:
            storage.close()

    @activity.defn(name="read_autonomous_mission_control_fence")
    async def read_autonomous_mission_control_fence(
        self, request: AutonomousMissionControlSnapshotInput
    ) -> AutonomousMissionControlSnapshotResult:
        try:
            return await asyncio.to_thread(
                self._read_autonomous_control_fence_sync, request
            )
        except (KeyError, PermissionError, ValueError, RuntimeError) as exc:
            raise ApplicationError(
                str(exc)[:4000], type="CONFIGURATION", non_retryable=True
            ) from exc

    def _apply_autonomous_control_sync(
        self, request: AutonomousMissionControlActivityInput
    ) -> AutonomousMissionControlResult:
        storage = self._autonomous_storage(request.scope)
        try:
            missions = AutonomousMissionService(storage)
            self._assert_autonomous_scope(request.scope, missions)
            command = request.command
            if command.mission_id != request.scope.mission_id:
                raise PermissionError("Control Signal mission identity is spoofed")
            result = MissionControlFenceService(storage).apply(
                MissionControlCommand(
                    mission_id=command.mission_id,
                    command_id=command.command_id,
                    action=MissionControlAction(command.action),
                    actor=command.actor,
                    reason=command.reason,
                    expected_mission_version=command.expected_mission_version,
                    expected_fencing_token=command.expected_fencing_token,
                    expected_backlog_revision_id=(
                        command.expected_backlog_revision_id
                    ),
                    expected_execution_epoch_id=(
                        command.expected_execution_epoch_id
                    ),
                    child_job_id=command.child_job_id,
                )
            )
            return AutonomousMissionControlResult(
                mission_id=result.mission_id,
                command_id=result.command_id,
                action=result.action.value,
                mission_version=result.mission_version,
                phase=result.phase,
                disposition=result.disposition,
                fencing_token=result.fencing_token,
                active_operations=result.active_operations,
                releasing_operations=result.releasing_operations,
                duplicate=result.duplicate,
                occurred_at=result.occurred_at,
                child_job_id=result.child_job_id,
                logical_attempt=result.logical_attempt,
            )
        finally:
            storage.close()

    @activity.defn(name="apply_autonomous_mission_control")
    async def apply_autonomous_mission_control(
        self, request: AutonomousMissionControlActivityInput
    ) -> AutonomousMissionControlResult:
        try:
            return await asyncio.to_thread(
                self._apply_autonomous_control_sync, request
            )
        except (KeyError, PermissionError, ValueError, RuntimeError) as exc:
            raise ApplicationError(
                str(exc)[:4000], type="CONFIGURATION", non_retryable=True
            ) from exc

    def _prepare_autonomous_epoch_handoff_sync(
        self, request: AutonomousEpochHandoffPreparationInput
    ) -> AutonomousEpochHandoffPreparationResult:
        storage = self._autonomous_storage(request.scope)
        try:
            missions = AutonomousMissionService(storage)
            self._assert_autonomous_scope(request.scope, missions)
            command = request.command
            if command.mission_id != request.scope.mission_id:
                raise PermissionError("Epoch handoff Signal mission identity is spoofed")
            checkpoints = MissionCheckpointService(
                storage, self._autonomous_capabilities(request.scope)
            )
            preparation = checkpoints.begin_epoch_handoff(
                command.command_id,
                mission_id=command.mission_id,
                action=command.action,
                expected_mission_version=command.expected_mission_version,
                expected_fencing_token=command.expected_fencing_token,
                expected_backlog_revision_id=command.expected_backlog_revision_id,
                expected_execution_epoch_id=command.expected_execution_epoch_id,
                expected_child_job_id=command.expected_child_job_id,
                selected_checkpoint_id=command.selected_checkpoint_id,
                selected_backlog_revision_id=command.selected_backlog_revision_id,
            )
            authoritative = checkpoints.get_epoch_handoff_request(command.command_id)
            return AutonomousEpochHandoffPreparationResult(
                mission_id=authoritative.mission_id,
                command_id=authoritative.command_id,
                action=authoritative.action.value,
                stopped_mission_version=preparation.stopped_mission_version,
                stopped_fencing_token=preparation.stopped_fencing_token,
                source_execution_epoch_id=(
                    authoritative.expected_execution_epoch_id
                ),
                selected_checkpoint_id=authoritative.selected_checkpoint_id,
                selected_backlog_revision_id=(
                    authoritative.selected_backlog_revision_id
                ),
                child_job_id=preparation.child_job_id,
                duplicate=preparation.duplicate,
                occurred_at=preparation.created_at,
            )
        finally:
            storage.close()

    @activity.defn(name="prepare_autonomous_epoch_handoff")
    async def prepare_autonomous_epoch_handoff(
        self, request: AutonomousEpochHandoffPreparationInput
    ) -> AutonomousEpochHandoffPreparationResult:
        try:
            return await asyncio.to_thread(
                self._prepare_autonomous_epoch_handoff_sync, request
            )
        except (KeyError, PermissionError, ValueError, RuntimeError) as exc:
            raise ApplicationError(
                str(exc)[:4000], type="CONFIGURATION", non_retryable=True
            ) from exc

    def _complete_autonomous_epoch_handoff_sync(
        self, request: AutonomousEpochHandoffCompletionInput
    ) -> AutonomousEpochHandoffCompletionResult:
        storage = self._autonomous_storage(request.scope)
        try:
            missions = AutonomousMissionService(storage)
            self._assert_autonomous_scope(request.scope, missions)
            checkpoints = MissionCheckpointService(
                storage, self._autonomous_capabilities(request.scope)
            )
            authoritative = checkpoints.get_epoch_handoff_request(
                request.command_id
            )
            if authoritative.mission_id != request.scope.mission_id:
                raise PermissionError("Epoch handoff command belongs to another mission")
            result = checkpoints.complete_epoch_handoff(request.command_id)
            mission = missions.get(authoritative.mission_id)
            revision = checkpoints._revision(
                authoritative.mission_id,
                result.selected_backlog_revision_id,
            )
            return AutonomousEpochHandoffCompletionResult(
                mission_id=mission.id,
                command_id=authoritative.command_id,
                action=authoritative.action.value,
                mission_version=result.result_mission_version,
                phase=mission.phase.value,
                disposition=mission.disposition.value,
                fencing_token=result.result_fencing_token,
                source_execution_epoch_id=result.source_execution_epoch_id,
                result_execution_epoch_id=result.result_execution_epoch_id,
                selected_checkpoint_id=result.selected_checkpoint_id,
                selected_backlog_revision_id=result.selected_backlog_revision_id,
                selected_backlog_revision_digest=str(revision["revision_digest"]),
                execution_authorization_id=result.execution_authorization_id,
                duplicate=result.duplicate,
                occurred_at=result.created_at,
            )
        finally:
            storage.close()

    @activity.defn(name="complete_autonomous_epoch_handoff")
    async def complete_autonomous_epoch_handoff(
        self, request: AutonomousEpochHandoffCompletionInput
    ) -> AutonomousEpochHandoffCompletionResult:
        try:
            return await asyncio.to_thread(
                self._complete_autonomous_epoch_handoff_sync, request
            )
        except EpochHandoffNotReadyError as exc:
            raise ApplicationError(
                str(exc)[:4000], type="TRANSIENT", non_retryable=False
            ) from exc
        except (KeyError, PermissionError, ValueError, RuntimeError) as exc:
            raise ApplicationError(
                str(exc)[:4000], type="CONFIGURATION", non_retryable=True
            ) from exc

    def _settle_autonomous_retry_sync(
        self, request: AutonomousRetrySettlementInput
    ) -> AutonomousRetrySettlementResult:
        storage = self._autonomous_storage(request.scope)
        try:
            missions = AutonomousMissionService(storage)
            self._assert_autonomous_scope(request.scope, missions)
            settlement = MissionControlFenceService(storage).settle_retry(
                request.child_job_id, command_id=request.command_id
            )
            return AutonomousRetrySettlementResult(
                mission_id=request.scope.mission_id,
                child_job_id=settlement.child_job_id,
                retry_request_id=settlement.retry_request_id,
                failed_state_id=settlement.failed_state_id,
                ready_state_id=settlement.ready_state_id,
                next_logical_attempt=settlement.next_logical_attempt,
                summary=(
                    "Current child strategy retired at a safe boundary; "
                    f"logical attempt {settlement.next_logical_attempt} is ready"
                ),
                occurred_at=settlement.created_at,
            )
        finally:
            storage.close()

    @activity.defn(name="settle_autonomous_child_retry")
    async def settle_autonomous_child_retry(
        self, request: AutonomousRetrySettlementInput
    ) -> AutonomousRetrySettlementResult:
        try:
            return await asyncio.to_thread(
                self._settle_autonomous_retry_sync, request
            )
        except (KeyError, PermissionError, ValueError, RuntimeError) as exc:
            raise ApplicationError(
                str(exc)[:4000], type="CONFIGURATION", non_retryable=True
            ) from exc

    @staticmethod
    def _autonomous_activity_error(exc: Exception) -> ApplicationError:
        return ApplicationError(
            str(exc)[:4000], type="CONFIGURATION", non_retryable=True
        )

    def _enter_autonomous_development_sync(
        self, request: AutonomousExecutionPreparationInput
    ) -> AutonomousExecutionPreparationResult:
        storage = self._autonomous_storage(request.scope)
        try:
            missions = AutonomousMissionService(storage)
            self._assert_autonomous_scope(request.scope, missions)
            delivery = AutonomousCodingDeliveryService(
                storage, self._autonomous_capabilities(request.scope)
            )
            approval = delivery.approvals.get(request.approval_id)
            if (
                approval.mission_id != request.scope.mission_id
                or approval.authorization_id != request.authorization_id
                or approval.result_mission_version
                != request.expected_mission_version
            ):
                raise PermissionError(
                    "Environment request does not match persisted approval authority"
                )
            MissionControlFenceService(storage).assert_allows(
                request.scope.mission_id,
                expected_fencing_token=request.expected_fencing_token,
                execution_epoch_id=approval.execution_epoch_id,
            )
            mission = delivery.enter_development(
                request.scope.mission_id,
                expected_mission_version=request.expected_mission_version,
                command_id=request.command_id,
            )
            return AutonomousExecutionPreparationResult(
                mission_id=mission.id,
                mission_version=mission.version,
                phase=mission.phase.value,
                disposition=mission.disposition.value,
                fencing_token=MissionControlFenceService(storage)
                .current(mission.id)
                .fencing_token,
                environment_status="READY",
                summary=(
                    "Authorized environment discovery and bootstrap completed; "
                    "mission development is ready"
                ),
                occurred_at=mission.updated_at,
            )
        finally:
            storage.close()

    @activity.defn(name="enter_autonomous_development")
    async def enter_autonomous_development(
        self, request: AutonomousExecutionPreparationInput
    ) -> AutonomousExecutionPreparationResult:
        try:
            return await asyncio.to_thread(
                self._enter_autonomous_development_sync, request
            )
        except (KeyError, PermissionError, ValueError, RuntimeError) as exc:
            raise self._autonomous_activity_error(exc) from exc

    @staticmethod
    def _autonomous_job_context(
        delivery: AutonomousCodingDeliveryService,
        child_job: Any,
    ) -> tuple[AutonomousChildJobContext, str, str]:
        authorization = delivery.authorizations.get_authorization(
            child_job.authorization_id
        )
        epoch = delivery.checkpoints.get_epoch(child_job.execution_epoch_id)
        item = delivery.revisions.item(
            child_job.backlog_revision_id, child_job.stable_item_id
        )
        role = item.item.assigned_role
        model = str(
            authorization.role_model_manifest.get("role_models", {}).get(role, "")
        )
        if not model:
            raise PermissionError(
                f"Approved role/model manifest omits child role {role!r}"
            )
        context = AutonomousChildJobContext(
            child_job_id=child_job.id,
            mission_id=child_job.mission_id,
            backlog_revision_id=child_job.backlog_revision_id,
            backlog_revision_digest=child_job.backlog_revision_digest,
            execution_epoch_id=child_job.execution_epoch_id,
            authorization_id=child_job.authorization_id,
            backlog_item_id=child_job.backlog_item_id,
            stable_item_id=child_job.stable_item_id,
            item_digest=child_job.item_digest,
            logical_attempt=child_job.logical_attempt,
            child_workflow_id=child_job.child_workflow_id,
            repository_path=authorization.repository_path,
            epoch_branch=epoch.epoch_branch,
            control_fencing_token=child_job.control_fencing_token,
        )
        return context, role, model

    def _prepare_autonomous_child_sync(
        self, request: AutonomousChildPreparationInput
    ) -> AutonomousChildPreparationResult:
        storage = self._autonomous_storage(request.scope)
        operation_id: str | None = None
        try:
            missions = AutonomousMissionService(storage)
            mission = self._assert_autonomous_scope(request.scope, missions)
            if mission.version != request.expected_mission_version:
                raise ValueError(
                    "Mission version changed before autonomous child preparation"
                )
            if (
                mission.phase is not MissionPhase.DEVELOPMENT
                or mission.disposition is not MissionDisposition.RUNNING
            ):
                raise PermissionError(
                    "Mission is not in authorized autonomous development"
                )
            delivery = AutonomousCodingDeliveryService(
                storage, self._autonomous_capabilities(request.scope)
            )
            operation_id = (
                f"{request.command_id}:next-work-item:"
                f"token-{request.expected_fencing_token}"
            )
            MissionControlFenceService(storage).begin_operation(
                operation_id=operation_id,
                mission_id=mission.id,
                execution_epoch_id=mission.active_execution_epoch_id,
                child_job_id=None,
                operation_kind=MissionOperationKind.NEXT_WORK_ITEM,
                expected_fencing_token=request.expected_fencing_token,
                request={
                    "mission_version": request.expected_mission_version,
                    "execution_mode": request.execution_mode,
                    "workflow_definition_id": request.workflow_definition_id,
                },
            )
            child_job = delivery.open_job(mission.id)
            projections = tuple(
                item
                for item in delivery.revisions.active_items(mission.id)
                if item.item.executable
            )
            completed = sum(
                item.status.value == "DONE" for item in projections
            )
            total = len(projections)
            if child_job is None:
                candidate = next(
                    (
                        item
                        for item in projections
                        if item.status.value in {"READY", "RUNNING"}
                    ),
                    None,
                )
                if candidate is None:
                    all_complete = bool(total) and completed == total
                    return AutonomousChildPreparationResult(
                        mission_id=mission.id,
                        mission_version=mission.version,
                        completed_items=completed,
                        total_items=total,
                        all_complete=all_complete,
                        blocked=not all_complete,
                        summary=(
                            "All executable backlog items have accepted checkpoints"
                            if all_complete
                            else "No dependency-ready executable backlog item is available"
                        ),
                        occurred_at=mission.updated_at,
                    )
                child_job = delivery.prepare_job(
                    mission.id,
                    candidate.item.stable_id,
                    execution_mode=request.execution_mode,
                    workflow_definition_id=request.workflow_definition_id,
                    command_id=request.command_id,
                    expected_fencing_token=request.expected_fencing_token,
                )
            context, role, model = self._autonomous_job_context(
                delivery, child_job
            )
            job = AgentFactoryJobInput(
                job_id=child_job.job_id,
                run_id=child_job.run_id,
                project_id=mission.project_id,
                task_id=child_job.task_id,
                workspace=context.repository_path,
                database=request.scope.database,
                workflow_definition_id=child_job.workflow_definition_id,
                mode=child_job.execution_mode,
                fast_activity_timeout_seconds=request.fast_activity_timeout_seconds,
                llm_activity_timeout_seconds=request.llm_activity_timeout_seconds,
                heartbeat_timeout_seconds=request.heartbeat_timeout_seconds,
                max_repair_iterations=request.max_repair_iterations,
                autonomous_context=context,
            )
            return AutonomousChildPreparationResult(
                mission_id=mission.id,
                mission_version=mission.version,
                completed_items=completed,
                total_items=total,
                all_complete=False,
                blocked=False,
                summary=(
                    f"Prepared deterministic autonomous child for "
                    f"{child_job.stable_item_id}"
                ),
                occurred_at=child_job.created_at,
                child_job_id=child_job.id,
                child_workflow_id=child_job.child_workflow_id,
                stable_item_id=child_job.stable_item_id,
                role=role,
                model=model,
                job=job,
            )
        finally:
            if operation_id is not None:
                try:
                    MissionControlFenceService(storage).finish_operation(
                        operation_id,
                        reason="Next work-item admission boundary completed",
                    )
                except KeyError:
                    pass
            storage.close()

    @activity.defn(name="prepare_autonomous_child_job")
    async def prepare_autonomous_child_job(
        self, request: AutonomousChildPreparationInput
    ) -> AutonomousChildPreparationResult:
        try:
            return await asyncio.to_thread(
                self._prepare_autonomous_child_sync, request
            )
        except (KeyError, PermissionError, ValueError, RuntimeError) as exc:
            raise self._autonomous_activity_error(exc) from exc

    @staticmethod
    def _assert_autonomous_job_binding(
        delivery: AutonomousCodingDeliveryService,
        job: AgentFactoryJobInput,
    ):
        context = job.autonomous_context
        if context is None:
            raise PermissionError("AgentFactory job has no autonomous context")
        persisted = delivery.get_job(context.child_job_id)
        expected = (
            context.mission_id,
            context.backlog_revision_id,
            context.backlog_revision_digest,
            context.execution_epoch_id,
            context.authorization_id,
            context.backlog_item_id,
            context.stable_item_id,
            context.item_digest,
            context.logical_attempt,
            context.child_workflow_id,
            job.job_id,
            job.task_id,
            job.run_id,
            job.project_id,
            job.workflow_definition_id,
            job.mode,
        )
        actual = (
            persisted.mission_id,
            persisted.backlog_revision_id,
            persisted.backlog_revision_digest,
            persisted.execution_epoch_id,
            persisted.authorization_id,
            persisted.backlog_item_id,
            persisted.stable_item_id,
            persisted.item_digest,
            persisted.logical_attempt,
            persisted.child_workflow_id,
            persisted.job_id,
            persisted.task_id,
            persisted.run_id,
            delivery.missions.get(persisted.mission_id).project_id,
            persisted.workflow_definition_id,
            persisted.execution_mode,
        )
        if actual != expected:
            raise PermissionError(
                "Autonomous child input does not match its immutable persisted scope"
            )
        authorization = delivery.authorizations.get_authorization(
            persisted.authorization_id
        )
        epoch = delivery.checkpoints.get_epoch(persisted.execution_epoch_id)
        if (
            Path(context.repository_path).expanduser().resolve()
            != Path(authorization.repository_path).expanduser().resolve()
            or context.epoch_branch != epoch.epoch_branch
            or Path(job.workspace).expanduser().resolve()
            != Path(authorization.repository_path).expanduser().resolve()
        ):
            raise PermissionError(
                "Autonomous child repository or epoch branch binding changed"
            )
        return persisted

    def _validate_autonomous_child_sync(
        self, job: AgentFactoryJobInput
    ) -> ActivityResult:
        if job.autonomous_context is None:
            raise PermissionError("AgentFactory job has no autonomous context")
        storage = self._storage(job)
        try:
            scope = AutonomousMissionActivityScope(
                mission_id=job.autonomous_context.mission_id,
                mission_identity=AutonomousMissionService(storage)
                .get(job.autonomous_context.mission_id)
                .identity,
                mission_key=AutonomousMissionService(storage)
                .get(job.autonomous_context.mission_id)
                .mission_key,
                project_id=job.project_id,
                workspace=job.workspace,
                database=job.database,
                temporal_workflow_id=job.autonomous_context.child_workflow_id,
                temporal_first_run_id=job.autonomous_context.child_workflow_id,
            )
            delivery = AutonomousCodingDeliveryService(
                storage, self._autonomous_capabilities(scope)
            )
            persisted = self._assert_autonomous_job_binding(delivery, job)
            MissionControlFenceService(storage).assert_allows(
                persisted.mission_id,
                expected_fencing_token=(
                    job.autonomous_context.control_fencing_token
                ),
                execution_epoch_id=persisted.execution_epoch_id,
            )
            authorization = delivery.authorize_job(
                persisted.id,
                command_id=f"{persisted.child_workflow_id}:authorize",
            )
            return ActivityResult(
                True,
                summary="Persisted autonomous mission authority validated",
                artifacts=[f"authorization-decision:{authorization.decision_id}"],
                metadata={
                    "child_job_id": persisted.id,
                    "authorization_id": authorization.authorization_id,
                    "authorization_decision_id": authorization.decision_id,
                    "authorization_decision_digest": authorization.decision_digest,
                    "provider_id": authorization.provider_id,
                    "role": authorization.role,
                    "model": authorization.model,
                },
            )
        finally:
            storage.close()

    @activity.defn(name="validate_autonomous_child_job")
    async def validate_autonomous_child_job(
        self, job: AgentFactoryJobInput
    ) -> ActivityResult:
        try:
            if (
                job.autonomous_context is None
                or activity.info().workflow_id
                != job.autonomous_context.child_workflow_id
            ):
                raise PermissionError(
                    "Temporal child Workflow id does not match autonomous scope"
                )
            return await asyncio.to_thread(
                self._validate_autonomous_child_sync, job
            )
        except (KeyError, PermissionError, ValueError, RuntimeError) as exc:
            raise self._autonomous_activity_error(exc) from exc

    def _finalize_autonomous_child_sync(
        self, job: AgentFactoryJobInput
    ) -> ActivityResult:
        if job.autonomous_context is None:
            raise PermissionError("AgentFactory job has no autonomous context")
        storage = self._storage(job)
        try:
            mission = AutonomousMissionService(storage).get(
                job.autonomous_context.mission_id
            )
            scope = AutonomousMissionActivityScope(
                mission_id=mission.id,
                mission_identity=mission.identity,
                mission_key=mission.mission_key,
                project_id=mission.project_id,
                workspace=job.workspace,
                database=job.database,
                temporal_workflow_id=job.autonomous_context.child_workflow_id,
                temporal_first_run_id=job.autonomous_context.child_workflow_id,
            )
            delivery = AutonomousCodingDeliveryService(
                storage, self._autonomous_capabilities(scope)
            )
            persisted = self._assert_autonomous_job_binding(delivery, job)
            MissionControlFenceService(storage).assert_allows(
                persisted.mission_id,
                expected_fencing_token=(
                    job.autonomous_context.control_fencing_token
                ),
                execution_epoch_id=persisted.execution_epoch_id,
            )
            completion = delivery.complete_job(
                persisted.id,
                command_id=f"{persisted.child_workflow_id}:complete",
                expected_fencing_token=(
                    job.autonomous_context.control_fencing_token
                ),
            )
            return ActivityResult(
                True,
                summary=(
                    "Autonomous child validation, review, and integration "
                    "evidence accepted without a per-item Founder gate"
                ),
                artifacts=[f"autonomous-completion:{completion.id}"],
                metadata={
                    "child_job_id": persisted.id,
                    "completion_id": completion.id,
                    "completion_digest": completion.completion_digest,
                    "git_commit_sha": completion.git_commit_sha,
                    "per_item_founder_gate": False,
                },
            )
        finally:
            storage.close()

    @activity.defn(name="finalize_autonomous_child_job")
    async def finalize_autonomous_child_job(
        self, job: AgentFactoryJobInput
    ) -> ActivityResult:
        try:
            return await asyncio.to_thread(
                self._finalize_autonomous_child_sync, job
            )
        except (KeyError, PermissionError, ValueError, RuntimeError) as exc:
            raise self._autonomous_activity_error(exc) from exc

    def _reconcile_autonomous_child_sync(
        self, request: AutonomousChildReconciliationInput
    ) -> AutonomousChildReconciliationResult:
        storage = self._autonomous_storage(request.scope)
        try:
            missions = AutonomousMissionService(storage)
            self._assert_autonomous_scope(request.scope, missions)
            delivery = AutonomousCodingDeliveryService(
                storage, self._autonomous_capabilities(request.scope)
            )
            job = delivery.get_job(request.child_job_id)
            MissionControlFenceService(storage).assert_allows(
                job.mission_id,
                expected_fencing_token=request.expected_fencing_token,
                execution_epoch_id=job.execution_epoch_id,
            )
            reconciliation = delivery.reconcile_job(
                request.child_job_id,
                expected_mission_version=request.expected_mission_version,
                command_id=request.command_id,
            )
            completion = delivery.get_completion(reconciliation.completion_id)
            progress = delivery.revisions.progress(request.scope.mission_id)
            return AutonomousChildReconciliationResult(
                mission_id=request.scope.mission_id,
                mission_version=reconciliation.result_mission_version,
                child_job_id=job.id,
                completion_id=completion.id,
                checkpoint_id=reconciliation.checkpoint_id,
                stable_item_id=job.stable_item_id,
                completed_items=int(progress["completed"]),
                total_items=int(progress["total"]),
                summary=(
                    f"Accepted {job.stable_item_id} and committed mission checkpoint"
                ),
                occurred_at=reconciliation.created_at,
            )
        finally:
            storage.close()

    @activity.defn(name="reconcile_autonomous_child_job")
    async def reconcile_autonomous_child_job(
        self, request: AutonomousChildReconciliationInput
    ) -> AutonomousChildReconciliationResult:
        try:
            return await asyncio.to_thread(
                self._reconcile_autonomous_child_sync, request
            )
        except (KeyError, PermissionError, ValueError, RuntimeError) as exc:
            raise self._autonomous_activity_error(exc) from exc

    def _complete_autonomous_mission_sync(
        self, request: AutonomousMissionCompletionInput
    ) -> AutonomousMissionCompletionResult:
        storage = self._autonomous_storage(request.scope)
        try:
            missions = AutonomousMissionService(storage)
            current = self._assert_autonomous_scope(request.scope, missions)
            MissionControlFenceService(storage).assert_allows(
                current.id,
                expected_fencing_token=request.expected_fencing_token,
                execution_epoch_id=current.active_execution_epoch_id,
            )
            delivery = AutonomousCodingDeliveryService(
                storage, self._autonomous_capabilities(request.scope)
            )
            mission = delivery.complete_mission(
                request.scope.mission_id,
                expected_mission_version=request.expected_mission_version,
                command_id=request.command_id,
            )
            progress = delivery.revisions.progress(mission.id)
            return AutonomousMissionCompletionResult(
                mission_id=mission.id,
                mission_version=mission.version,
                phase=mission.phase.value,
                disposition=mission.disposition.value,
                completed_items=int(progress["completed"]),
                total_items=int(progress["total"]),
                summary="Autonomous mission completed its accepted active revision",
                occurred_at=mission.updated_at,
            )
        finally:
            storage.close()

    @activity.defn(name="complete_autonomous_mission")
    async def complete_autonomous_mission(
        self, request: AutonomousMissionCompletionInput
    ) -> AutonomousMissionCompletionResult:
        try:
            return await asyncio.to_thread(
                self._complete_autonomous_mission_sync, request
            )
        except (KeyError, PermissionError, ValueError, RuntimeError) as exc:
            raise self._autonomous_activity_error(exc) from exc

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
        provider_authorization: ProviderExecutionAuthorization | None = None,
    ) -> ProviderResult:
        cancel_event = threading.Event()
        execution = asyncio.create_task(
            asyncio.to_thread(
                runtime.run,
                agent,
                item,
                context,
                provider_authorization,
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

    def _autonomous_execution_agent(
        self,
        storage: SQLiteStorage,
        job: AgentFactoryJobInput,
        template: Agent,
    ) -> tuple[Agent, ProviderExecutionAuthorization | None]:
        context = job.autonomous_context
        if context is None:
            return template, None
        row = storage.db.execute(
            "SELECT * FROM autonomous_child_job_authorizations "
            "WHERE child_job_id=?",
            (context.child_job_id,),
        ).fetchone()
        if not row:
            raise ApplicationError(
                "Autonomous stage lacks persisted provider authority",
                type="CONFIGURATION",
                non_retryable=True,
            )
        authorizations = AutonomousAuthorizationService(storage)
        decision = next(
            (
                value
                for value in authorizations.decisions(context.mission_id)
                if value.id == int(row["decision_id"])
            ),
            None,
        )
        if decision is None:
            raise ApplicationError(
                "Autonomous provider decision disappeared",
                type="CONFIGURATION",
                non_retryable=True,
            )
        provider_authorization = authorizations.provider_authorization(decision)
        authorization = authorizations.get_authorization(
            provider_authorization.authorization_id
        )
        execution_agent = Agent(
            id=provider_authorization.agent_id,
            name=f"Autonomous {template.name}",
            role=str(row["role"]),
            enabled=True,
            provider=(
                "deterministic"
                if job.mode == ExecutionMode.SIMULATION.value
                else provider_authorization.provider
            ),
            instructions=template.instructions,
            permissions=list(authorization.allowed_permissions),
            model=str(row["model"]),
        )
        return (
            execution_agent,
            None
            if job.mode == ExecutionMode.SIMULATION.value
            else provider_authorization,
        )

    async def _await_autonomous_stage_fence(
        self,
        storage: SQLiteStorage,
        request: StageActivityInput,
        stage_label: str,
    ) -> int | None:
        context = request.job.autonomous_context
        if context is None:
            return None
        while True:
            handoff = storage.db.execute(
                """SELECT 1
                     FROM autonomous_epoch_handoff_preparations preparation
                     JOIN autonomous_epoch_handoff_requests request
                       ON request.id=preparation.request_id
                    WHERE request.mission_id=?
                      AND request.expected_child_job_id=?
                      AND request.expected_execution_epoch_id=?
                    LIMIT 1""",
                (
                    context.mission_id,
                    context.child_job_id,
                    context.execution_epoch_id,
                ),
            ).fetchone()
            if handoff:
                return 0
            retry = storage.db.execute(
                """SELECT 1
                     FROM autonomous_mission_retry_requests retry
                     LEFT JOIN autonomous_mission_retry_settlements settlement
                       ON settlement.retry_request_id=retry.id
                    WHERE retry.child_job_id=? AND settlement.id IS NULL""",
                (context.child_job_id,),
            ).fetchone()
            if retry:
                return None
            fence = MissionControlFenceService(storage).current(
                context.mission_id
            )
            if fence.disposition == MissionDisposition.RUNNING.value:
                return fence.fencing_token
            if fence.disposition not in {
                MissionDisposition.PAUSED.value,
                MissionDisposition.STOPPED.value,
            }:
                raise PermissionError(
                    f"Autonomous stage is fenced by {fence.disposition}"
                )
            activity.heartbeat(
                {
                    "job_id": request.job.job_id,
                    "run_id": request.job.run_id,
                    "stage": stage_label,
                    "progress": f"waiting at mission {fence.disposition.lower()} fence",
                    "fencing_token": fence.fencing_token,
                }
            )
            await asyncio.sleep(0.05)

    @activity.defn(name="execute_agentfactory_stage")
    async def execute_stage(self, request: StageActivityInput) -> ActivityResult:
        job = request.job
        stage = request.stage
        stage_label = self._stage_label(request)
        key = f"temporal:{job.job_id}:{stage_label}"
        storage = self._storage(job)
        LOGGER.info("%s stage started", self._correlation(job, "execute_stage"))
        try:
            admitted_fencing_token: int | None = None
            if job.autonomous_context is not None:
                admitted_fencing_token = await self._await_autonomous_stage_fence(
                    storage, request, stage_label
                )
                if admitted_fencing_token == 0:
                    return ActivityResult(
                        True,
                        passed=False,
                        summary=(
                            "Current autonomous child reached its persisted "
                            "epoch handoff boundary"
                        ),
                        metadata={"epoch_handoff_requested": True},
                        failure_class="EPOCH_HANDOFF_REQUESTED",
                    )
                if admitted_fencing_token is None:
                    return ActivityResult(
                        True,
                        passed=False,
                        summary=(
                            "Current autonomous strategy was superseded by a "
                            "persisted retry command"
                        ),
                        metadata={"retry_requested": True},
                        failure_class="RETRY_REQUESTED",
                    )
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
            workflow_agent = self._stage_agent(storage, registry, request)
            agent, provider_authorization = self._autonomous_execution_agent(
                storage, job, workflow_agent
            )
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
            inference_operation_id: str | None = None
            if job.autonomous_context is not None:
                inference_operation_id = (
                    f"{key}:inference:activity-attempt-{activity.info().attempt}"
                )
                while True:
                    token = admitted_fencing_token or (
                        request.control_fencing_token
                        or job.autonomous_context.control_fencing_token
                    )
                    try:
                        LocalInferenceControlGuard(storage).begin(
                            LocalInferenceFenceBinding(
                                mission_id=job.autonomous_context.mission_id,
                                execution_epoch_id=(
                                    job.autonomous_context.execution_epoch_id
                                ),
                                child_job_id=job.autonomous_context.child_job_id,
                                fencing_token=token,
                                role=agent.role,
                                provider_id=agent.provider,
                                model=agent.model_identity,
                            ),
                            request_id=inference_operation_id,
                            request={
                                "stage": stage_label,
                                "repair_iteration": request.repair_iteration,
                                "run_id": job.run_id,
                            },
                        )
                        break
                    except (
                        MissionControlFenceConflictError,
                        MissionSchedulingFencedError,
                    ):
                        admitted_fencing_token = (
                            await self._await_autonomous_stage_fence(
                                storage, request, stage_label
                            )
                        )
                        if admitted_fencing_token == 0:
                            return ActivityResult(
                                True,
                                passed=False,
                                summary=(
                                    "Current autonomous child reached its "
                                    "persisted epoch handoff boundary"
                                ),
                                metadata={"epoch_handoff_requested": True},
                                failure_class="EPOCH_HANDOFF_REQUESTED",
                            )
                        if admitted_fencing_token is None:
                            return ActivityResult(
                                True,
                                passed=False,
                                summary=(
                                    "Current autonomous strategy was superseded "
                                    "before inference admission"
                                ),
                                metadata={"retry_requested": True},
                                failure_class="RETRY_REQUESTED",
                            )
            try:
                provider_result = await self._run_agent_with_heartbeat(
                    runtime,
                    agent,
                    child,
                    self._stage_context(storage, job),
                    job.mode,
                    job,
                    stage_label,
                    provider_authorization,
                )
            finally:
                if inference_operation_id is not None:
                    LocalInferenceControlGuard(storage).finish(
                        inference_operation_id,
                        reason="Autonomous stage inference boundary completed",
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
                workflow_agent.id,
                provider_result.provider,
                f"[execution_mode={job.mode}]\n{provider_result.content}",
                producer={
                    "agent_id": agent.id,
                    "workflow_agent_id": workflow_agent.id,
                    "provider": provider_result.provider,
                    "model": agent.model_identity,
                    "authorization_decision_id": (
                        provider_authorization.decision_id
                        if provider_authorization is not None
                        else None
                    ),
                },
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
                    "workflow_agent": workflow_agent.id,
                    "provider": provider_result.provider,
                    "verdict": verdict,
                    "stage": stage_label,
                    "authorization_decision_id": (
                        provider_authorization.decision_id
                        if provider_authorization is not None
                        else None
                    ),
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
        job = AgentFactoryJobInput.from_dict(payload["job"])
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
