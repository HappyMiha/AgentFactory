import asyncio
import unittest
import uuid
from pathlib import Path

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from agent_factory.autonomous_backlog_approval import (
    AutonomousBacklogApprovalService,
)
from agent_factory.autonomous_mission import (
    AutonomousMissionService,
    MissionControlFenceConflictError,
    MissionDisposition,
    MissionPhase,
)
from agent_factory.autonomous_proposal_verifier import (
    AutonomousProposalVerificationService,
)
from agent_factory.backlog_revisions import BacklogItemStatus, BacklogRevisionService
from agent_factory.coding_delivery import AutonomousCodingDeliveryService
from agent_factory.context_packages import ContextPackageBuilder
from agent_factory.control_plane import (
    MissionControlAction,
    MissionControlCommand,
    MissionControlCommandConflictError,
    MissionControlFenceService,
    MissionOperationKind,
    MissionSchedulingFencedError,
)
from agent_factory.models import Agent, ProviderResult, WorkItem
from agent_factory.orchestration.temporal.activities import AgentFactoryActivities
from agent_factory.orchestration.temporal.client import (
    autonomous_mission_workflow_input,
    signal_autonomous_backlog_approved,
    signal_autonomous_mission_control,
    signal_autonomous_planning,
    start_autonomous_mission_workflow,
)
from agent_factory.orchestration.temporal.models import (
    AutonomousBacklogApprovalNotice,
    AutonomousMissionControlCommand,
)
from agent_factory.orchestration.temporal.settings import TemporalSettings
from agent_factory.orchestration.temporal.workflows import (
    AgentFactoryJobWorkflow,
    AutonomousMissionWorkflow,
)
from agent_factory.providers import Provider
from agent_factory.worker_runtime import (
    DirectCLIProviderDriver,
    DirectCLIWorkerRuntime,
    RuntimeLaunch,
    RuntimeMissionControlBinding,
)
from tests.test_autonomous_child_orchestration import AutonomousChildFixture
from tests.test_autonomous_planning_pipeline import GoldenPlanningInvoker
from tests.test_autonomous_preapproval_workflow import run_git


class ToolResultProvider(Provider):
    name = "mission-control-tool-provider"

    def health(self):
        return {"provider": self.name, "healthy": True}

    def execute(self, agent, item, context, approval=None):
        return ProviderResult(
            True,
            provider=self.name,
            content="bounded worker session",
            metadata={"tool_calls": []},
        )


