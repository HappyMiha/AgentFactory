"""Pause, say what you want, continue - and what each of those really does."""

import tempfile
import unittest
from pathlib import Path

from agent_factory.localisation import LANGUAGES
from agent_factory.storage import SQLiteStorage
from agent_factory.studio_cycles import CycleRefused, StudioCycles


class CycleTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.storage = SQLiteStorage(Path(self.folder.name) / "cycles.db")
        self.addCleanup(self.storage.db.close)
        self.cycles = StudioCycles(self.storage)

    def test_a_mission_that_was_never_paused_is_running_on_cycle_one(self):
        self.assertEqual(self.cycles.current("m1"),
                         {"mission": "m1", "cycle": 1, "state": "running",
                          "paused_at": "", "paused_by": ""})

    def test_a_pause_says_what_is_still_finishing(self):
        pause = self.cycles.pause("m1", actor="miha", finishing=["збірка рівня"])
        summary = pause.record("en")["summary"]
        self.assertIn("No new task", summary)
        self.assertIn("збірка рівня", summary)

    def test_a_pause_with_nothing_running_says_that_instead(self):
        pause = self.cycles.pause("m1", actor="miha")
        self.assertIn("nothing is running", pause.record("en")["summary"])

    def test_a_pause_is_recorded_against_a_named_person(self):
        with self.assertRaises(CycleRefused):
            self.cycles.pause("m1", actor="   ")

    def test_pausing_twice_is_refused_rather_than_silently_ignored(self):
        self.cycles.pause("m1", actor="miha")
        with self.assertRaises(CycleRefused) as caught:
            self.cycles.pause("m1", actor="miha")
        self.assertIn("already paused", caught.exception.text("en"))

    def test_continuing_without_a_pause_is_refused(self):
        with self.assertRaises(CycleRefused) as caught:
            self.cycles.resume("m1", actor="miha")
        self.assertIn("not paused", caught.exception.text("en"))

    def test_a_comment_is_kept_in_the_person_s_own_words(self):
        comment = self.cycles.comment("m1", "  хочу подвійний стрибок  ", author="miha")
        self.assertEqual(comment.text, "хочу подвійний стрибок")
        self.assertEqual(comment.scope, "game")

    def test_an_empty_comment_is_refused(self):
        with self.assertRaises(CycleRefused):
            self.cycles.comment("m1", "   ")

    def test_a_comment_about_nothing_in_particular_is_refused(self):
        with self.assertRaises(CycleRefused) as caught:
            self.cycles.comment("m1", "щось", scope="vibes")
        self.assertIn("vibes", caught.exception.text("en"))

    def test_a_comment_can_be_about_one_task(self):
        comment = self.cycles.comment(
            "m1", "стрибок надто низький", scope="task", subject="jump")
        self.assertEqual((comment.scope, comment.subject), ("task", "jump"))

    def test_continuing_hands_over_the_comments_of_that_cycle(self):
        self.cycles.comment("m1", "хочу подвійний стрибок")
        self.cycles.pause("m1", actor="miha")
        self.cycles.comment("m1", "і монети яскравіші")
        resumed = self.cycles.resume("m1", actor="miha")
        said = [comment.text for comment in resumed.comments]
        self.assertEqual(said, ["хочу подвійний стрибок", "і монети яскравіші"])
        self.assertEqual((resumed.closed_cycle, resumed.new_cycle), (1, 2))

    def test_continuing_does_not_claim_the_comments_were_planned(self):
        self.cycles.pause("m1", actor="miha")
        self.cycles.comment("m1", "хочу подвійний стрибок")
        note = self.cycles.resume("m1", actor="miha").record("en")["note"]
        self.assertIn("Until it replans", note)

    def test_the_next_cycle_starts_running_and_empty(self):
        self.cycles.pause("m1", actor="miha")
        self.cycles.comment("m1", "хочу подвійний стрибок")
        self.cycles.resume("m1", actor="miha")
        self.assertEqual(self.cycles.current("m1")["cycle"], 2)
        self.assertFalse(self.cycles.paused("m1"))
        self.assertEqual(self.cycles.comments("m1", cycle=2), ())

    def test_the_history_says_which_comment_belongs_to_which_cycle(self):
        self.cycles.pause("m1", actor="miha")
        self.cycles.comment("m1", "хочу подвійний стрибок")
        self.cycles.resume("m1", actor="miha")
        self.cycles.pause("m1", actor="miha")
        self.cycles.comment("m1", "і другий рівень")
        history = self.cycles.history("m1")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["comments"][0]["text"], "хочу подвійний стрибок")
        self.assertEqual(history[1]["comments"][0]["text"], "і другий рівень")
        self.assertEqual(history[0]["resumed_by"], "miha")

    def test_a_comment_cannot_be_rewritten_or_deleted(self):
        comment = self.cycles.comment("m1", "хочу подвійний стрибок")
        for statement in (
            "UPDATE studio_cycle_comments SET text='нічого' WHERE id=?",
            "DELETE FROM studio_cycle_comments WHERE id=?",
        ):
            with self.assertRaises(Exception):
                with self.storage.db:
                    self.storage.db.execute(statement, (comment.comment_id,))

    def test_one_mission_does_not_see_another_mission_s_comments(self):
        self.cycles.comment("m1", "хочу подвійний стрибок")
        self.assertEqual(self.cycles.comments("m2"), ())

    def test_the_report_reads_in_both_languages(self):
        self.cycles.pause("m1", actor="miha")
        for language in LANGUAGES:
            report = self.cycles.report("m1", language=language)
            self.assertEqual(report["state"], "paused")
            self.assertTrue(report["note"])
        self.assertNotEqual(
            self.cycles.report("m1", language="uk")["note"],
            self.cycles.report("m1", language="en")["note"])


if __name__ == "__main__":
    unittest.main()
