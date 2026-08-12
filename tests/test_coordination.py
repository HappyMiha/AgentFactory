import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.coordination import (
    PATTERN_ARBITRATION,
    CoordinationLimitError,
    CoordinationPattern,
    CoordinationService,
    Participant,
)
from agent_factory.storage import SQLiteStorage


class CoordinationPatternTests(unittest.TestCase):
    participants = (
        Participant("producer-a", "model-a", "producer"),
        Participant("producer-b", "model-b", "producer"),
        Participant("review-a", "model-c", "reviewer"),
        Participant("review-b", "model-d", "reviewer"),
    )
    evidence = {"criterion": "AC-1", "provenance": "test-fixture"}

    def fixture(self, root: Path):
        storage = SQLiteStorage(root / "state.db")
        return storage, CoordinationService(storage)

    def pattern(self, pattern_type: str, **limits):
        return CoordinationPattern(
            pattern_key=f"test-{pattern_type}", version=1,
            pattern_type=pattern_type, participants=self.participants,
            reviewer_pool=("review-a", "review-b"),
            independence_constraints=("reviewer_model_differs_from_producer",),
            max_turns=limits.get("max_turns", 8),
            max_tokens=limits.get("max_tokens", 1_000),
            max_cost=limits.get("max_cost", 5.0),
            arbitration=PATTERN_ARBITRATION[pattern_type],
            termination="arbitration_complete_or_limit",
            required_evidence=("criterion", "provenance"),
        )

    def add_pattern_contributions(
        self, service: CoordinationService, run_id: int, pattern_type: str,
    ):
        add = lambda participant, kind, payload, dissent=(): service.contribute(
            run_id, participant_id=participant, contribution_type=kind,
            payload=payload, evidence=self.evidence, dissent=dissent,
            tokens_used=10, cost_used=0.01,
        )
        if pattern_type == "parallel":
            add("producer-a", "proposal", {"candidate": "alpha", "score": 0.8})
            add("producer-b", "proposal", {"candidate": "beta", "score": 0.7}, ("beta is safer",))
        elif pattern_type == "generator_critic":
            add("producer-a", "proposal", {"candidate": "alpha"})
            selection_id, reviewer = service.select_reviewer(
                run_id, producer_id="producer-a"
            )
            service.contribute(
                run_id, participant_id=reviewer, contribution_type="critique",
                payload={"accepted": True}, evidence=self.evidence,
                dissent=("minor unresolved edge",), tokens_used=10, cost_used=0.01,
                reviewer_selection_id=selection_id,
            )
        elif pattern_type == "quorum":
            add("producer-a", "vote", {"choice": "alpha"})
            add("producer-b", "vote", {"choice": "beta"}, ("prefer beta",))
            add("review-a", "vote", {"choice": "alpha"})
            add("review-b", "vote", {"choice": "alpha"})
        elif pattern_type == "debate":
            add("producer-a", "argument", {"position": "alpha"})
            add("producer-b", "argument", {"position": "beta"}, ("alpha risk",))
            selection_id, reviewer = service.select_reviewer(
                run_id, producer_id="producer-a"
            )
            service.contribute(
                run_id, participant_id=reviewer, contribution_type="verdict",
                payload={"winner": "alpha"}, evidence=self.evidence,
                reviewer_selection_id=selection_id, tokens_used=10, cost_used=0.01,
            )
        elif pattern_type == "tournament":
            add("producer-a", "score", {"candidate": "alpha", "score": 9})
            add("producer-b", "score", {"candidate": "beta", "score": 8}, ("beta is cheaper",))
        else:
            add("producer-a", "attack", {"finding": "unsafe input"}, ("critical path",))
            add("producer-b", "defense", {"resolved": True, "patch": "sanitized"})

    def test_all_six_patterns_terminate_deterministically_and_preserve_dissent(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, service = self.fixture(Path(tmp))
            winners = {}
            for pattern_type in PATTERN_ARBITRATION:
                pattern_id = service.register_pattern(
                    self.pattern(pattern_type), created_by="workflow-owner"
                )
                run_id = service.start_run(
                    pattern_id, objective=f"Resolve {pattern_type}"
                )
                self.add_pattern_contributions(service, run_id, pattern_type)
                first = service.arbitrate(run_id)
                replay = service.arbitrate(run_id)
                self.assertEqual(first, replay)
                self.assertTrue(first.dissent, pattern_type)
                self.assertEqual(
                    first.outcome["strategy"], PATTERN_ARBITRATION[pattern_type]
                )
                winners[pattern_type] = first.outcome.get("winner")
                run = storage.db.execute(
                    "SELECT status,termination_reason FROM coordination_runs WHERE id=?",
                    (run_id,),
                ).fetchone()
                self.assertEqual(run["status"], "completed")
                self.assertEqual(run["termination_reason"], "arbitration_complete_or_limit")
            self.assertEqual(winners["parallel"], "alpha")
            self.assertEqual(winners["generator_critic"], "alpha")
            self.assertEqual(winners["quorum"], "alpha")
            self.assertEqual(winners["debate"], "alpha")
            self.assertEqual(winners["tournament"], "alpha")
            self.assertEqual(winners["red_blue"], "blue")
            storage.close()

    def test_pattern_manifest_declares_every_required_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, service = self.fixture(Path(tmp))
            pattern_id = service.register_pattern(
                self.pattern("debate"), created_by="workflow-owner"
            )
            manifest = json.loads(storage.db.execute(
                "SELECT manifest_json FROM coordination_patterns WHERE id=?", (pattern_id,)
            ).fetchone()[0])
            self.assertEqual(len(manifest["participants"]), 4)
            self.assertEqual(
                manifest["reviewer_rotation"]["strategy"],
                "least_used_excluding_producer_model",
            )
            self.assertIn(
                "reviewer_model_differs_from_producer",
                manifest["independence_constraints"],
            )
            self.assertEqual(manifest["limits"]["max_turns"], 8)
            self.assertEqual(manifest["arbitration"], "independent_judge")
            self.assertTrue(manifest["termination"])
            self.assertEqual(
                manifest["required_evidence"], ["criterion", "provenance"]
            )
            with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                storage.db.execute(
                    "UPDATE coordination_patterns SET created_by='other' WHERE id=?",
                    (pattern_id,),
                )
            storage.close()

    def test_model_aware_rotation_excludes_producer_and_rotates_least_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, service = self.fixture(Path(tmp))
            pattern_id = service.register_pattern(
                self.pattern("generator_critic"), created_by="workflow-owner"
            )
            run_id = service.start_run(pattern_id, objective="Review candidate")
            first_id, first = service.select_reviewer(run_id, producer_id="producer-a")
            second_id, second = service.select_reviewer(run_id, producer_id="producer-a")
            self.assertNotEqual(first, second)
            self.assertEqual({first, second}, {"review-a", "review-b"})
            rows = storage.db.execute(
                "SELECT * FROM coordination_reviewer_selections ORDER BY id"
            ).fetchall()
            self.assertEqual([row["id"] for row in rows], [first_id, second_id])
            self.assertTrue(all(row["producer_model"] != row["reviewer_model"] for row in rows))
            storage.close()

    def test_contributions_are_typed_evidenced_audited_and_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, service = self.fixture(Path(tmp))
            pattern_id = service.register_pattern(
                self.pattern("parallel"), created_by="workflow-owner"
            )
            run_id = service.start_run(pattern_id, objective="Compare candidates")
            with self.assertRaisesRegex(PermissionError, "required evidence"):
                service.contribute(
                    run_id, participant_id="producer-a", contribution_type="proposal",
                    payload={"candidate": "alpha", "score": 1}, evidence={},
                )
            contribution_id = service.contribute(
                run_id, participant_id="producer-a", contribution_type="proposal",
                payload={"candidate": "alpha", "score": 1}, evidence=self.evidence,
                dissent=("document this concern",),
            )
            row = storage.db.execute(
                "SELECT * FROM coordination_contributions WHERE id=?", (contribution_id,)
            ).fetchone()
            self.assertEqual(row["contribution_type"], "proposal")
            self.assertEqual(json.loads(row["evidence_json"]), self.evidence)
            self.assertEqual(json.loads(row["dissent_json"]), ["document this concern"])
            self.assertEqual(
                storage.db.execute(
                    "SELECT COUNT(*) FROM events WHERE event_type='coordination.contribution.recorded'"
                ).fetchone()[0],
                1,
            )
            with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                storage.db.execute(
                    "UPDATE coordination_contributions SET payload_json='{}' WHERE id=?",
                    (contribution_id,),
                )
            storage.close()

    def test_turn_token_and_cost_limits_terminate_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, service = self.fixture(Path(tmp))
            limits = (
                ("turn_limit", {"max_turns": 1}, [0, 0]),
                ("token_budget", {"max_tokens": 5}, [6]),
                ("cost_budget", {"max_cost": 0.01}, [0.02]),
            )
            for index, (reason, overrides, usage) in enumerate(limits):
                pattern = self.pattern("parallel", **overrides)
                pattern = CoordinationPattern(
                    **{**pattern.__dict__, "pattern_key": f"limit-{index}"}
                )
                pattern_id = service.register_pattern(pattern, created_by="workflow-owner")
                run_id = service.start_run(pattern_id, objective=f"Exercise {reason}")
                if reason == "turn_limit":
                    service.contribute(
                        run_id, participant_id="producer-a", contribution_type="proposal",
                        payload={"candidate": "alpha", "score": 1}, evidence=self.evidence,
                    )
                    call = {"tokens_used": 0, "cost_used": 0}
                elif reason == "token_budget":
                    call = {"tokens_used": usage[0], "cost_used": 0}
                else:
                    call = {"tokens_used": 0, "cost_used": usage[0]}
                with self.assertRaisesRegex(CoordinationLimitError, reason):
                    service.contribute(
                        run_id, participant_id="producer-b", contribution_type="proposal",
                        payload={"candidate": "beta", "score": 1}, evidence=self.evidence,
                        **call,
                    )
                run = storage.db.execute(
                    "SELECT status,termination_reason FROM coordination_runs WHERE id=?",
                    (run_id,),
                ).fetchone()
                self.assertEqual((run["status"], run["termination_reason"]), ("terminated", reason))
            storage.close()


if __name__ == "__main__":
    unittest.main()
