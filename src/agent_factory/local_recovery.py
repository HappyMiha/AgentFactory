"""Read-only local recovery inspection and orphan classification."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .storage import SQLiteStorage
from .worktrees import WorktreeManager, WorktreeReconciliation


@dataclass(frozen=True)
class RecoverySnapshot:
    run_id: int
    run_status: str
    stages: tuple[dict[str, Any], ...]
    lease: dict[str, Any] | None
    hermes_session: dict[str, Any] | None
    context: dict[str, Any] | None
    worktree: dict[str, Any] | None
    pending_approvals: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class OrphanReport:
    provider_process_ids: tuple[int, ...]
    hermes_session_ids: tuple[int, ...]
    worktree_paths: tuple[str, ...]
    worktree_reconciliation: WorktreeReconciliation | None


class LocalRecoveryService:
    """Reconstruct authority without destructive adoption, cleanup, or retry."""

    def __init__(
        self,
        storage: SQLiteStorage,
        *,
        process_alive: Callable[[int], bool] | None = None,
    ):
        self.storage = storage
        self.process_alive = process_alive or self._process_alive

    @staticmethod
    def _process_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except (OSError, ValueError):
            return False
        return True

    def snapshot(self, run_id: int) -> RecoverySnapshot:
        run = self.storage.durable_run(run_id)
        stages = tuple(dict(row) for row in self.storage.durable_stages(run_id))
        lease = self.storage.db.execute(
            """SELECT l.*,a.id AS assignment_id,a.agent_id,a.runtime,a.status AS assignment_status
                 FROM assignments a JOIN leases l ON l.assignment_id=a.id
                WHERE a.task_id=? ORDER BY l.id DESC LIMIT 1""",
            (run["task_id"],),
        ).fetchone()
        hermes = self.storage.db.execute(
            "SELECT * FROM hermes_acp_sessions WHERE run_id=? ORDER BY id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        context = self.storage.db.execute(
            "SELECT * FROM execution_context_packages WHERE run_id=? ORDER BY id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        worktree = self.storage.db.execute(
            """SELECT w.* FROM worktrees w JOIN assignments a ON a.id=w.assignment_id
                WHERE a.task_id=? ORDER BY w.id DESC LIMIT 1""",
            (run["task_id"],),
        ).fetchone()
        approvals: list[dict[str, Any]] = []
        for row in self.storage.db.execute(
            """SELECT id,status,stage_id,request_digest FROM scoped_execution_approvals
                WHERE run_id=? AND status IN ('pending','approved') ORDER BY id""",
            (run_id,),
        ):
            approvals.append({"kind": "stage", **dict(row)})
        for row in self.storage.db.execute(
            "SELECT id,status FROM approval_gates WHERE run_id=? AND status='pending' ORDER BY id",
            (run_id,),
        ):
            approvals.append({"kind": "founder", **dict(row)})
        delivery = self.storage.db.execute(
            "SELECT github_gate_id FROM coding_delivery_runs WHERE run_id=? ORDER BY id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if delivery and delivery["github_gate_id"] is not None:
            gate = self.storage.db.execute(
                "SELECT id,status,plan_hash FROM github_mutation_gates WHERE id=? AND status='pending'",
                (delivery["github_gate_id"],),
            ).fetchone()
            if gate:
                approvals.append({"kind": "github", **dict(gate)})
        return RecoverySnapshot(
            run_id, str(run["status"]), stages,
            dict(lease) if lease else None, dict(hermes) if hermes else None,
            dict(context) if context else None, dict(worktree) if worktree else None,
            tuple(approvals),
        )

    def detect_orphans(
        self,
        *,
        repository: Path | None = None,
        worktrees: WorktreeManager | None = None,
    ) -> OrphanReport:
        provider_ids = tuple(
            int(row["id"])
            for row in self.storage.db.execute(
                """SELECT id,pid FROM provider_execution_attempts
                    WHERE status IN ('claimed','running') AND pid IS NOT NULL ORDER BY id"""
            )
            if not self.process_alive(int(row["pid"]))
        )
        hermes_ids = tuple(
            int(row["id"])
            for row in self.storage.db.execute(
                """SELECT h.id,h.process_pid,h.status,w.status AS worker_status
                     FROM hermes_acp_sessions h
                     JOIN worker_sessions w ON w.id=h.worker_session_id
                    WHERE h.status IN ('running','suspended') ORDER BY h.id"""
            )
            if (
                row["process_pid"] is None
                or not self.process_alive(int(row["process_pid"]))
                or row["worker_status"] in {"succeeded", "failed", "cancelled"}
            )
        )
        reconciliation = None
        if repository is not None or worktrees is not None:
            if repository is None or worktrees is None:
                raise ValueError("Repository and worktree manager must be supplied together")
            reconciliation = worktrees.reconcile(repository)
        return OrphanReport(
            provider_ids, hermes_ids,
            reconciliation.orphaned_paths if reconciliation else (),
            reconciliation,
        )

    def verify_restore(self) -> dict[str, Any]:
        integrity = self.storage.integrity_check()
        foreign_keys = [tuple(row) for row in self.storage.db.execute("PRAGMA foreign_key_check")]
        return {
            "ok": integrity["ok"] and not foreign_keys,
            "database": integrity["messages"],
            "artifacts": integrity["evidence"],
            "audit": integrity["audit"],
            "foreign_keys": foreign_keys,
        }

    def record_inspection(
        self,
        *,
        run_id: int | None,
        snapshot: RecoverySnapshot | None = None,
        orphans: OrphanReport | None = None,
    ) -> int:
        if run_id is not None and snapshot is None:
            snapshot = self.snapshot(run_id)
        if snapshot is not None and snapshot.run_id != run_id:
            raise ValueError("Recovery snapshot belongs to another run")
        orphans = orphans or self.detect_orphans()
        integrity = self.verify_restore()
        document = {
            "snapshot": asdict(snapshot) if snapshot else None,
            "provider_process_ids": orphans.provider_process_ids,
            "hermes_session_ids": orphans.hermes_session_ids,
            "worktree_paths": orphans.worktree_paths,
            "integrity": integrity,
        }
        payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        existing = self.storage.db.execute(
            "SELECT id FROM recovery_inspections WHERE snapshot_digest=?", (digest,)
        ).fetchone()
        if existing:
            return int(existing["id"])
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO recovery_inspections(
                       identity,run_id,snapshot_json,snapshot_digest,integrity_json,
                       orphan_provider_processes_json,orphan_hermes_sessions_json,
                       orphan_worktrees_json
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("recovery-inspection"), run_id,
                    json.dumps(asdict(snapshot) if snapshot else None, sort_keys=True),
                    digest, json.dumps(integrity, sort_keys=True),
                    json.dumps(orphans.provider_process_ids),
                    json.dumps(orphans.hermes_session_ids),
                    json.dumps(orphans.worktree_paths),
                ),
            )
            inspection_id = int(cursor.lastrowid)
            self.storage._event("recovery.inspected", "recovery_inspection", inspection_id, {
                "run_id": run_id, "snapshot_digest": digest,
                "integrity_ok": integrity["ok"], "destructive_action": False,
            })
        return inspection_id
