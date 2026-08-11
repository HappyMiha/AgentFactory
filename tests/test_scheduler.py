import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_factory.models import WorkItem
from agent_factory.storage import (
    ConflictDomainBusyError,
    SQLiteStorage,
    StaleLeaseError,
    TaskNotRunnableError,
)


NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


class DependencySchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self.temporary.name) / "scheduler.db")
        self.project_id = self.storage.create_project("Scheduler", "AF-007")

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def task(
        self,
        title: str,
        *,
        kind: str = "task",
        dependencies: list[int] | None = None,
    ) -> int:
        return self.storage.create_task(
            WorkItem(
                title=title,
                description=title,
                project_id=self.project_id,
                kind=kind,
                dependencies=dependencies or [],
            )
        )

    def test_only_leaf_tasks_with_completed_dependencies_are_runnable(self):
        epic_id = self.task("Epic", kind="epic")
        story_id = self.task("Story", kind="story")
        dependency_id = self.task("Dependency")
        blocked_id = self.task("Blocked", dependencies=[dependency_id])
        ready_id = self.task("Ready")

        self.assertEqual(
            [item.id for item in self.storage.runnable_tasks(now=NOW)],
            [dependency_id, ready_id],
        )
        self.assertEqual(self.storage.task_readiness(epic_id, now=NOW), ("kind:epic",))
        self.assertEqual(self.storage.task_readiness(story_id, now=NOW), ("kind:story",))
        self.assertEqual(
            self.storage.task_readiness(blocked_id, now=NOW),
            (f"dependency:{dependency_id}:pending",),
        )
        with self.assertRaises(TaskNotRunnableError):
            self.storage.claim_runnable_task(
                blocked_id, "worker", "direct", now=NOW
            )

        self.storage.transition_task(dependency_id, "running")
        self.storage.transition_task(dependency_id, "completed")
        self.assertEqual(self.storage.task_readiness(blocked_id, now=NOW), ())
        self.assertIn(
            blocked_id,
            [item.id for item in self.storage.runnable_tasks(now=NOW)],
        )

    def test_claim_atomically_persists_assignment_lease_and_fencing_token(self):
        task_id = self.task("Claim me")
        claim = self.storage.claim_runnable_task(
            task_id,
            "coding-worker",
            "codex",
            ttl_seconds=30,
            conflict_domains=["path:src/agent_factory/storage.py"],
            now=NOW,
        )

        assignment = self.storage.db.execute(
            "SELECT * FROM assignments WHERE id=?", (claim.assignment_id,)
        ).fetchone()
        lease = self.storage.db.execute(
            "SELECT * FROM leases WHERE id=?", (claim.lease_id,)
        ).fetchone()
        domains = self.storage.db.execute(
            "SELECT domain FROM assignment_conflict_domains WHERE assignment_id=?",
            (claim.assignment_id,),
        ).fetchall()
        self.assertEqual(assignment["status"], "active")
        self.assertEqual(assignment["agent_id"], "coding-worker")
        self.assertEqual(lease["status"], "active")
        self.assertEqual(lease["fencing_token"], claim.fencing_token)
        self.assertEqual(
            [row["domain"] for row in domains],
            [f"project:{self.project_id}/path:src/agent_factory/storage.py"],
        )
        event = self.storage.db.execute(
            "SELECT payload FROM events WHERE event_type='task.claimed' ORDER BY id DESC"
        ).fetchone()
        self.assertIn(f'"assignment_id": {claim.assignment_id}', event["payload"])

    def test_conflict_domains_allow_independence_and_serialize_or_escalate_overlap(self):
        storage_task = self.task("Storage")
        nested_task = self.task("Nested storage")
        tests_task = self.task("Tests")
        escalation_task = self.task("Escalation")
        first = self.storage.claim_runnable_task(
            storage_task,
            "worker-a",
            "codex",
            conflict_domains=["path:src/agent_factory"],
            now=NOW,
        )

        with self.assertRaises(ConflictDomainBusyError) as serialized:
            self.storage.claim_runnable_task(
                nested_task,
                "worker-b",
                "codex",
                conflict_domains=["path:src/agent_factory/storage.py"],
                now=NOW,
            )
        self.assertEqual(serialized.exception.assignment_ids, (first.assignment_id,))
        self.assertFalse(serialized.exception.escalated)

        independent = self.storage.claim_runnable_task(
            tests_task,
            "worker-c",
            "codex",
            conflict_domains=["path:tests"],
            now=NOW,
        )
        self.assertNotEqual(independent.assignment_id, first.assignment_id)

        with self.assertRaises(ConflictDomainBusyError) as escalated:
            self.storage.claim_runnable_task(
                escalation_task,
                "worker-d",
                "codex",
                conflict_domains=["path:src"],
                conflict_action="escalate",
                now=NOW,
            )
        self.assertTrue(escalated.exception.escalated)
        self.assertEqual(
            [row["action"] for row in self.storage.db.execute(
                "SELECT action FROM scheduler_conflicts ORDER BY id"
            )],
            ["serialize", "escalate"],
        )

    def test_expired_worker_cannot_write_artifact_or_cross_commit_boundary(self):
        task_id = self.task("Fenced task")
        old = self.storage.claim_runnable_task(
            task_id,
            "old-worker",
            "codex",
            ttl_seconds=5,
            conflict_domains=["path:src"],
            now=NOW,
        )
        run_id = self.storage.start_run(self.project_id, task_id, "delivery")
        first_artifact = self.storage.add_fenced_artifact(
            old.assignment_id,
            old.fencing_token,
            run_id,
            "implementation",
            "codex",
            "first candidate",
            evidence_kind="diff",
            now=NOW + timedelta(seconds=1),
        )
        self.assertGreater(first_artifact, 0)

        after_expiry = NOW + timedelta(seconds=6)
        with self.assertRaises(StaleLeaseError):
            self.storage.add_fenced_artifact(
                old.assignment_id,
                old.fencing_token,
                run_id,
                "implementation",
                "codex",
                "stale candidate",
                evidence_kind="diff",
                now=after_expiry,
            )
        replacement = self.storage.claim_runnable_task(
            task_id,
            "new-worker",
            "codex",
            conflict_domains=["path:src"],
            now=after_expiry,
        )
        self.assertGreater(replacement.fencing_token, old.fencing_token)
        with self.assertRaises(StaleLeaseError):
            self.storage.record_fenced_mutation(
                old.assignment_id,
                old.fencing_token,
                "commit",
                "candidate-sha",
                now=after_expiry,
            )
        self.storage.record_fenced_mutation(
            replacement.assignment_id,
            replacement.fencing_token,
            "commit",
            "candidate-sha",
            now=after_expiry,
        )
        second_artifact = self.storage.add_fenced_artifact(
            replacement.assignment_id,
            replacement.fencing_token,
            run_id,
            "repair",
            "codex",
            "replacement candidate",
            evidence_kind="diff",
            now=after_expiry,
        )
        self.assertGreater(second_artifact, first_artifact)
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM artifacts WHERE run_id=?", (run_id,)
            ).fetchone()[0],
            2,
        )


if __name__ == "__main__":
    unittest.main()
