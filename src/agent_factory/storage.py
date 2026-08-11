from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .lifecycle import TRANSITIONS, ensure_transition
from .models import Budget, Status, WorkItem

MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, """
        CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS work_items(id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), title TEXT NOT NULL, description TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS workflow_runs(id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), task_id INTEGER NOT NULL REFERENCES work_items(id), workflow_id TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, completed_at TEXT);
        CREATE TABLE IF NOT EXISTS artifacts(id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES workflow_runs(id), stage TEXT NOT NULL, agent_id TEXT NOT NULL, provider TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', review_note TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, event_type TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS approval_gates(id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL UNIQUE REFERENCES workflow_runs(id), status TEXT NOT NULL DEFAULT 'pending', decision_note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, decided_at TEXT);
        CREATE TABLE IF NOT EXISTS provider_execution_gates(id INTEGER PRIMARY KEY, provider TEXT NOT NULL, agent_id TEXT NOT NULL, task_id INTEGER NOT NULL REFERENCES work_items(id), status TEXT NOT NULL DEFAULT 'pending', decision_note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, decided_at TEXT, consumed_at TEXT);
        CREATE TABLE IF NOT EXISTS provider_execution_artifacts(id INTEGER PRIMARY KEY, gate_id INTEGER NOT NULL UNIQUE REFERENCES provider_execution_gates(id), provider TEXT NOT NULL, agent_id TEXT NOT NULL, content TEXT NOT NULL, metadata TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    """),
    (2, """
        CREATE INDEX IF NOT EXISTS idx_workflow_runs_task ON workflow_runs(task_id, workflow_id, status);
        CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity_type, entity_id, id);
        UPDATE workflow_runs
           SET status='awaiting_approval', completed_at=NULL
         WHERE status='completed'
           AND EXISTS (SELECT 1 FROM approval_gates g WHERE g.run_id=workflow_runs.id AND g.status='pending');
    """),
    (3, """
        CREATE TABLE IF NOT EXISTS provider_execution_attempts(
            id INTEGER PRIMARY KEY,
            gate_id INTEGER NOT NULL UNIQUE REFERENCES provider_execution_gates(id),
            provider TEXT NOT NULL, agent_id TEXT NOT NULL,
            task_id INTEGER NOT NULL REFERENCES work_items(id),
            request_hash TEXT NOT NULL, definition_hash TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('claimed','running','succeeded','failed','abandoned')),
            pid INTEGER, result TEXT, metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at TEXT, finished_at TEXT, heartbeat_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_provider_attempt_status ON provider_execution_attempts(status, heartbeat_at);
        ALTER TABLE provider_execution_artifacts ADD COLUMN attempt_id INTEGER REFERENCES provider_execution_attempts(id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_artifact_attempt ON provider_execution_artifacts(attempt_id) WHERE attempt_id IS NOT NULL;
    """),
    (4, """
        CREATE TABLE IF NOT EXISTS github_mutation_plans(
            id INTEGER PRIMARY KEY,
            repo TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            plan_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TRIGGER IF NOT EXISTS github_plans_no_update
        BEFORE UPDATE ON github_mutation_plans BEGIN SELECT RAISE(ABORT, 'github mutation plans are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS github_plans_no_delete
        BEFORE DELETE ON github_mutation_plans BEGIN SELECT RAISE(ABORT, 'github mutation plans are immutable'); END;
        CREATE TABLE IF NOT EXISTS github_mutation_gates(
            id INTEGER PRIMARY KEY,
            plan_id INTEGER NOT NULL REFERENCES github_mutation_plans(id),
            repo TEXT NOT NULL,
            plan_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','claimed','consumed')),
            decision_note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            decided_at TEXT,
            consumed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_github_gates_plan ON github_mutation_gates(plan_id,status);
        CREATE TABLE IF NOT EXISTS github_idempotency(
            repo TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(repo,idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS github_mutation_reports(
            id INTEGER PRIMARY KEY,
            gate_id INTEGER NOT NULL UNIQUE REFERENCES github_mutation_gates(id),
            plan_id INTEGER NOT NULL REFERENCES github_mutation_plans(id),
            status TEXT NOT NULL CHECK(status IN ('succeeded','partial','failed')),
            report_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """),
    (5, """
        CREATE TABLE IF NOT EXISTS active_workflow_claims(
            task_id INTEGER NOT NULL REFERENCES work_items(id),
            workflow_id TEXT NOT NULL,
            run_id INTEGER NOT NULL UNIQUE REFERENCES workflow_runs(id),
            claimed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(task_id,workflow_id)
        );
        INSERT OR IGNORE INTO active_workflow_claims(task_id,workflow_id,run_id)
        SELECT task_id,workflow_id,MIN(id)
          FROM workflow_runs
         WHERE status IN ('running','awaiting_approval')
         GROUP BY task_id,workflow_id;
        CREATE TABLE IF NOT EXISTS pending_provider_gate_claims(
            provider TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            task_id INTEGER NOT NULL REFERENCES work_items(id),
            gate_id INTEGER NOT NULL UNIQUE REFERENCES provider_execution_gates(id),
            claimed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(provider,agent_id,task_id)
        );
        INSERT OR IGNORE INTO pending_provider_gate_claims(provider,agent_id,task_id,gate_id)
        SELECT provider,agent_id,task_id,MIN(id)
          FROM provider_execution_gates
         WHERE status='pending'
        GROUP BY provider,agent_id,task_id;
    """),
    (6, """
        ALTER TABLE provider_execution_gates
            ADD COLUMN request_hash TEXT
            CHECK(request_hash IS NULL OR (length(request_hash)=64 AND request_hash NOT GLOB '*[^0-9a-f]*'));
        ALTER TABLE provider_execution_gates
            ADD COLUMN definition_hash TEXT
            CHECK(definition_hash IS NULL OR (length(definition_hash)=64 AND definition_hash NOT GLOB '*[^0-9a-f]*'));
        UPDATE provider_execution_gates
           SET status='rejected',
               decision_note=CASE
                   WHEN decision_note='' THEN 'Approval predates immutable snapshot binding; request a new gate.'
                   ELSE decision_note || char(10) || 'Approval predates immutable snapshot binding; request a new gate.'
               END,
               decided_at=COALESCE(decided_at,CURRENT_TIMESTAMP)
         WHERE status IN ('pending','approved');
        DELETE FROM pending_provider_gate_claims
         WHERE gate_id IN (
             SELECT id FROM provider_execution_gates WHERE status='rejected'
         );
        CREATE TRIGGER IF NOT EXISTS provider_gate_snapshot_no_update
        BEFORE UPDATE OF provider,agent_id,task_id,request_hash,definition_hash
        ON provider_execution_gates
        WHEN OLD.provider IS NOT NEW.provider
          OR OLD.agent_id IS NOT NEW.agent_id
          OR OLD.task_id IS NOT NEW.task_id
          OR OLD.request_hash IS NOT NEW.request_hash
          OR OLD.definition_hash IS NOT NEW.definition_hash
        BEGIN
            SELECT RAISE(ABORT, 'provider approval snapshot is immutable');
        END;
    """),
    (7, """
        CREATE TABLE IF NOT EXISTS reviewer_assignments(
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL REFERENCES workflow_runs(id),
            stage TEXT NOT NULL,
            reviewer_agent_id TEXT NOT NULL,
            reviewer_provider TEXT NOT NULL,
            reviewer_model TEXT NOT NULL,
            reviewed_stages TEXT NOT NULL,
            reviewed_artifact_ids TEXT NOT NULL,
            producer_agents TEXT NOT NULL,
            excluded_models TEXT NOT NULL,
            excluded_candidates TEXT NOT NULL,
            strategy TEXT NOT NULL,
            review_artifact_id INTEGER REFERENCES artifacts(id),
            verdict TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            UNIQUE(run_id,stage)
        );
        CREATE INDEX IF NOT EXISTS idx_reviewer_assignments_rotation
            ON reviewer_assignments(stage,reviewer_agent_id,id);
    """),
    (8, """
        CREATE TABLE IF NOT EXISTS runtime_settings(
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            version INTEGER NOT NULL CHECK(version > 0),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS runtime_setting_versions(
            id INTEGER PRIMARY KEY,
            key TEXT NOT NULL,
            version INTEGER NOT NULL,
            value_json TEXT NOT NULL,
            actor TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(key,version)
        );
        CREATE TRIGGER IF NOT EXISTS runtime_setting_versions_no_update
        BEFORE UPDATE ON runtime_setting_versions
        BEGIN SELECT RAISE(ABORT, 'runtime setting history is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS runtime_setting_versions_no_delete
        BEFORE DELETE ON runtime_setting_versions
        BEGIN SELECT RAISE(ABORT, 'runtime setting history is immutable'); END;
    """),
    (9, """
        ALTER TABLE work_items ADD COLUMN identity TEXT;
        ALTER TABLE work_items ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0);
        ALTER TABLE work_items ADD COLUMN kind TEXT NOT NULL DEFAULT 'task';
        ALTER TABLE work_items ADD COLUMN dependencies_json TEXT NOT NULL DEFAULT '[]';
        ALTER TABLE work_items ADD COLUMN inputs_json TEXT NOT NULL DEFAULT '{}';
        ALTER TABLE work_items ADD COLUMN expected_outputs_json TEXT NOT NULL DEFAULT '[]';
        ALTER TABLE work_items ADD COLUMN acceptance_criteria_json TEXT NOT NULL DEFAULT '[]';
        ALTER TABLE work_items ADD COLUMN permissions_json TEXT NOT NULL DEFAULT '[]';
        ALTER TABLE work_items ADD COLUMN budget_max_tokens INTEGER NOT NULL DEFAULT 4000;
        ALTER TABLE work_items ADD COLUMN budget_max_seconds INTEGER NOT NULL DEFAULT 120;
        ALTER TABLE work_items ADD COLUMN budget_max_cost_usd REAL NOT NULL DEFAULT 0.0;
        ALTER TABLE work_items ADD COLUMN artifact_ids_json TEXT NOT NULL DEFAULT '[]';
        ALTER TABLE work_items ADD COLUMN github_number INTEGER;
        ALTER TABLE work_items ADD COLUMN updated_at TEXT;

        UPDATE work_items SET
            identity='work-item:' || id,
            kind=COALESCE(json_extract(payload,'$.kind'),'task'),
            dependencies_json=COALESCE(json_extract(payload,'$.dependencies'),'[]'),
            inputs_json=COALESCE(json_extract(payload,'$.inputs'),'{}'),
            expected_outputs_json=COALESCE(json_extract(payload,'$.expected_outputs'),'[]'),
            acceptance_criteria_json=COALESCE(json_extract(payload,'$.acceptance_criteria'),'[]'),
            permissions_json=COALESCE(json_extract(payload,'$.permissions'),'[]'),
            budget_max_tokens=COALESCE(json_extract(payload,'$.budget.max_tokens'),4000),
            budget_max_seconds=COALESCE(json_extract(payload,'$.budget.max_seconds'),120),
            budget_max_cost_usd=COALESCE(json_extract(payload,'$.budget.max_cost_usd'),0.0),
            artifact_ids_json=COALESCE(json_extract(payload,'$.artifacts'),'[]'),
            github_number=json_extract(payload,'$.github_number'),
            updated_at=created_at
        WHERE json_valid(payload);
        UPDATE work_items SET identity='work-item:' || id, updated_at=created_at
         WHERE identity IS NULL;
        CREATE UNIQUE INDEX idx_work_items_identity ON work_items(identity);

        ALTER TABLE workflow_runs ADD COLUMN identity TEXT;
        ALTER TABLE workflow_runs ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0);
        UPDATE workflow_runs SET identity='run:' || id;
        CREATE UNIQUE INDEX idx_workflow_runs_identity ON workflow_runs(identity);

        ALTER TABLE artifacts ADD COLUMN identity TEXT;
        ALTER TABLE artifacts ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0);
        UPDATE artifacts SET identity='artifact:' || id;
        CREATE UNIQUE INDEX idx_artifacts_identity ON artifacts(identity);

        ALTER TABLE provider_execution_attempts ADD COLUMN identity TEXT;
        ALTER TABLE provider_execution_attempts ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0);
        UPDATE provider_execution_attempts SET identity='provider-attempt:' || id;
        CREATE UNIQUE INDEX idx_provider_attempts_identity ON provider_execution_attempts(identity);

        ALTER TABLE provider_execution_artifacts ADD COLUMN identity TEXT;
        ALTER TABLE provider_execution_artifacts ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0);
        UPDATE provider_execution_artifacts SET identity='provider-artifact:' || id;
        CREATE UNIQUE INDEX idx_provider_artifacts_identity ON provider_execution_artifacts(identity);

        CREATE TABLE workflow_stages(
            id INTEGER PRIMARY KEY,
            identity TEXT NOT NULL UNIQUE,
            run_id INTEGER NOT NULL REFERENCES workflow_runs(id),
            stage_key TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending','running','waiting_approval','succeeded','failed')),
            version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(run_id,stage_key)
        );
        INSERT INTO workflow_stages(identity,run_id,stage_key,status,created_at,updated_at)
        SELECT 'stage:legacy:' || id,id,'legacy',
               CASE status
                   WHEN 'approved' THEN 'succeeded'
                   WHEN 'rejected' THEN 'failed'
                   WHEN 'failed' THEN 'failed'
                   WHEN 'awaiting_approval' THEN 'waiting_approval'
                   ELSE 'running'
               END,
               created_at,COALESCE(completed_at,created_at)
          FROM workflow_runs;

        CREATE TABLE assignments(
            id INTEGER PRIMARY KEY,
            identity TEXT NOT NULL UNIQUE,
            task_id INTEGER NOT NULL REFERENCES work_items(id),
            run_id INTEGER REFERENCES workflow_runs(id),
            stage_id INTEGER REFERENCES workflow_stages(id),
            agent_id TEXT NOT NULL,
            runtime TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending','active','suspended','succeeded','failed','cancelled')),
            version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO assignments(identity,task_id,agent_id,runtime,status,created_at,updated_at)
        SELECT 'assignment:provider:' || id,task_id,agent_id,provider,
               CASE status
                   WHEN 'claimed' THEN 'active'
                   WHEN 'running' THEN 'active'
                   WHEN 'succeeded' THEN 'succeeded'
                   WHEN 'failed' THEN 'failed'
                   ELSE 'cancelled'
               END,
               created_at,COALESCE(finished_at,heartbeat_at,created_at)
          FROM provider_execution_attempts;

        CREATE TABLE worker_sessions(
            id INTEGER PRIMARY KEY,
            identity TEXT NOT NULL UNIQUE,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id),
            runtime TEXT NOT NULL,
            external_session_id TEXT,
            status TEXT NOT NULL CHECK(status IN ('starting','running','suspended','succeeded','failed','cancelled')),
            version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO worker_sessions(identity,assignment_id,runtime,status,created_at,updated_at)
        SELECT 'worker-session:provider:' || p.id,a.id,p.provider,
               CASE p.status
                   WHEN 'claimed' THEN 'starting'
                   WHEN 'running' THEN 'running'
                   WHEN 'succeeded' THEN 'succeeded'
                   WHEN 'failed' THEN 'failed'
                   ELSE 'cancelled'
               END,
               p.created_at,COALESCE(p.finished_at,p.heartbeat_at,p.created_at)
          FROM provider_execution_attempts p
          JOIN assignments a ON a.identity='assignment:provider:' || p.id;

        CREATE TABLE attempts(
            id INTEGER PRIMARY KEY,
            identity TEXT NOT NULL UNIQUE,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id),
            provider_attempt_id INTEGER UNIQUE REFERENCES provider_execution_attempts(id),
            ordinal INTEGER NOT NULL CHECK(ordinal > 0),
            status TEXT NOT NULL CHECK(status IN ('claimed','running','succeeded','failed','abandoned','cancelled')),
            version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(assignment_id,ordinal)
        );
        INSERT INTO attempts(identity,assignment_id,provider_attempt_id,ordinal,status,created_at,updated_at)
        SELECT 'attempt:provider:' || p.id,a.id,p.id,1,p.status,p.created_at,
               COALESCE(p.finished_at,p.heartbeat_at,p.created_at)
          FROM provider_execution_attempts p
          JOIN assignments a ON a.identity='assignment:provider:' || p.id;

        CREATE TABLE leases(
            id INTEGER PRIMARY KEY,
            identity TEXT NOT NULL UNIQUE,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id),
            fencing_token INTEGER NOT NULL CHECK(fencing_token > 0),
            status TEXT NOT NULL CHECK(status IN ('active','expired','released','revoked')),
            expires_at TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(assignment_id,fencing_token)
        );

        CREATE TABLE worktrees(
            id INTEGER PRIMARY KEY,
            identity TEXT NOT NULL UNIQUE,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id),
            attempt_id INTEGER REFERENCES attempts(id),
            repository TEXT NOT NULL,
            base_sha TEXT NOT NULL,
            branch TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL CHECK(status IN ('provisioning','ready','dirty','retained','cleaned','missing')),
            version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TRIGGER work_items_identity_required
        BEFORE INSERT ON work_items WHEN NEW.identity IS NULL
        BEGIN SELECT RAISE(ABORT, 'work item identity is required'); END;
        CREATE TRIGGER workflow_runs_identity_required
        BEFORE INSERT ON workflow_runs WHEN NEW.identity IS NULL
        BEGIN SELECT RAISE(ABORT, 'workflow run identity is required'); END;
        CREATE TRIGGER artifacts_identity_required
        BEFORE INSERT ON artifacts WHEN NEW.identity IS NULL
        BEGIN SELECT RAISE(ABORT, 'artifact identity is required'); END;
        CREATE TRIGGER provider_attempts_identity_required
        BEFORE INSERT ON provider_execution_attempts WHEN NEW.identity IS NULL
        BEGIN SELECT RAISE(ABORT, 'provider attempt identity is required'); END;
        CREATE TRIGGER provider_artifacts_identity_required
        BEFORE INSERT ON provider_execution_artifacts WHEN NEW.identity IS NULL
        BEGIN SELECT RAISE(ABORT, 'provider artifact identity is required'); END;

        CREATE TRIGGER work_items_identity_immutable BEFORE UPDATE OF identity ON work_items
        WHEN OLD.identity IS NOT NEW.identity BEGIN SELECT RAISE(ABORT, 'work item identity is immutable'); END;
        CREATE TRIGGER workflow_runs_identity_immutable BEFORE UPDATE OF identity ON workflow_runs
        WHEN OLD.identity IS NOT NEW.identity BEGIN SELECT RAISE(ABORT, 'workflow run identity is immutable'); END;
        CREATE TRIGGER artifacts_identity_immutable BEFORE UPDATE OF identity ON artifacts
        WHEN OLD.identity IS NOT NEW.identity BEGIN SELECT RAISE(ABORT, 'artifact identity is immutable'); END;
        CREATE TRIGGER provider_attempts_identity_immutable BEFORE UPDATE OF identity ON provider_execution_attempts
        WHEN OLD.identity IS NOT NEW.identity BEGIN SELECT RAISE(ABORT, 'provider attempt identity is immutable'); END;
        CREATE TRIGGER provider_artifacts_identity_immutable BEFORE UPDATE OF identity ON provider_execution_artifacts
        WHEN OLD.identity IS NOT NEW.identity BEGIN SELECT RAISE(ABORT, 'provider artifact identity is immutable'); END;
        CREATE TRIGGER workflow_stages_identity_immutable BEFORE UPDATE OF identity ON workflow_stages
        WHEN OLD.identity IS NOT NEW.identity BEGIN SELECT RAISE(ABORT, 'stage identity is immutable'); END;
        CREATE TRIGGER assignments_identity_immutable BEFORE UPDATE OF identity ON assignments
        WHEN OLD.identity IS NOT NEW.identity BEGIN SELECT RAISE(ABORT, 'assignment identity is immutable'); END;
        CREATE TRIGGER worker_sessions_identity_immutable BEFORE UPDATE OF identity ON worker_sessions
        WHEN OLD.identity IS NOT NEW.identity BEGIN SELECT RAISE(ABORT, 'worker session identity is immutable'); END;
        CREATE TRIGGER attempts_identity_immutable BEFORE UPDATE OF identity ON attempts
        WHEN OLD.identity IS NOT NEW.identity BEGIN SELECT RAISE(ABORT, 'attempt identity is immutable'); END;
        CREATE TRIGGER leases_identity_immutable BEFORE UPDATE OF identity ON leases
        WHEN OLD.identity IS NOT NEW.identity BEGIN SELECT RAISE(ABORT, 'lease identity is immutable'); END;
        CREATE TRIGGER worktrees_identity_immutable BEFORE UPDATE OF identity ON worktrees
        WHEN OLD.identity IS NOT NEW.identity BEGIN SELECT RAISE(ABORT, 'worktree identity is immutable'); END;

        CREATE TRIGGER workflow_runs_valid_transition BEFORE UPDATE OF status ON workflow_runs
        WHEN NOT (
            (OLD.status='running' AND NEW.status IN ('awaiting_approval','failed')) OR
            (OLD.status='awaiting_approval' AND NEW.status IN ('approved','rejected','failed'))
        ) BEGIN SELECT RAISE(ABORT, 'invalid workflow run transition'); END;
        CREATE TRIGGER work_items_valid_transition BEFORE UPDATE OF status ON work_items
        WHEN NOT (
            (OLD.status='pending' AND NEW.status IN ('running','failed')) OR
            (OLD.status='running' AND NEW.status IN ('completed','failed')) OR
            (OLD.status='completed' AND NEW.status IN ('approved','rejected')) OR
            (OLD.status='failed' AND NEW.status='pending')
        ) BEGIN SELECT RAISE(ABORT, 'invalid work item transition'); END;
        CREATE TRIGGER artifacts_valid_transition BEFORE UPDATE OF status ON artifacts
        WHEN NOT (OLD.status='pending' AND NEW.status IN ('approved','rejected'))
        BEGIN SELECT RAISE(ABORT, 'invalid artifact transition'); END;
        CREATE TRIGGER provider_attempts_valid_transition BEFORE UPDATE OF status ON provider_execution_attempts
        WHEN NOT (OLD.status IN ('claimed','running') AND NEW.status IN ('running','succeeded','failed','abandoned') AND OLD.status<>NEW.status)
        BEGIN SELECT RAISE(ABORT, 'invalid provider attempt transition'); END;
        CREATE TRIGGER workflow_stages_valid_transition BEFORE UPDATE OF status ON workflow_stages
        WHEN NOT (
            (OLD.status='pending' AND NEW.status IN ('running','failed')) OR
            (OLD.status='running' AND NEW.status IN ('waiting_approval','succeeded','failed')) OR
            (OLD.status='waiting_approval' AND NEW.status IN ('running','succeeded','failed')) OR
            (OLD.status='failed' AND NEW.status='pending')
        ) BEGIN SELECT RAISE(ABORT, 'invalid stage transition'); END;
        CREATE TRIGGER assignments_valid_transition BEFORE UPDATE OF status ON assignments
        WHEN NOT (
            (OLD.status='pending' AND NEW.status IN ('active','cancelled')) OR
            (OLD.status='active' AND NEW.status IN ('suspended','succeeded','failed','cancelled')) OR
            (OLD.status='suspended' AND NEW.status IN ('active','failed','cancelled'))
        ) BEGIN SELECT RAISE(ABORT, 'invalid assignment transition'); END;
        CREATE TRIGGER worker_sessions_valid_transition BEFORE UPDATE OF status ON worker_sessions
        WHEN NOT (
            (OLD.status='starting' AND NEW.status IN ('running','failed','cancelled')) OR
            (OLD.status='running' AND NEW.status IN ('suspended','succeeded','failed','cancelled')) OR
            (OLD.status='suspended' AND NEW.status IN ('running','failed','cancelled'))
        ) BEGIN SELECT RAISE(ABORT, 'invalid worker session transition'); END;
        CREATE TRIGGER attempts_valid_transition BEFORE UPDATE OF status ON attempts
        WHEN NOT (OLD.status IN ('claimed','running') AND NEW.status IN ('running','succeeded','failed','abandoned','cancelled') AND OLD.status<>NEW.status)
        BEGIN SELECT RAISE(ABORT, 'invalid attempt transition'); END;
        CREATE TRIGGER leases_valid_transition BEFORE UPDATE OF status ON leases
        WHEN NOT (OLD.status='active' AND NEW.status IN ('expired','released','revoked'))
        BEGIN SELECT RAISE(ABORT, 'invalid lease transition'); END;
        CREATE TRIGGER worktrees_valid_transition BEFORE UPDATE OF status ON worktrees
        WHEN NOT (
            (OLD.status='provisioning' AND NEW.status IN ('ready','missing','cleaned')) OR
            (OLD.status='ready' AND NEW.status IN ('dirty','retained','missing')) OR
            (OLD.status='dirty' AND NEW.status IN ('ready','retained','missing')) OR
            (OLD.status='retained' AND NEW.status IN ('cleaned','missing')) OR
            (OLD.status='missing' AND NEW.status IN ('provisioning','cleaned'))
        ) BEGIN SELECT RAISE(ABORT, 'invalid worktree transition'); END;
    """),
)

