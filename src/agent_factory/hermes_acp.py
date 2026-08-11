"""Concrete Hermes Agent Client Protocol stdio process driver."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import threading
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .providers import ProcessSupervisor, SENSITIVE_ENV_MARKERS
from .storage import SQLiteStorage
from .worker_runtime import RuntimeDriver, RuntimeDriverEvent, RuntimeLaunch
from .worktrees import WorktreeManager


HERMES_ACP_TOOLS = tuple(
    sorted(
        {
            "browser_back",
            "browser_cdp",
            "browser_click",
            "browser_console",
            "browser_dialog",
            "browser_exec",
            "browser_get_images",
            "browser_navigate",
            "browser_press",
            "browser_scroll",
            "browser_snapshot",
            "browser_type",
            "browser_vision",
            "delegate_task",
            "execute_code",
            "memory",
            "patch",
            "process",
            "read_file",
            "search_files",
            "session_search",
            "skill_manage",
            "skill_view",
            "skills_list",
            "terminal",
            "todo",
            "vision_analyze",
            "web_extract",
            "web_search",
            "write_file",
        }
    )
)
MUTABLE_TOOL_TITLES = (
    "write",
    "patch",
    "terminal",
    "execute",
    "process",
    "delegate",
    "manage skill",
)
VERSION_PATTERN = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)")


class HermesACPError(RuntimeError):
    pass


class HermesACPQualificationError(HermesACPError):
    pass


class HermesACPProtocolError(HermesACPError):
    pass


PermissionDecider = Callable[[str, dict[str, Any]], str | None]


@dataclass(frozen=True)
class HermesACPHealth:
    healthy: bool
    executable: str | None
    version: str | None
    protocol_version: int
    check_passed: bool
    workspace_access: bool
    reason: str

    def evidence(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "executable": self.executable,
            "version": self.version,
            "protocol_version": self.protocol_version,
            "check_passed": self.check_passed,
            "workspace_access": self.workspace_access,
            "reason": self.reason,
        }


class _ACPConnection:
    def __init__(
        self,
        process: subprocess.Popen[str],
        *,
        permission_decider: PermissionDecider | None,
        max_message_chars: int,
    ):
        self.process = process
        self.permission_decider = permission_decider
        self.max_message_chars = max_message_chars
        self.external_session_id = ""
        self._next_id = 1
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._events: deque[RuntimeDriverEvent] = deque()
        self._terminal_status: str | None = None
        self._terminal = threading.Event()
        self._stderr_chars = 0
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._stderr_reader = threading.Thread(
            target=self._read_stderr, daemon=True
        )
        self._reader.start()
        self._stderr_reader.start()

    def _append(self, event: RuntimeDriverEvent) -> None:
        with self._state_lock:
            self._events.append(event)

    def drain(self) -> list[RuntimeDriverEvent]:
        with self._state_lock:
            events = list(self._events)
            self._events.clear()
        return events

    @property
    def terminal_status(self) -> str | None:
        with self._state_lock:
            return self._terminal_status

    def set_terminal(self, status: str) -> None:
        with self._state_lock:
            self._terminal_status = status
        self._terminal.set()

    def wait_terminal(self, timeout: float) -> str | None:
        self._terminal.wait(timeout)
        return self.terminal_status

    def _send(self, message: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise HermesACPProtocolError("Hermes ACP stdin is unavailable")
        serialized = json.dumps(
            message, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        if len(serialized) > self.max_message_chars:
            raise HermesACPProtocolError("Hermes ACP request exceeds message limit")
        with self._write_lock:
            try:
                self.process.stdin.write(serialized + "\n")
                self.process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                raise HermesACPProtocolError("Hermes ACP transport closed") from exc

    def request(
        self, method: str, params: dict[str, Any], *, timeout: float
    ) -> dict[str, Any]:
        with self._state_lock:
            request_id = self._next_id
            self._next_id += 1
            response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue
        try:
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
            try:
                response = response_queue.get(timeout=timeout)
            except queue.Empty as exc:
                raise HermesACPProtocolError(
                    f"Hermes ACP {method} timed out"
                ) from exc
        finally:
            with self._state_lock:
                self._pending.pop(request_id, None)
        if "error" in response:
            error = response.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            raise HermesACPProtocolError(
                f"Hermes ACP {method} failed with JSON-RPC code {code}"
            )
        result = response.get("result", {})
        if result is None:
            return {}
        if not isinstance(result, dict):
            raise HermesACPProtocolError(
                f"Hermes ACP {method} returned a non-object result"
            )
        return result

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _respond(self, request_id: Any, result: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "id": request_id, "result": result})

    @staticmethod
    def _text(update: dict[str, Any]) -> str:
        content = update.get("content")
        if isinstance(content, dict):
            return str(content.get("text") or "")
        if isinstance(content, str):
            return content
        return ""

    @staticmethod
    def _is_mutable(update: dict[str, Any]) -> bool:
        title = str(update.get("title") or "").casefold()
        kind = str(update.get("kind") or "").casefold()
        return kind in {"edit", "delete", "move", "execute"} or any(
            marker in title for marker in MUTABLE_TOOL_TITLES
        )

    @staticmethod
    def _diffs(value: Any) -> Iterable[dict[str, Any]]:
        if isinstance(value, dict):
            if value.get("type") == "diff":
                yield value
            for nested in value.values():
                yield from _ACPConnection._diffs(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from _ACPConnection._diffs(nested)

    def _session_update(self, params: dict[str, Any]) -> None:
        update = params.get("update", {})
        if not isinstance(update, dict):
            return
        kind = str(update.get("sessionUpdate") or update.get("session_update") or "")
        if kind == "agent_message_chunk":
            text = self._text(update)
            if text:
                self._append(RuntimeDriverEvent("message", {"text": text}))
            return
        if kind == "agent_thought_chunk":
            text = self._text(update)
            if text:
                self._append(
                    RuntimeDriverEvent("message", {"channel": "thought", "text": text})
                )
            return
        if kind in {"tool_call", "tool_call_update"}:
            mutable = self._is_mutable(update)
            self._append(RuntimeDriverEvent("tool_call", dict(update), mutable=mutable))
            for diff in self._diffs(update.get("content")):
                self._append(
                    RuntimeDriverEvent(
                        "artifact",
                        {"kind": "candidate_diff", "diff": diff},
                    )
                )
            return
        if kind in {"usage_update", "session_info_update", "current_mode_update"}:
            self._append(RuntimeDriverEvent("status", {"state": kind, **update}))
            return
        self._append(
            RuntimeDriverEvent("message", {"channel": "acp", "update": update})
        )

    def _permission_request(self, request_id: Any, params: dict[str, Any]) -> None:
        selected = None
        if self.permission_decider is not None:
            try:
                selected = self.permission_decider(self.external_session_id, params)
            except Exception:
                selected = None
        options = params.get("options", [])
        option_ids = {
            str(option.get("optionId"))
            for option in options
            if isinstance(option, dict) and option.get("optionId")
        }
        if selected and selected in option_ids:
            self._append(
                RuntimeDriverEvent(
                    "tool_call",
                    {"permission": "allowed", "option_id": selected, **params},
                    mutable=True,
                )
            )
            self._respond(
                request_id,
                {"outcome": {"outcome": "selected", "optionId": selected}},
            )
            return
        self._append(
            RuntimeDriverEvent(
                "status", {"state": "permission_denied", "request": params}
            )
        )
        self._respond(request_id, {"outcome": {"outcome": "cancelled"}})

    def _dispatch(self, message: dict[str, Any]) -> None:
        response_id = message.get("id")
        if response_id is not None and ("result" in message or "error" in message):
            with self._state_lock:
                pending = self._pending.get(response_id)
            if pending is not None:
                with suppress(queue.Full):
                    pending.put_nowait(message)
            return
        method = message.get("method")
        params = message.get("params", {})
        if not isinstance(params, dict):
            params = {}
        if method == "session/update":
            self._session_update(params)
        elif method == "session/request_permission" and response_id is not None:
            self._permission_request(response_id, params)
        elif response_id is not None:
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": response_id,
                    "error": {
                        "code": -32601,
                        "message": "Client method is not allowlisted",
                    },
                }
            )

    def _read_loop(self) -> None:
        if self.process.stdout is None:
            self.set_terminal("failed")
            return
        try:
            for line in self.process.stdout:
                if len(line) > self.max_message_chars:
                    self._append(
                        RuntimeDriverEvent(
                            "error", {"error_type": "ACPMessageLimitExceeded"}
                        )
                    )
                    self.set_terminal("failed")
                    return
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    self._append(
                        RuntimeDriverEvent(
                            "error", {"error_type": "ACPInvalidJSON"}
                        )
                    )
                    continue
                if isinstance(message, dict):
                    self._dispatch(message)
        finally:
            if self.terminal_status is None:
                self._append(
                    RuntimeDriverEvent(
                        "error", {"error_type": "ACPTransportClosed"}
                    )
                )
                self.set_terminal("failed")
            with self._state_lock:
                pending = list(self._pending.values())
            for response_queue in pending:
                with suppress(queue.Full):
                    response_queue.put_nowait(
                        {"error": {"code": -32000, "message": "transport closed"}}
                    )

    def _read_stderr(self) -> None:
        if self.process.stderr is None:
            return
        for line in self.process.stderr:
            self._stderr_chars = min(
                self.max_message_chars, self._stderr_chars + len(line)
            )


class HermesACPProcessDriver(RuntimeDriver):
    """AF-045 JSON-RPC client and process-tree supervisor for Hermes ACP."""

    def __init__(
        self,
        storage: SQLiteStorage,
        workspace: Path,
        *,
        executable_candidates: Iterable[str] = ("hermes-acp",),
        executable_args: Iterable[str] = (),
        minimum_version: tuple[int, int, int] = (0, 20, 0),
        maximum_version_exclusive: tuple[int, int, int] = (0, 20, 1),
        protocol_version: int = 1,
        allowed_tools: Iterable[str] = HERMES_ACP_TOOLS,
        permission_decider: PermissionDecider | None = None,
        request_timeout: float = 15.0,
        prompt_timeout: float = 1800.0,
        max_message_chars: int = 1_000_000,
        supervisor: ProcessSupervisor | None = None,
    ):
        self.storage = storage
        self.workspace = workspace.resolve()
        self.executable_candidates = tuple(executable_candidates)
        self.executable_args = tuple(executable_args)
        self.minimum_version = minimum_version
        self.maximum_version_exclusive = maximum_version_exclusive
        self.protocol_version = protocol_version
        self.allowed_tools = tuple(sorted(set(allowed_tools)))
        self.permission_decider = permission_decider
        self.request_timeout = request_timeout
        self.prompt_timeout = prompt_timeout
        self.max_message_chars = max_message_chars
        self.supervisor = supervisor or ProcessSupervisor()
        self._connections: dict[str, _ACPConnection] = {}
        self._lock = threading.Lock()
        if not self.allowed_tools:
            raise ValueError("Hermes ACP tool allowlist cannot be empty")

    @staticmethod
    def _resolve_candidate(raw: str) -> str | None:
        expanded = os.path.expanduser(os.path.expandvars(raw))
        path = Path(expanded)
        if path.is_absolute() or path.parent != Path("."):
            resolved = path.resolve()
            return str(resolved) if resolved.is_file() else None
        located = shutil.which(expanded)
        return str(Path(located).resolve()) if located else None

    @staticmethod
    def _version(output: str) -> tuple[tuple[int, int, int], str] | None:
        match = VERSION_PATTERN.search(output)
        if not match:
            return None
        value = tuple(int(part) for part in match.groups())
        return value, ".".join(match.groups())

    def health(self, worktree: Path | None = None) -> HermesACPHealth:
        executable = next(
            (
                value
                for candidate in self.executable_candidates
                if (value := self._resolve_candidate(candidate)) is not None
            ),
            None,
        )
        workspace_access = self.workspace.is_dir() and os.access(self.workspace, os.R_OK)
        if worktree is not None:
            resolved_worktree = worktree.resolve()
            workspace_access = (
                workspace_access
                and resolved_worktree.is_dir()
                and os.access(resolved_worktree, os.R_OK | os.W_OK)
            )
        if not executable:
            return HermesACPHealth(
                False, None, None, self.protocol_version, False,
                workspace_access, "hermes-acp executable not found",
            )
        try:
            version_probe = subprocess.run(
                [executable, *self.executable_args, "--version"],
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.request_timeout,
                check=False,
            )
            parsed = self._version(version_probe.stdout or version_probe.stderr)
            if version_probe.returncode or parsed is None:
                return HermesACPHealth(
                    False, executable, None, self.protocol_version, False,
                    workspace_access, "Hermes version probe failed",
                )
            version_tuple, version = parsed
            compatible = (
                self.minimum_version <= version_tuple < self.maximum_version_exclusive
            )
            if not compatible:
                return HermesACPHealth(
                    False, executable, version, self.protocol_version, False,
                    workspace_access, "Hermes version is outside the qualified range",
                )
            check = subprocess.run(
                [executable, *self.executable_args, "--check"],
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.request_timeout,
                check=False,
            )
            check_passed = check.returncode == 0 and "OK" in check.stdout
        except (OSError, subprocess.TimeoutExpired):
            return HermesACPHealth(
                False, executable, None, self.protocol_version, False,
                workspace_access, "Hermes qualification command failed",
            )
        healthy = compatible and check_passed and workspace_access
        reason = "qualified" if healthy else "Hermes check or workspace access failed"
        return HermesACPHealth(
            healthy,
            executable,
            version,
            self.protocol_version,
            check_passed,
            workspace_access,
            reason,
        )

    @staticmethod
    def _environment() -> dict[str, str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
            and not key.startswith("AGENT_FACTORY_")
            and key not in {"PYTHONPATH", "PYTHONHOME"}
            and not any(marker in key.upper() for marker in SENSITIVE_ENV_MARKERS)
        }
        environment.update(
            {
                "GIT_TERMINAL_PROMPT": "0",
                "NO_COLOR": "1",
                "TERM": "dumb",
            }
        )
        return environment

    def _qualified(self, worktree: Path) -> HermesACPHealth:
        evidence = self.health(worktree)
        self.storage.event(
            "hermes.qualification.checked",
            "workspace",
            str(self.workspace),
            evidence.evidence(),
        )
        if not evidence.healthy:
            raise HermesACPQualificationError(evidence.reason)
        return evidence

    def _spawn(self, executable: str, worktree: Path) -> _ACPConnection:
        try:
            process = self.supervisor.spawn(
                [executable, *self.executable_args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=worktree,
                env=self._environment(),
            )
        except OSError as exc:
            raise HermesACPQualificationError(
                "Hermes ACP process could not be started"
            ) from exc
        return _ACPConnection(
            process,
            permission_decider=self.permission_decider,
            max_message_chars=self.max_message_chars,
        )

    def _initialize(self, connection: _ACPConnection) -> None:
        result = connection.request(
            "initialize",
            {
                "clientCapabilities": {
                    "auth": {"terminal": False},
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
                "clientInfo": {"name": "AgentFactory", "version": "0.1"},
                "protocolVersion": self.protocol_version,
            },
            timeout=self.request_timeout,
        )
        negotiated = result.get("protocolVersion")
        if negotiated != self.protocol_version:
            raise HermesACPProtocolError("Hermes ACP protocol version mismatch")

    def _worktree(self, launch: RuntimeLaunch) -> Path:
        if launch.binding is None:
            raise PermissionError("Hermes launch requires a durable runtime binding")
        if tuple(sorted(set(launch.binding.allowed_tools))) != self.allowed_tools:
            raise PermissionError("Hermes launch tool surface is not the qualified allowlist")
        context = self.storage.execution_context_package(launch.context_digest)
        if int(context["run_id"]) != launch.binding.run_id:
            raise PermissionError("Hermes run does not match its context package")
        return WorktreeManager(self.storage, self.workspace).assert_owned(
            launch.binding.worktree_id,
            launch.assignment_id,
            launch.fencing_token,
        )

    def _start_prompt(
        self, connection: _ACPConnection, launch: RuntimeLaunch
    ) -> None:
        canonical = json.dumps(
            launch.context, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

        def run() -> None:
            try:
                result = connection.request(
                    "session/prompt",
                    {
                        "prompt": [{"text": canonical, "type": "text"}],
                        "sessionId": connection.external_session_id,
                    },
                    timeout=self.prompt_timeout,
                )
                stop_reason = str(result.get("stopReason") or "end_turn")
                status = (
                    "cancelled"
                    if stop_reason == "cancelled"
                    else "failed"
                    if stop_reason == "refusal"
                    else "succeeded"
                )
                connection._append(
                    RuntimeDriverEvent(
                        "status", {"state": status, "stop_reason": stop_reason}
                    )
                )
                connection.set_terminal(status)
            except Exception as exc:
                connection._append(
                    RuntimeDriverEvent("error", {"error_type": type(exc).__name__})
                )
                connection.set_terminal("failed")

        threading.Thread(target=run, daemon=True).start()

    def _terminate(self, connection: _ACPConnection) -> dict[str, Any]:
        cleanup: dict[str, Any] = {}
        if connection.process.poll() is None:
            cleanup = self.supervisor.terminate_tree(connection.process)
        with suppress(subprocess.TimeoutExpired, OSError):
            connection.process.wait(timeout=5)
        for stream in (
            connection.process.stdin,
            connection.process.stdout,
            connection.process.stderr,
        ):
            if stream is not None:
                with suppress(OSError, ValueError):
                    stream.close()
        return cleanup

    def start(
        self, launch: RuntimeLaunch, *, control_session_id: int | None = None
    ) -> str:
        if control_session_id is None:
            raise ValueError("Hermes requires its durable Control Plane session identity")
        worktree = self._worktree(launch)
        health = self._qualified(worktree)
        if health.executable is None or health.version is None:
            raise HermesACPQualificationError("Hermes qualification evidence is incomplete")
        connection = self._spawn(health.executable, worktree)
        try:
            self._initialize(connection)
            result = connection.request(
                "session/new",
                {"cwd": str(worktree), "mcpServers": []},
                timeout=self.request_timeout,
            )
            external_id = str(result.get("sessionId") or "").strip()
            if not external_id:
                raise HermesACPProtocolError("Hermes did not return a session identity")
            connection.external_session_id = external_id
            binding = launch.binding
            assert binding is not None
            self.storage.record_hermes_acp_session(
                worker_session_id=control_session_id,
                task_id=int(launch.item.id),
                run_id=binding.run_id,
                stage_key=binding.stage_id,
                attempt_id=binding.attempt_id,
                assignment_id=launch.assignment_id,
                fencing_token=launch.fencing_token,
                agent_role=launch.agent.role,
                worktree_id=binding.worktree_id,
                context_digest=launch.context_digest,
                allowed_tools=self.allowed_tools,
                executable=health.executable,
                hermes_version=health.version,
                protocol_version=self.protocol_version,
                external_session_id=external_id,
                process_pid=connection.process.pid,
            )
            with self._lock:
                self._connections[external_id] = connection
            connection._append(
                RuntimeDriverEvent(
                    "status",
                    {
                        "state": "running",
                        "protocol_version": self.protocol_version,
                        "hermes_version": health.version,
                    },
                )
            )
            self._start_prompt(connection, launch)
            return external_id
        except Exception:
            self._terminate(connection)
            raise

    def _connection(self, external_session_id: str) -> _ACPConnection:
        with self._lock:
            connection = self._connections.get(external_session_id)
        if connection is None:
            raise KeyError(f"Hermes ACP session is not attached: {external_session_id}")
        return connection

    def resume(self, external_session_id: str) -> None:
        with self._lock:
            existing = self._connections.get(external_session_id)
        if existing is not None and existing.process.poll() is None:
            self.heartbeat(external_session_id)
            return
        row = self.storage.hermes_acp_session(external_session_id)
        worktree_row = self.storage.managed_worktree(int(row["worktree_id"]))
        worktree = WorktreeManager(self.storage, self.workspace).assert_owned(
            int(row["worktree_id"]),
            int(row["assignment_id"]),
            int(row["fencing_token"]),
        )
        health = self._qualified(worktree)
        if (
            health.executable != str(row["executable"])
            or health.version != str(row["hermes_version"])
            or tuple(json.loads(row["allowed_tools_json"])) != self.allowed_tools
            or str(worktree_row["path"]) != str(worktree)
        ):
            raise HermesACPQualificationError(
                "Hermes restart evidence no longer matches the durable session"
            )
        assert health.executable is not None
        connection = self._spawn(health.executable, worktree)
        try:
            self._initialize(connection)
            connection.external_session_id = external_session_id
            connection.request(
                "session/load",
                {
                    "cwd": str(worktree),
                    "mcpServers": [],
                    "sessionId": external_session_id,
                },
                timeout=self.request_timeout,
            )
            with self._lock:
                self._connections[external_session_id] = connection
            connection._append(
                RuntimeDriverEvent(
                    "status", {"state": "resumed", "stable_identity": True}
                )
            )
            self.storage.update_hermes_acp_session(
                external_session_id,
                status="running",
                process_pid=connection.process.pid,
            )
        except Exception:
            self._terminate(connection)
            raise

    def heartbeat(self, external_session_id: str) -> None:
        connection = self._connection(external_session_id)
        if connection.process.poll() is not None:
            raise HermesACPProtocolError("Hermes ACP process is not running")
        connection.request("session/list", {}, timeout=self.request_timeout)

    def cancel(self, external_session_id: str) -> None:
        connection = self._connection(external_session_id)
        with suppress(Exception):
            connection.notify(
                "session/cancel", {"sessionId": external_session_id}
            )
        cleanup = self._terminate(connection)
        connection._append(
            RuntimeDriverEvent(
                "status", {"state": "cancelled", "process_tree": cleanup}
            )
        )
        connection.set_terminal("cancelled")
        self.storage.update_hermes_acp_session(
            external_session_id, status="cancelled", process_pid=None
        )

    def collect_events(self, external_session_id: str) -> list[RuntimeDriverEvent]:
        return self._connection(external_session_id).drain()

    def finalize(self, external_session_id: str) -> str:
        connection = self._connection(external_session_id)
        status = connection.wait_terminal(min(self.request_timeout, 30.0))
        if status is None:
            if connection.process.poll() is not None:
                status = "failed"
            else:
                raise HermesACPProtocolError("Hermes prompt has not reached a terminal state")
        self._terminate(connection)
        self.storage.update_hermes_acp_session(
            external_session_id, status=status, process_pid=None
        )
        return status

    def detach(self, external_session_id: str) -> None:
        """Stop local transport while preserving the durable Hermes identity."""

        connection = self._connection(external_session_id)
        self._terminate(connection)
        with self._lock:
            self._connections.pop(external_session_id, None)
        self.storage.update_hermes_acp_session(
            external_session_id, status="suspended", process_pid=None
        )
