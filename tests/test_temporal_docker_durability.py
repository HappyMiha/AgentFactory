import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import timedelta
from pathlib import Path

from temporalio.worker import Worker

from agent_factory.orchestration.temporal.activities import AgentFactoryActivities
from agent_factory.orchestration.temporal.client import connect_temporal
from agent_factory.orchestration.temporal.models import DemoWorkflowInput
from agent_factory.orchestration.temporal.settings import TemporalSettings
from agent_factory.orchestration.temporal.workflows import (
    AgentFactoryJobWorkflow,
    TemporalDemoWorkflow,
)


RUN_DOCKER_TESTS = os.getenv("AGENTFACTORY_TEMPORAL_DOCKER_TESTS") == "1"
REPOSITORY = Path(__file__).resolve().parents[1]
COMPOSE = REPOSITORY / "infra" / "temporal" / "docker-compose.yml"
HEALTH = REPOSITORY / "infra" / "temporal" / "health.ps1"


@unittest.skipUnless(
    RUN_DOCKER_TESTS,
    "set AGENTFACTORY_TEMPORAL_DOCKER_TESTS=1 to exercise the local Docker stack",
)
class TemporalDockerDurabilityTests(unittest.IsolatedAsyncioTestCase):
    def compose(self, *arguments: str) -> None:
        subprocess.run(
            ["docker", "compose", "--file", str(COMPOSE), *arguments],
            cwd=REPOSITORY,
            check=True,
        )

    def wait_for_health(self) -> None:
        for _ in range(60):
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-File", str(HEALTH)],
                cwd=REPOSITORY,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                return
            import time

            time.sleep(1)
        self.fail("Temporal did not become healthy after Docker Compose start")

    def worker(self, client, settings: TemporalSettings) -> Worker:
        activities = AgentFactoryActivities(settings)
        return Worker(
            client,
            task_queue=settings.task_queue,
            workflows=[AgentFactoryJobWorkflow, TemporalDemoWorkflow],
            activities=[
                activities.validate_job,
                activities.load_project_context,
                activities.execute_stage,
                activities.finalize_job,
                activities.fail_job,
                activities.inspect_demo_workspace,
                activities.write_demo_marker,
                activities.run_demo_command,
                activities.validate_demo_result,
            ],
            max_cached_workflows=0,
            sticky_queue_schedule_to_start_timeout=timedelta(seconds=1),
        )

    async def test_server_and_worker_restart_preserve_completed_history(self):
        settings = TemporalSettings(enabled=True)
        client = await connect_temporal(settings, initialize_namespace=True)
        marker = f"docker-restart-{uuid.uuid4().hex}"
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary).resolve()
            request = DemoWorkflowInput(
                workspace=str(workspace),
                marker=marker,
                command=[sys.executable, "-c", "print('continued after restart')"],
                wait_before_command=True,
            )
            first_worker = self.worker(client, settings)
            await first_worker.__aenter__()
            try:
                handle = await client.start_workflow(
                    TemporalDemoWorkflow.run,
                    request,
                    id=f"agentfactory-temporal-demo-{marker}",
                    task_queue=settings.task_queue,
                )
                for _ in range(100):
                    if await handle.query("demo_phase") == "waiting_before_command":
                        break
                    await asyncio.sleep(0.05)
                self.assertEqual(
                    await handle.query("demo_phase"), "waiting_before_command"
                )
                marker_file = (
                    workspace
                    / ".agent-factory"
                    / "temporal-demo"
                    / f"{marker}.txt"
                )
                original_mtime = marker_file.stat().st_mtime_ns
            finally:
                await first_worker.__aexit__(None, None, None)

            try:
                await asyncio.to_thread(self.compose, "stop")
                await asyncio.to_thread(self.compose, "start")
                await asyncio.to_thread(self.wait_for_health)
                client = await connect_temporal(settings, initialize_namespace=True)
                handle = client.get_workflow_handle(
                    f"agentfactory-temporal-demo-{marker}"
                )
                await handle.signal("continue_demo")
                async with self.worker(client, settings):
                    result = await asyncio.wait_for(handle.result(), timeout=45)
            finally:
                await asyncio.to_thread(self.compose, "start")
                await asyncio.to_thread(self.wait_for_health)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(marker_file.stat().st_mtime_ns, original_mtime)


if __name__ == "__main__":
    unittest.main()
