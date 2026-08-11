import json
import sqlite3
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_factory.context_packages import ContextPackageBuilder
from agent_factory.live_stages import LiveStageExecution
from agent_factory.local_recovery import LocalRecoveryService
from agent_factory.hermes_acp import (
    HERMES_ACP_TOOLS,
    HermesACPProcessDriver,
)
from agent_factory.hermes_qualification import HermesQualificationService
from agent_factory.models import Agent, WorkItem
from agent_factory.policy import PolicyRequest
from agent_factory.storage import SQLiteStorage
from agent_factory.worker_runtime import (
    HermesACPWorkerRuntime,
    RuntimeBinding,
    RuntimeLaunch,
)
from agent_factory.worktrees import WorktreeManager


FAKE_ACP = r'''
import json
import sys
import time
from pathlib import Path

arguments = sys.argv[1:]
log_path = Path(arguments[0]) if arguments and not arguments[0].startswith("--") else None
mode = arguments[1] if len(arguments) > 1 and not arguments[1].startswith("--") else "normal"
if "--version" in arguments:
    print("0.19.0" if mode == "bad-version" else "0.20.0", flush=True)
    raise SystemExit(0)
if "--check" in arguments:
    print("Hermes ACP check OK", flush=True)
    raise SystemExit(0)

def send(value):
    print(json.dumps(value, separators=(",", ":")), flush=True)

def record(value):
    if log_path:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, sort_keys=True) + "\n")

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    params = request.get("params", {})
    request_id = request.get("id")
    if method == "initialize":
        send({"jsonrpc":"2.0","id":request_id,"result":{"protocolVersion":1,"agentInfo":{"name":"fake-hermes","version":"0.20.0"},"agentCapabilities":{}}})
    elif method == "session/new":
        record({"method": method, "cwd": params.get("cwd"), "mcpServers": params.get("mcpServers")})
        send({"jsonrpc":"2.0","id":request_id,"result":{"sessionId":"hermes-stable-session"}})
    elif method == "session/load":
        record({"method": method, "sessionId": params.get("sessionId"), "cwd": params.get("cwd")})
        send({"jsonrpc":"2.0","id":request_id,"result":{}})
    elif method == "session/list":
        send({"jsonrpc":"2.0","id":request_id,"result":{"sessions":[]}})
    elif method == "session/prompt":
        record({"method": method, "prompt": params.get("prompt"), "sessionId": params.get("sessionId")})
        if mode == "blocking":
            send({"jsonrpc":"2.0","method":"session/update","params":{"sessionId":params["sessionId"],"update":{"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":"waiting"}}}})
            time.sleep(60)
            continue
        send({"jsonrpc":"2.0","method":"session/update","params":{"sessionId":params["sessionId"],"update":{"sessionUpdate":"tool_call","toolCallId":"tool-1","title":"write file","kind":"edit","content":[{"type":"diff","path":"change.py","oldText":"","newText":"change"}]}}})
        send({"jsonrpc":"2.0","method":"session/update","params":{"sessionId":params["sessionId"],"update":{"sessionUpdate":"usage_update","usage":{"inputTokens":12,"outputTokens":4}}}})
        send({"jsonrpc":"2.0","id":900,"method":"session/request_permission","params":{"sessionId":params["sessionId"],"toolCall":{"toolCallId":"permission-1","title":"write file"},"options":[{"optionId":"allow_once","kind":"allow_once","name":"Allow once"},{"optionId":"deny","kind":"reject_once","name":"Deny"}]}})
        permission = json.loads(sys.stdin.readline())
        record({"permission_response": permission.get("result")})
        send({"jsonrpc":"2.0","method":"session/update","params":{"sessionId":params["sessionId"],"update":{"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":"implemented"}}}})
        send({"jsonrpc":"2.0","id":request_id,"result":{"stopReason":"end_turn"}})
    elif method == "session/cancel":
        record({"method": method, "sessionId": params.get("sessionId")})
'''


