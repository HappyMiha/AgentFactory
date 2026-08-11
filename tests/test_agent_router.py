import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.adapters import HEALTH_DIMENSIONS
from agent_factory.agent_router import AgentRouter, ROUTING_STRATEGIES, RoutingCandidate
from agent_factory.models import Agent, WorkItem
from agent_factory.registry import AgentRegistry
from agent_factory.reviewers import ReviewerRouter, ReviewSubject
from agent_factory.roles import ContractField, RoleDefinition, RoleRegistry
from agent_factory.storage import SQLiteStorage


class AgentRouterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self.temporary.name) / "state.db")
        RoleRegistry(self.storage).register(RoleDefinition(
            id="implementer", version="1.0.0", purpose="Implement",
            responsibilities=("Produce a candidate",),
            inputs=(ContractField("task", "object"),),
            outputs=(ContractField("candidate", "object"),),
            tools=("read_file",), permissions=("read_project",),
            limits=(("max_seconds", 60),),
            evidence=(ContractField("digest", "string"),),
        ))

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def qualify(self, agent_id, *, status="qualified", capabilities=("implement",), provider="codex"):
        dimensions = {
            name: {"status": "pass", "evidence": "router fixture"}
            for name in HEALTH_DIMENSIONS
        }
        return self.storage.record_worker_qualification(
            worker_id=agent_id, provider_id=provider, role="Implementation Worker",
            capabilities=list(capabilities), dimensions=dimensions,
            evidence={"agent": agent_id}, status=status, ttl_seconds=3600,
        )

    @staticmethod
    def candidates():
        return (
            RoutingCandidate("alpha", "codex", "model-a", .90, .10, 3.0, 200, .20),
            RoutingCandidate("beta", "claude", "model-b", .80, .05, 1.0, 100, .10, canary=True),
            RoutingCandidate("gamma", "codex", "model-c", .95, .20, 2.0, 300, .30),
        )

    def test_decision_records_every_dimension_exclusion_rationale_and_fallback(self):
        for candidate in self.candidates():
            self.qualify(candidate.agent_id, provider=candidate.provider_id)
        disabled = RoutingCandidate(
            "disabled", "claude", "model-d", .99, .01, .1, 10, 0, enabled=False
        )
        self.qualify("disabled", provider="claude")
        decision = AgentRouter(self.storage).route(
            decision_key="route:complete", role_id="implementer", role_version="1.0.0",
            qualification_role="Implementation Worker", required_capabilities={"implement"},
            candidates=(*self.candidates(), disabled), strategy="fallback",
            producer_model="model-z", require_independence=True,
        )
        self.assertEqual(decision.selected_agent_id, "gamma")
        self.assertEqual(set(decision.fallback_chain), {"alpha", "beta", "gamma"})
        self.assertEqual(decision.excluded[0]["reasons"], ["disabled"])
        for key in (
            "capabilities", "qualification_id", "qualification_status",
            "model_independent", "cost", "latency_ms", "load", "quality", "risk",
        ):
            self.assertIn(key, decision.eligible[0])
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE agent_routing_decisions SET rationale='changed' WHERE id=?",
                (decision.id,),
            )

    def test_failed_or_expired_latest_qualification_is_never_eligible(self):
        self.qualify("alpha")
        self.qualify("beta", status="failed", provider="claude")
        decision = AgentRouter(self.storage).route(
            decision_key="route:qualification", role_id="implementer", role_version="1.0.0",
            qualification_role="Implementation Worker", required_capabilities={"implement"},
            candidates=self.candidates()[:2], strategy="best-qualified",
        )
        self.assertEqual(decision.selected_agent_id, "alpha")
        self.assertIn("qualification_failed", decision.excluded[0]["reasons"])

    def test_all_strategies_are_deterministic(self):
        for candidate in self.candidates():
            self.qualify(candidate.agent_id, provider=candidate.provider_id)
        expected = {
            "pinned": "alpha", "best-qualified": "gamma", "cost-aware": "beta",
            "latency-aware": "beta", "diversity": "beta", "canary": "beta",
            "tournament": "gamma", "fallback": "gamma",
        }
        router = AgentRouter(self.storage)
        for strategy in ROUTING_STRATEGIES:
            with self.subTest(strategy=strategy):
                kwargs = {"pinned_agent_id": "alpha"} if strategy == "pinned" else {}
                decision = router.route(
                    decision_key=f"route:{strategy}", role_id="implementer",
                    role_version="1.0.0", qualification_role="Implementation Worker",
                    required_capabilities={"implement"}, candidates=self.candidates(),
                    strategy=strategy, producer_model="model-a",
                    producer_provider="codex", **kwargs,
                )
                self.assertEqual(decision.selected_agent_id, expected[strategy])
                replay = router.route(
                    decision_key=f"route:{strategy}", role_id="implementer",
                    role_version="1.0.0", qualification_role="Implementation Worker",
                    required_capabilities={"implement"}, candidates=self.candidates(),
                    strategy=strategy, producer_model="model-a",
                    producer_provider="codex", **kwargs,
                )
                self.assertEqual(replay, decision)

    def test_existing_model_aware_reviewer_rotation_remains_deterministic(self):
        agents = [
            Agent("author", "Author", "Implementation Worker", True, "codex", "", model="model-a"),
            Agent("review-b", "B", "Proxy Reviewer", True, "claude", "", model="model-b"),
            Agent("review-c", "C", "Proxy Reviewer", True, "ollama", "", model="model-c"),
        ]
        path = Path(self.temporary.name) / "agents.json"
        path.write_text(json.dumps({"agents": [agent.__dict__ for agent in agents]}), encoding="utf-8")
        registry = AgentRegistry(path)
        router = ReviewerRouter(self.storage, registry)
        project_id = self.storage.create_project("Review routing", "AF-011")
        selected = []
        for index in range(2):
            task_id = self.storage.create_task(WorkItem(f"Review {index}", "Review", project_id))
            run_id = self.storage.start_run(project_id, task_id, "review")
            artifact_id = self.storage.add_artifact(run_id, "implementation", "author", "codex", "candidate")
            selected.append(router.select(
                run_id=run_id, stage="review", candidate_ids=["review-b", "review-c"],
                subjects=[ReviewSubject("implementation", artifact_id, registry.get("author"))],
                required_role="Proxy Reviewer",
            ))
            self.storage.finish_run(run_id, "failed")
        first, second = selected
        self.assertEqual((first.id, second.id), ("review-b", "review-c"))


if __name__ == "__main__":
    unittest.main()
