import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.adapters import HEALTH_DIMENSIONS
from agent_factory.agent_router import RoutingCandidate
from agent_factory.blueprint import (
    AmendmentImpact,
    BlueprintAssumption,
    BlueprintDecision,
    BlueprintSections,
    BlueprintService,
    RejectedAlternative,
    REQUIRED_SECTIONS,
)
from agent_factory.mission_intake import MissionIntakeService, MissionSource
from agent_factory.roles import ContractField, RoleDefinition, RoleRegistry
from agent_factory.storage import SQLiteStorage
from agent_factory.workforce import RolePoolRequirement, WorkforceCandidate, WorkforceComposer


class BlueprintServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self.temporary.name) / "state.db")
        project_id = self.storage.create_project("Blueprint", "AF-013")
        intake_service = MissionIntakeService(self.storage)
        self.intake_id = intake_service.create(
            project_id=project_id, mission_owner="Founder",
            intent="Create a governed mission operating design",
            objectives=["Deliver a versioned Blueprint"],
            success_measures=["Exact owner approval gates execution"],
            constraints=["No execution before approval"],
            sources=(MissionSource(
                "requirements", "scope", "authoritative", "1.0",
                "Founder brief", "Governed Blueprint required",
            ),),
            high_risk_findings=["Unapproved execution could mutate external state"],
        )
        blocked = intake_service.assess(self.intake_id)
        risk_gap = next(gap for gap in blocked.blocking_gaps if gap["kind"] == "high_risk")
        intake_service.resolve_gap(
            self.intake_id, gap_code=risk_gap["code"], decision="Mitigate with exact gate",
            rationale="Blueprint approval remains a Control Plane authority",
            actor="Founder", actor_role="mission_owner",
        )
        self.assertEqual(intake_service.assess(self.intake_id).verdict, "READY_FOR_BLUEPRINT")

        RoleRegistry(self.storage).register(RoleDefinition(
            id="planner", version="1.0.0", purpose="Plan the mission",
            responsibilities=("Produce operating design",),
            inputs=(ContractField("mission", "object"),),
            outputs=(ContractField("plan", "object"),),
            tools=("read_file",), permissions=("read_project",),
            limits=(("max_seconds", 60),),
            evidence=(ContractField("digest", "string"),),
        ))
        dimensions = {
            name: {"status": "pass", "evidence": "blueprint fixture"}
            for name in HEALTH_DIMENSIONS
        }
        self.storage.record_worker_qualification(
            worker_id="planner-a", provider_id="codex", role="Mission Planner",
            capabilities=["plan"], dimensions=dimensions, evidence={"worker": "planner-a"},
            status="qualified", ttl_seconds=3600,
        )
        candidate = WorkforceCandidate(RoutingCandidate(
            "planner-a", "codex", "model-a", .9, .1, 1, 100, .1,
        ))
        composition = WorkforceComposer(self.storage).compose(
            composition_key="blueprint-workforce-v1",
            mission_key=f"intake:{self.intake_id}", budget=5,
            pools=(RolePoolRequirement(
                key="planning", role_id="planner", role_version="1.0.0",
                qualification_role="Mission Planner", required_capabilities=("plan",),
                pool_strategy="singleton", routing_strategy="best-qualified",
                minimum_replicas=1, maximum_replicas=1, arbitration_rule="single",
                candidates=(candidate,),
            ),),
        )
        self.composition_id = composition.id
        self.service = BlueprintService(self.storage)

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    @staticmethod
    def sections(*, budget=5):
        return BlueprintSections(
            modules={"orchestrator": "control-plane"},
            workforce={"planning_pool": "planning"},
            tools={"allow": ["read_file"]},
            context={"source_policy": "authoritative-first"},
            verification={"required": ["deterministic", "independent"]},
            budgets={"total": budget},
            policies={"mutation": "approval-required"},
            recovery={"resume": "latest-checkpoint"},
        )

    @staticmethod
    def assumptions():
        return (BlueprintAssumption("single_node", "The first mission runs on one node"),)

    @staticmethod
    def alternatives():
        return (RejectedAlternative(
            "unbounded_team", "Use an unbounded agent team", "Violates budget policy",
        ),)

    @staticmethod
    def decisions(*, include_trace=True):
        decisions = []
        for index, section in enumerate(REQUIRED_SECTIONS):
            decisions.append(BlueprintDecision(
                key=f"{section}_decision", section=section,
                rationale=f"Define governed {section}", source_keys=("requirements",),
                risk_refs=("Unapproved execution could mutate external state",)
                if index == 0 and include_trace else (),
                assumption_refs=("single_node",) if index == 0 and include_trace else (),
                rejected_alternative_refs=("unbounded_team",)
                if index == 0 and include_trace else (),
            ))
        return tuple(decisions)

    def create_blueprint(self):
        return self.service.create(
            blueprint_key="factory_alpha", intake_id=self.intake_id,
            composition_id=self.composition_id, sections=self.sections(),
            decisions=self.decisions(), assumptions=self.assumptions(),
            rejected_alternatives=self.alternatives(), created_by="Architect",
        )

    def test_blueprint_validates_sections_and_complete_mission_trace(self):
        blueprint = self.create_blueprint()
        self.assertEqual(set(blueprint.sections), set(REQUIRED_SECTIONS))
        self.assertEqual(
            blueprint.sections["workforce"]["composition_id"], self.composition_id
        )
        self.assertEqual(set(blueprint.trace["coverage"]["sections"]), set(REQUIRED_SECTIONS))
        self.assertEqual(blueprint.trace["coverage"]["source_keys"], ["requirements"])
        self.assertEqual(blueprint.trace["coverage"]["assumptions"], ["single_node"])
        self.assertEqual(
            blueprint.trace["coverage"]["rejected_alternatives"], ["unbounded_team"]
        )
        with self.assertRaisesRegex(ValueError, "every mission risk"):
            self.service.create(
                blueprint_key="missing_trace", intake_id=self.intake_id,
                composition_id=self.composition_id, sections=self.sections(),
                decisions=self.decisions(include_trace=False), assumptions=self.assumptions(),
                rejected_alternatives=self.alternatives(), created_by="Architect",
            )
        with self.assertRaisesRegex(ValueError, "section tools"):
            BlueprintSections(
                modules={"x": 1}, workforce={"x": 1}, tools={}, context={"x": 1},
                verification={"x": 1}, budgets={"x": 1}, policies={"x": 1},
                recovery={"x": 1},
            )

    def test_execution_requires_owner_signature_of_exact_version_and_digest(self):
        blueprint = self.create_blueprint()
        with self.assertRaisesRegex(PermissionError, "blocked"):
            self.service.authorize_execution(
                blueprint.id, expected_digest=blueprint.blueprint_digest
            )
        with self.assertRaisesRegex(PermissionError, "mission owner"):
            self.service.sign(
                blueprint.id, expected_version=1, expected_digest=blueprint.blueprint_digest,
                decision="approved", signer="Worker", signer_role="architect", note="Approve",
            )
        with self.assertRaisesRegex(PermissionError, "exact version and digest"):
            self.service.sign(
                blueprint.id, expected_version=1, expected_digest="0" * 64,
                decision="approved", signer="Founder", signer_role="mission_owner",
                note="Wrong digest",
            )
        approval_id = self.service.sign(
            blueprint.id, expected_version=1, expected_digest=blueprint.blueprint_digest,
            decision="approved", signer="Founder", signer_role="mission_owner",
            note="Exact operating design reviewed",
        )
        authorization_id = self.service.authorize_execution(
            blueprint.id, expected_digest=blueprint.blueprint_digest
        )
        approved = self.service.get(blueprint.id)
        self.assertEqual(approved.approval["id"], approval_id)
        self.assertTrue(approved.execution_authorized)
        self.assertEqual(self.service.authorize_execution(
            blueprint.id, expected_digest=blueprint.blueprint_digest
        ), authorization_id)

    def test_amendment_is_new_owner_only_version_and_preserves_history(self):
        first = self.create_blueprint()
        first_approval = self.service.sign(
            first.id, expected_version=1, expected_digest=first.blueprint_digest,
            decision="approved", signer="Founder", signer_role="mission_owner",
            note="Version one approved",
        )
        first_authorization = self.service.authorize_execution(
            first.id, expected_digest=first.blueprint_digest
        )
        impact = AmendmentImpact(
            affected_sections=("budgets",),
            execution_effect="New executions use a larger bounded budget",
            migration_plan="Existing history remains on version one",
            risk_changes="No new risk; cost ceiling increases",
        )
        with self.assertRaisesRegex(PermissionError, "mission owner"):
            self.service.amend(
                first.id, composition_id=self.composition_id, sections=self.sections(budget=6),
                decisions=self.decisions(), assumptions=self.assumptions(),
                rejected_alternatives=self.alternatives(), impact=impact,
                actor="Architect", actor_role="architect",
            )
        second = self.service.amend(
            first.id, composition_id=self.composition_id, sections=self.sections(budget=6),
            decisions=self.decisions(), assumptions=self.assumptions(),
            rejected_alternatives=self.alternatives(), impact=impact,
            actor="Founder", actor_role="mission_owner",
        )
        self.assertEqual((second.version, second.parent_blueprint_id), (2, first.id))
        self.assertNotEqual(second.blueprint_digest, first.blueprint_digest)
        self.assertEqual(second.amendment_impact["affected_sections"], ["budgets"])
        with self.assertRaisesRegex(PermissionError, "latest Blueprint"):
            self.service.authorize_execution(first.id, expected_digest=first.blueprint_digest)
        with self.assertRaisesRegex(PermissionError, "blocked"):
            self.service.authorize_execution(second.id, expected_digest=second.blueprint_digest)
        second_approval = self.service.sign(
            second.id, expected_version=2, expected_digest=second.blueprint_digest,
            decision="approved", signer="Founder", signer_role="mission_owner",
            note="Version two impact reviewed",
        )
        second_authorization = self.service.authorize_execution(
            second.id, expected_digest=second.blueprint_digest
        )
        self.assertTrue(second_approval > first_approval)
        self.assertTrue(second_authorization > first_authorization)
        history = self.storage.db.execute(
            """SELECT a.id approval_id,x.id authorization_id
                 FROM blueprint_approvals a JOIN blueprint_execution_authorizations x
                   ON x.approval_id=a.id WHERE a.blueprint_id=?""",
            (first.id,),
        ).fetchone()
        self.assertEqual((history["approval_id"], history["authorization_id"]), (
            first_approval, first_authorization,
        ))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE factory_blueprints SET version=3 WHERE id=?", (first.id,)
            )


if __name__ == "__main__":
    unittest.main()
