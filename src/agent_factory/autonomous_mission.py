"""Durable domain aggregate for opt-in Autonomous Missions."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from .lifecycle import ensure_transition
from .storage import SQLiteStorage


class MissionPhase(StrEnum):
    DRAFT = "DRAFT"
    SPECIFICATION_ANALYSIS = "SPECIFICATION_ANALYSIS"
    BACKLOG_GENERATION = "BACKLOG_GENERATION"
    WAITING_FOR_BACKLOG_APPROVAL = "WAITING_FOR_BACKLOG_APPROVAL"
    APPROVED = "APPROVED"
    ENVIRONMENT_DISCOVERY = "ENVIRONMENT_DISCOVERY"
    ENVIRONMENT_BOOTSTRAP = "ENVIRONMENT_BOOTSTRAP"
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    INTEGRATION = "INTEGRATION"
    FINAL_VALIDATION = "FINAL_VALIDATION"
    COMPLETED = "COMPLETED"


class MissionDisposition(StrEnum):
    """Runtime fence that preserves the mission's logical phase."""

    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    NEEDS_HUMAN_ACTION = "NEEDS_HUMAN_ACTION"
    REPLANNING = "REPLANNING"
    RECOVERING = "RECOVERING"
    FAILED = "FAILED"


@dataclass(frozen=True)
class AutonomousMissionConfiguration:
    """Version-one local execution profile stored with each mission."""

    schema_version: int = 1
    mode: str = "autonomous_local"
    max_concurrent_local_llm: int = 1
    default_model: str | None = None
    role_models: dict[str, str] = field(default_factory=dict)
    local_provider_ids: tuple[str, ...] = ()
    allowed_local_tool_profile: str = "autonomous-local-default"
    repository_path: str | None = None
    cost_budget_enforced: bool = False
    token_budget_enforced: bool = False
    automatic_repair: bool = True
    automatic_replanning: bool = True
    automatic_environment_bootstrap: bool = True
    automatic_service_recovery: bool = True
    durable_temporal: bool = True

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("Unsupported Autonomous Mission configuration version")
        if self.mode != "autonomous_local":
            raise ValueError("Autonomous Mission mode must be autonomous_local")
        if self.max_concurrent_local_llm < 1:
            raise ValueError("Local LLM concurrency must be at least one")
        if self.cost_budget_enforced or self.token_budget_enforced:
            raise ValueError(
                "Cost and token budgets are observational in autonomous local mode"
            )
        if not self.durable_temporal:
            raise ValueError("Autonomous Mission orchestration must be durable")
        if not self.allowed_local_tool_profile.strip():
            raise ValueError("An allowed local tool profile is required")
        if self.default_model is not None and not self.default_model.strip():
            raise ValueError("Default model cannot be blank")
        role_models = {
            str(role).strip(): str(model).strip()
            for role, model in self.role_models.items()
        }
        if any(not role or not model for role, model in role_models.items()):
            raise ValueError("Role and model names cannot be blank")
        provider_ids = tuple(
            sorted({str(provider).strip() for provider in self.local_provider_ids})
        )
        if any(not provider for provider in provider_ids):
            raise ValueError("Local provider identifiers cannot be blank")
        object.__setattr__(self, "role_models", role_models)
        object.__setattr__(self, "local_provider_ids", provider_ids)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AutonomousMissionConfiguration:
        payload = dict(value)
        payload["local_provider_ids"] = tuple(payload.get("local_provider_ids", ()))
        return cls(**payload)


@dataclass(frozen=True)
class AutonomousMission:
    id: int
    identity: str
    mission_key: str
    project_id: int
    intake_id: int | None
    blueprint_id: int | None
    name: str
    mission_owner: str
    phase: MissionPhase
    disposition: MissionDisposition
    configuration: AutonomousMissionConfiguration
    initial_specification: str
    initial_specification_digest: str | None
    specification_metadata: dict[str, Any]
    active_backlog_revision_id: int | None
    active_execution_epoch_id: int | None
    current_checkpoint_id: int | None
    version: int
    created_at: str
    updated_at: str

    @property
    def scheduling_allowed(self) -> bool:
        return (
            self.disposition is MissionDisposition.RUNNING
            and self.phase is not MissionPhase.COMPLETED
        )


class MissionVersionConflictError(RuntimeError):
    def __init__(self, mission_id: int, expected: int, actual: int):
        self.mission_id = mission_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Autonomous Mission {mission_id} version conflict: "
            f"expected {expected}, current {actual}"
        )


class MissionCommandConflictError(ValueError):
    """Raised when an idempotency key is reused for a different mutation."""


