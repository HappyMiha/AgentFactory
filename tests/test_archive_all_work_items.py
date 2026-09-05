import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from agent_factory.application import AgentFactoryService
from agent_factory.storage import SQLiteStorage
from agent_factory.web import create_app


class ArchiveAllWorkItemsTests(unittest.TestCase):
    def test_bulk_archive_hides_all_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp); database = workspace / "state.db"
            storage = SQLiteStorage(database); service = AgentFactoryService(storage, workspace=workspace)
            project = service.create_project("Bulk")
            for index in range(3):
                service.create_work_item(project_id=project.project_id, title=f"Item {index}", description="item", kind="epic", acceptance_criteria=["recorded"])
            storage.close()
            with TestClient(create_app(workspace, database), base_url="http://localhost") as client:
                response = client.post("/api/work-items/archive-all", json={"confirmed": True}, headers={"X-Agent-Factory-Confirm": "true"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["count"], 3)
                self.assertEqual(client.get("/api/work-items?limit=200").json()["total"], 0)

    def test_bulk_archive_expires_stale_lease_before_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp); database = workspace / "state.db"
            storage = SQLiteStorage(database); service = AgentFactoryService(storage, workspace=workspace)
            project = service.create_project("Bulk")
            item = service.create_work_item(project_id=project.project_id, title="Item", description="item", acceptance_criteria=["recorded"])
            claim = service.claim_work_item(item.id, "coding-worker-codex")
            storage.db.execute("UPDATE leases SET expires_at='2000-01-01T00:00:00+00:00' WHERE assignment_id=?", (claim.assignment_id,)); storage.db.commit(); storage.close()
            with TestClient(create_app(workspace, database), base_url="http://localhost") as client:
                response = client.post("/api/work-items/archive-all", json={"confirmed": True}, headers={"X-Agent-Factory-Confirm": "true"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["count"], 1)


if __name__ == "__main__":
    unittest.main()
