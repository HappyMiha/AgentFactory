from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

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
)

RUN_TRANSITIONS = {
    "running": {"awaiting_approval", "failed"},
    "awaiting_approval": {"approved", "rejected"},
}


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

    def event(self, kind: str, entity: str, entity_id: int | str, payload: dict[str, Any]) -> None:
        with self.db:
            self._event(kind, entity, entity_id, payload)

    def create_project(self, name: str, description: str) -> int:
        with self.db:
            cur = self.db.execute("INSERT INTO projects(name,description) VALUES(?,?)", (name, description))
            project_id = int(cur.lastrowid)
            self._event("project.created", "project", project_id, {"name": name})
        return project_id

    def find_project(self, name: str):
        return self.db.execute("SELECT * FROM projects WHERE name=?", (name,)).fetchone()

    def create_task(self, item: WorkItem) -> int:
        with self.db:
            cur = self.db.execute(
                "INSERT INTO work_items(project_id,title,description,payload,status) VALUES(?,?,?,?,?)",
                (item.project_id, item.title, item.description, json.dumps(item.to_dict()), item.status.value),
            )
            item.id = int(cur.lastrowid)
            self._event("task.created", "task", item.id, item.to_dict())
        return item.id

    def get_task(self, task_id: int) -> WorkItem:
        row = self.db.execute("SELECT * FROM work_items WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise KeyError(f"Unknown task: {task_id}")
        payload = json.loads(row["payload"])
        payload["id"] = int(row["id"])
        payload["budget"] = Budget(**payload["budget"])
        payload["status"] = Status(row["status"])
        return WorkItem(**payload)

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
                    "INSERT INTO workflow_runs(project_id,task_id,workflow_id,status) VALUES(?,?,?,'running')",
                    (project_id, task_id, workflow_id),
                )
                run_id = int(cur.lastrowid)
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
        if target not in RUN_TRANSITIONS.get(source, set()):
            raise ValueError(f"Invalid workflow transition: {source} -> {target}")
        completed = "CURRENT_TIMESTAMP" if target in {"approved", "rejected", "failed"} else "NULL"
        updated = self.db.execute(
            f"UPDATE workflow_runs SET status=?,completed_at={completed} WHERE id=? AND status=?",
            (target, run_id, source),
        )
        if updated.rowcount != 1:
            raise ValueError(f"Workflow run {run_id} changed concurrently")
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

    def decide_approval(self, gate_id: int, decision: str, note: str) -> None:
        if decision not in {"approved", "rejected"}:
            raise ValueError(decision)
        with self.db:
            gate = self.db.execute("SELECT run_id,status FROM approval_gates WHERE id=?", (gate_id,)).fetchone()
            if not gate:
                raise KeyError(f"Unknown approval: {gate_id}")
            if gate["status"] != "pending":
                raise ValueError(f"Approval {gate_id} is already {gate['status']}")
            updated = self.db.execute(
                "UPDATE approval_gates SET status=?,decision_note=?,decided_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'",
                (decision, note, gate_id),
            )
            if updated.rowcount != 1:
                raise ValueError(f"Approval {gate_id} was decided concurrently")
            self._transition_run(int(gate["run_id"]), decision, event_payload={"approval_gate_id": gate_id})
            self._event(f"approval.{decision}", "approval", gate_id, {"note": note, "approved_by": "Human"})

    def add_artifact(self, run_id: int, stage: str, agent_id: str, provider: str, content: str) -> int:
        with self.db:
            cur = self.db.execute("INSERT INTO artifacts(run_id,stage,agent_id,provider,content) VALUES(?,?,?,?,?)", (run_id, stage, agent_id, provider, content))
            artifact_id = int(cur.lastrowid)
            self._event("artifact.created", "artifact", artifact_id, {"stage": stage, "provider": provider})
        return artifact_id

    def latest_run(self):
        return self.db.execute("SELECT * FROM workflow_runs ORDER BY id DESC LIMIT 1").fetchone()

    def artifacts(self, run_id: int):
        return self.db.execute("SELECT * FROM artifacts WHERE run_id=? ORDER BY id", (run_id,)).fetchall()

    def review_artifact(self, artifact_id: int, status: str, note: str) -> None:
        if status not in {"approved", "rejected"}:
            raise ValueError(status)
        with self.db:
            updated = self.db.execute(
                "UPDATE artifacts SET status=?,review_note=? WHERE id=? AND status='pending'",
                (status, note, artifact_id),
            )
            if updated.rowcount != 1:
                row = self.db.execute("SELECT status FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
                if not row:
                    raise KeyError(f"Unknown artifact: {artifact_id}")
                raise ValueError(f"Artifact {artifact_id} is already {row['status']}")
            self._event(f"artifact.{status}", "artifact", artifact_id, {"note": note})

    # Provider execution methods remain compatible; runtime-attempt hardening is Wave 2.
    def request_provider_execution(self, provider: str, agent_id: str, task_id: int) -> int:
        if not self.db.execute("SELECT id FROM work_items WHERE id=?", (task_id,)).fetchone():
            raise KeyError(f"Unknown task: {task_id}")
        with self.db:
            try:
                cur = self.db.execute("INSERT INTO provider_execution_gates(provider,agent_id,task_id) VALUES(?,?,?)", (provider, agent_id, task_id))
                gate_id = int(cur.lastrowid)
                self.db.execute(
                    "INSERT INTO pending_provider_gate_claims(provider,agent_id,task_id,gate_id) VALUES(?,?,?,?)",
                    (provider, agent_id, task_id, gate_id),
                )
                self._event("provider.execution.requested", "provider_gate", gate_id, {"provider": provider, "agent_id": agent_id, "task_id": task_id})
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
        with self.db:
            row = self.db.execute("SELECT * FROM provider_execution_gates WHERE id=?", (gate_id,)).fetchone()
            if not row:
                raise KeyError(f"Unknown provider gate: {gate_id}")
            if row["status"] != "approved":
                raise PermissionError(f"Provider gate {gate_id} is {row['status']}, expected approved")
            updated = self.db.execute("UPDATE provider_execution_gates SET status='claimed' WHERE id=? AND status='approved'", (gate_id,))
            if updated.rowcount != 1:
                raise PermissionError(f"Provider gate {gate_id} was already claimed")
            cur = self.db.execute(
                "INSERT INTO provider_execution_attempts(gate_id,provider,agent_id,task_id,request_hash,definition_hash,status) VALUES(?,?,?,?,?,?,'claimed')",
                (gate_id, row["provider"], row["agent_id"], row["task_id"], request_hash, definition_hash),
            )
            attempt_id = int(cur.lastrowid)
            self._event("provider.execution.claimed", "provider_attempt", attempt_id, {"gate_id": gate_id, "request_hash": request_hash, "definition_hash": definition_hash})
        return self.db.execute("SELECT * FROM provider_execution_attempts WHERE id=?", (attempt_id,)).fetchone()

    def consume_provider_execution(self, gate_id: int):
        """Compatibility alias: a caller must use claim_provider_execution with hashes."""
        raise RuntimeError("use claim_provider_execution(gate_id, request_hash, definition_hash)")

    def mark_provider_attempt_running(self, attempt_id: int, pid: int | None = None) -> None:
        with self.db:
            updated = self.db.execute("UPDATE provider_execution_attempts SET status='running',pid=?,started_at=CURRENT_TIMESTAMP,heartbeat_at=CURRENT_TIMESTAMP WHERE id=? AND status='claimed'", (pid, attempt_id))
            if updated.rowcount != 1: raise ValueError(f"Attempt {attempt_id} is not claimed")
            self._event("provider.execution.running", "provider_attempt", attempt_id, {"pid": pid})

    def finish_provider_attempt(self, attempt_id: int, status: str, result: str, metadata: dict[str, Any]) -> int:
        if status not in {"succeeded", "failed", "abandoned"}: raise ValueError(status)
        bounded_result = result[:100_000]
        with self.db:
            row = self.db.execute("SELECT * FROM provider_execution_attempts WHERE id=?", (attempt_id,)).fetchone()
            if not row: raise KeyError(f"Unknown attempt: {attempt_id}")
            if row["status"] not in {"claimed", "running"}: raise ValueError(f"Attempt {attempt_id} is already {row['status']}")
            self.db.execute("UPDATE provider_execution_attempts SET status=?,result=?,metadata=?,finished_at=CURRENT_TIMESTAMP,heartbeat_at=CURRENT_TIMESTAMP WHERE id=?", (status, bounded_result, json.dumps(metadata), attempt_id))
            self.db.execute("UPDATE provider_execution_gates SET status='consumed',consumed_at=CURRENT_TIMESTAMP WHERE id=? AND status='claimed'", (row["gate_id"],))
            content = bounded_result if status == "succeeded" else ""
            cur = self.db.execute("INSERT INTO provider_execution_artifacts(gate_id,attempt_id,provider,agent_id,content,metadata,status) VALUES(?,?,?,?,?,?,?)", (row["gate_id"], attempt_id, row["provider"], row["agent_id"], content, json.dumps(metadata), status))
            artifact_id = int(cur.lastrowid)
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
            cur = self.db.execute("INSERT INTO provider_execution_artifacts(gate_id,provider,agent_id,content,metadata) VALUES(?,?,?,?,?)", (gate_id, provider, agent_id, content, json.dumps(metadata)))
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
