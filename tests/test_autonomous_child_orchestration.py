import asyncio
import json
import unittest
import uuid
from unittest.mock import patch

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from agent_factory.autonomous_backlog_approval import (
    AutonomousBacklogApprovalService,
)
from agent_factory.autonomous_mission import AutonomousMissionService, MissionPhase
from agent_factory.autonomous_proposal_verifier import (
    AutonomousProposalVerificationService,
)
from agent_factory.backlog_revisions import BacklogItemStatus, BacklogRevisionService
from agent_factory.coding_delivery import (
    AutonomousCodingDeliveryService,
    autonomous_child_workflow_id,
)
from agent_factory.models import Agent
from agent_factory.orchestration.temporal.activities import AgentFactoryActivities
from agent_factory.orchestration.temporal.client import (
    autonomous_mission_workflow_input,
    signal_autonomous_backlog_approved,
    signal_autonomous_planning,
    start_autonomous_mission_workflow,
)
from agent_factory.orchestration.temporal.models import (
    ActivityResult,
    AgentFactoryJobInput,
    AutonomousBacklogApprovalNotice,
)
from agent_factory.orchestration.temporal.settings import TemporalSettings
from agent_factory.orchestration.temporal.workflows import (
    AgentFactoryJobWorkflow,
    AutonomousMissionWorkflow,
)
from tests.test_autonomous_preapproval_workflow import (
    AutonomousPreapprovalFixture,
    run_git,
)
from tests.test_autonomous_planning_pipeline import GoldenPlanningInvoker


class AutonomousChildFixture(AutonomousPreapprovalFixture):
    def approve_fixture(self):
        invoker = GoldenPlanningInvoker()
        activities = AgentFactoryActivities(
            autonomous_planning_invoker=invoker,
            autonomous_provider_capabilities=self.capabilities,
        )
        planned = activities._run_autonomous_planning_sync(
            self._planning_request(self.planning_command(1))
        )
        report = AutonomousProposalVerificationService(self.storage).get(
            planned.verification_id
        )
        branch = "autonomous/AFM-TEMPORAL-PREAPPROVAL/epoch-1"
        run_git(self.repository, "checkout", "-b", branch)
        mission = self.missions.get(self.mission.id)
        approved = AutonomousBacklogApprovalService(
            self.storage, self.capabilities
        ).approve_and_start(
            report.id,
            expected_revision_id=report.revision_id,
            expected_canonical_digest=report.canonical_digest,
            expected_mission_version=mission.version,
            base_git_commit_sha=self.base_commit,
            epoch_branch=branch,
            temporal_workflow_id=self.activity_scope().temporal_workflow_id,
            temporal_run_id=self.activity_scope().temporal_first_run_id,
            actor="Founder",
            command_id="approve-autonomous-child-fixture",
            reason="Approve exact fixture revision for child orchestration",
            authentication_context={
                "schema_version": 1,
                "method": "authenticated-local-session",
                "subject": "Founder",
                "session_id": "autonomous-child-fixture",
            },
        )
        return approved

    def _planning_request(self, command):
        from agent_factory.orchestration.temporal.models import (
            AutonomousPlanningActivityInput,
        )

        return AutonomousPlanningActivityInput(
            scope=self.activity_scope(), command=command
        )

    def persist_passing_stage_evidence(self, child_job) -> None:
        for ordinal, stage in enumerate(
            (
                "policy-precheck",
                "implementation",
                "validation",
                "policy-postcheck",
            ),
            start=1,
        ):
            mutation, created = self.storage.reserve_workflow_mutation(
                run_id=child_job.run_id,
                stage_key="workflow",
                operation="provider_call",
                idempotency_key=f"fixture:{child_job.job_id}:{stage}",
                request={"stage": stage, "ordinal": ordinal},
            )
            self.assertTrue(created)
            artifact_id = self.storage.add_artifact(
                child_job.run_id,
                stage,
                f"fixture-{stage}",
                "local",
                json.dumps(
                    {
                        "verdict": (
                            "PASS"
                            if stage == "validation"
                            else "COMPLETE"
                            if stage == "implementation"
                            else "ALIGNED"
                        ),
                        "summary": f"{stage} passed",
                    },
                    sort_keys=True,
                ),
            )
            self.storage.complete_workflow_mutation(
                int(mutation["id"]),
                ActivityResult(
                    True,
                    passed=True,
                    summary=f"{stage} passed",
                    artifacts=[f"artifact:{artifact_id}"],
                ).to_dict(),
            )


