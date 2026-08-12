"""Audited, bounded multi-agent coordination patterns."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .storage import SQLiteStorage


PATTERN_ARBITRATION = {
    "parallel": "ranked_choice",
    "generator_critic": "critic_acceptance",
    "quorum": "majority",
    "debate": "independent_judge",
    "tournament": "deterministic_bracket",
    "red_blue": "blue_resolution",
}
CONTRIBUTION_TYPES = {
    "proposal", "critique", "vote", "argument", "verdict", "attack", "defense", "score",
}
REVIEW_TYPES = {"critique", "verdict"}


class CoordinationLimitError(RuntimeError):
    """Raised after a coordination run deterministically terminates at a limit."""


@dataclass(frozen=True)
class Participant:
    agent_id: str
    model: str
    role: str


@dataclass(frozen=True)
class CoordinationPattern:
    pattern_key: str
    version: int
    pattern_type: str
    participants: tuple[Participant, ...]
    reviewer_pool: tuple[str, ...]
    independence_constraints: tuple[str, ...]
    max_turns: int
    max_tokens: int
    max_cost: float
    arbitration: str
    termination: str
    required_evidence: tuple[str, ...]


@dataclass(frozen=True)
class ArbitrationResult:
    arbitration_id: int
    run_id: int
    outcome: dict[str, Any]
    dissent: tuple[dict[str, Any], ...]


class CoordinationService:
    """Persist every contribution and resolve supported patterns deterministically."""

    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_pattern(pattern: CoordinationPattern) -> None:
        if not pattern.pattern_key.strip() or pattern.version <= 0:
            raise ValueError("Pattern key and positive version are required")
        expected_arbitration = PATTERN_ARBITRATION.get(pattern.pattern_type)
        if expected_arbitration is None:
            raise ValueError(f"Unknown coordination pattern: {pattern.pattern_type}")
        if pattern.arbitration != expected_arbitration:
            raise ValueError(
                f"{pattern.pattern_type} requires {expected_arbitration} arbitration"
            )
        if len(pattern.participants) < 2:
            raise ValueError("Coordination requires at least two participants")
        by_id = {participant.agent_id: participant for participant in pattern.participants}
        if len(by_id) != len(pattern.participants) or any(
            not participant.agent_id.strip()
            or not participant.model.strip()
            or not participant.role.strip()
            for participant in pattern.participants
        ):
            raise ValueError("Participants require unique IDs, models, and roles")
        reviewers = set(pattern.reviewer_pool)
        if not reviewers or not reviewers <= set(by_id):
            raise ValueError("Reviewer pool must name known participants")
        if any(
            not any(
                reviewer_id != participant.agent_id
                and by_id[reviewer_id].model != participant.model
                for reviewer_id in reviewers
            )
            for participant in pattern.participants
        ):
            raise PermissionError(
                "Reviewer pool must provide a model-independent reviewer for every participant"
            )
        if "reviewer_model_differs_from_producer" not in pattern.independence_constraints:
            raise PermissionError("Model-aware reviewer independence must be declared")
        if (
            pattern.max_turns <= 0 or pattern.max_tokens <= 0 or pattern.max_cost <= 0
            or not pattern.termination.strip() or not pattern.required_evidence
            or any(not value.strip() for value in pattern.required_evidence)
        ):
            raise ValueError(
                "Positive turn/token/cost limits, termination, and evidence are required"
            )

    def register_pattern(self, pattern: CoordinationPattern, *, created_by: str) -> int:
        self._validate_pattern(pattern)
        if not created_by.strip():
            raise ValueError("Pattern creator is required")
        manifest = {
            "schema_version": 1,
            "pattern_key": pattern.pattern_key,
            "version": pattern.version,
            "pattern_type": pattern.pattern_type,
            "participants": [
                {
                    "agent_id": participant.agent_id,
                    "model": participant.model,
                    "role": participant.role,
                }
                for participant in sorted(pattern.participants, key=lambda item: item.agent_id)
            ],
            "reviewer_rotation": {
                "pool": sorted(set(pattern.reviewer_pool)),
                "strategy": "least_used_excluding_producer_model",
            },
            "independence_constraints": sorted(set(pattern.independence_constraints)),
            "limits": {
                "max_turns": pattern.max_turns,
                "max_tokens": pattern.max_tokens,
                "max_cost": pattern.max_cost,
            },
            "arbitration": pattern.arbitration,
            "termination": pattern.termination,
            "required_evidence": sorted(set(pattern.required_evidence)),
        }
        manifest_json = self._json(manifest)
        digest = self._digest(manifest_json)
        existing = self.storage.db.execute(
            "SELECT id,manifest_digest FROM coordination_patterns WHERE pattern_key=? AND version=?",
            (pattern.pattern_key, pattern.version),
        ).fetchone()
        if existing:
            if str(existing["manifest_digest"]) != digest:
                raise ValueError("Coordination pattern version already has another manifest")
            return int(existing["id"])
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO coordination_patterns(
                       identity,pattern_key,version,pattern_type,manifest_json,
                       manifest_digest,created_by
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("coordination-pattern"), pattern.pattern_key,
                    pattern.version, pattern.pattern_type, manifest_json, digest, created_by,
                ),
            )
        return int(cursor.lastrowid)

    def start_run(self, pattern_id: int, *, objective: str) -> int:
        if not objective.strip():
            raise ValueError("Coordination objective is required")
        if not self.storage.db.execute(
            "SELECT 1 FROM coordination_patterns WHERE id=?", (pattern_id,)
        ).fetchone():
            raise KeyError(f"Unknown coordination pattern: {pattern_id}")
        with self.storage.db:
            cursor = self.storage.db.execute(
                "INSERT INTO coordination_runs(identity,pattern_id,objective) VALUES(?,?,?)",
                (self.storage._identity("coordination-run"), pattern_id, objective.strip()),
            )
            run_id = int(cursor.lastrowid)
            self.storage._event("coordination.started", "coordination_run", run_id, {
                "pattern_id": pattern_id, "objective": objective.strip(),
            })
        return run_id

    def _scope(self, run_id: int) -> tuple[Any, dict[str, Any]]:
        run = self.storage.db.execute(
            """SELECT r.*,p.manifest_json FROM coordination_runs r
                 JOIN coordination_patterns p ON p.id=r.pattern_id WHERE r.id=?""",
            (run_id,),
        ).fetchone()
        if not run:
            raise KeyError(f"Unknown coordination run: {run_id}")
        return run, json.loads(run["manifest_json"])

    def select_reviewer(self, run_id: int, *, producer_id: str) -> tuple[int, str]:
        run, manifest = self._scope(run_id)
        if run["status"] != "running":
            raise ValueError("Reviewer selection requires a running coordination run")
        participants = {
            item["agent_id"]: item for item in manifest["participants"]
        }
        producer = participants.get(producer_id)
        if not producer:
            raise KeyError(f"Unknown coordination participant: {producer_id}")
        eligible: list[dict[str, Any]] = []
        excluded: list[dict[str, str]] = []
        for reviewer_id in manifest["reviewer_rotation"]["pool"]:
            reviewer = participants[reviewer_id]
            reasons = []
            if reviewer_id == producer_id:
                reasons.append("same_agent")
            if reviewer["model"] == producer["model"]:
                reasons.append("same_model")
            if reasons:
                excluded.append({"agent_id": reviewer_id, "reason": ",".join(reasons)})
                continue
            usage = self.storage.db.execute(
                """SELECT COUNT(*) AS uses,COALESCE(MAX(s.id),0) AS last_id
                     FROM coordination_reviewer_selections s
                     JOIN coordination_runs r ON r.id=s.run_id
                    WHERE r.pattern_id=? AND s.reviewer_id=?""",
                (run["pattern_id"], reviewer_id),
            ).fetchone()
            eligible.append({
                "agent_id": reviewer_id, "model": reviewer["model"],
                "uses": int(usage["uses"]), "last_id": int(usage["last_id"]),
            })
        if not eligible:
            raise PermissionError("No model-independent reviewer is eligible")
        selected = min(
            eligible, key=lambda item: (item["uses"], item["last_id"], item["agent_id"])
        )
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO coordination_reviewer_selections(
                       identity,run_id,producer_id,producer_model,reviewer_id,
                       reviewer_model,eligible_json,excluded_json,strategy
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("coordination-reviewer"), run_id,
                    producer_id, producer["model"], selected["agent_id"],
                    selected["model"], self._json(eligible), self._json(excluded),
                    manifest["reviewer_rotation"]["strategy"],
                ),
            )
            selection_id = int(cursor.lastrowid)
            self.storage._event("coordination.reviewer.selected", "coordination_run", run_id, {
                "selection_id": selection_id, "producer_id": producer_id,
                "reviewer_id": selected["agent_id"], "reviewer_model": selected["model"],
            })
        return selection_id, str(selected["agent_id"])

    def contribute(
        self, run_id: int, *, participant_id: str, contribution_type: str,
        payload: dict[str, Any], evidence: dict[str, Any],
        dissent: tuple[str, ...] = (), tokens_used: int = 0, cost_used: float = 0,
        reviewer_selection_id: int | None = None,
    ) -> int:
        run, manifest = self._scope(run_id)
        if run["status"] != "running":
            raise ValueError("Contributions require a running coordination run")
        participants = {item["agent_id"]: item for item in manifest["participants"]}
        participant = participants.get(participant_id)
        if not participant:
            raise KeyError(f"Unknown coordination participant: {participant_id}")
        if contribution_type not in CONTRIBUTION_TYPES or not payload:
            raise ValueError("Typed contribution and non-empty payload are required")
        missing_evidence = set(manifest["required_evidence"]) - set(evidence)
        if missing_evidence:
            raise PermissionError(
                f"Contribution lacks required evidence: {sorted(missing_evidence)}"
            )
        if any(not value.strip() for value in dissent):
            raise ValueError("Dissent entries cannot be empty")
        if (
            isinstance(tokens_used, bool) or tokens_used < 0
            or isinstance(cost_used, bool) or cost_used < 0
        ):
            raise ValueError("Contribution usage cannot be negative")
        if contribution_type in REVIEW_TYPES:
            selection = self.storage.db.execute(
                "SELECT * FROM coordination_reviewer_selections WHERE id=? AND run_id=?",
                (reviewer_selection_id, run_id),
            ).fetchone()
            if not selection or selection["reviewer_id"] != participant_id:
                raise PermissionError("Review contribution requires its model-aware selection")
            if selection["reviewer_model"] == selection["producer_model"]:
                raise PermissionError("Reviewer model cannot match producer model")
        limits = manifest["limits"]
        next_turn = int(run["turn_count"]) + 1
        next_tokens = int(run["tokens_used"]) + tokens_used
        next_cost = float(run["cost_used"]) + cost_used
        breached = None
        if next_turn > int(limits["max_turns"]):
            breached = "turn_limit"
        elif next_tokens > int(limits["max_tokens"]):
            breached = "token_budget"
        elif next_cost > float(limits["max_cost"]):
            breached = "cost_budget"
        if breached:
            self._terminate(run_id, breached)
            raise CoordinationLimitError(f"Coordination terminated at {breached}")
        document = {
            "run_id": run_id, "sequence": next_turn,
            "participant_id": participant_id, "participant_model": participant["model"],
            "participant_role": participant["role"],
            "contribution_type": contribution_type, "payload": payload,
            "evidence": evidence, "dissent": list(dissent),
            "reviewer_selection_id": reviewer_selection_id,
            "tokens_used": tokens_used, "cost_used": cost_used,
        }
        digest = self._digest(self._json(document))
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO coordination_contributions(
                       identity,run_id,sequence,participant_id,participant_model,
                       participant_role,contribution_type,payload_json,evidence_json,
                       dissent_json,reviewer_selection_id,tokens_used,cost_used,
                       contribution_digest
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("coordination-contribution"), run_id,
                    next_turn, participant_id, participant["model"], participant["role"],
                    contribution_type, self._json(payload), self._json(evidence),
                    self._json(dissent), reviewer_selection_id, tokens_used, cost_used, digest,
                ),
            )
            contribution_id = int(cursor.lastrowid)
            updated = self.storage.db.execute(
                """UPDATE coordination_runs
                      SET turn_count=?,tokens_used=?,cost_used=?
                    WHERE id=? AND status='running'""",
                (next_turn, next_tokens, next_cost, run_id),
            )
            if updated.rowcount != 1:
                raise ValueError("Coordination run changed concurrently")
            self.storage._event("coordination.contribution.recorded", "coordination_run", run_id, {
                "contribution_id": contribution_id, "sequence": next_turn,
                "participant_id": participant_id, "type": contribution_type,
            })
        return contribution_id

    def _terminate(self, run_id: int, reason: str) -> None:
        with self.storage.db:
            updated = self.storage.db.execute(
                """UPDATE coordination_runs
                      SET status='terminated',termination_reason=?,completed_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='running'""",
                (reason, run_id),
            )
            if updated.rowcount == 1:
                self.storage._event("coordination.terminated", "coordination_run", run_id, {
                    "reason": reason,
                })

    @staticmethod
    def _choice_score(rows: list[dict[str, Any]], *, score_key: str) -> dict[str, Any]:
        totals: dict[str, float] = {}
        for value in rows:
            candidate = value.get("candidate")
            score = value.get(score_key)
            if not isinstance(candidate, str) or not candidate.strip() \
                    or isinstance(score, bool) or not isinstance(score, (int, float)):
                raise ValueError("Arbitration contributions require candidate and numeric score")
            totals[candidate] = totals.get(candidate, 0.0) + float(score)
        winner = min(totals, key=lambda candidate: (-totals[candidate], candidate))
        return {"winner": winner, "scores": dict(sorted(totals.items()))}

    def _outcome(
        self, pattern_type: str, contributions: list[Any], participant_count: int,
    ) -> dict[str, Any]:
        typed: dict[str, list[Any]] = {}
        for row in contributions:
            typed.setdefault(str(row["contribution_type"]), []).append(row)
        if pattern_type == "parallel":
            proposals = [json.loads(row["payload_json"]) for row in typed.get("proposal", [])]
            if len({row["participant_id"] for row in typed.get("proposal", [])}) < 2:
                raise ValueError("Parallel arbitration requires two participant proposals")
            return {"strategy": "ranked_choice", **self._choice_score(proposals, score_key="score")}
        if pattern_type == "generator_critic":
            proposals = typed.get("proposal", [])
            critiques = typed.get("critique", [])
            if not proposals or not critiques:
                raise ValueError("Generator-critic arbitration requires proposal and critique")
            proposal = json.loads(proposals[-1]["payload_json"])
            critique = json.loads(critiques[-1]["payload_json"])
            if not isinstance(critique.get("accepted"), bool):
                raise ValueError("Critique must provide a boolean accepted verdict")
            return {
                "strategy": "critic_acceptance",
                "accepted": critique["accepted"],
                "winner": proposal.get("candidate") if critique["accepted"] else None,
            }
        if pattern_type == "quorum":
            latest: dict[str, str] = {}
            for row in typed.get("vote", []):
                choice = json.loads(row["payload_json"]).get("choice")
                if not isinstance(choice, str) or not choice.strip():
                    raise ValueError("Quorum votes require a choice")
                latest[str(row["participant_id"])] = choice
            if len(latest) < 3:
                raise ValueError("Quorum arbitration requires three distinct votes")
            counts: dict[str, int] = {}
            for choice in latest.values():
                counts[choice] = counts.get(choice, 0) + 1
            selected = min(counts, key=lambda choice: (-counts[choice], choice))
            threshold = participant_count // 2 + 1
            return {
                "strategy": "majority", "threshold": threshold,
                "counts": dict(sorted(counts.items())),
                "winner": selected if counts[selected] >= threshold else None,
            }
        if pattern_type == "debate":
            arguments = typed.get("argument", [])
            verdicts = typed.get("verdict", [])
            if len({row["participant_id"] for row in arguments}) < 2 or not verdicts:
                raise ValueError("Debate requires two debaters and an independent verdict")
            verdict = json.loads(verdicts[-1]["payload_json"])
            if not isinstance(verdict.get("winner"), str):
                raise ValueError("Debate verdict requires a winner")
            return {"strategy": "independent_judge", "winner": verdict["winner"]}
        if pattern_type == "tournament":
            scores = [json.loads(row["payload_json"]) for row in typed.get("score", [])]
            if len({value.get("candidate") for value in scores}) < 2:
                raise ValueError("Tournament requires scores for at least two candidates")
            return {
                "strategy": "deterministic_bracket",
                **self._choice_score(scores, score_key="score"),
            }
        attacks = typed.get("attack", [])
        defenses = typed.get("defense", [])
        if not attacks or not defenses:
            raise ValueError("Red/blue arbitration requires attack and defense evidence")
        defense = json.loads(defenses[-1]["payload_json"])
        if not isinstance(defense.get("resolved"), bool):
            raise ValueError("Blue defense requires a boolean resolved verdict")
        return {
            "strategy": "blue_resolution", "resolved": defense["resolved"],
            "winner": "blue" if defense["resolved"] else "red",
        }

    def arbitrate(self, run_id: int) -> ArbitrationResult:
        run, manifest = self._scope(run_id)
        existing = self.storage.db.execute(
            "SELECT * FROM coordination_arbitrations WHERE run_id=?", (run_id,)
        ).fetchone()
        if existing:
            return ArbitrationResult(
                int(existing["id"]), run_id, json.loads(existing["outcome_json"]),
                tuple(json.loads(existing["dissent_json"])),
            )
        if run["status"] != "running":
            raise ValueError("Terminated coordination cannot be arbitrated")
        contributions = self.storage.db.execute(
            "SELECT * FROM coordination_contributions WHERE run_id=? ORDER BY sequence",
            (run_id,),
        ).fetchall()
        outcome = self._outcome(
            manifest["pattern_type"], list(contributions), len(manifest["participants"])
        )
        dissent = tuple(
            {
                "contribution_id": int(row["id"]),
                "participant_id": str(row["participant_id"]),
                "statements": json.loads(row["dissent_json"]),
            }
            for row in contributions if json.loads(row["dissent_json"])
        )
        document = {
            "run_id": run_id, "strategy": manifest["arbitration"],
            "contribution_ids": [int(row["id"]) for row in contributions],
            "outcome": outcome, "dissent": dissent,
        }
        digest = self._digest(self._json(document))
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO coordination_arbitrations(
                       identity,run_id,strategy,contribution_ids_json,outcome_json,
                       dissent_json,arbitration_digest
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("coordination-arbitration"), run_id,
                    manifest["arbitration"], self._json(document["contribution_ids"]),
                    self._json(outcome), self._json(dissent), digest,
                ),
            )
            arbitration_id = int(cursor.lastrowid)
            updated = self.storage.db.execute(
                """UPDATE coordination_runs
                      SET status='completed',termination_reason=?,outcome_json=?,
                          completed_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='running'""",
                (manifest["termination"], self._json(outcome), run_id),
            )
            if updated.rowcount != 1:
                raise ValueError("Coordination run changed concurrently")
            self.storage._event("coordination.completed", "coordination_run", run_id, {
                "arbitration_id": arbitration_id, "strategy": manifest["arbitration"],
                "dissent_count": len(dissent), "termination": manifest["termination"],
            })
        return ArbitrationResult(arbitration_id, run_id, outcome, dissent)
