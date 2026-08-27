"""Initial provider-neutral software engineering role pack."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from .roles import ContractField, RoleDefinition, RoleRegistry
from .storage import SQLiteStorage


PACK_ID = "software-engineering"
PACK_VERSION = "1.0.0"
SOFTWARE_ROLE_IDS = (
    "requirements_backlog_steward",
    "solution_architect",
    "implementation_worker",
    "deterministic_test_runner",
    "independent_code_reviewer",
    "security_reviewer",
    "release_integration_agent",
    "policy_guardian",
)
AUTONOMOUS_PLANNING_PACK_ID = "autonomous-planning"
AUTONOMOUS_PLANNING_PACK_VERSION = "1.0.0"
AUTONOMOUS_PLANNING_ROLE_IDS = (
    "mission_analyst",
    "product_requirements_analyst",
    "software_architect",
    "backlog_planner",
    "backlog_reviewer",
)


def _field(name: str, kind: str = "object") -> tuple[ContractField, ...]:
    return (ContractField(name, kind),)


def software_role_definitions() -> tuple[RoleDefinition, ...]:
    shared_limits = (("max_cost", 10), ("max_seconds", 1800), ("max_tokens", 100000))
    return (
        RoleDefinition(
            "requirements_backlog_steward", PACK_VERSION,
            "Turn approved requirements into measurable dependency-aware work.",
            ("Preserve source authority", "Define acceptance criteria"),
            _field("requirements"), _field("backlog"),
            ("read_file",), ("create_work_item", "read_project"), shared_limits,
            _field("backlog_digest", "string"), ("policy_guardian",),
        ),
        RoleDefinition(
            "solution_architect", PACK_VERSION,
            "Produce bounded architecture decisions without implementation authority.",
            ("Design interfaces", "Record tradeoffs"),
            _field("approved_backlog"), _field("architecture"),
            ("read_file",), ("create_artifact", "read_project"), shared_limits,
            _field("architecture_digest", "string"), ("policy_guardian",),
        ),
        RoleDefinition(
            "implementation_worker", PACK_VERSION,
            "Implement one scoped candidate inside its leased worktree.",
            ("Modify scoped files", "Return candidate evidence"),
            _field("execution_context"), _field("candidate"),
            ("edit_file", "read_file"), ("read_project", "worktree_write"), shared_limits,
            _field("diff_digest", "string"),
            ("deterministic_test_runner", "independent_code_reviewer", "policy_guardian", "release_integration_agent", "security_reviewer"),
        ),
        RoleDefinition(
            "deterministic_test_runner", PACK_VERSION,
            "Run fixed validators and produce primary deterministic evidence.",
            ("Execute reviewed validator packs",),
            _field("candidate"), _field("validator_results"),
            ("run_validator",), ("read_project", "run_tests"), shared_limits,
            _field("validation_digest", "string"),
            ("implementation_worker", "independent_code_reviewer"),
        ),
        RoleDefinition(
            "independent_code_reviewer", PACK_VERSION,
            "Review candidate and primary evidence independently from production.",
            ("Issue criterion verdicts", "Record dissent"),
            _field("review_packet"), _field("criterion_verdicts"),
            ("read_file",), ("read_project", "review_evidence"), shared_limits,
            _field("review_digest", "string"),
            ("deterministic_test_runner", "implementation_worker", "release_integration_agent"),
        ),
        RoleDefinition(
            "security_reviewer", PACK_VERSION,
            "Assess candidate security evidence without implementation authority.",
            ("Review threats", "Issue security verdict"),
            _field("security_packet"), _field("security_verdict"),
            ("read_file",), ("read_project", "review_security"), shared_limits,
            _field("security_digest", "string"), ("implementation_worker",),
        ),
        RoleDefinition(
            "release_integration_agent", PACK_VERSION,
            "Prepare integration operations only for Founder-approved candidates.",
            ("Verify candidate approval", "Prepare release plan"),
            _field("approved_candidate"), _field("release_plan"),
            ("read_file",), ("plan_release", "read_project"), shared_limits,
            _field("release_plan_digest", "string"),
            ("implementation_worker", "independent_code_reviewer"),
        ),
        RoleDefinition(
            "policy_guardian", PACK_VERSION,
            "Verify policy and duty separation without producing delivery artifacts.",
            ("Evaluate authority", "Deny incompatible duties"),
            _field("policy_request"), _field("policy_decision"),
            ("read_file",), ("evaluate_policy", "read_project"), shared_limits,
            _field("policy_digest", "string"),
            ("implementation_worker", "requirements_backlog_steward", "solution_architect"),
        ),
    )


def _fields(*values: tuple[str, str]) -> tuple[ContractField, ...]:
    return tuple(ContractField(name, kind) for name, kind in values)


def autonomous_planning_role_definitions() -> tuple[RoleDefinition, ...]:
    """Logical read-only planning roles; sessions are assigned separately."""

    limits = (
        ("max_context_bytes", 50_000),
        ("max_context_tokens", 12_500),
        ("max_output_tokens", 8_000),
        ("max_seconds", 600),
    )
    producer_incompatibilities = (
        "implementation_worker",
        "release_integration_agent",
    )
    return (
        RoleDefinition(
            "mission_analyst",
            AUTONOMOUS_PLANNING_PACK_VERSION,
            "Interpret the exact mission source without decomposing implementation work.",
            (
                "Identify outcomes, constraints, ambiguities, and source traceability",
                "Preserve authoritative wording and surface unanswered questions",
            ),
            _fields(
                ("planning_request", "object"),
                ("specification_source", "object"),
            ),
            _fields(("mission_analysis", "object")),
            ("read_file",),
            ("create_artifact", "read_project"),
            limits,
            _fields(("analysis_digest", "string"), ("source_trace", "array")),
            producer_incompatibilities,
        ),
        RoleDefinition(
            "product_requirements_analyst",
            AUTONOMOUS_PLANNING_PACK_VERSION,
            "Normalize measurable product requirements without architecture authority.",
            (
                "Derive functional and non-functional requirements",
                "Define measurable outcomes and retain source references",
            ),
            _fields(
                ("mission_analysis", "object"),
                ("specification_source", "object"),
            ),
            _fields(("normalized_requirements", "object")),
            ("read_file",),
            ("create_artifact", "read_project"),
            limits,
            _fields(
                ("requirements_digest", "string"),
                ("traceability_matrix", "array"),
            ),
            producer_incompatibilities,
        ),
        RoleDefinition(
            "software_architect",
            AUTONOMOUS_PLANNING_PACK_VERSION,
            "Design a bounded implementation architecture without coding authority.",
            (
                "Define components, interfaces, infrastructure, and tradeoffs",
                "Order prerequisite infrastructure before dependent development",
            ),
            _fields(
                ("normalized_requirements", "object"),
                ("specification_source", "object"),
            ),
            _fields(("architecture_proposal", "object")),
            ("read_file",),
            ("create_artifact", "read_project"),
            limits,
            _fields(
                ("architecture_digest", "string"),
                ("decision_trace", "array"),
            ),
            producer_incompatibilities,
        ),
        RoleDefinition(
            "backlog_planner",
            AUTONOMOUS_PLANNING_PACK_VERSION,
            "Produce a rich dependency-aware proposal without execution authority.",
            (
                "Create complete epics and executable work items",
                "Bind dependencies, roles, validation, artifacts, and Definition of Done",
            ),
            _fields(
                ("architecture_proposal", "object"),
                ("normalized_requirements", "object"),
            ),
            _fields(("backlog_proposal", "object")),
            ("read_file",),
            ("create_artifact", "propose_backlog", "read_project"),
            limits,
            _fields(
                ("backlog_digest", "string"),
                ("dependency_evidence", "array"),
            ),
            (
                "backlog_reviewer",
                "implementation_worker",
                "release_integration_agent",
            ),
        ),
        RoleDefinition(
            "backlog_reviewer",
            AUTONOMOUS_PLANNING_PACK_VERSION,
            "Review planning artifacts independently and issue non-executable findings.",
            (
                "Check completeness, traceability, measurability, and dependency safety",
                "Retain findings and an explicit readiness verdict",
            ),
            _fields(
                ("architecture_proposal", "object"),
                ("backlog_proposal", "object"),
                ("normalized_requirements", "object"),
                ("specification_source", "object"),
            ),
            _fields(("review_report", "object")),
            ("read_file",),
            ("create_artifact", "read_project", "review_evidence"),
            limits,
            _fields(("findings", "array"), ("review_digest", "string")),
            (
                "backlog_planner",
                "implementation_worker",
                "release_integration_agent",
            ),
        ),
    )


@dataclass(frozen=True)
class SoftwareRolePack:
    id: int
    version: str
    role_ids: tuple[str, ...]
    manifest_digest: str


class SoftwareEngineeringRolePack:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage
        self.roles = RoleRegistry(storage)

    def install(self) -> SoftwareRolePack:
        definitions = software_role_definitions()
        if tuple(role.id for role in definitions) != SOFTWARE_ROLE_IDS:
            raise RuntimeError("Software role pack role order is invalid")
        role_definition_ids = [self.roles.register(role) for role in definitions]
        manifest = {
            "pack_id": PACK_ID, "version": PACK_VERSION,
            "roles": [
                {"id": role.id, "version": role.version, "definition_id": definition_id}
                for role, definition_id in zip(definitions, role_definition_ids, strict=True)
            ],
        }
        payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        existing = self.storage.db.execute(
            "SELECT * FROM software_role_packs WHERE pack_id=? AND version=?",
            (PACK_ID, PACK_VERSION),
        ).fetchone()
        if existing:
            if existing["manifest_digest"] != digest:
                raise ValueError("Software role pack version has another manifest")
            return SoftwareRolePack(int(existing["id"]), PACK_VERSION, SOFTWARE_ROLE_IDS, digest)
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO software_role_packs(
                       identity,pack_id,version,manifest_json,manifest_digest
                   ) VALUES(?,?,?,?,?)""",
                (self.storage._identity("software-role-pack"), PACK_ID, PACK_VERSION, payload, digest),
            )
            pack_id = int(cursor.lastrowid)
            self.storage._event("software.role_pack.installed", "software_role_pack", pack_id, {
                "pack_id": PACK_ID, "version": PACK_VERSION,
                "role_ids": SOFTWARE_ROLE_IDS, "manifest_digest": digest,
            })
        return SoftwareRolePack(pack_id, PACK_VERSION, SOFTWARE_ROLE_IDS, digest)

    def authorize_release(self, candidate_id: int, *, release_agent_id: str) -> int:
        pack = self.install()
        candidate = self.storage.db.execute(
            """SELECT c.id,d.id AS delivery_id,d.status AS delivery_status,
                      d.github_plan_id,d.founder_gate_id,g.status AS founder_status
                 FROM candidate_change_artifacts c
                 LEFT JOIN coding_delivery_runs d ON d.candidate_id=c.id
                 LEFT JOIN approval_gates g ON g.id=d.founder_gate_id
                WHERE c.id=? ORDER BY d.id DESC LIMIT 1""",
            (candidate_id,),
        ).fetchone()
        if not candidate:
            raise KeyError(f"Unknown candidate artifact: {candidate_id}")
        if (
            candidate["delivery_status"] != "pr_ready"
            or candidate["founder_status"] != "approved"
            or candidate["github_plan_id"] is None
        ):
            raise PermissionError("Release Agent requires a Founder-approved PR-ready candidate artifact")
        existing = self.storage.db.execute(
            """SELECT id FROM release_candidate_authorizations
                WHERE pack_id=? AND candidate_id=? AND release_agent_id=?""",
            (pack.id, candidate_id, release_agent_id),
        ).fetchone()
        if existing:
            return int(existing["id"])
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO release_candidate_authorizations(
                       identity,pack_id,candidate_id,delivery_id,founder_gate_id,
                       github_plan_id,release_agent_id
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("release-candidate-authorization"), pack.id,
                    candidate_id, candidate["delivery_id"], candidate["founder_gate_id"],
                    candidate["github_plan_id"], release_agent_id,
                ),
            )
            authorization_id = int(cursor.lastrowid)
            self.storage._event("release.candidate.authorized", "release_authorization", authorization_id, {
                "candidate_id": candidate_id, "delivery_id": candidate["delivery_id"],
                "release_agent_id": release_agent_id,
            })
        return authorization_id


