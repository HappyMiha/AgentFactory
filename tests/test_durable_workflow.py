import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.durable_workflow import DurableWorkflowExecution
from agent_factory.models import WorkItem
from agent_factory.storage import SQLiteStorage


def stage(stage_id, agent, dependencies=None):
    verdicts = ["ALIGNED"] if agent == "policy-guardian" else ["COMPLETE"]
    return {
        "id": stage_id,
        "name": stage_id,
        "agent": agent,
        "artifact": f"{stage_id}.json",
        "depends_on": dependencies or [],
        "acceptance_criteria": [f"{stage_id} criterion"],
        "contract": {"allowed_verdicts": verdicts},
    }


def definition():
    return {
        "id": "durable-delivery",
        "guardrails": {
            "precheck_stage": "policy-precheck",
            "postcheck_stage": "policy-postcheck",
            "guardian_agent": "policy-guardian",
        },
        "stages": [
            stage("policy-precheck", "policy-guardian"),
            stage("implementation", "worker", ["policy-precheck"]),
            stage("policy-postcheck", "policy-guardian", ["implementation"]),
        ],
    }


class DurableWorkflowTests(unittest.TestCase):
    def fixture(self, root: Path):
        storage = SQLiteStorage(root / "state.db")
        project_id = storage.create_project("Example", "Durable workflow")
        task_id = storage.create_task(WorkItem("Task", "Description", project_id))
        run_id = DurableWorkflowExecution(storage).start(
            project_id=project_id,
            task_id=task_id,
            workflow=definition(),
            version="2026.08.11.1",
        )
        return storage, run_id

    def test_version_is_pinned_and_every_stage_starts_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, run_id = self.fixture(Path(tmp))
            run = storage.durable_run(run_id)
            self.assertEqual(run["workflow_version"], "2026.08.11.1")
            self.assertEqual(len(run["definition_digest"]), 64)
            self.assertEqual(json.loads(run["definition_json"]), definition())
            self.assertEqual(
                [row["status"] for row in storage.durable_stages(run_id)],
                ["pending", "pending", "pending"],
            )
            with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                storage.db.execute(
                    "UPDATE workflow_runs SET workflow_version='changed' WHERE id=?",
                    (run_id,),
                )
            storage.close()

    def test_restart_resumes_at_first_dependency_ready_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage, run_id = self.fixture(root)
            execution = DurableWorkflowExecution(storage)
            self.assertEqual(execution.resume(run_id)["next_stage"]["stage_key"], "policy-precheck")
            execution.transition_stage(run_id, "policy-precheck", "running", {"attempt": 1})
            execution.transition_stage(run_id, "policy-precheck", "succeeded", {"artifact_id": 10})
            storage.close()

            reopened = SQLiteStorage(root / "state.db")
            resumed = DurableWorkflowExecution(reopened).resume(run_id)
            self.assertEqual(resumed["next_stage"]["stage_key"], "implementation")
            self.assertEqual(
                [row["state"] for row in reopened.db.execute(
                    "SELECT state FROM stage_checkpoints WHERE run_id=? ORDER BY sequence",
                    (run_id,),
                )],
                ["running", "succeeded"],
            )
            with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                reopened.db.execute(
                    "UPDATE stage_checkpoints SET payload_json='{}' WHERE run_id=?",
                    (run_id,),
                )
            reopened.close()

    def test_waiting_approval_is_durable_without_failing_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage, run_id = self.fixture(root)
            execution = DurableWorkflowExecution(storage)
            execution.transition_stage(run_id, "policy-precheck", "running", {})
            execution.transition_stage(
                run_id, "policy-precheck", "waiting_approval", {"gate": "policy"}
            )
            storage.close()
            reopened = SQLiteStorage(root / "state.db")
            state = DurableWorkflowExecution(reopened).resume(run_id)
            self.assertEqual(state["waiting_approval"][0]["stage_key"], "policy-precheck")
            DurableWorkflowExecution(reopened).transition_stage(
                run_id, "policy-precheck", "succeeded", {"approval_id": 1}
            )
            self.assertEqual(
                DurableWorkflowExecution(reopened).resume(run_id)["next_stage"]["stage_key"],
                "implementation",
            )
            reopened.close()

    def test_mutation_reservations_prevent_duplicate_external_operations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage, run_id = self.fixture(root)
            execution = DurableWorkflowExecution(storage)
            execution.transition_stage(run_id, "policy-precheck", "running", {})
            first = execution.reserve_mutation(
                run_id=run_id,
                stage_key="policy-precheck",
                operation="provider_call",
                idempotency_key="run:precheck:attempt:1",
                request={"provider": "codex", "prompt_digest": "a" * 64},
            )
            self.assertTrue(first.execute)
            storage.close()

            reopened = SQLiteStorage(root / "state.db")
            resumed = DurableWorkflowExecution(reopened).reserve_mutation(
                run_id=run_id,
                stage_key="policy-precheck",
                operation="provider_call",
                idempotency_key="run:precheck:attempt:1",
                request={"provider": "codex", "prompt_digest": "a" * 64},
            )
            self.assertFalse(resumed.execute)
            self.assertEqual(resumed.status, "reserved")
            DurableWorkflowExecution(reopened).complete_mutation(
                resumed.id, {"artifact_id": 7, "provider_call_id": "external-1"}
            )
            completed = DurableWorkflowExecution(reopened).reserve_mutation(
                run_id=run_id,
                stage_key="policy-precheck",
                operation="provider_call",
                idempotency_key="run:precheck:attempt:1",
                request={"provider": "codex", "prompt_digest": "a" * 64},
            )
            self.assertFalse(completed.execute)
            self.assertEqual(completed.result["provider_call_id"], "external-1")
            with self.assertRaisesRegex(ValueError, "different mutation"):
                DurableWorkflowExecution(reopened).reserve_mutation(
                    run_id=run_id,
                    stage_key="policy-precheck",
                    operation="provider_call",
                    idempotency_key="run:precheck:attempt:1",
                    request={"provider": "claude"},
                )
            reopened.close()


if __name__ == "__main__":
    unittest.main()
