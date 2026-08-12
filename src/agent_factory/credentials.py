"""Short-lived scoped credentials with zero persistent secret exposure."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .providers import SENSITIVE_ENV_MARKERS
from .storage import SQLiteStorage


ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
REDACTED = "[REDACTED_CREDENTIAL]"


class CredentialBroker:
    """Keeps credential values only in process memory and persists scope/evidence."""

    def __init__(self, storage: SQLiteStorage):
        self.storage = storage
        self._vault: dict[str, str] = {}

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _now(now: datetime | None = None) -> datetime:
        value = now or datetime.now(timezone.utc)
        if value.tzinfo is None:
            raise ValueError("Credential time must include a timezone")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _scope(row: Any) -> dict[str, Any]:
        return {
            "tenant_id": str(row["tenant_id"]), "mission_id": str(row["mission_id"]),
            "tool_key": str(row["tool_key"]),
            "operations": json.loads(row["operations_json"]),
            "environment_key": str(row["environment_key"]),
            "expires_at": str(row["expires_at"]),
        }

    def issue(
        self,
        *,
        tenant_id: str,
        mission_id: str,
        tool_key: str,
        operations: tuple[str, ...],
        preapproved_operations: set[str],
        environment_key: str,
        secret_value: str,
        ttl_seconds: int,
        actor: str,
        human_approved_by: str | None = None,
        now: datetime | None = None,
    ) -> str:
        if not all(value.strip() for value in (tenant_id, mission_id, tool_key, actor)):
            raise ValueError("Credential tenant, mission, tool, and actor are required")
        if not operations or tuple(sorted(set(operations))) != operations:
            raise ValueError("Credential operations must be non-empty, unique, and sorted")
        if not ENV_KEY.fullmatch(environment_key) or not any(
            marker in environment_key for marker in SENSITIVE_ENV_MARKERS
        ):
            raise ValueError("Credential environment key must be explicit and sensitive")
        if len(secret_value) < 12:
            raise ValueError("Credential value is too short")
        if not 1 <= ttl_seconds <= 3600:
            raise ValueError("Credential TTL must be between 1 and 3600 seconds")
        if not set(operations) <= preapproved_operations and not (human_approved_by or "").strip():
            raise PermissionError(
                "Credential scope above mission policy requires human system-owner approval"
            )
        instant = self._now(now)
        expires_at = (instant + timedelta(seconds=ttl_seconds)).isoformat()
        handle = f"cred_{uuid.uuid4().hex}"
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO credential_issuances(
                       identity,handle,tenant_id,mission_id,tool_key,operations_json,
                       environment_key,expires_at,approved_by,status
                   ) VALUES(?,?,?,?,?,?,?,?,?,'active')""",
                (
                    self.storage._identity("credential"), handle, tenant_id, mission_id,
                    tool_key, self._json(operations), environment_key, expires_at,
                    human_approved_by,
                ),
            )
            credential_id = int(cursor.lastrowid)
            row = self.storage.db.execute(
                "SELECT * FROM credential_issuances WHERE id=?", (credential_id,)
            ).fetchone()
            self._event(row, "issued", actor, "short-lived credential issued")
        self._vault[handle] = secret_value
        return handle

    def revoke(self, handle: str, *, actor: str, reason: str) -> None:
        row = self.storage.db.execute(
            "SELECT * FROM credential_issuances WHERE handle=?", (handle,)
        ).fetchone()
        if not row:
            raise KeyError("Unknown credential handle")
        if row["status"] == "revoked":
            self._vault.pop(handle, None)
            return
        if not actor.strip() or not reason.strip():
            raise ValueError("Credential revocation actor and reason are required")
        with self.storage.db:
            updated = self.storage.db.execute(
                """UPDATE credential_issuances SET status='revoked',version=version+1,
                          updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='active'""",
                (row["id"],),
            )
            if updated.rowcount != 1:
                raise PermissionError("Only an active credential can be revoked")
            current = self.storage.db.execute(
                "SELECT * FROM credential_issuances WHERE id=?", (row["id"],)
            ).fetchone()
            self._event(current, "revoked", actor, reason.strip())
        self._vault.pop(handle, None)

    def use(
        self,
        handle: str,
        *,
        tenant_id: str,
        mission_id: str,
        tool_key: str,
        operation: str,
        prompt: str,
        arguments: dict[str, Any],
        executor: Callable[[dict[str, str], dict[str, Any]], Any],
        actor: str,
        now: datetime | None = None,
    ) -> Any:
        row = self.storage.db.execute(
            "SELECT * FROM credential_issuances WHERE handle=?", (handle,)
        ).fetchone()
        if not row:
            raise PermissionError("Credential is unavailable")
        secret = self._vault.get(handle)
        instant = self._now(now)
        expires = datetime.fromisoformat(str(row["expires_at"]))
        if row["status"] != "active" or not secret:
            self._denied(row, actor, "credential is revoked or unavailable")
            raise PermissionError("Credential is revoked or unavailable")
        if instant >= expires:
            with self.storage.db:
                self.storage.db.execute(
                    """UPDATE credential_issuances SET status='expired',version=version+1,
                              updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='active'""",
                    (row["id"],),
                )
                expired = self.storage.db.execute(
                    "SELECT * FROM credential_issuances WHERE id=?", (row["id"],)
                ).fetchone()
                self._event(expired, "expired", actor, "credential TTL elapsed")
            self._vault.pop(handle, None)
            raise PermissionError("Credential has expired")
        if (tenant_id, mission_id, tool_key) != (
            row["tenant_id"], row["mission_id"], row["tool_key"]
        ) or operation not in json.loads(row["operations_json"]):
            self._denied(row, actor, "credential scope mismatch")
            raise PermissionError("Credential scope does not authorize this use")
        serialized_arguments = self._json(arguments)
        if secret in prompt or secret in serialized_arguments or handle in prompt \
                or handle in serialized_arguments:
            self._denied(row, actor, "credential injection firewall blocked secret material")
            raise PermissionError("Credential material cannot enter prompts or tool arguments")
        request = {
            "credential_id": int(row["id"]), "tenant_id": tenant_id,
            "mission_id": mission_id, "tool_key": tool_key, "operation": operation,
            "prompt_digest": hashlib.sha256(prompt.encode()).hexdigest(),
            "arguments": arguments,
        }
        request_digest = hashlib.sha256(self._json(request).encode()).hexdigest()
        try:
            raw = executor({str(row["environment_key"]): secret}, arguments)
            result = self._sanitize(raw, (secret, handle))
            outcome = "succeeded"
        except Exception as exc:
            result = {"error": self._sanitize(str(exc), (secret, handle))}
            outcome = "failed"
        result_json = self._json(result)
        result_digest = hashlib.sha256(self._json({
            "credential_id": int(row["id"]), "request_digest": request_digest,
            "outcome": outcome, "result": result,
        }).encode()).hexdigest()
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO credential_use_evidence(
                       identity,credential_id,tool_key,operation,request_digest,outcome,
                       sanitized_result_json,result_digest
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("credential-use"), row["id"], tool_key,
                    operation, request_digest, outcome, result_json, result_digest,
                ),
            )
            self._event(row, "used", actor, f"credential use {outcome}")
        if outcome == "failed":
            raise RuntimeError(result["error"])
        return result

    @classmethod
    def _sanitize(cls, value: Any, secrets: tuple[str, ...]) -> Any:
        if isinstance(value, str):
            result = value
            for secret in secrets:
                if secret:
                    result = result.replace(secret, REDACTED)
            return result
        if isinstance(value, dict):
            return {str(key): cls._sanitize(item, secrets) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._sanitize(item, secrets) for item in value]
        return value

    def _denied(self, row: Any, actor: str, detail: str) -> None:
        with self.storage.db:
            self._event(row, "denied", actor, detail)

    def _event(self, row: Any, event: str, actor: str, detail: str) -> None:
        scope = self._scope(row)
        cursor = self.storage.db.execute(
            """INSERT INTO credential_lifecycle_events(
                   identity,credential_id,event_type,actor,scope_json,detail
               ) VALUES(?,?,?,?,?,?)""",
            (
                self.storage._identity("credential-event"), row["id"], event,
                actor, self._json(scope), detail,
            ),
        )
        self.storage._event(f"credential.{event}", "credential", row["id"], {
            "lifecycle_event_id": int(cursor.lastrowid), "scope": scope,
            "actor": actor, "detail": detail,
        })
