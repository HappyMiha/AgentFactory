from __future__ import annotations

from collections.abc import Mapping


TRANSITIONS: Mapping[str, Mapping[str, frozenset[str]]] = {
    "work_item": {
        "pending": frozenset({"running", "failed"}),
        "running": frozenset({"completed", "failed"}),
        "completed": frozenset({"approved", "rejected"}),
        "failed": frozenset({"pending"}),
    },
    "run": {
        "running": frozenset({"awaiting_approval", "failed"}),
        "awaiting_approval": frozenset({"approved", "rejected", "failed"}),
    },
    "stage": {
        "pending": frozenset({"running", "failed"}),
        "running": frozenset({"waiting_approval", "succeeded", "failed"}),
        "waiting_approval": frozenset({"running", "succeeded", "failed"}),
        "failed": frozenset({"pending"}),
    },
    "assignment": {
        "pending": frozenset({"active", "cancelled"}),
        "active": frozenset({"suspended", "succeeded", "failed", "cancelled"}),
        "suspended": frozenset({"active", "failed", "cancelled"}),
    },
    "worker_session": {
        "starting": frozenset({"running", "failed", "cancelled"}),
        "running": frozenset({"suspended", "succeeded", "failed", "cancelled"}),
        "suspended": frozenset({"running", "failed", "cancelled"}),
    },
    "attempt": {
        "claimed": frozenset({"running", "succeeded", "failed", "abandoned", "cancelled"}),
        "running": frozenset({"succeeded", "failed", "abandoned", "cancelled"}),
    },
    "lease": {
        "active": frozenset({"expired", "released", "revoked"}),
    },
    "worktree": {
        "provisioning": frozenset({"ready", "missing", "cleaned"}),
        "ready": frozenset({"dirty", "retained", "missing"}),
        "dirty": frozenset({"ready", "retained", "missing"}),
        "retained": frozenset({"cleaned", "missing"}),
        "missing": frozenset({"provisioning", "cleaned"}),
    },
    "artifact": {
        "pending": frozenset({"approved", "rejected"}),
    },
}


def ensure_transition(entity: str, source: str, target: str) -> None:
    """Reject lifecycle changes that are not part of the versioned domain model."""

    if target not in TRANSITIONS.get(entity, {}).get(source, frozenset()):
        raise ValueError(f"Invalid {entity} transition: {source} -> {target}")
