"""OpenTelemetry-compatible export, cost accounting, and threshold actions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable

from .storage import SQLiteStorage


ThresholdExporter = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class CostEntry:
    id: int
    trace_id: int
    provider: str
    source: str
    tokens: int
    duration_ms: int
    cost_usd: float


class ObservabilityService:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def metrics(self) -> dict[str, float | int]:
        queue_depth = int(self.storage.db.execute(
            "SELECT COUNT(*) FROM work_items WHERE status IN ('pending','ready','queued')"
        ).fetchone()[0])
        wait = self.storage.db.execute(
            """SELECT COALESCE(AVG((julianday(COALESCE(a.updated_at,CURRENT_TIMESTAMP))-
                         julianday(w.created_at))*86400000),0)
                 FROM work_items w LEFT JOIN assignments a ON a.task_id=w.id"""
        ).fetchone()[0]
        runs = int(self.storage.db.execute(
            "SELECT COUNT(*) FROM workflow_runs"
        ).fetchone()[0])
        failures = int(self.storage.db.execute(
            "SELECT COUNT(*) FROM workflow_runs WHERE status IN ('failed','rejected')"
        ).fetchone()[0])
        orphaned = int(self.storage.db.execute(
            "SELECT COUNT(*) FROM worker_sessions WHERE status IN ('running','starting')"
        ).fetchone()[0]) + int(self.storage.db.execute(
            "SELECT COUNT(*) FROM worktrees WHERE status IN ('missing','dirty')"
        ).fetchone()[0])
        duration = self.storage.db.execute(
            "SELECT COALESCE(AVG(duration_ms),0) FROM execution_traces"
        ).fetchone()[0]
        iterations = int(self.storage.db.execute(
            "SELECT COUNT(*) FROM coding_delivery_iterations"
        ).fetchone()[0])
        return {
            "queue_depth": queue_depth,
            "wait_time_ms": round(float(wait or 0), 3),
            "run_duration_ms": round(float(duration or 0), 3),
            "failure_rate": (failures / runs) if runs else 0.0,
            "iteration_count": iterations,
            "orphaned_resources": orphaned,
        }

    def export_trace(
        self, trace_id: int, *, exporter: str = "otlp",
        sink: ThresholdExporter | None = None,
    ) -> dict[str, Any]:
        trace = self.storage.db.execute(
            "SELECT * FROM execution_traces WHERE id=?", (trace_id,)
        ).fetchone()
        if not trace:
            raise KeyError(f"Unknown execution trace: {trace_id}")
        samples = self.storage.db.execute(
            "SELECT * FROM execution_usage_samples WHERE trace_id=? ORDER BY id",
            (trace_id,),
        ).fetchall()
        links = self.storage.db.execute(
            "SELECT entity_type,entity_id FROM execution_trace_links WHERE trace_id=? ORDER BY id",
            (trace_id,),
        ).fetchall()
        payload = {
            "resource": {"service.name": "agent-factory", "exporter": exporter},
            "trace_id": str(trace["correlation_root"]),
            "trace_identity": str(trace["identity"]),
            "spans": [
                {
                    "name": str(sample["stage_key"]),
                    "duration_ms": int(sample["duration_ms"]),
                    "attributes": json.loads(sample["metadata_json"]),
                    "tokens": int(sample["tokens"]),
                    "estimated_cost_usd": float(sample["estimated_cost_usd"]),
                }
                for sample in samples
            ],
            "links": [
                {"entity_type": str(link["entity_type"]), "entity_id": int(link["entity_id"])}
                for link in links
            ],
            "metrics": self.metrics(),
            "status": str(trace["status"]),
        }
        canonical = self._json(payload)
        digest = self._digest(canonical)
        key = f"trace:{trace_id}:{digest}"
        existing = self.storage.db.execute(
            "SELECT payload_json FROM otel_exports WHERE idempotency_key=?", (key,)
        ).fetchone()
        if existing:
            payload = json.loads(existing["payload_json"])
        else:
            with self.storage.db:
                self.storage.db.execute(
                    """INSERT INTO otel_exports(
                           identity,trace_id,correlation_root,exporter,payload_json,
                           payload_digest,idempotency_key
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (
                        self.storage._identity("otel-export"), trace_id,
                        trace["correlation_root"], exporter, canonical, digest, key,
                    ),
                )
                self.storage._event("telemetry.otel.exported", "execution_trace", trace_id, {
                    "correlation_root": trace["correlation_root"], "exporter": exporter,
                    "payload_digest": digest,
                })
            if sink:
                sink(payload)
        return payload

    def record_cost(
        self, trace_id: int, *, idempotency_key: str, provider: str,
        source: str, tokens: int, duration_ms: int, cost_usd: float,
        metadata: dict[str, Any] | None = None,
    ) -> CostEntry:
        if source not in {"provider_reported", "estimated"} or not provider.strip() \
                or not idempotency_key.strip() or tokens < 0 or duration_ms < 0 or cost_usd < 0:
            raise ValueError("Cost ledger entry is invalid")
        trace = self.storage.db.execute(
            "SELECT 1 FROM execution_traces WHERE id=?", (trace_id,)
        ).fetchone()
        if not trace:
            raise KeyError(f"Unknown execution trace: {trace_id}")
        existing = self.storage.db.execute(
            "SELECT * FROM cost_ledger_entries WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone()
        if existing:
            return CostEntry(
                int(existing["id"]), int(existing["trace_id"]), str(existing["provider"]),
                str(existing["source"]), int(existing["tokens"]),
                int(existing["duration_ms"]), float(existing["cost_usd"]),
            )
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO cost_ledger_entries(
                       identity,trace_id,idempotency_key,provider,source,tokens,
                       duration_ms,cost_usd,metadata_json
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("cost-ledger"), trace_id, idempotency_key,
                    provider, source, tokens, duration_ms, cost_usd,
                    self._json(metadata or {}),
                ),
            )
            entry_id = int(cursor.lastrowid)
            self.storage._event("cost.ledger.recorded", "cost_ledger_entry", entry_id, {
                "trace_id": trace_id, "provider": provider, "source": source,
                "tokens": tokens, "cost_usd": cost_usd,
            })
        return CostEntry(entry_id, trace_id, provider, source, tokens, duration_ms, cost_usd)

    def add_threshold_policy(
        self, *, policy_key: str, metric: str, threshold: float,
        action: str, created_by: str, hard_budget: bool = False,
    ) -> int:
        if not policy_key.strip() or metric not in {"cost_usd", "tokens", "duration_ms"} \
                or action not in {"notify", "reroute", "pause", "require_approval"} \
                or threshold < 0 or not created_by.strip():
            raise ValueError("Budget threshold policy is invalid")
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO budget_threshold_policies(
                       identity,policy_key,metric,threshold,action,hard_budget,created_by
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("budget-threshold-policy"), policy_key,
                    metric, threshold, action, int(hard_budget), created_by,
                ),
            )
        return int(cursor.lastrowid)

    def evaluate_thresholds(self, trace_id: int) -> tuple[dict[str, Any], ...]:
        trace = self.storage.db.execute(
            "SELECT * FROM execution_traces WHERE id=?", (trace_id,)
        ).fetchone()
        if not trace:
            raise KeyError(f"Unknown execution trace: {trace_id}")
        totals = {
            "cost_usd": float(trace["estimated_cost_usd"]),
            "tokens": int(trace["tokens"]),
            "duration_ms": int(trace["duration_ms"]),
        }
        actions: list[dict[str, Any]] = []
        for policy in self.storage.db.execute(
            "SELECT * FROM budget_threshold_policies ORDER BY id"
        ):
            observed = totals[str(policy["metric"])]
            if observed < float(policy["threshold"]):
                continue
            existing = self.storage.db.execute(
                "SELECT * FROM budget_threshold_actions WHERE trace_id=? AND policy_id=?",
                (trace_id, policy["id"]),
            ).fetchone()
            if existing:
                actions.append({"policy_key": policy["policy_key"], "action": existing["action"], "status": existing["status"]})
                continue
            action = str(policy["action"])
            status = "awaiting_approval" if action == "require_approval" else "applied"
            detail = {"metric": policy["metric"], "threshold": policy["threshold"], "observed": observed}
            with self.storage.db:
                self.storage.db.execute(
                    """INSERT INTO budget_threshold_actions(
                           identity,trace_id,policy_id,observed_value,action,status,detail_json
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (
                        self.storage._identity("budget-threshold-action"), trace_id,
                        policy["id"], observed, action, status, self._json(detail),
                    ),
                )
                if action == "pause" and trace["status"] == "active":
                    self.storage.db.execute(
                        "UPDATE execution_traces SET status='paused',terminal_reason=? WHERE id=?",
                        (f"threshold:{policy['policy_key']}", trace_id),
                    )
                self.storage._event("budget.threshold.triggered", "execution_trace", trace_id, {
                    "policy_key": policy["policy_key"], "action": action,
                    "observed": observed, "status": status,
                })
            actions.append({"policy_key": policy["policy_key"], "action": action, "status": status})
        return tuple(actions)

    def increase_hard_budget(
        self, trace_id: int, *, new_max_cost_usd: float,
        authority: str, authority_role: str, reason: str,
    ) -> int:
        if authority_role != "human_budget_authority" or not authority.strip() or not reason.strip():
            raise PermissionError("Only a human budget authority may increase a hard budget")
        row = self.storage.db.execute(
            "SELECT max_cost_usd FROM execution_traces WHERE id=?", (trace_id,)
        ).fetchone()
        if not row or new_max_cost_usd < float(row["max_cost_usd"]):
            raise ValueError("New hard budget must be greater than the current budget")
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO budget_authorizations(
                       identity,trace_id,previous_max_cost_usd,new_max_cost_usd,
                       authority,authority_role,reason
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("budget-authorization"), trace_id,
                    row["max_cost_usd"], new_max_cost_usd, authority,
                    authority_role, reason,
                ),
            )
            self.storage.db.execute(
                "UPDATE execution_traces SET max_cost_usd=? WHERE id=?",
                (new_max_cost_usd, trace_id),
            )
            self.storage._event("budget.increased", "execution_trace", trace_id, {
                "authorization_id": int(cursor.lastrowid), "authority": authority,
                "new_max_cost_usd": new_max_cost_usd,
            })
        return int(cursor.lastrowid)
