import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent_factory.storage import SQLiteStorage
from agent_factory.web import create_app


class MonitorWebTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.database = self.workspace / "state.db"
        self.config = self.workspace / "config"
        self.config.mkdir()
        # Never probe personal AI CLIs or inherit an operator's config override.
        self.enterContext(patch.dict(os.environ, {"AGENT_FACTORY_CONFIG_DIR": str(self.config)}))
        self.providers = [
            {"id": "fixture", "type": "cli", "enabled": True,
             "executable": sys.executable, "version_args": ["--version"],
             "allow_execution": False},
            {"id": "optional", "type": "cli", "enabled": False,
             "executable": str(self.workspace / "missing-optional-cli"),
             "allow_execution": False},
        ]

    def monitor(self):
        (self.config / "providers.json").write_text(
            json.dumps({"providers": self.providers}), encoding="utf-8"
        )
        with TestClient(create_app(self.workspace, self.database)) as client:
            response = client.get("/api/monitor")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_monitor_reports_ready_local_control_plane(self):
        payload = self.monitor()
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["migrations"]["current"], payload["migrations"]["latest"])
        self.assertTrue(payload["database"]["ok"])
        self.assertEqual(payload["blockers"], [])
        # Built-in deterministic provider plus a real Python --version probe.
        self.assertEqual(payload["providers"], {
            "total": 3, "ready": 2, "enabled": 2, "execution_enabled": 1,
        })
        self.assertGreaterEqual(payload["agents"]["enabled"], 1)

    def test_missing_enabled_provider_blocks_monitor_until_disabled(self):
        self.providers[1]["enabled"] = True
        payload = self.monitor()
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["blockers"], ["provider_health_degraded"])
        self.assertEqual(payload["providers"]["enabled"], 3)

        self.providers[1]["enabled"] = False
        payload = self.monitor()
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["blockers"], [])

    def test_failed_enabled_provider_probe_blocks_monitor(self):
        self.providers[0]["version_args"] = ["-c", "raise SystemExit(7)"]
        payload = self.monitor()
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["blockers"], ["provider_health_degraded"])
        self.assertEqual(payload["providers"]["ready"], 1)

    def test_monitor_surfaces_emergency_stop_as_blocker(self):
        storage = SQLiteStorage(self.database)
        try:
            storage.set_emergency_stop(True, actor="test", reason="maintenance")
        finally:
            storage.close()
        payload = self.monitor()
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["blockers"], ["emergency_stop_active"])
        self.assertTrue(payload["safety"]["emergency_stop"])


if __name__ == "__main__":
    unittest.main()
