import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agent_factory.models import Agent, ExecutionApproval, WorkItem
from agent_factory.providers import CLIProvider, ProcessSupervisor
from agent_factory.runtime import AgentRuntime
from agent_factory.storage import SQLiteStorage


def create_test_task(storage: SQLiteStorage) -> tuple[int, int]:
    project_id = storage.create_project("Test Project", "Isolated provider checks")
    task_id = storage.create_task(
        WorkItem(
            "Create a review artifact",
            "Return bounded evidence",
            project_id,
            acceptance_criteria=["Evidence is present"],
        )
    )
    return project_id, task_id


class ProviderExecutionTests(unittest.TestCase):
    def setUp(self):
        self.agent = Agent(
            "worker",
            "Worker",
            "Implementation Worker",
            True,
            "test",
            "Return an artifact",
            ["read_project", "create_artifact"],
        )
        self.item = WorkItem(
            "Task",
            "Describe the result",
            1,
            id=7,
            acceptance_criteria=["Has evidence"],
        )

    def test_execution_is_blocked_without_human_gate(self):
        provider = CLIProvider(
            "test", sys.executable, ["-c", "print(input())"], allow_execution=True
        )
        result = provider.execute(self.agent, self.item, {})
        self.assertFalse(result.ok)
        self.assertTrue(result.metadata["blocked"])
        self.assertIn("approval required", result.error)

    def test_approval_is_scoped_to_provider_agent_and_task(self):
        provider = CLIProvider(
            "test", sys.executable, ["-c", "print(input())"], allow_execution=True
        )
        wrong = ExecutionApproval(1, "other", "worker", 7)
        result = provider.execute(self.agent, self.item, {}, wrong)
        self.assertFalse(result.ok)
        self.assertIn("scope mismatch", result.error)

    def test_approved_execution_captures_output_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = CLIProvider(
                "test",
                sys.executable,
                ["-c", "import sys; print(sys.stdin.read())"],
                allow_execution=True,
                workspace=Path(tmp),
            )
            result = provider.execute(
                self.agent,
                self.item,
                {"safe": "context"},
                ExecutionApproval(3, "test", "worker", 7),
            )
            self.assertTrue(result.ok)
            self.assertIn("Protected paths (read-only): none configured", result.content)
            self.assertIn("Task: Task", result.content)
            self.assertEqual(result.metadata["gate_id"], 3)
            self.assertNotIn("Task: Task", result.metadata["args"])

    def test_executable_candidates_precede_windows_store_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            native = Path(tmp) / "native-provider.exe"
            native.touch()
            with patch(
                "agent_factory.providers.shutil.which",
                return_value=r"C:\Program Files\WindowsApps\provider.exe",
            ):
                provider = CLIProvider(
                    "test",
                    "provider.exe",
                    [],
                    executable_candidates=[str(native)],
                )
                paths = provider._executable_paths()
            self.assertEqual(Path(paths[0]), native)
            self.assertIn("WindowsApps", paths[1])

    def test_health_falls_back_when_first_launcher_is_not_executable(self):
        provider = CLIProvider("test", "provider.exe", [])
        with patch.object(
            provider, "_executable_paths", return_value=["blocked.exe", "working.exe"]
        ):
            completed = subprocess.CompletedProcess(
                ["working.exe"], 0, "provider 1.0", ""
            )
            with patch(
                "agent_factory.providers.subprocess.run",
                side_effect=[PermissionError(5, "Access is denied"), completed],
            ):
                health = provider.health()
        self.assertTrue(health["healthy"])
        self.assertEqual(health["path"], "working.exe")
        self.assertEqual(health["version"], "provider 1.0")

    def test_provider_subprocess_uses_utf8_with_replacement(self):
        process = Mock(pid=31415, returncode=0)
        process.communicate.return_value = ("ready", "")
        supervisor = Mock()
        supervisor.spawn.return_value = process
        provider = CLIProvider(
            "test",
            sys.executable,
            ["safe"],
            allow_execution=True,
            supervisor=supervisor,
        )
        result = provider.execute(
            self.agent,
            self.item,
            {},
            ExecutionApproval(5, "test", "worker", 7),
        )
        self.assertTrue(result.ok)
        kwargs = supervisor.spawn.call_args.kwargs
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertEqual(kwargs["errors"], "replace")

    def test_timeout_uses_injected_tree_supervisor(self):
        process = Mock(pid=31415, returncode=None)
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(["safe"], 1),
            ("", ""),
        ]
        supervisor = Mock()
        supervisor.spawn.return_value = process
        supervisor.terminate_tree.return_value = {"tree_terminated": True}
        provider = CLIProvider(
            "test",
            sys.executable,
            ["safe"],
            allow_execution=True,
            max_timeout=1,
            supervisor=supervisor,
        )
        result = provider.execute(
            self.agent,
            self.item,
            {},
            ExecutionApproval(4, "test", "worker", 7),
        )
        self.assertFalse(result.ok)
        self.assertTrue(result.metadata["timed_out"])
        self.assertTrue(result.metadata["tree_terminated"])
        supervisor.terminate_tree.assert_called_once_with(process)

    def test_windows_cleanup_uses_fixed_argument_vector_without_shell(self):
        process = Mock(pid=1234)
        process.poll.return_value = None
        completed = Mock(returncode=0)
        with patch("agent_factory.providers.subprocess.run", return_value=completed) as run:
            result = ProcessSupervisor(windows=True).terminate_tree(process)
        self.assertTrue(result["tree_terminated"])
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["taskkill.exe", "/PID", "1234", "/T", "/F"])
        self.assertIs(kwargs["shell"], False)

    def test_windows_cleanup_rejects_invalid_pid_without_spawning_command(self):
        process = Mock(pid=0)
        with patch("agent_factory.providers.subprocess.run") as run:
            result = ProcessSupervisor(windows=True).terminate_tree(process)
        self.assertFalse(result["tree_terminated"])
        run.assert_not_called()

    def test_default_provider_catalog_is_portable_and_complete(self):
        providers = AgentRuntime().providers
        self.assertEqual(
            set(providers),
            {"deterministic", "codex", "claude", "gemini", "ollama", "openclaw"},
        )
        self.assertFalse(providers["openclaw"].allow_execution)

    def test_provider_gate_is_one_time_and_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "test.db")
            _, task_id = create_test_task(storage)
            gate_id = storage.request_provider_execution(
                "codex", "coding-worker-codex", task_id
            )
            storage.decide_provider_execution(gate_id, "approved", "Run once")
            row = storage.claim_provider_execution(
                gate_id, "request-hash", "definition-hash"
            )
            self.assertEqual(row["provider"], "codex")
            storage.mark_provider_attempt_running(int(row["id"]))
            artifact_id = storage.finish_provider_attempt(
                int(row["id"]), "succeeded", "reviewable result", {"ok": True}
            )
            self.assertGreater(artifact_id, 0)
            self.assertEqual(
                storage.provider_artifacts()[0]["content"], "reviewable result"
            )
            with self.assertRaises(PermissionError):
                storage.claim_provider_execution(
                    gate_id, "request-hash", "definition-hash"
                )
            events = [
                row[0]
                for row in storage.db.execute("SELECT event_type FROM events ORDER BY id")
            ]
            self.assertIn("provider.execution.requested", events)
            self.assertIn("provider.execution.approved", events)
            self.assertIn("provider.execution.claimed", events)
            self.assertIn("provider.execution.succeeded", events)
            storage.close()

    def test_human_can_cancel_unused_approved_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "test.db")
            _, task_id = create_test_task(storage)
            gate_id = storage.request_provider_execution(
                "gemini", "coding-worker-gemini", task_id
            )
            storage.decide_provider_execution(gate_id, "approved", "smoke")
            storage.cancel_provider_execution(gate_id, "replaced by bounded canary")
            gate = storage.db.execute(
                "SELECT * FROM provider_execution_gates WHERE id=?", (gate_id,)
            ).fetchone()
            self.assertEqual(gate["status"], "rejected")
            with self.assertRaises(PermissionError):
                storage.claim_provider_execution(gate_id, "r", "d")
            events = [
                row[0]
                for row in storage.db.execute("SELECT event_type FROM events ORDER BY id")
            ]
            self.assertIn("provider.execution.cancelled", events)
            storage.close()

    def test_interrupted_attempt_is_reconciled_and_gate_cannot_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "test.db")
            _, task_id = create_test_task(storage)
            gate_id = storage.request_provider_execution(
                "ollama", "coding-worker-ollama", task_id
            )
            storage.decide_provider_execution(gate_id, "approved", "Run once")
            attempt = storage.claim_provider_execution(gate_id, "r", "d")
            storage.mark_provider_attempt_running(int(attempt["id"]), 123)
            self.assertEqual(
                storage.reconcile_provider_attempts(), [int(attempt["id"])]
            )
            final = storage.db.execute(
                "SELECT status FROM provider_execution_attempts WHERE id=?",
                (attempt["id"],),
            ).fetchone()
            self.assertEqual(final["status"], "abandoned")
            with self.assertRaises(PermissionError):
                storage.claim_provider_execution(gate_id, "r", "d")
            storage.close()


if __name__ == "__main__":
    unittest.main()
