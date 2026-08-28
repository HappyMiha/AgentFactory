from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from temporalio.common import (
    SearchAttributeKey,
    SearchAttributePair,
    TypedSearchAttributes,
)

AUTONOMOUS_MISSION_WORKFLOW_SCHEMA_VERSION = 2
AUTONOMOUS_MISSION_WORKFLOW_SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2})
AUTONOMOUS_SUMMARY_LIMIT = 512
AUTONOMOUS_IDENTIFIER_LIMIT = 256
AUTONOMOUS_PATH_LIMIT = 2048
AUTONOMOUS_ROLLOVER_PATCH_ID = "af-amm-017-safe-rollover-v1"
AUTONOMOUS_ROLLOVER_REASONS = frozenset(
    {
        "SAFE_BOUNDARY_THRESHOLD",
        "HISTORY_EVENT_THRESHOLD",
        "TEMPORAL_RECOMMENDATION",
        "WORKER_DEPLOYMENT_CHANGED",
    }
)
AUTONOMOUS_MISSION_ID_SEARCH_ATTRIBUTE = SearchAttributeKey.for_int(
    "AgentFactoryMissionId"
)
AUTONOMOUS_PROJECT_ID_SEARCH_ATTRIBUTE = SearchAttributeKey.for_int(
    "AgentFactoryProjectId"
)
AUTONOMOUS_CHAIN_SEQUENCE_SEARCH_ATTRIBUTE = SearchAttributeKey.for_int(
    "AgentFactoryChainSequence"
)
AUTONOMOUS_MISSION_IDENTITY_SEARCH_ATTRIBUTE = SearchAttributeKey.for_keyword(
    "AgentFactoryMissionIdentity"
)
AUTONOMOUS_MISSION_KEY_SEARCH_ATTRIBUTE = SearchAttributeKey.for_keyword(
    "AgentFactoryMissionKey"
)
AUTONOMOUS_MISSION_PHASE_SEARCH_ATTRIBUTE = SearchAttributeKey.for_keyword(
    "AgentFactoryMissionPhase"
)
AUTONOMOUS_MISSION_DISPOSITION_SEARCH_ATTRIBUTE = SearchAttributeKey.for_keyword(
    "AgentFactoryMissionDisposition"
)
AUTONOMOUS_PHASES = frozenset(
    {
        "DRAFT",
        "SPECIFICATION_ANALYSIS",
        "BACKLOG_GENERATION",
        "WAITING_FOR_BACKLOG_APPROVAL",
        "APPROVED",
        "ENVIRONMENT_DISCOVERY",
        "ENVIRONMENT_BOOTSTRAP",
        "DEVELOPMENT",
        "VALIDATION",
        "INTEGRATION",
        "FINAL_VALIDATION",
        "COMPLETED",
    }
)
AUTONOMOUS_DISPOSITIONS = frozenset(
    {
        "RUNNING",
        "PAUSED",
        "STOPPED",
        "NEEDS_ATTENTION",
        "NEEDS_HUMAN_ACTION",
        "REPLANNING",
        "RECOVERING",
        "FAILED",
    }
)
AUTONOMOUS_ENVIRONMENT_STATUSES = frozenset(
    {"NOT_STARTED", "DISCOVERING", "BOOTSTRAPPING", "READY", "UNKNOWN"}
)
AUTONOMOUS_PLANNING_ACTIONS = frozenset({"ANALYZE", "REGENERATE_BACKLOG"})
AUTONOMOUS_CONTROL_ACTIONS = frozenset(
    {"PAUSE", "RESUME", "STOP", "RETRY_CURRENT_TASK"}
)
AUTONOMOUS_EPOCH_HANDOFF_ACTIONS = frozenset(
    {"RESTART_FROM_CHECKPOINT", "APPLY_BACKLOG_REVISION"}
)


def autonomous_mission_search_attributes(
    *,
    mission_id: int,
    project_id: int,
    mission_identity: str,
    mission_key: str,
    chain_sequence: int,
    phase: str,
    disposition: str,
) -> TypedSearchAttributes:
    """Return stable typed visibility fields inherited by every chain run."""

    return TypedSearchAttributes(
        [
            SearchAttributePair(
                AUTONOMOUS_MISSION_ID_SEARCH_ATTRIBUTE, int(mission_id)
            ),
            SearchAttributePair(
                AUTONOMOUS_PROJECT_ID_SEARCH_ATTRIBUTE, int(project_id)
            ),
            SearchAttributePair(
                AUTONOMOUS_CHAIN_SEQUENCE_SEARCH_ATTRIBUTE,
                int(chain_sequence),
            ),
            SearchAttributePair(
                AUTONOMOUS_MISSION_IDENTITY_SEARCH_ATTRIBUTE,
                str(mission_identity),
            ),
            SearchAttributePair(
                AUTONOMOUS_MISSION_KEY_SEARCH_ATTRIBUTE, str(mission_key)
            ),
            SearchAttributePair(
                AUTONOMOUS_MISSION_PHASE_SEARCH_ATTRIBUTE, str(phase)
            ),
            SearchAttributePair(
                AUTONOMOUS_MISSION_DISPOSITION_SEARCH_ATTRIBUTE,
                str(disposition),
            ),
        ]
    )


def autonomous_mission_visibility_memo(
    *,
    mission_id: int,
    project_id: int,
    mission_identity: str,
    mission_key: str,
    chain_sequence: int,
) -> dict[str, dict[str, Any]]:
    """Keep a small non-indexed identity fallback beside Search Attributes."""

    return {
        "agentfactory_autonomous_mission": {
            "schema_version": AUTONOMOUS_MISSION_WORKFLOW_SCHEMA_VERSION,
            "mission_id": int(mission_id),
            "project_id": int(project_id),
            "mission_identity": str(mission_identity),
            "mission_key": str(mission_key),
            "chain_sequence": int(chain_sequence),
        }
    }


def autonomous_rollover_reason(
    *,
    safe_boundary_count: int,
    history_event_count: int,
    safe_boundary_threshold: int,
    history_event_threshold: int,
    temporal_recommended: bool,
    worker_deployment_changed: bool,
) -> str | None:
    """Choose one deterministic rollover reason at an already-safe boundary."""

    if int(safe_boundary_count) <= 0:
        return None
    if worker_deployment_changed:
        return "WORKER_DEPLOYMENT_CHANGED"
    if temporal_recommended:
        return "TEMPORAL_RECOMMENDATION"
    if int(history_event_count) >= int(history_event_threshold):
        return "HISTORY_EVENT_THRESHOLD"
    if int(safe_boundary_count) >= int(safe_boundary_threshold):
        return "SAFE_BOUNDARY_THRESHOLD"
    return None


def _bounded(value: str, label: str, limit: int) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    if len(normalized) > limit:
        raise ValueError(f"{label} exceeds {limit} characters")
    return normalized


def _optional_bounded(
    value: str | None, label: str, limit: int = AUTONOMOUS_IDENTIFIER_LIMIT
) -> str | None:
    if value is None:
        return None
    return _bounded(value, label, limit)


def _optional_id(value: int | None, label: str) -> int | None:
    if value is not None and int(value) <= 0:
        raise ValueError(f"{label} must be positive")
    return int(value) if value is not None else None


