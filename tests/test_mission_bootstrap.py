import json
import sqlite3
import unittest

from agent_factory.mission_bootstrap import (
    MANIFEST_KINDS,
    RESOURCE_TABLES,
    MissionBootstrapService,
    MissionManifests,
)
from tests.test_durable_workflow import definition
from tests import test_blueprint as blueprint_tests


class MissionBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.fixture = blueprint_tests.BlueprintServiceTests(
            methodName="test_blueprint_validates_sections_and_complete_mission_trace"
        )
        self.fixture.setUp()
        self.storage = self.fixture.storage
        self.blueprint = self.fixture.create_blueprint()
        self.fixture.service.sign(
            self.blueprint.id, expected_version=self.blueprint.version,
            expected_digest=self.blueprint.blueprint_digest, decision="approved",
            signer="Founder", signer_role="mission_owner", note="Bootstrap approved",
        )
        self.fixture.service.authorize_execution(
            self.blueprint.id, expected_digest=self.blueprint.blueprint_digest
        )
        self.manifests = MissionManifests(
            agent={"agents": ["planner-a"]},
            role={"roles": ["planner@1.0.0"]},
            tool={"allow": ["read_file"]},
            policy={"permissions": ["read_project"], "mutation": "approval-required"},
            context={"intake_id": self.fixture.intake_id, "strategy": "authoritative-first"},
            budget={"max_tokens": 8000, "max_seconds": 300, "max_cost_usd": 5.0},
            environment={"runtime": "local", "network": "denied"},
        )

    def tearDown(self):
        self.fixture.tearDown()

    def bootstrap(self, service=None):
        return (service or MissionBootstrapService(self.storage)).bootstrap(
            blueprint_id=self.blueprint.id, workflow=definition(),
            workflow_version="1.0.0", manifests=self.manifests,
        )

    def test_repeated_exact_bootstrap_creates_one_mission_and_workflow_graph(self):
        first = self.bootstrap()
        second = self.bootstrap()
        self.assertEqual(first, second)
        self.assertEqual(self.storage.db.execute(
            "SELECT COUNT(*) FROM bootstrapped_missions"
        ).fetchone()[0], 1)
        self.assertEqual(self.storage.db.execute(
            "SELECT COUNT(*) FROM workflow_runs WHERE id=?", (first.workflow_run_id,)
        ).fetchone()[0], 1)
        stages = self.storage.db.execute(
            "SELECT stage_key,status FROM workflow_stages WHERE run_id=? ORDER BY id",
            (first.workflow_run_id,),
        ).fetchall()
        self.assertEqual([row["status"] for row in stages], ["pending", "pending", "pending"])
        self.assertEqual(self.storage.db.execute(
            "SELECT COUNT(*) FROM mission_bootstrap_attempts"
        ).fetchone()[0], 1)

    def test_exact_seven_manifests_and_initial_checkpoint_are_immutable(self):
        mission = self.bootstrap()
        rows = self.storage.db.execute(
            "SELECT * FROM mission_manifests WHERE mission_id=? ORDER BY manifest_kind",
            (mission.id,),
        ).fetchall()
        self.assertEqual({row["manifest_kind"] for row in rows}, set(MANIFEST_KINDS))
        for row in rows:
            self.assertEqual(
                json.loads(row["manifest_json"]), getattr(self.manifests, row["manifest_kind"])
            )
            self.assertEqual(len(row["manifest_digest"]), 64)
        checkpoint = self.storage.db.execute(
            "SELECT * FROM mission_initial_checkpoints WHERE mission_id=?", (mission.id,)
        ).fetchone()
        state = json.loads(checkpoint["state_json"])
        self.assertEqual(state["blueprint_digest"], self.blueprint.blueprint_digest)
        self.assertEqual(set(state["stage_states"].values()), {"pending"})
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE mission_manifests SET manifest_json='{}' WHERE id=?", (rows[0]["id"],)
            )

    def test_failed_bootstrap_rolls_back_partial_resources_and_retry_succeeds(self):
        before = {
            table: self.storage.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in RESOURCE_TABLES
        }

        def fail(phase):
            if phase == "manifests":
                raise RuntimeError("injected bootstrap failure")

        with self.assertRaisesRegex(RuntimeError, "injected bootstrap failure"):
            self.bootstrap(MissionBootstrapService(self.storage, fail))
        after = {
            table: self.storage.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in RESOURCE_TABLES
        }
        self.assertEqual(after, before)
        outcome = self.storage.db.execute(
            "SELECT * FROM mission_bootstrap_outcomes WHERE status='failed'"
        ).fetchone()
        compensation = json.loads(outcome["compensation_json"])
        self.assertTrue(compensation["verified"])
        self.assertEqual(compensation["expected_state"], compensation["restored_state"])
        mission = self.bootstrap()
        self.assertTrue(mission.id)
        self.assertEqual(self.storage.db.execute(
            "SELECT COUNT(*) FROM mission_bootstrap_attempts"
        ).fetchone()[0], 2)
        self.assertEqual(self.storage.db.execute(
            "SELECT COUNT(*) FROM mission_bootstrap_rollback_points"
        ).fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
