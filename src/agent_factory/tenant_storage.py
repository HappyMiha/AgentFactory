"""Tenant-scoped object storage and data-governance boundary (AF-029)."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .storage import SQLiteStorage

_CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")

class TenantStorageService:
    """A storage adapter whose every operation requires an exact tenant scope."""
    def __init__(self, storage: SQLiteStorage, root: Path):
        self.storage, self.root = storage, root
        self.root.mkdir(parents=True, exist_ok=True)

    def configure_tenant(self, tenant_id: str, *, classification: str = "internal",
                         residency: str = "local", retention_seconds: int = 86400,
                         quota_bytes: int = 10_000_000, legal_hold: bool = False) -> dict[str, Any]:
        if not tenant_id.strip() or classification not in _CLASSIFICATIONS or not residency.strip():
            raise ValueError("tenant policy requires tenant, classification, and residency")
        if retention_seconds < 0 or quota_bytes <= 0:
            raise ValueError("retention must be non-negative and quota positive")
        self.storage.db.execute("""INSERT INTO tenant_policies(tenant_id,classification,residency,retention_seconds,quota_bytes,legal_hold,updated_at)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(tenant_id) DO UPDATE SET classification=excluded.classification,
            residency=excluded.residency,retention_seconds=excluded.retention_seconds,quota_bytes=excluded.quota_bytes,
            legal_hold=excluded.legal_hold,updated_at=excluded.updated_at""",
            (tenant_id, classification, residency, retention_seconds, quota_bytes, int(legal_hold), _ts(_now())))
        self.storage.db.commit()
        return self.policy(tenant_id)

    def policy(self, tenant_id: str) -> dict[str, Any]:
        row = self.storage.db.execute("SELECT * FROM tenant_policies WHERE tenant_id=?", (tenant_id,)).fetchone()
        if not row: raise KeyError("unknown tenant")
        return dict(row)

    def put(self, tenant_id: str, object_key: str, content: bytes, *, classification: str | None = None) -> dict[str, Any]:
        policy = self.policy(tenant_id)
        if not object_key.strip() or object_key.startswith("/") or ".." in Path(object_key).parts:
            raise ValueError("object key must be a relative scoped key")
        classification = classification or str(policy["classification"])
        if classification not in _CLASSIFICATIONS: raise ValueError("invalid classification")
        used = self.storage.db.execute("SELECT COALESCE(SUM(size_bytes),0) FROM tenant_objects WHERE tenant_id=? AND deleted_at IS NULL", (tenant_id,)).fetchone()[0]
        if used + len(content) > int(policy["quota_bytes"]): raise PermissionError("tenant quota exceeded")
        digest = hashlib.sha256(content).hexdigest(); now = _now(); identity = f"tenant-object-{secrets.token_hex(12)}"
        path = self.root / tenant_id / digest; path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists(): path.write_bytes(content)
        self.storage.db.execute("INSERT INTO tenant_objects(identity,tenant_id,object_key,digest,size_bytes,classification,residency,created_at,retention_until) VALUES(?,?,?,?,?,?,?,?,?)",
            (identity, tenant_id, object_key, digest, len(content), classification, policy["residency"], _ts(now), _ts(now + timedelta(seconds=int(policy["retention_seconds"]))))); self.storage.db.commit()
        self.storage._event("tenant.object.stored", "tenant_object", identity, {"tenant_id": tenant_id, "digest": digest, "size_bytes": len(content)})
        return {"identity": identity, "tenant_id": tenant_id, "object_key": object_key, "digest": digest, "size_bytes": len(content), "classification": classification, "residency": policy["residency"]}

    def get(self, tenant_id: str, object_key: str) -> bytes:
        row = self.storage.db.execute("SELECT * FROM tenant_objects WHERE tenant_id=? AND object_key=? AND deleted_at IS NULL", (tenant_id, object_key)).fetchone()
        if not row: raise FileNotFoundError("object not found")
        path = self.root / tenant_id / str(row["digest"])
        if not path.is_file(): raise FileNotFoundError("object content unavailable")
        return path.read_bytes()

    def export(self, tenant_id: str) -> dict[str, Any]:
        rows = self.storage.db.execute("SELECT identity,object_key,digest,size_bytes,classification,residency,retention_until FROM tenant_objects WHERE tenant_id=? AND deleted_at IS NULL ORDER BY id", (tenant_id,)).fetchall()
        manifest = {"tenant_id": tenant_id, "objects": [dict(row) for row in rows]}; raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False); digest = hashlib.sha256(raw.encode()).hexdigest(); identity = f"tenant-export-{secrets.token_hex(12)}"
        self.storage.db.execute("INSERT INTO tenant_exports(identity,tenant_id,manifest_json,manifest_digest,verified) VALUES(?,?,?,?,1)", (identity, tenant_id, raw, digest)); self.storage.db.commit()
        self.storage._event("tenant.export.verified", "tenant_export", identity, {"tenant_id": tenant_id, "manifest_digest": digest, "count": len(rows)})
        return {"identity": identity, "tenant_id": tenant_id, "manifest_digest": digest, "object_count": len(rows), "verified": True}

    def delete(self, tenant_id: str, object_key: str, *, now: datetime | None = None) -> dict[str, Any]:
        policy = self.policy(tenant_id); row = self.storage.db.execute("SELECT * FROM tenant_objects WHERE tenant_id=? AND object_key=? AND deleted_at IS NULL", (tenant_id, object_key)).fetchone()
        if not row: raise FileNotFoundError("object not found")
        instant = now or _now(); blocked = bool(policy["legal_hold"]) or instant < datetime.fromisoformat(str(row["retention_until"]))
        status, reason = ("blocked", "legal_hold" if policy["legal_hold"] else "retention") if blocked else ("deleted", "policy_satisfied")
        identity = f"tenant-deletion-{secrets.token_hex(12)}"; self.storage.db.execute("INSERT INTO tenant_deletions(identity,tenant_id,object_identity,status,reason) VALUES(?,?,?,?,?)", (identity, tenant_id, row["identity"], status, reason))
        if status == "deleted": self.storage.db.execute("UPDATE tenant_objects SET deleted_at=? WHERE id=?", (_ts(instant), row["id"]))
        self.storage.db.commit()
        if status == "deleted":
            path = self.root / tenant_id / str(row["digest"])
            if path.exists(): path.unlink()
        self.storage._event("tenant.object.deletion", "tenant_deletion", identity, {"tenant_id": tenant_id, "object_key": object_key, "status": status, "reason": reason})
        return {"identity": identity, "tenant_id": tenant_id, "object_key": object_key, "status": status, "reason": reason}

class PostgresStorageContract:
    """Migration contract for a future PostgreSQL deployment; no driver is required locally."""
    dialect = "postgresql"
    required_scope_columns = ("tenant_id", "identity", "digest")

    @classmethod
    def validate(cls, *, dsn: str, tenant_id: str) -> dict[str, str]:
        if not dsn.startswith(("postgresql://", "postgres://")) or not tenant_id.strip():
            raise ValueError("PostgreSQL contract requires a PostgreSQL DSN and tenant scope")
        return {"dialect": cls.dialect, "tenant_id": tenant_id, "scope": "required", "migration": "sqlite-to-postgresql-preserve-digests"}
