"""Normalized mission intake, source authority, and readiness verdicts."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from .autonomous_mission import (
    AutonomousMission,
    AutonomousMissionConfiguration,
    AutonomousMissionService,
    MissionDisposition,
    MissionPhase,
    MissionVersionConflictError,
)
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


class SpecificationSourceKind(StrEnum):
    TEXT = "TEXT"
    UPLOAD = "UPLOAD"


class SpecificationCommandConflictError(ValueError):
    """Raised when an intake idempotency key is rebound to different input."""


class UnsafeSpecificationUploadError(ValueError):
    """Raised when uploaded bytes are unsupported, active, or unreadable."""


@dataclass(frozen=True)
class AutonomousSpecificationSource:
    id: int
    identity: str
    mission_id: int
    version: int
    source_kind: SpecificationSourceKind
    source_name: str
    media_type: str
    provenance: str
    actor: str
    content: str
    content_digest: str
    raw_digest: str
    byte_count: int
    metadata: dict[str, Any]
    source_digest: str
    intake_source_id: int | None
    command_id: str
    request_digest: str
    created_at: str
    current: bool
    superseded_by_source_id: int | None

    def binding(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "version": self.version,
            "source_kind": self.source_kind.value,
            "source_name": self.source_name,
            "media_type": self.media_type,
            "provenance": self.provenance,
            "actor": self.actor,
            "content_digest": self.content_digest,
            "raw_digest": self.raw_digest,
            "byte_count": self.byte_count,
            "metadata": self.metadata,
            "intake_source_id": self.intake_source_id,
        }


@dataclass(frozen=True)
class AutonomousMissionIntakeResult:
    mission: AutonomousMission
    source: AutonomousSpecificationSource


@dataclass(frozen=True)
class _PreparedSpecification:
    source_kind: SpecificationSourceKind
    source_name: str
    media_type: str
    raw: bytes
    content: str
    metadata: dict[str, Any]


class AutonomousMissionIntakeService:
    """Create and version authoritative Autonomous Mission specification sources."""

    MAX_UPLOAD_BYTES = 10 * 1024 * 1024
    MAX_PDF_PAGES = 500
    PREAPPROVAL_PHASES = frozenset(
        {
            MissionPhase.DRAFT,
            MissionPhase.SPECIFICATION_ANALYSIS,
            MissionPhase.BACKLOG_GENERATION,
            MissionPhase.WAITING_FOR_BACKLOG_APPROVAL,
        }
    )
    MEDIA_BY_SUFFIX = {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".json": "application/json",
        ".pdf": "application/pdf",
    }
    PDF_ACTIVE_MARKERS = (
        b"/javascript",
        b"/js",
        b"/launch",
        b"/embeddedfiles",
        b"/richmedia",
        b"/submitform",
        b"/importdata",
    )

    def __init__(self, storage: SQLiteStorage):
        self.storage = storage
        self.missions = AutonomousMissionService(storage)
        self.intakes = MissionIntakeService(storage)

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

    @classmethod
    def _digest(cls, value: Any) -> str:
        return hashlib.sha256(cls._json(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    @staticmethod
    def _required(value: str, label: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError(f"{label} is required")
        return normalized

    @staticmethod
    def _source_name(value: str) -> str:
        if "\x00" in str(value):
            raise UnsafeSpecificationUploadError("Specification filename is invalid")
        name = Path(str(value)).name.strip()
        if not name or name in {".", ".."}:
            raise UnsafeSpecificationUploadError("Specification filename is required")
        return name[:255]

    @staticmethod
    def _validate_text(content: str) -> str:
        if not content.strip():
            raise UnsafeSpecificationUploadError("Specification content is empty")
        if "\x00" in content or any(
            ord(character) < 32 and character not in "\n\r\t" for character in content
        ):
            raise UnsafeSpecificationUploadError(
                "Specification contains unsafe binary control characters"
            )
        return content

    @staticmethod
    def _json_without_duplicate_keys(content: str) -> Any:
        def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in values:
                if key in result:
                    raise UnsafeSpecificationUploadError(
                        f"JSON specification contains duplicate key {key!r}"
                    )
                result[key] = value
            return result

        try:
            return json.loads(content, object_pairs_hook=pairs)
        except UnsafeSpecificationUploadError:
            raise
        except (json.JSONDecodeError, RecursionError) as exc:
            raise UnsafeSpecificationUploadError(
                "JSON specification is malformed or excessively nested"
            ) from exc

    def _prepare_text(
        self,
        content: str,
        *,
        source_name: str,
        media_type: str | None,
        source_kind: SpecificationSourceKind,
    ) -> _PreparedSpecification:
        name = self._source_name(source_name)
        suffix = Path(name).suffix.casefold()
        inferred = self.MEDIA_BY_SUFFIX.get(suffix, "text/plain")
        if inferred == "application/pdf":
            raise UnsafeSpecificationUploadError("PDF input must be supplied as bytes")
        selected = (media_type or inferred).strip().casefold()
        if selected not in {"text/plain", "text/markdown", "application/json"}:
            raise UnsafeSpecificationUploadError(
                "Text specifications must be plain text, Markdown, or JSON"
            )
        if suffix in self.MEDIA_BY_SUFFIX and selected != inferred:
            raise UnsafeSpecificationUploadError(
                "Specification media type does not match its filename"
            )
        content = self._validate_text(str(content))
        raw = content.encode("utf-8")
        if len(raw) > self.MAX_UPLOAD_BYTES:
            raise UnsafeSpecificationUploadError("Specification exceeds the 10 MB limit")
        metadata: dict[str, Any] = {"encoding": "utf-8"}
        if selected == "application/json":
            document = self._json_without_duplicate_keys(content)
            if not isinstance(document, (dict, list)):
                raise UnsafeSpecificationUploadError(
                    "JSON specification root must be an object or array"
                )
            metadata["json_root_type"] = (
                "object" if isinstance(document, dict) else "array"
            )
        return _PreparedSpecification(
            source_kind, name, selected, raw, content, metadata
        )

    def _prepare_upload(
        self,
        raw: bytes,
        *,
        source_name: str,
        media_type: str | None,
    ) -> _PreparedSpecification:
        if not isinstance(raw, bytes):
            raise TypeError("Specification upload must be bytes")
        if not raw or len(raw) > self.MAX_UPLOAD_BYTES:
            raise UnsafeSpecificationUploadError(
                "Uploaded specification must be between 1 byte and 10 MB"
            )
        name = self._source_name(source_name)
        suffix = Path(name).suffix.casefold()
        inferred = self.MEDIA_BY_SUFFIX.get(suffix)
        if inferred is None:
            raise UnsafeSpecificationUploadError(
                "Unsupported specification type; use text, Markdown, JSON, or PDF"
            )
        selected = (media_type or inferred).split(";", 1)[0].strip().casefold()
        if selected != inferred:
            raise UnsafeSpecificationUploadError(
                "Specification media type does not match its filename"
            )
        if selected == "application/pdf":
            return self._prepare_pdf(raw, name)
        if raw.startswith(b"%PDF"):
            raise UnsafeSpecificationUploadError(
                "PDF bytes must use a PDF filename and media type"
            )
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise UnsafeSpecificationUploadError(
                "Text, Markdown, and JSON uploads must be valid UTF-8"
            ) from exc
        prepared = self._prepare_text(
            content,
            source_name=name,
            media_type=selected,
            source_kind=SpecificationSourceKind.UPLOAD,
        )
        return _PreparedSpecification(
            prepared.source_kind,
            prepared.source_name,
            prepared.media_type,
            raw,
            prepared.content,
            prepared.metadata,
        )

    def _prepare_pdf(self, raw: bytes, source_name: str) -> _PreparedSpecification:
        if not raw.startswith(b"%PDF-"):
            raise UnsafeSpecificationUploadError("PDF signature is missing")
        lowered = raw.lower()
        if any(marker in lowered for marker in self.PDF_ACTIVE_MARKERS):
            raise UnsafeSpecificationUploadError(
                "Active or embedded PDF content is not accepted"
            )
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise UnsafeSpecificationUploadError(
                "PDF support requires the optional pypdf dependency"
            ) from exc
        try:
            reader = PdfReader(io.BytesIO(raw), strict=True)
            if reader.is_encrypted:
                raise UnsafeSpecificationUploadError(
                    "Encrypted PDF specifications are not accepted"
                )
            if not 1 <= len(reader.pages) <= self.MAX_PDF_PAGES:
                raise UnsafeSpecificationUploadError(
                    "PDF page count is outside the supported range"
                )
            extracted_pages: list[str] = []
            extracted_bytes = 0
            for page in reader.pages:
                page_content = page.extract_text() or ""
                extracted_bytes += len(page_content.encode("utf-8"))
                if extracted_bytes > self.MAX_UPLOAD_BYTES:
                    raise UnsafeSpecificationUploadError(
                        "Extracted PDF specification exceeds the 10 MB limit"
                    )
                extracted_pages.append(page_content)
            content = "\n\n".join(extracted_pages)
        except UnsafeSpecificationUploadError:
            raise
        except Exception as exc:  # Treat the parser failure as untrusted input data.
            raise UnsafeSpecificationUploadError(
                f"Could not safely read PDF specification: {type(exc).__name__}"
            ) from exc
        content = self._validate_text(content)
        if len(content.encode("utf-8")) > self.MAX_UPLOAD_BYTES:
            raise UnsafeSpecificationUploadError(
                "Extracted PDF specification exceeds the 10 MB limit"
            )
        return _PreparedSpecification(
            SpecificationSourceKind.UPLOAD,
            source_name,
            "application/pdf",
            raw,
            content,
            {"extractor": "pypdf", "page_count": len(reader.pages)},
        )

    def _source_replay(
        self, command_id: str, request_digest: str
    ) -> AutonomousSpecificationSource | None:
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_specification_commands WHERE command_id=?",
            (command_id,),
        ).fetchone()
        if not row:
            return None
        if row["request_digest"] != request_digest:
            raise SpecificationCommandConflictError(
                f"Specification command {command_id!r} is already bound"
            )
        return self.get_source(int(row["result_source_id"]))

    def get_source(self, source_id: int) -> AutonomousSpecificationSource:
        row = self.storage.db.execute(
            """SELECT s.*,h.source_id AS current_source_id,
                      x.replacement_source_id
                 FROM autonomous_mission_specification_sources s
                 LEFT JOIN autonomous_mission_specification_heads h
                   ON h.mission_id=s.mission_id
                 LEFT JOIN autonomous_specification_supersessions x
                   ON x.previous_source_id=s.id
                WHERE s.id=?""",
            (source_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown Autonomous Mission specification source: {source_id}")
        result = AutonomousSpecificationSource(
            id=int(row["id"]),
            identity=str(row["identity"]),
            mission_id=int(row["mission_id"]),
            version=int(row["version"]),
            source_kind=SpecificationSourceKind(row["source_kind"]),
            source_name=str(row["source_name"]),
            media_type=str(row["media_type"]),
            provenance=str(row["provenance"]),
            actor=str(row["actor"]),
            content=str(row["content_text"]),
            content_digest=str(row["content_digest"]),
            raw_digest=str(row["raw_digest"]),
            byte_count=int(row["byte_count"]),
            metadata=json.loads(row["metadata_json"]),
            source_digest=str(row["source_digest"]),
            intake_source_id=(
                int(row["intake_source_id"])
                if row["intake_source_id"] is not None
                else None
            ),
            command_id=str(row["command_id"]),
            request_digest=str(row["request_digest"]),
            created_at=str(row["created_at"]),
            current=int(row["current_source_id"] or -1) == int(row["id"]),
            superseded_by_source_id=(
                int(row["replacement_source_id"])
                if row["replacement_source_id"] is not None
                else None
            ),
        )
        if self._digest(result.binding()) != result.source_digest:
            raise RuntimeError("Specification source digest no longer matches its binding")
        if hashlib.sha256(result.content.encode("utf-8")).hexdigest() != result.content_digest:
            raise RuntimeError("Specification source content digest is corrupt")
        return result

    def current_source(self, mission_id: int) -> AutonomousSpecificationSource:
        row = self.storage.db.execute(
            """SELECT source_id FROM autonomous_mission_specification_heads
                WHERE mission_id=?""",
            (mission_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Autonomous Mission {mission_id} has no specification source")
        return self.get_source(int(row["source_id"]))

    def sources(self, mission_id: int) -> tuple[AutonomousSpecificationSource, ...]:
        return tuple(
            self.get_source(int(row["id"]))
            for row in self.storage.db.execute(
                """SELECT id FROM autonomous_mission_specification_sources
                    WHERE mission_id=? ORDER BY version""",
                (mission_id,),
            )
        )

    def invalidated_revisions(self, mission_id: int) -> tuple[dict[str, Any], ...]:
        return tuple(
            dict(row)
            for row in self.storage.db.execute(
                """SELECT * FROM autonomous_backlog_revision_invalidations
                    WHERE mission_id=? ORDER BY id""",
                (mission_id,),
            )
        )

    def create_from_text(
        self,
        *,
        name: str,
        mission_owner: str,
        specification: str,
        actor: str,
        command_id: str,
        configuration: AutonomousMissionConfiguration | None = None,
        mission_key: str | None = None,
        description: str = "",
        source_name: str = "specification.txt",
        media_type: str | None = None,
        provenance: str = "human-paste",
    ) -> AutonomousMissionIntakeResult:
        prepared = self._prepare_text(
            specification,
            source_name=source_name,
            media_type=media_type,
            source_kind=SpecificationSourceKind.TEXT,
        )
        return self._create_mission(
            name=name,
            mission_owner=mission_owner,
            actor=actor,
            command_id=command_id,
            configuration=configuration,
            mission_key=mission_key,
            description=description,
            provenance=provenance,
            prepared=prepared,
        )

    def create_from_upload(
        self,
        *,
        name: str,
        mission_owner: str,
        raw: bytes,
        source_name: str,
        actor: str,
        command_id: str,
        configuration: AutonomousMissionConfiguration | None = None,
        mission_key: str | None = None,
        description: str = "",
        media_type: str | None = None,
        provenance: str = "human-upload",
    ) -> AutonomousMissionIntakeResult:
        prepared = self._prepare_upload(
            raw, source_name=source_name, media_type=media_type
        )
        return self._create_mission(
            name=name,
            mission_owner=mission_owner,
            actor=actor,
            command_id=command_id,
            configuration=configuration,
            mission_key=mission_key,
            description=description,
            provenance=provenance,
            prepared=prepared,
        )

    def _create_mission(
        self,
        *,
        name: str,
        mission_owner: str,
        actor: str,
        command_id: str,
        configuration: AutonomousMissionConfiguration | None,
        mission_key: str | None,
        description: str,
        provenance: str,
        prepared: _PreparedSpecification,
    ) -> AutonomousMissionIntakeResult:
        name = self._required(name, "Mission name")
        mission_owner = self._required(mission_owner, "Mission owner")
        actor = self._required(actor, "Mission actor")
        command_id = self._required(command_id, "Command id")
        provenance = self._required(provenance, "Source provenance")
        if actor != mission_owner:
            raise PermissionError("Initial specification requires the mission owner")
        creation_request = {
            "type": "create_autonomous_mission_intake",
            "name": name,
            "mission_owner": mission_owner,
            "mission_key": mission_key,
            "description": description.strip(),
            "actor": actor,
            "provenance": provenance,
            "source_name": prepared.source_name,
            "media_type": prepared.media_type,
            "raw_digest": hashlib.sha256(prepared.raw).hexdigest(),
            "configuration": (configuration or AutonomousMissionConfiguration()).to_dict(),
        }
        creation_digest = self._digest(creation_request)
        source_command_id = f"{command_id}:source"
        existing_source = self.storage.db.execute(
            """SELECT result_source_id FROM autonomous_specification_commands
                WHERE command_id=?""",
            (source_command_id,),
        ).fetchone()
        if existing_source:
            source = self.get_source(int(existing_source["result_source_id"]))
            if source.metadata.get("creation_request_digest") != creation_digest:
                raise SpecificationCommandConflictError(
                    f"Mission intake command {command_id!r} is already bound"
                )
            return AutonomousMissionIntakeResult(
                self.missions.get(source.mission_id), source
            )

        mission_command_id = f"{command_id}:mission"
        existing_mission = self.storage.db.execute(
            """SELECT mission_id FROM autonomous_mission_commands
                WHERE command_id=?""",
            (mission_command_id,),
        ).fetchone()
        if existing_mission:
            mission = self.missions.get(int(existing_mission["mission_id"]))
            if (
                mission.name != name
                or mission.mission_owner != mission_owner
                or mission.specification_metadata.get(
                    "intake_creation_request_digest"
                )
                != creation_digest
                or mission.initial_specification_digest
                != hashlib.sha256(prepared.content.encode("utf-8")).hexdigest()
            ):
                raise SpecificationCommandConflictError(
                    f"Mission intake command {command_id!r} is already bound"
                )
            intake_source = self.storage.db.execute(
                """SELECT id FROM mission_sources WHERE intake_id=?
                    ORDER BY id LIMIT 1""",
                (mission.intake_id,),
            ).fetchone()
        else:
            project_id = self.storage.create_project(
                name,
                description.strip()
                or "Autonomous Mission intake and specification container",
            )
            intake_id = self.intakes.create(
                project_id=project_id,
                mission_owner=mission_owner,
                intent=f"Plan and deliver {name} from the authoritative specification",
                objectives=["Derive an approved implementation backlog from the source"],
                success_measures=["All approved acceptance criteria are validated"],
                constraints=["No implementation begins before exact backlog approval"],
                sources=(
                    MissionSource(
                        key="autonomous-specification-v1",
                        subject="autonomous-mission-specification",
                        authority="authoritative",
                        version="1",
                        provenance=provenance,
                        content=prepared.content,
                    ),
                ),
            )
            intake_source = self.storage.db.execute(
                """SELECT id FROM mission_sources WHERE intake_id=?
                    AND source_key='autonomous-specification-v1'""",
                (intake_id,),
            ).fetchone()
            mission = self.missions.create(
                name=name,
                mission_owner=mission_owner,
                actor=actor,
                command_id=mission_command_id,
                configuration=configuration,
                mission_key=mission_key,
                description=description,
                initial_specification=prepared.content,
                specification_metadata={
                    "source_name": prepared.source_name,
                    "media_type": prepared.media_type,
                    "raw_digest": hashlib.sha256(prepared.raw).hexdigest(),
                    "provenance": provenance,
                    "intake_creation_request_digest": creation_digest,
                },
                intake_id=intake_id,
                project_id=project_id,
            )
        metadata = {
            **prepared.metadata,
            "creation_request_digest": creation_digest,
        }
        source = self._attach(
            mission.id,
            prepared=prepared,
            provenance=provenance,
            actor=actor,
            command_id=source_command_id,
            reason="Create authoritative Autonomous Mission specification",
            expected_mission_version=mission.version,
            expected_source_version=0,
            intake_source_id=(
                int(intake_source["id"]) if intake_source is not None else None
            ),
            metadata=metadata,
        )
        return AutonomousMissionIntakeResult(self.missions.get(mission.id), source)

    def update_from_text(
        self,
        mission_id: int,
        *,
        specification: str,
        actor: str,
        command_id: str,
        reason: str,
        expected_mission_version: int,
        expected_source_version: int,
        source_name: str = "specification.txt",
        media_type: str | None = None,
        provenance: str = "human-edit",
    ) -> AutonomousSpecificationSource:
        prepared = self._prepare_text(
            specification,
            source_name=source_name,
            media_type=media_type,
            source_kind=SpecificationSourceKind.TEXT,
        )
        return self._attach(
            mission_id,
            prepared=prepared,
            provenance=provenance,
            actor=actor,
            command_id=command_id,
            reason=reason,
            expected_mission_version=expected_mission_version,
            expected_source_version=expected_source_version,
        )

    def update_from_upload(
        self,
        mission_id: int,
        *,
        raw: bytes,
        source_name: str,
        actor: str,
        command_id: str,
        reason: str,
        expected_mission_version: int,
        expected_source_version: int,
        media_type: str | None = None,
        provenance: str = "human-upload",
    ) -> AutonomousSpecificationSource:
        prepared = self._prepare_upload(
            raw, source_name=source_name, media_type=media_type
        )
        return self._attach(
            mission_id,
            prepared=prepared,
            provenance=provenance,
            actor=actor,
            command_id=command_id,
            reason=reason,
            expected_mission_version=expected_mission_version,
            expected_source_version=expected_source_version,
        )

    def _record_source_command(
        self,
        *,
        mission_id: int,
        command_id: str,
        command_type: str,
        actor: str,
        request_digest: str,
        source_id: int,
        created_at: str,
    ) -> None:
        self.storage.db.execute(
            """INSERT INTO autonomous_specification_commands(
                   identity,mission_id,command_id,command_type,actor,
                   request_digest,result_source_id,created_at
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                self.storage._identity("autonomous-specification-command"),
                mission_id,
                command_id,
                command_type,
                actor,
                request_digest,
                source_id,
                created_at,
            ),
        )

    def _advance_mission_for_source(
        self,
        *,
        row: Any,
        command_id: str,
        actor: str,
        reason: str,
        clear_active_revision: bool,
    ) -> int:
        mission_id = int(row["id"])
        actual_version = int(row["version"])
        source_phase = MissionPhase(row["phase"])
        target_phase = {
            MissionPhase.BACKLOG_GENERATION: MissionPhase.SPECIFICATION_ANALYSIS,
            MissionPhase.WAITING_FOR_BACKLOG_APPROVAL: MissionPhase.BACKLOG_GENERATION,
        }.get(source_phase, source_phase)
        if (
            target_phase is not source_phase
            and MissionDisposition(row["disposition"]) is not MissionDisposition.RUNNING
        ):
            raise PermissionError(
                "Specification update cannot reset planning while mission is fenced"
            )
        result_version = actual_version + 1
        active_revision = (
            None if clear_active_revision else row["active_backlog_revision_id"]
        )
        state_command_id = f"{command_id}:mission-state"
        self.missions._insert_state_version(
            mission_id=mission_id,
            version=result_version,
            phase=target_phase,
            disposition=MissionDisposition(row["disposition"]),
            configuration_json=str(row["configuration_json"]),
            configuration_digest=str(row["configuration_digest"]),
            active_backlog_revision_id=(
                int(active_revision) if active_revision is not None else None
            ),
            active_execution_epoch_id=None,
            current_checkpoint_id=None,
            actor=actor,
            command_id=state_command_id,
            reason=reason,
        )
        updated = self.storage.db.execute(
            """UPDATE autonomous_missions
                  SET phase=?,active_backlog_revision_id=?,
                      active_execution_epoch_id=NULL,current_checkpoint_id=NULL,
                      version=?,updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND version=?""",
            (
                target_phase.value,
                active_revision,
                result_version,
                mission_id,
                actual_version,
            ),
        )
        if updated.rowcount != 1:
            raise MissionVersionConflictError(
                mission_id, actual_version, actual_version + 1
            )
        request_digest = self._digest(
            {
                "type": "specification_source_state",
                "mission_id": mission_id,
                "source_phase": source_phase.value,
                "target_phase": target_phase.value,
                "clear_active_revision": clear_active_revision,
                "actor": actor,
                "reason": reason,
            }
        )
        self.missions._insert_command(
            mission_id=mission_id,
            command_id=state_command_id,
            command_type="specification_source_state",
            actor=actor,
            expected_version=actual_version,
            request_digest=request_digest,
            result_version=result_version,
        )
        return result_version

    def _attach(
        self,
        mission_id: int,
        *,
        prepared: _PreparedSpecification,
        provenance: str,
        actor: str,
        command_id: str,
        reason: str,
        expected_mission_version: int,
        expected_source_version: int,
        intake_source_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AutonomousSpecificationSource:
        provenance = self._required(provenance, "Source provenance")
        actor = self._required(actor, "Specification actor")
        command_id = self._required(command_id, "Command id")
        reason = self._required(reason, "Specification change reason")
        raw_digest = hashlib.sha256(prepared.raw).hexdigest()
        content_digest = hashlib.sha256(prepared.content.encode("utf-8")).hexdigest()
        combined_metadata = {**prepared.metadata, **dict(metadata or {})}
        request = {
            "type": "attach_specification_source",
            "mission_id": mission_id,
            "source_kind": prepared.source_kind.value,
            "source_name": prepared.source_name,
            "media_type": prepared.media_type,
            "provenance": provenance,
            "actor": actor,
            "reason": reason,
            "raw_digest": raw_digest,
            "content_digest": content_digest,
            "byte_count": len(prepared.raw),
            "metadata": combined_metadata,
            "expected_mission_version": expected_mission_version,
            "expected_source_version": expected_source_version,
            "intake_source_id": intake_source_id,
        }
        request_digest = self._digest(request)
        replay = self._source_replay(command_id, request_digest)
        if replay:
            return replay
        mission = self.missions.get(mission_id)
        if actor != mission.mission_owner:
            raise PermissionError("Only the mission owner may change the specification")
        if mission.phase not in self.PREAPPROVAL_PHASES:
            raise PermissionError("Specification changes are pre-approval only")
        if mission.version != expected_mission_version:
            raise MissionVersionConflictError(
                mission_id, expected_mission_version, mission.version
            )
        head = self.storage.db.execute(
            """SELECT * FROM autonomous_mission_specification_heads
                WHERE mission_id=?""",
            (mission_id,),
        ).fetchone()
        actual_source_version = int(head["source_version"]) if head else 0
        if actual_source_version != expected_source_version:
            raise ValueError(
                "Specification source version conflict: "
                f"expected {expected_source_version}, current {actual_source_version}"
            )
        current = self.get_source(int(head["source_id"])) if head else None
        created_at = self._timestamp()
        if (
            current
            and current.raw_digest == raw_digest
            and current.content_digest == content_digest
            and current.media_type == prepared.media_type
        ):
            with self.storage.db:
                self.storage._begin_immediate()
                replay = self._source_replay(command_id, request_digest)
                if replay:
                    return replay
                row = self.storage.db.execute(
                    "SELECT version,phase FROM autonomous_missions WHERE id=?",
                    (mission_id,),
                ).fetchone()
                if not row:
                    raise KeyError(f"Unknown Autonomous Mission: {mission_id}")
                if int(row["version"]) != expected_mission_version:
                    raise MissionVersionConflictError(
                        mission_id, expected_mission_version, int(row["version"])
                    )
                if MissionPhase(row["phase"]) not in self.PREAPPROVAL_PHASES:
                    raise PermissionError("Specification changes are pre-approval only")
                locked_head = self.storage.db.execute(
                    """SELECT source_id,source_version
                         FROM autonomous_mission_specification_heads
                        WHERE mission_id=?""",
                    (mission_id,),
                ).fetchone()
                if (
                    not locked_head
                    or int(locked_head["source_version"]) != expected_source_version
                    or int(locked_head["source_id"]) != current.id
                ):
                    raise ValueError("Specification source changed before commit")
                self._record_source_command(
                    mission_id=mission_id,
                    command_id=command_id,
                    command_type="UPDATE_SOURCE",
                    actor=actor,
                    request_digest=request_digest,
                    source_id=current.id,
                    created_at=created_at,
                )
            return current

        new_version = actual_source_version + 1
        binding = {
            "mission_id": mission_id,
            "version": new_version,
            "source_kind": prepared.source_kind.value,
            "source_name": prepared.source_name,
            "media_type": prepared.media_type,
            "provenance": provenance,
            "actor": actor,
            "content_digest": content_digest,
            "raw_digest": raw_digest,
            "byte_count": len(prepared.raw),
            "metadata": combined_metadata,
            "intake_source_id": intake_source_id,
        }
        source_digest = self._digest(binding)
        with self.storage.db:
            self.storage._begin_immediate()
            replay = self._source_replay(command_id, request_digest)
            if replay:
                return replay
            row = self.storage.db.execute(
                "SELECT * FROM autonomous_missions WHERE id=?", (mission_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown Autonomous Mission: {mission_id}")
            if int(row["version"]) != expected_mission_version:
                raise MissionVersionConflictError(
                    mission_id, expected_mission_version, int(row["version"])
                )
            if MissionPhase(row["phase"]) not in self.PREAPPROVAL_PHASES:
                raise PermissionError("Specification changes are pre-approval only")
            locked_head = self.storage.db.execute(
                """SELECT * FROM autonomous_mission_specification_heads
                    WHERE mission_id=?""",
                (mission_id,),
            ).fetchone()
            locked_version = int(locked_head["source_version"]) if locked_head else 0
            if locked_version != expected_source_version:
                raise ValueError("Specification source changed before commit")
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_mission_specification_sources(
                       identity,mission_id,version,source_kind,source_name,
                       media_type,provenance,actor,content_text,content_digest,
                       raw_digest,byte_count,metadata_json,source_digest,
                       intake_source_id,command_id,request_digest,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-specification-source"),
                    mission_id,
                    new_version,
                    prepared.source_kind.value,
                    prepared.source_name,
                    prepared.media_type,
                    provenance,
                    actor,
                    prepared.content,
                    content_digest,
                    raw_digest,
                    len(prepared.raw),
                    self._json(combined_metadata),
                    source_digest,
                    intake_source_id,
                    command_id,
                    request_digest,
                    created_at,
                ),
            )
            source_id = int(cursor.lastrowid)
            invalidated_revision_ids: list[int] = []
            if locked_head:
                previous_source_id = int(locked_head["source_id"])
                self.storage.db.execute(
                    """INSERT INTO autonomous_specification_supersessions(
                           identity,mission_id,previous_source_id,
                           replacement_source_id,actor,command_id,reason,created_at
                       ) VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        self.storage._identity("autonomous-specification-supersession"),
                        mission_id,
                        previous_source_id,
                        source_id,
                        actor,
                        f"{command_id}:supersession",
                        reason,
                        created_at,
                    ),
                )
                stale_revisions = self.storage.db.execute(
                    """SELECT r.id,r.source_sha256
                         FROM autonomous_backlog_revisions r
                         LEFT JOIN autonomous_backlog_revision_invalidations i
                           ON i.revision_id=r.id
                        WHERE r.mission_id=? AND i.id IS NULL
                          AND r.source_sha256<>?
                        ORDER BY r.revision_number""",
                    (mission_id, raw_digest),
                ).fetchall()
                for revision in stale_revisions:
                    revision_id = int(revision["id"])
                    invalidated_revision_ids.append(revision_id)
                    self.storage.db.execute(
                        """INSERT INTO autonomous_backlog_revision_invalidations(
                               identity,mission_id,revision_id,previous_source_id,
                               replacement_source_id,revision_source_digest,reason,
                               actor,command_id,created_at
                           ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (
                            self.storage._identity("autonomous-revision-invalidation"),
                            mission_id,
                            revision_id,
                            previous_source_id,
                            source_id,
                            revision["source_sha256"],
                            "Specification source changed before approval",
                            actor,
                            f"{command_id}:invalidate:{revision_id}",
                            created_at,
                        ),
                    )
                self.storage.db.execute(
                    """UPDATE autonomous_mission_specification_heads
                          SET source_id=?,source_version=?,source_digest=?,updated_at=?
                        WHERE mission_id=? AND source_id=?""",
                    (
                        source_id,
                        new_version,
                        source_digest,
                        created_at,
                        mission_id,
                        previous_source_id,
                    ),
                )
            else:
                self.storage.db.execute(
                    """INSERT INTO autonomous_mission_specification_heads(
                           mission_id,source_id,source_version,source_digest,updated_at
                       ) VALUES(?,?,?,?,?)""",
                    (mission_id, source_id, new_version, source_digest, created_at),
                )
            clear_active = (
                row["active_backlog_revision_id"] is not None
                and int(row["active_backlog_revision_id"])
                in set(invalidated_revision_ids)
            )
            result_version = self._advance_mission_for_source(
                row=row,
                command_id=command_id,
                actor=actor,
                reason=reason,
                clear_active_revision=clear_active,
            )
            self._record_source_command(
                mission_id=mission_id,
                command_id=command_id,
                command_type=("CREATE_SOURCE" if new_version == 1 else "UPDATE_SOURCE"),
                actor=actor,
                request_digest=request_digest,
                source_id=source_id,
                created_at=created_at,
            )
            self.storage._event(
                "autonomous_mission.specification_created"
                if new_version == 1
                else "autonomous_mission.specification_updated",
                "autonomous_mission",
                mission_id,
                {
                    "source_id": source_id,
                    "source_version": new_version,
                    "source_digest": source_digest,
                    "raw_digest": raw_digest,
                    "actor": actor,
                    "command_id": command_id,
                    "reason": reason,
                    "invalidated_revision_ids": invalidated_revision_ids,
                    "mission_version": result_version,
                },
            )
        return self.get_source(source_id)