class AutonomousMissionControlTests(AutonomousChildFixture, unittest.TestCase):
    def setUp(self):
        self.create_fixture()

    def tearDown(self):
        self.close_fixture()

    def development_fixture(self):
        approved = self.approve_fixture()
        delivery = AutonomousCodingDeliveryService(self.storage, self.capabilities)
        mission = delivery.enter_development(
            self.mission.id,
            expected_mission_version=approved.approval.result_mission_version,
            command_id="control-enter-development",
        )
        fence = MissionControlFenceService(self.storage).current(mission.id)
        return approved, delivery, mission, fence

    @staticmethod
    def command(
        mission,
        fence,
        action: MissionControlAction,
        command_id: str,
        *,
        child_job_id: int | None = None,
        reason: str | None = None,
    ) -> MissionControlCommand:
        return MissionControlCommand(
            mission_id=mission.id,
            command_id=command_id,
            action=action,
            actor=mission.mission_owner,
            reason=reason or f"Exercise {action.value.lower()} control",
            expected_mission_version=mission.version,
            expected_fencing_token=fence.fencing_token,
            expected_backlog_revision_id=mission.active_backlog_revision_id,
            expected_execution_epoch_id=mission.active_execution_epoch_id,
            child_job_id=child_job_id,
        )

    def test_pause_resume_is_idempotent_and_fences_every_operation_kind(self):
        _approved, _delivery, development, fence = self.development_fixture()
        control = MissionControlFenceService(self.storage)
        active = control.begin_operation(
            operation_id="pause-race-active-inference",
            mission_id=development.id,
            execution_epoch_id=development.active_execution_epoch_id,
            child_job_id=None,
            operation_kind=MissionOperationKind.INFERENCE,
            expected_fencing_token=fence.fencing_token,
            request={"boundary": "pause-race"},
        )

        pause_command = self.command(
            development,
            fence,
            MissionControlAction.PAUSE,
            "pause-mission-once",
        )
        paused = control.apply(pause_command)
        replay = control.apply(pause_command)
        self.assertEqual(paused.fencing_token, fence.fencing_token + 1)
        self.assertEqual(paused.disposition, MissionDisposition.PAUSED.value)
        self.assertTrue(replay.duplicate)
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_mission_control_commands "
                "WHERE command_id='pause-mission-once'"
            ).fetchone()[0],
            1,
        )
        with self.assertRaises(MissionControlFenceConflictError):
            control.begin_operation(
                operation_id=active.operation_id,
                mission_id=development.id,
                execution_epoch_id=development.active_execution_epoch_id,
                child_job_id=None,
                operation_kind=MissionOperationKind.INFERENCE,
                expected_fencing_token=fence.fencing_token,
                request={"boundary": "pause-race"},
            )
        self.assertEqual(control.finish_operation(active.operation_id).status, "FINISHED")
        with self.assertRaises(MissionControlCommandConflictError):
            control.apply(
                self.command(
                    development,
                    fence,
                    MissionControlAction.PAUSE,
                    "pause-mission-once",
                    reason="Conflicting duplicate payload",
                )
            )

        for kind in MissionOperationKind:
            with self.subTest(kind=kind.value, token="stale"):
                with self.assertRaises(MissionControlFenceConflictError):
                    control.begin_operation(
                        operation_id=f"stale-{kind.value}",
                        mission_id=development.id,
                        execution_epoch_id=development.active_execution_epoch_id,
                        child_job_id=None,
                        operation_kind=kind,
                        expected_fencing_token=fence.fencing_token,
                    )
            with self.subTest(kind=kind.value, token="paused"):
                with self.assertRaises(MissionSchedulingFencedError):
                    control.begin_operation(
                        operation_id=f"paused-{kind.value}",
                        mission_id=development.id,
                        execution_epoch_id=development.active_execution_epoch_id,
                        child_job_id=None,
                        operation_kind=kind,
                        expected_fencing_token=paused.fencing_token,
                    )

        paused_mission = AutonomousMissionService(self.storage).get(development.id)
        with self.assertRaises(MissionControlFenceConflictError):
            control.apply(
                self.command(
                    paused_mission,
                    fence,
                    MissionControlAction.RESUME,
                    "stale-resume",
                )
            )
        resumed = control.apply(
            self.command(
                paused_mission,
                control.current(development.id),
                MissionControlAction.RESUME,
                "resume-mission-once",
            )
        )
        self.assertEqual(resumed.disposition, MissionDisposition.RUNNING.value)
        self.assertEqual(resumed.phase, MissionPhase.DEVELOPMENT.value)

        for ordinal, kind in enumerate(MissionOperationKind, start=1):
            lease = control.begin_operation(
                operation_id=f"resumed-{ordinal}-{kind.value}",
                mission_id=development.id,
                execution_epoch_id=development.active_execution_epoch_id,
                child_job_id=None,
                operation_kind=kind,
                expected_fencing_token=resumed.fencing_token,
            )
            self.assertEqual(control.finish_operation(lease.operation_id).status, "FINISHED")
        self.assertFalse(control.operation_leases(development.id, active_only=True))

    def test_stop_releases_leases_preserves_phase_and_remains_continuable(self):
        _approved, delivery, development, fence = self.development_fixture()
        child = delivery.prepare_job(
            development.id,
            "INFRA-001",
            execution_mode="simulation",
            workflow_definition_id="delivery",
            command_id="stop-child-preparation",
            expected_fencing_token=fence.fencing_token,
        )
        control = MissionControlFenceService(self.storage)
        operation = control.begin_operation(
            operation_id="stop-active-child-inference",
            mission_id=development.id,
            execution_epoch_id=development.active_execution_epoch_id,
            child_job_id=child.id,
            operation_kind=MissionOperationKind.INFERENCE,
            expected_fencing_token=fence.fencing_token,
        )
        stopped = control.apply(
            self.command(
                development,
                fence,
                MissionControlAction.STOP,
                "stop-mission-safe-boundary",
                child_job_id=child.id,
            )
        )
        self.assertEqual(stopped.phase, MissionPhase.DEVELOPMENT.value)
        self.assertEqual(stopped.disposition, MissionDisposition.STOPPED.value)
        self.assertEqual(
            control.operation_leases(development.id, active_only=True)[0].status,
            "RELEASING",
        )
        for kind in MissionOperationKind:
            with self.subTest(kind=kind.value, disposition="stopped"):
                with self.assertRaises(MissionSchedulingFencedError):
                    control.begin_operation(
                        operation_id=f"stopped-{kind.value}",
                        mission_id=development.id,
                        execution_epoch_id=development.active_execution_epoch_id,
                        child_job_id=child.id,
                        operation_kind=kind,
                        expected_fencing_token=stopped.fencing_token,
                    )
        stopped_mission = AutonomousMissionService(self.storage).get(development.id)
        with self.assertRaisesRegex(PermissionError, "safe boundary"):
            control.apply(
                self.command(
                    stopped_mission,
                    control.current(development.id),
                    MissionControlAction.RESUME,
                    "resume-before-stop-settled",
                    child_job_id=child.id,
                )
            )
        self.assertEqual(control.finish_operation(operation.operation_id).status, "RELEASED")
        resumed = control.apply(
            self.command(
                stopped_mission,
                control.current(development.id),
                MissionControlAction.RESUME,
                "resume-before-stop-settled",
                child_job_id=child.id,
            )
        )
        self.assertEqual(resumed.disposition, MissionDisposition.RUNNING.value)
        self.assertEqual(delivery.open_job(development.id).id, child.id)
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_authorization_revocations"
            ).fetchone()[0],
            0,
        )

    def test_retry_creates_one_new_logical_strategy_and_never_replays_completion(self):
        _approved, delivery, development, fence = self.development_fixture()
        first = delivery.prepare_job(
            development.id,
            "INFRA-001",
            execution_mode="simulation",
            workflow_definition_id="delivery",
            command_id="retry-first-child",
            expected_fencing_token=fence.fencing_token,
        )
        control = MissionControlFenceService(self.storage)
        operation = control.begin_operation(
            operation_id="retry-active-inference",
            mission_id=development.id,
            execution_epoch_id=development.active_execution_epoch_id,
            child_job_id=first.id,
            operation_kind=MissionOperationKind.INFERENCE,
            expected_fencing_token=fence.fencing_token,
        )
        retry_command = self.command(
            development,
            fence,
            MissionControlAction.RETRY_CURRENT_TASK,
            "retry-current-infra",
            child_job_id=first.id,
        )
        requested = control.apply(retry_command)
        replay = control.apply(retry_command)
        self.assertEqual(requested.logical_attempt, 2)
        self.assertTrue(replay.duplicate)
        self.assertEqual(control.finish_operation(operation.operation_id).status, "RELEASED")
        settlement = control.settle_retry(
            first.id, command_id="retry-current-infra:settle"
        )
        self.assertEqual(settlement.next_logical_attempt, 2)
        self.assertIsNone(delivery.open_job(development.id))
        item = BacklogRevisionService(self.storage).item(
            first.backlog_revision_id, first.stable_item_id
        )
        self.assertEqual(item.status, BacklogItemStatus.READY)

        second = delivery.prepare_job(
            development.id,
            "INFRA-001",
            execution_mode="simulation",
            workflow_definition_id="delivery",
            command_id="retry-second-child",
            expected_fencing_token=requested.fencing_token,
        )
        self.assertEqual(second.logical_attempt, 2)
        self.assertNotEqual(second.child_workflow_id, first.child_workflow_id)
        delivery.authorize_job(
            second.id, command_id=f"{second.child_workflow_id}:authorize"
        )
        self.persist_passing_stage_evidence(second)
        delivery.complete_job(
            second.id,
            command_id=f"{second.child_workflow_id}:complete",
            expected_fencing_token=requested.fencing_token,
        )
        current = AutonomousMissionService(self.storage).get(development.id)
        with self.assertRaisesRegex(ValueError, "completed item"):
            control.apply(
                self.command(
                    current,
                    control.current(development.id),
                    MissionControlAction.RETRY_CURRENT_TASK,
                    "retry-completed-infra",
                    child_job_id=second.id,
                )
            )

    def test_worker_multi_tool_session_rechecks_the_mission_fence(self):
        _approved, delivery, development, fence = self.development_fixture()
        child = delivery.prepare_job(
            development.id,
            "INFRA-001",
            execution_mode="simulation",
            workflow_definition_id="delivery",
            command_id="worker-fence-child",
            expected_fencing_token=fence.fencing_token,
        )
        task_id = self.storage.create_task(
            WorkItem(
                "Worker fence task",
                "Exercise per-tool mission admission",
                development.project_id,
                permissions=["read_project"],
            )
        )
        run_id = self.storage.start_durable_run(
            project_id=development.project_id,
            task_id=task_id,
            workflow_id="worker-fence-runtime",
            workflow_version="1",
            definition={"id": "worker-fence-runtime"},
            stages=[{"id": "runtime", "depends_on": []}],
        )
        self.storage.transition_durable_stage(
            run_id, "runtime", "running", {"reason": "mission control test"}
        )
        claim = self.storage.claim_runnable_task(
            task_id, "worker-fence-agent", "direct-cli"
        )
        package = ContextPackageBuilder(self.storage, Path(self.temporary.name)).build(
            task_id=task_id,
            run_id=run_id,
            assignment_id=claim.assignment_id,
            fencing_token=claim.fencing_token,
            base_sha="a" * 40,
        )
        agent = Agent(
            "worker-fence-agent",
            "Worker fence agent",
            "Implementation Worker",
            True,
            ToolResultProvider.name,
            "Return bounded evidence",
        )
        binding = RuntimeMissionControlBinding(
            mission_id=development.id,
            execution_epoch_id=development.active_execution_epoch_id,
            child_job_id=child.id,
            fencing_token=fence.fencing_token,
        )
        runtime = DirectCLIWorkerRuntime(
            self.storage, DirectCLIProviderDriver(ToolResultProvider())
        )
        session = runtime.start(
            RuntimeLaunch(
                claim.assignment_id,
                claim.fencing_token,
                agent,
                self.storage.get_task(task_id),
                package.payload,
                package.digest,
                mission_control=binding,
            )
        )
        current_tool = runtime.admit_tool_operation(
            session.id,
            operation_id="worker-tool-current",
            tool_name="read_file",
        )
        control = MissionControlFenceService(self.storage)
        paused = control.apply(
            self.command(
                development,
                fence,
                MissionControlAction.PAUSE,
                "pause-multi-tool-worker",
                child_job_id=child.id,
            )
        )
        runtime.finish_tool_operation(
            current_tool, reason="Current worker tool completed after pause"
        )
        with self.assertRaises(MissionControlFenceConflictError):
            runtime.admit_tool_operation(
                session.id,
                operation_id="worker-tool-stale",
                tool_name="run_command",
            )
        paused_binding = RuntimeMissionControlBinding(
            mission_id=development.id,
            execution_epoch_id=development.active_execution_epoch_id,
            child_job_id=child.id,
            fencing_token=paused.fencing_token,
        )
        with self.assertRaises(MissionSchedulingFencedError):
            runtime.admit_tool_operation(
                session.id,
                operation_id="worker-tool-paused",
                tool_name="run_command",
                mission_control=paused_binding,
            )
        paused_mission = AutonomousMissionService(self.storage).get(development.id)
        resumed = control.apply(
            self.command(
                paused_mission,
                control.current(development.id),
                MissionControlAction.RESUME,
                "resume-multi-tool-worker",
                child_job_id=child.id,
            )
        )
        resumed_binding = RuntimeMissionControlBinding(
            mission_id=development.id,
            execution_epoch_id=development.active_execution_epoch_id,
            child_job_id=child.id,
            fencing_token=resumed.fencing_token,
        )
        next_tool = runtime.admit_tool_operation(
            session.id,
            operation_id="worker-tool-resumed",
            tool_name="run_command",
            mission_control=resumed_binding,
        )
        runtime.finish_tool_operation(next_tool, reason="Resumed worker tool completed")


