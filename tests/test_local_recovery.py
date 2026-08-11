import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.local_recovery import LocalRecoveryService
from agent_factory.models import WorkItem
from agent_factory.storage import SQLiteStorage


class LocalRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.storage = SQLiteStorage(self.root / "state.db")
        self.project_id = self.storage.create_project("Recovery", "AF-057")
        self.task_id = self.storage.create_task(WorkItem(
            "Recover", "Inspect local authority", self.project_id,
        ))
        self.run_id = self.storage.start_durable_run(
            project_id=self.project_id, task_id=self.task_id,
            workflow_id="recovery", workflow_version="1",
            definition={"id": "recovery"},
            stages=[{"id": "inspect", "depends_on": []}],
        )

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def test_orphan_provider_process_is_classified_without_destructive_action(self):
        gate = self.storage.request_provider_execution(
            "codex", "worker", self.task_id, "a" * 64, "b" * 64
        )
        self.storage.decide_provider_execution(gate, "approved", "recoverable")
        attempt = self.storage.claim_provider_execution(gate, "a" * 64, "b" * 64)
        self.storage.mark_provider_attempt_running(int(attempt["id"]), 12345)
        service = LocalRecoveryService(self.storage, process_alive=lambda pid: False)
        report = service.detect_orphans()
        self.assertEqual(report.provider_process_ids, (int(attempt["id"]),))
        self.assertEqual(report.hermes_session_ids, ())
        self.assertEqual(report.worktree_paths, ())
        current = self.storage.db.execute(
            "SELECT status FROM provider_execution_attempts WHERE id=?", (attempt["id"],)
        ).fetchone()
        self.assertEqual(current["status"], "running")

    def test_restore_verifies_artifact_digest_audit_and_foreign_keys(self):
        artifact_id = self.storage.add_artifact(
            self.run_id, "inspect", "recovery", "deterministic", "intact evidence"
        )
        service = LocalRecoveryService(self.storage)
        verified = service.verify_restore()
        self.assertTrue(verified["ok"])
        inspection_id = service.record_inspection(
            run_id=self.run_id, snapshot=service.snapshot(self.run_id)
        )
        row = self.storage.db.execute(
            "SELECT * FROM recovery_inspections WHERE id=?", (inspection_id,)
        ).fetchone()
        self.assertEqual(len(row["snapshot_digest"]), 64)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE recovery_inspections SET snapshot_json='{}' WHERE id=?",
                (inspection_id,),
            )

        self.storage.db.execute(
            "UPDATE artifacts SET content='tampered evidence' WHERE id=?", (artifact_id,)
        )
        failed = service.verify_restore()
        self.assertFalse(failed["ok"])
        self.assertFalse(failed["artifacts"]["ok"])


if __name__ == "__main__":
    unittest.main()
