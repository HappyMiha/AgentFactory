"""A sentence after playing, and the four things it must not turn into."""

import tempfile
import unittest
from pathlib import Path

from agent_factory.game_feedback import (
    Attachment,
    BehaviourCheck,
    Change,
    ChangePlan,
    Cost,
    Feedback,
    FeedbackJournal,
    FeedbackRefused,
    PlayedBuild,
    RequirementImpact,
    accept_plan,
    judge,
    plan_change,
    summarise,
)
from agent_factory.localisation import LANGUAGES, Message
from agent_factory.storage import SQLiteStorage


BUILD = PlayedBuild("collector", "a" * 64, "godot", "2026-09-12T10:00:00+00:00")
HIGHER = Change(Message("Підняти висоту стрибка", "Raise the jump height"), ("AF-GC-016",))


def note(**rest):
    return Feedback.create(build=BUILD, wish="зроби стрибок вищим", **rest)


class FeedbackTests(unittest.TestCase):
    def test_a_note_is_bound_to_the_build_that_was_played(self):
        self.assertEqual(note().build.version_digest, "a" * 64)

    def test_an_empty_note_is_refused_in_both_languages(self):
        with self.assertRaises(FeedbackRefused) as caught:
            Feedback.create(build=BUILD, wish="   ")
        for language in LANGUAGES:
            self.assertTrue(caught.exception.text(language).strip())

    def test_a_note_that_is_too_long_says_by_how_much(self):
        with self.assertRaises(FeedbackRefused) as caught:
            Feedback.create(build=BUILD, wish="x" * 5000)
        self.assertIn("2000", caught.exception.text("en"))

    def test_the_same_words_about_the_same_build_are_the_same_note(self):
        self.assertEqual(note().digest, note().digest)

    def test_the_same_words_about_a_different_build_are_a_different_note(self):
        other = Feedback.create(
            build=PlayedBuild("collector", "b" * 64), wish="зроби стрибок вищим")
        self.assertNotEqual(note().digest, other.digest)

    def test_an_unknown_kind_of_attachment_is_refused(self):
        with self.assertRaises(FeedbackRefused):
            Attachment("video", "clip.mp4")


class PreviewTests(unittest.TestCase):
    def test_with_no_attachment_nothing_leaves_the_machine(self):
        preview = note().preview("en")
        self.assertEqual(preview["leaves_machine"], [])
        self.assertIn("Nothing leaves", preview["transmission"])

    def test_a_screenshot_that_would_be_sent_is_named_before_it_is_sent(self):
        preview = note(attachments=[
            Attachment("screenshot", "jump.png", 2048, "d" * 64, leaves_machine=True),
            Attachment("save", "slot1.save", 512, "e" * 64),
        ]).preview("en")
        self.assertEqual(preview["leaves_machine"], ["jump.png"])
        self.assertIn("jump.png", preview["transmission"])

    def test_the_preview_shows_the_words_that_would_be_sent_verbatim(self):
        self.assertEqual(note().preview()["wish"], "зроби стрибок вищим")

    def test_the_preview_reads_in_both_languages(self):
        one = note()
        self.assertNotEqual(
            one.preview("uk")["transmission"], one.preview("en")["transmission"])


