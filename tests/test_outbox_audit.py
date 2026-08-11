import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from agent_factory.models import WorkItem
from agent_factory.storage import SQLiteStorage


class TransactionalOutboxTests(unittest.TestCase):
    def fixture(self, root: Path):
        storage = SQLiteStorage(root / "state.db")
        project_id = storage.create_project("Example", "Outbox checks")
        task_id = storage.create_task(WorkItem("Task", "Description", project_id))
        return storage, project_id, task_id

    def test_state_and_outbox_event_commit_or_rollback_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, project_id, task_id = self.fixture(Path(tmp))
            before_events = storage.db.execute("SELECT count(*) FROM events").fetchone()[0]
            before_outbox = storage.db.execute(
                "SELECT count(*) FROM outbox_messages"
            ).fetchone()[0]
            with patch.object(storage, "_event", side_effect=RuntimeError("audit failed")):
                with self.assertRaisesRegex(RuntimeError, "audit failed"):
                    storage.transition_task(task_id, "running")
            self.assertEqual(storage.get_task(task_id).status.value, "pending")
            self.assertEqual(
                storage.db.execute("SELECT count(*) FROM events").fetchone()[0],
                before_events,
            )
            self.assertEqual(
                storage.db.execute("SELECT count(*) FROM outbox_messages").fetchone()[0],
                before_outbox,
            )

            storage.transition_task(task_id, "running")
            self.assertEqual(storage.get_task(task_id).status.value, "running")
            self.assertEqual(
                storage.db.execute("SELECT count(*) FROM events").fetchone()[0],
                before_events + 1,
            )
            self.assertEqual(
                storage.db.execute("SELECT count(*) FROM outbox_messages").fetchone()[0],
                before_outbox + 1,
            )
            event_id, outbox_event_id = storage.db.execute(
                """SELECT e.id,o.event_id FROM events e
                    JOIN outbox_messages o ON o.event_id=e.id
                    ORDER BY e.id DESC LIMIT 1"""
            ).fetchone()
            self.assertEqual(event_id, outbox_event_id)
            storage.close()

    def test_delivery_key_is_stable_and_delivered_message_cannot_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, _, _ = self.fixture(Path(tmp))
            claimed = storage.claim_outbox("test-consumer", limit=1)
            self.assertEqual(len(claimed), 1)
            message = claimed[0]
            self.assertTrue(message["delivery_key"].startswith("event:"))
            self.assertTrue(
                storage.acknowledge_outbox(message["id"], message["claim_token"])
            )
            self.assertFalse(
                storage.acknowledge_outbox(message["id"], message["claim_token"])
            )
            claimed_again = storage.claim_outbox("test-consumer", limit=100)
            self.assertNotIn(message["id"], [row["id"] for row in claimed_again])
            storage.close()

    def test_failed_delivery_reuses_delivery_key_with_a_new_claim_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, _, _ = self.fixture(Path(tmp))
            first = storage.claim_outbox("consumer", limit=1)[0]
            storage.fail_outbox(first["id"], first["claim_token"], "temporary")
            second = storage.claim_outbox("consumer", limit=1)[0]
            self.assertEqual(first["delivery_key"], second["delivery_key"])
            self.assertNotEqual(first["claim_token"], second["claim_token"])
            self.assertEqual(second["attempts"], 2)
            storage.close()


class AuditChainTests(unittest.TestCase):
    def test_every_event_has_complete_correlation_and_valid_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "state.db")
            project_id = storage.create_project("Example", "Correlation checks")
            task_id = storage.create_task(WorkItem("Task", "Description", project_id))
            run_id = storage.start_run(project_id, task_id, "delivery")
            artifact_id = storage.add_artifact(
                run_id, "implementation", "worker", "direct", "evidence"
            )
            report = storage.verify_audit_chain()
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["checked"], 4)
            required = {
                "mission_id",
                "task_id",
                "run_id",
                "stage_id",
                "attempt_id",
                "worker_session_id",
            }
            for row in storage.db.execute("SELECT * FROM events ORDER BY id"):
                self.assertEqual(set(json.loads(row["correlation_json"])), required)
                self.assertEqual(len(row["record_hash"]), 64)
            artifact_event = storage.db.execute(
                "SELECT correlation_json FROM events WHERE entity_type='artifact' AND entity_id=?",
                (str(artifact_id),),
            ).fetchone()
            correlation = json.loads(artifact_event["correlation_json"])
            self.assertEqual(correlation["mission_id"], project_id)
            self.assertEqual(correlation["task_id"], task_id)
            self.assertEqual(correlation["run_id"], run_id)
            self.assertEqual(correlation["stage_id"], "implementation")
            storage.close()

    def test_mutation_is_blocked_and_out_of_band_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "state.db")
            storage.create_project("Example", "Integrity")
            with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                storage.db.execute("UPDATE events SET payload='{}' WHERE id=1")
            with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                storage.db.execute("DELETE FROM events WHERE id=1")

            storage.db.execute("DROP TRIGGER events_no_update")
            storage.db.execute("UPDATE events SET payload='{}' WHERE id=1")
            storage.db.commit()
            report = storage.verify_audit_chain()
            self.assertFalse(report["ok"])
            self.assertIn("record hash does not match", report["failures"][0]["reasons"])
            self.assertFalse(storage.integrity_check()["ok"])
            storage.close()

    def test_concurrent_event_writers_preserve_one_serial_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.db"
            bootstrap = SQLiteStorage(path)
            bootstrap.close()

            def write_event(index: int) -> None:
                connection = SQLiteStorage(path)
                try:
                    connection.event("concurrent.test", "system", index, {"index": index})
                finally:
                    connection.close()

            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(write_event, range(20)))

            storage = SQLiteStorage(path)
            report = storage.verify_audit_chain()
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["checked"], 20)
            self.assertEqual(
                storage.db.execute("SELECT count(*) FROM outbox_messages").fetchone()[0],
                20,
            )
            storage.close()


if __name__ == "__main__":
    unittest.main()
