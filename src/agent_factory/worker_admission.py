"""Opt-in, transactional admission for qualified workers in one Core database.

Only a trusted control-plane caller may register ownership, worker identity or
stop evidence. Tenant/worker strings and evidence digests are not authentication.
Existing leases remain the sole fences. Occupancy deliberately survives their
expiry because an expired authorization does not prove an external process died.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any, TYPE_CHECKING

from .models import AssignmentLease

if TYPE_CHECKING:
    from .storage import SQLiteStorage


ADMISSION_MIGRATION = """
CREATE TABLE worker_capacity_pools(
    pool_id TEXT PRIMARY KEY,
    capacity INTEGER NOT NULL CHECK(capacity BETWEEN 1 AND 64),
    runtimes_json TEXT NOT NULL CHECK(json_valid(runtimes_json)),
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    valid_until TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version > 0),
    actor TEXT NOT NULL, reason TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE worker_admission_workers(
    worker_id TEXT PRIMARY KEY,
    pool_id TEXT NOT NULL REFERENCES worker_capacity_pools(pool_id),
    tenant_id TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    version INTEGER NOT NULL CHECK(version > 0),
    actor TEXT NOT NULL, reason TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE worker_admission_projects(
    project_id INTEGER PRIMARY KEY REFERENCES projects(id),
    tenant_id TEXT NOT NULL,
    authority_digest TEXT NOT NULL CHECK(length(authority_digest)=64),
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    version INTEGER NOT NULL CHECK(version > 0),
    actor TEXT NOT NULL, reason TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TRIGGER worker_admission_project_owner_immutable
BEFORE UPDATE OF project_id,tenant_id ON worker_admission_projects
BEGIN SELECT RAISE(ABORT,'project tenant association is immutable'); END;
CREATE TABLE worker_admissions(
    id INTEGER PRIMARY KEY,
    identity TEXT NOT NULL UNIQUE,
    request_id TEXT NOT NULL UNIQUE,
    request_digest TEXT NOT NULL CHECK(length(request_digest)=64),
    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
    tenant_id TEXT NOT NULL,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    task_id INTEGER NOT NULL REFERENCES work_items(id),
    run_id INTEGER NOT NULL REFERENCES workflow_runs(id),
    stage_id INTEGER NOT NULL REFERENCES workflow_stages(id),
    stage_key TEXT NOT NULL,
    worker_id TEXT NOT NULL REFERENCES worker_admission_workers(worker_id),
    pool_id TEXT NOT NULL REFERENCES worker_capacity_pools(pool_id),
    runtime TEXT NOT NULL, provider_id TEXT NOT NULL, role TEXT NOT NULL,
    capabilities_json TEXT NOT NULL CHECK(json_valid(capabilities_json)),
    qualification_id INTEGER NOT NULL REFERENCES worker_qualifications(id),
    pool_version INTEGER NOT NULL, worker_version INTEGER NOT NULL,
    project_version INTEGER NOT NULL, lifecycle_version INTEGER NOT NULL,
    assignment_id INTEGER NOT NULL UNIQUE REFERENCES assignments(id),
    lease_id INTEGER NOT NULL UNIQUE REFERENCES leases(id),
    attempt_id INTEGER NOT NULL UNIQUE REFERENCES attempts(id),
    fencing_token INTEGER NOT NULL CHECK(fencing_token > 0),
    expires_at TEXT NOT NULL,
    occupancy_state TEXT NOT NULL CHECK(occupancy_state IN ('occupied','stopped')),
    runtime_session_id INTEGER UNIQUE REFERENCES worker_sessions(id),
    stop_evidence_digest TEXT, stop_actor TEXT, stop_reason TEXT, stopped_at TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    created_at TEXT NOT NULL
);
CREATE INDEX worker_admissions_pool_occupancy ON worker_admissions(pool_id,occupancy_state);
CREATE TRIGGER worker_admission_scope_immutable
BEFORE UPDATE OF identity,request_id,request_digest,request_json,tenant_id,project_id,
    task_id,run_id,stage_id,stage_key,worker_id,pool_id,runtime,provider_id,role,
    capabilities_json,qualification_id,pool_version,worker_version,project_version,
    lifecycle_version,assignment_id,lease_id,attempt_id,fencing_token,expires_at,created_at
ON worker_admissions
BEGIN SELECT RAISE(ABORT,'worker admission scope is immutable'); END;
CREATE TRIGGER worker_admission_session_once
BEFORE UPDATE OF runtime_session_id ON worker_admissions
WHEN OLD.runtime_session_id IS NOT NULL AND OLD.runtime_session_id IS NOT NEW.runtime_session_id
BEGIN SELECT RAISE(ABORT,'worker admission launch is already reserved'); END;
CREATE TRIGGER worker_admission_stop_once
BEFORE UPDATE OF occupancy_state,stop_evidence_digest,stop_actor,stop_reason,stopped_at ON worker_admissions
WHEN OLD.occupancy_state='stopped'
BEGIN SELECT RAISE(ABORT,'worker admission stop evidence is immutable'); END;
CREATE TRIGGER worker_admissions_no_delete BEFORE DELETE ON worker_admissions
BEGIN SELECT RAISE(ABORT,'worker admission evidence is durable'); END;
CREATE TRIGGER worker_admission_workers_no_delete BEFORE DELETE ON worker_admission_workers
BEGIN SELECT RAISE(ABORT,'registered workers must be explicitly disabled'); END;
CREATE TRIGGER worker_admission_projects_no_delete BEFORE DELETE ON worker_admission_projects
BEGIN SELECT RAISE(ABORT,'project authority must be explicitly disabled'); END;
CREATE TRIGGER worker_capacity_pools_no_delete BEFORE DELETE ON worker_capacity_pools
BEGIN SELECT RAISE(ABORT,'capacity pools must be explicitly disabled'); END;
"""


class AdmissionDeniedError(PermissionError):
    """Current authority does not allow this admitted worker operation."""


class AdmissionConflictError(ValueError):
    """A version, identity or replay conflicts with durable state."""


class CapacityUnavailableError(AdmissionDeniedError):
    """The physical executor's registered capacity is still occupied."""


def _text(value: str, name: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError(f"{name} must be bounded non-empty text")
    return value


def _positive(value: int, name: str, *, zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if zero else 1):
        raise ValueError(f"{name} must be a {'non-negative' if zero else 'positive'} integer")
    return value


def _digest(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Evidence must have a lowercase SHA-256 digest")
    return value


def _now(value: datetime | None = None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        raise ValueError("Admission clocks must be timezone-aware")
    return result.astimezone(timezone.utc)


def _instant(value: str) -> datetime:
    # SQLite datetime('now') is naive UTC; existing scheduler timestamps are ISO.
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise AdmissionDeniedError("Authority timestamp is invalid") from exc
    return (result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc))


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _set(values, name: str) -> tuple[str, ...]:
    if isinstance(values, str) or not isinstance(values, (tuple, list, set, frozenset)) or len(values) > 64:
        raise ValueError(f"{name} must be a bounded collection")
    return tuple(sorted({_text(value, name) for value in values}))


@dataclass(frozen=True)
class AdmissionRequest:
    request_id: str
    tenant_id: str
    project_id: int
    task_id: int
    run_id: int
    stage_key: str
    worker_id: str
    runtime: str
    provider_id: str
    role: str
    required_capabilities: tuple[str, ...]
    qualification_id: int
    expected_pool_version: int
    expected_worker_version: int
    expected_project_version: int
    expected_lifecycle_version: int
    ttl_seconds: int = 60
    conflict_domains: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("request_id", "tenant_id", "stage_key", "worker_id", "runtime", "provider_id", "role"):
            _text(getattr(self, name), name)
        for name in ("project_id", "task_id", "run_id", "qualification_id", "expected_pool_version", "expected_worker_version", "expected_project_version", "expected_lifecycle_version", "ttl_seconds"):
            _positive(getattr(self, name), name)
        if self.ttl_seconds > 86400:
            raise ValueError("Admission TTL cannot exceed one day")
        object.__setattr__(self, "required_capabilities", _set(self.required_capabilities, "capabilities"))
        object.__setattr__(self, "conflict_domains", _set(self.conflict_domains, "conflict domains"))


@dataclass(frozen=True)
class AdmissionReceipt:
    admission_id: int
    lease: AssignmentLease
    attempt_id: int
    qualification_id: int
    tenant_id: str
    project_id: int
    run_id: int
    stage_key: str
    stage_id: int
    pool_id: str
    request_id: str
    status: str
    active: bool
    runtime_session_id: int | None

    @property
    def assignment_id(self) -> int:
        return self.lease.assignment_id

    @property
    def fencing_token(self) -> int:
        return self.lease.fencing_token

    @property
    def expires_at(self) -> str:
        return self.lease.expires_at


def registered_worker(storage: SQLiteStorage, worker: str) -> bool:
    return storage.db.execute("SELECT 1 FROM worker_admission_workers WHERE worker_id=?", (worker,)).fetchone() is not None


def admission_for_assignment(storage: SQLiteStorage, assignment_id: int) -> dict | None:
    row = storage.db.execute("SELECT * FROM worker_admissions WHERE assignment_id=?", (assignment_id,)).fetchone()
    return dict(row) if row else None


def _authority(storage: SQLiteStorage, row: dict, current: datetime, *, starting: bool = False) -> datetime:
    if row["occupancy_state"] != "occupied":
        raise AdmissionDeniedError("Admission has been reconciled as stopped")
    worker = storage.db.execute("SELECT * FROM worker_admission_workers WHERE worker_id=?", (row["worker_id"],)).fetchone()
    pool = storage.db.execute("SELECT * FROM worker_capacity_pools WHERE pool_id=?", (row["pool_id"],)).fetchone()
    project = storage.db.execute("SELECT * FROM worker_admission_projects WHERE project_id=?", (row["project_id"],)).fetchone()
    if not worker or not pool or not project:
        raise AdmissionDeniedError("Registered admission authority is missing")
    if (not worker["enabled"] or not pool["enabled"] or not project["enabled"]
            or worker["pool_id"] != row["pool_id"] or worker["tenant_id"] != row["tenant_id"]
            or project["tenant_id"] != row["tenant_id"]
            or worker["version"] != row["worker_version"] or pool["version"] != row["pool_version"]
            or project["version"] != row["project_version"]
            or row["runtime"] not in json.loads(pool["runtimes_json"])):
        raise AdmissionDeniedError("Registered admission authority changed or is disabled")
    lifecycle = storage.db.execute("SELECT * FROM worker_lifecycle WHERE worker_id=?", (row["worker_id"],)).fetchone()
    allowed_states = {"active"} if starting else {"active", "draining"}
    if not lifecycle or lifecycle["state"] not in allowed_states:
        raise AdmissionDeniedError("Worker lifecycle denies this operation")
    same_lifecycle = lifecycle["version"] == row["lifecycle_version"]
    newly_draining = (not starting and lifecycle["state"] == "draining"
                      and lifecycle["version"] == row["lifecycle_version"] + 1)
    if not same_lifecycle and not newly_draining:
        raise AdmissionDeniedError("Lifecycle changes cannot revive an older admission")
    qualification = storage.db.execute("SELECT * FROM worker_qualifications WHERE worker_id=? ORDER BY id DESC LIMIT 1", (row["worker_id"],)).fetchone()
    if (not qualification or qualification["id"] != row["qualification_id"]
            or qualification["status"] != "qualified" or qualification["provider_id"] != row["provider_id"]
            or qualification["role"] != row["role"]
            or not set(json.loads(row["capabilities_json"])) <= set(json.loads(qualification["capabilities_json"]))):
        raise AdmissionDeniedError("Exact current worker qualification is required")
    deadline = min(_instant(qualification["valid_until"]), _instant(pool["valid_until"]))
    if deadline <= current:
        raise AdmissionDeniedError("Worker qualification or registration expired")
    assignment = storage.db.execute("SELECT * FROM assignments WHERE id=?", (row["assignment_id"],)).fetchone()
    task = storage.db.execute("SELECT project_id,status,kind FROM work_items WHERE id=?", (row["task_id"],)).fetchone()
    run = storage.db.execute("SELECT task_id,project_id,status FROM workflow_runs WHERE id=?", (row["run_id"],)).fetchone()
    stage = storage.db.execute("SELECT run_id,stage_key,status FROM workflow_stages WHERE id=?", (row["stage_id"],)).fetchone()
    attempt = storage.db.execute("SELECT assignment_id,status FROM attempts WHERE id=?", (row["attempt_id"],)).fetchone()
    if (not assignment or not task or not run or not stage or not attempt
            or assignment["task_id"] != row["task_id"] or assignment["agent_id"] != row["worker_id"]
            or assignment["runtime"] != row["runtime"] or assignment["run_id"] != row["run_id"]
            or assignment["stage_id"] != row["stage_id"] or task["project_id"] != row["project_id"]
            or run["project_id"] != row["project_id"] or run["task_id"] != row["task_id"]
            or stage["run_id"] != row["run_id"] or stage["stage_key"] != row["stage_key"]
            or attempt["assignment_id"] != row["assignment_id"]
            or task["kind"] != "task" or task["status"] not in {"pending", "running"}
            or run["status"] != "running" or attempt["status"] not in {"claimed", "running"}
            or stage["status"] not in {"pending", "running", "waiting_approval"}):
        raise AdmissionDeniedError("Admission relational scope no longer matches")
    return deadline


def guard_lease(storage: SQLiteStorage, assignment_id: int, fencing_token: int, current_timestamp: str) -> None:
    """Called after Core's live/latest lease check, inside that same transaction."""
    row = admission_for_assignment(storage, assignment_id)
    if row is None:
        return
    if row["fencing_token"] != fencing_token:
        raise AdmissionDeniedError("Admission fencing token does not match")
    _authority(storage, row, _instant(current_timestamp))


def clamp_lease_expiry(storage: SQLiteStorage, assignment_id: int, proposed_iso: str) -> str:
    row = admission_for_assignment(storage, assignment_id)
    if row is None:
        return proposed_iso
    qualification = storage.db.execute("SELECT valid_until FROM worker_qualifications WHERE id=?", (row["qualification_id"],)).fetchone()
    pool = storage.db.execute("SELECT valid_until FROM worker_capacity_pools WHERE pool_id=?", (row["pool_id"],)).fetchone()
    if not qualification or not pool:
        raise AdmissionDeniedError("Admission expiry authority is missing")
    return min(_instant(proposed_iso), _instant(qualification["valid_until"]), _instant(pool["valid_until"])).isoformat(timespec="microseconds")


class WorkerAdmissionService:
    """Trusted in-process API; caller authentication remains outside this class."""

    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    @contextmanager
    def _transaction(self):
        if self.storage.db.in_transaction:
            raise RuntimeError("Admission operation requires its own transaction")
        self.storage._begin_immediate()
        try:
            yield
            self.storage.db.commit()
        except Exception:
            self.storage.db.rollback()
            raise

    def _event(self, kind: str, identity: str | int, payload: dict) -> None:
        self.storage._event(kind, "worker_admission", identity, payload)

    @staticmethod
    def _version(row, expected: int) -> int:
        _positive(expected, "expected version", zero=True)
        actual = int(row["version"]) if row else 0
        if expected != actual:
            raise AdmissionConflictError("Registration version changed")
        return actual + 1

    def configure_pool(self, *, pool_id: str, allowed_runtimes, valid_until: datetime,
                       capacity: int = 1, expected_version: int = 0, enabled: bool = True,
                       actor: str, reason: str) -> dict:
        _text(pool_id, "pool ID"); _text(actor, "actor"); _text(reason, "reason", 1024)
        _positive(capacity, "capacity")
        runtimes = _set(allowed_runtimes, "runtime allowlist")
        if capacity > 64 or not runtimes or not isinstance(enabled, bool):
            raise ValueError("Pool requires 1–64 slots, runtimes and a boolean enabled flag")
        expiry = _now(valid_until).isoformat(timespec="microseconds")
        with self._transaction():
            row = self.storage.db.execute("SELECT * FROM worker_capacity_pools WHERE pool_id=?", (pool_id,)).fetchone()
            version = self._version(row, expected_version)
            occupied = self.storage.db.execute("SELECT count(*) FROM worker_admissions WHERE pool_id=? AND occupancy_state='occupied'", (pool_id,)).fetchone()[0]
            if capacity < occupied:
                raise CapacityUnavailableError("Capacity cannot be reduced below unreconciled occupancy")
            values = (capacity, _json(runtimes), int(enabled), expiry, version, actor, reason, _now().isoformat(), pool_id)
            if row:
                self.storage.db.execute("UPDATE worker_capacity_pools SET capacity=?,runtimes_json=?,enabled=?,valid_until=?,version=?,actor=?,reason=?,updated_at=? WHERE pool_id=?", values)
            else:
                self.storage.db.execute("INSERT INTO worker_capacity_pools(capacity,runtimes_json,enabled,valid_until,version,actor,reason,updated_at,pool_id) VALUES(?,?,?,?,?,?,?,?,?)", values)
            self._event("worker.pool.configured", pool_id, {"pool_id": pool_id, "capacity": capacity, "version": version, "enabled": enabled, "actor": actor, "reason": reason})
            return dict(self.storage.db.execute("SELECT * FROM worker_capacity_pools WHERE pool_id=?", (pool_id,)).fetchone())

    def _live_legacy_work(self, worker_id: str | None = None, *, project_id: int | None = None) -> bool:
        # Any failed legacy session can still own a process: even a returned
        # external identity may be followed by a failed local persistence step.
        # Assignment finalization/release is not exact stopped-process evidence.
        # This profile must not silently convert that uncertainty into free space.
        if (worker_id is None) == (project_id is None):
            raise ValueError("Legacy work lookup requires exactly one scope")
        assignment_scope = "a.agent_id=?" if worker_id is not None else "t.project_id=?"
        provider_scope = "p.agent_id=?" if worker_id is not None else "t.project_id=?"
        parameters = (worker_id if worker_id is not None else project_id,)
        active_assignment = self.storage.db.execute(f"""SELECT 1 FROM assignments a
            JOIN work_items t ON t.id=a.task_id
            LEFT JOIN worker_admissions admitted ON admitted.assignment_id=a.id
            WHERE {assignment_scope} AND admitted.id IS NULL AND
                (a.status IN ('pending','active','suspended') OR EXISTS(
                    SELECT 1 FROM worker_sessions s WHERE s.assignment_id=a.id
                    AND s.status IN ('starting','running','suspended','failed')))
            LIMIT 1""", parameters).fetchone()
        if active_assignment:
            return True
        # Legacy provider recovery labels lost work abandoned and mirrors that
        # into cancelled assignments/sessions. It does not establish a stop.
        # Check the source table too, including historical rows without mirrors.
        return self.storage.db.execute(f"""SELECT 1 FROM provider_execution_attempts p
            JOIN work_items t ON t.id=p.task_id
            LEFT JOIN attempts a ON a.provider_attempt_id=p.id
            LEFT JOIN worker_admissions admitted ON admitted.assignment_id=a.assignment_id
            WHERE {provider_scope} AND admitted.id IS NULL
              AND p.status IN ('claimed','running','failed','abandoned')
            LIMIT 1""", parameters).fetchone() is not None

    def bind_worker(self, *, worker_id: str, pool_id: str, tenant_id: str,
                    expected_version: int = 0, enabled: bool = True, actor: str, reason: str) -> dict:
        for value, name in ((worker_id, "worker ID"), (pool_id, "pool ID"), (tenant_id, "tenant ID"), (actor, "actor"), (reason, "reason")):
            _text(value, name)
        if not isinstance(enabled, bool):
            raise ValueError("Enabled must be boolean")
        with self._transaction():
            if not self.storage.db.execute("SELECT 1 FROM worker_capacity_pools WHERE pool_id=?", (pool_id,)).fetchone():
                raise AdmissionDeniedError("Capacity pool is not registered")
            row = self.storage.db.execute("SELECT * FROM worker_admission_workers WHERE worker_id=?", (worker_id,)).fetchone()
            version = self._version(row, expected_version)
            if self._live_legacy_work(worker_id):
                raise AdmissionConflictError("Live legacy work must be stopped before registration")
            if row and (row["pool_id"] != pool_id or row["tenant_id"] != tenant_id):
                occupied = self.storage.db.execute("SELECT 1 FROM worker_admissions WHERE worker_id=? AND occupancy_state='occupied' LIMIT 1", (worker_id,)).fetchone()
                if occupied:
                    raise AdmissionConflictError("Rebinding cannot abandon unreconciled occupancy")
            values = (pool_id, tenant_id, int(enabled), version, actor, reason, _now().isoformat(), worker_id)
            if row:
                self.storage.db.execute("UPDATE worker_admission_workers SET pool_id=?,tenant_id=?,enabled=?,version=?,actor=?,reason=?,updated_at=? WHERE worker_id=?", values)
            else:
                self.storage.db.execute("INSERT INTO worker_admission_workers(pool_id,tenant_id,enabled,version,actor,reason,updated_at,worker_id) VALUES(?,?,?,?,?,?,?,?)", values)
            self._event("worker.identity.bound", worker_id, {"worker_id": worker_id, "pool_id": pool_id, "tenant_id": tenant_id, "version": version, "enabled": enabled, "actor": actor, "reason": reason})
            return dict(self.storage.db.execute("SELECT * FROM worker_admission_workers WHERE worker_id=?", (worker_id,)).fetchone())

    def bind_project(self, *, project_id: int, tenant_id: str, authority_digest: str,
                     expected_version: int = 0, enabled: bool = True, actor: str, reason: str) -> dict:
        _positive(project_id, "project ID"); _text(tenant_id, "tenant ID"); _digest(authority_digest)
        _text(actor, "actor"); _text(reason, "reason", 1024)
        if not isinstance(enabled, bool):
            raise ValueError("Enabled must be boolean")
        with self._transaction():
            if not self.storage.db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                raise AdmissionDeniedError("Core project does not exist")
            row = self.storage.db.execute("SELECT * FROM worker_admission_projects WHERE project_id=?", (project_id,)).fetchone()
            version = self._version(row, expected_version)
            if row and row["tenant_id"] != tenant_id:
                raise AdmissionConflictError("Core project tenant ownership cannot be reassigned")
            if (not row or enabled) and self._live_legacy_work(project_id=project_id):
                raise AdmissionConflictError("Live or unresolved legacy project work prevents registration")
            if row:
                self.storage.db.execute("UPDATE worker_admission_projects SET authority_digest=?,enabled=?,version=?,actor=?,reason=?,updated_at=? WHERE project_id=?", (authority_digest, int(enabled), version, actor, reason, _now().isoformat(), project_id))
            else:
                self.storage.db.execute("INSERT INTO worker_admission_projects(project_id,tenant_id,authority_digest,enabled,version,actor,reason,updated_at) VALUES(?,?,?,?,?,?,?,?)", (project_id, tenant_id, authority_digest, int(enabled), version, actor, reason, _now().isoformat()))
            self._event("worker.project.bound", project_id, {"project_id": project_id, "tenant_id": tenant_id, "authority_digest": authority_digest, "version": version, "enabled": enabled, "actor": actor, "reason": reason})
            return dict(self.storage.db.execute("SELECT * FROM worker_admission_projects WHERE project_id=?", (project_id,)).fetchone())

    def _stage(self, project_id: int, task_id: int, run_id: int, stage_key: str, *, allow_waiting_approval: bool = False):
        row = self.storage.db.execute("""SELECT s.*,r.project_id AS run_project_id,r.task_id AS run_task_id,
            r.status AS run_status,t.project_id AS task_project_id
            FROM workflow_stages s JOIN workflow_runs r ON r.id=s.run_id
            JOIN work_items t ON t.id=r.task_id WHERE s.run_id=? AND s.stage_key=?""", (run_id, stage_key)).fetchone()
        allowed_states = {"pending", "running"} | ({"waiting_approval"} if allow_waiting_approval else set())
        if (not row or row["run_task_id"] != task_id or row["run_project_id"] != project_id
                or row["task_project_id"] != project_id or row["run_status"] != "running"
                or row["status"] not in allowed_states):
            raise AdmissionDeniedError("Project, task, run and current stage must match")
        dependencies = set(json.loads(row["dependencies_json"]))
        succeeded = {item[0] for item in self.storage.db.execute("SELECT stage_key FROM workflow_stages WHERE run_id=? AND status='succeeded'", (run_id,))}
        if not dependencies <= succeeded:
            raise AdmissionDeniedError("Workflow stage dependencies are incomplete")
        return row

    def admit(self, request: AdmissionRequest, *, now: datetime | None = None) -> AdmissionReceipt:
        if not isinstance(request, AdmissionRequest):
            raise TypeError("An immutable AdmissionRequest is required")
        document = _json(asdict(request))
        digest = hashlib.sha256(document.encode("utf-8")).hexdigest()
        with self._transaction():
            current = _now(now)  # Sample after obtaining the writer lock.
            replay = self.storage.db.execute("SELECT * FROM worker_admissions WHERE request_id=?", (request.request_id,)).fetchone()
            if replay:
                if replay["request_digest"] != digest:
                    raise AdmissionConflictError("Request ID is already bound to another admission scope")
                return self._receipt(dict(replay), current)
            worker = self.storage.db.execute("SELECT * FROM worker_admission_workers WHERE worker_id=?", (request.worker_id,)).fetchone()
            project = self.storage.db.execute("SELECT * FROM worker_admission_projects WHERE project_id=?", (request.project_id,)).fetchone()
            if not worker or not project or worker["tenant_id"] != request.tenant_id or project["tenant_id"] != request.tenant_id:
                raise AdmissionDeniedError("Trusted worker and project tenant associations are required")
            pool = self.storage.db.execute("SELECT * FROM worker_capacity_pools WHERE pool_id=?", (worker["pool_id"],)).fetchone()
            lifecycle = self.storage.db.execute("SELECT * FROM worker_lifecycle WHERE worker_id=?", (request.worker_id,)).fetchone()
            if (not pool or not worker["enabled"] or not project["enabled"] or not pool["enabled"]
                    or request.runtime not in json.loads(pool["runtimes_json"])):
                raise AdmissionDeniedError("Worker pool or runtime policy denies admission")
            if (worker["version"] != request.expected_worker_version or pool["version"] != request.expected_pool_version
                    or project["version"] != request.expected_project_version or not lifecycle
                    or lifecycle["version"] != request.expected_lifecycle_version):
                raise AdmissionConflictError("Expected worker admission versions changed")
            if lifecycle["state"] != "active":
                raise AdmissionDeniedError("Only an active worker can receive new work")
            qualification = self.storage.db.execute("SELECT * FROM worker_qualifications WHERE worker_id=? ORDER BY id DESC LIMIT 1", (request.worker_id,)).fetchone()
            if (not qualification or qualification["id"] != request.qualification_id
                    or qualification["status"] != "qualified" or qualification["provider_id"] != request.provider_id
                    or qualification["role"] != request.role
                    or not set(request.required_capabilities) <= set(json.loads(qualification["capabilities_json"]))):
                raise AdmissionDeniedError("Exact latest qualified worker/provider/role/capabilities are required")
            authority_expiry = min(_instant(qualification["valid_until"]), _instant(pool["valid_until"]))
            # Existing scheduler TTL is integral seconds. Round down, never beyond authority.
            ttl = min(request.ttl_seconds, int((authority_expiry - current).total_seconds()))
            if ttl < 1:
                raise AdmissionDeniedError("Worker authority has expired or cannot cover one second")
            stage = self._stage(request.project_id, request.task_id, request.run_id, request.stage_key)
            occupied = self.storage.db.execute("SELECT count(*) FROM worker_admissions WHERE pool_id=? AND occupancy_state='occupied'", (worker["pool_id"],)).fetchone()[0]
            if occupied >= pool["capacity"]:
                raise CapacityUnavailableError("Physical worker capacity requires stopped-process reconciliation")
            if self._live_legacy_work(request.worker_id):
                raise AdmissionDeniedError("Registered worker has unaccounted legacy work")
            lease = self.storage._claim_runnable_task_in_transaction(
                request.task_id, request.worker_id, request.runtime, ttl_seconds=ttl,
                conflict_domains=request.conflict_domains, now=current,
            )
            self.storage.db.execute("UPDATE assignments SET run_id=?,stage_id=? WHERE id=?", (request.run_id, int(stage["id"]), lease.assignment_id))
            attempt_id = self.storage._create_assignment_attempt_in_transaction(lease.assignment_id, lease.fencing_token, now=current)
            values = {
                "identity": self.storage._identity("worker-admission"), "request_id": request.request_id,
                "request_digest": digest, "request_json": document, "tenant_id": request.tenant_id,
                "project_id": request.project_id, "task_id": request.task_id, "run_id": request.run_id,
                "stage_id": int(stage["id"]), "stage_key": request.stage_key, "worker_id": request.worker_id,
                "pool_id": worker["pool_id"], "runtime": request.runtime, "provider_id": request.provider_id,
                "role": request.role, "capabilities_json": _json(request.required_capabilities),
                "qualification_id": request.qualification_id, "pool_version": pool["version"],
                "worker_version": worker["version"], "project_version": project["version"],
                "lifecycle_version": lifecycle["version"], "assignment_id": lease.assignment_id,
                "lease_id": lease.lease_id, "attempt_id": attempt_id, "fencing_token": lease.fencing_token,
                "expires_at": lease.expires_at, "occupancy_state": "occupied", "created_at": current.isoformat(timespec="microseconds"),
            }
            cursor = self.storage.db.execute(f"INSERT INTO worker_admissions({','.join(values)}) VALUES({','.join('?' for _ in values)})", tuple(values.values()))
            admission_id = int(cursor.lastrowid)
            self._event("worker.admission.created", admission_id, {"admission_id": admission_id, "assignment_id": lease.assignment_id, "attempt_id": attempt_id, "fencing_token": lease.fencing_token, "pool_id": worker["pool_id"], "qualification_id": request.qualification_id, "request_digest": digest})
            return self._receipt(dict(self.storage.db.execute("SELECT * FROM worker_admissions WHERE id=?", (admission_id,)).fetchone()), current)

    def _receipt(self, row: dict, current: datetime) -> AdmissionReceipt:
        lease_row = self.storage.db.execute("SELECT * FROM leases WHERE id=?", (row["lease_id"],)).fetchone()
        assignment = self.storage.db.execute("SELECT status FROM assignments WHERE id=?", (row["assignment_id"],)).fetchone()
        domains = tuple(item[0] for item in self.storage.db.execute("SELECT domain FROM assignment_conflict_domains WHERE assignment_id=? ORDER BY domain", (row["assignment_id"],)))
        active = bool(lease_row and assignment and lease_row["status"] == "active" and assignment["status"] == "active" and _instant(lease_row["expires_at"]) > current)
        if active:
            try:
                _authority(self.storage, row, current)
            except AdmissionDeniedError:
                active = False
        lease = AssignmentLease(task_id=row["task_id"], assignment_id=row["assignment_id"], lease_id=row["lease_id"], worker=row["worker_id"], runtime=row["runtime"], fencing_token=row["fencing_token"], expires_at=lease_row["expires_at"] if lease_row else row["expires_at"], conflict_domains=domains)
        return AdmissionReceipt(admission_id=row["id"], lease=lease, attempt_id=row["attempt_id"], qualification_id=row["qualification_id"], tenant_id=row["tenant_id"], project_id=row["project_id"], run_id=row["run_id"], stage_key=row["stage_key"], stage_id=row["stage_id"], pool_id=row["pool_id"], request_id=row["request_id"], status=row["occupancy_state"], active=active, runtime_session_id=row["runtime_session_id"])

    def reconcile_stopped(self, *, admission_id: int, fencing_token: int, evidence_digest: str,
                          actor: str, reason: str, now: datetime | None = None) -> AdmissionReceipt:
        _positive(admission_id, "admission ID"); _positive(fencing_token, "fence"); _digest(evidence_digest)
        _text(actor, "actor"); _text(reason, "reason", 1024)
        with self._transaction():
            current = _now(now)
            found = self.storage.db.execute("SELECT * FROM worker_admissions WHERE id=?", (admission_id,)).fetchone()
            if not found or found["fencing_token"] != fencing_token:
                raise AdmissionDeniedError("Stop evidence must address the exact admission and fence")
            row = dict(found)
            if row["occupancy_state"] == "stopped":
                if (row["stop_evidence_digest"], row["stop_actor"], row["stop_reason"]) != (evidence_digest, actor, reason):
                    raise AdmissionConflictError("Stopped admission already has immutable evidence")
                return self._receipt(row, current)
            stamp = current.isoformat(timespec="microseconds")
            self.storage.db.execute("UPDATE leases SET status='revoked',version=version+1,updated_at=? WHERE id=? AND assignment_id=? AND fencing_token=? AND status='active'", (stamp, row["lease_id"], row["assignment_id"], fencing_token))
            self.storage.db.execute("UPDATE assignments SET status='cancelled',version=version+1,updated_at=? WHERE id=? AND status IN ('pending','active','suspended')", (stamp, row["assignment_id"]))
            self.storage.db.execute("UPDATE attempts SET status='cancelled',version=version+1,updated_at=? WHERE id=? AND assignment_id=? AND status IN ('claimed','running')", (stamp, row["attempt_id"], row["assignment_id"]))
            if row["runtime_session_id"] is not None:
                self.storage.db.execute("UPDATE worker_sessions SET status='cancelled',version=version+1,finalized_at=?,updated_at=? WHERE id=? AND assignment_id=? AND status IN ('starting','running','suspended')", (stamp, stamp, row["runtime_session_id"], row["assignment_id"]))
            self.storage.db.execute("UPDATE worker_admissions SET occupancy_state='stopped',stop_evidence_digest=?,stop_actor=?,stop_reason=?,stopped_at=?,version=version+1 WHERE id=? AND occupancy_state='occupied'", (evidence_digest, actor, reason, stamp, admission_id))
            self._event("worker.admission.stopped", admission_id, {"admission_id": admission_id, "assignment_id": row["assignment_id"], "fencing_token": fencing_token, "evidence_digest": evidence_digest, "actor": actor, "reason": reason})
            return self._receipt(dict(self.storage.db.execute("SELECT * FROM worker_admissions WHERE id=?", (admission_id,)).fetchone()), current)

    def validate_launch_in_transaction(self, launch, runtime_id: str, *, now: datetime | None = None) -> dict | None:
        """Validate stored association even when a caller omits launch metadata."""
        if not self.storage.db.in_transaction:
            raise RuntimeError("Launch validation must share its runtime reservation transaction")
        row = admission_for_assignment(self.storage, launch.assignment_id)
        if row is None:
            return None
        current = _now(now)
        self.storage._assert_fenced_lease(launch.assignment_id, launch.fencing_token, current.isoformat(timespec="microseconds"))
        _authority(self.storage, row, current, starting=True)
        binding = launch.binding
        if (binding is None or launch.item.id != row["task_id"] or launch.item.project_id != row["project_id"]
                or launch.agent.enabled is not True or launch.agent.id != row["worker_id"] or launch.agent.provider != row["provider_id"]
                or launch.agent.role != row["role"] or runtime_id != row["runtime"]
                or launch.fencing_token != row["fencing_token"] or binding.run_id != row["run_id"]
                or binding.stage_id != row["stage_key"] or binding.attempt_id != row["attempt_id"]):
            raise AdmissionDeniedError("Runtime launch does not match its stored admission")
        stored_task = self.storage.get_task(row["task_id"])
        if (set(launch.item.permissions) != set(stored_task.permissions)
                or launch.item.budget != stored_task.budget or launch.item.kind != stored_task.kind):
            raise AdmissionDeniedError("Runtime task permissions, budget and kind must match stored authority")
        stage = self._stage(row["project_id"], row["task_id"], row["run_id"], row["stage_key"],
                            allow_waiting_approval=launch.mutable and launch.approval is not None)
        if stage["id"] != row["stage_id"]:
            raise AdmissionDeniedError("Runtime stage identity changed")
        worktree = self.storage.db.execute("SELECT * FROM worktrees WHERE id=?", (binding.worktree_id,)).fetchone()
        if (not worktree or worktree["status"] != "ready" or worktree["assignment_id"] != row["assignment_id"]
                or worktree["attempt_id"] != row["attempt_id"] or worktree["task_id"] != row["task_id"]
                or worktree["owner"] != row["worker_id"] or worktree["lease_id"] != row["lease_id"]
                or worktree["fencing_token"] != row["fencing_token"]):
            raise AdmissionDeniedError("A ready worktree with the exact admission scope is required")
        context = _json(launch.context)
        if hashlib.sha256(context.encode("utf-8")).hexdigest() != launch.context_digest:
            raise AdmissionDeniedError("Runtime context digest does not match")
        package = self.storage.db.execute("SELECT * FROM execution_context_packages WHERE digest=?", (launch.context_digest,)).fetchone()
        if (not package or package["task_id"] != row["task_id"] or package["run_id"] != row["run_id"]
                or package["assignment_id"] != row["assignment_id"] or package["fencing_token"] != row["fencing_token"]):
            raise AdmissionDeniedError("Runtime context package belongs to another admission")
        return row

    def validate_launch(self, launch, runtime_id: str, *, now: datetime | None = None) -> dict | None:
        """Read/validate only; runtime reservation must use the internal method."""
        with self._transaction():
            return self.validate_launch_in_transaction(launch, runtime_id, now=now)
