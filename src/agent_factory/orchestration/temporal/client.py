from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from google.protobuf.duration_pb2 import Duration
from temporalio.api.workflowservice.v1 import (
    DescribeNamespaceRequest,
    RegisterNamespaceRequest,
)
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from .models import AgentFactoryJobInput, DemoWorkflowInput
from .settings import TemporalSettings


class TemporalUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkflowStartResult:
    workflow_id: str
    run_id: str | None
    duplicate: bool


def workflow_id_for_job(job_id: str) -> str:
    normalized = job_id.strip()
    if not normalized:
        raise ValueError("AgentFactory job ID is required")
    return f"agentfactory-job-{normalized}"


async def ensure_namespace(client: Client, namespace: str) -> None:
    try:
        await client.workflow_service.describe_namespace(
            DescribeNamespaceRequest(namespace=namespace)
        )
        return
    except RPCError as exc:
        if exc.status != RPCStatusCode.NOT_FOUND:
            raise
    try:
        await client.workflow_service.register_namespace(
            RegisterNamespaceRequest(
                namespace=namespace,
                description="AgentFactory local durable workflows",
                workflow_execution_retention_period=Duration(seconds=7 * 24 * 60 * 60),
            )
        )
    except RPCError as exc:
        if exc.status != RPCStatusCode.ALREADY_EXISTS:
            raise


async def connect_temporal(
    settings: TemporalSettings | None = None, *, initialize_namespace: bool = True
) -> Client:
    selected = settings or TemporalSettings.from_env()
    try:
        client = await asyncio.wait_for(
            Client.connect(selected.address, namespace=selected.namespace),
            timeout=selected.connect_timeout_seconds,
        )
        if initialize_namespace:
            await asyncio.wait_for(
                ensure_namespace(client, selected.namespace),
                timeout=selected.connect_timeout_seconds,
            )
        return client
    except (OSError, RPCError, TimeoutError) as exc:
        raise TemporalUnavailableError(
            "Temporal is enabled but Temporal Server is unavailable at "
            f"{selected.address}.\n\nRun:\n\n"
            ".\\infra\\temporal\\start.ps1"
        ) from exc


async def start_job_workflow(
    client: Client,
    job: AgentFactoryJobInput,
    settings: TemporalSettings | None = None,
) -> WorkflowStartResult:
    selected = settings or TemporalSettings.from_env()
    workflow_id = workflow_id_for_job(job.job_id)
    try:
        handle = await client.start_workflow(
            "AgentFactoryJobWorkflow",
            job,
            id=workflow_id,
            task_queue=selected.task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
            static_summary=f"AgentFactory job {job.job_id}",
            static_details=(
                f"Project {job.project_id}, task {job.task_id}, "
                f"AgentFactory run {job.run_id}"
            ),
        )
        return WorkflowStartResult(workflow_id, handle.first_execution_run_id, False)
    except WorkflowAlreadyStartedError:
        handle = client.get_workflow_handle(workflow_id)
        return WorkflowStartResult(workflow_id, handle.first_execution_run_id, True)


async def start_demo_workflow(
    client: Client,
    request: DemoWorkflowInput,
    settings: TemporalSettings | None = None,
) -> WorkflowStartResult:
    selected = settings or TemporalSettings.from_env()
    workflow_id = f"agentfactory-temporal-demo-{request.marker}"
    try:
        handle = await client.start_workflow(
            "TemporalDemoWorkflow",
            request,
            id=workflow_id,
            task_queue=selected.task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
        )
        return WorkflowStartResult(workflow_id, handle.first_execution_run_id, False)
    except WorkflowAlreadyStartedError:
        handle = client.get_workflow_handle(workflow_id)
        return WorkflowStartResult(workflow_id, handle.first_execution_run_id, True)


async def workflow_snapshot(client: Client, workflow_id: str) -> dict[str, Any]:
    handle = client.get_workflow_handle(workflow_id)
    description = await handle.describe()
    snapshot: dict[str, Any] = {
        "workflow_id": workflow_id,
        "run_id": description.run_id,
        "temporal_status": description.status.name,
    }
    if description.status.name == "RUNNING":
        status, progress, current = await asyncio.gather(
            handle.query("get_status", result_type=dict),
            handle.query("get_progress", result_type=dict),
            handle.query("get_current_task", result_type=dict),
        )
        snapshot.update(
            {"status": status, "progress": progress, "current_task": current}
        )
    return snapshot


async def signal_workflow(client: Client, workflow_id: str, signal: str) -> None:
    if signal not in {"pause", "resume", "cancel"}:
        raise ValueError(f"Unsupported Temporal signal: {signal}")
    await client.get_workflow_handle(workflow_id).signal(signal)