class AutonomousPlanningRolePack:
    """Install the five provider-neutral Autonomous Mission planning roles."""

    def __init__(self, storage: SQLiteStorage):
        self.storage = storage
        self.roles = RoleRegistry(storage)

    def install(self) -> SoftwareRolePack:
        definitions = autonomous_planning_role_definitions()
        if tuple(role.id for role in definitions) != AUTONOMOUS_PLANNING_ROLE_IDS:
            raise RuntimeError("Autonomous planning role order is invalid")
        registered: list[tuple[RoleDefinition, int, str]] = []
        for role in definitions:
            definition_id = self.roles.register(role)
            row = self.storage.db.execute(
                "SELECT contract_digest FROM role_definitions WHERE id=?",
                (definition_id,),
            ).fetchone()
            registered.append((role, definition_id, str(row["contract_digest"])))
        manifest = {
            "pack_id": AUTONOMOUS_PLANNING_PACK_ID,
            "version": AUTONOMOUS_PLANNING_PACK_VERSION,
            "roles": [
                {
                    "id": role.id,
                    "version": role.version,
                    "definition_id": definition_id,
                    "contract_digest": contract_digest,
                }
                for role, definition_id, contract_digest in registered
            ],
            "session_policy": {
                "fresh_context_per_role": True,
                "session_reuse": False,
                "transcript_reuse": False,
                "tool_authority": "read-only",
            },
        }
        payload = json.dumps(
            manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        existing = self.storage.db.execute(
            "SELECT * FROM software_role_packs WHERE pack_id=? AND version=?",
            (AUTONOMOUS_PLANNING_PACK_ID, AUTONOMOUS_PLANNING_PACK_VERSION),
        ).fetchone()
        if existing:
            if existing["manifest_digest"] != digest:
                raise ValueError("Autonomous planning role pack version has another manifest")
            return SoftwareRolePack(
                int(existing["id"]),
                AUTONOMOUS_PLANNING_PACK_VERSION,
                AUTONOMOUS_PLANNING_ROLE_IDS,
                digest,
            )
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO software_role_packs(
                       identity,pack_id,version,manifest_json,manifest_digest
                   ) VALUES(?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-planning-role-pack"),
                    AUTONOMOUS_PLANNING_PACK_ID,
                    AUTONOMOUS_PLANNING_PACK_VERSION,
                    payload,
                    digest,
                ),
            )
            pack_id = int(cursor.lastrowid)
            self.storage._event(
                "autonomous_planning.role_pack.installed",
                "software_role_pack",
                pack_id,
                {
                    "pack_id": AUTONOMOUS_PLANNING_PACK_ID,
                    "version": AUTONOMOUS_PLANNING_PACK_VERSION,
                    "role_ids": AUTONOMOUS_PLANNING_ROLE_IDS,
                    "manifest_digest": digest,
                },
            )
        return SoftwareRolePack(
            pack_id,
            AUTONOMOUS_PLANNING_PACK_VERSION,
            AUTONOMOUS_PLANNING_ROLE_IDS,
            digest,
        )