class HermesACPProcessDriverTests(unittest.TestCase):
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
        self.storage = SQLiteStorage(self.workspace / ".agent-factory" / "state.db")
        self.project_id = self.storage.create_project("Hermes", "AF-045")
        self.task_id = self.storage.create_task(
            WorkItem(
                "Hermes task",
                "Exercise the concrete ACP adapter",
                self.project_id,
                acceptance_criteria=["ACP lifecycle is durable"],
                permissions=["read_project", "worktree_write"],
            )
        )
        self.run_id = self.storage.start_durable_run(
            project_id=self.project_id,
            task_id=self.task_id,
            workflow_id="hermes-delivery",
            workflow_version="1",
            definition={"id": "hermes-delivery"},
            stages=[{"id": "implementation", "depends_on": []}],
        )
        self.storage.transition_durable_stage(
            self.run_id, "implementation", "running", {"reason": "dispatch"}
        )
        self.claim = self.storage.claim_runnable_task(
            self.task_id,
            "hermes-worker",
            "hermes-acp",
            conflict_domains=["path:hermes-task"],
        )
        self.attempt_id = self.storage.create_assignment_attempt(
            self.claim.assignment_id, self.claim.fencing_token
        )
        self.worktree = WorktreeManager(
            self.storage, self.workspace, git_executable=self.git
        ).provision(
            assignment_id=self.claim.assignment_id,
            fencing_token=self.claim.fencing_token,
            repository=self.repository,
            base_sha=self.base_sha,
            attempt_id=self.attempt_id,
        )
        self.package = ContextPackageBuilder(
            self.storage, self.workspace
        ).build(
            task_id=self.task_id,
            run_id=self.run_id,
            assignment_id=self.claim.assignment_id,
            fencing_token=self.claim.fencing_token,
            base_sha=self.base_sha,
        )
        request = PolicyRequest(
            mission_id=self.project_id,
            task_id=self.task_id,
            run_id=self.run_id,
            stage_id="implementation",
            worker_id="hermes-worker",
            runtime_id="hermes-acp",
            worktree_id=str(self.worktree.id),
            permissions=tuple(sorted(self.storage.get_task(self.task_id).permissions)),
        )
        live = LiveStageExecution(self.storage)
        gate = live.request_approval(request, requested_by="hermes-test")
        self.approval = live.decide(
            gate.approval_id, "approved", actor="hermes-test"
        )
        self.script = self.workspace / "fake_hermes_acp.py"
        self.script.write_text(FAKE_ACP, encoding="utf-8")
        self.log = self.workspace / "acp-log.jsonl"

    def tearDown(self):
        if hasattr(self, "storage"):
            self.storage.close()
        self.temporary.cleanup()

    def run_git(self, *args):
        completed = subprocess.run(
            [self.git, "-C", str(self.repository), *args],
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

    def driver(self, mode="normal", *, permission=True):
        return HermesACPProcessDriver(
            self.storage,
            self.workspace,
            executable_candidates=(sys.executable,),
            executable_args=(str(self.script), str(self.log), mode),
            permission_decider=(
                (lambda _session_id, _request: "allow_once")
                if permission
                else None
            ),
            request_timeout=5,
            prompt_timeout=10,
        )

    def launch(self, *, tools=HERMES_ACP_TOOLS):
        return RuntimeLaunch(
            assignment_id=self.claim.assignment_id,
            fencing_token=self.claim.fencing_token,
            agent=Agent(
                "hermes-worker",
                "Hermes worker",
                "Implementation Worker",
                True,
                "hermes-acp",
                "Use only the immutable context package",
            ),
            item=self.storage.get_task(self.task_id),
            context=self.package.payload,
            context_digest=self.package.digest,
            binding=RuntimeBinding(
                run_id=self.run_id,
                stage_id="implementation",
                attempt_id=self.attempt_id,
                worktree_id=self.worktree.id,
                allowed_tools=tuple(tools),
            ),
            approval=self.approval,
            mutable=True,
            permission_bridge_id="control-plane-permissions",
        )

    def records(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def test_health_requires_discovery_version_check_and_workspace_access(self):
        health = self.driver().health(Path(self.worktree.path))
        self.assertTrue(health.healthy)
        self.assertEqual(health.version, "0.20.0")
        self.assertTrue(health.check_passed)
        self.assertTrue(health.workspace_access)

        incompatible = self.driver("bad-version").health(Path(self.worktree.path))
        self.assertFalse(incompatible.healthy)
        self.assertIn("qualified range", incompatible.reason)

    def test_start_binds_full_scope_and_returns_structured_protocol_events(self):
        driver = self.driver()
        runtime = HermesACPWorkerRuntime(self.storage, driver)
        session = runtime.start(self.launch())
        result = runtime.finalize(session.id)
        self.assertEqual(result.status, "succeeded")
        self.assertTrue(result.messages)
        self.assertTrue(result.tool_calls)
        self.assertTrue(result.artifacts)
        self.assertGreater(result.session.mutable_action_count, 0)

        bound = self.storage.hermes_acp_session(session.external_session_id)
        self.assertEqual(bound["task_id"], self.task_id)
        self.assertEqual(bound["run_id"], self.run_id)
        self.assertEqual(bound["attempt_id"], self.attempt_id)
        self.assertEqual(bound["worktree_id"], self.worktree.id)
        self.assertEqual(bound["agent_role"], "Implementation Worker")
        self.assertEqual(
            tuple(json.loads(bound["allowed_tools_json"])), HERMES_ACP_TOOLS
        )
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE hermes_acp_sessions SET run_id=999 WHERE id=?",
                (bound["id"],),
            )
        records = self.records()
        new = next(record for record in records if record.get("method") == "session/new")
        self.assertEqual(Path(new["cwd"]), Path(self.worktree.path))
        self.assertEqual(new["mcpServers"], [])
        prompt = next(record for record in records if record.get("method") == "session/prompt")
        sent_context = json.loads(prompt["prompt"][0]["text"])
        self.assertEqual(sent_context, self.package.payload)
        self.assertEqual(
            next(record for record in records if "permission_response" in record)["permission_response"],
            {"outcome": {"optionId": "allow_once", "outcome": "selected"}},
        )

    def test_full_qualification_matrix_is_immutable_and_routable(self):
        driver = self.driver()
        runtime = HermesACPWorkerRuntime(self.storage, driver)
        session = runtime.start(self.launch())
        result = runtime.finalize(session.id)
        self.assertEqual(result.status, "succeeded")
        qualification = HermesQualificationService(self.storage).qualify(
            worker_id="hermes-worker", role="Implementation Worker",
            session_id=session.id, health=driver.health(Path(self.worktree.path)),
            cancellation_evidence={
                "process_tree_terminated": True,
                "worktree": str(self.worktree.path),
                "probe": "separate cancellation qualification",
            },
        )
        self.assertEqual(qualification.status, "qualified")
        self.assertTrue(all(qualification.checks.values()))
        self.assertEqual(
            self.storage.select_qualified_worker(
                role="Implementation Worker", required_capabilities={"hermes_acp"}
            ),
            "hermes-worker",
        )
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE hermes_qualification_runs SET checks_json='{}' WHERE id=?",
                (qualification.id,),
            )

    def test_restart_loads_the_same_stable_hermes_identity(self):
        first_driver = self.driver()
        first_runtime = HermesACPWorkerRuntime(self.storage, first_driver)
        session = first_runtime.start(self.launch())
        self.assertEqual(
            first_driver._connection(session.external_session_id).wait_terminal(5),
            "succeeded",
        )
        recovered = LocalRecoveryService(self.storage).snapshot(self.run_id)
        self.assertEqual(
            recovered.hermes_session["external_session_id"], session.external_session_id
        )
        orphans = LocalRecoveryService(
            self.storage, process_alive=lambda pid: False
        ).detect_orphans()
        self.assertIn(recovered.hermes_session["id"], orphans.hermes_session_ids)
        self.assertEqual(orphans.provider_process_ids, ())
        self.assertEqual(orphans.worktree_paths, ())
        self.storage.suspend_runtime_session(session.id, reason="Control Plane restart")
        first_driver.detach(session.external_session_id)

        resumed_driver = self.driver()
        resumed_runtime = HermesACPWorkerRuntime(self.storage, resumed_driver)
        resumed = resumed_runtime.resume(session.id)
        self.assertEqual(resumed.external_session_id, session.external_session_id)
        loaded = [record for record in self.records() if record.get("method") == "session/load"]
        self.assertEqual(loaded[-1]["sessionId"], session.external_session_id)
        self.assertEqual(Path(loaded[-1]["cwd"]), Path(self.worktree.path))
        resumed_runtime.cancel(session.id, reason="test complete")

    def test_cancel_terminates_the_complete_acp_process_tree(self):
        driver = self.driver("blocking")
        runtime = HermesACPWorkerRuntime(self.storage, driver)
        session = runtime.start(self.launch())
        process = driver._connection(session.external_session_id).process
        cancelled = runtime.cancel(session.id, reason="operator stop")
        self.assertEqual(cancelled.status, "cancelled")
        process.wait(timeout=5)
        self.assertIsNotNone(process.returncode)
        self.assertEqual(
            self.storage.hermes_acp_session(session.external_session_id)["status"],
            "cancelled",
        )

    def test_permission_bridge_denies_without_a_control_plane_decision(self):
        driver = self.driver(permission=False)
        runtime = HermesACPWorkerRuntime(self.storage, driver)
        session = runtime.start(self.launch())
        self.assertEqual(runtime.finalize(session.id).status, "succeeded")
        response = next(
            record for record in self.records() if "permission_response" in record
        )["permission_response"]
        self.assertEqual(response, {"outcome": {"outcome": "cancelled"}})

    def test_widened_tool_surface_fails_closed(self):
        with self.assertRaisesRegex(PermissionError, "tool surface"):
            HermesACPWorkerRuntime(self.storage, self.driver()).start(
                self.launch(tools=("read_file",))
            )
        self.assertEqual(
            self.storage.db.execute("SELECT COUNT(*) FROM hermes_acp_sessions").fetchone()[0],
            0,
        )


if __name__ == "__main__":
    unittest.main()
