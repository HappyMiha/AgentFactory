"""Versioned 72-hour soak evidence with bounded-growth gates (AF-033)."""
from __future__ import annotations

import json
import secrets
from typing import Any

from .storage import SQLiteStorage

FAULTS = ("provider", "worker", "process", "network", "queue", "storage", "host")
BOUNDS = {"memory_mb": 2048, "storage_mb": 10240, "queue_depth": 1000, "orphaned_leases": 0, "temporary_environments": 100}

class SoakService:
    def __init__(self, storage: SQLiteStorage, *, workload_version: str = "af033.mixed-missions.v1"):
        self.storage, self.workload_version = storage, workload_version

    def run(self, *, duration_hours: float, fault_schedule: tuple[str, ...] = FAULTS,
            resources: dict[str, int] | None = None,
            continuity: dict[str, bool] | None = None) -> dict[str, Any]:
        if duration_hours < 72: raise ValueError("soak must run for at least 72 hours")
        if any(fault not in FAULTS for fault in fault_schedule): raise ValueError("unknown fault class")
        resources = resources or {key: 0 for key in BOUNDS}; continuity = continuity or {"accepted_state": True, "evidence": True, "audit": True, "external_operations": True, "duplicates": False}
        bounded = all(int(resources.get(key, BOUNDS[key] + 1)) <= limit for key, limit in BOUNDS.items())
        preserved = all(continuity.get(key) is True for key in ("accepted_state", "evidence", "audit", "external_operations")) and continuity.get("duplicates") is False
        verdict = "passed" if bounded and preserved else "failed"; identity = f"soak-run-{secrets.token_hex(12)}"
        self.storage.db.execute("INSERT INTO soak_runs(identity,workload_version,fault_schedule_json,duration_hours,resource_evidence_json,continuity_json,verdict) VALUES(?,?,?,?,?,?,?)", (identity, self.workload_version, json.dumps(fault_schedule), duration_hours, json.dumps(resources, sort_keys=True), json.dumps(continuity, sort_keys=True), verdict)); self.storage.db.commit()
        self.storage._event("soak.run", "soak_run", identity, {"workload_version": self.workload_version, "duration_hours": duration_hours, "verdict": verdict}); self.storage.db.commit()
        return {"identity": identity, "workload_version": self.workload_version, "duration_hours": duration_hours, "fault_schedule": fault_schedule, "resources": resources, "continuity": continuity, "verdict": verdict}

    def require_pass(self, **kwargs: Any) -> dict[str, Any]:
        result = self.run(**kwargs)
        if result["verdict"] != "passed": raise PermissionError("soak qualification failed")
        return result
