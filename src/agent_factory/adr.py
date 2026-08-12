"""Architecture decision governance and atomic Blueprint impact propagation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from .blueprint import (
    IDENTIFIER,
    REQUIRED_SECTIONS,
    AmendmentImpact,
    BlueprintAssumption,
    BlueprintDecision,
    BlueprintSections,
    BlueprintService,
    FactoryBlueprint,
    RejectedAlternative,
)
from .storage import SQLiteStorage


MATERIAL_DOMAINS = {"authority", "safety", "data", "external_contracts", "architecture"}


@dataclass(frozen=True)
class ADRAlternative:
    key: str
    description: str
    tradeoffs: str

    def __post_init__(self):
        if not IDENTIFIER.fullmatch(self.key) or not all(
            value.strip() for value in (self.description, self.tradeoffs)
        ):
            raise ValueError("ADR alternative requires key, description, and tradeoffs")


@dataclass(frozen=True)
class ADRImpact:
    affected_tasks: tuple[int, ...]
    context_packages: tuple[int, ...]
    policies: tuple[str, ...]
    evaluations: tuple[int, ...]
    artifacts: tuple[int, ...]
    deployment_assumptions: tuple[str, ...]
    blueprint_sections: tuple[str, ...]

    def __post_init__(self):
        for field in (
            "affected_tasks", "context_packages", "policies", "evaluations",
            "artifacts", "deployment_assumptions", "blueprint_sections",
        ):
            values = getattr(self, field)
            if len(values) != len(set(values)):
                raise ValueError(f"ADR impact {field} references must be unique")
        if not self.blueprint_sections or any(
            section not in REQUIRED_SECTIONS for section in self.blueprint_sections
        ):
            raise ValueError("ADR impact requires valid affected Blueprint sections")
        if any(not value.strip() for value in (*self.policies, *self.deployment_assumptions)):
            raise ValueError("ADR impact policy and deployment references cannot be empty")


@dataclass(frozen=True)
class ArchitectureDecisionRecord:
    id: int
    adr_key: str
    version: int
    blueprint_id: int
    status: str
    decision_digest: str
    impact: dict[str, Any] | None
    approval: dict[str, Any] | None


@dataclass(frozen=True)
class ADRApplication:
    id: int
    adr_id: int
    prior_blueprint_id: int
    new_blueprint: FactoryBlueprint
    workflow_contract_version_ids: tuple[int, ...]


class ADRService:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage
        self.blueprints = BlueprintService(storage)

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def propose(
        self, *, adr_key: str, version: int, blueprint_id: int, context: str,
        alternatives: tuple[ADRAlternative, ...], decision: str,
        consequences: tuple[str, ...], affected_contracts: tuple[str, ...],
        evidence: dict[str, Any], material_domains: tuple[str, ...],
        architecture_owner: str, created_by: str,
    ) -> int:
        if not IDENTIFIER.fullmatch(adr_key) or version <= 0:
            raise ValueError("ADR key and positive version are required")
        if not all(value.strip() for value in (
            context, decision, architecture_owner, created_by
        )):
            raise ValueError("ADR context, decision, owner, and creator are required")
        if len(alternatives) < 2 or len({item.key for item in alternatives}) != len(alternatives):
            raise ValueError("ADR requires at least two unique alternatives")
        if not consequences or any(not value.strip() for value in consequences):
            raise ValueError("ADR consequences are required")
        if not affected_contracts or len(affected_contracts) != len(set(affected_contracts)) \
                or any(not IDENTIFIER.fullmatch(value) for value in affected_contracts):
            raise ValueError("ADR affected contracts require unique stable keys")
        if not evidence:
            raise ValueError("ADR evidence is required")
        if not material_domains or not set(material_domains) <= MATERIAL_DOMAINS:
            raise ValueError("ADR material domains are invalid")
        blueprint = self.storage.db.execute(
            "SELECT blueprint_key,version FROM factory_blueprints WHERE id=?", (blueprint_id,)
        ).fetchone()
        if not blueprint:
            raise KeyError(f"Unknown Factory Blueprint: {blueprint_id}")
        latest = self.storage.db.execute(
            "SELECT MAX(version) FROM factory_blueprints WHERE blueprint_key=?",
            (blueprint["blueprint_key"],),
        ).fetchone()[0]
        if int(blueprint["version"]) != int(latest):
            raise ValueError("ADR must target the latest Factory Blueprint")
        document = {
            "adr_key": adr_key, "version": version, "blueprint_id": blueprint_id,
            "context": context.strip(),
            "alternatives": [asdict(value) for value in alternatives],
            "decision": decision.strip(), "consequences": list(consequences),
            "affected_contracts": list(affected_contracts), "evidence": evidence,
            "material_domains": sorted(set(material_domains)),
            "architecture_owner": architecture_owner, "created_by": created_by,
        }
        digest = self._digest(self._json(document))
        existing = self.storage.db.execute(
            "SELECT id,decision_digest FROM architecture_decisions WHERE adr_key=? AND version=?",
            (adr_key, version),
        ).fetchone()
        if existing:
            if str(existing["decision_digest"]) != digest:
                raise ValueError("ADR version already has another decision")
            return int(existing["id"])
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO architecture_decisions(
                       identity,adr_key,version,blueprint_id,context,alternatives_json,
                       decision,consequences_json,affected_contracts_json,evidence_json,
                       material_domains_json,architecture_owner,decision_digest,created_by
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("architecture-decision"), adr_key, version,
                    blueprint_id, context.strip(), self._json(document["alternatives"]),
                    decision.strip(), self._json(consequences),
                    self._json(affected_contracts), self._json(evidence),
                    self._json(document["material_domains"]), architecture_owner,
                    digest, created_by,
                ),
            )
            adr_id = int(cursor.lastrowid)
            self.storage._event("adr.proposed", "architecture_decision", adr_id, {
                "adr_key": adr_key, "version": version, "blueprint_id": blueprint_id,
                "decision_digest": digest,
            })
        return adr_id

    @staticmethod
    def _validate_ids(storage: SQLiteStorage, table: str, ids: tuple[int, ...], label: str) -> None:
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        found = {
            int(row[0]) for row in storage.db.execute(
                f"SELECT id FROM {table} WHERE id IN ({placeholders})", ids
            )
        }
        missing = set(ids) - found
        if missing:
            raise KeyError(f"Unknown affected {label}: {sorted(missing)}")

    def analyze_impact(self, adr_id: int, impact: ADRImpact, *, analyzed_by: str) -> int:
        if not analyzed_by.strip():
            raise ValueError("Impact analyst is required")
        adr = self.storage.db.execute(
            "SELECT status FROM architecture_decisions WHERE id=?", (adr_id,)
        ).fetchone()
        if not adr:
            raise KeyError(f"Unknown ADR: {adr_id}")
        if adr["status"] != "proposed":
            raise ValueError("Impact analysis must precede ADR approval")
        self._validate_ids(self.storage, "work_items", impact.affected_tasks, "tasks")
        self._validate_ids(
            self.storage, "execution_context_packages", impact.context_packages,
            "context packages",
        )
        self._validate_ids(self.storage, "evaluation_runs", impact.evaluations, "evaluations")
        self._validate_ids(self.storage, "artifacts", impact.artifacts, "artifacts")
        document = {
            "schema_version": 1,
            "affected_tasks": list(impact.affected_tasks),
            "context_packages": list(impact.context_packages),
            "policies": list(impact.policies),
            "evaluations": list(impact.evaluations),
            "artifacts": list(impact.artifacts),
            "deployment_assumptions": list(impact.deployment_assumptions),
            "blueprint_sections": list(impact.blueprint_sections),
        }
        impact_json = self._json(document)
        digest = self._digest(impact_json)
        existing = self.storage.db.execute(
            "SELECT id,impact_digest FROM adr_impact_analyses WHERE adr_id=?", (adr_id,)
        ).fetchone()
        if existing:
            if str(existing["impact_digest"]) != digest:
                raise ValueError("ADR already has another impact analysis")
            return int(existing["id"])
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO adr_impact_analyses(
                       identity,adr_id,impact_json,impact_digest,analyzed_by
                   ) VALUES(?,?,?,?,?)""",
                (
                    self.storage._identity("adr-impact"), adr_id, impact_json,
                    digest, analyzed_by,
                ),
            )
            analysis_id = int(cursor.lastrowid)
            self.storage._event("adr.impact.analyzed", "architecture_decision", adr_id, {
                "impact_analysis_id": analysis_id, "impact_digest": digest,
            })
        return analysis_id

    def decide(
        self, adr_id: int, *, decision: str, reviewer: str,
        reviewer_role: str, note: str,
    ) -> int:
        if decision not in {"approved", "rejected"}:
            raise ValueError("ADR decision must be approved or rejected")
        adr = self.storage.db.execute(
            "SELECT * FROM architecture_decisions WHERE id=?", (adr_id,)
        ).fetchone()
        if not adr:
            raise KeyError(f"Unknown ADR: {adr_id}")
        if reviewer_role != "human_architecture_owner" or reviewer != adr["architecture_owner"]:
            raise PermissionError("Only the authorized human architecture owner may decide an ADR")
        if not note.strip():
            raise ValueError("ADR decision note is required")
        impact = self.storage.db.execute(
            "SELECT * FROM adr_impact_analyses WHERE adr_id=?", (adr_id,)
        ).fetchone()
        if not impact:
            raise PermissionError("ADR impact analysis is required before approval")
        document = {
            "adr_id": adr_id, "decision_digest": adr["decision_digest"],
            "impact_digest": impact["impact_digest"], "decision": decision,
            "reviewer": reviewer, "reviewer_role": reviewer_role, "note": note.strip(),
        }
        digest = self._digest(self._json(document))
        existing = self.storage.db.execute(
            "SELECT id,approval_digest FROM adr_approvals WHERE adr_id=?", (adr_id,)
        ).fetchone()
        if existing:
            if str(existing["approval_digest"]) != digest:
                raise ValueError("ADR already has another approval decision")
            return int(existing["id"])
        if adr["status"] != "proposed":
            raise ValueError(f"ADR is already {adr['status']}")
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO adr_approvals(
                       identity,adr_id,decision_digest,impact_digest,decision,
                       reviewer,reviewer_role,note,approval_digest
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("adr-approval"), adr_id,
                    adr["decision_digest"], impact["impact_digest"], decision,
                    reviewer, reviewer_role, note.strip(), digest,
                ),
            )
            approval_id = int(cursor.lastrowid)
            self.storage.db.execute(
                "UPDATE architecture_decisions SET status=? WHERE id=? AND status='proposed'",
                (decision, adr_id),
            )
            self.storage._event(f"adr.{decision}", "architecture_decision", adr_id, {
                "approval_id": approval_id, "reviewer": reviewer,
            })
        return approval_id

    def apply(
        self, adr_id: int, *, composition_id: int, sections: BlueprintSections,
        decisions: tuple[BlueprintDecision, ...],
        assumptions: tuple[BlueprintAssumption, ...],
        rejected_alternatives: tuple[RejectedAlternative, ...],
        amendment_impact: AmendmentImpact,
        workflow_updates: dict[str, dict[str, Any]],
        applied_by: str, applied_by_role: str,
    ) -> ADRApplication:
        existing = self.storage.db.execute(
            "SELECT * FROM adr_applications WHERE adr_id=?", (adr_id,)
        ).fetchone()
        if existing:
            return self._application(existing)
        adr = self.storage.db.execute(
            "SELECT * FROM architecture_decisions WHERE id=?", (adr_id,)
        ).fetchone()
        if not adr:
            raise KeyError(f"Unknown ADR: {adr_id}")
        if adr["status"] != "approved":
            raise PermissionError("Only an approved ADR can be applied")
        impact_row = self.storage.db.execute(
            "SELECT * FROM adr_impact_analyses WHERE adr_id=?", (adr_id,)
        ).fetchone()
        approval = self.storage.db.execute(
            "SELECT * FROM adr_approvals WHERE adr_id=? AND decision='approved'", (adr_id,)
        ).fetchone()
        if not impact_row or not approval or approval["impact_digest"] != impact_row["impact_digest"]:
            raise PermissionError("ADR approval must bind the exact impact analysis")
        impact = json.loads(impact_row["impact_json"])
        affected_contracts = tuple(json.loads(adr["affected_contracts_json"]))
        if set(workflow_updates) != set(affected_contracts):
            raise ValueError("Workflow updates must exactly cover affected ADR contracts")
        if set(amendment_impact.affected_sections) != set(impact["blueprint_sections"]):
            raise ValueError("Blueprint amendment must exactly match ADR impact sections")
        # Canonicalize before mutation where possible; non-serializable contract data still
        # raises inside the transaction below and proves complete rollback.
        with self.storage.db:
            new_blueprint = self.blueprints.amend_in_transaction(
                int(adr["blueprint_id"]), composition_id=composition_id,
                sections=sections, decisions=decisions, assumptions=assumptions,
                rejected_alternatives=rejected_alternatives, impact=amendment_impact,
                actor=applied_by, actor_role=applied_by_role,
            )
            update_digests = {
                key: self._digest(self._json(workflow_updates[key]))
                for key in sorted(workflow_updates)
            }
            application_document = {
                "adr_id": adr_id, "impact_analysis_id": int(impact_row["id"]),
                "approval_id": int(approval["id"]),
                "prior_blueprint_id": int(adr["blueprint_id"]),
                "new_blueprint_id": new_blueprint.id,
                "new_blueprint_digest": new_blueprint.blueprint_digest,
                "workflow_update_digests": update_digests, "applied_by": applied_by,
            }
            application_digest = self._digest(self._json(application_document))
            cursor = self.storage.db.execute(
                """INSERT INTO adr_applications(
                       identity,adr_id,impact_analysis_id,approval_id,
                       prior_blueprint_id,new_blueprint_id,application_digest,applied_by
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("adr-application"), adr_id, impact_row["id"],
                    approval["id"], adr["blueprint_id"], new_blueprint.id,
                    application_digest, applied_by,
                ),
            )
            application_id = int(cursor.lastrowid)
            contract_version_ids: list[int] = []
            for contract_key in sorted(workflow_updates):
                previous = self.storage.db.execute(
                    """SELECT id,version FROM adr_workflow_contract_versions
                         WHERE contract_key=? ORDER BY version DESC LIMIT 1""",
                    (contract_key,),
                ).fetchone()
                version = int(previous["version"]) + 1 if previous else 1
                contract_cursor = self.storage.db.execute(
                    """INSERT INTO adr_workflow_contract_versions(
                           identity,contract_key,version,application_id,contract_json,
                           contract_digest,previous_version_id
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (
                        self.storage._identity("adr-workflow-contract"), contract_key,
                        version, application_id, self._json(workflow_updates[contract_key]),
                        update_digests[contract_key], int(previous["id"]) if previous else None,
                    ),
                )
                contract_version_ids.append(int(contract_cursor.lastrowid))
            target_groups = (
                ("task", impact["affected_tasks"]),
                ("context_package", impact["context_packages"]),
                ("policy", impact["policies"]),
                ("evaluation", impact["evaluations"]),
                ("artifact", impact["artifacts"]),
                ("deployment_assumption", impact["deployment_assumptions"]),
                ("workflow_contract", affected_contracts),
            )
            for target_type, values in target_groups:
                for value in values:
                    self.storage.db.execute(
                        """INSERT INTO adr_contract_propagations(
                               identity,application_id,target_type,target_ref,action
                           ) VALUES(?,?,?,?,?)""",
                        (
                            self.storage._identity("adr-propagation"), application_id,
                            target_type, str(value),
                            "version_created" if target_type == "workflow_contract"
                            else "review_required",
                        ),
                    )
            updated = self.storage.db.execute(
                "UPDATE architecture_decisions SET status='applied' WHERE id=? AND status='approved'",
                (adr_id,),
            )
            if updated.rowcount != 1:
                raise ValueError("ADR changed concurrently")
            self.storage._event("adr.applied", "architecture_decision", adr_id, {
                "application_id": application_id,
                "prior_blueprint_id": int(adr["blueprint_id"]),
                "new_blueprint_id": new_blueprint.id,
                "workflow_contract_version_ids": contract_version_ids,
            })
        return ADRApplication(
            application_id, adr_id, int(adr["blueprint_id"]), new_blueprint,
            tuple(contract_version_ids),
        )

    def get(self, adr_id: int) -> ArchitectureDecisionRecord:
        row = self.storage.db.execute(
            "SELECT * FROM architecture_decisions WHERE id=?", (adr_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown ADR: {adr_id}")
        impact = self.storage.db.execute(
            "SELECT * FROM adr_impact_analyses WHERE adr_id=?", (adr_id,)
        ).fetchone()
        approval = self.storage.db.execute(
            "SELECT * FROM adr_approvals WHERE adr_id=?", (adr_id,)
        ).fetchone()
        return ArchitectureDecisionRecord(
            int(row["id"]), str(row["adr_key"]), int(row["version"]),
            int(row["blueprint_id"]), str(row["status"]),
            str(row["decision_digest"]),
            json.loads(impact["impact_json"]) if impact else None,
            dict(approval) if approval else None,
        )

    def _application(self, row: Any) -> ADRApplication:
        versions = self.storage.db.execute(
            "SELECT id FROM adr_workflow_contract_versions WHERE application_id=? ORDER BY id",
            (row["id"],),
        ).fetchall()
        return ADRApplication(
            int(row["id"]), int(row["adr_id"]), int(row["prior_blueprint_id"]),
            self.blueprints.get(int(row["new_blueprint_id"])),
            tuple(int(value["id"]) for value in versions),
        )
