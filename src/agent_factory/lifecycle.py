from __future__ import annotations

from collections.abc import Mapping


TRANSITIONS: Mapping[str, Mapping[str, frozenset[str]]] = {
    "autonomous_mission_phase": {
        "DRAFT": frozenset({"SPECIFICATION_ANALYSIS"}),
        "SPECIFICATION_ANALYSIS": frozenset({"BACKLOG_GENERATION"}),
        "BACKLOG_GENERATION": frozenset(
            {"SPECIFICATION_ANALYSIS", "WAITING_FOR_BACKLOG_APPROVAL"}
        ),
        "WAITING_FOR_BACKLOG_APPROVAL": frozenset(
            {"BACKLOG_GENERATION", "APPROVED"}
        ),
        "APPROVED": frozenset(
            {"ENVIRONMENT_DISCOVERY", "WAITING_FOR_BACKLOG_APPROVAL"}
        ),
        "ENVIRONMENT_DISCOVERY": frozenset(
            {"ENVIRONMENT_BOOTSTRAP", "WAITING_FOR_BACKLOG_APPROVAL"}
        ),
        "ENVIRONMENT_BOOTSTRAP": frozenset(
            {"DEVELOPMENT", "WAITING_FOR_BACKLOG_APPROVAL"}
        ),
        "DEVELOPMENT": frozenset(
            {"VALIDATION", "FINAL_VALIDATION", "WAITING_FOR_BACKLOG_APPROVAL"}
        ),
        "VALIDATION": frozenset(
            {"DEVELOPMENT", "INTEGRATION", "WAITING_FOR_BACKLOG_APPROVAL"}
        ),
        "INTEGRATION": frozenset(
            {"DEVELOPMENT", "FINAL_VALIDATION", "WAITING_FOR_BACKLOG_APPROVAL"}
        ),
        "FINAL_VALIDATION": frozenset(
            {"DEVELOPMENT", "COMPLETED", "WAITING_FOR_BACKLOG_APPROVAL"}
        ),
        "COMPLETED": frozenset(),
    },
    "autonomous_mission_disposition": {
        "RUNNING": frozenset(
            {
                "PAUSED",
                "STOPPED",
                "NEEDS_ATTENTION",
                "NEEDS_HUMAN_ACTION",
                "REPLANNING",
                "RECOVERING",
                "FAILED",
            }
        ),
        "PAUSED": frozenset({"RUNNING", "STOPPED", "FAILED"}),
        "STOPPED": frozenset({"RUNNING", "RECOVERING", "FAILED"}),
        "NEEDS_ATTENTION": frozenset(
            {"RUNNING", "STOPPED", "REPLANNING", "FAILED"}
        ),
        "NEEDS_HUMAN_ACTION": frozenset(
            {"RUNNING", "STOPPED", "RECOVERING", "FAILED"}
        ),
        "REPLANNING": frozenset(
            {"RUNNING", "PAUSED", "STOPPED", "NEEDS_ATTENTION", "FAILED"}
        ),
        "RECOVERING": frozenset(
            {
                "RUNNING",
                "STOPPED",
                "NEEDS_ATTENTION",
                "NEEDS_HUMAN_ACTION",
                "FAILED",
            }
        ),
        "FAILED": frozenset({"RECOVERING", "STOPPED"}),
    },
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
