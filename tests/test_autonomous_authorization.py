import sqlite3
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from agent_factory.autonomous_authorization import (
    AuthorizationCommandConflictError,
    AuthorizationOperation,
    AuthorizationOutcome,
    AutonomousAuthorizationRequest,
    AutonomousAuthorizationService,
    PlanningAction,
)
from agent_factory.autonomous_mission import (
    AutonomousMissionConfiguration,
    AutonomousMissionService,
    MissionDisposition,
    MissionPhase,
)
from agent_factory.backlog import BacklogProposal, ProposedItem
from agent_factory.backlog_revisions import (
    BacklogRevisionOrigin,
    BacklogRevisionService,
)
from agent_factory.mission_checkpoints import MissionCheckpointService
from agent_factory.models import (
    Agent,
    ExecutionApproval,
    ExecutionLocation,
    ProviderCapabilities,
    WorkItem,
)
from agent_factory.providers import CLIProvider
from agent_factory.storage import SQLiteStorage


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


def proposal(*, title: str = "Implement the approved capability") -> BacklogProposal:
    return BacklogProposal(
        source_path="memory://authorization-backlog.json",
        source_sha256=("a" if title.startswith("Implement") else "b") * 64,
        source_name="Authorization backlog",
        schema_version=2,
        items=(
            ProposedItem(
                stable_id="T1",
                kind="task",
                title=title,
                description="Implement and validate the bounded capability.",
                acceptance_criteria=("Deterministic validation passes",),
                priority="P0",
                validation_method=("Run tests",),
                required_components=("app.py",),
                required_infrastructure=("Python",),
                expected_artifacts=("Committed implementation",),
                definition_of_done=("Tests pass",),
                assigned_role="Developer",
            ),
        ),
    )


class AutonomousAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary_directory.name)
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
        (self.repository / "README.md").write_text("# Mission\n", encoding="utf-8")
        run_git(self.repository, "add", "README.md")
        run_git(self.repository, "commit", "-m", "initial")
        self.epoch_branch = "autonomous/AFM-AUTH/epoch-1"
        run_git(self.repository, "checkout", "-b", self.epoch_branch)
        self.base_commit = run_git(self.repository, "rev-parse", "HEAD")

        self.storage = SQLiteStorage(self.workspace / "state.db")
        self.missions = AutonomousMissionService(self.storage)
        self.revisions = BacklogRevisionService(self.storage)
        self.checkpoints = MissionCheckpointService(self.storage)
        self.capabilities = {
            "local-provider": ProviderCapabilities(
                execution_location=ExecutionLocation.LOCAL,
                location_declared=True,
                text_generation=True,
                structured_output=True,
                tool_calls=True,
            ),
            "second-local": ProviderCapabilities(
                execution_location=ExecutionLocation.LOCAL,
                location_declared=True,
                text_generation=True,
            ),
            "remote-provider": ProviderCapabilities(
                execution_location=ExecutionLocation.REMOTE,
                location_declared=True,
                text_generation=True,
            ),
            "ollama": ProviderCapabilities(
                execution_location=ExecutionLocation.REMOTE,
                location_declared=True,
                text_generation=True,
            ),
            "undeclared-local": ProviderCapabilities(text_generation=True),
        }
        self.authorizations = AutonomousAuthorizationService(
            self.storage, self.capabilities
        )
        self.mission = self._create_mission("AFM-AUTH")
        self._approve_mission()
        self.authorization = self.authorizations.grant_execution_authority(
            self.mission.id,
            expected_backlog_revision_id=self.revision.id,
            expected_execution_epoch_id=self.epoch.id,
            actor="Founder",
            command_id="grant-autonomous-authority",
            reason="Approve bounded local execution",
        )

    def tearDown(self):
        self.storage.close()
        self.temporary_directory.cleanup()

    def _configuration(self) -> AutonomousMissionConfiguration:
        return AutonomousMissionConfiguration(
            repository_path=str(self.repository),
            default_model="local:qwen-coder",
            role_models={
                "Developer": "local:qwen-coder",
                "Planner": "local:qwen-planner",
            },
            local_provider_ids=("local-provider",),
        )

    def _create_mission(self, key: str):
        return self.missions.create(
            name=f"Mission {key}",
            mission_owner="Founder",
            actor="Founder",
            command_id=f"create-{key}",
            mission_key=key,
            configuration=self._configuration(),
        )

    def _approve_mission(self):
        self.mission = self.missions.transition_phase(
            self.mission.id,
            MissionPhase.SPECIFICATION_ANALYSIS,
            actor="Founder",
            command_id="auth-analyze",
            expected_version=self.mission.version,
            reason="Analyze specification",
        )
        self.mission = self.missions.transition_phase(
            self.mission.id,
            MissionPhase.BACKLOG_GENERATION,
            actor="Founder",
            command_id="auth-generate",
            expected_version=self.mission.version,
            reason="Generate implementation backlog",
        )
        self.revision = self.revisions.create_revision(
            mission_id=self.mission.id,
            proposal=proposal(),
            origin=BacklogRevisionOrigin.HUMAN,
            created_by="Founder",
            command_id="auth-revision",
            rationale="Exact implementation scope",
        )
        self.mission = self.missions.transition_phase(
            self.mission.id,
            MissionPhase.WAITING_FOR_BACKLOG_APPROVAL,
            actor="Founder",
            command_id="auth-wait",
            expected_version=self.mission.version,
            reason="Backlog is ready for approval",
        )
        self.mission = self.revisions.activate_revision(
            self.revision.id,
            actor="Founder",
            command_id="auth-activate-revision",
            expected_mission_version=self.mission.version,
            reason="Approve the exact backlog revision",
        )
        self.mission = self.missions.transition_phase(
            self.mission.id,
            MissionPhase.APPROVED,
            actor="Founder",
            command_id="auth-approved",
            expected_version=self.mission.version,
            reason="Begin approved mission execution",
        )
        self.epoch = self.checkpoints.create_epoch(
            self.mission.id,
            expected_mission_version=self.mission.version,
            expected_backlog_revision_id=self.revision.id,
            expected_active_epoch_id=None,
            actor="Founder",
            command_id="auth-epoch",
            reason="Start the approved execution epoch",
            epoch_branch=self.epoch_branch,
            temporal_workflow_id="autonomous-AFM-AUTH-e1",
            temporal_run_id="auth-temporal-run-1",
            temporal_chain_metadata={"task_queue": "autonomous"},
            base_git_commit_sha=self.base_commit,
        )
        self.mission = self.missions.get(self.mission.id)

    def execution_request(self, **changes) -> AutonomousAuthorizationRequest:
        values = {
            "mission_id": self.mission.id,
            "operation": AuthorizationOperation.LOCAL_INFERENCE,
            "provider_id": "local-provider",
            "agent_id": "developer-1",
            "task_id": 101,
            "role": "Developer",
            "model": "local:qwen-coder",
            "backlog_revision_id": self.revision.id,
            "backlog_revision_digest": self.revision.revision_digest,
            "execution_epoch_id": self.epoch.id,
            "repository_path": str(self.repository),
            "epoch_branch": self.epoch_branch,
            "tool_profile": "autonomous-local-default",
            "permissions": ("execute_provider",),
            "authorization_id": self.authorization.id,
        }
        values.update(changes)
        return AutonomousAuthorizationRequest(**values)

    def test_exact_binding_allows_and_every_boundary_records_evidence(self):
        replay = self.authorizations.grant_execution_authority(
            self.mission.id,
            expected_backlog_revision_id=self.revision.id,
            expected_execution_epoch_id=self.epoch.id,
            actor="Founder",
            command_id="grant-autonomous-authority",
            reason="Approve bounded local execution",
        )
        self.assertEqual(replay.id, self.authorization.id)
        with self.assertRaises(AuthorizationCommandConflictError):
            self.authorizations.grant_execution_authority(
                self.mission.id,
                expected_backlog_revision_id=self.revision.id,
                expected_execution_epoch_id=self.epoch.id,
                actor="Founder",
                command_id="grant-autonomous-authority",
                reason="Different command body",
            )

        allowed = self.authorizations.resolve(self.execution_request())
        self.assertEqual(allowed.outcome, AuthorizationOutcome.ALLOW_AUTONOMOUS)
        self.assertTrue(allowed.authority_valid)
        self.assertEqual(self.authorization.provider_ids, ("local-provider",))
        self.assertEqual(
            self.authorization.role_model_manifest["role_models"]["Developer"],
            "local:qwen-coder",
        )
        self.assertEqual(self.authorization.epoch_branch, self.epoch_branch)

        remote = self.authorizations.resolve(
            self.execution_request(
                operation=AuthorizationOperation.REMOTE_INFERENCE,
                provider_id="remote-provider",
            )
        )
        external = self.authorizations.resolve(
            self.execution_request(operation=AuthorizationOperation.EXTERNAL_MUTATION)
        )
        protected = self.authorizations.resolve(
            self.execution_request(operation=AuthorizationOperation.PROTECTED_INTEGRATION)
        )
        masquerade = self.authorizations.resolve(
            self.execution_request(provider_id="ollama")
        )
        undeclared = self.authorizations.resolve(
            self.execution_request(provider_id="undeclared-local")
        )
        for decision in (remote, external, protected, masquerade, undeclared):
            self.assertEqual(
                decision.outcome, AuthorizationOutcome.REQUIRE_STANDARD_GATE
            )

        unrelated = self._create_mission("AFM-OTHER")
        unrelated_decision = self.authorizations.resolve(
            self.execution_request(mission_id=unrelated.id)
        )
        self.assertEqual(
            unrelated_decision.outcome, AuthorizationOutcome.REQUIRE_STANDARD_GATE
        )
        decisions = self.authorizations.decisions(self.mission.id)
        self.assertEqual(len(decisions), 6)
        for decision in decisions:
            self.assertEqual(len(decision.evidence_digest), 64)
            self.assertTrue(decision.evidence["checks"])

    def test_stopped_mission_preserves_authority_until_explicit_revocation(self):
        self.mission = self.missions.transition_disposition(
            self.mission.id,
            MissionDisposition.STOPPED,
            actor="Founder",
            command_id="stop-authorized-mission",
            expected_version=self.mission.version,
            reason="Stop at a safe boundary",
        )
        stopped = self.authorizations.resolve(self.execution_request())
        self.assertEqual(stopped.outcome, AuthorizationOutcome.DENY)
        self.assertTrue(stopped.authority_valid)
        self.assertIn("STOPPED", stopped.reason)
        self.assertFalse(
            self.authorizations.get_authorization(self.authorization.id).revoked
        )

        self.mission = self.missions.transition_disposition(
            self.mission.id,
            MissionDisposition.RUNNING,
            actor="Founder",
            command_id="resume-authorized-mission",
            expected_version=self.mission.version,
            reason="Continue from the safe boundary",
        )
        resumed = self.authorizations.resolve(self.execution_request())
        self.assertEqual(resumed.outcome, AuthorizationOutcome.ALLOW_AUTONOMOUS)

        revocation = self.authorizations.revoke_execution_authority(
            self.authorization.id,
            actor="Founder",
            command_id="revoke-autonomous-authority",
            reason="Human explicitly retired mission authority",
        )
        self.assertEqual(revocation.authorization_id, self.authorization.id)
        revoked = self.authorizations.resolve(self.execution_request())
        self.assertEqual(revoked.outcome, AuthorizationOutcome.DENY)
        self.assertFalse(revoked.authority_valid)

    def test_policy_drift_invalidates_even_after_emergency_stop_is_cleared(self):
        self.storage.set_emergency_stop(
            True, actor="Operations", reason="Exercise global safety fence"
        )
        drifted = self.authorizations.resolve(self.execution_request())
        self.assertEqual(drifted.outcome, AuthorizationOutcome.DENY)
        self.assertFalse(drifted.authority_valid)
        self.storage.set_emergency_stop(
            False, actor="Operations", reason="Clear exercise safety fence"
        )
        still_drifted = self.authorizations.resolve(self.execution_request())
        self.assertEqual(still_drifted.outcome, AuthorizationOutcome.DENY)

    def test_unapproved_agent_material_revision_invalidates_exact_authority(self):
        replacement = self.revisions.create_revision(
            mission_id=self.mission.id,
            proposal=proposal(title="Materially expand the approved capability"),
            origin=BacklogRevisionOrigin.AGENT_MATERIAL,
            created_by="Autonomous Planner",
            command_id="material-revision-after-approval",
            rationale="Propose a material scope change",
            parent_revision_id=self.revision.id,
        )
        self.assertGreater(replacement.revision_number, self.revision.revision_number)
        material = self.authorizations.resolve(self.execution_request())
        self.assertEqual(material.outcome, AuthorizationOutcome.DENY)
        failed = {
            check["name"]
            for check in material.evidence["checks"]
            if not check["passed"]
        }
        self.assertIn("no_unapproved_agent_material_revision", failed)

    def test_exact_scope_mismatches_fail_closed(self):
        mismatches = {
            "revision": {"backlog_revision_id": self.revision.id + 100},
            "digest": {"backlog_revision_digest": "0" * 64},
            "epoch": {"execution_epoch_id": self.epoch.id + 100},
            "branch": {"epoch_branch": "autonomous/other/epoch-1"},
            "repository": {"repository_path": str(self.workspace / "other")},
            "tool profile": {"tool_profile": "unrestricted"},
            "role": {"role": "Unknown Role"},
            "model": {"model": "different-model"},
            "provider": {"provider_id": "second-local"},
            "missing provider": {"provider_id": None},
            "missing agent": {"agent_id": ""},
            "missing task": {"task_id": None},
            "permission": {"permissions": ("read_secrets",)},
        }
        for label, changes in mismatches.items():
            with self.subTest(label=label):
                decision = self.authorizations.resolve(
                    self.execution_request(**changes)
                )
                self.assertEqual(decision.outcome, AuthorizationOutcome.DENY)
                self.assertFalse(decision.authority_valid)

        secret = self.authorizations.resolve(
            self.execution_request(operation=AuthorizationOperation.SECRET_ACCESS)
        )
        global_write = self.authorizations.resolve(
            self.execution_request(
                operation=AuthorizationOperation.MACHINE_GLOBAL_MUTATION
            )
        )
        self.assertEqual(secret.outcome, AuthorizationOutcome.DENY)
        self.assertEqual(global_write.outcome, AuthorizationOutcome.DENY)

    def test_preapproval_planning_is_one_bounded_read_only_request(self):
        planning_mission = self._create_mission("AFM-PLANNING")
        planning = self.authorizations.grant_planning_authority(
            planning_mission.id,
            planning_request_id="plan-request-1",
            requested_action=PlanningAction.ANALYZE,
            role_models={"Planner": "local:qwen-planner"},
            actor="Founder",
            command_id="grant-planning-request-1",
            reason="Analyze this specification with local models",
            ttl_seconds=3600,
        )
        request = AutonomousAuthorizationRequest(
            mission_id=planning_mission.id,
            operation=AuthorizationOperation.PLANNING_INFERENCE,
            provider_id="local-provider",
            agent_id="planner-1",
            task_id=201,
            role="Planner",
            model="local:qwen-planner",
            repository_path=str(self.repository),
            tool_profile="autonomous-local-planning-read-only-v1",
            permissions=("read_project", "execute_provider"),
            planning_authorization_id=planning.id,
            planning_request_id="plan-request-1",
            requested_action=PlanningAction.ANALYZE,
        )
        inference = self.authorizations.resolve(request)
        artifact = self.authorizations.resolve(
            replace(
                request,
                operation=AuthorizationOperation.PLANNING_ARTIFACT,
                permissions=("read_project", "create_artifact"),
            )
        )
        self.assertEqual(inference.outcome, AuthorizationOutcome.ALLOW_PLANNING)
        self.assertEqual(artifact.outcome, AuthorizationOutcome.ALLOW_PLANNING)

        mutation = self.authorizations.resolve(
            replace(
                request,
                operation=AuthorizationOperation.GIT_WRITE,
                permissions=("git_write",),
            )
        )
        wrong_request = self.authorizations.resolve(
            replace(request, planning_request_id="another-request")
        )
        remote = self.authorizations.resolve(
            replace(request, provider_id="remote-provider")
        )
        self.assertEqual(mutation.outcome, AuthorizationOutcome.DENY)
        self.assertEqual(wrong_request.outcome, AuthorizationOutcome.DENY)
        self.assertEqual(remote.outcome, AuthorizationOutcome.REQUIRE_STANDARD_GATE)

        closed = self.authorizations.close_planning_authority(
            planning.id,
            actor="Founder",
            command_id="close-planning-request-1",
            reason="Planning artifact was produced",
        )
        self.assertTrue(closed.closed)
        after_close = self.authorizations.resolve(request)
        self.assertEqual(after_close.outcome, AuthorizationOutcome.DENY)
        self.assertFalse(after_close.authority_valid)

    def test_provider_accepts_only_typed_explicit_local_authority(self):
        decision = self.authorizations.resolve(self.execution_request())
        typed = self.authorizations.provider_authorization(decision)
        provider = CLIProvider(
            "local-provider",
            sys.executable,
            ["-c", "print(input())", "{model}"],
            model_namespace="local",
            model_ids=["qwen-coder"],
            allow_execution=True,
            workspace=self.repository,
            capabilities=self.capabilities["local-provider"],
        )
        agent = Agent(
            id="developer-1",
            name="Developer",
            role="Developer",
            enabled=True,
            provider="local-provider",
            instructions="Return a bounded artifact",
            model="local:qwen-coder",
        )
        item = WorkItem(
            title="Authorized task",
            description="Return a local result",
            project_id=self.mission.project_id,
            id=101,
        )
        result = provider.execute(agent, item, {}, typed)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(
            result.metadata["authorization_evidence_digest"],
            decision.evidence_digest,
        )
        self.assertEqual(result.metadata["authorization_id"], self.authorization.id)

        remote = CLIProvider(
            "local-provider",
            sys.executable,
            ["-c", "print(input())", "{model}"],
            model_namespace="local",
            model_ids=["qwen-coder"],
            allow_execution=True,
            workspace=self.repository,
            capabilities=self.capabilities["remote-provider"],
        )
        blocked = remote.execute(agent, item, {}, typed)
        self.assertFalse(blocked.ok)
        self.assertIn("explicitly LOCAL", blocked.error)
        standard = provider.execute(agent, item, {})
        self.assertFalse(standard.ok)
        self.assertIn("approval required", standard.error)

        conventional = provider.execute(
            agent,
            item,
            {},
            ExecutionApproval(99, "local-provider", "developer-1", 101),
        )
        self.assertTrue(conventional.ok)

    def test_authorization_records_are_append_only(self):
        decision = self.authorizations.resolve(self.execution_request())
        revocation = self.authorizations.revoke_execution_authority(
            self.authorization.id,
            actor="Founder",
            command_id="immutable-revocation",
            reason="Test immutable revocation evidence",
        )
        planning_mission = self._create_mission("AFM-IMMUTABLE-PLAN")
        planning = self.authorizations.grant_planning_authority(
            planning_mission.id,
            planning_request_id="immutable-plan",
            requested_action=PlanningAction.ANALYZE,
            role_models={"Planner": "local:qwen-planner"},
            actor="Founder",
            command_id="grant-immutable-plan",
            reason="Test immutable planning evidence",
        )
        self.authorizations.close_planning_authority(
            planning.id,
            actor="Founder",
            command_id="close-immutable-plan",
            reason="Complete immutable planning request",
        )
        closure = self.storage.db.execute(
            """SELECT id FROM autonomous_planning_authorization_closures
                WHERE planning_authorization_id=?""",
            (planning.id,),
        ).fetchone()
        for table, row_id in (
            ("autonomous_local_authorizations", self.authorization.id),
            ("autonomous_authorization_revocations", revocation.id),
            ("autonomous_planning_authorizations", planning.id),
            ("autonomous_planning_authorization_closures", closure["id"]),
            ("autonomous_authorization_decisions", decision.id),
        ):
            with self.subTest(table=table, action="update"):
                with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                    self.storage.db.execute(
                        f"UPDATE {table} SET identity=identity || '-changed' WHERE id=?",
                        (row_id,),
                    )
            with self.subTest(table=table, action="delete"):
                with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                    self.storage.db.execute(
                        f"DELETE FROM {table} WHERE id=?", (row_id,)
                    )

        command = self.storage.db.execute(
            """SELECT id FROM autonomous_authorization_commands
                WHERE command_id='grant-autonomous-authority'"""
        ).fetchone()
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "DELETE FROM autonomous_authorization_commands WHERE id=?",
                (command["id"],),
            )


if __name__ == "__main__":
    unittest.main()
