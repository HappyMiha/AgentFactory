import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_factory.codex_worker import CODEX_EXEC_ARGS, CodexCLIProcessDriver
from agent_factory.context_packages import ContextPackageBuilder
from agent_factory.live_stages import LiveStageExecution
from agent_factory.models import Agent, WorkItem
from agent_factory.policy import PolicyRequest
from agent_factory.providers import ProcessSupervisor
from agent_factory.storage import SQLiteStorage
from agent_factory.worker_runtime import CodexCLIWorkerRuntime, RuntimeBinding, RuntimeLaunch
from agent_factory.worktrees import WorktreeManager


FAKE_CODEX = r'''
import json
import sys
import time
from pathlib import Path

mode = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "normal"
if "--version" in sys.argv:
    print("codex-cli 9.9.9-test")
    raise SystemExit(0)
if "--help" in sys.argv:
    if mode != "bad-help":
        print("--sandbox workspace-write --ephemeral --json --cd")
    raise SystemExit(0)
prompt = sys.stdin.read()
if mode == "sleep" or '"description":"sleep"' in prompt:
    time.sleep(60)
Path("src").mkdir(exist_ok=True)
Path("src/change.py").write_text("implemented = True\n", encoding="utf-8")
print(json.dumps({"type":"item.completed","item":{"type":"command_execution","command":"python -m unittest","status":"completed","exit_code":0}}), flush=True)
print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"Implemented scoped change; tests reported by handoff."}}), flush=True)
'''


class RecordingSupervisor(ProcessSupervisor):
    def __init__(self):
        super().__init__()
        self.terminations = 0

    def terminate_tree(self, proc):
        self.terminations += 1
        return super().terminate_tree(proc)


class CodexImplementationWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve()
        self.repository = self.workspace / "repository"
        self.repository.mkdir()
        self.git = shutil.which("git")
        if not self.git:
            self.skipTest("git unavailable")
        self.git_run("init")
        self.git_run("config", "user.email", "worker@example.invalid")
        self.git_run("config", "user.name", "Worker Test")
        (self.repository / "README.md").write_text("base\n", encoding="utf-8")
        self.git_run("add", "README.md")
        self.git_run("commit", "-m", "base")
        self.base_sha = self.git_run("rev-parse", "HEAD").stdout.strip().casefold()
        self.storage = SQLiteStorage(self.workspace / ".agent-factory" / "state.db")
        self.project_id = self.storage.create_project("Codex worker", "AF-049")
        self.script = self.workspace / "fake_codex.py"
        self.script.write_text(FAKE_CODEX, encoding="utf-8")

    def tearDown(self):
        if hasattr(self, "storage"):
            self.storage.close()
        self.temporary.cleanup()

    def git_run(self, *args):
        completed = subprocess.run(
            [self.git, "-C", str(self.repository), *args], shell=False,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20, check=False,
        )
        if completed.returncode:
            self.fail(completed.stderr)
        return completed

    def fixture(self, *, description="implement", mode="normal", max_seconds=5):
        task_id = self.storage.create_task(WorkItem(
            f"Codex task {time.time_ns()}", description, self.project_id,
            acceptance_criteria=["A scoped file changes"],
            permissions=["read_project", "worktree_write", "tool_use"],
        ))
        run_id = self.storage.start_durable_run(
            project_id=self.project_id, task_id=task_id,
            workflow_id=f"codex-{task_id}", workflow_version="1",
            definition={"id": f"codex-{task_id}"},
            stages=[{"id": "implementation", "depends_on": []}],
        )
        self.storage.transition_durable_stage(run_id, "implementation", "running", {"reason": "dispatch"})
        claim = self.storage.claim_runnable_task(
            task_id, "coding-worker-codex", "codex-cli",
            conflict_domains=[f"path:codex-{task_id}"],
        )
        attempt_id = self.storage.create_assignment_attempt(claim.assignment_id, claim.fencing_token)
        worktree = WorktreeManager(self.storage, self.workspace, git_executable=self.git).provision(
            assignment_id=claim.assignment_id, fencing_token=claim.fencing_token,
            repository=self.repository, base_sha=self.base_sha, attempt_id=attempt_id,
        )
        package = ContextPackageBuilder(self.storage, self.workspace).build(
            task_id=task_id, run_id=run_id, assignment_id=claim.assignment_id,
            fencing_token=claim.fencing_token, base_sha=self.base_sha,
        )
        request = PolicyRequest(
            mission_id=self.project_id, task_id=task_id, run_id=run_id,
            stage_id="implementation", worker_id="coding-worker-codex",
            runtime_id="codex-cli", worktree_id=str(worktree.id),
            permissions=tuple(sorted(self.storage.get_task(task_id).permissions)),
        )
        live = LiveStageExecution(self.storage)
        gate = live.request_approval(request, requested_by="founder")
        approval = live.decide(gate.approval_id, "approved", actor="founder")
        launch = RuntimeLaunch(
            assignment_id=claim.assignment_id, fencing_token=claim.fencing_token,
            agent=Agent("coding-worker-codex", "Codex", "Implementation Worker", True, "codex", "Implement", model=""),
            item=self.storage.get_task(task_id), context=package.payload,
            context_digest=package.digest,
            binding=RuntimeBinding(run_id, "implementation", attempt_id, worktree.id, ("read_file", "write_file")),
            approval=approval, mutable=True,
        )
        supervisor = RecordingSupervisor()
        driver = CodexCLIProcessDriver(
            self.storage, self.workspace, executable_candidates=(sys.executable,),
            executable_args=(str(self.script), mode), max_seconds=max_seconds,
            supervisor=supervisor,
        )
        return launch, worktree, driver, supervisor

    def test_qualified_worker_records_candidate_commands_exit_and_handoff(self):
        protected = self.workspace / "protected.txt"
        protected.write_text("control-plane\n", encoding="utf-8")
        launch, worktree, driver, _ = self.fixture()
        health = driver.health(Path(worktree.path))
        self.assertTrue(health.healthy)
        runtime = CodexCLIWorkerRuntime(self.storage, driver)
        session = runtime.start(launch)
        result = runtime.finalize(session.id)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(protected.read_text(encoding="utf-8"), "control-plane\n")

        row = self.storage.db.execute("SELECT * FROM codex_worker_results").fetchone()
        self.assertEqual(json.loads(row["changed_files_json"]), ["src/change.py"])
        self.assertEqual(len(row["diff_digest"]), 64)
        self.assertEqual(json.loads(row["executed_commands_json"])[0]["command"], "python -m unittest")
        self.assertIn("Implemented scoped change", json.loads(row["handoff_json"])["summary"])
        invocation = json.loads(row["invocation_json"])
        self.assertIn("--sandbox", invocation)
        self.assertIn("workspace-write", invocation)
        self.assertIn("--ask-for-approval", invocation)
        self.assertIn("never", invocation)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", invocation)
        self.assertNotIn("--add-dir", invocation)
        self.assertEqual(tuple(invocation[3:3 + len(CODEX_EXEC_ARGS)]), CODEX_EXEC_ARGS)
        profile = json.loads(row["permission_profile_json"])
        self.assertEqual(profile["additional_write_directories"], [])
        self.assertIn("merge", profile["forbidden_authorities"])
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute("UPDATE codex_worker_results SET status='failed' WHERE id=?", (row["id"],))

    def test_timeout_and_cancel_terminate_the_process_tree(self):
        launch, _, driver, supervisor = self.fixture(mode="sleep", max_seconds=1)
        runtime = CodexCLIWorkerRuntime(self.storage, driver)
        session = runtime.start(launch)
        self.assertEqual(runtime.finalize(session.id).status, "failed")
        self.assertEqual(
            self.storage.db.execute("SELECT status FROM codex_worker_results WHERE worker_session_id=?", (session.id,)).fetchone()[0],
            "timed_out",
        )
        self.assertGreaterEqual(supervisor.terminations, 1)

        launch, _, driver, supervisor = self.fixture(mode="sleep", max_seconds=30)
        runtime = CodexCLIWorkerRuntime(self.storage, driver)
        session = runtime.start(launch)
        cancelled = runtime.cancel(session.id, reason="operator stop")
        self.assertEqual(cancelled.status, "cancelled")
        self.assertGreaterEqual(supervisor.terminations, 1)
        self.assertEqual(
            self.storage.db.execute("SELECT status FROM codex_worker_results WHERE worker_session_id=?", (session.id,)).fetchone()[0],
            "cancelled",
        )

    def test_unqualified_interface_fails_before_task_process(self):
        launch, _, _, _ = self.fixture()
        driver = CodexCLIProcessDriver(
            self.storage, self.workspace, executable_candidates=(sys.executable,),
            executable_args=(str(self.script), "bad-help"), max_seconds=1,
        )
        self.assertFalse(driver.health().healthy)
        with self.assertRaisesRegex(RuntimeError, "not qualified"):
            CodexCLIWorkerRuntime(self.storage, driver).start(launch)
        self.assertEqual(self.storage.db.execute("SELECT COUNT(*) FROM codex_worker_results").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
