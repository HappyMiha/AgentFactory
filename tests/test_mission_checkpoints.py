import json
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent_factory.autonomous_mission import (
    AutonomousMissionConfiguration,
    AutonomousMissionService,
    MissionPhase,
    MissionVersionConflictError,
)
from agent_factory.backlog import BacklogProposal, ProposedItem
from agent_factory.backlog_revisions import (
    BacklogItemStatus,
    BacklogRevisionOrigin,
    BacklogRevisionService,
)
from agent_factory.mission_checkpoints import (
    CheckpointIntegrityError,
    ExecutionEpochOrigin,
    MissionCheckpointService,
    MissionCheckpointType,
)
from agent_factory.storage import SQLiteStorage


def run_git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def proposal() -> BacklogProposal:
    return BacklogProposal(
        source_path="memory://epoch-backlog.json",
        source_sha256="a" * 64,
        source_name="Epoch backlog",
        schema_version=2,
        items=(
            ProposedItem(
                stable_id="T1",
                kind="task",
                title="Deliver the first capability",
                description="Implement and validate the first capability.",
                acceptance_criteria=("The capability passes deterministic validation",),
                priority="P0",
                validation_method=("Run the deterministic suite",),
                required_components=("app.py",),
                required_infrastructure=("Python",),
                expected_artifacts=("Committed implementation",),
                definition_of_done=("Validation passes",),
                assigned_role="Developer",
            ),
        ),
    )


class MissionEpochAndCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary_directory.name)
        self.repository = self.workspace / "repository"
        self.repository.mkdir()
        run_git(self.repository, "init")
        run_git(self.repository, "config", "user.name", "Agent Factory Test")
        run_git(self.repository, "config", "user.email", "agent-factory@example.test")
        (self.repository / "README.md").write_text("# Mission\n", encoding="utf-8")
        run_git(self.repository, "add", "README.md")
        run_git(self.repository, "commit", "-m", "initial")
        self.epoch_one_branch = "autonomous/AFM-EPOCH/epoch-1"
        run_git(self.repository, "checkout", "-b", self.epoch_one_branch)
        self.base_commit = run_git(self.repository, "rev-parse", "HEAD")

        self.database = self.workspace / "state.db"
        self.storage = SQLiteStorage(self.database)
        self.missions = AutonomousMissionService(self.storage)
        self.revisions = BacklogRevisionService(self.storage)
        self.checkpoints = MissionCheckpointService(self.storage)
        self.mission = self.missions.create(
            name="Epoch mission",
            mission_owner="Founder",
            actor="Founder",
            command_id="create-epoch-mission",
            mission_key="AFM-EPOCH",
            configuration=AutonomousMissionConfiguration(
                repository_path=str(self.repository),
                default_model="qwen-coder",
                role_models={"reviewer": "qwen-coder"},
                local_provider_ids=("local-provider",),
            ),
        )
        self.mission = self.missions.transition_phase(
            self.mission.id,
            MissionPhase.SPECIFICATION_ANALYSIS,
            actor="Mission Analyst",
            command_id="epoch-analyze",
            expected_version=self.mission.version,
            reason="Analyze specification",
        )
        self.mission = self.missions.transition_phase(
            self.mission.id,
            MissionPhase.BACKLOG_GENERATION,
            actor="Backlog Planner",
            command_id="epoch-generate",
            expected_version=self.mission.version,
            reason="Generate backlog",
        )
        self.revision = self.revisions.create_revision(
            mission_id=self.mission.id,
            proposal=proposal(),
            origin=BacklogRevisionOrigin.HUMAN,
            created_by="Founder",
            command_id="epoch-revision",
            rationale="Approved implementation scope",
        )
        self.mission = self.missions.transition_phase(
            self.mission.id,
            MissionPhase.WAITING_FOR_BACKLOG_APPROVAL,
            actor="Backlog Reviewer",
            command_id="epoch-wait",
            expected_version=self.mission.version,
            reason="Proposal is ready",
        )
        self.mission = self.revisions.activate_revision(
            self.revision.id,
            actor="Founder",
            command_id="epoch-activate-revision",
            expected_mission_version=self.mission.version,
            reason="Approve exact backlog",
        )
        self.mission = self.missions.transition_phase(
            self.mission.id,
            MissionPhase.APPROVED,
            actor="Founder",
            command_id="epoch-approved",
            expected_version=self.mission.version,
            reason="Start autonomous mission",
        )

    def tearDown(self):
        self.storage.close()
        self.temporary_directory.cleanup()

    def create_epoch_one(self):
        epoch = self.checkpoints.create_epoch(
            self.mission.id,
            expected_mission_version=self.mission.version,
            expected_backlog_revision_id=self.revision.id,
            expected_active_epoch_id=None,
            actor="Control Plane",
            command_id="start-epoch-1",
            reason="Start approved execution",
            epoch_branch=self.epoch_one_branch,
            temporal_workflow_id="autonomous-AFM-EPOCH-e1",
            temporal_run_id="temporal-run-e1-1",
            temporal_chain_metadata={"task_queue": "agent-factory-autonomous"},
            workflow_build_id="worker-v1",
            base_git_commit_sha=self.base_commit,
        )
        self.mission = self.missions.get(self.mission.id)
        return epoch

    def checkpoint(
        self,
        epoch_id: int,
        *,
        command_id: str = "checkpoint-1",
        completed: tuple[str, ...] = (),
        pending: tuple[str, ...] = ("T1",),
        checkpoint_type: MissionCheckpointType = MissionCheckpointType.BACKLOG_APPROVED,
    ):
        checkpoint = self.checkpoints.record_checkpoint(
            self.mission.id,
            expected_mission_version=self.mission.version,
            expected_backlog_revision_id=self.revision.id,
            expected_execution_epoch_id=epoch_id,
            actor="Control Plane",
            command_id=command_id,
            reason="Record a durable safe boundary",
            checkpoint_type=checkpoint_type,
            git_commit_sha=run_git(self.repository, "rev-parse", "HEAD"),
            git_branch=self.epoch_one_branch,
            git_worktree_path=str(self.repository),
            completed_work_items=completed,
            pending_work_items=pending,
            artifacts=({"kind": "audit", "digest": "b" * 64},),
            memory_context=({"kind": "mission-memory", "digest": "c" * 64},),
            validation_state={"ok": True, "suite": "deterministic"},
        )
        self.mission = self.missions.get(self.mission.id)
        return checkpoint

    def accept_task(self):
        (self.repository / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        run_git(self.repository, "add", "app.py")
        run_git(self.repository, "commit", "-m", "deliver T1")
        commit = run_git(self.repository, "rev-parse", "HEAD")
        item = self.revisions.item(self.revision.id, "T1")
        running = self.revisions.record_item_state(
            mission_id=self.mission.id,
            stable_id="T1",
            target=BacklogItemStatus.RUNNING,
            actor="Developer",
            command_id="run-T1",
            expected_sequence=item.sequence,
            reason="Implement T1",
        )
        return self.revisions.record_item_state(
            mission_id=self.mission.id,
            stable_id="T1",
            target=BacklogItemStatus.DONE,
            actor="Integrator",
            command_id="accept-T1",
            expected_sequence=running.sequence,
            reason="T1 passed acceptance",
            validation_result={"ok": True},
            git_commit_sha=commit,
            evidence=({"kind": "test", "digest": "d" * 64},),
        )

    def test_epoch_one_is_exactly_once_optimistic_and_immutable(self):
        epoch = self.create_epoch_one()
        replay = self.checkpoints.create_epoch(
            self.mission.id,
            expected_mission_version=epoch.activation_mission_version - 1,
            expected_backlog_revision_id=self.revision.id,
            expected_active_epoch_id=None,
            actor="Control Plane",
            command_id="start-epoch-1",
            reason="Start approved execution",
            epoch_branch=self.epoch_one_branch,
            temporal_workflow_id="autonomous-AFM-EPOCH-e1",
            temporal_run_id="temporal-run-e1-1",
            temporal_chain_metadata={"task_queue": "agent-factory-autonomous"},
            workflow_build_id="worker-v1",
            base_git_commit_sha=self.base_commit,
        )
        self.assertEqual(replay.id, epoch.id)
        self.assertTrue(epoch.is_active)
        self.assertEqual(epoch.epoch_number, 1)
        self.assertEqual(epoch.temporal_runs[0].run_id, "temporal-run-e1-1")
        self.assertEqual(self.mission.active_execution_epoch_id, epoch.id)
        with self.assertRaises(MissionVersionConflictError):
            self.checkpoints.create_epoch(
                self.mission.id,
                expected_mission_version=epoch.activation_mission_version - 1,
                expected_backlog_revision_id=self.revision.id,
                expected_active_epoch_id=None,
                actor="Control Plane",
                command_id="duplicate-epoch-1",
                reason="Duplicate start",
                epoch_branch="autonomous/AFM-EPOCH/duplicate",
                temporal_workflow_id="duplicate-workflow",
                temporal_run_id="duplicate-run",
                base_git_commit_sha=self.base_commit,
            )
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE autonomous_mission_execution_epochs SET reason='rewrite' WHERE id=?",
                (epoch.id,),
            )

    def test_checkpoint_is_canonical_git_backed_and_immutable(self):
        epoch = self.create_epoch_one()
        checkpoint = self.checkpoint(epoch.id)
        verified = self.checkpoints.verify_checkpoint(checkpoint.id)
        self.assertEqual(verified.checkpoint_digest, checkpoint.checkpoint_digest)
        self.assertEqual(
            hashlib_sha256(checkpoint.document), checkpoint.checkpoint_digest
        )
        self.assertEqual(checkpoint.document["git"]["commit_sha"], self.base_commit)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE autonomous_mission_checkpoints SET reason='rewrite' WHERE id=?",
                (checkpoint.id,),
            )
        self.storage.db.rollback()
        (self.repository / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(CheckpointIntegrityError, "dirty worktree"):
            self.checkpoints.record_checkpoint(
                self.mission.id,
                expected_mission_version=self.mission.version,
                expected_backlog_revision_id=self.revision.id,
                expected_execution_epoch_id=epoch.id,
                actor="Control Plane",
                command_id="dirty-checkpoint",
                reason="Must fail closed",
                checkpoint_type=MissionCheckpointType.MANUAL,
                git_commit_sha=self.base_commit,
                git_branch=self.epoch_one_branch,
                git_worktree_path=str(self.repository),
                completed_work_items=(),
                pending_work_items=("T1",),
            )
        corrupted = dict(checkpoint.document)
        corrupted["reason"] = "physically corrupted"
        self.storage.db.execute("DROP TRIGGER autonomous_checkpoints_no_update")
        self.storage.db.execute(
            "UPDATE autonomous_mission_checkpoints SET document_json=? WHERE id=?",
            (
                json.dumps(
                    corrupted,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ),
                checkpoint.id,
            ),
        )
        self.storage.db.commit()
        with self.assertRaisesRegex(CheckpointIntegrityError, "digest"):
            self.checkpoints.verify_checkpoint(checkpoint.id, verify_git=False)

    def test_restart_supersedes_without_deleting_checkpoint_or_work_history(self):
        epoch_one = self.create_epoch_one()
        self.checkpoint(epoch_one.id)
        self.accept_task()
        accepted_checkpoint = self.checkpoint(
            epoch_one.id,
            command_id="checkpoint-accepted-T1",
            completed=("T1",),
            pending=(),
            checkpoint_type=MissionCheckpointType.WORK_ITEM_ACCEPTED,
        )
        epoch_two = self.checkpoints.create_epoch(
            self.mission.id,
            expected_mission_version=self.mission.version,
            expected_backlog_revision_id=self.revision.id,
            expected_active_epoch_id=epoch_one.id,
            actor="Founder",
            command_id="restart-epoch-2",
            reason="Restart from accepted T1",
            epoch_branch="autonomous/AFM-EPOCH/epoch-2",
            temporal_workflow_id="autonomous-AFM-EPOCH-e2",
            temporal_run_id="temporal-run-e2-1",
            origin=ExecutionEpochOrigin.CHECKPOINT_RESTART,
            base_checkpoint_id=accepted_checkpoint.id,
        )
        self.mission = self.missions.get(self.mission.id)
        epochs = self.checkpoints.list_epochs(self.mission.id)
        self.assertEqual([epoch.epoch_number for epoch in epochs], [1, 2])
        self.assertFalse(epochs[0].is_active)
        self.assertEqual(epochs[0].superseded_by_epoch_id, epoch_two.id)
        self.assertTrue(epochs[1].is_active)
        old_checkpoint = self.checkpoints.get_checkpoint(accepted_checkpoint.id)
        self.assertTrue(old_checkpoint.epoch_superseded)
        self.assertEqual(old_checkpoint.restart_base_for_epoch_ids, (epoch_two.id,))
        history = self.revisions.item_history(self.revision.id, "T1")
        accepted_state = next(
            state for state in history if state.status is BacklogItemStatus.DONE
        )
        self.assertEqual(accepted_state.execution_epoch_id, epoch_one.id)
        self.assertTrue(accepted_state.epoch_superseded)
        self.assertEqual(self.mission.current_checkpoint_id, accepted_checkpoint.id)

    def test_concurrent_restart_has_one_winner(self):
        epoch_one = self.create_epoch_one()
        checkpoint = self.checkpoint(epoch_one.id)
        expected_version = self.mission.version
        barrier = threading.Barrier(2)

        def attempt(index: int):
            storage = SQLiteStorage(self.database)
            try:
                service = MissionCheckpointService(storage)
                barrier.wait(timeout=10)
                epoch = service.create_epoch(
                    self.mission.id,
                    expected_mission_version=expected_version,
                    expected_backlog_revision_id=self.revision.id,
                    expected_active_epoch_id=epoch_one.id,
                    actor=f"operator-{index}",
                    command_id=f"concurrent-restart-{index}",
                    reason=f"Concurrent restart {index}",
                    epoch_branch=f"autonomous/AFM-EPOCH/concurrent-{index}",
                    temporal_workflow_id=f"concurrent-workflow-{index}",
                    temporal_run_id=f"concurrent-run-{index}",
                    origin=ExecutionEpochOrigin.CHECKPOINT_RESTART,
                    base_checkpoint_id=checkpoint.id,
                )
                return ("won", epoch.id)
            except MissionVersionConflictError:
                return ("conflict", None)
            finally:
                storage.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, (1, 2)))
        self.assertEqual(sorted(result[0] for result in results), ["conflict", "won"])
        self.assertEqual(len(self.checkpoints.list_epochs(self.mission.id)), 2)


def hashlib_sha256(value) -> str:
    import hashlib

    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


if __name__ == "__main__":
    unittest.main()
