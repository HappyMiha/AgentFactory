import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agent_factory.models import Agent, ExecutionApproval, WorkItem
from agent_factory.providers import CLIProvider, ProcessSupervisor
from agent_factory.runtime import AgentRuntime
from agent_factory.storage import SQLiteStorage

REQUEST_HASH = "a" * 64
DEFINITION_HASH = "b" * 64
DRIFTED_REQUEST_HASH = "c" * 64
DRIFTED_DEFINITION_HASH = "d" * 64


class FakeProcess:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int | None = 0):
        self.pid = 31415
        self.returncode = returncode
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self.stdin = io.StringIO()

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired(["provider"], timeout)
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


class TrackingSupervisor(ProcessSupervisor):
    def __init__(self):
        super().__init__()
        self.terminated = threading.Event()

    def terminate_tree(self, proc):
        self.terminated.set()
        proc.kill()
        return {"tree_terminated": True}


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

    def test_execution_falls_back_only_when_first_launcher_cannot_start(self):
        process = FakeProcess(stdout="second launcher worked")
        supervisor = Mock()
        supervisor.spawn.side_effect = [PermissionError(5, "Access is denied"), process]
        provider = CLIProvider(
            "test", "provider.exe", ["fixed"], allow_execution=True, supervisor=supervisor
        )
        with patch.object(
            provider, "_executable_paths", return_value=["blocked.exe", "working.exe"]
        ):
            result = provider.execute(
                self.agent, self.item, {}, ExecutionApproval(6, "test", "worker", 7)
            )
        self.assertTrue(result.ok)
        self.assertEqual(result.content, "second launcher worked")
        self.assertEqual(supervisor.spawn.call_count, 2)
        self.assertEqual(result.metadata["executable"], "working.exe")
        self.assertEqual(
            result.metadata["launcher_failures"],
            [
                {
                    "launcher": "blocked.exe",
                    "error_type": "PermissionError",
                    "errno": 5,
                    "winerror": None,
                }
            ],
        )

    def test_all_launchers_failing_returns_sanitized_diagnostics(self):
        supervisor = Mock()
        supervisor.spawn.side_effect = [
            PermissionError(5, "private first path"),
            OSError(2, "private second path"),
        ]
        provider = CLIProvider(
            "test", "provider.exe", [], allow_execution=True, supervisor=supervisor
        )
        with patch.object(
            provider, "_executable_paths", return_value=["first.exe", "second.exe"]
        ):
            result = provider.execute(
                self.agent, self.item, {}, ExecutionApproval(7, "test", "worker", 7)
            )
        self.assertFalse(result.ok)
        self.assertIn("failed before process start", result.error)
        self.assertEqual(supervisor.spawn.call_count, 2)
        serialized = json.dumps(result.metadata)
        self.assertNotIn("private first path", serialized)
        self.assertNotIn("private second path", serialized)
        self.assertEqual(
            [failure["launcher"] for failure in result.metadata["launcher_failures"]],
            ["first.exe", "second.exe"],
        )

    def test_execution_never_falls_back_after_a_process_starts(self):
        process = FakeProcess(stderr="provider rejected request", returncode=2)
        supervisor = Mock()
        supervisor.spawn.return_value = process
        provider = CLIProvider(
            "test", "provider.exe", [], allow_execution=True, supervisor=supervisor
        )
        with patch.object(
            provider, "_executable_paths", return_value=["started.exe", "unused.exe"]
        ):
            result = provider.execute(
                self.agent, self.item, {}, ExecutionApproval(8, "test", "worker", 7)
            )
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "provider rejected request")
        supervisor.spawn.assert_called_once()

    def test_provider_subprocess_uses_utf8_with_replacement(self):
        process = FakeProcess(stdout="ready")
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
        process = FakeProcess(returncode=None)
        supervisor = Mock()
        supervisor.spawn.return_value = process
        supervisor.terminate_tree.side_effect = lambda target: (
            target.kill() or {"tree_terminated": True}
        )
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

    def test_output_overflow_terminates_tree_and_retains_bounded_metadata(self):
        supervisor = TrackingSupervisor()
        provider = CLIProvider(
            "test",
            sys.executable,
            [
                "-c",
                "import sys\nwhile True:\n sys.stdout.write('x' * 4096)\n sys.stdout.flush()",
            ],
            allow_execution=True,
            max_timeout=10,
            max_output_chars=1024,
            supervisor=supervisor,
        )
        result = provider.execute(
            self.agent, self.item, {}, ExecutionApproval(9, "test", "worker", 7)
        )
        self.assertFalse(result.ok)
        self.assertTrue(result.metadata["output_limit_exceeded"])
        self.assertTrue(result.metadata["output_truncated"])
        self.assertLessEqual(result.metadata["retained_output_chars"], 1024)
        self.assertGreater(result.metadata["observed_output_chars"], 1024)
        self.assertTrue(result.metadata["tree_terminated"])
        self.assertTrue(supervisor.terminated.is_set())

    def test_argument_transport_places_prompt_once_but_redacts_metadata(self):
        process = FakeProcess(stdout="ok")
        supervisor = Mock()
        supervisor.spawn.return_value = process
        provider = CLIProvider(
            "test",
            sys.executable,
            ["fixed"],
            prompt_transport="argument",
            allow_execution=True,
            supervisor=supervisor,
        )
        result = provider.execute(
            self.agent,
            self.item,
            {"marker": "prompt-only-value"},
            ExecutionApproval(10, "test", "worker", 7),
        )
        self.assertTrue(result.ok)
        command = supervisor.spawn.call_args.args[0]
        self.assertEqual(command[:2], [sys.executable, "fixed"])
        self.assertIn("prompt-only-value", command[-1])
        self.assertEqual(command.count(command[-1]), 1)
        self.assertNotIn("prompt-only-value", json.dumps(result.metadata))

    def test_disabled_provider_and_role_denial_never_spawn(self):
        supervisor = Mock()
        disabled = CLIProvider(
            "test", sys.executable, [], allow_execution=False, supervisor=supervisor
        )
        result = disabled.execute(
            self.agent, self.item, {}, ExecutionApproval(11, "test", "worker", 7)
        )
        self.assertFalse(result.ok)
        self.assertIn("disabled", result.error)

        denied = CLIProvider(
            "test",
            sys.executable,
            [],
            allow_execution=True,
            allowed_roles=["Different Role"],
            supervisor=supervisor,
        )
        result = denied.execute(
            self.agent, self.item, {}, ExecutionApproval(12, "test", "worker", 7)
        )
        self.assertFalse(result.ok)
        self.assertIn("not allowlisted", result.error)
        supervisor.spawn.assert_not_called()

    def test_sensitive_environment_is_removed_unless_explicitly_allowed(self):
        provider = CLIProvider(
            "test",
            sys.executable,
            [],
            allowed_sensitive_env=["ALLOWED_API_KEY"],
        )
        with patch.dict(
            os.environ,
            {
                "PATH": "safe-path",
                "HIDDEN_TOKEN": "remove-me",
                "ALLOWED_API_KEY": "keep-me",
                "SERVICE_AUTH": "remove-me-too",
            },
            clear=True,
        ):
            environment = provider._safe_environment()
        self.assertEqual(environment["PATH"], "safe-path")
        self.assertEqual(environment["ALLOWED_API_KEY"], "keep-me")
        self.assertNotIn("HIDDEN_TOKEN", environment)
        self.assertNotIn("SERVICE_AUTH", environment)

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
            {
                "deterministic",
                "codex",
                "claude",
                "gemini",
                "antigravity",
                "ollama",
                "openclaw",
            },
        )
        antigravity = providers["antigravity"]
        self.assertEqual(antigravity.prompt_transport, "argument")
        self.assertEqual(
            antigravity.args,
            (
                "--output-format",
                "text",
                "--mode",
                "plan",
                "--sandbox",
                "--disable-slash-commands",
                "--print",
            ),
        )
        self.assertTrue(antigravity.allow_execution)
        self.assertIn("Implementation Worker", antigravity.allowed_roles)
        self.assertFalse(providers["openclaw"].allow_execution)

    def test_provider_gate_is_one_time_and_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "test.db")
            _, task_id = create_test_task(storage)
            gate_id = storage.request_provider_execution(
                "codex",
                "coding-worker-codex",
                task_id,
                REQUEST_HASH,
                DEFINITION_HASH,
            )
            storage.decide_provider_execution(gate_id, "approved", "Run once")
            row = storage.claim_provider_execution(
                gate_id, REQUEST_HASH, DEFINITION_HASH
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
                    gate_id, REQUEST_HASH, DEFINITION_HASH
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
                "gemini",
                "coding-worker-gemini",
                task_id,
                REQUEST_HASH,
                DEFINITION_HASH,
            )
            storage.decide_provider_execution(gate_id, "approved", "smoke")
            storage.cancel_provider_execution(gate_id, "replaced by bounded canary")
            gate = storage.db.execute(
                "SELECT * FROM provider_execution_gates WHERE id=?", (gate_id,)
            ).fetchone()
            self.assertEqual(gate["status"], "rejected")
            with self.assertRaises(PermissionError):
                storage.claim_provider_execution(
                    gate_id, REQUEST_HASH, DEFINITION_HASH
                )
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
                "ollama",
                "coding-worker-ollama",
                task_id,
                REQUEST_HASH,
                DEFINITION_HASH,
            )
            storage.decide_provider_execution(gate_id, "approved", "Run once")
            attempt = storage.claim_provider_execution(
                gate_id, REQUEST_HASH, DEFINITION_HASH
            )
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
                storage.claim_provider_execution(
                    gate_id, REQUEST_HASH, DEFINITION_HASH
                )
            storage.close()

    def test_gate_snapshot_is_stored_and_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "test.db")
            _, task_id = create_test_task(storage)
            gate_id = storage.request_provider_execution(
                "codex",
                "coding-worker-codex",
                task_id,
                REQUEST_HASH,
                DEFINITION_HASH,
            )
            gate = storage.db.execute(
                "SELECT * FROM provider_execution_gates WHERE id=?", (gate_id,)
            ).fetchone()
            self.assertEqual(gate["request_hash"], REQUEST_HASH)
            self.assertEqual(gate["definition_hash"], DEFINITION_HASH)
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "approval snapshot is immutable"
            ):
                storage.db.execute(
                    "UPDATE provider_execution_gates SET request_hash=? WHERE id=?",
                    (DRIFTED_REQUEST_HASH, gate_id),
                )
            storage.close()

    def test_snapshot_mismatch_invalidates_gate_and_requires_new_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "test.db")
            _, task_id = create_test_task(storage)
            gate_id = storage.request_provider_execution(
                "codex",
                "coding-worker-codex",
                task_id,
                REQUEST_HASH,
                DEFINITION_HASH,
            )
            storage.decide_provider_execution(gate_id, "approved", "Exact snapshot")
            with self.assertRaisesRegex(PermissionError, "request a new gate"):
                storage.claim_provider_execution(
                    gate_id, DRIFTED_REQUEST_HASH, DEFINITION_HASH
                )
            gate = storage.db.execute(
                "SELECT status,decision_note FROM provider_execution_gates WHERE id=?",
                (gate_id,),
            ).fetchone()
            self.assertEqual(gate["status"], "rejected")
            self.assertIn("snapshot", gate["decision_note"].lower())
            self.assertEqual(
                storage.db.execute(
                    "SELECT count(*) FROM provider_execution_attempts"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                storage.db.execute(
                    "SELECT count(*) FROM events WHERE event_type='provider.execution.snapshot_mismatch'"
                ).fetchone()[0],
                1,
            )
            replacement = storage.request_provider_execution(
                "codex",
                "coding-worker-codex",
                task_id,
                DRIFTED_REQUEST_HASH,
                DEFINITION_HASH,
            )
            self.assertGreater(replacement, gate_id)
            storage.close()

    def test_direct_storage_api_rejects_non_sha256_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "test.db")
            _, task_id = create_test_task(storage)
            with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
                storage.request_provider_execution(
                    "codex", "coding-worker-codex", task_id, "short", DEFINITION_HASH
                )
            gate_id = storage.request_provider_execution(
                "codex",
                "coding-worker-codex",
                task_id,
                REQUEST_HASH,
                DEFINITION_HASH,
            )
            storage.decide_provider_execution(gate_id, "approved", "Exact snapshot")
            with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
                storage.claim_provider_execution(
                    gate_id, REQUEST_HASH, DRIFTED_DEFINITION_HASH.upper()
                )
            self.assertEqual(
                storage.db.execute(
                    "SELECT status FROM provider_execution_gates WHERE id=?",
                    (gate_id,),
                ).fetchone()[0],
                "approved",
            )
            storage.close()


if __name__ == "__main__":
    unittest.main()
