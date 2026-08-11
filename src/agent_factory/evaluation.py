"""Independent, evidence-first criterion evaluation for candidate changes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .models import Agent
from .storage import SQLiteStorage
from .validators import VALIDATOR_CATEGORIES


@dataclass(frozen=True)
class CriterionEvidence:
    criterion: str
    primary_evidence: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class EvaluationRequest:
    candidate_id: int
    rubric_id: str
    rubric_version: str
    criteria: tuple[CriterionEvidence, ...]


@dataclass(frozen=True)
class CriterionVerdict:
    criterion: str
    verdict: str
    confidence: float
    concerns: tuple[str, ...]
    dissent: tuple[str, ...]
    primary_evidence: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class EvaluationResult:
    id: int
    accepted: bool
    summary: str
    verdicts: tuple[CriterionVerdict, ...]


ReviewFunction = Callable[[EvaluationRequest], Mapping[str, Any]]


class EvaluationService:
    """Run deterministic evidence checks before an independent model review."""

    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    @staticmethod
    def _strings(value: Any, field: str) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise ValueError(f"Reviewer {field} must be a list of non-empty strings")
        return tuple(item.strip() for item in value)

    def _existing(self, candidate_id: int, rubric_id: str, rubric_version: str) -> EvaluationResult | None:
        run = self.storage.db.execute(
            """SELECT * FROM evaluation_runs
                WHERE candidate_id=? AND rubric_id=? AND rubric_version=?""",
            (candidate_id, rubric_id, rubric_version),
        ).fetchone()
        if not run:
            return None
        rows = self.storage.db.execute(
            "SELECT * FROM criterion_verdicts WHERE evaluation_id=? ORDER BY criterion_index",
            (run["id"],),
        ).fetchall()
        return EvaluationResult(
            int(run["id"]), run["verdict"] == "accepted", str(run["summary"]),
            tuple(CriterionVerdict(
                str(row["criterion_text"]), str(row["verdict"]), float(row["confidence"]),
                tuple(json.loads(row["concerns_json"])), tuple(json.loads(row["dissent_json"])),
                tuple(json.loads(row["evidence_json"])),
            ) for row in rows),
        )

    def evaluate(
        self,
        candidate_id: int,
        *,
        reviewer: Agent,
        rubric_id: str,
        rubric_version: str,
        review: ReviewFunction,
    ) -> EvaluationResult:
        rubric_id, rubric_version = rubric_id.strip(), rubric_version.strip()
        if not rubric_id or not rubric_version:
            raise ValueError("Evaluation requires a rubric ID and version")
        existing = self._existing(candidate_id, rubric_id, rubric_version)
        if existing:
            return existing
        candidate = self.storage.db.execute(
            """SELECT c.*,w.attempt_id,w.producer_model
                 FROM candidate_change_artifacts c
                 JOIN codex_worker_results w ON w.id=c.codex_result_id
                WHERE c.id=?""",
            (candidate_id,),
        ).fetchone()
        if not candidate:
            raise KeyError(f"Unknown candidate: {candidate_id}")
        if not reviewer.enabled:
            raise PermissionError("Evaluation reviewer is disabled")
        producer_model = str(candidate["producer_model"])
        if reviewer.model_identity.casefold() == producer_model.casefold():
            raise PermissionError("A candidate-producing model cannot review its own change")

        rows = self.storage.db.execute(
            """SELECT * FROM validator_results
                WHERE task_id=? AND attempt_id=? AND candidate_digest=? ORDER BY category""",
            (candidate["task_id"], candidate["attempt_id"], candidate["diff_digest"]),
        ).fetchall()
        categories = {str(row["category"]) for row in rows}
        if len(rows) != len(VALIDATOR_CATEGORIES) or categories != set(VALIDATOR_CATEGORIES):
            raise PermissionError("Deterministic validation suite is incomplete")
        if any(row["status"] != "succeeded" for row in rows):
            raise PermissionError("Deterministic validation failed before model review")
        validation_snapshot = [
            {"category": row["category"], "evidence_digest": row["evidence_digest"]}
            for row in rows
        ]
        validation_json = json.dumps(validation_snapshot, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(validation_json.encode()).hexdigest() != candidate["validation_digest"]:
            raise PermissionError("Candidate validation evidence no longer matches its snapshot")

        task = self.storage.get_task(int(candidate["task_id"]))
        evidence_by_criterion: dict[str, list[dict[str, Any]]] = {
            criterion: [] for criterion in task.acceptance_criteria
        }
        for row in rows:
            evidence = {
                "validator_result_id": int(row["id"]),
                "category": str(row["category"]),
                "command_digest": str(row["command_digest"]),
                "evidence_digest": str(row["evidence_digest"]),
                "primary": True,
            }
            for criterion in json.loads(row["criterion_mappings_json"]):
                if criterion in evidence_by_criterion:
                    evidence_by_criterion[criterion].append(evidence)
        missing = [criterion for criterion, evidence in evidence_by_criterion.items() if not evidence]
        if missing:
            raise PermissionError(f"Required criteria lack primary evidence: {missing}")
        criteria = tuple(
            CriterionEvidence(criterion, tuple(evidence_by_criterion[criterion]))
            for criterion in task.acceptance_criteria
        )

        payload = review(EvaluationRequest(candidate_id, rubric_id, rubric_version, criteria))
        summary = payload.get("summary") if isinstance(payload, Mapping) else None
        supplied = payload.get("criteria") if isinstance(payload, Mapping) else None
        if not isinstance(summary, str) or not summary.strip() or not isinstance(supplied, list):
            raise ValueError("Reviewer must return a summary and criterion verdict list")
        by_criterion: dict[str, Mapping[str, Any]] = {}
        for value in supplied:
            if not isinstance(value, Mapping) or not isinstance(value.get("criterion"), str):
                raise ValueError("Reviewer returned an invalid criterion verdict")
            criterion = str(value["criterion"])
            if criterion in by_criterion:
                raise ValueError(f"Reviewer returned duplicate criterion: {criterion}")
            by_criterion[criterion] = value
        if set(by_criterion) != set(task.acceptance_criteria):
            raise ValueError("Reviewer must return exactly one verdict for every criterion")
        verdicts: list[CriterionVerdict] = []
        for criterion in task.acceptance_criteria:
            value = by_criterion[criterion]
            verdict = str(value.get("verdict", "")).casefold()
            if verdict not in {"pass", "fail"}:
                raise ValueError(f"Reviewer returned invalid verdict for {criterion}")
            confidence = value.get("confidence")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                raise ValueError(f"Reviewer confidence for {criterion} must be between 0 and 1")
            verdicts.append(CriterionVerdict(
                criterion, verdict, float(confidence),
                self._strings(value.get("concerns"), "concerns"),
                self._strings(value.get("dissent"), "dissent"),
                tuple(evidence_by_criterion[criterion]),
            ))
        accepted = all(value.verdict == "pass" for value in verdicts)
        evidence_json = json.dumps(
            [{"criterion": item.criterion, "evidence": item.primary_evidence} for item in criteria],
            sort_keys=True, separators=(",", ":"),
        )
        deterministic_digest = hashlib.sha256(evidence_json.encode()).hexdigest()
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO evaluation_runs(
                       identity,candidate_id,task_id,candidate_digest,producer_model,
                       reviewer_agent_id,reviewer_provider,reviewer_model,rubric_id,
                       rubric_version,deterministic_evidence_digest,verdict,summary
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("evaluation-run"), candidate_id, candidate["task_id"],
                    candidate["diff_digest"], producer_model, reviewer.id, reviewer.provider,
                    reviewer.model_identity, rubric_id, rubric_version, deterministic_digest,
                    "accepted" if accepted else "rejected", summary.strip(),
                ),
            )
            evaluation_id = int(cursor.lastrowid)
            for index, verdict in enumerate(verdicts):
                self.storage.db.execute(
                    """INSERT INTO criterion_verdicts(
                           identity,evaluation_id,criterion_index,criterion_text,verdict,
                           evidence_json,confidence,concerns_json,dissent_json
                       ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        self.storage._identity("criterion-verdict"), evaluation_id, index,
                        verdict.criterion, verdict.verdict,
                        json.dumps(verdict.primary_evidence, sort_keys=True, separators=(",", ":")),
                        verdict.confidence,
                        json.dumps(verdict.concerns, separators=(",", ":")),
                        json.dumps(verdict.dissent, separators=(",", ":")),
                    ),
                )
            self.storage._event("evaluation.completed", "evaluation_run", evaluation_id, {
                "candidate_id": candidate_id, "task_id": candidate["task_id"],
                "reviewer_agent_id": reviewer.id, "reviewer_model": reviewer.model_identity,
                "rubric_id": rubric_id, "rubric_version": rubric_version,
                "verdict": "accepted" if accepted else "rejected",
            })
        return EvaluationResult(evaluation_id, accepted, summary.strip(), tuple(verdicts))
