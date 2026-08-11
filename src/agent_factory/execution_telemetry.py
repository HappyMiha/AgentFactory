"""Single-node correlation and fail-closed execution budget enforcement."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

from .storage import SQLiteStorage


class BudgetExceeded(PermissionError):
    pass


@dataclass(frozen=True)
class ExecutionBudgets:
    max_tokens: int
    max_cost_usd: float
    max_stages: int
    max_retries: int
    max_tool_calls: int

    def validate(self) -> "ExecutionBudgets":
        integers = (self.max_tokens, self.max_stages, self.max_retries, self.max_tool_calls)
        if (
            any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in integers)
            or self.max_tokens <= 0 or self.max_stages <= 0
            or isinstance(self.max_cost_usd, bool)
            or not isinstance(self.max_cost_usd, (int, float))
            or not math.isfinite(self.max_cost_usd) or self.max_cost_usd < 0
        ):
            raise ValueError("Execution budgets require finite non-negative caps")
        return self


@dataclass(frozen=True)
class TraceState:
    id: int
    correlation_root: str
    status: str
    duration_ms: int
    retries: int
    tokens: int
    estimated_cost_usd: float
    tool_calls: int
    stages_reserved: int
    terminal_reason: str | None


class ExecutionTelemetryService:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    @staticmethod
    def _state(row) -> TraceState:
        return TraceState(
            int(row["id"]), str(row["correlation_root"]), str(row["status"]),
            int(row["duration_ms"]), int(row["retries"]), int(row["tokens"]),
            float(row["estimated_cost_usd"]), int(row["tool_calls"]),
            int(row["stages_reserved"]),
            str(row["terminal_reason"]) if row["terminal_reason"] else None,
        )

    def state(self, trace_id: int) -> TraceState:
        row = self.storage.db.execute(
            "SELECT * FROM execution_traces WHERE id=?", (trace_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown execution trace: {trace_id}")
        return self._state(row)

    def create(self, *, task_id: int, run_id: int, budgets: ExecutionBudgets) -> TraceState:
        budgets.validate()
        run = self.storage.db.execute(
            "SELECT task_id FROM workflow_runs WHERE id=?", (run_id,)
        ).fetchone()
        if not run or int(run["task_id"]) != task_id:
            raise ValueError("Execution trace task and workflow do not match")
        existing = self.storage.db.execute(
            "SELECT * FROM execution_traces WHERE run_id=?", (run_id,)
        ).fetchone()
        if existing:
            expected = (
                budgets.max_tokens, budgets.max_cost_usd, budgets.max_stages,
                budgets.max_retries, budgets.max_tool_calls,
            )
            actual = tuple(existing[key] for key in (
                "max_tokens", "max_cost_usd", "max_stages", "max_retries", "max_tool_calls"
            ))
            if actual != expected:
                raise ValueError("Workflow is already bound to a different execution budget")
            return self._state(existing)
        root = self.storage._identity("correlation-root")
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO execution_traces(
                       identity,correlation_root,task_id,run_id,max_tokens,max_cost_usd,
                       max_stages,max_retries,max_tool_calls
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("execution-trace"), root, task_id, run_id,
                    budgets.max_tokens, budgets.max_cost_usd, budgets.max_stages,
                    budgets.max_retries, budgets.max_tool_calls,
                ),
            )
            trace_id = int(cursor.lastrowid)
            self._link(trace_id, "task", task_id)
            self._link(trace_id, "workflow", run_id)
            self.storage._event("telemetry.trace.created", "execution_trace", trace_id, {
                "correlation_root": root, "task_id": task_id, "run_id": run_id,
                "budgets": budgets.__dict__,
            })
        return self.state(trace_id)

    def _link(self, trace_id: int, entity_type: str, entity_id: int) -> None:
        self.storage.db.execute(
            """INSERT OR IGNORE INTO execution_trace_links(
                   identity,trace_id,entity_type,entity_id
               ) VALUES(?,?,?,?)""",
            (self.storage._identity("execution-trace-link"), trace_id, entity_type, entity_id),
        )

    def link_delivery(self, trace_id: int, delivery_id: int) -> tuple[str, ...]:
        trace = self.storage.db.execute(
            "SELECT * FROM execution_traces WHERE id=?", (trace_id,)
        ).fetchone()
        delivery = self.storage.db.execute(
            "SELECT * FROM coding_delivery_runs WHERE id=?", (delivery_id,)
        ).fetchone()
        if not trace or not delivery or (
            int(trace["task_id"]) != int(delivery["task_id"])
            or int(trace["run_id"]) != int(delivery["run_id"])
        ):
            raise PermissionError("Coding delivery is outside the correlation root")
        with self.storage.db:
            self._link(trace_id, "coding_delivery", delivery_id)
            for row in self.storage.db.execute(
                "SELECT * FROM coding_delivery_iterations WHERE delivery_id=?", (delivery_id,)
            ):
                self._link(trace_id, "worker_process", int(row["codex_result_id"]))
                self._link(trace_id, "worktree", int(row["worktree_id"]))
                if row["candidate_id"] is not None:
                    self._link(trace_id, "candidate", int(row["candidate_id"]))
                if row["evaluation_id"] is not None:
                    self._link(trace_id, "evaluation", int(row["evaluation_id"]))
                result = self.storage.db.execute(
                    """SELECT w.attempt_id,c.approval_id
                         FROM codex_worker_results w
                         JOIN stage_approval_consumptions c ON c.id=w.approval_consumption_id
                        WHERE w.id=?""",
                    (row["codex_result_id"],),
                ).fetchone()
                self._link(trace_id, "stage_approval", int(result["approval_id"]))
                for validator in self.storage.db.execute(
                    "SELECT id FROM validator_results WHERE attempt_id=?", (result["attempt_id"],)
                ):
                    self._link(trace_id, "validator", int(validator["id"]))
            for hermes in self.storage.db.execute(
                "SELECT id FROM hermes_acp_sessions WHERE run_id=?", (trace["run_id"],)
            ):
                self._link(trace_id, "hermes_session", int(hermes["id"]))
            if delivery["founder_gate_id"] is not None:
                self._link(trace_id, "founder_approval", int(delivery["founder_gate_id"]))
            if delivery["github_gate_id"] is not None:
                self._link(trace_id, "github_approval", int(delivery["github_gate_id"]))
            self.storage._event("telemetry.trace.linked", "execution_trace", trace_id, {
                "correlation_root": trace["correlation_root"], "delivery_id": delivery_id,
            })
        return tuple(
            row["entity_type"] for row in self.storage.db.execute(
                "SELECT DISTINCT entity_type FROM execution_trace_links WHERE trace_id=? ORDER BY entity_type",
                (trace_id,),
            )
        )

    def reserve_stage(
        self, trace_id: int, stage_key: str, *,
        estimated_tokens: int = 0, estimated_cost_usd: float = 0.0,
        estimated_tool_calls: int = 0,
    ) -> bool:
        if (
            not stage_key.strip()
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in (estimated_tokens, estimated_tool_calls)
            )
            or isinstance(estimated_cost_usd, bool)
            or not isinstance(estimated_cost_usd, (int, float))
            or not math.isfinite(estimated_cost_usd) or estimated_cost_usd < 0
        ):
            raise ValueError("Stage budget estimate is invalid")
        row = self.storage.db.execute(
            "SELECT * FROM execution_traces WHERE id=?", (trace_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown execution trace: {trace_id}")
        existing = self.storage.db.execute(
            "SELECT * FROM execution_stage_reservations WHERE trace_id=? AND stage_key=?",
            (trace_id, stage_key),
        ).fetchone()
        if existing:
            if existing["decision"] == "blocked":
                raise BudgetExceeded(str(existing["reason"]))
            return False
        reasons = []
        if row["status"] != "active": reasons.append(f"trace is {row['status']}")
        if int(row["stages_reserved"]) + 1 > int(row["max_stages"]): reasons.append("stage budget exceeded")
        if int(row["tokens"]) + estimated_tokens > int(row["max_tokens"]): reasons.append("token budget exceeded")
        if float(row["estimated_cost_usd"]) + estimated_cost_usd > float(row["max_cost_usd"]): reasons.append("cost budget exceeded")
        if int(row["tool_calls"]) + estimated_tool_calls > int(row["max_tool_calls"]): reasons.append("tool-call budget exceeded")
        decision, reason = ("blocked", "; ".join(reasons)) if reasons else ("allowed", "within budget")
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO execution_stage_reservations(
                       identity,trace_id,stage_key,estimated_tokens,estimated_cost_usd,
                       estimated_tool_calls,decision,reason
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("execution-stage-reservation"), trace_id,
                    stage_key, estimated_tokens, estimated_cost_usd,
                    estimated_tool_calls, decision, reason,
                ),
            )
            if decision == "allowed":
                self.storage.db.execute(
                    "UPDATE execution_traces SET stages_reserved=stages_reserved+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (trace_id,),
                )
            else:
                self.storage.db.execute(
                    "UPDATE execution_traces SET status='paused',terminal_reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (reason, trace_id),
                )
            self.storage._event(f"telemetry.stage.{decision}", "execution_trace", trace_id, {
                "stage_key": stage_key, "reason": reason,
            })
        if decision == "blocked":
            raise BudgetExceeded(reason)
        return True

    def record_retry(self, trace_id: int, reason: str) -> bool:
        row = self.storage.db.execute("SELECT * FROM execution_traces WHERE id=?", (trace_id,)).fetchone()
        if not row or not reason.strip():
            raise ValueError("Retry requires a trace and reason")
        number = int(row["retries"]) + 1
        allowed = row["status"] == "active" and number <= int(row["max_retries"])
        decision = "allowed" if allowed else "blocked"
        with self.storage.db:
            self.storage.db.execute(
                "INSERT INTO execution_retry_records(identity,trace_id,retry_number,reason,decision) VALUES(?,?,?,?,?)",
                (self.storage._identity("execution-retry"), trace_id, number, reason.strip(), decision),
            )
            self.storage.db.execute(
                """UPDATE execution_traces SET retries=?,status=?,terminal_reason=?,updated_at=CURRENT_TIMESTAMP
                     WHERE id=?""",
                (number, "active" if allowed else "paused", None if allowed else "retry budget exceeded", trace_id),
            )
            self.storage._event(f"telemetry.retry.{decision}", "execution_trace", trace_id, {
                "retry_number": number, "reason": reason.strip(),
            })
        if not allowed:
            raise BudgetExceeded("retry budget exceeded")
        return True

    def ingest(
        self, trace_id: int, *, idempotency_key: str, stage_key: str,
        duration_ms: int, tokens: int, estimated_cost_usd: float, tool_calls: int,
        terminal_reason: str | None = None, metadata: Mapping[str, Any] | None = None,
    ) -> TraceState:
        values = (duration_ms, tokens, tool_calls)
        if (
            not idempotency_key.strip() or not stage_key.strip()
            or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values)
            or isinstance(estimated_cost_usd, bool)
            or not isinstance(estimated_cost_usd, (int, float))
            or not math.isfinite(estimated_cost_usd) or estimated_cost_usd < 0
        ):
            raise ValueError("Execution usage sample is invalid")
        existing = self.storage.db.execute(
            "SELECT id FROM execution_usage_samples WHERE trace_id=? AND idempotency_key=?",
            (trace_id, idempotency_key),
        ).fetchone()
        if existing:
            return self.state(trace_id)
        row = self.storage.db.execute("SELECT * FROM execution_traces WHERE id=?", (trace_id,)).fetchone()
        if not row or row["status"] not in {"active", "paused"}:
            raise ValueError("Usage can only attach to an active or paused trace")
        totals = {
            "duration_ms": int(row["duration_ms"]) + duration_ms,
            "tokens": int(row["tokens"]) + tokens,
            "estimated_cost_usd": float(row["estimated_cost_usd"]) + estimated_cost_usd,
            "tool_calls": int(row["tool_calls"]) + tool_calls,
        }
        exceeded = (
            totals["tokens"] > int(row["max_tokens"])
            or totals["estimated_cost_usd"] > float(row["max_cost_usd"])
            or totals["tool_calls"] > int(row["max_tool_calls"])
        )
        reason = terminal_reason or ("actual usage exceeded budget" if exceeded else row["terminal_reason"])
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO execution_usage_samples(
                       identity,trace_id,idempotency_key,stage_key,duration_ms,tokens,
                       estimated_cost_usd,tool_calls,terminal_reason,metadata_json
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("execution-usage"), trace_id,
                    idempotency_key, stage_key, duration_ms, tokens,
                    estimated_cost_usd, tool_calls, terminal_reason,
                    json.dumps(metadata or {}, sort_keys=True),
                ),
            )
            self.storage._event("telemetry.usage.recorded", "execution_trace", trace_id, {
                "idempotency_key": idempotency_key, "stage_key": stage_key,
                "duration_ms": duration_ms, "tokens": tokens,
                "estimated_cost_usd": estimated_cost_usd, "tool_calls": tool_calls,
                "paused": exceeded,
            })
            self.storage.db.execute(
                """UPDATE execution_traces SET duration_ms=?,tokens=?,estimated_cost_usd=?,
                       tool_calls=?,status=?,terminal_reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (
                    totals["duration_ms"], totals["tokens"], totals["estimated_cost_usd"],
                    totals["tool_calls"], "paused" if exceeded else row["status"], reason, trace_id,
                ),
            )
        return self.state(trace_id)

    def finish(self, trace_id: int, *, succeeded: bool, reason: str) -> TraceState:
        if not reason.strip():
            raise ValueError("Terminal telemetry reason is required")
        with self.storage.db:
            updated = self.storage.db.execute(
                """UPDATE execution_traces SET status=?,terminal_reason=?,updated_at=CURRENT_TIMESTAMP
                     WHERE id=? AND status IN ('active','paused')""",
                ("completed" if succeeded else "failed", reason.strip(), trace_id),
            )
            if updated.rowcount != 1:
                raise ValueError("Execution trace is already terminal")
            self.storage._event(
                "telemetry.trace.completed" if succeeded else "telemetry.trace.failed",
                "execution_trace", trace_id, {"terminal_reason": reason.strip()},
            )
        return self.state(trace_id)
