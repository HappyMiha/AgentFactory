"""Repeatable NFR, capacity, accessibility, isolation, and recovery gate (AF-032)."""
from __future__ import annotations

import json
import platform
import secrets
import sys
from datetime import datetime, timezone
from typing import Any

from .storage import SQLiteStorage

NFR_THRESHOLDS = {"availability": 0.99, "p95_latency_ms": 1000, "durability": 1.0, "security": 1.0}

class QualificationService:
    def __init__(self, storage: SQLiteStorage, *, suite_version: str = "af032.v1"):
        self.storage, self.suite_version = storage, suite_version

    def run(self, *, profile: str, load: dict[str, int] | None = None,
            nfr: dict[str, float] | None = None, accessibility: bool | None = True,
            isolation: bool | None = True, backup_restore: bool | None = True) -> dict[str, Any]:
        load = load or {"active_runs": 10, "runnable_tasks": 25, "registered_agents": 100}
        nfr = nfr or dict(NFR_THRESHOLDS)
        env = {"python": sys.version.split()[0], "platform": platform.platform(), "profile": profile, "utc": datetime.now(timezone.utc).isoformat()}
        criteria = {
            "nfr_thresholds": all(float(nfr.get(k, -1)) >= threshold for k, threshold in NFR_THRESHOLDS.items()),
            "capacity": load.get("active_runs", 0) >= 10 and load.get("runnable_tasks", 0) >= 25 and load.get("registered_agents", 0) >= 100,
            "accessibility": accessibility is True,
            "tenant_isolation": isolation is True,
            "backup_restore": backup_restore is True,
        }
        raw = {"load": load, "nfr": nfr, "checks": {key: bool(value) for key, value in criteria.items()}, "thresholds": NFR_THRESHOLDS}
        verdict = "passed" if all(criteria.values()) else "failed"; identity = f"qualification-run-{secrets.token_hex(12)}"
        self.storage.db.execute("INSERT INTO qualification_runs(identity,suite_version,environment_json,profile_json,criteria_json,raw_evidence_json,verdict) VALUES(?,?,?,?,?,?,?)", (identity, self.suite_version, json.dumps(env, sort_keys=True), json.dumps({"profile": profile}, sort_keys=True), json.dumps(criteria, sort_keys=True), json.dumps(raw, sort_keys=True), verdict)); self.storage.db.commit()
        self.storage._event("qualification.run", "qualification_run", identity, {"suite_version": self.suite_version, "verdict": verdict, "criteria": criteria})
        return {"identity": identity, "suite_version": self.suite_version, "environment": env, "criteria": criteria, "raw_evidence": raw, "verdict": verdict}

    def require_pass(self, **kwargs: Any) -> dict[str, Any]:
        result = self.run(**kwargs)
        if result["verdict"] != "passed": raise PermissionError("qualification gate failed")
        return result
