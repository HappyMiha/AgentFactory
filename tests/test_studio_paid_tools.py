"""A paid tool is a choice with four ways out, and declining is one of them."""

import tempfile
import unittest
from pathlib import Path

from agent_factory.localisation import LANGUAGES, Message
from agent_factory.storage import SQLiteStorage
from agent_factory.studio_paid_tools import PaidToolRefused, PaidTools


REASON = Message("Потрібен Unity для 3D.", "Unity is needed for 3D.")
FREE = Message("Godot з 3D-шаблоном", "Godot with a 3D template")


class PaidToolTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.storage = SQLiteStorage(Path(self.folder.name) / "tools.db")
        self.addCleanup(self.storage.db.close)
        self.tools = PaidTools(self.storage)

    def ask(self, **rest):
        options = {"reason": REASON, "blocks": ["3D level", "effects"]}
        options.update(rest)
        return self.tools.ask("m1", "Unity", **options)

    def test_a_paid_tool_offers_four_ways_out_when_there_is_an_alternative(self):
        choice = self.ask(alternative=FREE)
        self.assertEqual(len(choice.ways_out), 4)
        labels = [way["label"] for way in choice.record("en")["ways_out"]]
        self.assertIn("Take the free alternative", labels)

    def test_without_an_alternative_none_is_offered(self):
        choice = self.ask()
        self.assertNotIn("free_alternative", choice.ways_out)
        self.assertEqual(choice.record("en")["alternative"], "")

    def test_a_choice_that_was_not_offered_cannot_be_taken(self):
        choice = self.ask()
        with self.assertRaises(PaidToolRefused) as caught:
            self.tools.answer(choice.choice_id, choice="free_alternative", actor="miha")
        self.assertIn("free_alternative", caught.exception.text("en"))

    def test_an_invented_way_out_is_refused(self):
        choice = self.ask()
        with self.assertRaises(PaidToolRefused):
            self.tools.answer(choice.choice_id, choice="pirate_it", actor="miha")

    def test_an_unnamed_person_chooses_nothing(self):
        choice = self.ask()
        with self.assertRaises(PaidToolRefused):
            self.tools.answer(choice.choice_id, choice="decline", actor="  ")

    def test_declining_names_what_it_removes_from_the_plan(self):
        choice = self.ask()
        answered, rebuild = self.tools.answer(
            choice.choice_id, choice="decline", actor="miha")
        self.assertEqual(answered.chosen, "decline")
        self.assertEqual(rebuild.cut, ("3D level", "effects"))
        self.assertIn("3D level", rebuild.record("en")["summary"])
        self.assertEqual(self.tools.cut("m1"), ("3D level", "effects"))

    def test_declining_nothing_in_particular_says_nothing_was_cut(self):
        choice = self.ask(blocks=[])
        _, rebuild = self.tools.answer(choice.choice_id, choice="decline", actor="miha")
        self.assertIn("Nothing was cut", rebuild.record("en")["summary"])

    def test_choosing_a_subscription_cuts_nothing(self):
        choice = self.ask()
        answered, rebuild = self.tools.answer(
            choice.choice_id, choice="own_subscription", actor="miha")
        self.assertIsNone(rebuild)
        self.assertEqual(self.tools.cut("m1"), ())

    def test_an_unanswered_choice_holds_up_only_what_it_is_about(self):
        self.ask()
        self.assertEqual(self.tools.blocked("m1"), ("3D level", "effects"))
        self.assertEqual(self.tools.blocked("m2"), ())

    def test_an_answered_choice_stops_holding_anything_up(self):
        choice = self.ask()
        self.tools.answer(choice.choice_id, choice="buy_through_platform", actor="miha")
        self.assertEqual(self.tools.blocked("m1"), ())

    def test_a_choice_is_answered_once(self):
        choice = self.ask()
        self.tools.answer(choice.choice_id, choice="decline", actor="miha")
        with self.assertRaises(PaidToolRefused) as caught:
            self.tools.answer(choice.choice_id, choice="own_subscription", actor="miha")
        self.assertIn("already been answered", caught.exception.text("en"))

    def test_the_question_and_what_it_blocks_cannot_be_rewritten(self):
        choice = self.ask()
        for statement in (
            "UPDATE studio_paid_tool_choices SET blocks_json='[]' WHERE id=?",
            "UPDATE studio_paid_tool_choices SET tool='Godot' WHERE id=?",
            "DELETE FROM studio_paid_tool_choices WHERE id=?",
        ):
            with self.assertRaises(Exception):
                with self.storage.db:
                    self.storage.db.execute(statement, (choice.choice_id,))

    def test_nothing_here_asks_for_or_stores_a_credential(self):
        choice = self.ask()
        columns = {
            row[1] for row in self.storage.db.execute(
                "PRAGMA table_info(studio_paid_tool_choices)")
        }
        # "task_key" and "blocks_json" are plan references, not credentials.
        for forbidden in (
            "api_key", "token", "password", "licence", "license", "secret",
            "credential", "login",
        ):
            self.assertFalse(
                [name for name in columns if forbidden in name.casefold()],
                f"a paid-tool choice must have nowhere to put a {forbidden}")
        for language in LANGUAGES:
            self.assertTrue(choice.record(language)["credentials"].strip())

    def test_an_unknown_choice_is_refused_rather_than_invented(self):
        with self.assertRaises(KeyError):
            self.tools.answer(404, choice="decline", actor="miha")

    def test_the_report_shows_what_is_open_what_is_cut_and_the_whole_history(self):
        first = self.ask()
        self.tools.answer(first.choice_id, choice="decline", actor="miha")
        self.tools.ask(
            "m1", "Paid asset pack",
            reason=Message("Потрібні спрайти.", "Sprites are needed."),
            blocks=["nicer sprites"])
        report = self.tools.report("m1", language="en")
        self.assertEqual(len(report["open"]), 1)
        self.assertEqual(report["cut"], ["3D level", "effects"])
        self.assertEqual(report["blocked"], ["nicer sprites"])
        self.assertEqual(len(report["history"]), 2)


if __name__ == "__main__":
    unittest.main()
