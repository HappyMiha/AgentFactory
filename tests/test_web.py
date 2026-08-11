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
from agent_factory.backlog import load_backlog
from agent_factory.cli import _control_center_url, _schedule_browser_open, parser
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
    def test_web_open_flag_uses_loopback_url_without_blocking_shutdown(self):
        arguments = parser().parse_args(["--workspace", ".", "web", "--open"])
        self.assertTrue(arguments.open_browser)
        opened: list[str] = []
        timer = _schedule_browser_open(
            _control_center_url("127.0.0.1", 8765), delay=0, opener=opened.append
        )
        timer.join(timeout=2)
        self.assertEqual(opened, ["http://127.0.0.1:8765/"])
        self.assertTrue(timer.daemon)
        self.assertEqual(_control_center_url("::1", 8765), "http://[::1]:8765/")
        documentation = (ROOT / "docs" / "local-control-center.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'python -m pip install -e ".[web]"; if ($LASTEXITCODE -eq 0) '
            "{ python -m agent_factory --workspace . web --open }",
            documentation,
        )
        self.assertIn("Press `Ctrl+C`", documentation)
        self.assertIn("does not require or change `Set-ExecutionPolicy`", documentation)

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
                    except (TimeoutError, URLError):
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
                dashboard = client.get("/api/dashboard")
                self.assertEqual(dashboard.status_code, 200)
                self.assertEqual(
                    dashboard.json()["counts"],
                    {
                        "ready": 0,
                        "active": 0,
                        "blocked": 0,
                        "failed": 0,
                        "awaiting_review": 0,
                        "awaiting_approval": 0,
                    },
                )

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
                dashboard = client.get("/api/dashboard").json()
                self.assertEqual(dashboard["counts"]["ready"], 1)
                self.assertEqual(dashboard["counts"]["awaiting_review"], 4)
                self.assertEqual(dashboard["counts"]["awaiting_approval"], 1)
                self.assertEqual(dashboard["runs"][0]["id"], run_id)

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

    def test_openapi_exposes_only_reviewed_guarded_mutations(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with TestClient(
                create_app(workspace, workspace / ".agent-factory" / "state.db")
            ) as client:
                paths = client.get("/api/openapi.json").json()["paths"]
                self.assertIn("/api/projects", paths)
                mutation_routes = {
                    path
                    for path, operations in paths.items()
                    if "post" in operations
                }
                self.assertEqual(
                    mutation_routes,
                    {
                        "/api/work-items/{task_id}/claim",
                        "/api/work-items/{task_id}/runs",
                        "/api/artifacts/{artifact_id}/review",
                        "/api/agents/{agent_id}/enabled",
                        "/api/agents/{agent_id}/provider",
                        "/api/settings/{key}",
                        "/api/github/preview",
                        "/api/founder-decisions/{gate_id}",
                        "/api/backlog/import",
                    },
                )

    def test_founder_decision_packet_and_idempotent_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            database = workspace / ".agent-factory" / "state.db"
            _, task_id, run_id = seed(workspace, database)
            headers = {"X-Agent-Factory-Confirm": "true"}
            with TestClient(create_app(workspace, database)) as client:
                packets = client.get("/api/founder-decisions").json()
                self.assertEqual(len(packets), 1)
                packet = packets[0]
                gate_id = packet["approval"]["id"]
                self.assertEqual(packet["run"]["id"], run_id)
                self.assertEqual(
                    packet["work_item"]["acceptance_criteria"],
                    ["Responses are bounded"],
                )
                self.assertIn("implementation", [item["stage"] for item in packet["artifacts"]])
                self.assertIn("validation", [item["stage"] for item in packet["artifacts"]])
                self.assertEqual(len(packet["reviews"]), 2)
                self.assertIn("unresolved_findings", packet)
                for review in packet["reviews"]:
                    self.assertNotIn(
                        review["reviewer_model"].casefold(),
                        {
                            producer["model"].casefold()
                            for producer in review["producer_agents"]
                        },
                    )

                artifact_review = client.post(
                    f"/api/artifacts/{packet['artifacts'][0]['id']}/review",
                    headers=headers,
                    json={
                        "confirmed": True,
                        "task_id": task_id,
                        "decision": "approved",
                        "note": "Reviewer evidence only",
                    },
                )
                self.assertEqual(artifact_review.status_code, 200)
                self.assertEqual(
                    client.get("/api/founder-decisions").json()[0]["approval"]["status"],
                    "pending",
                )
                reviewer_actor = client.post(
                    f"/api/founder-decisions/{gate_id}",
                    headers=headers,
                    json={
                        "confirmed": True,
                        "decision": "approved",
                        "note": "Not authorized",
                        "actor": "Proxy Reviewer",
                    },
                )
                self.assertEqual(reviewer_actor.status_code, 422)
                unconfirmed = client.post(
                    f"/api/founder-decisions/{gate_id}",
                    json={"confirmed": False, "decision": "approved", "actor": "Founder"},
                )
                self.assertEqual(unconfirmed.status_code, 400)

                approved = client.post(
                    f"/api/founder-decisions/{gate_id}",
                    headers=headers,
                    json={
                        "confirmed": True,
                        "decision": "approved",
                        "note": "Founder accepts evidence",
                        "actor": "Founder",
                    },
                )
                self.assertEqual(approved.status_code, 200, approved.text)
                receipt = approved.json()
                self.assertFalse(receipt["idempotent"])
                self.assertEqual(receipt["actor"], "Founder")
                self.assertEqual(receipt["previous_state"], "pending")
                self.assertEqual(receipt["resulting_state"], "approved")
                self.assertEqual(receipt["target"], f"workflow_run:{run_id}")
                self.assertTrue(receipt["timestamp"])

                replay = client.post(
                    f"/api/founder-decisions/{gate_id}",
                    headers=headers,
                    json={
                        "confirmed": True,
                        "decision": "approved",
                        "note": "Replay does not rewrite note",
                        "actor": "Founder",
                    },
                )
                self.assertEqual(replay.status_code, 200, replay.text)
                self.assertTrue(replay.json()["idempotent"])
                self.assertEqual(replay.json()["previous_state"], "approved")
                conflict = client.post(
                    f"/api/founder-decisions/{gate_id}",
                    headers=headers,
                    json={
                        "confirmed": True,
                        "decision": "rejected",
                        "note": "Conflicting replay",
                        "actor": "Founder",
                    },
                )
                self.assertEqual(conflict.status_code, 400)
                self.assertEqual(client.get("/api/founder-decisions").json(), [])
                decided = client.get(
                    "/api/founder-decisions", params={"include_decided": True}
                ).json()[0]
                self.assertEqual(decided["approval"]["decision_note"], "Founder accepts evidence")
                events = client.get(
                    "/api/events", params={"action": "approval.approved", "limit": 200}
                ).json()["items"]
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["payload"]["actor"], "Founder")
                self.assertEqual(events[0]["payload"]["previous_state"], "pending")
                self.assertEqual(events[0]["payload"]["resulting_state"], "approved")
                self.assertEqual(
                    events[0]["payload"]["target"],
                    {"type": "workflow_run", "id": run_id},
                )
                all_event_types = {
                    item["event_type"]
                    for item in client.get("/api/events?limit=200").json()["items"]
                }
                self.assertFalse(
                    any(
                        token in event_type
                        for event_type in all_event_types
                        for token in ("merge", "close", "release", "github.apply")
                    )
                )

    def test_audit_settings_and_github_dry_run_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            database = workspace / ".agent-factory" / "state.db"
            project_id, task_id, run_id = seed(workspace, database)
            source = workspace / "backlog.json"
            source.write_bytes((ROOT / "examples" / "development-backlog.json").read_bytes())
            proposal = load_backlog(source)
            desired = proposal.items[0].issue()
            existing = [
                {
                    "number": 7,
                    "title": desired["title"],
                    "body": desired["body"].replace("Deliver", "Previously deliver", 1),
                    "labels": desired["labels"],
                }
            ]
            headers = {"X-Agent-Factory-Confirm": "true"}
            with TestClient(create_app(workspace, database)) as client:
                settings = client.get("/api/settings").json()
                by_key = {item["key"]: item for item in settings["runtime_settings"]}
                self.assertEqual(by_key["dashboard_refresh_seconds"]["value"], 5)
                self.assertEqual(by_key["dashboard_refresh_seconds"]["version"], 0)

                unconfirmed = client.post(
                    "/api/settings/dashboard_refresh_seconds",
                    json={"confirmed": False, "value": 10},
                )
                self.assertEqual(unconfirmed.status_code, 400)
                for value, version in ((10, 1), (12, 2)):
                    updated = client.post(
                        "/api/settings/dashboard_refresh_seconds",
                        headers=headers,
                        json={"confirmed": True, "value": value},
                    )
                    self.assertEqual(updated.status_code, 200, updated.text)
                    self.assertEqual(updated.json()["version"], version)
                rejected_secret = client.post(
                    "/api/settings/github_token",
                    headers=headers,
                    json={"confirmed": True, "value": 1},
                )
                self.assertEqual(rejected_secret.status_code, 400)
                out_of_range = client.post(
                    "/api/settings/audit_page_size",
                    headers=headers,
                    json={"confirmed": True, "value": 1000},
                )
                self.assertEqual(out_of_range.status_code, 400)

                preview = client.post(
                    "/api/github/preview",
                    headers=headers,
                    json={
                        "confirmed": True,
                        "repo": "owner/repository",
                        "backlog_path": "backlog.json",
                        "existing_issues": existing,
                    },
                )
                self.assertEqual(preview.status_code, 200, preview.text)
                plan = preview.json()
                self.assertTrue(plan["dry_run"])
                self.assertEqual(len(plan["plan_hash"]), 64)
                self.assertEqual(plan["gate_status"], "pending")
                self.assertTrue(any(op["action"] == "update_issue" for op in plan["operations"]))
                self.assertTrue(any(op["action"] == "create_issue" for op in plan["operations"]))
                self.assertTrue(all(not item["executed"] for item in plan["preview"]["results"]))

                escaped = client.post(
                    "/api/github/preview",
                    headers=headers,
                    json={
                        "confirmed": True,
                        "repo": "owner/repository",
                        "backlog_path": "../outside.json",
                        "existing_issues": [],
                    },
                )
                self.assertEqual(escaped.status_code, 400)

                audit = client.get(
                    "/api/events",
                    params={
                        "project_id": project_id,
                        "task_id": task_id,
                        "run_id": run_id,
                        "agent_id": "coding-worker-codex",
                        "provider": "deterministic",
                    },
                ).json()
                self.assertGreater(audit["total"], 0)
                self.assertTrue(
                    any(item["related_artifact_ids"] for item in audit["items"])
                )
                settings_audit = client.get(
                    "/api/events", params={"action": "settings", "outcome": "success"}
                ).json()
                self.assertEqual(settings_audit["total"], 2)
                newest = client.get("/api/events", params={"limit": 1}).json()["items"][0]
                bounded = client.get(
                    "/api/events",
                    params={"from_time": newest["created_at"], "to_time": newest["created_at"]},
                ).json()
                self.assertGreaterEqual(bounded["total"], 1)

            storage = SQLiteStorage(database)
            versions = storage.db.execute(
                """SELECT version,value_json FROM runtime_setting_versions
                     WHERE key='dashboard_refresh_seconds' ORDER BY version"""
            ).fetchall()
            self.assertEqual([(row["version"], row["value_json"]) for row in versions], [(1, "10"), (2, "12")])
            gate = storage.db.execute(
                "SELECT status FROM github_mutation_gates WHERE id=?", (plan["gate_id"],)
            ).fetchone()
            self.assertEqual(gate["status"], "pending")
            storage.close()

    def test_guarded_agent_provider_and_reviewer_routing_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            database = workspace / ".agent-factory" / "state.db"
            _, _, run_id = seed(workspace, database)
            headers = {"X-Agent-Factory-Confirm": "true"}
            with TestClient(create_app(workspace, database)) as client:
                agents = client.get("/api/agents", params={"limit": 200}).json()
                guardian = next(
                    item for item in agents["items"] if item["id"] == "policy-guardian"
                )
                self.assertIn("reviewer_assignment_count", guardian)
                self.assertIn("last_claimed_task_id", guardian)

                providers = client.get("/api/providers", params={"limit": 200}).json()
                codex = next(
                    item for item in providers["items"] if item["id"] == "codex"
                )
                self.assertIn("Policy Reviewer", codex["allowed_roles"])
                self.assertIn("health_details", codex)

                reviews = client.get(
                    "/api/reviews", params={"run_id": run_id, "limit": 200}
                ).json()["items"]
                self.assertEqual(len(reviews), 2)
                for review in reviews:
                    producer_models = {
                        producer["model"].casefold()
                        for producer in review["producer_agents"]
                    }
                    self.assertNotIn(review["reviewer_model"].casefold(), producer_models)
                    self.assertEqual(
                        review["strategy"], "least-used-model-aware-round-robin"
                    )

                unconfirmed = client.post(
                    "/api/agents/policy-guardian/enabled",
                    json={"confirmed": False, "enabled": False},
                )
                self.assertEqual(unconfirmed.status_code, 400)
                disabled = client.post(
                    "/api/agents/policy-guardian/enabled",
                    headers=headers,
                    json={"confirmed": True, "enabled": False},
                )
                self.assertEqual(disabled.status_code, 200, disabled.text)
                self.assertFalse(disabled.json()["agent"]["enabled"])
                self.assertIn("existing evidence remains immutable", disabled.json()["impact_summary"])

                incompatible = client.post(
                    "/api/agents/policy-guardian/provider",
                    headers=headers,
                    json={"confirmed": True, "provider": "openclaw", "model": "x"},
                )
                self.assertEqual(incompatible.status_code, 400)
                self.assertIn("incompatible", incompatible.json()["error"]["message"])

                replaced = client.post(
                    "/api/agents/policy-guardian/provider",
                    headers=headers,
                    json={
                        "confirmed": True,
                        "provider": "codex",
                        "model": "openai:independent-reviewer",
                    },
                )
                self.assertEqual(replaced.status_code, 200, replaced.text)
                self.assertEqual(replaced.json()["agent"]["provider"], "codex")
                persisted = next(
                    item
                    for item in client.get("/api/agents?limit=200").json()["items"]
                    if item["id"] == "policy-guardian"
                )
                self.assertFalse(persisted["enabled"])
                self.assertEqual(persisted["model"], "openai:independent-reviewer")
                event_names = {
                    item["event_type"]
                    for item in client.get("/api/events?limit=200").json()["items"]
                }
                self.assertIn("agent.disabled", event_names)
                self.assertIn("agent.provider.replaced", event_names)

    def test_guarded_work_item_run_and_review_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            database = workspace / ".agent-factory" / "state.db"
            storage = SQLiteStorage(database)
            service = AgentFactoryService(storage, workspace=workspace)
            project = service.create_project("Controls")
            item = service.create_work_item(
                project_id=project.project_id,
                title="Controlled task",
                description="Confirm every mutation",
                kind="task",
                inputs={"labels": ["priority:high"]},
                acceptance_criteria=["Mutation is audited"],
            )
            dependent = service.create_work_item(
                project_id=project.project_id,
                title="Dependent task",
                description="Exercise dependency filters",
                dependencies=[item.id],
            )
            storage.close()
            headers = {"X-Agent-Factory-Confirm": "true"}
            with TestClient(create_app(workspace, database)) as client:
                rejected = client.post(
                    f"/api/work-items/{item.id}/claim",
                    json={"confirmed": False, "agent_id": "coding-worker-codex"},
                )
                self.assertEqual(rejected.status_code, 400)
                claimed = client.post(
                    f"/api/work-items/{item.id}/claim",
                    headers=headers,
                    json={"confirmed": True, "agent_id": "coding-worker-codex"},
                )
                self.assertEqual(claimed.status_code, 200, claimed.text)
                filtered = client.get(
                    "/api/work-items", params={"assignee": "coding-worker-codex"}
                ).json()
                self.assertEqual(filtered["total"], 1)
                for key, value, expected_id in (
                    ("project_id", project.project_id, item.id),
                    ("kind", "task", item.id),
                    ("status", "pending", item.id),
                    ("priority", "high", item.id),
                    ("dependency", item.id, dependent.id),
                ):
                    with self.subTest(filter=key):
                        result = client.get(
                            "/api/work-items", params={key: value}
                        ).json()
                        self.assertIn(expected_id, [row["id"] for row in result["items"]])
                started = client.post(
                    f"/api/work-items/{item.id}/runs",
                    headers=headers,
                    json={"confirmed": True, "workflow_id": "delivery", "mode": "simulation"},
                )
                self.assertEqual(started.status_code, 200, started.text)
                run_id = started.json()["id"]
                detail = client.get(f"/api/runs/{run_id}/detail").json()
                self.assertEqual(
                    [artifact["stage"] for artifact in detail["artifacts"]],
                    ["policy-precheck", "implementation", "validation", "policy-postcheck"],
                )
                self.assertEqual(detail["stopped_reason"], "Founder decision required")
                artifact_id = detail["artifacts"][0]["id"]
                reviewed = client.post(
                    f"/api/artifacts/{artifact_id}/review",
                    headers=headers,
                    json={
                        "confirmed": True,
                        "task_id": item.id,
                        "decision": "approved",
                        "note": "Evidence checked",
                    },
                )
                self.assertEqual(reviewed.status_code, 200, reviewed.text)
                self.assertEqual(reviewed.json()["status"], "approved")

    def test_dashboard_shell_has_live_navigation_and_explicit_ui_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with TestClient(
                create_app(workspace, workspace / ".agent-factory" / "state.db")
            ) as client:
                page = client.get("/")
                self.assertEqual(page.status_code, 200)
                self.assertIn("Local Control Center", page.text)
                for target in ("#overview", "#work", "#runs", "#agents", "#reviews", "#audit"):
                    self.assertIn(f'href="{target}"', page.text)
                script = client.get("/assets/app.js")
                styles = client.get("/assets/styles.css")
                self.assertEqual(script.status_code, 200)
                self.assertEqual(styles.status_code, 200)
                self.assertIn("setInterval(refresh, 5000)", script.text)
                self.assertIn("Showing the last successful local snapshot", script.text)
                self.assertIn("Dashboard data is unavailable", script.text)
                self.assertIn("No workflow runs yet", script.text)
                self.assertIn('id="work-filters"', page.text)
                self.assertIn('id="confirm-dialog"', page.text)
                self.assertIn("Explicit confirmation", page.text)
                self.assertIn('"X-Agent-Factory-Confirm": "true"', script.text)
                self.assertIn("Run simulation", script.text)
                self.assertIn("Resume unavailable", script.text)
                self.assertIn("Cancel unavailable", script.text)
                self.assertIn('id="agent-list"', page.text)
                self.assertIn('id="routing-list"', page.text)
                self.assertIn("Compatible provider", script.text)
                self.assertIn("Candidate exclusions", script.text)
                self.assertIn("prior approval snapshots will not be reused", script.text)
                self.assertIn('id="audit-filters"', page.text)
                self.assertIn('id="settings-list"', page.text)
                self.assertIn('id="github-preview-form"', page.text)
                self.assertIn("DRY RUN", script.text)
                self.assertIn("unrestricted command arguments", script.text)
                self.assertNotIn("Available in AF-042", page.text)
                self.assertIn('id="founder-dialog"', page.text)
                self.assertIn("Only this separately confirmed Founder action", script.text)
                self.assertIn("no merge, close, release, or GitHub mutation", script.text)
                self.assertIn('id="backlog-import-form"', page.text)
                self.assertNotIn("Available in AF-039", page.text)
                self.assertIn("prefers-reduced-motion", styles.text)


if __name__ == "__main__":
    unittest.main()
