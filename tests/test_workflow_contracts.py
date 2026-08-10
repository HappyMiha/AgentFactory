import json
import tempfile
import unittest
from pathlib import Path

from agent_factory.models import ProviderResult, WorkItem
from agent_factory.providers import Provider
from agent_factory.runtime import AgentRuntime
from agent_factory.storage import SQLiteStorage
from agent_factory.workflow import WorkflowEngine
from agent_factory.workflow_contracts import (
    StageContractError,
    WorkflowContractError,
    validate_workflow,
)


def stage(stage_id, agent="worker", depends_on=None):
    if stage_id in {"policy-precheck", "policy-postcheck"}:
        verdicts = ["ALIGNED", "CONDITIONALLY_ALIGNED", "NOT_ALIGNED"]
    elif stage_id == "validation":
        verdicts = ["PASS", "FAIL"]
    else:
        verdicts = ["COMPLETE"]
    return {
        "id": stage_id,
        "name": stage_id,
        "agent": agent,
        "artifact": f"{stage_id}.json",
        "depends_on": depends_on or [],
        "acceptance_criteria": [f"{stage_id} criterion"],
        "contract": {"allowed_verdicts": verdicts},
    }


def workflow(stages):
    return {
        "id": "custom",
        "guardrails": {
            "precheck_stage": "policy-precheck",
            "postcheck_stage": "policy-postcheck",
            "guardian_agent": "policy-guardian",
        },
        "stages": stages,
    }


class ContractProvider(Provider):
    name = "contract"

    def __init__(self, overrides=None):
        self.overrides = overrides or {}

    def health(self):
        return {"healthy": True}

    def execute(self, agent, item, context, approval=None):
        stage_id = item.inputs["stage"]
        payload = self.overrides.get(stage_id)
        if payload is None:
            verdict = (
                "ALIGNED"
                if stage_id in {"policy-precheck", "policy-postcheck"}
                else "PASS" if stage_id == "validation" else "COMPLETE"
            )
            payload = {
                "verdict": verdict,
                "criteria_evidence": {
                    criterion: "specific evidence" for criterion in item.acceptance_criteria
                },
                "summary": "typed result",
            }
        return ProviderResult(True, json.dumps(payload), self.name)


class WorkflowGraphContractTests(unittest.TestCase):
    def test_duplicate_missing_dependency_and_cycle_are_rejected(self):
        duplicate = workflow(
            [
                stage("policy-precheck", "policy-guardian"),
                stage("policy-precheck", "policy-guardian"),
                stage("policy-postcheck", "policy-guardian"),
            ]
        )
        with self.assertRaises(WorkflowContractError):
            validate_workflow(duplicate)
        missing = workflow(
            [
                stage("policy-precheck", "policy-guardian", ["unknown"]),
                stage("policy-postcheck", "policy-guardian", ["policy-precheck"]),
            ]
        )
        with self.assertRaises(WorkflowContractError):
            validate_workflow(missing)
        cycle = workflow(
            [
                stage("policy-precheck", "policy-guardian", ["middle"]),
                stage("middle", depends_on=["policy-precheck"]),
                stage("policy-postcheck", "policy-guardian", ["middle"]),
            ]
        )
        with self.assertRaises(WorkflowContractError):
            validate_workflow(cycle)

    def test_configured_guardrail_boundaries_are_enforced(self):
        wrong_agent = workflow(
            [
                stage("policy-precheck", "worker"),
                stage("policy-postcheck", "policy-guardian", ["policy-precheck"]),
            ]
        )
        with self.assertRaises(WorkflowContractError):
            validate_workflow(wrong_agent)
        non_terminal = workflow(
            [
                stage("policy-precheck", "policy-guardian"),
                stage("policy-postcheck", "policy-guardian", ["policy-precheck"]),
                stage("later", depends_on=["policy-postcheck"]),
            ]
        )
        with self.assertRaises(WorkflowContractError):
            validate_workflow(non_terminal)

    def test_every_delivery_stage_is_between_policy_boundaries(self):
        valid = workflow(
            [
                stage("policy-precheck", "policy-guardian"),
                stage("delivery", depends_on=["policy-precheck"]),
                stage("policy-postcheck", "policy-guardian", ["delivery"]),
            ]
        )
        self.assertEqual(len(validate_workflow(valid)), 3)
        bypass = workflow(
            [
                stage("policy-precheck", "policy-guardian"),
                stage("delivery", depends_on=["policy-precheck"]),
                stage("side"),
                stage("policy-postcheck", "policy-guardian", ["delivery", "side"]),
            ]
        )
        with self.assertRaises(WorkflowContractError):
            validate_workflow(bypass)
        incomplete_postcheck = workflow(
            [
                stage("policy-precheck", "policy-guardian"),
                stage("delivery", depends_on=["policy-precheck"]),
                stage("side", depends_on=["policy-precheck"]),
                stage("policy-postcheck", "policy-guardian", ["delivery"]),
            ]
        )
        with self.assertRaises(WorkflowContractError):
            validate_workflow(incomplete_postcheck)

    def test_reviewer_pool_requires_default_member_and_ancestor_subject(self):
        review = stage("review", "reviewer", ["policy-precheck"])
        review["reviewer_pool"] = ["other-reviewer"]
        review["review_of"] = ["policy-precheck"]
        invalid_default = workflow(
            [
                stage("policy-precheck", "policy-guardian"),
                review,
                stage("policy-postcheck", "policy-guardian", ["review"]),
            ]
        )
        with self.assertRaisesRegex(WorkflowContractError, "default agent"):
            validate_workflow(invalid_default)

        review["reviewer_pool"] = ["reviewer"]
        review["review_of"] = ["policy-postcheck"]
        with self.assertRaisesRegex(WorkflowContractError, "ancestor"):
            validate_workflow(invalid_default)


