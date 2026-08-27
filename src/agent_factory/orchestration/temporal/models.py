from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class FailureClass(StrEnum):
    TOKEN_EXHAUSTED = "TOKEN_EXHAUSTED"
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


@dataclass
class DemoWorkflowInput:
    workspace: str
    marker: str
    command: list[str]
    fail_attempts: int = 0
    wait_before_command: bool = False
    activity_timeout_seconds: int = 60
    heartbeat_timeout_seconds: int = 10
