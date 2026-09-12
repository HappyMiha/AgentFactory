"""The plan as a person reads it, and the three ways it must not lie."""

import unittest
from dataclasses import dataclass

from agent_factory.localisation import LANGUAGES, Message
from agent_factory.studio_backlog import (
    BacklogRefused,
    Item,
    Plan,
    Stage,
    from_progress,
    human_title,
    role_label,
    state_of,
)


def item(key="a", title="Кіт збирає монети", state="planned", **rest):
    return Item.create(key, Message(title, "A cat collects coins"), state, **rest)


@dataclass
class Task:
    """The shape the engineering progress view produces."""

    stable_id: str
    title: str
    role: str = "developer"
    accepted: bool = False
    merged: bool = False
    explicitly_blocked: bool = False
    blocked_by: tuple = ()
    block: str = "base"


class TitleTests(unittest.TestCase):
    def test_an_internal_code_is_never_shown_as_a_name(self):
        with self.assertRaises(BacklogRefused) as caught:
            Item.create("a", Message("AF-GC-024 Доступність", "AF-GC-024 Accessibility"), "planned")
        self.assertIn("internal code", caught.exception.text("en"))

    def test_an_empty_title_is_refused(self):
        with self.assertRaises(Exception):
            Item.create("a", Message("   ", "   "), "planned")

    def test_a_code_is_stripped_rather_than_left_in_the_middle(self):
        self.assertEqual(human_title("AF-ST-101 — Зібрати дистрибутив"), "Зібрати дистрибутив")
        self.assertEqual(human_title("Fix the jump (AF-001)"), "Fix the jump ()")

    def test_a_name_with_no_code_is_left_alone(self):
        self.assertEqual(human_title("Кіт збирає монети"), "Кіт збирає монети")

    def test_an_unknown_state_is_refused(self):
        with self.assertRaises(ValueError):
            item(state="probably-fine")


class StateTests(unittest.TestCase):
    def test_only_accepted_work_is_done(self):
        self.assertEqual(state_of(accepted=True), "done")

    def test_a_mention_in_a_commit_is_progress_not_completion(self):
        self.assertEqual(state_of(accepted=False, started=True), "in_progress")

    def test_blocked_work_says_so_rather_than_looking_planned(self):
        self.assertEqual(state_of(accepted=False, blocked=True), "blocked")

    def test_acceptance_outranks_a_block(self):
        self.assertEqual(state_of(accepted=True, blocked=True), "done")

    def test_every_state_has_a_label_in_both_languages(self):
        for state in ("planned", "in_progress", "done", "blocked"):
            record = item(state=state).record("en")
            self.assertTrue(record["state_label"])
            self.assertNotEqual(
                item(state=state).record("uk")["state_label"], record["state_label"])


class StageTests(unittest.TestCase):
    def test_a_stage_cannot_call_itself_playable_without_a_version(self):
        with self.assertRaises(BacklogRefused):
            Stage("base", Message("База", "The base"), (item(),), boundary="playable")

    def test_a_stage_with_a_version_is_playable(self):
        stage = Stage(
            "base", Message("База", "The base"), (item(),),
            boundary="playable", playable_version="a" * 64)
        self.assertEqual(stage.record("en")["playable_version"], "a" * 64)

    def test_a_stage_with_nothing_to_test_says_so_out_loud(self):
        stage = Stage("setup", Message("Підготовка", "Preparation"), (item(),))
        self.assertIn("nothing to test", stage.record("en")["boundary_note"])

    def test_a_stage_counts_its_tasks_by_state(self):
        stage = Stage("base", Message("База", "The base"), (
            item(key="a", state="done"), item(key="b", state="planned"),
            item(key="c", state="planned")))
        self.assertEqual(stage.counts["planned"], 2)
        self.assertEqual(stage.counts["done"], 1)
        self.assertFalse(stage.done)

    def test_an_unknown_boundary_is_refused(self):
        with self.assertRaises(ValueError):
            Stage("base", Message("База", "The base"), (item(),), boundary="probably")


