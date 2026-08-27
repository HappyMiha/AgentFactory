"""Planning-role assignment manifests and fresh bounded context envelopes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .autonomous_mission import (
    AutonomousMissionService,
    MissionDisposition,
    MissionPhase,
)
from .mission_intake import AutonomousMissionIntakeService
from .models import ProviderCapabilities
from .roles import RoleDefinition, RoleRegistry
from .software_roles import (
    AUTONOMOUS_PLANNING_PACK_VERSION,
    AUTONOMOUS_PLANNING_ROLE_IDS,
    AutonomousPlanningRolePack,
)
from .storage import SQLiteStorage


class PlanningManifestCommandConflictError(ValueError):
    """Raised when a planning idempotency key is reused for other input."""


class PlanningContextLimitError(ValueError):
    """Raised when mandatory planning context cannot fit its reviewed bounds."""


@dataclass(frozen=True)
class RoleModelSelection:
    provider_id: str
    model: str

    def __post_init__(self) -> None:
        provider_id = str(self.provider_id).strip()
        model = str(self.model).strip()
        if not provider_id or not model:
            raise ValueError("Role provider and model are required")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "model", model)


@dataclass(frozen=True)
class PlanningRoleAssignment:
    role_id: str
    role_version: str
    role_definition_id: int
    role_contract_digest: str
    provider_id: str
    model: str
    logical_agent_id: str
    invocation_order: int
    inputs: tuple[dict[str, Any], ...]
    outputs: tuple[dict[str, Any], ...]
    evidence: tuple[dict[str, Any], ...]
    tools: tuple[str, ...]
    permissions: tuple[str, ...]
    limits: tuple[tuple[str, float], ...]
    incompatible_duties: tuple[str, ...]
    provider_capabilities: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlanningRoleModelManifest:
    id: int
    identity: str
    mission_id: int
    specification_source_id: int
    specification_source_digest: str
    proposal_key: str
    role_pack_id: int
    role_pack_digest: str
    default_provider_id: str
    default_model: str
    assignments: tuple[PlanningRoleAssignment, ...]
    context_policy: dict[str, Any]
    manifest_digest: str
    created_by: str
    command_id: str
    request_digest: str
    created_at: str
    stale: bool
    bound_revision_ids: tuple[int, ...]

    def document(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "specification_source_id": self.specification_source_id,
            "specification_source_digest": self.specification_source_digest,
            "proposal_key": self.proposal_key,
            "role_pack_id": self.role_pack_id,
            "role_pack_digest": self.role_pack_digest,
            "default_provider_id": self.default_provider_id,
            "default_model": self.default_model,
            "assignments": [assignment.to_dict() for assignment in self.assignments],
            "context_policy": self.context_policy,
            "created_by": self.created_by,
        }


@dataclass(frozen=True)
class PlanningManifestRevisionBinding:
    id: int
    identity: str
    mission_id: int
    manifest_id: int
    manifest_digest: str
    revision_id: int
    revision_digest: str
    actor: str
    command_id: str
    request_digest: str
    created_at: str


@dataclass(frozen=True)
class PlanningContextEnvelope:
    id: int
    identity: str
    mission_id: int
    manifest_id: int
    role_id: str
    invocation_sequence: int
    context_key: str
    document: dict[str, Any]
    context_digest: str
    byte_count: int
    token_count: int
    read_only: bool
    fresh_session: bool
    created_by: str
    command_id: str
    request_digest: str
    created_at: str


class AutonomousPlanningService:
    """Resolve one or many local models into five isolated logical roles."""

    PREAPPROVAL_PHASES = frozenset(
        {
            MissionPhase.DRAFT,
            MissionPhase.SPECIFICATION_ANALYSIS,
            MissionPhase.BACKLOG_GENERATION,
            MissionPhase.WAITING_FOR_BACKLOG_APPROVAL,
        }
    )
    READ_ONLY_TOOLS = frozenset({"read_file"})
    PLANNING_PERMISSIONS = frozenset(
        {
            "create_artifact",
            "propose_backlog",
            "read_project",
            "review_evidence",
        }
    )
    MUTATION_PERMISSIONS = frozenset(
        {
            "environment_bootstrap",
            "git_write",
            "merge",
            "network",
            "push",
            "read_secrets",
            "service_control",
            "tool_use",
            "worktree_write",
            "write_project",
        }
    )

    def __init__(
        self,
        storage: SQLiteStorage,
        provider_capabilities: Mapping[str, ProviderCapabilities] | None = None,
    ):
        self.storage = storage
        self.missions = AutonomousMissionService(storage)
        self.intake = AutonomousMissionIntakeService(storage)
        self.roles = RoleRegistry(storage)
        self.pack = AutonomousPlanningRolePack(storage)
        self.provider_capabilities = {
            str(provider_id).strip(): capability
            for provider_id, capability in (provider_capabilities or {}).items()
            if str(provider_id).strip()
        }

    @staticmethod
    def _json(value: Any) -> str:
        try:
            return json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Planning values must be JSON serializable") from exc

    @classmethod
    def _digest(cls, value: Any) -> str:
        return hashlib.sha256(cls._json(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _required(value: str, label: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError(f"{label} is required")
        return normalized

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    @staticmethod
    def _field_documents(
        role: RoleDefinition, field_name: str
    ) -> tuple[dict[str, Any], ...]:
        return tuple(asdict(field) for field in getattr(role, field_name))

    @staticmethod
    def _selection(value: Any) -> RoleModelSelection:
        if isinstance(value, RoleModelSelection):
            return value
        if isinstance(value, Mapping):
            return RoleModelSelection(
                provider_id=str(value.get("provider_id", "")),
                model=str(value.get("model", "")),
            )
        if isinstance(value, (tuple, list)) and len(value) == 2:
            return RoleModelSelection(str(value[0]), str(value[1]))
        raise TypeError("Role model overrides require provider_id and model")

    def _provider(self, provider_id: str) -> ProviderCapabilities:
        return self.provider_capabilities.get(provider_id, ProviderCapabilities())

    def _role_definition_row(self, role_id: str) -> tuple[RoleDefinition, Any]:
        role = self.roles.resolve(role_id, AUTONOMOUS_PLANNING_PACK_VERSION)
        row = self.storage.db.execute(
            """SELECT id,contract_digest FROM role_definitions
                WHERE role_id=? AND version=?""",
            (role_id, AUTONOMOUS_PLANNING_PACK_VERSION),
        ).fetchone()
        if not row:
            raise RuntimeError(f"Planning role {role_id} is not installed")
        return role, row

    def _manifest_replay(
        self, command_id: str, request_digest: str
    ) -> PlanningRoleModelManifest | None:
        row = self.storage.db.execute(
            "SELECT id,request_digest FROM autonomous_planning_manifests WHERE command_id=?",
            (command_id,),
        ).fetchone()
        if not row:
            return None
        if row["request_digest"] != request_digest:
            raise PlanningManifestCommandConflictError(
                f"Planning manifest command {command_id!r} is already bound"
            )
        return self.get_manifest(int(row["id"]))

    def create_manifest(
        self,
        mission_id: int,
        *,
        proposal_key: str,
        actor: str,
        command_id: str,
        default_provider_id: str | None = None,
        default_model: str | None = None,
        role_models: Mapping[
            str, RoleModelSelection | Mapping[str, str] | tuple[str, str]
        ]
        | None = None,
        max_context_bytes: int = 50_000,
        max_context_tokens: int = 12_500,
    ) -> PlanningRoleModelManifest:
        proposal_key = self._required(proposal_key, "Proposal key")
        actor = self._required(actor, "Manifest actor")
        command_id = self._required(command_id, "Command id")
        if not 1_024 <= max_context_bytes <= 1_000_000:
            raise ValueError("Planning context bytes must be between 1024 and 1000000")
        if not 256 <= max_context_tokens <= 250_000:
            raise ValueError("Planning context tokens must be between 256 and 250000")
        mission = self.missions.get(mission_id)
        if actor != mission.mission_owner:
            raise PermissionError("Only the mission owner may bind planning models")
        if mission.phase not in self.PREAPPROVAL_PHASES:
            raise PermissionError("Planning manifests are pre-approval only")
        source = self.intake.current_source(mission_id)
        pack = self.pack.install()
        configured_providers = tuple(mission.configuration.local_provider_ids)
        selected_default_provider = (
            str(default_provider_id).strip()
            if default_provider_id is not None
            else configured_providers[0]
            if len(configured_providers) == 1
            else ""
        )
        selected_default_model = (
            str(default_model).strip()
            if default_model is not None
            else str(mission.configuration.default_model or "").strip()
        )
        overrides = {
            str(role_id).strip(): self._selection(selection)
            for role_id, selection in (role_models or {}).items()
        }
        unknown_roles = set(overrides) - set(AUTONOMOUS_PLANNING_ROLE_IDS)
        if unknown_roles:
            raise ValueError(f"Unknown planning role overrides: {sorted(unknown_roles)}")
        context_policy = {
            "schema_version": 1,
            "max_bytes": int(max_context_bytes),
            "max_tokens": int(max_context_tokens),
            "fresh_context_per_role": True,
            "fresh_session_per_invocation": True,
            "session_reuse": False,
            "transcript_reuse": False,
            "tool_authority": "read-only",
            "prior_transcript_allowed": False,
        }
        request = {
            "type": "create_planning_manifest",
            "mission_id": mission_id,
            "specification_source_id": source.id,
            "specification_source_digest": source.source_digest,
            "proposal_key": proposal_key,
            "actor": actor,
            "default_provider_id": selected_default_provider,
            "default_model": selected_default_model,
            "role_models": {
                role_id: asdict(selection)
                for role_id, selection in sorted(overrides.items())
            },
            "context_policy": context_policy,
        }
        request_digest = self._digest(request)
        replay = self._manifest_replay(command_id, request_digest)
        if replay:
            return replay

        assignments: list[PlanningRoleAssignment] = []
        for order, role_id in enumerate(AUTONOMOUS_PLANNING_ROLE_IDS, 1):
            role, role_row = self._role_definition_row(role_id)
            selection = overrides.get(role_id)
            if selection is None:
                role_model = mission.configuration.role_models.get(
                    role_id, selected_default_model
                )
                if not selected_default_provider or not role_model:
                    raise ValueError(
                        f"Planning role {role_id!r} has no default or explicit model assignment"
                    )
                selection = RoleModelSelection(selected_default_provider, role_model)
            if selection.provider_id not in configured_providers:
                raise PermissionError(
                    f"Planning provider {selection.provider_id!r} is outside mission scope"
                )
            capability = self._provider(selection.provider_id)
            if not capability.autonomous_local_eligible:
                raise PermissionError(
                    f"Planning provider {selection.provider_id!r} is not explicitly local"
                )
            if not set(role.tools) <= self.READ_ONLY_TOOLS:
                raise PermissionError(f"Planning role {role_id} requests a mutable tool")
            if (
                not set(role.permissions) <= self.PLANNING_PERMISSIONS
                or set(role.permissions) & self.MUTATION_PERMISSIONS
            ):
                raise PermissionError(
                    f"Planning role {role_id} requests mutation authority"
                )
            assignment = PlanningRoleAssignment(
                role_id=role.id,
                role_version=role.version,
                role_definition_id=int(role_row["id"]),
                role_contract_digest=str(role_row["contract_digest"]),
                provider_id=selection.provider_id,
                model=selection.model,
                logical_agent_id=f"{proposal_key}:{order:02d}:{role.id}",
                invocation_order=order,
                inputs=self._field_documents(role, "inputs"),
                outputs=self._field_documents(role, "outputs"),
                evidence=self._field_documents(role, "evidence"),
                tools=role.tools,
                permissions=role.permissions,
                limits=role.limits,
                incompatible_duties=role.incompatible_duties,
                provider_capabilities=capability.to_dict(),
            )
            assignments.append(assignment)

        pack_row = self.storage.db.execute(
            "SELECT manifest_digest FROM software_role_packs WHERE id=?", (pack.id,)
        ).fetchone()
        manifest_document = {
            "mission_id": mission_id,
            "specification_source_id": source.id,
            "specification_source_digest": source.source_digest,
            "proposal_key": proposal_key,
            "role_pack_id": pack.id,
            "role_pack_digest": str(pack_row["manifest_digest"]),
            "default_provider_id": selected_default_provider,
            "default_model": selected_default_model,
            "assignments": [assignment.to_dict() for assignment in assignments],
            "context_policy": context_policy,
            "created_by": actor,
        }
        manifest_digest = self._digest(manifest_document)
        created_at = self._timestamp()
        with self.storage.db:
            self.storage._begin_immediate()
            replay = self._manifest_replay(command_id, request_digest)
            if replay:
                return replay
            current_mission = self.missions.get(mission_id)
            current_source = self.intake.current_source(mission_id)
            if (
                current_mission.phase not in self.PREAPPROVAL_PHASES
                or current_source.id != source.id
            ):
                raise ValueError("Mission planning source changed before manifest commit")
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_planning_manifests(
                       identity,mission_id,specification_source_id,
                       specification_source_digest,proposal_key,role_pack_id,
                       default_provider_id,default_model,
                       assignments_json,context_policy_json,manifest_digest,
                       created_by,command_id,request_digest,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-planning-manifest"),
                    mission_id,
                    source.id,
                    source.source_digest,
                    proposal_key,
                    pack.id,
                    selected_default_provider,
                    selected_default_model,
                    self._json([assignment.to_dict() for assignment in assignments]),
                    self._json(context_policy),
                    manifest_digest,
                    actor,
                    command_id,
                    request_digest,
                    created_at,
                ),
            )
            manifest_id = int(cursor.lastrowid)
            self.storage._event(
                "autonomous_planning.manifest_created",
                "autonomous_mission",
                mission_id,
                {
                    "manifest_id": manifest_id,
                    "manifest_digest": manifest_digest,
                    "proposal_key": proposal_key,
                    "specification_source_id": source.id,
                    "role_assignments": [
                        {
                            "role_id": assignment.role_id,
                            "provider_id": assignment.provider_id,
                            "model": assignment.model,
                            "logical_agent_id": assignment.logical_agent_id,
                        }
                        for assignment in assignments
                    ],
                    "actor": actor,
                },
            )
        return self.get_manifest(manifest_id)

    @staticmethod
    def _assignment(document: dict[str, Any]) -> PlanningRoleAssignment:
        return PlanningRoleAssignment(
            role_id=str(document["role_id"]),
            role_version=str(document["role_version"]),
            role_definition_id=int(document["role_definition_id"]),
            role_contract_digest=str(document["role_contract_digest"]),
            provider_id=str(document["provider_id"]),
            model=str(document["model"]),
            logical_agent_id=str(document["logical_agent_id"]),
            invocation_order=int(document["invocation_order"]),
            inputs=tuple(document["inputs"]),
            outputs=tuple(document["outputs"]),
            evidence=tuple(document["evidence"]),
            tools=tuple(document["tools"]),
            permissions=tuple(document["permissions"]),
            limits=tuple((str(key), float(value)) for key, value in document["limits"]),
            incompatible_duties=tuple(document["incompatible_duties"]),
            provider_capabilities=dict(document["provider_capabilities"]),
        )

    def get_manifest(self, manifest_id: int) -> PlanningRoleModelManifest:
        row = self.storage.db.execute(
            """SELECT p.*,pack.manifest_digest AS role_pack_digest,
                      h.source_id AS current_source_id
                 FROM autonomous_planning_manifests p
                 JOIN software_role_packs pack ON pack.id=p.role_pack_id
                 LEFT JOIN autonomous_mission_specification_heads h
                   ON h.mission_id=p.mission_id
                WHERE p.id=?""",
            (manifest_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown Autonomous Planning manifest: {manifest_id}")
        assignments = tuple(
            self._assignment(document)
            for document in json.loads(row["assignments_json"])
        )
        bindings = tuple(
            int(binding["revision_id"])
            for binding in self.storage.db.execute(
                """SELECT revision_id
                     FROM autonomous_planning_manifest_revision_bindings
                    WHERE manifest_id=? ORDER BY id""",
                (manifest_id,),
            )
        )
        result = PlanningRoleModelManifest(
            id=int(row["id"]),
            identity=str(row["identity"]),
            mission_id=int(row["mission_id"]),
            specification_source_id=int(row["specification_source_id"]),
            specification_source_digest=str(row["specification_source_digest"]),
            proposal_key=str(row["proposal_key"]),
            role_pack_id=int(row["role_pack_id"]),
            role_pack_digest=str(row["role_pack_digest"]),
            default_provider_id=str(row["default_provider_id"]),
            default_model=str(row["default_model"]),
            assignments=assignments,
            context_policy=json.loads(row["context_policy_json"]),
            manifest_digest=str(row["manifest_digest"]),
            created_by=str(row["created_by"]),
            command_id=str(row["command_id"]),
            request_digest=str(row["request_digest"]),
            created_at=str(row["created_at"]),
            stale=(
                row["current_source_id"] is None
                or int(row["current_source_id"])
                != int(row["specification_source_id"])
            ),
            bound_revision_ids=bindings,
        )
        if self._digest(result.document()) != result.manifest_digest:
            raise RuntimeError("Planning manifest digest no longer matches its document")
        return result

    def manifests(self, mission_id: int) -> tuple[PlanningRoleModelManifest, ...]:
        return tuple(
            self.get_manifest(int(row["id"]))
            for row in self.storage.db.execute(
                """SELECT id FROM autonomous_planning_manifests
                    WHERE mission_id=? ORDER BY id""",
                (mission_id,),
            )
        )

    def bind_revision(
        self,
        manifest_id: int,
        revision_id: int,
        *,
        actor: str,
        command_id: str,
    ) -> PlanningManifestRevisionBinding:
        actor = self._required(actor, "Binding actor")
        command_id = self._required(command_id, "Command id")
        manifest = self.get_manifest(manifest_id)
        mission = self.missions.get(manifest.mission_id)
        if actor != mission.mission_owner:
            raise PermissionError("Only the mission owner may bind a proposal revision")
        if manifest.stale:
            raise PermissionError("A stale planning manifest cannot bind a revision")
        source = self.intake.get_source(manifest.specification_source_id)
        revision = self.storage.db.execute(
            """SELECT id,mission_id,source_sha256,revision_digest
                 FROM autonomous_backlog_revisions WHERE id=?""",
            (revision_id,),
        ).fetchone()
        if not revision or int(revision["mission_id"]) != manifest.mission_id:
            raise ValueError("Backlog revision belongs to another mission")
        if revision["source_sha256"] != source.raw_digest:
            raise ValueError("Backlog revision is based on another specification source")
        if self.storage.db.execute(
            """SELECT 1 FROM autonomous_backlog_revision_invalidations
                WHERE revision_id=?""",
            (revision_id,),
        ).fetchone():
            raise PermissionError("An invalidated backlog revision cannot be bound")
        request = {
            "type": "bind_planning_manifest_revision",
            "manifest_id": manifest_id,
            "manifest_digest": manifest.manifest_digest,
            "revision_id": revision_id,
            "revision_digest": str(revision["revision_digest"]),
            "actor": actor,
        }
        request_digest = self._digest(request)
        existing = self.storage.db.execute(
            """SELECT * FROM autonomous_planning_manifest_revision_bindings
                WHERE command_id=?""",
            (command_id,),
        ).fetchone()
        if existing:
            if existing["request_digest"] != request_digest:
                raise PlanningManifestCommandConflictError(
                    f"Planning binding command {command_id!r} is already bound"
                )
            return self._binding(existing)
        created_at = self._timestamp()
        with self.storage.db:
            self.storage._begin_immediate()
            existing = self.storage.db.execute(
                """SELECT * FROM autonomous_planning_manifest_revision_bindings
                    WHERE command_id=?""",
                (command_id,),
            ).fetchone()
            if existing:
                if existing["request_digest"] != request_digest:
                    raise PlanningManifestCommandConflictError(
                        f"Planning binding command {command_id!r} is already bound"
                    )
                return self._binding(existing)
            if self.get_manifest(manifest_id).stale:
                raise PermissionError("Planning manifest became stale before binding")
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_planning_manifest_revision_bindings(
                       identity,mission_id,manifest_id,manifest_digest,revision_id,
                       revision_digest,actor,command_id,request_digest,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-planning-revision-binding"),
                    manifest.mission_id,
                    manifest_id,
                    manifest.manifest_digest,
                    revision_id,
                    revision["revision_digest"],
                    actor,
                    command_id,
                    request_digest,
                    created_at,
                ),
            )
            binding_id = int(cursor.lastrowid)
            self.storage._event(
                "autonomous_planning.revision_bound",
                "autonomous_mission",
                manifest.mission_id,
                {
                    "manifest_id": manifest_id,
                    "manifest_digest": manifest.manifest_digest,
                    "revision_id": revision_id,
                    "revision_digest": revision["revision_digest"],
                    "actor": actor,
                },
            )
        row = self.storage.db.execute(
            """SELECT * FROM autonomous_planning_manifest_revision_bindings
                WHERE id=?""",
            (binding_id,),
        ).fetchone()
        return self._binding(row)

    @staticmethod
    def _binding(row: Any) -> PlanningManifestRevisionBinding:
        return PlanningManifestRevisionBinding(
            id=int(row["id"]),
            identity=str(row["identity"]),
            mission_id=int(row["mission_id"]),
            manifest_id=int(row["manifest_id"]),
            manifest_digest=str(row["manifest_digest"]),
            revision_id=int(row["revision_id"]),
            revision_digest=str(row["revision_digest"]),
            actor=str(row["actor"]),
            command_id=str(row["command_id"]),
            request_digest=str(row["request_digest"]),
            created_at=str(row["created_at"]),
        )

    def create_context(
        self,
        manifest_id: int,
        role_id: str,
        *,
        actor: str,
        command_id: str,
        upstream_artifacts: tuple[dict[str, Any], ...] = (),
    ) -> PlanningContextEnvelope:
        role_id = self._required(role_id, "Planning role")
        actor = self._required(actor, "Context actor")
        command_id = self._required(command_id, "Command id")
        manifest = self.get_manifest(manifest_id)
        if manifest.stale:
            raise PermissionError("A stale manifest cannot create planning context")
        mission = self.missions.get(manifest.mission_id)
        if (
            mission.phase not in self.PREAPPROVAL_PHASES
            or mission.disposition is not MissionDisposition.RUNNING
        ):
            raise PermissionError("Mission planning is not currently schedulable")
        assignment = next(
            (value for value in manifest.assignments if value.role_id == role_id), None
        )
        if assignment is None:
            raise ValueError(f"Role {role_id!r} is not assigned by this manifest")
        artifacts = tuple(json.loads(self._json(value)) for value in upstream_artifacts)
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise TypeError("Upstream planning artifacts must be objects")
            digest = str(artifact.get("digest", ""))
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ValueError("Upstream planning artifacts require a SHA-256 digest")
        request = {
            "type": "create_planning_context",
            "manifest_id": manifest_id,
            "manifest_digest": manifest.manifest_digest,
            "role_id": role_id,
            "actor": actor,
            "upstream_artifact_digests": [
                artifact["digest"] for artifact in artifacts
            ],
        }
        request_digest = self._digest(request)
        existing = self.storage.db.execute(
            "SELECT * FROM autonomous_planning_contexts WHERE command_id=?",
            (command_id,),
        ).fetchone()
        if existing:
            if existing["request_digest"] != request_digest:
                raise PlanningManifestCommandConflictError(
                    f"Planning context command {command_id!r} is already bound"
                )
            return self._context(existing)
        source = self.intake.get_source(manifest.specification_source_id)
        previous = self.storage.db.execute(
            """SELECT MAX(invocation_sequence) AS sequence
                 FROM autonomous_planning_contexts
                WHERE manifest_id=? AND role_id=?""",
            (manifest_id, role_id),
        ).fetchone()
        sequence = int(previous["sequence"] or 0) + 1
        context_key = (
            f"planning:{manifest.proposal_key}:{role_id}:{sequence:04d}:"
            f"{request_digest[:12]}"
        )
        document = {
            "schema_version": 1,
            "mission_id": manifest.mission_id,
            "proposal_key": manifest.proposal_key,
            "manifest_id": manifest.id,
            "manifest_digest": manifest.manifest_digest,
            "context_key": context_key,
            "invocation_sequence": sequence,
            "role": assignment.to_dict(),
            "specification_source": {
                "id": source.id,
                "version": source.version,
                "source_name": source.source_name,
                "media_type": source.media_type,
                "content": source.content,
                "content_digest": source.content_digest,
                "raw_digest": source.raw_digest,
                "source_digest": source.source_digest,
                "provenance": source.provenance,
            },
            "upstream_artifacts": list(artifacts),
            "isolation": {
                "fresh_session": True,
                "session_parent": None,
                "prior_transcript": None,
                "transcript_reuse": False,
                "context_reuse": False,
            },
            "authority": {
                "read_only_tools": list(assignment.tools),
                "artifact_output_permissions": list(assignment.permissions),
                "repository_mutation": False,
                "environment_mutation": False,
                "external_mutation": False,
            },
        }
        canonical = self._json(document)
        byte_count = len(canonical.encode("utf-8"))
        token_count = (byte_count + 3) // 4
        if (
            byte_count > int(manifest.context_policy["max_bytes"])
            or token_count > int(manifest.context_policy["max_tokens"])
        ):
            raise PlanningContextLimitError(
                "Mandatory planning context exceeds the manifest byte/token limit"
            )
        context_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        created_at = self._timestamp()
        with self.storage.db:
            self.storage._begin_immediate()
            existing = self.storage.db.execute(
                "SELECT * FROM autonomous_planning_contexts WHERE command_id=?",
                (command_id,),
            ).fetchone()
            if existing:
                if existing["request_digest"] != request_digest:
                    raise PlanningManifestCommandConflictError(
                        f"Planning context command {command_id!r} is already bound"
                    )
                return self._context(existing)
            current_manifest = self.get_manifest(manifest_id)
            if current_manifest.stale:
                raise PermissionError("Planning manifest became stale before context commit")
            current_sequence = self.storage.db.execute(
                """SELECT COALESCE(MAX(invocation_sequence),0) AS sequence
                     FROM autonomous_planning_contexts
                    WHERE manifest_id=? AND role_id=?""",
                (manifest_id, role_id),
            ).fetchone()
            if int(current_sequence["sequence"]) + 1 != sequence:
                raise ValueError("Planning context sequence changed before commit")
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_planning_contexts(
                       identity,mission_id,manifest_id,role_id,
                       invocation_sequence,context_key,context_json,context_digest,
                       byte_count,token_count,read_only,fresh_session,created_by,
                       command_id,request_digest,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,1,1,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-planning-context"),
                    manifest.mission_id,
                    manifest_id,
                    role_id,
                    sequence,
                    context_key,
                    canonical,
                    context_digest,
                    byte_count,
                    token_count,
                    actor,
                    command_id,
                    request_digest,
                    created_at,
                ),
            )
            context_id = int(cursor.lastrowid)
            self.storage._event(
                "autonomous_planning.context_created",
                "autonomous_mission",
                manifest.mission_id,
                {
                    "context_id": context_id,
                    "context_key": context_key,
                    "context_digest": context_digest,
                    "manifest_id": manifest_id,
                    "role_id": role_id,
                    "logical_agent_id": assignment.logical_agent_id,
                    "provider_id": assignment.provider_id,
                    "model": assignment.model,
                    "byte_count": byte_count,
                    "token_count": token_count,
                    "fresh_session": True,
                },
            )
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_planning_contexts WHERE id=?", (context_id,)
        ).fetchone()
        return self._context(row)

    def _context(self, row: Any) -> PlanningContextEnvelope:
        document = json.loads(row["context_json"])
        canonical = self._json(document)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if digest != row["context_digest"]:
            raise RuntimeError("Planning context digest is corrupt")
        return PlanningContextEnvelope(
            id=int(row["id"]),
            identity=str(row["identity"]),
            mission_id=int(row["mission_id"]),
            manifest_id=int(row["manifest_id"]),
            role_id=str(row["role_id"]),
            invocation_sequence=int(row["invocation_sequence"]),
            context_key=str(row["context_key"]),
            document=document,
            context_digest=str(row["context_digest"]),
            byte_count=int(row["byte_count"]),
            token_count=int(row["token_count"]),
            read_only=bool(row["read_only"]),
            fresh_session=bool(row["fresh_session"]),
            created_by=str(row["created_by"]),
            command_id=str(row["command_id"]),
            request_digest=str(row["request_digest"]),
            created_at=str(row["created_at"]),
        )

    def contexts(
        self, manifest_id: int, role_id: str | None = None
    ) -> tuple[PlanningContextEnvelope, ...]:
        query = "SELECT * FROM autonomous_planning_contexts WHERE manifest_id=?"
        parameters: tuple[Any, ...] = (manifest_id,)
        if role_id is not None:
            query += " AND role_id=?"
            parameters = (manifest_id, role_id)
        query += " ORDER BY role_id,invocation_sequence"
        return tuple(
            self._context(row)
            for row in self.storage.db.execute(query, parameters)
        )
