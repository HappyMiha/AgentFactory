"""Three numbers about money, and the rule that keeps each one honest."""

import tempfile
import unittest
from pathlib import Path

from agent_factory.localisation import LANGUAGES
from agent_factory.storage import SQLiteStorage
from agent_factory.studio_cost import (
    CostRefused,
    StudioCosts,
    forecast_remaining,
)


class ForecastTests(unittest.TestCase):
    def test_no_measured_task_means_no_forecast(self):
        forecast = forecast_remaining(measured=(), remaining_tasks=5)
        self.assertFalse(forecast.known)
        self.assertIn("no measured task", forecast.basis.text("en"))

    def test_two_measured_tasks_are_too_few(self):
        forecast = forecast_remaining(measured=(0.4, 0.6), remaining_tasks=5)
        self.assertFalse(forecast.known)
        self.assertIn("too few", forecast.basis.text("en"))

    def test_three_measured_tasks_give_a_number_that_names_its_basis(self):
        forecast = forecast_remaining(measured=(0.4, 0.6, 0.5), remaining_tasks=4)
        self.assertEqual(forecast.amount, 2.0)
        self.assertIn("3 measured tasks", forecast.basis.text("en"))

    def test_a_free_task_is_not_a_measurement(self):
        self.assertFalse(
            forecast_remaining(measured=(0, 0, 0, 0.5), remaining_tasks=2).known)

    def test_nothing_left_in_the_stage_is_zero_rather_than_unknown(self):
        forecast = forecast_remaining(measured=(0.4, 0.6, 0.5), remaining_tasks=0)
        self.assertEqual(forecast.amount, 0.0)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.storage = SQLiteStorage(Path(self.folder.name) / "cost.db")
        self.addCleanup(self.storage.db.close)
        self.costs = StudioCosts(self.storage)

    def test_an_estimate_is_reserved_and_a_report_is_spent(self):
        self.costs.record("m1", amount=0.5, kind="estimated", task_key="t1")
        self.assertEqual(self.costs.totals("m1"),
                         {"spent": 0.0, "reserved": 0.5, "committed": 0.5})
        self.costs.record("m1", amount=0.7, kind="reported", task_key="t2")
        self.assertEqual(self.costs.totals("m1")["spent"], 0.7)

    def test_settling_a_task_releases_its_reservation_without_erasing_it(self):
        self.costs.record("m1", amount=0.5, kind="estimated", task_key="t1")
        self.costs.settle("m1", "t1", amount=0.7)
        self.assertEqual(self.costs.totals("m1"),
                         {"spent": 0.7, "reserved": 0.0, "committed": 0.7})
        rows = self.storage.db.execute(
            "SELECT kind,amount FROM studio_spend ORDER BY id").fetchall()
        self.assertEqual([(row["kind"], row["amount"]) for row in rows],
                         [("estimated", 0.5), ("reported", 0.7)])

    def test_an_estimate_for_another_task_keeps_counting(self):
        self.costs.record("m1", amount=0.5, kind="estimated", task_key="t1")
        self.costs.record("m1", amount=0.4, kind="estimated", task_key="t2")
        self.costs.settle("m1", "t1", amount=0.7)
        self.assertEqual(self.costs.totals("m1")["reserved"], 0.4)

    def test_a_negative_cost_is_refused(self):
        with self.assertRaises(CostRefused):
            self.costs.record("m1", amount=-1.0)

    def test_an_invented_kind_of_cost_is_refused(self):
        with self.assertRaises(CostRefused) as caught:
            self.costs.record("m1", amount=1.0, kind="probably")
        self.assertIn("probably", caught.exception.text("en"))

    def test_recorded_spend_cannot_be_rewritten_or_deleted(self):
        self.costs.record("m1", amount=1.0, task_key="t1")
        for statement in (
            "UPDATE studio_spend SET amount=0 WHERE id=1",
            "DELETE FROM studio_spend WHERE id=1",
        ):
            with self.assertRaises(Exception):
                with self.storage.db:
                    self.storage.db.execute(statement)

    def test_spend_is_attributed_to_the_role_that_incurred_it(self):
        self.costs.record("m1", amount=1.0, task_key="t1", role="developer")
        self.costs.record("m1", amount=0.4, task_key="t2", role="planner")
        by_role = {row["role"]: row["spent"] for row in self.costs.by_role("m1")}
        self.assertEqual(by_role, {"developer": 1.0, "planner": 0.4})

    def test_spend_with_no_role_is_shown_as_unattributed_not_spread_around(self):
        self.costs.record("m1", amount=1.0, task_key="t1", role="developer")
        self.costs.record("m1", amount=0.4, task_key="t2")
        by_role = {row["role"]: row["spent"] for row in self.costs.by_role("m1")}
        self.assertEqual(by_role["unattributed"], 0.4)
        self.assertEqual(by_role["developer"], 1.0)

    def test_the_task_table_says_who_did_it_with_what(self):
        self.costs.record(
            "m1", amount=1.0, task_key="t1", role="developer",
            provider="claude", model="opus")
        entry = self.costs.by_task("m1")[0]
        self.assertEqual(
            (entry["task"], entry["role"], entry["provider"], entry["model"]),
            ("t1", "developer", "claude", "opus"))

    def test_one_mission_does_not_see_another_mission_s_money(self):
        self.costs.record("m1", amount=1.0, task_key="t1")
        self.assertEqual(self.costs.totals("m2")["spent"], 0.0)


class LimitTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.storage = SQLiteStorage(Path(self.folder.name) / "limit.db")
        self.addCleanup(self.storage.db.close)
        self.costs = StudioCosts(self.storage)

    def test_with_no_limit_there_is_nothing_to_stop_at(self):
        state = self.costs.check("m1", next_step=100.0)
        self.assertFalse(state["over"])
        self.assertIsNone(state["question"])
        self.assertIn("No limit", state["summary"].text("en"))

    def test_a_limit_is_set_by_a_named_person(self):
        with self.assertRaises(CostRefused):
            self.costs.set_limit("m1", amount=5.0, actor="  ")

    def test_a_step_that_fits_is_not_a_question(self):
        self.costs.set_limit("m1", amount=5.0, actor="miha")
        self.costs.record("m1", amount=1.0, task_key="t1")
        state = self.costs.check("m1", next_step=1.0)
        self.assertFalse(state["over"])
        self.assertEqual(state["remaining"], 4.0)

    def test_a_step_that_would_go_over_becomes_a_question_for_the_person(self):
        self.costs.set_limit("m1", amount=2.0, actor="miha")
        self.costs.record("m1", amount=1.5, task_key="t1")
        state = self.costs.check("m1", next_step=1.0)
        self.assertTrue(state["over"])
        self.assertEqual(state["question"].reason, "over_budget")
        self.assertEqual(state["question"].options, ("raise_limit", "stop"))

    def test_a_reservation_counts_towards_the_limit_before_the_money_goes(self):
        self.costs.set_limit("m1", amount=1.0, actor="miha")
        self.costs.record("m1", amount=1.5, kind="estimated", task_key="t1")
        self.assertTrue(self.costs.check("m1")["over"])

    def test_a_raised_limit_supersedes_the_old_one_and_both_are_kept(self):
        self.costs.set_limit("m1", amount=2.0, actor="miha")
        self.costs.set_limit("m1", amount=6.0, actor="miha", reason="agreed")
        self.assertEqual(self.costs.limit("m1").amount, 6.0)
        self.assertEqual(len(self.costs.limit_history("m1")), 2)

    def test_a_limit_cannot_be_edited_in_place(self):
        self.costs.set_limit("m1", amount=2.0, actor="miha")
        with self.assertRaises(Exception):
            with self.storage.db:
                self.storage.db.execute("UPDATE studio_limits SET amount=99 WHERE id=1")

    def test_the_report_reads_in_both_languages(self):
        self.costs.set_limit("m1", amount=2.0, actor="miha")
        self.costs.record("m1", amount=0.5, task_key="t1", role="developer")
        for language in LANGUAGES:
            report = self.costs.report("m1", language=language, remaining_tasks=3)
            self.assertTrue(report["summary"])
            self.assertFalse(report["forecast"]["known"])
        self.assertNotEqual(
            self.costs.report("m1", language="uk")["summary"],
            self.costs.report("m1", language="en")["summary"])

    def test_the_forecast_uses_only_this_mission_s_measured_tasks(self):
        for index, amount in enumerate((0.4, 0.6, 0.5), start=1):
            self.costs.record("m1", amount=amount, task_key=f"t{index}", stage_key="base")
        self.costs.record("m2", amount=99.0, task_key="other")
        forecast = self.costs.forecast("m1", remaining_tasks=2, stage_key="base")
        self.assertEqual(forecast.amount, 1.0)
