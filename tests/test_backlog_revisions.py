import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.application import AgentFactoryService
from agent_factory.autonomous_mission import AutonomousMissionService
from agent_factory.backlog import BacklogProposal, ProposedItem
from agent_factory.backlog_revisions import (
    BacklogImpactClassification,
    BacklogItemStatus,
    BacklogRevisionOrigin,
    BacklogRevisionService,
)
from agent_factory.storage import SQLiteStorage


def task(
    stable_id: str,
    *,
    priority: str = "P0",
    acceptance: str = "The behavior is accepted",
    dependencies: tuple[str, ...] = (),
) -> ProposedItem:
    return ProposedItem(
        stable_id=stable_id,
        kind="task",
        title=f"Task {stable_id}",
        description=f"Implement {stable_id}",
        dependencies=dependencies,
        priority=priority,
        acceptance_criteria=(acceptance,),
        validation_method=("Run deterministic tests",),
        required_components=(f"{stable_id.lower()}.py",),
        required_infrastructure=("SQLite",),
        expected_artifacts=("Implementation", "Validation evidence"),
        definition_of_done=("Tests pass",),
        assigned_role="Developer",
        labels=(f"priority:{priority.lower()}",),
    )


def proposal(*items: ProposedItem) -> BacklogProposal:
    return BacklogProposal(
        source_path="memory://mission-backlog.json",
        source_sha256="a" * 64,
        source_name="Mission specification",
        items=tuple(items),
        schema_version=2,
        extension_schema="agentfactory.rich-backlog/v1",
        planning_contract={"execution_rule": "Only tasks execute"},
    )


class BacklogRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary_directory.name)
        self.storage = SQLiteStorage(self.workspace / "state.db")
        self.missions = AutonomousMissionService(self.storage)
        self.revisions = BacklogRevisionService(self.storage)
        self.mission = self.missions.create(
            name="Revision mission",
            mission_owner="Founder",
            actor="Founder",
            command_id="create-mission",
            mission_key="AFM-REVISION",
        )

    def tearDown(self):
        self.storage.close()
        self.temporary_directory.cleanup()

    def _revision_one(self):
        backlog = proposal(
            task("T1"),
            task("T2", dependencies=("T1",)),
            task("T3"),
            task("T5"),
        )
        revision = self.revisions.create_revision(
            mission_id=self.mission.id,
            proposal=backlog,
            origin=BacklogRevisionOrigin.HUMAN,
            created_by="Founder",
            command_id="create-revision-1",
            rationale="Human-authored initial backlog",
        )
        self.mission = self.revisions.activate_revision(
            revision.id,
            actor="Founder",
            command_id="activate-revision-1",
            expected_mission_version=self.mission.version,
            reason="Apply the human-authored backlog",
        )
        return revision

    def _complete(self, stable_id: str, prefix: str):
        current = self.revisions.item(
            self.mission.active_backlog_revision_id, stable_id
        )
        running = self.revisions.record_item_state(
            mission_id=self.mission.id,
            stable_id=stable_id,
            target=BacklogItemStatus.RUNNING,
            actor="Developer",
            command_id=f"{prefix}-running",
            expected_sequence=current.sequence,
            reason="Begin implementation",
        )
        return self.revisions.record_item_state(
            mission_id=self.mission.id,
            stable_id=stable_id,
            target=BacklogItemStatus.DONE,
            actor="Integrator",
            command_id=f"{prefix}-done",
            expected_sequence=running.sequence,
            reason="Acceptance criteria satisfied",
            validation_result={"ok": True, "tests": 12},
            git_commit_sha="a" * 40,
            evidence=({"kind": "test", "digest": "evidence-1"},),
        )

    def test_revisions_are_immutable_idempotent_and_preserve_rich_items(self):
        revision = self._revision_one()
        replay = self.revisions.create_revision(
            mission_id=self.mission.id,
            proposal=proposal(
                task("T1"),
                task("T2", dependencies=("T1",)),
                task("T3"),
                task("T5"),
            ),
            origin=BacklogRevisionOrigin.HUMAN,
            created_by="Founder",
            command_id="create-revision-1",
            rationale="Human-authored initial backlog",
        )
        self.assertEqual(replay.id, revision.id)
        self.assertEqual(revision.items[0].assigned_role, "Developer")
        self.assertEqual(
            revision.items[0].validation_method, ("Run deterministic tests",)
        )
        self.assertEqual(
            {impact.classification for impact in self.revisions.impacts(revision.id)},
            {BacklogImpactClassification.NEW},
        )
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE autonomous_backlog_revisions SET rationale='rewrite' WHERE id=?",
                (revision.id,),
            )
        self.storage.db.rollback()

    def test_impact_projection_invalidates_only_affected_completed_work(self):
        first = self._revision_one()
        self._complete("T1", "t1")
        self._complete("T3", "t3")

        second = self.revisions.create_revision(
            mission_id=self.mission.id,
            proposal=proposal(
                task("T1", acceptance="The changed behavior is accepted"),
                task("T2", dependencies=("T1",)),
                task("T3", priority="P1"),
                task("T4"),
            ),
            origin=BacklogRevisionOrigin.HUMAN,
            created_by="Founder",
            command_id="create-revision-2",
            rationale="Change T1 and add T4",
            parent_revision_id=first.id,
        )
        impact = {
            item.stable_id: item.classification
            for item in self.revisions.impacts(second.id)
        }
        self.assertEqual(impact["T1"], BacklogImpactClassification.STALE)
        self.assertEqual(impact["T2"], BacklogImpactClassification.VALID)
        self.assertEqual(
            impact["T3"], BacklogImpactClassification.PARTIALLY_AFFECTED
        )
        self.assertEqual(impact["T4"], BacklogImpactClassification.NEW)
        self.assertEqual(impact["T5"], BacklogImpactClassification.REMOVED)

        self.mission = self.revisions.activate_revision(
            second.id,
            actor="Founder",
            command_id="activate-revision-2",
            expected_mission_version=self.mission.version,
            reason="Apply revised requirements",
        )
        active = {
            item.item.stable_id: item
            for item in self.revisions.active_items(self.mission.id)
        }
        self.assertEqual(active["T1"].status, BacklogItemStatus.STALE)
        self.assertEqual(active["T2"].status, BacklogItemStatus.BLOCKED)
        self.assertEqual(active["T3"].status, BacklogItemStatus.DONE)
        self.assertEqual(active["T4"].status, BacklogItemStatus.READY)
        self.assertNotIn("T5", active)
        self.assertEqual(
            self.revisions.item(first.id, "T1").status,
            BacklogItemStatus.DONE,
        )
        self.assertEqual(
            self.revisions.progress(self.mission.id),
            {
                "mission_id": self.mission.id,
                "active_revision_id": second.id,
                "active_revision_number": 2,
                "completed": 1,
                "total": 4,
                "percent": 25.0,
            },
        )

    def test_agent_material_revision_cannot_activate_without_approval(self):
        first = self._revision_one()
        agent_revision = self.revisions.create_revision(
            mission_id=self.mission.id,
            proposal=proposal(task("T1"), task("T6")),
            origin=BacklogRevisionOrigin.AGENT_MATERIAL,
            created_by="Backlog Planner",
            command_id="agent-revision",
            rationale="Agent proposes material scope",
            parent_revision_id=first.id,
        )
        with self.assertRaisesRegex(PermissionError, "human approval"):
            self.revisions.activate_revision(
                agent_revision.id,
                actor="Founder",
                command_id="activate-agent-revision",
                expected_mission_version=self.mission.version,
                reason="Not approved yet",
            )
        self.assertEqual(self.mission.active_backlog_revision_id, first.id)

    def test_standard_import_preserves_every_rich_execution_field(self):
        manifest = proposal(task("T1"))
        application = AgentFactoryService(self.storage, workspace=self.workspace)
        result = application.import_backlog(manifest, self.mission.project_id)
        imported = self.storage.get_task(result.created[0]["task_id"])
        self.assertEqual(imported.inputs["priority"], "P0")
        self.assertEqual(
            imported.inputs["validation_method"], ["Run deterministic tests"]
        )
        self.assertEqual(imported.inputs["required_components"], ["t1.py"])
        self.assertEqual(imported.inputs["required_infrastructure"], ["SQLite"])
        self.assertEqual(
            imported.inputs["expected_artifacts"],
            ["Implementation", "Validation evidence"],
        )
        self.assertEqual(imported.inputs["definition_of_done"], ["Tests pass"])
        self.assertEqual(imported.inputs["assigned_role"], "Developer")
        self.assertEqual(
            imported.expected_outputs,
            ["Implementation", "Validation evidence"],
        )


if __name__ == "__main__":
    unittest.main()
