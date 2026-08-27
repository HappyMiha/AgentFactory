"""Deterministic readiness verification for autonomous planning proposals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterable

from .autonomous_mission import (
    AutonomousMissionService,
    MissionDisposition,
    MissionPhase,
    MissionVersionConflictError,
)
from .autonomous_planning import AutonomousPlanningService
from .autonomous_planning_pipeline import (
    AutonomousPlanningPipelineService,
    PlanningArtifactSchemas,
    PlanningInvocationRequest,
    PlanningPipelineArtifact,
    PlanningRoleOutputError,
)
from .backlog import BacklogManifestError, BacklogProposal, proposal_from_document
from .backlog_revisions import BacklogRevisionOrigin
from .lifecycle import ensure_transition
from .mission_intake import AutonomousMissionIntakeService
from .models import ProviderResult
from .software_roles import AUTONOMOUS_PLANNING_ROLE_IDS
from .storage import SQLiteStorage


class ProposalVerificationStatus(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class ProposalFindingSeverity(StrEnum):
    BLOCKER = "BLOCKER"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class ProposalVerificationCommandConflictError(ValueError):
    """Raised when a verifier idempotency key is rebound to other input."""


@dataclass(frozen=True)
class ProposalFinding:
    code: str
    severity: ProposalFindingSeverity
    message: str
    artifact: str
    blocking: bool
    display_to_human: bool = True
    references: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "artifact": self.artifact,
            "blocking": self.blocking,
            "display_to_human": self.display_to_human,
            "references": list(self.references),
        }


@dataclass(frozen=True)
class DeterministicProposalEvaluation:
    ready: bool
    checks: tuple[dict[str, Any], ...]
    findings: tuple[ProposalFinding, ...]
    reviewer_findings: tuple[dict[str, Any], ...]
    human_visible_findings: tuple[dict[str, Any], ...]
    proposal: BacklogProposal | None


@dataclass(frozen=True)
class ProposalReadinessReport:
    id: int
    identity: str
    mission_id: int
    pipeline_run_id: int
    completion_id: int
    completion_digest: str
    manifest_id: int
    manifest_digest: str
    revision_id: int
    revision_digest: str
    source_id: int
    source_digest: str
    verifier_version: str
    status: ProposalVerificationStatus
    canonical_snapshot: dict[str, Any]
    canonical_digest: str
    presentation: dict[str, Any]
    presentation_digest: str
    checks: tuple[dict[str, Any], ...]
    findings: tuple[dict[str, Any], ...]
    reviewer_findings: tuple[dict[str, Any], ...]
    human_visible_findings: tuple[dict[str, Any], ...]
    verified_by: str
    expected_mission_version: int
    mission_result_version: int | None
    command_id: str
    request_digest: str
    report_digest: str
    created_at: str

    @property
    def ready(self) -> bool:
        return self.status is ProposalVerificationStatus.READY


class DeterministicProposalVerifier:
    """Validate untrusted proposal documents without provider judgment."""

    @staticmethod
    def _finding(
        code: str,
        message: str,
        artifact: str,
        *,
        severity: ProposalFindingSeverity = ProposalFindingSeverity.BLOCKER,
        blocking: bool = True,
        display_to_human: bool = True,
        references: Iterable[str] = (),
    ) -> ProposalFinding:
        return ProposalFinding(
            code=code,
            severity=severity,
            message=str(message).strip()[:2000],
            artifact=artifact,
            blocking=blocking,
            display_to_human=display_to_human,
            references=tuple(str(value) for value in references),
        )

    @staticmethod
    def _code_for_error(message: str, artifact: str) -> str:
        normalized = message.casefold()
        if "duplicate stable" in normalized or "duplicated" in normalized:
            return "DUPLICATED_ITEM" if artifact == "backlog" else "DUPLICATED_VALUE"
        if "cycle" in normalized or "cyclic" in normalized:
            return "CYCLIC_DEPENDENCY"
        if "unknown items" in normalized or "unknown component" in normalized:
            return "ORPHANED_REFERENCE"
        if "unknown requirement" in normalized:
            return "ORPHANED_REQUIREMENT_REFERENCE"
        if "measurable" in normalized:
            return "NON_MEASURABLE_ACCEPTANCE"
        if "canonical dependency order" in normalized:
            return "NON_CANONICAL_ORDER"
        if "infrastructure" in normalized and "depend" in normalized:
            return "UNSAFE_INFRASTRUCTURE_ORDER"
        if "schema v2" in normalized or "fields invalid" in normalized:
            return "MALFORMED_RICH_ITEM"
        return f"MALFORMED_{artifact.upper()}"

    @staticmethod
    def _source_reference_valid(reference: str, roots: frozenset[str]) -> bool:
        normalized = reference.strip().casefold()
        for root in roots:
            if normalized == root:
                return True
            if normalized.startswith(
                (f"{root}#", f"{root}:", f"{root}/", f"{root}[", f"{root} ")
            ):
                return True
        return False

    def evaluate(
        self,
        *,
        backlog_document: Any,
        requirements_document: Any,
        architecture_document: Any,
        reviewer_report: Any,
        source_path: str,
        source_sha256: str,
        source_name: str,
        source_reference_roots: Iterable[str] = (),
        known_artifact_references: Iterable[str] = (),
    ) -> DeterministicProposalEvaluation:
        findings: list[ProposalFinding] = []
        checks: list[dict[str, Any]] = []

        def add(finding: ProposalFinding) -> None:
            key = (finding.code, finding.artifact, finding.message)
            if key not in {
                (value.code, value.artifact, value.message) for value in findings
            }:
                findings.append(finding)

        def check(name: str, passed: bool, detail: str) -> None:
            checks.append(
                {
                    "name": name,
                    "passed": bool(passed),
                    "detail": str(detail).strip()[:2000],
                }
            )

        roots = frozenset(
            str(value).strip().casefold()
            for value in (source_name, *tuple(source_reference_roots))
            if str(value).strip()
        )
        requirement_ids: set[str] = set()
        requirements_valid = False
        try:
            requirement_ids = PlanningArtifactSchemas.normalized_requirements(
                requirements_document
            )
            requirements_valid = True
        except (TypeError, ValueError) as exc:
            add(
                self._finding(
                    self._code_for_error(str(exc), "requirements"),
                    str(exc),
                    "requirements",
                )
            )
        check(
            "requirements_schema",
            requirements_valid,
            "Normalized requirements satisfy the strict planning schema."
            if requirements_valid
            else "Normalized requirements are malformed.",
        )

        requirement_scope_valid = requirements_valid
        if requirements_valid:
            for category in ("functional", "non_functional"):
                for requirement in requirements_document[category]:
                    invalid = [
                        reference
                        for reference in requirement["source_references"]
                        if not self._source_reference_valid(reference, roots)
                    ]
                    if invalid:
                        requirement_scope_valid = False
                        add(
                            self._finding(
                                "SCOPE_UNTRACEABLE_REQUIREMENT",
                                f"Requirement {requirement['id']!r} references "
                                f"sources outside the authoritative specification: {invalid}",
                                "requirements",
                                references=(requirement["id"], *invalid),
                            )
                        )
        check(
            "requirements_source_traceability",
            requirement_scope_valid,
            "Every requirement points into the authoritative source scope."
            if requirement_scope_valid
            else "One or more requirements have untrusted source references.",
        )

        architecture_valid = False
        if requirements_valid:
            try:
                PlanningArtifactSchemas.architecture(
                    architecture_document, requirement_ids
                )
                architecture_valid = True
            except (TypeError, ValueError) as exc:
                add(
                    self._finding(
                        self._code_for_error(str(exc), "architecture"),
                        str(exc),
                        "architecture",
                    )
                )
        else:
            add(
                self._finding(
                    "ARCHITECTURE_REQUIREMENTS_UNAVAILABLE",
                    "Architecture cannot be traced because requirements are invalid.",
                    "architecture",
                )
            )
        check(
            "architecture_schema_and_traceability",
            architecture_valid,
            "Architecture is complete and references only known requirements."
            if architecture_valid
            else "Architecture is malformed or untraceable.",
        )

        proposal: BacklogProposal | None = None
        backlog_schema_valid = False
        try:
            proposal = proposal_from_document(
                backlog_document,
                source_path=source_path,
                source_sha256=source_sha256,
                source_name=source_name,
            )
            backlog_schema_valid = proposal.schema_version == 2
            if not backlog_schema_valid:
                add(
                    self._finding(
                        "MALFORMED_RICH_ITEM",
                        "Autonomous proposals require backlog schema version 2.",
                        "backlog",
                    )
                )
        except (BacklogManifestError, TypeError, ValueError) as exc:
            add(
                self._finding(
                    self._code_for_error(str(exc), "backlog"),
                    str(exc),
                    "backlog",
                )
            )
        check(
            "backlog_rich_schema",
            backlog_schema_valid,
            "Every executable item has the complete schema-v2 execution contract."
            if backlog_schema_valid
            else "Backlog schema or rich execution fields are incomplete.",
        )

        graph_valid = backlog_schema_valid
        measurable = backlog_schema_valid
        traceable = backlog_schema_valid and requirements_valid
        deterministic_order = backlog_schema_valid
        infrastructure_order = backlog_schema_valid and architecture_valid
        if proposal is not None and backlog_schema_valid:
            actual_order = tuple(item.stable_id for item in proposal.items)
            try:
                expected_order = PlanningArtifactSchemas.canonical_item_ids(
                    proposal.items
                )
                if actual_order != expected_order:
                    deterministic_order = False
                    add(
                        self._finding(
                            "NON_CANONICAL_ORDER",
                            "Backlog item order does not equal the deterministic "
                            f"topological order {list(expected_order)}.",
                            "backlog",
                            references=actual_order,
                        )
                    )
            except (TypeError, ValueError) as exc:
                graph_valid = False
                deterministic_order = False
                add(
                    self._finding(
                        self._code_for_error(str(exc), "backlog"),
                        str(exc),
                        "backlog",
                    )
                )

            covered: set[str] = set()
            for item in proposal.items:
                if len(item.dependencies) != len(set(item.dependencies)):
                    graph_valid = False
                    add(
                        self._finding(
                            "DUPLICATED_DEPENDENCY",
                            f"Item {item.stable_id!r} repeats a dependency.",
                            "backlog",
                            references=(item.stable_id,),
                        )
                    )
                if len(item.acceptance_criteria) != len(
                    set(item.acceptance_criteria)
                ):
                    measurable = False
                    add(
                        self._finding(
                            "DUPLICATED_ACCEPTANCE_CRITERION",
                            f"Item {item.stable_id!r} repeats an acceptance criterion.",
                            "backlog",
                            references=(item.stable_id,),
                        )
                    )
                if item.executable and item.priority not in {"P0", "P1", "P2", "P3"}:
                    add(
                        self._finding(
                            "INVALID_PRIORITY",
                            f"Item {item.stable_id!r} has unsupported priority "
                            f"{item.priority!r}.",
                            "backlog",
                            references=(item.stable_id,),
                        )
                    )
                if item.executable:
                    for criterion in item.acceptance_criteria:
                        try:
                            PlanningArtifactSchemas._measurable(
                                criterion, f"item[{item.stable_id}]"
                            )
                        except PlanningRoleOutputError as exc:
                            measurable = False
                            add(
                                self._finding(
                                    "NON_MEASURABLE_ACCEPTANCE",
                                    str(exc),
                                    "backlog",
                                    references=(item.stable_id,),
                                )
                            )
                    references = set(item.source_references)
                    covered.update(references & requirement_ids)
                    if not (references & requirement_ids):
                        traceable = False
                        add(
                            self._finding(
                                "SCOPE_UNTRACEABLE_ITEM",
                                f"Executable item {item.stable_id!r} has no "
                                "normalized requirement reference.",
                                "backlog",
                                references=(item.stable_id,),
                            )
                        )
                    unknown = [
                        reference
                        for reference in references
                        if reference not in requirement_ids
                        and not self._source_reference_valid(reference, roots)
                    ]
                    if unknown:
                        traceable = False
                        add(
                            self._finding(
                                "SCOPE_UNTRACEABLE_ITEM",
                                f"Item {item.stable_id!r} references unknown scope: "
                                f"{sorted(unknown)}.",
                                "backlog",
                                references=(item.stable_id, *sorted(unknown)),
                            )
                        )
            uncovered = requirement_ids - covered
            if uncovered:
                traceable = False
                add(
                    self._finding(
                        "UNCOVERED_REQUIREMENT",
                        f"Backlog does not cover requirements: {sorted(uncovered)}.",
                        "backlog",
                        references=sorted(uncovered),
                    )
                )
            if architecture_valid:
                try:
                    PlanningArtifactSchemas._infrastructure_order(
                        proposal.items, architecture_document
                    )
                except (TypeError, ValueError) as exc:
                    infrastructure_order = False
                    add(
                        self._finding(
                            "UNSAFE_INFRASTRUCTURE_ORDER",
                            str(exc),
                            "backlog",
                        )
                    )

        check(
            "dependency_graph",
            graph_valid,
            "Dependencies and parents form a complete acyclic graph."
            if graph_valid
            else "Dependency graph is cyclic, orphaned, or duplicated.",
        )
        check(
            "deterministic_logical_order",
            deterministic_order,
            "Items are in deterministic topological order."
            if deterministic_order
            else "Items are not in deterministic logical order.",
        )
        check(
            "measurable_acceptance",
            measurable,
            "Executable acceptance criteria are deterministic and measurable."
            if measurable
            else "One or more executable acceptance criteria are not measurable.",
        )
        check(
            "backlog_requirement_traceability",
            traceable,
            "Every executable item and requirement is traceable."
            if traceable
            else "Backlog scope cannot be fully traced to normalized requirements.",
        )
        check(
            "infrastructure_dependency_order",
            infrastructure_order,
            "Bootstrap prerequisites precede dependent development work."
            if infrastructure_order
            else "Required infrastructure is not safely ordered.",
        )

        reviewer_findings: list[dict[str, Any]] = []
        human_visible: list[dict[str, Any]] = []
        reviewer_valid = False
        try:
            PlanningArtifactSchemas.review_report(reviewer_report)
            reviewer_valid = True
        except (TypeError, ValueError) as exc:
            add(
                self._finding(
                    "MALFORMED_REVIEW_REPORT",
                    str(exc),
                    "review",
                )
            )
        known_references = {
            str(reference).strip()
            for reference in known_artifact_references
            if str(reference).strip()
        }
        if reviewer_valid:
            reviewer_findings = [dict(value) for value in reviewer_report["findings"]]
            if reviewer_report["verdict"] != "READY":
                add(
                    self._finding(
                        "REVIEWER_REQUIRES_REPAIR",
                        "Backlog Reviewer verdict is NEEDS_REPAIR.",
                        "review",
                    )
                )
            for reviewer_finding in reviewer_findings:
                finding_id = str(reviewer_finding["id"])
                references = tuple(reviewer_finding["artifact_references"])
                if known_references:
                    unknown = sorted(set(references) - known_references)
                    if unknown:
                        add(
                            self._finding(
                                "REVIEWER_ORPHANED_REFERENCE",
                                f"Reviewer finding {finding_id!r} references unknown "
                                f"artifacts: {unknown}.",
                                "review",
                                references=(finding_id, *unknown),
                            )
                        )
                if reviewer_finding["display_to_human"]:
                    human_visible.append(dict(reviewer_finding))
                unresolved = reviewer_finding["status"] != "RESOLVED"
                if unresolved and not reviewer_finding["display_to_human"]:
                    add(
                        self._finding(
                            "HIDDEN_REVIEWER_FINDING",
                            f"Unresolved reviewer finding {finding_id!r} is hidden "
                            "from the human decision packet.",
                            "review",
                            references=(finding_id,),
                        )
                    )
                severity = ProposalFindingSeverity(reviewer_finding["severity"])
                if (
                    reviewer_finding["status"] == "OPEN"
                    and severity
                    in {
                        ProposalFindingSeverity.BLOCKER,
                        ProposalFindingSeverity.HIGH,
                    }
                ):
                    add(
                        self._finding(
                            "UNRESOLVED_REVIEWER_BLOCKER",
                            reviewer_finding["message"],
                            "review",
                            severity=severity,
                            references=(finding_id, *references),
                        )
                    )
                elif unresolved and reviewer_finding["display_to_human"]:
                    add(
                        self._finding(
                            "REVIEWER_FINDING_DISCLOSED",
                            reviewer_finding["message"],
                            "review",
                            severity=severity,
                            blocking=False,
                            references=(finding_id, *references),
                        )
                    )
        reviewer_blockers = [
            value
            for value in findings
            if value.artifact == "review" and value.blocking
        ]
        check(
            "reviewer_findings_resolved_or_disclosed",
            reviewer_valid and not reviewer_blockers,
            "Reviewer findings are retained and either resolved or safely disclosed."
            if reviewer_valid and not reviewer_blockers
            else "Reviewer evidence is malformed or contains unresolved blockers.",
        )

        human_visible.extend(
            value.to_dict()
            for value in findings
            if value.display_to_human and value.artifact != "review"
        )
        ready = not any(value.blocking for value in findings)
        return DeterministicProposalEvaluation(
            ready=ready,
            checks=tuple(checks),
            findings=tuple(findings),
            reviewer_findings=tuple(reviewer_findings),
            human_visible_findings=tuple(human_visible),
            proposal=proposal,
        )


class _ReadOnlyPlanningInvoker:
    def invoke(self, request: PlanningInvocationRequest) -> ProviderResult:
        raise PermissionError(
            "Proposal verification cannot invoke a planning provider"
        )


class AutonomousProposalVerificationService:
    """Persist readiness evidence and atomically enter the human approval wait."""

    VERIFIER_VERSION = "agentfactory.autonomous-proposal-verifier/1.0.0"

    def __init__(self, storage: SQLiteStorage):
        self.storage = storage
        self.missions = AutonomousMissionService(storage)
        self.planning = AutonomousPlanningService(storage)
        self.intake = AutonomousMissionIntakeService(storage)
        self.pipeline = AutonomousPlanningPipelineService(
            storage, _ReadOnlyPlanningInvoker()
        )
        self.verifier = DeterministicProposalVerifier()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
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

    def _existing(
        self, command_id: str, request_digest: str
    ) -> ProposalReadinessReport | None:
        row = self.storage.db.execute(
            "SELECT id,request_digest FROM autonomous_proposal_verifications "
            "WHERE command_id=?",
            (command_id,),
        ).fetchone()
        if not row:
            return None
        if row["request_digest"] != request_digest:
            raise ProposalVerificationCommandConflictError(
                f"Proposal verification command {command_id!r} is already bound"
            )
        return self.get(int(row["id"]))

    @staticmethod
    def _known_artifact_references(
        artifacts: tuple[PlanningPipelineArtifact, ...]
    ) -> set[str]:
        result: set[str] = set()
        for artifact in artifacts:
            result.update(
                {
                    artifact.role_id,
                    artifact.artifact_kind.value,
                    f"artifact:{artifact.id}",
                    artifact.artifact_digest,
                    artifact.output_digest,
                    *artifact.content.keys(),
                }
            )
        return result

    @staticmethod
    def _scope_finding(code: str, message: str, artifact: str) -> ProposalFinding:
        return ProposalFinding(
            code=code,
            severity=ProposalFindingSeverity.BLOCKER,
            message=message,
            artifact=artifact,
            blocking=True,
            display_to_human=True,
        )

    def verify_and_present(
        self,
        pipeline_run_id: int,
        *,
        actor: str,
        command_id: str,
        expected_mission_version: int,
    ) -> ProposalReadinessReport:
        actor = self._required(actor, "Verifier actor")
        command_id = self._required(command_id, "Command id")
        run = self.pipeline.get_run(pipeline_run_id)
        if run.status != "COMPLETED" or run.revision_id is None:
            raise PermissionError("Only a completed planning proposal can be verified")
        completion = self.storage.db.execute(
            "SELECT * FROM autonomous_planning_pipeline_completions WHERE run_id=?",
            (run.id,),
        ).fetchone()
        if not completion:
            raise RuntimeError("Completed planning run has no completion evidence")
        manifest = self.planning.get_manifest(run.manifest_id)
        source = self.intake.get_source(manifest.specification_source_id)
        revision_row = self.storage.db.execute(
            "SELECT * FROM autonomous_backlog_revisions WHERE id=?",
            (run.revision_id,),
        ).fetchone()
        if not revision_row:
            raise RuntimeError("Planning completion references a missing revision")
        request = {
            "type": "verify_and_present_autonomous_proposal",
            "pipeline_run_id": run.id,
            "completion_id": int(completion["id"]),
            "completion_digest": str(completion["completion_digest"]),
            "manifest_id": manifest.id,
            "manifest_digest": manifest.manifest_digest,
            "revision_id": int(revision_row["id"]),
            "revision_digest": str(revision_row["revision_digest"]),
            "source_id": source.id,
            "source_digest": source.source_digest,
            "verifier_version": self.VERIFIER_VERSION,
            "actor": actor,
            "expected_mission_version": int(expected_mission_version),
        }
        request_digest = self._digest(request)
        replay = self._existing(command_id, request_digest)
        if replay:
            return replay

        mission = self.missions.get(run.mission_id)
        if actor != mission.mission_owner:
            raise PermissionError(
                "Only the authenticated mission owner may present a proposal"
            )
        if mission.version != expected_mission_version:
            raise MissionVersionConflictError(
                mission.id, expected_mission_version, mission.version
            )
        if mission.phase not in {
            MissionPhase.SPECIFICATION_ANALYSIS,
            MissionPhase.BACKLOG_GENERATION,
        }:
            raise PermissionError(
                "Proposal verification requires the active pre-approval planning phase"
            )

        snapshot_text = str(revision_row["snapshot_json"])
        try:
            snapshot = json.loads(snapshot_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Backlog revision snapshot is not valid JSON") from exc
        artifacts = run.artifacts
        by_role = {artifact.role_id: artifact for artifact in artifacts}
        if tuple(artifact.role_id for artifact in artifacts) != AUTONOMOUS_PLANNING_ROLE_IDS:
            raise RuntimeError("Planning artifact chain is incomplete or out of order")
        requirements = by_role["product_requirements_analyst"].content[
            "normalized_requirements"
        ]
        architecture = by_role["software_architect"].content[
            "architecture_proposal"
        ]
        backlog_document = by_role["backlog_planner"].content["backlog_proposal"]
        reviewer_report = by_role["backlog_reviewer"].content["review_report"]
        evaluation = self.verifier.evaluate(
            backlog_document=backlog_document,
            requirements_document=requirements,
            architecture_document=architecture,
            reviewer_report=reviewer_report,
            source_path="autonomous://specification",
            source_sha256=source.raw_digest,
            source_name=source.source_name,
            source_reference_roots=(f"source:{source.id}",),
            known_artifact_references=self._known_artifact_references(artifacts),
        )
        findings = list(evaluation.findings)
        checks = list(evaluation.checks)

        def scope_check(
            name: str,
            passed: bool,
            code: str,
            message: str,
            artifact: str,
        ) -> None:
            checks.append({"name": name, "passed": bool(passed), "detail": message})
            if not passed:
                findings.append(self._scope_finding(code, message, artifact))

        canonical_text = self._json(snapshot)
        canonical_digest = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
        scope_check(
            "canonical_revision_snapshot",
            canonical_text == snapshot_text
            and canonical_digest == str(revision_row["revision_digest"]),
            "CANONICAL_DIGEST_MISMATCH",
            "The stored revision digest does not equal its exact canonical snapshot.",
            "revision",
        )
        current_source = self.intake.current_source(run.mission_id)
        source_current = (
            current_source.id == source.id
            and not manifest.stale
            and source.raw_digest == str(revision_row["source_sha256"])
        )
        scope_check(
            "authoritative_source_binding",
            source_current,
            "STALE_SPECIFICATION_SCOPE",
            "The proposal does not bind the current authoritative specification.",
            "source",
        )
        invalidated = self.storage.db.execute(
            "SELECT 1 FROM autonomous_backlog_revision_invalidations WHERE revision_id=?",
            (run.revision_id,),
        ).fetchone()
        scope_check(
            "revision_not_invalidated",
            invalidated is None,
            "INVALIDATED_REVISION",
            "The proposed revision was invalidated by a source change.",
            "revision",
        )
        scope_check(
            "agent_material_origin",
            revision_row["origin"] == BacklogRevisionOrigin.AGENT_MATERIAL.value,
            "UNSUPPORTED_REVISION_ORIGIN",
            "Planning verification requires an AGENT_MATERIAL proposal revision.",
            "revision",
        )

        artifact_bindings = {
            role_id: {
                "artifact_id": by_role[role_id].id,
                "artifact_digest": by_role[role_id].artifact_digest,
                "output_digest": by_role[role_id].output_digest,
            }
            for role_id in AUTONOMOUS_PLANNING_ROLE_IDS
        }
        expected_contract = {
            "schema_version": 1,
            "planning_run_id": run.id,
            "proposal_key": run.proposal_key,
            "manifest_id": manifest.id,
            "manifest_digest": manifest.manifest_digest,
            "planning_authorization_id": run.planning_authorization_id,
            "artifacts": artifact_bindings,
        }
        contract_valid = (
            snapshot.get("extension_schema")
            == "agentfactory.autonomous-planning/v1"
            and snapshot.get("planning_contract") == expected_contract
            and snapshot.get("schema_version") == 2
            and snapshot.get("requirements_artifact_digest")
            == by_role["product_requirements_analyst"].artifact_digest
            and snapshot.get("architecture_artifact_digest")
            == by_role["software_architect"].artifact_digest
            and snapshot.get("review_artifact_digest")
            == by_role["backlog_reviewer"].artifact_digest
        )
        scope_check(
            "planning_contract_binding",
            contract_valid,
            "PLANNING_CONTRACT_MISMATCH",
            "Revision planning contract does not bind the exact run and artifacts.",
            "revision",
        )
        expected_source_snapshot = {
            "name": source.source_name,
            "specification_source_id": source.id,
            "specification_source_digest": source.source_digest,
            "version": source.version,
            "provenance": source.provenance,
        }
        source_snapshot_valid = (
            snapshot.get("source_path") == "autonomous://specification"
            and snapshot.get("source_sha256") == source.raw_digest
            and snapshot.get("source_name") == source.source_name
            and snapshot.get("source") == expected_source_snapshot
        )
        scope_check(
            "revision_source_snapshot",
            source_snapshot_valid,
            "REVISION_SOURCE_MISMATCH",
            "Revision source metadata does not equal the bound specification.",
            "revision",
        )
        role_manifest_valid = (
            tuple(assignment.role_id for assignment in manifest.assignments)
            == AUTONOMOUS_PLANNING_ROLE_IDS
            and len(
                {
                    assignment.logical_agent_id
                    for assignment in manifest.assignments
                }
            )
            == len(AUTONOMOUS_PLANNING_ROLE_IDS)
            and all(
                assignment.provider_capabilities.get(
                    "autonomous_local_eligible"
                )
                is True
                for assignment in manifest.assignments
            )
        )
        scope_check(
            "role_model_manifest",
            role_manifest_valid,
            "ROLE_MODEL_MANIFEST_MISMATCH",
            "Planning roles, logical agents, or local provider capabilities changed.",
            "manifest",
        )
        reviewer_evidence_valid = (
            by_role["backlog_reviewer"].evidence.get("findings")
            == reviewer_report.get("findings")
        )
        scope_check(
            "reviewer_evidence_binding",
            reviewer_evidence_valid,
            "REVIEWER_EVIDENCE_MISMATCH",
            "Reviewer evidence does not equal the retained review findings.",
            "review",
        )
        snapshot_backlog = {
            "schema_version": snapshot.get("schema_version"),
            "items": snapshot.get("items"),
        }
        normalized_backlog = (
            {
                "schema_version": evaluation.proposal.schema_version,
                "items": [item.to_dict() for item in evaluation.proposal.items],
            }
            if evaluation.proposal is not None
            else None
        )
        scope_check(
            "artifact_revision_equivalence",
            normalized_backlog is not None
            and self._json(snapshot_backlog) == self._json(normalized_backlog),
            "ARTIFACT_REVISION_MISMATCH",
            "The persisted revision differs from the validated backlog artifact.",
            "revision",
        )
        completion_binding = {
            "run_id": run.id,
            "mission_id": run.mission_id,
            "manifest_id": manifest.id,
            "manifest_digest": manifest.manifest_digest,
            "manifest_revision_binding_id": int(
                completion["manifest_revision_binding_id"]
            ),
            "revision_id": int(completion["revision_id"]),
            "revision_digest": str(completion["revision_digest"]),
            "final_artifact_id": int(completion["final_artifact_id"]),
            "final_artifact_digest": by_role[
                "backlog_reviewer"
            ].artifact_digest,
            "artifact_digests": [
                by_role[role_id].artifact_digest
                for role_id in AUTONOMOUS_PLANNING_ROLE_IDS
            ],
        }
        completion_digest_valid = (
            self._digest(completion_binding) == completion["completion_digest"]
            and int(completion["revision_id"]) == int(revision_row["id"])
            and completion["revision_digest"] == revision_row["revision_digest"]
        )
        scope_check(
            "pipeline_completion_digest",
            completion_digest_valid,
            "COMPLETION_DIGEST_MISMATCH",
            "Planning completion evidence does not match the artifact chain.",
            "pipeline",
        )
        mission_ready_scope = (
            mission.phase is MissionPhase.BACKLOG_GENERATION
            and mission.disposition is MissionDisposition.RUNNING
        )
        scope_check(
            "mission_ready_for_presentation",
            mission_ready_scope,
            "MISSION_NOT_PRESENTABLE",
            "Mission is not in running BACKLOG_GENERATION state.",
            "mission",
        )

        deduplicated: list[ProposalFinding] = []
        seen: set[tuple[str, str, str]] = set()
        for finding in findings:
            key = (finding.code, finding.artifact, finding.message)
            if key not in seen:
                seen.add(key)
                deduplicated.append(finding)
        status = (
            ProposalVerificationStatus.BLOCKED
            if any(finding.blocking for finding in deduplicated)
            else ProposalVerificationStatus.READY
        )
        human_visible = list(evaluation.human_visible_findings)
        human_keys = {
            self._json(value) for value in human_visible
        }
        for finding in deduplicated:
            document = finding.to_dict()
            if finding.display_to_human and self._json(document) not in human_keys:
                human_keys.add(self._json(document))
                human_visible.append(document)

        presentation = {
            "schema_version": 1,
            "mission": {
                "id": mission.id,
                "mission_key": mission.mission_key,
                "name": mission.name,
                "version": mission.version,
                "phase": mission.phase.value,
                "proposed_phase": MissionPhase.WAITING_FOR_BACKLOG_APPROVAL.value,
            },
            "specification_source": {
                "id": source.id,
                "version": source.version,
                "source_name": source.source_name,
                "source_digest": source.source_digest,
                "raw_digest": source.raw_digest,
            },
            "proposal": {
                "pipeline_run_id": run.id,
                "proposal_key": run.proposal_key,
                "revision_id": int(revision_row["id"]),
                "revision_number": int(revision_row["revision_number"]),
                "canonical_digest": str(revision_row["revision_digest"]),
                "items": snapshot.get("items", []),
            },
            "requirements": requirements,
            "architecture": architecture,
            "planning_manifest": {
                "id": manifest.id,
                "manifest_digest": manifest.manifest_digest,
                "role_pack_digest": manifest.role_pack_digest,
                "assignments": [
                    {
                        "role_id": assignment.role_id,
                        "role_contract_digest": assignment.role_contract_digest,
                        "logical_agent_id": assignment.logical_agent_id,
                        "provider_id": assignment.provider_id,
                        "model": assignment.model,
                    }
                    for assignment in manifest.assignments
                ],
            },
            "review": {
                "report": reviewer_report,
                "reviewer_findings": list(evaluation.reviewer_findings),
                "human_visible_findings": human_visible,
            },
            "verification": {
                "verifier_version": self.VERIFIER_VERSION,
                "status": status.value,
                "checks": checks,
                "findings": [finding.to_dict() for finding in deduplicated],
            },
        }
        presentation_digest = self._digest(presentation)
        created_at = self._timestamp()
        mission_result_version = (
            expected_mission_version + 1
            if status is ProposalVerificationStatus.READY
            else None
        )
        report_values = {
            "mission_id": run.mission_id,
            "pipeline_run_id": run.id,
            "completion_id": int(completion["id"]),
            "completion_digest": str(completion["completion_digest"]),
            "manifest_id": manifest.id,
            "manifest_digest": manifest.manifest_digest,
            "revision_id": int(revision_row["id"]),
            "revision_digest": str(revision_row["revision_digest"]),
            "source_id": source.id,
            "source_digest": source.source_digest,
            "verifier_version": self.VERIFIER_VERSION,
            "status": status.value,
            "canonical_digest": str(revision_row["revision_digest"]),
            "presentation_digest": presentation_digest,
            "checks": checks,
            "findings": [finding.to_dict() for finding in deduplicated],
            "reviewer_findings": list(evaluation.reviewer_findings),
            "human_visible_findings": human_visible,
            "verified_by": actor,
            "expected_mission_version": expected_mission_version,
            "mission_result_version": mission_result_version,
            "command_id": command_id,
            "request_digest": request_digest,
            "created_at": created_at,
        }
        report_digest = self._digest(report_values)

        with self.storage.db:
            self.storage._begin_immediate()
            replay = self._existing(command_id, request_digest)
            if replay:
                return replay
            current = self.storage.db.execute(
                "SELECT * FROM autonomous_missions WHERE id=?", (run.mission_id,)
            ).fetchone()
            if not current:
                raise KeyError(f"Unknown Autonomous Mission: {run.mission_id}")
            actual_version = int(current["version"])
            if actual_version != expected_mission_version:
                raise MissionVersionConflictError(
                    run.mission_id, expected_mission_version, actual_version
                )
            if current["mission_owner"] != actor:
                raise PermissionError("Mission owner changed before verification commit")
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_proposal_verifications(
                       identity,mission_id,pipeline_run_id,completion_id,
                       completion_digest,manifest_id,manifest_digest,revision_id,
                       revision_digest,source_id,source_digest,verifier_version,
                       status,canonical_snapshot_json,canonical_digest,
                       presentation_json,presentation_digest,checks_json,
                       findings_json,reviewer_findings_json,
                       human_visible_findings_json,verified_by,
                       expected_mission_version,mission_result_version,command_id,
                       request_digest,report_digest,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-proposal-verification"),
                    run.mission_id,
                    run.id,
                    completion["id"],
                    completion["completion_digest"],
                    manifest.id,
                    manifest.manifest_digest,
                    revision_row["id"],
                    revision_row["revision_digest"],
                    source.id,
                    source.source_digest,
                    self.VERIFIER_VERSION,
                    status.value,
                    canonical_text,
                    revision_row["revision_digest"],
                    self._json(presentation),
                    presentation_digest,
                    self._json(checks),
                    self._json(report_values["findings"]),
                    self._json(report_values["reviewer_findings"]),
                    self._json(human_visible),
                    actor,
                    expected_mission_version,
                    mission_result_version,
                    command_id,
                    request_digest,
                    report_digest,
                    created_at,
                ),
            )
            report_id = int(cursor.lastrowid)
            if status is ProposalVerificationStatus.READY:
                ensure_transition(
                    "autonomous_mission_phase",
                    str(current["phase"]),
                    MissionPhase.WAITING_FOR_BACKLOG_APPROVAL.value,
                )
                wait_command_id = f"{command_id}:mission-waiting"
                self.missions._insert_state_version(
                    mission_id=run.mission_id,
                    version=int(mission_result_version),
                    phase=MissionPhase.WAITING_FOR_BACKLOG_APPROVAL,
                    disposition=MissionDisposition(current["disposition"]),
                    configuration_json=str(current["configuration_json"]),
                    configuration_digest=str(current["configuration_digest"]),
                    active_backlog_revision_id=self.missions._optional_id(
                        current["active_backlog_revision_id"]
                    ),
                    active_execution_epoch_id=self.missions._optional_id(
                        current["active_execution_epoch_id"]
                    ),
                    current_checkpoint_id=self.missions._optional_id(
                        current["current_checkpoint_id"]
                    ),
                    actor=actor,
                    command_id=wait_command_id,
                    reason="Deterministic proposal verification is ready",
                )
                updated = self.storage.db.execute(
                    """UPDATE autonomous_missions
                          SET phase=?,version=?,updated_at=CURRENT_TIMESTAMP
                        WHERE id=? AND version=?""",
                    (
                        MissionPhase.WAITING_FOR_BACKLOG_APPROVAL.value,
                        mission_result_version,
                        run.mission_id,
                        expected_mission_version,
                    ),
                )
                if updated.rowcount != 1:
                    raise MissionVersionConflictError(
                        run.mission_id,
                        expected_mission_version,
                        expected_mission_version + 1,
                    )
                transition_request_digest = self._digest(
                    {
                        "type": "verified_proposal_waiting",
                        "mission_id": run.mission_id,
                        "verification_id": report_id,
                        "revision_id": revision_row["id"],
                        "canonical_digest": revision_row["revision_digest"],
                        "actor": actor,
                        "expected_version": expected_mission_version,
                    }
                )
                self.missions._insert_command(
                    mission_id=run.mission_id,
                    command_id=wait_command_id,
                    command_type="verified_proposal_waiting",
                    actor=actor,
                    expected_version=expected_mission_version,
                    request_digest=transition_request_digest,
                    result_version=int(mission_result_version),
                )
            self.storage._event(
                "autonomous_proposal.ready"
                if status is ProposalVerificationStatus.READY
                else "autonomous_proposal.blocked",
                "autonomous_mission",
                run.mission_id,
                {
                    "verification_id": report_id,
                    "pipeline_run_id": run.id,
                    "revision_id": revision_row["id"],
                    "revision_digest": revision_row["revision_digest"],
                    "canonical_digest": revision_row["revision_digest"],
                    "presentation_digest": presentation_digest,
                    "status": status.value,
                    "finding_codes": [
                        finding.code for finding in deduplicated
                    ],
                    "actor": actor,
                    "mission_result_version": mission_result_version,
                },
            )
            if status is ProposalVerificationStatus.READY:
                self.storage._event(
                    "autonomous_mission.waiting_for_backlog_approval",
                    "autonomous_mission",
                    run.mission_id,
                    {
                        "verification_id": report_id,
                        "previous_phase": current["phase"],
                        "resulting_phase": MissionPhase.WAITING_FOR_BACKLOG_APPROVAL.value,
                        "version": mission_result_version,
                        "actor": actor,
                    },
                )
        return self.get(report_id)

    @classmethod
    def _report_binding(cls, row: Any) -> dict[str, Any]:
        return {
            "mission_id": int(row["mission_id"]),
            "pipeline_run_id": int(row["pipeline_run_id"]),
            "completion_id": int(row["completion_id"]),
            "completion_digest": str(row["completion_digest"]),
            "manifest_id": int(row["manifest_id"]),
            "manifest_digest": str(row["manifest_digest"]),
            "revision_id": int(row["revision_id"]),
            "revision_digest": str(row["revision_digest"]),
            "source_id": int(row["source_id"]),
            "source_digest": str(row["source_digest"]),
            "verifier_version": str(row["verifier_version"]),
            "status": str(row["status"]),
            "canonical_digest": str(row["canonical_digest"]),
            "presentation_digest": str(row["presentation_digest"]),
            "checks": json.loads(row["checks_json"]),
            "findings": json.loads(row["findings_json"]),
            "reviewer_findings": json.loads(row["reviewer_findings_json"]),
            "human_visible_findings": json.loads(
                row["human_visible_findings_json"]
            ),
            "verified_by": str(row["verified_by"]),
            "expected_mission_version": int(row["expected_mission_version"]),
            "mission_result_version": (
                int(row["mission_result_version"])
                if row["mission_result_version"] is not None
                else None
            ),
            "command_id": str(row["command_id"]),
            "request_digest": str(row["request_digest"]),
            "created_at": str(row["created_at"]),
        }

    def get(self, verification_id: int) -> ProposalReadinessReport:
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_proposal_verifications WHERE id=?",
            (verification_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown proposal verification: {verification_id}")
        canonical_snapshot = json.loads(row["canonical_snapshot_json"])
        presentation = json.loads(row["presentation_json"])
        if self._digest(canonical_snapshot) != row["canonical_digest"]:
            raise RuntimeError("Proposal canonical digest is corrupt")
        if row["canonical_digest"] != row["revision_digest"]:
            raise RuntimeError("Proposal canonical digest differs from revision digest")
        if self._digest(presentation) != row["presentation_digest"]:
            raise RuntimeError("Proposal presentation digest is corrupt")
        if self._digest(self._report_binding(row)) != row["report_digest"]:
            raise RuntimeError("Proposal verification report digest is corrupt")
        return ProposalReadinessReport(
            id=int(row["id"]),
            identity=str(row["identity"]),
            mission_id=int(row["mission_id"]),
            pipeline_run_id=int(row["pipeline_run_id"]),
            completion_id=int(row["completion_id"]),
            completion_digest=str(row["completion_digest"]),
            manifest_id=int(row["manifest_id"]),
            manifest_digest=str(row["manifest_digest"]),
            revision_id=int(row["revision_id"]),
            revision_digest=str(row["revision_digest"]),
            source_id=int(row["source_id"]),
            source_digest=str(row["source_digest"]),
            verifier_version=str(row["verifier_version"]),
            status=ProposalVerificationStatus(row["status"]),
            canonical_snapshot=canonical_snapshot,
            canonical_digest=str(row["canonical_digest"]),
            presentation=presentation,
            presentation_digest=str(row["presentation_digest"]),
            checks=tuple(json.loads(row["checks_json"])),
            findings=tuple(json.loads(row["findings_json"])),
            reviewer_findings=tuple(json.loads(row["reviewer_findings_json"])),
            human_visible_findings=tuple(
                json.loads(row["human_visible_findings_json"])
            ),
            verified_by=str(row["verified_by"]),
            expected_mission_version=int(row["expected_mission_version"]),
            mission_result_version=(
                int(row["mission_result_version"])
                if row["mission_result_version"] is not None
                else None
            ),
            command_id=str(row["command_id"]),
            request_digest=str(row["request_digest"]),
            report_digest=str(row["report_digest"]),
            created_at=str(row["created_at"]),
        )

    def reports(self, mission_id: int) -> tuple[ProposalReadinessReport, ...]:
        return tuple(
            self.get(int(row["id"]))
            for row in self.storage.db.execute(
                "SELECT id FROM autonomous_proposal_verifications "
                "WHERE mission_id=? ORDER BY id",
                (mission_id,),
            )
        )

    def current_ready_report(self, mission_id: int) -> ProposalReadinessReport:
        row = self.storage.db.execute(
            """SELECT id FROM autonomous_proposal_verifications
                WHERE mission_id=? AND status='READY' ORDER BY id DESC LIMIT 1""",
            (mission_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Mission {mission_id} has no ready proposal report")
        return self.get(int(row["id"]))
