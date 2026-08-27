"""Static workflow validation and typed stage-result parsing."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .models import ProviderResult

PASSING_VERDICTS = frozenset(
    {"COMPLETE", "PASS", "ALIGNED", "CONDITIONALLY_ALIGNED", "APPROVED", "CONDITIONALLY_APPROVED"}
)
BLOCKING_VERDICTS = frozenset({"FAIL", "NOT_ALIGNED", "REJECTED", "BLOCKED"})
KNOWN_VERDICTS = PASSING_VERDICTS | BLOCKING_VERDICTS


class WorkflowContractError(ValueError):
    """Raised before execution when a workflow definition is unsafe or ambiguous."""


class StageContractError(RuntimeError):
    """Raised when provider output does not satisfy a stage's typed contract."""


@dataclass(frozen=True)
class StageVerdict:
    verdict: str
    criteria_evidence: dict[str, str]
    summary: str = ""

    @property
    def permits_progress(self) -> bool:
        return self.verdict in PASSING_VERDICTS


def _ancestors(stage_id: str, by_id: dict[str, dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    pending = list(by_id[stage_id].get("depends_on", []))
    while pending:
        dependency = pending.pop()
        if dependency not in result:
            result.add(dependency)
            pending.extend(by_id[dependency].get("depends_on", []))
    return result


def validate_workflow(workflow: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Validate a deterministic DAG plus configurable entry/exit policy boundaries."""

    stages = workflow.get("stages")
    if not isinstance(stages, list) or not stages:
        raise WorkflowContractError("Workflow must define a non-empty stages list")
    ids = [stage.get("id") if isinstance(stage, dict) else None for stage in stages]
    if any(not isinstance(stage_id, str) or not stage_id for stage_id in ids):
        raise WorkflowContractError("Every workflow stage requires a non-empty string id")
    duplicates = sorted({stage_id for stage_id in ids if ids.count(stage_id) > 1})
    if duplicates:
        raise WorkflowContractError(f"Duplicate workflow stage ids: {duplicates}")
    by_id: dict[str, dict[str, Any]] = dict(zip(ids, stages, strict=True))
    for stage in stages:
        stage_id = stage["id"]
        for field in ("name", "agent", "artifact"):
            if not isinstance(stage.get(field), str) or not stage[field].strip():
                raise WorkflowContractError(f"Stage {stage_id} requires a non-empty {field}")
        dependencies = stage.get("depends_on", [])
        if not isinstance(dependencies, list) or not all(
            isinstance(value, str) for value in dependencies
        ):
            raise WorkflowContractError(
                f"Stage {stage_id} dependencies must be a list of stage ids"
            )
        missing = sorted(set(dependencies) - set(ids))
        if missing:
            raise WorkflowContractError(
                f"Stage {stage_id} references missing dependencies: {missing}"
            )
        reviewer_pool = stage.get("reviewer_pool")
        if reviewer_pool is not None:
            if (
                not isinstance(reviewer_pool, list)
                or not reviewer_pool
                or not all(isinstance(value, str) and value.strip() for value in reviewer_pool)
                or len(set(reviewer_pool)) != len(reviewer_pool)
            ):
                raise WorkflowContractError(
                    f"Stage {stage_id} reviewer_pool must contain unique agent ids"
                )
            if stage["agent"] not in reviewer_pool:
                raise WorkflowContractError(
                    f"Stage {stage_id} default agent must belong to reviewer_pool"
                )
            reviewed = stage.get("review_of")
            reviewed_stages = [reviewed] if isinstance(reviewed, str) else reviewed
            if (
                not isinstance(reviewed_stages, list)
                or not reviewed_stages
                or not all(isinstance(value, str) and value for value in reviewed_stages)
            ):
                raise WorkflowContractError(
                    f"Stage {stage_id} reviewer_pool requires review_of stage ids"
                )
            unavailable = sorted(set(reviewed_stages) - set(ids))
            if unavailable:
                raise WorkflowContractError(
                    f"Stage {stage_id} reviews missing stages: {unavailable}"
                )
            not_dependencies = sorted(set(reviewed_stages) - _ancestors(stage_id, by_id))
            if not_dependencies:
                raise WorkflowContractError(
                    f"Stage {stage_id} can only review ancestor stages: {not_dependencies}"
                )
        quota_fallbacks = stage.get("token_exhaustion_fallback_agents")
        if quota_fallbacks is not None:
            if (
                not isinstance(quota_fallbacks, list)
                or not quota_fallbacks
                or not all(
                    isinstance(value, str) and value.strip()
                    for value in quota_fallbacks
                )
                or len(set(quota_fallbacks)) != len(quota_fallbacks)
            ):
                raise WorkflowContractError(
                    f"Stage {stage_id} token_exhaustion_fallback_agents must "
                    "contain unique agent ids"
                )
            if stage["agent"] in quota_fallbacks:
                raise WorkflowContractError(
                    f"Stage {stage_id} cannot repeat its primary agent in the "
                    "token-exhaustion fallback chain"
                )
            if reviewer_pool is not None:
                raise WorkflowContractError(
                    f"Review stage {stage_id} cannot use coding token failover"
                )
        contract = stage.get("contract")
        if not isinstance(contract, dict):
            raise WorkflowContractError(f"Stage {stage_id} requires a typed contract")
        allowed = contract.get("allowed_verdicts")
        if (
            not isinstance(allowed, list)
            or not allowed
            or not all(isinstance(value, str) for value in allowed)
            or not set(allowed) <= KNOWN_VERDICTS
        ):
            raise WorkflowContractError(f"Stage {stage_id} has invalid allowed verdicts")
        if not set(allowed) & PASSING_VERDICTS:
            raise WorkflowContractError(f"Stage {stage_id} has no passing verdict")
        criteria = stage.get("acceptance_criteria")
        if not isinstance(criteria, list) or not criteria or not all(
            isinstance(value, str) and value.strip() for value in criteria
        ):
            raise WorkflowContractError(
                f"Stage {stage_id} requires non-empty acceptance criteria"
            )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(stage_id: str) -> None:
        if stage_id in visiting:
            raise WorkflowContractError(f"Workflow dependency cycle includes {stage_id}")
        if stage_id in visited:
            return
        visiting.add(stage_id)
        for dependency in by_id[stage_id].get("depends_on", []):
            visit(dependency)
        visiting.remove(stage_id)
        visited.add(stage_id)

    for stage_id in ids:
        visit(stage_id)

    position = {stage_id: index for index, stage_id in enumerate(ids)}
    for stage in stages:
        late = [
            dependency
            for dependency in stage.get("depends_on", [])
            if position[dependency] >= position[stage["id"]]
        ]
        if late:
            raise WorkflowContractError(
                f"Workflow order is not topological: stage {stage['id']} appears before {late}"
            )

    guardrails = workflow.get("guardrails")
    if not isinstance(guardrails, dict):
        raise WorkflowContractError("Workflow requires configurable guardrails")
    precheck = guardrails.get("precheck_stage")
    postcheck = guardrails.get("postcheck_stage")
    guardian = guardrails.get("guardian_agent")
    if not all(isinstance(value, str) and value for value in (precheck, postcheck, guardian)):
        raise WorkflowContractError(
            "guardrails require precheck_stage, postcheck_stage, and guardian_agent"
        )
    if precheck not in by_id or postcheck not in by_id:
        raise WorkflowContractError("Configured guardrail stages are missing")
    if by_id[precheck]["agent"] != guardian or by_id[postcheck]["agent"] != guardian:
        raise WorkflowContractError("Configured guardrail stages must use guardian_agent")
    if ids[-1] != postcheck:
        raise WorkflowContractError("The configured postcheck stage must be terminal")
    if position[precheck] >= position[postcheck]:
        raise WorkflowContractError("The precheck stage must execute before the postcheck stage")
    for stage_id in ids[position[precheck] + 1 :]:
        if stage_id != postcheck and precheck not in _ancestors(stage_id, by_id):
            raise WorkflowContractError(
                f"Stage {stage_id} is not transitively gated by {precheck}"
            )
    missing_from_post = set(ids[:-1]) - _ancestors(postcheck, by_id)
    if missing_from_post:
        raise WorkflowContractError(
            f"Postcheck does not cover stages: {sorted(missing_from_post)}"
        )
    return tuple(stages)


def _json_payload(content: str) -> dict[str, Any] | None:
    candidate = content.strip()
    fenced = re.search(
        r"```json\s*(\{.*?\})\s*```", candidate, flags=re.DOTALL | re.IGNORECASE
    )
    if fenced:
        candidate = fenced.group(1)
    elif not candidate.startswith("{"):
        return None
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise StageContractError(f"Malformed JSON stage result: {exc.msg}") from exc
    return payload if isinstance(payload, dict) else None


def parse_stage_verdict(stage: dict[str, Any], result: ProviderResult) -> StageVerdict:
    """Require a verdict and evidence for every configured acceptance criterion."""

    payload = _json_payload(result.content)
    if payload is None:
        raise StageContractError(
            f"Stage {stage['id']} must return JSON with verdict, criteria_evidence, and summary"
        )
    verdict = str(payload.get("verdict", "")).upper()
    evidence = payload.get("criteria_evidence", {})
    summary = str(payload.get("summary", ""))
    if not isinstance(evidence, dict) or not all(
        isinstance(key, str) and isinstance(value, str) and value.strip()
        for key, value in evidence.items()
    ):
        raise StageContractError(
            f"Stage {stage['id']} criteria_evidence must map criteria to non-empty evidence"
        )
    allowed = set(stage["contract"]["allowed_verdicts"])
    if verdict not in KNOWN_VERDICTS:
        raise StageContractError(
            f"Stage {stage['id']} returned unknown verdict {verdict!r}"
        )
    if verdict not in allowed:
        raise StageContractError(
            f"Stage {stage['id']} verdict {verdict} is not allowed by its contract"
        )
    missing_evidence = [
        criterion
        for criterion in stage.get("acceptance_criteria", [])
        if not str(evidence.get(criterion, "")).strip()
    ]
    if missing_evidence:
        raise StageContractError(
            f"Stage {stage['id']} lacks acceptance evidence for: {missing_evidence}"
        )
    parsed = StageVerdict(verdict, dict(evidence), summary)
    if not parsed.permits_progress:
        raise StageContractError(
            f"Stage {stage['id']} blocked progression with verdict {verdict}"
        )
    return parsed
