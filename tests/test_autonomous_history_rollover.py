import asyncio
import json
import sqlite3
import unittest
import uuid
from dataclasses import replace
from datetime import timedelta
from importlib.metadata import version
from pathlib import Path

from temporalio import workflow
from temporalio.common import VersioningBehavior
from temporalio.testing import WorkflowEnvironment
from temporalio.service import RPCError
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from agent_factory.autonomous_authorization import PlanningAction
from agent_factory.autonomous_mission import MissionPhase
from agent_factory.mission_checkpoints import MissionCheckpointService
from agent_factory.orchestration.temporal.activities import AgentFactoryActivities
from agent_factory.orchestration.temporal.client import (
    autonomous_mission_workflow_input,
    discover_autonomous_mission_workflow_runs,
    signal_autonomous_planning,
    start_autonomous_mission_workflow,
)
from agent_factory.orchestration.temporal.models import (
    AUTONOMOUS_CHAIN_SEQUENCE_SEARCH_ATTRIBUTE,
    AUTONOMOUS_MISSION_ID_SEARCH_ATTRIBUTE,
    AUTONOMOUS_MISSION_IDENTITY_SEARCH_ATTRIBUTE,
    AUTONOMOUS_MISSION_WORKFLOW_SCHEMA_VERSION,
    AUTONOMOUS_ROLLOVER_PATCH_ID,
    AutonomousMissionCarryOver,
    AutonomousMissionWorkflowInput,
    AutonomousMissionWorkflowState,
    WorkflowStatus,
    autonomous_mission_search_attributes,
    autonomous_mission_visibility_memo,
    autonomous_rollover_reason,
)
from agent_factory.orchestration.temporal.settings import TemporalSettings
from agent_factory.orchestration.temporal.worker import worker_versioning_options
from agent_factory.orchestration.temporal.workflows import (
    AutonomousMissionWorkflow,
)
from tests.test_autonomous_planning_pipeline import GoldenPlanningInvoker
from tests.test_autonomous_preapproval_workflow import AutonomousPreapprovalFixture


@workflow.defn(name="AutonomousMissionWorkflow")
class PreviousAutonomousMissionWorkflow:
    """Frozen pre-AF-AMM-017 completion path used to generate old history."""

    @workflow.run
    async def run(
        self, request: AutonomousMissionWorkflowInput
    ) -> dict[str, object]:
        info = workflow.info()
        state = AutonomousMissionWorkflowState.from_input(
            request,
            workflow_id=info.workflow_id,
            run_id=info.run_id,
            started_at=workflow.now().isoformat(),
        )
        current_build_id = info.get_current_build_id()
        state.workflow_build_id = current_build_id or request.worker_build_id
        state.workflow_status = WorkflowStatus.WAITING.value
        state.last_activity = (
            "Waiting for explicit bounded planning or persisted approval"
        )
        state.last_activity_at = workflow.now().isoformat()
        state.current_history_event_count = info.get_current_history_length()
        if state.phase == MissionPhase.COMPLETED.value:
            state.workflow_status = WorkflowStatus.COMPLETED.value
            return state.to_dict()
        await workflow.wait_condition(lambda: False)
        raise RuntimeError("Unreachable legacy Workflow branch")


