"""Replay-safe integration of the first complete coding-delivery slice."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable

from .candidate_changes import CandidateChangeService
from .engineering_loop import EngineeringLoopService, IterationUsage, LoopLimits
from .evaluation import EvaluationService, ReviewFunction
from .models import Agent
from .storage import SQLiteStorage
from .validators import VALIDATOR_CATEGORIES


ReplacementSelector = Callable[[str, dict[str, object]], str | None]


@dataclass(frozen=True)
class DeliveryState:
    id: int
    status: str
    repair_iterations: int
    current_worker_id: str
    candidate_id: int | None
    evaluation_id: int | None
    founder_gate_id: int | None
    github_plan_id: int | None
    github_gate_id: int | None


class CodingDeliveryService:
    """Connect persisted AF-049 output through review, Founder, and PR planning."""

    def __init__(
        self,
        storage: SQLiteStorage,
        candidate_changes: CandidateChangeService,
        evaluations: EvaluationService,
    ):
        self.storage = storage
        self.candidates = candidate_changes
        self.evaluations = evaluations
        self.loops = EngineeringLoopService(storage)

    @staticmethod
    def _snapshot(rows) -> list[dict[str, object]]:
        return [
            {
                "id": int(row["id"]), "category": str(row["category"]),
                "status": str(row["status"]), "command_digest": str(row["command_digest"]),
                "evidence_digest": str(row["evidence_digest"]),
            }
            for row in rows
        ]

    def _state(self, row) -> DeliveryState:
        return DeliveryState(
            int(row["id"]), str(row["status"]), int(row["repair_iterations"]),
            str(row["current_worker_id"]),
            int(row["candidate_id"]) if row["candidate_id"] is not None else None,
            int(row["evaluation_id"]) if row["evaluation_id"] is not None else None,
            int(row["founder_gate_id"]) if row["founder_gate_id"] is not None else None,
            int(row["github_plan_id"]) if row["github_plan_id"] is not None else None,
            int(row["github_gate_id"]) if row["github_gate_id"] is not None else None,
        )

    def state(self, delivery_id: int) -> DeliveryState:
        row = self.storage.db.execute(
            "SELECT * FROM coding_delivery_runs WHERE id=?", (delivery_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown coding delivery: {delivery_id}")
        return self._state(row)

    def start(
        self,
        codex_result_id: int,
        *,
        logical_attempt_key: str,
        stable_task_id: str,
        max_repair_iterations: int,
    ) -> DeliveryState:
        logical_attempt_key = logical_attempt_key.strip()
        if not logical_attempt_key or max_repair_iterations <= 0:
            raise ValueError("Delivery requires a logical attempt key and positive repair cap")
        result = self.storage.db.execute(
            """SELECT w.*,a.agent_id FROM codex_worker_results w
                 JOIN assignments a ON a.id=w.assignment_id WHERE w.id=?""",
            (codex_result_id,),
        ).fetchone()
        if not result:
            raise KeyError(f"Unknown Codex result: {codex_result_id}")
        existing = self.storage.db.execute(
            "SELECT * FROM coding_delivery_runs WHERE logical_attempt_key=?",
            (logical_attempt_key,),
        ).fetchone()
        if existing:
            if (
                int(existing["task_id"]) != int(result["task_id"])
                or str(existing["stable_task_id"]) != stable_task_id
                or int(existing["max_repair_iterations"]) != max_repair_iterations
            ):
                raise ValueError("Logical attempt key is already bound to another delivery scope")
            return self._state(existing)
        task = self.storage.get_task(int(result["task_id"]))
        loop_id = self.loops.create(
            run_id=int(result["run_id"]), objective=task.description or task.title,
            worker_id=str(result["agent_id"]),
            limits=LoopLimits(
                max_repair_iterations, max(1, task.budget.max_seconds),
                max(1, task.budget.max_tokens), max(0.0, task.budget.max_cost_usd),
                max_repair_iterations,
            ),
            repeated_failure_action="replace_worker",
        )
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO coding_delivery_runs(
                       identity,logical_attempt_key,task_id,run_id,stable_task_id,
                       engineering_loop_id,initial_worker_id,current_worker_id,
                       max_repair_iterations
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("coding-delivery"), logical_attempt_key,
                    result["task_id"], result["run_id"], stable_task_id, loop_id,
                    result["agent_id"], result["agent_id"], max_repair_iterations,
                ),
            )
            delivery_id = int(cursor.lastrowid)
            self.storage._event("coding.delivery.started", "coding_delivery", delivery_id, {
                "task_id": result["task_id"], "run_id": result["run_id"],
                "logical_attempt_key": logical_attempt_key,
                "assignment_id": result["assignment_id"], "worktree_id": result["worktree_id"],
            })
        return self.state(delivery_id)

    def process(
        self,
        delivery_id: int,
        codex_result_id: int,
        *,
        reviewer: Agent,
        rubric_id: str,
        rubric_version: str,
        review: ReviewFunction,
        replacement_selector: ReplacementSelector | None = None,
    ) -> DeliveryState:
        delivery = self.storage.db.execute(
            "SELECT * FROM coding_delivery_runs WHERE id=?", (delivery_id,)
        ).fetchone()
        if not delivery:
            raise KeyError(f"Unknown coding delivery: {delivery_id}")
        existing = self.storage.db.execute(
            "SELECT id FROM coding_delivery_iterations WHERE codex_result_id=?",
            (codex_result_id,),
        ).fetchone()
        if existing or delivery["status"] != "active":
            return self.state(delivery_id)
        result = self.storage.db.execute(
            """SELECT w.*,a.agent_id FROM codex_worker_results w
                 JOIN assignments a ON a.id=w.assignment_id WHERE w.id=?""",
            (codex_result_id,),
        ).fetchone()
        if not result or int(result["task_id"]) != int(delivery["task_id"]):
            raise PermissionError("Implementation result belongs to another delivery task")
        rows = self.storage.db.execute(
            """SELECT * FROM validator_results
                WHERE task_id=? AND attempt_id=? AND candidate_digest=? ORDER BY category""",
            (result["task_id"], result["attempt_id"], result["diff_digest"]),
        ).fetchall()
        snapshot = self._snapshot(rows)
        complete = len(rows) == len(VALIDATOR_CATEGORIES) and {
            str(row["category"]) for row in rows
        } == set(VALIDATOR_CATEGORIES)
        passed = complete and all(row["status"] == "succeeded" for row in rows)
        number = int(self.storage.db.execute(
            "SELECT COUNT(*) FROM coding_delivery_iterations WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()[0]) + 1
        failure: dict[str, object] | None = None
        candidate_id = evaluation_id = None
        if not passed:
            failure = {
                "kind": "validation", "complete": complete,
                "failed_categories": [row["category"] for row in rows if row["status"] != "succeeded"],
            }
        else:
            candidate = self.candidates.create(
                codex_result_id, stable_task_id=str(delivery["stable_task_id"])
            )
            candidate_id = candidate.id
            evaluation = self.evaluations.evaluate(
                candidate.id, reviewer=reviewer, rubric_id=rubric_id,
                rubric_version=rubric_version, review=review,
            )
            evaluation_id = evaluation.id
            if not evaluation.accepted:
                failure = {
                    "kind": "review", "evaluation_id": evaluation.id,
                    "failed_criteria": [item.criterion for item in evaluation.verdicts if item.verdict == "fail"],
                }

        handoff = json.loads(result["handoff_json"])
        if failure is None:
            self.loops.record_iteration(
                int(delivery["engineering_loop_id"]),
                plan={"worker": result["agent_id"], "handoff": handoff},
                diff_digest=str(result["diff_digest"]), validator_results=snapshot,
                critic_result={"verdict": "pass", "evaluation_id": evaluation_id},
                usage=IterationUsage(), accept=True, accepted_evidence=True,
            )
            founder_gate_id = self.storage.create_approval_gate(int(delivery["run_id"]))
            outcome, status, selected = "awaiting_founder", "awaiting_founder", None
        else:
            signature = hashlib.sha256(
                json.dumps(failure, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            selected = str(delivery["current_worker_id"])
            if replacement_selector:
                replacement = replacement_selector(selected, failure)
                if replacement and replacement.strip():
                    selected = replacement.strip()
            loop_result = self.loops.record_iteration(
                int(delivery["engineering_loop_id"]),
                plan={"worker": result["agent_id"], "handoff": handoff},
                diff_digest=str(result["diff_digest"]), validator_results=snapshot or [{"status": "missing"}],
                critic_result={"verdict": "repair", "failure": failure},
                usage=IterationUsage(tool_failures=int(not passed)), failure=failure,
            )
            repairs = int(delivery["repair_iterations"]) + 1
            exhausted = repairs >= int(delivery["max_repair_iterations"])
            outcome = "repair_exhausted" if exhausted else (
                "validation_failed" if not passed else "review_rejected"
            )
            status = "failed" if exhausted else "active"
            founder_gate_id = None
        if failure is None:
            repairs = int(delivery["repair_iterations"])

        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO coding_delivery_iterations(
                       identity,delivery_id,iteration_number,codex_result_id,
                       assignment_id,worktree_id,worker_id,validator_snapshot_json,
                       candidate_id,evaluation_id,outcome,selected_repair_worker_id,
                       failure_signature
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("coding-delivery-iteration"), delivery_id,
                    number, codex_result_id, result["assignment_id"], result["worktree_id"],
                    result["agent_id"], json.dumps(snapshot, sort_keys=True),
                    candidate_id, evaluation_id, outcome, selected,
                    hashlib.sha256(json.dumps(failure, sort_keys=True).encode()).hexdigest()
                    if failure else None,
                ),
            )
            iteration_id = int(cursor.lastrowid)
            self.storage.db.execute(
                """UPDATE coding_delivery_runs
                      SET status=?,repair_iterations=?,current_worker_id=?,
                          last_failure_signature=?,candidate_id=?,evaluation_id=?,
                          founder_gate_id=?,terminal_reason=?,updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='active'""",
                (
                    status, repairs, selected or delivery["current_worker_id"],
                    signature if failure else None, candidate_id, evaluation_id,
                    founder_gate_id, "maximum repair iterations reached" if status == "failed" else None,
                    delivery_id,
                ),
            )
            self.storage._event(f"coding.delivery.{outcome}", "coding_delivery_iteration", iteration_id, {
                "delivery_id": delivery_id, "iteration": number,
                "worker_id": result["agent_id"], "selected_repair_worker_id": selected,
                "candidate_id": candidate_id, "evaluation_id": evaluation_id,
                "founder_gate_id": founder_gate_id,
            })
        return self.state(delivery_id)

    def founder_decide(
        self,
        delivery_id: int,
        decision: str,
        *,
        actor: str,
        note: str,
        repo: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> DeliveryState:
        delivery = self.storage.db.execute(
            "SELECT * FROM coding_delivery_runs WHERE id=?", (delivery_id,)
        ).fetchone()
        if not delivery:
            raise KeyError(f"Unknown coding delivery: {delivery_id}")
        if delivery["status"] in {"pr_ready", "rejected"}:
            return self._state(delivery)
        if delivery["status"] != "awaiting_founder" or delivery["founder_gate_id"] is None:
            raise ValueError("Coding delivery is not awaiting Founder decision")
        self.storage.decide_approval(
            int(delivery["founder_gate_id"]), decision, note, actor=actor
        )
        plan_id = gate_id = None
        status = "rejected"
        if decision == "approved":
            plan_id, gate_id = self.candidates.plan_pull_request(
                int(delivery["candidate_id"]), repo=repo, base_branch=base_branch,
                title=title, body=body,
            )
            status = "pr_ready"
        with self.storage.db:
            self.storage.db.execute(
                """UPDATE coding_delivery_runs
                      SET status=?,github_plan_id=?,github_gate_id=?,terminal_reason=?,
                          updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='awaiting_founder'""",
                (
                    status, plan_id, gate_id,
                    None if status == "pr_ready" else "Founder rejected delivery",
                    delivery_id,
                ),
            )
            self.storage._event(f"coding.delivery.{status}", "coding_delivery", delivery_id, {
                "actor": actor, "founder_gate_id": delivery["founder_gate_id"],
                "github_plan_id": plan_id, "github_gate_id": gate_id,
                "external_mutation_executed": False,
            })
        return self.state(delivery_id)
