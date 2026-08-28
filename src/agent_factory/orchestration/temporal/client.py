from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Sequence

from google.protobuf.duration_pb2 import Duration
from temporalio.api.workflowservice.v1 import (
    DescribeNamespaceRequest,
    RegisterNamespaceRequest,
)
from temporalio.api.enums.v1 import IndexedValueType
from temporalio.api.operatorservice.v1 import (
    AddSearchAttributesRequest,
    ListSearchAttributesRequest,
)
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from ...autonomous_mission import AutonomousMission
from .models import (
    AgentFactoryJobInput,
    AUTONOMOUS_CHAIN_SEQUENCE_SEARCH_ATTRIBUTE,
    AUTONOMOUS_MISSION_DISPOSITION_SEARCH_ATTRIBUTE,
    AUTONOMOUS_MISSION_ID_SEARCH_ATTRIBUTE,
    AUTONOMOUS_MISSION_IDENTITY_SEARCH_ATTRIBUTE,
    AUTONOMOUS_MISSION_KEY_SEARCH_ATTRIBUTE,
    AUTONOMOUS_MISSION_PHASE_SEARCH_ATTRIBUTE,
    AUTONOMOUS_PROJECT_ID_SEARCH_ATTRIBUTE,
    AutonomousBacklogApprovalNotice,
    AutonomousEpochHandoffCommand,
    AutonomousMissionCarryOver,
    AutonomousMissionControlCommand,
    AutonomousMissionWorkflowInput,
    AutonomousPlanningCommand,
    DemoWorkflowInput,
    autonomous_mission_search_attributes,
    autonomous_mission_visibility_memo,
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
        continue_as_new_enabled=(
            selected.autonomous_continue_as_new_enabled
        ),
        continue_as_new_event_threshold=(
            selected.autonomous_continue_as_new_event_threshold
        ),
        continue_as_new_safe_boundary_threshold=(
            selected.autonomous_continue_as_new_safe_boundary_threshold
        ),
        worker_build_id=selected.worker_build_id,
        worker_versioning_enabled=selected.worker_versioning_enabled,
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


async def signal_autonomous_mission_control(
    client: Client,
    command: AutonomousMissionControlCommand,
    settings: TemporalSettings | None = None,
) -> None:
    """Persist one typed control command through the parent Workflow Activity."""

    selected = settings or TemporalSettings.from_env()
    workflow_id = workflow_id_for_autonomous_mission(
        command.mission_id, selected.autonomous_workflow_id_prefix
    )
    signals = {
        "PAUSE": "pause_autonomous_mission",
        "RESUME": "resume_autonomous_mission",
        "STOP": "stop_autonomous_mission",
        "RETRY_CURRENT_TASK": "retry_current_task",
    }
    try:
        signal = signals[command.action]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported Autonomous Mission control action: {command.action}"
        ) from exc
    await client.get_workflow_handle(workflow_id).signal(signal, command)


async def signal_autonomous_epoch_handoff(
    client: Client,
    command: AutonomousEpochHandoffCommand,
    settings: TemporalSettings | None = None,
) -> None:
    """Wake a handoff Activity that independently reloads owner authority."""

    selected = settings or TemporalSettings.from_env()
    workflow_id = workflow_id_for_autonomous_mission(
        command.mission_id, selected.autonomous_workflow_id_prefix
    )
    signals = {
        "RESTART_FROM_CHECKPOINT": "restart_from_checkpoint",
        "APPLY_BACKLOG_REVISION": "apply_backlog_revision",
    }
    try:
        signal = signals[command.action]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported Autonomous Mission epoch handoff: {command.action}"
        ) from exc
    await client.get_workflow_handle(workflow_id).signal(signal, command)


async def signal_restart_from_checkpoint(
    client: Client,
    command: AutonomousEpochHandoffCommand,
    settings: TemporalSettings | None = None,
) -> None:
    if command.action != "RESTART_FROM_CHECKPOINT":
        raise ValueError("Checkpoint restart requires RESTART_FROM_CHECKPOINT")
    await signal_autonomous_epoch_handoff(client, command, settings)


async def signal_apply_backlog_revision(
    client: Client,
    command: AutonomousEpochHandoffCommand,
    settings: TemporalSettings | None = None,
) -> None:
    if command.action != "APPLY_BACKLOG_REVISION":
        raise ValueError("Revision handoff requires APPLY_BACKLOG_REVISION")
    await signal_autonomous_epoch_handoff(client, command, settings)


