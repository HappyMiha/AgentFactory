from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from contextlib import suppress
from pathlib import Path
from typing import Any

from .models import Agent, ExecutionApproval, ProviderResult, WorkItem

SENSITIVE_ENV_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "API_KEY", "AUTH")
PASSING_VERDICTS = ("COMPLETE", "PASS", "ALIGNED", "CONDITIONALLY_ALIGNED")


class ProcessSupervisor:
    """Start a provider in an isolated process group and terminate its full tree."""

    def __init__(self, *, windows: bool | None = None):
        self.windows = os.name == "nt" if windows is None else windows

    def spawn(self, command: list[str], **kwargs: Any) -> subprocess.Popen[str]:
        if self.windows:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(command, shell=False, **kwargs)

    def terminate_tree(self, proc: subprocess.Popen[str]) -> dict[str, Any]:
        pid = int(proc.pid)
        if pid <= 0:
            return {"tree_terminated": False, "cleanup_error": "invalid process id"}
        try:
            if self.windows:
                cleanup = subprocess.run(
                    ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                verified = cleanup.returncode == 0
                if not verified and proc.poll() is None:
                    proc.kill()
                return {"tree_terminated": verified, "cleanup_returncode": cleanup.returncode}
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            return {"tree_terminated": True}
        except (OSError, subprocess.SubprocessError) as exc:
            if proc.poll() is None:
                with suppress(OSError):
                    proc.kill()
            return {"tree_terminated": False, "cleanup_error": type(exc).__name__}


class Provider(ABC):
    name: str

    @abstractmethod
    def health(self) -> dict[str, Any]: ...

    @abstractmethod
    def execute(
        self,
        agent: Agent,
        item: WorkItem,
        context: dict[str, str],
        approval: ExecutionApproval | None = None,
    ) -> ProviderResult: ...


class CLIProvider(Provider):
    def __init__(
        self,
        name: str,
        executable: str,
        args: list[str],
        *,
        executable_candidates: list[str] | None = None,
        version_args: list[str] | None = None,
        prompt_transport: str = "stdin",
        prompt_file_args: list[str] | None = None,
        allow_execution: bool = False,
        max_timeout: int = 180,
        max_output_chars: int = 100_000,
        max_prompt_chars: int = 50_000,
        allowed_roles: list[str] | None = None,
        allowed_sensitive_env: list[str] | None = None,
        protected_paths: list[str] | None = None,
        safety_rules: list[str] | None = None,
        workspace: Path | None = None,
        supervisor: ProcessSupervisor | None = None,
    ):
        self.name = name
        self.executable = executable
        self.executable_candidates = tuple(executable_candidates or [])
        self.args = tuple(args)
        self.version_args = tuple(version_args or ["--version"])
        self.prompt_transport = prompt_transport
        self.prompt_file_args = tuple(prompt_file_args or ["--message-file"])
        self.allow_execution = allow_execution
        self.max_timeout = max(1, int(max_timeout))
        self.max_output_chars = max(1, int(max_output_chars))
        self.max_prompt_chars = max(1, int(max_prompt_chars))
        self.allowed_roles = frozenset(allowed_roles or [])
        self.allowed_sensitive_env = frozenset(allowed_sensitive_env or [])
        self.protected_paths = tuple(protected_paths or [])
        self.safety_rules = tuple(safety_rules or [])
        self.workspace = (workspace or Path.cwd()).resolve()
        self.supervisor = supervisor or ProcessSupervisor()

    def _executable_paths(self) -> list[str]:
        """Resolve only configured launchers, preferring stable native binaries."""

        resolved: list[str] = []
        seen: set[str] = set()
        for raw in (*self.executable_candidates, self.executable):
            expanded = os.path.expandvars(os.path.expanduser(raw))
            candidate = Path(expanded)
            path: str | None
            if candidate.is_absolute():
                path = str(candidate) if candidate.is_file() else None
            elif candidate.parent != Path("."):
                workspace_candidate = (self.workspace / candidate).resolve()
                path = str(workspace_candidate) if workspace_candidate.is_file() else None
            else:
                path = shutil.which(expanded)
            if not path:
                continue
            key = os.path.normcase(os.path.abspath(path))
            if key not in seen:
                seen.add(key)
                resolved.append(path)
        return resolved

    def _executable_path(self) -> str | None:
        paths = self._executable_paths()
        return paths[0] if paths else None

    def health(self) -> dict[str, Any]:
        paths = self._executable_paths()
        if not paths:
            return {"provider": self.name, "healthy": False, "error": "allowlisted executable not found"}
        failures: list[str] = []
        for path in paths:
            try:
                proc = subprocess.run(
                    [path, *self.version_args],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=8,
                    check=False,
                )
                output = (proc.stdout or proc.stderr).strip()
                if proc.returncode == 0:
                    return {
                        "provider": self.name,
                        "healthy": True,
                        "path": path,
                        "version": output[:1000],
                        "execution_enabled": self.allow_execution,
                        "error": None,
                    }
                failures.append(f"{Path(path).name}: exit {proc.returncode}")
            except (OSError, subprocess.TimeoutExpired) as exc:
                failures.append(f"{Path(path).name}: {exc}")
        return {
            "provider": self.name,
            "healthy": False,
            "path": paths[0],
            "execution_enabled": self.allow_execution,
            "error": "; ".join(failures)[:1000],
        }

    def _approval_error(
        self,
        agent: Agent,
        item: WorkItem,
        approval: ExecutionApproval | None,
    ) -> str | None:
        if not self.allow_execution:
            return "provider execution disabled by configuration"
        if self.allowed_roles and agent.role not in self.allowed_roles:
            return f"agent role {agent.role!r} is not allowlisted for provider {self.name}"
        if approval is None:
            return "operator provider-execution approval required"
        expected = (self.name, agent.id, item.id)
        actual = (approval.provider, approval.agent_id, approval.task_id)
        if expected != actual:
            return f"approval scope mismatch: expected provider/agent/task {expected}"
        if not str(approval.approved_by).strip():
            return "approval issuer is required"
        return None

    def _safe_environment(self) -> dict[str, str]:
        return {
            key: value
            for key, value in os.environ.items()
            if key in self.allowed_sensitive_env
            or not any(marker in key.upper() for marker in SENSITIVE_ENV_MARKERS)
        } | {"NO_COLOR": "1", "TERM": "dumb"}

    def _prompt(self, agent: Agent, item: WorkItem, context: dict[str, str]) -> str:
        protected = ", ".join(self.protected_paths) if self.protected_paths else "none configured"
        rules = [
            "Work only on the requested task and return a reviewable artifact.",
            "Do not reveal credentials, merge changes, close work items, or contact external parties.",
            *self.safety_rules,
        ]
        prompt = (
            f"Role: {agent.role}\n"
            f"Instructions: {agent.instructions}\n"
            f"Task: {item.title}\n{item.description}\n"
            f"Acceptance criteria: {json.dumps(item.acceptance_criteria, ensure_ascii=False)}\n"
            f"Context: {json.dumps(context, ensure_ascii=False, sort_keys=True)}\n"
            f"Protected paths (read-only): {protected}\n\n"
            "Execution policy:\n- "
            + "\n- ".join(rules)
        )
        if len(prompt) > self.max_prompt_chars:
            raise ValueError(f"provider prompt exceeds {self.max_prompt_chars:,} character policy limit")
        return prompt

    def execute(
        self,
        agent: Agent,
        item: WorkItem,
        context: dict[str, str],
        approval: ExecutionApproval | None = None,
    ) -> ProviderResult:
        if error := self._approval_error(agent, item, approval):
            return ProviderResult(False, provider=self.name, error=error, metadata={"blocked": True})
        path = self._executable_path()
        if not path:
            return ProviderResult(False, provider=self.name, error="allowlisted executable not found")
        try:
            prompt = self._prompt(agent, item, context)
        except ValueError as exc:
            return ProviderResult(False, provider=self.name, error=str(exc), metadata={"blocked": True})

        command = [path, *self.args]
        stdin = None
        prompt_file: Path | None = None
        if self.prompt_transport == "stdin":
            stdin = prompt
        elif self.prompt_transport == "argument":
            command.append(prompt)
        elif self.prompt_transport == "file":
            prompt_dir = self.workspace / ".agent-factory" / "provider-prompts"
            prompt_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", suffix=".txt", dir=prompt_dir, delete=False
            ) as handle:
                handle.write(prompt)
                prompt_file = Path(handle.name)
            command.extend([*self.prompt_file_args, str(prompt_file)])
        else:
            return ProviderResult(
                False,
                provider=self.name,
                error=f"unsupported prompt transport: {self.prompt_transport}",
            )

        timeout = min(max(1, item.budget.max_seconds), self.max_timeout)
        started = time.monotonic()
        proc: subprocess.Popen[str] | None = None
        try:
            proc = self.supervisor.spawn(
                command,
                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=self.workspace,
                env=self._safe_environment(),
            )
            stdout, stderr = proc.communicate(input=stdin, timeout=timeout)
            elapsed = round(time.monotonic() - started, 3)
            metadata = {
                "gate_id": approval.gate_id if approval else None,
                "executable": Path(path).name,
                "args": list(self.args),
                "timeout_seconds": timeout,
                "elapsed_seconds": elapsed,
                "returncode": proc.returncode,
                "output_truncated": len(stdout) > self.max_output_chars,
                "process_group_contained": True,
            }
            if proc.returncode:
                error = (stderr or f"exit {proc.returncode}").strip()[: self.max_output_chars]
                return ProviderResult(False, provider=self.name, error=error, metadata=metadata)
            return ProviderResult(
                True,
                stdout[: self.max_output_chars].strip(),
                self.name,
                metadata=metadata,
            )
        except subprocess.TimeoutExpired:
            cleanup = self.supervisor.terminate_tree(proc) if proc is not None else {}
            if proc is not None:
                with suppress(subprocess.TimeoutExpired, OSError):
                    proc.communicate(timeout=5)
            return ProviderResult(
                False,
                provider=self.name,
                error=f"provider timed out after {timeout}s",
                metadata={
                    "gate_id": approval.gate_id if approval else None,
                    "timed_out": True,
                    **cleanup,
                },
            )
        except OSError as exc:
            return ProviderResult(
                False,
                provider=self.name,
                error=str(exc),
                metadata={"gate_id": approval.gate_id if approval else None},
            )
        finally:
            if prompt_file:
                prompt_file.unlink(missing_ok=True)


