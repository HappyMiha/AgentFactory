from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .lifecycle import TRANSITIONS, ensure_transition
from .models import AssignmentLease, Budget, Status, WorkItem

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
    (10, """
        ALTER TABLE events ADD COLUMN identity TEXT;
        ALTER TABLE events ADD COLUMN correlation_root TEXT;
        ALTER TABLE events ADD COLUMN correlation_json TEXT;
        ALTER TABLE events ADD COLUMN previous_hash TEXT;
        ALTER TABLE events ADD COLUMN record_hash TEXT;

        CREATE TABLE outbox_messages(
            id INTEGER PRIMARY KEY,
            identity TEXT NOT NULL UNIQUE,
            event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
            topic TEXT NOT NULL,
            payload TEXT NOT NULL,
            correlation_json TEXT NOT NULL,
            delivery_key TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','dispatching','delivered','failed')),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
            available_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            claimed_by TEXT,
            claim_token TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            delivered_at TEXT
        );
        CREATE INDEX idx_outbox_ready
            ON outbox_messages(status,available_at,id);
        CREATE TRIGGER outbox_valid_transition
        BEFORE UPDATE OF status ON outbox_messages
        WHEN NOT (
            (OLD.status IN ('pending','failed') AND NEW.status='dispatching') OR
            (OLD.status='dispatching' AND NEW.status IN ('delivered','failed'))
        )
        BEGIN SELECT RAISE(ABORT, 'invalid outbox transition'); END;
    """),
    (11, """
        ALTER TABLE artifacts ADD COLUMN digest TEXT;
        ALTER TABLE artifacts ADD COLUMN producer_json TEXT;
        ALTER TABLE artifacts ADD COLUMN verifier_json TEXT;
        ALTER TABLE artifacts ADD COLUMN inputs_json TEXT;
        ALTER TABLE artifacts ADD COLUMN toolchain_json TEXT;
        ALTER TABLE artifacts ADD COLUMN evidence_kind TEXT NOT NULL DEFAULT 'review';

        ALTER TABLE provider_execution_artifacts ADD COLUMN digest TEXT;
        ALTER TABLE provider_execution_artifacts ADD COLUMN producer_json TEXT;
        ALTER TABLE provider_execution_artifacts ADD COLUMN verifier_json TEXT;
        ALTER TABLE provider_execution_artifacts ADD COLUMN inputs_json TEXT;
        ALTER TABLE provider_execution_artifacts ADD COLUMN toolchain_json TEXT;

        CREATE TABLE criterion_evidence(
            id INTEGER PRIMARY KEY,
            identity TEXT NOT NULL UNIQUE,
            task_id INTEGER NOT NULL REFERENCES work_items(id),
            criterion_index INTEGER NOT NULL CHECK(criterion_index >= 0),
            criterion_text TEXT NOT NULL,
            artifact_id INTEGER NOT NULL REFERENCES artifacts(id),
            evidence_type TEXT NOT NULL
                CHECK(evidence_type IN ('test_result','diff','review','summary')),
            primary_evidence INTEGER NOT NULL CHECK(primary_evidence IN (0,1)),
            artifact_digest TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'proposed'
                CHECK(status IN ('proposed','accepted','rejected')),
            verifier_json TEXT NOT NULL DEFAULT '{}',
            version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            decided_at TEXT,
            UNIQUE(task_id,criterion_index,artifact_id,evidence_type)
        );
        CREATE INDEX idx_criterion_evidence_status
            ON criterion_evidence(task_id,criterion_index,status,primary_evidence);
        CREATE TRIGGER artifacts_evidence_envelope_required
        BEFORE INSERT ON artifacts
        WHEN NEW.digest IS NULL OR NEW.producer_json IS NULL
          OR NEW.verifier_json IS NULL OR NEW.inputs_json IS NULL
          OR NEW.toolchain_json IS NULL
        BEGIN SELECT RAISE(ABORT, 'artifact evidence envelope is required'); END;
        CREATE TRIGGER provider_artifacts_evidence_envelope_required
        BEFORE INSERT ON provider_execution_artifacts
        WHEN NEW.digest IS NULL OR NEW.producer_json IS NULL
          OR NEW.verifier_json IS NULL OR NEW.inputs_json IS NULL
          OR NEW.toolchain_json IS NULL
        BEGIN SELECT RAISE(ABORT, 'provider artifact evidence envelope is required'); END;
        CREATE TRIGGER criterion_evidence_identity_immutable
        BEFORE UPDATE OF identity ON criterion_evidence
        WHEN OLD.identity IS NOT NEW.identity
        BEGIN SELECT RAISE(ABORT, 'criterion evidence identity is immutable'); END;
        CREATE TRIGGER criterion_evidence_accepted_no_update
        BEFORE UPDATE ON criterion_evidence WHEN OLD.status='accepted'
        BEGIN SELECT RAISE(ABORT, 'accepted evidence is immutable'); END;
        CREATE TRIGGER criterion_evidence_accepted_no_delete
        BEFORE DELETE ON criterion_evidence WHEN OLD.status='accepted'
        BEGIN SELECT RAISE(ABORT, 'accepted evidence is immutable'); END;
        CREATE TRIGGER artifacts_accepted_evidence_no_update
        BEFORE UPDATE ON artifacts
        WHEN EXISTS(
            SELECT 1 FROM criterion_evidence e
             WHERE e.artifact_id=OLD.id AND e.status='accepted'
        )
        BEGIN SELECT RAISE(ABORT, 'accepted evidence artifact is immutable'); END;
        CREATE TRIGGER artifacts_accepted_evidence_no_delete
        BEFORE DELETE ON artifacts
        WHEN EXISTS(
            SELECT 1 FROM criterion_evidence e
             WHERE e.artifact_id=OLD.id AND e.status='accepted'
        )
        BEGIN SELECT RAISE(ABORT, 'accepted evidence artifact is immutable'); END;
    """),
    (12, """
        CREATE TABLE policy_state(
            id INTEGER PRIMARY KEY CHECK(id=1),
            emergency_stop INTEGER NOT NULL DEFAULT 0 CHECK(emergency_stop IN (0,1)),
            reason TEXT NOT NULL DEFAULT '',
            actor TEXT NOT NULL DEFAULT 'system',
            version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO policy_state(id) VALUES(1);

        CREATE TABLE policy_decisions(
            id INTEGER PRIMARY KEY,
            identity TEXT NOT NULL UNIQUE,
            request_digest TEXT NOT NULL,
            request_json TEXT NOT NULL,
            outcome TEXT NOT NULL CHECK(outcome IN ('allow','deny','require_approval')),
            reason TEXT NOT NULL,
            policy_version INTEGER NOT NULL CHECK(policy_version > 0),
            approval_id INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TRIGGER policy_decisions_no_update BEFORE UPDATE ON policy_decisions
        BEGIN SELECT RAISE(ABORT, 'policy decisions are immutable'); END;
        CREATE TRIGGER policy_decisions_no_delete BEFORE DELETE ON policy_decisions
        BEGIN SELECT RAISE(ABORT, 'policy decisions are immutable'); END;

        CREATE TABLE scoped_execution_approvals(
            id INTEGER PRIMARY KEY,
            identity TEXT NOT NULL UNIQUE,
            mission_id INTEGER NOT NULL,
            task_id INTEGER NOT NULL REFERENCES work_items(id),
            run_id INTEGER REFERENCES workflow_runs(id),
            stage_id TEXT NOT NULL,
            worker_id TEXT NOT NULL,
            runtime_id TEXT NOT NULL,
            worktree_id TEXT,
            permissions_json TEXT NOT NULL,
            request_digest TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','approved','rejected','consumed','expired','cancelled')),
            requested_by TEXT NOT NULL,
            decided_by TEXT,
            decision_note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            decided_at TEXT,
            consumed_at TEXT
        );
        CREATE INDEX idx_scoped_approvals_status
            ON scoped_execution_approvals(status,expires_at,task_id);
        CREATE TRIGGER scoped_approval_scope_immutable
        BEFORE UPDATE OF mission_id,task_id,run_id,stage_id,worker_id,runtime_id,
                         worktree_id,permissions_json,request_digest
        ON scoped_execution_approvals
        BEGIN SELECT RAISE(ABORT, 'approval scope is immutable'); END;
        CREATE TRIGGER scoped_approval_valid_transition
        BEFORE UPDATE OF status ON scoped_execution_approvals
        WHEN NOT (
            (OLD.status='pending' AND NEW.status IN ('approved','rejected','expired','cancelled')) OR
            (OLD.status='approved' AND NEW.status IN ('consumed','expired','cancelled'))
        )
        BEGIN SELECT RAISE(ABORT, 'invalid scoped approval transition'); END;
    """),
    (13, """
        CREATE TABLE worker_qualifications(
            id INTEGER PRIMARY KEY,
            identity TEXT NOT NULL UNIQUE,
            worker_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            role TEXT NOT NULL,
            capabilities_json TEXT NOT NULL,
            dimensions_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            evidence_digest TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('qualified','failed','expired','quarantined')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            valid_until TEXT NOT NULL
        );
        CREATE INDEX idx_worker_qualification_route
            ON worker_qualifications(status,role,valid_until,worker_id,id);
        CREATE TRIGGER worker_qualifications_no_update BEFORE UPDATE ON worker_qualifications
        BEGIN SELECT RAISE(ABORT, 'worker qualifications are immutable'); END;
        CREATE TRIGGER worker_qualifications_no_delete BEFORE DELETE ON worker_qualifications
        BEGIN SELECT RAISE(ABORT, 'worker qualifications are immutable'); END;

        CREATE TABLE worker_lifecycle(
            worker_id TEXT PRIMARY KEY,
            state TEXT NOT NULL CHECK(state IN ('active','draining','quarantined','offline')),
            reason TEXT NOT NULL DEFAULT '',
            version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE worker_handoffs(
            id INTEGER PRIMARY KEY,
            identity TEXT NOT NULL UNIQUE,
            source_worker_id TEXT NOT NULL,
            replacement_worker_id TEXT NOT NULL,
            task_id INTEGER NOT NULL REFERENCES work_items(id),
            run_id INTEGER REFERENCES workflow_runs(id),
            stage_id TEXT NOT NULL,
            attempt_id TEXT,
            context_digest TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TRIGGER worker_handoffs_no_update BEFORE UPDATE ON worker_handoffs
        BEGIN SELECT RAISE(ABORT, 'worker handoffs are immutable'); END;
        CREATE TRIGGER worker_handoffs_no_delete BEFORE DELETE ON worker_handoffs
        BEGIN SELECT RAISE(ABORT, 'worker handoffs are immutable'); END;
    """),
    (14, """
        ALTER TABLE workflow_runs ADD COLUMN workflow_version TEXT NOT NULL DEFAULT 'legacy';
        ALTER TABLE workflow_runs ADD COLUMN definition_digest TEXT;
        ALTER TABLE workflow_runs ADD COLUMN definition_json TEXT;
        ALTER TABLE workflow_runs ADD COLUMN checkpoint_sequence INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE workflow_stages ADD COLUMN dependencies_json TEXT NOT NULL DEFAULT '[]';
        ALTER TABLE workflow_stages ADD COLUMN definition_json TEXT;
        CREATE TRIGGER workflow_run_definition_immutable
        BEFORE UPDATE OF workflow_id,workflow_version,definition_digest,definition_json
        ON workflow_runs
        BEGIN SELECT RAISE(ABORT, 'workflow definition is immutable for a run'); END;

        CREATE TABLE stage_checkpoints(
            id INTEGER PRIMARY KEY,
            identity TEXT NOT NULL UNIQUE,
            run_id INTEGER NOT NULL REFERENCES workflow_runs(id),
            stage_id INTEGER NOT NULL REFERENCES workflow_stages(id),
            sequence INTEGER NOT NULL CHECK(sequence > 0),
            state TEXT NOT NULL CHECK(state IN ('pending','running','waiting_approval','succeeded','failed')),
            payload_json TEXT NOT NULL,
            payload_digest TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(run_id,sequence)
        );
        CREATE TRIGGER stage_checkpoints_no_update BEFORE UPDATE ON stage_checkpoints
        BEGIN SELECT RAISE(ABORT, 'stage checkpoints are immutable'); END;
        CREATE TRIGGER stage_checkpoints_no_delete BEFORE DELETE ON stage_checkpoints
        BEGIN SELECT RAISE(ABORT, 'stage checkpoints are immutable'); END;

        CREATE TABLE workflow_mutations(
            id INTEGER PRIMARY KEY,
            identity TEXT NOT NULL UNIQUE,
            run_id INTEGER NOT NULL REFERENCES workflow_runs(id),
            stage_id INTEGER NOT NULL REFERENCES workflow_stages(id),
            operation TEXT NOT NULL CHECK(operation IN ('provider_call','worktree','github')),
            idempotency_key TEXT NOT NULL,
            request_digest TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'reserved'
                CHECK(status IN ('reserved','completed','failed')),
            result_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            UNIQUE(run_id,operation,idempotency_key)
        );
        CREATE TRIGGER workflow_mutation_scope_immutable
        BEFORE UPDATE OF run_id,stage_id,operation,idempotency_key,request_digest
        ON workflow_mutations
        BEGIN SELECT RAISE(ABORT, 'workflow mutation scope is immutable'); END;
    """),
    (15, """
        CREATE TRIGGER leases_no_delete
        BEFORE DELETE ON leases
        BEGIN SELECT RAISE(ABORT, 'lease history is immutable'); END;

        CREATE TABLE assignment_conflict_domains(
            assignment_id INTEGER NOT NULL REFERENCES assignments(id),
            domain TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(assignment_id,domain)
        );
        CREATE INDEX idx_assignment_conflict_domains_domain
            ON assignment_conflict_domains(domain,assignment_id);
        CREATE TRIGGER assignment_conflict_domains_no_update
        BEFORE UPDATE ON assignment_conflict_domains
        BEGIN SELECT RAISE(ABORT, 'assignment conflict domains are immutable'); END;
        CREATE TRIGGER assignment_conflict_domains_no_delete
        BEFORE DELETE ON assignment_conflict_domains
        BEGIN SELECT RAISE(ABORT, 'assignment conflict domains are immutable'); END;

        CREATE TABLE scheduler_conflicts(
            id INTEGER PRIMARY KEY,
            identity TEXT NOT NULL UNIQUE,
            task_id INTEGER NOT NULL REFERENCES work_items(id),
            requested_domains_json TEXT NOT NULL,
            conflicting_assignment_ids_json TEXT NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('serialize','escalate')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TRIGGER scheduler_conflicts_no_update
        BEFORE UPDATE ON scheduler_conflicts
        BEGIN SELECT RAISE(ABORT, 'scheduler conflicts are immutable'); END;
        CREATE TRIGGER scheduler_conflicts_no_delete
        BEFORE DELETE ON scheduler_conflicts
        BEGIN SELECT RAISE(ABORT, 'scheduler conflicts are immutable'); END;
    """),
    (16, """
        ALTER TABLE worker_sessions ADD COLUMN request_json TEXT NOT NULL DEFAULT '{}';
        ALTER TABLE worker_sessions ADD COLUMN result_json TEXT;
        ALTER TABLE worker_sessions ADD COLUMN heartbeat_at TEXT;
        ALTER TABLE worker_sessions ADD COLUMN finalized_at TEXT;
        ALTER TABLE worker_sessions ADD COLUMN mutable_action_count INTEGER NOT NULL DEFAULT 0
            CHECK(mutable_action_count >= 0);

        CREATE TABLE runtime_session_events(
            id INTEGER PRIMARY KEY,
            identity TEXT NOT NULL UNIQUE,
            session_id INTEGER NOT NULL REFERENCES worker_sessions(id),
            sequence INTEGER NOT NULL CHECK(sequence > 0),
            kind TEXT NOT NULL CHECK(kind IN (
                'status','message','tool_call','artifact','heartbeat','error'
            )),
            payload_json TEXT NOT NULL,
            mutable INTEGER NOT NULL DEFAULT 0 CHECK(mutable IN (0,1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(session_id,sequence)
        );
        CREATE INDEX idx_runtime_session_events
            ON runtime_session_events(session_id,sequence);
        CREATE TRIGGER runtime_session_events_no_update
        BEFORE UPDATE ON runtime_session_events
        BEGIN SELECT RAISE(ABORT, 'runtime session events are immutable'); END;
        CREATE TRIGGER runtime_session_events_no_delete
        BEFORE DELETE ON runtime_session_events
        BEGIN SELECT RAISE(ABORT, 'runtime session events are immutable'); END;
        CREATE TRIGGER worker_session_scope_immutable
        BEFORE UPDATE OF assignment_id,runtime,request_json ON worker_sessions
        BEGIN SELECT RAISE(ABORT, 'worker session scope is immutable'); END;
        CREATE TRIGGER worker_session_external_id_immutable
        BEFORE UPDATE OF external_session_id ON worker_sessions
        WHEN OLD.external_session_id IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'worker external session identity is immutable'); END;
        CREATE TRIGGER worker_session_result_immutable
        BEFORE UPDATE OF result_json ON worker_sessions
        WHEN OLD.result_json IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'worker session result is immutable'); END;
    """),
    (17, """
        ALTER TABLE worktrees ADD COLUMN task_id INTEGER REFERENCES work_items(id);
        ALTER TABLE worktrees ADD COLUMN lease_id INTEGER REFERENCES leases(id);
        ALTER TABLE worktrees ADD COLUMN fencing_token INTEGER;
        ALTER TABLE worktrees ADD COLUMN owner TEXT;
        ALTER TABLE worktrees ADD COLUMN retention_until TEXT;
        ALTER TABLE worktrees ADD COLUMN reconciled_at TEXT;

        UPDATE worktrees
           SET task_id=(SELECT task_id FROM assignments WHERE id=worktrees.assignment_id),
               owner=(SELECT agent_id FROM assignments WHERE id=worktrees.assignment_id),
               lease_id=(SELECT id FROM leases
                          WHERE assignment_id=worktrees.assignment_id
                          ORDER BY fencing_token DESC LIMIT 1),
               fencing_token=(SELECT fencing_token FROM leases
                               WHERE assignment_id=worktrees.assignment_id
                               ORDER BY fencing_token DESC LIMIT 1);

        CREATE UNIQUE INDEX idx_worktrees_active_assignment ON worktrees(assignment_id)
            WHERE status<>'cleaned';
        CREATE UNIQUE INDEX idx_worktrees_repository_branch
            ON worktrees(repository,branch);
        CREATE INDEX idx_worktrees_reconcile
            ON worktrees(repository,status,retention_until);
        CREATE TRIGGER worktree_authority_required
        BEFORE INSERT ON worktrees
        WHEN NEW.task_id IS NULL OR NEW.lease_id IS NULL
          OR NEW.fencing_token IS NULL OR NEW.owner IS NULL
        BEGIN SELECT RAISE(ABORT, 'worktree authority metadata is required'); END;
        CREATE TRIGGER worktree_scope_immutable
        BEFORE UPDATE OF assignment_id,attempt_id,repository,base_sha,branch,path,
                         task_id,lease_id,fencing_token,owner
        ON worktrees
        BEGIN SELECT RAISE(ABORT, 'worktree authority metadata is immutable'); END;
        CREATE TRIGGER worktrees_no_delete
        BEFORE DELETE ON worktrees
        BEGIN SELECT RAISE(ABORT, 'worktree history is immutable'); END;
    """),
    (18, """
        CREATE TABLE execution_context_packages(
            id INTEGER PRIMARY KEY,
            identity TEXT NOT NULL UNIQUE,
            task_id INTEGER NOT NULL REFERENCES work_items(id),
            run_id INTEGER NOT NULL REFERENCES workflow_runs(id),
            assignment_id INTEGER NOT NULL REFERENCES assignments(id),
            fencing_token INTEGER NOT NULL CHECK(fencing_token > 0),
            digest TEXT NOT NULL UNIQUE
                CHECK(length(digest)=64 AND digest NOT GLOB '*[^0-9a-f]*'),
            package_json TEXT NOT NULL,
            byte_count INTEGER NOT NULL CHECK(byte_count > 0),
            token_count INTEGER NOT NULL CHECK(token_count > 0),
            compacted INTEGER NOT NULL CHECK(compacted IN (0,1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX idx_context_packages_scope
            ON execution_context_packages(task_id,run_id,assignment_id,id);
        CREATE TRIGGER execution_context_packages_no_update
        BEFORE UPDATE ON execution_context_packages
        BEGIN SELECT RAISE(ABORT, 'execution context packages are immutable'); END;
        CREATE TRIGGER execution_context_packages_no_delete
        BEFORE DELETE ON execution_context_packages
        BEGIN SELECT RAISE(ABORT, 'execution context packages are immutable'); END;

        ALTER TABLE worker_sessions ADD COLUMN context_package_id INTEGER
            REFERENCES execution_context_packages(id);
        ALTER TABLE worker_sessions ADD COLUMN context_digest TEXT;
        CREATE INDEX idx_worker_sessions_context
            ON worker_sessions(context_package_id);
        CREATE TRIGGER worker_session_context_immutable
        BEFORE UPDATE OF context_package_id,context_digest ON worker_sessions
        BEGIN SELECT RAISE(ABORT, 'worker session context is immutable'); END;
    """),
    (19, """
        CREATE TABLE hermes_acp_sessions(
            id INTEGER PRIMARY KEY,
            identity TEXT NOT NULL UNIQUE,
            worker_session_id INTEGER NOT NULL UNIQUE REFERENCES worker_sessions(id),
            task_id INTEGER NOT NULL REFERENCES work_items(id),
            run_id INTEGER NOT NULL REFERENCES workflow_runs(id),
            stage_id INTEGER NOT NULL REFERENCES workflow_stages(id),
            attempt_id INTEGER NOT NULL REFERENCES attempts(id),
            assignment_id INTEGER NOT NULL REFERENCES assignments(id),
            fencing_token INTEGER NOT NULL CHECK(fencing_token > 0),
            agent_role TEXT NOT NULL,
            worktree_id INTEGER NOT NULL REFERENCES worktrees(id),
            context_package_id INTEGER NOT NULL REFERENCES execution_context_packages(id),
            allowed_tools_json TEXT NOT NULL,
            executable TEXT NOT NULL,
            hermes_version TEXT NOT NULL,
            protocol_version INTEGER NOT NULL CHECK(protocol_version > 0),
            external_session_id TEXT NOT NULL UNIQUE,
            process_pid INTEGER,
            status TEXT NOT NULL CHECK(status IN (
                'running','suspended','succeeded','failed','cancelled'
            )),
            version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX idx_hermes_acp_assignment
            ON hermes_acp_sessions(assignment_id,status,id);
        CREATE TRIGGER hermes_acp_scope_immutable
        BEFORE UPDATE OF worker_session_id,task_id,run_id,stage_id,attempt_id,
                         assignment_id,fencing_token,agent_role,worktree_id,
                         context_package_id,allowed_tools_json,executable,
                         hermes_version,protocol_version,external_session_id
        ON hermes_acp_sessions
        BEGIN SELECT RAISE(ABORT, 'Hermes ACP session scope is immutable'); END;
        CREATE TRIGGER hermes_acp_sessions_no_delete
        BEFORE DELETE ON hermes_acp_sessions
        BEGIN SELECT RAISE(ABORT, 'Hermes ACP session history is immutable'); END;
    """),
)

