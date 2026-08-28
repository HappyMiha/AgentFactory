import asyncio
import unittest
import uuid
from unittest.mock import patch

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from agent_factory.autonomous_mission import AutonomousMissionService, MissionDisposition
from agent_factory.backlog import BacklogProposal
from agent_factory.backlog_revisions import (
    BacklogRevisionOrigin,
    BacklogRevisionService,
)
from agent_factory.coding_delivery import AutonomousCodingDeliveryService
from agent_factory.control_plane import (
    MissionControlFenceService,
    MissionOperationKind,
)
from agent_factory.mission_checkpoints import (
    EpochHandoffAction,
    EpochHandoffCommandConflictError,
    EpochHandoffNotReadyError,
    ExecutionEpochOrigin,
    MissionCheckpointService,
)
from agent_factory.orchestration.temporal.activities import AgentFactoryActivities
from agent_factory.orchestration.temporal.client import (
    autonomous_mission_workflow_input,
    signal_autonomous_backlog_approved,
    signal_autonomous_epoch_handoff,
    signal_autonomous_planning,
    start_autonomous_mission_workflow,
)
from agent_factory.orchestration.temporal.models import (
    AutonomousBacklogApprovalNotice,
    AutonomousEpochHandoffCommand,
    AutonomousEpochHandoffPreparationInput,
)
from agent_factory.orchestration.temporal.settings import TemporalSettings
from agent_factory.orchestration.temporal.workflows import (
    AgentFactoryJobWorkflow,
    AutonomousMissionWorkflow,
)
from agent_factory.autonomous_backlog_approval import AutonomousBacklogApprovalService
from agent_factory.autonomous_mission import MissionPhase
from agent_factory.autonomous_proposal_verifier import (
    AutonomousProposalVerificationService,
)
from tests.test_autonomous_child_orchestration import AutonomousChildFixture
from tests.test_autonomous_planning_pipeline import GoldenPlanningInvoker
from tests.test_autonomous_preapproval_workflow import run_git


