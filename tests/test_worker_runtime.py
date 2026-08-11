import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from agent_factory.context_packages import ContextPackageBuilder
from agent_factory.live_stages import LiveStageExecution
from agent_factory.models import Agent, ProviderResult, WorkItem
from agent_factory.policy import PolicyRequest
from agent_factory.providers import Provider
from agent_factory.storage import SQLiteStorage
from agent_factory.worker_runtime import (
    DirectCLIProviderDriver,
    DirectCLIWorkerRuntime,
    FallbackForbiddenError,
    HermesACPWorkerRuntime,
    RuntimeDriver,
    RuntimeDriverEvent,
    RuntimeBinding,
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

    def start(
        self, launch: RuntimeLaunch, *, control_session_id: int | None = None
    ) -> str:
        del control_session_id
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

    def fixture(self, *, mutable: bool = False, runtime_id: str = "direct-cli"):
        self.counter += 1
        worker_id = f"worker-{self.counter}"
        task_id = self.storage.create_task(
            WorkItem(
                f"Task {self.counter}",
                "Exercise runtime lifecycle",
                self.project_id,
                inputs={"requirements": ["contract-secret-content"]},
                permissions=["read_project", *( ["worktree_write"] if mutable else [])],
            )
        )
        run_id = self.storage.start_durable_run(
            project_id=self.project_id,
            task_id=task_id,
            workflow_id=f"runtime-{self.counter}",
            workflow_version="1",
            definition={"id": f"runtime-{self.counter}"},
            stages=[{"id": "runtime", "depends_on": []}],
        )
        self.storage.transition_durable_stage(
            run_id, "runtime", "running", {"reason": "dispatch"}
        )
        claim = self.storage.claim_runnable_task(
            task_id,
            worker_id,
            runtime_id,
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
        package = ContextPackageBuilder(
            self.storage, Path(self.temporary.name)
        ).build(
            task_id=task_id,
            run_id=run_id,
            assignment_id=claim.assignment_id,
            fencing_token=claim.fencing_token,
            base_sha="a" * 40,
        )
        launch = RuntimeLaunch(
            claim.assignment_id,
            claim.fencing_token,
            agent,
            self.storage.get_task(task_id),
            package.payload,
            package.digest,
            binding=None,
            approval=None,
            mutable=mutable,
            permission_bridge_id="bridge-1" if mutable else None,
        )
        if mutable:
            attempt_id = self.storage.create_assignment_attempt(
                claim.assignment_id, claim.fencing_token
            )
            worktree_id = self.storage.create_managed_worktree(
                assignment_id=claim.assignment_id,
                fencing_token=claim.fencing_token,
                repository=str(Path(self.temporary.name) / "repository"),
                base_sha="a" * 40,
                branch=f"agent-factory/task-{task_id}",
                path=str(Path(self.temporary.name) / f"worktree-{task_id}"),
                attempt_id=attempt_id,
            )
            self.storage.transition_managed_worktree(worktree_id, "ready")
            request = PolicyRequest(
                mission_id=self.project_id,
                task_id=task_id,
                run_id=run_id,
                stage_id="runtime",
                worker_id=worker_id,
                runtime_id=runtime_id,
                worktree_id=str(worktree_id),
                permissions=tuple(sorted(set(launch.item.permissions))),
            )
            live = LiveStageExecution(self.storage)
            gate = live.request_approval(request, requested_by="runtime-test")
            approval = live.decide(
                gate.approval_id, "approved", actor="runtime-test"
            )
            launch = replace(
                launch,
                binding=RuntimeBinding(
                    run_id=run_id,
                    stage_id="runtime",
                    attempt_id=attempt_id,
                    worktree_id=worktree_id,
                    allowed_tools=("read_file", "write_file"),
                ),
                approval=approval,
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
                _, launch = self.fixture(runtime_id=runtime.runtime_id)
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
                _, launch = self.fixture(runtime_id=runtime.runtime_id)
                session = runtime.start(launch)
                cancelled = runtime.cancel(session.id, reason="operator stop")
                self.assertEqual(cancelled.status, "cancelled")
                self.assertEqual(runtime.cancel(session.id, reason="replay").status, "cancelled")
                self.assertEqual(runtime.finalize(session.id).status, "cancelled")

    def test_fallback_becomes_forbidden_after_first_mutable_event(self):
        for name, runtime, _ in self.runtimes():
            with self.subTest(runtime=name):
                _, launch = self.fixture(mutable=True, runtime_id=runtime.runtime_id)
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
        _, mutable_launch = self.fixture(mutable=True, runtime_id="hermes-acp")
        no_bridge = RuntimeLaunch(
            mutable_launch.assignment_id,
            mutable_launch.fencing_token,
            mutable_launch.agent,
            mutable_launch.item,
            mutable_launch.context,
            mutable_launch.context_digest,
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

    def test_runtime_rejects_context_changed_after_package_creation(self):
        _, launch = self.fixture()
        tampered_context = {**launch.context, "base_sha": "b" * 40}
        tampered = replace(launch, context=tampered_context)
        with self.assertRaisesRegex(PermissionError, "immutable digest"):
            DirectCLIWorkerRuntime(
                self.storage, DirectCLIProviderDriver(StructuredProvider())
            ).start(tampered)
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM worker_sessions WHERE context_digest=?",
                (launch.context_digest,),
            ).fetchone()[0],
            0,
        )


if __name__ == "__main__":
    unittest.main()
