"""Exact human approval and Autonomous Mission start transaction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .autonomous_authorization import (
    AutonomousAuthorizationService,
    AutonomousLocalAuthorization,
)
from .autonomous_mission import (
    AutonomousMission,
    AutonomousMissionService,
    MissionDisposition,
    MissionPhase,
    MissionVersionConflictError,
)
from .autonomous_planning import AutonomousPlanningService
from .autonomous_proposal_verifier import (
    AutonomousProposalVerificationService,
    ProposalReadinessReport,
)
from .lifecycle import ensure_transition
from .mission_checkpoints import (
    ExecutionEpochOrigin,
    MissionCheckpointService,
    MissionExecutionEpoch,
)
from .mission_intake import AutonomousMissionIntakeService
from .models import ProviderCapabilities
from .storage import SQLiteStorage


class BacklogApprovalCommandConflictError(ValueError):
    """Raised when an approval idempotency key is rebound."""


class BacklogAlreadyApprovedError(ValueError):
    """Raised when another command already approved the verification."""


@dataclass(frozen=True)
class AutonomousBacklogApproval:
    id: int
    identity: str
    mission_id: int
    verification_id: int
    pipeline_run_id: int
    revision_id: int
    revision_digest: str
    canonical_digest: str
    source_id: int
    source_digest: str
    planning_manifest_id: int
    planning_manifest_digest: str
    planning_model_manifest: dict[str, Any]
    execution_role_model_manifest: dict[str, Any]
    execution_role_model_manifest_digest: str
    provider_ids: tuple[str, ...]
    tool_manifest: dict[str, Any]
    tool_manifest_digest: str
    policy_version: int
    policy_snapshot: dict[str, Any]
    policy_digest: str
    execution_epoch_id: int
    execution_authorization_digest: str
    approved_by: str
    authentication_context: dict[str, Any]
    authentication_context_digest: str
    expected_mission_version: int
    result_mission_version: int
    command_id: str
    request_digest: str
    reason: str
    approval_digest: str
    created_at: str
    authorization_id: int
    completion_digest: str


@dataclass(frozen=True)
class ApprovalStartResult:
    approval: AutonomousBacklogApproval
    mission: AutonomousMission
    execution_epoch: MissionExecutionEpoch
    authorization: AutonomousLocalAuthorization


class AutonomousBacklogApprovalService:
    """Approve, activate, epoch-bind, and authorize one verified proposal."""

    def __init__(
        self,
        storage: SQLiteStorage,
        provider_capabilities: Mapping[str, ProviderCapabilities] | None = None,
    ):
        self.storage = storage
        self.provider_capabilities = dict(provider_capabilities or {})
        self.missions = AutonomousMissionService(storage)
        self.verifications = AutonomousProposalVerificationService(storage)
        self.planning = AutonomousPlanningService(
            storage, self.provider_capabilities
        )
        self.intake = AutonomousMissionIntakeService(storage)
        self.checkpoints = MissionCheckpointService(storage)
        self.authorizations = AutonomousAuthorizationService(
            storage, self.provider_capabilities
        )

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

    @staticmethod
    def _sha256(value: str, label: str) -> str:
        normalized = str(value).strip().lower()
        if len(normalized) != 64 or any(
            character not in "0123456789abcdef" for character in normalized
        ):
            raise ValueError(f"{label} must be a lowercase SHA-256 digest")
        return normalized

    def _existing(
        self, command_id: str, request_digest: str
    ) -> ApprovalStartResult | None:
        row = self.storage.db.execute(
            "SELECT id,request_digest FROM autonomous_backlog_approvals "
            "WHERE command_id=?",
            (command_id,),
        ).fetchone()
        if not row:
            return None
        if row["request_digest"] != request_digest:
            raise BacklogApprovalCommandConflictError(
                f"Backlog approval command {command_id!r} is already bound"
            )
        return self.result(int(row["id"]))

    def _approval_binding(
        self,
        *,
        mission_id: int,
        verification: ProposalReadinessReport,
        planning_model_manifest: dict[str, Any],
        execution_role_model_manifest: dict[str, Any],
        execution_role_model_manifest_digest: str,
        provider_ids: tuple[str, ...],
        tool_manifest: dict[str, Any],
        tool_manifest_digest: str,
        policy_version: int,
        policy_snapshot: dict[str, Any],
        policy_digest: str,
        execution_epoch_id: int,
        execution_authorization_digest: str,
        approved_by: str,
        authentication_context: dict[str, Any],
        authentication_context_digest: str,
        expected_mission_version: int,
        result_mission_version: int,
        command_id: str,
        request_digest: str,
        reason: str,
        created_at: str,
    ) -> dict[str, Any]:
        return {
            "mission_id": mission_id,
            "verification_id": verification.id,
            "pipeline_run_id": verification.pipeline_run_id,
            "revision_id": verification.revision_id,
            "revision_digest": verification.revision_digest,
            "canonical_digest": verification.canonical_digest,
            "source_id": verification.source_id,
            "source_digest": verification.source_digest,
            "planning_manifest_id": verification.manifest_id,
            "planning_manifest_digest": verification.manifest_digest,
            "planning_model_manifest": planning_model_manifest,
            "execution_role_model_manifest": execution_role_model_manifest,
            "execution_role_model_manifest_digest": (
                execution_role_model_manifest_digest
            ),
            "provider_ids": list(provider_ids),
            "tool_manifest": tool_manifest,
            "tool_manifest_digest": tool_manifest_digest,
            "policy_version": policy_version,
            "policy_snapshot": policy_snapshot,
            "policy_digest": policy_digest,
            "execution_epoch_id": execution_epoch_id,
            "execution_authorization_digest": execution_authorization_digest,
            "approved_by": approved_by,
            "authentication_context": authentication_context,
            "authentication_context_digest": authentication_context_digest,
            "expected_mission_version": expected_mission_version,
            "result_mission_version": result_mission_version,
            "command_id": command_id,
            "request_digest": request_digest,
            "reason": reason,
            "created_at": created_at,
        }

    def approve_and_start(
        self,
        verification_id: int,
        *,
        expected_revision_id: int,
        expected_canonical_digest: str,
        expected_mission_version: int,
        base_git_commit_sha: str,
        epoch_branch: str,
        temporal_workflow_id: str,
        temporal_run_id: str,
        actor: str,
        command_id: str,
        reason: str,
        authentication_context: dict[str, Any] | None = None,
        temporal_chain_metadata: dict[str, Any] | None = None,
        workflow_build_id: str | None = None,
        allowed_permissions: tuple[str, ...] | None = None,
    ) -> ApprovalStartResult:
        actor = self._required(actor, "Approval actor")
        command_id = self._required(command_id, "Command id")
        reason = self._required(reason, "Approval reason")
        epoch_branch = self._required(epoch_branch, "Epoch branch")
        temporal_workflow_id = self._required(
            temporal_workflow_id, "Temporal workflow id"
        )
        temporal_run_id = self._required(temporal_run_id, "Temporal run id")
        canonical_digest = self._sha256(
            expected_canonical_digest, "Expected canonical digest"
        )
        normalized_commit = self.checkpoints._commit(base_git_commit_sha)
        build_id = (
            self._required(workflow_build_id, "Workflow build id")
            if workflow_build_id is not None
            else None
        )
        auth_context = dict(
            authentication_context
            or {
                "schema_version": 1,
                "method": "mission-owner-session",
                "subject": actor,
            }
        )
        if (
            auth_context.get("subject") != actor
            or not str(auth_context.get("method", "")).strip()
        ):
            raise PermissionError(
                "Authentication context must bind the exact approval actor"
            )
        metadata = dict(temporal_chain_metadata or {})
        reserved = {
            "workflow_id": temporal_workflow_id,
            "first_run_id": temporal_run_id,
            "workflow_build_id": build_id,
            "start_state": "APPROVED_NOT_DISPATCHED",
        }
        for key, expected in reserved.items():
            if key in metadata and metadata[key] != expected:
                raise ValueError(f"Temporal metadata cannot override {key}")
            metadata[key] = expected
        requested_permissions = (
            sorted(set(allowed_permissions))
            if allowed_permissions is not None
            else None
        )
        request = {
            "type": "approve_backlog_and_start_mission",
            "verification_id": int(verification_id),
            "expected_revision_id": int(expected_revision_id),
            "expected_canonical_digest": canonical_digest,
            "expected_mission_version": int(expected_mission_version),
            "base_git_commit_sha": normalized_commit,
            "epoch_branch": epoch_branch,
            "temporal_workflow_id": temporal_workflow_id,
            "temporal_run_id": temporal_run_id,
            "temporal_chain_metadata": metadata,
            "workflow_build_id": build_id,
            "actor": actor,
            "reason": reason,
            "authentication_context": auth_context,
            "allowed_permissions": requested_permissions,
        }
        request_digest = self._digest(request)
        replay = self._existing(command_id, request_digest)
        if replay:
            return replay

        verification = self.verifications.get(verification_id)
        if not verification.ready:
            raise PermissionError("An unverified or blocked proposal cannot be approved")
        prior = self.storage.db.execute(
            "SELECT id FROM autonomous_backlog_approvals WHERE verification_id=?",
            (verification.id,),
        ).fetchone()
        if prior:
            raise BacklogAlreadyApprovedError(
                "This verified proposal was approved by another command"
            )
        mission = self.missions.get(verification.mission_id)
        if actor != mission.mission_owner:
            raise PermissionError(
                "Only the authenticated mission owner may approve the backlog"
            )
        if mission.version != expected_mission_version:
            raise MissionVersionConflictError(
                mission.id, expected_mission_version, mission.version
            )
        if (
            mission.phase is not MissionPhase.WAITING_FOR_BACKLOG_APPROVAL
            or mission.disposition is not MissionDisposition.RUNNING
        ):
            raise PermissionError("Mission is not waiting for exact backlog approval")
        if verification.mission_result_version != mission.version:
            raise ValueError("Verification does not bind the current mission version")
        if (
            verification.revision_id != expected_revision_id
            or verification.revision_digest != canonical_digest
            or verification.canonical_digest != canonical_digest
        ):
            raise ValueError("Approved revision id or canonical digest does not match")
        if self.verifications.current_ready_report(mission.id).id != verification.id:
            raise ValueError("A newer ready proposal superseded this verification")
        revision = self.storage.db.execute(
            "SELECT * FROM autonomous_backlog_revisions WHERE id=?",
            (expected_revision_id,),
        ).fetchone()
        if not revision or int(revision["mission_id"]) != mission.id:
            raise ValueError("Approved revision does not belong to this mission")
        if revision["revision_digest"] != canonical_digest:
            raise ValueError("Revision digest changed after human presentation")
        if self.storage.db.execute(
            "SELECT 1 FROM autonomous_backlog_revision_invalidations WHERE revision_id=?",
            (expected_revision_id,),
        ).fetchone():
            raise PermissionError("An invalidated proposal cannot be approved")
        latest = self.storage.db.execute(
            "SELECT id FROM autonomous_backlog_revisions "
            "WHERE mission_id=? ORDER BY revision_number DESC LIMIT 1",
            (mission.id,),
        ).fetchone()
        if not latest or int(latest["id"]) != expected_revision_id:
            raise PermissionError("A newer backlog revision requires another approval")
        current_source = self.intake.current_source(mission.id)
        if (
            current_source.id != verification.source_id
            or current_source.source_digest != verification.source_digest
        ):
            raise PermissionError("Specification source changed after verification")
        planning_manifest = self.planning.get_manifest(verification.manifest_id)
        if (
            planning_manifest.stale
            or planning_manifest.manifest_digest != verification.manifest_digest
        ):
            raise PermissionError("Planning model manifest is stale")

        normalized_commit, repository = self.checkpoints._resolve_commit(
            mission, normalized_commit, require_clean_head=True
        )
        self.checkpoints._git(
            repository, "check-ref-format", "--branch", epoch_branch
        )
        provider_ids = self.authorizations._ids(
            list(mission.configuration.local_provider_ids)
        )
        self.authorizations._assert_local_providers(provider_ids)
        execution_manifest = self.authorizations._role_manifest(mission)
        if not execution_manifest["role_models"]:
            raise ValueError(
                "Autonomous approval requires explicit execution role/model bindings"
            )
        execution_manifest_digest = self._digest(execution_manifest)
        planning_model_manifest = planning_manifest.document()
        if self._digest(planning_model_manifest) != planning_manifest.manifest_digest:
            raise RuntimeError("Planning model manifest digest is corrupt")
        repository_path = self.authorizations._path(
            mission.configuration.repository_path or "",
            "Mission repository path",
        )
        permissions = self.authorizations._permissions(
            allowed_permissions
            if allowed_permissions is not None
            else self.authorizations.DEFAULT_AUTONOMOUS_PERMISSIONS
        )
        unsupported = set(permissions) - self.authorizations.DEFAULT_AUTONOMOUS_PERMISSIONS
        forbidden = set(permissions) & self.authorizations.DENIED_PERMISSIONS
        if unsupported or forbidden:
            raise PermissionError(
                "Autonomous permission set exceeds the reviewed local capability"
            )
        if not mission.configuration.automatic_environment_bootstrap:
            permissions = tuple(
                value for value in permissions if value != "environment_bootstrap"
            )
        if not mission.configuration.automatic_service_recovery:
            permissions = tuple(
                value for value in permissions if value != "service_control"
            )
        bootstrap_profile = self.authorizations._bootstrap_profile(mission)
        tool_manifest = {
            "repository_path": repository_path,
            "tool_profile": mission.configuration.allowed_local_tool_profile,
            "bootstrap_profile": bootstrap_profile,
            "allowed_permissions": list(permissions),
        }
        tool_manifest_digest = self._digest(tool_manifest)
        policy_snapshot = self.authorizations._policy_snapshot(provider_ids)
        if policy_snapshot["policy_state"]["emergency_stop"]:
            raise PermissionError("Emergency stop is active")
        policy_digest = self._digest(policy_snapshot)
        authentication_context_digest = self._digest(auth_context)
        metadata_digest = self._digest(metadata)
        result_mission_version = expected_mission_version + 1
        created_at = self._timestamp()

        with self.storage.db:
            self.storage._begin_immediate()
            replay = self._existing(command_id, request_digest)
            if replay:
                return replay
            if self.storage.db.execute(
                "SELECT 1 FROM autonomous_backlog_approvals WHERE verification_id=?",
                (verification.id,),
            ).fetchone():
                raise BacklogAlreadyApprovedError(
                    "This verified proposal was approved concurrently"
                )
            current = self.storage.db.execute(
                "SELECT * FROM autonomous_missions WHERE id=?", (mission.id,)
            ).fetchone()
            if not current:
                raise KeyError(f"Unknown Autonomous Mission: {mission.id}")
            actual_version = int(current["version"])
            if actual_version != expected_mission_version:
                raise MissionVersionConflictError(
                    mission.id, expected_mission_version, actual_version
                )
            if (
                current["phase"]
                != MissionPhase.WAITING_FOR_BACKLOG_APPROVAL.value
                or current["disposition"] != MissionDisposition.RUNNING.value
                or current["mission_owner"] != actor
                or current["active_backlog_revision_id"] is not None
                or current["active_execution_epoch_id"] is not None
            ):
                raise PermissionError("Mission approval scope changed before commit")
            head = self.storage.db.execute(
                "SELECT source_id,source_digest FROM "
                "autonomous_mission_specification_heads WHERE mission_id=?",
                (mission.id,),
            ).fetchone()
            if (
                not head
                or int(head["source_id"]) != verification.source_id
                or head["source_digest"] != verification.source_digest
            ):
                raise PermissionError("Specification changed before approval commit")
            if self.storage.db.execute(
                "SELECT 1 FROM autonomous_backlog_revision_invalidations "
                "WHERE revision_id=?",
                (expected_revision_id,),
            ).fetchone():
                raise PermissionError("Revision invalidated before approval commit")
            latest = self.storage.db.execute(
                "SELECT id FROM autonomous_backlog_revisions "
                "WHERE mission_id=? ORDER BY revision_number DESC LIMIT 1",
                (mission.id,),
            ).fetchone()
            if not latest or int(latest["id"]) != expected_revision_id:
                raise PermissionError("Backlog changed before approval commit")
            current_mission = self.missions.get(mission.id)
            if (
                current_mission.configuration.to_dict()
                != mission.configuration.to_dict()
                or self.authorizations._role_manifest(current_mission)
                != execution_manifest
            ):
                raise ValueError("Mission model/tool configuration changed")
            if self._digest(
                self.authorizations._policy_snapshot(provider_ids)
            ) != policy_digest:
                raise PermissionError("Local execution policy changed before commit")
            if self.storage.db.execute(
                "SELECT 1 FROM autonomous_mission_execution_epochs WHERE mission_id=?",
                (mission.id,),
            ).fetchone():
                raise ValueError("Initial execution epoch already exists")

            epoch_cursor = self.storage.db.execute(
                """INSERT INTO autonomous_mission_execution_epochs(
                       identity,mission_id,epoch_number,base_backlog_revision_id,
                       base_backlog_revision_digest,base_checkpoint_id,
                       base_checkpoint_digest,base_git_commit_sha,epoch_branch,origin,
                       temporal_workflow_id,temporal_first_run_id,
                       temporal_chain_metadata_json,temporal_chain_metadata_digest,
                       supersedes_epoch_id,activation_mission_version,created_by,
                       reason,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-mission-epoch"),
                    mission.id,
                    1,
                    expected_revision_id,
                    canonical_digest,
                    None,
                    None,
                    normalized_commit,
                    epoch_branch,
                    ExecutionEpochOrigin.INITIAL.value,
                    temporal_workflow_id,
                    temporal_run_id,
                    self._json(metadata),
                    metadata_digest,
                    None,
                    result_mission_version,
                    actor,
                    reason,
                    created_at,
                ),
            )
            epoch_id = int(epoch_cursor.lastrowid)
            temporal_run_metadata = {
                "chain": metadata,
                "epoch_number": 1,
                "mission_id": mission.id,
            }
            self.storage.db.execute(
                """INSERT INTO autonomous_epoch_temporal_runs(
                       identity,execution_epoch_id,sequence,workflow_id,run_id,
                       previous_run_id,workflow_build_id,metadata_json,
                       metadata_digest,command_id,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-epoch-temporal-run"),
                    epoch_id,
                    1,
                    temporal_workflow_id,
                    temporal_run_id,
                    None,
                    build_id,
                    self._json(temporal_run_metadata),
                    self._digest(temporal_run_metadata),
                    f"{command_id}:temporal-run:1",
                    created_at,
                ),
            )

            authorization_binding = {
                "mission_id": mission.id,
                "backlog_revision_id": expected_revision_id,
                "backlog_revision_digest": canonical_digest,
                "execution_epoch_id": epoch_id,
                "epoch_branch": epoch_branch,
                "repository_path": repository_path,
                "provider_ids": list(provider_ids),
                "role_model_manifest": execution_manifest,
                "role_model_manifest_digest": execution_manifest_digest,
                "allowed_permissions": list(permissions),
                "tool_profile": mission.configuration.allowed_local_tool_profile,
                "bootstrap_profile": bootstrap_profile,
                "policy_version": int(policy_snapshot["policy_state"]["version"]),
                "policy_snapshot": policy_snapshot,
                "policy_digest": policy_digest,
                "granted_by": actor,
                "reason": reason,
            }
            authorization_digest = self._digest(authorization_binding)
            approval_binding = self._approval_binding(
                mission_id=mission.id,
                verification=verification,
                planning_model_manifest=planning_model_manifest,
                execution_role_model_manifest=execution_manifest,
                execution_role_model_manifest_digest=execution_manifest_digest,
                provider_ids=provider_ids,
                tool_manifest=tool_manifest,
                tool_manifest_digest=tool_manifest_digest,
                policy_version=authorization_binding["policy_version"],
                policy_snapshot=policy_snapshot,
                policy_digest=policy_digest,
                execution_epoch_id=epoch_id,
                execution_authorization_digest=authorization_digest,
                approved_by=actor,
                authentication_context=auth_context,
                authentication_context_digest=authentication_context_digest,
                expected_mission_version=expected_mission_version,
                result_mission_version=result_mission_version,
                command_id=command_id,
                request_digest=request_digest,
                reason=reason,
                created_at=created_at,
            )
            approval_digest = self._digest(approval_binding)
            approval_cursor = self.storage.db.execute(
                """INSERT INTO autonomous_backlog_approvals(
                       identity,mission_id,verification_id,pipeline_run_id,
                       revision_id,revision_digest,canonical_digest,source_id,
                       source_digest,planning_manifest_id,planning_manifest_digest,
                       planning_model_manifest_json,
                       execution_role_model_manifest_json,
                       execution_role_model_manifest_digest,provider_ids_json,
                       tool_manifest_json,tool_manifest_digest,policy_version,
                       policy_snapshot_json,policy_digest,execution_epoch_id,
                       execution_authorization_digest,approved_by,
                       authentication_context_json,authentication_context_digest,
                       expected_mission_version,result_mission_version,command_id,
                       request_digest,reason,approval_digest,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-backlog-approval"),
                    mission.id,
                    verification.id,
                    verification.pipeline_run_id,
                    expected_revision_id,
                    canonical_digest,
                    canonical_digest,
                    verification.source_id,
                    verification.source_digest,
                    verification.manifest_id,
                    verification.manifest_digest,
                    self._json(planning_model_manifest),
                    self._json(execution_manifest),
                    execution_manifest_digest,
                    self._json(list(provider_ids)),
                    self._json(tool_manifest),
                    tool_manifest_digest,
                    authorization_binding["policy_version"],
                    self._json(policy_snapshot),
                    policy_digest,
                    epoch_id,
                    authorization_digest,
                    actor,
                    self._json(auth_context),
                    authentication_context_digest,
                    expected_mission_version,
                    result_mission_version,
                    command_id,
                    request_digest,
                    reason,
                    approval_digest,
                    created_at,
                ),
            )
            approval_id = int(approval_cursor.lastrowid)

            authorization_command_id = f"{command_id}:authorization"
            authorization_request = {
                "type": "grant_execution_authority",
                "mission_id": mission.id,
                "expected_backlog_revision_id": expected_revision_id,
                "expected_execution_epoch_id": epoch_id,
                "actor": actor,
                "reason": reason,
                "allowed_permissions": requested_permissions,
            }
            authorization_request_digest = self._digest(authorization_request)
            authorization_cursor = self.storage.db.execute(
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
                    mission.id,
                    expected_revision_id,
                    canonical_digest,
                    epoch_id,
                    epoch_branch,
                    repository_path,
                    self._json(list(provider_ids)),
                    self._json(execution_manifest),
                    execution_manifest_digest,
                    self._json(list(permissions)),
                    mission.configuration.allowed_local_tool_profile,
                    bootstrap_profile,
                    authorization_binding["policy_version"],
                    self._json(policy_snapshot),
                    policy_digest,
                    actor,
                    authorization_command_id,
                    reason,
                    authorization_digest,
                    created_at,
                ),
            )
            authorization_id = int(authorization_cursor.lastrowid)
            self.authorizations._record_command(
                mission_id=mission.id,
                command_id=authorization_command_id,
                command_type="grant_execution_authority",
                actor=actor,
                request_digest=authorization_request_digest,
                result={
                    "authorization_id": authorization_id,
                    "authorization_digest": authorization_digest,
                },
                created_at=created_at,
            )
            completion_binding = {
                "approval_id": approval_id,
                "approval_digest": approval_digest,
                "mission_id": mission.id,
                "verification_id": verification.id,
                "revision_id": expected_revision_id,
                "revision_digest": canonical_digest,
                "execution_epoch_id": epoch_id,
                "authorization_id": authorization_id,
                "authorization_digest": authorization_digest,
                "result_mission_version": result_mission_version,
            }
            completion_digest = self._digest(completion_binding)
            self.storage.db.execute(
                """INSERT INTO autonomous_backlog_approval_completions(
                       identity,approval_id,mission_id,authorization_id,
                       result_mission_version,completion_digest,created_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-backlog-approval-completion"),
                    approval_id,
                    mission.id,
                    authorization_id,
                    result_mission_version,
                    completion_digest,
                    created_at,
                ),
            )
            mission_command_id = f"{command_id}:mission-approved"
            self.missions._insert_state_version(
                mission_id=mission.id,
                version=result_mission_version,
                phase=MissionPhase.APPROVED,
                disposition=MissionDisposition.RUNNING,
                configuration_json=str(current["configuration_json"]),
                configuration_digest=str(current["configuration_digest"]),
                active_backlog_revision_id=expected_revision_id,
                active_execution_epoch_id=epoch_id,
                current_checkpoint_id=None,
                actor=actor,
                command_id=mission_command_id,
                reason=reason,
            )
            ensure_transition(
                "autonomous_mission_phase",
                str(current["phase"]),
                MissionPhase.APPROVED.value,
            )
            updated = self.storage.db.execute(
                """UPDATE autonomous_missions
                      SET phase=?,active_backlog_revision_id=?,
                          active_execution_epoch_id=?,current_checkpoint_id=NULL,
                          version=?,updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND version=?""",
                (
                    MissionPhase.APPROVED.value,
                    expected_revision_id,
                    epoch_id,
                    result_mission_version,
                    mission.id,
                    expected_mission_version,
                ),
            )
            if updated.rowcount != 1:
                raise MissionVersionConflictError(
                    mission.id,
                    expected_mission_version,
                    expected_mission_version + 1,
                )
            mission_request_digest = self._digest(
                {
                    "type": "approve_backlog_and_start_mission",
                    "approval_id": approval_id,
                    "approval_digest": approval_digest,
                    "completion_digest": completion_digest,
                    "mission_id": mission.id,
                    "actor": actor,
                    "expected_version": expected_mission_version,
                    "result_version": result_mission_version,
                }
            )
            self.missions._insert_command(
                mission_id=mission.id,
                command_id=mission_command_id,
                command_type="approve_backlog_and_start_mission",
                actor=actor,
                expected_version=expected_mission_version,
                request_digest=mission_request_digest,
                result_version=result_mission_version,
            )
            self.storage._event(
                "autonomous_backlog.approved",
                "autonomous_mission",
                mission.id,
                {
                    "approval_id": approval_id,
                    "approval_digest": approval_digest,
                    "verification_id": verification.id,
                    "revision_id": expected_revision_id,
                    "revision_digest": canonical_digest,
                    "canonical_digest": canonical_digest,
                    "execution_epoch_id": epoch_id,
                    "authorization_id": authorization_id,
                    "authorization_digest": authorization_digest,
                    "policy_digest": policy_digest,
                    "tool_manifest_digest": tool_manifest_digest,
                    "execution_role_model_manifest_digest": (
                        execution_manifest_digest
                    ),
                    "planning_manifest_digest": verification.manifest_digest,
                    "approved_by": actor,
                    "result_mission_version": result_mission_version,
                },
            )
            self.storage._event(
                "autonomous_authorization.granted",
                "autonomous_mission",
                mission.id,
                {
                    "authorization_id": authorization_id,
                    "authorization_digest": authorization_digest,
                    "approval_id": approval_id,
                    "actor": actor,
                    "reason": reason,
                },
            )
            self.storage._event(
                "autonomous_mission.execution_epoch_activated",
                "autonomous_mission_execution_epoch",
                epoch_id,
                {
                    "mission_id": mission.id,
                    "epoch_id": epoch_id,
                    "epoch_number": 1,
                    "backlog_revision_id": expected_revision_id,
                    "backlog_revision_digest": canonical_digest,
                    "base_git_commit_sha": normalized_commit,
                    "epoch_branch": epoch_branch,
                    "origin": ExecutionEpochOrigin.INITIAL.value,
                    "temporal_workflow_id": temporal_workflow_id,
                    "temporal_first_run_id": temporal_run_id,
                    "actor": actor,
                    "command_id": command_id,
                    "version": result_mission_version,
                },
            )
            self.storage._event(
                "autonomous_mission.approved",
                "autonomous_mission",
                mission.id,
                {
                    "approval_id": approval_id,
                    "previous_phase": current["phase"],
                    "resulting_phase": MissionPhase.APPROVED.value,
                    "active_backlog_revision_id": expected_revision_id,
                    "active_execution_epoch_id": epoch_id,
                    "version": result_mission_version,
                    "actor": actor,
                },
            )
        return self.result(approval_id)

    @classmethod
    def _row_binding(cls, row: Any) -> dict[str, Any]:
        return {
            "mission_id": int(row["mission_id"]),
            "verification_id": int(row["verification_id"]),
            "pipeline_run_id": int(row["pipeline_run_id"]),
            "revision_id": int(row["revision_id"]),
            "revision_digest": str(row["revision_digest"]),
            "canonical_digest": str(row["canonical_digest"]),
            "source_id": int(row["source_id"]),
            "source_digest": str(row["source_digest"]),
            "planning_manifest_id": int(row["planning_manifest_id"]),
            "planning_manifest_digest": str(row["planning_manifest_digest"]),
            "planning_model_manifest": json.loads(
                row["planning_model_manifest_json"]
            ),
            "execution_role_model_manifest": json.loads(
                row["execution_role_model_manifest_json"]
            ),
            "execution_role_model_manifest_digest": str(
                row["execution_role_model_manifest_digest"]
            ),
            "provider_ids": json.loads(row["provider_ids_json"]),
            "tool_manifest": json.loads(row["tool_manifest_json"]),
            "tool_manifest_digest": str(row["tool_manifest_digest"]),
            "policy_version": int(row["policy_version"]),
            "policy_snapshot": json.loads(row["policy_snapshot_json"]),
            "policy_digest": str(row["policy_digest"]),
            "execution_epoch_id": int(row["execution_epoch_id"]),
            "execution_authorization_digest": str(
                row["execution_authorization_digest"]
            ),
            "approved_by": str(row["approved_by"]),
            "authentication_context": json.loads(
                row["authentication_context_json"]
            ),
            "authentication_context_digest": str(
                row["authentication_context_digest"]
            ),
            "expected_mission_version": int(row["expected_mission_version"]),
            "result_mission_version": int(row["result_mission_version"]),
            "command_id": str(row["command_id"]),
            "request_digest": str(row["request_digest"]),
            "reason": str(row["reason"]),
            "created_at": str(row["created_at"]),
        }

    def get(self, approval_id: int) -> AutonomousBacklogApproval:
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_backlog_approvals WHERE id=?",
            (approval_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown autonomous backlog approval: {approval_id}")
        completion = self.storage.db.execute(
            "SELECT * FROM autonomous_backlog_approval_completions "
            "WHERE approval_id=?",
            (approval_id,),
        ).fetchone()
        if not completion:
            raise RuntimeError("Backlog approval has no atomic completion evidence")
        binding = self._row_binding(row)
        if self._digest(binding) != row["approval_digest"]:
            raise RuntimeError("Backlog approval digest is corrupt")
        if (
            self._digest(binding["planning_model_manifest"])
            != binding["planning_manifest_digest"]
        ):
            raise RuntimeError("Approved planning model manifest is corrupt")
        if (
            self._digest(binding["execution_role_model_manifest"])
            != binding["execution_role_model_manifest_digest"]
        ):
            raise RuntimeError("Approved execution role/model manifest is corrupt")
        if self._digest(binding["tool_manifest"]) != binding["tool_manifest_digest"]:
            raise RuntimeError("Approved tool manifest is corrupt")
        if self._digest(binding["policy_snapshot"]) != binding["policy_digest"]:
            raise RuntimeError("Approved policy snapshot is corrupt")
        if (
            self._digest(binding["authentication_context"])
            != binding["authentication_context_digest"]
        ):
            raise RuntimeError("Approval authentication context is corrupt")
        authorization = self.authorizations.get_authorization(
            int(completion["authorization_id"])
        )
        if (
            self._digest(authorization.binding())
            != authorization.authorization_digest
        ):
            raise RuntimeError("Approved autonomous authorization is corrupt")
        if authorization.authorization_digest != row["execution_authorization_digest"]:
            raise RuntimeError("Approval authorization digest is corrupt")
        if (
            authorization.mission_id != int(row["mission_id"])
            or authorization.backlog_revision_id != int(row["revision_id"])
            or authorization.backlog_revision_digest != row["revision_digest"]
            or authorization.execution_epoch_id != int(row["execution_epoch_id"])
            or authorization.provider_ids != tuple(binding["provider_ids"])
            or authorization.role_model_manifest_digest
            != binding["execution_role_model_manifest_digest"]
            or authorization.policy_digest != binding["policy_digest"]
        ):
            raise RuntimeError("Approval and autonomous authorization scopes differ")
        completion_binding = {
            "approval_id": int(row["id"]),
            "approval_digest": str(row["approval_digest"]),
            "mission_id": int(row["mission_id"]),
            "verification_id": int(row["verification_id"]),
            "revision_id": int(row["revision_id"]),
            "revision_digest": str(row["revision_digest"]),
            "execution_epoch_id": int(row["execution_epoch_id"]),
            "authorization_id": authorization.id,
            "authorization_digest": authorization.authorization_digest,
            "result_mission_version": int(row["result_mission_version"]),
        }
        if self._digest(completion_binding) != completion["completion_digest"]:
            raise RuntimeError("Backlog approval completion digest is corrupt")
        return AutonomousBacklogApproval(
            id=int(row["id"]),
            identity=str(row["identity"]),
            mission_id=int(row["mission_id"]),
            verification_id=int(row["verification_id"]),
            pipeline_run_id=int(row["pipeline_run_id"]),
            revision_id=int(row["revision_id"]),
            revision_digest=str(row["revision_digest"]),
            canonical_digest=str(row["canonical_digest"]),
            source_id=int(row["source_id"]),
            source_digest=str(row["source_digest"]),
            planning_manifest_id=int(row["planning_manifest_id"]),
            planning_manifest_digest=str(row["planning_manifest_digest"]),
            planning_model_manifest=binding["planning_model_manifest"],
            execution_role_model_manifest=binding[
                "execution_role_model_manifest"
            ],
            execution_role_model_manifest_digest=str(
                row["execution_role_model_manifest_digest"]
            ),
            provider_ids=tuple(binding["provider_ids"]),
            tool_manifest=binding["tool_manifest"],
            tool_manifest_digest=str(row["tool_manifest_digest"]),
            policy_version=int(row["policy_version"]),
            policy_snapshot=binding["policy_snapshot"],
            policy_digest=str(row["policy_digest"]),
            execution_epoch_id=int(row["execution_epoch_id"]),
            execution_authorization_digest=str(
                row["execution_authorization_digest"]
            ),
            approved_by=str(row["approved_by"]),
            authentication_context=binding["authentication_context"],
            authentication_context_digest=str(
                row["authentication_context_digest"]
            ),
            expected_mission_version=int(row["expected_mission_version"]),
            result_mission_version=int(row["result_mission_version"]),
            command_id=str(row["command_id"]),
            request_digest=str(row["request_digest"]),
            reason=str(row["reason"]),
            approval_digest=str(row["approval_digest"]),
            created_at=str(row["created_at"]),
            authorization_id=authorization.id,
            completion_digest=str(completion["completion_digest"]),
        )

    def result(self, approval_id: int) -> ApprovalStartResult:
        approval = self.get(approval_id)
        return ApprovalStartResult(
            approval=approval,
            mission=self.missions.get(approval.mission_id),
            execution_epoch=self.checkpoints.get_epoch(
                approval.execution_epoch_id
            ),
            authorization=self.authorizations.get_authorization(
                approval.authorization_id
            ),
        )

    def approvals(self, mission_id: int) -> tuple[AutonomousBacklogApproval, ...]:
        return tuple(
            self.get(int(row["id"]))
            for row in self.storage.db.execute(
                "SELECT id FROM autonomous_backlog_approvals "
                "WHERE mission_id=? ORDER BY id",
                (mission_id,),
            )
        )
