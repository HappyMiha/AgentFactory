"""Single-node correlation and fail-closed execution budget enforcement."""

from __future__ import annotations

import json
import math
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
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

    @contextmanager
    def _write(self):
        """Serialize decisions and preserve a caller's enclosing transaction."""
        db = self.storage.db
        if not db.in_transaction:
            with db:
                db.execute("BEGIN IMMEDIATE")
                yield
            return
        # Upgrade a deferred transaction before reading budget state. A stale
        # WAL snapshot fails here; it must never authorize from stale totals.
        db.execute("UPDATE execution_traces SET id=id WHERE 0")
        db.execute("SAVEPOINT execution_telemetry_write")
        try:
            yield
        except BaseException:
            db.execute("ROLLBACK TO execution_telemetry_write")
            db.execute("RELEASE execution_telemetry_write")
            raise
        else:
            db.execute("RELEASE execution_telemetry_write")

    def _outstanding(self, trace_id: int) -> tuple[int, Decimal, int]:
        """Unused estimates remain held until an explicit immutable closure."""
        tokens, cost, calls = 0, Decimal(0), 0
        rows = self.storage.db.execute(
            """SELECT r.* FROM execution_stage_reservations r
               LEFT JOIN execution_reservation_closures c ON c.reservation_id=r.id
               WHERE r.trace_id=? AND r.decision='allowed' AND c.reservation_id IS NULL""",
            (trace_id,),
        ).fetchall()
        for row in rows:
            samples = self.storage.db.execute(
                """SELECT tokens,estimated_cost_usd,tool_calls FROM execution_usage_samples
                   WHERE trace_id=? AND stage_key=?""", (trace_id, row["stage_key"]),
            ).fetchall()
            tokens += max(0, row["estimated_tokens"] - sum(s["tokens"] for s in samples))
            cost += max(Decimal(0), Decimal(str(row["estimated_cost_usd"]))
                        - sum((Decimal(str(s["estimated_cost_usd"])) for s in samples), Decimal(0)))
            calls += max(0, row["estimated_tool_calls"] - sum(s["tool_calls"] for s in samples))
        return tokens, cost, calls

    def settle_stage(self, trace_id: int, stage_key: str, *, reason: str) -> bool:
        """Close after the trusted host ingested ALL final usage, even if zero."""
        return self._close_stage(trace_id, stage_key, state="settled", reason=reason)

    def release_stage(
        self, trace_id: int, stage_key: str, *, reason: str,
        confirmed_no_effect: bool = False,
    ) -> bool:
        """Release only with host evidence of no execution; never on timeout."""
        if confirmed_no_effect is not True:
            raise ValueError("Release requires confirmed no effect")
        return self._close_stage(trace_id, stage_key, state="released", reason=reason)

    def _close_stage(self, trace_id: int, stage_key: str, *, state: str, reason: str) -> bool:
        if not stage_key.strip() or not reason.strip() or state not in {"settled", "released"}:
            raise ValueError("Reservation closure requires a known state, stage and reason")
        with self._write():
            row = self.storage.db.execute(
                """SELECT r.*,t.status FROM execution_stage_reservations r
                   JOIN execution_traces t ON t.id=r.trace_id WHERE r.trace_id=? AND r.stage_key=?""",
                (trace_id, stage_key),
            ).fetchone()
            if not row or row["decision"] != "allowed":
                raise ValueError("No allowed reservation to close")
            existing = self.storage.db.execute(
                "SELECT * FROM execution_reservation_closures WHERE reservation_id=?", (row["id"],),
            ).fetchone()
            if existing:
                if (existing["state"], existing["reason"]) != (state, reason.strip()):
                    raise ValueError("Reservation already has a different closure")
                return False
            if row["status"] not in {"active", "paused"}:
                raise ValueError("Cannot close reservations of a terminal trace")
            sample = self.storage.db.execute(
                "SELECT id FROM execution_usage_samples WHERE trace_id=? AND stage_key=? LIMIT 1",
                (trace_id, stage_key),
            ).fetchone()
            if (state == "settled" and not sample) or (state == "released" and sample):
                raise ValueError("Settlement requires final usage; release requires no usage")
            self.storage.db.execute(
                "INSERT INTO execution_reservation_closures(reservation_id,state,reason) VALUES(?,?,?)",
                (row["id"], state, reason.strip()),
            )
            self.storage._event(f"telemetry.stage.{state}", "execution_trace", trace_id, {
                "stage_key": stage_key, "reason": reason.strip(),
            })
            return True

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
        with self._write():
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
        with self._write():
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
                if tuple(existing[k] for k in (
                    "estimated_tokens", "estimated_cost_usd", "estimated_tool_calls"
                )) != (estimated_tokens, estimated_cost_usd, estimated_tool_calls):
                    raise ValueError("Stage key is already bound to a different estimate")
                if existing["decision"] == "blocked":
                    raise BudgetExceeded(str(existing["reason"]))
                return False
            if row["status"] not in {"active", "paused"}:
                raise BudgetExceeded(f"trace is {row['status']}")
            if self.storage.db.execute(
                "SELECT id FROM execution_usage_samples WHERE trace_id=? AND stage_key=? LIMIT 1",
                (trace_id, stage_key),
            ).fetchone():
                raise ValueError("Cannot reserve a stage that already has usage")
            pending_tokens, pending_cost, pending_calls = self._outstanding(trace_id)
            reasons = []
            if row["status"] != "active": reasons.append(f"trace is {row['status']}")
            if int(row["stages_reserved"]) + 1 > int(row["max_stages"]): reasons.append("stage budget exceeded")
            if int(row["tokens"]) + pending_tokens + estimated_tokens > int(row["max_tokens"]): reasons.append("token budget exceeded")
            if Decimal(str(row["estimated_cost_usd"])) + pending_cost + Decimal(str(estimated_cost_usd)) > Decimal(str(row["max_cost_usd"])): reasons.append("cost budget exceeded")
            if int(row["tool_calls"]) + pending_calls + estimated_tool_calls > int(row["max_tool_calls"]): reasons.append("tool-call budget exceeded")
            decision, reason = ("blocked", "; ".join(reasons)) if reasons else ("allowed", "within budget")
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
        with self._write():
            row = self.storage.db.execute("SELECT * FROM execution_traces WHERE id=?", (trace_id,)).fetchone()
            if not row or not reason.strip():
                raise ValueError("Retry requires a trace and reason")
            if row["status"] not in {"active", "paused"}:
                raise BudgetExceeded(f"trace is {row['status']}")
            number = int(row["retries"]) + 1
            allowed = row["status"] == "active" and number <= int(row["max_retries"])
            decision = "allowed" if allowed else "blocked"
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
        with self._write():
            existing = self.storage.db.execute(
                "SELECT id FROM execution_usage_samples WHERE trace_id=? AND idempotency_key=?",
                (trace_id, idempotency_key),
            ).fetchone()
            if existing:
                return self.state(trace_id)
            row = self.storage.db.execute("SELECT * FROM execution_traces WHERE id=?", (trace_id,)).fetchone()
            if not row or row["status"] not in {"active", "paused"}:
                raise ValueError("Usage can only attach to an active or paused trace")
            if self.storage.db.execute(
                """SELECT c.reservation_id FROM execution_reservation_closures c
                   JOIN execution_stage_reservations r ON r.id=c.reservation_id
                   WHERE r.trace_id=? AND r.stage_key=?""", (trace_id, stage_key),
            ).fetchone():
                raise ValueError("Cannot append usage after reservation closure")
            totals = {
                "duration_ms": int(row["duration_ms"]) + duration_ms,
                "tokens": int(row["tokens"]) + tokens,
                "estimated_cost_usd": float(Decimal(str(row["estimated_cost_usd"])) + Decimal(str(estimated_cost_usd))),
                "tool_calls": int(row["tool_calls"]) + tool_calls,
            }
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
            pending_tokens, pending_cost, pending_calls = self._outstanding(trace_id)
            exceeded = (
                totals["tokens"] + pending_tokens > int(row["max_tokens"])
                or Decimal(str(totals["estimated_cost_usd"])) + pending_cost > Decimal(str(row["max_cost_usd"]))
                or totals["tool_calls"] + pending_calls > int(row["max_tool_calls"])
            )
            reason = terminal_reason or ("actual usage and commitments exceeded budget" if exceeded else row["terminal_reason"])
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
        with self._write():
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