class PlanTests(unittest.TestCase):
    def plan(self):
        return Plan(Message("Кіт і монети", "The cat and the coins"), (
            Stage("setup", Message("Підготовка", "Preparation"),
                  (item(key="a", state="done"),)),
            Stage("base", Message("База гри", "The base of the game"), (
                item(key="b", state="in_progress"),
                item(key="c", state="planned"),
            ), boundary="playable", playable_version="b" * 64),
        ))

    def test_the_next_step_is_what_is_being_worked_on(self):
        self.assertEqual(self.plan().next_up.key, "b")

    def test_with_nothing_running_the_next_step_is_the_first_planned_one(self):
        plan = Plan(Message("Гра", "Game"), (
            Stage("base", Message("База", "Base"), (
                item(key="c", state="planned"), item(key="d", state="planned"))),
        ))
        self.assertEqual(plan.next_up.key, "c")

    def test_with_everything_done_the_plan_says_so(self):
        plan = Plan(Message("Гра", "Game"), (
            Stage("base", Message("База", "Base"), (item(key="a", state="done"),)),
        ))
        self.assertIsNone(plan.next_up)
        self.assertIn("done", plan.record("en")["next"])

    def test_with_everything_blocked_the_plan_says_it_is_waiting(self):
        plan = Plan(Message("Гра", "Game"), (
            Stage("base", Message("База", "Base"), (item(key="a", state="blocked"),)),
        ))
        self.assertIn("waiting", plan.record("en")["next"])

    def test_the_whole_plan_is_visible_not_only_the_current_task(self):
        record = self.plan().record("en")
        self.assertEqual(len(record["stages"]), 2)
        self.assertEqual(sum(len(stage["items"]) for stage in record["stages"]), 3)

    def test_the_playable_versions_are_listed_for_the_play_button(self):
        self.assertEqual(self.plan().record("en")["playable"], ["b" * 64])

    def test_no_internal_code_reaches_the_reader(self):
        import json
        import re

        for language in LANGUAGES:
            rendered = json.dumps(self.plan().record(language), ensure_ascii=False)
            self.assertIsNone(re.search(r"AF-[A-Z]{2,3}-\d", rendered))

    def test_the_plan_reads_in_both_languages(self):
        self.assertNotEqual(
            self.plan().record("uk")["project"], self.plan().record("en")["project"])


class FromProgressTests(unittest.TestCase):
    def convert(self, *tasks, **rest):
        return from_progress(tasks, project=Message("Гра", "Game"), **rest)

    def test_an_accepted_task_is_done(self):
        plan = self.convert(Task("AF-GC-001", "AF-GC-001 Прибрати дефект", accepted=True))
        self.assertEqual(plan.items[0].state, "done")

    def test_a_task_only_mentioned_in_a_commit_is_not_done(self):
        plan = self.convert(Task("AF-GC-002", "Додати стрибок", merged=True))
        self.assertEqual(plan.items[0].state, "in_progress")
        self.assertIn("not accepted", plan.items[0].record("en")["note"])

    def test_a_task_waiting_on_another_is_blocked(self):
        plan = self.convert(Task("AF-GC-003", "Зберігати гру", blocked_by=("AF-GC-002",)))
        self.assertEqual(plan.items[0].state, "blocked")

    def test_the_internal_code_is_stripped_from_the_title(self):
        plan = self.convert(Task("AF-GC-001", "AF-GC-001 Прибрати дефект"))
        self.assertEqual(plan.items[0].title.text("uk"), "Прибрати дефект")

    def test_the_role_is_named_in_words_or_not_at_all(self):
        named = self.convert(Task("AF-GC-001", "Додати стрибок", role="developer"))
        self.assertEqual(named.items[0].record("en")["role"], "Developer")
        unknown = self.convert(Task("AF-GC-002", "Додати стрибок", role="runtime-engineer"))
        self.assertEqual(unknown.items[0].record("en")["role"], "")

    def test_a_stage_becomes_playable_only_when_a_version_is_given(self):
        plan = self.convert(
            Task("AF-GC-001", "Додати стрибок"),
            playable={"base": "c" * 64},
        )
        self.assertEqual(plan.stages[0].boundary, "playable")
        plain = self.convert(Task("AF-GC-001", "Додати стрибок"))
        self.assertEqual(plain.stages[0].boundary, "nothing_to_test")

    def test_a_stage_title_falls_back_to_its_own_name(self):
        plan = self.convert(Task("AF-GC-001", "Додати стрибок"))
        self.assertEqual(plan.stages[0].record("en")["title"], "base")

    def test_role_label_is_none_for_an_unknown_role(self):
        self.assertIsNone(role_label("nobody-in-particular"))


if __name__ == "__main__":
    unittest.main()


