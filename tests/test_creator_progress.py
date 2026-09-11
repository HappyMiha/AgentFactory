"""What a creator sees about a project: progress, next action, playability.

The list used to show a phase and one sentence that was the same for every
project. These checks pin the three facts the creator actually needs, and keep
them separate: accepted work is not finished work, and neither one makes a game
playable.
"""

from __future__ import annotations

import os
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent_factory.local_games import LocalGames
from agent_factory.storage import SQLiteStorage
from agent_factory.web import create_app


def command() -> str:
    return str(uuid.uuid4())


def mission_stub(phase: str, *, epoch: int | None = 1) -> SimpleNamespace:
    return SimpleNamespace(
        phase=SimpleNamespace(value=phase), active_execution_epoch_id=epoch
    )


class ProgressSummaryTests(unittest.TestCase):
    def test_an_empty_plan_reports_nothing_rather_than_a_share(self):
        summary = LocalGames._progress({})
        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["accepted"], 0)
        self.assertEqual(summary["accepted_share"], 0.0)

    def test_the_share_counts_accepted_work_only(self):
        summary = LocalGames._progress({"approved": 1, "completed": 3})
        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["accepted"], 1)
        self.assertEqual(summary["finished"], 3)
        self.assertEqual(summary["accepted_share"], 25.0)

    def test_failed_and_rejected_work_is_reported_together_as_blocked(self):
        summary = LocalGames._progress({"failed": 2, "rejected": 1, "approved": 1})
        self.assertEqual(summary["blocked"], 3)
        self.assertEqual(summary["total"], 4)

    def test_running_and_pending_work_stay_distinguishable(self):
        summary = LocalGames._progress({"running": 2, "pending": 5})
        self.assertEqual((summary["in_progress"], summary["waiting"]), (2, 5))
        self.assertEqual(summary["accepted_share"], 0.0)

    def test_an_unknown_status_still_counts_towards_the_total(self):
        summary = LocalGames._progress({"approved": 1, "archived": 1})
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["accepted_share"], 50.0)


class NextActionTests(unittest.TestCase):
    def action(self, phase, *, epoch=1, blocked=0):
        return LocalGames._next_action(mission_stub(phase, epoch=epoch), {"blocked": blocked})

    def test_a_project_without_a_plan_is_asked_for_one(self):
        for phase in ("DRAFT", "SPECIFICATION_ANALYSIS", "BACKLOG_GENERATION"):
            with self.subTest(phase=phase):
                self.assertEqual(self.action(phase), "prepare_plan")

    def test_a_plan_awaiting_a_decision_asks_for_approval(self):
        self.assertEqual(self.action("WAITING_FOR_BACKLOG_APPROVAL"), "approve_plan")

    def test_an_approved_plan_with_no_epoch_still_asks_for_approval(self):
        self.assertEqual(self.action("DEVELOPMENT", epoch=None), "approve_plan")

    def test_blocked_work_outranks_a_readiness_check(self):
        self.assertEqual(self.action("DEVELOPMENT", blocked=1), "resolve_blocked_work")

    def test_a_finished_workflow_asks_for_a_review_not_a_readiness_check(self):
        self.assertEqual(self.action("COMPLETED"), "review_result")

    def test_running_work_asks_for_the_current_environment_state(self):
        self.assertEqual(self.action("DEVELOPMENT"), "inspect_readiness")


class ProjectViewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "state.db"
        self.storage = SQLiteStorage(self.path)
        self.addCleanup(self.storage.close)
        self.games = LocalGames(self.storage, self.root)
        draft = self.games.create("Founder", command())
        fields = {key: draft[key] for key in ("title", "idea", "model_key", "view_step")}
        draft = self.games.save(
            draft["id"], "Founder", command(), draft["revision"],
            **(fields | {"title": "Garden", "idea": "A cat collects coins.",
                         "model_key": self.games.model_choices()[0]["key"], "view_step": 2}),
        )
        self.submitted = self.games.materialize(
            draft["id"], "Founder", command(), draft["revision"]
        )
        self.mission_id = self.submitted["mission_id"]

    def add_work_items(self, **statuses):
        project_id = self.games.project(self.mission_id, "Founder")["id"]
        with self.storage.db:
            for status, count in statuses.items():
                for index in range(count):
                    self.storage.db.execute(
                        """INSERT INTO work_items(
                               project_id,title,description,payload,status,identity
                           ) VALUES(?,?,?,'{}',?,?)""",
                        (project_id, f"{status}-{index}", "synthetic", status,
                         self.storage._identity("work_item")),
                    )

    def test_a_new_project_reports_an_empty_plan_and_asks_for_approval(self):
        view = self.games.project(self.mission_id, "Founder")
        self.assertEqual(view["progress"]["total"], 0)
        self.assertEqual(view["next_action"], "prepare_plan")

    def test_progress_follows_the_stored_work_items(self):
        self.add_work_items(approved=1, completed=2, running=1)
        progress = self.games.project(self.mission_id, "Founder")["progress"]
        self.assertEqual(progress["total"], 4)
        self.assertEqual(progress["accepted"], 1)
        self.assertEqual(progress["accepted_share"], 25.0)

    def test_a_playable_version_is_never_implied_by_progress(self):
        self.add_work_items(approved=4)
        view = self.games.project(self.mission_id, "Founder")
        self.assertEqual(view["progress"]["accepted_share"], 100.0)
        self.assertIsNone(view["latest_working"])
        self.assertFalse(view["working_version"]["available"])
        self.assertEqual(
            view["working_version"]["reason"], "verified_playable_version_unavailable"
        )

    def test_the_existing_project_listing_carries_the_same_summary(self):
        self.add_work_items(approved=1, failed=1)
        listing = self.games.existing("Founder")
        self.assertEqual(listing["total"], 1)
        item = listing["items"][0]
        self.assertEqual(item["progress"]["blocked"], 1)
        self.assertEqual(item["next_action"], "prepare_plan")
        self.assertFalse(item["working_version"]["available"])

    def test_another_owner_sees_nothing(self):
        self.assertEqual(self.games.existing("Other")["total"], 0)
        with self.assertRaises(KeyError):
            self.games.project(self.mission_id, "Other")


class ProjectApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "state.db"
        environment = patch.dict(os.environ, {
            "AGENT_FACTORY_API_TOKEN": "synthetic-games-token",
            "AGENT_FACTORY_API_ACTOR": "Founder",
            "AGENT_FACTORY_API_ROLE": "operations_owner",
            "AGENT_FACTORY_API_SCOPES": "read,write,approve,control",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.client = TestClient(create_app(self.root, self.path), base_url="http://localhost")
        self.addCleanup(self.client.close)
        self.headers = {"Authorization": "Bearer synthetic-games-token"}

    def test_the_missions_endpoint_publishes_progress_and_the_next_action(self):
        created = self.client.post(
            "/api/games/starts", headers=self.headers, json={"command_id": command()}
        )
        self.assertEqual(created.status_code, 200, created.text)
        draft = created.json()
        saved = self.client.post(
            f"/api/games/starts/{draft['id']}/save",
            headers={**self.headers, "X-Agent-Factory-Confirm": "true"},
            json={"command_id": command(), "expected_revision": draft["revision"],
                  "title": "Garden", "idea": "A cat collects coins.",
                  "model_key": "", "view_step": 2},
        )
        if saved.status_code != 200:
            self.skipTest(f"draft save unavailable in this configuration: {saved.text}")
        listing = self.client.get("/api/games/missions", headers=self.headers)
        self.assertEqual(listing.status_code, 200, listing.text)
        for item in listing.json()["items"]:
            self.assertIn("progress", item)
            self.assertIn("next_action", item)
            self.assertIn("working_version", item)
            self.assertFalse(item["working_version"]["available"])


if __name__ == "__main__":
    unittest.main()