class PlanTests(unittest.TestCase):
    def test_a_free_change_within_scope_needs_no_acceptance(self):
        plan = plan_change(feedback=note(), changes=[HIGHER])
        self.assertEqual(plan.needs_acceptance(), ())

    def test_new_cost_is_never_accepted_silently(self):
        plan = plan_change(feedback=note(), changes=[HIGHER], cost=Cost(0.4))
        self.assertTrue(plan.adds_cost)
        with self.assertRaises(FeedbackRefused):
            accept_plan(plan, actor="miha")

    def test_new_scope_is_never_accepted_silently(self):
        plan = plan_change(
            feedback=note(), changes=[HIGHER],
            added_scope=[Message("Нові рівні", "New levels")])
        with self.assertRaises(FeedbackRefused):
            accept_plan(plan, actor="miha")

    def test_acceptance_is_recorded_against_a_named_person(self):
        plan = plan_change(feedback=note(), changes=[HIGHER], cost=Cost(0.4))
        accepted = accept_plan(plan, actor=" miha ", accept_cost=True)
        self.assertEqual(accepted.accepted_by, "miha")
        self.assertTrue(accepted.accepted)

    def test_an_unnamed_person_cannot_accept(self):
        with self.assertRaises(FeedbackRefused):
            accept_plan(plan_change(feedback=note(), changes=[HIGHER]), actor="  ")

    def test_accepting_the_cost_does_not_also_accept_new_scope(self):
        plan = plan_change(
            feedback=note(), changes=[HIGHER], cost=Cost(0.4),
            added_scope=[Message("Нові рівні", "New levels")])
        with self.assertRaises(FeedbackRefused):
            accept_plan(plan, actor="miha", accept_cost=True)

    def test_a_plan_built_on_a_newer_version_says_so(self):
        plan = plan_change(feedback=note(), changes=[HIGHER], current_version="b" * 64)
        self.assertIn("bbbb", plan.record("en")["note"])
        self.assertEqual(plan.applies_to, "b" * 64)

    def test_a_plan_built_on_the_played_version_needs_no_such_warning(self):
        plan = plan_change(feedback=note(), changes=[HIGHER], current_version="a" * 64)
        self.assertEqual(plan.record("en")["note"], "")

    def test_the_impact_on_what_was_already_agreed_is_stated(self):
        plan = plan_change(
            feedback=note(), changes=[HIGHER],
            impacts=[RequirementImpact(
                "AF-GC-016", "possibly_affected",
                Message("Стрибок впливає на рівень 2.", "The jump affects level 2."))])
        self.assertEqual(plan.record("en")["impacts"][0]["impact"], "possibly_affected")

    def test_an_unknown_kind_of_impact_is_refused(self):
        with self.assertRaises(ValueError):
            RequirementImpact("AF-GC-016", "probably-fine", Message("Х", "X"))


