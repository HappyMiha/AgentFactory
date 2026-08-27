import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.autonomous_authorization import (
    AutonomousAuthorizationService,
    PlanningAction,
)
from agent_factory.autonomous_mission import (
    AutonomousMissionConfiguration,
    AutonomousMissionService,
    MissionPhase,
)
from agent_factory.autonomous_planning import AutonomousPlanningService
from agent_factory.autonomous_planning_pipeline import (
    AutonomousPlanningPipelineService,
    PlanningPipelineCommandConflictError,
    PlanningPipelineFailedError,
)
from agent_factory.backlog_revisions import BacklogRevisionOrigin
from agent_factory.mission_intake import AutonomousMissionIntakeService
from agent_factory.models import (
    ExecutionAuthorizationMode,
    ExecutionLocation,
    ProviderCapabilities,
    ProviderResult,
)
from agent_factory.software_roles import AUTONOMOUS_PLANNING_ROLE_IDS
from agent_factory.storage import SQLiteStorage


def golden_planning_outputs() -> dict[str, dict]:
    requirements = {
        "functional": [
            {
                "id": "REQ-001",
                "statement": "The application exposes a local health endpoint.",
                "acceptance_criteria": [
                    "The health endpoint returns status 200 for a valid request."
                ],
                "source_references": ["specification.md"],
                "priority": "P0",
            }
        ],
        "non_functional": [
            {
                "id": "REQ-002",
                "statement": "The implementation has deterministic local validation.",
                "acceptance_criteria": [
                    "The complete local test suite passes within 60 seconds."
                ],
                "source_references": ["specification.md"],
                "priority": "P1",
            }
        ],
    }
    architecture = {
        "summary": "A small local service with an embedded SQLite store.",
        "components": [
            {
                "id": "service",
                "name": "Local service",
                "responsibilities": [
                    "Return health responses and persist application state."
                ],
                "requirement_ids": ["REQ-001", "REQ-002"],
            }
        ],
        "interfaces": [],
        "infrastructure": [
            {
                "id": "sqlite",
                "name": "SQLite",
                "purpose": "Persist local application state.",
                "bootstrap_required": True,
                "requirement_ids": ["REQ-001"],
            }
        ],
        "decisions": [
            {
                "id": "ADR-001",
                "decision": "Use an embedded SQLite database.",
                "rationale": "It satisfies the local-only deployment constraint.",
                "requirement_ids": ["REQ-001", "REQ-002"],
            }
        ],
    }
    backlog = {
        "schema_version": 2,
        "items": [
            {
                "stable_id": "INFRA-001",
                "kind": "task",
                "title": "Prepare SQLite storage",
                "description": "Create the local SQLite bootstrap and schema.",
                "parent_id": None,
                "dependencies": [],
                "acceptance_criteria": [
                    "The bootstrap command creates the SQLite database file."
                ],
                "source_references": ["REQ-001"],
                "review_notes": [],
                "labels": ["infrastructure"],
                "priority": "P0",
                "validation_method": ["Run the bootstrap integration test."],
                "required_components": ["storage.py"],
                "required_infrastructure": ["SQLite"],
                "expected_artifacts": ["SQLite schema migration"],
                "definition_of_done": [
                    "The SQLite bootstrap integration test passes."
                ],
                "assigned_role": "Environment Bootstrap",
            },
            {
                "stable_id": "DEV-001",
                "kind": "task",
                "title": "Implement the health endpoint",
                "description": "Return health status from the local service.",
                "parent_id": None,
                "dependencies": ["INFRA-001"],
                "acceptance_criteria": [
                    "The health endpoint returns status 200 for a valid request."
                ],
                "source_references": ["REQ-001", "REQ-002"],
                "review_notes": [],
                "labels": ["application"],
                "priority": "P0",
                "validation_method": ["Run the local endpoint test suite."],
                "required_components": ["service.py"],
                "required_infrastructure": ["SQLite"],
                "expected_artifacts": ["Health endpoint implementation"],
                "definition_of_done": [
                    "The complete local endpoint test suite passes."
                ],
                "assigned_role": "Developer",
            },
        ],
    }
    return {
        "mission_analyst": {
            "output": {
                "mission_analysis": {
                    "summary": "Build and validate a safe local application.",
                    "outcomes": ["A local health endpoint returns a success response."],
                    "constraints": ["All inference and execution remains local."],
                    "ambiguities": [],
                    "source_references": ["specification.md"],
                }
            },
            "evidence": {"source_trace": ["specification.md"]},
        },
        "product_requirements_analyst": {
            "output": {"normalized_requirements": requirements},
            "evidence": {
                "traceability_matrix": [
                    {"requirement_id": "REQ-001", "source": "specification.md"},
                    {"requirement_id": "REQ-002", "source": "specification.md"},
                ]
            },
        },
        "software_architect": {
            "output": {"architecture_proposal": architecture},
            "evidence": {
                "decision_trace": [
                    {"decision_id": "ADR-001", "requirements": ["REQ-001"]}
                ]
            },
        },
        "backlog_planner": {
            "output": {"backlog_proposal": backlog},
            "evidence": {
                "dependency_evidence": [
                    {
                        "item_id": "DEV-001",
                        "depends_on": "INFRA-001",
                        "reason": "SQLite must exist before endpoint implementation.",
                    }
                ]
            },
        },
        "backlog_reviewer": {
            "output": {
                "review_report": {
                    "verdict": "READY",
                    "summary": "The proposal is traceable and dependency safe.",
                    "findings": [],
                }
            },
            "evidence": {"findings": []},
        },
    }


