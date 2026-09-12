"""A stage ends with something you can play, or with an honest reason."""

import json
import tempfile
import unittest
from pathlib import Path

from agent_factory.localisation import LANGUAGES, Message
from agent_factory.storage import SQLiteStorage
from agent_factory.studio_slices import SliceRefused, StageBoundaries


NOTHING = Message(
    "Етап лише готував середовище.", "The stage only prepared the environment.",
)


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.storage = SQLiteStorage(Path(self.folder.name) / "slices.db")
        self.addCleanup(self.storage.db.close)
        self.boundaries = StageBoundaries(self.storage)

    def build(self, digest="a" * 64, *, gap=(), project="collector"):
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO playable_versions
                   (identity,project_key,version_digest,engine,engine_version,
                    source_commit,project_digest,template_id,template_version,preset,
                    artifact_path,artifact_checksum,artifact_bytes,verification_json,
                    evidence_gap_json,created_at)
                   VALUES(?,?,?,'godot','4.7.2','aaaa111','digest','collector-2d','1.0.0',
                          'linux-x86_64','/builds/game.x86_64',?,2048,'[]',?,
                          '2026-09-12T10:00:00+00:00')""",
                (f"version-{digest[:8]}", project, digest, "c" * 64,
                 json.dumps(list(gap))),
            )
        return digest

    def test_a_stage_can_only_be_playable_with_a_build_that_exists(self):
        with self.assertRaises(SliceRefused) as caught:
            self.boundaries.playable(
                "m1", "base", project_key="collector", version_digest="b" * 64)
        self.assertIn("no such built version", caught.exception.text("en"))

    def test_a_build_with_a_gap_in_its_evidence_is_not_offered(self):
        self.build(gap=["no recorded run on Windows"])
        with self.assertRaises(SliceRefused) as caught:
            self.boundaries.playable(
                "m1", "base", project_key="collector", version_digest="a" * 64)
        self.assertIn("gap in its evidence", caught.exception.text("en"))
        self.assertIn("Windows", caught.exception.text("en"))

    def test_a_real_build_makes_the_stage_playable(self):
        self.build()
        boundary = self.boundaries.playable(
            "m1", "base", project_key="collector", version_digest="a" * 64,
            declared_by="studio")
        self.assertTrue(boundary.playable)
        self.assertEqual(self.boundaries.playable_map("m1"), {"base": "a" * 64})

    def test_nothing_to_test_cannot_be_declared_without_a_reason(self):
        from agent_factory.localisation import MissingTranslation

        # The reason is a Message, and an empty one cannot be built at all.
        with self.assertRaises(MissingTranslation):
            Message(" ", " ")
        with self.assertRaises(MissingTranslation):
            Message("Просто так", "")

    def test_nothing_to_test_says_what_the_stage_did_instead(self):
        boundary = self.boundaries.nothing_to_test("m1", "setup", reason=NOTHING)
        self.assertFalse(boundary.playable)
        for language in LANGUAGES:
            self.assertTrue(boundary.record(language)["reason"].strip())
        self.assertEqual(self.boundaries.playable_map("m1"), {})

    def test_a_boundary_belongs_to_a_named_stage(self):
        with self.assertRaises(SliceRefused):
            self.boundaries.nothing_to_test("m1", "  ", reason=NOTHING)

    def test_a_later_slice_supersedes_the_earlier_one_without_erasing_it(self):
        self.build("a" * 64)
        self.build("d" * 64)
        self.boundaries.playable(
            "m1", "base", project_key="collector", version_digest="a" * 64)
        self.boundaries.playable(
            "m1", "base", project_key="collector", version_digest="d" * 64)
        self.assertEqual(self.boundaries.playable_map("m1"), {"base": "d" * 64})
        self.assertEqual(len(self.boundaries.history("m1")), 2)

    def test_a_stage_that_becomes_playable_stops_saying_there_is_nothing(self):
        self.build()
        self.boundaries.nothing_to_test("m1", "base", reason=NOTHING)
        self.boundaries.playable(
            "m1", "base", project_key="collector", version_digest="a" * 64)
        self.assertEqual(self.boundaries.playable_map("m1"), {"base": "a" * 64})

    def test_a_declaration_cannot_be_rewritten_or_deleted(self):
        self.boundaries.nothing_to_test("m1", "setup", reason=NOTHING)
        for statement in (
            "UPDATE studio_stage_boundaries SET outcome='playable' WHERE id=1",
            "DELETE FROM studio_stage_boundaries WHERE id=1",
        ):
            with self.assertRaises(Exception):
                with self.storage.db:
                    self.storage.db.execute(statement)

    def test_the_database_itself_refuses_a_playable_row_with_no_version(self):
        with self.assertRaises(Exception):
            with self.storage.db:
                self.storage.db.execute(
                    """INSERT INTO studio_stage_boundaries(mission,stage_key,outcome)
                       VALUES('m1','base','playable')""")

    def test_one_mission_does_not_see_another_mission_s_slices(self):
        self.build()
        self.boundaries.playable(
            "m1", "base", project_key="collector", version_digest="a" * 64)
        self.assertEqual(self.boundaries.playable_map("m2"), {})

    def test_the_report_lists_what_is_playable_and_the_whole_history(self):
        self.build()
        self.boundaries.nothing_to_test("m1", "setup", reason=NOTHING)
        self.boundaries.playable(
            "m1", "base", project_key="collector", version_digest="a" * 64)
        report = self.boundaries.report("m1", language="en")
        self.assertEqual(len(report["playable"]), 1)
        self.assertEqual(len(report["stages"]), 2)
        self.assertEqual(len(report["history"]), 2)
        self.assertIn("prepared the environment", report["stages"]["setup"]["reason"])


if __name__ == "__main__":
    unittest.main()
