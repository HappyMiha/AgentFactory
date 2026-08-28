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

from ...autonomous_mission import AutonomousMission
from .models import (
    AgentFactoryJobInput,
    AutonomousBacklogApprovalNotice,
    AutonomousMissionCarryOver,
    AutonomousMissionWorkflowInput,
    AutonomousPlanningCommand,
    DemoWorkflowInput,
)
from .settings import TemporalSettings


class TemporalUnavailableError(RuntimeError):
    pass


class AutonomousMissionWorkflowConflictError(ValueError):
    """Raised when a stable mission Workflow ID resolves to another identity."""


@dataclass(frozen=True)
class WorkflowStartResult:
    workflow_id: str
    run_id: str | None
    duplicate: bool


@dataclass(frozen=True)
class AutonomousMissionWorkflowStartResult:
    workflow_id: str
    run_id: str
    duplicate: bool
    mission_id: int
    mission_identity: str
    mission_key: str
    mission_version: int
    chain_sequence: int
    previous_run_id: str | None

    def correlation(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "mission_identity": self.mission_identity,
            "mission_key": self.mission_key,
            "mission_version": self.mission_version,
            "workflow_id": self.workflow_id,
            "run_id": self.run_id,
            "chain_sequence": self.chain_sequence,
            "previous_run_id": self.previous_run_id,
        }

    def approval_start_correlation(self) -> dict[str, Any]:
        """Return the AF-AMM-011 fields that bind approval to this parent run."""

        return {
            "temporal_workflow_id": self.workflow_id,
            "temporal_run_id": self.run_id,
            "temporal_chain_metadata": {
                **self.correlation(),
                "workflow_id": self.workflow_id,
                "first_run_id": self.run_id,
            },
        }


def workflow_id_for_job(job_id: str) -> str:
    normalized = job_id.strip()
    if not normalized:
        raise ValueError("AgentFactory job ID is required")
    return f"agentfactory-job-{normalized}"


def workflow_id_for_autonomous_mission(
    mission_id: int,
    prefix: str = "agentfactory-autonomous-mission",
) -> str:
    if int(mission_id) <= 0:
        raise ValueError("Autonomous Mission ID must be positive")
    normalized_prefix = str(prefix).strip()
    if not normalized_prefix:
        raise ValueError("Autonomous Mission Workflow prefix is required")
    if len(normalized_prefix) > 100 or any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for character in normalized_prefix
    ):
        raise ValueError("Autonomous Mission Workflow prefix is invalid")
    return f"{normalized_prefix}-{int(mission_id)}"


def autonomous_mission_workflow_input(
    mission: AutonomousMission,
    *,
    workspace: str,
    database: str,
    carry_over: AutonomousMissionCarryOver | None = None,
    temporal_settings: TemporalSettings | None = None,
    post_approval_execution_enabled: bool = True,
    autonomous_child_execution_mode: str = "live",
    autonomous_child_workflow_definition_id: str = "delivery",
    autonomous_child_max_repair_iterations: int = 5,
) -> AutonomousMissionWorkflowInput:
    """Build a compact Workflow input from the authoritative domain projection."""

    selected = temporal_settings or TemporalSettings()
    return AutonomousMissionWorkflowInput(
        mission_id=mission.id,
        mission_identity=mission.identity,
        mission_key=mission.mission_key,
        project_id=mission.project_id,
        mission_version=mission.version,
        phase=mission.phase.value,
        disposition=mission.disposition.value,
        workspace=workspace,
        database=database,
        carry_over=carry_over,
        fast_activity_timeout_seconds=selected.fast_activity_timeout_seconds,
        planning_activity_timeout_seconds=selected.llm_activity_timeout_seconds,
        heartbeat_timeout_seconds=selected.heartbeat_timeout_seconds,
        post_approval_execution_enabled=post_approval_execution_enabled,
        autonomous_child_execution_mode=autonomous_child_execution_mode,
        autonomous_child_workflow_definition_id=(
            autonomous_child_workflow_definition_id
        ),
        autonomous_child_max_repair_iterations=(
            autonomous_child_max_repair_iterations
        ),
    )


async def signal_autonomous_planning(
    client: Client,
    mission_id: int,
    command: AutonomousPlanningCommand,
    settings: TemporalSettings | None = None,
) -> None:
    """Wake the parent with identifiers for an already-persisted planning grant."""

    selected = settings or TemporalSettings.from_env()
    workflow_id = workflow_id_for_autonomous_mission(
        mission_id, selected.autonomous_workflow_id_prefix
    )
    await client.get_workflow_handle(workflow_id).signal(
        "request_autonomous_planning", command
    )