class GoldenPlanningInvoker:
    def __init__(
        self,
        *,
        repair_role: str | None = None,
        always_invalid=False,
        before_first_response=None,
    ):
        self.outputs = golden_planning_outputs()
        self.repair_role = repair_role
        self.always_invalid = always_invalid
        self.before_first_response = before_first_response
        self.requests = []
        self.role_attempts: dict[str, int] = {}

    def invoke(self, request):
        self.requests.append(request)
        role_id = request.assignment.role_id
        attempt = self.role_attempts.get(role_id, 0) + 1
        self.role_attempts[role_id] = attempt
        if self.before_first_response is not None and len(self.requests) == 1:
            self.before_first_response(request)
        if request.authorization.mode is not ExecutionAuthorizationMode.BOUNDED_LOCAL_PLANNING:
            raise AssertionError("Planning did not receive typed bounded authority")
        if request.context.document["authority"]["repository_mutation"]:
            raise AssertionError("Planning context permits repository mutation")
        if self.always_invalid or (role_id == self.repair_role and attempt == 1):
            envelope = {
                "output": {"architecture_proposal": {}},
                "evidence": {"decision_trace": []},
            }
        else:
            envelope = copy.deepcopy(self.outputs[role_id])
        return ProviderResult(
            True,
            content=json.dumps(envelope, sort_keys=True),
            provider=request.assignment.provider_id,
            metadata={"fixture": "golden", "attempt": attempt},
        )


class AutonomousPlanningPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.storage = SQLiteStorage(self.workspace / "state.db")
        self.capabilities = {
            "local": ProviderCapabilities(
                execution_location=ExecutionLocation.LOCAL,
                location_declared=True,
                text_generation=True,
                structured_output=True,
            )
        }
        self.intake = AutonomousMissionIntakeService(self.storage)
        created = self.intake.create_from_text(
            name="Pipeline mission",
            mission_owner="Founder",
            specification=(
                "# Product\n\nBuild a safe local health endpoint with deterministic "
                "validation and local persistence."
            ),
            actor="Founder",
            command_id="create-pipeline-mission",
            mission_key="AFM-PIPELINE",
            configuration=AutonomousMissionConfiguration(
                repository_path=str(self.workspace),
                default_model="local-planner",
                local_provider_ids=("local",),
            ),
            source_name="specification.md",
        )
        self.missions = AutonomousMissionService(self.storage)
        self.mission = created.mission
        for phase, command_id in (
            (MissionPhase.SPECIFICATION_ANALYSIS, "pipeline-analyze"),
            (MissionPhase.BACKLOG_GENERATION, "pipeline-generate"),
        ):
            self.mission = self.missions.transition_phase(
                self.mission.id,
                phase,
                actor="Founder",
                command_id=command_id,
                expected_version=self.mission.version,
                reason="Advance the planning fixture",
            )
        self.planning = AutonomousPlanningService(self.storage, self.capabilities)
        self.authorizations = AutonomousAuthorizationService(
            self.storage, self.capabilities
        )

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def planning_scope(
        self,
        sequence: int,
        *,
        action: PlanningAction = PlanningAction.ANALYZE,
    ):
        proposal_key = f"proposal-{sequence}"
        manifest = self.planning.create_manifest(
            self.mission.id,
            proposal_key=proposal_key,
            actor="Founder",
            command_id=f"manifest-{sequence}",
            default_provider_id="local",
        )
        authorization = self.authorizations.grant_planning_authority(
            self.mission.id,
            planning_request_id=proposal_key,
            requested_action=action,
            role_models={
                assignment.role_id: assignment.model
                for assignment in manifest.assignments
            },
            provider_ids=("local",),
            actor="Founder",
            command_id=f"authorize-planning-{sequence}",
            reason="Run the five bounded local planning roles",
        )
        return manifest, authorization

    def test_golden_pipeline_is_sequential_content_addressed_and_idempotent(self):
        manifest, authorization = self.planning_scope(1)
        invoker = GoldenPlanningInvoker()
        service = AutonomousPlanningPipelineService(
            self.storage, invoker, self.capabilities
        )

        run = service.execute(
            self.mission.id,
            manifest_id=manifest.id,
            planning_authorization_id=authorization.id,
            actor="Founder",
            command_id="run-golden-pipeline",
        )

        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual(
            tuple(artifact.role_id for artifact in run.artifacts),
            AUTONOMOUS_PLANNING_ROLE_IDS,
        )
        self.assertEqual(len(service.attempts(run.id)), 5)
        self.assertEqual(len({request.context.id for request in invoker.requests}), 5)
        for index, request in enumerate(invoker.requests):
            self.assertEqual(request.assignment.role_id, AUTONOMOUS_PLANNING_ROLE_IDS[index])
            self.assertEqual(len(request.context.document["upstream_artifacts"]), index)
            for upstream in request.context.document["upstream_artifacts"]:
                self.assertIn("content", upstream)
                self.assertEqual(len(upstream["digest"]), 64)
        for artifact in run.artifacts:
            self.assertEqual(len(artifact.output_digest), 64)
            self.assertEqual(len(artifact.evidence_digest), 64)
            self.assertEqual(len(artifact.artifact_digest), 64)

        revision = service.revision(run.id)
        self.assertEqual(revision.origin, BacklogRevisionOrigin.AGENT_MATERIAL)
        self.assertEqual(
            tuple(item.stable_id for item in revision.items),
            ("INFRA-001", "DEV-001"),
        )
        self.assertEqual(revision.items[1].dependencies, ("INFRA-001",))
        self.assertIsNone(self.missions.get(self.mission.id).active_backlog_revision_id)
        self.assertEqual(
            self.storage.db.execute("SELECT COUNT(*) FROM work_items").fetchone()[0],
            0,
        )
        self.assertTrue(
            self.authorizations.get_planning_authorization(authorization.id).closed
        )

        replay = service.execute(
            self.mission.id,
            manifest_id=manifest.id,
            planning_authorization_id=authorization.id,
            actor="Founder",
            command_id="run-golden-pipeline",
        )
        self.assertEqual(replay.id, run.id)
        self.assertEqual(len(invoker.requests), 5)
        with self.assertRaises(PlanningPipelineCommandConflictError):
            service.execute(
                self.mission.id,
                manifest_id=manifest.id,
                planning_authorization_id=authorization.id,
                actor="Founder",
                command_id="run-golden-pipeline",
                max_attempts_per_role=3,
            )

    def test_invalid_partial_output_gets_fresh_context_and_repair_feedback(self):
        manifest, authorization = self.planning_scope(1)
        invoker = GoldenPlanningInvoker(repair_role="software_architect")
        service = AutonomousPlanningPipelineService(
            self.storage, invoker, self.capabilities
        )

        run = service.execute(
            self.mission.id,
            manifest_id=manifest.id,
            planning_authorization_id=authorization.id,
            actor="Founder",
            command_id="run-repaired-pipeline",
        )

        attempts = service.attempts(run.id)
        architecture_attempts = [
            attempt for attempt in attempts if attempt.role_id == "software_architect"
        ]
        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual(len(attempts), 6)
        self.assertEqual([value.valid for value in architecture_attempts], [False, True])
        requests = [
            request
            for request in invoker.requests
            if request.assignment.role_id == "software_architect"
        ]
        self.assertNotEqual(requests[0].context.id, requests[1].context.id)
        self.assertTrue(requests[1].validation_feedback)
        feedback = requests[1].context.document["upstream_artifacts"][-1]
        self.assertEqual(feedback["artifact_type"], "VALIDATION_FEEDBACK")
        self.assertEqual(feedback["content"]["validation_errors"], list(requests[1].validation_feedback))

    def test_exhausted_invalid_output_is_durable_and_replay_does_not_reinvoke(self):
        manifest, authorization = self.planning_scope(1)
        invoker = GoldenPlanningInvoker(always_invalid=True)
        service = AutonomousPlanningPipelineService(
            self.storage, invoker, self.capabilities
        )

        with self.assertRaises(PlanningPipelineFailedError) as raised:
            service.execute(
                self.mission.id,
                manifest_id=manifest.id,
                planning_authorization_id=authorization.id,
                actor="Founder",
                command_id="run-invalid-pipeline",
            )
        self.assertEqual(raised.exception.role_id, "mission_analyst")
        run = service.runs(self.mission.id)[0]
        self.assertEqual(run.status, "FAILED")
        self.assertEqual(len(service.attempts(run.id)), 2)
        self.assertTrue(
            self.authorizations.get_planning_authorization(authorization.id).closed
        )
        calls = len(invoker.requests)
        with self.assertRaises(PlanningPipelineFailedError):
            service.execute(
                self.mission.id,
                manifest_id=manifest.id,
                planning_authorization_id=authorization.id,
                actor="Founder",
                command_id="run-invalid-pipeline",
            )
        self.assertEqual(len(invoker.requests), calls)
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_backlog_revisions"
            ).fetchone()[0],
            0,
        )

    def test_regeneration_creates_a_new_proposal_and_preserves_history(self):
        first_manifest, first_authorization = self.planning_scope(1)
        first_service = AutonomousPlanningPipelineService(
            self.storage, GoldenPlanningInvoker(), self.capabilities
        )
        first = first_service.execute(
            self.mission.id,
            manifest_id=first_manifest.id,
            planning_authorization_id=first_authorization.id,
            actor="Founder",
            command_id="run-proposal-1",
        )
        second_manifest, second_authorization = self.planning_scope(
            2, action=PlanningAction.REGENERATE_BACKLOG
        )
        second_service = AutonomousPlanningPipelineService(
            self.storage, GoldenPlanningInvoker(), self.capabilities
        )
        second = second_service.execute(
            self.mission.id,
            manifest_id=second_manifest.id,
            planning_authorization_id=second_authorization.id,
            actor="Founder",
            command_id="run-proposal-2",
        )

        first_revision = first_service.revision(first.id)
        second_revision = second_service.revision(second.id)
        self.assertNotEqual(first.id, second.id)
        self.assertNotEqual(first_revision.id, second_revision.id)
        self.assertNotEqual(first_revision.revision_digest, second_revision.revision_digest)
        self.assertEqual(second_revision.revision_number, 2)
        self.assertEqual(second_revision.parent_revision_id, first_revision.id)
        self.assertEqual(len(second_service.runs(self.mission.id)), 2)

    def test_source_change_during_provider_call_rejects_unbound_output(self):
        manifest, authorization = self.planning_scope(1)

        def replace_specification(_request):
            mission = self.missions.get(self.mission.id)
            source = self.intake.current_source(self.mission.id)
            self.intake.update_from_text(
                self.mission.id,
                specification="# Replacement\n\nBuild a different local capability.",
                actor="Founder",
                command_id="replace-source-during-inference",
                reason="Exercise the source-version fence",
                expected_mission_version=mission.version,
                expected_source_version=source.version,
                source_name="replacement.md",
            )

        invoker = GoldenPlanningInvoker(before_first_response=replace_specification)
        service = AutonomousPlanningPipelineService(
            self.storage, invoker, self.capabilities
        )
        with self.assertRaises(PlanningPipelineFailedError):
            service.execute(
                self.mission.id,
                manifest_id=manifest.id,
                planning_authorization_id=authorization.id,
                actor="Founder",
                command_id="run-source-race",
            )

        run = service.runs(self.mission.id)[0]
        self.assertEqual(run.status, "FAILED")
        self.assertEqual(service.attempts(run.id), ())
        self.assertTrue(self.planning.get_manifest(manifest.id).stale)
        self.assertTrue(
            self.authorizations.get_planning_authorization(authorization.id).closed
        )
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_backlog_revisions"
            ).fetchone()[0],
            0,
        )

    def test_pipeline_ledger_is_append_only(self):
        manifest, authorization = self.planning_scope(1)
        service = AutonomousPlanningPipelineService(
            self.storage, GoldenPlanningInvoker(), self.capabilities
        )
        run = service.execute(
            self.mission.id,
            manifest_id=manifest.id,
            planning_authorization_id=authorization.id,
            actor="Founder",
            command_id="run-immutable-pipeline",
        )
        rows = (
            ("autonomous_planning_pipeline_runs", run.id),
            ("autonomous_planning_pipeline_invocations", service.attempts(run.id)[0].id),
            ("autonomous_planning_pipeline_artifacts", run.artifacts[0].id),
            (
                "autonomous_planning_pipeline_completions",
                self.storage.db.execute(
                    "SELECT id FROM autonomous_planning_pipeline_completions WHERE run_id=?",
                    (run.id,),
                ).fetchone()[0],
            ),
        )
        for table, row_id in rows:
            with self.subTest(table=table):
                with self.assertRaises(sqlite3.IntegrityError):
                    with self.storage.db:
                        self.storage.db.execute(
                            f"UPDATE {table} SET identity=identity WHERE id=?", (row_id,)
                        )


if __name__ == "__main__":
    unittest.main()
