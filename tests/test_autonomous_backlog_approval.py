import copy
import sqlite3
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_factory.application import AgentFactoryService
from agent_factory.autonomous_authorization import (
    AuthorizationOperation,
    AuthorizationOutcome,
    AutonomousAuthorizationRequest,
    AutonomousAuthorizationService,
    PlanningAction,
)
from agent_factory.autonomous_backlog_approval import (
    AutonomousBacklogApprovalService,
    BacklogAlreadyApprovedError,
    BacklogApprovalCommandConflictError,
)
from agent_factory.autonomous_mission import (
    AutonomousMissionConfiguration,
    AutonomousMissionService,
    MissionPhase,
    MissionVersionConflictError,
)
from agent_factory.autonomous_planning import AutonomousPlanningService
from agent_factory.autonomous_planning_pipeline import (
    AutonomousPlanningPipelineService,
)
from agent_factory.autonomous_proposal_verifier import (
    AutonomousProposalVerificationService,
)
from agent_factory.backlog import BacklogProposal, ProposedItem
from agent_factory.backlog_revisions import (
    BacklogRevisionAuthorityCommandConflictError,
    BacklogRevisionAuthorityOutcome,
    BacklogRevisionOrigin,
    BacklogRevisionService,
)
from agent_factory.mission_intake import AutonomousMissionIntakeService
from agent_factory.models import ExecutionLocation, ProviderCapabilities
from agent_factory.storage import SQLiteStorage
from tests.test_autonomous_planning_pipeline import GoldenPlanningInvoker


def run_git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


class AutonomousBacklogApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.repository = self.workspace / "repository"
        self.repository.mkdir()
        run_git(self.repository, "init")
        run_git(self.repository, "config", "user.name", "Agent Factory Test")
        run_git(
            self.repository,
            "config",
            "user.email",
            "agent-factory@example.test",
        )
        (self.repository / "README.md").write_text(
            "# Approval mission\n", encoding="utf-8"
        )
        run_git(self.repository, "add", "README.md")
        run_git(self.repository, "commit", "-m", "initial")
        self.base_commit = run_git(self.repository, "rev-parse", "HEAD")

        self.storage = SQLiteStorage(self.workspace / "state.db")
        self.capabilities = {
            "local": ProviderCapabilities(
                execution_location=ExecutionLocation.LOCAL,
                location_declared=True,
                text_generation=True,
                structured_output=True,
                tool_calls=True,
            )
        }
        self.missions = AutonomousMissionService(self.storage)
        self.intake = AutonomousMissionIntakeService(self.storage)
        created = self.intake.create_from_text(
            name="Approval mission",
            mission_owner="Founder",
            specification=(
                "# Product\n\nBuild a safe local health endpoint with deterministic "
                "validation and local persistence."
            ),
            actor="Founder",
            command_id="create-approval-mission",
            mission_key="AFM-APPROVAL",
            configuration=AutonomousMissionConfiguration(
                repository_path=str(self.repository),
                default_model="local-planner",
                role_models={
                    "Developer": "local-coder",
                    "Environment Bootstrap": "local-coder",
                },
                local_provider_ids=("local",),
            ),
            source_name="specification.md",
        )
        self.mission = created.mission
        for phase, command_id in (
            (MissionPhase.SPECIFICATION_ANALYSIS, "approval-analyze"),
            (MissionPhase.BACKLOG_GENERATION, "approval-generate"),
        ):
            self.mission = self.missions.transition_phase(
                self.mission.id,
                phase,
                actor="Founder",
                command_id=command_id,
                expected_version=self.mission.version,
                reason="Advance the approval fixture",
            )
        self.planning = AutonomousPlanningService(
            self.storage, self.capabilities
        )
        self.authorizations = AutonomousAuthorizationService(
            self.storage, self.capabilities
        )
        self.verifications = AutonomousProposalVerificationService(self.storage)
        self.approvals = AutonomousBacklogApprovalService(
            self.storage, self.capabilities
        )
        self.revisions = BacklogRevisionService(self.storage)
        self.report = self._ready_report()
        self.mission = self.missions.get(self.mission.id)

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def _ready_report(self, *, reviewer_report=None):
        return self._report_for_mission(
            self.mission,
            prefix="approval",
            reviewer_report=reviewer_report,
        )

    def _report_for_mission(self, mission, *, prefix, reviewer_report=None):
        manifest = self.planning.create_manifest(
            mission.id,
            proposal_key=f"{prefix}-proposal",
            actor="Founder",
            command_id=f"{prefix}-manifest",
            default_provider_id="local",
        )
        authorization = self.authorizations.grant_planning_authority(
            mission.id,
            planning_request_id=manifest.proposal_key,
            requested_action=PlanningAction.ANALYZE,
            role_models={
                assignment.role_id: assignment.model
                for assignment in manifest.assignments
            },
            provider_ids=("local",),
            actor="Founder",
            command_id=f"authorize-{prefix}-planning",
            reason="Produce the exact proposal for approval",
        )
        invoker = GoldenPlanningInvoker()
        if reviewer_report is not None:
            invoker.outputs["backlog_reviewer"] = {
                "output": {"review_report": copy.deepcopy(reviewer_report)},
                "evidence": {
                    "findings": copy.deepcopy(reviewer_report["findings"])
                },
            }
        run = AutonomousPlanningPipelineService(
            self.storage, invoker, self.capabilities
        ).execute(
            mission.id,
            manifest_id=manifest.id,
            planning_authorization_id=authorization.id,
            actor="Founder",
            command_id=f"run-{prefix}-pipeline",
        )
        return self.verifications.verify_and_present(
            run.id,
            actor="Founder",
            command_id=f"verify-{prefix}-proposal",
            expected_mission_version=self.missions.get(mission.id).version,
        )

    def approval_arguments(self, **changes):
        values = {
            "expected_revision_id": self.report.revision_id,
            "expected_canonical_digest": self.report.canonical_digest,
            "expected_mission_version": self.mission.version,
            "base_git_commit_sha": self.base_commit,
            "epoch_branch": "autonomous/AFM-APPROVAL/epoch-1",
            "temporal_workflow_id": "autonomous-AFM-APPROVAL",
            "temporal_run_id": "temporal-run-1",
            "actor": "Founder",
            "command_id": "approve-and-start",
            "reason": "Approve the exact reviewed proposal",
            "authentication_context": {
                "schema_version": 1,
                "method": "authenticated-local-session",
                "subject": "Founder",
                "session_id": "session-7",
            },
        }
        values.update(changes)
        return values

    def execution_request(self, result, *, task_id: int):
        return AutonomousAuthorizationRequest(
            mission_id=self.mission.id,
            operation=AuthorizationOperation.LOCAL_INFERENCE,
            provider_id="local",
            agent_id=f"developer-{task_id}",
            task_id=task_id,
            role="Developer",
            model="local-coder",
            backlog_revision_id=result.approval.revision_id,
            backlog_revision_digest=result.approval.revision_digest,
            execution_epoch_id=result.execution_epoch.id,
            repository_path=str(self.repository),
            epoch_branch=result.execution_epoch.epoch_branch,
            tool_profile="autonomous-local-default",
            permissions=("execute_provider",),
            authorization_id=result.authorization.id,
        )

    @staticmethod
    def revised_proposal(revision, *items, marker: str):
        changed = tuple(
            replace(
                item,
                review_notes=(*item.review_notes, marker),
            )
            for item in revision.items
        )
        return BacklogProposal(
            source_path="autonomous://revision-authority",
            source_sha256=revision.source_sha256,
            source_name="Revision authority fixture",
            items=(*changed, *items),
            schema_version=revision.schema_version,
            extension_schema="agentfactory.rich-backlog/v1",
            planning_contract={"execution_rule": "Only executable items run"},
        )

    def counts(self):
        return {
            table: int(
                self.storage.db.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            )
            for table in (
                "autonomous_backlog_approvals",
                "autonomous_backlog_approval_completions",
                "autonomous_mission_execution_epochs",
                "autonomous_epoch_temporal_runs",
                "autonomous_local_authorizations",
                "provider_execution_attempts",
                "work_items",
            )
        }

    def test_one_human_action_atomically_starts_exact_local_mission(self):
        before = self.counts()
        self.assertEqual(
            before,
            {
                "autonomous_backlog_approvals": 0,
                "autonomous_backlog_approval_completions": 0,
                "autonomous_mission_execution_epochs": 0,
                "autonomous_epoch_temporal_runs": 0,
                "autonomous_local_authorizations": 0,
                "provider_execution_attempts": 0,
                "work_items": 0,
            },
        )

        result = AgentFactoryService(
            self.storage, workspace=self.workspace
        ).approve_autonomous_backlog_and_start(
            self.report.id,
            provider_capabilities=self.capabilities,
            **self.approval_arguments(),
        )

        approval = result.approval
        self.assertEqual(result.mission.phase, MissionPhase.APPROVED)
        self.assertEqual(result.mission.version, self.mission.version + 1)
        self.assertEqual(result.mission.active_backlog_revision_id, approval.revision_id)
        self.assertEqual(result.mission.active_execution_epoch_id, approval.execution_epoch_id)
        self.assertEqual(approval.verification_id, self.report.id)
        self.assertEqual(approval.revision_digest, self.report.revision_digest)
        self.assertEqual(approval.canonical_digest, self.report.canonical_digest)
        self.assertEqual(approval.approved_by, "Founder")
        self.assertEqual(approval.authentication_context["session_id"], "session-7")
        self.assertEqual(approval.policy_digest, result.authorization.policy_digest)
        self.assertEqual(
            approval.execution_role_model_manifest_digest,
            result.authorization.role_model_manifest_digest,
        )
        self.assertEqual(
            approval.execution_authorization_digest,
            result.authorization.authorization_digest,
        )
        self.assertEqual(result.execution_epoch.base_git_commit_sha, self.base_commit)
        self.assertEqual(
            result.execution_epoch.temporal_chain_metadata["start_state"],
            "APPROVED_NOT_DISPATCHED",
        )
        self.assertEqual(self.counts()["work_items"], 0)

        for task_id in (101, 102):
            decision = self.authorizations.resolve(
                self.execution_request(result, task_id=task_id)
            )
            self.assertEqual(decision.outcome, AuthorizationOutcome.ALLOW_AUTONOMOUS)
            self.assertTrue(decision.authority_valid)

        replay = self.approvals.approve_and_start(
            self.report.id, **self.approval_arguments()
        )
        self.assertEqual(replay.approval.id, approval.id)
        self.assertEqual(
            self.counts(),
            {
                "autonomous_backlog_approvals": 1,
                "autonomous_backlog_approval_completions": 1,
                "autonomous_mission_execution_epochs": 1,
                "autonomous_epoch_temporal_runs": 1,
                "autonomous_local_authorizations": 1,
                "provider_execution_attempts": 0,
                "work_items": 0,
            },
        )

    def test_mismatch_stale_actor_and_conflicting_duplicates_fail_closed(self):
        unchanged = self.counts()
        bad = (
            {"expected_revision_id": self.report.revision_id + 1},
            {"expected_canonical_digest": "0" * 64},
        )
        for change in bad:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.approvals.approve_and_start(
                        self.report.id,
                        **self.approval_arguments(**change),
                    )
                self.assertEqual(self.counts(), unchanged)
        with self.assertRaises(MissionVersionConflictError):
            self.approvals.approve_and_start(
                self.report.id,
                **self.approval_arguments(
                    expected_mission_version=self.mission.version - 1
                ),
            )
        with self.assertRaises(PermissionError):
            self.approvals.approve_and_start(
                self.report.id,
                **self.approval_arguments(actor="Mallory"),
            )
        with self.assertRaises(PermissionError):
            self.approvals.approve_and_start(
                self.report.id,
                **self.approval_arguments(
                    authentication_context={
                        "method": "authenticated-local-session",
                        "subject": "Mallory",
                    }
                ),
            )
        self.assertEqual(self.counts(), unchanged)

        accepted = self.approvals.approve_and_start(
            self.report.id, **self.approval_arguments()
        )
        with self.assertRaises(BacklogApprovalCommandConflictError):
            self.approvals.approve_and_start(
                self.report.id,
                **self.approval_arguments(reason="A conflicting replay"),
            )
        with self.assertRaises(BacklogAlreadyApprovedError):
            self.approvals.approve_and_start(
                self.report.id,
                **self.approval_arguments(command_id="second-approval-command"),
            )
        self.assertEqual(self.approvals.approvals(self.mission.id)[0].id, accepted.approval.id)

    def test_unverified_proposal_and_direct_phase_bypass_fail_closed(self):
        with self.assertRaises(KeyError):
            self.approvals.approve_and_start(
                self.report.id + 999,
                **self.approval_arguments(),
            )
        blocked_mission = self.intake.create_from_text(
            name="Blocked approval mission",
            mission_owner="Founder",
            specification=(
                "# Product\n\nBuild a safe local health endpoint with deterministic "
                "validation and local persistence."
            ),
            actor="Founder",
            command_id="create-blocked-approval-mission",
            mission_key="AFM-APPROVAL-BLOCKED",
            configuration=self.mission.configuration,
            source_name="specification.md",
        ).mission
        for phase, command_id in (
            (MissionPhase.SPECIFICATION_ANALYSIS, "blocked-analyze"),
            (MissionPhase.BACKLOG_GENERATION, "blocked-generate"),
        ):
            blocked_mission = self.missions.transition_phase(
                blocked_mission.id,
                phase,
                actor="Founder",
                command_id=command_id,
                expected_version=blocked_mission.version,
                reason="Advance the blocked approval fixture",
            )
        blocked = self._report_for_mission(
            blocked_mission,
            prefix="blocked-approval",
            reviewer_report={
                "verdict": "NEEDS_REPAIR",
                "summary": "The proposal requires another planning pass.",
                "findings": [],
            },
        )
        self.assertFalse(blocked.ready)
        with self.assertRaisesRegex(PermissionError, "unverified or blocked"):
            self.approvals.approve_and_start(
                blocked.id,
                **self.approval_arguments(
                    expected_revision_id=blocked.revision_id,
                    expected_canonical_digest=blocked.canonical_digest,
                    expected_mission_version=blocked_mission.version,
                    command_id="approve-blocked-proposal",
                    epoch_branch="autonomous/AFM-APPROVAL-BLOCKED/epoch-1",
                    temporal_workflow_id="autonomous-AFM-APPROVAL-BLOCKED",
                ),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.missions.transition_phase(
                self.mission.id,
                MissionPhase.APPROVED,
                actor="Founder",
                command_id="bypass-exact-approval",
                expected_version=self.mission.version,
                reason="Direct phase mutation must fail",
            )
        current = self.missions.get(self.mission.id)
        self.assertEqual(current.phase, MissionPhase.WAITING_FOR_BACKLOG_APPROVAL)
        self.assertIsNone(current.active_backlog_revision_id)
        self.assertEqual(self.counts()["autonomous_local_authorizations"], 0)

    def test_fault_rolls_back_every_approval_start_record_and_retry_succeeds(self):
        original_event = self.storage._event

        def fail_at_final_audit(event_type, *args, **kwargs):
            if event_type == "autonomous_backlog.approved":
                raise RuntimeError("injected approval audit failure")
            return original_event(event_type, *args, **kwargs)

        with patch.object(self.storage, "_event", side_effect=fail_at_final_audit):
            with self.assertRaisesRegex(RuntimeError, "injected approval"):
                self.approvals.approve_and_start(
                    self.report.id, **self.approval_arguments()
                )

        self.assertEqual(
            self.counts(),
            {
                "autonomous_backlog_approvals": 0,
                "autonomous_backlog_approval_completions": 0,
                "autonomous_mission_execution_epochs": 0,
                "autonomous_epoch_temporal_runs": 0,
                "autonomous_local_authorizations": 0,
                "provider_execution_attempts": 0,
                "work_items": 0,
            },
        )
        current = self.missions.get(self.mission.id)
        self.assertEqual(current.phase, MissionPhase.WAITING_FOR_BACKLOG_APPROVAL)
        self.assertEqual(current.version, self.mission.version)
        self.assertIsNone(current.active_backlog_revision_id)
        self.assertIsNone(current.active_execution_epoch_id)

        result = self.approvals.approve_and_start(
            self.report.id, **self.approval_arguments()
        )
        self.assertEqual(result.mission.phase, MissionPhase.APPROVED)

    def test_concurrent_exact_replay_commits_one_approval(self):
        def invoke():
            storage = SQLiteStorage(self.storage.path)
            try:
                result = AutonomousBacklogApprovalService(
                    storage, self.capabilities
                ).approve_and_start(
                    self.report.id, **self.approval_arguments()
                )
                return result.approval.id
            finally:
                storage.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            approval_ids = tuple(executor.map(lambda _: invoke(), range(2)))
        self.assertEqual(approval_ids[0], approval_ids[1])
        self.assertEqual(self.counts()["autonomous_backlog_approvals"], 1)
        self.assertEqual(self.counts()["autonomous_local_authorizations"], 1)
        self.assertEqual(self.counts()["autonomous_mission_execution_epochs"], 1)

    def test_revision_origin_authority_matrix_is_durable_and_fail_closed(self):
        started = self.approvals.approve_and_start(
            self.report.id, **self.approval_arguments()
        )
        initial = self.revisions.get_revision(started.approval.revision_id)

        human = self.revisions.create_revision(
            mission_id=self.mission.id,
            proposal=self.revised_proposal(initial, marker="human adjustment"),
            origin=BacklogRevisionOrigin.HUMAN,
            created_by="Product Manager",
            command_id="create-human-revision",
            rationale="Human-authored priority clarification",
            parent_revision_id=initial.id,
        )
        with self.assertRaises(PermissionError):
            self.revisions.apply_revision(
                human.id,
                actor="Product Manager",
                command_id="apply-human-as-non-owner",
                expected_mission_version=started.mission.version,
                reason="Only the owner may apply this",
            )
        human_result = self.revisions.apply_revision(
            human.id,
            actor="Founder",
            command_id="apply-human-revision",
            expected_mission_version=started.mission.version,
            reason="Apply the human-authored revision at the owner boundary",
        )
        self.assertEqual(
            human_result.authority.outcome,
            BacklogRevisionAuthorityOutcome.APPLIED,
        )
        self.assertEqual(
            human_result.authority.base_approval_id, started.approval.id
        )
        self.assertIsNone(human_result.authority.base_authority_id)
        self.assertEqual(human_result.mission.active_backlog_revision_id, human.id)

        technical_item = ProposedItem(
            stable_id="TECH-001",
            kind="task",
            title="Refactor the health adapter",
            description="Extract an internal adapter without changing product scope.",
            dependencies=("DEV-001",),
            priority="P1",
            acceptance_criteria=("Existing health behavior remains unchanged",),
            validation_method=("Run the health endpoint regression suite",),
            required_components=("service.py",),
            required_infrastructure=("SQLite",),
            expected_artifacts=("Internal adapter refactor",),
            definition_of_done=("All existing endpoint tests pass",),
            assigned_role="Developer",
            source_references=("DEV-001",),
            labels=("scope:technical",),
        )
        technical = self.revisions.create_revision(
            mission_id=self.mission.id,
            proposal=self.revised_proposal(
                human,
                technical_item,
                marker="technical subtask",
            ),
            origin=BacklogRevisionOrigin.TECHNICAL_SUBTASK,
            created_by="Developer Agent",
            command_id="create-technical-revision",
            rationale="Implementation-only decomposition",
            parent_revision_id=human.id,
        )
        with self.assertRaisesRegex(PermissionError, "trace"):
            self.revisions.apply_revision(
                technical.id,
                actor="Developer Agent",
                command_id="apply-untraced-technical",
                expected_mission_version=human_result.mission.version,
                reason="Missing approved parent item",
            )
        technical_result = self.revisions.apply_revision(
            technical.id,
            actor="Developer Agent",
            command_id="apply-technical-revision",
            expected_mission_version=human_result.mission.version,
            reason="Trace the technical decomposition to approved work",
            approved_item_stable_id="DEV-001",
        )
        self.assertEqual(
            technical_result.authority.outcome,
            BacklogRevisionAuthorityOutcome.APPLIED,
        )
        self.assertEqual(
            technical_result.authority.base_authority_id,
            human_result.authority.id,
        )
        self.assertEqual(
            technical_result.authority.approved_item_stable_id, "DEV-001"
        )
        self.assertEqual(len(technical_result.authority.approved_item_digest), 64)
        replay = self.revisions.apply_revision(
            technical.id,
            actor="Developer Agent",
            command_id="apply-technical-revision",
            expected_mission_version=human_result.mission.version,
            reason="Trace the technical decomposition to approved work",
            approved_item_stable_id="DEV-001",
        )
        self.assertEqual(replay.authority.id, technical_result.authority.id)
        with self.assertRaises(BacklogRevisionAuthorityCommandConflictError):
            self.revisions.apply_revision(
                technical.id,
                actor="Developer Agent",
                command_id="apply-technical-revision",
                expected_mission_version=human_result.mission.version,
                reason="Conflicting replay",
                approved_item_stable_id="DEV-001",
            )

        material_item = replace(
            technical_item,
            stable_id="SCOPE-001",
            title="Add a public metrics endpoint",
            description="Add new externally visible product behavior.",
            dependencies=(),
            source_references=("REQ-NEW",),
            labels=("scope:material",),
        )
        material = self.revisions.create_revision(
            mission_id=self.mission.id,
            proposal=self.revised_proposal(
                technical,
                material_item,
                marker="material proposal",
            ),
            origin=BacklogRevisionOrigin.AGENT_MATERIAL,
            created_by="Backlog Planner",
            command_id="create-material-revision",
            rationale="Propose new user-visible scope",
            parent_revision_id=technical.id,
        )
        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "lacks authority"
        ):
            self.missions.set_active_backlog_revision(
                self.mission.id,
                material.id,
                actor="Backlog Planner",
                command_id="bypass-material-approval",
                expected_version=technical_result.mission.version,
                reason="A material agent revision cannot self-activate",
            )
        routed = self.revisions.apply_revision(
            material.id,
            actor="Backlog Planner",
            command_id="route-material-revision",
            expected_mission_version=technical_result.mission.version,
            reason="Return material scope to the exact human boundary",
        )
        self.assertEqual(
            routed.authority.outcome,
            BacklogRevisionAuthorityOutcome.WAITING_FOR_APPROVAL,
        )
        self.assertEqual(
            routed.mission.phase, MissionPhase.WAITING_FOR_BACKLOG_APPROVAL
        )
        self.assertEqual(
            routed.mission.active_backlog_revision_id, technical.id
        )
        self.assertEqual(
            [value.revision_origin for value in self.revisions.revision_authorities(self.mission.id)],
            [
                BacklogRevisionOrigin.HUMAN,
                BacklogRevisionOrigin.TECHNICAL_SUBTASK,
                BacklogRevisionOrigin.AGENT_MATERIAL,
            ],
        )


if __name__ == "__main__":
    unittest.main()
