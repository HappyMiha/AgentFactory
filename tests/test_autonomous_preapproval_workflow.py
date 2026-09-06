import asyncio
import json
import subprocess
import tempfile
import unittest
import uuid
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from agent_factory.autonomous_authorization import (
    AutonomousAuthorizationService,
    PlanningAction,
)
from agent_factory.autonomous_backlog_approval import (
    AutonomousBacklogApprovalService,
)
from agent_factory.autonomous_mission import (
    AutonomousMissionConfiguration,
    AutonomousMissionService,
    MissionPhase,
)
from agent_factory.autonomous_planning import AutonomousPlanningService
from agent_factory.autonomous_proposal_verifier import (
    AutonomousProposalVerificationService,
)
from agent_factory.backlog_revisions import BacklogRevisionService
from agent_factory.mission_intake import AutonomousMissionIntakeService
from agent_factory.models import (
    ExecutionLocation,
    ProviderCapabilities,
)
from agent_factory.orchestration.temporal.activities import AgentFactoryActivities
from agent_factory.orchestration.temporal.client import (
    autonomous_mission_workflow_input,
    signal_autonomous_backlog_approved,
    signal_autonomous_planning,
    start_autonomous_mission_workflow,
)
from agent_factory.orchestration.temporal.models import (
    AutonomousBacklogApprovalNotice,
    AutonomousMissionActivityScope,
    AutonomousPlanningActivityInput,
    AutonomousPlanningCommand,
)
from agent_factory.orchestration.temporal.settings import TemporalSettings
from agent_factory.orchestration.temporal.workflows import (
    AutonomousMissionWorkflow,
)
from agent_factory.storage import SQLiteStorage
from tests.test_autonomous_planning_pipeline import GoldenPlanningInvoker


def run_git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


class AutonomousPreapprovalFixture:
    def create_fixture(self, *, provider_id="local", model=None, capability=None) -> None:
        self.fixture_provider_id = provider_id
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve()
        self.repository = self.workspace / "repository"
        self.repository.mkdir()
        run_git(self.repository, "init")
        run_git(self.repository, "config", "user.name", "Agent Factory Test")
        run_git(
            self.repository,
            "config",
            "user.email",
            "agent-factory@example.test",
        )
        (self.repository / "README.md").write_text(
            "# Temporal pre-approval mission\n", encoding="utf-8"
        )
        (self.repository / "agentfactory.environment.json").write_text(json.dumps({
            "schema_version": 1, "profile": "autonomous-local-default",
            "tools": ["git", "python"], "services": []
        }))
        run_git(self.repository, "add", "README.md", "agentfactory.environment.json")
        run_git(self.repository, "commit", "-m", "initial")
        self.base_commit = run_git(self.repository, "rev-parse", "HEAD")
        self.database = self.workspace / "state.db"
        self.storage = SQLiteStorage(self.database)
        self.capabilities = {
            provider_id: capability or ProviderCapabilities(
                execution_location=ExecutionLocation.LOCAL,
                location_declared=True,
                text_generation=True,
                structured_output=True,
                tool_calls=True,
            )
        }
        created = AutonomousMissionIntakeService(self.storage).create_from_text(
            name="Temporal pre-approval mission",
            mission_owner="Founder",
            specification=(
                "# Product\n\nBuild a safe local health endpoint with deterministic "
                "validation and local persistence."
            ),
            actor="Founder",
            command_id="create-temporal-preapproval",
            mission_key="AFM-TEMPORAL-PREAPPROVAL",
            configuration=AutonomousMissionConfiguration(
                repository_path=str(self.repository),
                default_model=model or "local-planner",
                role_models={
                    "Developer": model or "local-coder",
                    "Environment Bootstrap": model or "local-coder",
                },
                local_provider_ids=(provider_id,),
            ),
            source_name="specification.md",
        )
        self.mission = created.mission
        self.missions = AutonomousMissionService(self.storage)
        self.planning = AutonomousPlanningService(
            self.storage, self.capabilities
        )
        self.authorizations = AutonomousAuthorizationService(
            self.storage, self.capabilities
        )

    def close_fixture(self) -> None:
        self.storage.close()
        self.temporary.cleanup()

    def planning_command(
        self,
        sequence: int,
        *,
        action: PlanningAction = PlanningAction.ANALYZE,
        command_action: PlanningAction | None = None,
    ) -> AutonomousPlanningCommand:
        mission = self.missions.get(self.mission.id)
        manifest = self.planning.create_manifest(
            mission.id,
            proposal_key=f"temporal-proposal-{sequence}",
            actor="Founder",
            command_id=f"temporal-manifest-{sequence}",
            default_provider_id=self.fixture_provider_id,
        )
        authorization = self.authorizations.grant_planning_authority(
            mission.id,
            planning_request_id=manifest.proposal_key,
            requested_action=action,
            role_models={
                assignment.role_id: assignment.model
                for assignment in manifest.assignments
            },
            provider_ids=(self.fixture_provider_id,),
            actor="Founder",
            command_id=f"temporal-planning-authorization-{sequence}",
            reason="Explicit bounded local planning request",
        )
        return AutonomousPlanningCommand(
            command_id=f"temporal-planning-command-{sequence}",
            manifest_id=manifest.id,
            planning_authorization_id=authorization.id,
            expected_mission_version=mission.version,
            actor="Founder",
            requested_action=(command_action or action).value,
        )

    def activity_scope(self) -> AutonomousMissionActivityScope:
        return AutonomousMissionActivityScope(
            mission_id=self.mission.id,
            mission_identity=self.mission.identity,
            mission_key=self.mission.mission_key,
            project_id=self.mission.project_id,
            workspace=str(self.repository),
            database=str(self.database),
            temporal_workflow_id=f"agentfactory-autonomous-mission-{self.mission.id}",
            temporal_first_run_id="temporal-first-run",
        )


