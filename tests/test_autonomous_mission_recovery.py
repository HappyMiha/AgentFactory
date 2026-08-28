import sqlite3
import unittest
from pathlib import Path

from agent_factory.coding_delivery import AutonomousCodingDeliveryService
from agent_factory.control_plane import (
    MissionControlFenceService,
    MissionOperationKind,
)
from agent_factory.durable_workflow import (
    DurableWorkflowExecution,
    MissionOperationJournal,
    ObservationStatus,
    OperationClass,
    OperationLifecycle,
    OperationObservation,
    ReconciliationPolicy,
)
from agent_factory.environment_bootstrap import EnvironmentOperationReconciler
from agent_factory.local_recovery import (
    LocalRecoveryService,
    MissionRecoveryDisposition,
)
from agent_factory.mission_checkpoints import (
    MissionCheckpointService,
    MissionCheckpointType,
)
from agent_factory.models import WorkItem
from agent_factory.storage import SQLiteStorage
from tests.test_autonomous_child_orchestration import AutonomousChildFixture
from tests.test_autonomous_preapproval_workflow import run_git
from tests.test_durable_workflow import definition


class AutonomousMissionRecoveryTests(AutonomousChildFixture, unittest.TestCase):
    def setUp(self):
        self.create_fixture()
        self.journal = MissionOperationJournal(self.storage)

    def tearDown(self):
        self.close_fixture()

    def reserve(
        self,
        operation_class: OperationClass,
        key: str,
        *,
        fault: str,
        request: dict | None = None,
    ):
        return self.journal.reserve(
            mission_id=self.mission.id,
            operation_key=key,
            operation_class=operation_class,
            request={"fault": fault, **(request or {})},
            reconciliation_policy=ReconciliationPolicy.VERIFY_THEN_RETRY,
            actor="Recovery Test",
        )

    def test_kill_point_fault_matrix_covers_every_typed_mutation(self):
        reservations: dict[tuple[OperationClass, str], int] = {}
        accepted_counts: dict[OperationClass, int] = {}
        for operation_class in OperationClass:
            before = self.reserve(
                operation_class,
                f"{operation_class.value}:before",
                fault="before",
            )
            reservations[(operation_class, "before")] = before.operation.id

            during = self.reserve(
                operation_class,
                f"{operation_class.value}:during",
                fault="during",
            )
            self.journal.start(
                during.operation.id,
                event_key=f"{operation_class.value}:during:start",
            )
            reservations[(operation_class, "during")] = during.operation.id

            after = self.reserve(
                operation_class,
                f"{operation_class.value}:after",
                fault="after",
            )
            self.journal.start(
                after.operation.id,
                event_key=f"{operation_class.value}:after:start",
            )
            accepted_counts[operation_class] = 1
            reservations[(operation_class, "after")] = after.operation.id

        def observe(operation):
            if operation.request["fault"] == "after":
                return OperationObservation.present(
                    {"accepted": True, "operation": operation.operation_class.value},
                    evidence={"probe": "fault-matrix"},
                )
            return OperationObservation.absent(
                evidence={"probe": "fault-matrix"}
            )

        recovery = LocalRecoveryService(self.storage).reconstruct_mission(
            self.mission.id,
            recovery_key="fault-matrix-restart",
            actor="Recovery Test",
            reconcilers={operation_class: observe for operation_class in OperationClass},
        )

        self.assertEqual(recovery.disposition, MissionRecoveryDisposition.RESUME_SAFE)
        self.assertTrue(recovery.replay_safe)
        for operation_class in OperationClass:
            with self.subTest(operation_class=operation_class.value, fault="before"):
                self.assertEqual(
                    self.journal.get(
                        reservations[(operation_class, "before")]
                    ).latest_event.lifecycle,
                    OperationLifecycle.RETRY_READY,
                )
            with self.subTest(operation_class=operation_class.value, fault="during"):
                self.assertEqual(
                    self.journal.get(
                        reservations[(operation_class, "during")]
                    ).latest_event.lifecycle,
                    OperationLifecycle.RETRY_READY,
                )
            with self.subTest(operation_class=operation_class.value, fault="after"):
                operation = self.journal.get(
                    reservations[(operation_class, "after")]
                )
                self.assertEqual(
                    operation.latest_event.lifecycle,
                    OperationLifecycle.RECONCILED,
                )
                replay = self.reserve(
                    operation_class,
                    f"{operation_class.value}:after",
                    fault="after",
                )
                if replay.execute:
                    accepted_counts[operation_class] += 1
                self.assertFalse(replay.execute)
                self.assertEqual(accepted_counts[operation_class], 1)
        for mutation_class in (
            OperationClass.INSTALLATION,
            OperationClass.SERVICE,
            OperationClass.GIT_INTEGRATION,
        ):
            self.assertEqual(accepted_counts[mutation_class], 1)
        self.assertTrue(self.storage.verify_audit_chain()["ok"])

    def test_idempotency_binding_lifecycle_and_evidence_are_immutable(self):
        reservation = self.reserve(
            OperationClass.COMMAND,
            "command:stable",
            fault="normal",
            request={"argv": ["tool", "--check"]},
        )
        replay = self.reserve(
            OperationClass.COMMAND,
            "command:stable",
            fault="normal",
            request={"argv": ["tool", "--check"]},
        )
        self.assertFalse(replay.created)
        self.assertEqual(replay.operation.request_digest, reservation.operation.request_digest)
        self.assertEqual(len(replay.operation.request_digest), 64)
        started = self.journal.start(
            reservation.operation.id,
            event_key="command:stable:start",
        )
        self.assertEqual(started.latest_event.lifecycle, OperationLifecycle.RUNNING)
        self.journal.start(
            reservation.operation.id,
            event_key="command:stable:start",
        )
        completed = self.journal.complete(
            reservation.operation.id,
            event_key="command:stable:complete",
            result={"exit_code": 0},
            evidence={"stdout_digest": "a" * 64},
        )
        self.assertEqual(completed.latest_event.lifecycle, OperationLifecycle.COMPLETED)
        self.assertEqual(len(completed.latest_event.result_digest), 64)
        self.assertEqual(len(completed.latest_event.evidence_digest), 64)
        self.journal.complete(
            reservation.operation.id,
            event_key="command:stable:complete",
            result={"exit_code": 0},
            evidence={"stdout_digest": "a" * 64},
        )
        with self.assertRaisesRegex(ValueError, "bound to a different request"):
            self.reserve(
                OperationClass.COMMAND,
                "command:stable",
                fault="normal",
                request={"argv": ["different"]},
            )
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE autonomous_mission_operations SET actor='changed' WHERE id=?",
                (reservation.operation.id,),
            )

    def test_unknown_environment_result_is_observed_and_secrets_are_redacted(self):
        reservation = self.reserve(
            OperationClass.MODEL_LIFECYCLE,
            "model:load",
            fault="during",
            request={"desired_state": "ready", "model": "local-model"},
        )
        self.journal.start(
            reservation.operation.id,
            event_key="model:load:start",
        )
        environment = EnvironmentOperationReconciler(
            {
                OperationClass.MODEL_LIFECYCLE: lambda _request: {
                    "state": "ready",
                    "token": "must-not-persist",
                }
            }
        )
        recovery = LocalRecoveryService(self.storage).reconstruct_mission(
            self.mission.id,
            recovery_key="model-restart",
            actor="Recovery Test",
            reconcilers={OperationClass.MODEL_LIFECYCLE: environment.observe},
        )
        operation = self.journal.get(reservation.operation.id)
        self.assertTrue(recovery.replay_safe)
        self.assertEqual(operation.latest_event.lifecycle, OperationLifecycle.RECONCILED)
        self.assertEqual(operation.latest_event.result["token"], "<redacted>")

    def test_sqlite_reopen_reconciles_once_and_recovery_key_replays(self):
        reservation = self.reserve(
            OperationClass.INSTALLATION,
            "install:package",
            fault="after",
            request={"package": "example", "desired_state": "installed"},
        )
        self.journal.start(
            reservation.operation.id,
            event_key="install:package:start",
        )
        operation_id = reservation.operation.id
        self.storage.close()
        self.storage = SQLiteStorage(self.database)
        self.journal = MissionOperationJournal(self.storage)
        self.journal.mark_unknown(
            operation_id,
            event_key=(
                f"sqlite-reopen:operation:{operation_id}:mark-unknown"
            ),
            evidence={"simulated_crash": "after-unknown-before-recovery-record"},
        )
        service = LocalRecoveryService(self.storage)
        observer = lambda _operation: OperationObservation.present(
            {"package": "example", "state": "installed"},
            evidence={"probe": "package-manager"},
        )
        first = service.reconstruct_mission(
            self.mission.id,
            recovery_key="sqlite-reopen",
            actor="Recovery Test",
            reconcilers={OperationClass.INSTALLATION: observer},
        )
        decision_count = self.storage.db.execute(
            """SELECT COUNT(*) FROM autonomous_mission_recovery_decisions
                WHERE recovery_id=?""",
            (first.id,),
        ).fetchone()[0]
        replay = service.reconstruct_mission(
            self.mission.id,
            recovery_key="sqlite-reopen",
            actor="Different Replay Actor",
            reconcilers={OperationClass.INSTALLATION: observer},
        )
        self.assertEqual(replay, first)
        self.assertEqual(
            self.storage.db.execute(
                """SELECT COUNT(*) FROM autonomous_mission_recovery_decisions
                    WHERE recovery_id=?""",
                (first.id,),
            ).fetchone()[0],
            decision_count,
        )
        self.assertEqual(
            self.journal.get(operation_id).latest_event.lifecycle,
            OperationLifecycle.RECONCILED,
        )
        decision_types = {decision.decision_type for decision in first.decisions}
        self.assertIn("OPERATION_MARKED_UNKNOWN", decision_types)
        self.assertIn("OPERATION_RECONCILED", decision_types)

    def test_real_git_integration_is_adopted_without_duplicate_commit(self):
        target_branch = run_git(self.repository, "branch", "--show-current")
        run_git(self.repository, "checkout", "-b", "recovery-source")
        (self.repository / "integrated.txt").write_text(
            "accepted once\n", encoding="utf-8"
        )
        run_git(self.repository, "add", "integrated.txt")
        run_git(self.repository, "commit", "-m", "prepared recovery commit")
        commit_sha = run_git(self.repository, "rev-parse", "HEAD")
        run_git(self.repository, "checkout", target_branch)
        reservation = self.reserve(
            OperationClass.GIT_INTEGRATION,
            "git:integrate",
            fault="after",
            request={
                "repository_path": str(self.repository),
                "branch": target_branch,
                "commit_sha": commit_sha,
            },
        )
        self.journal.start(
            reservation.operation.id,
            event_key="git:integrate:start",
        )
        run_git(self.repository, "merge", "--ff-only", "recovery-source")
        accepted_count = int(run_git(self.repository, "rev-list", "--count", "HEAD"))

        recovery = LocalRecoveryService(self.storage).reconstruct_mission(
            self.mission.id,
            recovery_key="git-after-restart",
            actor="Recovery Test",
        )
        replay = self.reserve(
            OperationClass.GIT_INTEGRATION,
            "git:integrate",
            fault="after",
            request={
                "repository_path": str(self.repository),
                "branch": target_branch,
                "commit_sha": commit_sha,
            },
        )
        self.assertTrue(recovery.replay_safe)
        self.assertFalse(replay.execute)
        self.assertEqual(
            self.journal.get(reservation.operation.id).latest_event.lifecycle,
            OperationLifecycle.RECONCILED,
        )
        self.assertEqual(
            int(run_git(self.repository, "rev-list", "--count", "HEAD")),
            accepted_count,
        )

    def test_git_conflict_blocks_retry_and_persists_decision(self):
        target_branch = run_git(self.repository, "branch", "--show-current")
        run_git(self.repository, "checkout", "-b", "unmerged-source")
        (self.repository / "unmerged.txt").write_text("not integrated\n", encoding="utf-8")
        run_git(self.repository, "add", "unmerged.txt")
        run_git(self.repository, "commit", "-m", "unmerged recovery commit")
        commit_sha = run_git(self.repository, "rev-parse", "HEAD")
        run_git(self.repository, "checkout", target_branch)
        reservation = self.reserve(
            OperationClass.GIT_INTEGRATION,
            "git:conflict",
            fault="during",
            request={
                "repository_path": str(self.repository),
                "branch": target_branch,
                "commit_sha": commit_sha,
            },
        )
        self.journal.start(
            reservation.operation.id,
            event_key="git:conflict:start",
        )
        recovery = LocalRecoveryService(self.storage).reconstruct_mission(
            self.mission.id,
            recovery_key="git-conflict-restart",
            actor="Recovery Test",
        )
        self.assertEqual(
            recovery.disposition,
            MissionRecoveryDisposition.NEEDS_ATTENTION,
        )
        self.assertFalse(recovery.replay_safe)
        self.assertEqual(
            self.journal.get(reservation.operation.id).latest_event.lifecycle,
            OperationLifecycle.NEEDS_ATTENTION,
        )
        self.assertIn(
            "OPERATION_BLOCKED",
            {decision.decision_type for decision in recovery.decisions},
        )

    def test_artifact_and_audit_corruption_fail_closed_with_persisted_evidence(self):
        task_id = self.storage.create_task(
            WorkItem("Recovery evidence", "Integrity fixture", self.mission.project_id)
        )
        run_id = DurableWorkflowExecution(self.storage).start(
            project_id=self.mission.project_id,
            task_id=task_id,
            workflow=definition(),
            version="recovery-integrity-v1",
        )
        artifact_id = self.storage.add_artifact(
            run_id,
            "implementation",
            "worker",
            "local",
            "trusted evidence",
        )
        self.storage.db.execute(
            "UPDATE artifacts SET content='tampered evidence' WHERE id=?",
            (artifact_id,),
        )
        self.storage.db.execute("DROP TRIGGER events_no_update")
        self.storage.db.execute(
            "UPDATE events SET payload='{}' WHERE id=(SELECT MIN(id) FROM events)"
        )
        self.storage.db.commit()

        recovery = LocalRecoveryService(self.storage).reconstruct_mission(
            self.mission.id,
            recovery_key="integrity-corruption",
            actor="Recovery Test",
        )
        self.assertEqual(
            recovery.disposition,
            MissionRecoveryDisposition.NEEDS_ATTENTION,
        )
        self.assertFalse(recovery.replay_safe)
        self.assertFalse(recovery.integrity["artifacts"]["ok"])
        self.assertFalse(recovery.integrity["audit"]["ok"])
        self.assertIn(
            "INTEGRITY_FAILED",
            {decision.decision_type for decision in recovery.decisions},
        )

    def test_authoritative_snapshot_recovers_task_checkpoint_git_model_and_services(self):
        approved = self.approve_fixture()
        delivery = AutonomousCodingDeliveryService(self.storage, self.capabilities)
        delivery.enter_development(
            self.mission.id,
            expected_mission_version=approved.approval.result_mission_version,
            command_id="recovery-enter-development",
        )
        child = delivery.prepare_job(
            self.mission.id,
            "INFRA-001",
            execution_mode="simulation",
            workflow_definition_id="delivery",
            command_id="recovery-prepare-child",
        )
        mission = self.missions.get(self.mission.id)
        pending = tuple(
            str(row["stable_id"])
            for row in self.storage.db.execute(
                """SELECT stable_id FROM autonomous_backlog_items
                    WHERE revision_id=? AND executable=1 ORDER BY stable_id""",
                (mission.active_backlog_revision_id,),
            )
        )
        epoch = MissionCheckpointService(self.storage).get_epoch(
            mission.active_execution_epoch_id
        )
        checkpoint = MissionCheckpointService(self.storage).record_checkpoint(
            self.mission.id,
            expected_mission_version=mission.version,
            expected_backlog_revision_id=mission.active_backlog_revision_id,
            expected_execution_epoch_id=mission.active_execution_epoch_id,
            actor="Recovery Test",
            command_id="recovery-checkpoint",
            reason="Persist exact recovery boundary",
            checkpoint_type=MissionCheckpointType.MANUAL,
            git_commit_sha=run_git(self.repository, "rev-parse", "HEAD"),
            git_branch=epoch.epoch_branch,
            git_worktree_path=str(self.repository),
            completed_work_items=(),
            pending_work_items=pending,
            current_work_item=child.stable_item_id,
            service_manifest_version="services-v1",
            service_manifest_digest="d" * 64,
            validation_state={"status": "passing"},
        )
        service = self.journal.reserve(
            mission_id=self.mission.id,
            operation_key="service:required",
            operation_class=OperationClass.SERVICE,
            request={"service": "database", "desired_state": "running"},
            reconciliation_policy=ReconciliationPolicy.VERIFY_THEN_RETRY,
            actor="Recovery Test",
            child_job_id=child.id,
            stable_item_id=child.stable_item_id,
        )
        self.journal.start(service.operation.id, event_key="service:required:start")
        self.journal.complete(
            service.operation.id,
            event_key="service:required:complete",
            result={"state": "running"},
            evidence={"probe": "service-manager"},
        )
        fence = MissionControlFenceService(self.storage).current(self.mission.id)
        model_lease = MissionControlFenceService(self.storage).begin_operation(
            operation_id="recovery-model-lease",
            mission_id=self.mission.id,
            execution_epoch_id=child.execution_epoch_id,
            child_job_id=child.id,
            operation_kind=MissionOperationKind.INFERENCE,
            expected_fencing_token=fence.fencing_token,
            request={"model": "local-coder"},
        )

        recovery = LocalRecoveryService(self.storage).reconstruct_mission(
            self.mission.id,
            recovery_key="authoritative-snapshot",
            actor="Recovery Test",
        )
        snapshot = recovery.snapshot
        self.assertTrue(recovery.replay_safe)
        self.assertEqual(
            snapshot["active_backlog_revision"]["id"],
            child.backlog_revision_id,
        )
        self.assertEqual(
            snapshot["active_execution_epoch"]["id"],
            child.execution_epoch_id,
        )
        self.assertEqual(snapshot["active_task"]["child_job_id"], child.id)
        self.assertEqual(
            snapshot["last_committed_checkpoint"]["id"], checkpoint.id
        )
        self.assertEqual(snapshot["git_authority"]["status"], ObservationStatus.PRESENT)
        self.assertEqual(snapshot["model_lease"]["id"], model_lease.id)
        self.assertEqual(
            snapshot["required_services"]["manifest"]["version"],
            "services-v1",
        )
        self.assertEqual(
            snapshot["required_services"]["operations"][0]["service"],
            "database",
        )

    def test_general_workflow_mutations_are_typed_and_digest_bound(self):
        task_id = self.storage.create_task(
            WorkItem("Typed mutation", "Journal fixture", self.mission.project_id)
        )
        run_id = DurableWorkflowExecution(self.storage).start(
            project_id=self.mission.project_id,
            task_id=task_id,
            workflow=definition(),
            version="typed-mutation-v1",
        )
        row, created = self.storage.reserve_workflow_mutation(
            run_id=run_id,
            stage_key="policy-precheck",
            operation=OperationClass.INSTALLATION,
            idempotency_key="install:typed",
            request={"package": "example"},
            reconciliation_policy=ReconciliationPolicy.VERIFY_THEN_RETRY,
        )
        self.assertTrue(created)
        self.storage.transition_workflow_mutation(int(row["id"]), "running")
        self.storage.complete_workflow_mutation(
            int(row["id"]),
            {"state": "installed"},
            {"probe": "package-manager"},
        )
        completed = self.storage.db.execute(
            "SELECT * FROM workflow_mutations WHERE id=?", (row["id"],)
        ).fetchone()
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(len(completed["request_digest"]), 64)
        self.assertEqual(len(completed["result_digest"]), 64)
        self.assertEqual(len(completed["evidence_digest"]), 64)
        with self.assertRaises(ValueError):
            self.storage.reserve_workflow_mutation(
                run_id=run_id,
                stage_key="policy-precheck",
                operation="arbitrary-shell-side-effect",
                idempotency_key="invalid",
                request={},
            )


if __name__ == "__main__":
    unittest.main()