RUN_TRANSITIONS = TRANSITIONS["run"]


class TaskNotRunnableError(RuntimeError):
    """Raised when a work item cannot be dispatched by the scheduler."""


class ConflictDomainBusyError(RuntimeError):
    """Raised when an active assignment owns an overlapping mutation domain."""

    def __init__(self, assignment_ids: tuple[int, ...], *, escalated: bool = False):
        self.assignment_ids = assignment_ids
        self.escalated = escalated
        action = "escalated" if escalated else "serialized"
        super().__init__(
            f"Conflict domains overlap active assignments {list(assignment_ids)}; "
            f"request was {action}"
        )


class StaleLeaseError(PermissionError):
    """Raised when a worker presents an expired or superseded fencing token."""


def _sha256_snapshot(value: str, field: str) -> str:
    """Validate a caller-computed canonical SHA-256 approval snapshot."""

    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Scheduler timestamps must be timezone-aware")
    return current.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds")


def _normalize_conflict_domains(
    project_id: int, domains: list[str] | tuple[str, ...] | None
) -> tuple[str, ...]:
    requested = domains or ()
    if not requested:
        return (f"project:{project_id}",)
    normalized: set[str] = set()
    prefix = f"project:{project_id}"
    for value in requested:
        domain = str(value).strip().replace("\\", "/").casefold()
        while "//" in domain:
            domain = domain.replace("//", "/")
        domain = domain.rstrip("/")
        if not domain:
            raise ValueError("Conflict domains cannot be empty")
        if domain.startswith("project:"):
            if domain != prefix and not domain.startswith(f"{prefix}/"):
                raise ValueError("Conflict domains cannot cross project boundaries")
        else:
            if domain.startswith("module:"):
                namespace, resource = domain.split(":", 1)
                domain = f"{namespace}:{resource.replace('.', '/')}"
            domain = f"{prefix}/{domain}"
        normalized.add(domain)
    return tuple(sorted(normalized))


