"""Qualified role pools and deterministic workforce composition."""

from __future__ import annotations

import hashlib
import itertools
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from .agent_router import AgentRouter, ROUTING_STRATEGIES, RoutingCandidate
from .roles import RoleDefinition, RoleRegistry
from .storage import SQLiteStorage


POOL_STRATEGIES = ("singleton", "fixed", "elastic", "strengthened")
ARBITRATION_RULES = ("single", "majority", "unanimous", "ranked_choice", "human_decision")
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True)
class WorkforceCandidate:
    routing: RoutingCandidate
    capacity: int = 1

    def __post_init__(self):
        if self.capacity < 0:
            raise ValueError("Candidate capacity cannot be negative")


@dataclass(frozen=True)
class RolePoolRequirement:
    key: str
    role_id: str
    role_version: str
    qualification_role: str
    required_capabilities: tuple[str, ...]
    pool_strategy: str
    routing_strategy: str
    minimum_replicas: int
    maximum_replicas: int
    arbitration_rule: str
    candidates: tuple[WorkforceCandidate, ...]
    require_model_independence: bool = False
    require_provider_diversity: bool = False
    pinned_agent_id: str | None = None

    def __post_init__(self):
        if not IDENTIFIER.fullmatch(self.key):
            raise ValueError("Role pool key is invalid")
        if not self.qualification_role.strip():
            raise ValueError("Role pool qualification role is required")
        if self.pool_strategy not in POOL_STRATEGIES:
            raise ValueError(f"Unknown pool strategy: {self.pool_strategy}")
        if self.routing_strategy not in ROUTING_STRATEGIES:
            raise ValueError(f"Unknown routing strategy: {self.routing_strategy}")
        if self.arbitration_rule not in ARBITRATION_RULES:
            raise ValueError(f"Unknown arbitration rule: {self.arbitration_rule}")
        if not 0 < self.minimum_replicas <= self.maximum_replicas <= 8:
            raise ValueError("Role pool replicas must satisfy 0 < minimum <= maximum <= 8")
        if self.pool_strategy == "singleton" and (
            self.minimum_replicas != 1 or self.maximum_replicas != 1
        ):
            raise ValueError("Singleton pools require exactly one replica")
        if self.pool_strategy == "strengthened" and (
            self.minimum_replicas < 2 or self.arbitration_rule == "single"
        ):
            raise ValueError("Strengthened pools require two replicas and explicit arbitration")
        if self.minimum_replicas > 1 and self.arbitration_rule == "single":
            raise ValueError("Multi-agent pools require explicit arbitration")
        if tuple(sorted(set(self.required_capabilities))) != self.required_capabilities:
            raise ValueError("Required capabilities must be unique and sorted")
        if len(self.candidates) > 16:
            raise ValueError("Role pools are bounded to sixteen candidates")
        agent_ids = [candidate.routing.agent_id for candidate in self.candidates]
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("Role pool candidates must have unique agent IDs")
        if self.routing_strategy == "pinned" and not self.pinned_agent_id:
            raise ValueError("Pinned role pools require a pinned agent")


@dataclass(frozen=True)
class WorkforceComposition:
    id: int
    composition_key: str
    mission_key: str
    status: str
    budget: float
    rationale: dict[str, Any]
    gaps: tuple[dict[str, Any], ...]
    pools: tuple[dict[str, Any], ...]
    composition_digest: str