def _sha256(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return normalized


class FailureClass(StrEnum):
    TRANSIENT = "TRANSIENT"
    CONFIGURATION = "CONFIGURATION"
    AGENT_ERROR = "AGENT_ERROR"
    BUILD_ERROR = "BUILD_ERROR"
    TEST_FAILURE = "TEST_FAILURE"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    INTERNAL = "INTERNAL"


class WorkflowStatus(StrEnum):
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    RETRYING = "RETRYING"
    PAUSED = "PAUSED"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    STOPPED = "STOPPED"
    SUPERSEDED = "SUPERSEDED"


@dataclass
class ActivityResult:
    success: bool
    passed: bool = True
    exit_code: int | None = None
    summary: str = ""
    stdout_ref: str | None = None
    stderr_ref: str | None = None
    artifacts: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    failure_class: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ActivityResult":
        return cls(**value)


@dataclass
class AutonomousChildJobContext:
    """Persisted autonomous authority bound to one deterministic child attempt."""

    child_job_id: int
    mission_id: int
    backlog_revision_id: int
    backlog_revision_digest: str
    execution_epoch_id: int
    authorization_id: int
    backlog_item_id: int
    stable_item_id: str
    item_digest: str
    logical_attempt: int
    child_workflow_id: str
    repository_path: str
    epoch_branch: str
    control_fencing_token: int = 1

    def __post_init__(self) -> None:
        for value, label in (
            (self.child_job_id, "Autonomous child job id"),
            (self.mission_id, "Mission id"),
            (self.backlog_revision_id, "Backlog revision id"),
            (self.execution_epoch_id, "Execution epoch id"),
            (self.authorization_id, "Authorization id"),
            (self.backlog_item_id, "Backlog item id"),
            (self.logical_attempt, "Logical attempt"),
            (self.control_fencing_token, "Mission control fencing token"),
        ):
            _optional_id(value, label)
        _sha256(self.backlog_revision_digest, "Backlog revision digest")
        _sha256(self.item_digest, "Backlog item digest")
        _bounded(
            self.stable_item_id,
            "Stable work item id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )
        _bounded(
            self.child_workflow_id,
            "Autonomous child Workflow id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )
        _bounded(
            self.repository_path,
            "Autonomous repository path",
            AUTONOMOUS_PATH_LIMIT,
        )
        _bounded(
            self.epoch_branch,
            "Autonomous epoch branch",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AutonomousChildJobContext":
        return cls(**value)


@dataclass
class AgentFactoryJobInput:
    job_id: str
    run_id: int
    project_id: int
    task_id: int
    workspace: str
    database: str
    workflow_definition_id: str = "delivery"
    mode: str = "simulation"
    fast_activity_timeout_seconds: int = 120
    llm_activity_timeout_seconds: int = 3600
    heartbeat_timeout_seconds: int = 60
    max_repair_iterations: int = 5
    autonomous_context: AutonomousChildJobContext | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentFactoryJobInput":
        payload = dict(value)
        context = payload.get("autonomous_context")
        if isinstance(context, dict):
            payload["autonomous_context"] = AutonomousChildJobContext.from_dict(
                context
            )
        return cls(**payload)


@dataclass
class StageActivityInput:
    job: AgentFactoryJobInput
    stage: dict[str, Any]
    ordinal: int
    repair_iteration: int = 0
    failure_summary: str = ""
    control_fencing_token: int | None = None


@dataclass
class WorkflowState:
    job_id: str = ""
    run_id: int = 0
    project_id: int = 0
    task_id: int = 0
    temporal_workflow_id: str = ""
    status: str = WorkflowStatus.RUNNING
    phase: str = "starting"
    current_task_id: str | None = None
    completed_tasks: int = 0
    total_tasks: int = 0
    current_agent: str | None = None
    attempt: int = 1
    repair_iteration: int = 0
    started_at: str = ""
    last_progress: str = "Workflow created"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AutonomousMissionCarryOver:
    """Compact continue-as-new state; never contains source or artifact payloads."""

    mission_id: int
    mission_version: int
    phase: str
    disposition: str
    chain_sequence: int = 1
    previous_run_id: str | None = None
    first_run_id: str | None = None
    active_backlog_revision_id: int | None = None
    active_backlog_revision_digest: str | None = None
    proposed_backlog_revision_id: int | None = None
    proposed_backlog_revision_digest: str | None = None
    proposal_verification_id: int | None = None
    proposal_pipeline_run_id: int | None = None
    proposal_revision_count: int = 0
    active_execution_epoch_id: int | None = None
    backlog_approval_id: int | None = None
    execution_authorization_id: int | None = None
    current_checkpoint_id: int | None = None
    current_child_job_id: int | None = None
    current_child_workflow_id: str | None = None
    current_work_item_stable_id: str | None = None
    # Schema v1 carried these display values. Schema v2 leaves them empty and
    # reconstructs display state in the new run so only identities cross runs.
    current_role: str | None = None
    current_model: str | None = None
    completed_items: int = 0
    total_items: int = 0
    accepted_mutation_count: int = 0
    previous_run_safe_boundary_count: int = 0
    previous_run_history_event_count: int = 0
    rollover_reason: str | None = None
    previous_worker_build_id: str | None = None
    environment_status: str = "NOT_STARTED"
    control_fencing_token: int = 1
    last_control_command_id: str | None = None
    last_control_action: str | None = None
    pending_retry_child_job_id: int | None = None
    pending_retry_logical_attempt: int | None = None
    pending_epoch_handoff_command_id: str | None = None
    pending_epoch_handoff_action: str | None = None
    last_epoch_handoff_command_id: str | None = None
    last_epoch_handoff_action: str | None = None
    last_activity: str = ""
    last_activity_at: str = ""
    schema_version: int = AUTONOMOUS_MISSION_WORKFLOW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version not in (
            AUTONOMOUS_MISSION_WORKFLOW_SUPPORTED_SCHEMA_VERSIONS
        ):
            raise ValueError("Unsupported Autonomous Mission carry-over version")
        if int(self.mission_id) <= 0 or int(self.mission_version) <= 0:
            raise ValueError("Mission identity and version must be positive")
        if self.phase not in AUTONOMOUS_PHASES:
            raise ValueError(f"Unsupported Autonomous Mission phase: {self.phase}")
        if self.disposition not in AUTONOMOUS_DISPOSITIONS:
            raise ValueError(
                f"Unsupported Autonomous Mission disposition: {self.disposition}"
            )
        if int(self.chain_sequence) <= 0:
            raise ValueError("Temporal chain sequence must be positive")
        previous_run_id = _optional_bounded(
            self.previous_run_id, "Previous Temporal run id"
        )
        first_run_id = _optional_bounded(
            self.first_run_id, "First Temporal run id"
        )
        if (self.chain_sequence == 1) != (previous_run_id is None):
            raise ValueError(
                "Only the first Temporal chain entry omits previous_run_id"
            )
        if self.chain_sequence > 2 and first_run_id is None:
            raise ValueError(
                "Later Temporal chain entries must retain first_run_id"
            )
        revision_id = _optional_id(
            self.active_backlog_revision_id, "Active backlog revision id"
        )
        revision_digest = _sha256(
            self.active_backlog_revision_digest,
            "Active backlog revision digest",
        )
        if (revision_id is None) != (revision_digest is None):
            raise ValueError("Active revision id and digest must be supplied together")
        proposed_revision_id = _optional_id(
            self.proposed_backlog_revision_id, "Proposed backlog revision id"
        )
        proposed_revision_digest = _sha256(
            self.proposed_backlog_revision_digest,
            "Proposed backlog revision digest",
        )
        if (proposed_revision_id is None) != (proposed_revision_digest is None):
            raise ValueError(
                "Proposed revision id and digest must be supplied together"
            )
        _optional_id(self.proposal_verification_id, "Proposal verification id")
        _optional_id(self.proposal_pipeline_run_id, "Proposal pipeline run id")
        if self.proposal_revision_count < 0:
            raise ValueError("Proposal revision count cannot be negative")
        _optional_id(self.active_execution_epoch_id, "Active execution epoch id")
        _optional_id(self.backlog_approval_id, "Backlog approval id")
        _optional_id(
            self.execution_authorization_id,
            "Execution authorization id",
        )
        _optional_id(self.current_checkpoint_id, "Current checkpoint id")
        _optional_id(self.current_child_job_id, "Current child job id")
        _optional_bounded(
            self.current_child_workflow_id,
            "Current child Workflow id",
        )
        _optional_bounded(
            self.current_work_item_stable_id, "Current work item stable id"
        )
        _optional_bounded(self.current_role, "Current role")
        _optional_bounded(self.current_model, "Current model")
        if self.completed_items < 0 or self.total_items < 0:
            raise ValueError("Mission progress counters cannot be negative")
        if self.completed_items > self.total_items:
            raise ValueError("Completed item count cannot exceed total item count")
        for value, label in (
            (self.accepted_mutation_count, "Accepted mutation count"),
            (
                self.previous_run_safe_boundary_count,
                "Previous run safe-boundary count",
            ),
            (
                self.previous_run_history_event_count,
                "Previous run history-event count",
            ),
        ):
            if int(value) < 0:
                raise ValueError(f"{label} cannot be negative")
        if self.rollover_reason is not None and (
            self.rollover_reason not in AUTONOMOUS_ROLLOVER_REASONS
        ):
            raise ValueError(
                f"Unsupported continue-as-new reason: {self.rollover_reason}"
            )
        _optional_bounded(
            self.previous_worker_build_id,
            "Previous Worker build id",
        )
        if self.environment_status not in AUTONOMOUS_ENVIRONMENT_STATUSES:
            raise ValueError(
                f"Unsupported environment status: {self.environment_status}"
            )
        if int(self.control_fencing_token) <= 0:
            raise ValueError("Mission control fencing token must be positive")
        _optional_bounded(
            self.last_control_command_id, "Last control command id"
        )
        if (
            self.last_control_action is not None
            and self.last_control_action not in AUTONOMOUS_CONTROL_ACTIONS
        ):
            raise ValueError(
                f"Unsupported mission control action: {self.last_control_action}"
            )
        _optional_id(
            self.pending_retry_child_job_id, "Pending retry child job id"
        )
        _optional_id(
            self.pending_retry_logical_attempt,
            "Pending retry logical attempt",
        )
        if (self.pending_retry_child_job_id is None) != (
            self.pending_retry_logical_attempt is None
        ):
            raise ValueError(
                "Pending retry child and logical attempt must be supplied together"
            )
        for command_id, action, label in (
            (
                self.pending_epoch_handoff_command_id,
                self.pending_epoch_handoff_action,
                "Pending epoch handoff",
            ),
            (
                self.last_epoch_handoff_command_id,
                self.last_epoch_handoff_action,
                "Last epoch handoff",
            ),
        ):
            if (command_id is None) != (action is None):
                raise ValueError(f"{label} command and action must be supplied together")
            _optional_bounded(command_id, f"{label} command id")
            if action is not None and action not in AUTONOMOUS_EPOCH_HANDOFF_ACTIONS:
                raise ValueError(f"Unsupported {label.lower()} action: {action}")
        if self.schema_version >= 2 and any(
            (
                self.current_role is not None,
                self.current_model is not None,
                bool(self.last_activity),
                bool(self.last_activity_at),
            )
        ):
            raise ValueError(
                "Carry-over schema v2 cannot contain display summaries or role/model data"
            )
        if self.last_activity:
            _bounded(self.last_activity, "Last activity", AUTONOMOUS_SUMMARY_LIMIT)
        if self.last_activity_at:
            _bounded(
                self.last_activity_at,
                "Last activity timestamp",
                AUTONOMOUS_IDENTIFIER_LIMIT,
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AutonomousMissionCarryOver":
        return cls(**value)


@dataclass(frozen=True)
class AutonomousMissionWorkflowInput:
    """Identifier-only parent Workflow input for one durable mission chain."""

    mission_id: int
    mission_identity: str
    mission_key: str
    project_id: int
    mission_version: int
    phase: str
    disposition: str
    workspace: str
    database: str
    carry_over: AutonomousMissionCarryOver | None = None
    fast_activity_timeout_seconds: int = 120
    planning_activity_timeout_seconds: int = 3600
    heartbeat_timeout_seconds: int = 60
    post_approval_execution_enabled: bool = True
    autonomous_child_execution_mode: str = "live"
    autonomous_child_workflow_definition_id: str = "delivery"
    autonomous_child_max_repair_iterations: int = 5
    continue_as_new_enabled: bool = False
    continue_as_new_event_threshold: int = 10_000
    continue_as_new_safe_boundary_threshold: int = 100
    worker_build_id: str = "agentfactory-legacy-unversioned"
    worker_versioning_enabled: bool = False
    schema_version: int = AUTONOMOUS_MISSION_WORKFLOW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version not in (
            AUTONOMOUS_MISSION_WORKFLOW_SUPPORTED_SCHEMA_VERSIONS
        ):
            raise ValueError("Unsupported Autonomous Mission Workflow input version")
        if int(self.mission_id) <= 0 or int(self.project_id) <= 0:
            raise ValueError("Mission and project identifiers must be positive")
        if int(self.mission_version) <= 0:
            raise ValueError("Mission version must be positive")
        _bounded(self.mission_identity, "Mission identity", AUTONOMOUS_IDENTIFIER_LIMIT)
        _bounded(self.mission_key, "Mission key", AUTONOMOUS_IDENTIFIER_LIMIT)
        if self.phase not in AUTONOMOUS_PHASES:
            raise ValueError(f"Unsupported Autonomous Mission phase: {self.phase}")
        if self.disposition not in AUTONOMOUS_DISPOSITIONS:
            raise ValueError(
                f"Unsupported Autonomous Mission disposition: {self.disposition}"
            )
        _bounded(self.workspace, "Mission workspace", AUTONOMOUS_PATH_LIMIT)
        _bounded(self.database, "Mission database", AUTONOMOUS_PATH_LIMIT)
        for value, label in (
            (self.fast_activity_timeout_seconds, "Fast activity timeout"),
            (self.planning_activity_timeout_seconds, "Planning activity timeout"),
            (self.heartbeat_timeout_seconds, "Heartbeat timeout"),
        ):
            if int(value) <= 0:
                raise ValueError(f"{label} must be positive")
        if self.heartbeat_timeout_seconds >= self.planning_activity_timeout_seconds:
            raise ValueError(
                "Heartbeat timeout must be shorter than planning activity timeout"
            )
        if self.autonomous_child_execution_mode not in {"simulation", "live"}:
            raise ValueError(
                "Autonomous child execution mode must be simulation or live"
            )
        _bounded(
            self.autonomous_child_workflow_definition_id,
            "Autonomous child workflow definition id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )
        if not 0 <= int(self.autonomous_child_max_repair_iterations) <= 100:
            raise ValueError(
                "Autonomous child repair iterations must be between zero and 100"
            )
        if not 10 <= int(self.continue_as_new_event_threshold) <= 50_000:
            raise ValueError(
                "Continue-as-new event threshold must be between 10 and 50000"
            )
        if not 1 <= int(self.continue_as_new_safe_boundary_threshold) <= 10_000:
            raise ValueError(
                "Continue-as-new safe-boundary threshold must be between 1 and 10000"
            )
        _bounded(
            self.worker_build_id,
            "Temporal Worker build id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )
        if self.carry_over is not None:
            carry = self.carry_over
            if (
                carry.mission_id != self.mission_id
                or carry.mission_version != self.mission_version
                or carry.phase != self.phase
                or carry.disposition != self.disposition
                or carry.schema_version != self.schema_version
            ):
                raise ValueError(
                    "Carry-over must bind the exact mission version and control state"
                )

    @property
    def chain_sequence(self) -> int:
        return self.carry_over.chain_sequence if self.carry_over else 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AutonomousMissionWorkflowInput":
        payload = dict(value)
        carry = payload.get("carry_over")
        if isinstance(carry, dict):
            payload["carry_over"] = AutonomousMissionCarryOver.from_dict(carry)
        return cls(**payload)


@dataclass
class AutonomousMissionWorkflowState:
    """Bounded query state owned by Temporal, with SQLite remaining authoritative."""

    mission_id: int
    mission_identity: str
    mission_key: str
    project_id: int
    mission_version: int
    temporal_workflow_id: str
    temporal_run_id: str
    chain_sequence: int
    workflow_status: str
    phase: str
    disposition: str
    previous_temporal_run_id: str | None = None
    temporal_first_run_id: str | None = None
    active_backlog_revision_id: int | None = None
    active_backlog_revision_digest: str | None = None
    proposed_backlog_revision_id: int | None = None
    proposed_backlog_revision_digest: str | None = None
    proposal_verification_id: int | None = None
    proposal_pipeline_run_id: int | None = None
    proposal_revision_count: int = 0
    active_execution_epoch_id: int | None = None
    backlog_approval_id: int | None = None
    execution_authorization_id: int | None = None
    current_checkpoint_id: int | None = None
    current_child_job_id: int | None = None
    current_child_workflow_id: str | None = None
    current_work_item_stable_id: str | None = None
    current_role: str | None = None
    current_model: str | None = None
    completed_items: int = 0
    total_items: int = 0
    accepted_mutation_count: int = 0
    run_safe_boundary_count: int = 0
    previous_run_safe_boundary_count: int = 0
    current_history_event_count: int = 0
    previous_run_history_event_count: int = 0
    last_rollover_reason: str | None = None
    workflow_build_id: str | None = None
    previous_worker_build_id: str | None = None
    rollover_pending: bool = False
    environment_status: str = "NOT_STARTED"
    control_fencing_token: int = 1
    last_control_command_id: str | None = None
    last_control_action: str | None = None
    pending_retry_child_job_id: int | None = None
    pending_retry_logical_attempt: int | None = None
    pending_epoch_handoff_command_id: str | None = None
    pending_epoch_handoff_action: str | None = None
    last_epoch_handoff_command_id: str | None = None
    last_epoch_handoff_action: str | None = None
    last_activity: str = "Mission workflow created"
    last_activity_at: str = ""
    started_at: str = ""
    schema_version: int = AUTONOMOUS_MISSION_WORKFLOW_SCHEMA_VERSION

    @classmethod
    def from_input(
        cls,
        request: AutonomousMissionWorkflowInput,
        *,
        workflow_id: str,
        run_id: str,
        started_at: str,
    ) -> "AutonomousMissionWorkflowState":
        carry = request.carry_over or AutonomousMissionCarryOver(
            mission_id=request.mission_id,
            mission_version=request.mission_version,
            phase=request.phase,
            disposition=request.disposition,
            schema_version=request.schema_version,
        )
        return cls(
            mission_id=request.mission_id,
            mission_identity=request.mission_identity,
            mission_key=request.mission_key,
            project_id=request.project_id,
            mission_version=carry.mission_version,
            temporal_workflow_id=workflow_id,
            temporal_run_id=run_id,
            chain_sequence=carry.chain_sequence,
            workflow_status=WorkflowStatus.RUNNING.value,
            phase=carry.phase,
            disposition=carry.disposition,
            previous_temporal_run_id=carry.previous_run_id,
            temporal_first_run_id=(
                carry.first_run_id or carry.previous_run_id or run_id
            ),
            active_backlog_revision_id=carry.active_backlog_revision_id,
            active_backlog_revision_digest=carry.active_backlog_revision_digest,
            proposed_backlog_revision_id=carry.proposed_backlog_revision_id,
            proposed_backlog_revision_digest=carry.proposed_backlog_revision_digest,
            proposal_verification_id=carry.proposal_verification_id,
            proposal_pipeline_run_id=carry.proposal_pipeline_run_id,
            proposal_revision_count=carry.proposal_revision_count,
            active_execution_epoch_id=carry.active_execution_epoch_id,
            backlog_approval_id=carry.backlog_approval_id,
            execution_authorization_id=carry.execution_authorization_id,
            current_checkpoint_id=carry.current_checkpoint_id,
            current_child_job_id=carry.current_child_job_id,
            current_child_workflow_id=carry.current_child_workflow_id,
            current_work_item_stable_id=carry.current_work_item_stable_id,
            current_role=(carry.current_role if carry.schema_version == 1 else None),
            current_model=(carry.current_model if carry.schema_version == 1 else None),
            completed_items=carry.completed_items,
            total_items=carry.total_items,
            accepted_mutation_count=carry.accepted_mutation_count,
            previous_run_safe_boundary_count=(
                carry.previous_run_safe_boundary_count
            ),
            previous_run_history_event_count=(
                carry.previous_run_history_event_count
            ),
            last_rollover_reason=carry.rollover_reason,
            previous_worker_build_id=carry.previous_worker_build_id,
            environment_status=carry.environment_status,
            control_fencing_token=carry.control_fencing_token,
            last_control_command_id=carry.last_control_command_id,
            last_control_action=carry.last_control_action,
            pending_retry_child_job_id=carry.pending_retry_child_job_id,
            pending_retry_logical_attempt=carry.pending_retry_logical_attempt,
            pending_epoch_handoff_command_id=(
                carry.pending_epoch_handoff_command_id
            ),
            pending_epoch_handoff_action=carry.pending_epoch_handoff_action,
            last_epoch_handoff_command_id=carry.last_epoch_handoff_command_id,
            last_epoch_handoff_action=carry.last_epoch_handoff_action,
            last_activity=(
                carry.last_activity
                if carry.schema_version == 1 and carry.last_activity
                else "Mission workflow continued from durable identities"
            ),
            last_activity_at=(
                carry.last_activity_at
                if carry.schema_version == 1 and carry.last_activity_at
                else started_at
            ),
            started_at=started_at,
            schema_version=request.schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AutonomousMissionWorkflowState":
        state = cls(**value)
        state.validate()
        return state

    def validate(self) -> None:
        if (self.chain_sequence == 1) != (
            self.previous_temporal_run_id is None
        ):
            raise ValueError(
                "Only the first Workflow state omits its previous Temporal run id"
            )
        AutonomousMissionWorkflowInput(
            mission_id=self.mission_id,
            mission_identity=self.mission_identity,
            mission_key=self.mission_key,
            project_id=self.project_id,
            mission_version=self.mission_version,
            phase=self.phase,
            disposition=self.disposition,
            workspace="bounded-state",
            database="bounded-state",
            carry_over=self.to_carry_over(),
            schema_version=self.schema_version,
        )
        _bounded(
            self.temporal_workflow_id,
            "Temporal workflow id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )
        _bounded(
            self.temporal_run_id, "Temporal run id", AUTONOMOUS_IDENTIFIER_LIMIT
        )
        _optional_bounded(
            self.previous_temporal_run_id, "Previous Temporal run id"
        )
        _bounded(
            self.temporal_first_run_id or "",
            "First Temporal run id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )
        _bounded(
            self.workflow_status, "Workflow status", AUTONOMOUS_IDENTIFIER_LIMIT
        )
        if self.started_at:
            _bounded(
                self.started_at, "Workflow start timestamp", AUTONOMOUS_IDENTIFIER_LIMIT
            )
        for value, label in (
            (self.accepted_mutation_count, "Accepted mutation count"),
            (self.run_safe_boundary_count, "Run safe-boundary count"),
            (
                self.previous_run_safe_boundary_count,
                "Previous run safe-boundary count",
            ),
            (self.current_history_event_count, "Current history-event count"),
            (
                self.previous_run_history_event_count,
                "Previous run history-event count",
            ),
        ):
            if int(value) < 0:
                raise ValueError(f"{label} cannot be negative")
        if self.last_rollover_reason is not None and (
            self.last_rollover_reason not in AUTONOMOUS_ROLLOVER_REASONS
        ):
            raise ValueError(
                f"Unsupported continue-as-new reason: {self.last_rollover_reason}"
            )
        _optional_bounded(self.workflow_build_id, "Temporal Worker build id")
        _optional_bounded(
            self.previous_worker_build_id,
            "Previous Temporal Worker build id",
        )

    def to_carry_over(
        self,
        *,
        rollover_reason: str | None = None,
        history_event_count: int | None = None,
        worker_build_id: str | None = None,
    ) -> AutonomousMissionCarryOver:
        return AutonomousMissionCarryOver(
            mission_id=self.mission_id,
            mission_version=self.mission_version,
            phase=self.phase,
            disposition=self.disposition,
            chain_sequence=self.chain_sequence + 1,
            previous_run_id=self.temporal_run_id,
            first_run_id=self.temporal_first_run_id,
            active_backlog_revision_id=self.active_backlog_revision_id,
            active_backlog_revision_digest=self.active_backlog_revision_digest,
            proposed_backlog_revision_id=self.proposed_backlog_revision_id,
            proposed_backlog_revision_digest=self.proposed_backlog_revision_digest,
            proposal_verification_id=self.proposal_verification_id,
            proposal_pipeline_run_id=self.proposal_pipeline_run_id,
            proposal_revision_count=self.proposal_revision_count,
            active_execution_epoch_id=self.active_execution_epoch_id,
            backlog_approval_id=self.backlog_approval_id,
            execution_authorization_id=self.execution_authorization_id,
            current_checkpoint_id=self.current_checkpoint_id,
            current_child_job_id=self.current_child_job_id,
            current_child_workflow_id=self.current_child_workflow_id,
            current_work_item_stable_id=self.current_work_item_stable_id,
            current_role=None,
            current_model=None,
            completed_items=self.completed_items,
            total_items=self.total_items,
            accepted_mutation_count=self.accepted_mutation_count,
            previous_run_safe_boundary_count=self.run_safe_boundary_count,
            previous_run_history_event_count=(
                self.current_history_event_count
                if history_event_count is None
                else int(history_event_count)
            ),
            rollover_reason=rollover_reason,
            previous_worker_build_id=(worker_build_id or self.workflow_build_id),
            environment_status=self.environment_status,
            control_fencing_token=self.control_fencing_token,
            last_control_command_id=self.last_control_command_id,
            last_control_action=self.last_control_action,
            pending_retry_child_job_id=self.pending_retry_child_job_id,
            pending_retry_logical_attempt=self.pending_retry_logical_attempt,
            pending_epoch_handoff_command_id=(
                self.pending_epoch_handoff_command_id
            ),
            pending_epoch_handoff_action=self.pending_epoch_handoff_action,
            last_epoch_handoff_command_id=self.last_epoch_handoff_command_id,
            last_epoch_handoff_action=self.last_epoch_handoff_action,
            last_activity="",
            last_activity_at="",
            schema_version=self.schema_version,
        )


@dataclass(frozen=True)
class AutonomousMissionActivityScope:
    """Stable identifiers supplied by the Workflow, never by a wake-up Signal."""

    mission_id: int
    mission_identity: str
    mission_key: str
    project_id: int
    workspace: str
    database: str
    temporal_workflow_id: str
    temporal_first_run_id: str

    def __post_init__(self) -> None:
        if int(self.mission_id) <= 0 or int(self.project_id) <= 0:
            raise ValueError("Mission and project identifiers must be positive")
        _bounded(self.mission_identity, "Mission identity", AUTONOMOUS_IDENTIFIER_LIMIT)
        _bounded(self.mission_key, "Mission key", AUTONOMOUS_IDENTIFIER_LIMIT)
        _bounded(self.workspace, "Mission workspace", AUTONOMOUS_PATH_LIMIT)
        _bounded(self.database, "Mission database", AUTONOMOUS_PATH_LIMIT)
        _bounded(
            self.temporal_workflow_id,
            "Temporal workflow id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )
        _bounded(
            self.temporal_first_run_id,
            "Temporal first run id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )


@dataclass(frozen=True)
class AutonomousTemporalRunRegistrationInput:
    """Identifier-only evidence for one concrete run in a logical mission chain."""

    scope: AutonomousMissionActivityScope
    run_id: str
    chain_sequence: int
    previous_run_id: str | None
    first_run_id: str
    mission_version: int
    phase: str
    disposition: str
    active_backlog_revision_id: int | None
    active_execution_epoch_id: int | None
    current_checkpoint_id: int | None
    control_fencing_token: int
    workflow_build_id: str
    rollover_reason: str | None
    previous_run_history_event_count: int
    previous_run_safe_boundary_count: int
    accepted_mutation_count: int

    def __post_init__(self) -> None:
        _bounded(self.run_id, "Temporal run id", AUTONOMOUS_IDENTIFIER_LIMIT)
        _bounded(
            self.first_run_id,
            "Temporal first run id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )
        _optional_bounded(
            self.previous_run_id,
            "Previous Temporal run id",
        )
        if int(self.chain_sequence) <= 0:
            raise ValueError("Temporal chain sequence must be positive")
        if (int(self.chain_sequence) == 1) != (self.previous_run_id is None):
            raise ValueError(
                "Only the first Temporal run omits its previous run identity"
            )
        if int(self.chain_sequence) == 1 and self.first_run_id != self.run_id:
            raise ValueError("The first Temporal run must identify itself as first")
        if int(self.mission_version) <= 0 or int(self.control_fencing_token) <= 0:
            raise ValueError("Mission version and fencing token must be positive")
        if self.phase not in AUTONOMOUS_PHASES:
            raise ValueError(f"Unsupported Autonomous Mission phase: {self.phase}")
        if self.disposition not in AUTONOMOUS_DISPOSITIONS:
            raise ValueError(
                f"Unsupported Autonomous Mission disposition: {self.disposition}"
            )
        for value, label in (
            (self.active_backlog_revision_id, "Active backlog revision id"),
            (self.active_execution_epoch_id, "Active execution epoch id"),
            (self.current_checkpoint_id, "Current checkpoint id"),
        ):
            _optional_id(value, label)
        _bounded(
            self.workflow_build_id,
            "Temporal Worker build id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )
        if self.rollover_reason is not None and (
            self.rollover_reason not in AUTONOMOUS_ROLLOVER_REASONS
        ):
            raise ValueError(
                f"Unsupported continue-as-new reason: {self.rollover_reason}"
            )
        if int(self.chain_sequence) == 1 and self.rollover_reason is not None:
            raise ValueError("The first Temporal run cannot have a rollover reason")
        if int(self.chain_sequence) > 1 and self.rollover_reason is None:
            raise ValueError("A continued Temporal run requires a rollover reason")
        for value, label in (
            (
                self.previous_run_history_event_count,
                "Previous run history-event count",
            ),
            (
                self.previous_run_safe_boundary_count,
                "Previous run safe-boundary count",
            ),
            (self.accepted_mutation_count, "Accepted mutation count"),
        ):
            if int(value) < 0:
                raise ValueError(f"{label} cannot be negative")


@dataclass(frozen=True)
class AutonomousTemporalRunRegistrationResult:
    mission_id: int
    registration_id: int
    run_id: str
    chain_sequence: int
    workflow_build_id: str
    run_digest: str
    duplicate: bool
    registered_at: str

    def __post_init__(self) -> None:
        _optional_id(self.mission_id, "Mission id")
        _optional_id(self.registration_id, "Temporal run registration id")
        _bounded(self.run_id, "Temporal run id", AUTONOMOUS_IDENTIFIER_LIMIT)
        if int(self.chain_sequence) <= 0:
            raise ValueError("Temporal chain sequence must be positive")
        _bounded(
            self.workflow_build_id,
            "Temporal Worker build id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )
        _sha256(self.run_digest, "Temporal run digest")
        _bounded(
            self.registered_at,
            "Temporal run registration timestamp",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )


@dataclass(frozen=True)
class AutonomousMissionControlCommand:
    """Typed, idempotent mission control request carried by a Signal."""

    mission_id: int
    command_id: str
    action: str
    actor: str
    reason: str
    expected_mission_version: int
    expected_fencing_token: int
    expected_backlog_revision_id: int | None = None
    expected_execution_epoch_id: int | None = None
    child_job_id: int | None = None

    def __post_init__(self) -> None:
        _optional_id(self.mission_id, "Mission id")
        _bounded(
            self.command_id,
            "Mission control command id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )
        if self.action not in AUTONOMOUS_CONTROL_ACTIONS:
            raise ValueError(f"Unsupported mission control action: {self.action}")
        _bounded(self.actor, "Mission control actor", AUTONOMOUS_IDENTIFIER_LIMIT)
        _bounded(self.reason, "Mission control reason", AUTONOMOUS_SUMMARY_LIMIT)
        _optional_id(self.expected_mission_version, "Expected mission version")
        _optional_id(self.expected_fencing_token, "Expected fencing token")
        _optional_id(
            self.expected_backlog_revision_id,
            "Expected backlog revision id",
        )
        _optional_id(
            self.expected_execution_epoch_id,
            "Expected execution epoch id",
        )
        _optional_id(self.child_job_id, "Current child job id")
        if self.action == "RETRY_CURRENT_TASK" and self.child_job_id is None:
            raise ValueError("Retry requires the current child job id")


@dataclass(frozen=True)
class AutonomousMissionControlActivityInput:
    scope: AutonomousMissionActivityScope
    command: AutonomousMissionControlCommand


@dataclass(frozen=True)
class AutonomousMissionControlResult:
    mission_id: int
    command_id: str
    action: str
    mission_version: int
    phase: str
    disposition: str
    fencing_token: int
    active_operations: int
    releasing_operations: int
    duplicate: bool
    occurred_at: str
    child_job_id: int | None = None
    logical_attempt: int | None = None

    def __post_init__(self) -> None:
        _optional_id(self.mission_id, "Mission id")
        _bounded(
            self.command_id,
            "Mission control command id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )
        if self.action not in AUTONOMOUS_CONTROL_ACTIONS:
            raise ValueError(f"Unsupported mission control action: {self.action}")
        _optional_id(self.mission_version, "Mission version")
        if self.phase not in AUTONOMOUS_PHASES:
            raise ValueError(f"Unsupported Autonomous Mission phase: {self.phase}")
        if self.disposition not in AUTONOMOUS_DISPOSITIONS:
            raise ValueError(
                f"Unsupported Autonomous Mission disposition: {self.disposition}"
            )
        _optional_id(self.fencing_token, "Mission fencing token")
        if self.active_operations < 0 or self.releasing_operations < 0:
            raise ValueError("Mission operation counts cannot be negative")
        _optional_id(self.child_job_id, "Current child job id")
        _optional_id(self.logical_attempt, "Retry logical attempt")
        if self.action == "RETRY_CURRENT_TASK" and any(
            value is None for value in (self.child_job_id, self.logical_attempt)
        ):
            raise ValueError("Retry result requires child and attempt identity")
        _bounded(
            self.occurred_at,
            "Mission control timestamp",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )


@dataclass(frozen=True)
class AutonomousMissionControlSnapshotInput:
    scope: AutonomousMissionActivityScope


@dataclass(frozen=True)
class AutonomousMissionControlSnapshotResult:
    mission_id: int
    mission_version: int
    phase: str
    disposition: str
    fencing_token: int
    backlog_revision_id: int | None
    execution_epoch_id: int | None
    occurred_at: str

    def __post_init__(self) -> None:
        _optional_id(self.mission_id, "Mission id")
        _optional_id(self.mission_version, "Mission version")
        if self.phase not in AUTONOMOUS_PHASES:
            raise ValueError(f"Unsupported Autonomous Mission phase: {self.phase}")
        if self.disposition not in AUTONOMOUS_DISPOSITIONS:
            raise ValueError(
                f"Unsupported Autonomous Mission disposition: {self.disposition}"
            )
        _optional_id(self.fencing_token, "Mission fencing token")
        _optional_id(self.backlog_revision_id, "Active backlog revision id")
        _optional_id(self.execution_epoch_id, "Active execution epoch id")
        _bounded(
            self.occurred_at,
            "Mission control snapshot timestamp",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )


@dataclass(frozen=True)
class AutonomousEpochHandoffCommand:
    """Identifier-only Signal claims revalidated against a persisted owner command."""

    mission_id: int
    command_id: str
    action: str
    expected_mission_version: int
    expected_fencing_token: int
    expected_backlog_revision_id: int
    expected_execution_epoch_id: int
    selected_checkpoint_id: int
    selected_backlog_revision_id: int
    expected_child_job_id: int | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.mission_id, "Mission id"),
            (self.expected_mission_version, "Expected mission version"),
            (self.expected_fencing_token, "Expected fencing token"),
            (self.expected_backlog_revision_id, "Expected backlog revision id"),
            (self.expected_execution_epoch_id, "Expected execution epoch id"),
            (self.selected_checkpoint_id, "Selected checkpoint id"),
            (self.selected_backlog_revision_id, "Selected backlog revision id"),
        ):
            _optional_id(value, label)
        _optional_id(self.expected_child_job_id, "Expected child job id")
        _bounded(
            self.command_id,
            "Epoch handoff command id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )
        if self.action not in AUTONOMOUS_EPOCH_HANDOFF_ACTIONS:
            raise ValueError(f"Unsupported epoch handoff action: {self.action}")


@dataclass(frozen=True)
class AutonomousEpochHandoffPreparationInput:
    scope: AutonomousMissionActivityScope
    command: AutonomousEpochHandoffCommand


@dataclass(frozen=True)
class AutonomousEpochHandoffPreparationResult:
    mission_id: int
    command_id: str
    action: str
    stopped_mission_version: int
    stopped_fencing_token: int
    source_execution_epoch_id: int
    selected_checkpoint_id: int
    selected_backlog_revision_id: int
    child_job_id: int | None
    duplicate: bool
    occurred_at: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.mission_id, "Mission id"),
            (self.stopped_mission_version, "Stopped mission version"),
            (self.stopped_fencing_token, "Stopped fencing token"),
            (self.source_execution_epoch_id, "Source execution epoch id"),
            (self.selected_checkpoint_id, "Selected checkpoint id"),
            (self.selected_backlog_revision_id, "Selected backlog revision id"),
        ):
            _optional_id(value, label)
        _optional_id(self.child_job_id, "Epoch handoff child job id")
        _bounded(self.command_id, "Epoch handoff command id", AUTONOMOUS_IDENTIFIER_LIMIT)
        if self.action not in AUTONOMOUS_EPOCH_HANDOFF_ACTIONS:
            raise ValueError(f"Unsupported epoch handoff action: {self.action}")
        _bounded(self.occurred_at, "Epoch handoff timestamp", AUTONOMOUS_IDENTIFIER_LIMIT)


@dataclass(frozen=True)
class AutonomousEpochHandoffCompletionInput:
    scope: AutonomousMissionActivityScope
    command_id: str

    def __post_init__(self) -> None:
        _bounded(
            self.command_id,
            "Epoch handoff completion command id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )


@dataclass(frozen=True)
class AutonomousEpochHandoffCompletionResult:
    mission_id: int
    command_id: str
    action: str
    mission_version: int
    phase: str
    disposition: str
    fencing_token: int
    source_execution_epoch_id: int
    result_execution_epoch_id: int
    selected_checkpoint_id: int
    selected_backlog_revision_id: int
    selected_backlog_revision_digest: str
    execution_authorization_id: int
    duplicate: bool
    occurred_at: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.mission_id, "Mission id"),
            (self.mission_version, "Mission version"),
            (self.fencing_token, "Fencing token"),
            (self.source_execution_epoch_id, "Source execution epoch id"),
            (self.result_execution_epoch_id, "Result execution epoch id"),
            (self.selected_checkpoint_id, "Selected checkpoint id"),
            (self.selected_backlog_revision_id, "Selected backlog revision id"),
            (self.execution_authorization_id, "Execution authorization id"),
        ):
            _optional_id(value, label)
        _bounded(self.command_id, "Epoch handoff command id", AUTONOMOUS_IDENTIFIER_LIMIT)
        if self.action not in AUTONOMOUS_EPOCH_HANDOFF_ACTIONS:
            raise ValueError(f"Unsupported epoch handoff action: {self.action}")
        _sha256(
            self.selected_backlog_revision_digest,
            "Selected backlog revision digest",
        )
        if self.phase not in AUTONOMOUS_PHASES:
            raise ValueError(f"Unsupported Autonomous Mission phase: {self.phase}")
        if self.disposition not in AUTONOMOUS_DISPOSITIONS:
            raise ValueError(
                f"Unsupported Autonomous Mission disposition: {self.disposition}"
            )
        _bounded(self.occurred_at, "Epoch handoff timestamp", AUTONOMOUS_IDENTIFIER_LIMIT)


@dataclass(frozen=True)
class AutonomousChildEpochHandoffNotice:
    mission_id: int
    child_job_id: int
    command_id: str
    stopped_mission_version: int
    stopped_fencing_token: int

    def __post_init__(self) -> None:
        for value, label in (
            (self.mission_id, "Mission id"),
            (self.child_job_id, "Child job id"),
            (self.stopped_mission_version, "Stopped mission version"),
            (self.stopped_fencing_token, "Stopped fencing token"),
        ):
            _optional_id(value, label)
        _bounded(
            self.command_id,
            "Child epoch handoff command id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )


@dataclass(frozen=True)
class AutonomousChildControlNotice:
    mission_id: int
    child_job_id: int
    command_id: str
    action: str
    mission_version: int
    fencing_token: int
    logical_attempt: int | None = None

    def __post_init__(self) -> None:
        _optional_id(self.mission_id, "Mission id")
        _optional_id(self.child_job_id, "Child job id")
        _bounded(
            self.command_id,
            "Child control command id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )
        if self.action not in AUTONOMOUS_CONTROL_ACTIONS:
            raise ValueError(f"Unsupported child control action: {self.action}")
        _optional_id(self.mission_version, "Mission version")
        _optional_id(self.fencing_token, "Mission fencing token")
        _optional_id(self.logical_attempt, "Retry logical attempt")


@dataclass(frozen=True)
class AutonomousRetrySettlementInput:
    scope: AutonomousMissionActivityScope
    child_job_id: int
    command_id: str

    def __post_init__(self) -> None:
        _optional_id(self.child_job_id, "Retry child job id")
        _bounded(
            self.command_id,
            "Retry settlement command id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )


@dataclass(frozen=True)
class AutonomousRetrySettlementResult:
    mission_id: int
    child_job_id: int
    retry_request_id: int
    failed_state_id: int
    ready_state_id: int
    next_logical_attempt: int
    summary: str
    occurred_at: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.mission_id, "Mission id"),
            (self.child_job_id, "Retry child job id"),
            (self.retry_request_id, "Retry request id"),
            (self.failed_state_id, "Failed backlog state id"),
            (self.ready_state_id, "Ready backlog state id"),
            (self.next_logical_attempt, "Next logical attempt"),
        ):
            _optional_id(value, label)
        _bounded(self.summary, "Retry settlement summary", AUTONOMOUS_SUMMARY_LIMIT)
        _bounded(
            self.occurred_at,
            "Retry settlement timestamp",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )


@dataclass(frozen=True)
class AutonomousPlanningCommand:
    """Identifier-only reference to an explicit, persisted human planning grant."""

    command_id: str
    manifest_id: int
    planning_authorization_id: int
    expected_mission_version: int
    actor: str
    requested_action: str = "ANALYZE"
    max_attempts_per_role: int = 2

    def __post_init__(self) -> None:
        _bounded(self.command_id, "Planning command id", AUTONOMOUS_IDENTIFIER_LIMIT)
        _optional_id(self.manifest_id, "Planning manifest id")
        _optional_id(
            self.planning_authorization_id, "Planning authorization id"
        )
        if int(self.expected_mission_version) <= 0:
            raise ValueError("Expected mission version must be positive")
        _bounded(self.actor, "Planning actor", AUTONOMOUS_IDENTIFIER_LIMIT)
        if self.requested_action not in AUTONOMOUS_PLANNING_ACTIONS:
            raise ValueError(
                f"Unsupported autonomous planning action: {self.requested_action}"
            )
        if not 1 <= int(self.max_attempts_per_role) <= 5:
            raise ValueError("Planning role attempts must be between one and five")


@dataclass(frozen=True)
class AutonomousPlanningActivityInput:
    scope: AutonomousMissionActivityScope
    command: AutonomousPlanningCommand


@dataclass(frozen=True)
class AutonomousPlanningActivityResult:
    mission_id: int
    mission_version: int
    phase: str
    disposition: str
    command_id: str
    requested_action: str
    manifest_id: int
    planning_authorization_id: int
    pipeline_run_id: int
    verification_id: int
    verification_status: str
    proposed_revision_id: int
    proposed_revision_digest: str
    parent_revision_id: int | None
    proposal_revision_count: int
    ready_for_approval: bool
    summary: str
    occurred_at: str
    duplicate: bool = False

    def __post_init__(self) -> None:
        for value, label in (
            (self.mission_id, "Mission id"),
            (self.mission_version, "Mission version"),
            (self.manifest_id, "Planning manifest id"),
            (self.planning_authorization_id, "Planning authorization id"),
            (self.pipeline_run_id, "Planning pipeline run id"),
            (self.verification_id, "Proposal verification id"),
            (self.proposed_revision_id, "Proposed revision id"),
        ):
            _optional_id(value, label)
        if self.phase not in AUTONOMOUS_PHASES:
            raise ValueError(f"Unsupported Autonomous Mission phase: {self.phase}")
        if self.disposition not in AUTONOMOUS_DISPOSITIONS:
            raise ValueError(
                f"Unsupported Autonomous Mission disposition: {self.disposition}"
            )
        _bounded(self.command_id, "Planning command id", AUTONOMOUS_IDENTIFIER_LIMIT)
        if self.requested_action not in AUTONOMOUS_PLANNING_ACTIONS:
            raise ValueError(
                f"Unsupported autonomous planning action: {self.requested_action}"
            )
        if self.verification_status not in {"READY", "BLOCKED"}:
            raise ValueError(
                f"Unsupported proposal verification status: {self.verification_status}"
            )
        if self.ready_for_approval != (self.verification_status == "READY"):
            raise ValueError("Proposal readiness conflicts with verification status")
        _sha256(self.proposed_revision_digest, "Proposed revision digest")
        _optional_id(self.parent_revision_id, "Parent revision id")
        if self.proposal_revision_count <= 0:
            raise ValueError("Proposal revision count must be positive")
        _bounded(self.summary, "Planning summary", AUTONOMOUS_SUMMARY_LIMIT)
        _bounded(
            self.occurred_at,
            "Planning occurrence timestamp",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )


@dataclass(frozen=True)
class AutonomousBacklogApprovalNotice:
    """Untrusted wake-up hint; all claimed values are non-authoritative."""

    notice_id: str
    claimed_approval_id: int | None = None
    claimed_revision_id: int | None = None
    claimed_revision_digest: str | None = None
    claimed_execution_epoch_id: int | None = None

    def __post_init__(self) -> None:
        _bounded(self.notice_id, "Approval notice id", AUTONOMOUS_IDENTIFIER_LIMIT)
        _optional_id(self.claimed_approval_id, "Claimed approval id")
        _optional_id(self.claimed_revision_id, "Claimed revision id")
        _sha256(self.claimed_revision_digest, "Claimed revision digest")
        _optional_id(
            self.claimed_execution_epoch_id, "Claimed execution epoch id"
        )


@dataclass(frozen=True)
class AutonomousApprovalRevalidationInput:
    scope: AutonomousMissionActivityScope
    notice: AutonomousBacklogApprovalNotice


@dataclass(frozen=True)
class AutonomousApprovalRevalidationResult:
    mission_id: int
    mission_version: int
    phase: str
    disposition: str
    approved: bool
    notice_matches_authority: bool
    reason: str
    occurred_at: str
    approval_id: int | None = None
    revision_id: int | None = None
    revision_digest: str | None = None
    execution_epoch_id: int | None = None
    authorization_id: int | None = None

    def __post_init__(self) -> None:
        _optional_id(self.mission_id, "Mission id")
        _optional_id(self.mission_version, "Mission version")
        if self.phase not in AUTONOMOUS_PHASES:
            raise ValueError(f"Unsupported Autonomous Mission phase: {self.phase}")
        if self.disposition not in AUTONOMOUS_DISPOSITIONS:
            raise ValueError(
                f"Unsupported Autonomous Mission disposition: {self.disposition}"
            )
        _bounded(self.reason, "Approval revalidation reason", AUTONOMOUS_SUMMARY_LIMIT)
        _optional_id(self.approval_id, "Approval id")
        _optional_id(self.revision_id, "Approved revision id")
        _sha256(self.revision_digest, "Approved revision digest")
        _optional_id(self.execution_epoch_id, "Execution epoch id")
        _optional_id(self.authorization_id, "Execution authorization id")
        _bounded(
            self.occurred_at,
            "Approval occurrence timestamp",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )
        if self.approved and any(
            value is None
            for value in (
                self.approval_id,
                self.revision_id,
                self.revision_digest,
                self.execution_epoch_id,
                self.authorization_id,
            )
        ):
            raise ValueError(
                "Approved revalidation requires complete authority identifiers"
            )


@dataclass(frozen=True)
class AutonomousExecutionPreparationInput:
    scope: AutonomousMissionActivityScope
    expected_mission_version: int
    expected_fencing_token: int
    approval_id: int
    authorization_id: int
    command_id: str

    def __post_init__(self) -> None:
        _optional_id(self.expected_mission_version, "Expected mission version")
        _optional_id(self.expected_fencing_token, "Expected fencing token")
        _optional_id(self.approval_id, "Backlog approval id")
        _optional_id(self.authorization_id, "Execution authorization id")
        _bounded(self.command_id, "Environment command id", AUTONOMOUS_IDENTIFIER_LIMIT)


@dataclass(frozen=True)
class AutonomousExecutionPreparationResult:
    mission_id: int
    mission_version: int
    phase: str
    disposition: str
    fencing_token: int
    environment_status: str
    summary: str
    occurred_at: str

    def __post_init__(self) -> None:
        _optional_id(self.mission_id, "Mission id")
        _optional_id(self.mission_version, "Mission version")
        _optional_id(self.fencing_token, "Mission fencing token")
        if self.phase not in AUTONOMOUS_PHASES:
            raise ValueError(f"Unsupported Autonomous Mission phase: {self.phase}")
        if self.disposition not in AUTONOMOUS_DISPOSITIONS:
            raise ValueError(
                f"Unsupported Autonomous Mission disposition: {self.disposition}"
            )
        if self.environment_status not in AUTONOMOUS_ENVIRONMENT_STATUSES:
            raise ValueError(
                f"Unsupported environment status: {self.environment_status}"
            )
        _bounded(self.summary, "Environment summary", AUTONOMOUS_SUMMARY_LIMIT)
        _bounded(
            self.occurred_at,
            "Environment occurrence timestamp",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )


@dataclass(frozen=True)
class AutonomousChildPreparationInput:
    scope: AutonomousMissionActivityScope
    expected_mission_version: int
    expected_fencing_token: int
    execution_mode: str
    workflow_definition_id: str
    fast_activity_timeout_seconds: int
    llm_activity_timeout_seconds: int
    heartbeat_timeout_seconds: int
    max_repair_iterations: int
    command_id: str

    def __post_init__(self) -> None:
        _optional_id(self.expected_mission_version, "Expected mission version")
        _optional_id(self.expected_fencing_token, "Expected fencing token")
        if self.execution_mode not in {"simulation", "live"}:
            raise ValueError("Child execution mode must be simulation or live")
        _bounded(
            self.workflow_definition_id,
            "Child workflow definition id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )
        for value, label in (
            (self.fast_activity_timeout_seconds, "Fast activity timeout"),
            (self.llm_activity_timeout_seconds, "LLM activity timeout"),
            (self.heartbeat_timeout_seconds, "Heartbeat timeout"),
        ):
            if int(value) <= 0:
                raise ValueError(f"{label} must be positive")
        if self.heartbeat_timeout_seconds >= self.llm_activity_timeout_seconds:
            raise ValueError("Heartbeat timeout must be shorter than LLM timeout")
        if not 0 <= int(self.max_repair_iterations) <= 100:
            raise ValueError("Repair iterations must be between zero and 100")
        _bounded(
            self.command_id,
            "Child preparation command id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )


@dataclass(frozen=True)
class AutonomousChildPreparationResult:
    mission_id: int
    mission_version: int
    completed_items: int
    total_items: int
    all_complete: bool
    blocked: bool
    summary: str
    occurred_at: str
    child_job_id: int | None = None
    child_workflow_id: str | None = None
    stable_item_id: str | None = None
    role: str | None = None
    model: str | None = None
    job: AgentFactoryJobInput | None = None

    def __post_init__(self) -> None:
        _optional_id(self.mission_id, "Mission id")
        _optional_id(self.mission_version, "Mission version")
        if self.completed_items < 0 or self.total_items < 0:
            raise ValueError("Mission progress counters cannot be negative")
        if self.completed_items > self.total_items:
            raise ValueError("Completed item count cannot exceed total item count")
        if self.all_complete and self.blocked:
            raise ValueError("Child preparation cannot be complete and blocked")
        _bounded(self.summary, "Child preparation summary", AUTONOMOUS_SUMMARY_LIMIT)
        _bounded(
            self.occurred_at,
            "Child preparation timestamp",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )
        optional_ids = (
            self.child_job_id,
            self.child_workflow_id,
            self.stable_item_id,
            self.role,
            self.model,
            self.job,
        )
        if self.job is None:
            if any(value is not None for value in optional_ids[:-1]):
                raise ValueError("Non-runnable preparation cannot identify a child")
        elif any(value is None for value in optional_ids[:-1]):
            raise ValueError("Runnable preparation requires complete child identity")
        if self.child_job_id is not None:
            _optional_id(self.child_job_id, "Child job id")
        for value, label in (
            (self.child_workflow_id, "Child Workflow id"),
            (self.stable_item_id, "Stable work item id"),
            (self.role, "Current role"),
            (self.model, "Current model"),
        ):
            _optional_bounded(value, label)


@dataclass(frozen=True)
class AutonomousChildReconciliationInput:
    scope: AutonomousMissionActivityScope
    child_job_id: int
    expected_mission_version: int
    expected_fencing_token: int
    command_id: str

    def __post_init__(self) -> None:
        _optional_id(self.child_job_id, "Child job id")
        _optional_id(self.expected_mission_version, "Expected mission version")
        _optional_id(self.expected_fencing_token, "Expected fencing token")
        _bounded(
            self.command_id,
            "Child reconciliation command id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )


@dataclass(frozen=True)
class AutonomousChildReconciliationResult:
    mission_id: int
    mission_version: int
    child_job_id: int
    completion_id: int
    checkpoint_id: int
    stable_item_id: str
    completed_items: int
    total_items: int
    summary: str
    occurred_at: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.mission_id, "Mission id"),
            (self.mission_version, "Mission version"),
            (self.child_job_id, "Child job id"),
            (self.completion_id, "Child completion id"),
            (self.checkpoint_id, "Mission checkpoint id"),
        ):
            _optional_id(value, label)
        _bounded(
            self.stable_item_id,
            "Stable work item id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )
        if self.completed_items < 0 or self.total_items < 0:
            raise ValueError("Mission progress counters cannot be negative")
        if self.completed_items > self.total_items:
            raise ValueError("Completed item count cannot exceed total item count")
        _bounded(self.summary, "Reconciliation summary", AUTONOMOUS_SUMMARY_LIMIT)
        _bounded(
            self.occurred_at,
            "Reconciliation timestamp",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )


@dataclass(frozen=True)
class AutonomousMissionCompletionInput:
    scope: AutonomousMissionActivityScope
    expected_mission_version: int
    expected_fencing_token: int
    command_id: str

    def __post_init__(self) -> None:
        _optional_id(self.expected_mission_version, "Expected mission version")
        _optional_id(self.expected_fencing_token, "Expected fencing token")
        _bounded(
            self.command_id,
            "Mission completion command id",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )


@dataclass(frozen=True)
class AutonomousMissionCompletionResult:
    mission_id: int
    mission_version: int
    phase: str
    disposition: str
    completed_items: int
    total_items: int
    summary: str
    occurred_at: str

    def __post_init__(self) -> None:
        _optional_id(self.mission_id, "Mission id")
        _optional_id(self.mission_version, "Mission version")
        if self.phase not in AUTONOMOUS_PHASES:
            raise ValueError(f"Unsupported Autonomous Mission phase: {self.phase}")
        if self.disposition not in AUTONOMOUS_DISPOSITIONS:
            raise ValueError(
                f"Unsupported Autonomous Mission disposition: {self.disposition}"
            )
        if self.completed_items < 0 or self.completed_items != self.total_items:
            raise ValueError("Completed mission requires its complete item count")
        _bounded(self.summary, "Mission completion summary", AUTONOMOUS_SUMMARY_LIMIT)
        _bounded(
            self.occurred_at,
            "Mission completion timestamp",
            AUTONOMOUS_IDENTIFIER_LIMIT,
        )


@dataclass
class DemoWorkflowInput:
    workspace: str
    marker: str
    command: list[str]
    fail_attempts: int = 0
    wait_before_command: bool = False
    activity_timeout_seconds: int = 60
    heartbeat_timeout_seconds: int = 10
