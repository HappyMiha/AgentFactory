"""The gates are answered by policy, and the three questions that remain."""

import tempfile
import unittest
from pathlib import Path

from agent_factory.localisation import LANGUAGES
from agent_factory.storage import SQLiteStorage
from agent_factory.studio_autonomy import (
    ASK_REASONS,
    AutonomyJournal,
    AutonomyRefused,
    CATALOGUE,
    beyond_capability,
    catalogue,
    decide,
    irreversible,
    over_budget,
)


class GateTests(unittest.TestCase):
    def test_the_plan_and_the_permission_to_run_are_no_longer_clicked(self):
        for gate in ("backlog_revision", "execution_authorization", "environment_profile"):
            self.assertTrue(decide(gate).automatic, gate)

    def test_the_data_compatibility_check_stays_automatic_and_required(self):
        decision = decide("schema_compatibility")
        self.assertTrue(decision.automatic)
        self.assertFalse(decision.needs_person)

    def test_the_engine_evidence_gate_waits_for_evidence_not_for_a_person(self):
        decision = decide("engine_evidence")
        self.assertFalse(decision.automatic)
        self.assertFalse(decision.needs_person)
        self.assertIn("evidence", decision.summary.text("en"))

    def test_an_unknown_gate_is_refused_rather_than_waved_through(self):
        with self.assertRaises(ValueError):
            decide("looks_fine_to_me")

    def test_the_catalogue_names_only_three_reasons_to_ask_a_person(self):
        self.assertEqual(tuple(catalogue()["asks_a_person_only_for"]), ASK_REASONS)
        self.assertEqual(len(catalogue()["gates"]), len(CATALOGUE))

    def test_every_gate_explains_itself_in_both_languages(self):
        for language in LANGUAGES:
            for gate in catalogue(language)["gates"]:
                self.assertTrue(gate["policy"].strip())
                self.assertTrue(gate["title"].strip())
        self.assertNotEqual(
            catalogue("uk")["gates"][0]["policy"], catalogue("en")["gates"][0]["policy"])


