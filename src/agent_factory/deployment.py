"""Versioned deployment profiles and continuity-checked upgrade boundary (AF-031)."""
from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from .storage import SQLiteStorage

PROFILES: dict[str, dict[str, Any]] = {
    "single-node": {"version": 1, "replicas": 1, "services": ["control-plane", "worker", "postgres", "object-store"], "egress": {"mode": "allowlist", "hosts": []}, "model": "provider-adapter", "connectors": "approval-gated", "updates": "signed-registry", "artifact_transfer": "local"},
    "clustered": {"version": 1, "replicas": 3, "services": ["control-plane", "worker", "postgres", "object-store"], "egress": {"mode": "allowlist", "hosts": []}, "model": "provider-adapter", "connectors": "approval-gated", "updates": "signed-registry", "artifact_transfer": "signed-registry"},
    "hybrid": {"version": 1, "replicas": 3, "services": ["control-plane", "worker", "postgres", "object-store"], "egress": {"mode": "allowlist", "hosts": ["model-provider", "connector-gateway", "artifact-registry"]}, "model": "remote-allowlist", "connectors": "gateway-allowlist", "updates": "signed-registry", "artifact_transfer": "signed-registry"},
    "air-gapped": {"version": 1, "replicas": 1, "services": ["control-plane", "worker", "postgres", "object-store"], "egress": {"mode": "deny-all", "hosts": []}, "model": "local-only", "connectors": "none", "updates": "offline-signed-bundle", "artifact_transfer": "human-approved-media"},
}

class DeploymentService:
    def __init__(self, storage: SQLiteStorage, manifest_dir: Path | None = None):
        self.storage = storage; self.manifest_dir = manifest_dir

    def manifest(self, profile: str) -> dict[str, Any]:
        if profile not in PROFILES: raise KeyError("unknown deployment profile")
        value = dict(PROFILES[profile]); value["profile"] = profile; return value

    def smoke(self, profile: str) -> dict[str, Any]:
        manifest = self.manifest(profile)
        if not manifest["services"] or manifest["replicas"] < 1: raise ValueError("invalid deployment manifest")
        if manifest["egress"]["mode"] == "deny-all" and manifest["egress"]["hosts"]: raise ValueError("air-gapped profile has egress")
        if profile == "air-gapped" and manifest["model"] != "local-only": raise ValueError("air-gapped model must be local")
        return {"profile": profile, "status": "healthy", "replicas": manifest["replicas"], "services": tuple(manifest["services"]), "egress": manifest["egress"]}

    def record(self, profile: str, operation: str, to_version: str, *, from_version: str | None = None,
               continuity: dict[str, Any] | None = None) -> dict[str, Any]:
        if operation not in {"deploy", "upgrade", "rollback"}: raise ValueError("invalid deployment operation")
        required = {"active_mission_authority", "pending_approvals", "accepted_artifacts", "audit_chain"}
        continuity = continuity or {}
        status = "verified" if required <= set(continuity) and all(continuity[k] is not None for k in required) else "blocked"
        identity = f"deployment-operation-{secrets.token_hex(12)}"; raw = json.dumps(continuity, sort_keys=True, separators=(",", ":"))
        self.storage.db.execute("INSERT INTO deployment_operations(identity,profile,operation,from_version,to_version,continuity_json,status) VALUES(?,?,?,?,?,?,?)", (identity, profile, operation, from_version, to_version, raw, status)); self.storage.db.commit()
        self.storage._event("deployment.operation", "deployment_operation", identity, {"profile": profile, "operation": operation, "status": status})
        if status != "verified": raise PermissionError("deployment continuity evidence incomplete")
        return {"identity": identity, "profile": profile, "operation": operation, "status": status, "continuity": continuity}
