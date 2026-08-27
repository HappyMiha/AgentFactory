from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from temporalio.worker import Worker

from .activities import AgentFactoryActivities
from .client import connect_temporal
from .settings import TemporalSettings
from .workflows import (
    AgentFactoryJobWorkflow,
    AutonomousMissionWorkflow,
    TemporalDemoWorkflow,
)


REGISTERED_WORKFLOWS = (
    AgentFactoryJobWorkflow,
    AutonomousMissionWorkflow,
    TemporalDemoWorkflow,
)


async def run_worker(settings: TemporalSettings | None = None) -> None:
    selected = settings or TemporalSettings.from_env()
    client = await connect_temporal(selected, initialize_namespace=True)
    activities = AgentFactoryActivities(selected)
    worker = Worker(
        client,
        task_queue=selected.task_queue,
        workflows=list(REGISTERED_WORKFLOWS),
        activities=[
            activities.run_autonomous_planning,
            activities.revalidate_autonomous_approval,
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
        graceful_shutdown_timeout=timedelta(
            seconds=selected.cancellation_grace_seconds
        ),
    )
    logging.getLogger(__name__).info(
        "AgentFactory Temporal Worker connected address=%s namespace=%s task_queue=%s",
        selected.address,
        selected.namespace,
        selected.task_queue,
    )
    await worker.run()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