class AutonomousCodingDeliveryTests(AutonomousChildFixture, unittest.TestCase):
    def setUp(self):
        self.create_fixture()

    def tearDown(self):
        self.close_fixture()

    def test_duplicate_prepare_and_post_result_recovery_are_idempotent(self):
        approved = self.approve_fixture()
        delivery = AutonomousCodingDeliveryService(
            self.storage, self.capabilities
        )
        development = delivery.enter_development(
            self.mission.id,
            expected_mission_version=approved.approval.result_mission_version,
            command_id="enter-autonomous-development",
        )
        first = delivery.prepare_job(
            self.mission.id,
            "INFRA-001",
            execution_mode="simulation",
            workflow_definition_id="delivery",
            command_id="prepare-infra-child",
        )
        replay = delivery.prepare_job(
            self.mission.id,
            "INFRA-001",
            execution_mode="simulation",
            workflow_definition_id="delivery",
            command_id="prepare-infra-child",
        )

        self.assertEqual(replay, first)
        self.assertEqual(first.logical_attempt, 1)
        self.assertEqual(
            first.child_workflow_id,
            autonomous_child_workflow_id(
                self.mission.id,
                approved.approval.revision_id,
                approved.execution_epoch.id,
                "INFRA-001",
                1,
            ),
        )
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_child_jobs"
            ).fetchone()[0],
            1,
        )
        delivery.authorize_job(
            first.id, command_id=f"{first.child_workflow_id}:authorize"
        )
        activities = AgentFactoryActivities(
            autonomous_provider_capabilities=self.capabilities
        )
        context, _role, _model = activities._autonomous_job_context(
            delivery, first
        )
        simulation_agent, simulation_authority = (
            activities._autonomous_execution_agent(
                self.storage,
                AgentFactoryJobInput(
                    job_id=first.job_id,
                    run_id=first.run_id,
                    project_id=self.mission.project_id,
                    task_id=first.task_id,
                    workspace=str(self.repository),
                    database=str(self.database),
                    mode="simulation",
                    autonomous_context=context,
                ),
                Agent(
                    id="configured-worker",
                    name="Configured worker",
                    role="Implementation Worker",
                    enabled=True,
                    provider="remote",
                    instructions="Implement the item",
                ),
            )
        )
        self.assertEqual(simulation_agent.provider, "deterministic")
        self.assertIsNone(simulation_authority)
        self.persist_passing_stage_evidence(first)
        completion = delivery.complete_job(
            first.id, command_id=f"{first.child_workflow_id}:complete"
        )
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM approval_gates WHERE run_id=?",
                (first.run_id,),
            ).fetchone()[0],
            0,
        )

        # Simulate a process loss after the checkpoint commits but before the
        # immutable reconciliation ledger/event transaction commits.
        original_event = self.storage._event

        def crash_after_checkpoint(event_type, entity_type, entity_id, payload):
            if event_type == "autonomous_child.reconciled":
                raise RuntimeError("simulated parent loss after checkpoint")
            return original_event(event_type, entity_type, entity_id, payload)

        with patch.object(self.storage, "_event", side_effect=crash_after_checkpoint):
            with self.assertRaisesRegex(RuntimeError, "simulated parent loss"):
                delivery.reconcile_job(
                    first.id,
                    expected_mission_version=development.version,
                    command_id="reconcile-infra-child",
                )
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_mission_checkpoints"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_child_reconciliations"
            ).fetchone()[0],
            0,
        )

        # A parent/worker restart uses only the persisted completion/checkpoint.
        recovered = AutonomousCodingDeliveryService(
            self.storage, self.capabilities
        )
        reconciliation = recovered.reconcile_job(
            first.id,
            expected_mission_version=development.version,
            command_id="reconcile-infra-child",
        )
        replay_reconciliation = recovered.reconcile_job(
            first.id,
            expected_mission_version=development.version,
            command_id="reconcile-infra-child",
        )

        self.assertEqual(replay_reconciliation, reconciliation)
        self.assertEqual(reconciliation.completion_id, completion.id)
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_mission_checkpoints"
            ).fetchone()[0],
            1,
        )
        items = BacklogRevisionService(self.storage).active_items(self.mission.id)
        self.assertEqual(items[0].status, BacklogItemStatus.DONE)
        self.assertEqual(items[1].status, BacklogItemStatus.READY)

        live = recovered.prepare_job(
            self.mission.id,
            "DEV-001",
            execution_mode="live",
            workflow_definition_id="delivery",
            command_id="prepare-live-dev-child",
        )
        recovered.authorize_job(
            live.id, command_id=f"{live.child_workflow_id}:authorize"
        )
        live_context, _role, _model = activities._autonomous_job_context(
            recovered, live
        )
        live_agent, live_authority = activities._autonomous_execution_agent(
            self.storage,
            AgentFactoryJobInput(
                job_id=live.job_id,
                run_id=live.run_id,
                project_id=self.mission.project_id,
                task_id=live.task_id,
                workspace=str(self.repository),
                database=str(self.database),
                mode="live",
                autonomous_context=live_context,
            ),
            Agent(
                id="configured-worker",
                name="Configured worker",
                role="Developer",
                enabled=True,
                provider="local",
                model="local-coder",
                permissions=["execute_provider"],
                instructions="Implement the item",
            ),
            stage_key="implementation", effective_model="local-coder",
        )
        self.assertEqual(live_agent.provider, "local")
        self.assertEqual(live_authority.authorization_id, live.authorization_id)
        self.persist_passing_stage_evidence(live)
        with self.assertRaisesRegex(ValueError, "integrated commit"):
            recovered.complete_job(
                live.id, command_id=f"{live.child_workflow_id}:complete"
            )