class VerdictTests(unittest.TestCase):
    def check(self, **rest):
        base = dict(
            wish_digest=note().digest,
            description=Message("Стрибок вищий за 2 клітинки", "Jump clears two tiles"),
            ran=True, passed=True, evidence="run-42",
        )
        base.update(rest)
        return BehaviourCheck(**base)

    def test_a_build_that_passed_is_not_evidence_that_the_wish_came_true(self):
        verdict = judge(note(), [])
        self.assertEqual(verdict.state, "not_checked")
        self.assertIn("not evidence", verdict.summary.text("en"))

    def test_a_check_about_another_wish_does_not_count_for_this_one(self):
        verdict = judge(note(), [self.check(wish_digest="f" * 64)])
        self.assertEqual(verdict.state, "not_checked")

    def test_a_check_that_never_ran_does_not_count(self):
        verdict = judge(note(), [self.check(ran=False)])
        self.assertEqual(verdict.state, "not_checked")

    def test_a_passing_check_without_evidence_confirms_nothing(self):
        verdict = judge(note(), [self.check(evidence="")])
        self.assertEqual(verdict.state, "not_checked")
        self.assertFalse(verdict.confirmed)

    def test_a_checked_and_passing_wish_is_confirmed(self):
        verdict = judge(note(), [self.check()])
        self.assertTrue(verdict.confirmed)

    def test_one_failing_check_outweighs_the_passing_ones(self):
        verdict = judge(note(), [self.check(), self.check(passed=False)])
        self.assertEqual(verdict.state, "fails")

    def test_the_previous_version_stays_offered_whatever_the_verdict(self):
        for checks in ([], [self.check()], [self.check(passed=False)]):
            verdict = judge(note(), checks, previous_version="a" * 64)
            self.assertTrue(verdict.record("en")["revert_available"])

    def test_the_verdict_reads_in_both_languages(self):
        verdict = judge(note(), [self.check()])
        self.assertNotEqual(
            verdict.record("uk")["summary"], verdict.record("en")["summary"])


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.storage = SQLiteStorage(Path(self.folder.name) / "feedback.db")
        self.addCleanup(self.storage.db.close)
        self.journal = FeedbackJournal(self.storage)

    def test_a_note_is_stored_and_comes_back_word_for_word(self):
        written = note(steps=["натиснути пробіл"])
        stored = self.journal.feedback(self.journal.record(written))
        self.assertEqual(stored.wish, "зроби стрибок вищим")
        self.assertEqual(stored.steps, ("натиснути пробіл",))
        self.assertEqual(stored.digest, written.digest)

    def test_the_same_wish_with_different_steps_is_a_different_note(self):
        self.assertNotEqual(note().digest, note(steps=["натиснути пробіл"]).digest)

    def test_the_same_note_twice_is_one_record(self):
        first = self.journal.record(note())
        self.assertEqual(self.journal.record(note()), first)

    def test_recorded_feedback_cannot_be_rewritten_or_deleted(self):
        identifier = self.journal.record(note())
        for statement, values in (
            ("UPDATE game_feedback SET wish=? WHERE id=?", ("something else", identifier)),
            ("DELETE FROM game_feedback WHERE id=?", (identifier,)),
        ):
            with self.assertRaises(Exception):
                with self.storage.db:
                    self.storage.db.execute(statement, values)

    def test_a_plan_may_gain_its_acceptance_and_nothing_else(self):
        identifier = self.journal.record(note())
        plan_id = self.journal.record_plan(
            identifier, plan_change(feedback=note(), changes=[HIGHER], cost=Cost(0.4)))
        self.journal.accept(plan_id, actor="miha")
        row = self.storage.db.execute(
            "SELECT accepted_by,accepted_at FROM game_feedback_plans WHERE id=?",
            (plan_id,)).fetchone()
        self.assertEqual(row["accepted_by"], "miha")
        self.assertTrue(row["accepted_at"])
        with self.assertRaises(Exception):
            with self.storage.db:
                self.storage.db.execute(
                    "UPDATE game_feedback_plans SET cost_amount=0 WHERE id=?", (plan_id,))

    def test_an_accepted_plan_cannot_be_reassigned_to_someone_else(self):
        identifier = self.journal.record(note())
        plan_id = self.journal.record_plan(
            identifier, plan_change(feedback=note(), changes=[HIGHER]))
        self.journal.accept(plan_id, actor="miha")
        with self.assertRaises(Exception):
            self.journal.accept(plan_id, actor="someone-else")

    def test_an_unnamed_person_cannot_accept_a_stored_plan(self):
        identifier = self.journal.record(note())
        plan_id = self.journal.record_plan(
            identifier, plan_change(feedback=note(), changes=[HIGHER]))
        with self.assertRaises(FeedbackRefused):
            self.journal.accept(plan_id, actor="")

    def test_the_stored_verdict_follows_the_stored_checks(self):
        identifier = self.journal.record(note())
        self.assertEqual(self.journal.verdict(identifier).state, "not_checked")
        self.journal.record_check(identifier, BehaviourCheck(
            note().digest, Message("Стрибок вищий", "Higher jump"),
            ran=True, passed=True, evidence="run-42"))
        self.assertTrue(self.journal.verdict(identifier).confirmed)

    def test_a_recorded_check_cannot_be_rewritten(self):
        identifier = self.journal.record(note())
        check_id = self.journal.record_check(identifier, BehaviourCheck(
            note().digest, Message("Стрибок вищий", "Higher jump"),
            ran=True, passed=False, evidence="run-42"))
        with self.assertRaises(Exception):
            with self.storage.db:
                self.storage.db.execute(
                    "UPDATE game_feedback_checks SET passed=1 WHERE id=?", (check_id,))

    def test_the_history_counts_the_plans_and_which_were_accepted(self):
        identifier = self.journal.record(note())
        plan_id = self.journal.record_plan(
            identifier, plan_change(feedback=note(), changes=[HIGHER]))
        self.journal.accept(plan_id, actor="miha")
        entry = self.journal.history("collector")[0]
        self.assertEqual((entry["plans"], entry["accepted"]), (1, 1))

    def test_an_unknown_note_is_refused_rather_than_invented(self):
        with self.assertRaises(KeyError):
            self.journal.feedback(404)


class SummaryTests(unittest.TestCase):
    def test_one_record_holds_the_words_the_plan_and_the_verdict(self):
        one = note()
        record = summarise(
            one, plan_change(feedback=one, changes=[HIGHER]), judge(one, []),
            language="en")
        self.assertEqual(record["feedback"]["wish"], "зроби стрибок вищим")
        self.assertEqual(record["plan"]["changes"][0]["summary"], "Raise the jump height")
        self.assertEqual(record["verdict"]["state"], "not_checked")


if __name__ == "__main__":
    unittest.main()
