"""What the status screen is allowed to claim.

These tests are about honesty rather than arithmetic: an estimate may exist
only when measured steps support one, a silence must surface as a blocker with
something to do about it, a stop must not promise to recall a paid call that
was already sent, and a restart must never relaunch an orphan.
"""

import unittest
from datetime import datetime, timedelta, timezone

from agent_factory.localisation import LANGUAGES, Message, missing_translations
from agent_factory import work_status as status


NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
STAGE = status.Stage.create("development", Message("Розробка", "Development"))


def beat(seconds_ago):
    return (NOW - timedelta(seconds=seconds_ago)).isoformat()


class StageTests(unittest.TestCase):
    def test_a_stage_knows_where_it_sits_in_the_whole_run(self):
        self.assertEqual(STAGE.index, 3)
        self.assertEqual(STAGE.total, len(status.STAGES))

    def test_an_unknown_stage_is_refused_rather_than_invented(self):
        with self.assertRaises(ValueError):
            status.Stage.create("finishing-touches", Message("Штрихи", "Touches"))


    def test_a_stage_of_a_configured_workflow_is_numbered_inside_it(self):
        stage = status.Stage.within(
            "implementation", Message("Реалізація", "Implementation"), index=2, total=4)
        self.assertEqual((stage.index, stage.total), (2, 4))

    def test_a_position_outside_the_workflow_is_refused(self):
        with self.assertRaises(ValueError):
            status.Stage.within("x", Message("Х", "X"), index=5, total=4)


class EstimateTests(unittest.TestCase):
    def test_no_finished_step_means_no_estimate(self):
        estimate = status.estimate_remaining(finished_step_seconds=(), remaining_steps=4)
        self.assertFalse(estimate.known)
        self.assertIs(estimate.basis, status.UNKNOWN_NO_SAMPLES)

    def test_two_finished_steps_are_too_few_to_extrapolate(self):
        estimate = status.estimate_remaining(finished_step_seconds=(30, 50), remaining_steps=4)
        self.assertFalse(estimate.known)
        self.assertIs(estimate.basis, status.UNKNOWN_TOO_FEW)

    def test_three_finished_steps_support_an_estimate_that_names_its_basis(self):
        estimate = status.estimate_remaining(
            finished_step_seconds=(30, 40, 50), remaining_steps=4)
        self.assertEqual(estimate.seconds, 160.0)
        self.assertIn("3", estimate.basis.text("en"))

    def test_a_silent_run_gets_no_estimate_however_many_steps_finished(self):
        estimate = status.estimate_remaining(
            finished_step_seconds=(30, 40, 50), remaining_steps=4, alive=False)
        self.assertFalse(estimate.known)
        self.assertIs(estimate.basis, status.UNKNOWN_STALLED)

    def test_waiting_on_a_person_gets_no_estimate(self):
        estimate = status.estimate_remaining(
            finished_step_seconds=(30, 40, 50), remaining_steps=4, blocked=True)
        self.assertFalse(estimate.known)
        self.assertIs(estimate.basis, status.UNKNOWN_BLOCKED)

    def test_nothing_running_gets_no_estimate(self):
        estimate = status.estimate_remaining(
            finished_step_seconds=(30, 40, 50), remaining_steps=4, running=False)
        self.assertFalse(estimate.known)
        self.assertIs(estimate.basis, status.UNKNOWN_IDLE)

    def test_a_zero_length_step_is_not_a_measurement(self):
        estimate = status.estimate_remaining(
            finished_step_seconds=(0, 0, 0, 40), remaining_steps=2)
        self.assertFalse(estimate.known)

    def test_nothing_left_to_do_is_zero_rather_than_unknown(self):
        estimate = status.estimate_remaining(
            finished_step_seconds=(30, 40, 50), remaining_steps=0)
        self.assertEqual(estimate.seconds, 0.0)


class SpendTests(unittest.TestCase):
    def test_committed_counts_the_reservation_as_well_as_the_spend(self):
        self.assertEqual(status.Spend(reserved=2.5, spent=7.5).committed, 10.0)

    def test_without_a_cap_nothing_is_over_it(self):
        self.assertFalse(status.Spend(spent=1000.0).over_cap)
        self.assertIsNone(status.Spend(spent=1000.0).remaining)

    def test_a_reservation_can_put_a_run_over_the_cap_before_the_money_is_gone(self):
        money = status.Spend(reserved=6.0, spent=5.0, cap=10.0)
        self.assertTrue(money.over_cap)
        self.assertEqual(money.remaining, -1.0)


