import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.models import WorkItem
from agent_factory.policy import ControlPlanePolicy, PolicyOutcome, PolicyRequest
from agent_factory.storage import SQLiteStorage


class PolicyPlaneTests(unittest.TestCase):
    def fixture(self, root: Path):
        storage = SQLiteStorage(root / "state.db")
        mission_id = storage.create_project("Example", "Policy checks")
        task_id = storage.create_task(WorkItem("Task", "Description", mission_id))
        return storage, mission_id, task_id

    @staticmethod
    def request(
        mission_id: int,
        task_id: int,
        *,
        permissions: tuple[str, ...],
        run_id: int | None = None,
        runtime_id: str = "hermes",
    ) -> PolicyRequest:
        return PolicyRequest(
            mission_id=mission_id,
            task_id=task_id,
            run_id=run_id,
            stage_id="implementation",
            worker_id="coding-worker-codex",
            runtime_id=runtime_id,
            worktree_id="worktree:task-1-attempt-1",
            permissions=permissions,
        )

    def test_policy_returns_allow_deny_and_require_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, mission_id, task_id = self.fixture(Path(tmp))
            policy = ControlPlanePolicy(storage)
            allowed = policy.evaluate(
                self.request(mission_id, task_id, permissions=("read_project",))
            )
            mutable = policy.evaluate(
                self.request(
                    mission_id,
                    task_id,
                    permissions=("read_project", "worktree_write"),
                )
            )
            denied = policy.evaluate(
                self.request(
                    mission_id,
                    task_id,
                    permissions=("read_project", "bypass_policy"),
                    runtime_id="hermes-skill",
                )
            )
            self.assertEqual(allowed.outcome, PolicyOutcome.ALLOW)
            self.assertEqual(mutable.outcome, PolicyOutcome.REQUIRE_APPROVAL)
            self.assertEqual(denied.outcome, PolicyOutcome.DENY)
            self.assertEqual(
                [row[0] for row in storage.db.execute("SELECT outcome FROM policy_decisions ORDER BY id")],
                ["allow", "require_approval", "deny"],
            )
            with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                storage.db.execute("UPDATE policy_decisions SET outcome='allow' WHERE outcome='deny'")
            storage.close()

    def test_exact_scoped_approval_is_one_use_and_digest_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, mission_id, task_id = self.fixture(Path(tmp))
            run_id = storage.start_run(mission_id, task_id, "delivery")
            policy = ControlPlanePolicy(storage)
            request = self.request(
                mission_id,
                task_id,
                run_id=run_id,
                permissions=("read_project", "worktree_write", "tool_use"),
            )
            approval_id = storage.request_scoped_approval(
                request=request.canonical(), requested_by="founder"
            )
            row = storage.db.execute(
                "SELECT * FROM scoped_execution_approvals WHERE id=?", (approval_id,)
            ).fetchone()
            self.assertEqual(row["task_id"], task_id)
            self.assertEqual(row["run_id"], run_id)
            self.assertEqual(row["stage_id"], "implementation")
            self.assertEqual(row["worker_id"], "coding-worker-codex")
            self.assertEqual(row["runtime_id"], "hermes")
            self.assertEqual(row["worktree_id"], "worktree:task-1-attempt-1")
            self.assertEqual(json.loads(row["permissions_json"]), sorted(request.permissions))
            self.assertEqual(row["request_digest"], request.digest)
            storage.decide_scoped_approval(
                approval_id, "approved", actor="founder", note="Exact execution approved"
            )

            changed = self.request(
                mission_id,
                task_id,
                run_id=run_id,
                permissions=request.permissions,
                runtime_id="direct-codex",
            )
            with self.assertRaisesRegex(PermissionError, "scope does not match"):
                policy.authorize(changed, approval_id=approval_id)

            decision = policy.authorize(request, approval_id=approval_id)
            self.assertEqual(decision.outcome, PolicyOutcome.ALLOW)
            self.assertEqual(decision.approval_id, approval_id)
            self.assertEqual(
                storage.db.execute(
                    "SELECT status FROM scoped_execution_approvals WHERE id=?", (approval_id,)
                ).fetchone()[0],
                "consumed",
            )
            with self.assertRaisesRegex(PermissionError, "consumed"):
                policy.authorize(request, approval_id=approval_id)
            with self.assertRaisesRegex(sqlite3.DatabaseError, "scope is immutable"):
                storage.db.execute(
                    "UPDATE scoped_execution_approvals SET runtime_id='other' WHERE id=?",
                    (approval_id,),
                )
            storage.close()

    def test_expired_approval_cannot_authorize_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, mission_id, task_id = self.fixture(Path(tmp))
            request = self.request(
                mission_id, task_id, permissions=("worktree_write",)
            )
            approval_id = storage.request_scoped_approval(
                request=request.canonical(), requested_by="founder"
            )
            storage.decide_scoped_approval(approval_id, "approved", actor="founder")
            storage.db.execute(
                "UPDATE scoped_execution_approvals SET expires_at='2000-01-01 00:00:00' WHERE id=?",
                (approval_id,),
            )
            storage.db.commit()
            with self.assertRaisesRegex(PermissionError, "expired"):
                ControlPlanePolicy(storage).authorize(request, approval_id=approval_id)
            self.assertEqual(
                storage.db.execute(
                    "SELECT status FROM scoped_execution_approvals WHERE id=?", (approval_id,)
                ).fetchone()[0],
                "expired",
            )
            storage.close()

    def test_emergency_stop_blocks_dispatch_and_cancels_mutable_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.db"
            storage, mission_id, task_id = self.fixture(Path(tmp))
            request_hash = "a" * 64
            definition_hash = "b" * 64
            gate_id = storage.request_provider_execution(
                "codex", "worker", task_id, request_hash, definition_hash
            )
            storage.decide_provider_execution(gate_id, "approved", "Approved")
            provider_attempt = storage.claim_provider_execution(
                gate_id, request_hash, definition_hash
            )
            storage.mark_provider_attempt_running(provider_attempt["id"], pid=123)
            assignment_id = storage.db.execute(
                "SELECT assignment_id FROM attempts WHERE provider_attempt_id=?",
                (provider_attempt["id"],),
            ).fetchone()[0]
            storage.db.execute(
                """INSERT INTO leases(
                       identity,assignment_id,fencing_token,status,expires_at
                   ) VALUES('lease:test',?,1,'active',datetime('now','+5 minutes'))""",
                (assignment_id,),
            )
            storage.db.commit()

            self.assertTrue(
                storage.set_emergency_stop(
                    True, actor="founder", reason="Unsafe runtime behavior"
                )
            )
            self.assertEqual(
                storage.db.execute(
                    "SELECT status FROM worker_sessions WHERE assignment_id=?",
                    (assignment_id,),
                ).fetchone()[0],
                "cancelled",
            )
            self.assertEqual(
                storage.db.execute(
                    "SELECT status FROM attempts WHERE assignment_id=?", (assignment_id,)
                ).fetchone()[0],
                "cancelled",
            )
            self.assertEqual(
                storage.db.execute(
                    "SELECT status FROM provider_execution_attempts WHERE id=?",
                    (provider_attempt["id"],),
                ).fetchone()[0],
                "abandoned",
            )
            self.assertEqual(
                storage.db.execute("SELECT status FROM leases WHERE assignment_id=?", (assignment_id,)).fetchone()[0],
                "revoked",
            )
            with self.assertRaisesRegex(PermissionError, "Emergency stop"):
                storage.start_run(mission_id, task_id, "blocked-delivery")
            denied = ControlPlanePolicy(storage).evaluate(
                self.request(mission_id, task_id, permissions=("read_project",))
            )
            self.assertEqual(denied.outcome, PolicyOutcome.DENY)
            storage.close()

            reopened = SQLiteStorage(path)
            self.assertTrue(reopened.policy_state()["emergency_stop"])
            self.assertTrue(
                reopened.set_emergency_stop(
                    False, actor="founder", reason="Incident resolved"
                )
            )
            run_id = reopened.start_run(mission_id, task_id, "resumed-delivery")
            self.assertGreater(run_id, 0)
            reopened.close()


if __name__ == "__main__":
    unittest.main()
