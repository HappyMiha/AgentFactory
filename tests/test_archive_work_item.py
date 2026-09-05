import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from agent_factory.application import AgentFactoryService
from agent_factory.storage import SQLiteStorage
from agent_factory.web import create_app


class ArchiveWorkItemTests(unittest.TestCase):
    def test_archive_hides_item_and_keeps_audit_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            database = workspace / "state.db"
            storage = SQLiteStorage(database)
            service = AgentFactoryService(storage, workspace=workspace)
            project = service.create_project("Archive")
            item = service.create_work_item(project_id=project.project_id, title="Old", description="Old", kind="epic", acceptance_criteria=["Recorded"])
            storage.close()
            with TestClient(create_app(workspace, database), base_url="http://localhost") as client:
                response = client.post(f"/api/work-items/{item.id}/archive", json={"confirmed": True, "reason": "Superseded"}, headers={"X-Agent-Factory-Confirm": "true"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(client.get("/api/work-items?limit=200").json()["total"], 0)
                detail = client.get(f"/api/work-items/{item.id}").json()
                self.assertTrue(detail["inputs"]["archived"])
                events = client.get("/api/events?limit=20").json()["items"]
                self.assertTrue(any(event["event_type"] == "task.archived" for event in events))

    def test_archive_rejects_dependents(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            database = workspace / "state.db"
            storage = SQLiteStorage(database)
            service = AgentFactoryService(storage, workspace=workspace)
            project = service.create_project("Archive")
            parent = service.create_work_item(project_id=project.project_id, title="Parent", description="Parent", kind="epic", acceptance_criteria=["Recorded"])
            service.create_work_item(project_id=project.project_id, title="Child", description="Child", dependencies=[parent.id], acceptance_criteria=["Recorded"])
            storage.close()
            with TestClient(create_app(workspace, database), base_url="http://localhost") as client:
                response = client.post(f"/api/work-items/{parent.id}/archive", json={"confirmed": True}, headers={"X-Agent-Factory-Confirm": "true"})
            self.assertEqual(response.status_code, 400)
            self.assertIn("dependent", response.json()["error"]["message"])


if __name__ == "__main__":
    unittest.main()