class ComposeTests(unittest.TestCase):
    def test_a_recent_heartbeat_reads_as_alive_with_nothing_to_do(self):
        state = status.compose(project="core", stage=STAGE, heartbeat_at=beat(10), now=NOW)
        self.assertEqual(state.liveness, "alive")
        self.assertFalse(state.blocked)
        self.assertIs(state.next_action, status.NEXT_WAIT)

    def test_a_late_heartbeat_is_quiet_and_still_not_a_blocker(self):
        state = status.compose(project="core", stage=STAGE, heartbeat_at=beat(120), now=NOW)
        self.assertEqual(state.liveness, "quiet")
        self.assertEqual(state.blockers, ())

    def test_a_stopped_heartbeat_becomes_a_blocker_with_an_action(self):
        state = status.compose(project="core", stage=STAGE, heartbeat_at=beat(1200), now=NOW)
        self.assertEqual(state.liveness, "stalled")
        self.assertEqual([one.code for one in state.blockers], ["no_heartbeat"])
        self.assertTrue(state.blockers[0].since)
        self.assertEqual(state.next_action, state.blockers[0].action)

    def test_a_heartbeat_that_never_arrived_is_stalled_not_alive(self):
        state = status.compose(project="core", stage=STAGE, heartbeat_at=None, now=NOW)
        self.assertEqual(state.liveness, "stalled")
        self.assertEqual(state.heartbeat_at, "")
        self.assertIsNone(state.heartbeat_age_seconds)

    def test_an_unreadable_heartbeat_is_treated_as_no_heartbeat(self):
        state = status.compose(project="core", stage=STAGE, heartbeat_at="soon", now=NOW)
        self.assertEqual(state.liveness, "stalled")

    def test_going_over_the_cap_blocks_and_says_what_to_decide(self):
        state = status.compose(
            project="core", stage=STAGE, heartbeat_at=beat(5),
            spend=status.Spend(reserved=1.0, spent=10.0, cap=10.0), now=NOW)
        self.assertIn("over_cap", [one.code for one in state.blockers])
        self.assertIs(state.next_action, status.OVER_CAP.action)

    def test_a_blocked_run_never_shows_a_finishing_time(self):
        state = status.compose(
            project="core", stage=STAGE, heartbeat_at=beat(5),
            spend=status.Spend(spent=11.0, cap=10.0),
            finished_step_seconds=(30, 40, 50), remaining_steps=4, now=NOW)
        self.assertFalse(state.estimate.known)

    def test_a_caller_supplied_blocker_is_kept_and_answered_first(self):
        waiting = status.Blocker(
            "needs_key", Message("Потрібен ключ.", "A key is needed."),
            Message("Додайте ключ у налаштуваннях.", "Add the key in settings."))
        state = status.compose(
            project="core", stage=STAGE, heartbeat_at=beat(5),
            blockers=[waiting], now=NOW)
        self.assertIs(state.next_action, waiting.action)

    def test_a_playable_version_is_offered_while_the_rest_continues(self):
        state = status.compose(
            project="core", stage=STAGE, heartbeat_at=beat(5),
            playable_version="v7", now=NOW)
        self.assertIs(state.next_action, status.NEXT_PLAY)

    def test_a_playable_version_never_replaces_a_blocker(self):
        state = status.compose(
            project="core", stage=STAGE, heartbeat_at=beat(1200),
            playable_version="v7", now=NOW)
        self.assertEqual(state.next_action, state.blockers[0].action)

    def test_a_run_waiting_on_a_person_is_not_reported_as_a_dead_worker(self):
        state = status.compose(
            project="core", stage=STAGE, heartbeat_at=None,
            expects_heartbeat=False, now=NOW)
        self.assertEqual(state.liveness, "waiting")
        self.assertEqual(state.blockers, ())
        self.assertIs(state.next_action, status.NEXT_IDLE)

    def test_a_waiting_run_still_shows_a_blocker_the_caller_knows_about(self):
        waiting = status.Blocker(
            "needs_key", Message("Потрібен ключ.", "A key is needed."),
            Message("Додайте ключ.", "Add the key."))
        state = status.compose(
            project="core", stage=STAGE, heartbeat_at=None, blockers=[waiting],
            expects_heartbeat=False, now=NOW)
        self.assertEqual([one.code for one in state.blockers], ["needs_key"])

    def test_the_record_carries_every_claim_in_the_asked_language(self):
        state = status.compose(
            project="core", stage=STAGE, heartbeat_at=beat(1200),
            spend=status.Spend(spent=1.0, cap=10.0), now=NOW)
        for language in LANGUAGES:
            record = state.record(language)
            self.assertEqual(record["project"], "core")
            self.assertEqual(record["stage"]["index"], 3)
            self.assertTrue(record["next_action"])
            self.assertFalse(record["estimate"]["known"])
            self.assertTrue(record["blockers"][0]["action"])
        self.assertNotEqual(
            state.record("uk")["next_action"], state.record("en")["next_action"])


