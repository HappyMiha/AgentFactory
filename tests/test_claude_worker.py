import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

from agent_factory.claude_worker import (
    CLAUDE_EXEC_ARGS,
    CLAUDE_PERMISSION_PROFILE,
    ClaudeCodeProcessDriver,
)
from agent_factory.context_packages import ContextPackageBuilder
from agent_factory.live_stages import LiveStageExecution
from agent_factory.models import Agent, WorkItem
from agent_factory.policy import PolicyRequest
from agent_factory.providers import ProcessSupervisor
from agent_factory.storage import SQLiteStorage
from agent_factory.worker_runtime import ClaudeCodeWorkerRuntime, RuntimeBinding, RuntimeLaunch
from agent_factory.worktrees import WorktreeManager


FAKE_CLAUDE = r'''
import json
import sys
import time
from pathlib import Path

mode = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "normal"
if "--version" in sys.argv:
    print("2.1.213 (Claude Code)")
    raise SystemExit(0)
if "--help" in sys.argv:
    if mode != "bad-help":
        print("--print --output-format --permission-mode --tools --allowedTools --setting-sources --strict-mcp-config")
    raise SystemExit(0)
prompt = sys.stdin.read()
if mode == "sleep" or '"description":"sleep"' in prompt:
    time.sleep(60)
Path("src").mkdir(exist_ok=True)
Path("src/claude_change.py").write_text("implemented_by = 'claude'\n", encoding="utf-8")
print(json.dumps({"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"src/claude_change.py"}}]}}), flush=True)
print(json.dumps({"type":"result","subtype":"success","result":"Implemented scoped Claude change.","usage":{"input_tokens":10,"output_tokens":4}}), flush=True)
'''


class RecordingSupervisor(ProcessSupervisor):
    def __init__(self):
        super().__init__()
        self.terminations = 0

    def terminate_tree(self, proc):
        self.terminations += 1
        return super().terminate_tree(proc)


class ClaudeCodeWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve()
        self.repository = self.workspace / "repository"
        self.repository.mkdir()
        self.git = shutil.which("git")
        if not self.git:
            self.skipTest("git unavailable")
        self.git_run("init")
        self.git_run("config", "user.email", "claude@example.invalid")
        self.git_run("config", "user.name", "Claude Worker Test")
        (self.repository / "README.md").write_text("base\n", encoding="utf-8")
        self.git_run("add", "README.md")
        self.git_run("commit", "-m", "base")
        self.base_sha = self.git_run("rev-parse", "HEAD").stdout.strip().casefold()
        self.storage = SQLiteStorage(self.workspace / ".agent-factory" / "state.db")
        self.project_id = self.storage.create_project("Claude worker", "AF-050")
        self.script = self.workspace / "fake_claude.py"
        self.script.write_text(FAKE_CLAUDE, encoding="utf-8")

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def git_run(self, *args):
        completed = subprocess.run(
            [self.git, "-C", str(self.repository), *args], capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=20,
        )
        if completed.returncode:
            self.fail(completed.stderr)
        return completed

    def fixture(self, *, description="implement", mode="normal", max_seconds=5):
        task_id = self.storage.create_task(WorkItem(
            f"Claude task {time.time_ns()}", description, self.project_id,
            acceptance_criteria=["A scoped Claude file changes"],
            permissions=["read_project", "worktree_write", "tool_use"],
        ))
        run_id = self.storage.start_durable_run(
            project_id=self.project_id, task_id=task_id,
            workflow_id=f"claude-{task_id}", workflow_version="1",
            definition={"id": f"claude-{task_id}"},
            stages=[{"id": "implementation", "depends_on": []}],
        )
        self.storage.transition_durable_stage(run_id, "implementation", "running", {"reason": "dispatch"})
        claim = self.storage.claim_runnable_task(
            task_id, "coding-worker-claude", "claude-cli",
            conflict_domains=[f"path:claude-{task_id}"],
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
        agent = Agent(
            "coding-worker-claude", "Claude", "Implementation Worker", True,
            "claude", "Implement", model="claude-test",
        )
        request = PolicyRequest(
            mission_id=self.project_id, task_id=task_id, run_id=run_id,
            stage_id="implementation", worker_id=agent.id, runtime_id="claude-cli",
            worktree_id=str(worktree.id),
            permissions=tuple(sorted(self.storage.get_task(task_id).permissions)),
        )
        live = LiveStageExecution(self.storage)
        gate = live.request_approval(request, requested_by="founder")
        approval = live.decide(gate.approval_id, "approved", actor="founder")
        launch = RuntimeLaunch(
            claim.assignment_id, claim.fencing_token, agent,
            self.storage.get_task(task_id), package.payload, package.digest,
            binding=RuntimeBinding(
                run_id, "implementation", attempt_id, worktree.id,
                ("Read", "Edit", "Write", "Glob", "Grep"),
            ),
            approval=approval, mutable=True,
        )
        supervisor = RecordingSupervisor()
        driver = ClaudeCodeProcessDriver(
            self.storage, self.workspace, executable_candidates=(sys.executable,),
            executable_args=(str(self.script), mode), max_seconds=max_seconds,
            supervisor=supervisor,
        )
        return launch, worktree, driver, supervisor

    def test_qualified_profile_records_same_task_workflow_and_candidate_contract(self):
        launch, worktree, driver, _ = self.fixture()
        health = driver.health(Path(worktree.path))
        self.assertTrue(health.healthy)
        runtime = ClaudeCodeWorkerRuntime(self.storage, driver)
        result = runtime.finalize(runtime.start(launch).id)
        self.assertEqual(result.status, "succeeded")
        row = self.storage.db.execute("SELECT * FROM claude_worker_results").fetchone()
        self.assertEqual((row["task_id"], row["run_id"]), (launch.item.id, launch.binding.run_id))
        self.assertEqual(json.loads(row["changed_files_json"]), ["src/claude_change.py"])
        self.assertEqual(len(row["diff_digest"]), 64)
        self.assertEqual(json.loads(row["tool_calls_json"])[0]["name"], "Edit")
        invocation = json.loads(row["invocation_json"])
        profile_start = invocation.index("--print")
        self.assertEqual(
            tuple(invocation[profile_start:profile_start + len(CLAUDE_EXEC_ARGS)]),
            CLAUDE_EXEC_ARGS,
        )
        self.assertNotIn("Bash", CLAUDE_PERMISSION_PROFILE["tools"])
        self.assertNotIn("--add-dir", invocation)
        self.assertNotIn("--dangerously-skip-permissions", invocation)
        qualification_id = driver.qualify_result(int(row["id"]))
        self.assertEqual(
            self.storage.db.execute(
                "SELECT status FROM worker_qualifications WHERE id=?", (qualification_id,)
            ).fetchone()[0],
            "qualified",
        )
        self.assertEqual(
            self.storage.select_qualified_worker(
                role="Implementation Worker",
                required_capabilities={"implementation_worker", "worktree_write"},
            ),
            "coding-worker-claude",
        )
        self.assertIsNone(self.storage.select_qualified_worker(
            role="Delivery Planner", required_capabilities={"worktree_write"}
        ))

    def test_plan_only_role_cannot_enter_writable_profile(self):
        launch, _, driver, _ = self.fixture()
        plan_launch = replace(launch, agent=replace(launch.agent, role="Delivery Planner"))
        with self.assertRaisesRegex(PermissionError, "implementation role"):
            ClaudeCodeWorkerRuntime(self.storage, driver).start(plan_launch)
        self.assertEqual(self.storage.db.execute("SELECT COUNT(*) FROM claude_worker_results").fetchone()[0], 0)

    def test_timeout_and_cancel_terminate_complete_process_tree(self):
        launch, _, driver, supervisor = self.fixture(mode="sleep", max_seconds=1)
        runtime = ClaudeCodeWorkerRuntime(self.storage, driver)
        self.assertEqual(runtime.finalize(runtime.start(launch).id).status, "failed")
        self.assertGreaterEqual(supervisor.terminations, 1)

        launch, _, driver, supervisor = self.fixture(mode="sleep", max_seconds=30)
        runtime = ClaudeCodeWorkerRuntime(self.storage, driver)
        cancelled = runtime.cancel(runtime.start(launch).id, reason="operator stop")
        self.assertEqual(cancelled.status, "cancelled")
        self.assertGreaterEqual(supervisor.terminations, 1)

    def test_incompatible_interface_fails_before_task_process(self):
        launch, worktree, _, _ = self.fixture()
        driver = ClaudeCodeProcessDriver(
            self.storage, self.workspace, executable_candidates=(sys.executable,),
            executable_args=(str(self.script), "bad-help"), max_seconds=1,
        )
        self.assertFalse(driver.health(Path(worktree.path)).healthy)
        with self.assertRaisesRegex(RuntimeError, "not qualified"):
            ClaudeCodeWorkerRuntime(self.storage, driver).start(launch)
        self.assertEqual(self.storage.db.execute("SELECT COUNT(*) FROM claude_worker_results").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
