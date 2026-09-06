"""Persistent local connections; execution still requires the existing scoped broker.

Only trusted host composition calls execute(). There is no HTTP execution endpoint.
The metadata transaction serializes disconnect with admission across processes.
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
from pathlib import Path
import sqlite3
import uuid
from .credentials import CredentialBroker
from .os_credentials import WindowsCredentialStore

PROVIDERS = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
REVOKE_GUIDANCE = "Local access is disconnected. Revoke or rotate the key in your provider account to invalidate other copies."

class CredentialConnections:
    def __init__(self, database: Path, *, store=None):
        self.database = Path(database).resolve()
        self.store = store if store is not None else WindowsCredentialStore(
            hashlib.sha256(str(self.database).encode()).hexdigest())

    @contextmanager
    def _db(self):
        self.database.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.database, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("CREATE TABLE IF NOT EXISTS connections(id TEXT PRIMARY KEY, actor TEXT NOT NULL, tenant TEXT NOT NULL, provider TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','active','revoked')), created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            db.execute("CREATE TABLE IF NOT EXISTS connection_audit(id INTEGER PRIMARY KEY, connection_id TEXT NOT NULL, actor TEXT NOT NULL, event TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _owner(actor, tenant):
        if not all(isinstance(x, str) and 0 < len(x) <= 160 and x.isprintable() for x in (actor, tenant)):
            raise ValueError("Invalid connection owner")

    @staticmethod
    def _row(db, reference, actor, tenant):
        row = db.execute("SELECT * FROM connections WHERE id=? AND actor=? AND tenant=?", (reference, actor, tenant)).fetchone()
        if row is None:
            raise PermissionError("Connection is unavailable")
        return row

    @staticmethod
    def _view(row):
        return {k: row[k] for k in ("id", "provider", "status", "created_at")}

    def list(self, *, actor, tenant):
        self._owner(actor, tenant)
        with self._db() as db:
            return [self._view(r) for r in db.execute("SELECT * FROM connections WHERE actor=? AND tenant=? ORDER BY created_at,id", (actor, tenant))]

    def connect(self, *, actor, tenant, provider, secret):
        self._owner(actor, tenant)
        if provider not in PROVIDERS:
            raise ValueError("Unsupported provider")
        reference = uuid.uuid4().hex
        # Persist the non-secret reference before OS write so a killed process leaves
        # a visible pending record that can be removed, never an admitted connection.
        with self._db() as db:
            if db.execute("SELECT count(*) FROM connections WHERE actor=? AND tenant=? AND status!='revoked'", (actor, tenant)).fetchone()[0] >= 32:
                raise ValueError("Connection limit reached")
            db.execute("INSERT INTO connections(id,actor,tenant,provider,status) VALUES(?,?,?,?,'pending')", (reference, actor, tenant, provider))
        try:
            with self._db() as db:
                if self._row(db, reference, actor, tenant)['status'] != 'pending':
                    raise PermissionError("Connection is unavailable")
                self.store.put(reference, secret)
                db.execute("UPDATE connections SET status='active' WHERE id=?", (reference,))
                db.execute("INSERT INTO connection_audit(connection_id,actor,event) VALUES(?,?,'connected')", (reference, actor))
                result = self._view(self._row(db, reference, actor, tenant))
        except Exception:
            try:
                self.disconnect(reference, actor=actor, tenant=tenant)
            except Exception:
                pass  # The durable pending record still denies admission and permits retry.
            raise RuntimeError("Credential connection could not be saved") from None
        return result

    def disconnect(self, reference, *, actor, tenant):
        self._owner(actor, tenant)
        with self._db() as db:
            row = self._row(db, reference, actor, tenant)
            if row['status'] != 'revoked':
                db.execute("UPDATE connections SET status='revoked' WHERE id=?", (reference,))
                db.execute("INSERT INTO connection_audit(connection_id,actor,event) VALUES(?,?,'disconnected')", (reference, actor))
        # Commit the fence first. Failed OS deletion can be retried, never reactivate.
        removed = True
        try:
            self.store.delete(reference)
        except Exception:
            removed = False
        return {"id": reference, "status": "revoked", "os_removal_pending": not removed, "guidance": REVOKE_GUIDANCE}

    def execute(self, reference, *, actor, tenant, broker: CredentialBroker,
                mission_id, tool_key, operation, preapproved_operations,
                prompt, arguments, executor):
        """Trusted caller supplies current mission authority, never browser JSON.

        A saved connection is not an approval. Existing broker rejects scope expansion,
        forbids credential material in prompts/arguments and sanitizes evidence/output.
        A synchronous in-flight executor may finish before disconnect returns.
        """
        self._owner(actor, tenant)
        with self._db() as db:
            row = self._row(db, reference, actor, tenant)
            if row['status'] != 'active':
                raise PermissionError("Connection is disconnected")
            if operation not in preapproved_operations:
                raise PermissionError("Current mission authority is required")
            handle = None
            try:
                secret = self.store.get(reference)
                if any(secret in str(x) for x in (actor, tenant, mission_id, tool_key, operation)):
                    raise PermissionError("Credential material cannot enter scope metadata")
                handle = broker.issue(tenant_id=tenant, mission_id=mission_id, tool_key=tool_key,
                    operations=(operation,), preapproved_operations=preapproved_operations,
                    environment_key=PROVIDERS[row['provider']], secret_value=secret,
                    ttl_seconds=60, actor=actor)
                return broker.use(handle, tenant_id=tenant, mission_id=mission_id,
                    tool_key=tool_key, operation=operation, prompt=prompt, arguments=arguments,
                    executor=executor, actor=actor)
            except Exception:
                # Never propagate raw OS/provider exceptions or their input representation.
                raise RuntimeError("Credential-backed operation failed") from None
            finally:
                if handle is not None:
                    broker.revoke(handle, actor=actor, reason="Connection operation finished")
