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
from ...config import config_path_for_workspace, load_yaml
from ...models import Budget, ProviderCapabilities, ProviderResult, Status, WorkItem
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
    AutonomousMissionActivityScope,
    AutonomousPlanningActivityInput,
    AutonomousPlanningActivityResult,
    DemoWorkflowInput,
    StageActivityInput,
)
from .policies import classify_error
from .settings import TemporalSettings

LOGGER = logging.getLogger(__name__)
MARKER_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


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
                storage, invoker, capabilities
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
                    missions, revisions, run, report, request
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
