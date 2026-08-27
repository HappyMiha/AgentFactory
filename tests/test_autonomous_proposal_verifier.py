import copy
import hashlib
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
)
from agent_factory.autonomous_proposal_verifier import (
    AutonomousProposalVerificationService,
    DeterministicProposalVerifier,
    ProposalVerificationCommandConflictError,
    ProposalVerificationStatus,
)
from agent_factory.mission_intake import AutonomousMissionIntakeService
from agent_factory.models import (
    ExecutionLocation,
    ProviderCapabilities,
)
from agent_factory.storage import SQLiteStorage
from tests.test_autonomous_planning_pipeline import (
    GoldenPlanningInvoker,
    golden_planning_outputs,
)


class AutonomousProposalVerifierTests(unittest.TestCase):
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
            name="Verifier mission",
            mission_owner="Founder",
            specification=(
                "# Product\n\nBuild a safe local health endpoint with deterministic "
                "validation and local persistence."
            ),
            actor="Founder",
            command_id="create-verifier-mission",
            mission_key="AFM-VERIFIER",
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
            (MissionPhase.SPECIFICATION_ANALYSIS, "verifier-analyze"),
            (MissionPhase.BACKLOG_GENERATION, "verifier-generate"),
        ):
            self.mission = self.missions.transition_phase(
                self.mission.id,
                phase,
                actor="Founder",
                command_id=command_id,
                expected_version=self.mission.version,
                reason="Advance the verifier fixture",
            )
        self.planning = AutonomousPlanningService(self.storage, self.capabilities)
        self.authorizations = AutonomousAuthorizationService(
            self.storage, self.capabilities
        )

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def complete_pipeline(self, *, reviewer_report=None):
        manifest = self.planning.create_manifest(
            self.mission.id,
            proposal_key="verified-proposal",
            actor="Founder",
            command_id="verifier-manifest",
            default_provider_id="local",
        )
        authorization = self.authorizations.grant_planning_authority(
            self.mission.id,
            planning_request_id=manifest.proposal_key,
            requested_action=PlanningAction.ANALYZE,
            role_models={
                assignment.role_id: assignment.model
                for assignment in manifest.assignments
            },
            provider_ids=("local",),
            actor="Founder",
            command_id="authorize-verifier-planning",
            reason="Produce the proposal that will be verified",
        )
        invoker = GoldenPlanningInvoker()
        if reviewer_report is not None:
            invoker.outputs["backlog_reviewer"] = {
                "output": {"review_report": copy.deepcopy(reviewer_report)},
                "evidence": {
                    "findings": copy.deepcopy(reviewer_report["findings"])
                },
            }
        pipeline = AutonomousPlanningPipelineService(
            self.storage, invoker, self.capabilities
        )
        return pipeline.execute(
            self.mission.id,
            manifest_id=manifest.id,
            planning_authorization_id=authorization.id,
            actor="Founder",
            command_id="run-verifier-pipeline",
        )

    @staticmethod
    def canonical_digest(value):
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def test_only_verified_complete_proposal_enters_approval_wait(self):
        run = self.complete_pipeline()
        before = self.missions.get(self.mission.id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.missions.transition_phase(
                self.mission.id,
                MissionPhase.WAITING_FOR_BACKLOG_APPROVAL,
                actor="Founder",
                command_id="attempt-verifier-bypass",
                expected_version=before.version,
                reason="This direct transition must be rejected",
            )
        unchanged = self.missions.get(self.mission.id)
        self.assertEqual(unchanged.phase, MissionPhase.BACKLOG_GENERATION)
        self.assertEqual(unchanged.version, before.version)

        service = AutonomousProposalVerificationService(self.storage)
        report = service.verify_and_present(
            run.id,
            actor="Founder",
            command_id="verify-ready-proposal",
            expected_mission_version=before.version,
        )

        self.assertTrue(report.ready)
        self.assertEqual(report.status, ProposalVerificationStatus.READY)
        self.assertEqual(report.findings, ())
        self.assertTrue(all(check["passed"] for check in report.checks))
        self.assertEqual(report.canonical_digest, report.revision_digest)
        self.assertEqual(
            self.canonical_digest(report.canonical_snapshot),
            report.canonical_digest,
        )
        self.assertEqual(
            report.presentation["proposal"]["canonical_digest"],
            report.canonical_digest,
        )
        self.assertEqual(
            service.current_ready_report(self.mission.id).id, report.id
        )
        mission = self.missions.get(self.mission.id)
        self.assertEqual(mission.phase, MissionPhase.WAITING_FOR_BACKLOG_APPROVAL)
        self.assertEqual(mission.version, before.version + 1)
        self.assertIsNone(mission.active_backlog_revision_id)
        self.assertEqual(
            self.storage.db.execute("SELECT COUNT(*) FROM work_items").fetchone()[0],
            0,
        )

        replay = service.verify_and_present(
            run.id,
            actor="Founder",
            command_id="verify-ready-proposal",
            expected_mission_version=before.version,
        )
        self.assertEqual(replay.id, report.id)
        with self.assertRaises(ProposalVerificationCommandConflictError):
            service.verify_and_present(
                run.id,
                actor="Founder",
                command_id="verify-ready-proposal",
                expected_mission_version=before.version + 1,
            )

    def test_adversarial_documents_fail_closed_with_specific_findings(self):
        golden = golden_planning_outputs()
        evaluator = DeterministicProposalVerifier()

        def evaluate(backlog=None, requirements=None, architecture=None):
            return evaluator.evaluate(
                backlog_document=(
                    backlog
                    if backlog is not None
                    else copy.deepcopy(
                        golden["backlog_planner"]["output"]["backlog_proposal"]
                    )
                ),
                requirements_document=(
                    requirements
                    if requirements is not None
                    else copy.deepcopy(
                        golden["product_requirements_analyst"]["output"][
                            "normalized_requirements"
                        ]
                    )
                ),
                architecture_document=(
                    architecture
                    if architecture is not None
                    else copy.deepcopy(
                        golden["software_architect"]["output"][
                            "architecture_proposal"
                        ]
                    )
                ),
                reviewer_report=copy.deepcopy(
                    golden["backlog_reviewer"]["output"]["review_report"]
                ),
                source_path="autonomous://specification",
                source_sha256="a" * 64,
                source_name="specification.md",
                known_artifact_references=("backlog_planner",),
            )

        fixtures = []
        malformed = copy.deepcopy(
            golden["backlog_planner"]["output"]["backlog_proposal"]
        )
        malformed["items"][1].pop("expected_artifacts")
        fixtures.append(("malformed", malformed, None, "MALFORMED_RICH_ITEM"))

        cyclic = copy.deepcopy(
            golden["backlog_planner"]["output"]["backlog_proposal"]
        )
        cyclic["items"][0]["dependencies"] = ["DEV-001"]
        fixtures.append(("cyclic", cyclic, None, "CYCLIC_DEPENDENCY"))

        orphaned = copy.deepcopy(
            golden["backlog_planner"]["output"]["backlog_proposal"]
        )
        orphaned["items"][1]["dependencies"] = ["MISSING-001"]
        fixtures.append(("orphaned", orphaned, None, "ORPHANED_REFERENCE"))

        duplicated = copy.deepcopy(
            golden["backlog_planner"]["output"]["backlog_proposal"]
        )
        duplicated["items"].append(copy.deepcopy(duplicated["items"][0]))
        fixtures.append(("duplicated", duplicated, None, "DUPLICATED_ITEM"))

        non_measurable = copy.deepcopy(
            golden["backlog_planner"]["output"]["backlog_proposal"]
        )
        non_measurable["items"][1]["acceptance_criteria"] = ["Looks good"]
        fixtures.append(
            (
                "non-measurable",
                non_measurable,
                None,
                "NON_MEASURABLE_ACCEPTANCE",
            )
        )

        non_canonical = copy.deepcopy(
            golden["backlog_planner"]["output"]["backlog_proposal"]
        )
        non_canonical["items"].reverse()
        fixtures.append(
            ("non-canonical", non_canonical, None, "NON_CANONICAL_ORDER")
        )

        untraceable_requirements = copy.deepcopy(
            golden["product_requirements_analyst"]["output"][
                "normalized_requirements"
            ]
        )
        untraceable_requirements["functional"][0]["source_references"] = [
            "internet.example"
        ]
        fixtures.append(
            (
                "scope-untraceable",
                None,
                untraceable_requirements,
                "SCOPE_UNTRACEABLE_REQUIREMENT",
            )
        )

        for label, backlog, requirements, expected_code in fixtures:
            with self.subTest(label=label):
                result = evaluate(backlog=backlog, requirements=requirements)
                self.assertFalse(result.ready)
                self.assertIn(
                    expected_code, {finding.code for finding in result.findings}
                )

    def test_reviewer_findings_are_resolved_or_explicitly_displayed(self):
        golden = golden_planning_outputs()
        evaluator = DeterministicProposalVerifier()

        def evaluate(finding, *, verdict="READY"):
            return evaluator.evaluate(
                backlog_document=copy.deepcopy(
                    golden["backlog_planner"]["output"]["backlog_proposal"]
                ),
                requirements_document=copy.deepcopy(
                    golden["product_requirements_analyst"]["output"][
                        "normalized_requirements"
                    ]
                ),
                architecture_document=copy.deepcopy(
                    golden["software_architect"]["output"][
                        "architecture_proposal"
                    ]
                ),
                reviewer_report={
                    "verdict": verdict,
                    "summary": "Reviewer fixture result.",
                    "findings": [finding],
                },
                source_path="autonomous://specification",
                source_sha256="b" * 64,
                source_name="specification.md",
                known_artifact_references=("backlog_planner",),
            )

        base = {
            "id": "REV-001",
            "severity": "LOW",
            "status": "RESOLVED",
            "message": "Clarify one low-risk implementation note.",
            "artifact_references": ["backlog_planner"],
            "display_to_human": False,
        }
        resolved = evaluate(copy.deepcopy(base))
        self.assertTrue(resolved.ready)
        self.assertEqual(resolved.reviewer_findings[0]["status"], "RESOLVED")

        disclosed_finding = {**base, "status": "OPEN", "display_to_human": True}
        disclosed = evaluate(disclosed_finding)
        self.assertTrue(disclosed.ready)
        self.assertEqual(disclosed.human_visible_findings[0]["id"], "REV-001")
        self.assertIn(
            "REVIEWER_FINDING_DISCLOSED",
            {finding.code for finding in disclosed.findings},
        )

        hidden = evaluate({**base, "status": "OPEN", "display_to_human": False})
        self.assertFalse(hidden.ready)
        self.assertIn(
            "HIDDEN_REVIEWER_FINDING",
            {finding.code for finding in hidden.findings},
        )

        high = evaluate(
            {
                **base,
                "severity": "HIGH",
                "status": "OPEN",
                "display_to_human": True,
            }
        )
        self.assertFalse(high.ready)
        self.assertIn(
            "UNRESOLVED_REVIEWER_BLOCKER",
            {finding.code for finding in high.findings},
        )

    def test_reviewer_needs_repair_persists_blocked_report_without_transition(self):
        run = self.complete_pipeline(
            reviewer_report={
                "verdict": "NEEDS_REPAIR",
                "summary": "The proposal requires another planning pass.",
                "findings": [],
            }
        )
        before = self.missions.get(self.mission.id)
        service = AutonomousProposalVerificationService(self.storage)
        report = service.verify_and_present(
            run.id,
            actor="Founder",
            command_id="verify-blocked-proposal",
            expected_mission_version=before.version,
        )
        self.assertFalse(report.ready)
        self.assertEqual(report.status, ProposalVerificationStatus.BLOCKED)
        self.assertIn(
            "REVIEWER_REQUIRES_REPAIR",
            {finding["code"] for finding in report.findings},
        )
        after = self.missions.get(self.mission.id)
        self.assertEqual(after.phase, MissionPhase.BACKLOG_GENERATION)
        self.assertEqual(after.version, before.version)

    def test_disclosed_reviewer_finding_is_retained_in_human_packet(self):
        reviewer_finding = {
            "id": "REV-VISIBLE-001",
            "severity": "LOW",
            "status": "OPEN",
            "message": "Show the operator a low-risk implementation note.",
            "artifact_references": ["backlog_planner"],
            "display_to_human": True,
        }
        run = self.complete_pipeline(
            reviewer_report={
                "verdict": "READY",
                "summary": "Ready with one explicitly disclosed low-risk note.",
                "findings": [reviewer_finding],
            }
        )
        before = self.missions.get(self.mission.id)
        service = AutonomousProposalVerificationService(self.storage)
        report = service.verify_and_present(
            run.id,
            actor="Founder",
            command_id="verify-visible-reviewer-finding",
            expected_mission_version=before.version,
        )
        self.assertTrue(report.ready)
        self.assertEqual(report.reviewer_findings, (reviewer_finding,))
        visible_ids = {
            finding.get("id") for finding in report.human_visible_findings
        }
        self.assertIn("REV-VISIBLE-001", visible_ids)
        self.assertEqual(
            report.presentation["review"]["reviewer_findings"],
            [reviewer_finding],
        )

    def test_ready_transition_rolls_back_with_verification_on_audit_failure(self):
        run = self.complete_pipeline()
        before = self.missions.get(self.mission.id)
        service = AutonomousProposalVerificationService(self.storage)
        original_event = self.storage._event

        def fail_ready_event(event_type, *args, **kwargs):
            if event_type == "autonomous_proposal.ready":
                raise RuntimeError("controlled verification audit failure")
            return original_event(event_type, *args, **kwargs)

        self.storage._event = fail_ready_event
        try:
            with self.assertRaisesRegex(RuntimeError, "controlled"):
                service.verify_and_present(
                    run.id,
                    actor="Founder",
                    command_id="verify-with-fault",
                    expected_mission_version=before.version,
                )
        finally:
            self.storage._event = original_event

        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_proposal_verifications"
            ).fetchone()[0],
            0,
        )
        unchanged = self.missions.get(self.mission.id)
        self.assertEqual(unchanged.phase, MissionPhase.BACKLOG_GENERATION)
        self.assertEqual(unchanged.version, before.version)
        report = service.verify_and_present(
            run.id,
            actor="Founder",
            command_id="verify-with-fault",
            expected_mission_version=before.version,
        )
        self.assertTrue(report.ready)

    def test_source_change_blocks_historical_proposal_and_report_is_immutable(self):
        run = self.complete_pipeline()
        mission = self.missions.get(self.mission.id)
        source = self.intake.current_source(self.mission.id)
        self.intake.update_from_text(
            self.mission.id,
            specification="# Changed\n\nBuild another local capability.",
            actor="Founder",
            command_id="change-source-before-verification",
            reason="Invalidate the historical proposal",
            expected_mission_version=mission.version,
            expected_source_version=source.version,
            source_name="changed.md",
        )
        current = self.missions.get(self.mission.id)
        service = AutonomousProposalVerificationService(self.storage)
        report = service.verify_and_present(
            run.id,
            actor="Founder",
            command_id="verify-stale-proposal",
            expected_mission_version=current.version,
        )
        self.assertFalse(report.ready)
        codes = {finding["code"] for finding in report.findings}
        self.assertIn("STALE_SPECIFICATION_SCOPE", codes)
        self.assertIn("INVALIDATED_REVISION", codes)
        self.assertEqual(
            self.missions.get(self.mission.id).phase,
            MissionPhase.SPECIFICATION_ANALYSIS,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            with self.storage.db:
                self.storage.db.execute(
                    "UPDATE autonomous_proposal_verifications "
                    "SET status='READY' WHERE id=?",
                    (report.id,),
                )


if __name__ == "__main__":
    unittest.main()
