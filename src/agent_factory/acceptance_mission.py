"""Reference acceptance mission evidence gate (AF-034)."""
from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

from .storage import SQLiteStorage

class AcceptanceMissionService:
    def __init__(self, storage: SQLiteStorage, *, mission_version: str = "af034.reference.v1"):
        self.storage, self.mission_version = storage, mission_version

    def run(self, *, providers: tuple[dict[str, Any], ...], evidence: dict[str, Any],
            exceptions: tuple[dict[str, str], ...] = ()) -> dict[str, Any]:
        if len({str(item.get("provider")) for item in providers}) < 3: raise ValueError("three heterogeneous providers are required")
        required = {"routing", "independent_verification", "worker_replacement", "recovery", "approval", "release_artifact"}
        criterion_results = evidence.get("criteria", {})
        signed = {key for key, value in criterion_results.items() if isinstance(value, dict) and value.get("signed") is True}
        accepted_exceptions = {item.get("criterion") for item in exceptions if item.get("accepted_by") and item.get("rationale")}
        criteria_ok = len(signed | accepted_exceptions) >= 45
        flow_ok = required <= set(evidence) and all(evidence[key] is True for key in required)
        verdict = "accepted" if criteria_ok and flow_ok else "failed"; identity = f"acceptance-mission-{secrets.token_hex(12)}"
        payload = {"providers": providers, "evidence": evidence, "exceptions": exceptions}; raw = json.dumps(payload, sort_keys=True, separators=(",", ":")); release_digest = hashlib.sha256(raw.encode()).hexdigest()
        self.storage.db.execute("INSERT INTO acceptance_missions(identity,mission_version,providers_json,evidence_json,release_digest,verdict) VALUES(?,?,?,?,?,?)", (identity, self.mission_version, json.dumps(providers, sort_keys=True), json.dumps(payload, sort_keys=True), release_digest, verdict)); self.storage.db.commit()
        self.storage._event("acceptance.mission", "acceptance_mission", identity, {"mission_version": self.mission_version, "verdict": verdict, "release_digest": release_digest}); self.storage.db.commit()
        return {"identity": identity, "mission_version": self.mission_version, "providers": providers, "release_digest": release_digest, "criteria_count": len(signed | accepted_exceptions), "verdict": verdict}

    def require_acceptance(self, **kwargs: Any) -> dict[str, Any]:
        result = self.run(**kwargs)
        if result["verdict"] != "accepted": raise PermissionError("reference acceptance mission failed")
        return result
