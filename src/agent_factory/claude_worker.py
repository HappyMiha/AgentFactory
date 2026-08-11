"""Separately qualified writable Claude Code implementation worker."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters import HEALTH_DIMENSIONS
from .codex_worker import CodexCLIProcessDriver
from .providers import BoundedCapture
from .sandbox import _candidate_manifest, _tree_snapshot
from .worker_runtime import RuntimeDriverEvent, RuntimeLaunch


CLAUDE_TOOLS = "Read,Edit,Write,Glob,Grep"
CLAUDE_PERMISSION_PROFILE = {
    "mode": "dontAsk",
    "tools": CLAUDE_TOOLS.split(","),
    "allow": ["Read(./**)", "Edit(./**)"],
    "setting_sources": [],
    "mcp_servers": [],
    "additional_directories": [],
    "forbidden_authorities": [
        "bash", "network", "merge", "push", "close_issue", "final_approval"
    ],
}
CLAUDE_EXEC_ARGS = (
    "--print", "--input-format", "text", "--output-format", "stream-json",
    "--verbose", "--permission-mode", "dontAsk", "--tools", CLAUDE_TOOLS,
    "--allowedTools", "Read(./**)", "Edit(./**)",
    "--setting-sources", "", "--mcp-config", '{"mcpServers":{}}',
    "--strict-mcp-config", "--disable-slash-commands",
)
VERSION_PATTERN = re.compile(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)")


@dataclass(frozen=True)
class ClaudeWorkerHealth:
    healthy: bool
    executable: str | None
    version: str | None
    interface_qualified: bool
    workspace_access: bool
    profile_digest: str
    reason: str

    def evidence(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy, "executable": self.executable,
            "version": self.version, "interface_qualified": self.interface_qualified,
            "workspace_access": self.workspace_access,
            "profile_digest": self.profile_digest, "reason": self.reason,
        }


class ClaudeCodeProcessDriver(CodexCLIProcessDriver):
    """Claude stream-JSON driver with a fixed file-only writable profile."""

    def health(self, worktree: Path | None = None) -> ClaudeWorkerHealth:
        profile_json = json.dumps(CLAUDE_PERMISSION_PROFILE, sort_keys=True, separators=(",", ":"))
        profile_digest = hashlib.sha256(profile_json.encode()).hexdigest()
        executable = next(
            (value for raw in self.executable_candidates if (value := self._resolve(raw))), None
        )
        if executable is None:
            return ClaudeWorkerHealth(False, None, None, False, False, profile_digest, "executable unavailable")
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
                [*prefix, "--help"], shell=False, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=8, check=False,
                env=self._environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ClaudeWorkerHealth(False, executable, None, False, False, profile_digest, type(exc).__name__)
        help_text = help_probe.stdout or help_probe.stderr
        required = (
            "--print", "--output-format", "--permission-mode", "--tools",
            "--allowedTools", "--setting-sources", "--strict-mcp-config",
        )
        interface = help_probe.returncode == 0 and all(flag in help_text for flag in required)
        accessible = worktree is None or (
            worktree.resolve().is_dir() and self._within(worktree.resolve(), self.workspace)
        )
        healthy = bool(version and interface and accessible)
        return ClaudeWorkerHealth(
            healthy, executable, version, interface, accessible, profile_digest,
            "qualified" if healthy else "version, interface, or workspace qualification failed",
        )

    @staticmethod
    def _prompt(launch: RuntimeLaunch) -> str:
        return json.dumps({
            "schema_version": 1, "role": "Implementation Worker",
            "context_package": launch.context,
            "constraints": {
                "write_scope": "current task worktree only",
                "tools": CLAUDE_PERMISSION_PROFILE["tools"],
                "forbidden": CLAUDE_PERMISSION_PROFILE["forbidden_authorities"],
                "handoff": "Report changed files, tool calls, remaining risks, and summary.",
            },
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _parsed_output(stdout: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        messages: list[str] = []
        usage: dict[str, Any] = {}
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "assistant":
                message = event.get("message", {})
                for block in message.get("content", []) if isinstance(message, dict) else []:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        calls.append({
                            "name": str(block.get("name", "")),
                            "input": block.get("input", {}), "status": "requested",
                        })
                    elif block.get("type") == "text" and block.get("text"):
                        messages.append(str(block["text"]))
            if event.get("type") == "result":
                if event.get("result"):
                    messages.append(str(event["result"]))
                if isinstance(event.get("usage"), dict):
                    usage = dict(event["usage"])
        return calls, {
            "summary": messages[-1] if messages else "",
            "message_count": len(messages), "usage": usage,
        }

    def _launch_scope(self, launch: RuntimeLaunch):
        if not launch.mutable or launch.binding is None:
            raise PermissionError("Claude implementation worker requires a mutable runtime binding")
        if launch.agent.role != "Implementation Worker" or launch.agent.provider != "claude":
            raise PermissionError("Claude writable runtime is restricted to the Claude implementation role")
        binding = launch.binding
        worktree = self.storage.managed_worktree(binding.worktree_id)
        if (
            int(worktree["assignment_id"]) != launch.assignment_id
            or int(worktree["attempt_id"] or 0) != binding.attempt_id
            or int(worktree["fencing_token"] or 0) != launch.fencing_token
            or str(worktree["status"]) not in {"ready", "dirty"}
        ):
            raise PermissionError("Claude worktree is not owned by the live attempt")
        path = Path(str(worktree["path"])).resolve()
        if not path.is_dir() or not self._within(path, self.workspace):
            raise PermissionError("Claude worktree is outside the Control Plane workspace")
        return path, worktree

    def start(self, launch: RuntimeLaunch, *, control_session_id: int | None = None) -> str:
        if control_session_id is None:
            raise ValueError("Claude driver requires a durable Control Plane session")
        worktree, worktree_row = self._launch_scope(launch)
        health = self.health(worktree)
        if not health.healthy or not health.executable or not health.version:
            raise RuntimeError(f"Claude worker is not qualified: {health.reason}")
        model = launch.agent.model.split(":", 1)[-1] if launch.agent.model else ""
        command = [
            health.executable, *self.executable_args, *CLAUDE_EXEC_ARGS,
            *(["--model", model] if model else []),
        ]
        prompt = self._prompt(launch)
        before = _tree_snapshot(worktree)
        external_id = f"claude-worker:{uuid.uuid4().hex}"
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
        threading.Thread(
            target=self._write_prompt, args=(proc, prompt), daemon=True,
            name=f"claude-prompt-{control_session_id}",
        ).start()
        threading.Thread(
            target=self._monitor, args=(external_id,), daemon=True,
            name=f"claude-monitor-{control_session_id}",
        ).start()
        return external_id

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
        candidate = _candidate_manifest(state["before"], _tree_snapshot(state["worktree"]))
        candidate_json = json.dumps(candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        diff_digest = hashlib.sha256(candidate_json.encode()).hexdigest()
        changed_files = [change["path"] for change in candidate["changes"]]
        calls, handoff = self._parsed_output(stdout)
        status = (
            "cancelled" if state["cancel"].is_set() else "timed_out" if timed_out
            else "output_limited" if output_limited or capture.overflow.is_set()
            else "succeeded" if proc.returncode == 0 else "failed"
        )
        evidence_dir = self.workspace / ".agent-factory" / "claude-evidence" / external_id.split(":", 1)[1]
        evidence_dir.mkdir(parents=True, exist_ok=False)
        evidence = {
            "schema_version": 1, "status": status, "exit_code": proc.returncode,
            "changed_files": changed_files, "diff_digest": diff_digest,
            "tool_calls": calls, "handoff": handoff,
            "qualification": state["health"].evidence(),
            "permission_profile": CLAUDE_PERMISSION_PROFILE,
            "invocation": state["invocation"], "claude_version": state["health"].version,
        }
        evidence_json = json.dumps(evidence, sort_keys=True, indent=2, ensure_ascii=False)
        evidence_digest = hashlib.sha256(evidence_json.encode()).hexdigest()
        (evidence_dir / "result.json").write_text(evidence_json, encoding="utf-8")
        (evidence_dir / "events.jsonl").write_text(stdout, encoding="utf-8")
        (evidence_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
        state["record"] = {
            "changed_files": changed_files, "diff_digest": diff_digest,
            "tool_calls": calls, "handoff": handoff, "status": status,
            "exit_code": proc.returncode, "evidence_directory": str(evidence_dir.relative_to(self.workspace)),
            "evidence_digest": evidence_digest,
        }
        state["events"].extend([
            *(RuntimeDriverEvent("tool_call", call, mutable=True) for call in calls),
            RuntimeDriverEvent("artifact", {
                "kind": "candidate_change", "changed_files": changed_files,
                "diff_digest": diff_digest, "handoff": handoff,
            }, mutable=bool(changed_files)),
            RuntimeDriverEvent("status", {"state": status}),
        ])
        state["status"] = status
        state["done"].set()

    def _persist(self, state: dict[str, Any]) -> None:
        if state.get("persisted") or not state.get("record"):
            return
        launch, binding, record = state["launch"], state["launch"].binding, state["record"]
        assert binding is not None
        session = self.storage.runtime_session(state["control_session_id"])
        stage = self.storage.db.execute(
            "SELECT id FROM workflow_stages WHERE run_id=? AND stage_key=?",
            (binding.run_id, binding.stage_id),
        ).fetchone()
        consumption = self.storage.db.execute(
            """SELECT * FROM stage_approval_consumptions
                WHERE attempt_id=? AND assignment_id=? AND run_id=?""",
            (binding.attempt_id, launch.assignment_id, binding.run_id),
        ).fetchone()
        context = self.storage.execution_context_package(launch.context_digest)
        worktree = self.storage.managed_worktree(binding.worktree_id)
        if (
            session["runtime"] != "claude-cli" or not stage or not consumption
            or int(consumption["stage_id"]) != int(stage["id"])
            or int(worktree["assignment_id"]) != launch.assignment_id
            or int(context["task_id"]) != int(launch.item.id)
        ):
            raise PermissionError("Claude result scope or approval consumption does not match")
        existing = self.storage.db.execute(
            "SELECT id FROM claude_worker_results WHERE worker_session_id=?",
            (state["control_session_id"],),
        ).fetchone()
        if existing:
            state["persisted"] = True
            return
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO claude_worker_results(
                       identity,worker_session_id,approval_consumption_id,task_id,run_id,
                       stage_id,attempt_id,assignment_id,worktree_id,context_package_id,
                       claude_version,producer_model,qualification_json,permission_profile_json,
                       invocation_json,tool_calls_json,changed_files_json,diff_digest,status,
                       exit_code,handoff_json,evidence_directory,evidence_digest
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("claude-worker-result"), state["control_session_id"],
                    consumption["id"], launch.item.id, binding.run_id, stage["id"],
                    binding.attempt_id, launch.assignment_id, binding.worktree_id, context["id"],
                    state["health"].version, launch.agent.model_identity,
                    json.dumps(state["health"].evidence(), sort_keys=True),
                    json.dumps(CLAUDE_PERMISSION_PROFILE, sort_keys=True),
                    json.dumps(state["invocation"]), json.dumps(record["tool_calls"], sort_keys=True),
                    json.dumps(sorted(record["changed_files"])), record["diff_digest"],
                    record["status"], record["exit_code"], json.dumps(record["handoff"], sort_keys=True),
                    record["evidence_directory"], record["evidence_digest"],
                ),
            )
            result_id = int(cursor.lastrowid)
            self.storage._event("claude.worker.recorded", "claude_worker_result", result_id, {
                "task_id": launch.item.id, "run_id": binding.run_id,
                "assignment_id": launch.assignment_id, "worktree_id": binding.worktree_id,
                "diff_digest": record["diff_digest"], "status": record["status"],
            })
        state["persisted"] = True

    def qualify_result(self, result_id: int, *, ttl_seconds: int = 86_400) -> int:
        row = self.storage.db.execute(
            """SELECT r.*,w.path,s.request_json FROM claude_worker_results r
                 JOIN worktrees w ON w.id=r.worktree_id
                 JOIN worker_sessions s ON s.id=r.worker_session_id WHERE r.id=?""",
            (result_id,),
        ).fetchone()
        if not row or row["status"] != "succeeded":
            raise ValueError("Claude qualification requires a successful worker result")
        request = json.loads(row["request_json"])
        if request.get("role") != "Implementation Worker":
            raise PermissionError("Plan-only Claude roles cannot qualify as writable workers")
        health = self.health(Path(row["path"]))
        stored = json.loads(row["qualification_json"])
        passed = health.healthy and stored.get("profile_digest") == health.profile_digest
        dimensions = {
            name: {
                "status": "pass" if passed else "fail",
                "evidence": "Claude AF-050 writable profile and result contract",
            }
            for name in HEALTH_DIMENSIONS
        }
        return self.storage.record_worker_qualification(
            worker_id=str(request["worker_id"]), provider_id="claude",
            role="Implementation Worker",
            capabilities=[
                "implementation_worker", "read_project", "structured_artifacts",
                "worktree_write",
            ],
            dimensions=dimensions,
            evidence={
                "schema_version": 1, "result_id": result_id,
                "health": health.evidence(), "result_evidence_digest": row["evidence_digest"],
                "task_id": row["task_id"], "run_id": row["run_id"],
            },
            status="qualified" if passed else "failed", ttl_seconds=ttl_seconds,
        )
