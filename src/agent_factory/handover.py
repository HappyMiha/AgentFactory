"""GA runbook, clean-install, restore, and evidence handover gate (AF-035)."""
from __future__ import annotations

import json
import secrets
from typing import Any

from .storage import SQLiteStorage

CHECKLIST = ("clean_install", "provider_registration", "mission_start", "emergency_stop", "backup", "restore", "upgrade")

class HandoverService:
    def __init__(self, storage: SQLiteStorage, *, bundle_version: str = "af035.ga.v1"): self.storage, self.bundle_version = storage, bundle_version

    def build(self, *, checklist: dict[str, bool], evidence_index: dict[str, tuple[str, ...]], second_mission: bool) -> dict[str, Any]:
        complete = all(checklist.get(item) is True for item in CHECKLIST) and second_mission and all(evidence_index.get(item) for item in ("requirements", "risks", "criteria", "tests", "artifacts", "decisions", "exceptions", "recovery"))
        identity = f"handover-bundle-{secrets.token_hex(12)}"; verdict = "ready" if complete else "blocked"
        self.storage.db.execute("INSERT INTO handover_bundles(identity,bundle_version,checklist_json,evidence_index_json,verdict) VALUES(?,?,?,?,?)", (identity, self.bundle_version, json.dumps(checklist, sort_keys=True), json.dumps(evidence_index, sort_keys=True), verdict)); self.storage.db.commit()
        self.storage._event("handover.bundle", "handover_bundle", identity, {"bundle_version": self.bundle_version, "verdict": verdict}); self.storage.db.commit()
        return {"identity": identity, "bundle_version": self.bundle_version, "verdict": verdict, "checklist": checklist, "second_mission": second_mission}

    def require_ready(self, **kwargs: Any) -> dict[str, Any]:
        result = self.build(**kwargs)
        if result["verdict"] != "ready": raise PermissionError("GA handover evidence incomplete")
        return result
