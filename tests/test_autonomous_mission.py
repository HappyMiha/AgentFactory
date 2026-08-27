import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.autonomous_mission import (
    AutonomousMissionConfiguration,
    AutonomousMissionService,
    MissionCommandConflictError,
    MissionDisposition,
    MissionPhase,
    MissionVersionConflictError,
)
from agent_factory.storage import SQLiteStorage


class AutonomousMissionDomainTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(
            Path(self.temporary_directory.name) / "autonomous.db"
        )
        self.service = AutonomousMissionService(self.storage)

    def tearDown(self):
        self.storage.close()
        self.temporary_directory.cleanup()

    def create_mission(self):
        return self.service.create(
            name="Build a local application",
            mission_owner="Founder",
            actor="Founder",
            command_id="create-AFM-001",
            mission_key="AFM-001",
            initial_specification="Build and validate the application.",
            specification_metadata={"source": "paste", "media_type": "text/plain"},
            configuration=AutonomousMissionConfiguration(
                default_model="qwen-coder",
                role_models={"architect": "qwen-coder"},
                local_provider_ids=("ollama-local",),
            ),
        )

    def test_create_mission_creates_draft_project_without_work_items(self):
        mission = self.create_mission()

        self.assertEqual(mission.mission_key, "AFM-001")
        self.assertEqual(mission.phase, MissionPhase.DRAFT)
        self.assertEqual(mission.disposition, MissionDisposition.RUNNING)
        self.assertEqual(mission.version, 1)
        self.assertTrue(mission.scheduling_allowed)
        self.assertEqual(mission.configuration.default_model, "qwen-coder")
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM projects WHERE id=?", (mission.project_id,)
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM work_items WHERE project_id=?",
                (mission.project_id,),
            ).fetchone()[0],
            0,
        )
        event = self.storage.db.execute(
            """SELECT payload FROM events
               WHERE event_type='autonomous_mission.created'"""
        ).fetchone()
        payload = json.loads(event["payload"])
        self.assertEqual(payload["actor"], "Founder")
        self.assertEqual(payload["command_id"], "create-AFM-001")
        self.assertEqual(payload["resulting_phase"], "DRAFT")

    def test_create_and_transitions_are_idempotent_and_optimistic(self):
        mission = self.create_mission()
        replay = self.create_mission()
        self.assertEqual(replay.id, mission.id)
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_missions"
            ).fetchone()[0],
            1,
        )

        analyzed = self.service.transition_phase(
            mission.id,
            MissionPhase.SPECIFICATION_ANALYSIS,
            actor="planner",
            command_id="analyze-AFM-001",
            expected_version=1,
            reason="Begin specification analysis",
        )
        self.assertEqual(analyzed.version, 2)
        self.assertEqual(analyzed.phase, MissionPhase.SPECIFICATION_ANALYSIS)
        transition_replay = self.service.transition_phase(
            mission.id,
            MissionPhase.SPECIFICATION_ANALYSIS,
            actor="planner",
            command_id="analyze-AFM-001",
            expected_version=1,
            reason="Begin specification analysis",
        )
        self.assertEqual(transition_replay.version, 2)

        with self.assertRaises(MissionVersionConflictError):
            self.service.transition_phase(
                mission.id,
                MissionPhase.BACKLOG_GENERATION,
                actor="planner",
                command_id="stale-AFM-001",
                expected_version=1,
                reason="Stale caller",
            )
        with self.assertRaises(MissionCommandConflictError):
            self.service.transition_phase(
                mission.id,
                MissionPhase.BACKLOG_GENERATION,
                actor="different-planner",
                command_id="analyze-AFM-001",
                expected_version=2,
                reason="Reuse a bound command",
            )

    def test_pause_stop_and_resume_preserve_logical_phase(self):
        mission = self.create_mission()
        mission = self.service.transition_phase(
            mission.id,
            MissionPhase.SPECIFICATION_ANALYSIS,
            actor="planner",
            command_id="phase-1",
            expected_version=mission.version,
            reason="Analyze",
        )
        paused = self.service.transition_disposition(
            mission.id,
            MissionDisposition.PAUSED,
            actor="Founder",
            command_id="pause-1",
            expected_version=mission.version,
            reason="Inspect progress",
        )
        self.assertEqual(paused.phase, MissionPhase.SPECIFICATION_ANALYSIS)
        self.assertFalse(paused.scheduling_allowed)
        with self.assertRaisesRegex(ValueError, "execution is fenced"):
            self.service.transition_phase(
                mission.id,
                MissionPhase.BACKLOG_GENERATION,
                actor="planner",
                command_id="advance-paused",
                expected_version=paused.version,
                reason="Must remain fenced",
            )
        stopped = self.service.transition_disposition(
            mission.id,
            MissionDisposition.STOPPED,
            actor="Founder",
            command_id="stop-1",
            expected_version=paused.version,
            reason="Release execution resources",
        )
        self.assertEqual(stopped.phase, MissionPhase.SPECIFICATION_ANALYSIS)
        resumed = self.service.transition_disposition(
            mission.id,
            MissionDisposition.RUNNING,
            actor="Founder",
            command_id="continue-1",
            expected_version=stopped.version,
            reason="Continue from the durable phase",
        )
        self.assertEqual(resumed.phase, MissionPhase.SPECIFICATION_ANALYSIS)
        self.assertTrue(resumed.scheduling_allowed)

    def test_invalid_transitions_are_rejected_in_service_and_database(self):
        mission = self.create_mission()
        with self.assertRaisesRegex(ValueError, "Invalid autonomous_mission_phase"):
            self.service.transition_phase(
                mission.id,
                MissionPhase.DEVELOPMENT,
                actor="planner",
                command_id="invalid-phase",
                expected_version=mission.version,
                reason="Skip approval",
            )
        with self.assertRaisesRegex(sqlite3.DatabaseError, "state evidence"):
            self.storage.db.execute(
                """UPDATE autonomous_missions
                   SET phase='SPECIFICATION_ANALYSIS',version=version+1 WHERE id=?""",
                (mission.id,),
            )
        self.storage.db.rollback()

    def test_historical_state_versions_are_available_and_immutable(self):
        mission = self.create_mission()
        current = self.service.transition_phase(
            mission.id,
            MissionPhase.SPECIFICATION_ANALYSIS,
            actor="planner",
            command_id="history-1",
            expected_version=mission.version,
            reason="Analyze",
        )
        original = self.service.get(mission.id, version=1)
        self.assertEqual(original.phase, MissionPhase.DRAFT)
        self.assertEqual(current.phase, MissionPhase.SPECIFICATION_ANALYSIS)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                """UPDATE autonomous_mission_state_versions
                   SET reason='rewritten' WHERE mission_id=? AND version=1""",
                (mission.id,),
            )

    def test_autonomous_configuration_rejects_budget_authorization_limits(self):
        with self.assertRaisesRegex(ValueError, "observational"):
            AutonomousMissionConfiguration(token_budget_enforced=True)
        with self.assertRaisesRegex(ValueError, "at least one"):
            AutonomousMissionConfiguration(max_concurrent_local_llm=0)


if __name__ == "__main__":
    unittest.main()
