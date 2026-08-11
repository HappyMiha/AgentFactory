import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.engineering_loop import (
    EngineeringLoopService,
    IterationUsage,
    LoopLimits,
)
from agent_factory.models import WorkItem
from agent_factory.storage import SQLiteStorage


class EngineeringLoopTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.storage = SQLiteStorage(self.root / "state.db")
        project_id = self.storage.create_project("Loop", "AF-008")
        task_id = self.storage.create_task(WorkItem(
            "Repair candidate", "Bounded loop", project_id,
            acceptance_criteria=["Evidence is accepted"],
        ))
        self.run_id = self.storage.start_durable_run(
            project_id=project_id, task_id=task_id, workflow_id="engineering-loop",
            workflow_version="1", definition={"id": "engineering-loop"},
            stages=[{"id": "repair", "depends_on": []}],
        )

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    @staticmethod
    def limits(**changes):
        values = {
            "max_iterations": 4, "max_seconds": 100, "max_tokens": 1000,
            "max_cost_usd": 5.0, "max_tool_failures": 2,
        }
        values.update(changes)
        return LoopLimits(**values)

    def create_loop(self, **changes):
        action = changes.pop("repeated_failure_action", "replan")
        return EngineeringLoopService(self.storage).create(
            run_id=self.run_id, objective="Produce accepted evidence",
            worker_id="codex-worker", limits=self.limits(**changes),
            repeated_failure_action=action,
        )

    def record(self, service, loop_id, **changes):
        values = {
            "plan": {"steps": ["implement", "validate", "critic"]},
            "diff_digest": "a" * 64,
            "validator_results": [{"category": "test", "status": "failed"}],
            "critic_result": {"verdict": "repair", "concerns": ["test failed"]},
            "usage": IterationUsage(seconds=3, tokens=20, cost_usd=0.1),
            "failure": {"code": "test_failure", "criterion": 0},
        }
        values.update(changes)
        return service.record_iteration(loop_id, **values)

    def test_iteration_snapshot_survives_restart_and_is_immutable(self):
        service = EngineeringLoopService(self.storage)
        loop_id = self.create_loop()
        result = self.record(service, loop_id)
        self.assertEqual(result.outcome, "repair")
        self.storage.close()

        self.storage = SQLiteStorage(self.root / "state.db")
        state = EngineeringLoopService(self.storage).state(loop_id)
        iteration = state["iterations"][0]
        self.assertEqual(iteration["objective"], "Produce accepted evidence")
        self.assertEqual(iteration["plan"]["steps"][1], "validate")
        self.assertEqual(iteration["diff_digest"], "a" * 64)
        self.assertEqual(iteration["validator_results"][0]["category"], "test")
        self.assertEqual(iteration["critic_result"]["verdict"], "repair")
        self.assertEqual(iteration["budget_usage"]["cumulative"]["tokens"], 20)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE engineering_iterations SET outcome='accepted' WHERE id=?",
                (result.id,),
            )

    def test_same_failure_twice_forces_policy_action(self):
        service = EngineeringLoopService(self.storage)
        loop_id = self.create_loop(repeated_failure_action="replace_worker")
        first = self.record(service, loop_id)
        second = self.record(service, loop_id, diff_digest="b" * 64)
        self.assertEqual(first.outcome, "repair")
        self.assertEqual(second.outcome, "replace_worker")
        self.assertEqual(second.consecutive_failure_count, 2)
        events = self.storage.db.execute(
            "SELECT event_type FROM events WHERE entity_type='engineering_iteration' ORDER BY id"
        ).fetchall()
        self.assertEqual(events[-1][0], "engineering.iteration.replace_worker")

    def test_every_limit_pauses_deterministically(self):
        cases = (
            ({"max_iterations": 1}, {}),
            ({"max_seconds": 2}, {"usage": IterationUsage(seconds=3)}),
            ({"max_tokens": 10}, {"usage": IterationUsage(tokens=11)}),
            ({"max_cost_usd": 0.05}, {"usage": IterationUsage(cost_usd=0.1)}),
            ({"max_tool_failures": 0}, {"usage": IterationUsage(tool_failures=1)}),
        )
        for index, (limit_change, record_change) in enumerate(cases):
            with self.subTest(limit=next(iter(limit_change))):
                if index:
                    project_id = self.storage.create_project(f"Loop {index}", "AF-008")
                    task_id = self.storage.create_task(WorkItem(
                        f"Task {index}", "Bounded", project_id,
                        acceptance_criteria=["Evidence is accepted"],
                    ))
                    self.run_id = self.storage.start_durable_run(
                        project_id=project_id, task_id=task_id,
                        workflow_id=f"engineering-loop-{index}", workflow_version="1",
                        definition={"id": f"engineering-loop-{index}"},
                        stages=[{"id": "repair", "depends_on": []}],
                    )
                service = EngineeringLoopService(self.storage)
                result = self.record(service, self.create_loop(**limit_change), **record_change)
                self.assertEqual(result.outcome, "paused")
                self.assertEqual(result.loop_status, "paused")

    def test_terminal_states_require_evidence_failure_or_human_escalation(self):
        service = EngineeringLoopService(self.storage)
        loop_id = self.create_loop()
        with self.assertRaisesRegex(sqlite3.DatabaseError, "requires evidence"):
            self.storage.db.execute(
                "UPDATE engineering_loops SET status='accepted' WHERE id=?", (loop_id,)
            )
        with self.assertRaisesRegex(PermissionError, "accepted evidence"):
            self.record(service, loop_id, accept=True, accepted_evidence=False)
        accepted = self.record(
            service, loop_id, accept=True, accepted_evidence=True,
            failure=None, critic_result={"verdict": "pass"},
            validator_results=[{"category": "test", "status": "succeeded"}],
        )
        self.assertEqual(accepted.loop_status, "accepted")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "terminal.*immutable"):
            self.storage.db.execute(
                "UPDATE engineering_loops SET termination_reason='rewritten' WHERE id=?",
                (loop_id,),
            )

        project_id = self.storage.create_project("Failure", "AF-008")
        task_id = self.storage.create_task(WorkItem("Failure", "Explicit", project_id))
        self.run_id = self.storage.start_durable_run(
            project_id=project_id, task_id=task_id, workflow_id="failure-loop",
            workflow_version="1", definition={"id": "failure-loop"},
            stages=[{"id": "repair", "depends_on": []}],
        )
        failed_id = self.create_loop()
        failed = self.record(service, failed_id, explicit_failure="unsupported repository")
        self.assertEqual(failed.loop_status, "failed")

        project_id = self.storage.create_project("Escalation", "AF-008")
        task_id = self.storage.create_task(WorkItem("Escalate", "Human", project_id))
        self.run_id = self.storage.start_durable_run(
            project_id=project_id, task_id=task_id, workflow_id="escalation-loop",
            workflow_version="1", definition={"id": "escalation-loop"},
            stages=[{"id": "repair", "depends_on": []}],
        )
        escalated_id = self.create_loop()
        service.escalate(escalated_id, actor="Founder", reason="Scope decision required")
        state = service.state(escalated_id)["loop"]
        self.assertEqual(state["status"], "escalated")
        self.assertEqual(state["termination_actor"], "Founder")

    def test_limit_increase_requires_human_approval_and_is_audited(self):
        service = EngineeringLoopService(self.storage)
        loop_id = self.create_loop(max_iterations=1)
        self.assertEqual(self.record(service, loop_id).loop_status, "paused")
        with self.assertRaisesRegex(PermissionError, "human approval"):
            service.resume_with_approved_limits(
                loop_id, limits=self.limits(max_iterations=2),
                approved_by="", approval_note="",
            )
        service.resume_with_approved_limits(
            loop_id, limits=self.limits(max_iterations=2),
            approved_by="Founder", approval_note="One bounded repair approved",
        )
        state = service.state(loop_id)["loop"]
        self.assertEqual(state["status"], "active")
        revision = self.storage.db.execute(
            "SELECT * FROM engineering_loop_limit_revisions WHERE loop_id=?", (loop_id,)
        ).fetchone()
        self.assertEqual(revision["approved_by"], "Founder")
        self.assertEqual(json.loads(revision["new_limits_json"])["max_iterations"], 2)


if __name__ == "__main__":
    unittest.main()
