import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_factory.models import WorkItem
from agent_factory.sandbox import (
    BubblewrapBackend,
    MacOSSandboxBackend,
    SandboxBackend,
    SandboxManager,
    SandboxPathError,
    SandboxPolicy,
    SandboxUnavailableError,
    UnavailableSandboxBackend,
    WindowsAppContainerBackend,
    configured_tool_roots,
    platform_sandbox_backend,
)
from agent_factory.storage import SQLiteStorage


class DirectTestBackend(SandboxBackend):
    name = "test-enforced-backend"

    def availability(self) -> tuple[bool, str]:
        return True, "test backend"

    def wrap(
        self, policy: SandboxPolicy, command: tuple[str, ...], control_dir: Path
    ) -> list[str]:
        del policy, control_dir
        return list(command)


class LocalSandboxTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve()
        self.worktree = self.workspace / "worktrees" / "task-1"
        self.worktree.mkdir(parents=True)
        self.temp_path = (
            self.workspace / ".agent-factory" / "sandbox-temp" / "task-1" / "run"
        )
        self.storage = SQLiteStorage(
            self.workspace / ".agent-factory" / "state.db"
        )
        project_id = self.storage.create_project("Sandbox", "AF-017")
        self.task_id = self.storage.create_task(
            WorkItem("Writable task", "Sandboxed", project_id)
        )
        self.claim = self.storage.claim_runnable_task(
            self.task_id,
            "writable-worker",
            "test-runtime",
            conflict_domains=["path:worktrees/task-1"],
        )

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def policy(self, **overrides) -> SandboxPolicy:
        values = {
            "max_seconds": 5,
            "max_output_chars": 10_000,
        }
        values.update(overrides)
        return SandboxPolicy.create(
            self.workspace,
            self.worktree,
            [self.temp_path],
            **values,
        )

    def manager(self, backend: SandboxBackend | None = None) -> SandboxManager:
        return SandboxManager(
            self.storage,
            self.workspace,
            backend=backend or DirectTestBackend(),
        )

    def test_write_gateway_allows_declared_roots_and_audits_denial(self):
        policy = self.policy()
        manager = self.manager()
        allowed = manager.authorize_write(
            self.claim.assignment_id,
            self.claim.fencing_token,
            policy,
            self.worktree / "src" / "module.py",
        )
        self.assertEqual(allowed, self.worktree / "src" / "module.py")

        with self.assertRaises(SandboxPathError):
            manager.authorize_write(
                self.claim.assignment_id,
                self.claim.fencing_token,
                policy,
                self.workspace / "protected.txt",
            )
        event = self.storage.db.execute(
            """SELECT payload FROM events
                 WHERE event_type='sandbox.write.blocked' ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        payload = json.loads(event["payload"])
        self.assertEqual(payload["assignment_id"], self.claim.assignment_id)
        self.assertNotIn("protected.txt", event["payload"])

    def test_policy_rejects_broad_or_external_write_roots_and_network(self):
        with self.assertRaisesRegex(ValueError, "distinct directory"):
            SandboxPolicy.create(self.workspace, self.workspace)
        outside = self.workspace.parent / "outside-temp"
        with self.assertRaisesRegex(ValueError, "sandbox-temp"):
            SandboxPolicy.create(
                self.workspace, self.worktree, [outside]
            )
        with self.assertRaisesRegex(ValueError, "deny-only"):
            SandboxPolicy.create(
                self.workspace, self.worktree, network="allow"
            )

    def test_unsupported_host_fails_closed_before_process_launch(self):
        manager = self.manager(
            UnavailableSandboxBackend("qualified backend missing")
        )
        with self.assertRaisesRegex(SandboxUnavailableError, "backend missing"):
            manager.execute(
                self.claim.assignment_id,
                self.claim.fencing_token,
                self.policy(),
                [sys.executable, "-c", "raise SystemExit('must not run')"],
            )
        self.assertEqual(
            self.storage.db.execute(
                """SELECT COUNT(*) FROM events
                     WHERE event_type='sandbox.execution.blocked'"""
            ).fetchone()[0],
            1,
        )

    def test_execution_preserves_candidate_and_evidence_then_cleans_temp(self):
        result = self.manager().execute(
            self.claim.assignment_id,
            self.claim.fencing_token,
            self.policy(),
            [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; import os; "
                    "Path('candidate.txt').write_text('candidate', encoding='utf-8'); "
                    "Path(os.environ['TMP']).joinpath('scratch.txt').write_text('scratch'); "
                    "print('done')"
                ),
            ],
        )

        evidence = Path(result.evidence_directory)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.stdout.strip(), "done")
        self.assertEqual(result.changed_files, ("candidate.txt",))
        self.assertTrue((evidence / "evidence.json").is_file())
        self.assertTrue((evidence / "candidate.json").is_file())
        self.assertEqual(
            (evidence / "files" / "candidate.txt").read_text(encoding="utf-8"),
            "candidate",
        )
        self.assertFalse(self.temp_path.exists())
        completed = self.storage.db.execute(
            """SELECT payload FROM events
                 WHERE event_type='sandbox.execution.completed' ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        self.assertEqual(json.loads(completed["payload"])["status"], "succeeded")

    def test_time_and_combined_output_limits_terminate_the_process_tree(self):
        output = self.manager().execute(
            self.claim.assignment_id,
            self.claim.fencing_token,
            self.policy(max_output_chars=100),
            [sys.executable, "-c", "print('x' * 5000)"],
        )
        self.assertEqual(output.status, "output_limited")
        self.assertTrue(output.output_limit_exceeded)
        self.assertLessEqual(len(output.stdout) + len(output.stderr), 100)

        timeout = self.manager().execute(
            self.claim.assignment_id,
            self.claim.fencing_token,
            self.policy(max_seconds=1),
            [sys.executable, "-c", "import time; time.sleep(3)"],
        )
        self.assertEqual(timeout.status, "timed_out")
        self.assertTrue(timeout.timed_out)
        self.assertTrue(timeout.process_tree_contained)

    def test_windows_backend_stays_unavailable_until_tool_roots_are_provisioned(self):
        backend = WindowsAppContainerBackend()
        available, reason = backend.availability()
        self.assertFalse(available)
        self.assertRegex(reason, "Windows|tool root")
        with self.assertRaises(SandboxUnavailableError):
            backend.wrap(self.policy(), (sys.executable, "-c", "pass"), self.workspace)

        missing = WindowsAppContainerBackend([self.workspace / "never-provisioned"])
        self.assertFalse(missing.availability()[0])

    def test_configured_tool_roots_read_only_an_explicit_operator_setting(self):
        previous = os.environ.get("AGENT_FACTORY_SANDBOX_TOOL_ROOTS")
        self.addCleanup(
            lambda: os.environ.__setitem__("AGENT_FACTORY_SANDBOX_TOOL_ROOTS", previous)
            if previous is not None
            else os.environ.pop("AGENT_FACTORY_SANDBOX_TOOL_ROOTS", None)
        )
        os.environ.pop("AGENT_FACTORY_SANDBOX_TOOL_ROOTS", None)
        self.assertEqual(configured_tool_roots(), ())
        os.environ["AGENT_FACTORY_SANDBOX_TOOL_ROOTS"] = os.pathsep.join(
            [str(self.workspace), ""]
        )
        self.assertEqual(configured_tool_roots(), (self.workspace,))

    @unittest.skipUnless(sys.platform == "win32", "AppContainer isolation is Windows-only")
    def test_windows_backend_plans_a_launcher_for_commands_inside_a_tool_root(self):
        tools = self.workspace / "tools"
        tools.mkdir()
        shutil.copy2(Path(os.environ["SystemRoot"]) / "System32" / "where.exe", tools)
        backend = WindowsAppContainerBackend([tools])
        self.assertTrue(backend.availability()[0])

        with self.assertRaisesRegex(SandboxUnavailableError, "outside every qualified"):
            backend.wrap(self.policy(), (sys.executable, "-c", "pass"), self.workspace)

        policy = self.policy()
        control = self.workspace / "control"
        control.mkdir()
        command = (str(tools / "where.exe"), "/?")
        wrapped = backend.wrap(policy, command, control)
        self.assertEqual(wrapped[:3], [sys.executable, "-m", "agent_factory.windows_sandbox"])
        specification = json.loads(
            (control / "appcontainer.json").read_text(encoding="utf-8")
        )
        self.assertEqual(specification["command"], list(command))
        self.assertEqual(specification["cwd"], str(policy.worktree))
        self.assertEqual(specification["tool_roots"], [str(tools)])
        self.assertEqual(
            specification["write_roots"], [str(root) for root in policy.write_roots]
        )

    @unittest.skipUnless(sys.platform == "win32", "AppContainer isolation is Windows-only")
    def test_windows_container_writes_only_inside_the_declared_roots(self):
        tools = self.workspace / "tools"
        tools.mkdir()
        shutil.copy2(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe", tools)
        manager = self.manager(WindowsAppContainerBackend([tools]))
        shell = str(tools / "cmd.exe")
        # The NUL device is unreachable inside the container, so copy a real seed.
        (self.worktree / "seed.txt").write_text("seed", encoding="utf-8")

        allowed = manager.execute(
            self.claim.assignment_id,
            self.claim.fencing_token,
            self.policy(max_seconds=90),
            [shell, "/c", "copy", "seed.txt", "candidate.txt"],
        )
        self.assertEqual(allowed.status, "succeeded")
        self.assertEqual(allowed.backend, "appcontainer")
        self.assertIn("candidate.txt", allowed.changed_files)

        outside = self.workspace / "escaped.txt"
        denied = manager.execute(
            self.claim.assignment_id,
            self.claim.fencing_token,
            self.policy(max_seconds=90),
            [shell, "/c", "copy", "seed.txt", str(outside)],
        )
        self.assertEqual(denied.status, "failed")
        self.assertFalse(outside.exists())

    @unittest.skipUnless(sys.platform == "win32", "AppContainer isolation is Windows-only")
    def test_windows_container_grants_do_not_outlive_a_killed_launcher(self):
        tools = self.workspace / "tools"
        tools.mkdir()
        shutil.copy2(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe", tools)
        manager = self.manager(WindowsAppContainerBackend([tools]))

        timed_out = manager.execute(
            self.claim.assignment_id,
            self.claim.fencing_token,
            self.policy(max_seconds=2),
            [str(tools / "cmd.exe"), "/c", "for /l %i in (0,0,1) do @rem"],
        )
        self.assertEqual(timed_out.status, "timed_out")
        for root in (tools, self.worktree):
            listing = subprocess.run(
                ["icacls", str(root)], capture_output=True, text=True
            ).stdout
            self.assertNotIn("S-1-15-2-", listing)

    def test_platform_backend_never_reports_an_unconfigured_host_as_ready(self):
        backend = platform_sandbox_backend()
        if sys.platform == "win32":
            self.assertIsInstance(backend, WindowsAppContainerBackend)
            if not configured_tool_roots():
                self.assertFalse(backend.availability()[0])
        else:
            self.assertNotIsInstance(backend, WindowsAppContainerBackend)

    def test_os_backend_plans_mount_only_declared_writes_and_denies_network(self):
        policy = self.policy()
        bubblewrap = BubblewrapBackend(sys.executable)
        command = (sys.executable, "-c", "print('x')")
        wrapped = bubblewrap.wrap(policy, command, self.workspace)
        self.assertIn("--unshare-all", wrapped)
        self.assertNotIn("--share-net", wrapped)
        self.assertIn("--die-with-parent", wrapped)
        bind_targets = [
            wrapped[index + 2]
            for index, value in enumerate(wrapped)
            if value == "--bind"
        ]
        self.assertEqual(
            bind_targets,
            [str(self.worktree), str(self.temp_path)],
        )

        control = self.workspace / "mac-profile"
        control.mkdir()
        macos = MacOSSandboxBackend(sys.executable)
        macos.wrap(policy, command, control)
        profile = (control / "sandbox.sb").read_text(encoding="utf-8")
        self.assertIn("(deny network*)", profile)
        self.assertIn(str(self.worktree).replace("\\", "\\\\"), profile)
        self.assertIn(str(self.temp_path).replace("\\", "\\\\"), profile)
        self.assertNotIn(str(self.workspace / "protected.txt"), profile)


if __name__ == "__main__":
    unittest.main()