class AutonomousPreapprovalActivityTests(
    AutonomousPreapprovalFixture, unittest.TestCase
):
    def setUp(self):
        self.create_fixture()
        self.invoker = GoldenPlanningInvoker()
        self.activities = AgentFactoryActivities(
            TemporalSettings(
                heartbeat_interval_seconds=1,
                heartbeat_timeout_seconds=5,
            ),
            autonomous_planning_invoker=self.invoker,
            autonomous_provider_capabilities=self.capabilities,
        )

    def tearDown(self):
        self.close_fixture()

    def test_activity_replay_and_regeneration_preserve_proposal_lineage(self):
        first_command = self.planning_command(1)
        first_request = AutonomousPlanningActivityInput(
            scope=self.activity_scope(), command=first_command
        )
        first = self.activities._run_autonomous_planning_sync(first_request)
        replay = self.activities._run_autonomous_planning_sync(first_request)

        self.assertEqual(replay, replace(first, duplicate=True))
        self.assertTrue(first.ready_for_approval)
        self.assertEqual(first.phase, MissionPhase.WAITING_FOR_BACKLOG_APPROVAL)
        self.assertEqual(first.proposal_revision_count, 1)
        self.assertEqual(len(self.invoker.requests), 5)

        self.invoker.outputs["backlog_planner"]["output"]["backlog_proposal"][
            "items"
        ][1]["review_notes"] = ["Regenerated after human review"]
        second_command = self.planning_command(
            2, action=PlanningAction.REGENERATE_BACKLOG
        )
        second_request = AutonomousPlanningActivityInput(
            scope=self.activity_scope(), command=second_command
        )
        second = self.activities._run_autonomous_planning_sync(second_request)
        second_replay = self.activities._run_autonomous_planning_sync(
            second_request
        )

        self.assertEqual(second_replay, replace(second, duplicate=True))
        self.assertTrue(second.ready_for_approval)
        self.assertEqual(second.parent_revision_id, first.proposed_revision_id)
        self.assertEqual(second.proposal_revision_count, 2)
        self.assertNotEqual(
            second.proposed_revision_digest, first.proposed_revision_digest
        )
        self.assertEqual(len(self.invoker.requests), 10)
        revisions = BacklogRevisionService(self.storage).list_revisions(
            self.mission.id
        )
        self.assertEqual(
            tuple(revision.id for revision in revisions),
            (first.proposed_revision_id, second.proposed_revision_id),
        )
        reports = AutonomousProposalVerificationService(self.storage).reports(
            self.mission.id
        )
        self.assertEqual(tuple(report.id for report in reports), (
            first.verification_id,
            second.verification_id,
        ))

    def test_action_mismatch_is_denied_before_any_phase_mutation(self):
        command = self.planning_command(
            1,
            action=PlanningAction.REGENERATE_BACKLOG,
            command_action=PlanningAction.ANALYZE,
        )
        request = AutonomousPlanningActivityInput(
            scope=self.activity_scope(), command=command
        )

        with self.assertRaisesRegex(PermissionError, "action"):
            self.activities._run_autonomous_planning_sync(request)

        mission = self.missions.get(self.mission.id)
        self.assertEqual(mission.phase, MissionPhase.DRAFT)
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_planning_pipeline_runs"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(len(self.invoker.requests), 0)