async def signal_autonomous_backlog_approved(
    client: Client,
    mission_id: int,
    notice: AutonomousBacklogApprovalNotice,
    settings: TemporalSettings | None = None,
) -> None:
    """Wake approval revalidation without treating Signal claims as authority."""

    selected = settings or TemporalSettings.from_env()
    workflow_id = workflow_id_for_autonomous_mission(
        mission_id, selected.autonomous_workflow_id_prefix
    )
    await client.get_workflow_handle(workflow_id).signal(
        "autonomous_backlog_approved", notice
    )


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


async def start_autonomous_mission_workflow(
    client: Client,
    request: AutonomousMissionWorkflowInput,
    settings: TemporalSettings | None = None,
) -> AutonomousMissionWorkflowStartResult:
    """Start or attach to the one stable parent Workflow for a mission."""

    selected = settings or TemporalSettings.from_env()
    selected.validate()
    request.to_dict()
    workflow_id = workflow_id_for_autonomous_mission(
        request.mission_id, selected.autonomous_workflow_id_prefix
    )
    duplicate = False
    correlated_version = request.mission_version
    chain_sequence = request.chain_sequence
    previous_run_id = (
        request.carry_over.previous_run_id if request.carry_over else None
    )
    try:
        handle = await client.start_workflow(
            "AutonomousMissionWorkflow",
            request,
            id=workflow_id,
            task_queue=selected.task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
            static_summary=f"Autonomous Mission {request.mission_key}",
            static_details=(
                f"Mission {request.mission_id}, project {request.project_id}, "
                f"domain version {request.mission_version}"
            ),
        )
        run_id = handle.first_execution_run_id
        if not run_id:
            description = await handle.describe()
            run_id = description.run_id
    except WorkflowAlreadyStartedError:
        duplicate = True
        handle = client.get_workflow_handle(workflow_id)
        status = await handle.query("get_mission_status", result_type=dict)
        immutable = (
            int(status.get("mission_id", 0)),
            str(status.get("mission_identity", "")),
            str(status.get("mission_key", "")),
        )
        expected = (
            request.mission_id,
            request.mission_identity,
            request.mission_key,
        )
        if immutable != expected:
            raise AutonomousMissionWorkflowConflictError(
                "Stable Autonomous Mission Workflow identity is already bound"
            )
        run_id = str(status.get("temporal_run_id", "")).strip()
        if not run_id:
            raise RuntimeError("Attached mission Workflow did not expose its run id")
        correlated_version = int(status["mission_version"])
        chain_sequence = int(status["chain_sequence"])
        previous_run_id = status.get("previous_temporal_run_id")
    return AutonomousMissionWorkflowStartResult(
        workflow_id=workflow_id,
        run_id=str(run_id),
        duplicate=duplicate,
        mission_id=request.mission_id,
        mission_identity=request.mission_identity,
        mission_key=request.mission_key,
        mission_version=correlated_version,
        chain_sequence=chain_sequence,
        previous_run_id=previous_run_id,
    )


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


async def autonomous_mission_workflow_snapshot(
    client: Client,
    mission_id: int,
    settings: TemporalSettings | None = None,
) -> dict[str, Any]:
    selected = settings or TemporalSettings.from_env()
    workflow_id = workflow_id_for_autonomous_mission(
        mission_id, selected.autonomous_workflow_id_prefix
    )
    handle = client.get_workflow_handle(workflow_id)
    description = await handle.describe()
    snapshot: dict[str, Any] = {
        "workflow_id": workflow_id,
        "run_id": description.run_id,
        "temporal_status": description.status.name,
    }
    if description.status.name == "RUNNING":
        status, progress, current_role, environment = await asyncio.gather(
            handle.query("get_mission_status", result_type=dict),
            handle.query("get_mission_progress", result_type=dict),
            handle.query("get_current_role", result_type=dict),
            handle.query("get_environment_status", result_type=dict),
        )
        snapshot.update(
            {
                "status": status,
                "progress": progress,
                "current_role": current_role,
                "environment": environment,
            }
        )
    return snapshot


async def signal_workflow(client: Client, workflow_id: str, signal: str) -> None:
    if signal not in {"pause", "resume", "cancel"}:
        raise ValueError(f"Unsupported Temporal signal: {signal}")
    await client.get_workflow_handle(workflow_id).signal(signal)
