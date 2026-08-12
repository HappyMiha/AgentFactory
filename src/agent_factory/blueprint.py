"""Versioned Factory Blueprints, exact human approval, and amendments."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from .storage import SQLiteStorage


REQUIRED_SECTIONS = (
    "modules", "workforce", "tools", "context", "verification",
    "budgets", "policies", "recovery",
)
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True)
class BlueprintSections:
    modules: dict[str, Any]
    workforce: dict[str, Any]
    tools: dict[str, Any]
    context: dict[str, Any]
    verification: dict[str, Any]
    budgets: dict[str, Any]
    policies: dict[str, Any]
    recovery: dict[str, Any]

    def __post_init__(self):
        for name in REQUIRED_SECTIONS:
            value = getattr(self, name)
            if not isinstance(value, dict) or not value:
                raise ValueError(f"Blueprint section {name} must be a non-empty object")
        if {"composition_id", "composition_digest"} & set(self.workforce):
            raise ValueError("Workforce composition identity is derived by the Control Plane")


@dataclass(frozen=True)
class BlueprintAssumption:
    key: str
    statement: str

    def __post_init__(self):
        if not IDENTIFIER.fullmatch(self.key) or not self.statement.strip():
            raise ValueError("Blueprint assumption requires a stable key and statement")


@dataclass(frozen=True)
class RejectedAlternative:
    key: str
    description: str
    rejection_reason: str

    def __post_init__(self):
        if not IDENTIFIER.fullmatch(self.key) or not all(value.strip() for value in (
            self.description, self.rejection_reason
        )):
            raise ValueError("Rejected alternative requires a stable key, description, and reason")


@dataclass(frozen=True)
class BlueprintDecision:
    key: str
    section: str
    rationale: str
    source_keys: tuple[str, ...]
    risk_refs: tuple[str, ...] = ()
    assumption_refs: tuple[str, ...] = ()
    rejected_alternative_refs: tuple[str, ...] = ()

    def __post_init__(self):
        if not IDENTIFIER.fullmatch(self.key) or self.section not in REQUIRED_SECTIONS:
            raise ValueError("Blueprint decision key or section is invalid")
        if not self.rationale.strip() or not self.source_keys:
            raise ValueError("Blueprint decisions require rationale and mission-source evidence")
        for values in (
            self.source_keys, self.risk_refs, self.assumption_refs,
            self.rejected_alternative_refs,
        ):
            if len(values) != len(set(values)):
                raise ValueError("Blueprint decision trace references must be unique")


@dataclass(frozen=True)
class AmendmentImpact:
    affected_sections: tuple[str, ...]
    execution_effect: str
    migration_plan: str
    risk_changes: str

    def __post_init__(self):
        if not self.affected_sections or len(self.affected_sections) != len(set(self.affected_sections)):
            raise ValueError("Amendment impact requires unique affected sections")
        if any(section not in REQUIRED_SECTIONS for section in self.affected_sections):
            raise ValueError("Amendment impact references an unknown section")
        if not all(value.strip() for value in (
            self.execution_effect, self.migration_plan, self.risk_changes
        )):
            raise ValueError("Amendment execution, migration, and risk impacts are required")


@dataclass(frozen=True)
class FactoryBlueprint:
    id: int
    blueprint_key: str
    version: int
    intake_id: int
    readiness_assessment_id: int
    composition_id: int
    parent_blueprint_id: int | None
    sections: dict[str, Any]
    trace: dict[str, Any]
    amendment_impact: dict[str, Any] | None
    blueprint_digest: str
    approval: dict[str, Any] | None
    execution_authorized: bool


class BlueprintService:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _unique_keys(items: tuple[Any, ...], label: str) -> None:
        keys = [item.key for item in items]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{label} keys must be unique")

    def _dependencies(self, intake_id: int, composition_id: int):
        intake = self.storage.db.execute(
            "SELECT * FROM mission_intakes WHERE id=?", (intake_id,)
        ).fetchone()
        if not intake:
            raise KeyError(f"Unknown mission intake: {intake_id}")
        readiness = self.storage.db.execute(
            """SELECT * FROM mission_readiness_assessments
               WHERE intake_id=? ORDER BY sequence DESC LIMIT 1""",
            (intake_id,),
        ).fetchone()
        if not readiness or readiness["verdict"] != "READY_FOR_BLUEPRINT":
            raise PermissionError("Mission is not ready for Blueprint generation")
        composition = self.storage.db.execute(
            "SELECT * FROM workforce_compositions WHERE id=?", (composition_id,)
        ).fetchone()
        if not composition or composition["status"] != "ready":
            raise PermissionError("Blueprint requires a ready workforce composition")
        if composition["mission_key"] != f"intake:{intake_id}":
            raise PermissionError("Workforce composition is not bound to this mission intake")
        return intake, readiness, composition

    def _trace(
        self,
        *,
        intake_id: int,
        decisions: tuple[BlueprintDecision, ...],
        assumptions: tuple[BlueprintAssumption, ...],
        rejected_alternatives: tuple[RejectedAlternative, ...],
    ) -> dict[str, Any]:
        if not decisions or not assumptions or not rejected_alternatives:
            raise ValueError("Blueprint decisions, assumptions, and rejected alternatives are required")
        self._unique_keys(decisions, "Decision")
        self._unique_keys(assumptions, "Assumption")
        self._unique_keys(rejected_alternatives, "Rejected alternative")
        sources = [dict(row) for row in self.storage.db.execute(
            """SELECT source_key,subject,authority,version,provenance,content_digest,
                      conflict_status
                 FROM mission_sources WHERE intake_id=? ORDER BY source_key""",
            (intake_id,),
        )]
        source_keys = {str(source["source_key"]) for source in sources}
        authoritative = {
            str(source["source_key"]) for source in sources
            if source["authority"] == "authoritative" and source["conflict_status"] != "superseded"
        }
        intake = self.storage.db.execute(
            "SELECT normalized_json FROM mission_intakes WHERE id=?", (intake_id,)
        ).fetchone()
        normalized = json.loads(intake["normalized_json"])
        risks = set(normalized["high_risk_findings"])
        assumption_keys = {item.key for item in assumptions}
        alternative_keys = {item.key for item in rejected_alternatives}
        sections = {decision.section for decision in decisions}
        cited_sources: set[str] = set()
        cited_risks: set[str] = set()
        cited_assumptions: set[str] = set()
        cited_alternatives: set[str] = set()
        for decision in decisions:
            if not set(decision.source_keys) <= source_keys:
                raise ValueError(f"Decision {decision.key} references an unknown mission source")
            if not set(decision.risk_refs) <= risks:
                raise ValueError(f"Decision {decision.key} references an unknown mission risk")
            if not set(decision.assumption_refs) <= assumption_keys:
                raise ValueError(f"Decision {decision.key} references an unknown assumption")
            if not set(decision.rejected_alternative_refs) <= alternative_keys:
                raise ValueError(f"Decision {decision.key} references an unknown rejected alternative")
            cited_sources.update(decision.source_keys)
            cited_risks.update(decision.risk_refs)
            cited_assumptions.update(decision.assumption_refs)
            cited_alternatives.update(decision.rejected_alternative_refs)
        missing_sections = set(REQUIRED_SECTIONS) - sections
        if missing_sections:
            raise ValueError(f"Blueprint decisions do not cover sections: {sorted(missing_sections)}")
        if not authoritative <= cited_sources:
            raise ValueError("Blueprint trace does not cover every authoritative mission source")
        if risks != cited_risks:
            raise ValueError("Blueprint trace does not cover every mission risk")
        if assumption_keys != cited_assumptions:
            raise ValueError("Blueprint trace does not cover every assumption")
        if alternative_keys != cited_alternatives:
            raise ValueError("Blueprint trace does not cover every rejected alternative")
        return {
            "schema_version": 1,
            "mission_sources": sources,
            "mission_risks": sorted(risks),
            "assumptions": [asdict(item) for item in sorted(assumptions, key=lambda item: item.key)],
            "rejected_alternatives": [
                asdict(item) for item in sorted(rejected_alternatives, key=lambda item: item.key)
            ],
            "decisions": [asdict(item) for item in sorted(decisions, key=lambda item: item.key)],
            "coverage": {
                "sections": sorted(sections), "source_keys": sorted(cited_sources),
                "risks": sorted(cited_risks), "assumptions": sorted(cited_assumptions),
                "rejected_alternatives": sorted(cited_alternatives),
            },
        }

    def create(
        self,
        *,
        blueprint_key: str,
        intake_id: int,
        composition_id: int,
        sections: BlueprintSections,
        decisions: tuple[BlueprintDecision, ...],
        assumptions: tuple[BlueprintAssumption, ...],
        rejected_alternatives: tuple[RejectedAlternative, ...],
        created_by: str,
    ) -> FactoryBlueprint:
        if not IDENTIFIER.fullmatch(blueprint_key) or not created_by.strip():
            raise ValueError("Blueprint key and creator are required")
        with self.storage.db:
            if self.storage.db.execute(
                "SELECT 1 FROM factory_blueprints WHERE blueprint_key=?", (blueprint_key,)
            ).fetchone():
                raise ValueError("Initial Blueprint already exists; create an amendment")
            return self._create_version(
                blueprint_key=blueprint_key, version=1, intake_id=intake_id,
                composition_id=composition_id, parent_blueprint_id=None, sections=sections,
                decisions=decisions, assumptions=assumptions,
                rejected_alternatives=rejected_alternatives, amendment_impact=None,
                created_by=created_by,
            )

    def amend(
        self,
        parent_blueprint_id: int,
        *,
        composition_id: int,
        sections: BlueprintSections,
        decisions: tuple[BlueprintDecision, ...],
        assumptions: tuple[BlueprintAssumption, ...],
        rejected_alternatives: tuple[RejectedAlternative, ...],
        impact: AmendmentImpact,
        actor: str,
        actor_role: str,
    ) -> FactoryBlueprint:
        with self.storage.db:
            return self.amend_in_transaction(
                parent_blueprint_id, composition_id=composition_id, sections=sections,
                decisions=decisions, assumptions=assumptions,
                rejected_alternatives=rejected_alternatives, impact=impact,
                actor=actor, actor_role=actor_role,
            )

    def amend_in_transaction(
        self,
        parent_blueprint_id: int,
        *,
        composition_id: int,
        sections: BlueprintSections,
        decisions: tuple[BlueprintDecision, ...],
        assumptions: tuple[BlueprintAssumption, ...],
        rejected_alternatives: tuple[RejectedAlternative, ...],
        impact: AmendmentImpact,
        actor: str,
        actor_role: str,
    ) -> FactoryBlueprint:
        """Create an amendment inside a transaction owned by the caller."""

        parent = self.storage.db.execute(
            "SELECT * FROM factory_blueprints WHERE id=?", (parent_blueprint_id,)
        ).fetchone()
        if not parent:
            raise KeyError(f"Unknown Factory Blueprint: {parent_blueprint_id}")
        latest = self.storage.db.execute(
            "SELECT MAX(version) FROM factory_blueprints WHERE blueprint_key=?",
            (parent["blueprint_key"],),
        ).fetchone()[0]
        if int(parent["version"]) != int(latest):
            raise ValueError("Amendment must target the latest Blueprint version")
        owner = self.storage.db.execute(
            "SELECT mission_owner FROM mission_intakes WHERE id=?", (parent["intake_id"],)
        ).fetchone()[0]
        if actor_role != "mission_owner" or actor != owner:
            raise PermissionError("Blueprint amendments are reserved for the human mission owner")
        old_sections = json.loads(parent["sections_json"])
        new_sections = asdict(sections)
        changed = {
            name for name in REQUIRED_SECTIONS
            if old_sections[name] != new_sections[name]
            and name != "workforce"
        }
        old_workforce = {
            key: value for key, value in old_sections["workforce"].items()
            if key not in {"composition_id", "composition_digest"}
        }
        if old_workforce != new_sections["workforce"] or int(parent["composition_id"]) != composition_id:
            changed.add("workforce")
        if changed != set(impact.affected_sections):
            raise ValueError("Amendment impact must exactly name every changed Blueprint section")
        return self._create_version(
            blueprint_key=str(parent["blueprint_key"]), version=int(parent["version"]) + 1,
            intake_id=int(parent["intake_id"]), composition_id=composition_id,
            parent_blueprint_id=parent_blueprint_id, sections=sections, decisions=decisions,
            assumptions=assumptions, rejected_alternatives=rejected_alternatives,
            amendment_impact=impact, created_by=actor,
        )

    def _create_version(
        self,
        *,
        blueprint_key: str,
        version: int,
        intake_id: int,
        composition_id: int,
        parent_blueprint_id: int | None,
        sections: BlueprintSections,
        decisions: tuple[BlueprintDecision, ...],
        assumptions: tuple[BlueprintAssumption, ...],
        rejected_alternatives: tuple[RejectedAlternative, ...],
        amendment_impact: AmendmentImpact | None,
        created_by: str,
    ) -> FactoryBlueprint:
        _, readiness, composition = self._dependencies(intake_id, composition_id)
        section_document = asdict(sections)
        section_document["workforce"] = {
            **section_document["workforce"],
            "composition_id": composition_id,
            "composition_digest": str(composition["composition_digest"]),
        }
        trace = self._trace(
            intake_id=intake_id, decisions=decisions, assumptions=assumptions,
            rejected_alternatives=rejected_alternatives,
        )
        impact_document = asdict(amendment_impact) if amendment_impact else None
        document = {
            "blueprint_key": blueprint_key, "version": version,
            "intake_id": intake_id, "readiness_assessment_id": int(readiness["id"]),
            "composition_id": composition_id, "parent_blueprint_id": parent_blueprint_id,
            "sections": section_document, "trace": trace,
            "amendment_impact": impact_document, "created_by": created_by,
        }
        digest = hashlib.sha256(self._json(document).encode()).hexdigest()
        cursor = self.storage.db.execute(
            """INSERT INTO factory_blueprints(
                   identity,blueprint_key,version,intake_id,readiness_assessment_id,
                   composition_id,parent_blueprint_id,sections_json,trace_json,
                   amendment_impact_json,blueprint_digest,created_by
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self.storage._identity("factory-blueprint"), blueprint_key, version,
                intake_id, readiness["id"], composition_id, parent_blueprint_id,
                self._json(section_document), self._json(trace),
                self._json(impact_document) if impact_document else None,
                digest, created_by,
            ),
        )
        blueprint_id = int(cursor.lastrowid)
        self.storage._event("blueprint.version.created", "factory_blueprint", blueprint_id, {
            "blueprint_key": blueprint_key, "version": version,
            "parent_blueprint_id": parent_blueprint_id, "blueprint_digest": digest,
        })
        return self.get(blueprint_id)

    def sign(
        self,
        blueprint_id: int,
        *,
        expected_version: int,
        expected_digest: str,
        decision: str,
        signer: str,
        signer_role: str,
        note: str,
    ) -> int:
        if decision not in {"approved", "rejected"}:
            raise ValueError("Blueprint decision must be approved or rejected")
        row = self.storage.db.execute(
            """SELECT b.*,i.mission_owner FROM factory_blueprints b
                 JOIN mission_intakes i ON i.id=b.intake_id WHERE b.id=?""",
            (blueprint_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown Factory Blueprint: {blueprint_id}")
        if signer_role != "mission_owner" or signer != row["mission_owner"]:
            raise PermissionError("Only the human mission owner may sign a Blueprint")
        latest = self.storage.db.execute(
            "SELECT MAX(version) FROM factory_blueprints WHERE blueprint_key=?",
            (row["blueprint_key"],),
        ).fetchone()[0]
        if row["version"] != latest:
            raise PermissionError("Only the latest Blueprint version can receive a new signature")
        if expected_version != row["version"] or expected_digest != row["blueprint_digest"]:
            raise PermissionError("Blueprint signature does not match the exact version and digest")
        if not note.strip():
            raise ValueError("Blueprint approval note is required")
        document = {
            "blueprint_id": blueprint_id, "version": expected_version,
            "blueprint_digest": expected_digest, "decision": decision,
            "signer": signer, "signer_role": signer_role, "note": note.strip(),
        }
        digest = hashlib.sha256(self._json(document).encode()).hexdigest()
        existing = self.storage.db.execute(
            "SELECT id,approval_digest FROM blueprint_approvals WHERE blueprint_id=?",
            (blueprint_id,),
        ).fetchone()
        if existing:
            if existing["approval_digest"] != digest:
                raise ValueError("Blueprint version already has another human decision")
            return int(existing["id"])
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO blueprint_approvals(
                       identity,blueprint_id,blueprint_version,blueprint_digest,decision,
                       signer,signer_role,note,approval_digest
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("blueprint-approval"), blueprint_id,
                    expected_version, expected_digest, decision, signer, signer_role,
                    note.strip(), digest,
                ),
            )
            approval_id = int(cursor.lastrowid)
            self.storage._event(f"blueprint.{decision}", "blueprint_approval", approval_id, {
                "blueprint_id": blueprint_id, "version": expected_version,
                "blueprint_digest": expected_digest, "signer": signer,
            })
        return approval_id

    def authorize_execution(self, blueprint_id: int, *, expected_digest: str) -> int:
        row = self.storage.db.execute(
            "SELECT * FROM factory_blueprints WHERE id=?", (blueprint_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown Factory Blueprint: {blueprint_id}")
        latest = self.storage.db.execute(
            "SELECT MAX(version) FROM factory_blueprints WHERE blueprint_key=?",
            (row["blueprint_key"],),
        ).fetchone()[0]
        if row["version"] != latest:
            raise PermissionError("Only the latest Blueprint version can authorize new execution")
        if expected_digest != row["blueprint_digest"]:
            raise PermissionError("Execution request does not match the exact Blueprint digest")
        approval = self.storage.db.execute(
            """SELECT * FROM blueprint_approvals
               WHERE blueprint_id=? AND decision='approved'""",
            (blueprint_id,),
        ).fetchone()
        if not approval or approval["blueprint_version"] != row["version"] \
                or approval["blueprint_digest"] != row["blueprint_digest"]:
            raise PermissionError("Execution is blocked until the exact Blueprint is approved")
        document = {
            "blueprint_id": blueprint_id, "approval_id": int(approval["id"]),
            "version": int(row["version"]), "blueprint_digest": expected_digest,
        }
        digest = hashlib.sha256(self._json(document).encode()).hexdigest()
        existing = self.storage.db.execute(
            "SELECT id FROM blueprint_execution_authorizations WHERE blueprint_id=?",
            (blueprint_id,),
        ).fetchone()
        if existing:
            return int(existing["id"])
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO blueprint_execution_authorizations(
                       identity,blueprint_id,approval_id,blueprint_version,
                       blueprint_digest,authorization_digest
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    self.storage._identity("blueprint-execution"), blueprint_id,
                    approval["id"], row["version"], expected_digest, digest,
                ),
            )
            authorization_id = int(cursor.lastrowid)
            self.storage._event("blueprint.execution.authorized", "factory_blueprint", blueprint_id, {
                "authorization_id": authorization_id, "approval_id": int(approval["id"]),
                "version": int(row["version"]), "blueprint_digest": expected_digest,
            })
        return authorization_id

    def get(self, blueprint_id: int) -> FactoryBlueprint:
        row = self.storage.db.execute(
            "SELECT * FROM factory_blueprints WHERE id=?", (blueprint_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown Factory Blueprint: {blueprint_id}")
        approval = self.storage.db.execute(
            "SELECT * FROM blueprint_approvals WHERE blueprint_id=?", (blueprint_id,)
        ).fetchone()
        authorization = self.storage.db.execute(
            "SELECT 1 FROM blueprint_execution_authorizations WHERE blueprint_id=?",
            (blueprint_id,),
        ).fetchone()
        return FactoryBlueprint(
            int(row["id"]), str(row["blueprint_key"]), int(row["version"]),
            int(row["intake_id"]), int(row["readiness_assessment_id"]),
            int(row["composition_id"]),
            int(row["parent_blueprint_id"]) if row["parent_blueprint_id"] else None,
            json.loads(row["sections_json"]), json.loads(row["trace_json"]),
            json.loads(row["amendment_impact_json"]) if row["amendment_impact_json"] else None,
            str(row["blueprint_digest"]), dict(approval) if approval else None,
            bool(authorization),
        )
