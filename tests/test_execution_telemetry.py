import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.application import AgentFactoryService
from agent_factory.execution_telemetry import (
    BudgetExceeded,
    ExecutionBudgets,
    ExecutionTelemetryService,
)
from agent_factory.models import WorkItem
from agent_factory.storage import SQLiteStorage


class ExecutionTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.storage = SQLiteStorage(self.workspace / "state.db")
        self.sequence = 0

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def trace(self, budgets):
        self.sequence += 1
        project_id = self.storage.create_project(f"Telemetry {self.sequence}", "AF-056")
        task_id = self.storage.create_task(WorkItem(
            f"Trace {self.sequence}", "Retain usage", project_id,
        ))
        run_id = self.storage.start_durable_run(
            project_id=project_id, task_id=task_id,
            workflow_id=f"telemetry-{self.sequence}", workflow_version="1",
            definition={"id": f"telemetry-{self.sequence}"},
            stages=[{"id": "execute", "depends_on": []}],
        )
        trace = ExecutionTelemetryService(self.storage).create(
            task_id=task_id, run_id=run_id, budgets=budgets,
        )
        return trace, task_id, run_id

    def test_token_cost_and_stage_preflight_budgets_block_and_pause(self):
        service = ExecutionTelemetryService(self.storage)
        cases = (
            (ExecutionBudgets(10, 5.0, 2, 1, 5), {"estimated_tokens": 11}, "token"),
            (ExecutionBudgets(10, 0.1, 2, 1, 5), {"estimated_cost_usd": 0.2}, "cost"),
        )
        for budgets, estimate, reason in cases:
            with self.subTest(reason=reason):
                trace, _, _ = self.trace(budgets)
                with self.assertRaisesRegex(BudgetExceeded, reason):
                    service.reserve_stage(trace.id, "implementation", **estimate)
                self.assertEqual(service.state(trace.id).status, "paused")

        trace, _, _ = self.trace(ExecutionBudgets(100, 5.0, 1, 1, 5))
        self.assertTrue(service.reserve_stage(trace.id, "implementation"))
        self.assertFalse(service.reserve_stage(trace.id, "implementation"))
        with self.assertRaisesRegex(BudgetExceeded, "stage"):
            service.reserve_stage(trace.id, "validation")
        self.assertEqual(service.state(trace.id).stages_reserved, 1)

    def test_usage_retry_and_terminal_reason_are_retained_idempotently(self):
        service = ExecutionTelemetryService(self.storage)
        trace, _, _ = self.trace(ExecutionBudgets(100, 2.0, 3, 1, 5))
        service.reserve_stage(trace.id, "implementation")
        first = service.ingest(
            trace.id, idempotency_key="worker:1", stage_key="implementation",
            duration_ms=1250, tokens=40, estimated_cost_usd=0.25, tool_calls=3,
            metadata={"runtime": "codex"},
        )
        replay = service.ingest(
            trace.id, idempotency_key="worker:1", stage_key="implementation",
            duration_ms=9999, tokens=99, estimated_cost_usd=1.0, tool_calls=1,
        )
        self.assertEqual(replay, first)
        self.assertTrue(service.record_retry(trace.id, "validator failed"))
        with self.assertRaisesRegex(BudgetExceeded, "retry"):
            service.record_retry(trace.id, "validator failed again")
        terminal = service.finish(trace.id, succeeded=False, reason="repair budget exhausted")
        self.assertEqual(terminal.status, "failed")
        self.assertEqual(terminal.duration_ms, 1250)
        self.assertEqual(terminal.retries, 2)
        self.assertEqual(terminal.tokens, 40)
        self.assertEqual(terminal.estimated_cost_usd, 0.25)
        self.assertEqual(terminal.tool_calls, 3)
        self.assertEqual(terminal.terminal_reason, "repair budget exhausted")
        sample = self.storage.db.execute("SELECT * FROM execution_usage_samples").fetchone()
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE execution_usage_samples SET tokens=0 WHERE id=?", (sample["id"],)
            )

    def test_dashboard_operational_state_includes_queue_leases_worktrees_failures_and_budgets(self):
        trace, _, _ = self.trace(ExecutionBudgets(100, 2.0, 3, 1, 5))
        service = ExecutionTelemetryService(self.storage)
        with self.assertRaises(BudgetExceeded):
            service.reserve_stage(trace.id, "too-expensive", estimated_tokens=101)
        dashboard = AgentFactoryService(
            self.storage, workspace=self.workspace
        ).operational_state()
        self.assertGreaterEqual(dashboard.queued_tasks, 1)
        self.assertEqual(dashboard.active_sessions, 0)
        self.assertEqual(dashboard.active_leases, 0)
        self.assertEqual(dashboard.active_worktrees, 0)
        self.assertGreaterEqual(dashboard.failures, 1)
        self.assertEqual(dashboard.budgets[0].status, "paused")
        self.assertIn("token budget", dashboard.budgets[0].terminal_reason)


if __name__ == "__main__":
    unittest.main()
