"""Durable bounded implementation/validation/critic/repair loop."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .storage import SQLiteStorage, _sha256_snapshot


@dataclass(frozen=True)
class LoopLimits:
    max_iterations: int
    max_seconds: int
    max_tokens: int
    max_cost_usd: float
    max_tool_failures: int

    def validate(self) -> "LoopLimits":
        integers = (
            self.max_iterations, self.max_seconds, self.max_tokens, self.max_tool_failures
        )
        if (
            any(isinstance(value, bool) or not isinstance(value, int) for value in integers)
            or self.max_iterations <= 0 or self.max_seconds <= 0 or self.max_tokens <= 0
            or self.max_tool_failures < 0
            or isinstance(self.max_cost_usd, bool)
            or not isinstance(self.max_cost_usd, (int, float))
            or not math.isfinite(self.max_cost_usd) or self.max_cost_usd < 0
        ):
            raise ValueError("Loop limits must be finite non-negative caps with positive iteration/time/token limits")
        return self


@dataclass(frozen=True)
class IterationUsage:
    seconds: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    tool_failures: int = 0

    def validate(self) -> "IterationUsage":
        integers = (self.seconds, self.tokens, self.tool_failures)
        if (
            any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in integers)
            or isinstance(self.cost_usd, bool)
            or not isinstance(self.cost_usd, (int, float))
            or not math.isfinite(self.cost_usd) or self.cost_usd < 0
        ):
            raise ValueError("Iteration usage cannot be negative")
        return self


@dataclass(frozen=True)
class IterationResult:
    id: int
    number: int
    outcome: str
    loop_status: str
    consecutive_failure_count: int


class EngineeringLoopService:
    """Persist every loop decision and enforce deterministic progress boundaries."""

    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    @staticmethod
    def _canonical(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def create(
        self,
        *,
        run_id: int,
        objective: str,
        worker_id: str,
        limits: LoopLimits,
        repeated_failure_action: str = "replan",
    ) -> int:
        objective, worker_id = objective.strip(), worker_id.strip()
        limits.validate()
        if not objective or not worker_id:
            raise ValueError("Engineering loop objective and worker are required")
        if repeated_failure_action not in {"replan", "replace_worker"}:
            raise ValueError("Repeated failure action must be replan or replace_worker")
        run = self.storage.durable_run(run_id)
        existing = self.storage.db.execute(
            "SELECT * FROM engineering_loops WHERE run_id=?", (run_id,)
        ).fetchone()
        if existing:
            expected = (
                objective, worker_id, repeated_failure_action,
                limits.max_iterations, limits.max_seconds, limits.max_tokens,
                limits.max_cost_usd, limits.max_tool_failures,
            )
            actual = tuple(existing[key] for key in (
                "objective", "worker_id", "repeated_failure_action", "max_iterations",
                "max_seconds", "max_tokens", "max_cost_usd", "max_tool_failures",
            ))
            if actual != expected:
                raise ValueError("Run is already bound to a different engineering loop")
            return int(existing["id"])
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO engineering_loops(
                       identity,run_id,task_id,objective,worker_id,repeated_failure_action,
                       max_iterations,max_seconds,max_tokens,max_cost_usd,max_tool_failures
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("engineering-loop"), run_id, run["task_id"],
                    objective, worker_id, repeated_failure_action, limits.max_iterations,
                    limits.max_seconds, limits.max_tokens, limits.max_cost_usd,
                    limits.max_tool_failures,
                ),
            )
            loop_id = int(cursor.lastrowid)
            self.storage._event("engineering.loop.created", "engineering_loop", loop_id, {
                "run_id": run_id, "task_id": run["task_id"], "worker_id": worker_id,
                "limits": asdict(limits), "repeated_failure_action": repeated_failure_action,
            })
        return loop_id

    def record_iteration(
        self,
        loop_id: int,
        *,
        plan: Mapping[str, Any],
        diff_digest: str,
        validator_results: Sequence[Mapping[str, Any]] | Mapping[str, Any],
        critic_result: Mapping[str, Any],
        usage: IterationUsage,
        failure: Mapping[str, Any] | None = None,
        accept: bool = False,
        accepted_evidence: bool = False,
        explicit_failure: str = "",
    ) -> IterationResult:
        _sha256_snapshot(diff_digest, "iteration diff digest")
        usage.validate()
        if not isinstance(plan, Mapping) or not plan:
            raise ValueError("Every engineering iteration requires a non-empty plan")
        valid_results = isinstance(validator_results, Mapping) or (
            isinstance(validator_results, Sequence)
            and not isinstance(validator_results, (str, bytes))
            and all(isinstance(value, Mapping) for value in validator_results)
        )
        if not valid_results or not validator_results:
            raise ValueError("Every engineering iteration requires validator results")
        if not isinstance(critic_result, Mapping) or not critic_result:
            raise ValueError("Every engineering iteration requires a critic result")
        if accept and not accepted_evidence:
            raise PermissionError("Loop acceptance requires accepted evidence")
        if accepted_evidence and not accept:
            raise ValueError("Accepted evidence can only be recorded by an accepting iteration")
        if accept and explicit_failure.strip():
            raise ValueError("An iteration cannot be accepted and explicitly failed")
        row = self.storage.db.execute(
            "SELECT * FROM engineering_loops WHERE id=?", (loop_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown engineering loop: {loop_id}")
        if row["status"] != "active":
            raise ValueError(f"Engineering loop {loop_id} is {row['status']}")

        number = int(row["current_iteration"]) + 1
        seconds = int(row["consumed_seconds"]) + usage.seconds
        tokens = int(row["consumed_tokens"]) + usage.tokens
        cost = float(row["consumed_cost_usd"]) + usage.cost_usd
        tool_failures = int(row["tool_failures"]) + usage.tool_failures
        failure_signature = None
        consecutive = 0
        if failure is not None:
            if not isinstance(failure, Mapping) or not failure:
                raise ValueError("Failure evidence must be a non-empty mapping")
            failure_signature = hashlib.sha256(self._canonical(failure).encode("utf-8")).hexdigest()
            consecutive = (
                int(row["consecutive_failure_count"]) + 1
                if failure_signature == row["last_failure_signature"] else 1
            )

        if accept:
            outcome, status, reason = "accepted", "accepted", "accepted evidence"
        elif explicit_failure.strip():
            outcome, status, reason = "failed", "failed", explicit_failure.strip()
        elif (
            number >= int(row["max_iterations"])
            or seconds > int(row["max_seconds"])
            or tokens > int(row["max_tokens"])
            or cost > float(row["max_cost_usd"])
            or tool_failures > int(row["max_tool_failures"])
        ):
            outcome, status, reason = "paused", "paused", "deterministic loop limit reached"
        elif consecutive >= 2:
            outcome = str(row["repeated_failure_action"])
            status, reason = "active", None
        else:
            outcome, status, reason = "repair", "active", None

        budget = {
            "iteration": number,
            "usage": asdict(usage),
            "cumulative": {
                "seconds": seconds, "tokens": tokens, "cost_usd": cost,
                "tool_failures": tool_failures,
            },
            "limits": {
                key: row[key] for key in (
                    "max_iterations", "max_seconds", "max_tokens",
                    "max_cost_usd", "max_tool_failures",
                )
            },
        }
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO engineering_iterations(
                       identity,loop_id,iteration_number,objective,plan_json,diff_digest,
                       validator_results_json,critic_result_json,budget_usage_json,
                       failure_signature,consecutive_failure_count,accepted_evidence,outcome
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("engineering-iteration"), loop_id, number,
                    row["objective"], self._canonical(plan), diff_digest,
                    self._canonical(validator_results), self._canonical(critic_result),
                    self._canonical(budget), failure_signature, consecutive,
                    int(accepted_evidence), outcome,
                ),
            )
            iteration_id = int(cursor.lastrowid)
            self.storage.db.execute(
                """UPDATE engineering_loops
                      SET status=?,current_iteration=?,consumed_seconds=?,consumed_tokens=?,
                          consumed_cost_usd=?,tool_failures=?,last_failure_signature=?,
                          consecutive_failure_count=?,termination_reason=?,
                          updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='active'""",
                (
                    status, number, seconds, tokens, cost, tool_failures,
                    failure_signature, consecutive, reason, loop_id,
                ),
            )
            self.storage._event(f"engineering.iteration.{outcome}", "engineering_iteration", iteration_id, {
                "loop_id": loop_id, "iteration": number, "status": status,
                "failure_signature": failure_signature,
                "consecutive_failure_count": consecutive, "budget": budget,
            })
        return IterationResult(iteration_id, number, outcome, status, consecutive)

    def escalate(self, loop_id: int, *, actor: str, reason: str) -> None:
        actor, reason = actor.strip(), reason.strip()
        if not actor or not reason:
            raise ValueError("Human escalation requires actor and reason")
        with self.storage.db:
            updated = self.storage.db.execute(
                """UPDATE engineering_loops
                      SET status='escalated',termination_actor=?,termination_reason=?,
                          updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status IN ('active','paused')""",
                (actor, reason, loop_id),
            )
            if updated.rowcount != 1:
                raise ValueError("Only an active or paused loop can be escalated")
            self.storage._event("engineering.loop.escalated", "engineering_loop", loop_id, {
                "actor": actor, "reason": reason,
            })

    def resume_with_approved_limits(
        self,
        loop_id: int,
        *,
        limits: LoopLimits,
        approved_by: str,
        approval_note: str,
    ) -> None:
        limits.validate()
        approved_by, approval_note = approved_by.strip(), approval_note.strip()
        if not approved_by or not approval_note:
            raise PermissionError("Limit increases require a human approval record")
        row = self.storage.db.execute(
            "SELECT * FROM engineering_loops WHERE id=?", (loop_id,)
        ).fetchone()
        if not row or row["status"] != "paused":
            raise ValueError("Only a paused engineering loop can resume")
        old = LoopLimits(*(row[key] for key in (
            "max_iterations", "max_seconds", "max_tokens", "max_cost_usd", "max_tool_failures"
        )))
        old_values, new_values = tuple(asdict(old).values()), tuple(asdict(limits).values())
        if any(new < previous for new, previous in zip(new_values, old_values)) or new_values == old_values:
            raise ValueError("Approved limits must increase at least one cap and cannot reduce another")
        if (
            limits.max_iterations <= int(row["current_iteration"])
            or limits.max_seconds < int(row["consumed_seconds"])
            or limits.max_tokens < int(row["consumed_tokens"])
            or limits.max_cost_usd < float(row["consumed_cost_usd"])
            or limits.max_tool_failures < int(row["tool_failures"])
        ):
            raise ValueError("Approved limits do not cover already consumed budget")
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO engineering_loop_limit_revisions(
                       identity,loop_id,previous_limits_json,new_limits_json,
                       approved_by,approval_note
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    self.storage._identity("engineering-limit-revision"), loop_id,
                    self._canonical(asdict(old)), self._canonical(asdict(limits)),
                    approved_by, approval_note,
                ),
            )
            self.storage.db.execute(
                """UPDATE engineering_loops
                      SET status='active',max_iterations=?,max_seconds=?,max_tokens=?,
                          max_cost_usd=?,max_tool_failures=?,termination_reason=NULL,
                          updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='paused'""",
                (
                    limits.max_iterations, limits.max_seconds, limits.max_tokens,
                    limits.max_cost_usd, limits.max_tool_failures, loop_id,
                ),
            )
            self.storage._event("engineering.loop.resumed", "engineering_loop", loop_id, {
                "approved_by": approved_by, "approval_note": approval_note,
                "limits": asdict(limits),
            })

    def state(self, loop_id: int) -> dict[str, Any]:
        loop = self.storage.db.execute(
            "SELECT * FROM engineering_loops WHERE id=?", (loop_id,)
        ).fetchone()
        if not loop:
            raise KeyError(f"Unknown engineering loop: {loop_id}")
        iterations = self.storage.db.execute(
            "SELECT * FROM engineering_iterations WHERE loop_id=? ORDER BY iteration_number",
            (loop_id,),
        ).fetchall()
        return {
            "loop": dict(loop),
            "iterations": [
                dict(row) | {
                    "plan": json.loads(row["plan_json"]),
                    "validator_results": json.loads(row["validator_results_json"]),
                    "critic_result": json.loads(row["critic_result_json"]),
                    "budget_usage": json.loads(row["budget_usage_json"]),
                }
                for row in iterations
            ],
        }