RUN_TRANSITIONS = TRANSITIONS["run"]


def _sha256_snapshot(value: str, field: str) -> str:
    """Validate a caller-computed canonical SHA-256 approval snapshot."""

    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


class SQLiteStorage:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self) -> None:
        self.db.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        applied = {int(row[0]) for row in self.db.execute("SELECT version FROM schema_migrations")}
        for version, script in MIGRATIONS:
            if version in applied:
                continue
            # executescript commits implicitly, so each migration owns its explicit transaction.
            self.db.executescript(f"BEGIN IMMEDIATE;\n{script}\nINSERT INTO schema_migrations(version) VALUES({version});\nCOMMIT;")

    def _event(self, kind: str, entity: str, entity_id: int | str, payload: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO events(event_type,entity_type,entity_id,payload) VALUES(?,?,?,?)",
            (kind, entity, str(entity_id), json.dumps(payload)),
        )

    @staticmethod
    def _identity(kind: str) -> str:
        return f"{kind}:{uuid.uuid4().hex}"

    def event(self, kind: str, entity: str, entity_id: int | str, payload: dict[str, Any]) -> None:
        with self.db:
            self._event(kind, entity, entity_id, payload)

    def runtime_settings(self):
        return self.db.execute(
            "SELECT * FROM runtime_settings ORDER BY key"
        ).fetchall()

    def update_runtime_setting(
        self, key: str, value: Any, actor: str = "Local operator"
    ) -> int:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
        with self.db:
            current = self.db.execute(
                "SELECT value_json,version FROM runtime_settings WHERE key=?", (key,)
            ).fetchone()
            previous = json.loads(current["value_json"]) if current else None
            version = int(current["version"]) + 1 if current else 1
            self.db.execute(
                """INSERT INTO runtime_setting_versions(key,version,value_json,actor)
                     VALUES(?,?,?,?)""",
                (key, version, payload, actor),
            )
            self.db.execute(
                """INSERT INTO runtime_settings(key,value_json,version)
                     VALUES(?,?,?)
                     ON CONFLICT(key) DO UPDATE SET
                         value_json=excluded.value_json,
                         version=excluded.version,
                         updated_at=CURRENT_TIMESTAMP""",
                (key, payload, version),
            )
            self._event(
                "settings.updated",
                "runtime_setting",
                key,
                {
                    "key": key,
                    "previous": previous,
                    "value": value,
                    "version": version,
                    "actor": actor,
                },
            )
        return version

    def create_project(self, name: str, description: str) -> int:
        with self.db:
            cur = self.db.execute("INSERT INTO projects(name,description) VALUES(?,?)", (name, description))
            project_id = int(cur.lastrowid)
            self._event("project.created", "project", project_id, {"name": name})
        return project_id

    def find_project(self, name: str):
        return self.db.execute("SELECT * FROM projects WHERE name=?", (name,)).fetchone()

    def create_task(self, item: WorkItem) -> int:
        identity = self._identity("work-item")
        snapshot = json.dumps(item.to_dict())
        with self.db:
            cur = self.db.execute(
                """INSERT INTO work_items(
                       identity,project_id,title,description,payload,status,kind,
                       dependencies_json,inputs_json,expected_outputs_json,
                       acceptance_criteria_json,permissions_json,budget_max_tokens,
                       budget_max_seconds,budget_max_cost_usd,artifact_ids_json,
                       github_number,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                (
                    identity,
                    item.project_id,
                    item.title,
                    item.description,
                    snapshot,
                    item.status.value,
                    item.kind,
                    json.dumps(item.dependencies),
                    json.dumps(item.inputs),
                    json.dumps(item.expected_outputs),
                    json.dumps(item.acceptance_criteria),
                    json.dumps(item.permissions),
                    item.budget.max_tokens,
                    item.budget.max_seconds,
                    item.budget.max_cost_usd,
                    json.dumps(item.artifacts),
                    item.github_number,
                ),
            )
            item.id = int(cur.lastrowid)
            self._event("task.created", "task", item.id, item.to_dict())
        return item.id

    def get_task(self, task_id: int) -> WorkItem:
        row = self.db.execute("SELECT * FROM work_items WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise KeyError(f"Unknown task: {task_id}")
        return WorkItem(
            id=int(row["id"]),
            project_id=int(row["project_id"]),
            title=str(row["title"]),
            description=str(row["description"]),
            status=Status(row["status"]),
            kind=str(row["kind"]),
            dependencies=json.loads(row["dependencies_json"]),
            inputs=json.loads(row["inputs_json"]),
            expected_outputs=json.loads(row["expected_outputs_json"]),
            acceptance_criteria=json.loads(row["acceptance_criteria_json"]),
            permissions=json.loads(row["permissions_json"]),
            budget=Budget(
                max_tokens=int(row["budget_max_tokens"]),
                max_seconds=int(row["budget_max_seconds"]),
                max_cost_usd=float(row["budget_max_cost_usd"]),
            ),
            artifacts=json.loads(row["artifact_ids_json"]),
            github_number=row["github_number"],
        )

    def transition_task(self, task_id: int, target: str) -> None:
        with self.db:
            row = self.db.execute(
                "SELECT status,version FROM work_items WHERE id=?", (task_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown task: {task_id}")
            source = str(row["status"])
            ensure_transition("work_item", source, target)
            updated = self.db.execute(
                """UPDATE work_items
                      SET status=?,version=version+1,updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status=? AND version=?""",
                (target, task_id, source, row["version"]),
            )
            if updated.rowcount != 1:
                raise ValueError(f"Work item {task_id} changed concurrently")
            self._event(
                f"task.{target}",
                "task",
                task_id,
                {"previous_state": source, "resulting_state": target},
            )

    def close(self) -> None:
        self.db.close()

    def integrity_check(self) -> dict[str, Any]:
        messages = [str(row[0]) for row in self.db.execute("PRAGMA integrity_check")]
        return {"ok": messages == ["ok"], "messages": messages}

    def online_backup(self, destination: Path) -> Path:
        destination = destination.resolve()
        if destination == self.path.resolve():
            raise ValueError("Backup destination must differ from the live database")
        if destination.exists():
            raise FileExistsError(f"Backup destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        target = sqlite3.connect(temporary)
        try:
            self.db.backup(target)
            messages = [str(row[0]) for row in target.execute("PRAGMA integrity_check")]
            if messages != ["ok"]:
                raise sqlite3.DatabaseError(f"Backup integrity check failed: {messages}")
            target.close()
            os.replace(temporary, destination)
        except Exception:
            target.close()
            temporary.unlink(missing_ok=True)
            raise
        return destination

    def stale_workflow_runs(self, older_than_seconds: int) -> list[sqlite3.Row]:
        if older_than_seconds < 0:
            raise ValueError("older_than_seconds must be non-negative")
        threshold = f"-{int(older_than_seconds)} seconds"
        return self.db.execute(
            """SELECT * FROM workflow_runs
                 WHERE status IN ('running','awaiting_approval')
                   AND created_at <= datetime('now', ?)
                 ORDER BY created_at,id""",
            (threshold,),
        ).fetchall()

    def stale_provider_attempts(self, older_than_seconds: int) -> list[sqlite3.Row]:
        if older_than_seconds < 0:
            raise ValueError("older_than_seconds must be non-negative")
        threshold = f"-{int(older_than_seconds)} seconds"
        return self.db.execute(
            """SELECT * FROM provider_execution_attempts
                 WHERE status IN ('claimed','running')
                   AND COALESCE(heartbeat_at,started_at,created_at) <= datetime('now', ?)
                 ORDER BY COALESCE(heartbeat_at,started_at,created_at),id""",
            (threshold,),
        ).fetchall()

    def start_run(self, project_id: int, task_id: int | None, workflow_id: str) -> int:
        if task_id is None:
            raise ValueError("Workflow requires a persisted work item")
        task = self.db.execute("SELECT project_id FROM work_items WHERE id=?", (task_id,)).fetchone()
        if not task:
            raise KeyError(f"Unknown task: {task_id}")
        if int(task["project_id"]) != project_id:
            raise ValueError(f"Task {task_id} does not belong to project {project_id}")
        with self.db:
            try:
                cur = self.db.execute(
                    """INSERT INTO workflow_runs(
                           identity,project_id,task_id,workflow_id,status
                       ) VALUES(?,?,?,?, 'running')""",
                    (self._identity("run"), project_id, task_id, workflow_id),
                )
                run_id = int(cur.lastrowid)
                self.db.execute(
                    """INSERT INTO workflow_stages(identity,run_id,stage_key,status)
                       VALUES(?,?,?,'running')""",
                    (self._identity("stage"), run_id, "workflow"),
                )
                self.db.execute(
                    "INSERT INTO active_workflow_claims(task_id,workflow_id,run_id) VALUES(?,?,?)",
                    (task_id, workflow_id, run_id),
                )
                self._event("workflow.started", "run", run_id, {"workflow": workflow_id})
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Active workflow already exists for task {task_id} and workflow {workflow_id}") from exc
        return run_id

    def _transition_run(self, run_id: int, target: str, *, event_payload: dict[str, Any] | None = None) -> None:
        row = self.db.execute("SELECT status,task_id,workflow_id FROM workflow_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise KeyError(f"Unknown run: {run_id}")
        source = str(row["status"])
        ensure_transition("run", source, target)
        completed = "CURRENT_TIMESTAMP" if target in {"approved", "rejected", "failed"} else "NULL"
        updated = self.db.execute(
            f"UPDATE workflow_runs SET status=?,version=version+1,completed_at={completed} WHERE id=? AND status=?",
            (target, run_id, source),
        )
        if updated.rowcount != 1:
            raise ValueError(f"Workflow run {run_id} changed concurrently")
        stage_target = {
            "awaiting_approval": "waiting_approval",
            "approved": "succeeded",
            "rejected": "failed",
            "failed": "failed",
        }[target]
        self.db.execute(
            """UPDATE workflow_stages
                  SET status=?,version=version+1,updated_at=CURRENT_TIMESTAMP
                WHERE run_id=? AND stage_key='workflow'
                  AND status IN ('running','waiting_approval')""",
            (stage_target, run_id),
        )
        if target in {"approved", "rejected", "failed"}:
            self.db.execute("DELETE FROM active_workflow_claims WHERE run_id=?", (run_id,))
            self.db.execute(
                """INSERT OR IGNORE INTO active_workflow_claims(task_id,workflow_id,run_id)
                   SELECT task_id,workflow_id,MIN(id) FROM workflow_runs
                    WHERE task_id=? AND workflow_id=?
                      AND status IN ('running','awaiting_approval')
                    GROUP BY task_id,workflow_id""",
                (row["task_id"], row["workflow_id"]),
            )
        self._event(f"workflow.{target}", "run", run_id, event_payload or {})

    def finish_run(self, run_id: int, status: str, *, event_payload: dict[str, Any] | None = None) -> None:
        with self.db:
            self._transition_run(run_id, status, event_payload=event_payload)

    def create_approval_gate(self, run_id: int) -> int:
        with self.db:
            self._transition_run(run_id, "awaiting_approval")
            cur = self.db.execute("INSERT INTO approval_gates(run_id) VALUES(?)", (run_id,))
            gate_id = int(cur.lastrowid)
            self._event("approval.requested", "approval", gate_id, {"run_id": run_id})
        return gate_id

    def approvals(self):
        return self.db.execute("SELECT * FROM approval_gates ORDER BY id").fetchall()

    def decide_approval(
        self, gate_id: int, decision: str, note: str, actor: str = "Founder"
    ) -> bool:
        if decision not in {"approved", "rejected"}:
            raise ValueError(decision)
        with self.db:
            gate = self.db.execute("SELECT run_id,status FROM approval_gates WHERE id=?", (gate_id,)).fetchone()
            if not gate:
                raise KeyError(f"Unknown approval: {gate_id}")
            if gate["status"] == decision:
                return False
            if gate["status"] != "pending":
                raise ValueError(f"Approval {gate_id} is already {gate['status']}")
            updated = self.db.execute(
                "UPDATE approval_gates SET status=?,decision_note=?,decided_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'",
                (decision, note, gate_id),
            )
            if updated.rowcount != 1:
                current = self.db.execute(
                    "SELECT status FROM approval_gates WHERE id=?", (gate_id,)
                ).fetchone()
                if current and current["status"] == decision:
                    return False
                raise ValueError(f"Approval {gate_id} was decided concurrently")
            self._transition_run(int(gate["run_id"]), decision, event_payload={"approval_gate_id": gate_id})
            decided_at = self.db.execute(
                "SELECT decided_at FROM approval_gates WHERE id=?", (gate_id,)
            ).fetchone()[0]
            self._event(
                f"approval.{decision}",
                "approval",
                gate_id,
                {
                    "note": note,
                    "actor": actor,
                    "timestamp": decided_at,
                    "target": {"type": "workflow_run", "id": int(gate["run_id"])},
                    "previous_state": "pending",
                    "resulting_state": decision,
                },
            )
        return True

    def add_artifact(self, run_id: int, stage: str, agent_id: str, provider: str, content: str) -> int:
        with self.db:
            cur = self.db.execute(
                """INSERT INTO artifacts(identity,run_id,stage,agent_id,provider,content)
                   VALUES(?,?,?,?,?,?)""",
                (self._identity("artifact"), run_id, stage, agent_id, provider, content),
            )
            artifact_id = int(cur.lastrowid)
            self._event("artifact.created", "artifact", artifact_id, {"stage": stage, "provider": provider})
        return artifact_id

    def latest_run(self):
        return self.db.execute("SELECT * FROM workflow_runs ORDER BY id DESC LIMIT 1").fetchone()

    def artifacts(self, run_id: int):
        return self.db.execute("SELECT * FROM artifacts WHERE run_id=? ORDER BY id", (run_id,)).fetchall()

    def reviewer_assignments(self, run_id: int | None = None):
        if run_id is None:
            return self.db.execute(
                "SELECT * FROM reviewer_assignments ORDER BY id"
            ).fetchall()
        return self.db.execute(
            "SELECT * FROM reviewer_assignments WHERE run_id=? ORDER BY id",
            (run_id,),
        ).fetchall()

    def reviewer_usage(
        self, stage: str, candidate_ids: list[str]
    ) -> dict[str, tuple[int, int]]:
        if not candidate_ids:
            return {}
        placeholders = ",".join("?" for _ in candidate_ids)
        rows = self.db.execute(
            f"""SELECT reviewer_agent_id,COUNT(*) AS uses,MAX(id) AS last_id
                   FROM reviewer_assignments
                  WHERE stage=? AND reviewer_agent_id IN ({placeholders})
                  GROUP BY reviewer_agent_id""",
            (stage, *candidate_ids),
        ).fetchall()
        return {
            str(row["reviewer_agent_id"]): (int(row["uses"]), int(row["last_id"]))
            for row in rows
        }

    def latest_reviewer_assignment(self, stage: str):
        return self.db.execute(
            """SELECT * FROM reviewer_assignments
                 WHERE stage=? ORDER BY id DESC LIMIT 1""",
            (stage,),
        ).fetchone()

    def record_reviewer_assignment(
        self,
        *,
        run_id: int,
        stage: str,
        reviewer: Any,
        subjects: list[Any],
        excluded_models: list[str],
        excluded_candidates: dict[str, str],
        strategy: str,
    ) -> int:
        producer_agents = [
            {
                "stage": subject.stage,
                "agent_id": subject.producer.id,
                "provider": subject.producer.provider,
                "model": subject.producer.model_identity,
            }
            for subject in subjects
        ]
        with self.db:
            cur = self.db.execute(
                """INSERT INTO reviewer_assignments(
                       run_id,stage,reviewer_agent_id,reviewer_provider,reviewer_model,
                       reviewed_stages,reviewed_artifact_ids,producer_agents,
                       excluded_models,excluded_candidates,strategy
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    stage,
                    reviewer.id,
                    reviewer.provider,
                    reviewer.model_identity,
                    json.dumps([subject.stage for subject in subjects]),
                    json.dumps([subject.artifact_id for subject in subjects]),
                    json.dumps(producer_agents, sort_keys=True),
                    json.dumps(excluded_models),
                    json.dumps(excluded_candidates, sort_keys=True),
                    strategy,
                ),
            )
            assignment_id = int(cur.lastrowid)
            self._event(
                "reviewer.assigned",
                "review_assignment",
                assignment_id,
                {
                    "run_id": run_id,
                    "stage": stage,
                    "reviewer_agent_id": reviewer.id,
                    "reviewer_provider": reviewer.provider,
                    "reviewer_model": reviewer.model_identity,
                    "producer_agents": producer_agents,
                    "strategy": strategy,
                },
            )
        return assignment_id

    def complete_reviewer_assignment(
        self,
        *,
        run_id: int,
        stage: str,
        review_artifact_id: int,
        verdict: str,
    ) -> None:
        with self.db:
            updated = self.db.execute(
                """UPDATE reviewer_assignments
                      SET review_artifact_id=?,verdict=?,completed_at=CURRENT_TIMESTAMP
                    WHERE run_id=? AND stage=? AND completed_at IS NULL""",
                (review_artifact_id, verdict, run_id, stage),
            )
            if updated.rowcount != 1:
                raise ValueError(
                    f"Reviewer assignment for run {run_id} stage {stage} is missing or complete"
                )
            assignment = self.db.execute(
                "SELECT id,reviewer_agent_id,reviewer_model FROM reviewer_assignments WHERE run_id=? AND stage=?",
                (run_id, stage),
            ).fetchone()
            self._event(
                "reviewer.review.completed",
                "review_assignment",
                int(assignment["id"]),
                {
                    "review_artifact_id": review_artifact_id,
                    "reviewer_agent_id": assignment["reviewer_agent_id"],
                    "reviewer_model": assignment["reviewer_model"],
                    "verdict": verdict,
                },
            )

    def review_artifact(self, artifact_id: int, status: str, note: str) -> None:
        if status not in {"approved", "rejected"}:
            raise ValueError(status)
        with self.db:
            ensure_transition("artifact", "pending", status)
            updated = self.db.execute(
                "UPDATE artifacts SET status=?,review_note=?,version=version+1 WHERE id=? AND status='pending'",
                (status, note, artifact_id),
            )
            if updated.rowcount != 1:
                row = self.db.execute("SELECT status FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
                if not row:
                    raise KeyError(f"Unknown artifact: {artifact_id}")
                raise ValueError(f"Artifact {artifact_id} is already {row['status']}")
            self._event(f"artifact.{status}", "artifact", artifact_id, {"note": note})

    # Provider approvals bind immutable snapshots to durable, one-use attempts.
    def request_provider_execution(
        self,
        provider: str,
        agent_id: str,
        task_id: int,
        request_hash: str,
        definition_hash: str,
    ) -> int:
        request_hash = _sha256_snapshot(request_hash, "request_hash")
        definition_hash = _sha256_snapshot(definition_hash, "definition_hash")
        if not self.db.execute("SELECT id FROM work_items WHERE id=?", (task_id,)).fetchone():
            raise KeyError(f"Unknown task: {task_id}")
        with self.db:
            try:
                cur = self.db.execute(
                    """INSERT INTO provider_execution_gates(
                           provider,agent_id,task_id,request_hash,definition_hash
                       ) VALUES(?,?,?,?,?)""",
                    (provider, agent_id, task_id, request_hash, definition_hash),
                )
                gate_id = int(cur.lastrowid)
                self.db.execute(
                    "INSERT INTO pending_provider_gate_claims(provider,agent_id,task_id,gate_id) VALUES(?,?,?,?)",
                    (provider, agent_id, task_id, gate_id),
                )
                self._event(
                    "provider.execution.requested",
                    "provider_gate",
                    gate_id,
                    {
                        "provider": provider,
                        "agent_id": agent_id,
                        "task_id": task_id,
                        "request_hash": request_hash,
                        "definition_hash": definition_hash,
                    },
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Pending provider gate already exists for {provider}/{agent_id}/task {task_id}") from exc
        return gate_id

    def provider_execution_gates(self):
        return self.db.execute("SELECT * FROM provider_execution_gates ORDER BY id").fetchall()

    def decide_provider_execution(self, gate_id: int, decision: str, note: str) -> None:
        if decision not in {"approved", "rejected"}:
            raise ValueError(decision)
        with self.db:
            row = self.db.execute("SELECT * FROM provider_execution_gates WHERE id=?", (gate_id,)).fetchone()
            if not row:
                raise KeyError(f"Unknown provider gate: {gate_id}")
            if row["status"] != "pending":
                raise ValueError(f"Provider gate {gate_id} is already {row['status']}")
            updated = self.db.execute("UPDATE provider_execution_gates SET status=?,decision_note=?,decided_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'", (decision, note, gate_id))
            if updated.rowcount != 1:
                raise ValueError(f"Provider gate {gate_id} was decided concurrently")
            self.db.execute("DELETE FROM pending_provider_gate_claims WHERE gate_id=?", (gate_id,))
            self.db.execute(
                """INSERT OR IGNORE INTO pending_provider_gate_claims(provider,agent_id,task_id,gate_id)
                   SELECT provider,agent_id,task_id,MIN(id) FROM provider_execution_gates
                    WHERE provider=? AND agent_id=? AND task_id=? AND status='pending'
                    GROUP BY provider,agent_id,task_id""",
                (row["provider"], row["agent_id"], row["task_id"]),
            )
            self._event(f"provider.execution.{decision}", "provider_gate", gate_id, {"note": note, "approved_by": "Human"})

    def cancel_provider_execution(self, gate_id: int, note: str) -> None:
        """Revoke an unused pending or approved one-time execution gate."""
        with self.db:
            row = self.db.execute("SELECT * FROM provider_execution_gates WHERE id=?", (gate_id,)).fetchone()
            if not row:
                raise KeyError(f"Unknown provider gate: {gate_id}")
            if row["status"] not in {"pending", "approved"}:
                raise ValueError(f"Provider gate {gate_id} is already {row['status']}")
            updated = self.db.execute(
                "UPDATE provider_execution_gates SET status='rejected',decision_note=?,decided_at=CURRENT_TIMESTAMP WHERE id=? AND status IN ('pending','approved')",
                (note, gate_id),
            )
            if updated.rowcount != 1:
                raise ValueError(f"Provider gate {gate_id} changed concurrently")
            self.db.execute("DELETE FROM pending_provider_gate_claims WHERE gate_id=?", (gate_id,))
            self._event(
                "provider.execution.cancelled",
                "provider_gate",
                gate_id,
                {"note": note, "approved_by": "Human", "previous_status": row["status"]},
            )

    def claim_provider_execution(self, gate_id: int, request_hash: str, definition_hash: str):
        request_hash = _sha256_snapshot(request_hash, "request_hash")
        definition_hash = _sha256_snapshot(definition_hash, "definition_hash")
        mismatch_error: str | None = None
        attempt_id: int | None = None
        with self.db:
            updated = self.db.execute(
                """UPDATE provider_execution_gates
                      SET status='claimed'
                    WHERE id=? AND status='approved'
                      AND request_hash=? AND definition_hash=?""",
                (gate_id, request_hash, definition_hash),
            )
            row = self.db.execute(
                "SELECT * FROM provider_execution_gates WHERE id=?", (gate_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown provider gate: {gate_id}")
            if updated.rowcount != 1:
                if row["status"] != "approved":
                    raise PermissionError(
                        f"Provider gate {gate_id} is {row['status']}, expected approved"
                    )
                note = (
                    "Approval snapshot no longer matches the current request or "
                    "provider policy; request a new gate."
                )
                invalidated = self.db.execute(
                    """UPDATE provider_execution_gates
                          SET status='rejected',
                              decision_note=CASE
                                  WHEN decision_note='' THEN ?
                                  ELSE decision_note || char(10) || ?
                              END,
                              decided_at=COALESCE(decided_at,CURRENT_TIMESTAMP)
                        WHERE id=? AND status='approved'""",
                    (note, note, gate_id),
                )
                if invalidated.rowcount != 1:
                    raise PermissionError(
                        f"Provider gate {gate_id} changed concurrently"
                    )
                self.db.execute(
                    "DELETE FROM pending_provider_gate_claims WHERE gate_id=?",
                    (gate_id,),
                )
                self._event(
                    "provider.execution.snapshot_mismatch",
                    "provider_gate",
                    gate_id,
                    {
                        "expected_request_hash": row["request_hash"],
                        "actual_request_hash": request_hash,
                        "expected_definition_hash": row["definition_hash"],
                        "actual_definition_hash": definition_hash,
                    },
                )
                mismatch_error = note
            else:
                cur = self.db.execute(
                    """INSERT INTO provider_execution_attempts(
                           identity,gate_id,provider,agent_id,task_id,request_hash,
                           definition_hash,status
                       ) VALUES(?,?,?,?,?,?,?,'claimed')""",
                    (
                        self._identity("provider-attempt"),
                        gate_id,
                        row["provider"],
                        row["agent_id"],
                        row["task_id"],
                        request_hash,
                        definition_hash,
                    ),
                )
                attempt_id = int(cur.lastrowid)
                assignment = self.db.execute(
                    """INSERT INTO assignments(
                           identity,task_id,agent_id,runtime,status
                       ) VALUES(?,?,?,?, 'active') RETURNING id""",
                    (
                        self._identity("assignment"),
                        row["task_id"],
                        row["agent_id"],
                        row["provider"],
                    ),
                ).fetchone()
                assignment_id = int(assignment["id"])
                self.db.execute(
                    """INSERT INTO worker_sessions(
                           identity,assignment_id,runtime,status
                       ) VALUES(?,?,?,'starting')""",
                    (self._identity("worker-session"), assignment_id, row["provider"]),
                )
                self.db.execute(
                    """INSERT INTO attempts(
                           identity,assignment_id,provider_attempt_id,ordinal,status
                       ) VALUES(?,?,?,?, 'claimed')""",
                    (self._identity("attempt"), assignment_id, attempt_id, 1),
                )
                self._event(
                    "provider.execution.claimed",
                    "provider_attempt",
                    attempt_id,
                    {
                        "gate_id": gate_id,
                        "request_hash": request_hash,
                        "definition_hash": definition_hash,
                    },
                )
        if mismatch_error is not None:
            raise PermissionError(mismatch_error)
        if attempt_id is None:
            raise RuntimeError("Provider gate claim did not create an attempt")
        return self.db.execute("SELECT * FROM provider_execution_attempts WHERE id=?", (attempt_id,)).fetchone()

    def consume_provider_execution(self, gate_id: int):
        """Compatibility alias: a caller must use claim_provider_execution with hashes."""
        raise RuntimeError("use claim_provider_execution(gate_id, request_hash, definition_hash)")

    def mark_provider_attempt_running(self, attempt_id: int, pid: int | None = None) -> None:
        with self.db:
            ensure_transition("attempt", "claimed", "running")
            updated = self.db.execute("UPDATE provider_execution_attempts SET status='running',version=version+1,pid=?,started_at=CURRENT_TIMESTAMP,heartbeat_at=CURRENT_TIMESTAMP WHERE id=? AND status='claimed'", (pid, attempt_id))
            if updated.rowcount != 1: raise ValueError(f"Attempt {attempt_id} is not claimed")
            self.db.execute(
                """UPDATE attempts SET status='running',version=version+1,updated_at=CURRENT_TIMESTAMP
                    WHERE provider_attempt_id=? AND status='claimed'""",
                (attempt_id,),
            )
            self.db.execute(
                """UPDATE worker_sessions SET status='running',version=version+1,updated_at=CURRENT_TIMESTAMP
                    WHERE assignment_id=(SELECT assignment_id FROM attempts WHERE provider_attempt_id=?)
                      AND status='starting'""",
                (attempt_id,),
            )
            self._event("provider.execution.running", "provider_attempt", attempt_id, {"pid": pid})

    def finish_provider_attempt(self, attempt_id: int, status: str, result: str, metadata: dict[str, Any]) -> int:
        if status not in {"succeeded", "failed", "abandoned"}: raise ValueError(status)
        bounded_result = result[:100_000]
        with self.db:
            row = self.db.execute("SELECT * FROM provider_execution_attempts WHERE id=?", (attempt_id,)).fetchone()
            if not row: raise KeyError(f"Unknown attempt: {attempt_id}")
            if row["status"] not in {"claimed", "running"}: raise ValueError(f"Attempt {attempt_id} is already {row['status']}")
            ensure_transition("attempt", str(row["status"]), status)
            self.db.execute("UPDATE provider_execution_attempts SET status=?,version=version+1,result=?,metadata=?,finished_at=CURRENT_TIMESTAMP,heartbeat_at=CURRENT_TIMESTAMP WHERE id=?", (status, bounded_result, json.dumps(metadata), attempt_id))
            self.db.execute("UPDATE provider_execution_gates SET status='consumed',consumed_at=CURRENT_TIMESTAMP WHERE id=? AND status='claimed'", (row["gate_id"],))
            content = bounded_result if status == "succeeded" else ""
            cur = self.db.execute("INSERT INTO provider_execution_artifacts(identity,gate_id,attempt_id,provider,agent_id,content,metadata,status) VALUES(?,?,?,?,?,?,?,?)", (self._identity("provider-artifact"), row["gate_id"], attempt_id, row["provider"], row["agent_id"], content, json.dumps(metadata), status))
            artifact_id = int(cur.lastrowid)
            assignment_status = "cancelled" if status == "abandoned" else status
            session_status = "cancelled" if status == "abandoned" else status
            self.db.execute(
                """UPDATE attempts SET status=?,version=version+1,updated_at=CURRENT_TIMESTAMP
                    WHERE provider_attempt_id=? AND status IN ('claimed','running')""",
                (status, attempt_id),
            )
            self.db.execute(
                """UPDATE assignments SET status=?,version=version+1,updated_at=CURRENT_TIMESTAMP
                    WHERE id=(SELECT assignment_id FROM attempts WHERE provider_attempt_id=?)
                      AND status='active'""",
                (assignment_status, attempt_id),
            )
            self.db.execute(
                """UPDATE worker_sessions SET status='running',version=version+1,updated_at=CURRENT_TIMESTAMP
                    WHERE assignment_id=(SELECT assignment_id FROM attempts WHERE provider_attempt_id=?)
                      AND status='starting' AND ?='succeeded'""",
                (attempt_id, status),
            )
            self.db.execute(
                """UPDATE worker_sessions SET status=?,version=version+1,updated_at=CURRENT_TIMESTAMP
                    WHERE assignment_id=(SELECT assignment_id FROM attempts WHERE provider_attempt_id=?)
                      AND status IN ('starting','running')""",
                (session_status, attempt_id),
            )
            self._event(f"provider.execution.{status}", "provider_attempt", attempt_id, {"artifact_id": artifact_id})
        return artifact_id

    def reconcile_provider_attempts(self) -> list[int]:
        rows = self.db.execute("SELECT id FROM provider_execution_attempts WHERE status IN ('claimed','running')").fetchall()
        reconciled = []
        for row in rows:
            attempt_id = int(row["id"])
            self.finish_provider_attempt(attempt_id, "abandoned", "Interrupted before a durable terminal result", {"reconciled": True, "retry_requires_new_gate": True})
            reconciled.append(attempt_id)
        return reconciled

    def add_provider_artifact(self, gate_id: int, provider: str, agent_id: str, content: str, metadata: dict[str, Any]) -> int:
        with self.db:
            cur = self.db.execute("INSERT INTO provider_execution_artifacts(identity,gate_id,provider,agent_id,content,metadata) VALUES(?,?,?,?,?,?)", (self._identity("provider-artifact"), gate_id, provider, agent_id, content, json.dumps(metadata)))
            artifact_id = int(cur.lastrowid)
            self._event("provider.artifact.created", "provider_artifact", artifact_id, {"gate_id": gate_id, "provider": provider, "agent_id": agent_id})
        return artifact_id

    def provider_artifacts(self):
        return self.db.execute("SELECT * FROM provider_execution_artifacts ORDER BY id").fetchall()

    def create_github_plan(self, repo: str, operations: list[dict[str, Any]]) -> tuple[int, str]:
        import hashlib
        if not repo or "/" not in repo:
            raise ValueError("GitHub plan requires owner/repository")
        keys = [str(op.get("idempotency_key", "")) for op in operations]
        if not operations or any(not key for key in keys) or len(keys) != len(set(keys)):
            raise ValueError("Operations require unique non-empty idempotency keys")
        document = {"version": 1, "repo": repo, "operations": operations}
        payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        plan_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with self.db:
            existing = self.db.execute("SELECT id FROM github_mutation_plans WHERE plan_hash=?", (plan_hash,)).fetchone()
            if existing:
                return int(existing["id"]), plan_hash
            cur = self.db.execute("INSERT INTO github_mutation_plans(repo,plan_json,plan_hash) VALUES(?,?,?)", (repo, payload, plan_hash))
            plan_id = int(cur.lastrowid)
            self._event("github.plan.created", "github_plan", plan_id, {"repo": repo, "plan_hash": plan_hash, "operation_count": len(operations)})
        return plan_id, plan_hash

    def github_plan(self, plan_id: int):
        row = self.db.execute("SELECT * FROM github_mutation_plans WHERE id=?", (plan_id,)).fetchone()
        if not row:
            raise KeyError(f"Unknown GitHub plan: {plan_id}")
        return row

    def request_github_gate(self, plan_id: int) -> int:
        plan = self.github_plan(plan_id)
        with self.db:
            cur = self.db.execute("INSERT INTO github_mutation_gates(plan_id,repo,plan_hash) VALUES(?,?,?)", (plan_id, plan["repo"], plan["plan_hash"]))
            gate_id = int(cur.lastrowid)
            self._event("github.gate.requested", "github_gate", gate_id, {"plan_id": plan_id, "repo": plan["repo"], "plan_hash": plan["plan_hash"]})
        return gate_id

    def github_gates(self):
        return self.db.execute("SELECT * FROM github_mutation_gates ORDER BY id").fetchall()

    def decide_github_gate(self, gate_id: int, decision: str, note: str) -> None:
        if decision not in {"approved", "rejected"}:
            raise ValueError(decision)
        with self.db:
            updated = self.db.execute("UPDATE github_mutation_gates SET status=?,decision_note=?,decided_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'", (decision, note, gate_id))
            if updated.rowcount != 1:
                row = self.db.execute("SELECT status FROM github_mutation_gates WHERE id=?", (gate_id,)).fetchone()
                if not row: raise KeyError(f"Unknown GitHub gate: {gate_id}")
                raise ValueError(f"GitHub gate {gate_id} is already {row['status']}")
            self._event(f"github.gate.{decision}", "github_gate", gate_id, {"note": note, "approved_by": "Human"})

    def claim_github_gate(self, gate_id: int, plan_id: int, repo: str, plan_hash: str):
        with self.db:
            row = self.db.execute("SELECT * FROM github_mutation_gates WHERE id=?", (gate_id,)).fetchone()
            if not row: raise KeyError(f"Unknown GitHub gate: {gate_id}")
            if (int(row["plan_id"]), row["repo"], row["plan_hash"]) != (plan_id, repo, plan_hash):
                raise PermissionError("Approval gate does not match plan repository and SHA-256")
            updated = self.db.execute("UPDATE github_mutation_gates SET status='claimed' WHERE id=? AND status='approved'", (gate_id,))
            if updated.rowcount != 1: raise PermissionError(f"GitHub gate {gate_id} is {row['status']}, expected approved")
            self._event("github.gate.claimed", "github_gate", gate_id, {"plan_id": plan_id, "repo": repo, "plan_hash": plan_hash})
        return row

    def github_completed_keys(self, repo: str) -> set[str]:
        return {str(row[0]) for row in self.db.execute("SELECT idempotency_key FROM github_idempotency WHERE repo=?", (repo,))}

    def finish_github_apply(self, gate_id: int, plan_id: int, report: dict[str, Any]) -> int:
        results = list(report.get("results", []))
        failures = [r for r in results if not r.get("ok") and not r.get("skipped")]
        successes = [r for r in results if r.get("ok")]
        status = "partial" if failures and successes else ("failed" if failures or not report.get("ok", False) else "succeeded")
        with self.db:
            gate = self.db.execute("SELECT * FROM github_mutation_gates WHERE id=?", (gate_id,)).fetchone()
            if not gate or gate["status"] != "claimed" or int(gate["plan_id"]) != plan_id:
                raise PermissionError("GitHub gate is not claimed for this plan")
            for result in successes:
                self.db.execute("INSERT OR IGNORE INTO github_idempotency(repo,idempotency_key,result_json) VALUES(?,?,?)", (gate["repo"], result["idempotency_key"], json.dumps(result, sort_keys=True)))
            cur = self.db.execute("INSERT INTO github_mutation_reports(gate_id,plan_id,status,report_json) VALUES(?,?,?,?)", (gate_id, plan_id, status, json.dumps(report, sort_keys=True)))
            report_id = int(cur.lastrowid)
            self.db.execute("UPDATE github_mutation_gates SET status='consumed',consumed_at=CURRENT_TIMESTAMP WHERE id=? AND status='claimed'", (gate_id,))
            self._event(f"github.apply.{status}", "github_report", report_id, {"gate_id": gate_id, "plan_id": plan_id, "successes": len(successes), "failures": len(failures)})
        return report_id
