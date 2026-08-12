"""Authenticated API, idempotency, ETag, signed webhook, and SDK contracts (AF-026)."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any, Callable

from .storage import SQLiteStorage

class ControlPlaneAPIContract:
    def __init__(self, storage: SQLiteStorage, *, token: str | None = None, webhook_secret: bytes | None = None):
        self.storage, self.token, self.webhook_secret = storage, token, webhook_secret or secrets.token_bytes(32)

    def authenticate(self, authorization: str | None) -> str:
        if not self.token or authorization == f"Bearer {self.token}": return "authenticated"
        raise PermissionError("Bearer authentication required")

    @staticmethod
    def etag(payload: Any) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(); return '"' + hashlib.sha256(raw).hexdigest() + '"'

    def idempotent(self, tenant_id: str, key: str, request: Any, operation: Callable[[], Any]) -> Any:
        if not tenant_id.strip() or not key.strip(): raise ValueError("tenant scope and idempotency key are required")
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        row = self.storage.db.execute("SELECT request_digest,response_json FROM api_idempotency WHERE tenant_id=? AND idempotency_key=?", (tenant_id, key)).fetchone()
        if row:
            if row["request_digest"] != digest: raise ValueError("idempotency key was reused for another request")
            return json.loads(row["response_json"])
        result = operation(); raw = json.dumps(result, sort_keys=True, default=str)
        self.storage.db.execute("INSERT INTO api_idempotency(identity,tenant_id,idempotency_key,request_digest,response_json) VALUES(?,?,?,?,?)", (self.storage._identity("api-idempotency"), tenant_id, key, digest, raw)); self.storage.db.commit(); return result

    def require_if_match(self, current: Any, if_match: str | None) -> None:
        expected = self.etag(current)
        if if_match != expected: raise ConflictError("stale ETag; refresh resource before mutation")

    def signed_webhook(self, tenant_id: str, delivery_key: str, event: dict[str, Any], *, sender: Callable[[dict[str, Any], str], bool], max_attempts: int = 3) -> dict[str, Any]:
        raw = json.dumps(event, sort_keys=True, separators=(",", ":")).encode(); signature = "sha256=" + hmac.new(self.webhook_secret, raw, hashlib.sha256).hexdigest()
        row = self.storage.db.execute("SELECT * FROM api_webhook_deliveries WHERE tenant_id=? AND delivery_key=?", (tenant_id, delivery_key)).fetchone()
        if row and row["status"] == "delivered": return {"delivery_key": delivery_key, "status": "delivered", "attempts": int(row["attempts"]), "signature": row["signature"]}
        attempts = int(row["attempts"]) if row else 0; delivered = False
        while attempts < max_attempts and not delivered:
            attempts += 1; delivered = bool(sender(event, signature))
        status = "delivered" if delivered else "failed"; identity = str(row["identity"]) if row else self.storage._identity("webhook")
        if row: self.storage.db.execute("UPDATE api_webhook_deliveries SET attempts=?,status=? WHERE id=?", (attempts, status, row["id"]))
        else: self.storage.db.execute("INSERT INTO api_webhook_deliveries(identity,tenant_id,delivery_key,event_json,signature,attempts,status) VALUES(?,?,?,?,?,?,?)", (identity, tenant_id, delivery_key, json.dumps(event, sort_keys=True), signature, attempts, status))
        self.storage.db.commit(); return {"delivery_key": delivery_key, "status": status, "attempts": attempts, "signature": signature}

class ConflictError(RuntimeError): pass

class SDKClient:
    """Small generated-SDK-compatible client contract used by contract tests."""
    def __init__(self, transport: Callable[..., Any], token: str): self.transport, self.token = transport, token
    def get(self, path: str, **params: Any) -> Any: return self.transport("GET", path, headers={"Authorization": f"Bearer {self.token}"}, params=params)
    def mutate(self, path: str, payload: dict[str, Any], *, idempotency_key: str, etag: str | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.token}", "Idempotency-Key": idempotency_key};
        if etag: headers["If-Match"] = etag
        return self.transport("POST", path, headers=headers, json=payload)
