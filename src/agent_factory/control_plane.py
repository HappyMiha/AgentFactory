"""Authenticated human control-plane action and agent lifecycle boundary (AF-030)."""
from __future__ import annotations

import json
import secrets
from typing import Any

from .storage import SQLiteStorage

ROLE_ACTIONS = {
    "mission_owner": {"approve", "reject", "pause", "resume", "cancel", "recompose", "release", "emergency_stop"},
    "operations_owner": {"pause", "resume", "cancel", "emergency_stop", "enable", "drain", "quarantine", "replace", "retire"},
    "security_reviewer": {"quarantine", "release"},
}

class HumanControlPlaneService:
    def __init__(self, storage: SQLiteStorage): self.storage = storage

    def act(self, *, tenant_id: str, actor: str, role: str, action: str, target_type: str, target_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not all(value.strip() for value in (tenant_id, actor, role, action, target_type, target_id)): raise ValueError("authenticated action scope is required")
        if action not in ROLE_ACTIONS.get(role, set()): raise PermissionError("role is not authorized for this action")
        if action == "retire" and (payload or {}).get("irreversible") is not True: raise PermissionError("irreversible retirement requires explicit confirmation")
        identity = f"control-action-{secrets.token_hex(12)}"; body = payload or {}
        self.storage.db.execute("INSERT INTO control_plane_actions(identity,tenant_id,actor,role,action,target_type,target_id,payload_json,outcome) VALUES(?,?,?,?,?,?,?,?,?)", (identity, tenant_id, actor, role, action, target_type, target_id, json.dumps(body, sort_keys=True), "accepted")); self.storage.db.commit()
        self.storage._event("control_plane.action", target_type, target_id, {"tenant_id": tenant_id, "actor": actor, "role": role, "action": action, "control_action": identity}); self.storage.db.commit()
        return {"identity": identity, "tenant_id": tenant_id, "actor": actor, "role": role, "action": action, "target_type": target_type, "target_id": target_id, "outcome": "accepted"}

    def list_actions(self, tenant_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.storage.db.execute("SELECT * FROM control_plane_actions WHERE tenant_id=? ORDER BY id", (tenant_id,))]
