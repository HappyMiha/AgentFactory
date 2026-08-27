import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.autonomous_mission import AutonomousMissionConfiguration
from agent_factory.autonomous_planning import (
    AutonomousPlanningService,
    PlanningContextLimitError,
    PlanningManifestCommandConflictError,
    RoleModelSelection,
)
from agent_factory.backlog_revisions import (
    BacklogRevisionOrigin,
    BacklogRevisionService,
)
from agent_factory.mission_intake import AutonomousMissionIntakeService
from agent_factory.models import ExecutionLocation, ProviderCapabilities
from agent_factory.roles import RoleRegistry
from agent_factory.software_roles import (
    AUTONOMOUS_PLANNING_PACK_VERSION,
    AUTONOMOUS_PLANNING_ROLE_IDS,
)
from agent_factory.storage import SQLiteStorage
from tests.test_autonomous_mission_intake import rich_proposal


class AutonomousPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.storage = SQLiteStorage(self.workspace / "state.db")
        self.intake = AutonomousMissionIntakeService(self.storage)
        self.capabilities = {
            "local-one": ProviderCapabilities(
                execution_location=ExecutionLocation.LOCAL,
                location_declared=True,
                text_generation=True,
                structured_output=True,
            ),
            "local-two": ProviderCapabilities(
                execution_location=ExecutionLocation.LOCAL,
                location_declared=True,
                text_generation=True,
            ),
            "remote": ProviderCapabilities(
                execution_location=ExecutionLocation.REMOTE,
                location_declared=True,
                text_generation=True,
            ),
            "ollama": ProviderCapabilities(
                execution_location=ExecutionLocation.REMOTE,
                location_declared=True,
                text_generation=True,
            ),
            "undeclared": ProviderCapabilities(text_generation=True),
        }
        configuration = AutonomousMissionConfiguration(
            repository_path=str(self.workspace),
            default_model="shared-local-model",
            role_models={"software_architect": "architecture-model"},
            # The mission allowlist is necessary but not sufficient: the
            # provider capability record must still prove local execution.
            local_provider_ids=(
                "local-one",
                "local-two",
                "remote",
                "ollama",
                "undeclared",
            ),
        )
        created = self.intake.create_from_text(
            name="Planning mission",
            mission_owner="Founder",
            specification="# Product\n\nBuild a safe local application with measurable tests.",
            actor="Founder",
            command_id="create-planning-mission",
            mission_key="AFM-PLANNING-ROLES",
            configuration=configuration,
            source_name="specification.md",
        )
        self.mission = created.mission
        self.source = created.source
        self.planning = AutonomousPlanningService(self.storage, self.capabilities)
        self.revisions = BacklogRevisionService(self.storage)

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def manifest(self, *, proposal_key="proposal-1", command_id="manifest-1", **values):
        return self.planning.create_manifest(
            self.mission.id,
            proposal_key=proposal_key,
            actor="Founder",
            command_id=command_id,
            default_provider_id="local-one",
            **values,
        )

    def test_single_model_fills_five_typed_roles_with_distinct_logical_agents(self):
        manifest = self.manifest()
        self.assertEqual(
            tuple(assignment.role_id for assignment in manifest.assignments),
            AUTONOMOUS_PLANNING_ROLE_IDS,
        )
        self.assertEqual(len(manifest.assignments), 5)
        self.assertEqual(
            len({assignment.logical_agent_id for assignment in manifest.assignments}), 5
        )
        for assignment in manifest.assignments:
            with self.subTest(role=assignment.role_id):
                self.assertTrue(assignment.inputs)
                self.assertTrue(assignment.outputs)
                self.assertTrue(assignment.evidence)
                self.assertTrue(assignment.tools)
                self.assertTrue(assignment.permissions)
                self.assertTrue(assignment.limits)
                self.assertEqual(assignment.provider_id, "local-one")
                expected_model = (
                    "architecture-model"
                    if assignment.role_id == "software_architect"
                    else "shared-local-model"
                )
                self.assertEqual(assignment.model, expected_model)
                self.assertTrue(
                    assignment.provider_capabilities["autonomous_local_eligible"]
                )
                self.assertNotIn("write_project", assignment.permissions)
                self.assertNotIn("git_write", assignment.permissions)
        self.assertFalse(manifest.stale)
        self.assertEqual(len(manifest.manifest_digest), 64)
        self.assertEqual(
            manifest.specification_source_digest, self.source.source_digest
        )

        replay = self.manifest()
        self.assertEqual(replay.id, manifest.id)
        with self.assertRaises(PlanningManifestCommandConflictError):
            self.manifest(
                proposal_key="different-proposal",
                command_id="manifest-1",
            )

        registry = RoleRegistry(self.storage)
        for role_id in AUTONOMOUS_PLANNING_ROLE_IDS:
            role = registry.resolve(role_id, AUTONOMOUS_PLANNING_PACK_VERSION)
            self.assertEqual(role.tools, ("read_file",))
        registry.assign_decision_role(
            decision_key="proposal:1",
            agent_id="logical-producer",
            role_id="backlog_planner",
            role_version=AUTONOMOUS_PLANNING_PACK_VERSION,
        )
        with self.assertRaisesRegex(PermissionError, "incompatible"):
            registry.assign_decision_role(
                decision_key="proposal:1",
                agent_id="logical-producer",
                role_id="backlog_reviewer",
                role_version=AUTONOMOUS_PLANNING_PACK_VERSION,
            )

    def test_per_role_multi_model_manifest_and_provider_qualification_fail_closed(self):
        overrides = {
            role_id: RoleModelSelection(
                "local-one" if index % 2 else "local-two",
                f"model-{index}",
            )
            for index, role_id in enumerate(AUTONOMOUS_PLANNING_ROLE_IDS, 1)
        }
        manifest = self.planning.create_manifest(
            self.mission.id,
            proposal_key="all-overrides",
            actor="Founder",
            command_id="manifest-all-overrides",
            default_provider_id="",
            default_model="",
            role_models=overrides,
        )
        self.assertEqual(
            [assignment.model for assignment in manifest.assignments],
            [f"model-{index}" for index in range(1, 6)],
        )
        self.assertEqual(manifest.default_provider_id, "")
        self.assertEqual(manifest.default_model, "")

        for index, provider_id in enumerate(("remote", "ollama", "undeclared"), 1):
            with self.subTest(provider=provider_id), self.assertRaisesRegex(
                PermissionError, "not explicitly local"
            ):
                self.planning.create_manifest(
                    self.mission.id,
                    proposal_key=f"bad-provider-{index}",
                    actor="Founder",
                    command_id=f"bad-provider-manifest-{index}",
                    default_provider_id="local-one",
                    role_models={
                        "mission_analyst": RoleModelSelection(
                            provider_id, "masquerading-model"
                        )
                    },
                )
        with self.assertRaisesRegex(ValueError, "Unknown planning role"):
            self.planning.create_manifest(
                self.mission.id,
                proposal_key="unknown-role",
                actor="Founder",
                command_id="unknown-role-manifest",
                default_provider_id="local-one",
                role_models={"developer": ("local-one", "model")},
            )
        with self.assertRaisesRegex(PermissionError, "mission owner"):
            self.planning.create_manifest(
                self.mission.id,
                proposal_key="wrong-owner",
                actor="Agent",
                command_id="wrong-owner-manifest",
                default_provider_id="local-one",
            )

    def test_contexts_are_bounded_read_only_and_fresh_for_every_invocation(self):
        manifest = self.manifest()
        contexts = []
        for index, role_id in enumerate(AUTONOMOUS_PLANNING_ROLE_IDS, 1):
            upstream = (
                {
                    "artifact_type": "prior-role-output",
                    "digest": f"{index:064x}",
                    "content": {"sequence": index},
                },
            ) if index > 1 else ()
            contexts.append(
                self.planning.create_context(
                    manifest.id,
                    role_id,
                    actor=f"scheduler-{index}",
                    command_id=f"context-{index}",
                    upstream_artifacts=upstream,
                )
            )
        self.assertEqual(len({value.context_key for value in contexts}), 5)
        self.assertEqual(len({value.context_digest for value in contexts}), 5)
        for context in contexts:
            with self.subTest(role=context.role_id):
                self.assertTrue(context.read_only)
                self.assertTrue(context.fresh_session)
                self.assertLessEqual(
                    context.byte_count, manifest.context_policy["max_bytes"]
                )
                self.assertLessEqual(
                    context.token_count, manifest.context_policy["max_tokens"]
                )
                isolation = context.document["isolation"]
                self.assertTrue(isolation["fresh_session"])
                self.assertIsNone(isolation["prior_transcript"])
                self.assertIsNone(isolation["session_parent"])
                authority = context.document["authority"]
                self.assertFalse(authority["repository_mutation"])
                self.assertFalse(authority["environment_mutation"])
                self.assertFalse(authority["external_mutation"])

        repeated = self.planning.create_context(
            manifest.id,
            "mission_analyst",
            actor="scheduler-repeat",
            command_id="context-repeat",
        )
        self.assertEqual(repeated.invocation_sequence, 2)
        self.assertNotEqual(repeated.context_key, contexts[0].context_key)
        replay = self.planning.create_context(
            manifest.id,
            "mission_analyst",
            actor="scheduler-repeat",
            command_id="context-repeat",
        )
        self.assertEqual(replay.id, repeated.id)
        with self.assertRaises(PlanningManifestCommandConflictError):
            self.planning.create_context(
                manifest.id,
                "mission_analyst",
                actor="scheduler-repeat",
                command_id="context-repeat",
                upstream_artifacts=(
                    {
                        "artifact_type": "changed",
                        "digest": "f" * 64,
                        "content": {},
                    },
                ),
            )

        limited = self.manifest(
            proposal_key="limited-proposal",
            command_id="limited-manifest",
            max_context_bytes=1_024,
            max_context_tokens=250_000,
        )
        with self.assertRaises(PlanningContextLimitError):
            self.planning.create_context(
                limited.id,
                "mission_analyst",
                actor="scheduler-limited",
                command_id="limited-context",
            )

    def test_manifest_binds_exact_revision_and_becomes_stale_with_source(self):
        manifest = self.manifest()
        revision = self.revisions.create_revision(
            mission_id=self.mission.id,
            proposal=rich_proposal(self.source.raw_digest),
            origin=BacklogRevisionOrigin.HUMAN,
            created_by="Founder",
            command_id="planning-revision",
            rationale="Proposal generated by the planning roles",
        )
        binding = self.planning.bind_revision(
            manifest.id,
            revision.id,
            actor="Founder",
            command_id="bind-planning-revision",
        )
        self.assertEqual(binding.revision_digest, revision.revision_digest)
        self.assertEqual(binding.manifest_digest, manifest.manifest_digest)
        self.assertEqual(
            self.planning.get_manifest(manifest.id).bound_revision_ids,
            (revision.id,),
        )

        updated = self.intake.update_from_text(
            self.mission.id,
            specification="# Changed specification\n\nNew product scope.",
            actor="Founder",
            command_id="change-planning-source",
            reason="Revise the source before approval",
            expected_mission_version=self.mission.version,
            expected_source_version=1,
            source_name="specification.md",
        )
        self.assertEqual(updated.version, 2)
        self.assertTrue(self.planning.get_manifest(manifest.id).stale)
        with self.assertRaisesRegex(PermissionError, "stale"):
            self.planning.create_context(
                manifest.id,
                "mission_analyst",
                actor="scheduler",
                command_id="stale-context",
            )
        with self.assertRaisesRegex(PermissionError, "stale"):
            self.planning.bind_revision(
                manifest.id,
                revision.id,
                actor="Founder",
                command_id="stale-binding",
            )

    def test_manifest_context_and_revision_binding_are_immutable(self):
        manifest = self.manifest()
        context = self.planning.create_context(
            manifest.id,
            "mission_analyst",
            actor="scheduler",
            command_id="immutable-context",
        )
        revision = self.revisions.create_revision(
            mission_id=self.mission.id,
            proposal=rich_proposal(self.source.raw_digest),
            origin=BacklogRevisionOrigin.HUMAN,
            created_by="Founder",
            command_id="immutable-planning-revision",
            rationale="Bind immutable planning evidence",
        )
        binding = self.planning.bind_revision(
            manifest.id,
            revision.id,
            actor="Founder",
            command_id="immutable-planning-binding",
        )
        for table, row_id in (
            ("autonomous_planning_manifests", manifest.id),
            ("autonomous_planning_contexts", context.id),
            ("autonomous_planning_manifest_revision_bindings", binding.id),
        ):
            with self.subTest(table=table, action="update"):
                with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                    self.storage.db.execute(
                        f"UPDATE {table} SET identity=identity || '-x' WHERE id=?",
                        (row_id,),
                    )
            with self.subTest(table=table, action="delete"):
                with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                    self.storage.db.execute(
                        f"DELETE FROM {table} WHERE id=?", (row_id,)
                    )


if __name__ == "__main__":
    unittest.main()
