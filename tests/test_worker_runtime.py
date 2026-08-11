import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.models import Agent, ProviderResult, WorkItem
from agent_factory.providers import Provider
from agent_factory.storage import SQLiteStorage
from agent_factory.worker_runtime import (
    DirectCLIProviderDriver,
    DirectCLIWorkerRuntime,
    FallbackForbiddenError,
    HermesACPWorkerRuntime,
    RuntimeDriver,
    RuntimeDriverEvent,
    RuntimeLaunch,
)


class StructuredProvider(Provider):
    def __init__(self):
        self.name = "structured-cli"

    def health(self):
        return {"provider": self.name, "healthy": True}

    def execute(self, agent, item, context, approval=None):
        return ProviderResult(
            True,
            content=f"candidate:{item.id}",
            provider=self.name,
            metadata={
                "tool_calls": [
                    {"name": "read_file", "arguments": {"path": "README.md"}}
                ],
                "artifacts": [
                    {"kind": "trace", "sha256": "a" * 64}
                ],
            },
        )


class ScriptedACPDriver(RuntimeDriver):
    def __init__(self):
        self.sessions = {}
        self.resumes = 0
        self.heartbeats = 0

    def start(self, launch: RuntimeLaunch) -> str:
        external_id = f"acp-session-{len(self.sessions) + 1}"
        self.sessions[external_id] = {
            "status": "succeeded",
            "events": [
                RuntimeDriverEvent("status", {"state": "running"}),
                RuntimeDriverEvent("message", {"text": "working"}),
                RuntimeDriverEvent(
                    "tool_call",
                    {"name": "write_file", "arguments": {"path": "src/change.py"}},
                    mutable=launch.mutable,
                ),
                RuntimeDriverEvent(
                    "artifact", {"kind": "candidate_diff", "sha256": "b" * 64}
                ),
                RuntimeDriverEvent("status", {"state": "succeeded"}),
            ],
        }
        return external_id

    def resume(self, external_session_id: str) -> None:
        self.sessions[external_session_id]
        self.resumes += 1

    def heartbeat(self, external_session_id: str) -> None:
        self.sessions[external_session_id]
        self.heartbeats += 1

    def cancel(self, external_session_id: str) -> None:
        self.sessions[external_session_id]["status"] = "cancelled"

    def collect_events(self, external_session_id: str):
        session = self.sessions[external_session_id]
        events = list(session["events"])
        session["events"].clear()
        return events

    def finalize(self, external_session_id: str) -> str:
        return self.sessions[external_session_id]["status"]


class WorkerRuntimeContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self.temporary.name) / "runtime.db")
        self.project_id = self.storage.create_project("Runtime", "AF-044")
        self.counter = 0

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def fixture(self, *, mutable: bool = False):
        self.counter += 1
        worker_id = f"worker-{self.counter}"
        task_id = self.storage.create_task(
            WorkItem(
                f"Task {self.counter}",
                "Exercise runtime lifecycle",
                self.project_id,
                permissions=["read_project", *( ["worktree_write"] if mutable else [])],
            )
        )
        claim = self.storage.claim_runnable_task(
            task_id,
            worker_id,
            "runtime-contract",
            conflict_domains=[f"path:worktree-{self.counter}"],
        )
        agent = Agent(
            worker_id,
            worker_id,
            "Implementation Worker",
            True,
            "runtime-contract",
            "Return structured evidence",
        )
        launch = RuntimeLaunch(
            claim.assignment_id,
            claim.fencing_token,
            agent,
            self.storage.get_task(task_id),
            {"scope": "contract-secret-content"},
            mutable=mutable,
            permission_bridge_id="bridge-1" if mutable else None,
        )
        return claim, launch

    def runtimes(self):
        direct_driver = DirectCLIProviderDriver(StructuredProvider())
        acp_driver = ScriptedACPDriver()
        return (
            ("direct", DirectCLIWorkerRuntime(self.storage, direct_driver), direct_driver),
            ("hermes-acp", HermesACPWorkerRuntime(self.storage, acp_driver), acp_driver),
        )

    def test_direct_and_hermes_share_complete_lifecycle_and_structured_result(self):
        for name, runtime, driver in self.runtimes():
            with self.subTest(runtime=name):
                _, launch = self.fixture()
                self.assertEqual(
                    runtime.operations,
                    {
                        "start",
                        "resume",
                        "heartbeat",
                        "cancel",
                        "collect_events",
                        "finalize",
                    },
                )
                session = runtime.start(launch)
                self.assertEqual(session.status, "running")
                self.assertTrue(session.external_session_id)
                heartbeat = runtime.heartbeat(session.id)
                self.assertTrue(heartbeat)
                events = runtime.collect_events(session.id)
                self.assertIn("tool_call", {event.kind for event in events})
                self.assertIn("artifact", {event.kind for event in events})

                self.storage.suspend_runtime_session(
                    session.id, reason="contract disconnect"
                )
                resumed_runtime = type(runtime)(self.storage, driver)
                resumed = resumed_runtime.resume(session.id)
                self.assertEqual(resumed.status, "running")
                result = resumed_runtime.finalize(session.id)
                self.assertEqual(result.status, "succeeded")
                self.assertTrue(result.tool_calls)
                self.assertTrue(result.artifacts)
                self.assertEqual(result.session.status, "succeeded")

                row = self.storage.runtime_session(session.id)
                request = json.loads(row["request_json"])
                self.assertNotIn("contract-secret-content", row["request_json"])
                self.assertEqual(len(request["context_sha256"]), 64)
                first_event = self.storage.runtime_events(session.id)[0]
                with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                    self.storage.db.execute(
                        "UPDATE runtime_session_events SET kind='error' WHERE id=?",
                        (first_event["id"],),
                    )

    def test_cancel_is_supported_and_idempotent_for_both_runtimes(self):
        for name, runtime, _ in self.runtimes():
            with self.subTest(runtime=name):
                _, launch = self.fixture()
                session = runtime.start(launch)
                cancelled = runtime.cancel(session.id, reason="operator stop")
                self.assertEqual(cancelled.status, "cancelled")
                self.assertEqual(runtime.cancel(session.id, reason="replay").status, "cancelled")
                self.assertEqual(runtime.finalize(session.id).status, "cancelled")

    def test_fallback_becomes_forbidden_after_first_mutable_event(self):
        for name, runtime, _ in self.runtimes():
            with self.subTest(runtime=name):
                _, launch = self.fixture(mutable=True)
                session = runtime.start(launch)
                if name == "direct":
                    with self.assertRaises(FallbackForbiddenError):
                        runtime.assert_fallback_allowed(session.id)
                else:
                    runtime.assert_fallback_allowed(session.id)
                runtime.collect_events(session.id)
                with self.assertRaises(FallbackForbiddenError):
                    runtime.assert_fallback_allowed(session.id)
                self.assertGreater(
                    runtime.session(session.id).mutable_action_count, 0
                )

    def test_hermes_mutation_requires_acp_permission_bridge_and_never_oneshot(self):
        _, mutable_launch = self.fixture(mutable=True)
        no_bridge = RuntimeLaunch(
            mutable_launch.assignment_id,
            mutable_launch.fencing_token,
            mutable_launch.agent,
            mutable_launch.item,
            mutable_launch.context,
            mutable=True,
        )
        with self.assertRaisesRegex(PermissionError, "permission bridge"):
            HermesACPWorkerRuntime(
                self.storage, ScriptedACPDriver()
            ).start(no_bridge)
        with self.assertRaisesRegex(PermissionError, "one-shot"):
            HermesACPWorkerRuntime(
                self.storage,
                ScriptedACPDriver(),
                transport_mode="oneshot",
            ).start(mutable_launch)

        _, readonly_launch = self.fixture()
        oneshot = HermesACPWorkerRuntime(
            self.storage,
            ScriptedACPDriver(),
            transport_mode="oneshot",
        )
        session = oneshot.start(readonly_launch)
        self.assertEqual(oneshot.finalize(session.id).status, "succeeded")


if __name__ == "__main__":
    unittest.main()
