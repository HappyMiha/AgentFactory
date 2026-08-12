import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.adapters import HEALTH_DIMENSIONS
from agent_factory.adr import ADRAlternative, ADRImpact, ADRService
from agent_factory.agent_router import RoutingCandidate
from agent_factory.blueprint import (
    REQUIRED_SECTIONS,
    AmendmentImpact,
    BlueprintAssumption,
    BlueprintDecision,
    BlueprintSections,
    BlueprintService,
    RejectedAlternative,
)
from agent_factory.mission_intake import MissionIntakeService, MissionSource
from agent_factory.models import WorkItem
from agent_factory.roles import ContractField, RoleDefinition, RoleRegistry
from agent_factory.storage import SQLiteStorage
from agent_factory.workforce import RolePoolRequirement, WorkforceCandidate, WorkforceComposer


class ADRServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self.temporary.name) / "state.db")
        self.project_id = self.storage.create_project("ADR", "AF-022")
        intake = MissionIntakeService(self.storage)
        self.intake_id = intake.create(
            project_id=self.project_id, mission_owner="Founder",
            intent="Govern architecture changes",
            objectives=["Propagate one approved decision"],
            success_measures=["Blueprint changes atomically"],
            constraints=["No partial contract activation"],
            sources=(MissionSource(
                "requirements", "scope", "authoritative", "1.0",
                "Founder brief", "Govern every architecture change",
            ),),
            high_risk_findings=["Partial propagation could split authority"],
        )
        assessment = intake.assess(self.intake_id)
        gap = next(value for value in assessment.blocking_gaps if value["kind"] == "high_risk")
        intake.resolve_gap(
            self.intake_id, gap_code=gap["code"], decision="Require atomic ADR apply",
            rationale="One transaction preserves prior authority",
            actor="Founder", actor_role="mission_owner",
        )
        self.assertEqual(intake.assess(self.intake_id).verdict, "READY_FOR_BLUEPRINT")
        RoleRegistry(self.storage).register(RoleDefinition(
            id="planner", version="1.0.0", purpose="Plan architecture",
            responsibilities=("Design governed changes",),
            inputs=(ContractField("mission", "object"),),
            outputs=(ContractField("plan", "object"),),
            tools=("read_file",), permissions=("read_project",),
            limits=(("max_seconds", 60),),
            evidence=(ContractField("digest", "string"),),
        ))
        dimensions = {
            name: {"status": "pass", "evidence": "ADR fixture"}
            for name in HEALTH_DIMENSIONS
        }
        self.storage.record_worker_qualification(
            worker_id="planner-a", provider_id="codex", role="Mission Planner",
            capabilities=["plan"], dimensions=dimensions,
            evidence={"worker": "planner-a"}, status="qualified", ttl_seconds=3600,
        )
        composition = WorkforceComposer(self.storage).compose(
            composition_key="adr-workforce-v1", mission_key=f"intake:{self.intake_id}",
            budget=5, pools=(RolePoolRequirement(
                key="planning", role_id="planner", role_version="1.0.0",
                qualification_role="Mission Planner", required_capabilities=("plan",),
                pool_strategy="singleton", routing_strategy="best-qualified",
                minimum_replicas=1, maximum_replicas=1, arbitration_rule="single",
                candidates=(WorkforceCandidate(RoutingCandidate(
                    "planner-a", "codex", "model-a", .9, .1, 1, 100, .1,
                )),),
            ),),
        )
        self.composition_id = composition.id
        self.blueprints = BlueprintService(self.storage)
        self.first = self.blueprints.create(
            blueprint_key="adr_factory", intake_id=self.intake_id,
            composition_id=self.composition_id, sections=self.sections(),
            decisions=self.decisions(), assumptions=self.assumptions(),
            rejected_alternatives=self.alternatives(), created_by="Architect",
        )
        self.blueprints.sign(
            self.first.id, expected_version=1,
            expected_digest=self.first.blueprint_digest, decision="approved",
            signer="Founder", signer_role="mission_owner", note="Baseline approved",
        )
        self.authorization_id = self.blueprints.authorize_execution(
            self.first.id, expected_digest=self.first.blueprint_digest
        )
        self.service = ADRService(self.storage)

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
            budgets={"total": budget}, policies={"mutation": "approval-required"},
            recovery={"resume": "latest-checkpoint"},
        )

    @staticmethod
    def assumptions():
        return (BlueprintAssumption("single_node", "Initial deployment is one node"),)

    @staticmethod
    def alternatives():
        return (RejectedAlternative(
            "partial_update", "Update contracts separately", "Can split active authority",
        ),)

    @staticmethod
    def decisions():
        return tuple(BlueprintDecision(
            key=f"{section}_decision", section=section,
            rationale=f"Govern {section}", source_keys=("requirements",),
            risk_refs=("Partial propagation could split authority",) if index == 0 else (),
            assumption_refs=("single_node",) if index == 0 else (),
            rejected_alternative_refs=("partial_update",) if index == 0 else (),
        ) for index, section in enumerate(REQUIRED_SECTIONS))

    def propose(self):
        return self.service.propose(
            adr_key="increase_budget", version=1, blueprint_id=self.first.id,
            context="Validation needs a larger bounded budget",
            alternatives=(
                ADRAlternative("keep_limit", "Keep the current cap", "May block validation"),
                ADRAlternative("raise_limit", "Raise only this cap", "Costs can increase"),
            ),
            decision="Raise the Blueprint budget from five to six",
            consequences=("New runs can spend one additional unit", "Existing evidence is retained"),
            affected_contracts=("delivery_workflow",),
            evidence={"benchmark": "validation-budget-2026-08-12"},
            material_domains=("authority", "external_contracts"),
            architecture_owner="Founder", created_by="Architect",
        )

    def impact(self):
        task_id = self.storage.create_task(
            WorkItem("Affected task", "Uses the delivery workflow", self.project_id)
        )
        run_id = self.storage.start_run(self.project_id, task_id, "delivery")
        artifact_id = self.storage.add_artifact(
            run_id, "plan", "architect", "local", "budget evidence"
        )
        return ADRImpact(
            affected_tasks=(task_id,), context_packages=(),
            policies=("execution_budget",), evaluations=(), artifacts=(artifact_id,),
            deployment_assumptions=("single_node_capacity",),
            blueprint_sections=("budgets",),
        )

    def approve(self, adr_id: int, impact: ADRImpact):
        analysis_id = self.service.analyze_impact(
            adr_id, impact, analyzed_by="Architecture Analyst"
        )
        approval_id = self.service.decide(
            adr_id, decision="approved", reviewer="Founder",
            reviewer_role="human_architecture_owner",
            note="Exact decision and impact reviewed",
        )
        return analysis_id, approval_id

    def apply(self, adr_id: int, workflow_updates=None):
        return self.service.apply(
            adr_id, composition_id=self.composition_id, sections=self.sections(budget=6),
            decisions=self.decisions(), assumptions=self.assumptions(),
            rejected_alternatives=self.alternatives(),
            amendment_impact=AmendmentImpact(
                affected_sections=("budgets",),
                execution_effect="New executions use budget six",
                migration_plan="Existing runs remain bound to version one",
                risk_changes="Maximum cost increases by one",
            ),
            workflow_updates=workflow_updates or {
                "delivery_workflow": {"budget": 6, "version": "2.0.0"}
            },
            applied_by="Founder", applied_by_role="mission_owner",
        )

    def test_adr_records_complete_decision_and_requires_impact_before_human_approval(self):
        adr_id = self.propose()
        row = self.storage.db.execute(
            "SELECT * FROM architecture_decisions WHERE id=?", (adr_id,)
        ).fetchone()
        self.assertEqual(row["status"], "proposed")
        self.assertEqual(len(json.loads(row["alternatives_json"])), 2)
        self.assertTrue(json.loads(row["consequences_json"]))
        self.assertEqual(json.loads(row["affected_contracts_json"]), ["delivery_workflow"])
        self.assertTrue(json.loads(row["evidence_json"])["benchmark"])
        with self.assertRaisesRegex(PermissionError, "impact analysis"):
            self.service.decide(
                adr_id, decision="approved", reviewer="Founder",
                reviewer_role="human_architecture_owner", note="Premature",
            )
        impact = self.impact()
        self.service.analyze_impact(adr_id, impact, analyzed_by="Analyst")
        record = self.service.get(adr_id)
        self.assertEqual(set(record.impact), {
            "schema_version", "affected_tasks", "context_packages", "policies",
            "evaluations", "artifacts", "deployment_assumptions", "blueprint_sections",
        })
        with self.assertRaisesRegex(PermissionError, "human architecture owner"):
            self.service.decide(
                adr_id, decision="approved", reviewer="Worker",
                reviewer_role="agent", note="Self approved",
            )
        self.service.decide(
            adr_id, decision="approved", reviewer="Founder",
            reviewer_role="human_architecture_owner", note="Impact reviewed",
        )
        self.assertEqual(self.service.get(adr_id).status, "approved")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE architecture_decisions SET decision='other' WHERE id=?", (adr_id,)
            )

    def test_approved_adr_atomically_versions_blueprint_workflow_and_impacts(self):
        adr_id = self.propose()
        impact = self.impact()
        self.approve(adr_id, impact)
        result = self.apply(adr_id)
        self.assertEqual((result.prior_blueprint_id, result.new_blueprint.version), (
            self.first.id, 2,
        ))
        self.assertEqual(len(result.workflow_contract_version_ids), 1)
        contract = self.storage.db.execute(
            "SELECT * FROM adr_workflow_contract_versions WHERE id=?",
            (result.workflow_contract_version_ids[0],),
        ).fetchone()
        self.assertEqual((contract["contract_key"], contract["version"]), (
            "delivery_workflow", 1,
        ))
        propagated = {
            row["target_type"] for row in self.storage.db.execute(
                "SELECT target_type FROM adr_contract_propagations WHERE application_id=?",
                (result.id,),
            )
        }
        self.assertEqual(propagated, {
            "task", "policy", "artifact", "deployment_assumption", "workflow_contract",
        })
        self.assertEqual(self.service.get(adr_id).status, "applied")
        self.assertEqual(self.apply(adr_id), result)

    def test_failed_contract_propagation_rolls_back_and_keeps_prior_blueprint_active(self):
        adr_id = self.propose()
        self.approve(adr_id, self.impact())
        with self.assertRaises(TypeError):
            self.apply(adr_id, {
                "delivery_workflow": {"budget": 6, "invalid": {"not-json"}}
            })
        versions = self.storage.db.execute(
            "SELECT id,version FROM factory_blueprints WHERE blueprint_key='adr_factory'"
        ).fetchall()
        self.assertEqual([(row["id"], row["version"]) for row in versions], [
            (self.first.id, 1),
        ])
        self.assertEqual(self.service.get(adr_id).status, "approved")
        self.assertEqual(
            self.storage.db.execute(
                "SELECT id FROM blueprint_execution_authorizations WHERE blueprint_id=?",
                (self.first.id,),
            ).fetchone()[0],
            self.authorization_id,
        )
        result = self.apply(adr_id)
        self.assertEqual(result.new_blueprint.version, 2)


if __name__ == "__main__":
    unittest.main()
