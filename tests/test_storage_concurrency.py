import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent_factory.models import WorkItem
from agent_factory.storage import SQLiteStorage


def seed_delivery(storage: SQLiteStorage) -> tuple[int, int]:
    project_id = storage.create_project("Example Project", "Concurrent delivery checks")
    task_id = storage.create_task(
        WorkItem(
            title="Deliver a reviewable capability",
            description="Produce evidence for an explicit acceptance criterion.",
            project_id=project_id,
            acceptance_criteria=["The result is independently reviewable"],
        )
    )
    return project_id, task_id


class StorageConcurrencyTests(unittest.TestCase):
    def _database(self, tmp: str) -> tuple[Path, int, int]:
        path = Path(tmp) / "shared.db"
        storage = SQLiteStorage(path)
        project_id, task_id = seed_delivery(storage)
        storage.close()
        return path, project_id, task_id

    def test_two_connections_racing_to_start_workflow_have_one_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, project_id, task_id = self._database(tmp)
            barrier = threading.Barrier(2)

            def start():
                storage = SQLiteStorage(path)
                try:
                    barrier.wait()
                    return (
                        "won",
                        storage.start_run(project_id, task_id, "delivery"),
                    )
                except ValueError as exc:
                    return ("blocked", str(exc))
                finally:
                    storage.close()

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = [
                    future.result()
                    for future in [pool.submit(start), pool.submit(start)]
                ]
            self.assertEqual(
                sorted(result[0] for result in results), ["blocked", "won"]
            )
            check = SQLiteStorage(path)
            self.assertEqual(
                check.db.execute("SELECT count(*) FROM workflow_runs").fetchone()[0],
                1,
            )
            self.assertTrue(check.integrity_check()["ok"])
            winner = int(next(result[1] for result in results if result[0] == "won"))
            check.finish_run(winner, "failed")
            self.assertGreater(
                check.start_run(project_id, task_id, "delivery"), winner
            )
            check.close()

    def test_two_connections_racing_for_pending_provider_gate_have_one_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _, task_id = self._database(tmp)
            barrier = threading.Barrier(2)

            def request():
                storage = SQLiteStorage(path)
                try:
                    barrier.wait()
                    return (
                        "won",
                        storage.request_provider_execution("ollama", "worker", task_id),
                    )
                except ValueError as exc:
                    return ("blocked", str(exc))
                finally:
                    storage.close()

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = [
                    future.result()
                    for future in [pool.submit(request), pool.submit(request)]
                ]
            self.assertEqual(
                sorted(result[0] for result in results), ["blocked", "won"]
            )
            check = SQLiteStorage(path)
            self.assertEqual(
                check.db.execute(
                    "SELECT count(*) FROM provider_execution_gates"
                ).fetchone()[0],
                1,
            )
            self.assertTrue(check.integrity_check()["ok"])
            gate_id = int(next(result[1] for result in results if result[0] == "won"))
            check.decide_provider_execution(gate_id, "rejected", "Race check")
            self.assertGreater(
                check.request_provider_execution("ollama", "worker", task_id), gate_id
            )
            check.close()


class StorageRecoveryTests(unittest.TestCase):
    def test_online_backup_is_consistent_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "live.db"
            backup = Path(tmp) / "backups" / "snapshot.db"
            storage = SQLiteStorage(path)
            seed_delivery(storage)
            self.assertEqual(storage.online_backup(backup), backup.resolve())
            with self.assertRaises(FileExistsError):
                storage.online_backup(backup)
            snapshot = SQLiteStorage(backup)
            self.assertTrue(snapshot.integrity_check()["ok"])
            self.assertEqual(
                snapshot.db.execute("SELECT count(*) FROM work_items").fetchone()[0],
                1,
            )
            snapshot.close()
            storage.close()

    def test_stale_workflow_and_attempt_inspection_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.db"
            storage = SQLiteStorage(path)
            project_id, task_id = seed_delivery(storage)
            run_id = storage.start_run(project_id, task_id, "delivery")
            storage.db.execute(
                "UPDATE workflow_runs SET created_at=datetime('now','-2 hours') WHERE id=?",
                (run_id,),
            )
            gate_id = storage.request_provider_execution("ollama", "worker", task_id)
            storage.decide_provider_execution(gate_id, "approved", "Inspect")
            attempt = storage.claim_provider_execution(
                gate_id, "request", "definition"
            )
            storage.db.execute(
                "UPDATE provider_execution_attempts SET created_at=datetime('now','-2 hours') WHERE id=?",
                (attempt["id"],),
            )
            storage.db.commit()
            self.assertEqual(
                [row["id"] for row in storage.stale_workflow_runs(3600)], [run_id]
            )
            self.assertEqual(
                [row["id"] for row in storage.stale_provider_attempts(3600)],
                [attempt["id"]],
            )
            self.assertEqual(
                storage.db.execute(
                    "SELECT status FROM workflow_runs WHERE id=?", (run_id,)
                ).fetchone()[0],
                "running",
            )
            self.assertEqual(
                storage.db.execute(
                    "SELECT status FROM provider_execution_attempts WHERE id=?",
                    (attempt["id"],),
                ).fetchone()[0],
                "claimed",
            )
            with self.assertRaises(ValueError):
                storage.stale_workflow_runs(-1)
            storage.close()


if __name__ == "__main__":
    unittest.main()
