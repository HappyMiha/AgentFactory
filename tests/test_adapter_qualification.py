import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.adapters import (
    HEALTH_DIMENSIONS,
    NormalizedAdapter,
    WorkerQualificationRegistry,
)
from agent_factory.models import Agent, ProviderResult, WorkItem
from agent_factory.providers import Provider
from agent_factory.storage import SQLiteStorage


class ContractProvider(Provider):
    def __init__(self, name: str, healthy: bool = True):
        self.name = name
        self.healthy = healthy

    def health(self):
        return {
            "provider": self.name,
            "healthy": self.healthy,
            "path": f"/{self.name}" if self.healthy else None,
            "version": "1.0" if self.healthy else None,
            "execution_enabled": True,
            "error": None if self.healthy else "not available",
        }

    def execute(self, agent, item, context, approval=None):
        return ProviderResult(
            ok=True,
            provider=self.name,
            content=f"{agent.id}:{item.title}:{context['scope']}",
            metadata={"contract": 1},
        )


class NormalizedAdapterContractTests(unittest.TestCase):
    def test_six_core_adapters_share_one_supported_operation_contract(self):
        providers = ("codex", "claude", "gemini", "antigravity", "ollama", "deterministic")
        agent = Agent(
            id="worker",
            name="Worker",
            role="Implementation Worker",
            enabled=True,
            provider="test",
            instructions="Return evidence",
        )
        item = WorkItem("Task", "Description", 1)
        for provider_id in providers:
            with self.subTest(provider=provider_id):
                adapter = NormalizedAdapter(ContractProvider(provider_id))
                self.assertEqual(adapter.operations, {"health", "execute"})
                health = adapter.health()
                self.assertEqual(set(health.dimensions), set(HEALTH_DIMENSIONS))
                self.assertTrue(health.available)
                result = adapter.execute(agent, item, {"scope": "contract"})
                self.assertTrue(result.ok)
                self.assertEqual(result.provider, provider_id)

    def test_health_distinguishes_all_required_dimensions(self):
        health = NormalizedAdapter(ContractProvider("codex", healthy=False)).health()
        self.assertFalse(health.available)
        self.assertEqual(health.dimensions["availability"]["status"], "missing")
        for dimension in HEALTH_DIMENSIONS:
            self.assertIn("status", health.dimensions[dimension])
            self.assertIn("evidence", health.dimensions[dimension])


class WorkerQualificationLifecycleTests(unittest.TestCase):
    def fixture(self, root: Path):
        storage = SQLiteStorage(root / "state.db")
        project_id = storage.create_project("Example", "Qualification")
        task_id = storage.create_task(WorkItem("Task", "Description", project_id))
        run_id = storage.start_run(project_id, task_id, "delivery")
        return storage, task_id, run_id

    def test_failed_worker_is_quarantined_and_handoff_selects_compatible_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, task_id, run_id = self.fixture(Path(tmp))
            registry = WorkerQualificationRegistry(storage)
            for worker_id, provider_id in (
                ("worker-codex", "codex"),
                ("worker-claude", "claude"),
            ):
                registry.qualify(
                    worker_id=worker_id,
                    provider_id=provider_id,
                    role="Implementation Worker",
                    capabilities={"read_project", "propose_code"},
                    adapter=NormalizedAdapter(ContractProvider(provider_id)),
                )

            replacement = registry.replacement_and_handoff(
                failed_worker_id="worker-codex",
                role="Implementation Worker",
                required_capabilities={"read_project", "propose_code"},
                task_id=task_id,
                run_id=run_id,
                stage_id="implementation",
                attempt_id="attempt:1",
                context_digest="c" * 64,
                evidence={"failure": "tool process exited", "last_checkpoint": 3},
                reason="Repeated provider failure",
            )
            self.assertEqual(replacement, "worker-claude")
            self.assertEqual(
                storage.db.execute(
                    "SELECT state FROM worker_lifecycle WHERE worker_id='worker-codex'"
                ).fetchone()[0],
                "quarantined",
            )
            handoff = storage.db.execute("SELECT * FROM worker_handoffs").fetchone()
            self.assertEqual(handoff["source_worker_id"], "worker-codex")
            self.assertEqual(handoff["replacement_worker_id"], "worker-claude")
            self.assertEqual(handoff["context_digest"], "c" * 64)
            self.assertEqual(json.loads(handoff["evidence_json"])["last_checkpoint"], 3)
            with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                storage.db.execute(
                    "UPDATE worker_handoffs SET reason='changed' WHERE id=?",
                    (handoff["id"],),
                )
            storage.close()

    def test_failed_or_expired_qualification_is_not_routable(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, _, _ = self.fixture(Path(tmp))
            registry = WorkerQualificationRegistry(storage)
            failed_id = registry.qualify(
                worker_id="worker-missing",
                provider_id="ollama",
                role="Implementation Worker",
                capabilities={"read_project"},
                adapter=NormalizedAdapter(ContractProvider("ollama", healthy=False)),
            )
            self.assertEqual(
                storage.db.execute(
                    "SELECT status FROM worker_qualifications WHERE id=?", (failed_id,)
                ).fetchone()[0],
                "failed",
            )
            self.assertIsNone(
                storage.select_qualified_worker(
                    role="Implementation Worker",
                    required_capabilities={"read_project"},
                )
            )

            qualification_id = registry.qualify(
                worker_id="worker-short-lived",
                provider_id="codex",
                role="Implementation Worker",
                capabilities={"read_project"},
                adapter=NormalizedAdapter(ContractProvider("codex")),
            )
            storage.db.execute(
                "DROP TRIGGER worker_qualifications_no_update"
            )
            storage.db.execute(
                "UPDATE worker_qualifications SET valid_until='2000-01-01 00:00:00' WHERE id=?",
                (qualification_id,),
            )
            storage.db.commit()
            self.assertIsNone(
                storage.select_qualified_worker(
                    role="Implementation Worker",
                    required_capabilities={"read_project"},
                )
            )
            storage.close()


if __name__ == "__main__":
    unittest.main()