class AutonomousMissionService:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

    @classmethod
    def _digest(cls, value: Any) -> str:
        return hashlib.sha256(cls._json(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _required(value: str, label: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{label} is required")
        return normalized

    @staticmethod
    def _optional_id(value: Any) -> int | None:
        return int(value) if value is not None else None

    def _command_replay(
        self, command_id: str, request_digest: str
    ) -> AutonomousMission | None:
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_mission_commands WHERE command_id=?",
            (command_id,),
        ).fetchone()
        if not row:
            return None
        if row["request_digest"] != request_digest:
            raise MissionCommandConflictError(
                f"Command {command_id!r} is already bound to another request"
            )
        return self.get(int(row["mission_id"]), version=int(row["result_version"]))

    def _insert_state_version(
        self,
        *,
        mission_id: int,
        version: int,
        phase: MissionPhase,
        disposition: MissionDisposition,
        configuration_json: str,
        configuration_digest: str,
        active_backlog_revision_id: int | None,
        active_execution_epoch_id: int | None,
        current_checkpoint_id: int | None,
        actor: str,
        command_id: str,
        reason: str,
    ) -> None:
        self.storage.db.execute(
            """INSERT INTO autonomous_mission_state_versions(
                   identity,mission_id,version,phase,disposition,
                   configuration_json,configuration_digest,
                   active_backlog_revision_id,active_execution_epoch_id,
                   current_checkpoint_id,actor,command_id,reason
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self.storage._identity("autonomous-mission-state"),
                mission_id,
                version,
                phase.value,
                disposition.value,
                configuration_json,
                configuration_digest,
                active_backlog_revision_id,
                active_execution_epoch_id,
                current_checkpoint_id,
                actor,
                command_id,
                reason,
            ),
        )

    def _insert_command(
        self,
        *,
        mission_id: int,
        command_id: str,
        command_type: str,
        actor: str,
        expected_version: int | None,
        request_digest: str,
        result_version: int,
    ) -> None:
        self.storage.db.execute(
            """INSERT INTO autonomous_mission_commands(
                   identity,mission_id,command_id,command_type,actor,
                   expected_version,request_digest,result_version,result_json
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                self.storage._identity("autonomous-mission-command"),
                mission_id,
                command_id,
                command_type,
                actor,
                expected_version,
                request_digest,
                result_version,
                self._json({"mission_id": mission_id, "version": result_version}),
            ),
        )

    def create(
        self,
        *,
        name: str,
        mission_owner: str,
        actor: str,
        command_id: str,
        configuration: AutonomousMissionConfiguration | None = None,
        mission_key: str | None = None,
        description: str = "",
        initial_specification: str = "",
        specification_metadata: dict[str, Any] | None = None,
        intake_id: int | None = None,
        blueprint_id: int | None = None,
    ) -> AutonomousMission:
        name = self._required(name, "Mission name")
        mission_owner = self._required(mission_owner, "Mission owner")
        actor = self._required(actor, "Actor")
        command_id = self._required(command_id, "Command id")
        key = (mission_key or f"AFM-{uuid.uuid4().hex[:12]}").strip().upper()
        if not key:
            raise ValueError("Mission key is required")
        config = configuration or AutonomousMissionConfiguration()
        config_json = self._json(config.to_dict())
        config_digest = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
        specification = initial_specification.strip()
        specification_digest = (
            hashlib.sha256(specification.encode("utf-8")).hexdigest()
            if specification
            else None
        )
        metadata = specification_metadata or {}
        if not isinstance(metadata, dict):
            raise TypeError("Specification metadata must be an object")
        request = {
            "type": "create",
            "name": name,
            "mission_owner": mission_owner,
            "actor": actor,
            "mission_key": key,
            "description": description.strip(),
            "configuration_digest": config_digest,
            "initial_specification_digest": specification_digest,
            "specification_metadata": metadata,
            "intake_id": intake_id,
            "blueprint_id": blueprint_id,
        }
        request_digest = self._digest(request)
        replay = self._command_replay(command_id, request_digest)
        if replay:
            return replay

        with self.storage.db:
            self.storage._begin_immediate()
            replay = self._command_replay(command_id, request_digest)
            if replay:
                return replay
            project = self.storage.db.execute(
                "INSERT INTO projects(name,description) VALUES(?,?)",
                (
                    name,
                    description.strip()
                    or f"Autonomous Mission project container for {key}",
                ),
            )
            project_id = int(project.lastrowid)
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_missions(
                       identity,mission_key,project_id,intake_id,blueprint_id,name,
                       mission_owner,phase,disposition,configuration_json,
                       configuration_digest,initial_specification_text,
                       initial_specification_digest,specification_metadata_json
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-mission"),
                    key,
                    project_id,
                    intake_id,
                    blueprint_id,
                    name,
                    mission_owner,
                    MissionPhase.DRAFT.value,
                    MissionDisposition.RUNNING.value,
                    config_json,
                    config_digest,
                    specification,
                    specification_digest,
                    self._json(metadata),
                ),
            )
            mission_id = int(cursor.lastrowid)
            self._insert_state_version(
                mission_id=mission_id,
                version=1,
                phase=MissionPhase.DRAFT,
                disposition=MissionDisposition.RUNNING,
                configuration_json=config_json,
                configuration_digest=config_digest,
                active_backlog_revision_id=None,
                active_execution_epoch_id=None,
                current_checkpoint_id=None,
                actor=actor,
                command_id=command_id,
                reason="Autonomous Mission created",
            )
            self._insert_command(
                mission_id=mission_id,
                command_id=command_id,
                command_type="create",
                actor=actor,
                expected_version=None,
                request_digest=request_digest,
                result_version=1,
            )
            self.storage._event(
                "project.created",
                "project",
                project_id,
                {
                    "mission_id": mission_id,
                    "name": name,
                    "actor": actor,
                    "command_id": command_id,
                },
            )
            self.storage._event(
                "autonomous_mission.created",
                "autonomous_mission",
                mission_id,
                {
                    "mission_id": mission_id,
                    "project_id": project_id,
                    "mission_key": key,
                    "actor": actor,
                    "command_id": command_id,
                    "previous_phase": None,
                    "resulting_phase": MissionPhase.DRAFT.value,
                    "previous_disposition": None,
                    "resulting_disposition": MissionDisposition.RUNNING.value,
                    "version": 1,
                },
            )
        return self.get(mission_id)

    def get(self, mission_id: int, *, version: int | None = None) -> AutonomousMission:
        if version is None:
            row = self.storage.db.execute(
                "SELECT * FROM autonomous_missions WHERE id=?", (mission_id,)
            ).fetchone()
            state = row
        else:
            row = self.storage.db.execute(
                "SELECT * FROM autonomous_missions WHERE id=?", (mission_id,)
            ).fetchone()
            state = self.storage.db.execute(
                """SELECT * FROM autonomous_mission_state_versions
                   WHERE mission_id=? AND version=?""",
                (mission_id, version),
            ).fetchone()
        if not row or not state:
            suffix = f" at version {version}" if version is not None else ""
            raise KeyError(f"Unknown Autonomous Mission: {mission_id}{suffix}")
        configuration = AutonomousMissionConfiguration.from_dict(
            json.loads(state["configuration_json"])
        )
        return AutonomousMission(
            id=int(row["id"]),
            identity=str(row["identity"]),
            mission_key=str(row["mission_key"]),
            project_id=int(row["project_id"]),
            intake_id=self._optional_id(row["intake_id"]),
            blueprint_id=self._optional_id(row["blueprint_id"]),
            name=str(row["name"]),
            mission_owner=str(row["mission_owner"]),
            phase=MissionPhase(state["phase"]),
            disposition=MissionDisposition(state["disposition"]),
            configuration=configuration,
            initial_specification=str(row["initial_specification_text"]),
            initial_specification_digest=row["initial_specification_digest"],
            specification_metadata=json.loads(row["specification_metadata_json"]),
            active_backlog_revision_id=self._optional_id(
                state["active_backlog_revision_id"]
            ),
            active_execution_epoch_id=self._optional_id(
                state["active_execution_epoch_id"]
            ),
            current_checkpoint_id=self._optional_id(state["current_checkpoint_id"]),
            version=int(state["version"]),
            created_at=str(row["created_at"]),
            updated_at=str(
                state["created_at"] if version is not None else row["updated_at"]
            ),
        )

    def list(self) -> tuple[AutonomousMission, ...]:
        return tuple(
            self.get(int(row["id"]))
            for row in self.storage.db.execute(
                "SELECT id FROM autonomous_missions ORDER BY id"
            )
        )

    def transition_phase(
        self,
        mission_id: int,
        target: MissionPhase | str,
        *,
        actor: str,
        command_id: str,
        expected_version: int,
        reason: str,
    ) -> AutonomousMission:
        target_phase = MissionPhase(target)
        return self._transition(
            mission_id=mission_id,
            command_type="transition_phase",
            actor=actor,
            command_id=command_id,
            expected_version=expected_version,
            reason=reason,
            target_phase=target_phase,
            target_disposition=None,
        )

    def transition_disposition(
        self,
        mission_id: int,
        target: MissionDisposition | str,
        *,
        actor: str,
        command_id: str,
        expected_version: int,
        reason: str,
    ) -> AutonomousMission:
        target_disposition = MissionDisposition(target)
        return self._transition(
            mission_id=mission_id,
            command_type="transition_disposition",
            actor=actor,
            command_id=command_id,
            expected_version=expected_version,
            reason=reason,
            target_phase=None,
            target_disposition=target_disposition,
        )

    def _transition(
        self,
        *,
        mission_id: int,
        command_type: str,
        actor: str,
        command_id: str,
        expected_version: int,
        reason: str,
        target_phase: MissionPhase | None,
        target_disposition: MissionDisposition | None,
    ) -> AutonomousMission:
        actor = self._required(actor, "Actor")
        command_id = self._required(command_id, "Command id")
        reason = self._required(reason, "Transition reason")
        request = {
            "type": command_type,
            "mission_id": mission_id,
            "actor": actor,
            "expected_version": expected_version,
            "reason": reason,
            "target_phase": target_phase.value if target_phase else None,
            "target_disposition": (
                target_disposition.value if target_disposition else None
            ),
        }
        request_digest = self._digest(request)
        replay = self._command_replay(command_id, request_digest)
        if replay:
            return replay

        with self.storage.db:
            self.storage._begin_immediate()
            replay = self._command_replay(command_id, request_digest)
            if replay:
                return replay
            row = self.storage.db.execute(
                "SELECT * FROM autonomous_missions WHERE id=?", (mission_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown Autonomous Mission: {mission_id}")
            actual_version = int(row["version"])
            if actual_version != expected_version:
                raise MissionVersionConflictError(
                    mission_id, expected_version, actual_version
                )
            source_phase = MissionPhase(row["phase"])
            source_disposition = MissionDisposition(row["disposition"])
            if source_phase is MissionPhase.COMPLETED:
                raise ValueError("Completed Autonomous Missions are immutable")
            if target_phase is not None:
                if source_disposition is not MissionDisposition.RUNNING:
                    raise ValueError(
                        "Mission phase cannot advance while execution is fenced"
                    )
                ensure_transition(
                    "autonomous_mission_phase", source_phase.value, target_phase.value
                )
            if target_disposition is not None:
                ensure_transition(
                    "autonomous_mission_disposition",
                    source_disposition.value,
                    target_disposition.value,
                )
            resulting_phase = target_phase or source_phase
            resulting_disposition = target_disposition or source_disposition
            result_version = actual_version + 1
            self._insert_state_version(
                mission_id=mission_id,
                version=result_version,
                phase=resulting_phase,
                disposition=resulting_disposition,
                configuration_json=str(row["configuration_json"]),
                configuration_digest=str(row["configuration_digest"]),
                active_backlog_revision_id=self._optional_id(
                    row["active_backlog_revision_id"]
                ),
                active_execution_epoch_id=self._optional_id(
                    row["active_execution_epoch_id"]
                ),
                current_checkpoint_id=self._optional_id(row["current_checkpoint_id"]),
                actor=actor,
                command_id=command_id,
                reason=reason,
            )
            updated = self.storage.db.execute(
                """UPDATE autonomous_missions
                      SET phase=?,disposition=?,version=?,updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND version=?""",
                (
                    resulting_phase.value,
                    resulting_disposition.value,
                    result_version,
                    mission_id,
                    actual_version,
                ),
            )
            if updated.rowcount != 1:
                raise MissionVersionConflictError(
                    mission_id, expected_version, actual_version + 1
                )
            self._insert_command(
                mission_id=mission_id,
                command_id=command_id,
                command_type=command_type,
                actor=actor,
                expected_version=expected_version,
                request_digest=request_digest,
                result_version=result_version,
            )
            event_suffix = (
                resulting_phase.value.lower()
                if target_phase is not None
                else resulting_disposition.value.lower()
            )
            self.storage._event(
                f"autonomous_mission.{event_suffix}",
                "autonomous_mission",
                mission_id,
                {
                    "mission_id": mission_id,
                    "project_id": int(row["project_id"]),
                    "actor": actor,
                    "command_id": command_id,
                    "reason": reason,
                    "previous_phase": source_phase.value,
                    "resulting_phase": resulting_phase.value,
                    "previous_disposition": source_disposition.value,
                    "resulting_disposition": resulting_disposition.value,
                    "version": result_version,
                },
            )
        return self.get(mission_id)
