"""Lifecycle-aware worker runtime contract shared by direct CLI and Hermes."""

from __future__ import annotations

import hashlib
import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .models import Agent, ExecutionApproval, WorkItem
from .providers import Provider
from .storage import SQLiteStorage


class FallbackForbiddenError(PermissionError):
    """Raised when a runtime has crossed its first mutable boundary."""


@dataclass(frozen=True)
class RuntimeLaunch:
    assignment_id: int
    fencing_token: int
    agent: Agent
    item: WorkItem
    context: dict[str, Any]
    context_digest: str
    approval: ExecutionApproval | None = None
    mutable: bool = False
    permission_bridge_id: str | None = None

    def durable_scope(self) -> dict[str, Any]:
        context_json = json.dumps(
            self.context, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return {
            "assignment_id": self.assignment_id,
            "fencing_token": self.fencing_token,
            "task_id": self.item.id,
            "project_id": self.item.project_id,
            "worker_id": self.agent.id,
            "role": self.agent.role,
            "permissions": sorted(set(self.item.permissions)),
            "mutable": self.mutable,
            "permission_bridge_id": self.permission_bridge_id,
            "context_sha256": hashlib.sha256(context_json.encode("utf-8")).hexdigest(),
            "context_package_digest": self.context_digest,
        }


@dataclass(frozen=True)
class RuntimeDriverEvent:
    kind: str
    payload: dict[str, Any]
    mutable: bool = False


@dataclass(frozen=True)
class RuntimeEvent:
    id: int
    session_id: int
    sequence: int
    kind: str
    payload: dict[str, Any]
    mutable: bool
    created_at: str


@dataclass(frozen=True)
class RuntimeSession:
    id: int
    identity: str
    assignment_id: int
    runtime: str
    external_session_id: str | None
    status: str
    mutable_action_count: int
    heartbeat_at: str | None
    finalized_at: str | None


@dataclass(frozen=True)
class RuntimeFinalResult:
    session: RuntimeSession
    status: str
    events: tuple[RuntimeEvent, ...]
    tool_calls: tuple[dict[str, Any], ...]
    artifacts: tuple[dict[str, Any], ...]
    messages: tuple[dict[str, Any], ...]


class RuntimeDriver(ABC):
    """Transport/process implementation below the Control Plane lifecycle."""

    mutation_boundary_on_start: bool = False

    @abstractmethod
    def start(self, launch: RuntimeLaunch) -> str: ...

    @abstractmethod
    def resume(self, external_session_id: str) -> None: ...

    @abstractmethod
    def heartbeat(self, external_session_id: str) -> None: ...

    @abstractmethod
    def cancel(self, external_session_id: str) -> None: ...

    @abstractmethod
    def collect_events(self, external_session_id: str) -> list[RuntimeDriverEvent]: ...

    @abstractmethod
    def finalize(self, external_session_id: str) -> str: ...


class DirectCLIProviderDriver(RuntimeDriver):
    """Adapt a synchronous AF-005 Provider to the AF-044 lifecycle contract."""

    mutation_boundary_on_start = True

    def __init__(self, provider: Provider):
        self.provider = provider
        self._sessions: dict[str, dict[str, Any]] = {}

    def start(self, launch: RuntimeLaunch) -> str:
        external_id = f"direct:{uuid.uuid4().hex}"
        result = self.provider.execute(
            launch.agent,
            launch.item,
            launch.context,
            launch.approval,
        )
        events = [
            RuntimeDriverEvent(
                "status",
                {"state": "started", "provider": result.provider},
            )
        ]
        tool_calls = result.metadata.get("tool_calls", [])
        if isinstance(tool_calls, list):
            events.extend(
                RuntimeDriverEvent("tool_call", dict(call), mutable=bool(call.get("mutable")))
                for call in tool_calls
                if isinstance(call, dict)
            )
        artifacts = result.metadata.get("artifacts", [])
        if isinstance(artifacts, list):
            events.extend(
                RuntimeDriverEvent("artifact", dict(artifact))
                for artifact in artifacts
                if isinstance(artifact, dict)
            )
        if result.content:
            events.append(
                RuntimeDriverEvent(
                    "artifact",
                    {
                        "kind": "provider_output",
                        "provider": result.provider,
                        "content": result.content,
                        "sha256": hashlib.sha256(
                            result.content.encode("utf-8")
                        ).hexdigest(),
                    },
                )
            )
        if result.error:
            events.append(
                RuntimeDriverEvent(
                    "error", {"provider": result.provider, "message": result.error}
                )
            )
        terminal = "succeeded" if result.ok else "failed"
        events.append(RuntimeDriverEvent("status", {"state": terminal}))
        self._sessions[external_id] = {
            "events": events,
            "status": terminal,
            "cancelled": False,
        }
        return external_id

    def _session(self, external_session_id: str) -> dict[str, Any]:
        try:
            return self._sessions[external_session_id]
        except KeyError as exc:
            raise KeyError(f"Unknown direct CLI session: {external_session_id}") from exc

    def resume(self, external_session_id: str) -> None:
        self._session(external_session_id)

    def heartbeat(self, external_session_id: str) -> None:
        self._session(external_session_id)

    def cancel(self, external_session_id: str) -> None:
        session = self._session(external_session_id)
        session["cancelled"] = True
        session["status"] = "cancelled"
        session["events"].append(
            RuntimeDriverEvent("status", {"state": "cancelled"})
        )

    def collect_events(self, external_session_id: str) -> list[RuntimeDriverEvent]:
        session = self._session(external_session_id)
        events = list(session["events"])
        session["events"].clear()
        return events

    def finalize(self, external_session_id: str) -> str:
        return str(self._session(external_session_id)["status"])


class WorkerRuntime(ABC):
    operations = frozenset(
        {"start", "resume", "heartbeat", "cancel", "collect_events", "finalize"}
    )

    def __init__(
        self,
        storage: SQLiteStorage,
        driver: RuntimeDriver,
        *,
        runtime_id: str,
    ):
        self.storage = storage
        self.driver = driver
        self.runtime_id = runtime_id

    def _validate_launch(self, launch: RuntimeLaunch) -> None:
        self.storage.assert_fenced_lease(
            launch.assignment_id, launch.fencing_token
        )
        assignment = self.storage.db.execute(
            "SELECT task_id,agent_id FROM assignments WHERE id=?",
            (launch.assignment_id,),
        ).fetchone()
        if not assignment:
            raise KeyError(f"Unknown assignment: {launch.assignment_id}")
        if launch.item.id is None or int(assignment["task_id"]) != launch.item.id:
            raise PermissionError("Runtime launch task does not match its assignment")
        if str(assignment["agent_id"]) != launch.agent.id:
            raise PermissionError("Runtime launch worker does not own its assignment")
        context_json = json.dumps(
            launch.context, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        actual_digest = hashlib.sha256(context_json.encode("utf-8")).hexdigest()
        if actual_digest != launch.context_digest:
            raise PermissionError("Runtime context does not match its immutable digest")
        self.storage.assert_execution_context_scope(
            launch.context_digest,
            task_id=launch.item.id,
            assignment_id=launch.assignment_id,
            fencing_token=launch.fencing_token,
        )

    def start(self, launch: RuntimeLaunch) -> RuntimeSession:
        self._validate_launch(launch)
        session_id = self.storage.create_runtime_session(
            assignment_id=launch.assignment_id,
            runtime=self.runtime_id,
            request=launch.durable_scope(),
            context_digest=launch.context_digest,
            fencing_token=launch.fencing_token,
        )
        try:
            external_id = self.driver.start(launch)
            self.storage.start_runtime_session(session_id, external_id)
            if launch.mutable and self.driver.mutation_boundary_on_start:
                self.storage.append_runtime_event(
                    session_id,
                    kind="status",
                    payload={"state": "mutable_execution_started"},
                    mutable=True,
                )
        except Exception as exc:
            self.storage.append_runtime_event(
                session_id,
                kind="error",
                payload={"error_type": type(exc).__name__},
            )
            self.storage.finalize_runtime_session(
                session_id,
                status="failed",
                result={"status": "failed", "error_type": type(exc).__name__},
            )
            raise
        return self.session(session_id)

    def session(self, session_id: int) -> RuntimeSession:
        row = self.storage.runtime_session(session_id)
        return RuntimeSession(
            id=int(row["id"]),
            identity=str(row["identity"]),
            assignment_id=int(row["assignment_id"]),
            runtime=str(row["runtime"]),
            external_session_id=(
                str(row["external_session_id"])
                if row["external_session_id"] is not None
                else None
            ),
            status=str(row["status"]),
            mutable_action_count=int(row["mutable_action_count"]),
            heartbeat_at=(
                str(row["heartbeat_at"]) if row["heartbeat_at"] else None
            ),
            finalized_at=(
                str(row["finalized_at"]) if row["finalized_at"] else None
            ),
        )

    def resume(self, session_id: int) -> RuntimeSession:
        session = self.session(session_id)
        if not session.external_session_id:
            raise ValueError("Runtime session has no external identity")
        self.driver.resume(session.external_session_id)
        self.storage.resume_runtime_session(session_id)
        return self.session(session_id)

    def heartbeat(self, session_id: int) -> str:
        session = self.session(session_id)
        if not session.external_session_id:
            raise ValueError("Runtime session has no external identity")
        self.driver.heartbeat(session.external_session_id)
        heartbeat = self.storage.heartbeat_runtime_session(session_id)
        self.storage.append_runtime_event(
            session_id,
            kind="heartbeat",
            payload={"heartbeat_at": heartbeat},
        )
        return heartbeat

    @staticmethod
    def _event(row: Any) -> RuntimeEvent:
        payload = json.loads(row["payload_json"])
        if not isinstance(payload, dict):
            raise TypeError("Stored runtime event payload must be an object")
        return RuntimeEvent(
            id=int(row["id"]),
            session_id=int(row["session_id"]),
            sequence=int(row["sequence"]),
            kind=str(row["kind"]),
            payload=payload,
            mutable=bool(row["mutable"]),
            created_at=str(row["created_at"]),
        )

    def collect_events(
        self, session_id: int, *, after_sequence: int = 0
    ) -> tuple[RuntimeEvent, ...]:
        session = self.session(session_id)
        if not session.external_session_id:
            raise ValueError("Runtime session has no external identity")
        if session.status in {"starting", "running", "suspended"}:
            for event in self.driver.collect_events(session.external_session_id):
                if not isinstance(event.payload, dict):
                    raise TypeError("Runtime driver event payload must be an object")
                self.storage.append_runtime_event(
                    session_id,
                    kind=event.kind,
                    payload=event.payload,
                    mutable=event.mutable,
                )
        return tuple(
            self._event(row)
            for row in self.storage.runtime_events(
                session_id, after_sequence=after_sequence
            )
        )

    def cancel(self, session_id: int, *, reason: str) -> RuntimeSession:
        session = self.session(session_id)
        if session.status == "cancelled":
            return session
        if not session.external_session_id:
            raise ValueError("Runtime session has no external identity")
        self.driver.cancel(session.external_session_id)
        self.storage.append_runtime_event(
            session_id,
            kind="status",
            payload={"state": "cancelled", "reason": reason},
        )
        self.storage.cancel_runtime_session(session_id, reason=reason)
        return self.session(session_id)

    def finalize(self, session_id: int) -> RuntimeFinalResult:
        session = self.session(session_id)
        if not session.external_session_id:
            raise ValueError("Runtime session has no external identity")
        if session.status not in {"succeeded", "failed", "cancelled"}:
            self.collect_events(session_id)
            status = self.driver.finalize(session.external_session_id)
            self.storage.finalize_runtime_session(
                session_id,
                status=status,
                result={"status": status},
            )
        events = tuple(
            self._event(row) for row in self.storage.runtime_events(session_id)
        )
        session = self.session(session_id)
        return RuntimeFinalResult(
            session=session,
            status=session.status,
            events=events,
            tool_calls=tuple(
                event.payload for event in events if event.kind == "tool_call"
            ),
            artifacts=tuple(
                event.payload for event in events if event.kind == "artifact"
            ),
            messages=tuple(
                event.payload for event in events if event.kind == "message"
            ),
        )

    def assert_fallback_allowed(self, session_id: int) -> None:
        if not self.storage.runtime_fallback_allowed(session_id):
            raise FallbackForbiddenError(
                "Runtime fallback is forbidden after the first mutable action"
            )


class DirectCLIWorkerRuntime(WorkerRuntime):
    def __init__(self, storage: SQLiteStorage, driver: RuntimeDriver):
        super().__init__(storage, driver, runtime_id="direct-cli")


class HermesACPWorkerRuntime(WorkerRuntime):
    def __init__(
        self,
        storage: SQLiteStorage,
        driver: RuntimeDriver,
        *,
        transport_mode: str = "acp",
    ):
        if transport_mode not in {"acp", "oneshot"}:
            raise ValueError("Hermes transport mode must be acp or oneshot")
        self.transport_mode = transport_mode
        super().__init__(storage, driver, runtime_id=f"hermes-{transport_mode}")

    def _validate_launch(self, launch: RuntimeLaunch) -> None:
        super()._validate_launch(launch)
        if self.transport_mode == "oneshot" and launch.mutable:
            raise PermissionError(
                "Hermes one-shot is qualification/read-only only; mutable sessions require ACP"
            )
        if (
            self.transport_mode == "acp"
            and launch.mutable
            and not (launch.permission_bridge_id or "").strip()
        ):
            raise PermissionError(
                "Mutable Hermes ACP sessions require a permission bridge"
            )
