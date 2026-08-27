import json
import tempfile
import unittest
import uuid
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from agent_factory.autonomous_mission import AutonomousMissionService
from agent_factory.orchestration.temporal.client import (
    AutonomousMissionWorkflowConflictError,
    autonomous_mission_workflow_input,
    autonomous_mission_workflow_snapshot,
    start_autonomous_mission_workflow,
    workflow_id_for_autonomous_mission,
)
from agent_factory.orchestration.temporal.models import (
    AUTONOMOUS_SUMMARY_LIMIT,
    AutonomousMissionCarryOver,
    AutonomousMissionWorkflowInput,
    AutonomousMissionWorkflowState,
)
from agent_factory.orchestration.temporal.settings import TemporalSettings
from agent_factory.orchestration.temporal.worker import REGISTERED_WORKFLOWS
from agent_factory.orchestration.temporal.workflows import (
    AgentFactoryJobWorkflow,
    AutonomousMissionWorkflow,
    TemporalDemoWorkflow,
)
from agent_factory.storage import SQLiteStorage


class AutonomousMissionWorkflowContractTests(unittest.TestCase):
    def test_input_carry_over_and_state_are_bounded_and_round_trip(self):
        carry = AutonomousMissionCarryOver(
            mission_id=7,
            mission_version=11,
            phase="DEVELOPMENT",
            disposition="RUNNING",
            chain_sequence=2,
            previous_run_id="temporal-run-1",
            active_backlog_revision_id=19,
            active_backlog_revision_digest="a" * 64,
            active_execution_epoch_id=23,
            current_checkpoint_id=29,
            current_work_item_stable_id="AF-AMM-012",
            current_role="Developer",
            current_model="local-coder",
            completed_items=4,
            total_items=9,
            environment_status="READY",
            last_activity="Checkpoint 29 committed",
            last_activity_at="2026-08-27T12:00:00+00:00",
        )
        request = AutonomousMissionWorkflowInput(
            mission_id=7,
            mission_identity="autonomous-mission:7:stable",
            mission_key="AFM-007",
            project_id=3,
            mission_version=11,
            phase="DEVELOPMENT",
            disposition="RUNNING",
            workspace="C:/project",
            database="C:/project/.agent-factory/state.db",
            carry_over=carry,
        )
        serialized = json.dumps(request.to_dict(), sort_keys=True)
        self.assertLess(len(serialized), 4096)
        for forbidden in (
            "initial_specification",
            "backlog_snapshot",
            "artifact_content",
            "provider_output",
            "source_tree",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(
            AutonomousMissionWorkflowInput.from_dict(request.to_dict()), request
        )

        state = AutonomousMissionWorkflowState.from_input(
            request,
            workflow_id="agentfactory-autonomous-mission-7",
            run_id="temporal-run-2",
            started_at="2026-08-27T12:01:00+00:00",
        )
        self.assertEqual(state.phase, "DEVELOPMENT")
        self.assertEqual(state.disposition, "RUNNING")
        self.assertEqual(state.temporal_first_run_id, "temporal-run-1")
        self.assertEqual(state.active_backlog_revision_id, 19)
        self.assertEqual(state.active_execution_epoch_id, 23)
        self.assertEqual(state.current_checkpoint_id, 29)
        self.assertEqual(state.current_work_item_stable_id, "AF-AMM-012")
        self.assertEqual(state.current_role, "Developer")
        self.assertEqual(state.current_model, "local-coder")
        self.assertEqual(
            AutonomousMissionWorkflowState.from_dict(state.to_dict()), state
        )
        next_carry = state.to_carry_over()
        self.assertEqual(next_carry.chain_sequence, 3)
        self.assertEqual(next_carry.previous_run_id, "temporal-run-2")
        self.assertEqual(next_carry.first_run_id, "temporal-run-1")
        self.assertEqual(next_carry.active_backlog_revision_digest, "a" * 64)

        workflow_instance = AutonomousMissionWorkflow()
        workflow_instance.state = state
        status = workflow_instance.get_mission_status()
        progress = workflow_instance.get_mission_progress()
        role = workflow_instance.get_current_role()
        environment = workflow_instance.get_environment_status()
        self.assertEqual(status["mission_version"], 11)
        self.assertEqual(status["previous_temporal_run_id"], "temporal-run-1")
        self.assertEqual(progress["percent"], 44.44)
        self.assertEqual(progress["last_activity"], "Checkpoint 29 committed")
        self.assertEqual(role, {
            "mission_id": 7,
            "current_work_item_stable_id": "AF-AMM-012",
            "role": "Developer",
            "model": "local-coder",
        })
        self.assertEqual(environment["environment_status"], "READY")
        self.assertEqual(environment["disposition"], "RUNNING")

    def test_contract_rejects_large_or_mismatched_history_payloads(self):
        with self.assertRaisesRegex(ValueError, "Last activity exceeds"):
            AutonomousMissionCarryOver(
                mission_id=1,
                mission_version=1,
                phase="DRAFT",
                disposition="RUNNING",
                last_activity="x" * (AUTONOMOUS_SUMMARY_LIMIT + 1),
            )
        with self.assertRaisesRegex(ValueError, "id and digest"):
            AutonomousMissionCarryOver(
                mission_id=1,
                mission_version=1,
                phase="APPROVED",
                disposition="RUNNING",
                active_backlog_revision_id=3,
            )
        carry = AutonomousMissionCarryOver(
            mission_id=2,
            mission_version=1,
            phase="DRAFT",
            disposition="RUNNING",
        )
        with self.assertRaisesRegex(ValueError, "exact mission"):
            AutonomousMissionWorkflowInput(
                mission_id=1,
                mission_identity="autonomous-mission:1",
                mission_key="AFM-1",
                project_id=1,
                mission_version=1,
                phase="DRAFT",
                disposition="RUNNING",
                workspace="C:/project",
                database="C:/project/state.db",
                carry_over=carry,
            )

    def test_registration_is_additive_and_stable_id_is_domain_scoped(self):
        self.assertEqual(
            REGISTERED_WORKFLOWS,
            (
                AgentFactoryJobWorkflow,
                AutonomousMissionWorkflow,
                TemporalDemoWorkflow,
            ),
        )
        self.assertEqual(
            workflow_id_for_autonomous_mission(41),
            "agentfactory-autonomous-mission-41",
        )
        self.assertEqual(
            workflow_id_for_autonomous_mission(41, "custom-mission"),
            "custom-mission-41",
        )
        with self.assertRaises(ValueError):
            workflow_id_for_autonomous_mission(0)


class AutonomousMissionWorkflowTemporalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve()
        self.database = self.workspace / ".agent-factory" / "state.db"
        storage = SQLiteStorage(self.database)
        self.mission = AutonomousMissionService(storage).create(
            name="Temporal parent mission",
            mission_owner="Founder",
            actor="Founder",
            command_id="create-temporal-parent-mission",
            mission_key="AFM-TEMPORAL-PARENT",
            initial_specification=(
                "This large specification stays in SQLite and out of Workflow history."
            ),
        )
        storage.close()
        self.request = autonomous_mission_workflow_input(
            self.mission,
            workspace=str(self.workspace),
            database=str(self.database),
        )
        self.environment = await WorkflowEnvironment.start_time_skipping()
        self.task_queue = f"autonomous-parent-{uuid.uuid4().hex}"
        self.settings = TemporalSettings(
            task_queue=self.task_queue,
            heartbeat_interval_seconds=1,
            heartbeat_timeout_seconds=5,
        )

    async def asyncTearDown(self):
        await self.environment.shutdown()
        self.temporary.cleanup()

    async def test_draft_start_attach_and_queries_use_one_parent(self):
        worker = Worker(
            self.environment.client,
            task_queue=self.task_queue,
            workflows=list(REGISTERED_WORKFLOWS),
        )
        async with worker:
            started = await start_autonomous_mission_workflow(
                self.environment.client, self.request, self.settings
            )
            self.assertFalse(started.duplicate)
            self.assertEqual(started.mission_id, self.mission.id)
            self.assertEqual(started.chain_sequence, 1)
            self.assertIsNone(started.previous_run_id)
            self.assertEqual(
                started.workflow_id,
                f"agentfactory-autonomous-mission-{self.mission.id}",
            )
            self.assertEqual(started.correlation()["run_id"], started.run_id)
            approval_correlation = started.approval_start_correlation()
            self.assertEqual(
                approval_correlation["temporal_workflow_id"], started.workflow_id
            )
            self.assertEqual(
                approval_correlation["temporal_chain_metadata"]["mission_id"],
                self.mission.id,
            )

            snapshot = await autonomous_mission_workflow_snapshot(
                self.environment.client, self.mission.id, self.settings
            )
            self.assertEqual(snapshot["temporal_status"], "RUNNING")
            self.assertEqual(snapshot["status"]["mission_id"], self.mission.id)
            self.assertEqual(snapshot["status"]["phase"], "DRAFT")
            self.assertEqual(snapshot["status"]["disposition"], "RUNNING")
            self.assertIsNone(
                snapshot["status"]["active_backlog_revision_id"]
            )
            self.assertEqual(snapshot["progress"]["completed_items"], 0)
            self.assertEqual(snapshot["progress"]["total_items"], 0)
            self.assertIsNone(snapshot["current_role"]["role"])
            self.assertEqual(
                snapshot["environment"]["environment_status"], "NOT_STARTED"
            )
            serialized = json.dumps(snapshot, sort_keys=True)
            self.assertNotIn("large specification", serialized.casefold())

            attached = await start_autonomous_mission_workflow(
                self.environment.client, self.request, self.settings
            )
            self.assertTrue(attached.duplicate)
            self.assertEqual(attached.workflow_id, started.workflow_id)
            self.assertEqual(attached.run_id, started.run_id)

            conflicting = replace(
                self.request,
                mission_identity="autonomous-mission:foreign",
            )
            with self.assertRaises(AutonomousMissionWorkflowConflictError):
                await start_autonomous_mission_workflow(
                    self.environment.client, conflicting, self.settings
                )

            handle = self.environment.client.get_workflow_handle(
                started.workflow_id
            )
            await handle.cancel()
            with self.assertRaises(WorkflowFailureError):
                await handle.result()


if __name__ == "__main__":
    unittest.main()
