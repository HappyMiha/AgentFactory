"""Evidence-backed authority for bounded Autonomous Local execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from .autonomous_mission import (
    AutonomousMission,
    AutonomousMissionService,
    MissionDisposition,
    MissionPhase,
)
from .models import (
    ExecutionAuthorizationMode,
    ProviderCapabilities,
    ProviderExecutionAuthorization,
)
from .storage import SQLiteStorage


class AuthorizationOperation(StrEnum):
    LOCAL_INFERENCE = "LOCAL_INFERENCE"
    LOCAL_TOOL = "LOCAL_TOOL"
    PROJECT_COMMAND = "PROJECT_COMMAND"
    ENVIRONMENT_BOOTSTRAP = "ENVIRONMENT_BOOTSTRAP"
    SERVICE_CONTROL = "SERVICE_CONTROL"
    GIT_WRITE = "GIT_WRITE"
    PLANNING_INFERENCE = "PLANNING_INFERENCE"
    PLANNING_ARTIFACT = "PLANNING_ARTIFACT"
    REMOTE_INFERENCE = "REMOTE_INFERENCE"
    EXTERNAL_MUTATION = "EXTERNAL_MUTATION"
    PROTECTED_INTEGRATION = "PROTECTED_INTEGRATION"
    SECRET_ACCESS = "SECRET_ACCESS"
    MACHINE_GLOBAL_MUTATION = "MACHINE_GLOBAL_MUTATION"


class PlanningAction(StrEnum):
    ANALYZE = "ANALYZE"
    REGENERATE_BACKLOG = "REGENERATE_BACKLOG"


class AuthorizationOutcome(StrEnum):
    ALLOW_AUTONOMOUS = "ALLOW_AUTONOMOUS"
    ALLOW_PLANNING = "ALLOW_PLANNING"
    REQUIRE_STANDARD_GATE = "REQUIRE_STANDARD_GATE"
    DENY = "DENY"


EXECUTION_PHASES = frozenset(
    {
        MissionPhase.APPROVED,
        MissionPhase.ENVIRONMENT_DISCOVERY,
        MissionPhase.ENVIRONMENT_BOOTSTRAP,
        MissionPhase.DEVELOPMENT,
        MissionPhase.VALIDATION,
        MissionPhase.INTEGRATION,
        MissionPhase.FINAL_VALIDATION,
    }
)
PREAPPROVAL_PHASES = frozenset(
    {
        MissionPhase.DRAFT,
        MissionPhase.SPECIFICATION_ANALYSIS,
        MissionPhase.BACKLOG_GENERATION,
        MissionPhase.WAITING_FOR_BACKLOG_APPROVAL,
    }
)
AUTONOMOUS_OPERATIONS = frozenset(
    {
        AuthorizationOperation.LOCAL_INFERENCE,
        AuthorizationOperation.LOCAL_TOOL,
        AuthorizationOperation.PROJECT_COMMAND,
        AuthorizationOperation.ENVIRONMENT_BOOTSTRAP,
        AuthorizationOperation.SERVICE_CONTROL,
        AuthorizationOperation.GIT_WRITE,
    }
)
PLANNING_OPERATIONS = frozenset(
    {
        AuthorizationOperation.PLANNING_INFERENCE,
        AuthorizationOperation.PLANNING_ARTIFACT,
    }
)
STANDARD_GATED_OPERATIONS = frozenset(
    {
        AuthorizationOperation.REMOTE_INFERENCE,
        AuthorizationOperation.EXTERNAL_MUTATION,
        AuthorizationOperation.PROTECTED_INTEGRATION,
    }
)
FORBIDDEN_OPERATIONS = frozenset(
    {
        AuthorizationOperation.SECRET_ACCESS,
        AuthorizationOperation.MACHINE_GLOBAL_MUTATION,
    }
)


@dataclass(frozen=True)
class AutonomousAuthorizationRequest:
    mission_id: int
    operation: AuthorizationOperation | str
    provider_id: str | None = None
    agent_id: str = ""
    task_id: int | None = None
    role: str = ""
    model: str = ""
    backlog_revision_id: int | None = None
    backlog_revision_digest: str | None = None
    execution_epoch_id: int | None = None
    repository_path: str | None = None
    epoch_branch: str | None = None
    tool_profile: str | None = None
    permissions: tuple[str, ...] = ()
    authorization_id: int | None = None
    planning_authorization_id: int | None = None
    planning_request_id: str | None = None
    requested_action: PlanningAction | str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", AuthorizationOperation(self.operation))
        object.__setattr__(
            self,
            "permissions",
            tuple(
                sorted(
                    {
                        str(value).strip()
                        for value in self.permissions
                        if str(value).strip()
                    }
                )
            ),
        )
        if self.requested_action is not None:
            object.__setattr__(
                self, "requested_action", PlanningAction(self.requested_action)
            )

    def canonical(self) -> dict[str, Any]:
        return {
            "mission_id": int(self.mission_id),
            "operation": self.operation.value,
            "provider_id": self.provider_id,
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "role": self.role,
            "model": self.model,
            "backlog_revision_id": self.backlog_revision_id,
            "backlog_revision_digest": self.backlog_revision_digest,
            "execution_epoch_id": self.execution_epoch_id,
            "repository_path": self.repository_path,
            "epoch_branch": self.epoch_branch,
            "tool_profile": self.tool_profile,
            "permissions": list(self.permissions),
            "authorization_id": self.authorization_id,
            "planning_authorization_id": self.planning_authorization_id,
            "planning_request_id": self.planning_request_id,
            "requested_action": (
                self.requested_action.value if self.requested_action else None
            ),
        }


@dataclass(frozen=True)
class AutonomousLocalAuthorization:
    id: int
    identity: str
    mission_id: int
    backlog_revision_id: int
    backlog_revision_digest: str
    execution_epoch_id: int
    epoch_branch: str
    repository_path: str
    provider_ids: tuple[str, ...]
    role_model_manifest: dict[str, Any]
    role_model_manifest_digest: str
    allowed_permissions: tuple[str, ...]
    tool_profile: str
    bootstrap_profile: str
    policy_version: int
    policy_snapshot: dict[str, Any]
    policy_digest: str
    granted_by: str
    command_id: str
    reason: str
    authorization_digest: str
    created_at: str
    revoked: bool
    revocation_reason: str | None

    def binding(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "backlog_revision_id": self.backlog_revision_id,
            "backlog_revision_digest": self.backlog_revision_digest,
            "execution_epoch_id": self.execution_epoch_id,
            "epoch_branch": self.epoch_branch,
            "repository_path": self.repository_path,
            "provider_ids": list(self.provider_ids),
            "role_model_manifest": self.role_model_manifest,
            "role_model_manifest_digest": self.role_model_manifest_digest,
            "allowed_permissions": list(self.allowed_permissions),
            "tool_profile": self.tool_profile,
            "bootstrap_profile": self.bootstrap_profile,
            "policy_version": self.policy_version,
            "policy_snapshot": self.policy_snapshot,
            "policy_digest": self.policy_digest,
            "granted_by": self.granted_by,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AuthorizationRevocation:
    id: int
    identity: str
    authorization_id: int
    mission_id: int
    actor: str
    command_id: str
    reason: str
    created_at: str


@dataclass(frozen=True)
class PlanningAuthorization:
    id: int
    identity: str
    mission_id: int
    planning_request_id: str
    requested_action: PlanningAction
    provider_ids: tuple[str, ...]
    role_models: dict[str, str]
    repository_path: str
    allowed_permissions: tuple[str, ...]
    tool_profile: str
    policy_version: int
    policy_snapshot: dict[str, Any]
    policy_digest: str
    authorized_by: str
    command_id: str
    reason: str
    authorization_digest: str
    created_at: str
    expires_at: str
    closed: bool
    closure_reason: str | None

    def binding(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "planning_request_id": self.planning_request_id,
            "requested_action": self.requested_action.value,
            "provider_ids": list(self.provider_ids),
            "role_models": self.role_models,
            "repository_path": self.repository_path,
            "allowed_permissions": list(self.allowed_permissions),
            "tool_profile": self.tool_profile,
            "policy_version": self.policy_version,
            "policy_snapshot": self.policy_snapshot,
            "policy_digest": self.policy_digest,
            "authorized_by": self.authorized_by,
            "reason": self.reason,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class AuthorizationDecision:
    id: int
    identity: str
    mission_id: int
    request: AutonomousAuthorizationRequest
    request_digest: str
    outcome: AuthorizationOutcome
    reason: str
    authority_valid: bool
    autonomous_authorization_id: int | None
    planning_authorization_id: int | None
    policy_version: int
    policy_digest: str
    evidence: dict[str, Any]
    evidence_digest: str
    decision_digest: str
    created_at: str


class AuthorizationCommandConflictError(ValueError):
    """Raised when an authorization idempotency key is rebound."""


class AutonomousAuthorizationService:
    """Resolve bounded mission capabilities without changing standard policy gates."""

    RESOLVER_SCHEMA_VERSION = 1
    DENIED_PERMISSIONS = frozenset(
        {
            "bypass_policy",
            "final_approval",
            "merge",
            "push",
            "close_issue",
            "read_secrets",
            "arbitrary_network",
            "machine_global_write",
            "protected_branch_write",
        }
    )
    DEFAULT_AUTONOMOUS_PERMISSIONS = frozenset(
        {
            "read_project",
            "create_artifact",
            "structured_artifacts",
            "execute_provider",
            "propose_code",
            "worktree_write",
            "write_project",
            "tool_use",
            "run_tests",
            "git_write",
            "environment_bootstrap",
            "service_control",
            "review_artifact",
            "issue_verdict",
        }
    )
    PLANNING_PERMISSIONS = frozenset(
        {
            "read_project",
            "create_artifact",
            "structured_artifacts",
            "propose_backlog",
            "execute_provider",
            "review_evidence",
        }
    )
    OPERATION_PERMISSION = {
        AuthorizationOperation.LOCAL_INFERENCE: "execute_provider",
        AuthorizationOperation.LOCAL_TOOL: "tool_use",
        AuthorizationOperation.PROJECT_COMMAND: "run_tests",
        AuthorizationOperation.ENVIRONMENT_BOOTSTRAP: "environment_bootstrap",
        AuthorizationOperation.SERVICE_CONTROL: "service_control",
        AuthorizationOperation.GIT_WRITE: "git_write",
        AuthorizationOperation.PLANNING_INFERENCE: "execute_provider",
        AuthorizationOperation.PLANNING_ARTIFACT: "create_artifact",
    }

    def __init__(
        self,
        storage: SQLiteStorage,
        provider_capabilities: Mapping[str, ProviderCapabilities] | None = None,
    ):
        self.storage = storage
        self.missions = AutonomousMissionService(storage)
        self.provider_capabilities = {
            str(provider_id).strip(): capabilities
            for provider_id, capabilities in (provider_capabilities or {}).items()
            if str(provider_id).strip()
        }

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
    def _path(value: str, label: str = "Repository path") -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError(f"{label} is required")
        return str(Path(normalized).expanduser().resolve())

    @classmethod
    def _same_path(cls, value: str | None, expected: str) -> bool:
        if value is None:
            return False
        try:
            return cls._path(value) == expected
        except (OSError, ValueError):
            return False

    @staticmethod
    def _ids(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        normalized = tuple(sorted({str(value).strip() for value in values}))
        if not normalized or any(not value for value in normalized):
            raise ValueError("At least one provider id is required")
        return normalized

    @staticmethod
    def _permissions(values: tuple[str, ...] | list[str] | frozenset[str]) -> tuple[str, ...]:
        normalized = tuple(sorted({str(value).strip() for value in values}))
        if not normalized or any(not value for value in normalized):
            raise ValueError("At least one permission is required")
        return normalized

    @staticmethod
    def _optional_id(value: Any) -> int | None:
        return int(value) if value is not None else None

    def _capability(self, provider_id: str) -> ProviderCapabilities:
        return self.provider_capabilities.get(provider_id, ProviderCapabilities())

    def _policy_snapshot(self, provider_ids: tuple[str, ...]) -> dict[str, Any]:
        state = self.storage.policy_state()
        return {
            "resolver_schema_version": self.RESOLVER_SCHEMA_VERSION,
            "policy_state": {
                "version": int(state["version"]),
                "emergency_stop": bool(state["emergency_stop"]),
                "reason": str(state["reason"]),
                "actor": str(state["actor"]),
            },
            "provider_capabilities": {
                provider_id: self._capability(provider_id).to_dict()
                for provider_id in provider_ids
            },
            "denied_permissions": sorted(self.DENIED_PERMISSIONS),
        }

    @staticmethod
    def _role_manifest(mission: AutonomousMission) -> dict[str, Any]:
        return {
            "default_model": mission.configuration.default_model,
            "role_models": dict(sorted(mission.configuration.role_models.items())),
        }

    @staticmethod
    def _model_for(manifest: dict[str, Any], role: str) -> str | None:
        role_models = manifest.get("role_models", {})
        if role in role_models:
            return str(role_models[role])
        return None

    @staticmethod
    def _bootstrap_profile(mission: AutonomousMission) -> str:
        if mission.configuration.automatic_environment_bootstrap:
            return "autonomous-local-bootstrap-v1"
        return "bootstrap-disabled"

    def _assert_owner(self, mission: AutonomousMission, actor: str) -> str:
        actor = self._required(actor, "Authorization actor")
        if actor != mission.mission_owner:
            raise PermissionError("Only the authenticated mission owner may grant authority")
        return actor

    def assert_role_model_profiles(self, provider_ids: tuple[str, ...], role_models: Mapping[str, str]) -> None:
        """Reject a manifest with no compatible configured route before approval."""
        for role, model in role_models.items():
            errors = [self._capability(provider).role_model_error(role, model) for provider in provider_ids]
            if not errors or all(error is not None for error in errors):
                detail = "; ".join(error for error in errors if error is not None)
                raise PermissionError(f"No configured provider supports role {role!r}: {detail}")

    def _assert_local_providers(self, provider_ids: tuple[str, ...]) -> None:
        ineligible = [
            provider_id
            for provider_id in provider_ids
            if not self._capability(provider_id).autonomous_local_eligible
        ]
        if ineligible:
            raise PermissionError(
                "Autonomous authority requires explicitly LOCAL text-generation "
                f"providers: {', '.join(ineligible)}"
            )

    def _command_replay(
        self, command_id: str, command_type: str, request_digest: str
    ) -> dict[str, Any] | None:
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_authorization_commands WHERE command_id=?",
            (command_id,),
        ).fetchone()
        if not row:
            return None
        if row["command_type"] != command_type or row["request_digest"] != request_digest:
            raise AuthorizationCommandConflictError(
                f"Authorization command {command_id!r} is already bound to another request"
            )
        return json.loads(row["result_json"])

    def _record_command(
        self,
        *,
        mission_id: int,
        command_id: str,
        command_type: str,
        actor: str,
        request_digest: str,
        result: dict[str, Any],
        created_at: str,
    ) -> None:
        self.storage.db.execute(
            """INSERT INTO autonomous_authorization_commands(
                   identity,mission_id,command_id,command_type,actor,
                   request_digest,result_json,created_at
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                self.storage._identity("autonomous-authorization-command"),
                mission_id,
                command_id,
                command_type,
                actor,
                request_digest,
                self._json(result),
                created_at,
            ),
        )

    def get_authorization(self, authorization_id: int) -> AutonomousLocalAuthorization:
        row = self.storage.db.execute(
            """SELECT a.*,r.reason AS revocation_reason
                 FROM autonomous_local_authorizations a
                 LEFT JOIN autonomous_authorization_revocations r
                   ON r.authorization_id=a.id
                WHERE a.id=?""",
            (authorization_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown autonomous authorization: {authorization_id}")
        return AutonomousLocalAuthorization(
            id=int(row["id"]),
            identity=str(row["identity"]),
            mission_id=int(row["mission_id"]),
            backlog_revision_id=int(row["backlog_revision_id"]),
            backlog_revision_digest=str(row["backlog_revision_digest"]),
            execution_epoch_id=int(row["execution_epoch_id"]),
            epoch_branch=str(row["epoch_branch"]),
            repository_path=str(row["repository_path"]),
            provider_ids=tuple(json.loads(row["provider_ids_json"])),
            role_model_manifest=json.loads(row["role_model_manifest_json"]),
            role_model_manifest_digest=str(row["role_model_manifest_digest"]),
            allowed_permissions=tuple(json.loads(row["allowed_permissions_json"])),
            tool_profile=str(row["tool_profile"]),
            bootstrap_profile=str(row["bootstrap_profile"]),
            policy_version=int(row["policy_version"]),
            policy_snapshot=json.loads(row["policy_snapshot_json"]),
            policy_digest=str(row["policy_digest"]),
            granted_by=str(row["granted_by"]),
            command_id=str(row["command_id"]),
            reason=str(row["reason"]),
            authorization_digest=str(row["authorization_digest"]),
            created_at=str(row["created_at"]),
            revoked=row["revocation_reason"] is not None,
            revocation_reason=(
                str(row["revocation_reason"])
                if row["revocation_reason"] is not None
                else None
            ),
        )

    def get_planning_authorization(
        self, authorization_id: int
    ) -> PlanningAuthorization:
        row = self.storage.db.execute(
            """SELECT p.*,c.reason AS closure_reason
                 FROM autonomous_planning_authorizations p
                 LEFT JOIN autonomous_planning_authorization_closures c
                   ON c.planning_authorization_id=p.id
                WHERE p.id=?""",
            (authorization_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown planning authorization: {authorization_id}")
        return PlanningAuthorization(
            id=int(row["id"]),
            identity=str(row["identity"]),
            mission_id=int(row["mission_id"]),
            planning_request_id=str(row["planning_request_id"]),
            requested_action=PlanningAction(row["requested_action"]),
            provider_ids=tuple(json.loads(row["provider_ids_json"])),
            role_models=json.loads(row["role_models_json"]),
            repository_path=str(row["repository_path"]),
            allowed_permissions=tuple(json.loads(row["allowed_permissions_json"])),
            tool_profile=str(row["tool_profile"]),
            policy_version=int(row["policy_version"]),
            policy_snapshot=json.loads(row["policy_snapshot_json"]),
            policy_digest=str(row["policy_digest"]),
            authorized_by=str(row["authorized_by"]),
            command_id=str(row["command_id"]),
            reason=str(row["reason"]),
            authorization_digest=str(row["authorization_digest"]),
            created_at=str(row["created_at"]),
            expires_at=str(row["expires_at"]),
            closed=row["closure_reason"] is not None,
            closure_reason=(
                str(row["closure_reason"])
                if row["closure_reason"] is not None
                else None
            ),
        )

    def assert_planning_authority(
        self,
        mission_id: int,
        authorization_id: int,
        *,
        planning_request_id: str,
        requested_action: PlanningAction | str,
        role_models: Mapping[str, str],
        provider_ids: tuple[str, ...],
        actor: str,
    ) -> PlanningAuthorization:
        """Revalidate an explicit bounded planning grant without mutating state."""

        actor = self._required(actor, "Planning actor")
        planning_request_id = self._required(
            planning_request_id, "Planning request id"
        )
        action = PlanningAction(requested_action)
        authorization = self.get_planning_authorization(authorization_id)
        mission = self.missions.get(mission_id)
        normalized_roles = {
            str(role).strip(): str(model).strip()
            for role, model in role_models.items()
        }
        normalized_providers = self._ids(list(provider_ids))
        try:
            expires_at = datetime.fromisoformat(authorization.expires_at)
        except ValueError as exc:
            raise PermissionError(
                "Planning authorization expiry is invalid"
            ) from exc
        current_policy = self._policy_snapshot(authorization.provider_ids)
        checks = {
            "mission": authorization.mission_id == mission_id,
            "owner": actor == mission.mission_owner == authorization.authorized_by,
            "open": not authorization.closed,
            "unexpired": datetime.now(timezone.utc) < expires_at,
            "preapproval": mission.phase in PREAPPROVAL_PHASES,
            "running": mission.disposition is MissionDisposition.RUNNING,
            "request": authorization.planning_request_id == planning_request_id,
            "action": authorization.requested_action is action,
            "roles": authorization.role_models == normalized_roles,
            "providers": set(normalized_providers)
            <= set(authorization.provider_ids),
            "local": all(
                self._capability(provider_id).autonomous_local_eligible
                for provider_id in authorization.provider_ids
            ),
            "repository": self._same_path(
                mission.configuration.repository_path,
                authorization.repository_path,
            ),
            "permissions": set(authorization.allowed_permissions)
            == set(self.PLANNING_PERMISSIONS),
            "tool_profile": authorization.tool_profile
            == "autonomous-local-planning-read-only-v1",
            "integrity": self._digest(authorization.binding())
            == authorization.authorization_digest,
            "policy_version": authorization.policy_version
            == int(current_policy["policy_state"]["version"]),
            "policy_digest": authorization.policy_digest
            == self._digest(current_policy),
            "emergency_stop": not current_policy["policy_state"][
                "emergency_stop"
            ],
        }
        failed = tuple(name for name, passed in checks.items() if not passed)
        if failed:
            raise PermissionError(
                "Bounded planning authority failed revalidation: "
                + ", ".join(failed)
            )
        return authorization

    def grant_execution_authority(
        self,
        mission_id: int,
        *,
        expected_backlog_revision_id: int,
        expected_execution_epoch_id: int,
        actor: str,
        command_id: str,
        reason: str,
        allowed_permissions: tuple[str, ...] | None = None,
    ) -> AutonomousLocalAuthorization:
        command_id = self._required(command_id, "Command id")
        reason = self._required(reason, "Authorization reason")
        request = {
            "type": "grant_execution_authority",
            "mission_id": mission_id,
            "expected_backlog_revision_id": expected_backlog_revision_id,
            "expected_execution_epoch_id": expected_execution_epoch_id,
            "actor": str(actor).strip(),
            "reason": reason,
            "allowed_permissions": (
                sorted(set(allowed_permissions)) if allowed_permissions is not None else None
            ),
        }
        request_digest = self._digest(request)
        replay = self._command_replay(
            command_id, "grant_execution_authority", request_digest
        )
        if replay:
            return self.get_authorization(int(replay["authorization_id"]))

        mission = self.missions.get(mission_id)
        actor = self._assert_owner(mission, actor)
        if mission.phase not in EXECUTION_PHASES:
            raise PermissionError("Autonomous execution authority requires an approved phase")
        if mission.active_backlog_revision_id != expected_backlog_revision_id:
            raise ValueError("Active backlog revision changed before authorization")
        if mission.active_execution_epoch_id != expected_execution_epoch_id:
            raise ValueError("Active execution epoch changed before authorization")

        revision = self.storage.db.execute(
            """SELECT id,revision_number,revision_digest
                 FROM autonomous_backlog_revisions
                WHERE id=? AND mission_id=?""",
            (expected_backlog_revision_id, mission_id),
        ).fetchone()
        epoch = self.storage.db.execute(
            """SELECT id,epoch_branch,base_backlog_revision_id,
                      base_backlog_revision_digest
                 FROM autonomous_mission_execution_epochs
                WHERE id=? AND mission_id=?""",
            (expected_execution_epoch_id, mission_id),
        ).fetchone()
        if not revision or not epoch:
            raise ValueError("Authorization revision or epoch is invalid")
        if (
            int(epoch["base_backlog_revision_id"]) != expected_backlog_revision_id
            or str(epoch["base_backlog_revision_digest"])
            != str(revision["revision_digest"])
        ):
            raise ValueError("Execution epoch is not bound to the active revision")
        approved = self.storage.db.execute(
            """SELECT version,actor,command_id
                 FROM autonomous_mission_state_versions
                WHERE mission_id=? AND phase='APPROVED'
                  AND active_backlog_revision_id=?
                ORDER BY version DESC LIMIT 1""",
            (mission_id, expected_backlog_revision_id),
        ).fetchone()
        revision_authority = self.storage.db.execute(
            """SELECT id FROM autonomous_backlog_revision_authorities
                WHERE mission_id=? AND revision_id=? AND outcome='APPLIED'
                ORDER BY id DESC LIMIT 1""",
            (mission_id, expected_backlog_revision_id),
        ).fetchone()
        if not approved and not revision_authority:
            raise PermissionError(
                "The exact active backlog revision has no durable human authority"
            )
        material = self.storage.db.execute(
            """SELECT id FROM autonomous_backlog_revisions
                WHERE mission_id=? AND origin='AGENT_MATERIAL'
                  AND revision_number>?
                ORDER BY revision_number LIMIT 1""",
            (mission_id, int(revision["revision_number"])),
        ).fetchone()
        if material:
            raise PermissionError("An unapproved agent material revision is pending")

        provider_ids = self._ids(list(mission.configuration.local_provider_ids))
        self._assert_local_providers(provider_ids)
        manifest = self._role_manifest(mission)
        if not manifest["role_models"]:
            raise ValueError("Autonomous authority requires explicit role/model bindings")
        self.assert_role_model_profiles(provider_ids, manifest["role_models"])
        manifest_digest = self._digest(manifest)
        repository_path = self._path(
            mission.configuration.repository_path or "", "Mission repository path"
        )
        permissions = self._permissions(
            allowed_permissions
            if allowed_permissions is not None
            else self.DEFAULT_AUTONOMOUS_PERMISSIONS
        )
        unsupported = set(permissions) - self.DEFAULT_AUTONOMOUS_PERMISSIONS
        forbidden = set(permissions) & self.DENIED_PERMISSIONS
        if unsupported or forbidden:
            raise PermissionError(
                "Autonomous permission set exceeds the reviewed local capability"
            )
        if not mission.configuration.automatic_environment_bootstrap:
            permissions = tuple(
                value for value in permissions if value != "environment_bootstrap"
            )
        if not mission.configuration.automatic_service_recovery:
            permissions = tuple(value for value in permissions if value != "service_control")
        policy_snapshot = self._policy_snapshot(provider_ids)
        if policy_snapshot["policy_state"]["emergency_stop"]:
            raise PermissionError("Emergency stop is active")
        policy_digest = self._digest(policy_snapshot)
        binding = {
            "mission_id": mission_id,
            "backlog_revision_id": expected_backlog_revision_id,
            "backlog_revision_digest": str(revision["revision_digest"]),
            "execution_epoch_id": expected_execution_epoch_id,
            "epoch_branch": str(epoch["epoch_branch"]),
            "repository_path": repository_path,
            "provider_ids": list(provider_ids),
            "role_model_manifest": manifest,
            "role_model_manifest_digest": manifest_digest,
            "allowed_permissions": list(permissions),
            "tool_profile": mission.configuration.allowed_local_tool_profile,
            "bootstrap_profile": self._bootstrap_profile(mission),
            "policy_version": int(policy_snapshot["policy_state"]["version"]),
            "policy_snapshot": policy_snapshot,
            "policy_digest": policy_digest,
            "granted_by": actor,
            "reason": reason,
        }
        authorization_digest = self._digest(binding)
        created_at = self._timestamp()

        with self.storage.db:
            self.storage._begin_immediate()
            replay = self._command_replay(
                command_id, "grant_execution_authority", request_digest
            )
            if replay:
                return self.get_authorization(int(replay["authorization_id"]))
            current = self.missions.get(mission_id)
            if (
                current.active_backlog_revision_id != expected_backlog_revision_id
                or current.active_execution_epoch_id != expected_execution_epoch_id
            ):
                raise ValueError("Mission scope changed before authorization commit")
            if current.phase not in EXECUTION_PHASES:
                raise PermissionError("Mission left its approved execution phase")
            if (
                self._role_manifest(current) != manifest
                or tuple(current.configuration.local_provider_ids) != provider_ids
                or self._path(current.configuration.repository_path or "")
                != repository_path
                or current.configuration.allowed_local_tool_profile
                != mission.configuration.allowed_local_tool_profile
                or self._bootstrap_profile(current)
                != self._bootstrap_profile(mission)
            ):
                raise ValueError("Mission execution configuration changed before commit")
            if self._digest(self._policy_snapshot(provider_ids)) != policy_digest:
                raise PermissionError("Local execution policy changed before commit")
            if self.storage.db.execute(
                """SELECT 1 FROM autonomous_backlog_revisions
                    WHERE mission_id=? AND origin='AGENT_MATERIAL'
                      AND revision_number>?
                    ORDER BY revision_number LIMIT 1""",
                (mission_id, int(revision["revision_number"])),
            ).fetchone():
                raise PermissionError("An unapproved agent material revision is pending")
            current_approved = self.storage.db.execute(
                """SELECT 1 FROM autonomous_mission_state_versions
                    WHERE mission_id=? AND phase='APPROVED'
                      AND active_backlog_revision_id=? LIMIT 1""",
                (mission_id, expected_backlog_revision_id),
            ).fetchone()
            current_revision_authority = self.storage.db.execute(
                """SELECT 1 FROM autonomous_backlog_revision_authorities
                    WHERE mission_id=? AND revision_id=? AND outcome='APPLIED'
                    LIMIT 1""",
                (mission_id, expected_backlog_revision_id),
            ).fetchone()
            if not current_approved and not current_revision_authority:
                raise PermissionError(
                    "Backlog revision authority changed before authorization commit"
                )
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_local_authorizations(
                       identity,mission_id,backlog_revision_id,
                       backlog_revision_digest,execution_epoch_id,epoch_branch,
                       repository_path,provider_ids_json,role_model_manifest_json,
                       role_model_manifest_digest,allowed_permissions_json,
                       tool_profile,bootstrap_profile,policy_version,
                       policy_snapshot_json,policy_digest,granted_by,command_id,
                       reason,authorization_digest,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-local-authorization"),
                    mission_id,
                    expected_backlog_revision_id,
                    revision["revision_digest"],
                    expected_execution_epoch_id,
                    epoch["epoch_branch"],
                    repository_path,
                    self._json(list(provider_ids)),
                    self._json(manifest),
                    manifest_digest,
                    self._json(list(permissions)),
                    mission.configuration.allowed_local_tool_profile,
                    self._bootstrap_profile(mission),
                    binding["policy_version"],
                    self._json(policy_snapshot),
                    policy_digest,
                    actor,
                    command_id,
                    reason,
                    authorization_digest,
                    created_at,
                ),
            )
            authorization_id = int(cursor.lastrowid)
            result = {
                "authorization_id": authorization_id,
                "authorization_digest": authorization_digest,
            }
            self._record_command(
                mission_id=mission_id,
                command_id=command_id,
                command_type="grant_execution_authority",
                actor=actor,
                request_digest=request_digest,
                result=result,
                created_at=created_at,
            )
            self.storage._event(
                "autonomous_authorization.granted",
                "autonomous_mission",
                mission_id,
                {**result, "actor": actor, "reason": reason},
            )
        return self.get_authorization(authorization_id)

    def revoke_execution_authority(
        self,
        authorization_id: int,
        *,
        actor: str,
        command_id: str,
        reason: str,
    ) -> AuthorizationRevocation:
        command_id = self._required(command_id, "Command id")
        reason = self._required(reason, "Revocation reason")
        authorization = self.get_authorization(authorization_id)
        request = {
            "type": "revoke_execution_authority",
            "authorization_id": authorization_id,
            "mission_id": authorization.mission_id,
            "actor": str(actor).strip(),
            "reason": reason,
        }
        request_digest = self._digest(request)
        replay = self._command_replay(
            command_id, "revoke_execution_authority", request_digest
        )
        if replay:
            return self.get_revocation(int(replay["revocation_id"]))
        mission = self.missions.get(authorization.mission_id)
        actor = self._assert_owner(mission, actor)
        if authorization.revoked:
            raise ValueError("Autonomous authorization is already revoked")
        created_at = self._timestamp()
        with self.storage.db:
            self.storage._begin_immediate()
            replay = self._command_replay(
                command_id, "revoke_execution_authority", request_digest
            )
            if replay:
                return self.get_revocation(int(replay["revocation_id"]))
            if self.storage.db.execute(
                "SELECT 1 FROM autonomous_authorization_revocations WHERE authorization_id=?",
                (authorization_id,),
            ).fetchone():
                raise ValueError("Autonomous authorization is already revoked")
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_authorization_revocations(
                       identity,authorization_id,mission_id,actor,command_id,
                       reason,created_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-authorization-revocation"),
                    authorization_id,
                    authorization.mission_id,
                    actor,
                    command_id,
                    reason,
                    created_at,
                ),
            )
            revocation_id = int(cursor.lastrowid)
            self._record_command(
                mission_id=authorization.mission_id,
                command_id=command_id,
                command_type="revoke_execution_authority",
                actor=actor,
                request_digest=request_digest,
                result={"revocation_id": revocation_id},
                created_at=created_at,
            )
            self.storage._event(
                "autonomous_authorization.revoked",
                "autonomous_mission",
                authorization.mission_id,
                {
                    "authorization_id": authorization_id,
                    "revocation_id": revocation_id,
                    "actor": actor,
                    "reason": reason,
                },
            )
        return self.get_revocation(revocation_id)

    def get_revocation(self, revocation_id: int) -> AuthorizationRevocation:
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_authorization_revocations WHERE id=?",
            (revocation_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown authorization revocation: {revocation_id}")
        return AuthorizationRevocation(
            id=int(row["id"]),
            identity=str(row["identity"]),
            authorization_id=int(row["authorization_id"]),
            mission_id=int(row["mission_id"]),
            actor=str(row["actor"]),
            command_id=str(row["command_id"]),
            reason=str(row["reason"]),
            created_at=str(row["created_at"]),
        )

    def grant_planning_authority(
        self,
        mission_id: int,
        *,
        planning_request_id: str,
        requested_action: PlanningAction | str,
        role_models: Mapping[str, str],
        actor: str,
        command_id: str,
        reason: str,
        ttl_seconds: int = 3600,
        provider_ids: tuple[str, ...] | None = None,
    ) -> PlanningAuthorization:
        planning_request_id = self._required(planning_request_id, "Planning request id")
        action = PlanningAction(requested_action)
        command_id = self._required(command_id, "Command id")
        reason = self._required(reason, "Planning authorization reason")
        if ttl_seconds < 1 or ttl_seconds > 86_400:
            raise ValueError("Planning authorization TTL must be between 1 and 86400 seconds")
        normalized_roles = {
            str(role).strip(): str(model).strip() for role, model in role_models.items()
        }
        if not normalized_roles or any(
            not role or not model for role, model in normalized_roles.items()
        ):
            raise ValueError("Planning authorization requires explicit role/model bindings")
        requested_providers = tuple(provider_ids or ())
        request = {
            "type": "grant_planning_authority",
            "mission_id": mission_id,
            "planning_request_id": planning_request_id,
            "requested_action": action.value,
            "role_models": dict(sorted(normalized_roles.items())),
            "provider_ids": sorted(set(requested_providers)) if provider_ids else None,
            "actor": str(actor).strip(),
            "reason": reason,
            "ttl_seconds": ttl_seconds,
        }
        request_digest = self._digest(request)
        replay = self._command_replay(
            command_id, "grant_planning_authority", request_digest
        )
        if replay:
            return self.get_planning_authorization(
                int(replay["planning_authorization_id"])
            )

        mission = self.missions.get(mission_id)
        actor = self._assert_owner(mission, actor)
        if mission.phase not in PREAPPROVAL_PHASES:
            raise PermissionError("Bounded planning authority is pre-approval only")
        providers = self._ids(
            list(provider_ids or mission.configuration.local_provider_ids)
        )
        if not set(providers) <= set(mission.configuration.local_provider_ids):
            raise PermissionError("Planning providers must be in the mission local provider set")
        self._assert_local_providers(providers)
        repository_path = self._path(
            mission.configuration.repository_path or "", "Mission repository path"
        )
        policy_snapshot = self._policy_snapshot(providers)
        if policy_snapshot["policy_state"]["emergency_stop"]:
            raise PermissionError("Emergency stop is active")
        policy_digest = self._digest(policy_snapshot)
        created = datetime.now(timezone.utc)
        created_at = created.isoformat(timespec="microseconds")
        expires_at = (created + timedelta(seconds=ttl_seconds)).isoformat(
            timespec="microseconds"
        )
        binding = {
            "mission_id": mission_id,
            "planning_request_id": planning_request_id,
            "requested_action": action.value,
            "provider_ids": list(providers),
            "role_models": dict(sorted(normalized_roles.items())),
            "repository_path": repository_path,
            "allowed_permissions": sorted(self.PLANNING_PERMISSIONS),
            "tool_profile": "autonomous-local-planning-read-only-v1",
            "policy_version": int(policy_snapshot["policy_state"]["version"]),
            "policy_snapshot": policy_snapshot,
            "policy_digest": policy_digest,
            "authorized_by": actor,
            "reason": reason,
            "created_at": created_at,
            "expires_at": expires_at,
        }
        authorization_digest = self._digest(binding)
        with self.storage.db:
            self.storage._begin_immediate()
            replay = self._command_replay(
                command_id, "grant_planning_authority", request_digest
            )
            if replay:
                return self.get_planning_authorization(
                    int(replay["planning_authorization_id"])
                )
            current = self.missions.get(mission_id)
            if current.phase not in PREAPPROVAL_PHASES:
                raise PermissionError("Mission reached approval before planning grant commit")
            if (
                not set(providers) <= set(current.configuration.local_provider_ids)
                or not self._same_path(
                    current.configuration.repository_path, repository_path
                )
            ):
                raise ValueError("Mission planning configuration changed before commit")
            if self._digest(self._policy_snapshot(providers)) != policy_digest:
                raise PermissionError("Local planning policy changed before commit")
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_planning_authorizations(
                       identity,mission_id,planning_request_id,requested_action,
                       provider_ids_json,role_models_json,repository_path,
                       allowed_permissions_json,tool_profile,policy_version,
                       policy_snapshot_json,policy_digest,authorized_by,command_id,
                       reason,authorization_digest,created_at,expires_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-planning-authorization"),
                    mission_id,
                    planning_request_id,
                    action.value,
                    self._json(list(providers)),
                    self._json(binding["role_models"]),
                    repository_path,
                    self._json(binding["allowed_permissions"]),
                    binding["tool_profile"],
                    binding["policy_version"],
                    self._json(policy_snapshot),
                    policy_digest,
                    actor,
                    command_id,
                    reason,
                    authorization_digest,
                    created_at,
                    expires_at,
                ),
            )
            authorization_id = int(cursor.lastrowid)
            result = {
                "planning_authorization_id": authorization_id,
                "authorization_digest": authorization_digest,
            }
            self._record_command(
                mission_id=mission_id,
                command_id=command_id,
                command_type="grant_planning_authority",
                actor=actor,
                request_digest=request_digest,
                result=result,
                created_at=created_at,
            )
            self.storage._event(
                "autonomous_authorization.planning_granted",
                "autonomous_mission",
                mission_id,
                {**result, "planning_request_id": planning_request_id, "actor": actor},
            )
        return self.get_planning_authorization(authorization_id)

    def close_planning_authority(
        self,
        planning_authorization_id: int,
        *,
        actor: str,
        command_id: str,
        reason: str,
    ) -> PlanningAuthorization:
        command_id = self._required(command_id, "Command id")
        reason = self._required(reason, "Planning closure reason")
        authorization = self.get_planning_authorization(planning_authorization_id)
        request = {
            "type": "close_planning_authority",
            "planning_authorization_id": planning_authorization_id,
            "mission_id": authorization.mission_id,
            "actor": str(actor).strip(),
            "reason": reason,
        }
        request_digest = self._digest(request)
        replay = self._command_replay(
            command_id, "close_planning_authority", request_digest
        )
        if replay:
            return self.get_planning_authorization(planning_authorization_id)
        mission = self.missions.get(authorization.mission_id)
        actor = self._assert_owner(mission, actor)
        if authorization.closed:
            raise ValueError("Planning authorization is already closed")
        created_at = self._timestamp()
        with self.storage.db:
            self.storage._begin_immediate()
            replay = self._command_replay(
                command_id, "close_planning_authority", request_digest
            )
            if replay:
                return self.get_planning_authorization(planning_authorization_id)
            if self.storage.db.execute(
                """SELECT 1 FROM autonomous_planning_authorization_closures
                    WHERE planning_authorization_id=?""",
                (planning_authorization_id,),
            ).fetchone():
                raise ValueError("Planning authorization is already closed")
            self.storage.db.execute(
                """INSERT INTO autonomous_planning_authorization_closures(
                       identity,planning_authorization_id,mission_id,actor,
                       command_id,reason,created_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-planning-closure"),
                    planning_authorization_id,
                    authorization.mission_id,
                    actor,
                    command_id,
                    reason,
                    created_at,
                ),
            )
            self._record_command(
                mission_id=authorization.mission_id,
                command_id=command_id,
                command_type="close_planning_authority",
                actor=actor,
                request_digest=request_digest,
                result={"planning_authorization_id": planning_authorization_id},
                created_at=created_at,
            )
            self.storage._event(
                "autonomous_authorization.planning_closed",
                "autonomous_mission",
                authorization.mission_id,
                {
                    "planning_authorization_id": planning_authorization_id,
                    "actor": actor,
                    "reason": reason,
                },
            )
        return self.get_planning_authorization(planning_authorization_id)

    @staticmethod
    def _add_check(
        evidence: dict[str, Any],
        name: str,
        passed: bool,
        *,
        expected: Any = None,
        actual: Any = None,
    ) -> bool:
        evidence["checks"].append(
            {
                "name": name,
                "passed": bool(passed),
                "expected": expected,
                "actual": actual,
            }
        )
        return bool(passed)

    def _record_decision(
        self,
        request: AutonomousAuthorizationRequest,
        *,
        outcome: AuthorizationOutcome,
        reason: str,
        authority_valid: bool,
        autonomous_authorization_id: int | None,
        planning_authorization_id: int | None,
        provider_ids: tuple[str, ...],
        evidence: dict[str, Any],
    ) -> AuthorizationDecision:
        policy_snapshot = self._policy_snapshot(provider_ids)
        policy_version = int(policy_snapshot["policy_state"]["version"])
        policy_digest = self._digest(policy_snapshot)
        request_json = request.canonical()
        request_digest = self._digest(request_json)
        evidence = {
            "resolver_schema_version": self.RESOLVER_SCHEMA_VERSION,
            "request_digest": request_digest,
            **evidence,
        }
        evidence_digest = self._digest(evidence)
        created_at = self._timestamp()
        decision_document = {
            "mission_id": request.mission_id,
            "request_digest": request_digest,
            "outcome": outcome.value,
            "reason": reason,
            "authority_valid": authority_valid,
            "autonomous_authorization_id": autonomous_authorization_id,
            "planning_authorization_id": planning_authorization_id,
            "policy_version": policy_version,
            "policy_digest": policy_digest,
            "evidence_digest": evidence_digest,
            "created_at": created_at,
        }
        identity = self.storage._identity("autonomous-authorization-decision")
        decision_document["identity"] = identity
        decision_digest = self._digest(decision_document)
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_authorization_decisions(
                       identity,mission_id,request_json,request_digest,outcome,
                       reason,authority_valid,autonomous_authorization_id,
                       planning_authorization_id,policy_version,policy_digest,
                       evidence_json,decision_digest,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    identity,
                    request.mission_id,
                    self._json(request_json),
                    request_digest,
                    outcome.value,
                    reason,
                    int(authority_valid),
                    autonomous_authorization_id,
                    planning_authorization_id,
                    policy_version,
                    policy_digest,
                    self._json(evidence),
                    decision_digest,
                    created_at,
                ),
            )
            decision_id = int(cursor.lastrowid)
            self.storage._event(
                "autonomous_authorization.decision",
                "autonomous_mission",
                request.mission_id,
                {
                    "decision_id": decision_id,
                    "request_digest": request_digest,
                    "outcome": outcome.value,
                    "reason": reason,
                    "authority_valid": authority_valid,
                    "evidence_digest": evidence_digest,
                },
            )
        return AuthorizationDecision(
            id=decision_id,
            identity=identity,
            mission_id=request.mission_id,
            request=request,
            request_digest=request_digest,
            outcome=outcome,
            reason=reason,
            authority_valid=authority_valid,
            autonomous_authorization_id=autonomous_authorization_id,
            planning_authorization_id=planning_authorization_id,
            policy_version=policy_version,
            policy_digest=policy_digest,
            evidence=evidence,
            evidence_digest=evidence_digest,
            decision_digest=decision_digest,
            created_at=created_at,
        )

    def resolve(
        self, request: AutonomousAuthorizationRequest
    ) -> AuthorizationDecision:
        """Evaluate and persist one decision against a consistent durable snapshot."""

        with self.storage.db:
            self.storage._begin_immediate()
            return self._resolve_locked(request)

    def _resolve_locked(
        self, request: AutonomousAuthorizationRequest
    ) -> AuthorizationDecision:
        provider_ids = (request.provider_id,) if request.provider_id else ()
        evidence: dict[str, Any] = {"checks": []}
        if request.operation in FORBIDDEN_OPERATIONS:
            self._add_check(evidence, "operation_not_forbidden", False)
            return self._record_decision(
                request,
                outcome=AuthorizationOutcome.DENY,
                reason=(
                    "Secret access and machine-global mutation are never "
                    "implicit mission authority"
                ),
                authority_valid=False,
                autonomous_authorization_id=None,
                planning_authorization_id=None,
                provider_ids=provider_ids,
                evidence=evidence,
            )
        if request.operation in STANDARD_GATED_OPERATIONS:
            self._add_check(evidence, "standard_gate_boundary", True)
            return self._record_decision(
                request,
                outcome=AuthorizationOutcome.REQUIRE_STANDARD_GATE,
                reason="Remote, external, and protected operations retain their standard gate",
                authority_valid=False,
                autonomous_authorization_id=None,
                planning_authorization_id=None,
                provider_ids=provider_ids,
                evidence=evidence,
            )
        try:
            mission = self.missions.get(request.mission_id)
        except KeyError:
            self._add_check(evidence, "mission_exists", False)
            return self._record_decision(
                request,
                outcome=AuthorizationOutcome.REQUIRE_STANDARD_GATE,
                reason="The request is not scoped to an Autonomous Mission",
                authority_valid=False,
                autonomous_authorization_id=None,
                planning_authorization_id=None,
                provider_ids=provider_ids,
                evidence=evidence,
            )
        self._add_check(evidence, "mission_exists", True)
        if request.operation in PLANNING_OPERATIONS:
            return self._resolve_planning(request, mission, evidence)
        if request.operation not in AUTONOMOUS_OPERATIONS:
            return self._record_decision(
                request,
                outcome=AuthorizationOutcome.DENY,
                reason="Unknown operation is outside autonomous authority",
                authority_valid=False,
                autonomous_authorization_id=None,
                planning_authorization_id=None,
                provider_ids=provider_ids,
                evidence=evidence,
            )
        return self._resolve_execution(request, mission, evidence)

    def _resolve_execution(
        self,
        request: AutonomousAuthorizationRequest,
        mission: AutonomousMission,
        evidence: dict[str, Any],
    ) -> AuthorizationDecision:
        provider_ids = (request.provider_id,) if request.provider_id else ()
        if request.provider_id and request.operation in {
            AuthorizationOperation.LOCAL_INFERENCE, AuthorizationOperation.PLANNING_INFERENCE,
        }:
            compatibility_error = self._capability(request.provider_id).role_model_error(request.role, request.model)
            if compatibility_error:
                self._add_check(evidence, "provider_role_model_compatible", False)
                return self._record_decision(
                    request, outcome=AuthorizationOutcome.DENY,
                    reason=compatibility_error, authority_valid=False,
                    autonomous_authorization_id=None, planning_authorization_id=None,
                    provider_ids=provider_ids, evidence=evidence,
                )
        if request.provider_id and not self._capability(
            request.provider_id
        ).autonomous_local_eligible:
            self._add_check(evidence, "provider_explicitly_local", False)
            return self._record_decision(
                request,
                outcome=AuthorizationOutcome.REQUIRE_STANDARD_GATE,
                reason="Provider is not explicitly qualified for local autonomous inference",
                authority_valid=False,
                autonomous_authorization_id=None,
                planning_authorization_id=None,
                provider_ids=provider_ids,
                evidence=evidence,
            )
        if request.authorization_id is None:
            self._add_check(evidence, "authorization_supplied", False)
            if request.planning_authorization_id is not None:
                return self._record_decision(
                    request,
                    outcome=AuthorizationOutcome.DENY,
                    reason="Bounded planning authority cannot authorize development or mutation",
                    authority_valid=False,
                    autonomous_authorization_id=None,
                    planning_authorization_id=request.planning_authorization_id,
                    provider_ids=provider_ids,
                    evidence=evidence,
                )
            return self._record_decision(
                request,
                outcome=AuthorizationOutcome.REQUIRE_STANDARD_GATE,
                reason="No Autonomous Local authority was supplied",
                authority_valid=False,
                autonomous_authorization_id=None,
                planning_authorization_id=None,
                provider_ids=provider_ids,
                evidence=evidence,
            )
        try:
            authorization = self.get_authorization(request.authorization_id)
        except KeyError:
            self._add_check(evidence, "authorization_exists", False)
            return self._record_decision(
                request,
                outcome=AuthorizationOutcome.DENY,
                reason="Autonomous authorization does not exist",
                authority_valid=False,
                autonomous_authorization_id=None,
                planning_authorization_id=None,
                provider_ids=provider_ids,
                evidence=evidence,
            )
        if authorization.mission_id != request.mission_id:
            self._add_check(
                evidence,
                "authorization_mission",
                False,
                expected=request.mission_id,
                actual=authorization.mission_id,
            )
            return self._record_decision(
                request,
                outcome=AuthorizationOutcome.REQUIRE_STANDARD_GATE,
                reason="Authorization belongs to another mission",
                authority_valid=False,
                autonomous_authorization_id=authorization.id,
                planning_authorization_id=None,
                provider_ids=authorization.provider_ids,
                evidence=evidence,
            )

        current_policy = self._policy_snapshot(authorization.provider_ids)
        current_manifest = self._role_manifest(mission)
        try:
            current_repository = self._path(
                mission.configuration.repository_path or "", "Mission repository path"
            )
        except (OSError, ValueError):
            current_repository = ""
        revision = self.storage.db.execute(
            """SELECT revision_number,revision_digest
                 FROM autonomous_backlog_revisions WHERE id=? AND mission_id=?""",
            (authorization.backlog_revision_id, mission.id),
        ).fetchone()
        epoch = self.storage.db.execute(
            """SELECT epoch_branch FROM autonomous_mission_execution_epochs
                WHERE id=? AND mission_id=?""",
            (authorization.execution_epoch_id, mission.id),
        ).fetchone()
        pending_material = False
        if revision:
            pending_material = bool(
                self.storage.db.execute(
                    """SELECT 1 FROM autonomous_backlog_revisions
                        WHERE mission_id=? AND origin='AGENT_MATERIAL'
                          AND revision_number>?
                        ORDER BY revision_number LIMIT 1""",
                    (mission.id, int(revision["revision_number"])),
                ).fetchone()
            )
        expected_model = self._model_for(authorization.role_model_manifest, request.role)
        required_permission = self.OPERATION_PERMISSION[request.operation]
        current_policy_digest = self._digest(current_policy)
        inference_scope_present = (
            request.operation is not AuthorizationOperation.LOCAL_INFERENCE
            or (
                bool(request.provider_id)
                and bool(request.agent_id)
                and request.task_id is not None
            )
        )
        checks = [
            self._add_check(
                evidence,
                "authorization_integrity",
                self._digest(authorization.binding())
                == authorization.authorization_digest,
            ),
            self._add_check(evidence, "not_revoked", not authorization.revoked),
            self._add_check(
                evidence,
                "policy_version",
                authorization.policy_version
                == int(current_policy["policy_state"]["version"]),
                expected=authorization.policy_version,
                actual=current_policy["policy_state"]["version"],
            ),
            self._add_check(
                evidence,
                "policy_digest",
                authorization.policy_digest == current_policy_digest,
                expected=authorization.policy_digest,
                actual=current_policy_digest,
            ),
            self._add_check(
                evidence,
                "active_revision",
                mission.active_backlog_revision_id
                == authorization.backlog_revision_id
                and request.backlog_revision_id
                == authorization.backlog_revision_id,
            ),
            self._add_check(
                evidence,
                "revision_digest",
                bool(revision)
                and str(revision["revision_digest"])
                == authorization.backlog_revision_digest
                and request.backlog_revision_digest
                == authorization.backlog_revision_digest,
            ),
            self._add_check(
                evidence,
                "active_epoch",
                mission.active_execution_epoch_id == authorization.execution_epoch_id
                and request.execution_epoch_id == authorization.execution_epoch_id,
            ),
            self._add_check(
                evidence,
                "epoch_branch",
                bool(epoch)
                and str(epoch["epoch_branch"]) == authorization.epoch_branch
                and request.epoch_branch == authorization.epoch_branch,
            ),
            self._add_check(
                evidence,
                "repository",
                current_repository == authorization.repository_path
                and self._same_path(
                    request.repository_path, authorization.repository_path
                ),
            ),
            self._add_check(
                evidence,
                "provider_set",
                tuple(sorted(mission.configuration.local_provider_ids))
                == authorization.provider_ids,
            ),
            self._add_check(
                evidence,
                "provider_allowed",
                request.provider_id is None
                or request.provider_id in authorization.provider_ids,
            ),
            self._add_check(
                evidence, "inference_scope_present", inference_scope_present
            ),
            self._add_check(
                evidence,
                "role_model_manifest",
                self._digest(current_manifest)
                == authorization.role_model_manifest_digest,
            ),
            self._add_check(
                evidence,
                "role_model",
                bool(request.role)
                and bool(request.model)
                and expected_model == request.model,
                expected=expected_model,
                actual=request.model,
            ),
            self._add_check(
                evidence,
                "tool_profile",
                mission.configuration.allowed_local_tool_profile
                == authorization.tool_profile
                and request.tool_profile == authorization.tool_profile,
            ),
            self._add_check(
                evidence,
                "bootstrap_profile",
                self._bootstrap_profile(mission) == authorization.bootstrap_profile,
            ),
            self._add_check(
                evidence,
                "permission_subset",
                bool(request.permissions)
                and set(request.permissions) <= set(authorization.allowed_permissions),
            ),
            self._add_check(
                evidence,
                "required_permission",
                required_permission in request.permissions,
            ),
            self._add_check(
                evidence,
                "forbidden_permissions",
                not (set(request.permissions) & self.DENIED_PERMISSIONS),
            ),
            self._add_check(
                evidence,
                "no_unapproved_agent_material_revision",
                not pending_material,
            ),
        ]
        authority_valid = all(checks)
        if not authority_valid:
            return self._record_decision(
                request,
                outcome=AuthorizationOutcome.DENY,
                reason="Autonomous authority no longer matches the exact mission scope",
                authority_valid=False,
                autonomous_authorization_id=authorization.id,
                planning_authorization_id=None,
                provider_ids=authorization.provider_ids,
                evidence=evidence,
            )
        if mission.phase not in EXECUTION_PHASES:
            self._add_check(evidence, "execution_phase", False, actual=mission.phase.value)
            return self._record_decision(
                request,
                outcome=AuthorizationOutcome.DENY,
                reason="Mission phase is not executable",
                authority_valid=True,
                autonomous_authorization_id=authorization.id,
                planning_authorization_id=None,
                provider_ids=authorization.provider_ids,
                evidence=evidence,
            )
        if mission.disposition is not MissionDisposition.RUNNING:
            self._add_check(
                evidence,
                "scheduling_fence",
                False,
                expected=MissionDisposition.RUNNING.value,
                actual=mission.disposition.value,
            )
            return self._record_decision(
                request,
                outcome=AuthorizationOutcome.DENY,
                reason=f"Mission scheduling is fenced by {mission.disposition.value}",
                authority_valid=True,
                autonomous_authorization_id=authorization.id,
                planning_authorization_id=None,
                provider_ids=authorization.provider_ids,
                evidence=evidence,
            )
        self._add_check(evidence, "execution_phase", True, actual=mission.phase.value)
        self._add_check(evidence, "scheduling_fence", True)
        return self._record_decision(
            request,
            outcome=AuthorizationOutcome.ALLOW_AUTONOMOUS,
            reason="Exact approved Autonomous Local capability is valid",
            authority_valid=True,
            autonomous_authorization_id=authorization.id,
            planning_authorization_id=None,
            provider_ids=authorization.provider_ids,
            evidence=evidence,
        )

    def _resolve_planning(
        self,
        request: AutonomousAuthorizationRequest,
        mission: AutonomousMission,
        evidence: dict[str, Any],
    ) -> AuthorizationDecision:
        provider_ids = (request.provider_id,) if request.provider_id else ()
        if request.provider_id and request.operation in {
            AuthorizationOperation.LOCAL_INFERENCE, AuthorizationOperation.PLANNING_INFERENCE,
        }:
            compatibility_error = self._capability(request.provider_id).role_model_error(request.role, request.model)
            if compatibility_error:
                self._add_check(evidence, "provider_role_model_compatible", False)
                return self._record_decision(
                    request, outcome=AuthorizationOutcome.DENY,
                    reason=compatibility_error, authority_valid=False,
                    autonomous_authorization_id=None, planning_authorization_id=None,
                    provider_ids=provider_ids, evidence=evidence,
                )
        if request.provider_id and not self._capability(
            request.provider_id
        ).autonomous_local_eligible:
            self._add_check(evidence, "provider_explicitly_local", False)
            return self._record_decision(
                request,
                outcome=AuthorizationOutcome.REQUIRE_STANDARD_GATE,
                reason="Remote planning providers retain their standard gate",
                authority_valid=False,
                autonomous_authorization_id=None,
                planning_authorization_id=None,
                provider_ids=provider_ids,
                evidence=evidence,
            )
        if request.planning_authorization_id is None:
            self._add_check(evidence, "planning_authorization_supplied", False)
            if request.authorization_id is not None:
                return self._record_decision(
                    request,
                    outcome=AuthorizationOutcome.DENY,
                    reason=(
                        "Execution authority cannot be used for a pre-approval "
                        "planning request"
                    ),
                    authority_valid=False,
                    autonomous_authorization_id=request.authorization_id,
                    planning_authorization_id=None,
                    provider_ids=provider_ids,
                    evidence=evidence,
                )
            return self._record_decision(
                request,
                outcome=AuthorizationOutcome.REQUIRE_STANDARD_GATE,
                reason="No explicit bounded planning authorization was supplied",
                authority_valid=False,
                autonomous_authorization_id=None,
                planning_authorization_id=None,
                provider_ids=provider_ids,
                evidence=evidence,
            )
        try:
            authorization = self.get_planning_authorization(
                request.planning_authorization_id
            )
        except KeyError:
            self._add_check(evidence, "planning_authorization_exists", False)
            return self._record_decision(
                request,
                outcome=AuthorizationOutcome.DENY,
                reason="Planning authorization does not exist",
                authority_valid=False,
                autonomous_authorization_id=None,
                planning_authorization_id=None,
                provider_ids=provider_ids,
                evidence=evidence,
            )
        if authorization.mission_id != request.mission_id:
            self._add_check(evidence, "planning_authorization_mission", False)
            return self._record_decision(
                request,
                outcome=AuthorizationOutcome.REQUIRE_STANDARD_GATE,
                reason="Planning authorization belongs to another mission",
                authority_valid=False,
                autonomous_authorization_id=None,
                planning_authorization_id=authorization.id,
                provider_ids=authorization.provider_ids,
                evidence=evidence,
            )
        current_policy = self._policy_snapshot(authorization.provider_ids)
        expected_model = authorization.role_models.get(request.role)
        required_permission = self.OPERATION_PERMISSION[request.operation]
        try:
            expires_at = datetime.fromisoformat(authorization.expires_at)
        except ValueError:
            expires_at = datetime.min.replace(tzinfo=timezone.utc)
        inference_scope_present = (
            request.operation is not AuthorizationOperation.PLANNING_INFERENCE
            or (bool(request.agent_id) and request.task_id is not None)
        )
        mutation_permissions = {
            "write_project",
            "worktree_write",
            "git_write",
            "tool_use",
            "environment_bootstrap",
            "service_control",
        }
        checks = [
            self._add_check(
                evidence,
                "planning_authorization_integrity",
                self._digest(authorization.binding())
                == authorization.authorization_digest,
            ),
            self._add_check(
                evidence, "planning_authorization_open", not authorization.closed
            ),
            self._add_check(
                evidence,
                "planning_authorization_unexpired",
                datetime.now(timezone.utc) < expires_at,
            ),
            self._add_check(
                evidence,
                "preapproval_phase",
                mission.phase in PREAPPROVAL_PHASES,
                actual=mission.phase.value,
            ),
            self._add_check(
                evidence,
                "policy_version",
                authorization.policy_version
                == int(current_policy["policy_state"]["version"]),
            ),
            self._add_check(
                evidence,
                "policy_digest",
                authorization.policy_digest == self._digest(current_policy),
            ),
            self._add_check(
                evidence,
                "planning_request",
                request.planning_request_id == authorization.planning_request_id,
            ),
            self._add_check(
                evidence,
                "planning_action",
                request.requested_action == authorization.requested_action,
            ),
            self._add_check(
                evidence,
                "provider_allowed",
                request.provider_id in authorization.provider_ids,
            ),
            self._add_check(
                evidence, "inference_scope_present", inference_scope_present
            ),
            self._add_check(
                evidence,
                "role_model",
                bool(request.role) and expected_model == request.model,
                expected=expected_model,
                actual=request.model,
            ),
            self._add_check(
                evidence,
                "repository",
                self._same_path(
                    request.repository_path, authorization.repository_path
                )
                and self._same_path(
                    mission.configuration.repository_path,
                    authorization.repository_path,
                ),
            ),
            self._add_check(
                evidence,
                "tool_profile",
                request.tool_profile == authorization.tool_profile,
            ),
            self._add_check(
                evidence,
                "permission_subset",
                bool(request.permissions)
                and set(request.permissions) <= set(authorization.allowed_permissions),
            ),
            self._add_check(
                evidence,
                "required_permission",
                required_permission in request.permissions,
            ),
            self._add_check(
                evidence,
                "no_mutation_permission",
                not (mutation_permissions & set(request.permissions)),
            ),
            self._add_check(
                evidence,
                "forbidden_permissions",
                not (set(request.permissions) & self.DENIED_PERMISSIONS),
            ),
        ]
        authority_valid = all(checks)
        if not authority_valid:
            return self._record_decision(
                request,
                outcome=AuthorizationOutcome.DENY,
                reason="Bounded planning authority no longer matches the exact request",
                authority_valid=False,
                autonomous_authorization_id=None,
                planning_authorization_id=authorization.id,
                provider_ids=authorization.provider_ids,
                evidence=evidence,
            )
        if mission.disposition is not MissionDisposition.RUNNING:
            self._add_check(
                evidence,
                "scheduling_fence",
                False,
                actual=mission.disposition.value,
            )
            return self._record_decision(
                request,
                outcome=AuthorizationOutcome.DENY,
                reason=f"Mission scheduling is fenced by {mission.disposition.value}",
                authority_valid=True,
                autonomous_authorization_id=None,
                planning_authorization_id=authorization.id,
                provider_ids=authorization.provider_ids,
                evidence=evidence,
            )
        self._add_check(evidence, "scheduling_fence", True)
        return self._record_decision(
            request,
            outcome=AuthorizationOutcome.ALLOW_PLANNING,
            reason="Explicit bounded local planning request is valid",
            authority_valid=True,
            autonomous_authorization_id=None,
            planning_authorization_id=authorization.id,
            provider_ids=authorization.provider_ids,
            evidence=evidence,
        )

    def provider_authorization(
        self, decision: AuthorizationDecision
    ) -> ProviderExecutionAuthorization:
        if decision.outcome not in {
            AuthorizationOutcome.ALLOW_AUTONOMOUS,
            AuthorizationOutcome.ALLOW_PLANNING,
        }:
            raise PermissionError("A denied or standard-gated decision cannot execute a provider")
        request = decision.request
        expected_operation = (
            AuthorizationOperation.LOCAL_INFERENCE
            if decision.outcome is AuthorizationOutcome.ALLOW_AUTONOMOUS
            else AuthorizationOperation.PLANNING_INFERENCE
        )
        if request.operation is not expected_operation:
            raise PermissionError("The authorization decision is not for provider inference")
        if not request.provider_id or not request.agent_id or request.task_id is None:
            raise ValueError("Provider authority requires provider, agent, and task scope")
        if decision.autonomous_authorization_id is not None:
            authorization_id = decision.autonomous_authorization_id
            authorized_by = self.get_authorization(authorization_id).granted_by
            mode = ExecutionAuthorizationMode.AUTONOMOUS_LOCAL
        elif decision.planning_authorization_id is not None:
            authorization_id = decision.planning_authorization_id
            authorized_by = self.get_planning_authorization(
                authorization_id
            ).authorized_by
            mode = ExecutionAuthorizationMode.BOUNDED_LOCAL_PLANNING
        else:
            raise RuntimeError("Allowed decision is missing its authority reference")
        return ProviderExecutionAuthorization(
            decision_id=decision.id,
            authorization_id=authorization_id,
            mode=mode,
            operation=request.operation.value,
            provider=request.provider_id,
            agent_id=request.agent_id,
            task_id=request.task_id,
            mission_id=request.mission_id,
            backlog_revision_id=request.backlog_revision_id,
            execution_epoch_id=request.execution_epoch_id,
            permissions=request.permissions,
            tool_profile=request.tool_profile or "",
            evidence_digest=decision.evidence_digest,
            authorized_by=authorized_by,
            planning_request_id=request.planning_request_id,
        )

    def decisions(self, mission_id: int) -> tuple[AuthorizationDecision, ...]:
        rows = self.storage.db.execute(
            """SELECT * FROM autonomous_authorization_decisions
                WHERE mission_id=? ORDER BY id""",
            (mission_id,),
        ).fetchall()
        results: list[AuthorizationDecision] = []
        for row in rows:
            document = json.loads(row["request_json"])
            document["permissions"] = tuple(document.get("permissions", ()))
            request = AutonomousAuthorizationRequest(**document)
            evidence = json.loads(row["evidence_json"])
            results.append(
                AuthorizationDecision(
                    id=int(row["id"]),
                    identity=str(row["identity"]),
                    mission_id=int(row["mission_id"]),
                    request=request,
                    request_digest=str(row["request_digest"]),
                    outcome=AuthorizationOutcome(row["outcome"]),
                    reason=str(row["reason"]),
                    authority_valid=bool(row["authority_valid"]),
                    autonomous_authorization_id=self._optional_id(
                        row["autonomous_authorization_id"]
                    ),
                    planning_authorization_id=self._optional_id(
                        row["planning_authorization_id"]
                    ),
                    policy_version=int(row["policy_version"]),
                    policy_digest=str(row["policy_digest"]),
                    evidence=evidence,
                    evidence_digest=self._digest(evidence),
                    decision_digest=str(row["decision_digest"]),
                    created_at=str(row["created_at"]),
                )
            )
        return tuple(results)
