"""Inventory routes use the real Core authentication and event-loop boundary."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_factory.hardware_web import install_routes
from agent_factory.web import create_app


class HardwareWebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {
            "AGENT_FACTORY_API_TOKEN": "synthetic-hardware-token",
            "AGENT_FACTORY_API_ACTOR": "Founder",
            "AGENT_FACTORY_API_ROLE": "operations_owner",
            "AGENT_FACTORY_API_SCOPES": "read,write,approve,control",
            "AGENT_FACTORY_API_TENANTS": "*",
            "AGENT_FACTORY_TEMPORAL_ENABLED": "false",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.collector = Mock(return_value={"schema_version": 1, "gpu_status": "unknown"})
        self.app = self.make_app(self.root / "state.db", self.collector)
        self.client = TestClient(self.app, base_url="http://127.0.0.1")
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.headers = {"Authorization": "Bearer synthetic-hardware-token"}

    def make_app(self, database, collector):
        # Bind before composition so Core010's default installer captures the
        # fixture too. The fallback supports the pre-composition Core007 base.
        # Core010 separately asserts its default app installs these routes.
        with patch("agent_factory.hardware_web.collect_inventory", collector):
            app = create_app(self.root, database)
            if not getattr(app.state, "hardware_routes_installed", False):
                install_routes(app, self.root)
        return app

    def post(self, **kwargs):
        return self.client.post("/api/hardware/scan", json={}, headers=self.headers, **kwargs)

    def test_no_probe_until_authorized_explicit_scan_and_no_database_side_effect(self):
        before = list(self.root.iterdir())
        self.assertEqual(self.client.get("/hardware").status_code, 200)
        self.assertIn('id="token"', self.client.get("/hardware").text)
        self.assertEqual(self.client.get("/api/hardware/scan", headers=self.headers).status_code, 405)
        self.assertEqual(self.client.post("/api/hardware/scan", json={}).status_code, 401)
        self.collector.assert_not_called()
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["gpu_status"], "unknown")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.collector.assert_called_once_with(self.root.resolve())
        self.assertEqual(list(self.root.iterdir()), before)

    def test_write_scope_required_by_existing_post_policy_before_probe(self):
        with patch.dict(os.environ, {"AGENT_FACTORY_API_SCOPES": "read"}):
            self.assertEqual(self.post().status_code, 403)
        self.collector.assert_not_called()

    def test_origin_and_host_are_checked_before_probe(self):
        for headers in (
            {**self.headers, "Origin": "https://untrusted.example"},
            {**self.headers, "Host": "untrusted.example"},
        ):
            response = self.client.post("/api/hardware/scan", json={}, headers=headers)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.headers["cache-control"], "no-store")
        self.collector.assert_not_called()

    def test_http_cannot_select_path_command_or_probe(self):
        for value in ({"workspace": "another-path"}, {"command": "anything"}, {"confirmed": True}, []):
            response = self.client.post("/api/hardware/scan", json=value, headers=self.headers)
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.post(params={"workspace": "another-path"}).status_code, 400)
        self.collector.assert_not_called()

    def test_failure_is_redacted_and_does_not_keep_lock(self):
        self.collector.side_effect = RuntimeError("private-path-secret-canary")
        response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"error": {"code": "hardware_scan_failed"}})
        self.assertNotIn("canary", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.collector.side_effect = None
        self.assertEqual(self.post().status_code, 200)

    def test_slow_probe_does_not_block_home_or_queue_another_workspace(self):
        started, release = threading.Event(), threading.Event()
        def slow(_root):
            started.set()
            if not release.wait(8):
                raise TimeoutError("test barrier expired")
            return {"schema_version": 1}
        self.collector.side_effect = slow
        other_collector = Mock()
        other = self.make_app(self.root / "other.db", other_collector)
        with TestClient(other, base_url="http://127.0.0.1") as client, ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.post)
            try:
                self.assertTrue(started.wait(4))
                self.assertEqual(self.client.get("/", headers=self.headers).status_code, 200)
                self.assertEqual(self.post().status_code, 409)
                response = client.post("/api/hardware/scan", json={}, headers=self.headers)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["error"]["code"], "hardware_scan_in_progress")
                other_collector.assert_not_called()
                self.collector.assert_called_once()
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=4).status_code, 200)

    def test_installer_refuses_unprotected_host_or_duplicate_registration(self):
        with self.assertRaisesRegex(ValueError, "boundary"):
            install_routes(FastAPI(), self.root, collector=self.collector)
        with self.assertRaisesRegex(ValueError, "already installed"):
            install_routes(self.app, self.root, collector=self.collector)


if __name__ == "__main__":
    unittest.main()
