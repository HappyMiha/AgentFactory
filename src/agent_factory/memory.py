"""Typed governed memory, bounded retrieval, invalidation, and skills."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .storage import SQLiteStorage


STORE_POLICIES = {
    "working": {"decision", "context"},
    "semantic": {"fact", "decision"},
    "episodic": {"outcome"},
    "procedural": {"procedure"},
    "entity": {"entity"},
    "contextual": {"context"},
    "preference": {"preference"},
    "raw_history": {"raw_event"},
}
AUTHORITY_RANK = {"raw": 0, "advisory": 1, "verified": 2, "authoritative": 3}
VERSION = re.compile(r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")


@dataclass(frozen=True)
class MemoryWrite:
    store_type: str
    memory_type: str
    tenant_id: str
    mission_id: str
    task_id: str | None
    purpose: str
    authority: str
    source: str
    confidence: float
    valid_from: str
    valid_until: str | None
    invalidation_conditions: tuple[str, ...]
    content: Any

    def __post_init__(self):
        if self.store_type not in STORE_POLICIES:
            raise ValueError(f"Unknown memory store: {self.store_type}")
        if self.memory_type not in STORE_POLICIES[self.store_type]:
            raise PermissionError(
                f"{self.store_type} store does not accept {self.memory_type} writes"
            )
        if self.authority not in AUTHORITY_RANK:
            raise ValueError("Unknown memory authority")
        if not 0 <= self.confidence <= 1:
            raise ValueError("Memory confidence must be between zero and one")
        if not all(value.strip() for value in (
            self.tenant_id, self.mission_id, self.purpose, self.source, self.valid_from
        )):
            raise ValueError("Memory scope, purpose, source, and validity are required")
        if not self.invalidation_conditions or any(
            not value.strip() for value in self.invalidation_conditions
        ):
            raise ValueError("Memory invalidation conditions are required")
        start = _time(self.valid_from)
        if self.valid_until and _time(self.valid_until) <= start:
            raise ValueError("Memory validity interval is invalid")
        if self.store_type == "working" and not (self.task_id or "").strip():
            raise PermissionError("Working memory requires task scope")
        if self.store_type == "raw_history" and self.authority != "raw":
            raise PermissionError("Raw-history writes must retain raw authority")


@dataclass(frozen=True)
class MemoryRecord:
    id: int
    store_type: str
    memory_type: str
    content: Any
    authority: str
    confidence: float
    valid_from: str
    valid_until: str | None
    source: str
    content_digest: str


def _time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Memory validity must be ISO-8601") from exc
    if result.tzinfo is None:
        raise ValueError("Memory validity must include a timezone")
    return result


class MemoryService:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def write(self, memory: MemoryWrite) -> int:
        content_json = self._json(memory.content)
        valid_from = _time(memory.valid_from).astimezone(timezone.utc).isoformat()
        valid_until = (
            _time(memory.valid_until).astimezone(timezone.utc).isoformat()
            if memory.valid_until else None
        )
        document = {
            **{key: value for key, value in memory.__dict__.items() if key != "content"},
            "valid_from": valid_from, "valid_until": valid_until,
            "content": json.loads(content_json),
        }
        digest = hashlib.sha256(self._json(document).encode()).hexdigest()
        existing = self.storage.db.execute(
            "SELECT id FROM memory_entries WHERE content_digest=?", (digest,)
        ).fetchone()
        if existing:
            return int(existing["id"])
        source_digest = hashlib.sha256(memory.source.encode()).hexdigest()
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO memory_entries(
                       identity,store_type,memory_type,tenant_id,mission_id,task_id,
                       purpose,authority,source,source_digest,confidence,valid_from,
                       valid_until,invalidation_conditions_json,content_json,content_digest
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("memory"), memory.store_type, memory.memory_type,
                    memory.tenant_id, memory.mission_id, memory.task_id, memory.purpose,
                    memory.authority, memory.source, source_digest, memory.confidence,
                    valid_from, valid_until,
                    self._json(sorted(set(memory.invalidation_conditions))), content_json, digest,
                ),
            )
            memory_id = int(cursor.lastrowid)
            self.storage._event("memory.written", "memory", memory_id, {
                "store_type": memory.store_type, "memory_type": memory.memory_type,
                "tenant_id": memory.tenant_id, "mission_id": memory.mission_id,
                "purpose": memory.purpose, "authority": memory.authority,
                "source_digest": source_digest, "content_digest": digest,
            })
        return memory_id

    def retrieve(
        self,
        *,
        tenant_id: str,
        mission_id: str,
        purpose: str,
        store_types: tuple[str, ...],
        minimum_authority: str,
        max_results: int,
        task_id: str | None = None,
        now: datetime | None = None,
        consumer_type: str | None = None,
        consumer_id: str | None = None,
    ) -> tuple[MemoryRecord, ...]:
        if not tenant_id.strip() or not mission_id.strip() or not purpose.strip():
            raise ValueError("Memory retrieval scope and purpose are required")
        if not 1 <= max_results <= 50:
            raise ValueError("Memory retrieval result count must be between 1 and 50")
        if not store_types or not set(store_types) <= set(STORE_POLICIES):
            raise ValueError("Memory retrieval store types are invalid")
        if minimum_authority not in AUTHORITY_RANK:
            raise ValueError("Memory retrieval authority is invalid")
        if bool(consumer_type) != bool(consumer_id):
            raise ValueError("Memory consumer type and identity must be provided together")
        instant = (now or datetime.now(timezone.utc)).isoformat()
        placeholders = ",".join("?" for _ in store_types)
        rows = self.storage.db.execute(
            f"""SELECT m.* FROM memory_entries m
                 LEFT JOIN memory_invalidations i ON i.memory_id=m.id
                WHERE i.id IS NULL AND m.tenant_id=? AND m.mission_id=?
                  AND m.purpose=? AND m.store_type IN ({placeholders})
                  AND m.valid_from<=? AND (m.valid_until IS NULL OR m.valid_until>?)
                  AND (m.task_id IS NULL OR (? IS NOT NULL AND m.task_id=?))
                ORDER BY m.confidence DESC,m.id DESC""",
            (tenant_id, mission_id, purpose, *store_types, instant, instant, task_id, task_id),
        ).fetchall()
        eligible = [
            row for row in rows
            if AUTHORITY_RANK[str(row["authority"])] >= AUTHORITY_RANK[minimum_authority]
        ][:max_results]
        records = tuple(self._record(row) for row in eligible)
        if consumer_type:
            with self.storage.db:
                for record in records:
                    self.storage.db.execute(
                        """INSERT OR IGNORE INTO memory_consumers(
                               identity,memory_id,consumer_type,consumer_id,purpose
                           ) VALUES(?,?,?,?,?)""",
                        (
                            self.storage._identity("memory-consumer"), record.id,
                            consumer_type, consumer_id, purpose,
                        ),
                    )
        return records

    def invalidate(
        self,
        memory_id: int,
        *,
        reason: str,
        condition_key: str,
        invalidated_by: str,
        replacement_memory_id: int | None = None,
    ) -> int:
        row = self.storage.db.execute(
            "SELECT * FROM memory_entries WHERE id=?", (memory_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown memory entry: {memory_id}")
        conditions = json.loads(row["invalidation_conditions_json"])
        if condition_key not in conditions:
            raise PermissionError("Memory invalidation does not match a declared condition")
        if not reason.strip() or not invalidated_by.strip():
            raise ValueError("Memory invalidation reason and actor are required")
        if replacement_memory_id is not None and not self.storage.db.execute(
            "SELECT 1 FROM memory_entries WHERE id=?", (replacement_memory_id,)
        ).fetchone():
            raise KeyError(f"Unknown replacement memory: {replacement_memory_id}")
        existing = self.storage.db.execute(
            "SELECT id FROM memory_invalidations WHERE memory_id=?", (memory_id,)
        ).fetchone()
        if existing:
            return int(existing["id"])
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO memory_invalidations(
                       identity,memory_id,reason,condition_key,invalidated_by,replacement_memory_id
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    self.storage._identity("memory-invalidation"), memory_id,
                    reason.strip(), condition_key, invalidated_by, replacement_memory_id,
                ),
            )
            invalidation_id = int(cursor.lastrowid)
            self.storage._event("memory.invalidated", "memory", memory_id, {
                "invalidation_id": invalidation_id, "condition_key": condition_key,
                "invalidated_by": invalidated_by, "replacement_memory_id": replacement_memory_id,
            })
        return invalidation_id

    @staticmethod
    def _record(row: Any) -> MemoryRecord:
        return MemoryRecord(
            int(row["id"]), str(row["store_type"]), str(row["memory_type"]),
            json.loads(row["content_json"]), str(row["authority"]),
            float(row["confidence"]), str(row["valid_from"]), row["valid_until"],
            str(row["source"]), str(row["content_digest"]),
        )


class GovernedSkillService:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def draft(
        self, *, skill_key: str, version: str, specification: dict[str, Any],
        created_by: str, source_memory_id: int | None = None,
    ) -> int:
        if not skill_key.strip() or not VERSION.fullmatch(version) or not specification:
            raise ValueError("Skill key, semantic version, and specification are required")
        if source_memory_id is not None and not self.storage.db.execute(
            "SELECT 1 FROM memory_entries WHERE id=?", (source_memory_id,)
        ).fetchone():
            raise KeyError(f"Unknown source memory: {source_memory_id}")
        spec_json = self._json(specification)
        digest = hashlib.sha256(spec_json.encode()).hexdigest()
        existing = self.storage.db.execute(
            "SELECT id,specification_digest FROM governed_skills WHERE skill_key=? AND version=?",
            (skill_key, version),
        ).fetchone()
        if existing:
            if existing["specification_digest"] != digest:
                raise ValueError("Skill version already exists with another specification")
            return int(existing["id"])
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO governed_skills(
                       identity,skill_key,version,source_memory_id,specification_json,
                       specification_digest,status,created_by
                   ) VALUES(?,?,?,?,?,?,'draft',?)""",
                (
                    self.storage._identity("governed-skill"), skill_key, version,
                    source_memory_id, spec_json, digest, created_by,
                ),
            )
        return int(cursor.lastrowid)

    def review(
        self, skill_id: int, *, tests_version: str, tests_passed: bool,
        security_review: str, evaluation_score: float, evaluation_threshold: float,
        representative_cases: int, reviewer: str, reviewer_role: str,
        evidence: dict[str, Any],
    ) -> int:
        if reviewer_role not in {"curator", "human_approver"}:
            raise PermissionError("Reusable skill review requires curator or human approval")
        if not VERSION.fullmatch(tests_version) or security_review not in {"passed", "failed"}:
            raise ValueError("Skill review tests version or security verdict is invalid")
        if not 0 <= evaluation_score <= 1 or not 0 <= evaluation_threshold <= 1:
            raise ValueError("Skill evaluation values must be between zero and one")
        if representative_cases <= 0 or not evidence:
            raise ValueError("Representative skill evaluation evidence is required")
        if not self.storage.db.execute(
            "SELECT 1 FROM governed_skills WHERE id=?", (skill_id,)
        ).fetchone():
            raise KeyError(f"Unknown governed skill: {skill_id}")
        document = {
            "skill_id": skill_id, "tests_version": tests_version,
            "tests_passed": tests_passed, "security_review": security_review,
            "evaluation_score": evaluation_score,
            "evaluation_threshold": evaluation_threshold,
            "representative_cases": representative_cases, "reviewer": reviewer,
            "reviewer_role": reviewer_role, "evidence": evidence,
        }
        digest = hashlib.sha256(self._json(document).encode()).hexdigest()
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO governed_skill_reviews(
                       identity,skill_id,tests_version,tests_passed,security_review,
                       evaluation_score,evaluation_threshold,representative_cases,
                       reviewer,reviewer_role,evidence_json,review_digest
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("skill-review"), skill_id, tests_version,
                    int(tests_passed), security_review, evaluation_score,
                    evaluation_threshold, representative_cases, reviewer, reviewer_role,
                    self._json(evidence), digest,
                ),
            )
        return int(cursor.lastrowid)

    def transition(
        self, skill_id: int, target: str, *, actor: str, reason: str,
        review_id: int | None = None,
    ) -> None:
        skill = self.storage.db.execute(
            "SELECT * FROM governed_skills WHERE id=?", (skill_id,)
        ).fetchone()
        if not skill:
            raise KeyError(f"Unknown governed skill: {skill_id}")
        source = str(skill["status"])
        allowed = {"draft": {"approved", "revoked"}, "approved": {"deprecated", "revoked"},
                   "deprecated": {"revoked"}, "revoked": set()}
        if target not in allowed[source]:
            raise ValueError(f"Invalid skill transition: {source} -> {target}")
        if not actor.strip() or not reason.strip():
            raise ValueError("Skill transition actor and reason are required")
        if target == "approved":
            review = self.storage.db.execute(
                "SELECT * FROM governed_skill_reviews WHERE id=? AND skill_id=?",
                (review_id, skill_id),
            ).fetchone()
            if not review or not review["tests_passed"] or review["security_review"] != "passed" \
                    or review["evaluation_score"] < review["evaluation_threshold"]:
                raise PermissionError(
                    "Skill approval requires versioned passing tests, security review, and evaluation threshold"
                )
        with self.storage.db:
            updated = self.storage.db.execute(
                "UPDATE governed_skills SET status=? WHERE id=? AND status=?",
                (target, skill_id, source),
            )
            if updated.rowcount != 1:
                raise ValueError("Governed skill changed concurrently")
            self.storage.db.execute(
                """INSERT INTO governed_skill_transitions(
                       identity,skill_id,from_status,to_status,review_id,actor,reason
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("skill-transition"), skill_id, source,
                    target, review_id, actor, reason.strip(),
                ),
            )
            self.storage._event(f"skill.{target}", "governed_skill", skill_id, {
                "from_status": source, "review_id": review_id, "actor": actor,
            })
