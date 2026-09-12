"""Two roles by default, and what turning on a third would mean."""

import tempfile
import unittest
from pathlib import Path

from agent_factory.localisation import LANGUAGES
from agent_factory.storage import SQLiteStorage
from agent_factory.studio_cost import StudioCosts
from agent_factory.studio_roster import (
    CATALOGUE,
    MINIMUM_ROSTER,
    RosterRefused,
    StudioRoster,
)


class Fixture(unittest.TestCase):
    """Shared setup only: the subclasses below carry the tests."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.storage = SQLiteStorage(Path(self.folder.name) / "roster.db")
        self.addCleanup(self.storage.db.close)
        self.roster = StudioRoster(self.storage)

    def measure(self, *amounts):
        costs = StudioCosts(self.storage)
        for index, amount in enumerate(amounts, start=1):
            costs.record("m1", amount=amount, task_key=f"t{index}")


class RosterTests(Fixture):
    def test_a_new_game_starts_with_exactly_two_roles(self):
        self.assertEqual(self.roster.enabled("m1"), MINIMUM_ROSTER)

    def test_every_other_role_is_in_the_catalogue_and_switched_off(self):
        assignments = {item.role.role_id: item for item in self.roster.assignments("m1")}
        self.assertEqual(len(assignments), len(CATALOGUE))
        self.assertFalse(assignments["artist"].enabled)
        self.assertFalse(assignments["tester"].enabled)

    def test_the_minimum_pair_cannot_be_switched_off(self):
        for role in MINIMUM_ROSTER:
            with self.assertRaises(RosterRefused) as caught:
                self.roster.disable("m1", role, actor="miha")
            self.assertIn("minimum", caught.exception.text("en"))

    def test_a_role_that_is_not_in_the_catalogue_is_refused(self):
        with self.assertRaises(RosterRefused) as caught:
            self.roster.enable("m1", "wizard", actor="miha")
        self.assertIn("wizard", caught.exception.text("en"))

    def test_a_change_is_recorded_against_a_named_person(self):
        with self.assertRaises(RosterRefused):
            self.roster.enable("m1", "tester", actor="  ")

    def test_turning_on_a_role_twice_is_refused(self):
        self.roster.enable("m1", "tester", actor="miha")
        with self.assertRaises(RosterRefused) as caught:
            self.roster.enable("m1", "tester", actor="miha")
        self.assertIn("already on", caught.exception.text("en"))

    def test_turning_off_a_role_that_is_off_is_refused(self):
        with self.assertRaises(RosterRefused) as caught:
            self.roster.disable("m1", "artist", actor="miha")
        self.assertIn("already off", caught.exception.text("en"))


class ConsequenceTests(Fixture):
    def test_with_nothing_measured_the_added_cost_is_admitted_unknown(self):
        consequence = self.roster.consequence("m1", "tester")
        self.assertIsNone(consequence.added_cost)
        self.assertIn("unknown", consequence.basis.text("en"))

    def test_with_measured_tasks_the_estimate_names_its_basis(self):
        self.measure(0.4, 0.6, 0.5)
        consequence = self.roster.consequence("m1", "artist")
        self.assertIsNotNone(consequence.added_cost)
        self.assertIn("3 measured tasks", consequence.basis.text("en"))

    def test_a_role_that_takes_turns_needs_no_second_subscription(self):
        consequence = self.roster.consequence("m1", "artist")
        self.assertFalse(consequence.another_subscription)
        self.assertIn("one subscription is enough",
                      consequence.subscription_note.text("en"))

    def test_a_role_that_runs_at_the_same_time_says_it_needs_another(self):
        consequence = self.roster.consequence("m1", "artist", concurrency="parallel")
        self.assertTrue(consequence.another_subscription)
        self.assertIn("another subscription",
                      consequence.subscription_note.text("en"))

    def test_the_consequence_is_produced_when_the_role_is_enabled(self):
        consequence = self.roster.enable("m1", "tester", actor="miha")
        self.assertTrue(consequence.acceptance_changes)

    def test_the_consequence_reads_in_both_languages(self):
        consequence = self.roster.consequence("m1", "tester")
        for language in LANGUAGES:
            self.assertTrue(consequence.record(language)["basis"])
        self.assertNotEqual(
            consequence.record("uk")["basis"], consequence.record("en")["basis"])


class AcceptanceTests(Fixture):
    def test_with_two_roles_acceptance_rests_on_the_engine(self):
        self.assertTrue(self.roster.developer_accepts_own_work("m1"))
        self.assertIn("engine", self.roster.report("m1", language="en")["acceptance"])

    def test_a_tester_takes_acceptance_away_from_the_developer(self):
        self.roster.enable("m1", "tester", actor="miha")
        self.assertFalse(self.roster.developer_accepts_own_work("m1"))
        self.assertIn("no longer accepts",
                      self.roster.report("m1", language="en")["acceptance"])

    def test_turning_the_tester_off_gives_it_back_and_says_so(self):
        self.roster.enable("m1", "tester", actor="miha")
        self.roster.disable("m1", "tester", actor="miha")
        self.assertTrue(self.roster.developer_accepts_own_work("m1"))

    def test_a_role_that_reviews_nobody_does_not_change_acceptance(self):
        self.roster.enable("m1", "artist", actor="miha")
        self.assertTrue(self.roster.developer_accepts_own_work("m1"))


class ModelTests(Fixture):
    def test_a_role_with_no_model_uses_the_profile_default(self):
        assignment = {
            item.role.role_id: item for item in self.roster.assignments("m1")
        }["planner"]
        self.assertTrue(assignment.record("en")["uses_default_model"])

    def test_each_role_can_have_its_own_provider_and_model(self):
        self.roster.assign_model(
            "m1", "planner", provider="claude", model="opus", actor="miha")
        self.roster.assign_model(
            "m1", "developer", provider="codex", model="codex-1", actor="miha")
        models = {
            item.role.role_id: (item.provider, item.model)
            for item in self.roster.assignments("m1")
        }
        self.assertEqual(models["planner"], ("claude", "opus"))
        self.assertEqual(models["developer"], ("codex", "codex-1"))

    def test_assigning_a_model_does_not_turn_a_role_on(self):
        self.roster.assign_model(
            "m1", "artist", provider="local", model="sdxl", actor="miha")
        self.assertNotIn("artist", self.roster.enabled("m1"))

    def test_a_model_is_assigned_by_a_named_person(self):
        with self.assertRaises(RosterRefused):
            self.roster.assign_model(
                "m1", "planner", provider="claude", model="opus", actor="")


class HistoryTests(Fixture):
    def test_every_change_is_kept_with_who_made_it(self):
        self.roster.enable("m1", "tester", actor="miha", reason="too many defects")
        self.roster.disable("m1", "tester", actor="miha")
        history = self.roster.history("m1")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[-1]["actor"], "miha")
        self.assertEqual(history[-1]["reason"], "too many defects")

    def test_a_roster_change_cannot_be_edited_or_deleted(self):
        self.roster.enable("m1", "tester", actor="miha")
        for statement in (
            "UPDATE studio_roster SET enabled=0 WHERE id=1",
            "DELETE FROM studio_roster WHERE id=1",
        ):
            with self.assertRaises(Exception):
                with self.storage.db:
                    self.storage.db.execute(statement)

    def test_one_game_does_not_see_another_game_s_studio(self):
        self.roster.enable("m1", "tester", actor="miha")
        self.assertEqual(self.roster.enabled("m2"), MINIMUM_ROSTER)


if __name__ == "__main__":
    unittest.main()
