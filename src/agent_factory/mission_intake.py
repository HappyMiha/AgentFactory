"""Normalized mission intake, source authority, and readiness verdicts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from .storage import SQLiteStorage


READINESS_VERDICTS = (
    "READY_FOR_BLUEPRINT", "NEEDS_CLARIFICATION", "NEEDS_HUMAN_REVIEW", "INFEASIBLE"
)


@dataclass(frozen=True)
class MissionSource:
    key: str
    subject: str
    authority: str
    version: str
    provenance: str
    content: str
    superseded: bool = False

    def __post_init__(self):
        if self.authority not in {"authoritative", "advisory", "reference"}:
            raise ValueError(f"Unknown source authority: {self.authority}")
        if not all(value.strip() for value in (
            self.key, self.subject, self.version, self.provenance, self.content
        )):
            raise ValueError("Source key, subject, version, provenance, and content are required")


@dataclass(frozen=True)
class MissionReadiness:
    id: int
    intake_id: int
    sequence: int
    verdict: str
    rationale: dict[str, Any]
    blocking_gaps: tuple[dict[str, Any], ...]
    request_ids: tuple[int, ...]


class MissionIntakeService:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    @staticmethod
    def _code(prefix: str, value: str) -> str:
        digest = hashlib.sha256(value.strip().encode()).hexdigest()[:12]
        return f"{prefix}:{digest}"

    def create(
        self,
        *,
        project_id: int,
        mission_owner: str,
        intent: str,
        objectives: list[str],
        success_measures: list[str],
        constraints: list[str],
        sources: tuple[MissionSource, ...],
        ambiguities: list[str] | None = None,
        infeasible_reasons: list[str] | None = None,
        high_risk_findings: list[str] | None = None,
        reduced_scope_proposed: str | None = None,
    ) -> int:
        if not mission_owner.strip() or not intent.strip():
            raise ValueError("Mission owner and intent are required")
        if not objectives or not success_measures or not sources:
            raise ValueError("Mission objectives, success measures, and sources are required")
        if len({source.key for source in sources}) != len(sources):
            raise ValueError("Mission source keys must be unique")
        normalized = {
            "objectives": sorted(set(value.strip() for value in objectives if value.strip())),
            "success_measures": sorted(set(value.strip() for value in success_measures if value.strip())),
            "constraints": sorted(set(value.strip() for value in constraints if value.strip())),
            "ambiguities": sorted(set(value.strip() for value in (ambiguities or []) if value.strip())),
            "infeasible_reasons": sorted(set(value.strip() for value in (infeasible_reasons or []) if value.strip())),
            "high_risk_findings": sorted(set(value.strip() for value in (high_risk_findings or []) if value.strip())),
            "reduced_scope_proposed": (reduced_scope_proposed or "").strip() or None,
            "sources": [asdict(source) for source in sorted(sources, key=lambda item: item.key)],
        }
        if not normalized["objectives"] or not normalized["success_measures"]:
            raise ValueError("Mission objectives and success measures cannot be blank")
        document = {
            "project_id": project_id, "mission_owner": mission_owner.strip(),
            "intent": intent.strip(), **normalized,
        }
        payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        existing = self.storage.db.execute(
            "SELECT id FROM mission_intakes WHERE intake_digest=?", (digest,)
        ).fetchone()
        if existing:
            return int(existing["id"])

        authoritative: dict[str, set[str]] = {}
        for source in sources:
            if source.authority == "authoritative" and not source.superseded:
                content_digest = hashlib.sha256(source.content.encode()).hexdigest()
                authoritative.setdefault(source.subject, set()).add(content_digest)
        conflicts = {subject for subject, digests in authoritative.items() if len(digests) > 1}
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO mission_intakes(
                       identity,project_id,mission_owner,intent,normalized_json,intake_digest
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    self.storage._identity("mission-intake"), project_id,
                    mission_owner.strip(), intent.strip(),
                    json.dumps(normalized, sort_keys=True), digest,
                ),
            )
            intake_id = int(cursor.lastrowid)
            for source in sorted(sources, key=lambda item: item.key):
                content_digest = hashlib.sha256(source.content.encode()).hexdigest()
                status = (
                    "superseded" if source.superseded else
                    "conflicted" if source.authority == "authoritative" and source.subject in conflicts
                    else "clear"
                )
                source_cursor = self.storage.db.execute(
                    """INSERT INTO mission_sources(
                           identity,intake_id,source_key,subject,authority,version,
                           provenance,content_digest,conflict_status
                       ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        self.storage._identity("mission-source"), intake_id, source.key,
                        source.subject, source.authority, source.version, source.provenance,
                        content_digest, status,
                    ),
                )
                self.storage._event("mission.source.classified", "mission_source", int(source_cursor.lastrowid), {
                    "intake_id": intake_id, "source_key": source.key, "subject": source.subject,
                    "authority": source.authority, "version": source.version,
                    "provenance": source.provenance, "content_digest": content_digest,
                    "conflict_status": status,
                })
            self.storage._event("mission.intake.created", "mission_intake", intake_id, {
                "project_id": project_id, "mission_owner": mission_owner.strip(),
                "intake_digest": digest, "source_count": len(sources),
            })
        return intake_id

    def resolve_gap(
        self,
        intake_id: int,
        *,
        gap_code: str,
        decision: str,
        rationale: str,
        actor: str,
        actor_role: str,
        accepted_reduced_scope: bool = False,
    ) -> int:
        intake = self.storage.db.execute(
            "SELECT mission_owner FROM mission_intakes WHERE id=?", (intake_id,)
        ).fetchone()
        if not intake:
            raise KeyError(f"Unknown mission intake: {intake_id}")
        if actor_role != "mission_owner" or actor != intake["mission_owner"]:
            raise PermissionError("Only the human mission owner may resolve mission intent or scope")
        if not gap_code.strip() or not decision.strip() or not rationale.strip():
            raise ValueError("Gap, decision, and rationale are required")
        already_resolved = self.storage.db.execute(
            "SELECT 1 FROM mission_owner_resolutions WHERE intake_id=? AND gap_code=?",
            (intake_id, gap_code),
        ).fetchone()
        if already_resolved:
            raise ValueError("Resolution must target a current blocking gap")
        latest_row = self.storage.db.execute(
            """SELECT * FROM mission_readiness_assessments
               WHERE intake_id=? ORDER BY sequence DESC LIMIT 1""",
            (intake_id,),
        ).fetchone()
        latest = self._result(latest_row) if latest_row else self.assess(intake_id)
        gap = next((item for item in latest.blocking_gaps if item["code"] == gap_code), None)
        if gap is None:
            raise ValueError("Resolution must target a current blocking gap")
        if gap["kind"] == "reduced_scope" and not accepted_reduced_scope:
            raise PermissionError("Materially reduced scope requires explicit owner acceptance")
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO mission_owner_resolutions(
                       identity,intake_id,gap_code,decision,rationale,resolved_by,
                       accepted_reduced_scope
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("mission-resolution"), intake_id, gap_code,
                    decision.strip(), rationale.strip(), actor, int(accepted_reduced_scope),
                ),
            )
            resolution_id = int(cursor.lastrowid)
            self.storage._event("mission.gap.resolved", "mission_resolution", resolution_id, {
                "intake_id": intake_id, "gap_code": gap_code, "resolved_by": actor,
                "accepted_reduced_scope": accepted_reduced_scope,
            })
        return resolution_id

    def assess(self, intake_id: int) -> MissionReadiness:
        intake = self.storage.db.execute(
            "SELECT * FROM mission_intakes WHERE id=?", (intake_id,)
        ).fetchone()
        if not intake:
            raise KeyError(f"Unknown mission intake: {intake_id}")
        normalized = json.loads(intake["normalized_json"])
        resolved = {
            str(row["gap_code"]): dict(row)
            for row in self.storage.db.execute(
                "SELECT * FROM mission_owner_resolutions WHERE intake_id=?", (intake_id,)
            )
        }
        gaps: list[dict[str, Any]] = []
        for value in normalized["ambiguities"]:
            code = self._code("ambiguity", value)
            if code not in resolved:
                gaps.append({"code": code, "kind": "ambiguity", "detail": value, "request_type": "clarification"})
        conflicted_subjects = sorted({
            str(row["subject"]) for row in self.storage.db.execute(
                "SELECT subject FROM mission_sources WHERE intake_id=? AND conflict_status='conflicted'",
                (intake_id,),
            )
        })
        for subject in conflicted_subjects:
            code = self._code("source_conflict", subject)
            if code not in resolved:
                gaps.append({"code": code, "kind": "source_conflict", "detail": subject, "request_type": "clarification"})
        for value in normalized["high_risk_findings"]:
            code = self._code("high_risk", value)
            if code not in resolved:
                gaps.append({"code": code, "kind": "high_risk", "detail": value, "request_type": "risk_review"})
        for value in normalized["infeasible_reasons"]:
            code = self._code("infeasible", value)
            if code not in resolved:
                gaps.append({"code": code, "kind": "infeasible", "detail": value, "request_type": "scope_review"})
        proposed = normalized.get("reduced_scope_proposed")
        if proposed:
            code = self._code("reduced_scope", proposed)
            resolution = resolved.get(code)
            if not resolution or not resolution["accepted_reduced_scope"]:
                gaps.append({"code": code, "kind": "reduced_scope", "detail": proposed, "request_type": "scope_review"})

        kinds = {gap["kind"] for gap in gaps}
        verdict = (
            "INFEASIBLE" if "infeasible" in kinds else
            "NEEDS_HUMAN_REVIEW" if kinds & {"high_risk", "reduced_scope"} else
            "NEEDS_CLARIFICATION" if gaps else "READY_FOR_BLUEPRINT"
        )
        rationale = {
            "schema_version": 1, "verdict": verdict,
            "objective_count": len(normalized["objectives"]),
            "success_measure_count": len(normalized["success_measures"]),
            "source_count": int(self.storage.db.execute(
                "SELECT COUNT(*) FROM mission_sources WHERE intake_id=?", (intake_id,)
            ).fetchone()[0]),
            "resolved_gap_codes": sorted(resolved),
            "blocking_gap_codes": [gap["code"] for gap in gaps],
            "can_proceed": verdict == "READY_FOR_BLUEPRINT",
        }
        existing = self.storage.db.execute(
            "SELECT * FROM mission_readiness_assessments WHERE intake_id=? ORDER BY sequence DESC LIMIT 1",
            (intake_id,),
        ).fetchone()
        document = {
            "intake_id": intake_id,
            "rationale": rationale,
            "blocking_gaps": gaps,
        }
        payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        if existing and existing["assessment_digest"] == digest:
            return self._result(existing)
        sequence = int(existing["sequence"]) + 1 if existing else 1
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO mission_readiness_assessments(
                       identity,intake_id,sequence,verdict,rationale_json,
                       blocking_gaps_json,assessment_digest
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("mission-readiness"), intake_id, sequence,
                    verdict, json.dumps(rationale, sort_keys=True),
                    json.dumps(gaps, sort_keys=True), digest,
                ),
            )
            assessment_id = int(cursor.lastrowid)
            for gap in gaps:
                request = self.storage.db.execute(
                    """INSERT INTO mission_review_requests(
                           identity,intake_id,assessment_id,gap_code,request_type,prompt
                       ) VALUES(?,?,?,?,?,?)""",
                    (
                        self.storage._identity("mission-review-request"), intake_id,
                        assessment_id, gap["code"], gap["request_type"],
                        f"Mission owner decision required: {gap['detail']}",
                    ),
                )
                self.storage._event("mission.review.requested", "mission_review_request", int(request.lastrowid), {
                    "intake_id": intake_id, "assessment_id": assessment_id,
                    "gap_code": gap["code"], "request_type": gap["request_type"],
                })
            self.storage._event("mission.readiness.assessed", "mission_readiness", assessment_id, {
                "intake_id": intake_id, "sequence": sequence, "verdict": verdict,
                "blocking_gap_codes": rationale["blocking_gap_codes"],
                "assessment_digest": digest,
            })
        row = self.storage.db.execute(
            "SELECT * FROM mission_readiness_assessments WHERE id=?", (assessment_id,)
        ).fetchone()
        return self._result(row)

    def _result(self, row: Any) -> MissionReadiness:
        requests = tuple(
            int(item["id"]) for item in self.storage.db.execute(
                "SELECT id FROM mission_review_requests WHERE assessment_id=? ORDER BY id",
                (row["id"],),
            )
        )
        return MissionReadiness(
            int(row["id"]), int(row["intake_id"]), int(row["sequence"]),
            str(row["verdict"]), json.loads(row["rationale_json"]),
            tuple(json.loads(row["blocking_gaps_json"])), requests,
        )
