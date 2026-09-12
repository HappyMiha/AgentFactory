"""The status screen reads the run's own rows, and never flatters them."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_factory.localisation import LANGUAGES
from agent_factory.storage import SQLiteStorage
from agent_factory.work_status_store import WorkStatusReader


NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)


def stamp(seconds_ago):
    return (NOW - timedelta(seconds=seconds_ago)).isoformat()


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.storage = SQLiteStorage(Path(self.folder.name) / "status.db")
        self.addCleanup(self.storage.db.close)
        db = self.storage.db
        with db:
            db.execute("INSERT INTO projects(id,name,description) VALUES(1,'Lokvetia Core','')")
            db.execute(
                "INSERT INTO work_items(id,project_id,identity,title,description,payload,status)"
                " VALUES(1,1,'task-1','Ship the status screen','','{}','in_progress')")
            db.execute(
                "INSERT INTO workflow_runs(id,identity,project_id,task_id,workflow_id,status)"
                " VALUES(1,'run-1',1,1,'delivery','running')")
        self.reader = WorkStatusReader(self.storage)

    def stages(self, *rows):
        with self.storage.db:
            for index, (key, state, touched) in enumerate(rows, start=1):
                self.storage.db.execute(
                    "INSERT INTO workflow_stages(identity,run_id,stage_key,status,updated_at)"
                    " VALUES(?,1,?,?,?)",
                    (f"stage-{index}", key, state, touched))

    def attempt(self, *, provider="claude", status="running", started=None,
                finished=None, heartbeat=None, gate=1):
        with self.storage.db:
            self.storage.db.execute(
                "INSERT INTO provider_execution_gates(id,provider,agent_id,task_id)"
                " VALUES(?,?,?,1)", (gate, provider, "coding-worker"))
            self.storage.db.execute(
                """INSERT INTO provider_execution_attempts
                   (identity,gate_id,provider,agent_id,task_id,request_hash,definition_hash,
                    status,started_at,finished_at,heartbeat_at)
                   VALUES(?,?,?,?,1,'request','definition',?,?,?,?)""",
                (f"attempt-{gate}", gate, provider, "coding-worker", status,
                 started, finished, heartbeat))

    def trace(self, *, cap=10.0):
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO execution_traces
                   (id,identity,correlation_root,task_id,run_id,max_tokens,max_cost_usd,
                    max_stages,max_retries,max_tool_calls)
                   VALUES(1,'trace-1','root-1',1,1,100000,?,10,2,50)""", (cap,))

    def ledger(self, *entries):
        with self.storage.db:
            for index, (source, cost) in enumerate(entries, start=1):
                self.storage.db.execute(
                    """INSERT INTO cost_ledger_entries
                       (identity,trace_id,idempotency_key,provider,source,tokens,
                        duration_ms,cost_usd,metadata_json)
                       VALUES(?,1,?, 'claude',?,100,1000,?,'{}')""",
                    (f"entry-{index}", f"key-{index}", source, cost))

    # ------------------------------------------------------------------ stage

    def test_the_stage_is_numbered_inside_the_run_s_own_workflow(self):
        self.stages(("policy-precheck", "succeeded", stamp(600)),
                    ("implementation", "running", stamp(10)),
                    ("validation", "pending", stamp(600)))
        state = self.reader.for_run(1, now=NOW)
        self.assertEqual(state.stage.stage_id, "implementation")
        self.assertEqual((state.stage.index, state.stage.total), (2, 3))

    def test_a_run_with_no_stage_yet_says_so_instead_of_inventing_one(self):
        state = self.reader.for_run(1, now=NOW)
        self.assertEqual(state.stage.index, 1)
        self.assertTrue(state.stage.label.text("uk"))

    def test_an_unknown_run_is_refused(self):
        with self.assertRaises(KeyError):
            self.reader.for_run(404)

    # -------------------------------------------------------------- liveness

    def test_a_worker_heartbeat_is_the_sign_of_life(self):
        self.stages(("implementation", "running", stamp(500)))
        self.attempt(started=stamp(300), heartbeat=stamp(5))
        self.assertEqual(self.reader.for_run(1, now=NOW).liveness, "alive")

    def test_without_a_worker_the_running_stage_is_the_only_sign_of_life(self):
        self.stages(("implementation", "running", stamp(20)))
        self.assertEqual(self.reader.for_run(1, now=NOW).liveness, "alive")

    def test_a_worker_that_stopped_reporting_becomes_a_blocker(self):
        self.stages(("implementation", "running", stamp(4000)))
        self.attempt(started=stamp(5000), heartbeat=stamp(3600))
        state = self.reader.for_run(1, now=NOW)
        self.assertEqual(state.liveness, "stalled")
        self.assertIn("no_heartbeat", [one.code for one in state.blockers])

    def test_a_finished_attempt_is_not_mistaken_for_a_live_one(self):
        self.stages(("implementation", "running", stamp(4000)))
        self.attempt(status="succeeded", started=stamp(4200), finished=stamp(4000),
                     heartbeat=stamp(1))
        self.assertEqual(self.reader.for_run(1, now=NOW).liveness, "stalled")

    # -------------------------------------------------------------- blockers

    def test_a_stage_waiting_for_a_person_says_what_the_person_should_do(self):
        self.stages(("validation", "waiting_approval", stamp(30)))
        state = self.reader.for_run(1, now=NOW)
        self.assertEqual([one.code for one in state.blockers], ["waiting_approval"])
        self.assertTrue(state.next_action.text("en"))
        self.assertFalse(state.estimate.known)

    def test_a_failed_stage_is_a_blocker_with_a_decision_attached(self):
        self.stages(("implementation", "failed", stamp(30)))
        state = self.reader.for_run(1, now=NOW)
        self.assertEqual([one.code for one in state.blockers], ["stage_failed"])

    # ------------------------------------------------------------- estimates

    def test_an_estimate_comes_only_from_this_run_s_measured_attempts(self):
        self.stages(("implementation", "running", stamp(10)),
                    ("validation", "pending", stamp(10)))
        for index in range(3):
            self.attempt(status="succeeded", gate=index + 1,
                         started=stamp(1000 - index * 100),
                         finished=stamp(940 - index * 100))
        self.attempt(gate=9, started=stamp(100), heartbeat=stamp(2))
        state = self.reader.for_run(1, now=NOW)
        self.assertTrue(state.estimate.known)
        self.assertEqual(state.estimate.seconds, 120.0)

    def test_one_measured_attempt_is_not_enough_for_an_estimate(self):
        self.stages(("implementation", "running", stamp(10)))
        self.attempt(status="succeeded", started=stamp(200), finished=stamp(140))
        self.assertFalse(self.reader.for_run(1, now=NOW).estimate.known)

    # ----------------------------------------------------------------- money

    def test_reported_cost_is_spent_and_an_estimate_is_only_reserved(self):
        self.trace(cap=10.0)
        self.ledger(("provider_reported", 2.0), ("estimated", 0.5))
        money = self.reader.spend(1)
        self.assertEqual((money.spent, money.reserved), (2.0, 0.5))
        self.assertEqual(money.remaining, 7.5)

    def test_a_run_over_its_cap_blocks_and_names_the_decision(self):
        self.stages(("implementation", "running", stamp(10)))
        self.trace(cap=1.0)
        self.ledger(("provider_reported", 1.5))
        state = self.reader.for_run(1, now=NOW)
        self.assertIn("over_cap", [one.code for one in state.blockers])

    def test_a_cap_a_person_raised_is_the_cap_that_counts(self):
        self.trace(cap=1.0)
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO budget_authorizations
                   (identity,trace_id,previous_max_cost_usd,new_max_cost_usd,
                    authority,authority_role,reason)
                   VALUES('auth-1',1,1.0,5.0,'miha','human_budget_authority','agreed')""")
        self.assertEqual(self.reader.spend(1).cap, 5.0)

    def test_a_run_with_no_trace_claims_no_budget(self):
        money = self.reader.spend(1)
        self.assertIsNone(money.cap)
        self.assertFalse(money.over_cap)

    # -------------------------------------------------------------- stopping

    def test_a_call_already_sent_is_not_promised_back(self):
        self.stages(("implementation", "running", stamp(10)))
        self.attempt(provider="claude", started=stamp(30), heartbeat=stamp(2))
        plan = self.reader.stop_plan(1)
        self.assertEqual([one.kind for one in plan.finishes_anyway], ["inference"])
        self.assertIn("cannot be recalled", plan.spending.text("en"))

    def test_a_local_model_call_costs_nothing_to_abandon(self):
        self.stages(("implementation", "running", stamp(10)))
        self.attempt(provider="ollama", started=stamp(30), heartbeat=stamp(2))
        self.assertNotIn("cannot be recalled", self.reader.stop_plan(1).spending.text("en"))

    def test_queued_stages_are_what_a_stop_can_actually_cut_short(self):
        self.stages(("implementation", "running", stamp(10)),
                    ("validation", "pending", stamp(10)))
        self.attempt(provider="ollama", started=stamp(30), heartbeat=stamp(2))
        plan = self.reader.stop_plan(1)
        self.assertEqual([one.kind for one in plan.stops_now], ["scheduling"])

    def test_the_wait_for_a_call_is_measured_or_admitted_unknown(self):
        self.stages(("implementation", "running", stamp(10)))
        self.attempt(gate=1, provider="claude", status="succeeded",
                     started=stamp(400), finished=stamp(340))
        self.attempt(gate=2, provider="claude", started=stamp(30), heartbeat=stamp(2))
        self.assertEqual(self.reader.stop_plan(1).longest_wait_seconds, 60.0)

    def test_with_nothing_measured_the_wait_is_not_guessed(self):
        self.stages(("implementation", "running", stamp(10)))
        self.attempt(provider="claude", started=stamp(30), heartbeat=stamp(2))
        plan = self.reader.stop_plan(1)
        self.assertIsNone(plan.longest_wait_seconds)
        self.assertTrue(plan.warnings)

    # --------------------------------------------------------- after restart

    def test_an_unfinished_attempt_survives_a_restart_as_something_to_check(self):
        self.attempt(gate=1, status="succeeded", started=stamp(400), finished=stamp(340))
        self.attempt(gate=2, status="running", started=stamp(30), heartbeat=stamp(20))
        result = self.reader.after_restart(1)
        self.assertEqual([one.identity for one in result.preserved], ["attempt-1"])
        self.assertEqual([one.identity for one in result.to_check], ["attempt-2"])
        self.assertTrue(result.safe)

    # --------------------------------------------------------------- reports

    def test_the_report_answers_in_the_language_it_was_asked_in(self):
        self.stages(("implementation", "running", stamp(10)))
        self.attempt(provider="claude", started=stamp(30), heartbeat=stamp(2))
        reports = {language: self.reader.report(1, language=language, now=NOW)
                   for language in LANGUAGES}
        for language, report in reports.items():
            self.assertEqual(report["run_id"], 1)
            self.assertTrue(report["next_action"])
            self.assertTrue(report["stop"]["spending"])
        self.assertNotEqual(reports["uk"]["next_action"], reports["en"]["next_action"])

    def test_an_open_run_is_listed_with_its_project_and_task(self):
        listed = self.reader.open_runs()
        self.assertEqual(listed[0]["run_id"], 1)
        self.assertEqual(listed[0]["project"], "Lokvetia Core")
        self.assertEqual(listed[0]["title"], "Ship the status screen")


if __name__ == "__main__":
    unittest.main()
