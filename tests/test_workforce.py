import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.adapters import HEALTH_DIMENSIONS
from agent_factory.agent_router import RoutingCandidate
from agent_factory.roles import ContractField, RoleDefinition, RoleRegistry
from agent_factory.storage import SQLiteStorage
from agent_factory.workforce import (
    RolePoolRequirement,
    WorkforceCandidate,
    WorkforceComposer,
)


class WorkforceComposerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self.temporary.name) / "state.db")
        self.composer = WorkforceComposer(self.storage)
        RoleRegistry(self.storage).register(RoleDefinition(
            id="analyst", version="1.0.0", purpose="Analyze mission evidence",
            responsibilities=("Produce a bounded analysis",),
            inputs=(ContractField("mission", "object"),),
            outputs=(ContractField("analysis", "object"),),
            tools=("read_file",), permissions=("read_project",),
            limits=(("max_seconds", 60),),
            evidence=(ContractField("digest", "string"),),
        ))

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def qualify(self, agent_id, *, provider="codex", capabilities=("analyze",)):
        dimensions = {
            name: {"status": "pass", "evidence": "workforce fixture"}
            for name in HEALTH_DIMENSIONS
        }
        self.storage.record_worker_qualification(
            worker_id=agent_id, provider_id=provider, role="Mission Analyst",
            capabilities=list(capabilities), dimensions=dimensions,
            evidence={"agent": agent_id}, status="qualified", ttl_seconds=3600,
        )

    @staticmethod
    def candidate(
        agent_id, *, provider="codex", model=None, cost=1.0, quality=.8, capacity=1
    ):
        return WorkforceCandidate(RoutingCandidate(
            agent_id, provider, model or f"model-{agent_id}", quality, .1,
            cost, 100, .1,
        ), capacity)

    @staticmethod
    def pool(key, candidates, **overrides):
        values = {
            "key": key, "role_id": "analyst", "role_version": "1.0.0",
            "qualification_role": "Mission Analyst",
            "required_capabilities": ("analyze",), "pool_strategy": "elastic",
            "routing_strategy": "best-qualified", "minimum_replicas": 1,
            "maximum_replicas": 2, "arbitration_rule": "single",
            "candidates": tuple(candidates),
        }
        values.update(overrides)
        return RolePoolRequirement(**values)

    def test_composition_emits_pool_contract_qualifications_and_fallbacks(self):
        candidates = (
            self.candidate("alpha", quality=.9),
            self.candidate("beta", provider="claude", quality=.8),
        )
        for candidate in candidates:
            self.qualify(candidate.routing.agent_id, provider=candidate.routing.provider_id)
        result = self.composer.compose(
            composition_key="mission-a-v1", mission_key="mission-a",
            pools=(self.pool("analysis", candidates),), budget=5,
        )
        self.assertEqual(result.status, "ready")
        self.assertTrue(result.rationale["can_dispatch"])
        pool = result.pools[0]
        self.assertEqual((pool["role_id"], pool["pool_strategy"]), ("analyst", "elastic"))
        self.assertEqual((pool["minimum_replicas"], pool["maximum_replicas"]), (1, 2))
        self.assertEqual(pool["primary_assignments"], ["alpha"])
        self.assertEqual(pool["fallback_assignments"], ["beta"])
        self.assertTrue(all(item["qualification_id"] for item in pool["qualifications"]))
        self.assertIsNotNone(pool["routing_decision_id"])
        self.assertEqual(self.composer.compose(
            composition_key="mission-a-v1", mission_key="mission-a",
            pools=(self.pool("analysis", candidates),), budget=5,
        ).id, result.id)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE workforce_role_pools SET valid=0 WHERE id=?", (pool["id"],)
            )

    def test_strengthened_pool_uses_two_heterogeneous_agents_and_arbitration(self):
        candidates = (
            self.candidate("codex-a", provider="codex", model="gpt-a", quality=.9),
            self.candidate("claude-b", provider="claude", model="claude-b", quality=.8),
            self.candidate("codex-c", provider="codex", model="gpt-c", quality=.7),
        )
        for candidate in candidates:
            self.qualify(candidate.routing.agent_id, provider=candidate.routing.provider_id)
        requirement = self.pool(
            "strengthened_analysis", candidates, pool_strategy="strengthened",
            minimum_replicas=2, maximum_replicas=3, arbitration_rule="majority",
            require_model_independence=True, require_provider_diversity=True,
        )
        result = self.composer.compose(
            composition_key="mission-b-v1", mission_key="mission-b",
            pools=(requirement,), budget=10,
        )
        pool = result.pools[0]
        selected = set(pool["primary_assignments"])
        self.assertEqual((result.status, len(selected), pool["arbitration_rule"]), (
            "ready", 2, "majority",
        ))
        selected_details = [
            item for item in pool["qualifications"] if item["agent_id"] in selected
        ]
        self.assertEqual(len({item["provider_id"] for item in selected_details}), 2)
        self.assertEqual(len({item["model_identity"] for item in selected_details}), 2)

    def test_missing_capability_independence_capacity_or_budget_is_visible(self):
        missing = self.candidate("missing")
        self.qualify("missing", capabilities=("write",))
        capacity = self.candidate("busy", capacity=0)
        self.qualify("busy")
        same_model = (
            self.candidate("same-a", provider="codex", model="same"),
            self.candidate("same-b", provider="claude", model="same"),
        )
        for candidate in same_model:
            self.qualify(candidate.routing.agent_id, provider=candidate.routing.provider_id)
        expensive = self.candidate("expensive", cost=5)
        self.qualify("expensive")
        pinned = (
            self.candidate("pinned-busy", capacity=0),
            self.candidate("pinned-other", provider="claude"),
        )
        for candidate in pinned:
            self.qualify(candidate.routing.agent_id, provider=candidate.routing.provider_id)
        scenarios = (
            ("missing", self.pool("missing_pool", (missing,)), 10, "missing_capability"),
            ("capacity", self.pool("capacity_pool", (capacity,)), 10, "capacity"),
            ("independence", self.pool(
                "independence_pool", same_model, pool_strategy="strengthened",
                minimum_replicas=2, maximum_replicas=2, arbitration_rule="unanimous",
                require_model_independence=True,
            ), 10, "independence"),
            ("budget", self.pool("budget_pool", (expensive,)), 4, "budget"),
            ("pinned", self.pool(
                "pinned_pool", pinned, routing_strategy="pinned",
                pinned_agent_id="pinned-busy",
            ), 10, "capacity"),
        )
        for key, requirement, budget, expected_gap in scenarios:
            with self.subTest(key=key):
                result = self.composer.compose(
                    composition_key=f"gap-{key}", mission_key=f"mission-{key}",
                    pools=(requirement,), budget=budget,
                )
                self.assertEqual(result.status, "blocked")
                self.assertFalse(result.rationale["can_dispatch"])
                self.assertIn(expected_gap, {gap["kind"] for gap in result.gaps})
                self.assertFalse(result.pools[0]["valid"])
                self.assertEqual(result.pools[0]["primary_assignments"], [])

    def test_diversity_exception_requires_immutable_human_review(self):
        candidates = (
            self.candidate("one", provider="codex", model="same"),
            self.candidate("two", provider="codex", model="same"),
        )
        for candidate in candidates:
            self.qualify(candidate.routing.agent_id, provider=candidate.routing.provider_id)
        requirement = self.pool(
            "reviewed_pool", candidates, pool_strategy="strengthened",
            minimum_replicas=2, maximum_replicas=2, arbitration_rule="human_decision",
            require_provider_diversity=True,
        )
        blocked = self.composer.compose(
            composition_key="mission-review-v1", mission_key="mission-review",
            pools=(requirement,), budget=10,
        )
        self.assertTrue(blocked.gaps[0]["human_review_required"])
        with self.assertRaisesRegex(PermissionError, "human reviewer"):
            self.composer.record_exception_review(
                review_key="review-1", mission_key="mission-review",
                pool_key="reviewed_pool", constraint="provider_diversity",
                decision="approved", reviewer="worker", reviewer_role="agent",
                rationale="No diverse provider is currently qualified",
            )
        review_id = self.composer.record_exception_review(
            review_key="review-1", mission_key="mission-review",
            pool_key="reviewed_pool", constraint="provider_diversity",
            decision="approved", reviewer="Founder", reviewer_role="mission_owner",
            rationale="Accept same-provider strengthened pool for this version",
        )
        ready = self.composer.compose(
            composition_key="mission-review-v2", mission_key="mission-review",
            pools=(requirement,), budget=10,
            approved_exception_review_ids=(review_id,),
        )
        self.assertEqual(ready.status, "ready")
        self.assertEqual(ready.pools[0]["applied_exceptions"][0]["review_id"], review_id)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE workforce_exception_reviews SET rationale='changed' WHERE id=?",
                (review_id,),
            )


if __name__ == "__main__":
    unittest.main()
