"""Evaluation-aware deterministic routing with durable rationale."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from .roles import RoleRegistry
from .storage import SQLiteStorage


ROUTING_STRATEGIES = (
    "pinned", "best-qualified", "cost-aware", "latency-aware",
    "diversity", "canary", "tournament", "fallback",
)


@dataclass(frozen=True)
class RoutingCandidate:
    agent_id: str
    provider_id: str
    model_identity: str
    quality: float
    risk: float
    cost: float
    latency_ms: float
    load: float
    healthy: bool = True
    enabled: bool = True
    canary: bool = False

    def __post_init__(self):
        if not self.agent_id.strip() or not self.provider_id.strip() or not self.model_identity.strip():
            raise ValueError("Routing candidate identities are required")
        if not 0 <= self.quality <= 1 or not 0 <= self.risk <= 1:
            raise ValueError("Candidate quality and risk must be between zero and one")
        if min(self.cost, self.latency_ms, self.load) < 0:
            raise ValueError("Candidate cost, latency, and load cannot be negative")


@dataclass(frozen=True)
class RoutingDecision:
    id: int
    selected_agent_id: str
    fallback_chain: tuple[str, ...]
    eligible: tuple[dict[str, Any], ...]
    excluded: tuple[dict[str, Any], ...]
    rationale: str
    decision_digest: str


class AgentRouter:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    @staticmethod
    def _best_key(item: dict[str, Any]):
        return (
            -item["quality"], item["risk"], item["cost"],
            item["latency_ms"], item["load"], item["agent_id"],
        )

    def _qualification(self, agent_id: str, qualification_role: str):
        return self.storage.db.execute(
            """SELECT q.*,COALESCE(l.state,'offline') AS lifecycle_state,
                      q.valid_until>CURRENT_TIMESTAMP AS current
                 FROM worker_qualifications q
                 LEFT JOIN worker_lifecycle l ON l.worker_id=q.worker_id
                WHERE q.worker_id=? AND q.role=?
                  AND q.id=(SELECT MAX(latest.id) FROM worker_qualifications latest
                             WHERE latest.worker_id=q.worker_id)
                ORDER BY q.id DESC LIMIT 1""",
            (agent_id, qualification_role),
        ).fetchone()

    def route(
        self,
        *,
        decision_key: str,
        role_id: str,
        role_version: str,
        qualification_role: str,
        required_capabilities: set[str],
        candidates: tuple[RoutingCandidate, ...],
        strategy: str,
        producer_model: str | None = None,
        producer_provider: str | None = None,
        pinned_agent_id: str | None = None,
        require_independence: bool = False,
    ) -> RoutingDecision:
        if strategy not in ROUTING_STRATEGIES:
            raise ValueError(f"Unknown routing strategy: {strategy}")
        if not decision_key.strip() or not candidates:
            raise ValueError("Routing decision key and candidates are required")
        RoleRegistry(self.storage).resolve(role_id, role_version)
        request = {
            "decision_key": decision_key, "role_id": role_id, "role_version": role_version,
            "qualification_role": qualification_role,
            "required_capabilities": sorted(required_capabilities), "strategy": strategy,
            "producer_model": producer_model, "producer_provider": producer_provider,
            "pinned_agent_id": pinned_agent_id, "require_independence": require_independence,
            "candidates": [asdict(candidate) for candidate in candidates],
        }
        existing = self.storage.db.execute(
            "SELECT * FROM agent_routing_decisions WHERE decision_key=?", (decision_key,)
        ).fetchone()
        if existing:
            if json.loads(existing["request_json"]) != request:
                raise ValueError("Routing decision key is already bound to another request")
            return self._result(existing)
        eligible: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in sorted(candidates, key=lambda item: item.agent_id):
            if candidate.agent_id in seen:
                raise ValueError("Routing candidate agent IDs must be unique")
            seen.add(candidate.agent_id)
            qualification = self._qualification(candidate.agent_id, qualification_role)
            capabilities = set(json.loads(qualification["capabilities_json"])) if qualification else set()
            reasons = []
            if not candidate.enabled:
                reasons.append("disabled")
            if not candidate.healthy:
                reasons.append("unhealthy")
            if not qualification:
                reasons.append("missing_qualification")
            elif qualification["status"] != "qualified":
                reasons.append(f"qualification_{qualification['status']}")
            elif not qualification["current"]:
                reasons.append("qualification_expired")
            elif qualification["lifecycle_state"] != "active":
                reasons.append(f"worker_{qualification['lifecycle_state']}")
            elif qualification["provider_id"] != candidate.provider_id:
                reasons.append("qualification_provider_mismatch")
            if not required_capabilities <= capabilities:
                reasons.append("capability_mismatch")
            independent = not producer_model or candidate.model_identity != producer_model
            if require_independence and not independent:
                reasons.append("producer_model_conflict")
            snapshot = {
                **asdict(candidate), "capabilities": sorted(capabilities),
                "qualification_id": int(qualification["id"]) if qualification else None,
                "qualification_status": str(qualification["status"]) if qualification else "missing",
                "qualification_current": bool(qualification["current"]) if qualification else False,
                "model_independent": independent,
            }
            if reasons:
                excluded.append({**snapshot, "reasons": reasons})
            else:
                eligible.append(snapshot)
        if not eligible:
            raise RuntimeError("No eligible qualified routing candidate")

        best = sorted(eligible, key=self._best_key)
        if strategy == "pinned":
            if not pinned_agent_id or pinned_agent_id not in {item["agent_id"] for item in eligible}:
                raise PermissionError("Pinned agent is not eligible")
            ordered = sorted(eligible, key=lambda item: (item["agent_id"] != pinned_agent_id, self._best_key(item)))
        elif strategy == "cost-aware":
            ordered = sorted(eligible, key=lambda item: (item["cost"], -item["quality"], item["agent_id"]))
        elif strategy == "latency-aware":
            ordered = sorted(eligible, key=lambda item: (item["latency_ms"], -item["quality"], item["agent_id"]))
        elif strategy == "diversity":
            ordered = sorted(eligible, key=lambda item: (
                item["provider_id"] == producer_provider,
                item["model_identity"] == producer_model,
                self._best_key(item),
            ))
        elif strategy == "canary":
            ordered = sorted(eligible, key=lambda item: (not item["canary"], self._best_key(item)))
        elif strategy == "tournament":
            winner = sorted(eligible, key=lambda item: item["agent_id"])[0]
            for challenger in sorted(eligible, key=lambda item: item["agent_id"])[1:]:
                winner = min((winner, challenger), key=self._best_key)
            ordered = [winner, *(item for item in best if item["agent_id"] != winner["agent_id"])]
        else:
            ordered = best
        chain = tuple(item["agent_id"] for item in ordered)
        rationale = (
            f"{strategy} selected {chain[0]} from {len(eligible)} eligible; "
            f"excluded {len(excluded)}; fallback={' -> '.join(chain[1:]) or 'none'}"
        )
        document = {
            "request": request, "eligible": eligible, "excluded": excluded,
            "selected_agent_id": chain[0], "fallback_chain": chain, "rationale": rationale,
        }
        payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO agent_routing_decisions(
                       identity,decision_key,role_id,role_version,strategy,request_json,
                       eligible_json,excluded_json,selected_agent_id,fallback_chain_json,
                       rationale,decision_digest
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("agent-routing"), decision_key, role_id,
                    role_version, strategy, json.dumps(request, sort_keys=True),
                    json.dumps(eligible, sort_keys=True), json.dumps(excluded, sort_keys=True),
                    chain[0], json.dumps(chain), rationale, digest,
                ),
            )
            decision_id = int(cursor.lastrowid)
            self.storage._event("agent.routing.selected", "agent_routing_decision", decision_id, {
                "decision_key": decision_key, "selected_agent_id": chain[0],
                "fallback_chain": chain, "strategy": strategy, "decision_digest": digest,
            })
        return RoutingDecision(decision_id, chain[0], chain, tuple(eligible), tuple(excluded), rationale, digest)

    @staticmethod
    def _result(row: Any) -> RoutingDecision:
        return RoutingDecision(
            int(row["id"]), str(row["selected_agent_id"]),
            tuple(json.loads(row["fallback_chain_json"])),
            tuple(json.loads(row["eligible_json"])), tuple(json.loads(row["excluded_json"])),
            str(row["rationale"]), str(row["decision_digest"]),
        )
