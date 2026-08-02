import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_factory.models import Agent
from agent_factory.registry import AgentRegistry


class RegistryTests(unittest.TestCase):
    def test_add_replace_enable_disable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agents.json"
            path.write_text('{"agents": []}', encoding="utf-8")
            registry = AgentRegistry(path)
            agent = Agent("a", "A", "Role", True, "deterministic", "Do work")
            registry.add(agent)
            self.assertTrue(registry.get("a").enabled)
            registry.set_enabled("a", False)
            self.assertFalse(registry.get("a").enabled)
            agent.name = "Replacement"
            registry.replace(agent)
            self.assertEqual(registry.get("a").name, "Replacement")

    def test_packaged_default_agents_are_discoverable(self):
        agents = AgentRegistry().list()
        ids = {agent.id for agent in agents}
        self.assertIn("policy-guardian", ids)
        self.assertIn("coding-worker-codex", ids)
        self.assertIn("coding-worker-antigravity", ids)
        self.assertIn("validation-agent", ids)

    def test_explicit_config_directory_overrides_packaged_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agents.json"
            path.write_text(
                json.dumps(
                    {
                        "agents": [
                            {
                                "id": "custom",
                                "name": "Custom",
                                "role": "Role",
                                "enabled": True,
                                "provider": "deterministic",
                                "instructions": "Return evidence",
                                "permissions": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ, {"AGENT_FACTORY_CONFIG_DIR": tmp}, clear=False
            ):
                registry = AgentRegistry()
                self.assertEqual([agent.id for agent in registry.list()], ["custom"])


if __name__ == "__main__":
    unittest.main()
