import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.storage import MIGRATIONS, SQLiteStorage


class StorageMigrationTests(unittest.TestCase):
    def test_migrations_are_versioned_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.db"
            storage = SQLiteStorage(path)
            versions = [
                row[0]
                for row in storage.db.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
            self.assertEqual(versions, [version for version, _ in MIGRATIONS])
            storage.close()

            reopened = SQLiteStorage(path)
            self.assertEqual(
                reopened.db.execute(
                    "SELECT count(*) FROM schema_migrations"
                ).fetchone()[0],
                len(MIGRATIONS),
            )
            self.assertEqual(
                reopened.db.execute("PRAGMA journal_mode").fetchone()[0], "wal"
            )
            self.assertEqual(
                reopened.db.execute("PRAGMA busy_timeout").fetchone()[0], 10000
            )
            reopened.close()

    def test_existing_initial_database_is_preserved_and_reconciled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "initial.db"
            db = sqlite3.connect(path)
            db.executescript(MIGRATIONS[0][1])
            db.execute(
                "INSERT INTO projects(id,name,description) VALUES(1,'Example','baseline')"
            )
            db.execute(
                "INSERT INTO work_items(id,project_id,title,description,payload,status) "
                "VALUES(1,1,'Task','baseline','{}','pending')"
            )
            db.execute(
                "INSERT INTO workflow_runs(id,project_id,task_id,workflow_id,status,completed_at) "
                "VALUES(1,1,1,'delivery','completed',CURRENT_TIMESTAMP)"
            )
            db.execute(
                "INSERT INTO approval_gates(id,run_id,status) VALUES(1,1,'pending')"
            )
            db.commit()
            db.close()

            storage = SQLiteStorage(path)
            self.assertEqual(
                storage.db.execute(
                    "SELECT name FROM projects WHERE id=1"
                ).fetchone()[0],
                "Example",
            )
            run = storage.db.execute(
                "SELECT status,completed_at FROM workflow_runs WHERE id=1"
            ).fetchone()
            self.assertEqual(run["status"], "awaiting_approval")
            self.assertIsNone(run["completed_at"])
            gate = storage.db.execute(
                "SELECT status,decision_note FROM approval_gates WHERE id=1"
            ).fetchone()
            self.assertEqual((gate["status"], gate["decision_note"]), ("pending", ""))
            storage.close()

    def test_pre_snapshot_provider_approval_is_invalidated_during_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pre-snapshot.db"
            db = sqlite3.connect(path)
            db.execute(
                "CREATE TABLE schema_migrations("
                "version INTEGER PRIMARY KEY, "
                "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            for version, script in MIGRATIONS[:-1]:
                db.executescript(script)
                db.execute(
                    "INSERT INTO schema_migrations(version) VALUES(?)", (version,)
                )
            db.execute(
                "INSERT INTO projects(id,name,description) VALUES(1,'Example','baseline')"
            )
            db.execute(
                "INSERT INTO work_items(id,project_id,title,description,payload,status) "
                "VALUES(1,1,'Task','baseline','{}','pending')"
            )
            db.execute(
                "INSERT INTO provider_execution_gates(id,provider,agent_id,task_id,status) "
                "VALUES(1,'codex','worker',1,'approved')"
            )
            db.commit()
            db.close()

            storage = SQLiteStorage(path)
            gate = storage.db.execute(
                "SELECT * FROM provider_execution_gates WHERE id=1"
            ).fetchone()
            self.assertEqual(gate["status"], "rejected")
            self.assertIsNone(gate["request_hash"])
            self.assertIsNone(gate["definition_hash"])
            self.assertIn("predates immutable snapshot", gate["decision_note"])
            self.assertEqual(
                storage.db.execute(
                    "SELECT count(*) FROM pending_provider_gate_claims"
                ).fetchone()[0],
                0,
            )
            storage.close()


if __name__ == "__main__":
    unittest.main()
