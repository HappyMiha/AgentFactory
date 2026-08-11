from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum

from .storage import SQLiteStorage


class PolicyOutcome(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class PolicyRequest:
    mission_id: int
    task_id: int
    run_id: int | None
    stage_id: str
    worker_id: str
    runtime_id: str
    worktree_id: str | None
    permissions: tuple[str, ...]

    def canonical(self) -> dict[str, object]:
        value = asdict(self)
        value["permissions"] = sorted(set(self.permissions))
        return value

    @property
    def digest(self) -> str:
        payload = json.dumps(
            self.canonical(), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PolicyDecision:
    outcome: PolicyOutcome
    reason: str
    policy_version: int
    request_digest: str
    approval_id: int | None = None


class ControlPlanePolicy:
    """Authoritative policy evaluator; runtimes may request but never override it."""

    DENIED_PERMISSIONS = frozenset(
        {"bypass_policy", "final_approval", "merge", "push", "close_issue", "read_secrets"}
    )
    MUTABLE_PERMISSIONS = frozenset(
        {
            "create_artifact",
            "execute_provider",
            "git_write",
            "network",
            "tool_use",
            "worktree_write",
            "write_project",
        }
    )

    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        state = self.storage.policy_state()
        permissions = frozenset(request.permissions)
        if state["emergency_stop"]:
            outcome = PolicyOutcome.DENY
            reason = f"Emergency stop is active: {state['reason']}"
        elif forbidden := sorted(permissions & self.DENIED_PERMISSIONS):
            outcome = PolicyOutcome.DENY
            reason = f"Forbidden permissions requested: {', '.join(forbidden)}"
        elif permissions & self.MUTABLE_PERMISSIONS:
            outcome = PolicyOutcome.REQUIRE_APPROVAL
            reason = "Mutable execution requires an exact, one-use Control Plane approval"
        else:
            outcome = PolicyOutcome.ALLOW
            reason = "Read-only request is allowed by the current policy"
        self.storage.record_policy_decision(
            request=request.canonical(),
            request_digest=request.digest,
            outcome=outcome.value,
            reason=reason,
            policy_version=int(state["version"]),
        )
        return PolicyDecision(
            outcome=outcome,
            reason=reason,
            policy_version=int(state["version"]),
            request_digest=request.digest,
            approval_id=None,
        )

    def authorize(
        self, request: PolicyRequest, *, approval_id: int | None = None
    ) -> PolicyDecision:
        decision = self.evaluate(request)
        if decision.outcome is not PolicyOutcome.REQUIRE_APPROVAL:
            return decision
        if approval_id is None:
            return decision
        self.storage.consume_scoped_approval(
            approval_id, request=request.canonical(), request_digest=request.digest
        )
        state = self.storage.policy_state()
        reason = "Exact one-use Control Plane approval consumed"
        self.storage.record_policy_decision(
            request=request.canonical(),
            request_digest=request.digest,
            outcome=PolicyOutcome.ALLOW.value,
            reason=reason,
            policy_version=int(state["version"]),
            approval_id=approval_id,
        )
        return PolicyDecision(
            outcome=PolicyOutcome.ALLOW,
            reason=reason,
            policy_version=int(state["version"]),
            request_digest=request.digest,
            approval_id=approval_id,
        )
