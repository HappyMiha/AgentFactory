import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from fastapi.testclient import TestClient

from agent_factory.application import AgentFactoryService
from agent_factory.providers import DeterministicProvider
from agent_factory.runtime import AgentRuntime
from agent_factory.storage import SQLiteStorage
from agent_factory.web import create_app, validate_loopback_host

ROOT = Path(__file__).resolve().parent.parent


def seed(workspace: Path, database: Path) -> tuple[int, int, int]:
    storage = SQLiteStorage(database)
    runtime = AgentRuntime(
        {
            name: DeterministicProvider()
            for name in (
                "deterministic",
                "codex",
                "claude",
                "gemini",
                "antigravity",
                "ollama",
            )
        },
        workspace=workspace,
    )
    service = AgentFactoryService(storage, runtime=runtime, workspace=workspace)
    project = service.create_project("Control Center API")
    item = service.create_work_item(
        project_id=project.project_id,
        title="Read operations",
        description="Expose typed state",
        acceptance_criteria=["Responses are bounded"],
    )
    run = service.run_workflow(item.id)
    storage.close()
    return project.project_id, item.id, run.id


class WebHostTests(unittest.TestCase):
    def test_documented_cli_command_starts_and_stops_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = int(reservation.getsockname()[1])
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(ROOT / "src")
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "agent_factory",
                    "--workspace",
                    str(workspace),
                    "web",
                    "--port",
                    str(port),
                ],
                cwd=ROOT,
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                payload = None
                for _ in range(100):
                    if process.poll() is not None:
                        break
                    try:
                        with urlopen(
                            f"http://127.0.0.1:{port}/api/health", timeout=1
                        ) as response:
                            payload = json.load(response)
                        break
                    except URLError:
                        time.sleep(0.05)
                self.assertIsNotNone(
                    payload,
                    process.stderr.read() if process.poll() is not None else "server timeout",
                )
                self.assertEqual(payload["status"], "ready")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                if process.stderr is not None:
                    process.stderr.close()

    def test_only_loopback_hosts_are_accepted(self):
        self.assertEqual(validate_loopback_host("127.0.0.1"), "127.0.0.1")
        self.assertEqual(validate_loopback_host("LOCALHOST"), "localhost")
        self.assertEqual(validate_loopback_host("::1"), "::1")
        for host in ("0.0.0.0", "192.168.1.10", "example.com", ""):
            with self.subTest(host=host), self.assertRaisesRegex(
                ValueError, "loopback"
            ):
                validate_loopback_host(host)

    def test_empty_database_health_and_resource_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            database = workspace / ".agent-factory" / "state.db"
            with TestClient(create_app(workspace, database)) as client:
                health = client.get("/api/health")
                self.assertEqual(health.status_code, 200)
                self.assertEqual(health.json()["status"], "ready")
                for endpoint in (
                    "projects",
                    "work-items",
                    "runs",
                    "artifacts",
                    "reviews",
                    "approvals",
                    "events",
                ):
                    response = client.get(f"/api/{endpoint}")
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["items"], [])
                    self.assertEqual(response.json()["total"], 0)

    def test_typed_resources_pagination_missing_and_malformed_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            database = workspace / ".agent-factory" / "state.db"
            project_id, task_id, run_id = seed(workspace, database)
            with TestClient(create_app(workspace, database)) as client:
                projects = client.get("/api/projects", params={"offset": 0, "limit": 1})
                self.assertEqual(projects.status_code, 200)
                self.assertEqual(projects.json()["total"], 1)
                self.assertEqual(projects.json()["items"][0]["id"], project_id)
                self.assertEqual(
                    client.get(f"/api/work-items/{task_id}").json()["title"],
                    "Read operations",
                )
                self.assertEqual(
                    client.get(f"/api/runs/{run_id}").json()["status"],
                    "awaiting_approval",
                )
                self.assertEqual(client.get("/api/artifacts").json()["total"], 4)
                self.assertGreater(client.get("/api/agents").json()["total"], 1)
                self.assertGreater(client.get("/api/providers").json()["total"], 1)
                self.assertEqual(client.get("/api/reviews").json()["total"], 2)
                self.assertEqual(client.get("/api/approvals").json()["total"], 1)
                self.assertGreater(client.get("/api/events").json()["total"], 1)
                self.assertEqual(
                    client.get("/api/settings").json()["workspace"],
                    str(workspace.resolve()),
                )
                integrations = {
                    item["name"]: item for item in client.get("/api/integrations").json()
                }
                self.assertEqual(integrations["github"]["status"], "unconfigured")

                missing = client.get("/api/work-items/999")
                self.assertEqual(missing.status_code, 404)
                self.assertEqual(missing.json()["error"]["code"], "not_found")
                malformed = client.get("/api/work-items/not-an-integer")
                self.assertEqual(malformed.status_code, 422)
                self.assertEqual(
                    malformed.json()["error"]["code"], "validation_error"
                )
                for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
                    response = client.get("/api/projects", params=params)
                    self.assertEqual(response.status_code, 422)

    def test_concurrent_reads_use_independent_sqlite_connections(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            database = workspace / ".agent-factory" / "state.db"
            _, task_id, _ = seed(workspace, database)
            with TestClient(create_app(workspace, database)) as client:
                paths = [
                    "/api/projects",
                    "/api/work-items",
                    f"/api/work-items/{task_id}",
                    "/api/runs",
                    "/api/events?limit=10",
                ] * 4
                with ThreadPoolExecutor(max_workers=8) as pool:
                    responses = list(pool.map(client.get, paths))
                self.assertTrue(all(response.status_code == 200 for response in responses))

    def test_openapi_exposes_read_only_api_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with TestClient(
                create_app(workspace, workspace / ".agent-factory" / "state.db")
            ) as client:
                paths = client.get("/api/openapi.json").json()["paths"]
                self.assertIn("/api/projects", paths)
                self.assertTrue(
                    all(set(operations).issubset({"get", "head"}) for operations in paths.values())
                )


if __name__ == "__main__":
    unittest.main()
