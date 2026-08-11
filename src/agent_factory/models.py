from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class Budget:
    max_tokens: int = 4000
    max_seconds: int = 120
    max_cost_usd: float = 0.0


@dataclass
class WorkItem:
    title: str
    description: str
    project_id: int
    dependencies: list[int] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    expected_outputs: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=lambda: ["read_project", "create_artifact"])
    budget: Budget = field(default_factory=Budget)
    status: Status = Status.PENDING
    artifacts: list[int] = field(default_factory=list)
    id: int | None = None
    kind: str = "task"
    github_number: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True)
class AssignmentLease:
    task_id: int
    assignment_id: int
    lease_id: int
    worker: str
    runtime: str
    fencing_token: int
    expires_at: str
    conflict_domains: tuple[str, ...]


@dataclass
class Agent:
    id: str
    name: str
    role: str
    enabled: bool
    provider: str
    instructions: str
    permissions: list[str] = field(default_factory=list)
    model: str = ""

    @property
    def model_identity(self) -> str:
        """Stable identity used to prevent a model from reviewing its own work."""

        configured = self.model.strip()
        return configured if configured else f"provider:{self.provider}"


@dataclass
class AgentRole:
    id: str
    purpose: str
    can_write_code: bool = False
    can_close_work: bool = False


@dataclass
class ProviderConfig:
    id: str
    type: str
    executable: str
    enabled: bool = True


@dataclass
class ReviewResult:
    reviewer: str
    verdict: str
    evidence: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)


@dataclass
class PolicyAlignmentResult:
    aligned: bool
    progress_score: int
    rationale: str
    policy_reference: str


@dataclass
class Artifact:
    kind: str
    path: str
    producer: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApprovalGate:
    run_id: int
    status: str = "pending"
    decision_note: str = ""


@dataclass
class ProviderResult:
    ok: bool
    content: str = ""
    provider: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionApproval:
    gate_id: int
    provider: str
    agent_id: str
    task_id: int
    approved_by: str = "Human"
    run_id: int | None = None
    stage_id: str | None = None
    runtime_id: str | None = None
    worktree_id: str | None = None
    permissions: tuple[str, ...] = ()
    request_digest: str | None = None