class AutonomousEpochHandoffTests(AutonomousChildFixture, unittest.TestCase):
    def setUp(self):
        self.create_fixture()

    def tearDown(self):
        self.close_fixture()

    def checkpoint_fixture(self, *, prepare_active_child: bool):
        approved = self.approve_fixture()
        delivery = AutonomousCodingDeliveryService(self.storage, self.capabilities)
        development = delivery.enter_development(
            self.mission.id,
            expected_mission_version=approved.approval.result_mission_version,
            command_id="handoff-enter-development",
        )
        first = delivery.prepare_job(
            self.mission.id,
            "INFRA-001",
            execution_mode="simulation",
            workflow_definition_id="delivery",
            command_id="handoff-prepare-infra",
        )
        delivery.authorize_job(
            first.id, command_id=f"{first.child_workflow_id}:authorize"
        )
        self.persist_passing_stage_evidence(first)
        delivery.complete_job(
            first.id, command_id=f"{first.child_workflow_id}:complete"
        )
        reconciled = delivery.reconcile_job(
            first.id,
            expected_mission_version=development.version,
            command_id="handoff-reconcile-infra",
        )
        mission = AutonomousMissionService(self.storage).get(self.mission.id)
        child = None
        if prepare_active_child:
            fence = MissionControlFenceService(self.storage).current(mission.id)
            child = delivery.prepare_job(
                mission.id,
                "DEV-001",
                execution_mode="simulation",
                workflow_definition_id="delivery",
                command_id="handoff-prepare-dev-old-epoch",
                expected_fencing_token=fence.fencing_token,
            )
        return delivery, mission, reconciled.checkpoint_id, child

    @staticmethod
    def signal_claims(request):
        return {
            "mission_id": request.mission_id,
            "action": request.action,
            "expected_mission_version": request.expected_mission_version,
            "expected_fencing_token": request.expected_fencing_token,
            "expected_backlog_revision_id": request.expected_backlog_revision_id,
            "expected_execution_epoch_id": request.expected_execution_epoch_id,
            "expected_child_job_id": request.expected_child_job_id,
            "selected_checkpoint_id": request.selected_checkpoint_id,
            "selected_backlog_revision_id": request.selected_backlog_revision_id,
        }

    def authorize_checkpoint_restart(self, mission, checkpoint_id, child_id=None):
        fence = MissionControlFenceService(self.storage).current(mission.id)
        return MissionCheckpointService(
            self.storage, self.capabilities
        ).authorize_epoch_handoff(
            mission.id,
            action=EpochHandoffAction.RESTART_FROM_CHECKPOINT,
            selected_checkpoint_id=checkpoint_id,
            selected_backlog_revision_id=mission.active_backlog_revision_id,
            expected_mission_version=mission.version,
            expected_fencing_token=fence.fencing_token,
            expected_execution_epoch_id=mission.active_execution_epoch_id,
            expected_child_job_id=child_id,
            actor=mission.mission_owner,
            command_id="restart-from-checkpoint-1",
            reason="Restart from the last accepted checkpoint",
            epoch_branch="autonomous/AFM-TEMPORAL-PREAPPROVAL/epoch-2",
            authentication_context={
                "schema_version": 1,
                "method": "authenticated-local-session",
                "subject": mission.mission_owner,
                "session_id": "epoch-handoff-test",
            },
        )

    def test_checkpoint_restart_waits_for_safe_boundary_and_replays_one_epoch(self):
        delivery, mission, checkpoint_id, child = self.checkpoint_fixture(
            prepare_active_child=True
        )
        self.assertIsNotNone(child)
        checkpoints = MissionCheckpointService(self.storage, self.capabilities)
        request = self.authorize_checkpoint_restart(mission, checkpoint_id, child.id)
        with self.assertRaises(EpochHandoffCommandConflictError):
            checkpoints.authorize_epoch_handoff(
                mission.id,
                action=request.action,
                selected_checkpoint_id=checkpoint_id,
                selected_backlog_revision_id=mission.active_backlog_revision_id,
                expected_mission_version=mission.version,
                expected_fencing_token=request.expected_fencing_token,
                expected_execution_epoch_id=mission.active_execution_epoch_id,
                expected_child_job_id=child.id,
                actor=mission.mission_owner,
                command_id=request.command_id,
                reason="Conflicting command reuse",
                epoch_branch=request.epoch_branch,
                authentication_context=request.authentication_context,
            )

        operation = MissionControlFenceService(self.storage).begin_operation(
            operation_id="epoch-handoff-active-operation",
            mission_id=mission.id,
            execution_epoch_id=mission.active_execution_epoch_id,
            child_job_id=child.id,
            operation_kind=MissionOperationKind.INFERENCE,
            expected_fencing_token=request.expected_fencing_token,
        )
        with self.assertRaisesRegex(PermissionError, "persisted owner command"):
            checkpoints.begin_epoch_handoff(
                request.command_id,
                **{
                    **self.signal_claims(request),
                    "selected_checkpoint_id": checkpoint_id + 999,
                },
            )
        prepared = checkpoints.begin_epoch_handoff(
            request.command_id, **self.signal_claims(request)
        )
        self.assertIs(
            AutonomousMissionService(self.storage).get(mission.id).disposition,
            MissionDisposition.STOPPED,
        )
        with self.assertRaises(EpochHandoffNotReadyError):
            checkpoints.complete_epoch_handoff(request.command_id)
        MissionControlFenceService(self.storage).finish_operation(operation.operation_id)

        original_event = self.storage._event

        def lose_completion(event_type, entity_type, entity_id, payload):
            if event_type == "autonomous_mission.epoch_handoff_completed":
                raise RuntimeError("simulated lost handoff Activity completion")
            return original_event(event_type, entity_type, entity_id, payload)

        with patch.object(self.storage, "_event", side_effect=lose_completion):
            with self.assertRaisesRegex(RuntimeError, "lost handoff"):
                checkpoints.complete_epoch_handoff(request.command_id)
        self.assertEqual(len(checkpoints.list_epochs(mission.id)), 2)
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_epoch_handoff_results"
            ).fetchone()[0],
            0,
        )
        result = checkpoints.complete_epoch_handoff(request.command_id)
        replay_preparation = checkpoints.begin_epoch_handoff(
            request.command_id, **self.signal_claims(request)
        )
        replay_result = checkpoints.complete_epoch_handoff(request.command_id)
        self.assertTrue(replay_preparation.duplicate)
        self.assertTrue(replay_result.duplicate)
        self.assertEqual(result.result_execution_epoch_id, replay_result.result_execution_epoch_id)
        self.assertEqual(
            len(checkpoints.list_epochs(mission.id)),
            2,
        )
        epoch = checkpoints.get_epoch(result.result_execution_epoch_id)
        self.assertEqual(epoch.origin, ExecutionEpochOrigin.CHECKPOINT_RESTART)
        self.assertEqual(epoch.supersedes_epoch_id, mission.active_execution_epoch_id)
        current = AutonomousMissionService(self.storage).get(mission.id)
        self.assertIs(current.disposition, MissionDisposition.RUNNING)
        self.assertEqual(current.active_execution_epoch_id, epoch.id)
        self.assertEqual(current.current_checkpoint_id, checkpoint_id)
        self.assertIsNone(delivery.open_job(mission.id))

        next_fence = MissionControlFenceService(self.storage).current(mission.id)
        replacement = delivery.prepare_job(
            mission.id,
            "DEV-001",
            execution_mode="simulation",
            workflow_definition_id="delivery",
            command_id="handoff-prepare-dev-new-epoch",
            expected_fencing_token=next_fence.fencing_token,
        )
        self.assertEqual(replacement.execution_epoch_id, epoch.id)
        self.assertEqual(replacement.authorization_id, result.execution_authorization_id)
        self.assertNotEqual(replacement.child_workflow_id, child.child_workflow_id)
        self.assertEqual(prepared.child_job_id, child.id)

    def test_signal_is_not_authority_and_activity_rejects_spoofed_scope(self):
        _delivery, mission, checkpoint_id, child = self.checkpoint_fixture(
            prepare_active_child=True
        )
        request = self.authorize_checkpoint_restart(mission, checkpoint_id, child.id)
        command = AutonomousEpochHandoffCommand(
            mission_id=mission.id + 1,
            command_id=request.command_id,
            action=request.action.value,
            expected_mission_version=request.expected_mission_version,
            expected_fencing_token=request.expected_fencing_token,
            expected_backlog_revision_id=request.expected_backlog_revision_id,
            expected_execution_epoch_id=request.expected_execution_epoch_id,
            expected_child_job_id=request.expected_child_job_id,
            selected_checkpoint_id=request.selected_checkpoint_id,
            selected_backlog_revision_id=request.selected_backlog_revision_id,
        )
        activities = AgentFactoryActivities(
            autonomous_provider_capabilities=self.capabilities
        )
        with self.assertRaisesRegex(PermissionError, "spoofed"):
            activities._prepare_autonomous_epoch_handoff_sync(
                AutonomousEpochHandoffPreparationInput(
                    scope=self.activity_scope(), command=command
                )
            )

    def test_applied_revision_handoff_uses_revision_authority(self):
        delivery, mission, checkpoint_id, _child = self.checkpoint_fixture(
            prepare_active_child=False
        )
        revisions = BacklogRevisionService(self.storage)
        parent = revisions.get_revision(mission.active_backlog_revision_id)
        proposed = BacklogProposal(
            source_path="memory://authorized-revision-2.json",
            source_sha256="b" * 64,
            source_name="Authorized revision 2",
            items=parent.items,
            schema_version=parent.schema_version,
            extension_schema="agentfactory.rich-backlog/v1",
            planning_contract={"execution_rule": "Only tasks execute"},
        )
        revision = revisions.create_revision(
            mission_id=mission.id,
            proposal=proposed,
            origin=BacklogRevisionOrigin.HUMAN,
            created_by=mission.mission_owner,
            command_id="create-authorized-handoff-revision",
            rationale="Persist a human revision before epoch handoff",
            parent_revision_id=parent.id,
        )
        applied = revisions.apply_revision(
            revision.id,
            actor=mission.mission_owner,
            command_id="apply-authorized-handoff-revision",
            expected_mission_version=mission.version,
            reason="Apply the exact human revision",
        )
        fence = MissionControlFenceService(self.storage).current(mission.id)
        request = revisions.authorize_epoch_handoff(
            revision.id,
            selected_checkpoint_id=checkpoint_id,
            expected_mission_version=applied.mission.version,
            expected_fencing_token=fence.fencing_token,
            expected_execution_epoch_id=applied.mission.active_execution_epoch_id,
            expected_child_job_id=None,
            actor=mission.mission_owner,
            command_id="apply-revision-epoch-handoff",
            reason="Restart the applied revision from the accepted checkpoint",
            epoch_branch="autonomous/AFM-TEMPORAL-PREAPPROVAL/revision-2-epoch",
        )
        checkpoints = MissionCheckpointService(self.storage, self.capabilities)
        checkpoints.begin_epoch_handoff(
            request.command_id, **self.signal_claims(request)
        )
        result = checkpoints.complete_epoch_handoff(request.command_id)
        epoch = checkpoints.get_epoch(result.result_execution_epoch_id)
        self.assertEqual(epoch.origin, ExecutionEpochOrigin.BACKLOG_REVISION_RESTART)
        self.assertEqual(epoch.base_backlog_revision_id, revision.id)
        self.assertEqual(result.selected_checkpoint_id, checkpoint_id)
        self.assertEqual(
            delivery.prepare_job(
                mission.id,
                "DEV-001",
                execution_mode="simulation",
                workflow_definition_id="delivery",
                command_id="prepare-after-revision-handoff",
                expected_fencing_token=result.result_fencing_token,
            ).execution_epoch_id,
            epoch.id,
        )


