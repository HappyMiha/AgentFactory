import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.storage import SQLiteStorage
from agent_factory.tools import ConnectorManager, ToolDescriptor, ToolGateway, ToolRegistry


def descriptor(key="web.search", connector="research-mcp", effects=("none",)):
    return ToolDescriptor(
        key=key, version="1.0.0", connector_key=connector,
        input_schema={
            "type": "object", "properties": {"query": {"type": "string"}},
            "required": ["query"], "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"result": {"type": "string"}, "source_digest": {"type": "string"}},
            "required": ["result", "source_digest"], "additionalProperties": False,
        },
        side_effects=tuple(effects), risk_tier="low" if effects == ("none",) else "high",
        required_capabilities=("web_research",), timeout_seconds=30,
        evidence_outputs=("source_digest",),
    )


class ToolGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self.temporary.name) / "state.db")
        self.registry = ToolRegistry(self.storage)
        self.manager = ConnectorManager(self.storage)
        self.gateway = ToolGateway(self.storage)

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def install(self, key="research-mcp"):
        connector_id = self.manager.install(
            connector_key=key, version="1.0.0", kind="mcp",
            environment="development", mutation_capable=False,
            manifest={"transport": "stdio", "command": ["research-server"]},
            actor="Operator",
        )
        self.manager.health(
            connector_id, healthy=True, actor="Health Probe", reason="handshake passed"
        )
        return connector_id

    def test_descriptor_requires_complete_contract_and_is_immutable(self):
        descriptor_id = self.registry.register(descriptor())
        row = self.storage.db.execute(
            "SELECT * FROM tool_descriptors WHERE id=?", (descriptor_id,)
        ).fetchone()
        document = json.loads(row["descriptor_json"])
        for key in (
            "input_schema", "output_schema", "side_effects", "risk_tier",
            "required_capabilities", "timeout_seconds", "evidence_outputs",
        ):
            self.assertIn(key, document)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE tool_descriptors SET descriptor_json='{}' WHERE id=?", (descriptor_id,)
            )
        with self.assertRaisesRegex(ValueError, "evidence outputs"):
            ToolDescriptor(
                key="bad", version="1.0.0", connector_key="bad",
                input_schema={"type": "object", "properties": {}},
                output_schema={"type": "object", "properties": {}},
                side_effects=("none",), risk_tier="low",
                required_capabilities=("read",), timeout_seconds=1,
                evidence_outputs=(),
            )

    def test_dynamic_discovery_never_expands_intersected_authority(self):
        connector_id = self.install()
        self.registry.register(descriptor())
        self.registry.register(descriptor("web.scrape"))
        authorized = self.gateway.discover(
            connector_id=connector_id, mission_id="mission-a", role_id="researcher",
            discovered_tools=("web.search", "web.scrape", "mcp.dynamic.admin"),
            mission_allowlist={"web.search", "web.scrape"},
            role_allowlist={"web.search", "mcp.dynamic.admin"},
            policy_allowlist={"web.search", "web.scrape", "mcp.dynamic.admin"},
        )
        self.assertEqual(authorized, ("web.search",))
        row = self.storage.db.execute("SELECT * FROM tool_discoveries").fetchone()
        self.assertIn("mcp.dynamic.admin", json.loads(row["discovered_json"]))
        self.assertNotIn("mcp.dynamic.admin", json.loads(row["authorized_json"]))
        with self.assertRaisesRegex(PermissionError, "allowlist"):
            self.gateway.invoke(
                tool_key="web.scrape", tool_version="1.0.0", connector_id=connector_id,
                mission_id="mission-a", role_id="researcher", arguments={"query": "x"},
                mission_allowlist={"web.search", "web.scrape"},
                role_allowlist={"web.search"}, policy_allowlist={"web.search", "web.scrape"},
                capabilities={"web_research"}, executor=lambda args, timeout: {
                    "result": "x", "source_digest": "a" * 64,
                },
            )

    def test_gateway_validates_schema_capability_health_timeout_and_evidence(self):
        connector_id = self.install()
        self.registry.register(descriptor())
        seen = {}

        def execute(arguments, timeout):
            seen.update(arguments=arguments, timeout=timeout)
            return {"result": "bounded", "source_digest": "a" * 64}

        invocation_id = self.gateway.invoke(
            tool_key="web.search", tool_version="1.0.0", connector_id=connector_id,
            mission_id="mission-a", role_id="researcher", arguments={"query": "agent factory"},
            mission_allowlist={"web.search"}, role_allowlist={"web.search"},
            policy_allowlist={"web.search"}, capabilities={"web_research"}, executor=execute,
        )
        self.assertEqual(seen["timeout"], 30)
        row = self.storage.db.execute(
            "SELECT * FROM tool_invocations WHERE id=?", (invocation_id,)
        ).fetchone()
        self.assertEqual(row["outcome"], "succeeded")
        self.assertEqual(len(row["evidence_digest"]), 64)
        with self.assertRaisesRegex(PermissionError, "capabilities"):
            self.gateway.invoke(
                tool_key="web.search", tool_version="1.0.0", connector_id=connector_id,
                mission_id="mission-a", role_id="researcher", arguments={"query": "x"},
                mission_allowlist={"web.search"}, role_allowlist={"web.search"},
                policy_allowlist={"web.search"}, capabilities=set(), executor=execute,
            )

    def test_connector_lifecycle_and_production_mutation_approval_are_auditable(self):
        with self.assertRaisesRegex(PermissionError, "human approval"):
            self.manager.install(
                connector_key="github-prod", version="1.0.0", kind="cli",
                environment="production", mutation_capable=True,
                manifest={"command": ["gh"]}, actor="Operator",
            )
        connector_id = self.manager.install(
            connector_key="github-prod", version="1.0.0", kind="cli",
            environment="production", mutation_capable=True,
            manifest={"command": ["gh"]}, actor="Operator", approved_by="Founder",
        )
        self.manager.health(
            connector_id, healthy=False, actor="Health Probe", reason="authentication failed"
        )
        self.manager.disable(connector_id, actor="Operator", reason="failed health")
        self.manager.upgrade(
            connector_id, version="1.1.0", kind="cli", environment="production",
            mutation_capable=True, manifest={"command": ["gh"], "profile": "restricted"},
            actor="Operator", approved_by="Founder",
        )
        self.manager.health(connector_id, healthy=True, actor="Health Probe", reason="passed")
        self.manager.remove(connector_id, actor="Operator", reason="retired")
        events = [row["event_type"] for row in self.storage.db.execute(
            "SELECT event_type FROM connector_lifecycle_events WHERE connector_id=? ORDER BY id",
            (connector_id,),
        )]
        self.assertEqual(events, [
            "installed", "health_failed", "disabled", "upgraded", "healthy", "removed",
        ])
        row = self.storage.db.execute(
            "SELECT status,version_counter FROM connector_instances WHERE id=?", (connector_id,)
        ).fetchone()
        self.assertEqual(row["status"], "removed")
        self.assertEqual(self.storage.db.execute(
            "SELECT approved_by FROM connector_versions WHERE connector_key='github-prod' AND version='1.1.0'"
        ).fetchone()[0], "Founder")


if __name__ == "__main__":
    unittest.main()