class AutonomousChildTemporalTests(
    AutonomousChildFixture, unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self):
        self.create_fixture()
        self.environment = await WorkflowEnvironment.start_time_skipping()
        self.task_queue = f"autonomous-child-{uuid.uuid4().hex}"
        self.settings = TemporalSettings(
            task_queue=self.task_queue,
            fast_activity_timeout_seconds=30,
            llm_activity_timeout_seconds=120,
            heartbeat_interval_seconds=1,
            heartbeat_timeout_seconds=5,
        )
        self.invoker = GoldenPlanningInvoker()
        self.activities = AgentFactoryActivities(
            self.settings,
            autonomous_planning_invoker=self.invoker,
            autonomous_provider_capabilities=self.capabilities,
        )
        self.command = self.planning_command(1)
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

    async def wait_for_phase(self, handle, phase: str, attempts: int = 300):
        for _ in range(attempts):
            state = await handle.query("get_mission_status", result_type=dict)
            if state["phase"] == phase:
                return state
            await asyncio.sleep(0.025)
        self.fail(f"Timed out waiting for mission phase {phase}")

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

    async def test_parent_completes_two_dependent_children_once_and_checkpoints_each(self):
        async with self.worker():
            started = await start_autonomous_mission_workflow(
                self.environment.client, self.request, self.settings
            )
            handle = self.environment.client.get_workflow_handle(started.workflow_id)
            await signal_autonomous_planning(
                self.environment.client,
                self.mission.id,
                self.command,
                self.settings,
            )
            waiting = await self.wait_for_phase(
                handle, MissionPhase.WAITING_FOR_BACKLOG_APPROVAL.value
            )
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
                command_id="approve-temporal-child-orchestration",
                reason="Approve exact backlog for autonomous child execution",
                authentication_context={
                    "schema_version": 1,
                    "method": "authenticated-local-session",
                    "subject": "Founder",
                    "session_id": "temporal-child-session",
                },
            )
            await signal_autonomous_backlog_approved(
                self.environment.client,
                self.mission.id,
                AutonomousBacklogApprovalNotice(
                    notice_id="wake-autonomous-child-orchestration",
                    claimed_approval_id=approved.approval.id,
                ),
                self.settings,
            )
            result = await asyncio.wait_for(handle.result(), timeout=60)

        self.assertEqual(result["workflow_status"], "COMPLETED")
        self.assertEqual(result["phase"], MissionPhase.COMPLETED.value)
        self.assertEqual(result["completed_items"], 2)
        self.assertEqual(result["total_items"], 2)
        jobs = self.storage.db.execute(
            "SELECT * FROM autonomous_child_jobs ORDER BY id"
        ).fetchall()
        self.assertEqual(
            [str(row["stable_item_id"]) for row in jobs],
            ["INFRA-001", "DEV-001"],
        )
        self.assertEqual(len({str(row["child_workflow_id"]) for row in jobs}), 2)
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_child_delivery_completions"
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_child_reconciliations"
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_mission_checkpoints"
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM approval_gates"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM workflow_mutations "
                "WHERE operation='provider_call'"
            ).fetchone()[0],
            8,
        )
        self.assertEqual(
            {
                str(row["status"])
                for row in self.storage.db.execute(
                    "SELECT status FROM workflow_runs"
                )
            },
            {"approved"},
        )
        items = BacklogRevisionService(self.storage).active_items(self.mission.id)
        self.assertEqual(
            [item.status for item in items],
            [BacklogItemStatus.DONE, BacklogItemStatus.DONE],
        )


if __name__ == "__main__":
    unittest.main()
