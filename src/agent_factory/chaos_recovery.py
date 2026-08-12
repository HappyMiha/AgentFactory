"""Deterministic clustered fault-boundary and restore evidence (AF-028)."""
from __future__ import annotations

import json
import secrets
import tempfile
from pathlib import Path
from typing import Any

from .local_recovery import LocalRecoveryService
from .storage import SQLiteStorage

BOUNDARIES = ("before_commit", "after_commit", "before_approval", "after_approval", "before_external_operation", "after_external_operation", "host_termination", "network_partition", "queue_restart", "storage_restart")

class ChaosRecoveryService:
    def __init__(self, storage: SQLiteStorage): self.storage = storage

    def run(self, *, profile: str = "clustered", fault_boundary: str, identities: dict[str, Any],
            restore: dict[str, Any] | None = None) -> dict[str, Any]:
        if fault_boundary not in BOUNDARIES: raise ValueError("unknown fault boundary")
        required = {"stage", "lease", "runtime_session", "context", "worktree", "budget", "approval", "external_operation"}
        restore = restore or LocalRecoveryService(self.storage).verify_restore()
        continuity = required <= set(identities) and all(identities[key] is not None for key in required)
        restore_ok = bool(restore.get("ok")) and bool(restore.get("audit"))
        verdict = "passed" if continuity and restore_ok else "failed"; identity = f"chaos-recovery-{secrets.token_hex(12)}"
        self.storage.db.execute("INSERT INTO chaos_recovery_runs(identity,profile,fault_boundary,identities_json,restore_json,verdict) VALUES(?,?,?,?,?,?)", (identity, profile, fault_boundary, json.dumps(identities, sort_keys=True), json.dumps(restore, sort_keys=True), verdict)); self.storage.db.commit()
        self.storage._event("chaos.recovery", "chaos_recovery_run", identity, {"profile": profile, "fault_boundary": fault_boundary, "verdict": verdict})
        self.storage.db.commit()
        return {"identity": identity, "profile": profile, "fault_boundary": fault_boundary, "verdict": verdict, "identities": identities, "restore": restore}

    def restore_exercise(self) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "restore.db"; self.storage.online_backup(backup)
            restored = SQLiteStorage(backup); result = LocalRecoveryService(restored).verify_restore(); restored.close()
        return {"verified": bool(result["ok"]), "evidence": result}
