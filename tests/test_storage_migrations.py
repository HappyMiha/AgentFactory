import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.models import Budget, WorkItem
from agent_factory.storage import MIGRATIONS, SQLiteStorage


class StorageMigrationTests(unittest.TestCase):
    def test_v63_database_upgrades_to_proposal_verification_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v63.db"
            db = sqlite3.connect(path)
            db.execute(
                "CREATE TABLE schema_migrations("
                "version INTEGER PRIMARY KEY, "
                "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            for version, script in MIGRATIONS:
                if version >= 64:
                    break
                db.executescript(script)
                db.execute(
                    "INSERT INTO schema_migrations(version) VALUES(?)", (version,)
                )
            db.commit()
            db.close()

            storage = SQLiteStorage(path)
            self.assertGreaterEqual(
                storage.db.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0],
                64,
            )
            self.assertIsNotNone(
                storage.db.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' "
                    "AND name='autonomous_proposal_verifications'"
                ).fetchone()
            )
            self.assertIsNotNone(
                storage.db.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='trigger' "
                    "AND name='autonomous_waiting_requires_verified_proposal'"
                ).fetchone()
            )
            storage.close()

    def test_v62_database_upgrades_to_append_only_planning_pipeline_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v62.db"
            db = sqlite3.connect(path)
            db.execute(
                "CREATE TABLE schema_migrations("
                "version INTEGER PRIMARY KEY, "
                "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            for version, script in MIGRATIONS:
                if version >= 63:
                    break
                db.executescript(script)
                db.execute(
                    "INSERT INTO schema_migrations(version) VALUES(?)", (version,)
                )
            db.commit()
            db.close()

            storage = SQLiteStorage(path)
            self.assertGreaterEqual(
                storage.db.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0],
                63,
            )
            for table in (
                "autonomous_planning_pipeline_runs",
                "autonomous_planning_pipeline_invocations",
                "autonomous_planning_pipeline_artifacts",
                "autonomous_planning_pipeline_failures",
                "autonomous_planning_pipeline_completions",
            ):
                with self.subTest(table=table):
                    self.assertIsNotNone(
                        storage.db.execute(
                            "SELECT name FROM sqlite_master "
                            "WHERE type='table' AND name=?",
                            (table,),
                        ).fetchone()
                    )
            storage.close()

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
            for version, script in MIGRATIONS[:5]:
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

    def test_runtime_setting_versions_are_immutable_and_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "settings.db")
            self.assertEqual(
                storage.update_runtime_setting("dashboard_refresh_seconds", 8), 1
            )
            self.assertEqual(
                storage.update_runtime_setting("dashboard_refresh_seconds", 10), 2
            )
            with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                storage.db.execute(
                    "UPDATE runtime_setting_versions SET value_json='99' WHERE version=1"
                )
            self.assertEqual(
                storage.db.execute(
                    "SELECT COUNT(*) FROM events WHERE event_type='settings.updated'"
                ).fetchone()[0],
                2,
            )
            storage.close()

    def test_work_item_domain_state_is_not_dependent_on_payload_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "domain.db")
            project_id = storage.create_project("Example", "Normalized state")
            task_id = storage.create_task(
                WorkItem(
                    title="Durable task",
                    description="Normalized description",
                    project_id=project_id,
                    kind="story",
                    dependencies=[7, 8],
                    inputs={"base_sha": "abc123"},
                    expected_outputs=["candidate diff"],
                    acceptance_criteria=["Tests pass"],
                    permissions=["read_project"],
                    budget=Budget(max_tokens=321, max_seconds=45, max_cost_usd=1.25),
                    artifacts=[11],
                    github_number=17,
                )
            )
            storage.db.execute(
                "UPDATE work_items SET payload='{}' WHERE id=?", (task_id,)
            )
            storage.db.commit()

            restored = storage.get_task(task_id)
            self.assertEqual(restored.description, "Normalized description")
            self.assertEqual(restored.kind, "story")
            self.assertEqual(restored.dependencies, [7, 8])
            self.assertEqual(restored.inputs, {"base_sha": "abc123"})
            self.assertEqual(restored.expected_outputs, ["candidate diff"])
            self.assertEqual(restored.acceptance_criteria, ["Tests pass"])
            self.assertEqual(restored.permissions, ["read_project"])
            self.assertEqual(restored.budget.max_tokens, 321)
            self.assertEqual(restored.budget.max_seconds, 45)
            self.assertEqual(restored.budget.max_cost_usd, 1.25)
            self.assertEqual(restored.artifacts, [11])
            self.assertEqual(restored.github_number, 17)
            storage.close()

    def test_domain_entities_have_separate_immutable_identities(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "identities.db")
            expected = {
                "work_items",
                "workflow_runs",
                "workflow_stages",
                "assignments",
                "worker_sessions",
                "provider_execution_attempts",
                "attempts",
                "leases",
                "worktrees",
                "artifacts",
            }
            tables = {
                row["name"]
                for row in storage.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertTrue(expected.issubset(tables))
            for table in expected:
                columns = {
                    row["name"] for row in storage.db.execute(f"PRAGMA table_info({table})")
                }
                self.assertIn("identity", columns, table)
                self.assertIn("version", columns, table)

            project_id = storage.create_project("Example", "Identity checks")
            task_id = storage.create_task(
                WorkItem("Task", "Description", project_id)
            )
            run_id = storage.start_run(project_id, task_id, "delivery")
            artifact_id = storage.add_artifact(
                run_id, "implementation", "worker", "direct", "candidate"
            )
            storage.create_approval_gate(run_id)
            self.assertEqual(
                storage.db.execute(
                    "SELECT status FROM workflow_stages WHERE run_id=?", (run_id,)
                ).fetchone()[0],
                "waiting_approval",
            )
            identities = [
                storage.db.execute(
                    "SELECT identity FROM work_items WHERE id=?", (task_id,)
                ).fetchone()[0],
                storage.db.execute(
                    "SELECT identity FROM workflow_runs WHERE id=?", (run_id,)
                ).fetchone()[0],
                storage.db.execute(
                    "SELECT identity FROM workflow_stages WHERE run_id=?", (run_id,)
                ).fetchone()[0],
                storage.db.execute(
                    "SELECT identity FROM artifacts WHERE id=?", (artifact_id,)
                ).fetchone()[0],
            ]
            self.assertEqual(len(identities), len(set(identities)))
            with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                storage.db.execute(
                    "UPDATE work_items SET identity='replacement' WHERE id=?",
                    (task_id,),
                )
            storage.close()

    def test_lifecycle_transitions_are_checked_by_service_and_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "states.db")
            project_id = storage.create_project("Example", "State machine")
            task_id = storage.create_task(WorkItem("Task", "Description", project_id))
            with self.assertRaisesRegex(ValueError, "Invalid work_item transition"):
                storage.transition_task(task_id, "approved")
            storage.transition_task(task_id, "running")
            self.assertEqual(storage.get_task(task_id).status.value, "running")
            self.assertEqual(
                storage.db.execute(
                    "SELECT version FROM work_items WHERE id=?", (task_id,)
                ).fetchone()[0],
                2,
            )
            with self.assertRaisesRegex(sqlite3.DatabaseError, "invalid work item"):
                storage.db.execute(
                    "UPDATE work_items SET status='approved' WHERE id=?", (task_id,)
                )
            storage.close()

    def test_v9_migration_preserves_authoritative_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pre-domain.db"
            db = sqlite3.connect(path)
            db.execute(
                "CREATE TABLE schema_migrations("
                "version INTEGER PRIMARY KEY, "
                "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            for version, script in MIGRATIONS[:8]:
                db.executescript(script)
                db.execute("INSERT INTO schema_migrations(version) VALUES(?)", (version,))
            db.execute("INSERT INTO projects(id,name,description) VALUES(1,'P','D')")
            db.execute(
                """INSERT INTO work_items(
                       id,project_id,title,description,payload,status
                   ) VALUES(1,1,'T','D',?, 'pending')""",
                (
                    '{"dependencies":[2],"acceptance_criteria":["proof"],'
                    '"budget":{"max_tokens":99,"max_seconds":12,"max_cost_usd":0.5}}',
                ),
            )
            db.execute(
                """INSERT INTO workflow_runs(
                       id,project_id,task_id,workflow_id,status
                   ) VALUES(1,1,1,'delivery','awaiting_approval')"""
            )
            db.execute("INSERT INTO artifacts(id,run_id,stage,agent_id,provider,content) VALUES(1,1,'build','worker','direct','evidence')")
            db.execute("INSERT INTO events(id,event_type,entity_type,entity_id,payload) VALUES(1,'legacy.event','task','1','{}')")
            db.execute("INSERT INTO approval_gates(id,run_id,status) VALUES(1,1,'pending')")
            db.execute(
                """INSERT INTO provider_execution_gates(
                       id,provider,agent_id,task_id,status,request_hash,definition_hash
                   ) VALUES(1,'direct','worker',1,'claimed',?,?)""",
                ("a" * 64, "b" * 64),
            )
            db.execute(
                """INSERT INTO provider_execution_attempts(
                       id,gate_id,provider,agent_id,task_id,request_hash,
                       definition_hash,status,result
                   ) VALUES(1,1,'direct','worker',1,?,?,'failed','failure')""",
                ("a" * 64, "b" * 64),
            )
            db.execute(
                """INSERT INTO provider_execution_artifacts(
                       id,gate_id,attempt_id,provider,agent_id,content,metadata,status
                   ) VALUES(1,1,1,'direct','worker','','{}','failed')"""
            )
            db.commit()
            db.close()

            storage = SQLiteStorage(path)
            self.assertEqual(storage.db.execute("SELECT count(*) FROM approval_gates").fetchone()[0], 1)
            self.assertEqual(storage.db.execute("SELECT count(*) FROM provider_execution_attempts").fetchone()[0], 1)
            self.assertEqual(storage.db.execute("SELECT count(*) FROM events").fetchone()[0], 1)
            self.assertEqual(storage.db.execute("SELECT count(*) FROM artifacts").fetchone()[0], 1)
            self.assertEqual(storage.db.execute("SELECT count(*) FROM provider_execution_artifacts").fetchone()[0], 1)
            self.assertEqual(storage.db.execute("SELECT count(*) FROM attempts").fetchone()[0], 1)
            self.assertEqual(storage.db.execute("SELECT count(*) FROM worker_sessions").fetchone()[0], 1)
            self.assertEqual(storage.get_task(1).acceptance_criteria, ["proof"])
            storage.close()


if __name__ == "__main__":
    unittest.main()
