import asyncio
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import timedelta
from pathlib import Path

from temporalio.client import WorkflowFailureError
from temporalio.exceptions import CancelledError
from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from agent_factory.models import WorkItem
from agent_factory.orchestration.temporal.activities import AgentFactoryActivities
from agent_factory.orchestration.temporal.models import (
    AgentFactoryJobInput,
    DemoWorkflowInput,
)
from agent_factory.orchestration.temporal.settings import TemporalSettings
from agent_factory.orchestration.temporal.workflows import (
    AgentFactoryJobWorkflow,
    TemporalDemoWorkflow,
)
from agent_factory.storage import SQLiteStorage


@activity.defn
async def record_restart_step(payload: dict) -> str:
    destination = Path(payload["workspace"]) / f"{payload['step']}.count"
    count = int(destination.read_text()) + 1 if destination.exists() else 1
    destination.write_text(str(count))
    return payload["step"]


@workflow.defn(sandboxed=False)
class WorkerRestartProbeWorkflow:
    def __init__(self):
        self.continue_requested = False
        self.first_completed = False

    @workflow.query
    def phase(self) -> str:
        if self.continue_requested:
            return "continued"
        return "waiting" if self.first_completed else "starting"

    @workflow.signal
    async def continue_after_restart(self) -> None:
        self.continue_requested = True

    @workflow.run
    async def run(self, workspace: str) -> list[str]:
        first = await workflow.execute_activity(
            record_restart_step,
            {"workspace": workspace, "step": "first"},
            start_to_close_timeout=timedelta(seconds=10),
        )
        self.first_completed = True
        await workflow.wait_condition(lambda: self.continue_requested)
        second = await workflow.execute_activity(
            record_restart_step,
            {"workspace": workspace, "step": "second"},
            start_to_close_timeout=timedelta(seconds=10),
        )
        return [first, second]


class TemporalWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve()
        self.database = self.workspace / ".agent-factory" / "state.db"
        self.settings = TemporalSettings(
            heartbeat_interval_seconds=1,
            heartbeat_timeout_seconds=5,
            cancellation_grace_seconds=5,
        )
        self.environment = await WorkflowEnvironment.start_time_skipping()
        self.task_queue = f"temporal-test-{uuid.uuid4().hex}"
        self.activities = AgentFactoryActivities(self.settings)

    async def asyncTearDown(self):
        await self.environment.shutdown()
        self.temporary.cleanup()

    def worker(self, *, graceful_shutdown_seconds=0):
        return Worker(
            self.environment.client,
            task_queue=self.task_queue,
            workflows=[AgentFactoryJobWorkflow, TemporalDemoWorkflow],
            activities=[
                self.activities.validate_job,
                self.activities.load_project_context,
                self.activities.execute_stage,
                self.activities.finalize_job,
                self.activities.fail_job,
                self.activities.inspect_demo_workspace,
                self.activities.write_demo_marker,
                self.activities.run_demo_command,
                self.activities.validate_demo_result,
            ],
            graceful_shutdown_timeout=timedelta(
                seconds=graceful_shutdown_seconds
            ),
        )

    def persisted_job(self) -> AgentFactoryJobInput:
        storage = SQLiteStorage(self.database)
        project_id = storage.create_project("Temporal project", "durability test")
        task_id = storage.create_task(
            WorkItem(
                title="Run a real AgentFactory delivery workflow",
                description="Produce and validate reviewable evidence",
                project_id=project_id,
                acceptance_criteria=["Evidence is persisted"],
            )
        )
        run_id = storage.start_run(project_id, task_id, "delivery")
        storage.close()
        return AgentFactoryJobInput(
            job_id=f"test-{run_id}-{uuid.uuid4().hex}",
            run_id=run_id,
            project_id=project_id,
            task_id=task_id,
            workspace=str(self.workspace),
            database=str(self.database),
            fast_activity_timeout_seconds=30,
            llm_activity_timeout_seconds=60,
            heartbeat_timeout_seconds=5,
            max_repair_iterations=2,
        )

    async def test_real_agentfactory_job_completes_without_workflow_side_effects(self):
        job = self.persisted_job()
        async with self.worker():
            result = await self.environment.client.execute_workflow(
                AgentFactoryJobWorkflow.run,
                job,
                id=f"agentfactory-job-{job.job_id}",
                task_queue=self.task_queue,
            )
        self.assertEqual(result["status"], "WAITING")
        self.assertEqual(result["completed_tasks"], 4)
        storage = SQLiteStorage(self.database)
        try:
            self.assertEqual(
                storage.db.execute(
                    "SELECT COUNT(*) FROM artifacts WHERE run_id=?", (job.run_id,)
                ).fetchone()[0],
                4,
            )
            self.assertEqual(
                storage.db.execute(
                    "SELECT status FROM workflow_runs WHERE id=?", (job.run_id,)
                ).fetchone()[0],
                "awaiting_approval",
            )
        finally:
            storage.close()

    async def test_controlled_transient_activity_retries_then_succeeds(self):
        request = DemoWorkflowInput(
            workspace=str(self.workspace),
            marker=f"retry-{uuid.uuid4().hex}",
            command=[sys.executable, "-c", "print('temporal retry succeeded')"],
            fail_attempts=2,
            activity_timeout_seconds=30,
            heartbeat_timeout_seconds=5,
        )
        async with self.worker():
            result = await self.environment.client.execute_workflow(
                TemporalDemoWorkflow.run,
                request,
                id=f"demo-{request.marker}",
                task_queue=self.task_queue,
            )
        self.assertEqual(result["status"], "completed")

    async def test_application_test_failure_enters_repair_without_activity_retry(self):
        request = DemoWorkflowInput(
            workspace=str(self.workspace),
            marker=f"test-failure-{uuid.uuid4().hex}",
            command=[sys.executable, "-c", "raise SystemExit(3)"],
            activity_timeout_seconds=30,
            heartbeat_timeout_seconds=5,
        )
        async with self.worker():
            result = await self.environment.client.execute_workflow(
                TemporalDemoWorkflow.run,
                request,
                id=f"demo-{request.marker}",
                task_queue=self.task_queue,
            )
        self.assertEqual(result["status"], "repair_required")
        self.assertEqual(result["failure_class"], "BUILD_ERROR")

    async def test_cancellation_terminates_long_running_subprocess(self):
        marker = f"cancel-{uuid.uuid4().hex}"
        pid_file = self.workspace / f"{marker}.pid"
        script = (
            "import os,time,pathlib; "
            f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); "
            "time.sleep(120)"
        )
        request = DemoWorkflowInput(
            workspace=str(self.workspace),
            marker=marker,
            command=[sys.executable, "-c", script],
            activity_timeout_seconds=180,
            heartbeat_timeout_seconds=5,
        )
        async with self.worker():
            handle = await self.environment.client.start_workflow(
                TemporalDemoWorkflow.run,
                request,
                id=f"demo-{marker}",
                task_queue=self.task_queue,
            )
            for _ in range(100):
                if pid_file.is_file():
                    break
                await asyncio.sleep(0.05)
            self.assertTrue(pid_file.is_file(), "long-running process did not start")
            process_id = int(pid_file.read_text())
            await handle.cancel()
            with self.assertRaises(WorkflowFailureError) as failure:
                await handle.result()
            self.assertIsInstance(failure.exception.cause, CancelledError)
            await asyncio.sleep(0.5)
        tasklist = subprocess.run(
            ["tasklist.exe", "/FI", f"PID eq {process_id}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        self.assertNotIn(str(process_id), tasklist)

    async def test_worker_restart_preserves_completed_activity_history(self):
        workflow_id = f"worker-restart-{uuid.uuid4().hex}"
        first_worker = Worker(
            self.environment.client,
            task_queue=self.task_queue,
            workflows=[WorkerRestartProbeWorkflow],
            activities=[record_restart_step],
            max_cached_workflows=0,
            sticky_queue_schedule_to_start_timeout=timedelta(seconds=1),
        )
        await first_worker.__aenter__()
        try:
            handle = await self.environment.client.start_workflow(
                WorkerRestartProbeWorkflow.run,
                str(self.workspace),
                id=workflow_id,
                task_queue=self.task_queue,
            )
            for _ in range(100):
                if (
                    (self.workspace / "first.count").is_file()
                    and await handle.query(WorkerRestartProbeWorkflow.phase)
                    == "waiting"
                ):
                    break
                await asyncio.sleep(0.05)
            self.assertEqual((self.workspace / "first.count").read_text(), "1")
            self.assertEqual(
                await handle.query(WorkerRestartProbeWorkflow.phase), "waiting"
            )
        finally:
            await first_worker.__aexit__(None, None, None)

        await asyncio.sleep(1)
        await handle.signal("continue_after_restart")
        await self.environment.sleep(timedelta(seconds=2))
        second_worker = Worker(
            self.environment.client,
            task_queue=self.task_queue,
            workflows=[WorkerRestartProbeWorkflow],
            activities=[record_restart_step],
            max_cached_workflows=0,
            sticky_queue_schedule_to_start_timeout=timedelta(seconds=1),
        )
        async with second_worker:
            for _ in range(100):
                if await handle.query("phase") == "continued":
                    break
                await asyncio.sleep(0.05)
            self.assertEqual(await handle.query("phase"), "continued")
            result = await asyncio.wait_for(handle.result(), timeout=30)
        self.assertEqual(result, ["first", "second"])
        self.assertEqual((self.workspace / "first.count").read_text(), "1")
        self.assertEqual((self.workspace / "second.count").read_text(), "1")


if __name__ == "__main__":
    unittest.main()