AUTONOMOUS_SEARCH_ATTRIBUTE_TYPES = {
    AUTONOMOUS_MISSION_ID_SEARCH_ATTRIBUTE.name: (
        IndexedValueType.INDEXED_VALUE_TYPE_INT
    ),
    AUTONOMOUS_PROJECT_ID_SEARCH_ATTRIBUTE.name: (
        IndexedValueType.INDEXED_VALUE_TYPE_INT
    ),
    AUTONOMOUS_CHAIN_SEQUENCE_SEARCH_ATTRIBUTE.name: (
        IndexedValueType.INDEXED_VALUE_TYPE_INT
    ),
    AUTONOMOUS_MISSION_IDENTITY_SEARCH_ATTRIBUTE.name: (
        IndexedValueType.INDEXED_VALUE_TYPE_KEYWORD
    ),
    AUTONOMOUS_MISSION_KEY_SEARCH_ATTRIBUTE.name: (
        IndexedValueType.INDEXED_VALUE_TYPE_KEYWORD
    ),
    AUTONOMOUS_MISSION_PHASE_SEARCH_ATTRIBUTE.name: (
        IndexedValueType.INDEXED_VALUE_TYPE_KEYWORD
    ),
    AUTONOMOUS_MISSION_DISPOSITION_SEARCH_ATTRIBUTE.name: (
        IndexedValueType.INDEXED_VALUE_TYPE_KEYWORD
    ),
}


async def ensure_namespace(
    client: Client, namespace: str, retention_days: int = 7
) -> None:
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
                workflow_execution_retention_period=Duration(
                    seconds=int(retention_days) * 24 * 60 * 60
                ),
            )
        )
    except RPCError as exc:
        if exc.status != RPCStatusCode.ALREADY_EXISTS:
            raise


async def ensure_autonomous_search_attributes(
    client: Client, namespace: str
) -> bool:
    """Idempotently register the typed fields used for mission discovery."""

    try:
        listed = await client.operator_service.list_search_attributes(
            ListSearchAttributesRequest(namespace=namespace)
        )
    except RPCError as exc:
        # Temporal's lightweight time-skipping test server intentionally omits
        # OperatorService. Memo-based visibility remains available there.
        if exc.status == RPCStatusCode.UNIMPLEMENTED:
            return False
        raise
    missing = {
        name: value_type
        for name, value_type in AUTONOMOUS_SEARCH_ATTRIBUTE_TYPES.items()
        if name not in listed.custom_attributes
    }
    if not missing:
        return True
    try:
        await client.operator_service.add_search_attributes(
            AddSearchAttributesRequest(
                namespace=namespace,
                search_attributes=missing,
            )
        )
    except RPCError as exc:
        if exc.status != RPCStatusCode.ALREADY_EXISTS:
            raise
    return True


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
                ensure_namespace(
                    client,
                    selected.namespace,
                    selected.namespace_retention_days,
                ),
                timeout=selected.connect_timeout_seconds,
            )
            await asyncio.wait_for(
                ensure_autonomous_search_attributes(client, selected.namespace),
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
    custom_visibility_enabled = await ensure_autonomous_search_attributes(
        client, client.namespace
    )
    duplicate = False
    correlated_version = request.mission_version
    chain_sequence = request.chain_sequence
    previous_run_id = (
        request.carry_over.previous_run_id if request.carry_over else None
    )
    try:
        visibility_options: dict[str, Any] = {
            "memo": autonomous_mission_visibility_memo(
                mission_id=request.mission_id,
                project_id=request.project_id,
                mission_identity=request.mission_identity,
                mission_key=request.mission_key,
                chain_sequence=request.chain_sequence,
            )
        }
        if custom_visibility_enabled:
            visibility_options["search_attributes"] = (
                autonomous_mission_search_attributes(
                    mission_id=request.mission_id,
                    project_id=request.project_id,
                    mission_identity=request.mission_identity,
                    mission_key=request.mission_key,
                    chain_sequence=request.chain_sequence,
                    phase=request.phase,
                    disposition=request.disposition,
                )
            )
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
                f"identity {request.mission_identity}, logical Workflow "
                f"{workflow_id}, domain version {request.mission_version}"
            ),
            **visibility_options,
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


