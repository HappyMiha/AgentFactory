from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import re
from typing import Any


class Status(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    APPROVED = "approved"
    REJECTED = "rejected"


class ExecutionLocation(StrEnum):
    LOCAL = "LOCAL"
    REMOTE = "REMOTE"


@dataclass(frozen=True)
class ProviderCapabilities:
    """Provider-neutral inference and model-lifecycle capability declaration."""

    execution_location: ExecutionLocation = ExecutionLocation.REMOTE
    location_declared: bool = False
    text_generation: bool = False
    structured_output: bool = False
    tool_calls: bool = False
    model_listing: bool = False
    model_switching: bool = False
    model_load_release: bool = False
    # None retains the provider-neutral contract for programmatically supplied
    # adapters. Configured CLI profiles always declare an explicit role set.
    profile_roles: tuple[str, ...] | None = None
    profile_models: tuple[str, ...] = ()
    profile_execution_enabled: bool = False

    @staticmethod
    def _flag(document: dict[str, Any], key: str) -> bool:
        value = document.get(key, False)
        if not isinstance(value, bool):
            raise TypeError(f"Provider capability {key!r} must be boolean")
        return value

    @classmethod
    def from_config(cls, value: dict[str, Any]) -> ProviderCapabilities:
        raw_location = value.get("execution_location")
        declared = raw_location is not None
        location = (
            ExecutionLocation(str(raw_location).strip().upper())
            if declared
            else ExecutionLocation.REMOTE
        )
        document = value.get("capabilities", {})
        if not isinstance(document, dict):
            raise TypeError("Provider capabilities must be an object")
        profile_roles = None
        profile_models = ()
        if value.get("type") in {"cli", "health_only_cli"} or "allowed_roles" in value:
            roles = value.get("allowed_roles", [])
            if not isinstance(roles, list) or any(not isinstance(role, str) or not role.strip() for role in roles):
                raise TypeError("Provider allowed_roles must be a list of nonempty role IDs")
            profile_roles = tuple(roles)
            namespace = value.get("model_namespace", "")
            models = value.get("model_ids", [])
            args = value.get("args", [])
            if (isinstance(namespace, str) and re.fullmatch(r"[a-z][a-z0-9_-]*", namespace)
                    and isinstance(models, list) and isinstance(args, list) and all(isinstance(arg, str) for arg in args) and args.count("{model}") == 1
                    and all(isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model) for model in models)):
                profile_models = tuple(f"{namespace}:{model}" for model in models)
        result = cls(
            profile_roles=profile_roles,
            profile_models=profile_models,
            profile_execution_enabled=value.get("type") != "health_only_cli" and value.get("enabled", True) is True and value.get("allow_execution") is True,
            execution_location=location,
            location_declared=declared,
            text_generation=cls._flag(document, "text_generation"),
            structured_output=cls._flag(document, "structured_output"),
            tool_calls=cls._flag(document, "tool_calls"),
            model_listing=cls._flag(document, "model_listing"),
            model_switching=cls._flag(document, "model_switching"),
            model_load_release=cls._flag(document, "model_load_release"),
        )
        if result.model_switching and not result.model_listing:
            raise ValueError("Model switching requires model-listing capability")
        if result.model_load_release and not result.model_listing:
            raise ValueError("Model lifecycle control requires model-listing capability")
        return result

    @property
    def autonomous_local_eligible(self) -> bool:
        return (
            self.location_declared
            and self.execution_location is ExecutionLocation.LOCAL
            and self.text_generation
        )

    def role_model_error(self, role: str, model: str) -> str | None:
        """Check configured compatibility, not live model quality or tool rights."""
        if self.profile_roles is None:
            return None  # A programmatic adapter owns its separate role contract.
        if not self.profile_execution_enabled or not self.text_generation:
            return "Provider profile does not enable text inference"
        if role not in self.profile_roles:
            alternatives = ", ".join(self.profile_roles) or "none"
            return f"Provider profile does not allow role {role!r}; configured roles: {alternatives}"
        if model not in self.profile_models:
            alternatives = ", ".join(self.profile_models) or "none"
            return f"Provider profile does not bind model {model!r}; configured models: {alternatives}"
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_location": self.execution_location.value,
            "location_declared": self.location_declared,
            "text_generation": self.text_generation,
            "structured_output": self.structured_output,
            "tool_calls": self.tool_calls,
            "model_listing": self.model_listing,
            "model_switching": self.model_switching,
            "model_load_release": self.model_load_release,
            "autonomous_local_eligible": self.autonomous_local_eligible,
            "profile_roles": list(self.profile_roles) if self.profile_roles is not None else None,
            "profile_models": list(self.profile_models),
            "profile_execution_enabled": self.profile_execution_enabled,
        }


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
    execution_location: ExecutionLocation = ExecutionLocation.REMOTE
    capabilities: ProviderCapabilities = field(default_factory=ProviderCapabilities)


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


class ExecutionAuthorizationMode(StrEnum):
    """Non-standard provider authority issued by a durable mission resolver."""

    AUTONOMOUS_LOCAL = "AUTONOMOUS_LOCAL"
    BOUNDED_LOCAL_PLANNING = "BOUNDED_LOCAL_PLANNING"


@dataclass(frozen=True)
class ProviderExecutionAuthorization:
    """Typed, evidence-bound provider authority; never a global gate bypass."""

    decision_id: int
    authorization_id: int
    mode: ExecutionAuthorizationMode
    operation: str
    provider: str
    agent_id: str
    task_id: int
    mission_id: int
    backlog_revision_id: int | None
    execution_epoch_id: int | None
    permissions: tuple[str, ...]
    tool_profile: str
    evidence_digest: str
    authorized_by: str
    planning_request_id: str | None = None

    @property
    def gate_id(self) -> int:
        """Compatibility metadata only; this is not a standard one-use gate id."""

        return self.decision_id

    @property
    def approved_by(self) -> str:
        return self.authorized_by
