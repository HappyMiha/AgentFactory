import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_factory.memory import (
    STORE_POLICIES,
    GovernedSkillService,
    MemoryService,
    MemoryWrite,
)
from agent_factory.storage import SQLiteStorage


class MemoryServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self.temporary.name) / "state.db")
        self.memory = MemoryService(self.storage)
        self.now = datetime(2026, 8, 12, tzinfo=timezone.utc)

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def write(self, store="semantic", memory_type="fact", **overrides):
        values = {
            "store_type": store, "memory_type": memory_type,
            "tenant_id": "tenant-a", "mission_id": "mission-a", "task_id": None,
            "purpose": "implementation", "authority": "verified",
            "source": "artifact:sha256:abc", "confidence": .9,
            "valid_from": (self.now - timedelta(minutes=1)).isoformat(),
            "valid_until": (self.now + timedelta(hours=1)).isoformat(),
            "invalidation_conditions": ("source_contradicted", "source_stale"),
            "content": {"statement": "Use deterministic validation"},
        }
        values.update(overrides)
        return self.memory.write(MemoryWrite(**values))

    def test_writes_retain_complete_contract_and_store_policies_are_separate(self):
        cases = {
            "working": ("decision", {"task_id": "task-a"}),
            "semantic": ("fact", {}), "episodic": ("outcome", {}),
            "procedural": ("procedure", {}), "entity": ("entity", {}),
            "contextual": ("context", {}), "preference": ("preference", {}),
            "raw_history": ("raw_event", {"authority": "raw"}),
        }
        for store, (memory_type, overrides) in cases.items():
            memory_id = self.write(
                store, memory_type, purpose=f"purpose-{store}",
                content={"store": store}, **overrides,
            )
            row = self.storage.db.execute(
                "SELECT * FROM memory_entries WHERE id=?", (memory_id,)
            ).fetchone()
            self.assertEqual((row["store_type"], row["memory_type"]), (store, memory_type))
            for field in (
                "tenant_id", "mission_id", "purpose", "authority", "source",
                "confidence", "valid_from", "valid_until", "invalidation_conditions_json",
            ):
                self.assertIsNotNone(row[field])
        self.assertEqual(set(STORE_POLICIES), {
            "working", "semantic", "episodic", "procedural", "entity",
            "contextual", "preference", "raw_history",
        })
        with self.assertRaisesRegex(PermissionError, "does not accept"):
            self.write("semantic", "raw_event")
        with self.assertRaisesRegex(PermissionError, "task scope"):
            self.write("working", "decision")

    def test_retrieval_is_bounded_by_scope_purpose_authority_freshness_and_count(self):
        selected_id = self.write(content={"value": "selected"})
        self.write(mission_id="mission-b", content={"value": "foreign mission"})
        self.write(purpose="review", content={"value": "foreign purpose"})
        self.write(authority="advisory", content={"value": "weak"})
        self.write(
            valid_until=(self.now - timedelta(seconds=1)).isoformat(),
            valid_from=(self.now - timedelta(hours=2)).isoformat(),
            content={"value": "stale"},
        )
        results = self.memory.retrieve(
            tenant_id="tenant-a", mission_id="mission-a", purpose="implementation",
            store_types=("semantic",), minimum_authority="verified", max_results=1,
            now=self.now, consumer_type="context_package", consumer_id="package:1",
        )
        self.assertEqual([item.id for item in results], [selected_id])
        consumer = self.storage.db.execute(
            "SELECT * FROM memory_consumers WHERE memory_id=?", (selected_id,)
        ).fetchone()
        self.assertEqual(consumer["consumer_id"], "package:1")
        working_id = self.write(
            "working", "decision", task_id="task-a", content={"value": "task scoped"}
        )
        without_task = self.memory.retrieve(
            tenant_id="tenant-a", mission_id="mission-a", purpose="implementation",
            store_types=("working",), minimum_authority="verified", max_results=5,
            now=self.now,
        )
        self.assertNotIn(working_id, {item.id for item in without_task})
        with_task = self.memory.retrieve(
            tenant_id="tenant-a", mission_id="mission-a", purpose="implementation",
            store_types=("working",), minimum_authority="verified", max_results=5,
            task_id="task-a", now=self.now,
        )
        self.assertIn(working_id, {item.id for item in with_task})
        with self.assertRaisesRegex(ValueError, "between 1 and 50"):
            self.memory.retrieve(
                tenant_id="tenant-a", mission_id="mission-a", purpose="implementation",
                store_types=("semantic",), minimum_authority="raw", max_results=51,
            )

    def test_invalidation_preserves_provenance_entry_and_historical_consumers(self):
        old_id = self.write(content={"value": "old"})
        self.memory.retrieve(
            tenant_id="tenant-a", mission_id="mission-a", purpose="implementation",
            store_types=("semantic",), minimum_authority="verified", max_results=5,
            now=self.now, consumer_type="blueprint", consumer_id="blueprint:1",
        )
        replacement_id = self.write(content={"value": "new"}, source="artifact:sha256:def")
        invalidation_id = self.memory.invalidate(
            old_id, reason="New verified source contradicts prior value",
            condition_key="source_contradicted", invalidated_by="curator",
            replacement_memory_id=replacement_id,
        )
        self.assertTrue(invalidation_id)
        self.assertIsNotNone(self.storage.db.execute(
            "SELECT * FROM memory_entries WHERE id=?", (old_id,)
        ).fetchone())
        self.assertIsNotNone(self.storage.db.execute(
            "SELECT * FROM memory_consumers WHERE memory_id=?", (old_id,)
        ).fetchone())
        results = self.memory.retrieve(
            tenant_id="tenant-a", mission_id="mission-a", purpose="implementation",
            store_types=("semantic",), minimum_authority="verified", max_results=5,
            now=self.now,
        )
        self.assertNotIn(old_id, {item.id for item in results})
        self.assertIn(replacement_id, {item.id for item in results})
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE memory_entries SET source='changed' WHERE id=?", (old_id,)
            )

    def test_generated_skill_requires_all_evidence_then_can_deprecate_and_revoke(self):
        procedure_id = self.write("procedural", "procedure")
        skills = GovernedSkillService(self.storage)
        skill_id = skills.draft(
            skill_key="safe-repair", version="1.0.0",
            specification={"steps": ["validate", "repair", "revalidate"]},
            created_by="agent-a", source_memory_id=procedure_id,
        )
        failed_review = skills.review(
            skill_id, tests_version="1.0.0", tests_passed=True,
            security_review="passed", evaluation_score=.7, evaluation_threshold=.8,
            representative_cases=10, reviewer="Curator", reviewer_role="curator",
            evidence={"suite": "representative-v1"},
        )
        with self.assertRaisesRegex(PermissionError, "evaluation threshold"):
            skills.transition(
                skill_id, "approved", actor="Curator", reason="Promote",
                review_id=failed_review,
            )
        with self.assertRaisesRegex(PermissionError, "curator or human"):
            skills.review(
                skill_id, tests_version="1.0.0", tests_passed=True,
                security_review="passed", evaluation_score=.9, evaluation_threshold=.8,
                representative_cases=10, reviewer="agent", reviewer_role="agent",
                evidence={"suite": "representative-v1"},
            )
        review_id = skills.review(
            skill_id, tests_version="1.0.1", tests_passed=True,
            security_review="passed", evaluation_score=.92, evaluation_threshold=.8,
            representative_cases=20, reviewer="Founder", reviewer_role="human_approver",
            evidence={"tests": "sha256:test", "security": "sha256:security"},
        )
        skills.transition(
            skill_id, "approved", actor="Founder", reason="Evidence passed",
            review_id=review_id,
        )
        skills.transition(skill_id, "deprecated", actor="Curator", reason="New version available")
        skills.transition(skill_id, "revoked", actor="Founder", reason="Security policy changed")
        row = self.storage.db.execute(
            "SELECT status,specification_json FROM governed_skills WHERE id=?", (skill_id,)
        ).fetchone()
        self.assertEqual(row["status"], "revoked")
        self.assertEqual(json.loads(row["specification_json"])["steps"][0], "validate")
        self.assertEqual(self.storage.db.execute(
            "SELECT COUNT(*) FROM governed_skill_transitions WHERE skill_id=?", (skill_id,)
        ).fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()
