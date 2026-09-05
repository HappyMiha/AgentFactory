import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from agent_factory.application import AgentFactoryService
from agent_factory.storage import SQLiteStorage
from agent_factory.web import create_app


class ExecutionControlTests(unittest.TestCase):
    def test_execution_snapshot_and_release_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp); database = workspace / "state.db"
            storage = SQLiteStorage(database); service = AgentFactoryService(storage, workspace=workspace)
            project = service.create_project("Execution")
            item = service.create_work_item(project_id=project.project_id, title="Run", description="Run", acceptance_criteria=["works"])
            claim = service.claim_work_item(item.id, "coding-worker-codex")
            storage.close()
            with TestClient(create_app(workspace, database), base_url="http://localhost") as client:
                snapshot = client.get("/api/executions").json()
                self.assertEqual(len(snapshot["leases"]), 1)
                response = client.post("/api/executions/leases/release", json={"confirmed": True, "assignment_id": claim.assignment_id, "fencing_token": claim.fencing_token}, headers={"X-Agent-Factory-Confirm": "true"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(client.get("/api/executions").json()["leases"], [])


if __name__ == "__main__":
    unittest.main()
