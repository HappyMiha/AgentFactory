"""Independent reviewer selection with durable, model-aware rotation."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Callable

from .models import Agent
from .registry import AgentRegistry
from .storage import SQLiteStorage


@dataclass(frozen=True)
class ReviewSubject:
    stage: str
    artifact_id: int
    producer: Agent


class ReviewerRouter:
    """Choose an enabled reviewer that did not produce the reviewed evidence."""

    def __init__(self, storage: SQLiteStorage, registry: AgentRegistry):
        self.storage = storage
        self.registry = registry

    def select(
        self,
        *,
        run_id: int,
        stage: str,
        candidate_ids: list[str],
        subjects: list[ReviewSubject],
        required_role: str,
        model_resolver: Callable[[Agent], str] | None = None,
    ) -> Agent:
        if not candidate_ids:
            raise ValueError(f"Review stage {stage} has an empty reviewer pool")
        if not subjects:
            raise ValueError(f"Review stage {stage} has no reviewed artifacts")

        if model_resolver is not None:
            frozen_subjects = []
            for subject in subjects:
                row = self.storage.db.execute(
                    "SELECT producer_json FROM artifacts WHERE id=? AND run_id=?",
                    (subject.artifact_id, run_id),
                ).fetchone()
                evidence = json.loads(row["producer_json"] or "{}") if row else {}
                identity = evidence.get("effective_model")
                if not identity or evidence.get("model_identity_source") != "qualified_request":
                    raise RuntimeError("Reviewed artifact has no effective model identity")
                frozen_subjects.append(replace(subject, producer=replace(
                    subject.producer, id=evidence.get("agent_id", subject.producer.id), model=identity
                )))
            subjects = frozen_subjects
        excluded_models = {subject.producer.model_identity.casefold() for subject in subjects}
        producer_ids = {subject.producer.id for subject in subjects}
        eligible: list[Agent] = []
        excluded: dict[str, str] = {}
        for agent_id in dict.fromkeys(candidate_ids):
            agent = self.registry.get(agent_id)
            if model_resolver is not None:
                try:
                    agent = replace(agent, model=model_resolver(agent))
                except ValueError:
                    excluded[agent.id] = "model has no qualified execution binding"
                    continue
            if not agent.enabled:
                excluded[agent.id] = "disabled"
            elif agent.role != required_role:
                excluded[agent.id] = f"role is {agent.role!r}, expected {required_role!r}"
            elif agent.id in producer_ids:
                excluded[agent.id] = "reviewer produced a reviewed artifact"
            elif agent.model_identity.casefold() in excluded_models:
                excluded[agent.id] = "reviewer model produced a reviewed artifact"
            else:
                eligible.append(agent)

        if not eligible:
            details = ", ".join(f"{key}: {value}" for key, value in excluded.items())
            raise RuntimeError(
                f"No independent reviewer is eligible for stage {stage}; {details}"
            )

        existing = self.storage.db.execute(
            "SELECT * FROM reviewer_assignments WHERE run_id=? AND stage=?", (run_id, stage)
        ).fetchone()
        if existing is not None:
            frozen = next((agent for agent in eligible
                           if agent.id == existing["reviewer_agent_id"]
                           and agent.provider == existing["reviewer_provider"]
                           and agent.model_identity == existing["reviewer_model"]), None)
            if (frozen is None
                    or json.loads(existing["reviewed_artifact_ids"]) != [subject.artifact_id for subject in subjects]
                    or json.loads(existing["reviewed_stages"]) != [subject.stage for subject in subjects]
                    or set(json.loads(existing["excluded_models"])) != excluded_models):
                raise RuntimeError("Persisted reviewer assignment changed; explicit new review attempt required")
            return frozen

        history = self.storage.reviewer_usage(stage, [agent.id for agent in eligible])
        last = self.storage.latest_reviewer_assignment(stage)
        pool_index = {agent_id: index for index, agent_id in enumerate(candidate_ids)}

        def rank(agent: Agent) -> tuple[int, int, int, int, str]:
            count, last_id = history.get(agent.id, (0, 0))
            same_last_agent = int(bool(last) and last["reviewer_agent_id"] == agent.id)
            same_last_model = int(
                bool(last)
                and str(last["reviewer_model"]).casefold()
                == agent.model_identity.casefold()
            )
            return (
                same_last_agent,
                same_last_model,
                count,
                last_id,
                f"{pool_index.get(agent.id, len(pool_index)):08d}:{agent.id}",
            )

        reviewer = min(eligible, key=rank)
        self.storage.record_reviewer_assignment(
            run_id=run_id,
            stage=stage,
            reviewer=reviewer,
            subjects=subjects,
            excluded_models=sorted(excluded_models),
            excluded_candidates=excluded,
            strategy="least-used-model-aware-round-robin",
        )
        return reviewer
