import json
import tempfile
import unittest
from pathlib import Path

from agent_factory.models import ProviderResult, WorkItem
from agent_factory.providers import DeterministicProvider, Provider
from agent_factory.runtime import AgentRuntime, ExecutionMode
from agent_factory.storage import SQLiteStorage
from agent_factory.workflow import WorkflowEngine


def seed_delivery(storage: SQLiteStorage) -> tuple[int, int]:
    project_id = storage.create_project("Example Project", "Workflow checks")
    task_id = storage.create_task(
        WorkItem(
            title="Deliver a reviewable capability",
            description="Produce a bounded result with acceptance evidence.",
            project_id=project_id,
            acceptance_criteria=["The result is independently reviewable"],
        )
    )
    return project_id, task_id


class WorkflowTests(unittest.TestCase):
    class FailingProvider(Provider):
        name = "failing"

        def health(self):
            return {"healthy": False}

        def execute(self, agent, item, context, approval=None):
            return ProviderResult(
                False,
                provider=self.name,
                error="live provider approval required",
            )

    @staticmethod
    def runtime(provider: Provider) -> AgentRuntime:
        return AgentRuntime(
            {
                "claude": provider,
                "codex": provider,
                "deterministic": DeterministicProvider(),
            }
        )

    def test_simulation_can_fall_back_and_labels_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "test.db")
            _, task_id = seed_delivery(storage)
            runtime = self.runtime(self.FailingProvider())
            run_id = WorkflowEngine(storage, runtime=runtime).run(
                "delivery", storage.get_task(task_id), ExecutionMode.SIMULATION
            )
            self.assertEqual(storage.latest_run()["status"], "awaiting_approval")
            self.assertTrue(
                all(
                    row["content"].startswith("[execution_mode=simulation]")
                    for row in storage.artifacts(run_id)
                )
            )
            mode_event = storage.db.execute(
                "SELECT payload FROM events WHERE event_type='workflow.mode.selected'"
            ).fetchone()
            self.assertIn('"mode": "simulation"', mode_event["payload"])
            storage.close()

    def test_live_never_falls_back_or_reaches_human_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "test.db")
            _, task_id = seed_delivery(storage)
            runtime = self.runtime(self.FailingProvider())
            with self.assertRaisesRegex(RuntimeError, "approval required"):
                WorkflowEngine(storage, runtime=runtime).run(
                    "delivery", storage.get_task(task_id), ExecutionMode.LIVE
                )
            self.assertEqual(storage.latest_run()["status"], "failed")
            self.assertEqual(len(storage.approvals()), 0)
            self.assertEqual(
                len(storage.artifacts(int(storage.latest_run()["id"]))), 0
            )
            storage.close()

    def test_end_to_end_creates_policy_checks_and_human_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "test.db")
            _, task_id = seed_delivery(storage)
            runtime = self.runtime(DeterministicProvider())
            run_id = WorkflowEngine(storage, runtime=runtime).run(
                "delivery", storage.get_task(task_id)
            )
            artifacts = storage.artifacts(run_id)
            self.assertEqual(storage.latest_run()["status"], "awaiting_approval")
            self.assertEqual(len(artifacts), 4)
            self.assertEqual(artifacts[0]["stage"], "policy-precheck")
            self.assertEqual(artifacts[-1]["stage"], "policy-postcheck")
            self.assertIn('"verdict": "ALIGNED"', artifacts[-1]["content"])
            assignments = storage.reviewer_assignments(run_id)
            self.assertEqual(len(assignments), 2)
            for assignment in assignments:
                self.assertIsNotNone(assignment["review_artifact_id"])
                self.assertIsNotNone(assignment["completed_at"])
                producer_models = {
                    producer["model"]
                    for producer in json.loads(assignment["producer_agents"])
                }
                self.assertNotIn(assignment["reviewer_model"], producer_models)
            self.assertEqual(storage.approvals()[0]["status"], "pending")
            self.assertGreater(
                storage.db.execute("SELECT count(*) FROM events").fetchone()[0], 7
            )
            storage.close()

    def test_human_decision_is_immutable_and_transitions_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "test.db")
            _, task_id = seed_delivery(storage)
            runtime = self.runtime(DeterministicProvider())
            run_id = WorkflowEngine(storage, runtime=runtime).run(
                "delivery", storage.get_task(task_id)
            )
            gate_id = int(storage.approvals()[0]["id"])
            storage.decide_approval(gate_id, "approved", "Human accepts")
            run = storage.db.execute(
                "SELECT * FROM workflow_runs WHERE id=?", (run_id,)
            ).fetchone()
            self.assertEqual(run["status"], "approved")
            self.assertIsNotNone(run["completed_at"])
            with self.assertRaises(ValueError):
                storage.decide_approval(gate_id, "rejected", "Changed mind")
            self.assertEqual(
                storage.approvals()[0]["decision_note"], "Human accepts"
            )
            storage.close()

    def test_run_requires_persisted_task_and_valid_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "test.db")
            project_id = storage.create_project("Project", "Test")
            with self.assertRaisesRegex(ValueError, "persisted"):
                storage.start_run(project_id, None, "delivery")
            with self.assertRaises(KeyError):
                storage.start_run(project_id, 999, "delivery")
            storage.close()

    def test_human_decision_rolls_back_when_audit_write_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "test.db")
            _, task_id = seed_delivery(storage)
            runtime = self.runtime(DeterministicProvider())
            run_id = WorkflowEngine(storage, runtime=runtime).run(
                "delivery", storage.get_task(task_id)
            )
            gate_id = int(storage.approvals()[0]["id"])
            storage.db.execute(
                """
                CREATE TRIGGER fail_approval_audit BEFORE INSERT ON events
                WHEN NEW.event_type='approval.approved'
                BEGIN SELECT RAISE(ABORT, 'simulated audit failure'); END
                """
            )
            with self.assertRaisesRegex(Exception, "simulated audit failure"):
                storage.decide_approval(gate_id, "approved", "Should roll back")
            gate = storage.db.execute(
                "SELECT status,decision_note FROM approval_gates WHERE id=?",
                (gate_id,),
            ).fetchone()
            run = storage.db.execute(
                "SELECT status FROM workflow_runs WHERE id=?", (run_id,)
            ).fetchone()
            self.assertEqual((gate["status"], gate["decision_note"]), ("pending", ""))
            self.assertEqual(run["status"], "awaiting_approval")
            storage.close()

    def test_artifact_human_review_is_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "test.db")
            _, task_id = seed_delivery(storage)
            runtime = self.runtime(DeterministicProvider())
            run_id = WorkflowEngine(storage, runtime=runtime).run(
                "delivery", storage.get_task(task_id)
            )
            artifact_id = storage.artifacts(run_id)[0]["id"]
            storage.review_artifact(artifact_id, "approved", "Clear scope")
            self.assertEqual(storage.artifacts(run_id)[0]["status"], "approved")
            self.assertEqual(
                storage.db.execute(
                    "SELECT event_type FROM events ORDER BY id DESC LIMIT 1"
                ).fetchone()[0],
                "artifact.approved",
            )
            storage.close()


if __name__ == "__main__":
    unittest.main()
