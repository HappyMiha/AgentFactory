import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.context_packages import (
    ContextPackageBuilder,
    ContextPackageError,
    ContextSource,
)
from agent_factory.models import WorkItem
from agent_factory.storage import SQLiteStorage


class ExecutionContextPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.storage = SQLiteStorage(self.workspace / "state.db")
        self.project_id = self.storage.create_project("Context", "AF-055")
        dependency_id = self.storage.create_task(
            WorkItem(
                "Dependency",
                "Already delivered dependency",
                self.project_id,
                acceptance_criteria=["Dependency criterion"],
            )
        )
        self.storage.transition_task(dependency_id, "running")
        self.storage.transition_task(dependency_id, "completed")
        self.task_id = self.storage.create_task(
            WorkItem(
                "Bounded task",
                "Build immutable dispatch context",
                self.project_id,
                dependencies=[dependency_id],
                inputs={
                    "requirements": ["Preserve deterministic behavior"],
                    "previous_decisions": ["Use the Control Plane as authority"],
                },
                expected_outputs=["context package"],
                acceptance_criteria=["Digest is immutable", "Sources are explicit"],
            )
        )
        self.run_id = self.storage.start_durable_run(
            project_id=self.project_id,
            task_id=self.task_id,
            workflow_id="context-package",
            workflow_version="1",
            definition={"id": "context-package"},
            stages=[{"id": "dispatch", "depends_on": []}],
        )
        self.claim = self.storage.claim_runnable_task(
            self.task_id,
            "context-worker",
            "context-runtime",
            conflict_domains=["context:package"],
        )

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def builder(self, **limits):
        return ContextPackageBuilder(self.storage, self.workspace, **limits)

    def build(self, builder=None, sources=()):
        return (builder or self.builder()).build(
            task_id=self.task_id,
            run_id=self.run_id,
            assignment_id=self.claim.assignment_id,
            fencing_token=self.claim.fencing_token,
            base_sha="a" * 40,
            sources=sources,
        )

    def test_package_contains_required_dispatch_scope_and_is_immutable(self):
        package = self.build()
        payload = package.payload
        self.assertEqual(payload["scope"]["task_id"], self.task_id)
        self.assertEqual(payload["scope"]["run_id"], self.run_id)
        self.assertEqual(payload["base_sha"], "a" * 40)
        self.assertEqual(payload["acceptance_criteria"], [
            "Digest is immutable",
            "Sources are explicit",
        ])
        self.assertEqual(payload["dependencies"][0]["status"], "completed")
        self.assertIn("prompt", payload["policies"])
        self.assertEqual(len(payload["relevant_requirements"]), 1)
        self.assertEqual(len(payload["previous_decisions"]), 1)
        included = payload["source_manifest"]["included"]
        self.assertIn(f"task:{self.task_id}", included)
        self.assertIn("policies:effective", included)
        self.assertTrue(
            all(source["required"] for source in payload["source_manifest"]["required"])
        )
        self.assertEqual(
            hashlib.sha256(package.canonical.encode("utf-8")).hexdigest(),
            package.digest,
        )
        replay = self.build()
        self.assertEqual((replay.id, replay.digest), (package.id, package.digest))

        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE execution_context_packages SET compacted=1 WHERE id=?",
                (package.id,),
            )
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "DELETE FROM execution_context_packages WHERE id=?",
                (package.id,),
            )

    def test_source_order_does_not_change_digest_and_supersession_is_explicit(self):
        old = ContextSource("requirement:old", "requirement", "old", "spec", 5)
        new = ContextSource(
            "requirement:new",
            "requirement",
            "new",
            "decision",
            10,
            ("requirement:old",),
        )
        first = self.build(sources=[old, new])
        second = self.build(sources=[new, old])
        self.assertEqual(first.digest, second.digest)
        manifest = first.payload["source_manifest"]
        self.assertEqual(
            manifest["superseded"][0]["source_id"], "requirement:old"
        )
        self.assertEqual(
            manifest["superseded"][0]["superseded_by"], "requirement:new"
        )
        with self.assertRaisesRegex(ValueError, "supersession contains a cycle"):
            self.build(
                sources=[
                    ContextSource("cycle:a", "reference", "a", "test", supersedes=("cycle:b",)),
                    ContextSource("cycle:b", "reference", "b", "test", supersedes=("cycle:a",)),
                ]
            )

    def test_compaction_is_deterministic_and_records_budget_exclusions(self):
        sources = [
            ContextSource("reference:small", "reference", "important", "spec", 100),
            ContextSource("reference:large", "reference", "x" * 5_000, "repo", 1),
        ]
        builder = self.builder(max_bytes=10_000, max_tokens=1_200)
        first = self.build(builder, sources)
        second = self.build(builder, reversed(sources))
        self.assertEqual(first.digest, second.digest)
        self.assertTrue(first.compacted)
        payload = first.payload
        self.assertIn("reference:small", payload["source_manifest"]["included"])
        excluded = {entry["source_id"]: entry["reason"] for entry in payload["source_manifest"]["excluded"]}
        self.assertEqual(excluded["reference:large"], "budget")
        self.assertLessEqual(first.byte_count, 10_000)
        self.assertLessEqual(first.token_count, 1_200)

    def test_mandatory_context_fails_closed_when_limits_are_too_small(self):
        with self.assertRaisesRegex(ContextPackageError, "Mandatory context"):
            self.build(self.builder(max_bytes=128, max_tokens=32))

    def test_package_scope_cannot_be_reused_by_another_dispatch(self):
        package = self.build()
        other_task = self.storage.create_task(
            WorkItem("Other", "Different dispatch", self.project_id)
        )
        other_claim = self.storage.claim_runnable_task(
            other_task,
            "other-worker",
            "context-runtime",
            conflict_domains=["context:other"],
        )
        with self.assertRaisesRegex(PermissionError, "another dispatch"):
            self.storage.assert_execution_context_scope(
                package.digest,
                task_id=other_task,
                assignment_id=other_claim.assignment_id,
                fencing_token=other_claim.fencing_token,
            )


if __name__ == "__main__":
    unittest.main()
