from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum

from .storage import SQLiteStorage, ScopedApprovalExpiredError


def canonical_policy_request(request: dict[str, object]) -> dict[str, object]:
    """Validate one exact request shape without changing legacy canonical bytes."""
    required = {"mission_id", "task_id", "run_id", "stage_id", "worker_id",
                "runtime_id", "worktree_id", "permissions"}
    if not isinstance(request, dict) or set(request) not in (required, required | {"effect_digest"}):
        raise ValueError("Policy request requires exact fields and optional effect_digest")
    value = dict(request)
    for key in ("mission_id", "task_id", "run_id"):
        item = value[key]
        if key == "run_id" and item is None:
            continue
        if type(item) is not int or item <= 0:
            raise ValueError("Policy scope identifiers must be positive integers")
    for key in ("stage_id", "worker_id", "runtime_id", "worktree_id"):
        item = value[key]
        if key == "worktree_id" and item is None:
            continue
        if not isinstance(item, str) or not item.strip() or not item.isprintable():
            raise ValueError("Policy scope names must be nonempty printable strings")
    permissions = value["permissions"]
    if (not isinstance(permissions, (list, tuple))
            or any(not isinstance(item, str) or not item.strip() or not item.isprintable()
                   for item in permissions)):
        raise ValueError("Policy permissions must be a list or tuple of names")
    value["permissions"] = sorted(set(permissions))
    if "effect_digest" in value and (
        not isinstance(value["effect_digest"], str)
        or re.fullmatch(r"[a-f0-9]{64}", value["effect_digest"]) is None
    ):
        raise ValueError("effect_digest must be a lowercase SHA-256 digest")
    return value


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
    effect_digest: str | None = None

    def __post_init__(self):
        self.canonical()

    def canonical(self) -> dict[str, object]:
        value = asdict(self)
        if self.effect_digest is None:
            del value["effect_digest"]
        return canonical_policy_request(value)

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
        with self.storage._policy_transaction():
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
        self,
        request: PolicyRequest,
        *,
        approval_id: int | None = None,
        assignment_id: int | None = None,
        attempt_id: int | None = None,
    ) -> PolicyDecision:
        expired = None
        with self.storage._policy_transaction():
            decision = self.evaluate(request)
            if decision.outcome is not PolicyOutcome.REQUIRE_APPROVAL or approval_id is None:
                return decision
            try:
                self.storage.consume_scoped_approval(
                    approval_id,
                    request=request.canonical(),
                    request_digest=request.digest,
                    assignment_id=assignment_id,
                    attempt_id=attempt_id,
                )
            except ScopedApprovalExpiredError as error:
                # Retain the legacy standalone expiry transition. With a caller
                # transaction, the caller still owns its final commit/rollback.
                expired = error
            if expired is None:
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
                decision = PolicyDecision(
                    outcome=PolicyOutcome.ALLOW,
                    reason=reason,
                    policy_version=int(state["version"]),
                    request_digest=request.digest,
                    approval_id=approval_id,
                )
        if expired is not None:
            raise expired
        return decision
