import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_factory.autonomous_mission import (
    AutonomousMissionConfiguration,
    AutonomousMissionService,
    MissionPhase,
)
from agent_factory.backlog import BacklogProposal, ProposedItem
from agent_factory.backlog_revisions import (
    BacklogRevisionOrigin,
    BacklogRevisionService,
)
from agent_factory.mission_checkpoints import (
    ExecutionEpochOrigin,
    MissionCheckpointService,
    MissionCheckpointType,
    mission_epoch_branch,
    normalize_mission_git_segment,
)
from agent_factory.storage import SQLiteStorage
from agent_factory.worktrees import WorktreeError, WorktreeManager


def epoch_proposal() -> BacklogProposal:
    return BacklogProposal(
        source_path="memory://epoch-worktree-backlog.json",
        source_sha256="a" * 64,
        source_name="Epoch worktree backlog",
        schema_version=2,
        items=(
            ProposedItem(
                stable_id="T1",
                kind="task",
                title="Implement the epoch capability",
                description="Create an accepted commit on an isolated epoch branch.",
                acceptance_criteria=("The epoch branch preserves accepted history",),
                priority="P0",
                validation_method=("Run the deterministic Git tests",),
                required_components=("worktrees.py",),
                required_infrastructure=("Git",),
                expected_artifacts=("Epoch commit",),
                definition_of_done=("The commit is checkpointed",),
                assigned_role="Developer",
            ),
        ),
    )