class QuestionTests(unittest.TestCase):
    def test_money_over_the_limit_asks_with_both_numbers(self):
        question = over_budget(amount=1.2, remaining=0.3)
        text = question.subject.text("en")
        self.assertIn("1.2", text)
        self.assertIn("0.3", text)
        self.assertEqual(question.options, ("raise_limit", "stop"))

    def test_an_irreversible_action_names_itself(self):
        self.assertIn("publish", irreversible("publish").subject.text("en"))

    def test_a_request_beyond_the_declared_capability_quotes_the_statement(self):
        question = beyond_capability("3D is not supported")
        self.assertIn("3D is not supported", question.subject.text("en"))

    def test_a_made_up_reason_to_ask_is_refused(self):
        from agent_factory.localisation import Message
        from agent_factory.studio_autonomy import Question

        with self.assertRaises(ValueError):
            Question("because_i_said_so", Message("Х", "X"), Message("Х", "X"), ())

    def test_a_question_turns_the_decision_into_one_that_needs_a_person(self):
        decision = decide("execution_authorization", question=over_budget(
            amount=2.0, remaining=0.0, blocks="task-7"))
        self.assertFalse(decision.automatic)
        self.assertTrue(decision.needs_person)
        self.assertEqual(decision.record("en")["question"]["blocks"], "task-7")


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.storage = SQLiteStorage(Path(self.folder.name) / "autonomy.db")
        self.addCleanup(self.storage.db.close)
        self.journal = AutonomyJournal(self.storage)

    def test_an_automatic_decision_is_recorded_with_the_policy_that_made_it(self):
        self.journal.record(decide("backlog_revision", context={"mission": 1}), mission="m1")
        entry = self.journal.decisions(mission="m1", language="en")[0]
        self.assertTrue(entry["automatic"])
        self.assertIn("Applied automatically", entry["policy"])
        self.assertTrue(entry["context"])

    def test_the_journal_reads_in_both_languages(self):
        self.journal.record(decide("backlog_revision"), mission="m1")
        self.assertNotEqual(
            self.journal.decisions(mission="m1", language="uk")[0]["policy"],
            self.journal.decisions(mission="m1", language="en")[0]["policy"])

    def test_a_recorded_decision_cannot_be_rewritten_or_deleted(self):
        self.journal.record(decide("backlog_revision"), mission="m1")
        for statement in (
            "UPDATE studio_decisions SET automatic=0 WHERE id=1",
            "DELETE FROM studio_decisions WHERE id=1",
        ):
            with self.assertRaises(Exception):
                with self.storage.db:
                    self.storage.db.execute(statement)

    def test_a_question_blocks_only_what_it_is_about(self):
        self.journal.record(decide("backlog_revision"), mission="m1")
        self.journal.record(
            decide("execution_authorization",
                   question=over_budget(amount=2.0, remaining=0.0, blocks="task-7")),
            mission="m1")
        self.assertEqual(self.journal.blocked_by_questions(mission="m1"), ("task-7",))

    def test_a_question_without_a_subject_blocks_nothing(self):
        self.journal.record(
            decide("execution_authorization", question=irreversible("publish")),
            mission="m1")
        self.assertEqual(self.journal.blocked_by_questions(mission="m1"), ())
        self.assertEqual(len(self.journal.open_questions(mission="m1")), 1)

    def test_an_answer_is_recorded_against_a_named_person(self):
        self.journal.record(
            decide("execution_authorization",
                   question=over_budget(amount=2.0, remaining=0.0)), mission="m1")
        question_id = self.journal.open_questions(mission="m1")[0]["question_id"]
        answered = self.journal.answer(question_id, answer="stop", actor=" miha ")
        self.assertEqual(answered["answered_by"], "miha")
        self.assertEqual(self.journal.open_questions(mission="m1"), ())

    def test_an_unnamed_person_answers_nothing(self):
        self.journal.record(
            decide("execution_authorization", question=irreversible("delete")), mission="m1")
        question_id = self.journal.open_questions()[0]["question_id"]
        with self.assertRaises(AutonomyRefused):
            self.journal.answer(question_id, answer="skip", actor="")

    def test_an_answer_outside_the_offered_options_is_refused(self):
        self.journal.record(
            decide("execution_authorization", question=irreversible("delete")), mission="m1")
        question_id = self.journal.open_questions()[0]["question_id"]
        with self.assertRaises(AutonomyRefused) as caught:
            self.journal.answer(question_id, answer="maybe", actor="miha")
        self.assertIn("maybe", caught.exception.text("en"))

    def test_a_question_is_answered_once(self):
        self.journal.record(
            decide("execution_authorization", question=irreversible("delete")), mission="m1")
        question_id = self.journal.open_questions()[0]["question_id"]
        self.journal.answer(question_id, answer="skip", actor="miha")
        with self.assertRaises(AutonomyRefused):
            self.journal.answer(question_id, answer="do_it", actor="someone-else")

    def test_a_withdrawn_question_stops_waiting_without_being_answered(self):
        self.journal.record(
            decide("execution_authorization",
                   question=irreversible("delete", blocks="task-2")), mission="m1")
        question_id = self.journal.open_questions()[0]["question_id"]
        self.journal.withdraw(question_id)
        self.assertEqual(self.journal.open_questions(mission="m1"), ())
        self.assertEqual(self.journal.blocked_by_questions(mission="m1"), ())

    def test_an_unknown_question_is_refused_rather_than_invented(self):
        with self.assertRaises(KeyError):
            self.journal.answer(404, answer="stop", actor="miha")

    def test_the_report_shows_the_gates_the_decisions_and_what_is_held_up(self):
        self.journal.record(decide("backlog_revision"), mission="m1")
        self.journal.record(
            decide("execution_authorization",
                   question=over_budget(amount=2.0, remaining=0.0, blocks="task-7")),
            mission="m1")
        report = self.journal.report(mission="m1", language="en")
        self.assertEqual(len(report["gates"]), len(CATALOGUE))
        self.assertEqual(len(report["decisions"]), 2)
        self.assertEqual(report["blocked"], ["task-7"])
        self.assertEqual(len(report["questions"]), 1)


if __name__ == "__main__":
    unittest.main()