class EpochHandoffBlockingActivities(AgentFactoryActivities):
    def __init__(
        self,
        *args,
        second_child_started: asyncio.Event,
        release_second_child: asyncio.Event,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.second_child_started = second_child_started
        self.release_second_child = release_second_child
        self.calls = 0

    async def _run_agent_with_heartbeat(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 5:
            self.second_child_started.set()
            await self.release_second_child.wait()
        return await super()._run_agent_with_heartbeat(*args, **kwargs)


class AutonomousEpochHandoffTemporalTests(
    AutonomousChildFixture, unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self):
        self.create_fixture()
        self.environment = await WorkflowEnvironment.start_time_skipping()
        self.task_queue = f"epoch-handoff-{uuid.uuid4().hex}"
        self.settings = TemporalSettings(
            task_queue=self.task_queue,
            fast_activity_timeout_seconds=30,
            llm_activity_timeout_seconds=120,
            heartbeat_interval_seconds=1,
            heartbeat_timeout_seconds=5,
        )
        self.second_child_started = asyncio.Event()
        self.release_second_child = asyncio.Event()
        self.activities = EpochHandoffBlockingActivities(
            self.settings,
            second_child_started=self.second_child_started,
            release_second_child=self.release_second_child,
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
                self.activities.prepare_autonomous_epoch_handoff,
                self.activities.complete_autonomous_epoch_handoff,
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

    async def wait_for(self, predicate, attempts: int = 600):
        for _ in range(attempts):
            value = predicate()
            if value:
                return value
            await asyncio.sleep(0.025)
        self.fail("Timed out waiting for epoch handoff state")

    async def approve_running_mission(self, handle, started):
        await signal_autonomous_planning(
            self.environment.client,
            self.mission.id,
            self.planning_command(1),
            self.settings,
        )
        waiting = None
        for _ in range(600):
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
            command_id=f"approve-epoch-handoff-{uuid.uuid4().hex}",
            reason="Approve exact backlog for epoch handoff test",
            authentication_context={
                "schema_version": 1,
                "method": "authenticated-local-session",
                "subject": "Founder",
                "session_id": "epoch-handoff-temporal",
            },
        )
        await signal_autonomous_backlog_approved(
            self.environment.client,
            self.mission.id,
            AutonomousBacklogApprovalNotice(
                notice_id=f"epoch-handoff-approval-{uuid.uuid4().hex}",
                claimed_approval_id=approved.approval.id,
            ),
            self.settings,
        )

    async def test_active_child_reaches_boundary_and_parent_resumes_new_epoch(self):
        async with self.worker():
            started = await start_autonomous_mission_workflow(
                self.environment.client, self.request, self.settings
            )
            handle = self.environment.client.get_workflow_handle(started.workflow_id)
            await self.approve_running_mission(handle, started)
            await asyncio.wait_for(self.second_child_started.wait(), timeout=60)
            state = await handle.query("get_mission_status", result_type=dict)
            self.assertIsNotNone(state["current_checkpoint_id"])
            self.assertIsNotNone(state["current_child_job_id"])
            mission = AutonomousMissionService(self.storage).get(self.mission.id)
            fence = MissionControlFenceService(self.storage).current(mission.id)
            epoch_branch = "autonomous/AFM-TEMPORAL-PREAPPROVAL/epoch-2"
            # AF-AMM-021 owns Git restoration; this AF-016 orchestration test
            # supplies its already-materialized destination branch fixture.
            run_git(self.repository, "checkout", "-b", epoch_branch)
            request = MissionCheckpointService(
                self.storage, self.capabilities
            ).authorize_epoch_handoff(
                mission.id,
                action=EpochHandoffAction.RESTART_FROM_CHECKPOINT,
                selected_checkpoint_id=state["current_checkpoint_id"],
                selected_backlog_revision_id=mission.active_backlog_revision_id,
                expected_mission_version=mission.version,
                expected_fencing_token=fence.fencing_token,
                expected_execution_epoch_id=mission.active_execution_epoch_id,
                expected_child_job_id=state["current_child_job_id"],
                actor=mission.mission_owner,
                command_id="temporal-restart-from-checkpoint",
                reason="Restart while the current child is inside an atomic Activity",
                epoch_branch=epoch_branch,
            )
            command = AutonomousEpochHandoffCommand(
                mission_id=request.mission_id,
                command_id=request.command_id,
                action=request.action.value,
                expected_mission_version=request.expected_mission_version,
                expected_fencing_token=request.expected_fencing_token,
                expected_backlog_revision_id=request.expected_backlog_revision_id,
                expected_execution_epoch_id=request.expected_execution_epoch_id,
                expected_child_job_id=request.expected_child_job_id,
                selected_checkpoint_id=request.selected_checkpoint_id,
                selected_backlog_revision_id=request.selected_backlog_revision_id,
            )
            await signal_autonomous_epoch_handoff(
                self.environment.client, command, self.settings
            )
            await signal_autonomous_epoch_handoff(
                self.environment.client, command, self.settings
            )
            await self.wait_for(
                lambda: self.storage.db.execute(
                    "SELECT COUNT(*) FROM autonomous_epoch_handoff_preparations"
                ).fetchone()[0]
                == 1
            )
            self.release_second_child.set()
            terminal_state = None
            for _ in range(1200):
                terminal_state = await handle.query(
                    "get_mission_status", result_type=dict
                )
                if terminal_state["workflow_status"] == "COMPLETED":
                    break
                await asyncio.sleep(0.025)
            child_state = await self.environment.client.get_workflow_handle(
                state["current_child_workflow_id"]
            ).query("get_status", result_type=dict)
            leases = [
                dict(row)
                for row in self.storage.db.execute(
                    """SELECT operation_id,status FROM autonomous_mission_operation_leases
                        WHERE mission_id=? ORDER BY id""",
                    (self.mission.id,),
                )
            ]
            self.assertEqual(
                terminal_state["workflow_status"],
                "COMPLETED",
                {
                    "parent": terminal_state,
                    "child": child_state,
                    "leases": leases,
                },
            )
            result = await asyncio.wait_for(handle.result(), timeout=30)

        self.assertEqual(result["workflow_status"], "COMPLETED")
        self.assertEqual(result["completed_items"], 2)
        self.assertEqual(result["last_epoch_handoff_command_id"], command.command_id)
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_epoch_handoff_results"
            ).fetchone()[0],
            1,
        )
        epochs = MissionCheckpointService(self.storage).list_epochs(self.mission.id)
        self.assertEqual(len(epochs), 2)
        self.assertEqual(
            result["active_execution_epoch_id"], epochs[-1].id
        )
        jobs = self.storage.db.execute(
            """SELECT execution_epoch_id,stable_item_id FROM autonomous_child_jobs
                ORDER BY id"""
        ).fetchall()
        self.assertEqual(
            [(int(row["execution_epoch_id"]), str(row["stable_item_id"])) for row in jobs],
            [
                (epochs[0].id, "INFRA-001"),
                (epochs[0].id, "DEV-001"),
                (epochs[1].id, "DEV-001"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
