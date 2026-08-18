import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agent_factory.application import AgentFactoryService
from agent_factory.orchestration.temporal.client import WorkflowStartResult
from agent_factory.storage import SQLiteStorage
from agent_factory.web import create_app


class TemporalApiTests(unittest.TestCase):
    def test_start_returns_immediately_and_exposes_signals_and_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary).resolve()
            database = workspace / ".agent-factory" / "state.db"
            storage = SQLiteStorage(database)
            service = AgentFactoryService(storage, workspace=workspace)
            project = service.create_project("Temporal API")
            item = service.create_work_item(
                project_id=project.project_id,
                title="Durable task",
                description="Start without holding the HTTP request open",
                acceptance_criteria=["A Temporal workflow is created"],
            )
            storage.close()

            fake_client = object()
            connected = AsyncMock(return_value=fake_client)
            started = AsyncMock(
                return_value=WorkflowStartResult(
                    "agentfactory-job-run-1", "temporal-run-id", False
                )
            )
            signalled = AsyncMock()
            snapshot = AsyncMock(
                return_value={
                    "workflow_id": "agentfactory-job-run-1",
                    "temporal_status": "RUNNING",
                    "status": {"phase": "development"},
                }
            )
            environment = {
                "TEMPORAL_ENABLED": "true",
                "TEMPORAL_ADDRESS": "localhost:7233",
                "TEMPORAL_NAMESPACE": "agentfactory",
                "TEMPORAL_TASK_QUEUE": "agentfactory-main",
            }
            with (
                patch.dict(os.environ, environment, clear=False),
                patch("agent_factory.web.connect_temporal", connected),
                patch("agent_factory.web.start_job_workflow", started),
                patch("agent_factory.web.signal_workflow", signalled),
                patch("agent_factory.web.workflow_snapshot", snapshot),
                TestClient(create_app(workspace, database)) as client,
            ):
                response = client.post(
                    f"/api/work-items/{item.id}/runs",
                    headers={"X-Agent-Factory-Confirm": "true"},
                    json={
                        "workflow_id": "delivery",
                        "mode": "simulation",
                        "confirmed": True,
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)
                payload = response.json()
                self.assertEqual(
                    payload["temporal_workflow_id"], "agentfactory-job-run-1"
                )
                self.assertEqual(payload["status"], "running")
                started.assert_awaited_once()

                status = client.get(f"/api/runs/{payload['id']}/temporal")
                self.assertEqual(status.status_code, 200)
                self.assertEqual(status.json()["temporal_status"], "RUNNING")

                for action in ("pause", "resume", "cancel"):
                    control = client.post(
                        f"/api/executions/runs/{payload['id']}/{action}",
                        headers={"X-Agent-Factory-Confirm": "true"},
                        json={"reason": f"test {action}", "confirmed": True},
                    )
                    self.assertEqual(control.status_code, 200, control.text)

            connected.assert_awaited_once()
            self.assertEqual(
                [call.args[2] for call in signalled.await_args_list],
                ["pause", "resume", "cancel"],
            )


if __name__ == "__main__":
    unittest.main()