class MissionPlanTests(unittest.TestCase):
    """The live mission's own backlog, in four words a person knows."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        from agent_factory.storage import SQLiteStorage

        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.storage = SQLiteStorage(Path(self.folder.name) / "mission.db")
        self.addCleanup(self.storage.db.close)
        db = self.storage.db
        with db:
            db.execute("INSERT INTO projects(id,name,description) VALUES(1,'Кіт і монети','')")
            db.execute(
                """INSERT INTO autonomous_missions
                   (id,identity,mission_key,project_id,name,mission_owner,phase,
                    disposition,configuration_json,configuration_digest)
                   VALUES(1,'mission-1','cat-coins',1,'Кіт і монети','miha','DEVELOPMENT',
                          'RUNNING','{}',?)""", ("c" * 64,))
            db.execute(
                """INSERT INTO autonomous_backlog_revisions
                   (id,identity,mission_id,revision_number,origin,created_by,rationale,
                    schema_version,source_sha256,snapshot_json,revision_digest,item_count)
                   VALUES(1,'rev-1',1,1,'HUMAN','miha','first',2,?,'{}',?,1)""",
                ("a" * 64, "b" * 64))

    def item(self, item_id, stable_id, title, status, *, parent=None, executable=1):
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO autonomous_backlog_items
                   (id,identity,revision_id,stable_id,kind,executable,title,description,
                    parent_stable_id,dependencies_json,priority,acceptance_criteria_json,
                    validation_method_json,required_components_json,
                    required_infrastructure_json,expected_artifacts_json,
                    definition_of_done_json,assigned_role,source_references_json,
                    review_notes_json,labels_json,item_digest)
                   VALUES(?,?,1,?,?,?,?,'',?,'[]','P1','[]','[]','[]','[]','[]','[]',
                          'developer','[]','[]','[]',?)""",
                (item_id, f"item-{item_id}", stable_id,
                 "task" if executable else "epic", executable, title, parent,
                 f"{item_id:064d}"))
            if status:
                self.storage.db.execute(
                    """INSERT INTO autonomous_backlog_item_states
                       (identity,item_id,sequence,status,actor,command_id,reason)
                       VALUES(?,?,1,?,'system','cmd','planned')""",
                    (f"state-{item_id}", item_id, status))

    def plan(self, **rest):
        from agent_factory.studio_backlog import from_mission

        return from_mission(self.storage, "cat-coins", **rest)

    def test_an_unknown_mission_is_refused_in_both_languages(self):
        from agent_factory.studio_backlog import BacklogRefused, from_mission

        with self.assertRaises(BacklogRefused) as caught:
            from_mission(self.storage, "no-such-game")
        self.assertIn("no such mission", caught.exception.text("en"))

    def test_a_mission_with_no_revision_yet_has_an_empty_plan(self):
        from agent_factory.studio_backlog import from_mission

        with self.storage.db:
            self.storage.db.execute("INSERT INTO projects(id,name,description) VALUES(2,'Друга гра','')")
            self.storage.db.execute(
                """INSERT INTO autonomous_missions
                   (id,identity,mission_key,project_id,name,mission_owner,phase,
                    disposition,configuration_json,configuration_digest)
                   VALUES(2,'mission-2','second-game',2,'Друга гра','miha','DRAFT',
                          'RUNNING','{}',?)""", ("d" * 64,))
        self.assertEqual(from_mission(self.storage, "second-game").stages, ())

    def test_the_engineering_statuses_become_four_a_person_knows(self):
        self.item(1, "AF-M-001", "Кіт стрибає", "DONE")
        self.item(2, "AF-M-002", "Монети рахуються", "RUNNING")
        self.item(3, "AF-M-003", "Рівень другий", "READY")
        self.item(4, "AF-M-004", "Збереження", "BLOCKED")
        states = {item.key: item.state for item in self.plan().items}
        self.assertEqual(states, {
            "AF-M-001": "done", "AF-M-002": "in_progress",
            "AF-M-003": "planned", "AF-M-004": "blocked",
        })

    def test_a_failed_attempt_reads_as_blocked_with_the_reason(self):
        self.item(1, "AF-M-001", "Кіт стрибає", "FAILED")
        item = self.plan().items[0]
        self.assertEqual(item.state, "blocked")
        self.assertIn("failed", item.record("en")["note"])

    def test_a_stale_task_is_planned_with_a_note_that_the_plan_moved(self):
        self.item(1, "AF-M-001", "Кіт стрибає", "STALE")
        item = self.plan().items[0]
        self.assertEqual(item.state, "planned")
        self.assertIn("plan changed", item.record("en")["note"])

    def test_an_item_with_no_state_yet_is_planned(self):
        self.item(1, "AF-M-001", "Кіт стрибає", None)
        self.assertEqual(self.plan().items[0].state, "planned")

    def test_an_epic_is_the_stage_and_not_a_task_inside_it(self):
        self.item(1, "AF-M-E1", "База гри", None, executable=0)
        self.item(2, "AF-M-001", "Кіт стрибає", "READY", parent="AF-M-E1")
        plan = self.plan()
        self.assertEqual(len(plan.items), 1)
        self.assertEqual(plan.stages[0].record("uk")["title"], "База гри")

    def test_a_task_with_no_epic_lands_in_a_named_group(self):
        self.item(1, "AF-M-001", "Кіт стрибає", "READY")
        self.assertEqual(self.plan().stages[0].record("en")["title"], "The rest of the work")

    def test_a_stage_is_playable_only_when_a_version_is_supplied(self):
        self.item(1, "AF-M-E1", "База гри", None, executable=0)
        self.item(2, "AF-M-001", "Кіт стрибає", "DONE", parent="AF-M-E1")
        self.assertEqual(self.plan().stages[0].boundary, "nothing_to_test")
        promoted = self.plan(playable={"AF-M-E1": "d" * 64})
        self.assertEqual(promoted.stages[0].boundary, "playable")
        self.assertEqual(promoted.record("en")["playable"], ["d" * 64])

    def test_the_rendered_plan_carries_no_internal_code(self):
        import json
        import re

        self.item(1, "AF-M-E1", "AF-M-E1 База гри", None, executable=0)
        self.item(2, "AF-M-001", "AF-M-001 Кіт стрибає", "RUNNING", parent="AF-M-E1")
        rendered = json.dumps(self.plan().record("uk"), ensure_ascii=False)
        self.assertIsNone(re.search(r"AF-[A-Z]-\d", rendered))
        self.assertIn("Кіт стрибає", rendered)