class MissionEpochWorktreeManagerTests(unittest.TestCase):
    def setUp(self):
        self.git = shutil.which("git")
        if not self.git:
            self.skipTest("git is unavailable")
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve()
        self.repository = self.workspace / "repository"
        self.repository.mkdir()
        self.run_git("init")
        self.run_git("config", "user.name", "Agent Factory Test")
        self.run_git("config", "user.email", "agent-factory@example.test")
        self.run_git("config", "core.autocrlf", "false")
        (self.repository / "README.md").write_text("# Epoch\n", encoding="utf-8")
        self.run_git("add", "README.md")
        self.run_git("commit", "-m", "approved base")
        self.base_sha = self.run_git("rev-parse", "HEAD")
        self.main_branch = self.run_git("branch", "--show-current")

        self.storage = SQLiteStorage(self.workspace / "state.db")
        self.missions = AutonomousMissionService(self.storage)
        self.revisions = BacklogRevisionService(self.storage)
        self.checkpoints = MissionCheckpointService(self.storage)
        self.manager = WorktreeManager(
            self.storage,
            self.workspace,
            git_executable=self.git,
        )
        self.mission = self.missions.create(
            name="Epoch worktree mission",
            mission_owner="Founder",
            actor="Founder",
            command_id="create-epoch-worktree-mission",
            mission_key="AFM-EPOCH-WORKTREE",
            configuration=AutonomousMissionConfiguration(
                repository_path=str(self.repository)
            ),
        )
        self.mission = self.missions.transition_phase(
            self.mission.id,
            MissionPhase.SPECIFICATION_ANALYSIS,
            actor="Analyst",
            command_id="analyze-epoch-worktree",
            expected_version=self.mission.version,
            reason="Analyze the mission",
        )
        self.mission = self.missions.transition_phase(
            self.mission.id,
            MissionPhase.BACKLOG_GENERATION,
            actor="Planner",
            command_id="plan-epoch-worktree",
            expected_version=self.mission.version,
            reason="Generate the backlog",
        )
        self.revision = self.revisions.create_revision(
            mission_id=self.mission.id,
            proposal=epoch_proposal(),
            origin=BacklogRevisionOrigin.HUMAN,
            created_by="Founder",
            command_id="create-epoch-worktree-revision",
            rationale="Approve the Git topology test scope",
        )
        self.mission = self.missions.transition_phase(
            self.mission.id,
            MissionPhase.WAITING_FOR_BACKLOG_APPROVAL,
            actor="Reviewer",
            command_id="wait-epoch-worktree-approval",
            expected_version=self.mission.version,
            reason="Wait for approval",
        )
        self.mission = self.revisions.activate_revision(
            self.revision.id,
            actor="Founder",
            command_id="activate-epoch-worktree-revision",
            expected_mission_version=self.mission.version,
            reason="Approve the exact revision",
        )
        self.mission = self.missions.transition_phase(
            self.mission.id,
            MissionPhase.APPROVED,
            actor="Founder",
            command_id="approve-epoch-worktree-mission",
            expected_version=self.mission.version,
            reason="Permit local epoch execution",
        )

    def tearDown(self):
        if hasattr(self, "storage"):
            self.storage.close()
        self.temporary.cleanup()

    def run_git(self, *arguments: str, cwd: Path | None = None) -> str:
        result = subprocess.run(
            [self.git, "-C", str(cwd or self.repository), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=20,
        )
        if result.returncode:
            self.fail(result.stderr or result.stdout)
        return result.stdout.strip()

    def create_epoch_one(self):
        epoch = self.checkpoints.create_epoch(
            self.mission.id,
            expected_mission_version=self.mission.version,
            expected_backlog_revision_id=self.revision.id,
            expected_active_epoch_id=None,
            actor="Control Plane",
            command_id="create-managed-epoch-1",
            reason="Start at the approved repository base",
            epoch_branch=mission_epoch_branch(self.mission.mission_key, 1),
            temporal_workflow_id="managed-epoch-workflow-1",
            temporal_run_id="managed-epoch-run-1",
            base_git_commit_sha=self.base_sha,
        )
        self.mission = self.missions.get(self.mission.id)
        return epoch

    def record_checkpoint(self, epoch, worktree: Path):
        checkpoint = self.checkpoints.record_checkpoint(
            self.mission.id,
            expected_mission_version=self.mission.version,
            expected_backlog_revision_id=self.revision.id,
            expected_execution_epoch_id=epoch.id,
            actor="Control Plane",
            command_id="managed-epoch-checkpoint-1",
            reason="Preserve the accepted epoch-one commit",
            checkpoint_type=MissionCheckpointType.MANUAL,
            git_commit_sha=self.run_git("rev-parse", "HEAD", cwd=worktree),
            git_branch=epoch.epoch_branch,
            git_worktree_path=str(worktree),
            completed_work_items=(),
            pending_work_items=("T1",),
            validation_state={"ok": True},
        )
        self.mission = self.missions.get(self.mission.id)
        return checkpoint

    def test_two_epoch_worktrees_coexist_from_exact_distinct_bases(self):
        epoch_one = self.create_epoch_one()
        first = self.manager.provision_epoch(
            execution_epoch_id=epoch_one.id,
            repository=self.repository,
        )
        first_path = Path(first.path)
        self.assertEqual(first.status, "READY")
        self.assertEqual(self.run_git("rev-parse", "HEAD", cwd=first_path), self.base_sha)
        self.assertEqual(
            self.run_git("branch", "--show-current", cwd=first_path),
            epoch_one.epoch_branch,
        )
        (first_path / "accepted.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.run_git("add", "accepted.py", cwd=first_path)
        self.run_git("commit", "-m", "accept T1", cwd=first_path)
        checkpoint = self.record_checkpoint(epoch_one, first_path)

        epoch_two = self.checkpoints.create_epoch(
            self.mission.id,
            expected_mission_version=self.mission.version,
            expected_backlog_revision_id=self.revision.id,
            expected_active_epoch_id=epoch_one.id,
            actor="Control Plane",
            command_id="create-managed-epoch-2",
            reason="Restart from the accepted checkpoint",
            epoch_branch=mission_epoch_branch(self.mission.mission_key, 2),
            temporal_workflow_id="managed-epoch-workflow-2",
            temporal_run_id="managed-epoch-run-2",
            origin=ExecutionEpochOrigin.CHECKPOINT_RESTART,
            base_checkpoint_id=checkpoint.id,
        )
        second = self.manager.provision_epoch(
            execution_epoch_id=epoch_two.id,
            repository=self.repository,
        )
        second_path = Path(second.path)
        self.assertNotEqual(first.path, second.path)
        self.assertNotEqual(first.branch, second.branch)
        self.assertEqual(
            self.run_git("rev-parse", "HEAD", cwd=second_path),
            checkpoint.git_commit_sha,
        )
        self.assertEqual(
            self.run_git("rev-parse", f"refs/heads/{epoch_one.epoch_branch}"),
            checkpoint.git_commit_sha,
        )
        self.assertEqual(self.run_git("rev-parse", self.main_branch), self.base_sha)
        report = self.manager.reconcile_epochs(self.repository)
        self.assertEqual(report.ready_ids, (first.id, second.id))
        self.assertEqual(report.conflict_ids, ())
        standard_report = self.manager.reconcile(self.repository)
        self.assertEqual(standard_report.orphaned_paths, ())
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_epoch_worktrees"
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            self.storage.db.execute(
                "SELECT status FROM autonomous_epoch_worktree_events "
                "WHERE epoch_worktree_id=? ORDER BY sequence LIMIT 1",
                (second.id,),
            ).fetchone()[0],
            "RESERVED",
        )
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE autonomous_epoch_worktrees SET epoch_branch='rewrite' "
                "WHERE id=?",
                (first.id,),
            )
        self.storage.db.rollback()
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE autonomous_epoch_worktree_events SET reason='rewrite' "
                "WHERE epoch_worktree_id=?",
                (first.id,),
            )
        self.storage.db.rollback()
        latest = self.storage.db.execute(
            """SELECT sequence,observation_json,observation_digest
                 FROM autonomous_epoch_worktree_events
                WHERE epoch_worktree_id=? ORDER BY sequence DESC LIMIT 1""",
            (first.id,),
        ).fetchone()
        with self.assertRaisesRegex(sqlite3.DatabaseError, "invalid.*transition"):
            self.storage.db.execute(
                """INSERT INTO autonomous_epoch_worktree_events(
                       identity,epoch_worktree_id,sequence,status,
                       observation_json,observation_digest,reason,created_at
                   ) VALUES(?,?,?,'PROVISIONING',?,?,?,CURRENT_TIMESTAMP)""",
                (
                    "invalid-ready-to-provisioning",
                    first.id,
                    int(latest["sequence"]) + 1,
                    latest["observation_json"],
                    latest["observation_digest"],
                    "Invalid transition test",
                ),
            )
        self.storage.db.rollback()

    def test_reservation_is_committed_before_git_mutation(self):
        epoch = self.create_epoch_one()
        original_git = self.manager._git
        observed_reservation = []

        def fail_after_reservation(repository, *arguments, **kwargs):
            if arguments[:2] == ("worktree", "add"):
                observed_reservation.append(
                    self.storage.db.execute(
                        "SELECT COUNT(*) FROM autonomous_epoch_worktrees "
                        "WHERE execution_epoch_id=?",
                        (epoch.id,),
                    ).fetchone()[0]
                )
                raise WorktreeError("simulated kill point")
            return original_git(repository, *arguments, **kwargs)

        self.manager._git = fail_after_reservation
        with self.assertRaisesRegex(WorktreeError, "reserved epoch worktree"):
            self.manager.provision_epoch(
                execution_epoch_id=epoch.id,
                repository=self.repository,
            )
        self.assertEqual(observed_reservation, [1])
        authority = self.manager.epoch_worktree(epoch.id)
        self.assertEqual(authority.status, "CONFLICT")
        statuses = [
            row[0]
            for row in self.storage.db.execute(
                "SELECT status FROM autonomous_epoch_worktree_events "
                "WHERE epoch_worktree_id=? ORDER BY sequence",
                (authority.id,),
            )
        ]
        self.assertEqual(statuses[:3], ["RESERVED", "MISSING", "PROVISIONING"])

    def test_divergent_branch_and_dirty_worktree_fail_closed(self):
        epoch = self.create_epoch_one()
        tree = self.run_git("rev-parse", "HEAD^{tree}")
        divergent = self.run_git(
            "commit-tree", tree, "-p", self.base_sha, "-m", "unapproved divergence"
        )
        self.run_git("branch", epoch.epoch_branch, divergent)
        with self.assertRaisesRegex(WorktreeError, "conflicts"):
            self.manager.provision_epoch(
                execution_epoch_id=epoch.id,
                repository=self.repository,
            )
        authority = self.manager.epoch_worktree(epoch.id)
        self.assertEqual(authority.status, "CONFLICT")
        self.assertEqual(
            self.run_git("rev-parse", f"refs/heads/{epoch.epoch_branch}"), divergent
        )
        self.assertEqual(self.run_git("rev-parse", self.main_branch), self.base_sha)
        self.assertFalse(Path(authority.path).exists())

    def test_dirty_and_missing_states_reconcile_without_destructive_adoption(self):
        epoch = self.create_epoch_one()
        authority = self.manager.provision_epoch(
            execution_epoch_id=epoch.id,
            repository=self.repository,
        )
        path = Path(authority.path)
        dirty_file = path / "uncommitted.txt"
        dirty_file.write_text("keep me\n", encoding="utf-8")
        with self.assertRaisesRegex(WorktreeError, "dirty"):
            self.manager.provision_epoch(
                execution_epoch_id=epoch.id,
                repository=self.repository,
            )
        dirty = self.manager.reconcile_epoch(epoch.id)
        self.assertEqual(dirty.status, "DIRTY")
        self.assertTrue(dirty_file.is_file())

        dirty_file.unlink()
        self.run_git("worktree", "remove", str(path))
        missing = self.manager.reconcile_epoch(epoch.id)
        self.assertEqual(missing.status, "MISSING")
        self.assertEqual(
            self.run_git("rev-parse", f"refs/heads/{epoch.epoch_branch}"), self.base_sha
        )
        recovered = self.manager.provision_epoch(
            execution_epoch_id=epoch.id,
            repository=self.repository,
        )
        self.assertEqual(recovered.id, authority.id)
        self.assertEqual(recovered.status, "READY")
        tracked = Path(recovered.path) / "README.md"
        tracked.write_text("# changed but unaccepted\n", encoding="utf-8")
        modified = self.manager.reconcile_epoch(epoch.id)
        self.assertEqual(modified.status, "DIRTY")
        self.assertIn("README.md", modified.observation["content_mismatches"])
        self.run_git("add", "README.md", cwd=Path(recovered.path))
        staged = self.manager.reconcile_epoch(epoch.id)
        self.assertEqual(staged.status, "DIRTY")
        self.assertIn("README.md", staged.observation["staged_entries"])

    def test_occupied_deterministic_path_is_preserved_as_a_conflict(self):
        epoch = self.create_epoch_one()
        segment = normalize_mission_git_segment(self.mission.mission_key)
        path = self.manager._epoch_path(segment, epoch.epoch_number)
        path.parent.mkdir(parents=True)
        path.write_text("operator-owned collision\n", encoding="utf-8")
        with self.assertRaisesRegex(WorktreeError, "conflicts"):
            self.manager.provision_epoch(
                execution_epoch_id=epoch.id,
                repository=self.repository,
            )
        authority = self.manager.epoch_worktree(epoch.id)
        self.assertEqual(authority.status, "CONFLICT")
        self.assertEqual(
            path.read_text(encoding="utf-8"), "operator-owned collision\n"
        )
        self.assertFalse(
            self.storage.db.execute(
                "SELECT 1 FROM autonomous_epoch_worktree_events "
                "WHERE epoch_worktree_id=? AND status='PROVISIONING'",
                (authority.id,),
            ).fetchone()
        )

    def test_branch_policy_normalizes_collisions_and_contains_paths(self):
        left = normalize_mission_git_segment("../../unsafe mission")
        right = normalize_mission_git_segment("..\\..\\unsafe mission")
        self.assertNotEqual(left, right)
        for segment in (left, right):
            self.assertNotIn("/", segment)
            self.assertNotIn("\\", segment)
            self.assertNotIn("..", segment)
            path = self.manager._epoch_path(segment, 1)
            self.assertTrue(self.manager._within(path, self.manager.epoch_worktree_root))
        self.assertEqual(
            mission_epoch_branch("AFM-EPOCH-WORKTREE", 2),
            "autonomous/AFM-EPOCH-WORKTREE/epoch-2",
        )
        with self.assertRaisesRegex(ValueError, "inside the workspace"):
            WorktreeManager(
                self.storage,
                self.workspace,
                worktree_root=self.workspace.parent / "escaped-worktrees",
                git_executable=self.git,
            )

    def test_nonpolicy_persisted_branch_is_rejected_before_reservation(self):
        epoch = self.checkpoints.create_epoch(
            self.mission.id,
            expected_mission_version=self.mission.version,
            expected_backlog_revision_id=self.revision.id,
            expected_active_epoch_id=None,
            actor="Control Plane",
            command_id="create-traversal-epoch",
            reason="Exercise fail-closed branch validation",
            epoch_branch="autonomous/../../epoch-1",
            temporal_workflow_id="traversal-workflow",
            temporal_run_id="traversal-run",
            base_git_commit_sha=self.base_sha,
        )
        with self.assertRaisesRegex(WorktreeError, "naming policy"):
            self.manager.provision_epoch(
                execution_epoch_id=epoch.id,
                repository=self.repository,
            )
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_epoch_worktrees"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(self.run_git("rev-parse", self.main_branch), self.base_sha)


if __name__ == "__main__":
    unittest.main()
