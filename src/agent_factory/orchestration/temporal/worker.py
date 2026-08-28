from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from temporalio.common import (
    VersioningBehavior,
    WorkerDeploymentVersion,
)
from temporalio.worker import Worker, WorkerDeploymentConfig

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


def worker_versioning_options(settings: TemporalSettings) -> dict[str, Any]:
    """Build an explicit pinned deployment contract for long-lived missions."""

    settings.validate()
    if settings.worker_versioning_enabled:
        return {
            "deployment_config": WorkerDeploymentConfig(
                version=WorkerDeploymentVersion(
                    deployment_name=settings.worker_deployment_name,
                    build_id=settings.worker_build_id,
                ),
                use_worker_versioning=True,
                default_versioning_behavior=VersioningBehavior.PINNED,
            )
        }
    return {"build_id": settings.worker_build_id}


async def run_worker(settings: TemporalSettings | None = None) -> None:
    selected = settings or TemporalSettings.from_env()
    client = await connect_temporal(selected, initialize_namespace=True)
    activities = AgentFactoryActivities(selected)
    worker = Worker(
        client,
        task_queue=selected.task_queue,
        workflows=list(REGISTERED_WORKFLOWS),
        activities=[
            activities.register_autonomous_temporal_run,
            activities.run_autonomous_planning,
            activities.revalidate_autonomous_approval,
            activities.read_autonomous_mission_control_fence,
            activities.apply_autonomous_mission_control,
            activities.prepare_autonomous_epoch_handoff,
            activities.complete_autonomous_epoch_handoff,
            activities.settle_autonomous_child_retry,
            activities.enter_autonomous_development,
            activities.prepare_autonomous_child_job,
            activities.validate_autonomous_child_job,
            activities.finalize_autonomous_child_job,
            activities.reconcile_autonomous_child_job,
            activities.complete_autonomous_mission,
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
        **worker_versioning_options(selected),
    )
    logging.getLogger(__name__).info(
        "AgentFactory Temporal Worker connected address=%s namespace=%s "
        "task_queue=%s build_id=%s versioning=%s",
        selected.address,
        selected.namespace,
        selected.task_queue,
        selected.worker_build_id,
        selected.worker_versioning_enabled,
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
