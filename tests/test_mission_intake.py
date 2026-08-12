import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.mission_intake import MissionIntakeService, MissionSource, READINESS_VERDICTS
from agent_factory.storage import SQLiteStorage


class MissionIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self.temporary.name) / "state.db")
        self.project_id = self.storage.create_project("Mission", "AF-009")
        self.service = MissionIntakeService(self.storage)

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def create(self, **overrides):
        values = {
            "project_id": self.project_id,
            "mission_owner": "Founder",
            "intent": "Deliver a measurable local agent factory capability",
            "objectives": ["Implement one bounded capability"],
            "success_measures": ["All acceptance tests pass"],
            "constraints": ["No unapproved external mutation"],
            "sources": (
                MissionSource("requirements", "scope", "authoritative", "1.0", "Founder brief", "bounded scope"),
                MissionSource("notes", "ideas", "advisory", "draft-2", "Workshop", "optional idea"),
            ),
        }
        values.update(overrides)
        return self.service.create(**values)

    def test_ready_intake_emits_allowed_machine_readable_verdict(self):
        intake_id = self.create()
        result = self.service.assess(intake_id)
        self.assertIn(result.verdict, READINESS_VERDICTS)
        self.assertEqual(result.verdict, "READY_FOR_BLUEPRINT")
        self.assertTrue(result.rationale["can_proceed"])
        self.assertEqual(result.blocking_gaps, ())
        self.assertEqual(result.request_ids, ())
        replay = self.service.assess(intake_id)
        self.assertEqual(replay.id, result.id)

        other_id = self.create(intent="Deliver another bounded agent factory capability")
        other = self.service.assess(other_id)
        self.assertNotEqual(other.id, result.id)
        self.assertNotEqual(
            self.storage.db.execute(
                "SELECT assessment_digest FROM mission_readiness_assessments WHERE id=?",
                (other.id,),
            ).fetchone()[0],
            self.storage.db.execute(
                "SELECT assessment_digest FROM mission_readiness_assessments WHERE id=?",
                (result.id,),
            ).fetchone()[0],
        )

    def test_sources_record_authority_version_provenance_digest_and_conflict(self):
        intake_id = self.create(sources=(
            MissionSource("brief-a", "scope", "authoritative", "1", "Owner A", "scope A"),
            MissionSource("brief-b", "scope", "authoritative", "2", "Owner B", "scope B"),
            MissionSource("research", "market", "reference", "2026", "Dataset X", "facts"),
        ))
        rows = self.storage.db.execute(
            "SELECT * FROM mission_sources WHERE intake_id=? ORDER BY source_key", (intake_id,)
        ).fetchall()
        self.assertEqual([row["conflict_status"] for row in rows], ["conflicted", "conflicted", "clear"])
        for row in rows:
            self.assertTrue(row["authority"])
            self.assertTrue(row["version"])
            self.assertTrue(row["provenance"])
            self.assertEqual(len(row["content_digest"]), 64)
        result = self.service.assess(intake_id)
        self.assertEqual(result.verdict, "NEEDS_CLARIFICATION")
        self.assertEqual(result.blocking_gaps[0]["kind"], "source_conflict")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE mission_sources SET authority='advisory' WHERE id=?", (rows[0]["id"],)
            )

    def test_ambiguity_risk_and_infeasibility_fail_closed_with_typed_requests(self):
        scenarios = (
            ({"ambiguities": ["Which jurisdiction applies?"]}, "NEEDS_CLARIFICATION", "clarification"),
            ({"high_risk_findings": ["May expose regulated data"]}, "NEEDS_HUMAN_REVIEW", "risk_review"),
            ({"infeasible_reasons": ["Required system has no supported API"]}, "INFEASIBLE", "scope_review"),
        )
        for inputs, verdict, request_type in scenarios:
            with self.subTest(verdict=verdict):
                result = self.service.assess(self.create(**inputs))
                self.assertEqual(result.verdict, verdict)
                self.assertFalse(result.rationale["can_proceed"])
                request = self.storage.db.execute(
                    "SELECT request_type FROM mission_review_requests WHERE id=?",
                    (result.request_ids[0],),
                ).fetchone()
                self.assertEqual(request["request_type"], request_type)

    def test_only_owner_resolves_ambiguity_or_accepts_reduced_scope(self):
        intake_id = self.create(
            ambiguities=["Who approves the final scope?"],
            reduced_scope_proposed="Deliver read-only reporting first",
        )
        first = self.service.assess(intake_id)
        ambiguity = next(gap for gap in first.blocking_gaps if gap["kind"] == "ambiguity")
        reduced = next(gap for gap in first.blocking_gaps if gap["kind"] == "reduced_scope")
        with self.assertRaisesRegex(PermissionError, "mission owner"):
            self.service.resolve_gap(
                intake_id, gap_code=ambiguity["code"], decision="Founder approves",
                rationale="Delegation rejected", actor="Worker", actor_role="implementation_worker",
            )
        self.service.resolve_gap(
            intake_id, gap_code=ambiguity["code"], decision="Founder approves",
            rationale="Owner clarified final authority", actor="Founder", actor_role="mission_owner",
        )
        with self.assertRaisesRegex(PermissionError, "explicit owner acceptance"):
            self.service.resolve_gap(
                intake_id, gap_code=reduced["code"], decision="Proceed",
                rationale="Reduced delivery", actor="Founder", actor_role="mission_owner",
            )
        self.service.resolve_gap(
            intake_id, gap_code=reduced["code"], decision="Accept reduced scope",
            rationale="Bounded first delivery", actor="Founder", actor_role="mission_owner",
            accepted_reduced_scope=True,
        )
        ready = self.service.assess(intake_id)
        self.assertEqual((ready.sequence, ready.verdict), (2, "READY_FOR_BLUEPRINT"))


if __name__ == "__main__":
    unittest.main()
