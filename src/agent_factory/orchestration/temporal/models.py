from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


AUTONOMOUS_MISSION_WORKFLOW_SCHEMA_VERSION = 1
AUTONOMOUS_SUMMARY_LIMIT = 512
AUTONOMOUS_IDENTIFIER_LIMIT = 256
AUTONOMOUS_PATH_LIMIT = 2048
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


@dataclass
class StageActivityInput:
    job: AgentFactoryJobInput
    stage: dict[str, Any]
    ordinal: int
    repair_iteration: int = 0
    failure_summary: str = ""


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
    active_backlog_revision_id: int | None = None
    active_backlog_revision_digest: str | None = None
    active_execution_epoch_id: int | None = None
    current_checkpoint_id: int | None = None
    current_work_item_stable_id: str | None = None
    current_role: str | None = None
    current_model: str | None = None
    completed_items: int = 0
    total_items: int = 0
    environment_status: str = "NOT_STARTED"
    last_activity: str = "Mission workflow created"
    last_activity_at: str = ""
    schema_version: int = AUTONOMOUS_MISSION_WORKFLOW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AUTONOMOUS_MISSION_WORKFLOW_SCHEMA_VERSION:
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
        if (self.chain_sequence == 1) != (previous_run_id is None):
            raise ValueError(
                "Only the first Temporal chain entry omits previous_run_id"
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
        _optional_id(self.active_execution_epoch_id, "Active execution epoch id")
        _optional_id(self.current_checkpoint_id, "Current checkpoint id")
        _optional_bounded(
            self.current_work_item_stable_id, "Current work item stable id"
        )
        _optional_bounded(self.current_role, "Current role")
        _optional_bounded(self.current_model, "Current model")
        if self.completed_items < 0 or self.total_items < 0:
            raise ValueError("Mission progress counters cannot be negative")
        if self.completed_items > self.total_items:
            raise ValueError("Completed item count cannot exceed total item count")
        if self.environment_status not in AUTONOMOUS_ENVIRONMENT_STATUSES:
            raise ValueError(
                f"Unsupported environment status: {self.environment_status}"
            )
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
    schema_version: int = AUTONOMOUS_MISSION_WORKFLOW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AUTONOMOUS_MISSION_WORKFLOW_SCHEMA_VERSION:
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
        if self.carry_over is not None:
            carry = self.carry_over
            if (
                carry.mission_id != self.mission_id
                or carry.mission_version != self.mission_version
                or carry.phase != self.phase
                or carry.disposition != self.disposition
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
    active_backlog_revision_id: int | None = None
    active_backlog_revision_digest: str | None = None
    active_execution_epoch_id: int | None = None
    current_checkpoint_id: int | None = None
    current_work_item_stable_id: str | None = None
    current_role: str | None = None
    current_model: str | None = None
    completed_items: int = 0
    total_items: int = 0
    environment_status: str = "NOT_STARTED"
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
            active_backlog_revision_id=carry.active_backlog_revision_id,
            active_backlog_revision_digest=carry.active_backlog_revision_digest,
            active_execution_epoch_id=carry.active_execution_epoch_id,
            current_checkpoint_id=carry.current_checkpoint_id,
            current_work_item_stable_id=carry.current_work_item_stable_id,
            current_role=carry.current_role,
            current_model=carry.current_model,
            completed_items=carry.completed_items,
            total_items=carry.total_items,
            environment_status=carry.environment_status,
            last_activity=carry.last_activity,
            last_activity_at=carry.last_activity_at or started_at,
            started_at=started_at,
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
            self.workflow_status, "Workflow status", AUTONOMOUS_IDENTIFIER_LIMIT
        )
        if self.started_at:
            _bounded(
                self.started_at, "Workflow start timestamp", AUTONOMOUS_IDENTIFIER_LIMIT
            )

    def to_carry_over(self) -> AutonomousMissionCarryOver:
        return AutonomousMissionCarryOver(
            mission_id=self.mission_id,
            mission_version=self.mission_version,
            phase=self.phase,
            disposition=self.disposition,
            chain_sequence=self.chain_sequence + 1,
            previous_run_id=self.temporal_run_id,
            active_backlog_revision_id=self.active_backlog_revision_id,
            active_backlog_revision_digest=self.active_backlog_revision_digest,
            active_execution_epoch_id=self.active_execution_epoch_id,
            current_checkpoint_id=self.current_checkpoint_id,
            current_work_item_stable_id=self.current_work_item_stable_id,
            current_role=self.current_role,
            current_model=self.current_model,
            completed_items=self.completed_items,
            total_items=self.total_items,
            environment_status=self.environment_status,
            last_activity=self.last_activity,
            last_activity_at=self.last_activity_at,
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