class DeterministicProvider(Provider):
    """Offline provider that emits typed, reproducible workflow artifacts."""

    name = "deterministic"

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "healthy": True, "version": "1"}

    @staticmethod
    def _verdict(item: WorkItem) -> str:
        contract = item.inputs.get("stage_contract", item.inputs.get("contract", {}))
        allowed = contract.get("allowed_verdicts", []) if isinstance(contract, dict) else []
        stage = str(item.inputs.get("stage", "implementation"))
        preferred = {
            "policy-precheck": "ALIGNED",
            "implementation": "COMPLETE",
            "validation": "PASS",
            "policy-postcheck": "ALIGNED",
        }.get(stage, "COMPLETE")
        if not allowed or preferred in allowed:
            return preferred
        return next((value for value in allowed if value in PASSING_VERDICTS), str(allowed[0]))

    def execute(
        self,
        agent: Agent,
        item: WorkItem,
        context: dict[str, str],
        approval: ExecutionApproval | None = None,
    ) -> ProviderResult:
        verdict = self._verdict(item)
        evidence = {
            criterion: "Satisfied by the deterministic offline simulation."
            for criterion in item.acceptance_criteria
        }
        payload = {
            "verdict": verdict,
            "criteria_evidence": evidence,
            "summary": f"Reproducible proposal for {item.title}.",
        }
        return ProviderResult(
            True,
            json.dumps(payload, indent=2, ensure_ascii=False),
            self.name,
            metadata={"deterministic": True, "agent": agent.id},
        )