class StopTests(unittest.TestCase):
    def make(self, kind, interruptible, **rest):
        return status.Operation(
            kind, Message(f"Дія {kind}", f"Action {kind}"), interruptible, **rest)

    def test_a_stop_names_the_kinds_of_work_it_covers(self):
        plan = status.plan_stop([])
        self.assertEqual(plan.covers, status.STOPPABLE)

    def test_what_can_be_cut_short_is_separated_from_what_cannot(self):
        plan = status.plan_stop([
            self.make("scheduling", True),
            self.make("build", False, typical_seconds=90),
        ])
        self.assertEqual([one.kind for one in plan.stops_now], ["scheduling"])
        self.assertEqual([one.kind for one in plan.finishes_anyway], ["build"])
        self.assertEqual(plan.longest_wait_seconds, 90)

    def test_a_paid_call_already_sent_is_not_claimed_back(self):
        plan = status.plan_stop([self.make("inference", False, paid=True, typical_seconds=20)])
        self.assertIs(plan.spending, status.SPENDING_IN_FLIGHT)

    def test_with_nothing_paid_in_flight_the_stop_stops_the_spending(self):
        plan = status.plan_stop([self.make("scheduling", True)])
        self.assertIs(plan.spending, status.SPENDING_STOPPED)

    def test_an_unmeasurable_wait_is_admitted_rather_than_guessed(self):
        plan = status.plan_stop([self.make("build", False)])
        self.assertIsNone(plan.longest_wait_seconds)
        self.assertIn(status.UNKNOWN_WAIT, plan.warnings)

    def test_a_measurable_wait_needs_no_warning(self):
        plan = status.plan_stop([self.make("build", False, typical_seconds=30)])
        self.assertEqual(plan.warnings, ())

    def test_an_unknown_kind_of_work_is_refused_rather_than_hidden(self):
        with self.assertRaises(ValueError):
            self.make("gardening", True)

    def test_the_plan_reads_in_both_languages(self):
        plan = status.plan_stop([self.make("inference", False, paid=True)])
        self.assertNotEqual(plan.record("uk")["spending"], plan.record("en")["spending"])


class RestartTests(unittest.TestCase):
    def records(self):
        return [
            status.Record("run", "run-1", "completed",
                          Message("Завершено.", "Finished."), accepted=True),
            status.Record("call", "call-9", "in_flight",
                          Message("Виклик міг завершитися після падіння.",
                                  "The call may have finished after the crash.")),
        ]

    def test_accepted_work_survives_a_restart(self):
        result = status.reconcile_after_restart(self.records())
        self.assertEqual([one.identity for one in result.preserved], ["run-1"])

    def test_an_orphan_is_handed_back_to_be_checked(self):
        result = status.reconcile_after_restart(self.records())
        self.assertEqual([one.identity for one in result.to_check], ["call-9"])

    def test_nothing_is_ever_relaunched(self):
        result = status.reconcile_after_restart(self.records())
        self.assertEqual(result.relaunched, ())
        self.assertTrue(result.safe)

    def test_the_record_says_out_loud_that_nothing_was_repeated(self):
        result = status.reconcile_after_restart(self.records())
        self.assertIn("checked rather than repeated", result.record("en")["note"])
        self.assertTrue(result.record("uk")["note"])


class TranslationTests(unittest.TestCase):
    def test_every_message_this_module_publishes_exists_in_both_languages(self):
        messages = [
            value for value in vars(status).values() if isinstance(value, Message)
        ]
        self.assertTrue(messages)
        self.assertEqual(missing_translations(messages), ())

    def test_every_blocker_offers_an_action_in_both_languages(self):
        for blocker in (status.NO_HEARTBEAT, status.OVER_CAP):
            for language in LANGUAGES:
                self.assertTrue(blocker.record(language)["action"].strip())


if __name__ == "__main__":
    unittest.main()
