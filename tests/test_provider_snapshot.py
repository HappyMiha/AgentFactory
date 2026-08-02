import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_factory.cli import _provider_invoke, _provider_snapshot_hashes
from agent_factory.models import Agent, WorkItem
from agent_factory.registry import AgentRegistry
from agent_factory.storage import SQLiteStorage


ROOT = Path(__file__).resolve().parent.parent


class ProviderApprovalSnapshotTests(unittest.TestCase):
    @staticmethod
    def write_json(path: Path, value: object, *, indent: int = 2) -> None:
        path.write_text(
            json.dumps(value, indent=indent, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def fixture(self, root: Path):
        config = root / "config"
        config.mkdir()
        agent = Agent(
            id="worker",
            name="Worker",
            role="Implementation Worker",
            enabled=True,
            provider="codex",
            instructions="Return one bounded artifact.",
            permissions=["read_project", "create_artifact"],
        )
        providers = {
            "providers": [
                {
                    "id": "codex",
                    "type": "cli",
                    "enabled": True,
                    "executable": "codex",
                    "args": ["exec", "-"],
                    "allow_execution": True,
                }
            ]
        }
        policy = {
            "prompt": {"max_chars": 50000, "rules": ["Return evidence."]},
            "execution": {"max_timeout": 120},
        }
        agents_path = config / "agents.json"
        providers_path = config / "providers.json"
        policy_path = config / "policy.json"
        self.write_json(agents_path, {"agents": [agent.__dict__]})
        self.write_json(providers_path, providers)
        self.write_json(policy_path, policy)

        storage = SQLiteStorage(root / "state.db")
        project_id = storage.create_project("Example", "Snapshot checks")
        task_id = storage.create_task(
            WorkItem(
                title="Create an artifact",
                description="Return bounded evidence.",
                project_id=project_id,
                acceptance_criteria=["Evidence is reviewable"],
            )
        )
        registry = AgentRegistry(agents_path)
        return storage, registry, providers_path, policy_path, task_id

    @staticmethod
    def approve_current_snapshot(
        storage: SQLiteStorage,
        registry: AgentRegistry,
        task_id: int,
    ) -> int:
        agent = registry.get("worker")
        item = storage.get_task(task_id)
        request_hash, definition_hash = _provider_snapshot_hashes(
            "codex", agent, item
        )
        gate_id = storage.request_provider_execution(
            "codex",
            agent.id,
            task_id,
            request_hash,
            definition_hash,
        )
        storage.decide_provider_execution(gate_id, "approved", "Exact snapshot")
        return gate_id

    def assert_invalidated(self, storage: SQLiteStorage, gate_id: int) -> None:
        gate = storage.db.execute(
            "SELECT status,decision_note FROM provider_execution_gates WHERE id=?",
            (gate_id,),
        ).fetchone()
        self.assertEqual(gate["status"], "rejected")
        self.assertIn("request a new gate", gate["decision_note"])
        self.assertEqual(
            storage.db.execute(
                "SELECT count(*) FROM provider_execution_attempts WHERE gate_id=?",
                (gate_id,),
            ).fetchone()[0],
            0,
        )

    def test_canonical_definition_hash_ignores_formatting_and_detects_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage, registry, providers_path, policy_path, task_id = self.fixture(root)
            with patch.dict(
                os.environ, {"AGENT_FACTORY_CONFIG_DIR": str(policy_path.parent)}
            ):
                agent = registry.get("worker")
                item = storage.get_task(task_id)
                first = _provider_snapshot_hashes("codex", agent, item)
                policy = json.loads(policy_path.read_text(encoding="utf-8"))
                self.write_json(policy_path, policy, indent=7)
                reformatted = _provider_snapshot_hashes("codex", agent, item)
                self.assertEqual(first, reformatted)
                policy["execution"]["max_timeout"] = 121
                self.write_json(policy_path, policy)
                changed = _provider_snapshot_hashes("codex", agent, item)
                self.assertEqual(first[0], changed[0])
                self.assertNotEqual(first[1], changed[1])
                policy["execution"]["max_timeout"] = 120
                self.write_json(policy_path, policy)
                providers = json.loads(providers_path.read_text(encoding="utf-8"))
                providers["providers"][0]["args"].append("--reviewed-option")
                self.write_json(providers_path, providers)
                provider_changed = _provider_snapshot_hashes("codex", agent, item)
                self.assertEqual(first[0], provider_changed[0])
                self.assertNotEqual(first[1], provider_changed[1])
            storage.close()

    def test_cli_request_persists_both_canonical_snapshot_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = SQLiteStorage(root / ".agent-factory" / "state.db")
            project_id = storage.create_project("Example", "CLI snapshot check")
            task_id = storage.create_task(
                WorkItem(
                    title="Create an artifact",
                    description="Return bounded evidence.",
                    project_id=project_id,
                    acceptance_criteria=["Evidence is reviewable"],
                )
            )
            storage.close()
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(ROOT / "src")
            requested = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agent_factory",
                    "--workspace",
                    str(root),
                    "providers",
                    "request",
                    "codex",
                    "--agent",
                    "coding-worker-codex",
                    "--task-id",
                    str(task_id),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
            self.assertEqual(requested.returncode, 0, requested.stderr)
            storage = SQLiteStorage(root / ".agent-factory" / "state.db")
            gate = storage.provider_execution_gates()[0]
            self.assertEqual(len(gate["request_hash"]), 64)
            self.assertEqual(len(gate["definition_hash"]), 64)
            self.assertNotEqual(gate["request_hash"], gate["definition_hash"])
            event = storage.db.execute(
                "SELECT payload FROM events "
                "WHERE event_type='provider.execution.requested'"
            ).fetchone()
            payload = json.loads(event["payload"])
            self.assertEqual(payload["request_hash"], gate["request_hash"])
            self.assertEqual(payload["definition_hash"], gate["definition_hash"])
            storage.close()

    def test_task_drift_blocks_invoke_and_requires_a_new_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage, registry, _, policy_path, task_id = self.fixture(root)
            with patch.dict(
                os.environ, {"AGENT_FACTORY_CONFIG_DIR": str(policy_path.parent)}
            ):
                gate_id = self.approve_current_snapshot(storage, registry, task_id)
                row = storage.db.execute(
                    "SELECT payload FROM work_items WHERE id=?", (task_id,)
                ).fetchone()
                payload = json.loads(row["payload"])
                payload["description"] = "Changed after approval."
                storage.db.execute(
                    "UPDATE work_items SET payload=? WHERE id=?",
                    (json.dumps(payload), task_id),
                )
                storage.db.commit()
                with self.assertRaisesRegex(PermissionError, "request a new gate"):
                    _provider_invoke(storage, registry, gate_id)
                self.assert_invalidated(storage, gate_id)
            storage.close()

    def test_agent_drift_blocks_invoke_and_requires_a_new_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage, registry, _, policy_path, task_id = self.fixture(root)
            with patch.dict(
                os.environ, {"AGENT_FACTORY_CONFIG_DIR": str(policy_path.parent)}
            ):
                gate_id = self.approve_current_snapshot(storage, registry, task_id)
                agents = json.loads(registry.path.read_text(encoding="utf-8"))
                agents["agents"][0]["instructions"] = "Changed after approval."
                self.write_json(registry.path, agents)
                with self.assertRaisesRegex(PermissionError, "request a new gate"):
                    _provider_invoke(storage, registry, gate_id)
                self.assert_invalidated(storage, gate_id)
            storage.close()

    def test_effective_policy_drift_blocks_invoke_and_requires_a_new_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage, registry, _, policy_path, task_id = self.fixture(root)
            with patch.dict(
                os.environ, {"AGENT_FACTORY_CONFIG_DIR": str(policy_path.parent)}
            ):
                gate_id = self.approve_current_snapshot(storage, registry, task_id)
                policy = json.loads(policy_path.read_text(encoding="utf-8"))
                policy["execution"]["max_timeout"] = 60
                self.write_json(policy_path, policy)
                with self.assertRaisesRegex(PermissionError, "request a new gate"):
                    _provider_invoke(storage, registry, gate_id)
                self.assert_invalidated(storage, gate_id)
            storage.close()


if __name__ == "__main__":
    unittest.main()