class BlockingAgentFactoryActivities(AgentFactoryActivities):
    def __init__(self, *args, stage_started: asyncio.Event, release_stage: asyncio.Event, **kwargs):
        super().__init__(*args, **kwargs)
        self.stage_started = stage_started
        self.release_stage = release_stage
        self.calls = 0

    async def _run_agent_with_heartbeat(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            self.stage_started.set()
            await self.release_stage.wait()
        return await super()._run_agent_with_heartbeat(*args, **kwargs)


class AutonomousMissionControlTemporalTests(
    AutonomousChildFixture, unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self):
        self.create_fixture()
        self.environment = await WorkflowEnvironment.start_time_skipping()
        self.task_queue = f"mission-control-{uuid.uuid4().hex}"
        self.settings = TemporalSettings(
            task_queue=self.task_queue,
            fast_activity_timeout_seconds=30,
            llm_activity_timeout_seconds=120,
            heartbeat_interval_seconds=1,
            heartbeat_timeout_seconds=5,
        )
        self.stage_started = asyncio.Event()
        self.release_stage = asyncio.Event()
        self.activities = BlockingAgentFactoryActivities(
            self.settings,
            stage_started=self.stage_started,
            release_stage=self.release_stage,
            autonomous_planning_invoker=GoldenPlanningInvoker(),
            autonomous_provider_capabilities=self.capabilities,
        )
        self.request = autonomous_mission_workflow_input(
            self.mission,
            workspace=str(self.repository),
            database=str(self.database),
            temporal_settings=self.settings,
            post_approval_execution_enabled=True,
            autonomous_child_execution_mode="simulation",
        )

    async def asyncTearDown(self):
        await self.environment.shutdown()
        self.close_fixture()

    def worker(self):
        return Worker(
            self.environment.client,
            task_queue=self.task_queue,
            workflows=[AutonomousMissionWorkflow, AgentFactoryJobWorkflow],
            activities=[
                self.activities.run_autonomous_planning,
                self.activities.revalidate_autonomous_approval,
                self.activities.read_autonomous_mission_control_fence,
                self.activities.apply_autonomous_mission_control,
                self.activities.settle_autonomous_child_retry,
                self.activities.enter_autonomous_development,
                self.activities.prepare_autonomous_child_job,
                self.activities.validate_autonomous_child_job,
                self.activities.load_project_context,
                self.activities.execute_stage,
                self.activities.finalize_autonomous_child_job,
                self.activities.fail_job,
                self.activities.reconcile_autonomous_child_job,
                self.activities.complete_autonomous_mission,
            ],
        )

    async def wait_for(self, predicate, attempts: int = 400):
        for _ in range(attempts):
            value = predicate()
            if value:
                return value
            await asyncio.sleep(0.025)
        self.fail("Timed out waiting for persisted mission control state")

    async def prepare_running_mission(self, handle, started):
        await signal_autonomous_planning(
            self.environment.client,
            self.mission.id,
            self.planning_command(1),
            self.settings,
        )
        waiting = None
        for _ in range(400):
            state = await handle.query("get_mission_status", result_type=dict)
            if state["phase"] == MissionPhase.WAITING_FOR_BACKLOG_APPROVAL.value:
                waiting = state
                break
            await asyncio.sleep(0.025)
        self.assertIsNotNone(waiting)
        report = AutonomousProposalVerificationService(self.storage).get(
            waiting["proposal_verification_id"]
        )
        branch = "autonomous/AFM-TEMPORAL-PREAPPROVAL/epoch-1"
        run_git(self.repository, "checkout", "-b", branch)
        mission = AutonomousMissionService(self.storage).get(self.mission.id)
        approved = AutonomousBacklogApprovalService(
            self.storage, self.capabilities
        ).approve_and_start(
            report.id,
            expected_revision_id=report.revision_id,
            expected_canonical_digest=report.canonical_digest,
            expected_mission_version=mission.version,
            base_git_commit_sha=self.base_commit,
            epoch_branch=branch,
            temporal_workflow_id=started.workflow_id,
            temporal_run_id=started.run_id,
            actor="Founder",
            command_id=f"approve-control-{uuid.uuid4().hex}",
            reason="Approve exact backlog for mission control test",
            authentication_context={
                "schema_version": 1,
                "method": "authenticated-local-session",
                "subject": "Founder",
                "session_id": "mission-control-temporal",
            },
        )
        await signal_autonomous_backlog_approved(
            self.environment.client,
            self.mission.id,
            AutonomousBacklogApprovalNotice(
                notice_id=f"control-approval-{uuid.uuid4().hex}",
                claimed_approval_id=approved.approval.id,
            ),
            self.settings,
        )
        await asyncio.wait_for(self.stage_started.wait(), timeout=30)

    def temporal_command(self, action: str, command_id: str):
        mission = AutonomousMissionService(self.storage).get(self.mission.id)
        fence = MissionControlFenceService(self.storage).current(self.mission.id)
        child = self.storage.db.execute(
            """SELECT id FROM autonomous_child_jobs
                WHERE mission_id=? ORDER BY id DESC LIMIT 1""",
            (self.mission.id,),
        ).fetchone()
        return AutonomousMissionControlCommand(
            mission_id=mission.id,
            command_id=command_id,
            action=action,
            actor=mission.mission_owner,
            reason=f"Temporal {action.lower()} race test",
            expected_mission_version=mission.version,
            expected_fencing_token=fence.fencing_token,
            expected_backlog_revision_id=mission.active_backlog_revision_id,
            expected_execution_epoch_id=mission.active_execution_epoch_id,
            child_job_id=int(child["id"]) if child else None,
        )

    async def test_pause_propagates_to_active_child_and_blocks_the_next_inference(self):
        async with self.worker():
            started = await start_autonomous_mission_workflow(
                self.environment.client, self.request, self.settings
            )
            handle = self.environment.client.get_workflow_handle(started.workflow_id)
            await self.prepare_running_mission(handle, started)
            before = self.temporal_command("PAUSE", "temporal-pause-active-child")
            await signal_autonomous_mission_control(
                self.environment.client, before, self.settings
            )
            await self.wait_for(
                lambda: (
                    AutonomousMissionService(self.storage)
                    .get(self.mission.id)
                    .disposition
                    is MissionDisposition.PAUSED
                )
            )
            self.release_stage.set()
            await self.wait_for(
                lambda: not MissionControlFenceService(self.storage).operation_leases(
                    self.mission.id, active_only=True
                )
            )
            inference_count = self.activities.calls
            await asyncio.sleep(0.2)
            self.assertEqual(self.activities.calls, inference_count)
            paused_mission = AutonomousMissionService(self.storage).get(self.mission.id)
            stale = AutonomousMissionControlCommand(
                mission_id=paused_mission.id,
                command_id="temporal-stale-resume",
                action="RESUME",
                actor=paused_mission.mission_owner,
                reason="Reject stale fencing token",
                expected_mission_version=paused_mission.version,
                expected_fencing_token=before.expected_fencing_token,
                expected_backlog_revision_id=paused_mission.active_backlog_revision_id,
                expected_execution_epoch_id=paused_mission.active_execution_epoch_id,
                child_job_id=before.child_job_id,
            )
            await signal_autonomous_mission_control(
                self.environment.client, stale, self.settings
            )
            await asyncio.sleep(0.2)
            self.assertIs(
                AutonomousMissionService(self.storage).get(self.mission.id).disposition,
                MissionDisposition.PAUSED,
            )
            resume = self.temporal_command(
                "RESUME", "temporal-resume-active-child"
            )
            await signal_autonomous_mission_control(
                self.environment.client, resume, self.settings
            )
            await signal_autonomous_mission_control(
                self.environment.client, before, self.settings
            )
            result = await asyncio.wait_for(handle.result(), timeout=60)

        self.assertEqual(result["workflow_status"], "COMPLETED")
        self.assertEqual(result["completed_items"], 2)
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_mission_control_commands"
            ).fetchone()[0],
            2,
        )

    async def test_duplicate_retry_signal_creates_one_new_child_attempt(self):
        async with self.worker():
            started = await start_autonomous_mission_workflow(
                self.environment.client, self.request, self.settings
            )
            handle = self.environment.client.get_workflow_handle(started.workflow_id)
            await self.prepare_running_mission(handle, started)
            retry = self.temporal_command(
                "RETRY_CURRENT_TASK", "temporal-retry-active-child"
            )
            await signal_autonomous_mission_control(
                self.environment.client, retry, self.settings
            )
            await signal_autonomous_mission_control(
                self.environment.client, retry, self.settings
            )
            await self.wait_for(
                lambda: self.storage.db.execute(
                    "SELECT COUNT(*) FROM autonomous_mission_retry_requests"
                ).fetchone()[0]
                == 1
            )
            self.release_stage.set()
            result = await asyncio.wait_for(handle.result(), timeout=60)

        self.assertEqual(result["workflow_status"], "COMPLETED")
        jobs = self.storage.db.execute(
            """SELECT stable_item_id,logical_attempt FROM autonomous_child_jobs
                ORDER BY id"""
        ).fetchall()
        self.assertEqual(
            [(str(row["stable_item_id"]), int(row["logical_attempt"])) for row in jobs],
            [("INFRA-001", 1), ("INFRA-001", 2), ("DEV-001", 1)],
        )
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_mission_retry_settlements"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_child_delivery_completions"
            ).fetchone()[0],
            2,
        )


if __name__ == "__main__":
    unittest.main()
