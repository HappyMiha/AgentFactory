"""The button does nothing until somebody can actually do the work."""

import tempfile
import unittest
from pathlib import Path

from agent_factory.localisation import LANGUAGES, Message
from agent_factory.storage import SQLiteStorage
from agent_factory.studio_first_run import FirstRun, FirstRunRefused
from agent_factory.studio_workers import StudioMachines


class FirstRunTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.storage = SQLiteStorage(Path(self.folder.name) / "first-run.db")
        self.addCleanup(self.storage.db.close)
        self.wizard = FirstRun(self.storage)
        self.machines = StudioMachines(self.storage)

    def test_with_nothing_connected_the_button_is_off_and_says_why(self):
        readiness = self.wizard.readiness()
        self.assertFalse(readiness.can_start)
        self.assertIn("no source of execution", readiness.summary.text("en"))

    def test_a_connected_but_unchecked_subscription_does_not_unlock_it(self):
        self.wizard.connect("claude", kind="own_subscription", name="Claude")
        readiness = self.wizard.readiness()
        self.assertFalse(readiness.can_start)
        self.assertIn("no source has been checked", readiness.summary.text("en"))

    def test_a_checked_subscription_unlocks_the_button(self):
        self.wizard.connect("claude", kind="own_subscription", name="Claude")
        self.wizard.verify("claude", works=True)
        self.assertTrue(self.wizard.readiness().can_start)

    def test_a_subscription_that_failed_its_check_does_not_unlock_it(self):
        self.wizard.connect("claude", kind="own_subscription", name="Claude")
        self.wizard.verify("claude", works=False, detail=Message(
            "Ключ відхилено.", "The key was rejected."))
        readiness = self.wizard.readiness()
        self.assertFalse(readiness.can_start)
        self.assertEqual(readiness.sources[0].state, "unavailable")
        self.assertIn("rejected", readiness.sources[0].record("en")["detail"])

    def test_a_platform_subscription_counts_like_any_other(self):
        self.wizard.connect(
            "platform", kind="platform_subscription", name="Trial through Lokvetia",
            state="verified")
        self.assertTrue(self.wizard.readiness().can_start)

    def test_a_local_model_is_offered_only_after_the_hardware_is_looked_at(self):
        self.machines.register(
            "pc", name="desktop", kind="this_pc", video_memory_gb=24.0)
        source = self.wizard.offer_local_model(
            "llama", name="Llama 8B", machines=self.machines,
            machine_key="pc", needed_gb=10)
        self.assertTrue(source.usable)
        self.assertIn("fits", source.record("en")["detail"])
        self.assertTrue(self.wizard.readiness().can_start)

    def test_a_local_model_that_will_not_fit_is_refused_plainly(self):
        self.machines.register(
            "pc", name="desktop", kind="this_pc", video_memory_gb=6.0)
        source = self.wizard.offer_local_model(
            "llama", name="Llama 70B", machines=self.machines,
            machine_key="pc", needed_gb=40)
        self.assertFalse(source.usable)
        self.assertIn("will not run locally", source.record("en")["detail"])
        self.assertFalse(self.wizard.readiness().can_start)

    def test_a_local_model_cannot_be_declared_available_with_no_verdict(self):
        with self.assertRaises(FirstRunRefused) as caught:
            self.wizard.connect(
                "llama", kind="local_model", name="Llama", state="verified")
        self.assertIn("hardware has been checked", caught.exception.text("en"))

    def test_an_unknown_kind_of_source_is_refused(self):
        with self.assertRaises(FirstRunRefused) as caught:
            self.wizard.connect("magic", kind="wishful_thinking", name="Magic")
        self.assertIn("wishful_thinking", caught.exception.text("en"))

    def test_an_unnamed_source_is_refused(self):
        with self.assertRaises(FirstRunRefused):
            self.wizard.connect("claude", kind="own_subscription", name="  ")

    def test_reconnecting_the_same_source_updates_it_rather_than_doubling_it(self):
        self.wizard.connect("claude", kind="own_subscription", name="Claude")
        self.wizard.verify("claude", works=True)
        self.assertEqual(len(self.wizard.sources()), 1)
        self.assertTrue(self.wizard.sources()[0].usable)

    def test_the_wizard_has_nowhere_to_put_the_key_itself(self):
        columns = {
            row[1] for row in self.storage.db.execute(
                "PRAGMA table_info(studio_execution_sources)")
        }
        for forbidden in ("api_key", "token", "password", "secret", "credential"):
            self.assertFalse([name for name in columns if forbidden in name.casefold()])

    def test_the_report_lists_the_three_ways_in_both_languages(self):
        for language in LANGUAGES:
            report = self.wizard.report(language=language)
            self.assertEqual(len(report["kinds"]), 3)
            self.assertTrue(report["summary"])
        self.assertNotEqual(
            self.wizard.report(language="uk")["summary"],
            self.wizard.report(language="en")["summary"])

    def test_an_unknown_source_is_refused_rather_than_invented(self):
        with self.assertRaises(KeyError):
            self.wizard.source("nothing-here")


if __name__ == "__main__":
    unittest.main()
