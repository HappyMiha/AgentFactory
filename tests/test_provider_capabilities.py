import json
import sys
import tempfile
import unittest
from pathlib import Path

from agent_factory.models import (
    Agent,
    ExecutionLocation,
    ProviderCapabilities,
    WorkItem,
)
from agent_factory.providers import CLIProvider
from agent_factory.runtime import AgentRuntime


ROOT = Path(__file__).resolve().parent.parent


class ProviderCapabilityTests(unittest.TestCase):
    def test_missing_location_is_compatible_but_fails_closed_for_autonomous_use(self):
        legacy = ProviderCapabilities.from_config(
            {"id": "ollama", "capabilities": {"text_generation": True}}
        )
        self.assertEqual(legacy.execution_location, ExecutionLocation.REMOTE)
        self.assertFalse(legacy.location_declared)
        self.assertFalse(legacy.autonomous_local_eligible)

        explicit = ProviderCapabilities.from_config(
            {
                "id": "arbitrary-name",
                "execution_location": "LOCAL",
                "capabilities": {"text_generation": True},
            }
        )
        self.assertTrue(explicit.location_declared)
        self.assertTrue(explicit.autonomous_local_eligible)

    def test_provider_name_cannot_imply_locality_or_bypass_standard_gate(self):
        provider = CLIProvider(
            "ollama",
            sys.executable,
            ["-c", "print(input())"],
            allow_execution=True,
        )
        self.assertFalse(provider.autonomous_local_eligible)

        local = CLIProvider(
            "not-ollama",
            sys.executable,
            ["-c", "print(input())"],
            allow_execution=True,
            capabilities=ProviderCapabilities.from_config(
                {
                    "execution_location": "LOCAL",
                    "capabilities": {"text_generation": True},
                }
            ),
        )
        self.assertTrue(local.autonomous_local_eligible)
        agent = Agent(
            id="worker",
            name="Worker",
            role="Implementation Worker",
            enabled=True,
            provider="not-ollama",
            instructions="Return evidence",
        )
        item = WorkItem("Task", "Description", 1, id=7)
        result = local.execute(agent, item, {})
        self.assertFalse(result.ok)
        self.assertIn("approval required", result.error)

    def test_runtime_loads_explicit_capabilities_and_safe_legacy_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            config = workspace / ".agent-factory" / "config"
            config.mkdir(parents=True)
            (config / "policy.json").write_text(
                json.dumps({"prompt": {}, "execution": {}}), encoding="utf-8"
            )
            (config / "providers.json").write_text(
                json.dumps(
                    {
                        "providers": [
                            {
                                "id": "explicit-local",
                                "type": "cli",
                                "enabled": True,
                                "executable": sys.executable,
                                "args": ["-c", "print(input())"],
                                "allow_execution": True,
                                "execution_location": "LOCAL",
                                "capabilities": {
                                    "text_generation": True,
                                    "structured_output": True,
                                    "tool_calls": False,
                                    "model_listing": True,
                                    "model_switching": True,
                                    "model_load_release": True,
                                },
                            },
                            {
                                "id": "legacy",
                                "type": "cli",
                                "enabled": True,
                                "executable": sys.executable,
                                "args": [],
                                "allow_execution": True,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            runtime = AgentRuntime(workspace=workspace)
            local = runtime.providers["explicit-local"]
            legacy = runtime.providers["legacy"]
            self.assertTrue(local.autonomous_local_eligible)
            self.assertTrue(local.capabilities.model_switching)
            self.assertTrue(local.capabilities.model_load_release)
            self.assertFalse(legacy.autonomous_local_eligible)
            self.assertEqual(
                legacy.capabilities.execution_location, ExecutionLocation.REMOTE
            )

    def test_invalid_capability_contracts_fail_during_configuration(self):
        with self.assertRaisesRegex(ValueError, "requires model-listing"):
            ProviderCapabilities.from_config(
                {
                    "execution_location": "LOCAL",
                    "capabilities": {
                        "text_generation": True,
                        "model_switching": True,
                    },
                }
            )
        with self.assertRaisesRegex(TypeError, "must be boolean"):
            ProviderCapabilities.from_config(
                {
                    "execution_location": "LOCAL",
                    "capabilities": {"text_generation": "yes"},
                }
            )

    def test_shipped_catalog_declares_every_location_and_capability(self):
        document = json.loads(
            (ROOT / "src" / "agent_factory" / "defaults" / "providers.json").read_text(
                encoding="utf-8"
            )
        )
        required = {
            "text_generation",
            "structured_output",
            "tool_calls",
            "model_listing",
            "model_switching",
            "model_load_release",
        }
        providers = {value["id"]: value for value in document["providers"]}
        for provider_id, value in providers.items():
            with self.subTest(provider=provider_id):
                self.assertIn(value["execution_location"], {"LOCAL", "REMOTE"})
                self.assertEqual(set(value["capabilities"]), required)
                ProviderCapabilities.from_config(value)
        self.assertTrue(
            ProviderCapabilities.from_config(providers["ollama"])
            .autonomous_local_eligible
        )
        self.assertEqual(providers["codex"]["execution_location"], "REMOTE")


if __name__ == "__main__":
    unittest.main()
