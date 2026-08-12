import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.execution_telemetry import ExecutionBudgets, ExecutionTelemetryService
from agent_factory.models import WorkItem
from agent_factory.observability import ObservabilityService
from agent_factory.storage import SQLiteStorage


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self.temporary.name) / "state.db")
        project_id = self.storage.create_project("Observability", "AF-027")
        task_id = self.storage.create_task(WorkItem("Observe", "Export telemetry", project_id))
        run_id = self.storage.start_durable_run(
            project_id=project_id, task_id=task_id,
            workflow_id="observability", workflow_version="1",
            definition={"id": "observability"}, stages=[{"id": "execute", "depends_on": []}],
        )
        self.trace = ExecutionTelemetryService(self.storage).create(
            task_id=task_id, run_id=run_id,
            budgets=ExecutionBudgets(1000, 2.0, 5, 2, 10),
        )
        self.service = ObservabilityService(self.storage)

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def test_export_preserves_correlation_identity_and_is_idempotent(self):
        telemetry = ExecutionTelemetryService(self.storage)
        telemetry.reserve_stage(self.trace.id, "implementation")
        telemetry.ingest(
            self.trace.id, idempotency_key="sample-1", stage_key="implementation",
            duration_ms=125, tokens=25, estimated_cost_usd=0.15, tool_calls=2,
            metadata={"provider": "codex"},
        )
        exports = []
        first = self.service.export_trace(self.trace.id, sink=exports.append)
        replay = self.service.export_trace(self.trace.id, sink=exports.append)
        self.assertEqual(first, replay)
        self.assertEqual(len(exports), 1)
        self.assertEqual(first["trace_id"], self.trace.correlation_root)
        self.assertEqual(first["spans"][0]["name"], "implementation")
        self.assertEqual(first["spans"][0]["tokens"], 25)
        self.assertEqual(first["metrics"]["iteration_count"], 0)
        self.assertEqual(
            self.storage.db.execute("SELECT COUNT(*) FROM otel_exports").fetchone()[0], 1
        )

    def test_cost_ledger_accepts_provider_and_estimated_usage_with_replay(self):
        provider = self.service.record_cost(
            self.trace.id, idempotency_key="cost-provider-1", provider="codex",
            source="provider_reported", tokens=30, duration_ms=200, cost_usd=0.31,
            metadata={"invoice": "provider-123"},
        )
        estimated = self.service.record_cost(
            self.trace.id, idempotency_key="cost-estimated-1", provider="hermes",
            source="estimated", tokens=10, duration_ms=100, cost_usd=0.05,
        )
        self.assertEqual(provider.source, "provider_reported")
        self.assertEqual(estimated.source, "estimated")
        self.assertEqual(
            self.service.record_cost(
                self.trace.id, idempotency_key="cost-provider-1", provider="other",
                source="estimated", tokens=1, duration_ms=1, cost_usd=0.01,
            ),
            provider,
        )
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE cost_ledger_entries SET cost_usd=0 WHERE id=?", (provider.id,)
            )

    def test_threshold_actions_are_deterministic_and_hard_budget_increase_is_human_gated(self):
        telemetry = ExecutionTelemetryService(self.storage)
        telemetry.reserve_stage(self.trace.id, "implementation")
        telemetry.ingest(
            self.trace.id, idempotency_key="sample-threshold", stage_key="implementation",
            duration_ms=100, tokens=50, estimated_cost_usd=0.4, tool_calls=1,
        )
        notify_id = self.service.add_threshold_policy(
            policy_key="notify-cost", metric="cost_usd", threshold=0.3,
            action="notify", created_by="budget-admin",
        )
        pause_id = self.service.add_threshold_policy(
            policy_key="pause-tokens", metric="tokens", threshold=40,
            action="pause", created_by="budget-admin",
        )
        approval_id = self.service.add_threshold_policy(
            policy_key="approve-duration", metric="duration_ms", threshold=50,
            action="require_approval", created_by="budget-admin",
        )
        actions = self.service.evaluate_thresholds(self.trace.id)
        self.assertEqual(
            [(item["policy_key"], item["action"], item["status"]) for item in actions],
            [
                ("notify-cost", "notify", "applied"),
                ("pause-tokens", "pause", "applied"),
                ("approve-duration", "require_approval", "awaiting_approval"),
            ],
        )
        self.assertEqual(self.service.evaluate_thresholds(self.trace.id), actions)
        self.assertEqual(self.storage.db.execute(
            "SELECT status FROM execution_traces WHERE id=?", (self.trace.id,)
        ).fetchone()[0], "paused")
        with self.assertRaisesRegex(PermissionError, "human budget authority"):
            self.service.increase_hard_budget(
                self.trace.id, new_max_cost_usd=3.0,
                authority="operator", authority_role="operator", reason="needed",
            )
        authorization_id = self.service.increase_hard_budget(
            self.trace.id, new_max_cost_usd=3.0,
            authority="BudgetLead", authority_role="human_budget_authority",
            reason="Approved after threshold review",
        )
        self.assertGreater(authorization_id, 0)
        self.assertEqual(self.storage.db.execute(
            "SELECT max_cost_usd FROM execution_traces WHERE id=?", (self.trace.id,)
        ).fetchone()[0], 3.0)
        self.assertEqual({notify_id, pause_id, approval_id}, {
            row["policy_id"] for row in self.storage.db.execute(
                "SELECT policy_id FROM budget_threshold_actions WHERE trace_id=?", (self.trace.id,)
            )
        })


if __name__ == "__main__":
    unittest.main()