class WorkforceComposer:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage
        self.roles = RoleRegistry(storage)
        self.router = AgentRouter(storage)

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def record_exception_review(
        self,
        *,
        review_key: str,
        mission_key: str,
        pool_key: str,
        constraint: str,
        decision: str,
        reviewer: str,
        reviewer_role: str,
        rationale: str,
    ) -> int:
        if constraint not in {"model_independence", "provider_diversity"}:
            raise ValueError("Only independence or provider-diversity exceptions are reviewable")
        if decision not in {"approved", "rejected"}:
            raise ValueError("Exception review decision must be approved or rejected")
        if reviewer_role not in {"mission_owner", "human_reviewer"}:
            raise PermissionError("Workforce exceptions require a human reviewer")
        if not all(value.strip() for value in (
            review_key, mission_key, pool_key, reviewer, rationale
        )):
            raise ValueError("Exception review identity and rationale are required")
        document = {
            "review_key": review_key, "mission_key": mission_key, "pool_key": pool_key,
            "constraint": constraint, "decision": decision, "reviewer": reviewer,
            "reviewer_role": reviewer_role, "rationale": rationale.strip(),
        }
        digest = hashlib.sha256(self._json(document).encode()).hexdigest()
        existing = self.storage.db.execute(
            "SELECT id,review_digest FROM workforce_exception_reviews WHERE review_key=?",
            (review_key,),
        ).fetchone()
        if existing:
            if existing["review_digest"] != digest:
                raise ValueError("Exception review key is already bound to another decision")
            return int(existing["id"])
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO workforce_exception_reviews(
                       identity,review_key,mission_key,pool_key,constraint_key,decision,
                       reviewer,reviewer_role,rationale,review_digest
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("workforce-exception"), review_key, mission_key,
                    pool_key, constraint, decision, reviewer, reviewer_role,
                    rationale.strip(), digest,
                ),
            )
            review_id = int(cursor.lastrowid)
            self.storage._event("workforce.exception.reviewed", "workforce_exception_review", review_id, {
                "mission_key": mission_key, "pool_key": pool_key, "constraint": constraint,
                "decision": decision, "reviewer": reviewer, "review_digest": digest,
            })
        return review_id

    def _exception_map(
        self, mission_key: str, review_ids: tuple[int, ...]
    ) -> dict[tuple[str, str], dict[str, Any]]:
        reviews: dict[tuple[str, str], dict[str, Any]] = {}
        if len(review_ids) != len(set(review_ids)):
            raise ValueError("Exception review IDs must be unique")
        for review_id in review_ids:
            row = self.storage.db.execute(
                "SELECT * FROM workforce_exception_reviews WHERE id=?", (review_id,)
            ).fetchone()
            if not row or row["mission_key"] != mission_key:
                raise PermissionError("Exception review does not belong to this mission")
            if row["decision"] != "approved":
                raise PermissionError("Rejected workforce exception cannot be applied")
            key = (str(row["pool_key"]), str(row["constraint_key"]))
            if key in reviews:
                raise ValueError("Only one approved review may satisfy a pool constraint")
            reviews[key] = dict(row)
        return reviews

    def _qualification_snapshot(
        self, pool: RolePoolRequirement, candidate: WorkforceCandidate
    ) -> dict[str, Any]:
        routing = candidate.routing
        qualification = self.router._qualification(routing.agent_id, pool.qualification_role)
        capabilities = set(json.loads(qualification["capabilities_json"])) if qualification else set()
        reasons: list[str] = []
        if not routing.enabled:
            reasons.append("disabled")
        if not routing.healthy:
            reasons.append("unhealthy")
        if not qualification:
            reasons.append("missing_qualification")
        elif qualification["status"] != "qualified":
            reasons.append(f"qualification_{qualification['status']}")
        elif not qualification["current"]:
            reasons.append("qualification_expired")
        elif qualification["lifecycle_state"] != "active":
            reasons.append(f"worker_{qualification['lifecycle_state']}")
        elif qualification["provider_id"] != routing.provider_id:
            reasons.append("qualification_provider_mismatch")
        if not set(pool.required_capabilities) <= capabilities:
            reasons.append("capability_mismatch")
        if candidate.capacity == 0:
            reasons.append("capacity_exhausted")
        return {
            "agent_id": routing.agent_id,
            "provider_id": routing.provider_id,
            "model_identity": routing.model_identity,
            "qualification_id": int(qualification["id"]) if qualification else None,
            "qualification_status": str(qualification["status"]) if qualification else "missing",
            "qualification_current": bool(qualification["current"]) if qualification else False,
            "lifecycle_state": str(qualification["lifecycle_state"]) if qualification else "offline",
            "capabilities": sorted(capabilities), "capacity": candidate.capacity,
            "estimated_cost": routing.cost, "eligible": not reasons, "reasons": reasons,
        }

    @staticmethod
    def _gap(pool_key: str, kind: str, detail: str, *, human: bool = False) -> dict[str, Any]:
        return {
            "code": f"{pool_key}:{kind}", "pool_key": pool_key, "kind": kind,
            "detail": detail, "human_review_required": human,
        }

    @staticmethod
    def _find_global_assignment(
        pool_options: list[tuple[str, list[tuple[str, ...]]]],
        candidates: dict[tuple[str, str], WorkforceCandidate],
        capacities: dict[str, int],
        roles: dict[str, RoleDefinition] | None,
        budget: float | None,
    ) -> tuple[dict[str, tuple[str, ...]], float] | None:
        def visit(
            index: int, used: dict[str, int], assigned_roles: dict[str, tuple[RoleDefinition, ...]],
            cost: float,
        ):
            if index == len(pool_options):
                return {}, cost
            pool_key, options = pool_options[index]
            for option in options:
                next_used = dict(used)
                option_cost = 0.0
                possible = True
                for agent_id in option:
                    next_used[agent_id] = next_used.get(agent_id, 0) + 1
                    if next_used[agent_id] > capacities[agent_id]:
                        possible = False
                        break
                    if roles:
                        role = roles[pool_key]
                        if any(
                            other.id in role.incompatible_duties
                            or role.id in other.incompatible_duties
                            for other in assigned_roles.get(agent_id, ())
                        ):
                            possible = False
                            break
                    option_cost += candidates[(pool_key, agent_id)].routing.cost
                if not possible or (budget is not None and cost + option_cost > budget):
                    continue
                next_roles = dict(assigned_roles)
                if roles:
                    for agent_id in option:
                        next_roles[agent_id] = (*next_roles.get(agent_id, ()), roles[pool_key])
                result = visit(index + 1, next_used, next_roles, cost + option_cost)
                if result:
                    assignments, total = result
                    return {pool_key: option, **assignments}, total
            return None

        return visit(0, {}, {}, 0.0)

    def compose(
        self,
        *,
        composition_key: str,
        mission_key: str,
        pools: tuple[RolePoolRequirement, ...],
        budget: float,
        approved_exception_review_ids: tuple[int, ...] = (),
    ) -> WorkforceComposition:
        if not composition_key.strip() or not mission_key.strip() or not pools:
            raise ValueError("Composition, mission, and at least one role pool are required")
        if budget < 0:
            raise ValueError("Workforce budget cannot be negative")
        if len({pool.key for pool in pools}) != len(pools):
            raise ValueError("Role pool keys must be unique")
        approved_exception_review_ids = tuple(sorted(approved_exception_review_ids))
        request = json.loads(self._json({
            "composition_key": composition_key, "mission_key": mission_key,
            "budget": budget, "pools": [asdict(pool) for pool in pools],
            "approved_exception_review_ids": list(approved_exception_review_ids),
        }))
        existing = self.storage.db.execute(
            "SELECT * FROM workforce_compositions WHERE composition_key=?", (composition_key,)
        ).fetchone()
        if existing:
            if json.loads(existing["request_json"]) != request:
                raise ValueError("Composition key is already bound to another request")
            return self._result(existing)

        exception_map = self._exception_map(mission_key, approved_exception_review_ids)
        gaps: list[dict[str, Any]] = []
        pool_work: list[dict[str, Any]] = []
        candidate_index: dict[tuple[str, str], WorkforceCandidate] = {}
        capacities: dict[str, int] = {}
        role_by_pool: dict[str, RoleDefinition] = {}
        used_exception_ids: set[int] = set()

        for pool in pools:
            role = self.roles.resolve(pool.role_id, pool.role_version)
            role_by_pool[pool.key] = role
            diagnostics = tuple(
                self._qualification_snapshot(pool, candidate) for candidate in pool.candidates
            )
            available = [
                candidate for candidate, snapshot in zip(pool.candidates, diagnostics)
                if snapshot["eligible"]
            ]
            for candidate in pool.candidates:
                agent_id = candidate.routing.agent_id
                previous = capacities.setdefault(agent_id, candidate.capacity)
                if previous != candidate.capacity:
                    raise ValueError("Candidate capacity must be consistent across role pools")
                candidate_index[(pool.key, agent_id)] = candidate
            applied: list[dict[str, Any]] = []
            waive_independence = exception_map.get((pool.key, "model_independence"))
            waive_diversity = exception_map.get((pool.key, "provider_diversity"))
            if waive_independence and not pool.require_model_independence:
                raise ValueError("Model-independence exception does not match a required constraint")
            if waive_diversity and not pool.require_provider_diversity:
                raise ValueError("Provider-diversity exception does not match a required constraint")
            for review in (waive_independence, waive_diversity):
                if review:
                    used_exception_ids.add(int(review["id"]))
                    applied.append({
                        "review_id": int(review["id"]),
                        "constraint": str(review["constraint_key"]),
                        "reviewer": str(review["reviewer"]),
                        "rationale": str(review["rationale"]),
                    })

            local_gaps: list[dict[str, Any]] = []
            qualified_without_capacity = [
                snapshot for snapshot in diagnostics
                if not [reason for reason in snapshot["reasons"] if reason != "capacity_exhausted"]
            ]
            if len(available) < pool.minimum_replicas:
                if len(qualified_without_capacity) >= pool.minimum_replicas:
                    local_gaps.append(self._gap(
                        pool.key, "capacity",
                        f"{len(available)} available slots for minimum {pool.minimum_replicas}",
                    ))
                else:
                    local_gaps.append(self._gap(
                        pool.key, "missing_capability",
                        f"{len(qualified_without_capacity)} qualified agents for minimum {pool.minimum_replicas}",
                    ))
            if pool.routing_strategy == "pinned" and pool.pinned_agent_id not in {
                candidate.routing.agent_id for candidate in available
            }:
                pinned = next((
                    snapshot for snapshot in diagnostics
                    if snapshot["agent_id"] == pool.pinned_agent_id
                ), None)
                kind = "capacity" if pinned and pinned["reasons"] == ["capacity_exhausted"] else "missing_capability"
                local_gaps.append(self._gap(
                    pool.key, kind, "Pinned agent is not currently eligible",
                ))

            decision = None
            options: list[tuple[str, ...]] = []
            if available and not local_gaps:
                decision = self.router.route(
                    decision_key=f"workforce:{composition_key}:{pool.key}",
                    role_id=pool.role_id, role_version=pool.role_version,
                    qualification_role=pool.qualification_role,
                    required_capabilities=set(pool.required_capabilities),
                    candidates=tuple(candidate.routing for candidate in available),
                    strategy=pool.routing_strategy, pinned_agent_id=pool.pinned_agent_id,
                )
                ordered = list(decision.fallback_chain)
                base_options = list(itertools.combinations(ordered, pool.minimum_replicas))
                independent_options = [option for option in base_options if len({
                    candidate_index[(pool.key, agent_id)].routing.model_identity
                    for agent_id in option
                }) == len(option)]
                diverse_options = [option for option in base_options if len({
                    candidate_index[(pool.key, agent_id)].routing.provider_id
                    for agent_id in option
                }) >= min(2, len(option))]
                if pool.require_model_independence and not waive_independence:
                    if not independent_options and base_options:
                        local_gaps.append(self._gap(
                            pool.key, "independence", "No model-independent replica set",
                            human=True,
                        ))
                    base_options = independent_options
                if pool.require_provider_diversity and not waive_diversity:
                    matching_diverse = [option for option in base_options if option in diverse_options]
                    if not matching_diverse and base_options:
                        local_gaps.append(self._gap(
                            pool.key, "provider_diversity", "No provider-diverse replica set",
                            human=True,
                        ))
                    base_options = matching_diverse
                options = base_options
            if not options and not local_gaps:
                local_gaps.append(self._gap(
                    pool.key, "capacity",
                    f"No replica set can satisfy minimum {pool.minimum_replicas}",
                ))
            gaps.extend(local_gaps)
            pool_work.append({
                "requirement": pool, "role": role, "diagnostics": diagnostics,
                "decision": decision, "options": options, "applied_exceptions": applied,
                "local_valid": not local_gaps,
            })

        if used_exception_ids != set(approved_exception_review_ids):
            raise ValueError("Every approved exception review must match a required pool constraint")

        assignment = None
        if not gaps:
            option_sets = [(item["requirement"].key, item["options"]) for item in pool_work]
            capacity_feasible = self._find_global_assignment(
                option_sets, candidate_index, capacities, role_by_pool, None
            )
            if not capacity_feasible:
                without_duty_constraints = self._find_global_assignment(
                    option_sets, candidate_index, capacities, None, None
                )
                gaps.append(self._gap(
                    "workforce",
                    "incompatible_duties" if without_duty_constraints else "capacity",
                    "No global assignment satisfies role-duty compatibility"
                    if without_duty_constraints
                    else "No global assignment satisfies agent capacity",
                ))
            else:
                assignment = self._find_global_assignment(
                    option_sets, candidate_index, capacities, role_by_pool, budget
                )
                if not assignment:
                    gaps.append(self._gap(
                        "workforce", "budget",
                        f"Minimum qualified workforce exceeds budget {budget:g}",
                    ))

        selected_by_pool, estimated_cost = assignment if assignment else ({}, 0.0)
        pool_documents: list[dict[str, Any]] = []
        for item in pool_work:
            pool = item["requirement"]
            selected = selected_by_pool.get(pool.key, ())
            decision = item["decision"]
            fallback = tuple(
                agent_id for agent_id in (decision.fallback_chain if decision else ())
                if agent_id not in selected
            )
            pool_documents.append({
                "pool_key": pool.key, "role_id": pool.role_id,
                "role_version": pool.role_version,
                "qualification_role": pool.qualification_role,
                "required_capabilities": list(pool.required_capabilities),
                "pool_strategy": pool.pool_strategy,
                "routing_strategy": pool.routing_strategy,
                "minimum_replicas": pool.minimum_replicas,
                "maximum_replicas": pool.maximum_replicas,
                "arbitration_rule": pool.arbitration_rule,
                "constraints": {
                    "model_independence": pool.require_model_independence,
                    "provider_diversity": pool.require_provider_diversity,
                },
                "qualifications": list(item["diagnostics"]),
                "primary_assignments": list(selected),
                "fallback_assignments": list(fallback),
                "routing_decision_id": decision.id if decision else None,
                "estimated_cost": sum(
                    candidate_index[(pool.key, agent_id)].routing.cost for agent_id in selected
                ),
                "valid": bool(assignment and item["local_valid"]),
                "applied_exceptions": item["applied_exceptions"],
            })

        status = "ready" if not gaps else "blocked"
        rationale = {
            "schema_version": 1, "status": status, "can_dispatch": status == "ready",
            "required_role_count": len(pools), "budget": budget,
            "estimated_cost": estimated_cost, "remaining_budget": budget - estimated_cost,
            "gap_codes": [gap["code"] for gap in gaps],
            "applied_exception_review_ids": sorted(approved_exception_review_ids),
        }
        document = {
            "request": request, "status": status, "rationale": rationale,
            "gaps": gaps, "pools": pool_documents,
        }
        digest = hashlib.sha256(self._json(document).encode()).hexdigest()
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO workforce_compositions(
                       identity,composition_key,mission_key,budget,request_json,status,
                       rationale_json,gaps_json,composition_digest
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("workforce-composition"), composition_key,
                    mission_key, budget, self._json(request), status,
                    self._json(rationale), self._json(gaps), digest,
                ),
            )
            composition_id = int(cursor.lastrowid)
            for pool in pool_documents:
                self.storage.db.execute(
                    """INSERT INTO workforce_role_pools(
                           identity,composition_id,pool_key,role_id,role_version,
                           qualification_role,pool_strategy,routing_strategy,minimum_replicas,
                           maximum_replicas,qualifications_json,arbitration_rule,constraints_json,
                           primary_assignments_json,fallback_assignments_json,routing_decision_id,
                           estimated_cost,valid,applied_exceptions_json
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        self.storage._identity("workforce-role-pool"), composition_id,
                        pool["pool_key"], pool["role_id"], pool["role_version"],
                        pool["qualification_role"], pool["pool_strategy"],
                        pool["routing_strategy"], pool["minimum_replicas"],
                        pool["maximum_replicas"], self._json(pool["qualifications"]),
                        pool["arbitration_rule"], self._json(pool["constraints"]),
                        self._json(pool["primary_assignments"]),
                        self._json(pool["fallback_assignments"]),
                        pool["routing_decision_id"], pool["estimated_cost"],
                        int(pool["valid"]), self._json(pool["applied_exceptions"]),
                    ),
                )
            self.storage._event("workforce.composed", "workforce_composition", composition_id, {
                "composition_key": composition_key, "mission_key": mission_key,
                "status": status, "gap_codes": rationale["gap_codes"],
                "estimated_cost": estimated_cost, "composition_digest": digest,
            })
        row = self.storage.db.execute(
            "SELECT * FROM workforce_compositions WHERE id=?", (composition_id,)
        ).fetchone()
        return self._result(row)

    def _result(self, row: Any) -> WorkforceComposition:
        pools = []
        for item in self.storage.db.execute(
            "SELECT * FROM workforce_role_pools WHERE composition_id=? ORDER BY id", (row["id"],)
        ):
            pools.append({
                "id": int(item["id"]), "pool_key": str(item["pool_key"]),
                "role_id": str(item["role_id"]), "role_version": str(item["role_version"]),
                "qualification_role": str(item["qualification_role"]),
                "pool_strategy": str(item["pool_strategy"]),
                "routing_strategy": str(item["routing_strategy"]),
                "minimum_replicas": int(item["minimum_replicas"]),
                "maximum_replicas": int(item["maximum_replicas"]),
                "qualifications": json.loads(item["qualifications_json"]),
                "arbitration_rule": str(item["arbitration_rule"]),
                "constraints": json.loads(item["constraints_json"]),
                "primary_assignments": json.loads(item["primary_assignments_json"]),
                "fallback_assignments": json.loads(item["fallback_assignments_json"]),
                "routing_decision_id": item["routing_decision_id"],
                "estimated_cost": float(item["estimated_cost"]),
                "valid": bool(item["valid"]),
                "applied_exceptions": json.loads(item["applied_exceptions_json"]),
            })
        return WorkforceComposition(
            int(row["id"]), str(row["composition_key"]), str(row["mission_key"]),
            str(row["status"]), float(row["budget"]), json.loads(row["rationale_json"]),
            tuple(json.loads(row["gaps_json"])), tuple(pools),
            str(row["composition_digest"]),
        )