class AutonomousPreapprovalTemporalTests(
    AutonomousPreapprovalFixture, unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self):
        self.create_fixture()
        self.environment = await WorkflowEnvironment.start_time_skipping()
        self.task_queue = f"autonomous-preapproval-{uuid.uuid4().hex}"
        self.settings = TemporalSettings(
            task_queue=self.task_queue,
            fast_activity_timeout_seconds=30,
            llm_activity_timeout_seconds=120,
            heartbeat_interval_seconds=1,
            heartbeat_timeout_seconds=5,
        )
        self.command = self.planning_command(1)
        self.invoker = GoldenPlanningInvoker()
        self.activities = AgentFactoryActivities(
            self.settings,
            autonomous_planning_invoker=self.invoker,
            autonomous_provider_capabilities=self.capabilities,
        )
        self.request = autonomous_mission_workflow_input(
            self.mission,
            workspace=str(self.repository),
            database=str(self.database),
            temporal_settings=self.settings,
            post_approval_execution_enabled=False,
        )

    async def asyncTearDown(self):
        await self.environment.shutdown()
        self.close_fixture()

    async def wait_for_status(self, predicate, *, attempts: int = 200):
        handle = self.environment.client.get_workflow_handle(
            f"agentfactory-autonomous-mission-{self.mission.id}"
        )
        for _ in range(attempts):
            status = await handle.query("get_mission_status", result_type=dict)
            if predicate(status):
                return status
            await asyncio.sleep(0.025)
        self.fail("Timed out waiting for Autonomous Mission Workflow state")

    async def test_durable_wait_spoofed_signal_and_persisted_approval(self):
        worker = Worker(
            self.environment.client,
            task_queue=self.task_queue,
            workflows=[AutonomousMissionWorkflow],
            activities=[
                self.activities.run_autonomous_planning,
                self.activities.revalidate_autonomous_approval,
            ],
        )
        async with worker:
            started = await start_autonomous_mission_workflow(
                self.environment.client, self.request, self.settings
            )
            await signal_autonomous_backlog_approved(
                self.environment.client,
                self.mission.id,
                AutonomousBacklogApprovalNotice(
                    notice_id="spoof-before-persisted-approval",
                    claimed_approval_id=999,
                    claimed_revision_id=999,
                    claimed_revision_digest="0" * 64,
                    claimed_execution_epoch_id=999,
                ),
                self.settings,
            )
            spoofed = await self.wait_for_status(
                lambda status: "did not resolve" in status["last_activity"]
            )
            self.assertEqual(spoofed["phase"], MissionPhase.DRAFT)
            self.assertIsNone(spoofed["active_backlog_revision_id"])

            await signal_autonomous_planning(
                self.environment.client,
                self.mission.id,
                self.command,
                self.settings,
            )
            waiting = await self.wait_for_status(
                lambda status: status["phase"]
                == MissionPhase.WAITING_FOR_BACKLOG_APPROVAL
            )
            self.assertEqual(waiting["workflow_status"], "WAITING")
            self.assertIsNone(waiting["active_backlog_revision_id"])
            self.assertIsNotNone(waiting["proposed_backlog_revision_id"])
            self.assertEqual(waiting["environment_status"], "NOT_STARTED")
            self.assertEqual(len(self.invoker.requests), 5)

            await self.environment.sleep(timedelta(days=30))
            durable = await self.wait_for_status(
                lambda status: status["phase"]
                == MissionPhase.WAITING_FOR_BACKLOG_APPROVAL
            )
            self.assertEqual(
                durable["proposed_backlog_revision_id"],
                waiting["proposed_backlog_revision_id"],
            )
            self.assertEqual(durable["environment_status"], "NOT_STARTED")

            await signal_autonomous_planning(
                self.environment.client,
                self.mission.id,
                self.command,
                self.settings,
            )
            await asyncio.sleep(0.1)
            self.assertEqual(len(self.invoker.requests), 5)

            report = AutonomousProposalVerificationService(self.storage).get(
                waiting["proposal_verification_id"]
            )
            mission = self.missions.get(self.mission.id)
            approved = AutonomousBacklogApprovalService(
                self.storage, self.capabilities
            ).approve_and_start(
                report.id,
                expected_revision_id=report.revision_id,
                expected_canonical_digest=report.canonical_digest,
                expected_mission_version=mission.version,
                base_git_commit_sha=self.base_commit,
                epoch_branch="autonomous/AFM-TEMPORAL-PREAPPROVAL/epoch-1",
                temporal_workflow_id=started.workflow_id,
                temporal_run_id=started.run_id,
                actor="Founder",
                command_id="approve-temporal-preapproval",
                reason="Approve the exact persisted Temporal proposal",
                authentication_context={
                    "schema_version": 1,
                    "method": "authenticated-local-session",
                    "subject": "Founder",
                    "session_id": "temporal-preapproval-session",
                },
            )
            await signal_autonomous_backlog_approved(
                self.environment.client,
                self.mission.id,
                AutonomousBacklogApprovalNotice(
                    notice_id="wake-after-persisted-approval",
                    claimed_approval_id=approved.approval.id + 10,
                    claimed_revision_id=approved.approval.revision_id + 10,
                    claimed_revision_digest="f" * 64,
                    claimed_execution_epoch_id=approved.execution_epoch.id + 10,
                ),
                self.settings,
            )
            authoritative = await self.wait_for_status(
                lambda status: status["phase"] == MissionPhase.APPROVED
            )
            self.assertEqual(
                authoritative["active_backlog_revision_id"],
                approved.approval.revision_id,
            )
            self.assertEqual(
                authoritative["active_execution_epoch_id"],
                approved.execution_epoch.id,
            )
            self.assertEqual(authoritative["environment_status"], "NOT_STARTED")
            self.assertIn("independently of Signal", authoritative["last_activity"])
            await self.environment.client.get_workflow_handle(
                started.workflow_id
            ).cancel()


if __name__ == "__main__":
    unittest.main()
