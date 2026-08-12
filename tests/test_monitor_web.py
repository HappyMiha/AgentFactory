import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from agent_factory.storage import SQLiteStorage
from agent_factory.web import create_app


class MonitorWebTests(unittest.TestCase):
    def test_monitor_reports_ready_local_control_plane(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with TestClient(create_app(workspace, workspace / "state.db")) as client:
                response = client.get("/api/monitor")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "ready")
            self.assertEqual(payload["migrations"]["current"], payload["migrations"]["latest"])
            self.assertTrue(payload["database"]["ok"])
            self.assertEqual(payload["blockers"], [])
            self.assertGreaterEqual(payload["providers"]["ready"], 1)
            self.assertGreaterEqual(payload["agents"]["enabled"], 1)

    def test_monitor_surfaces_emergency_stop_as_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            database = workspace / "state.db"
            storage = SQLiteStorage(database)
            storage.set_emergency_stop(True, actor="test", reason="maintenance")
            storage.close()
            with TestClient(create_app(workspace, database)) as client:
                payload = client.get("/api/monitor").json()
            self.assertEqual(payload["status"], "degraded")
            self.assertIn("emergency_stop_active", payload["blockers"])
            self.assertTrue(payload["safety"]["emergency_stop"])


if __name__ == "__main__":
    unittest.main()
