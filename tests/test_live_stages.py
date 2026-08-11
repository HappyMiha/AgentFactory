import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from agent_factory.context_packages import ContextPackageBuilder
from agent_factory.live_stages import LiveStageExecution
from agent_factory.models import Agent, ExecutionApproval, WorkItem
from agent_factory.policy import PolicyRequest
from agent_factory.storage import SQLiteStorage
from agent_factory.worker_runtime import (
    DirectCLIWorkerRuntime,
    RuntimeBinding,
    RuntimeDriver,
    RuntimeLaunch,
)


class TrackingDriver(RuntimeDriver):
    def __init__(self):
        self.starts = 0

    def start(self, launch, *, control_session_id=None):
        del launch, control_session_id
        self.starts += 1
        return f"tracking-{self.starts}"

    def resume(self, external_session_id):
        del external_session_id

    def heartbeat(self, external_session_id):
        del external_session_id

    def cancel(self, external_session_id):
        del external_session_id

    def collect_events(self, external_session_id):
        del external_session_id
        return []

    def finalize(self, external_session_id):
        del external_session_id
        return "succeeded"


class LiveStageExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.storage = SQLiteStorage(self.workspace / "state.db")
        self.project_id = self.storage.create_project("Live stages", "AF-046")
        self.counter = 0

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def fixture(self):
        self.counter += 1
        worker_id = f"live-worker-{self.counter}"
        task_id = self.storage.create_task(
            WorkItem(
                f"Live task {self.counter}",
                "Run one approved mutable stage",
                self.project_id,
                permissions=["read_project", "worktree_write"],
            )
        )
        run_id = self.storage.start_durable_run(
            project_id=self.project_id,
            task_id=task_id,
            workflow_id=f"live-{self.counter}",
            workflow_version="1",
            definition={"id": f"live-{self.counter}"},
            stages=[{"id": "implementation", "depends_on": []}],
        )
        self.storage.transition_durable_stage(
            run_id, "implementation", "running", {"reason": "dispatch"}
        )
        claim = self.storage.claim_runnable_task(
            task_id,
            worker_id,
            "direct-cli",
            conflict_domains=[f"path:live-{self.counter}"],
        )
        attempt_id = self.storage.create_assignment_attempt(
            claim.assignment_id, claim.fencing_token
        )
        worktree_id = self.storage.create_managed_worktree(
            assignment_id=claim.assignment_id,
            fencing_token=claim.fencing_token,
            repository=str(self.workspace / "repository"),
            base_sha="a" * 40,
            branch=f"agent-factory/live-{self.counter}",
            path=str(self.workspace / f"worktree-{self.counter}"),
            attempt_id=attempt_id,
        )
        self.storage.transition_managed_worktree(worktree_id, "ready")
        package = ContextPackageBuilder(self.storage, self.workspace).build(
            task_id=task_id,
            run_id=run_id,
            assignment_id=claim.assignment_id,
            fencing_token=claim.fencing_token,
            base_sha="a" * 40,
        )
        request = PolicyRequest(
            mission_id=self.project_id,
            task_id=task_id,
            run_id=run_id,
            stage_id="implementation",
            worker_id=worker_id,
            runtime_id="direct-cli",
            worktree_id=str(worktree_id),
            permissions=("read_project", "worktree_write"),
        )
        binding = RuntimeBinding(
            run_id=run_id,
            stage_id="implementation",
            attempt_id=attempt_id,
            worktree_id=worktree_id,
            allowed_tools=("read_file", "write_file"),
        )
        launch = RuntimeLaunch(
            assignment_id=claim.assignment_id,
            fencing_token=claim.fencing_token,
            agent=Agent(
                worker_id,
                worker_id,
                "Implementation Worker",
                True,
                "direct-cli",
                "Implement the bounded stage",
            ),
            item=self.storage.get_task(task_id),
            context=package.payload,
            context_digest=package.digest,
            binding=binding,
            mutable=True,
        )
        return run_id, request, launch

    @staticmethod
    def rejected_envelope(approval_id, request):
        return ExecutionApproval(
            gate_id=approval_id,
            provider=request.runtime_id,
            agent_id=request.worker_id,
            task_id=request.task_id,
            approved_by="founder",
            run_id=request.run_id,
            stage_id=request.stage_id,
            runtime_id=request.runtime_id,
            worktree_id=request.worktree_id,
            permissions=request.permissions,
            request_digest=request.digest,
        )

    def test_live_stage_waits_without_failing_the_workflow(self):
        run_id, request, _ = self.fixture()
        gate = LiveStageExecution(self.storage).request_approval(
            request, requested_by="founder"
        )
        stage = self.storage.durable_stages(run_id)[0]
        self.assertEqual(stage["status"], "waiting_approval")
        self.assertEqual(self.storage.durable_run(run_id)["status"], "running")
        self.assertEqual(gate.status, "pending")

    def test_approved_gate_is_exact_and_consumed_by_one_logical_attempt(self):
        run_id, request, launch = self.fixture()
        live = LiveStageExecution(self.storage)
        first = live.request_approval(request, requested_by="founder")
        approval = live.decide(first.approval_id, "approved", actor="founder")
        driver = TrackingDriver()
        runtime = DirectCLIWorkerRuntime(self.storage, driver)
        with self.assertRaisesRegex(PermissionError, "envelope"):
            runtime.start(
                replace(launch, approval=replace(approval, stage_id="validation"))
            )
        self.assertEqual(driver.starts, 0)
        runtime.start(replace(launch, approval=approval))
        consumption = self.storage.db.execute(
            "SELECT * FROM stage_approval_consumptions WHERE approval_id=?",
            (first.approval_id,),
        ).fetchone()
        self.assertEqual(consumption["attempt_id"], launch.binding.attempt_id)
        self.assertEqual(consumption["run_id"], run_id)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE stage_approval_consumptions SET assignment_id=999 WHERE id=?",
                (consumption["id"],),
            )

        second = live.request_approval(request, requested_by="founder")
        second_approval = live.decide(
            second.approval_id, "approved", actor="founder"
        )
        with self.assertRaisesRegex(PermissionError, "logical attempt"):
            runtime.start(replace(launch, approval=second_approval))
        self.assertEqual(driver.starts, 1)
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM worker_sessions"
            ).fetchone()[0],
            1,
        )

    def test_rejected_or_expired_gate_cannot_start_a_runtime(self):
        for outcome in ("rejected", "expired"):
            with self.subTest(outcome=outcome):
                _, request, launch = self.fixture()
                live = LiveStageExecution(self.storage)
                gate = live.request_approval(request, requested_by="founder")
                if outcome == "rejected":
                    live.decide(gate.approval_id, "rejected", actor="founder")
                else:
                    live.decide(gate.approval_id, "approved", actor="founder")
                    self.storage.db.execute(
                        """UPDATE scoped_execution_approvals
                              SET expires_at='2000-01-01 00:00:00' WHERE id=?""",
                        (gate.approval_id,),
                    )
                    self.storage.db.commit()
                approval = self.rejected_envelope(gate.approval_id, request)
                driver = TrackingDriver()
                with self.assertRaisesRegex(PermissionError, outcome):
                    DirectCLIWorkerRuntime(self.storage, driver).start(
                        replace(launch, approval=approval)
                    )
                self.assertEqual(driver.starts, 0)

    def test_completed_stage_advances_the_next_dependency_ready_stage(self):
        task_id = self.storage.create_task(
            WorkItem("Pipeline", "Advance dependency-ready stage", self.project_id)
        )
        run_id = self.storage.start_durable_run(
            project_id=self.project_id,
            task_id=task_id,
            workflow_id="pipeline",
            workflow_version="1",
            definition={"id": "pipeline"},
            stages=[
                {"id": "implementation", "depends_on": []},
                {"id": "validation", "depends_on": ["implementation"]},
                {"id": "review", "depends_on": ["validation"]},
            ],
        )
        self.storage.transition_durable_stage(
            run_id, "implementation", "running", {"reason": "dispatch"}
        )
        next_stage = LiveStageExecution(self.storage).complete_stage(
            run_id, "implementation", {"result": "candidate ready"}
        )
        states = {
            row["stage_key"]: row["status"]
            for row in self.storage.durable_stages(run_id)
        }
        self.assertEqual(next_stage, "validation")
        self.assertEqual(
            states,
            {
                "implementation": "succeeded",
                "validation": "running",
                "review": "pending",
            },
        )


if __name__ == "__main__":
    unittest.main()
