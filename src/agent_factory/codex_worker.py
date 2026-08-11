"""Qualified writable Codex CLI worker for one leased task worktree."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .providers import BoundedCapture, ProcessSupervisor, SENSITIVE_ENV_MARKERS
from .sandbox import _candidate_manifest, _tree_snapshot
from .storage import SQLiteStorage
from .worker_runtime import RuntimeDriver, RuntimeDriverEvent, RuntimeLaunch


CODEX_PERMISSION_PROFILE = {
    "sandbox": "workspace-write",
    "approval_policy": "never",
    "network_for_model_commands": "sandbox-default-deny",
    "additional_write_directories": [],
    "forbidden_authorities": [
        "close_issue", "final_approval", "merge", "push", "read_secrets"
    ],
}
CODEX_EXEC_ARGS = (
    "--ask-for-approval", "never", "exec", "--strict-config",
    "--sandbox", "workspace-write", "--ephemeral", "--ignore-user-config",
    "--color", "never", "--json", "--cd",
)
VERSION_PATTERN = re.compile(r"codex-cli\s+([^\s]+)", re.IGNORECASE)


@dataclass(frozen=True)
class CodexWorkerHealth:
    healthy: bool
    executable: str | None
    version: str | None
    interface_qualified: bool
    workspace_access: bool
    reason: str


class CodexCLIProcessDriver(RuntimeDriver):
    """Async process driver with a reviewed, non-widenable Codex invocation."""

    mutation_boundary_on_start = True

    def __init__(
        self,
        storage: SQLiteStorage,
        workspace: Path,
        *,
        executable_candidates: Iterable[str] = ("codex",),
        executable_args: Iterable[str] = (),
        max_seconds: int = 180,
        max_output_chars: int = 200_000,
        supervisor: ProcessSupervisor | None = None,
    ):
        self.storage = storage
        self.workspace = workspace.resolve()
        self.executable_candidates = tuple(executable_candidates)
        self.executable_args = tuple(executable_args)
        self.max_seconds = max_seconds
        self.max_output_chars = max_output_chars
        self.supervisor = supervisor or ProcessSupervisor()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _resolve(raw: str) -> str | None:
        expanded = os.path.expandvars(os.path.expanduser(raw))
        candidate = Path(expanded)
        if candidate.is_absolute() or candidate.parent != Path("."):
            resolved = candidate.resolve()
            return str(resolved) if resolved.is_file() else None
        located = shutil.which(expanded)
        return str(Path(located).resolve()) if located else None

    @staticmethod
    def _environment() -> dict[str, str]:
        environment = {
            key: value for key, value in os.environ.items()
            if not any(marker in key.upper() for marker in SENSITIVE_ENV_MARKERS)
        }
        environment.update({
            "NO_COLOR": "1", "TERM": "dumb", "GIT_TERMINAL_PROMPT": "0",
            "GH_PROMPT_DISABLED": "1", "GIT_CONFIG_NOSYSTEM": "1",
        })
        return environment

    def health(self, worktree: Path | None = None) -> CodexWorkerHealth:
        executable = next(
            (value for raw in self.executable_candidates if (value := self._resolve(raw))),
            None,
        )
        if executable is None:
            return CodexWorkerHealth(False, None, None, False, False, "executable unavailable")
        prefix = [executable, *self.executable_args]
        try:
            version_probe = subprocess.run(
                [*prefix, "--version"], shell=False, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=8, check=False,
                env=self._environment(),
            )
            match = VERSION_PATTERN.search(version_probe.stdout or version_probe.stderr)
            version = match.group(1) if version_probe.returncode == 0 and match else None
            help_probe = subprocess.run(
                [*prefix, "--ask-for-approval", "never", "exec", "--help"],
                shell=False, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=8, check=False, env=self._environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return CodexWorkerHealth(False, executable, None, False, False, type(exc).__name__)
        help_text = help_probe.stdout or help_probe.stderr
        qualified = help_probe.returncode == 0 and all(
            flag in help_text for flag in ("--sandbox", "workspace-write", "--ephemeral", "--json", "--cd")
        )
        accessible = worktree is None or (worktree.resolve().is_dir() and self._within(worktree.resolve(), self.workspace))
        healthy = bool(version and qualified and accessible)
        return CodexWorkerHealth(
            healthy, executable, version, qualified, accessible,
            "qualified" if healthy else "version, interface, or workspace qualification failed",
        )

    @staticmethod
    def _within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _prompt(launch: RuntimeLaunch) -> str:
        return json.dumps({
            "schema_version": 1,
            "role": "Implementation Worker",
            "context_package": launch.context,
            "constraints": {
                "write_scope": "current task worktree only",
                "forbidden": CODEX_PERMISSION_PROFILE["forbidden_authorities"],
                "handoff": "Report changed files, commands run, remaining risks, and summary.",
            },
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _parsed_output(stdout: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        commands: list[dict[str, Any]] = []
        messages: list[str] = []
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            item = event.get("item")
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type", ""))
            if kind == "command_execution":
                commands.append({
                    "command": str(item.get("command", "")),
                    "status": str(item.get("status", "")),
                    "exit_code": item.get("exit_code"),
                })
            elif kind == "agent_message" and item.get("text"):
                messages.append(str(item["text"]))
        return commands, {
            "summary": messages[-1] if messages else "",
            "message_count": len(messages),
        }

    def _launch_scope(self, launch: RuntimeLaunch) -> tuple[Path, Any]:
        if not launch.mutable or launch.binding is None:
            raise PermissionError("Codex implementation worker requires a mutable runtime binding")
        if launch.agent.role != "Implementation Worker" or launch.agent.provider != "codex":
            raise PermissionError("Codex writable runtime is restricted to the Codex implementation role")
        binding = launch.binding
        worktree = self.storage.managed_worktree(binding.worktree_id)
        if (
            int(worktree["assignment_id"]) != launch.assignment_id
            or int(worktree["attempt_id"] or 0) != binding.attempt_id
            or int(worktree["fencing_token"] or 0) != launch.fencing_token
            or str(worktree["status"]) not in {"ready", "dirty"}
        ):
            raise PermissionError("Codex worktree is not owned by the live attempt")
        path = Path(str(worktree["path"])).resolve()
        if not path.is_dir() or not self._within(path, self.workspace):
            raise PermissionError("Codex worktree is outside the Control Plane workspace")
        return path, worktree

    def start(self, launch: RuntimeLaunch, *, control_session_id: int | None = None) -> str:
        if control_session_id is None:
            raise ValueError("Codex driver requires a durable Control Plane session")
        worktree, worktree_row = self._launch_scope(launch)
        health = self.health(worktree)
        if not health.healthy or not health.executable or not health.version:
            raise RuntimeError(f"Codex worker is not qualified: {health.reason}")
        model = launch.agent.model.split(":", 1)[-1] if launch.agent.model else ""
        command = [
            health.executable, *self.executable_args, *CODEX_EXEC_ARGS, str(worktree),
            *( ["--model", model] if model else []), "-",
        ]
        prompt = self._prompt(launch)
        before = _tree_snapshot(worktree)
        external_id = f"codex-worker:{uuid.uuid4().hex}"
        proc = self.supervisor.spawn(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", cwd=worktree,
            env=self._environment(),
        )
        capture = BoundedCapture(proc, self.max_output_chars)
        capture.start()
        state = {
            "proc": proc, "capture": capture, "events": [], "status": "running",
            "cancel": threading.Event(), "done": threading.Event(), "before": before,
            "launch": launch, "worktree": worktree, "worktree_row": worktree_row,
            "control_session_id": control_session_id, "health": health,
            "invocation": [Path(command[0]).name, *command[1:]],
        }
        with self._lock:
            self._sessions[external_id] = state
        writer = threading.Thread(
            target=self._write_prompt, args=(proc, prompt), daemon=True,
            name=f"codex-prompt-{control_session_id}",
        )
        monitor = threading.Thread(
            target=self._monitor, args=(external_id,), daemon=True,
            name=f"codex-monitor-{control_session_id}",
        )
        writer.start()
        monitor.start()
        return external_id

    @staticmethod
    def _write_prompt(proc: subprocess.Popen[str], prompt: str) -> None:
        if proc.stdin is None:
            return
        with suppress(BrokenPipeError, OSError, ValueError):
            proc.stdin.write(prompt)
            proc.stdin.close()

    def _monitor(self, external_id: str) -> None:
        state = self._sessions[external_id]
        proc, capture = state["proc"], state["capture"]
        started = time.monotonic()
        timed_out = output_limited = False
        while proc.poll() is None:
            if state["cancel"].is_set():
                self.supervisor.terminate_tree(proc)
                break
            if capture.overflow.is_set():
                output_limited = True
                self.supervisor.terminate_tree(proc)
                break
            if time.monotonic() - started >= self.max_seconds:
                timed_out = True
                self.supervisor.terminate_tree(proc)
                break
            time.sleep(0.02)
        with suppress(subprocess.TimeoutExpired, OSError):
            proc.wait(timeout=5)
        capture.join(5)
        captured = capture.snapshot()
        stdout, stderr = str(captured["stdout"]), str(captured["stderr"])
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                with suppress(OSError, ValueError):
                    stream.close()
        after = _tree_snapshot(state["worktree"])
        candidate = _candidate_manifest(state["before"], after)
        candidate_json = json.dumps(candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        diff_digest = hashlib.sha256(candidate_json.encode("utf-8")).hexdigest()
        changed_files = [change["path"] for change in candidate["changes"]]
        commands, handoff = self._parsed_output(stdout)
        if state["cancel"].is_set():
            status = "cancelled"
        elif timed_out:
            status = "timed_out"
        elif output_limited or capture.overflow.is_set():
            status = "output_limited"
        elif proc.returncode == 0:
            status = "succeeded"
        else:
            status = "failed"
        evidence_dir = self.workspace / ".agent-factory" / "codex-evidence" / external_id.split(":", 1)[1]
        evidence_dir.mkdir(parents=True, exist_ok=False)
        evidence = {
            "schema_version": 1, "status": status, "exit_code": proc.returncode,
            "changed_files": changed_files, "diff_digest": diff_digest,
            "commands": commands, "handoff": handoff,
            "permission_profile": CODEX_PERMISSION_PROFILE,
            "invocation": state["invocation"], "codex_version": state["health"].version,
        }
        evidence_json = json.dumps(evidence, sort_keys=True, indent=2, ensure_ascii=False)
        evidence_digest = hashlib.sha256(evidence_json.encode("utf-8")).hexdigest()
        (evidence_dir / "result.json").write_text(evidence_json, encoding="utf-8")
        (evidence_dir / "events.jsonl").write_text(stdout, encoding="utf-8")
        (evidence_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
        launch, binding = state["launch"], state["launch"].binding
        state["record_kwargs"] = dict(
            worker_session_id=state["control_session_id"], task_id=int(launch.item.id),
            run_id=binding.run_id, stage_key=binding.stage_id,
            attempt_id=binding.attempt_id, assignment_id=launch.assignment_id,
            worktree_id=binding.worktree_id, context_digest=launch.context_digest,
            codex_version=state["health"].version,
            permission_profile=CODEX_PERMISSION_PROFILE, invocation=state["invocation"],
            executed_commands=commands, changed_files=changed_files,
            diff_digest=diff_digest, status=status, exit_code=proc.returncode,
            handoff=handoff, evidence_directory=str(evidence_dir.relative_to(self.workspace)),
            evidence_digest=evidence_digest,
        )
        events = [
            RuntimeDriverEvent("tool_call", command, mutable=True) for command in commands
        ]
        events.append(RuntimeDriverEvent("artifact", {
            "kind": "candidate_change", "changed_files": changed_files,
            "diff_digest": diff_digest, "handoff": handoff,
        }, mutable=bool(changed_files)))
        events.append(RuntimeDriverEvent("status", {"state": status}))
        with self._lock:
            state["events"].extend(events)
            state["status"] = status
            state["done"].set()

    def _session(self, external_session_id: str) -> dict[str, Any]:
        try:
            return self._sessions[external_session_id]
        except KeyError as exc:
            raise KeyError(f"Unknown Codex worker session: {external_session_id}") from exc

    def resume(self, external_session_id: str) -> None:
        self._session(external_session_id)

    def heartbeat(self, external_session_id: str) -> None:
        if self._session(external_session_id)["proc"].poll() is not None:
            return

    def cancel(self, external_session_id: str) -> None:
        state = self._session(external_session_id)
        state["cancel"].set()
        if state["proc"].poll() is None:
            self.supervisor.terminate_tree(state["proc"])
        if not state["done"].wait(10):
            raise RuntimeError("Codex process tree did not terminate within the cancellation bound")
        self._persist(state)

    def _persist(self, state: dict[str, Any]) -> None:
        if state.get("persisted") or not state.get("record_kwargs"):
            return
        self.storage.record_codex_worker_result(**state["record_kwargs"])
        state["persisted"] = True

    def collect_events(self, external_session_id: str) -> list[RuntimeDriverEvent]:
        state = self._session(external_session_id)
        if state["done"].is_set():
            self._persist(state)
        with self._lock:
            events = list(state["events"])
            state["events"].clear()
        return events

    def finalize(self, external_session_id: str) -> str:
        state = self._session(external_session_id)
        if not state["done"].wait(self.max_seconds + 10):
            self.cancel(external_session_id)
        self._persist(state)
        status = str(state["status"])
        return "failed" if status in {"timed_out", "output_limited"} else status