class AutonomousHistoryPolicyTests(unittest.TestCase):
    def test_visibility_contract_repeats_logical_identity_per_run(self):
        attributes = autonomous_mission_search_attributes(
            mission_id=17,
            project_id=5,
            mission_identity="autonomous-mission:17:stable",
            mission_key="AFM-017",
            chain_sequence=3,
            phase=MissionPhase.DEVELOPMENT.value,
            disposition="RUNNING",
        )
        memo = autonomous_mission_visibility_memo(
            mission_id=17,
            project_id=5,
            mission_identity="autonomous-mission:17:stable",
            mission_key="AFM-017",
            chain_sequence=3,
        )["agentfactory_autonomous_mission"]

        self.assertEqual(attributes.get(AUTONOMOUS_MISSION_ID_SEARCH_ATTRIBUTE), 17)
        self.assertEqual(
            attributes.get(AUTONOMOUS_MISSION_IDENTITY_SEARCH_ATTRIBUTE),
            "autonomous-mission:17:stable",
        )
        self.assertEqual(
            attributes.get(AUTONOMOUS_CHAIN_SEQUENCE_SEARCH_ATTRIBUTE), 3
        )
        self.assertEqual(memo["mission_id"], 17)
        self.assertEqual(memo["chain_sequence"], 3)

    def test_retention_and_release_policy_are_documented_and_configurable(self):
        root = Path(__file__).resolve().parents[1]
        runbook = (
            root / "docs" / "development" / "temporal-worker-versioning.md"
        ).read_text(encoding="utf-8")
        environment = (root / ".env.example").read_text(encoding="utf-8")
        namespace_script = (
            root / "infra" / "temporal" / "scripts" / "create-namespace.sh"
        ).read_text(encoding="utf-8")

        for required in (
            "temporalio==1.31.0",
            "af-amm-017-safe-rollover-v1",
            "seven-day retention",
            "autonomous_mission_temporal_runs",
            "workflow.deprecate_patch",
            "PINNED",
            "AUTO_UPGRADE",
        ):
            self.assertIn(required, runbook)
        self.assertIn("TEMPORAL_NAMESPACE_RETENTION_DAYS=7", environment)
        self.assertIn("TEMPORAL_WORKER_VERSIONING_ENABLED=false", environment)
        self.assertIn('${TEMPORAL_NAMESPACE_RETENTION:-7d}', namespace_script)

    def test_schema_v2_carry_over_excludes_display_and_artifact_content(self):
        carry = AutonomousMissionCarryOver(
            mission_id=17,
            mission_version=31,
            phase=MissionPhase.DEVELOPMENT.value,
            disposition="RUNNING",
            chain_sequence=4,
            previous_run_id="run-3",
            first_run_id="run-1",
            active_backlog_revision_id=11,
            active_backlog_revision_digest="a" * 64,
            active_execution_epoch_id=13,
            current_checkpoint_id=19,
            current_work_item_stable_id="AF-AMM-017",
            completed_items=8,
            total_items=21,
            accepted_mutation_count=12,
            previous_run_safe_boundary_count=3,
            previous_run_history_event_count=417,
            rollover_reason="SAFE_BOUNDARY_THRESHOLD",
            previous_worker_build_id="agentfactory-build-4",
            control_fencing_token=5,
        )

        payload = carry.to_dict()
        serialized = json.dumps(payload, sort_keys=True)

        self.assertEqual(
            payload["schema_version"], AUTONOMOUS_MISSION_WORKFLOW_SCHEMA_VERSION
        )
        self.assertIsNone(payload["current_role"])
        self.assertIsNone(payload["current_model"])
        self.assertEqual(payload["last_activity"], "")
        self.assertEqual(payload["last_activity_at"], "")
        for forbidden in (
            "source content",
            "provider output",
            "artifact body",
            "backlog snapshot",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertLess(len(serialized), 4096)

    def test_rollover_policy_requires_a_safe_boundary_and_has_stable_priority(self):
        common = {
            "history_event_count": 500,
            "safe_boundary_threshold": 1,
            "history_event_threshold": 100,
            "temporal_recommended": True,
            "worker_deployment_changed": True,
        }
        self.assertIsNone(
            autonomous_rollover_reason(safe_boundary_count=0, **common)
        )
        self.assertEqual(
            autonomous_rollover_reason(safe_boundary_count=1, **common),
            "WORKER_DEPLOYMENT_CHANGED",
        )
        self.assertEqual(AUTONOMOUS_ROLLOVER_PATCH_ID, "af-amm-017-safe-rollover-v1")

    def test_pinned_sdk_and_worker_deployment_contract(self):
        self.assertEqual(version("temporalio"), "1.31.0")
        settings = TemporalSettings(
            worker_build_id="agentfactory-release-17",
            worker_deployment_name="agentfactory-autonomous",
            worker_versioning_enabled=True,
        )

        options = worker_versioning_options(settings)
        deployment = options["deployment_config"]

        self.assertTrue(deployment.use_worker_versioning)
        self.assertEqual(
            deployment.default_versioning_behavior,
            VersioningBehavior.PINNED,
        )
        self.assertEqual(deployment.version.build_id, "agentfactory-release-17")
        self.assertEqual(
            deployment.version.deployment_name, "agentfactory-autonomous"
        )
        self.assertEqual(
            worker_versioning_options(
                replace(settings, worker_versioning_enabled=False)
            ),
            {"build_id": "agentfactory-release-17"},
        )


class AutonomousHistoryRolloverTemporalTests(
    AutonomousPreapprovalFixture, unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self):
        self.create_fixture()
        self.environment = await WorkflowEnvironment.start_time_skipping()
        self.task_queue = f"autonomous-history-{uuid.uuid4().hex}"
        self.settings_v1 = TemporalSettings(
            task_queue=self.task_queue,
            fast_activity_timeout_seconds=30,
            llm_activity_timeout_seconds=120,
            heartbeat_interval_seconds=1,
            heartbeat_timeout_seconds=5,
            autonomous_continue_as_new_enabled=True,
            autonomous_continue_as_new_event_threshold=50_000,
            autonomous_continue_as_new_safe_boundary_threshold=1,
            worker_build_id="history-worker-v1",
        )
        self.invoker = GoldenPlanningInvoker()
        self.activities = AgentFactoryActivities(
            self.settings_v1,
            autonomous_planning_invoker=self.invoker,
            autonomous_provider_capabilities=self.capabilities,
        )
        self.request = autonomous_mission_workflow_input(
            self.mission,
            workspace=str(self.repository),
            database=str(self.database),
            temporal_settings=self.settings_v1,
            post_approval_execution_enabled=False,
        )

    async def asyncTearDown(self):
        await self.environment.shutdown()
        self.close_fixture()

    async def wait_for_chain_status(
        self, chain_sequence: int, predicate, *, attempts: int = 400
    ):
        for _ in range(attempts):
            registrations = MissionCheckpointService(
                self.storage
            ).mission_temporal_runs(self.mission.id)
            if len(registrations) >= chain_sequence:
                handle = self.environment.client.get_workflow_handle(
                    f"agentfactory-autonomous-mission-{self.mission.id}",
                    run_id=registrations[chain_sequence - 1].run_id,
                )
                try:
                    status = await handle.query(
                        "get_mission_status",
                        result_type=dict,
                        rpc_timeout=timedelta(seconds=1),
                    )
                except RPCError:
                    pass
                else:
                    if predicate(status):
                        return status
            await asyncio.sleep(0.025)
        self.fail("Timed out waiting for the continued mission Workflow")

    async def test_three_runs_survive_worker_replacement_without_replayed_mutations(self):
        worker_v1 = Worker(
            self.environment.client,
            task_queue=self.task_queue,
            workflows=[AutonomousMissionWorkflow],
            activities=[
                self.activities.register_autonomous_temporal_run,
                self.activities.run_autonomous_planning,
            ],
            build_id="history-worker-v1",
            max_cached_workflows=0,
        )
        first_command = self.planning_command(1)
        async with worker_v1:
            started = await start_autonomous_mission_workflow(
                self.environment.client,
                self.request,
                self.settings_v1,
            )
            await signal_autonomous_planning(
                self.environment.client,
                self.mission.id,
                first_command,
                self.settings_v1,
            )
            second_run = await self.wait_for_chain_status(
                2,
                lambda state: (
                    state["chain_sequence"] == 2
                    and state["proposal_revision_count"] == 1
                    and state["workflow_status"] == WorkflowStatus.WAITING.value
                )
            )

        second_command = self.planning_command(
            2, action=PlanningAction.REGENERATE_BACKLOG
        )
        settings_v2 = replace(
            self.settings_v1, worker_build_id="history-worker-v2"
        )
        worker_v2 = Worker(
            self.environment.client,
            task_queue=self.task_queue,
            workflows=[AutonomousMissionWorkflow],
            activities=[
                self.activities.register_autonomous_temporal_run,
                self.activities.run_autonomous_planning,
            ],
            build_id="history-worker-v2",
            max_cached_workflows=0,
        )
        async with worker_v2:
            await signal_autonomous_planning(
                self.environment.client,
                self.mission.id,
                second_command,
                settings_v2,
            )
            third_run = await self.wait_for_chain_status(
                3,
                lambda state: (
                    state["chain_sequence"] == 3
                    and state["proposal_revision_count"] == 2
                    and state["accepted_mutation_count"] == 2
                    and state["workflow_status"] == WorkflowStatus.WAITING.value
                )
            )

            discovered = ()
            retained = MissionCheckpointService(
                self.storage
            ).mission_temporal_runs(self.mission.id)
            for _ in range(100):
                discovered = await discover_autonomous_mission_workflow_runs(
                    self.environment.client,
                    self.mission.id,
                    workflow_id=started.workflow_id,
                    retained_run_ids=tuple(row.run_id for row in retained),
                )
                if len(discovered) == 3:
                    break
                await asyncio.sleep(0.025)

            self.assertEqual(len(discovered), 3)
            self.assertEqual(
                tuple(item["chain_sequence"] for item in discovered),
                (1, 2, 3),
            )
            self.assertEqual(
                {item["workflow_id"] for item in discovered},
                {started.workflow_id},
            )
            self.assertEqual(
                {item["mission_identity"] for item in discovered},
                {self.mission.identity},
            )
            self.assertIn(
                self.mission.identity,
                discovered[0]["static_details"] or "",
            )
            await self.environment.client.get_workflow_handle(
                started.workflow_id
            ).cancel(reason="AF-AMM-017 test complete")

        registrations = MissionCheckpointService(
            self.storage
        ).mission_temporal_runs(self.mission.id)
        self.assertEqual(tuple(row.sequence for row in registrations), (1, 2, 3))
        self.assertEqual(
            tuple(row.previous_run_id for row in registrations),
            (None, registrations[0].run_id, registrations[1].run_id),
        )
        self.assertEqual(
            tuple(row.first_run_id for row in registrations),
            (registrations[0].run_id,) * 3,
        )
        self.assertEqual(
            tuple(row.workflow_build_id for row in registrations),
            ("history-worker-v1", "history-worker-v1", "history-worker-v2"),
        )
        self.assertEqual(
            tuple(row.rollover_reason for row in registrations),
            (None, "SAFE_BOUNDARY_THRESHOLD", "SAFE_BOUNDARY_THRESHOLD"),
        )
        self.assertEqual(
            tuple(row.accepted_mutation_count for row in registrations),
            (0, 1, 2),
        )
        ledger = MissionCheckpointService(self.storage)
        latest = registrations[-1]
        replayed = ledger.register_mission_temporal_run(
            latest.mission_id,
            mission_identity=self.mission.identity,
            mission_key=self.mission.mission_key,
            project_id=self.mission.project_id,
            sequence=latest.sequence,
            workflow_id=latest.workflow_id,
            run_id=latest.run_id,
            previous_run_id=latest.previous_run_id,
            first_run_id=latest.first_run_id,
            mission_version=latest.mission_version,
            phase=latest.phase,
            disposition=latest.disposition,
            active_backlog_revision_id=latest.active_backlog_revision_id,
            active_execution_epoch_id=latest.active_execution_epoch_id,
            current_checkpoint_id=latest.current_checkpoint_id,
            control_fencing_token=latest.control_fencing_token,
            workflow_build_id=latest.workflow_build_id,
            rollover_reason=latest.rollover_reason,
            previous_run_history_event_count=(
                latest.previous_run_history_event_count
            ),
            previous_run_safe_boundary_count=(
                latest.previous_run_safe_boundary_count
            ),
            accepted_mutation_count=latest.accepted_mutation_count,
        )
        self.assertTrue(replayed.duplicate)
        with self.assertRaisesRegex(ValueError, "identity is already bound"):
            ledger.register_mission_temporal_run(
                latest.mission_id,
                mission_identity=self.mission.identity,
                mission_key=self.mission.mission_key,
                project_id=self.mission.project_id,
                sequence=latest.sequence,
                workflow_id=latest.workflow_id,
                run_id=latest.run_id,
                previous_run_id=latest.previous_run_id,
                first_run_id=latest.first_run_id,
                mission_version=latest.mission_version,
                phase=latest.phase,
                disposition=latest.disposition,
                active_backlog_revision_id=latest.active_backlog_revision_id,
                active_execution_epoch_id=latest.active_execution_epoch_id,
                current_checkpoint_id=latest.current_checkpoint_id,
                control_fencing_token=latest.control_fencing_token,
                workflow_build_id="tampered-build",
                rollover_reason=latest.rollover_reason,
                previous_run_history_event_count=(
                    latest.previous_run_history_event_count
                ),
                previous_run_safe_boundary_count=(
                    latest.previous_run_safe_boundary_count
                ),
                accepted_mutation_count=latest.accepted_mutation_count,
            )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
            self.storage.db.execute(
                "UPDATE autonomous_mission_temporal_runs "
                "SET workflow_build_id='tampered' WHERE id=?",
                (registrations[0].id,),
            )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
            self.storage.db.execute(
                "DELETE FROM autonomous_mission_temporal_runs WHERE id=?",
                (registrations[0].id,),
            )
        self.assertTrue(
            all(
                row.previous_run_history_event_count > 0
                for row in registrations[1:]
            )
        )
        self.assertEqual(second_run["accepted_mutation_count"], 1)
        self.assertEqual(third_run["previous_worker_build_id"], "history-worker-v1")
        self.assertEqual(third_run["workflow_build_id"], "history-worker-v2")
        self.assertEqual(len(self.invoker.requests), 10)
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_planning_pipeline_runs"
            ).fetchone()[0],
            2,
        )


class AutonomousHistoryReplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_workflow_replays_pre_patch_completed_history(self):
        environment = await WorkflowEnvironment.start_time_skipping()
        try:
            task_queue = f"autonomous-replay-{uuid.uuid4().hex}"
            request = AutonomousMissionWorkflowInput(
                mission_id=1,
                mission_identity="autonomous-mission:legacy:1",
                mission_key="AFM-LEGACY-1",
                project_id=1,
                mission_version=1,
                phase=MissionPhase.COMPLETED.value,
                disposition="RUNNING",
                workspace="C:/legacy-project",
                database="C:/legacy-project/state.db",
                continue_as_new_enabled=False,
                worker_build_id="history-worker-v0",
                schema_version=1,
            )
            worker = Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[PreviousAutonomousMissionWorkflow],
                workflow_runner=UnsandboxedWorkflowRunner(),
                build_id="history-worker-v0",
            )
            async with worker:
                handle = await environment.client.start_workflow(
                    PreviousAutonomousMissionWorkflow.run,
                    request,
                    id=f"legacy-autonomous-{uuid.uuid4().hex}",
                    task_queue=task_queue,
                    result_type=dict,
                )
                completed = await handle.result()
                history = await handle.fetch_history()

            self.assertEqual(completed["workflow_status"], "COMPLETED")
            replay = await Replayer(
                workflows=[AutonomousMissionWorkflow],
                build_id="history-worker-v0",
            ).replay_workflow(history)
            self.assertIsNone(replay.replay_failure)
        finally:
            await environment.shutdown()
