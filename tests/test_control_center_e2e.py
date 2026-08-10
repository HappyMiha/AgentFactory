import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from agent_factory.web import create_app


class LocalControlCenterEndToEndTests(unittest.TestCase):
    def test_fresh_state_delivery_and_dry_run_exit_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            manifest = workspace / "sample-backlog.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source": {"name": "R0.2 qualification sample"},
                        "items": [
                            {
                                "stable_id": "LCC-E2E-001",
                                "kind": "task",
                                "title": "Qualify the local delivery path",
                                "description": "Produce independently reviewed evidence and stop for Founder authority.",
                                "parent_id": None,
                                "dependencies": [],
                                "acceptance_criteria": [
                                    "The UI-facing API exposes the complete evidence chain"
                                ],
                                "source_references": ["docs/local-control-center.md"],
                                "review_notes": ["Founder remains the final authority"],
                                "labels": ["priority:p0", "release:r0.2"],
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            database = workspace / ".agent-factory" / "state.db"
            headers = {"X-Agent-Factory-Confirm": "true"}
            with TestClient(create_app(workspace, database)) as client:
                imported = client.post(
                    "/api/backlog/import",
                    headers=headers,
                    json={
                        "confirmed": True,
                        "project_name": "R0.2 Qualification",
                        "project_description": "Fresh-state end-to-end evidence",
                        "backlog_path": manifest.name,
                    },
                )
                self.assertEqual(imported.status_code, 200, imported.text)
                task_id = imported.json()["created"][0]["task_id"]
                item = client.get(f"/api/work-items/{task_id}").json()
                self.assertEqual(item["priority"], "p0")
                self.assertEqual(item["inputs"]["stable_id"], "LCC-E2E-001")

                claimed = client.post(
                    f"/api/work-items/{task_id}/claim",
                    headers=headers,
                    json={
                        "confirmed": True,
                        "agent_id": "coding-worker-codex",
                    },
                )
                self.assertEqual(claimed.status_code, 200, claimed.text)
                started = client.post(
                    f"/api/work-items/{task_id}/runs",
                    headers=headers,
                    json={
                        "confirmed": True,
                        "workflow_id": "delivery",
                        "mode": "simulation",
                    },
                )
                self.assertEqual(started.status_code, 200, started.text)
                run_id = started.json()["id"]
                detail = client.get(f"/api/runs/{run_id}/detail").json()
                self.assertEqual(detail["stopped_reason"], "Founder decision required")
                self.assertEqual(
                    [artifact["stage"] for artifact in detail["artifacts"]],
                    ["policy-precheck", "implementation", "validation", "policy-postcheck"],
                )
                self.assertEqual(len(detail["reviews"]), 2)
                for review in detail["reviews"]:
                    producer_models = {
                        producer["model"].casefold()
                        for producer in review["producer_agents"]
                    }
                    self.assertNotIn(review["reviewer_model"].casefold(), producer_models)

                packet = client.get("/api/founder-decisions").json()[0]
                self.assertEqual(packet["run"]["id"], run_id)
                gate_id = packet["approval"]["id"]
                decided = client.post(
                    f"/api/founder-decisions/{gate_id}",
                    headers=headers,
                    json={
                        "confirmed": True,
                        "decision": "approved",
                        "note": "R0.2 end-to-end evidence accepted",
                        "actor": "Founder",
                    },
                )
                self.assertEqual(decided.status_code, 200, decided.text)
                self.assertEqual(decided.json()["resulting_state"], "approved")

                preview = client.post(
                    "/api/github/preview",
                    headers=headers,
                    json={
                        "confirmed": True,
                        "repo": "owner/repository",
                        "backlog_path": manifest.name,
                        "existing_issues": [],
                    },
                )
                self.assertEqual(preview.status_code, 200, preview.text)
                self.assertTrue(preview.json()["dry_run"])
                self.assertEqual(preview.json()["gate_status"], "pending")
                self.assertTrue(
                    all(
                        result["executed"] is False
                        for result in preview.json()["preview"]["results"]
                    )
                )

                audit = client.get(
                    "/api/events",
                    params={"task_id": task_id, "run_id": run_id, "limit": 200},
                ).json()["items"]
                event_types = {event["event_type"] for event in audit}
                self.assertIn("approval.approved", event_types)
                self.assertTrue(any(event["related_artifact_ids"] for event in audit))
                full_audit = client.get("/api/events?limit=200").json()["items"]
                self.assertIn("github.plan.created", {event["event_type"] for event in full_audit})
                self.assertNotIn("github.apply.succeeded", {event["event_type"] for event in full_audit})
                self.assertEqual(client.get(f"/api/runs/{run_id}").json()["status"], "approved")


if __name__ == "__main__":
    unittest.main()
