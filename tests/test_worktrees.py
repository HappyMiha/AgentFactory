import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_factory.models import WorkItem
from agent_factory.local_recovery import LocalRecoveryService
from agent_factory.storage import SQLiteStorage
from agent_factory.worktrees import WorktreeError, WorktreeManager


NOW = datetime(2026, 8, 11, 20, 0, tzinfo=timezone.utc)


class WorktreeManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve()
        self.repository = self.workspace / "repository"
        self.repository.mkdir()
        self.git = shutil.which("git")
        if not self.git:
            self.skipTest("git is unavailable")
        self.run_git("init")
        self.run_git("config", "user.email", "agent-factory@example.invalid")
        self.run_git("config", "user.name", "Agent Factory Tests")
        (self.repository / "README.md").write_text("base\n", encoding="utf-8")
        self.run_git("add", "README.md")
        self.run_git("commit", "-m", "base")
        self.base_sha = self.run_git("rev-parse", "HEAD").stdout.strip().casefold()
        self.storage = SQLiteStorage(
            self.workspace / ".agent-factory" / "state.db"
        )
        self.project_id = self.storage.create_project("Worktrees", "AF-048")
        self.manager = WorktreeManager(
            self.storage,
            self.workspace,
            retention_seconds=1,
            git_executable=self.git,
        )
        self.counter = 0

    def tearDown(self):
        if hasattr(self, "storage"):
            self.storage.close()
        self.temporary.cleanup()

    def run_git(self, *args: str, cwd: Path | None = None):
        completed = subprocess.run(
            [self.git, "-C", str(cwd or self.repository), *args],
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=20,
        )
        if completed.returncode:
            self.fail(completed.stderr)
        return completed

    def claim(self):
        self.counter += 1
        task_id = self.storage.create_task(
            WorkItem(
                f"Task {self.counter}",
                "Isolated change",
                self.project_id,
            )
        )
        return self.storage.claim_runnable_task(
            task_id,
            f"worker-{self.counter}",
            "codex",
            conflict_domains=[f"path:task-{self.counter}"],
        )

    def provision(self, claim=None):
        claim = claim or self.claim()
        return claim, self.manager.provision(
            assignment_id=claim.assignment_id,
            fencing_token=claim.fencing_token,
            repository=self.repository,
            base_sha=self.base_sha,
        )

    def test_provision_is_deterministic_isolated_durable_and_idempotent(self):
        claim, worktree = self.provision()
        replay = self.manager.provision(
            assignment_id=claim.assignment_id,
            fencing_token=claim.fencing_token,
            repository=self.repository,
            base_sha=self.base_sha,
        )

        self.assertEqual(replay.id, worktree.id)
        self.assertEqual(worktree.status, "ready")
        self.assertEqual(worktree.task_id, claim.task_id)
        self.assertEqual(worktree.lease_id, claim.lease_id)
        self.assertEqual(worktree.fencing_token, claim.fencing_token)
        self.assertEqual(worktree.owner, claim.worker)
        self.assertEqual(
            worktree.branch,
            f"agent-factory/task-{claim.task_id}/lease-{claim.fencing_token}",
        )
        path = Path(worktree.path)
        self.assertTrue(path.is_dir())
        self.assertEqual(self.run_git("rev-parse", "HEAD", cwd=path).stdout.strip(), self.base_sha)
        self.assertEqual(
            self.run_git("branch", "--show-current", cwd=path).stdout.strip(),
            worktree.branch,
        )
        self.assertEqual(
            self.manager.assert_owned(
                worktree.id, claim.assignment_id, claim.fencing_token
            ),
            path,
        )

    def test_concurrent_tasks_never_share_worktree_or_ownership(self):
        first_claim, first = self.provision()
        second_claim, second = self.provision()
        self.assertNotEqual(first.path, second.path)
        self.assertNotEqual(first.branch, second.branch)
        self.assertTrue(Path(first.path).is_dir())
        self.assertTrue(Path(second.path).is_dir())
        with self.assertRaises(PermissionError):
            self.manager.assert_owned(
                first.id,
                second_claim.assignment_id,
                second_claim.fencing_token,
            )
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(DISTINCT path) FROM worktrees WHERE status='ready'"
            ).fetchone()[0],
            2,
        )
        self.assertNotEqual(first_claim.assignment_id, second_claim.assignment_id)

    def test_reconcile_finds_dirty_missing_and_orphaned_worktrees(self):
        _, dirty = self.provision()
        _, missing = self.provision()
        (Path(dirty.path) / "change.py").write_text("change\n", encoding="utf-8")
        self.run_git(
            "worktree", "remove", "--force", missing.path, cwd=self.repository
        )
        orphan = self.manager.worktree_root / "manual-orphan"
        self.run_git(
            "worktree",
            "add",
            "-b",
            "manual/orphan",
            str(orphan),
            self.base_sha,
            cwd=self.repository,
        )

        orphan_report = LocalRecoveryService(
            self.storage, process_alive=lambda pid: True
        ).detect_orphans(repository=self.repository, worktrees=self.manager)
        report = orphan_report.worktree_reconciliation
        self.assertEqual(orphan_report.provider_process_ids, ())
        self.assertEqual(orphan_report.hermes_session_ids, ())
        self.assertIn(str(orphan), orphan_report.worktree_paths)
        self.assertIn(dirty.id, report.dirty_ids)
        self.assertIn(missing.id, report.missing_ids)
        self.assertIn(str(orphan), report.orphaned_paths)
        self.assertEqual(self.manager.get(dirty.id).status, "dirty")
        self.assertEqual(self.manager.get(missing.id).status, "missing")
        self.assertTrue(orphan.is_dir(), "reconciliation must be non-destructive")

    def test_cleanup_requires_terminal_assignment_and_elapsed_retention(self):
        claim, worktree = self.provision()
        with self.assertRaisesRegex(PermissionError, "terminal"):
            self.manager.retain(worktree.id, now=NOW)
        self.storage.release_task_lease(
            claim.assignment_id,
            claim.fencing_token,
            outcome="succeeded",
        )
        retained = self.manager.retain(worktree.id, now=NOW)
        self.assertEqual(retained.status, "retained")
        with self.assertRaisesRegex(PermissionError, "has not elapsed"):
            self.manager.cleanup(worktree.id, now=NOW)
        self.assertTrue(Path(worktree.path).is_dir())

        cleaned = self.manager.cleanup(
            worktree.id, now=NOW + timedelta(seconds=2)
        )
        self.assertEqual(cleaned.status, "cleaned")
        self.assertFalse(Path(worktree.path).exists())
        self.assertEqual(
            self.run_git(
                "show-ref", "--verify", f"refs/heads/{worktree.branch}"
            ).returncode,
            0,
            "cleanup preserves branch and commit history",
        )

    def test_invalid_base_and_conflicting_replay_fail_closed(self):
        claim = self.claim()
        with self.assertRaisesRegex(ValueError, "full lowercase"):
            self.manager.provision(
                assignment_id=claim.assignment_id,
                fencing_token=claim.fencing_token,
                repository=self.repository,
                base_sha="main",
            )
        worktree = self.manager.provision(
            assignment_id=claim.assignment_id,
            fencing_token=claim.fencing_token,
            repository=self.repository,
            base_sha=self.base_sha,
        )
        self.run_git("checkout", "--detach", cwd=Path(worktree.path))
        with self.assertRaisesRegex(WorktreeError, "branch"):
            self.manager.provision(
                assignment_id=claim.assignment_id,
                fencing_token=claim.fencing_token,
                repository=self.repository,
                base_sha=self.base_sha,
            )
        report = self.manager.reconcile(self.repository)
        self.assertIn(f"worktree:{worktree.id}:branch-mismatch", report.conflicts)
        with self.assertRaisesRegex(PermissionError, "branch"):
            self.manager.assert_owned(
                worktree.id, claim.assignment_id, claim.fencing_token
            )

    def test_startup_reconciliation_can_resume_pre_mutation_provisioning(self):
        claim = self.claim()
        branch = (
            f"agent-factory/task-{claim.task_id}/lease-{claim.fencing_token}"
        )
        path = self.manager.worktree_root / (
            f"task-{claim.task_id}-lease-{claim.fencing_token}"
        )
        worktree_id = self.storage.create_managed_worktree(
            assignment_id=claim.assignment_id,
            fencing_token=claim.fencing_token,
            repository=str(self.repository),
            base_sha=self.base_sha,
            branch=branch,
            path=str(path),
        )
        report = self.manager.reconcile(self.repository)
        self.assertIn(worktree_id, report.missing_ids)
        self.assertEqual(self.manager.get(worktree_id).status, "missing")

        recovered = self.manager.provision(
            assignment_id=claim.assignment_id,
            fencing_token=claim.fencing_token,
            repository=self.repository,
            base_sha=self.base_sha,
        )
        self.assertEqual(recovered.id, worktree_id)
        self.assertEqual(recovered.status, "ready")
        self.assertTrue(path.is_dir())


if __name__ == "__main__":
    unittest.main()