async def discover_autonomous_mission_workflow_runs(
    client: Client,
    mission_id: int,
    *,
    workflow_id: str | None = None,
    retained_run_ids: Sequence[str] = (),
) -> tuple[dict[str, Any], ...]:
    """Discover retained runs, with domain-ledger IDs as a retention fallback."""

    if int(mission_id) <= 0:
        raise ValueError("Autonomous Mission ID must be positive")
    custom_visibility_enabled = await ensure_autonomous_search_attributes(
        client, client.namespace
    )
    executions = []
    visibility_query = (
        f"{AUTONOMOUS_MISSION_ID_SEARCH_ATTRIBUTE.name} = {int(mission_id)}"
        if custom_visibility_enabled
        else 'WorkflowType = "AutonomousMissionWorkflow"'
    )
    try:
        async for execution in client.list_workflows(visibility_query):
            attributes = execution.typed_search_attributes
            memo = await execution.memo()
            memo_identity = memo.get("agentfactory_autonomous_mission", {})
            if not isinstance(memo_identity, dict):
                memo_identity = {}
            visible_mission_id = attributes.get(
                AUTONOMOUS_MISSION_ID_SEARCH_ATTRIBUTE
            )
            if visible_mission_id is None:
                visible_mission_id = memo_identity.get("mission_id")
            if visible_mission_id != int(mission_id):
                continue
            handle = client.get_workflow_handle(
                execution.id, run_id=execution.run_id
            )
            description = await handle.describe()
            executions.append(
                {
                    "workflow_id": execution.id,
                    "run_id": execution.run_id,
                    "status": (
                        execution.status.name
                        if execution.status
                        else "UNKNOWN"
                    ),
                    "mission_id": visible_mission_id,
                    "mission_identity": attributes.get(
                        AUTONOMOUS_MISSION_IDENTITY_SEARCH_ATTRIBUTE
                    ) or memo_identity.get("mission_identity"),
                    "mission_key": attributes.get(
                        AUTONOMOUS_MISSION_KEY_SEARCH_ATTRIBUTE
                    ) or memo_identity.get("mission_key"),
                    "project_id": attributes.get(
                        AUTONOMOUS_PROJECT_ID_SEARCH_ATTRIBUTE
                    ) or memo_identity.get("project_id"),
                    "chain_sequence": attributes.get(
                        AUTONOMOUS_CHAIN_SEQUENCE_SEARCH_ATTRIBUTE
                    ) or memo_identity.get("chain_sequence"),
                    "phase": attributes.get(
                        AUTONOMOUS_MISSION_PHASE_SEARCH_ATTRIBUTE
                    ),
                    "disposition": attributes.get(
                        AUTONOMOUS_MISSION_DISPOSITION_SEARCH_ATTRIBUTE
                    ),
                    "history_length": execution.history_length,
                    "static_summary": await description.static_summary(),
                    "static_details": await description.static_details(),
                }
            )
    except RPCError as exc:
        if exc.status != RPCStatusCode.UNIMPLEMENTED or not retained_run_ids:
            raise
        executions.clear()
        selected_workflow_id = workflow_id or workflow_id_for_autonomous_mission(
            mission_id
        )
        for run_id in retained_run_ids:
            normalized_run_id = str(run_id).strip()
            if not normalized_run_id:
                raise ValueError("Retained Temporal run IDs cannot be empty")
            handle = client.get_workflow_handle(
                selected_workflow_id, run_id=normalized_run_id
            )
            description = await handle.describe()
            raw_info = description.raw_description.workflow_execution_info
            memo = await description.memo()
            memo_identity = memo.get("agentfactory_autonomous_mission", {})
            if not isinstance(memo_identity, dict):
                memo_identity = {}
            if memo_identity.get("mission_id") != int(mission_id):
                continue
            executions.append(
                {
                    "workflow_id": selected_workflow_id,
                    "run_id": normalized_run_id,
                    "status": WorkflowExecutionStatus(raw_info.status).name,
                    "mission_id": memo_identity.get("mission_id"),
                    "mission_identity": memo_identity.get("mission_identity"),
                    "mission_key": memo_identity.get("mission_key"),
                    "project_id": memo_identity.get("project_id"),
                    "chain_sequence": memo_identity.get("chain_sequence"),
                    "phase": None,
                    "disposition": None,
                    "history_length": int(raw_info.history_length),
                    "static_summary": await description.static_summary(),
                    "static_details": await description.static_details(),
                }
            )
    return tuple(
        sorted(
            executions,
            key=lambda item: (
                int(item["chain_sequence"] or 0),
                str(item["run_id"]),
            ),
        )
    )


async def signal_workflow(client: Client, workflow_id: str, signal: str) -> None:
    if signal not in {"pause", "resume", "cancel"}:
        raise ValueError(f"Unsupported Temporal signal: {signal}")
    await client.get_workflow_handle(workflow_id).signal(signal)