def _domains_overlap(left: str, right: str) -> bool:
    return (
        left == right
        or left.startswith(f"{right}/")
        or right.startswith(f"{left}/")
    )


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
        self._ensure_audit_chain()
        self._ensure_evidence_ledger()

    def _migrate(self) -> None:
        self.db.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        applied = {int(row[0]) for row in self.db.execute("SELECT version FROM schema_migrations")}
        for version, script in MIGRATIONS:
            if version in applied:
                continue
            # executescript commits implicitly, so each migration owns its explicit transaction.
            self.db.executescript(f"BEGIN IMMEDIATE;\n{script}\nINSERT INTO schema_migrations(version) VALUES({version});\nCOMMIT;")

    @staticmethod
    def _audit_digest(
        *,
        identity: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: str,
        correlation_json: str,
        created_at: str,
        previous_hash: str,
    ) -> str:
        material = json.dumps(
            {
                "identity": identity,
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "payload": json.loads(payload),
                "correlation": json.loads(correlation_json),
                "created_at": created_at,
                "previous_hash": previous_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _correlation(
        self, entity: str, entity_id: int | str, payload: dict[str, Any]
    ) -> dict[str, str | int | None]:
        correlation: dict[str, str | int | None] = {
            "mission_id": payload.get("mission_id") or payload.get("project_id"),
            "task_id": payload.get("task_id"),
            "run_id": payload.get("run_id"),
            "stage_id": payload.get("stage_id") or payload.get("stage"),
            "attempt_id": payload.get("attempt_id"),
            "worker_session_id": payload.get("worker_session_id"),
        }
        numeric_id = int(entity_id) if str(entity_id).isdigit() else None
        if entity == "project":
            correlation["mission_id"] = entity_id
        elif entity == "task":
            correlation["task_id"] = entity_id
        elif entity == "run":
            correlation["run_id"] = entity_id
        elif entity == "stage":
            correlation["stage_id"] = entity_id
        elif entity == "provider_attempt":
            correlation["attempt_id"] = entity_id

        run_id = correlation["run_id"]
        task_id = correlation["task_id"]
        if numeric_id is not None and entity == "approval":
            row = self.db.execute(
                "SELECT run_id FROM approval_gates WHERE id=?", (numeric_id,)
            ).fetchone()
            run_id = int(row["run_id"]) if row else run_id
        elif numeric_id is not None and entity == "artifact":
            row = self.db.execute(
                "SELECT run_id,stage FROM artifacts WHERE id=?", (numeric_id,)
            ).fetchone()
            if row:
                run_id = int(row["run_id"])
                correlation["stage_id"] = correlation["stage_id"] or row["stage"]
        elif numeric_id is not None and entity == "review_assignment":
            row = self.db.execute(
                "SELECT run_id,stage FROM reviewer_assignments WHERE id=?", (numeric_id,)
            ).fetchone()
            if row:
                run_id = int(row["run_id"])
                correlation["stage_id"] = correlation["stage_id"] or row["stage"]
        elif numeric_id is not None and entity == "provider_gate":
            row = self.db.execute(
                "SELECT task_id FROM provider_execution_gates WHERE id=?", (numeric_id,)
            ).fetchone()
            task_id = int(row["task_id"]) if row else task_id
        elif numeric_id is not None and entity == "provider_attempt":
            row = self.db.execute(
                "SELECT task_id FROM provider_execution_attempts WHERE id=?", (numeric_id,)
            ).fetchone()
            if row:
                task_id = int(row["task_id"])
                session = self.db.execute(
                    """SELECT s.identity
                         FROM attempts a
                         JOIN worker_sessions s ON s.assignment_id=a.assignment_id
                        WHERE a.provider_attempt_id=?""",
                    (numeric_id,),
                ).fetchone()
                if session:
                    correlation["worker_session_id"] = session["identity"]

        if run_id is not None:
            correlation["run_id"] = run_id
            row = self.db.execute(
                "SELECT task_id FROM workflow_runs WHERE id=?", (run_id,)
            ).fetchone()
            task_id = int(row["task_id"]) if row else task_id
        if task_id is not None:
            correlation["task_id"] = task_id
            row = self.db.execute(
                "SELECT project_id FROM work_items WHERE id=?", (task_id,)
            ).fetchone()
            if row:
                correlation["mission_id"] = int(row["project_id"])
        return correlation

    def _ensure_audit_chain(self) -> None:
        """One-time compatibility backfill followed by immutable audit guards."""

        previous_hash = ""
        with self.db:
            self._begin_immediate()
            rows = self.db.execute("SELECT * FROM events ORDER BY id").fetchall()
            for row in rows:
                if row["identity"] and row["record_hash"] and row["correlation_json"]:
                    previous_hash = str(row["record_hash"])
                    continue
                decoded_payload = json.loads(row["payload"])
                payload = decoded_payload if isinstance(decoded_payload, dict) else {}
                correlation = self._correlation(
                    str(row["entity_type"]), str(row["entity_id"]), payload
                )
                correlation_json = json.dumps(
                    correlation, sort_keys=True, separators=(",", ":")
                )
                identity = f"event:{row['id']}"
                digest = self._audit_digest(
                    identity=identity,
                    event_type=str(row["event_type"]),
                    entity_type=str(row["entity_type"]),
                    entity_id=str(row["entity_id"]),
                    payload=str(row["payload"]),
                    correlation_json=correlation_json,
                    created_at=str(row["created_at"]),
                    previous_hash=previous_hash,
                )
                self.db.execute(
                    """UPDATE events
                          SET identity=?,correlation_root=?,correlation_json=?,
                              previous_hash=?,record_hash=?
                        WHERE id=?""",
                    (
                        identity,
                        self._correlation_root(correlation),
                        correlation_json,
                        previous_hash,
                        digest,
                        row["id"],
                    ),
                )
                self.db.execute(
                    """INSERT OR IGNORE INTO outbox_messages(
                           identity,event_id,topic,payload,correlation_json,
                           delivery_key,status,delivered_at
                       ) VALUES(?,?,?,?,?,?,'delivered',CURRENT_TIMESTAMP)""",
                    (
                        f"outbox:{row['id']}",
                        row["id"],
                        row["event_type"],
                        row["payload"],
                        correlation_json,
                        identity,
                    ),
                )
                previous_hash = digest
            self.db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_identity ON events(identity)"
            )
            self.db.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS events_identity_required
                BEFORE INSERT ON events
                WHEN NEW.identity IS NULL OR NEW.correlation_json IS NULL
                  OR NEW.previous_hash IS NULL OR NEW.record_hash IS NULL
                BEGIN SELECT RAISE(ABORT, 'complete audit envelope is required'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_update
                BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT, 'audit records are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete
                BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT, 'audit records are immutable'); END;
                """
            )

    @staticmethod
    def _correlation_root(correlation: dict[str, str | int | None]) -> str:
        for key in (
            "mission_id",
            "task_id",
            "run_id",
            "stage_id",
            "attempt_id",
            "worker_session_id",
        ):
            value = correlation.get(key)
            if value is not None:
                return f"{key}:{value}"
        return "control-plane"

    def _begin_immediate(self) -> None:
        if not self.db.in_transaction:
            self.db.execute("BEGIN IMMEDIATE")

    @staticmethod
    def _content_digest(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _ensure_evidence_ledger(self) -> None:
        with self.db:
            for row in self.db.execute(
                """SELECT id,run_id,stage,agent_id,provider,content
                     FROM artifacts WHERE digest IS NULL"""
            ).fetchall():
                self.db.execute(
                    """UPDATE artifacts
                          SET digest=?,producer_json=?,verifier_json=?,inputs_json=?,
                              toolchain_json=?
                        WHERE id=?""",
                    (
                        self._content_digest(str(row["content"])),
                        json.dumps(
                            {"agent_id": row["agent_id"], "provider": row["provider"]},
                            sort_keys=True,
                        ),
                        json.dumps({"status": "unverified"}, sort_keys=True),
                        json.dumps(
                            {"run_id": row["run_id"], "stage": row["stage"]},
                            sort_keys=True,
                        ),
                        json.dumps({"provider": row["provider"]}, sort_keys=True),
                        row["id"],
                    ),
                )
            for row in self.db.execute(
                """SELECT id,gate_id,attempt_id,provider,agent_id,content,metadata
                     FROM provider_execution_artifacts WHERE digest IS NULL"""
            ).fetchall():
                metadata = json.loads(row["metadata"])
                self.db.execute(
                    """UPDATE provider_execution_artifacts
                          SET digest=?,producer_json=?,verifier_json=?,inputs_json=?,
                              toolchain_json=?
                        WHERE id=?""",
                    (
                        self._content_digest(str(row["content"])),
                        json.dumps(
                            {"agent_id": row["agent_id"], "provider": row["provider"]},
                            sort_keys=True,
                        ),
                        json.dumps({"status": "unverified"}, sort_keys=True),
                        json.dumps(
                            {"gate_id": row["gate_id"], "attempt_id": row["attempt_id"]},
                            sort_keys=True,
                        ),
                        json.dumps(
                            {"provider": row["provider"], "metadata": metadata},
                            sort_keys=True,
                        ),
                        row["id"],
                    ),
                )

    def _event(self, kind: str, entity: str, entity_id: int | str, payload: dict[str, Any]) -> None:
        self._begin_immediate()
        identity = self._identity("event")
        payload_json = json.dumps(payload, ensure_ascii=False)
        correlation = self._correlation(entity, entity_id, payload)
        correlation_json = json.dumps(
            correlation, sort_keys=True, separators=(",", ":")
        )
        previous = self.db.execute(
            "SELECT record_hash FROM events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        previous_hash = str(previous["record_hash"]) if previous else ""
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
        record_hash = self._audit_digest(
            identity=identity,
            event_type=kind,
            entity_type=entity,
            entity_id=str(entity_id),
            payload=payload_json,
            correlation_json=correlation_json,
            created_at=created_at,
            previous_hash=previous_hash,
        )
        cur = self.db.execute(
            """INSERT INTO events(
                   identity,event_type,entity_type,entity_id,payload,created_at,
                   correlation_root,correlation_json,previous_hash,record_hash
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                identity,
                kind,
                entity,
                str(entity_id),
                payload_json,
                created_at,
                self._correlation_root(correlation),
                correlation_json,
                previous_hash,
                record_hash,
            ),
        )
        event_id = int(cur.lastrowid)
        self.db.execute(
            """INSERT INTO outbox_messages(
                   identity,event_id,topic,payload,correlation_json,delivery_key
               ) VALUES(?,?,?,?,?,?)""",
            (
                self._identity("outbox"),
                event_id,
                kind,
                payload_json,
                correlation_json,
                identity,
            ),
        )

    @staticmethod
    def _identity(kind: str) -> str:
        return f"{kind}:{uuid.uuid4().hex}"

    def event(self, kind: str, entity: str, entity_id: int | str, payload: dict[str, Any]) -> None:
        with self.db:
            self._event(kind, entity, entity_id, payload)

    def verify_audit_chain(self) -> dict[str, Any]:
        failures: list[dict[str, Any]] = []
        expected_previous = ""
        rows = self.db.execute("SELECT * FROM events ORDER BY id").fetchall()
        required_correlation = {
            "mission_id",
            "task_id",
            "run_id",
            "stage_id",
            "attempt_id",
            "worker_session_id",
        }
        for row in rows:
            reasons: list[str] = []
            try:
                correlation = json.loads(row["correlation_json"])
                if set(correlation) != required_correlation:
                    reasons.append("correlation envelope is incomplete")
            except (TypeError, json.JSONDecodeError):
                correlation = {}
                reasons.append("correlation envelope is invalid JSON")
            if row["previous_hash"] != expected_previous:
                reasons.append("previous hash does not match")
            try:
                expected_hash = self._audit_digest(
                    identity=str(row["identity"]),
                    event_type=str(row["event_type"]),
                    entity_type=str(row["entity_type"]),
                    entity_id=str(row["entity_id"]),
                    payload=str(row["payload"]),
                    correlation_json=str(row["correlation_json"]),
                    created_at=str(row["created_at"]),
                    previous_hash=str(row["previous_hash"]),
                )
                if row["record_hash"] != expected_hash:
                    reasons.append("record hash does not match")
            except (TypeError, ValueError, json.JSONDecodeError):
                reasons.append("record cannot be canonicalized")
            if reasons:
                failures.append({"event_id": int(row["id"]), "reasons": reasons})
            expected_previous = str(row["record_hash"])
        return {"ok": not failures, "checked": len(rows), "failures": failures}

    def verify_evidence_ledger(self) -> dict[str, Any]:
        failures: list[dict[str, Any]] = []
        checked = 0
        for table in ("artifacts", "provider_execution_artifacts"):
            for row in self.db.execute(
                f"SELECT id,content,digest FROM {table} ORDER BY id"
            ).fetchall():
                checked += 1
                expected = self._content_digest(str(row["content"]))
                if row["digest"] != expected:
                    failures.append(
                        {
                            "artifact": f"{table}:{row['id']}",
                            "reason": "content digest does not match",
                        }
                    )
        for row in self.db.execute(
            """SELECT e.id,e.artifact_digest,a.digest
                 FROM criterion_evidence e
                 JOIN artifacts a ON a.id=e.artifact_id
                WHERE e.status='accepted' ORDER BY e.id"""
        ).fetchall():
            if row["artifact_digest"] != row["digest"]:
                failures.append(
                    {
                        "criterion_evidence_id": int(row["id"]),
                        "reason": "accepted evidence digest does not match artifact",
                    }
                )
        return {"ok": not failures, "checked": checked, "failures": failures}

    def outbox_messages(self, status: str | None = None):
        if status is None:
            return self.db.execute("SELECT * FROM outbox_messages ORDER BY id").fetchall()
        if status not in {"pending", "dispatching", "delivered", "failed"}:
            raise ValueError(status)
        return self.db.execute(
            "SELECT * FROM outbox_messages WHERE status=? ORDER BY id", (status,)
        ).fetchall()

    def claim_outbox(self, consumer: str, limit: int = 25):
        if not consumer.strip():
            raise ValueError("Outbox consumer is required")
        if limit < 1 or limit > 100:
            raise ValueError("Outbox claim limit must be between 1 and 100")
        claimed_ids: list[int] = []
        with self.db:
            self._begin_immediate()
            rows = self.db.execute(
                """SELECT id FROM outbox_messages
                    WHERE status IN ('pending','failed')
                      AND available_at<=CURRENT_TIMESTAMP
                    ORDER BY id LIMIT ?""",
                (limit,),
            ).fetchall()
            for row in rows:
                claim_token = uuid.uuid4().hex
                updated = self.db.execute(
                    """UPDATE outbox_messages
                          SET status='dispatching',attempts=attempts+1,
                              claimed_by=?,claim_token=?,last_error=NULL
                        WHERE id=? AND status IN ('pending','failed')""",
                    (consumer, claim_token, row["id"]),
                )
                if updated.rowcount == 1:
                    claimed_ids.append(int(row["id"]))
        if not claimed_ids:
            return []
        placeholders = ",".join("?" for _ in claimed_ids)
        return self.db.execute(
            f"SELECT * FROM outbox_messages WHERE id IN ({placeholders}) ORDER BY id",
            claimed_ids,
        ).fetchall()

    def acknowledge_outbox(self, message_id: int, claim_token: str) -> bool:
        with self.db:
            self._begin_immediate()
            row = self.db.execute(
                "SELECT status,claim_token FROM outbox_messages WHERE id=?", (message_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown outbox message: {message_id}")
            if row["status"] == "delivered":
                return False
            if row["status"] != "dispatching" or row["claim_token"] != claim_token:
                raise PermissionError("Outbox claim token is invalid or stale")
            updated = self.db.execute(
                """UPDATE outbox_messages
                      SET status='delivered',delivered_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='dispatching' AND claim_token=?""",
                (message_id, claim_token),
            )
            return updated.rowcount == 1

    def fail_outbox(
        self, message_id: int, claim_token: str, error: str, retry_seconds: int = 0
    ) -> None:
        if retry_seconds < 0 or retry_seconds > 86_400:
            raise ValueError("retry_seconds must be between 0 and 86400")
        with self.db:
            self._begin_immediate()
            updated = self.db.execute(
                """UPDATE outbox_messages
                      SET status='failed',last_error=?,
                          available_at=datetime('now', ?),claim_token=NULL
                    WHERE id=? AND status='dispatching' AND claim_token=?""",
                (error[:2000], f"+{retry_seconds} seconds", message_id, claim_token),
            )
            if updated.rowcount != 1:
                row = self.db.execute(
                    "SELECT id FROM outbox_messages WHERE id=?", (message_id,)
                ).fetchone()
                if not row:
                    raise KeyError(f"Unknown outbox message: {message_id}")
                raise PermissionError("Outbox claim token is invalid or stale")

    @staticmethod
    def _policy_digest(request: dict[str, Any]) -> str:
        normalized = dict(request)
        normalized["permissions"] = sorted(set(normalized.get("permissions", [])))
        payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def policy_state(self) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM policy_state WHERE id=1").fetchone()
        return {
            "emergency_stop": bool(row["emergency_stop"]),
            "reason": str(row["reason"]),
            "actor": str(row["actor"]),
            "version": int(row["version"]),
            "updated_at": str(row["updated_at"]),
        }

    def _assert_dispatch_allowed(self) -> None:
        state = self.policy_state()
        if state["emergency_stop"]:
            raise PermissionError(f"Emergency stop is active: {state['reason']}")

    def record_policy_decision(
        self,
        *,
        request: dict[str, Any],
        request_digest: str,
        outcome: str,
        reason: str,
        policy_version: int,
        approval_id: int | None = None,
    ) -> int:
        if outcome not in {"allow", "deny", "require_approval"}:
            raise ValueError(outcome)
        if self._policy_digest(request) != request_digest:
            raise ValueError("Policy request digest does not match canonical request")
        request_json = json.dumps(request, sort_keys=True, separators=(",", ":"))
        with self.db:
            cur = self.db.execute(
                """INSERT INTO policy_decisions(
                       identity,request_digest,request_json,outcome,reason,
                       policy_version,approval_id
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    self._identity("policy-decision"),
                    request_digest,
                    request_json,
                    outcome,
                    reason,
                    policy_version,
                    approval_id,
                ),
            )
            decision_id = int(cur.lastrowid)
            self._event(
                f"policy.{outcome}",
                "policy_decision",
                decision_id,
                {
                    **request,
                    "request_digest": request_digest,
                    "policy_version": policy_version,
                    "approval_id": approval_id,
                    "reason": reason,
                },
            )
        return decision_id

    def request_scoped_approval(
        self,
        *,
        request: dict[str, Any],
        requested_by: str,
        ttl_seconds: int = 900,
    ) -> int:
        required = {
            "mission_id",
            "task_id",
            "run_id",
            "stage_id",
            "worker_id",
            "runtime_id",
            "worktree_id",
            "permissions",
        }
        if set(request) != required:
            raise ValueError(f"Approval request requires exact fields: {sorted(required)}")
        if not requested_by.strip():
            raise ValueError("Approval requester is required")
        if ttl_seconds < 1 or ttl_seconds > 86_400:
            raise ValueError("Approval TTL must be between 1 and 86400 seconds")
        task = self.db.execute(
            "SELECT project_id FROM work_items WHERE id=?", (request["task_id"],)
        ).fetchone()
        if not task:
            raise KeyError(f"Unknown task: {request['task_id']}")
        if int(task["project_id"]) != int(request["mission_id"]):
            raise ValueError("Approval mission does not own the requested task")
        if request["run_id"] is not None:
            run = self.db.execute(
                "SELECT task_id FROM workflow_runs WHERE id=?", (request["run_id"],)
            ).fetchone()
            if not run or int(run["task_id"]) != int(request["task_id"]):
                raise ValueError("Approval run does not belong to the requested task")
        normalized = dict(request)
        normalized["permissions"] = sorted(set(request["permissions"]))
        digest = self._policy_digest(normalized)
        with self.db:
            cur = self.db.execute(
                """INSERT INTO scoped_execution_approvals(
                       identity,mission_id,task_id,run_id,stage_id,worker_id,
                       runtime_id,worktree_id,permissions_json,request_digest,
                       requested_by,expires_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,datetime('now', ?))""",
                (
                    self._identity("execution-approval"),
                    normalized["mission_id"],
                    normalized["task_id"],
                    normalized["run_id"],
                    normalized["stage_id"],
                    normalized["worker_id"],
                    normalized["runtime_id"],
                    normalized["worktree_id"],
                    json.dumps(normalized["permissions"], separators=(",", ":")),
                    digest,
                    requested_by,
                    f"+{ttl_seconds} seconds",
                ),
            )
            approval_id = int(cur.lastrowid)
            self._event(
                "policy.approval.requested",
                "scoped_approval",
                approval_id,
                {**normalized, "request_digest": digest, "requested_by": requested_by},
            )
        return approval_id

    def decide_scoped_approval(
        self, approval_id: int, decision: str, *, actor: str, note: str = ""
    ) -> bool:
        if decision not in {"approved", "rejected"}:
            raise ValueError(decision)
        if not actor.strip():
            raise ValueError("Approval decision actor is required")
        with self.db:
            row = self.db.execute(
                "SELECT * FROM scoped_execution_approvals WHERE id=?", (approval_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown scoped approval: {approval_id}")
            if row["status"] == decision:
                return False
            if row["status"] != "pending":
                raise ValueError(f"Scoped approval {approval_id} is already {row['status']}")
            if self.db.execute(
                "SELECT datetime(?)<=CURRENT_TIMESTAMP", (row["expires_at"],)
            ).fetchone()[0]:
                raise ValueError(f"Scoped approval {approval_id} has expired")
            self.db.execute(
                """UPDATE scoped_execution_approvals
                      SET status=?,decided_by=?,decision_note=?,
                          decided_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='pending'""",
                (decision, actor, note, approval_id),
            )
            self._event(
                f"policy.approval.{decision}",
                "scoped_approval",
                approval_id,
                {
                    "mission_id": row["mission_id"],
                    "task_id": row["task_id"],
                    "run_id": row["run_id"],
                    "stage_id": row["stage_id"],
                    "worker_id": row["worker_id"],
                    "runtime_id": row["runtime_id"],
                    "worktree_id": row["worktree_id"],
                    "request_digest": row["request_digest"],
                    "actor": actor,
                    "note": note,
                },
            )
        return True

    def consume_scoped_approval(
        self,
        approval_id: int,
        *,
        request: dict[str, Any],
        request_digest: str,
    ) -> None:
        self._assert_dispatch_allowed()
        if self._policy_digest(request) != request_digest:
            raise PermissionError("Current policy request digest is invalid")
        expired = False
        with self.db:
            row = self.db.execute(
                "SELECT * FROM scoped_execution_approvals WHERE id=?", (approval_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown scoped approval: {approval_id}")
            if row["status"] != "approved":
                raise PermissionError(
                    f"Scoped approval {approval_id} is {row['status']}, expected approved"
                )
            if self.db.execute(
                "SELECT datetime(?)<=CURRENT_TIMESTAMP", (row["expires_at"],)
            ).fetchone()[0]:
                self.db.execute(
                    "UPDATE scoped_execution_approvals SET status='expired' WHERE id=?",
                    (approval_id,),
                )
                self._event(
                    "policy.approval.expired", "scoped_approval", approval_id, {"task_id": row["task_id"]}
                )
                expired = True
            elif row["request_digest"] != request_digest:
                raise PermissionError("Approval scope does not match the current request digest")
            else:
                self.db.execute(
                    """UPDATE scoped_execution_approvals
                          SET status='consumed',consumed_at=CURRENT_TIMESTAMP
                        WHERE id=? AND status='approved'""",
                    (approval_id,),
                )
                self._event(
                    "policy.approval.consumed",
                    "scoped_approval",
                    approval_id,
                    {**request, "request_digest": request_digest},
                )
        if expired:
            raise PermissionError(f"Scoped approval {approval_id} has expired")

    def set_emergency_stop(self, active: bool, *, actor: str, reason: str) -> bool:
        if not actor.strip() or not reason.strip():
            raise ValueError("Emergency stop requires actor and reason")
        with self.db:
            state = self.db.execute("SELECT * FROM policy_state WHERE id=1").fetchone()
            if bool(state["emergency_stop"]) == active:
                return False
            self.db.execute(
                """UPDATE policy_state
                      SET emergency_stop=?,reason=?,actor=?,version=version+1,
                          updated_at=CURRENT_TIMESTAMP WHERE id=1""",
                (int(active), reason, actor),
            )
            cancelled: dict[str, int] = {}
            if active:
                cancelled["worker_sessions"] = self.db.execute(
                    """UPDATE worker_sessions
                          SET status='cancelled',version=version+1,updated_at=CURRENT_TIMESTAMP
                        WHERE status IN ('starting','running','suspended')"""
                ).rowcount
                cancelled["attempts"] = self.db.execute(
                    """UPDATE attempts
                          SET status='cancelled',version=version+1,updated_at=CURRENT_TIMESTAMP
                        WHERE status IN ('claimed','running')"""
                ).rowcount
                cancelled["assignments"] = self.db.execute(
                    """UPDATE assignments
                          SET status='cancelled',version=version+1,updated_at=CURRENT_TIMESTAMP
                        WHERE status IN ('pending','active','suspended')"""
                ).rowcount
                cancelled["leases"] = self.db.execute(
                    """UPDATE leases
                          SET status='revoked',version=version+1,updated_at=CURRENT_TIMESTAMP
                        WHERE status='active'"""
                ).rowcount
                provider_attempts = self.db.execute(
                    """SELECT id,gate_id FROM provider_execution_attempts
                        WHERE status IN ('claimed','running')"""
                ).fetchall()
                for attempt in provider_attempts:
                    self.db.execute(
                        """UPDATE provider_execution_attempts
                              SET status='abandoned',version=version+1,
                                  result='Cancelled by Control Plane emergency stop',
                                  metadata='{"emergency_stop":true}',
                                  finished_at=CURRENT_TIMESTAMP,
                                  heartbeat_at=CURRENT_TIMESTAMP
                            WHERE id=?""",
                        (attempt["id"],),
                    )
                    self.db.execute(
                        """UPDATE provider_execution_gates
                              SET status='consumed',consumed_at=CURRENT_TIMESTAMP
                            WHERE id=? AND status='claimed'""",
                        (attempt["gate_id"],),
                    )
                cancelled["provider_attempts"] = len(provider_attempts)
                self.db.execute(
                    """UPDATE provider_execution_gates
                          SET status='rejected',decision_note=?,decided_at=CURRENT_TIMESTAMP
                        WHERE status IN ('pending','approved')""",
                    (f"Emergency stop by {actor}: {reason}",),
                )
                self.db.execute("DELETE FROM pending_provider_gate_claims")
                self.db.execute(
                    """UPDATE scoped_execution_approvals
                          SET status='cancelled',decision_note=?,decided_at=CURRENT_TIMESTAMP
                        WHERE status IN ('pending','approved')""",
                    (f"Emergency stop by {actor}: {reason}",),
                )
            self._event(
                "policy.emergency_stop.activated" if active else "policy.emergency_stop.cleared",
                "policy_state",
                1,
                {"active": active, "actor": actor, "reason": reason, "cancelled": cancelled},
            )
        return True

    def record_worker_qualification(
        self,
        *,
        worker_id: str,
        provider_id: str,
        role: str,
        capabilities: list[str],
        dimensions: dict[str, Any],
        evidence: dict[str, Any],
        status: str,
        ttl_seconds: int,
    ) -> int:
        if status not in {"qualified", "failed"}:
            raise ValueError(status)
        required_dimensions = {
            "availability",
            "reliability",
            "quality",
            "safety",
            "performance",
            "cost",
            "freshness",
            "drift",
        }
        if set(dimensions) != required_dimensions:
            raise ValueError("Qualification health dimensions are incomplete")
        evidence_json = json.dumps(
            evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        evidence_digest = hashlib.sha256(evidence_json.encode("utf-8")).hexdigest()
        capabilities_json = json.dumps(sorted(set(capabilities)), separators=(",", ":"))
        with self.db:
            cur = self.db.execute(
                """INSERT INTO worker_qualifications(
                       identity,worker_id,provider_id,role,capabilities_json,
                       dimensions_json,evidence_json,evidence_digest,status,valid_until
                   ) VALUES(?,?,?,?,?,?,?,?,?,datetime('now', ?))""",
                (
                    self._identity("worker-qualification"),
                    worker_id,
                    provider_id,
                    role,
                    capabilities_json,
                    json.dumps(dimensions, sort_keys=True, separators=(",", ":")),
                    evidence_json,
                    evidence_digest,
                    status,
                    f"+{ttl_seconds} seconds",
                ),
            )
            qualification_id = int(cur.lastrowid)
            current = self.db.execute(
                "SELECT state FROM worker_lifecycle WHERE worker_id=?", (worker_id,)
            ).fetchone()
            if not current:
                self.db.execute(
                    """INSERT INTO worker_lifecycle(worker_id,state,reason)
                       VALUES(?,?,?)""",
                    (
                        worker_id,
                        "active" if status == "qualified" else "offline",
                        "qualification passed" if status == "qualified" else "qualification failed",
                    ),
                )
            self._event(
                f"worker.qualification.{status}",
                "worker_qualification",
                qualification_id,
                {
                    "worker_id": worker_id,
                    "provider_id": provider_id,
                    "role": role,
                    "capabilities": sorted(set(capabilities)),
                    "evidence_digest": evidence_digest,
                },
            )
        return qualification_id

    def set_worker_lifecycle(self, worker_id: str, state: str, *, reason: str) -> None:
        allowed = {
            "active": {"draining", "quarantined", "offline"},
            "draining": {"active", "quarantined", "offline"},
            "quarantined": {"active", "offline"},
            "offline": {"active", "quarantined"},
        }
        if state not in allowed:
            raise ValueError(state)
        if not reason.strip():
            raise ValueError("Worker lifecycle reason is required")
        with self.db:
            row = self.db.execute(
                "SELECT state FROM worker_lifecycle WHERE worker_id=?", (worker_id,)
            ).fetchone()
            if not row:
                self.db.execute(
                    "INSERT INTO worker_lifecycle(worker_id,state,reason) VALUES(?,?,?)",
                    (worker_id, state, reason),
                )
                previous = None
            else:
                previous = str(row["state"])
                if previous == state:
                    return
                if state not in allowed[previous]:
                    raise ValueError(f"Invalid worker lifecycle transition: {previous} -> {state}")
                self.db.execute(
                    """UPDATE worker_lifecycle
                          SET state=?,reason=?,version=version+1,updated_at=CURRENT_TIMESTAMP
                        WHERE worker_id=? AND state=?""",
                    (state, reason, worker_id, previous),
                )
            self._event(
                f"worker.{state}",
                "worker",
                worker_id,
                {"worker_id": worker_id, "previous_state": previous, "reason": reason},
            )

    def select_qualified_worker(
        self,
        *,
        role: str,
        required_capabilities: set[str],
        excluded_workers: set[str] | None = None,
    ) -> str | None:
        excluded_workers = excluded_workers or set()
        rows = self.db.execute(
            """SELECT q.*,COALESCE(l.state,'offline') lifecycle_state
                 FROM worker_qualifications q
                 LEFT JOIN worker_lifecycle l ON l.worker_id=q.worker_id
                WHERE q.id=(
                    SELECT MAX(latest.id) FROM worker_qualifications latest
                     WHERE latest.worker_id=q.worker_id
                )
                  AND q.status='qualified' AND q.role=?
                  AND q.valid_until>CURRENT_TIMESTAMP
                  AND COALESCE(l.state,'offline')='active'
                ORDER BY q.worker_id""",
            (role,),
        ).fetchall()
        for row in rows:
            if row["worker_id"] in excluded_workers:
                continue
            capabilities = set(json.loads(row["capabilities_json"]))
            if required_capabilities <= capabilities:
                return str(row["worker_id"])
        return None

    def create_worker_handoff(
        self,
        *,
        source_worker_id: str,
        replacement_worker_id: str,
        task_id: int,
        run_id: int | None,
        stage_id: str,
        attempt_id: str | None,
        context_digest: str,
        evidence: dict[str, Any],
        reason: str,
    ) -> int:
        _sha256_snapshot(context_digest, "context_digest")
        if source_worker_id == replacement_worker_id:
            raise ValueError("Worker handoff requires a distinct replacement")
        with self.db:
            cur = self.db.execute(
                """INSERT INTO worker_handoffs(
                       identity,source_worker_id,replacement_worker_id,task_id,
                       run_id,stage_id,attempt_id,context_digest,evidence_json,reason
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    self._identity("worker-handoff"),
                    source_worker_id,
                    replacement_worker_id,
                    task_id,
                    run_id,
                    stage_id,
                    attempt_id,
                    context_digest,
                    json.dumps(evidence, sort_keys=True),
                    reason,
                ),
            )
            handoff_id = int(cur.lastrowid)
            self._event(
                "worker.handoff.created",
                "worker_handoff",
                handoff_id,
                {
                    "task_id": task_id,
                    "run_id": run_id,
                    "stage_id": stage_id,
                    "attempt_id": attempt_id,
                    "source_worker_id": source_worker_id,
                    "replacement_worker_id": replacement_worker_id,
                    "context_digest": context_digest,
                    "reason": reason,
                },
            )
        return handoff_id

    def create_assignment_attempt(
        self,
        assignment_id: int,
        fencing_token: int,
        *,
        now: datetime | None = None,
    ) -> int:
        current = _timestamp(_utc(now))
        self._begin_immediate()
        try:
            self._expire_scheduler_leases(current)
            lease = self._assert_fenced_lease(
                assignment_id, fencing_token, current
            )
            ordinal = int(
                self.db.execute(
                    "SELECT COALESCE(MAX(ordinal),0)+1 FROM attempts WHERE assignment_id=?",
                    (assignment_id,),
                ).fetchone()[0]
            )
            cursor = self.db.execute(
                """INSERT INTO attempts(
                       identity,assignment_id,ordinal,status,updated_at
                   ) VALUES(?,?,?,'claimed',?)""",
                (
                    self._identity("attempt"),
                    assignment_id,
                    ordinal,
                    current,
                ),
            )
            attempt_id = int(cursor.lastrowid)
            self._event(
                "attempt.claimed",
                "attempt",
                attempt_id,
                {
                    "task_id": int(lease["task_id"]),
                    "assignment_id": assignment_id,
                    "fencing_token": fencing_token,
                    "ordinal": ordinal,
                },
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return attempt_id

    def store_execution_context_package(
        self,
        *,
        task_id: int,
        run_id: int,
        assignment_id: int,
        fencing_token: int,
        digest: str,
        package_json: str,
        byte_count: int,
        token_count: int,
        compacted: bool,
        now: datetime | None = None,
    ) -> int:
        _sha256_snapshot(digest, "context package digest")
        try:
            decoded = json.loads(package_json)
        except json.JSONDecodeError as exc:
            raise ValueError("Context package must be valid JSON") from exc
        canonical = json.dumps(
            decoded, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        if canonical != package_json:
            raise ValueError("Context package JSON must use canonical encoding")
        encoded = package_json.encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() != digest:
            raise ValueError("Context package digest does not match its content")
        if byte_count != len(encoded) or token_count != (len(encoded) + 3) // 4:
            raise ValueError("Context package size metadata does not match its content")

        current = _timestamp(_utc(now))
        self._begin_immediate()
        try:
            self._expire_scheduler_leases(current)
            lease = self._assert_fenced_lease(
                assignment_id, fencing_token, current
            )
            if int(lease["task_id"]) != task_id:
                raise PermissionError("Context package task is not owned by its lease")
            run = self.db.execute(
                "SELECT task_id FROM workflow_runs WHERE id=?", (run_id,)
            ).fetchone()
            if not run:
                raise KeyError(f"Unknown workflow run: {run_id}")
            if int(run["task_id"]) != task_id:
                raise PermissionError("Context package run belongs to another task")
            existing = self.db.execute(
                "SELECT * FROM execution_context_packages WHERE digest=?",
                (digest,),
            ).fetchone()
            if existing:
                expected = (task_id, run_id, assignment_id, fencing_token, package_json)
                stored = (
                    int(existing["task_id"]),
                    int(existing["run_id"]),
                    int(existing["assignment_id"]),
                    int(existing["fencing_token"]),
                    str(existing["package_json"]),
                )
                if stored != expected:
                    raise ValueError("Context digest is already bound to another scope")
                self.db.commit()
                return int(existing["id"])
            cursor = self.db.execute(
                """INSERT INTO execution_context_packages(
                       identity,task_id,run_id,assignment_id,fencing_token,digest,
                       package_json,byte_count,token_count,compacted
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    self._identity("execution-context"),
                    task_id,
                    run_id,
                    assignment_id,
                    fencing_token,
                    digest,
                    package_json,
                    byte_count,
                    token_count,
                    int(compacted),
                ),
            )
            package_id = int(cursor.lastrowid)
            self._event(
                "context.package.created",
                "execution_context_package",
                package_id,
                {
                    "task_id": task_id,
                    "run_id": run_id,
                    "assignment_id": assignment_id,
                    "fencing_token": fencing_token,
                    "digest": digest,
                    "byte_count": byte_count,
                    "token_count": token_count,
                    "compacted": bool(compacted),
                },
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return package_id

    def execution_context_package(self, digest: str):
        _sha256_snapshot(digest, "context package digest")
        row = self.db.execute(
            "SELECT * FROM execution_context_packages WHERE digest=?", (digest,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown execution context package: {digest}")
        return row

    def assert_execution_context_scope(
        self,
        digest: str,
        *,
        task_id: int,
        assignment_id: int,
        fencing_token: int,
    ) -> int:
        row = self.execution_context_package(digest)
        if (
            int(row["task_id"]) != task_id
            or int(row["assignment_id"]) != assignment_id
            or int(row["fencing_token"]) != fencing_token
        ):
            raise PermissionError("Execution context package belongs to another dispatch")
        return int(row["id"])

    def record_hermes_acp_session(
        self,
        *,
        worker_session_id: int,
        task_id: int,
        run_id: int,
        stage_key: str,
        attempt_id: int,
        assignment_id: int,
        fencing_token: int,
        agent_role: str,
        worktree_id: int,
        context_digest: str,
        allowed_tools: tuple[str, ...],
        executable: str,
        hermes_version: str,
        protocol_version: int,
        external_session_id: str,
        process_pid: int | None,
        now: datetime | None = None,
    ) -> int:
        if not stage_key.strip() or not agent_role.strip():
            raise ValueError("Hermes stage and agent role are required")
        if not executable.strip() or not hermes_version.strip():
            raise ValueError("Hermes executable and version evidence are required")
        if protocol_version <= 0 or not external_session_id.strip():
            raise ValueError("Hermes protocol and external session identity are required")
        normalized_tools = tuple(sorted({tool.strip() for tool in allowed_tools if tool.strip()}))
        if not normalized_tools:
            raise ValueError("Hermes requires an explicit non-empty tool allowlist")
        current = _timestamp(_utc(now))
        self._begin_immediate()
        try:
            self._expire_scheduler_leases(current)
            lease = self._assert_fenced_lease(
                assignment_id, fencing_token, current
            )
            if int(lease["task_id"]) != task_id:
                raise PermissionError("Hermes task is not owned by its lease")
            worker_session = self.db.execute(
                "SELECT * FROM worker_sessions WHERE id=?", (worker_session_id,)
            ).fetchone()
            if not worker_session or int(worker_session["assignment_id"]) != assignment_id:
                raise PermissionError("Hermes worker session belongs to another assignment")
            context = self.execution_context_package(context_digest)
            if (
                int(context["task_id"]) != task_id
                or int(context["run_id"]) != run_id
                or int(context["assignment_id"]) != assignment_id
                or int(context["fencing_token"]) != fencing_token
                or int(worker_session["context_package_id"] or 0) != int(context["id"])
            ):
                raise PermissionError("Hermes context package scope does not match")
            stage = self.db.execute(
                "SELECT id,status FROM workflow_stages WHERE run_id=? AND stage_key=?",
                (run_id, stage_key),
            ).fetchone()
            if not stage:
                raise KeyError(f"Unknown Hermes stage {stage_key} for run {run_id}")
            if str(stage["status"]) not in {"running", "waiting_approval"}:
                raise PermissionError("Hermes requires an active durable workflow stage")
            attempt = self.db.execute(
                "SELECT assignment_id,status FROM attempts WHERE id=?", (attempt_id,)
            ).fetchone()
            if (
                not attempt
                or int(attempt["assignment_id"]) != assignment_id
                or str(attempt["status"]) not in {"claimed", "running"}
            ):
                raise PermissionError("Hermes attempt is not active for its assignment")
            worktree = self.db.execute(
                "SELECT * FROM worktrees WHERE id=?", (worktree_id,)
            ).fetchone()
            if (
                not worktree
                or int(worktree["assignment_id"]) != assignment_id
                or int(worktree["fencing_token"] or 0) != fencing_token
                or str(worktree["status"]) not in {"ready", "dirty"}
            ):
                raise PermissionError("Hermes worktree is not owned by its assignment")
            existing = self.db.execute(
                "SELECT * FROM hermes_acp_sessions WHERE worker_session_id=?",
                (worker_session_id,),
            ).fetchone()
            if existing:
                if str(existing["external_session_id"]) != external_session_id:
                    raise ValueError("Worker session already has another Hermes identity")
                self.db.commit()
                return int(existing["id"])
            cursor = self.db.execute(
                """INSERT INTO hermes_acp_sessions(
                       identity,worker_session_id,task_id,run_id,stage_id,attempt_id,
                       assignment_id,fencing_token,agent_role,worktree_id,
                       context_package_id,allowed_tools_json,executable,hermes_version,
                       protocol_version,external_session_id,process_pid,status,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'running',?)""",
                (
                    self._identity("hermes-acp-session"),
                    worker_session_id,
                    task_id,
                    run_id,
                    int(stage["id"]),
                    attempt_id,
                    assignment_id,
                    fencing_token,
                    agent_role,
                    worktree_id,
                    int(context["id"]),
                    json.dumps(normalized_tools, separators=(",", ":")),
                    executable,
                    hermes_version,
                    protocol_version,
                    external_session_id,
                    process_pid,
                    current,
                ),
            )
            hermes_session_id = int(cursor.lastrowid)
            self.db.execute(
                """UPDATE attempts SET status='running',version=version+1,updated_at=?
                    WHERE id=? AND status='claimed'""",
                (current, attempt_id),
            )
            self._event(
                "hermes.session.bound",
                "hermes_acp_session",
                hermes_session_id,
                {
                    "task_id": task_id,
                    "run_id": run_id,
                    "stage_id": stage_key,
                    "attempt_id": attempt_id,
                    "assignment_id": assignment_id,
                    "fencing_token": fencing_token,
                    "worktree_id": worktree_id,
                    "context_digest": context_digest,
                    "external_session_id": external_session_id,
                    "hermes_version": hermes_version,
                    "protocol_version": protocol_version,
                    "allowed_tools": list(normalized_tools),
                },
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return hermes_session_id

    def hermes_acp_session(self, external_session_id: str):
        row = self.db.execute(
            "SELECT * FROM hermes_acp_sessions WHERE external_session_id=?",
            (external_session_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown Hermes ACP session: {external_session_id}")
        return row

    def update_hermes_acp_session(
        self,
        external_session_id: str,
        *,
        status: str,
        process_pid: int | None = None,
    ) -> None:
        if status not in {"running", "suspended", "succeeded", "failed", "cancelled"}:
            raise ValueError(f"Unknown Hermes ACP status: {status}")
        with self.db:
            row = self.hermes_acp_session(external_session_id)
            source = str(row["status"])
            allowed = {
                "running": {"running", "suspended", "succeeded", "failed", "cancelled"},
                "suspended": {"suspended", "running", "failed", "cancelled"},
                "succeeded": {"succeeded"},
                "failed": {"failed"},
                "cancelled": {"cancelled"},
            }
            if status not in allowed[source]:
                raise ValueError(f"Invalid Hermes ACP transition: {source} -> {status}")
            updated = self.db.execute(
                """UPDATE hermes_acp_sessions
                      SET status=?,process_pid=?,version=version+1,
                          updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND version=?""",
                (status, process_pid, int(row["id"]), int(row["version"])),
            )
            if updated.rowcount != 1:
                raise ValueError("Hermes ACP session changed concurrently")
            if status in {"succeeded", "failed", "cancelled"}:
                attempt = self.db.execute(
                    "SELECT status FROM attempts WHERE id=?", (int(row["attempt_id"]),)
                ).fetchone()
                if attempt and str(attempt["status"]) not in {
                    "succeeded",
                    "failed",
                    "cancelled",
                }:
                    ensure_transition("attempt", str(attempt["status"]), status)
                    self.db.execute(
                        """UPDATE attempts
                              SET status=?,version=version+1,updated_at=CURRENT_TIMESTAMP
                            WHERE id=?""",
                        (status, int(row["attempt_id"])),
                    )
            self._event(
                f"hermes.session.{status}",
                "hermes_acp_session",
                int(row["id"]),
                {"external_session_id": external_session_id},
            )

    def create_runtime_session(
        self,
        *,
        assignment_id: int,
        runtime: str,
        request: dict[str, Any],
        context_digest: str | None = None,
        fencing_token: int | None = None,
    ) -> int:
        if not runtime.strip():
            raise ValueError("Runtime identity is required")
        if (context_digest is None) != (fencing_token is None):
            raise ValueError("Context digest and fencing token must be supplied together")
        self._begin_immediate()
        try:
            assignment = self.db.execute(
                "SELECT task_id,status FROM assignments WHERE id=?",
                (assignment_id,),
            ).fetchone()
            if not assignment:
                raise KeyError(f"Unknown assignment: {assignment_id}")
            if str(assignment["status"]) != "active":
                raise ValueError("Runtime session requires an active assignment")
            context_package_id = None
            if context_digest is not None and fencing_token is not None:
                current = _timestamp(_utc())
                self._expire_scheduler_leases(current)
                self._assert_fenced_lease(assignment_id, fencing_token, current)
                context_package_id = self.assert_execution_context_scope(
                    context_digest,
                    task_id=int(assignment["task_id"]),
                    assignment_id=assignment_id,
                    fencing_token=fencing_token,
                )
            cursor = self.db.execute(
                """INSERT INTO worker_sessions(
                       identity,assignment_id,runtime,status,request_json,
                       context_package_id,context_digest,updated_at
                   ) VALUES(?,?,?,'starting',?,?,?,CURRENT_TIMESTAMP)""",
                (
                    self._identity("worker-session"),
                    assignment_id,
                    runtime,
                    json.dumps(request, sort_keys=True),
                    context_package_id,
                    context_digest,
                ),
            )
            session_id = int(cursor.lastrowid)
            self._event(
                "runtime.session.created",
                "worker_session",
                session_id,
                {
                    "task_id": int(assignment["task_id"]),
                    "assignment_id": assignment_id,
                    "runtime": runtime,
                    "context_digest": context_digest,
                },
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return session_id

    def runtime_session(self, session_id: int):
        row = self.db.execute(
            "SELECT * FROM worker_sessions WHERE id=?", (session_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown runtime session: {session_id}")
        return row

    def start_runtime_session(self, session_id: int, external_session_id: str) -> None:
        if not external_session_id.strip():
            raise ValueError("External session identity is required")
        with self.db:
            row = self.runtime_session(session_id)
            if str(row["status"]) != "starting":
                raise ValueError("Only a starting runtime session can bind externally")
            self.db.execute(
                """UPDATE worker_sessions
                      SET external_session_id=?,status='running',version=version+1,
                          updated_at=CURRENT_TIMESTAMP,heartbeat_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='starting'""",
                (external_session_id, session_id),
            )
            self._event(
                "runtime.session.started",
                "worker_session",
                session_id,
                {"external_session_id": external_session_id},
            )

    def resume_runtime_session(self, session_id: int) -> None:
        with self.db:
            row = self.runtime_session(session_id)
            status = str(row["status"])
            if status == "running":
                return
            if status != "suspended":
                raise ValueError(f"Runtime session cannot resume from {status}")
            self.db.execute(
                """UPDATE worker_sessions
                      SET status='running',version=version+1,
                          updated_at=CURRENT_TIMESTAMP,heartbeat_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='suspended'""",
                (session_id,),
            )
            self._event(
                "runtime.session.resumed", "worker_session", session_id, {}
            )

    def suspend_runtime_session(self, session_id: int, *, reason: str) -> None:
        with self.db:
            row = self.runtime_session(session_id)
            if str(row["status"]) != "running":
                raise ValueError("Only a running runtime session can be suspended")
            self.db.execute(
                """UPDATE worker_sessions
                      SET status='suspended',version=version+1,updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='running'""",
                (session_id,),
            )
            self._event(
                "runtime.session.suspended",
                "worker_session",
                session_id,
                {"reason": reason},
            )

    def heartbeat_runtime_session(self, session_id: int) -> str:
        heartbeat = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        with self.db:
            row = self.runtime_session(session_id)
            if str(row["status"]) != "running":
                raise ValueError("Only a running runtime session can heartbeat")
            self.db.execute(
                """UPDATE worker_sessions
                      SET heartbeat_at=?,version=version+1,updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='running'""",
                (heartbeat, session_id),
            )
            self._event(
                "runtime.session.heartbeat",
                "worker_session",
                session_id,
                {"heartbeat_at": heartbeat},
            )
        return heartbeat

    def append_runtime_event(
        self,
        session_id: int,
        *,
        kind: str,
        payload: dict[str, Any],
        mutable: bool = False,
    ) -> int:
        allowed = {"status", "message", "tool_call", "artifact", "heartbeat", "error"}
        if kind not in allowed:
            raise ValueError(f"Unknown runtime event kind: {kind}")
        with self.db:
            self._begin_immediate()
            session = self.runtime_session(session_id)
            if str(session["status"]) not in {"starting", "running", "suspended"}:
                raise ValueError("Cannot append events to a terminal runtime session")
            sequence = int(
                self.db.execute(
                    """SELECT COALESCE(MAX(sequence),0)+1
                         FROM runtime_session_events WHERE session_id=?""",
                    (session_id,),
                ).fetchone()[0]
            )
            cursor = self.db.execute(
                """INSERT INTO runtime_session_events(
                       identity,session_id,sequence,kind,payload_json,mutable
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    self._identity("runtime-event"),
                    session_id,
                    sequence,
                    kind,
                    json.dumps(payload, sort_keys=True),
                    int(mutable),
                ),
            )
            if mutable:
                self.db.execute(
                    """UPDATE worker_sessions
                          SET mutable_action_count=mutable_action_count+1,
                              version=version+1,updated_at=CURRENT_TIMESTAMP
                        WHERE id=?""",
                    (session_id,),
                )
            event_id = int(cursor.lastrowid)
            self._event(
                f"runtime.event.{kind}",
                "worker_session",
                session_id,
                {
                    "event_id": event_id,
                    "sequence": sequence,
                    "mutable": mutable,
                },
            )
        return event_id

    def runtime_events(self, session_id: int, *, after_sequence: int = 0):
        self.runtime_session(session_id)
        return self.db.execute(
            """SELECT * FROM runtime_session_events
                WHERE session_id=? AND sequence>? ORDER BY sequence""",
            (session_id, after_sequence),
        ).fetchall()

    def cancel_runtime_session(self, session_id: int, *, reason: str) -> bool:
        with self.db:
            row = self.runtime_session(session_id)
            status = str(row["status"])
            if status == "cancelled":
                return False
            if status in {"succeeded", "failed"}:
                raise ValueError(f"Terminal runtime session is already {status}")
            self.db.execute(
                """UPDATE worker_sessions
                      SET status='cancelled',version=version+1,
                          updated_at=CURRENT_TIMESTAMP,finalized_at=CURRENT_TIMESTAMP,
                          result_json=? WHERE id=?""",
                (json.dumps({"status": "cancelled", "reason": reason}), session_id),
            )
            self._event(
                "runtime.session.cancelled",
                "worker_session",
                session_id,
                {"reason": reason},
            )
        return True

    def finalize_runtime_session(
        self, session_id: int, *, status: str, result: dict[str, Any]
    ) -> bool:
        if status not in {"succeeded", "failed", "cancelled"}:
            raise ValueError("Runtime terminal status is invalid")
        with self.db:
            row = self.runtime_session(session_id)
            current = str(row["status"])
            if current in {"succeeded", "failed", "cancelled"}:
                if current != status:
                    raise ValueError(
                        f"Runtime session already finalized as {current}"
                    )
                return False
            ensure_transition("worker_session", current, status)
            self.db.execute(
                """UPDATE worker_sessions
                      SET status=?,version=version+1,updated_at=CURRENT_TIMESTAMP,
                          finalized_at=CURRENT_TIMESTAMP,result_json=? WHERE id=?""",
                (status, json.dumps(result, sort_keys=True), session_id),
            )
            self._event(
                "runtime.session.finalized",
                "worker_session",
                session_id,
                {"status": status},
            )
        return True

    def runtime_fallback_allowed(self, session_id: int) -> bool:
        row = self.runtime_session(session_id)
        return int(row["mutable_action_count"]) == 0

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
            if target == "approved":
                evidence = self.criterion_evidence_status(task_id)
                if not evidence["closed"]:
                    raise ValueError(
                        "Work item cannot be approved without accepted primary "
                        f"evidence for criteria: {evidence['missing_criteria']}"
                    )
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

    def task_readiness(self, task_id: int, *, now: datetime | None = None) -> tuple[str, ...]:
        """Return deterministic blockers; an empty tuple means the task is runnable."""

        current = _timestamp(_utc(now))
        row = self.db.execute(
            "SELECT id,project_id,kind,status,dependencies_json FROM work_items WHERE id=?",
            (task_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown task: {task_id}")
        return self._task_blockers(row, current)

    def _task_blockers(self, row: sqlite3.Row, current: str) -> tuple[str, ...]:
        blockers: list[str] = []
        if str(row["kind"]) != "task":
            blockers.append(f"kind:{row['kind']}")
        if str(row["status"]) != "pending":
            blockers.append(f"status:{row['status']}")
        dependency_ids = [int(value) for value in json.loads(row["dependencies_json"])]
        for dependency_id in dependency_ids:
            dependency = self.db.execute(
                "SELECT project_id,status FROM work_items WHERE id=?", (dependency_id,)
            ).fetchone()
            if not dependency or int(dependency["project_id"]) != int(row["project_id"]):
                blockers.append(f"dependency:{dependency_id}:missing")
            elif str(dependency["status"]) not in {"completed", "approved"}:
                blockers.append(
                    f"dependency:{dependency_id}:{dependency['status']}"
                )
        active = self.db.execute(
            """SELECT a.id FROM assignments a
                 JOIN leases l ON l.assignment_id=a.id
                WHERE a.task_id=? AND a.status='active' AND l.status='active'
                  AND l.expires_at>? LIMIT 1""",
            (int(row["id"]), current),
        ).fetchone()
        if active:
            blockers.append(f"assignment:{active['id']}:active")
        return tuple(blockers)

    def runnable_tasks(
        self, project_id: int | None = None, *, now: datetime | None = None
    ) -> list[WorkItem]:
        current = _timestamp(_utc(now))
        query = (
            "SELECT id,project_id,kind,status,dependencies_json FROM work_items"
        )
        parameters: tuple[Any, ...] = ()
        if project_id is not None:
            query += " WHERE project_id=?"
            parameters = (project_id,)
        query += " ORDER BY id"
        return [
            self.get_task(int(row["id"]))
            for row in self.db.execute(query, parameters)
            if not self._task_blockers(row, current)
        ]

    def _expire_scheduler_leases(self, current: str) -> None:
        rows = self.db.execute(
            """SELECT l.id,l.assignment_id,l.fencing_token,a.task_id
                 FROM leases l JOIN assignments a ON a.id=l.assignment_id
                WHERE l.status='active' AND l.expires_at<=?""",
            (current,),
        ).fetchall()
        for row in rows:
            self.db.execute(
                """UPDATE leases SET status='expired',version=version+1,
                          updated_at=? WHERE id=? AND status='active'""",
                (current, int(row["id"])),
            )
            self.db.execute(
                """UPDATE assignments SET status='cancelled',version=version+1,
                          updated_at=? WHERE id=? AND status='active'""",
                (current, int(row["assignment_id"])),
            )
            self._event(
                "lease.expired",
                "assignment",
                int(row["assignment_id"]),
                {
                    "task_id": int(row["task_id"]),
                    "lease_id": int(row["id"]),
                    "fencing_token": int(row["fencing_token"]),
                },
            )

    def claim_runnable_task(
        self,
        task_id: int,
        worker: str,
        runtime: str,
        *,
        ttl_seconds: int = 60,
        conflict_domains: list[str] | tuple[str, ...] | None = None,
        conflict_action: str = "serialize",
        now: datetime | None = None,
    ) -> AssignmentLease:
        if not worker.strip() or not runtime.strip():
            raise ValueError("Worker and runtime are required")
        if not 1 <= ttl_seconds <= 86400:
            raise ValueError("Lease TTL must be between 1 and 86400 seconds")
        if conflict_action not in {"serialize", "escalate"}:
            raise ValueError("Conflict action must be serialize or escalate")
        instant = _utc(now)
        current = _timestamp(instant)
        expires_at = _timestamp(instant + timedelta(seconds=ttl_seconds))
        conflict_error: ConflictDomainBusyError | None = None
        claim: AssignmentLease | None = None
        self._begin_immediate()
        try:
            self._assert_dispatch_allowed()
            self._expire_scheduler_leases(current)
            row = self.db.execute(
                "SELECT id,project_id,kind,status,dependencies_json FROM work_items WHERE id=?",
                (task_id,),
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown task: {task_id}")
            blockers = self._task_blockers(row, current)
            if blockers:
                raise TaskNotRunnableError(
                    f"Task {task_id} is not runnable: {', '.join(blockers)}"
                )
            domains = _normalize_conflict_domains(
                int(row["project_id"]), conflict_domains
            )
            active_rows = self.db.execute(
                """SELECT DISTINCT a.id,a.task_id,d.domain
                     FROM assignments a
                     JOIN leases l ON l.assignment_id=a.id
                     JOIN assignment_conflict_domains d ON d.assignment_id=a.id
                    WHERE a.status='active' AND l.status='active' AND l.expires_at>?
                    ORDER BY a.id,d.domain""",
                (current,),
            ).fetchall()
            conflicting = tuple(
                sorted(
                    {
                        int(active["id"])
                        for active in active_rows
                        if int(active["task_id"]) == task_id
                        or any(
                            _domains_overlap(domain, str(active["domain"]))
                            for domain in domains
                        )
                    }
                )
            )
            if conflicting:
                conflict = self.db.execute(
                    """INSERT INTO scheduler_conflicts(
                           identity,task_id,requested_domains_json,
                           conflicting_assignment_ids_json,action
                       ) VALUES(?,?,?,?,?)""",
                    (
                        self._identity("scheduler-conflict"),
                        task_id,
                        json.dumps(domains),
                        json.dumps(conflicting),
                        conflict_action,
                    ),
                )
                conflict_id = int(conflict.lastrowid)
                self._event(
                    f"scheduler.conflict.{conflict_action}",
                    "task",
                    task_id,
                    {
                        "task_id": task_id,
                        "conflict_id": conflict_id,
                        "domains": list(domains),
                        "conflicting_assignment_ids": list(conflicting),
                    },
                )
                conflict_error = ConflictDomainBusyError(
                    conflicting, escalated=conflict_action == "escalate"
                )
            else:
                assignment = self.db.execute(
                    """INSERT INTO assignments(
                           identity,task_id,agent_id,runtime,status,updated_at
                       ) VALUES(?,?,?,?, 'active',?)""",
                    (
                        self._identity("assignment"),
                        task_id,
                        worker,
                        runtime,
                        current,
                    ),
                )
                assignment_id = int(assignment.lastrowid)
                self.db.executemany(
                    """INSERT INTO assignment_conflict_domains(assignment_id,domain)
                       VALUES(?,?)""",
                    [(assignment_id, domain) for domain in domains],
                )
                fencing_token = int(
                    self.db.execute(
                        "SELECT COALESCE(MAX(fencing_token),0)+1 FROM leases"
                    ).fetchone()[0]
                )
                lease = self.db.execute(
                    """INSERT INTO leases(
                           identity,assignment_id,fencing_token,status,expires_at,updated_at
                       ) VALUES(?,?,?,'active',?,?)""",
                    (
                        self._identity("lease"),
                        assignment_id,
                        fencing_token,
                        expires_at,
                        current,
                    ),
                )
                lease_id = int(lease.lastrowid)
                self._event(
                    "task.claimed",
                    "task",
                    task_id,
                    {
                        "task_id": task_id,
                        "worker": worker,
                        "runtime": runtime,
                        "assignment_id": assignment_id,
                        "lease_id": lease_id,
                        "fencing_token": fencing_token,
                        "expires_at": expires_at,
                        "conflict_domains": list(domains),
                    },
                )
                claim = AssignmentLease(
                    task_id=task_id,
                    assignment_id=assignment_id,
                    lease_id=lease_id,
                    worker=worker,
                    runtime=runtime,
                    fencing_token=fencing_token,
                    expires_at=expires_at,
                    conflict_domains=domains,
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        if conflict_error:
            raise conflict_error
        if claim is None:  # pragma: no cover - defensive invariant
            raise RuntimeError("Scheduler claim did not produce a lease")
        return claim

    def _assert_fenced_lease(
        self, assignment_id: int, fencing_token: int, current: str
    ) -> sqlite3.Row:
        row = self.db.execute(
            """SELECT l.*,a.task_id,a.agent_id,a.status AS assignment_status
                 FROM leases l JOIN assignments a ON a.id=l.assignment_id
                WHERE l.assignment_id=? ORDER BY l.fencing_token DESC LIMIT 1""",
            (assignment_id,),
        ).fetchone()
        if (
            not row
            or int(row["fencing_token"]) != fencing_token
            or str(row["status"]) != "active"
            or str(row["assignment_status"]) != "active"
            or str(row["expires_at"]) <= current
        ):
            raise StaleLeaseError(
                f"Assignment {assignment_id} has no active lease for fencing token "
                f"{fencing_token}"
            )
        return row

    def assert_fenced_lease(
        self, assignment_id: int, fencing_token: int, *, now: datetime | None = None
    ) -> None:
        current = _timestamp(_utc(now))
        stale: StaleLeaseError | None = None
        self._begin_immediate()
        try:
            self._expire_scheduler_leases(current)
            try:
                self._assert_fenced_lease(assignment_id, fencing_token, current)
            except StaleLeaseError as exc:
                stale = exc
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        if stale:
            raise stale

    def renew_task_lease(
        self,
        assignment_id: int,
        fencing_token: int,
        *,
        ttl_seconds: int = 60,
        now: datetime | None = None,
    ) -> str:
        if not 1 <= ttl_seconds <= 86400:
            raise ValueError("Lease TTL must be between 1 and 86400 seconds")
        instant = _utc(now)
        current = _timestamp(instant)
        expires_at = _timestamp(instant + timedelta(seconds=ttl_seconds))
        with self.db:
            self._begin_immediate()
            self._expire_scheduler_leases(current)
            lease = self._assert_fenced_lease(
                assignment_id, fencing_token, current
            )
            self.db.execute(
                """UPDATE leases SET expires_at=?,version=version+1,updated_at=?
                    WHERE id=?""",
                (expires_at, current, int(lease["id"])),
            )
            self._event(
                "lease.renewed",
                "assignment",
                assignment_id,
                {
                    "task_id": int(lease["task_id"]),
                    "fencing_token": fencing_token,
                    "expires_at": expires_at,
                },
            )
        return expires_at

    def release_task_lease(
        self,
        assignment_id: int,
        fencing_token: int,
        *,
        outcome: str = "succeeded",
        now: datetime | None = None,
    ) -> None:
        if outcome not in {"succeeded", "failed", "cancelled"}:
            raise ValueError("Assignment outcome must be succeeded, failed, or cancelled")
        current = _timestamp(_utc(now))
        with self.db:
            self._begin_immediate()
            self._expire_scheduler_leases(current)
            lease = self._assert_fenced_lease(
                assignment_id, fencing_token, current
            )
            self.db.execute(
                """UPDATE leases SET status='released',version=version+1,updated_at=?
                    WHERE id=?""",
                (current, int(lease["id"])),
            )
            self.db.execute(
                """UPDATE assignments SET status=?,version=version+1,updated_at=?
                    WHERE id=?""",
                (outcome, current, assignment_id),
            )
            self._event(
                "lease.released",
                "assignment",
                assignment_id,
                {
                    "task_id": int(lease["task_id"]),
                    "fencing_token": fencing_token,
                    "outcome": outcome,
                },
            )

    def record_fenced_mutation(
        self,
        assignment_id: int,
        fencing_token: int,
        operation: str,
        resource: str,
        *,
        now: datetime | None = None,
    ) -> None:
        """Authorize a Control Plane artifact or commit boundary with a live fence."""

        if operation not in {"artifact", "commit"}:
            raise ValueError("Fenced operation must be artifact or commit")
        current = _timestamp(_utc(now))
        with self.db:
            self._begin_immediate()
            self._expire_scheduler_leases(current)
            lease = self._assert_fenced_lease(
                assignment_id, fencing_token, current
            )
            self._event(
                f"assignment.{operation}.authorized",
                "assignment",
                assignment_id,
                {
                    "task_id": int(lease["task_id"]),
                    "worker": str(lease["agent_id"]),
                    "fencing_token": fencing_token,
                    "resource": resource,
                },
            )

    def create_managed_worktree(
        self,
        *,
        assignment_id: int,
        fencing_token: int,
        repository: str,
        base_sha: str,
        branch: str,
        path: str,
        attempt_id: int | None = None,
        now: datetime | None = None,
    ) -> int:
        current = _timestamp(_utc(now))
        self._begin_immediate()
        try:
            self._expire_scheduler_leases(current)
            lease = self._assert_fenced_lease(
                assignment_id, fencing_token, current
            )
            existing = self.db.execute(
                """SELECT * FROM worktrees
                    WHERE assignment_id=? AND status<>'cleaned' ORDER BY id DESC LIMIT 1""",
                (assignment_id,),
            ).fetchone()
            scope = (repository, base_sha, branch, path, attempt_id)
            if existing:
                stored = (
                    str(existing["repository"]),
                    str(existing["base_sha"]),
                    str(existing["branch"]),
                    str(existing["path"]),
                    int(existing["attempt_id"])
                    if existing["attempt_id"] is not None
                    else None,
                )
                if stored != scope:
                    raise ValueError(
                        "Assignment already owns a different active worktree"
                    )
                self.db.commit()
                return int(existing["id"])
            cursor = self.db.execute(
                """INSERT INTO worktrees(
                       identity,assignment_id,attempt_id,repository,base_sha,
                       branch,path,status,task_id,lease_id,fencing_token,owner,
                       reconciled_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,'provisioning',?,?,?,?,?,?)""",
                (
                    self._identity("worktree"),
                    assignment_id,
                    attempt_id,
                    repository,
                    base_sha,
                    branch,
                    path,
                    int(lease["task_id"]),
                    int(lease["id"]),
                    fencing_token,
                    str(lease["agent_id"]),
                    current,
                    current,
                ),
            )
            worktree_id = int(cursor.lastrowid)
            self._event(
                "worktree.provisioning",
                "worktree",
                worktree_id,
                {
                    "task_id": int(lease["task_id"]),
                    "assignment_id": assignment_id,
                    "lease_id": int(lease["id"]),
                    "fencing_token": fencing_token,
                    "owner": str(lease["agent_id"]),
                    "repository": repository,
                    "base_sha": base_sha,
                    "branch": branch,
                    "path": path,
                },
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return worktree_id

    def managed_worktree(self, worktree_id: int):
        row = self.db.execute(
            "SELECT * FROM worktrees WHERE id=?", (worktree_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown worktree: {worktree_id}")
        return row

    def managed_worktrees(self, repository: str | None = None):
        if repository is None:
            return self.db.execute("SELECT * FROM worktrees ORDER BY id").fetchall()
        return self.db.execute(
            "SELECT * FROM worktrees WHERE repository=? ORDER BY id",
            (repository,),
        ).fetchall()

    def transition_managed_worktree(
        self,
        worktree_id: int,
        target: str,
        *,
        retention_until: str | None = None,
        reconciled_at: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> bool:
        with self.db:
            row = self.managed_worktree(worktree_id)
            source = str(row["status"])
            timestamp = reconciled_at or datetime.now(timezone.utc).isoformat(
                timespec="microseconds"
            )
            if source == target:
                self.db.execute(
                    """UPDATE worktrees
                          SET reconciled_at=?,version=version+1,updated_at=CURRENT_TIMESTAMP
                        WHERE id=?""",
                    (timestamp, worktree_id),
                )
                return False
            ensure_transition("worktree", source, target)
            self.db.execute(
                """UPDATE worktrees
                      SET status=?,retention_until=COALESCE(?,retention_until),
                          reconciled_at=?,version=version+1,updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status=?""",
                (target, retention_until, timestamp, worktree_id, source),
            )
            self._event(
                f"worktree.{target}",
                "worktree",
                worktree_id,
                {
                    "task_id": int(row["task_id"]),
                    "assignment_id": int(row["assignment_id"]),
                    "previous_state": source,
                    "resulting_state": target,
                    **(details or {}),
                },
            )
        return True

    def close(self) -> None:
        self.db.close()

    def integrity_check(self) -> dict[str, Any]:
        messages = [str(row[0]) for row in self.db.execute("PRAGMA integrity_check")]
        audit = self.verify_audit_chain()
        evidence = self.verify_evidence_ledger()
        return {
            "ok": messages == ["ok"] and audit["ok"] and evidence["ok"],
            "messages": messages,
            "audit": audit,
            "evidence": evidence,
        }

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
        self._assert_dispatch_allowed()
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

    def start_durable_run(
        self,
        *,
        project_id: int,
        task_id: int,
        workflow_id: str,
        workflow_version: str,
        definition: dict[str, Any],
        stages: list[dict[str, Any]],
    ) -> int:
        self._assert_dispatch_allowed()
        task = self.db.execute(
            "SELECT project_id FROM work_items WHERE id=?", (task_id,)
        ).fetchone()
        if not task:
            raise KeyError(f"Unknown task: {task_id}")
        if int(task["project_id"]) != project_id:
            raise ValueError(f"Task {task_id} does not belong to project {project_id}")
        definition_json = json.dumps(
            definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        definition_digest = hashlib.sha256(definition_json.encode("utf-8")).hexdigest()
        with self.db:
            try:
                cur = self.db.execute(
                    """INSERT INTO workflow_runs(
                           identity,project_id,task_id,workflow_id,status,
                           workflow_version,definition_digest,definition_json
                       ) VALUES(?,?,?,?, 'running',?,?,?)""",
                    (
                        self._identity("run"),
                        project_id,
                        task_id,
                        workflow_id,
                        workflow_version,
                        definition_digest,
                        definition_json,
                    ),
                )
                run_id = int(cur.lastrowid)
                self.db.execute(
                    "INSERT INTO active_workflow_claims(task_id,workflow_id,run_id) VALUES(?,?,?)",
                    (task_id, workflow_id, run_id),
                )
                for stage in stages:
                    self.db.execute(
                        """INSERT INTO workflow_stages(
                               identity,run_id,stage_key,status,dependencies_json,
                               definition_json
                           ) VALUES(?,?,?,'pending',?,?)""",
                        (
                            self._identity("stage"),
                            run_id,
                            stage["id"],
                            json.dumps(stage.get("depends_on", []), separators=(",", ":")),
                            json.dumps(
                                stage, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                            ),
                        ),
                    )
                self._event(
                    "workflow.started",
                    "run",
                    run_id,
                    {
                        "task_id": task_id,
                        "workflow": workflow_id,
                        "workflow_version": workflow_version,
                        "definition_digest": definition_digest,
                    },
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    f"Active workflow already exists for task {task_id} and workflow {workflow_id}"
                ) from exc
        return run_id

    def durable_run(self, run_id: int):
        row = self.db.execute(
            "SELECT * FROM workflow_runs WHERE id=? AND definition_digest IS NOT NULL",
            (run_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown durable workflow run: {run_id}")
        return row

    def durable_stages(self, run_id: int):
        self.durable_run(run_id)
        return self.db.execute(
            "SELECT * FROM workflow_stages WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()

    def transition_durable_stage(
        self, run_id: int, stage_key: str, target: str, payload: dict[str, Any]
    ) -> None:
        with self.db:
            row = self.db.execute(
                """SELECT s.*,r.checkpoint_sequence,r.task_id
                     FROM workflow_stages s
                     JOIN workflow_runs r ON r.id=s.run_id
                    WHERE s.run_id=? AND s.stage_key=?""",
                (run_id, stage_key),
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown stage {stage_key} for run {run_id}")
            source = str(row["status"])
            ensure_transition("stage", source, target)
            if target == "running":
                succeeded = {
                    value[0]
                    for value in self.db.execute(
                        "SELECT stage_key FROM workflow_stages WHERE run_id=? AND status='succeeded'",
                        (run_id,),
                    )
                }
                missing = set(json.loads(row["dependencies_json"])) - succeeded
                if missing:
                    raise ValueError(f"Stage {stage_key} dependencies are incomplete: {sorted(missing)}")
            sequence = int(row["checkpoint_sequence"]) + 1
            payload_json = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            payload_digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            updated = self.db.execute(
                """UPDATE workflow_stages
                      SET status=?,version=version+1,updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status=?""",
                (target, row["id"], source),
            )
            if updated.rowcount != 1:
                raise ValueError(f"Stage {stage_key} changed concurrently")
            self.db.execute(
                "UPDATE workflow_runs SET checkpoint_sequence=? WHERE id=?",
                (sequence, run_id),
            )
            self.db.execute(
                """INSERT INTO stage_checkpoints(
                       identity,run_id,stage_id,sequence,state,payload_json,payload_digest
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    self._identity("checkpoint"),
                    run_id,
                    row["id"],
                    sequence,
                    target,
                    payload_json,
                    payload_digest,
                ),
            )
            self._event(
                f"stage.{target}",
                "stage",
                row["id"],
                {
                    "task_id": row["task_id"],
                    "run_id": run_id,
                    "stage_id": stage_key,
                    "sequence": sequence,
                    "payload_digest": payload_digest,
                },
            )

    def reserve_workflow_mutation(
        self,
        *,
        run_id: int,
        stage_key: str,
        operation: str,
        idempotency_key: str,
        request: dict[str, Any],
    ):
        if operation not in {"provider_call", "worktree", "github"}:
            raise ValueError(operation)
        if not idempotency_key.strip():
            raise ValueError("Mutation idempotency key is required")
        request_json = json.dumps(request, sort_keys=True, separators=(",", ":"))
        request_digest = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        created = False
        with self.db:
            stage = self.db.execute(
                "SELECT id FROM workflow_stages WHERE run_id=? AND stage_key=?",
                (run_id, stage_key),
            ).fetchone()
            if not stage:
                raise KeyError(f"Unknown stage {stage_key} for run {run_id}")
            existing = self.db.execute(
                """SELECT * FROM workflow_mutations
                    WHERE run_id=? AND operation=? AND idempotency_key=?""",
                (run_id, operation, idempotency_key),
            ).fetchone()
            if existing:
                if int(existing["stage_id"]) != int(stage["id"]) or existing["request_digest"] != request_digest:
                    raise ValueError("Idempotency key was already bound to a different mutation")
                return existing, created
            cur = self.db.execute(
                """INSERT INTO workflow_mutations(
                       identity,run_id,stage_id,operation,idempotency_key,request_digest
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    self._identity("workflow-mutation"),
                    run_id,
                    stage["id"],
                    operation,
                    idempotency_key,
                    request_digest,
                ),
            )
            mutation_id = int(cur.lastrowid)
            created = True
            self._event(
                "workflow.mutation.reserved",
                "workflow_mutation",
                mutation_id,
                {
                    "run_id": run_id,
                    "stage_id": stage_key,
                    "operation": operation,
                    "idempotency_key": idempotency_key,
                    "request_digest": request_digest,
                },
            )
        return self.db.execute(
            "SELECT * FROM workflow_mutations WHERE id=?", (mutation_id,)
        ).fetchone(), created

    def complete_workflow_mutation(
        self, mutation_id: int, result: dict[str, Any]
    ) -> bool:
        result_json = json.dumps(result, sort_keys=True, separators=(",", ":"))
        with self.db:
            row = self.db.execute(
                "SELECT * FROM workflow_mutations WHERE id=?", (mutation_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown workflow mutation: {mutation_id}")
            if row["status"] == "completed":
                if row["result_json"] != result_json:
                    raise ValueError("Completed mutation result is immutable")
                return False
            if row["status"] != "reserved":
                raise ValueError(f"Workflow mutation {mutation_id} is {row['status']}")
            self.db.execute(
                """UPDATE workflow_mutations
                      SET status='completed',result_json=?,completed_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='reserved'""",
                (result_json, mutation_id),
            )
            self._event(
                "workflow.mutation.completed",
                "workflow_mutation",
                mutation_id,
                {"run_id": row["run_id"], "operation": row["operation"]},
            )
        return True

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

    def add_artifact(
        self,
        run_id: int,
        stage: str,
        agent_id: str,
        provider: str,
        content: str,
        *,
        producer: dict[str, Any] | None = None,
        verifier: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        toolchain: dict[str, Any] | None = None,
        evidence_kind: str = "review",
    ) -> int:
        if evidence_kind not in {"test_result", "diff", "review", "summary"}:
            raise ValueError(f"Unknown evidence kind: {evidence_kind}")
        producer = producer or {"agent_id": agent_id, "provider": provider}
        verifier = verifier or {"status": "unverified"}
        inputs = inputs or {"run_id": run_id, "stage": stage}
        toolchain = toolchain or {"provider": provider}
        with self.db:
            return self._insert_artifact(
                run_id,
                stage,
                agent_id,
                provider,
                content,
                producer,
                verifier,
                inputs,
                toolchain,
                evidence_kind,
            )

    def _insert_artifact(
        self,
        run_id: int,
        stage: str,
        agent_id: str,
        provider: str,
        content: str,
        producer: dict[str, Any],
        verifier: dict[str, Any],
        inputs: dict[str, Any],
        toolchain: dict[str, Any],
        evidence_kind: str,
    ) -> int:
        cur = self.db.execute(
            """INSERT INTO artifacts(
                   identity,run_id,stage,agent_id,provider,content,digest,
                   producer_json,verifier_json,inputs_json,toolchain_json,
                   evidence_kind
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self._identity("artifact"),
                run_id,
                stage,
                agent_id,
                provider,
                content,
                self._content_digest(content),
                json.dumps(producer, sort_keys=True),
                json.dumps(verifier, sort_keys=True),
                json.dumps(inputs, sort_keys=True),
                json.dumps(toolchain, sort_keys=True),
                evidence_kind,
            ),
        )
        artifact_id = int(cur.lastrowid)
        self._event(
            "artifact.created",
            "artifact",
            artifact_id,
            {"stage": stage, "provider": provider},
        )
        return artifact_id

    def add_fenced_artifact(
        self,
        assignment_id: int,
        fencing_token: int,
        run_id: int,
        stage: str,
        provider: str,
        content: str,
        *,
        evidence_kind: str = "review",
        now: datetime | None = None,
    ) -> int:
        """Atomically verify assignment authority and persist a worker artifact."""

        if evidence_kind not in {"test_result", "diff", "review", "summary"}:
            raise ValueError(f"Unknown evidence kind: {evidence_kind}")
        current = _timestamp(_utc(now))
        with self.db:
            self._begin_immediate()
            self._expire_scheduler_leases(current)
            lease = self._assert_fenced_lease(
                assignment_id, fencing_token, current
            )
            run = self.db.execute(
                "SELECT task_id FROM workflow_runs WHERE id=?", (run_id,)
            ).fetchone()
            if not run:
                raise KeyError(f"Unknown run: {run_id}")
            if int(run["task_id"]) != int(lease["task_id"]):
                raise PermissionError("Assignment lease does not own the workflow task")
            worker = str(lease["agent_id"])
            artifact_id = self._insert_artifact(
                run_id,
                stage,
                worker,
                provider,
                content,
                {
                    "agent_id": worker,
                    "provider": provider,
                    "assignment_id": assignment_id,
                    "fencing_token": fencing_token,
                },
                {"status": "unverified"},
                {
                    "run_id": run_id,
                    "stage": stage,
                    "assignment_id": assignment_id,
                    "fencing_token": fencing_token,
                },
                {"provider": provider},
                evidence_kind,
            )
            self._event(
                "assignment.artifact.authorized",
                "assignment",
                assignment_id,
                {
                    "task_id": int(lease["task_id"]),
                    "artifact_id": artifact_id,
                    "fencing_token": fencing_token,
                },
            )
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
                """UPDATE artifacts
                      SET status=?,review_note=?,version=version+1,verifier_json=?
                    WHERE id=? AND status='pending'""",
                (
                    status,
                    note,
                    json.dumps(
                        {"type": "human_artifact_review", "decision": status, "note": note},
                        sort_keys=True,
                    ),
                    artifact_id,
                ),
            )
            if updated.rowcount != 1:
                row = self.db.execute("SELECT status FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
                if not row:
                    raise KeyError(f"Unknown artifact: {artifact_id}")
                raise ValueError(f"Artifact {artifact_id} is already {row['status']}")
            self._event(f"artifact.{status}", "artifact", artifact_id, {"note": note})

    def link_criterion_evidence(
        self,
        *,
        task_id: int,
        criterion_index: int,
        artifact_id: int,
        evidence_type: str,
    ) -> int:
        if evidence_type not in {"test_result", "diff", "review", "summary"}:
            raise ValueError(f"Unknown evidence type: {evidence_type}")
        task = self.get_task(task_id)
        if criterion_index < 0 or criterion_index >= len(task.acceptance_criteria):
            raise ValueError(f"Unknown criterion index {criterion_index} for task {task_id}")
        artifact = self.db.execute(
            """SELECT a.*,r.task_id
                 FROM artifacts a
                 JOIN workflow_runs r ON r.id=a.run_id
                WHERE a.id=?""",
            (artifact_id,),
        ).fetchone()
        if not artifact:
            raise KeyError(f"Unknown artifact: {artifact_id}")
        if int(artifact["task_id"]) != task_id:
            raise ValueError("Evidence artifact belongs to a different work item")
        if artifact["evidence_kind"] != evidence_type:
            raise ValueError(
                f"Artifact is typed {artifact['evidence_kind']}, not {evidence_type}"
            )
        with self.db:
            existing = self.db.execute(
                """SELECT id FROM criterion_evidence
                    WHERE task_id=? AND criterion_index=? AND artifact_id=?
                      AND evidence_type=?""",
                (task_id, criterion_index, artifact_id, evidence_type),
            ).fetchone()
            if existing:
                return int(existing["id"])
            cur = self.db.execute(
                """INSERT INTO criterion_evidence(
                       identity,task_id,criterion_index,criterion_text,artifact_id,
                       evidence_type,primary_evidence,artifact_digest
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    self._identity("criterion-evidence"),
                    task_id,
                    criterion_index,
                    task.acceptance_criteria[criterion_index],
                    artifact_id,
                    evidence_type,
                    int(evidence_type != "summary"),
                    artifact["digest"],
                ),
            )
            evidence_id = int(cur.lastrowid)
            self._event(
                "evidence.linked",
                "criterion_evidence",
                evidence_id,
                {
                    "task_id": task_id,
                    "run_id": artifact["run_id"],
                    "stage": artifact["stage"],
                    "artifact_id": artifact_id,
                    "criterion_index": criterion_index,
                    "evidence_type": evidence_type,
                    "primary_evidence": evidence_type != "summary",
                },
            )
        return evidence_id

    def decide_criterion_evidence(
        self,
        evidence_id: int,
        decision: str,
        *,
        verifier: str,
        note: str = "",
    ) -> bool:
        if decision not in {"accepted", "rejected"}:
            raise ValueError(decision)
        if not verifier.strip():
            raise ValueError("Evidence verifier is required")
        with self.db:
            row = self.db.execute(
                """SELECT e.*,a.content,a.digest,a.run_id,a.stage
                     FROM criterion_evidence e
                     JOIN artifacts a ON a.id=e.artifact_id
                    WHERE e.id=?""",
                (evidence_id,),
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown criterion evidence: {evidence_id}")
            if row["status"] == decision:
                return False
            if row["status"] != "proposed":
                raise ValueError(f"Evidence {evidence_id} is already {row['status']}")
            current_digest = self._content_digest(str(row["content"]))
            if current_digest != row["artifact_digest"] or current_digest != row["digest"]:
                raise ValueError("Evidence artifact digest changed before verification")
            verifier_record = json.dumps(
                {"verifier": verifier, "decision": decision, "note": note},
                sort_keys=True,
            )
            if decision == "accepted":
                already_locked = self.db.execute(
                    """SELECT 1 FROM criterion_evidence
                        WHERE artifact_id=? AND status='accepted' LIMIT 1""",
                    (row["artifact_id"],),
                ).fetchone()
                if not already_locked:
                    self.db.execute(
                        "UPDATE artifacts SET verifier_json=? WHERE id=?",
                        (verifier_record, row["artifact_id"]),
                    )
            updated = self.db.execute(
                """UPDATE criterion_evidence
                      SET status=?,verifier_json=?,version=version+1,
                          decided_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='proposed'""",
                (decision, verifier_record, evidence_id),
            )
            if updated.rowcount != 1:
                raise ValueError(f"Evidence {evidence_id} changed concurrently")
            self._event(
                f"evidence.{decision}",
                "criterion_evidence",
                evidence_id,
                {
                    "task_id": row["task_id"],
                    "run_id": row["run_id"],
                    "stage": row["stage"],
                    "artifact_id": row["artifact_id"],
                    "criterion_index": row["criterion_index"],
                    "evidence_type": row["evidence_type"],
                    "verifier": verifier,
                    "note": note,
                },
            )
        return True

    def criterion_evidence_status(self, task_id: int) -> dict[str, Any]:
        task = self.get_task(task_id)
        rows = self.db.execute(
            """SELECT * FROM criterion_evidence
                WHERE task_id=? ORDER BY criterion_index,id""",
            (task_id,),
        ).fetchall()
        accepted_primary = {
            int(row["criterion_index"])
            for row in rows
            if row["status"] == "accepted" and int(row["primary_evidence"]) == 1
        }
        missing = [
            {"index": index, "criterion": criterion}
            for index, criterion in enumerate(task.acceptance_criteria)
            if index not in accepted_primary
        ]
        return {
            "task_id": task_id,
            "closed": not missing,
            "missing_criteria": missing,
            "evidence": [
                {
                    "id": int(row["id"]),
                    "criterion_index": int(row["criterion_index"]),
                    "artifact_id": int(row["artifact_id"]),
                    "evidence_type": str(row["evidence_type"]),
                    "primary": bool(row["primary_evidence"]),
                    "status": str(row["status"]),
                    "digest": str(row["artifact_digest"]),
                }
                for row in rows
            ],
        }

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
        self._assert_dispatch_allowed()
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
            cur = self.db.execute(
                """INSERT INTO provider_execution_artifacts(
                       identity,gate_id,attempt_id,provider,agent_id,content,
                       metadata,status,digest,producer_json,verifier_json,
                       inputs_json,toolchain_json
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self._identity("provider-artifact"),
                    row["gate_id"],
                    attempt_id,
                    row["provider"],
                    row["agent_id"],
                    content,
                    json.dumps(metadata),
                    status,
                    self._content_digest(content),
                    json.dumps(
                        {"agent_id": row["agent_id"], "provider": row["provider"]},
                        sort_keys=True,
                    ),
                    json.dumps({"status": "unverified"}, sort_keys=True),
                    json.dumps(
                        {"gate_id": row["gate_id"], "attempt_id": attempt_id},
                        sort_keys=True,
                    ),
                    json.dumps(
                        {"provider": row["provider"], "metadata": metadata},
                        sort_keys=True,
                    ),
                ),
            )
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
            cur = self.db.execute(
                """INSERT INTO provider_execution_artifacts(
                       identity,gate_id,provider,agent_id,content,metadata,digest,
                       producer_json,verifier_json,inputs_json,toolchain_json
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self._identity("provider-artifact"),
                    gate_id,
                    provider,
                    agent_id,
                    content,
                    json.dumps(metadata),
                    self._content_digest(content),
                    json.dumps(
                        {"agent_id": agent_id, "provider": provider}, sort_keys=True
                    ),
                    json.dumps({"status": "unverified"}, sort_keys=True),
                    json.dumps({"gate_id": gate_id, "attempt_id": None}, sort_keys=True),
                    json.dumps(
                        {"provider": provider, "metadata": metadata}, sort_keys=True
                    ),
                ),
            )
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