class WorkflowStageContractTests(unittest.TestCase):
    def run_with(self, provider):
        temporary = tempfile.TemporaryDirectory()
        storage = SQLiteStorage(Path(temporary.name) / "state.db")
        project_id = storage.create_project("Example", "Contract test")
        task_id = storage.create_task(
            WorkItem(
                title="Capability",
                description="Produce reviewed evidence",
                project_id=project_id,
                acceptance_criteria=["Evidence exists"],
            )
        )
        runtime = AgentRuntime(
            providers={
                name: provider
                for name in (
                    "claude",
                    "codex",
                    "gemini",
                    "antigravity",
                    "ollama",
                    "deterministic",
                )
            }
        )
        callback = lambda: WorkflowEngine(storage, runtime=runtime).run(
            "delivery", storage.get_task(task_id)
        )
        return temporary, storage, callback

    def test_blocking_precheck_creates_no_human_gate(self):
        provider = ContractProvider(
            {
                "policy-precheck": {
                    "verdict": "NOT_ALIGNED",
                    "criteria_evidence": {
                        "The task is consistent with configured policy": "conflict found",
                        "The expected outcome is explicit and testable": "outcome is ambiguous",
                    },
                    "summary": "blocked",
                }
            }
        )
        temporary, storage, callback = self.run_with(provider)
        try:
            with self.assertRaises(StageContractError):
                callback()
            self.assertEqual(storage.approvals(), [])
            self.assertEqual(storage.latest_run()["status"], "failed")
        finally:
            storage.close()
            temporary.cleanup()

    def test_failed_validation_creates_no_human_gate(self):
        provider = ContractProvider(
            {
                "validation": {
                    "verdict": "FAIL",
                    "criteria_evidence": {
                        "Every task acceptance criterion has evidence": "one criterion missing",
                        "Known concerns and residual risks are explicit": "risk recorded",
                    },
                    "summary": "failed",
                }
            }
        )
        temporary, storage, callback = self.run_with(provider)
        try:
            with self.assertRaises(StageContractError):
                callback()
            self.assertEqual(storage.approvals(), [])
        finally:
            storage.close()
            temporary.cleanup()

    def test_missing_acceptance_evidence_blocks_gate(self):
        provider = ContractProvider(
            {
                "implementation": {
                    "verdict": "COMPLETE",
                    "criteria_evidence": {},
                    "summary": "unsupported",
                }
            }
        )
        temporary, storage, callback = self.run_with(provider)
        try:
            with self.assertRaises(StageContractError):
                callback()
            self.assertEqual(storage.approvals(), [])
        finally:
            storage.close()
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
