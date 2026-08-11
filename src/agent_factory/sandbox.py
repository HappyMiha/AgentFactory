"""Fail-closed local isolation for future writable worker runtimes."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .providers import BoundedCapture, ProcessSupervisor, SENSITIVE_ENV_MARKERS
from .storage import SQLiteStorage


class SandboxUnavailableError(RuntimeError):
    """Raised before launch when no qualified OS enforcement backend exists."""


class SandboxPathError(PermissionError):
    """Raised when a requested path is outside the sandbox write roots."""


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _digest(value: bytes | str) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def _canonical_command(command: Sequence[str]) -> tuple[str, ...]:
    values = tuple(str(value) for value in command)
    if not values or any(not value or "\x00" in value for value in values):
        raise ValueError("Sandbox command must be a non-empty fixed argument vector")
    executable = Path(values[0]).expanduser()
    if executable.is_absolute():
        resolved = executable.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Sandbox executable does not exist: {resolved.name}")
        return (str(resolved), *values[1:])
    located = shutil.which(values[0])
    if not located:
        raise FileNotFoundError(f"Sandbox executable is not allowlisted on PATH: {values[0]}")
    return (str(Path(located).resolve()), *values[1:])


@dataclass(frozen=True)
class SandboxPolicy:
    workspace: Path
    worktree: Path
    temporary_paths: tuple[Path, ...]
    max_seconds: int = 120
    max_output_chars: int = 100_000
    network: str = "deny"

    @classmethod
    def create(
        cls,
        workspace: Path,
        worktree: Path,
        temporary_paths: Sequence[Path] = (),
        *,
        max_seconds: int = 120,
        max_output_chars: int = 100_000,
        network: str = "deny",
    ) -> SandboxPolicy:
        root = workspace.resolve()
        tree = worktree.resolve()
        temporary = tuple(path.resolve() for path in temporary_paths)
        if not root.is_dir():
            raise ValueError("Sandbox workspace must exist")
        if not tree.is_dir() or not _within(tree, root) or tree == root:
            raise ValueError("Sandbox worktree must be a distinct directory in the workspace")
        control_root = (root / ".agent-factory").resolve()
        managed_worktrees = (control_root / "worktrees").resolve()
        if _within(tree, control_root) and not _within(tree, managed_worktrees):
            raise ValueError("Sandbox worktree cannot contain Control Plane state")
        temp_root = (control_root / "sandbox-temp").resolve()
        for path in temporary:
            if not _within(path, temp_root):
                raise ValueError(
                    "Declared temporary paths must be inside .agent-factory/sandbox-temp"
                )
            if path == temp_root:
                raise ValueError("The shared sandbox temp root cannot be writable")
        if not 1 <= max_seconds <= 3600:
            raise ValueError("Sandbox timeout must be between 1 and 3600 seconds")
        if not 1 <= max_output_chars <= 10_000_000:
            raise ValueError("Sandbox output limit is outside the supported range")
        if network != "deny":
            raise ValueError("AF-017 supports deny-only network policy")
        return cls(
            root,
            tree,
            tuple(sorted(set(temporary), key=str)),
            max_seconds,
            max_output_chars,
            network,
        )

    @property
    def write_roots(self) -> tuple[Path, ...]:
        return (self.worktree, *self.temporary_paths)

    def canonical(self) -> dict[str, Any]:
        return {
            "workspace": str(self.workspace),
            "worktree": str(self.worktree),
            "temporary_paths": [str(path) for path in self.temporary_paths],
            "max_seconds": self.max_seconds,
            "max_output_chars": self.max_output_chars,
            "network": self.network,
        }

    @property
    def digest(self) -> str:
        return _digest(
            json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))
        )

    def permits_write(self, target: Path) -> bool:
        resolved = target.resolve(strict=False)
        return any(_within(resolved, root) for root in self.write_roots)


class SandboxBackend(ABC):
    """An OS boundary that makes non-write roots and network inaccessible."""

    name: str
    enforced: bool = True

    @abstractmethod
    def availability(self) -> tuple[bool, str]: ...

    @abstractmethod
    def wrap(
        self, policy: SandboxPolicy, command: tuple[str, ...], control_dir: Path
    ) -> list[str]: ...


class BubblewrapBackend(SandboxBackend):
    name = "bubblewrap"

    def __init__(self, executable: str | None = None):
        self.executable = executable or shutil.which("bwrap") or ""

    def availability(self) -> tuple[bool, str]:
        return (
            (True, "bubblewrap executable found")
            if self.executable and Path(self.executable).is_file()
            else (False, "bubblewrap executable not found")
        )

    def wrap(
        self, policy: SandboxPolicy, command: tuple[str, ...], control_dir: Path
    ) -> list[str]:
        del control_dir
        available, reason = self.availability()
        if not available:
            raise SandboxUnavailableError(reason)
        wrapped = [
            self.executable,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--ro-bind",
            "/",
            "/",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
        ]
        for root in policy.write_roots:
            wrapped.extend(("--bind", str(root), str(root)))
        wrapped.extend(("--chdir", str(policy.worktree), "--", *command))
        return wrapped


def _sandbox_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


class MacOSSandboxBackend(SandboxBackend):
    name = "sandbox-exec"

    def __init__(self, executable: str | None = None):
        self.executable = executable or shutil.which("sandbox-exec") or ""

    def availability(self) -> tuple[bool, str]:
        return (
            (True, "sandbox-exec executable found")
            if self.executable and Path(self.executable).is_file()
            else (False, "sandbox-exec executable not found")
        )

    def wrap(
        self, policy: SandboxPolicy, command: tuple[str, ...], control_dir: Path
    ) -> list[str]:
        available, reason = self.availability()
        if not available:
            raise SandboxUnavailableError(reason)
        writes = "\n".join(
            f'(allow file-write* (subpath "{_sandbox_quote(str(path))}"))'
            for path in policy.write_roots
        )
        profile = control_dir / "sandbox.sb"
        profile.write_text(
            "\n".join(
                (
                    "(version 1)",
                    "(deny default)",
                    "(allow process*)",
                    "(allow sysctl-read)",
                    "(allow file-read*)",
                    "(deny network*)",
                    writes,
                )
            ),
            encoding="utf-8",
        )
        return [self.executable, "-f", str(profile), "--", *command]


class UnavailableSandboxBackend(SandboxBackend):
    name = "unavailable"
    enforced = False

    def __init__(self, reason: str):
        self.reason = reason

    def availability(self) -> tuple[bool, str]:
        return False, self.reason

    def wrap(
        self, policy: SandboxPolicy, command: tuple[str, ...], control_dir: Path
    ) -> list[str]:
        del policy, command, control_dir
        raise SandboxUnavailableError(self.reason)


def platform_sandbox_backend() -> SandboxBackend:
    if sys.platform.startswith("linux"):
        return BubblewrapBackend()
    if sys.platform == "darwin":
        return MacOSSandboxBackend()
    return UnavailableSandboxBackend(
        "No qualified Windows sandbox backend is configured; writable execution is disabled"
    )


@dataclass(frozen=True)
class SandboxResult:
    execution_id: str
    status: str
    backend: str
    returncode: int | None
    stdout: str
    stderr: str
    elapsed_seconds: float
    timed_out: bool
    output_limit_exceeded: bool
    process_tree_contained: bool
    policy_digest: str
    command_digest: str
    evidence_directory: str
    evidence_digest: str
    candidate_digest: str
    changed_files: tuple[str, ...]


def _tree_snapshot(root: Path) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative == ".git" or relative.startswith(".git/"):
            continue
        if path.is_symlink():
            snapshot[relative] = {
                "kind": "symlink",
                "target": os.readlink(path),
            }
        elif path.is_file():
            stat = path.stat()
            snapshot[relative] = {
                "kind": "file",
                "sha256": _digest(path.read_bytes()),
                "size": stat.st_size,
                "mode": stat.st_mode & 0o777,
            }
    return snapshot


def _candidate_manifest(
    before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    names = sorted(set(before) | set(after))
    changes = []
    for name in names:
        if before.get(name) == after.get(name):
            continue
        status = "added" if name not in before else "deleted" if name not in after else "modified"
        changes.append(
            {
                "path": name,
                "status": status,
                "before": before.get(name),
                "after": after.get(name),
            }
        )
    return {"schema_version": 1, "changes": changes}


class SandboxManager:
    def __init__(
        self,
        storage: SQLiteStorage,
        workspace: Path,
        *,
        backend: SandboxBackend | None = None,
        supervisor: ProcessSupervisor | None = None,
    ):
        self.storage = storage
        self.workspace = workspace.resolve()
        self.backend = backend or platform_sandbox_backend()
        self.supervisor = supervisor or ProcessSupervisor()

    def authorize_write(
        self,
        assignment_id: int,
        fencing_token: int,
        policy: SandboxPolicy,
        target: Path,
    ) -> Path:
        self.storage.assert_fenced_lease(assignment_id, fencing_token)
        resolved = target.resolve(strict=False)
        if policy.permits_write(resolved):
            return resolved
        self.storage.event(
            "sandbox.write.blocked",
            "assignment",
            assignment_id,
            {
                "assignment_id": assignment_id,
                "fencing_token": fencing_token,
                "policy_digest": policy.digest,
                "target_sha256": _digest(str(resolved)),
                "reason": "outside declared write roots",
            },
        )
        raise SandboxPathError("Write target is outside the task worktree and temp paths")

    @staticmethod
    def _safe_environment(policy: SandboxPolicy) -> dict[str, str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not any(marker in key.upper() for marker in SENSITIVE_ENV_MARKERS)
        }
        home = policy.temporary_paths[0] if policy.temporary_paths else policy.worktree
        environment.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "TMP": str(home),
                "TEMP": str(home),
                "TMPDIR": str(home),
                "NO_COLOR": "1",
                "TERM": "dumb",
                "HTTP_PROXY": "http://127.0.0.1:9",
                "HTTPS_PROXY": "http://127.0.0.1:9",
                "ALL_PROXY": "http://127.0.0.1:9",
                "NO_PROXY": "",
            }
        )
        return environment

    def _audit_block(
        self,
        assignment_id: int,
        fencing_token: int,
        policy: SandboxPolicy,
        reason: str,
    ) -> None:
        self.storage.event(
            "sandbox.execution.blocked",
            "assignment",
            assignment_id,
            {
                "assignment_id": assignment_id,
                "fencing_token": fencing_token,
                "backend": self.backend.name,
                "policy_digest": policy.digest,
                "reason": reason,
            },
        )

    def execute(
        self,
        assignment_id: int,
        fencing_token: int,
        policy: SandboxPolicy,
        command: Sequence[str],
    ) -> SandboxResult:
        if policy.workspace != self.workspace:
            raise ValueError("Sandbox policy belongs to a different workspace")
        self.storage.assert_fenced_lease(assignment_id, fencing_token)
        available, reason = self.backend.availability()
        if not available or not self.backend.enforced:
            self._audit_block(
                assignment_id, fencing_token, policy, reason
            )
            raise SandboxUnavailableError(reason)
        fixed_command = _canonical_command(command)
        command_digest = _digest(
            json.dumps(fixed_command, separators=(",", ":"), ensure_ascii=False)
        )
        execution_id = f"sandbox-{uuid.uuid4().hex}"
        control_dir = self.workspace / ".agent-factory" / "sandbox-control" / execution_id
        evidence_dir = self.workspace / ".agent-factory" / "sandbox-evidence" / execution_id
        created_temp: list[Path] = []
        for path in policy.temporary_paths:
            if path.exists() and any(path.iterdir()):
                raise ValueError("Declared sandbox temporary paths must start empty")
            if not path.exists():
                path.mkdir(parents=True)
                created_temp.append(path)
        control_dir.mkdir(parents=True, exist_ok=False)
        evidence_dir.mkdir(parents=True, exist_ok=False)
        before = _tree_snapshot(policy.worktree)
        try:
            wrapped = self.backend.wrap(policy, fixed_command, control_dir)
        except Exception:
            for path in reversed(created_temp):
                shutil.rmtree(path, ignore_errors=True)
            shutil.rmtree(control_dir, ignore_errors=True)
            shutil.rmtree(evidence_dir, ignore_errors=True)
            raise
        self.storage.event(
            "sandbox.execution.started",
            "assignment",
            assignment_id,
            {
                "assignment_id": assignment_id,
                "fencing_token": fencing_token,
                "execution_id": execution_id,
                "backend": self.backend.name,
                "policy_digest": policy.digest,
                "command_digest": command_digest,
            },
        )
        started = time.monotonic()
        proc: subprocess.Popen[str] | None = None
        stdout = ""
        stderr = ""
        cleanup: dict[str, Any] = {}
        timed_out = False
        output_limit_exceeded = False
        capture_complete = False
        try:
            proc = self.supervisor.spawn(
                wrapped,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=policy.worktree,
                env=self._safe_environment(policy),
            )
            capture = BoundedCapture(proc, policy.max_output_chars)
            capture.start()
            deadline = started + policy.max_seconds
            while True:
                if capture.overflow.is_set():
                    output_limit_exceeded = True
                    cleanup = self.supervisor.terminate_tree(proc)
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    cleanup = self.supervisor.terminate_tree(proc)
                    break
                try:
                    proc.wait(timeout=min(0.05, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            with suppress(subprocess.TimeoutExpired, OSError):
                proc.wait(timeout=5)
            capture_complete = capture.join(5)
            captured = capture.snapshot()
            stdout = str(captured["stdout"])
            stderr = str(captured["stderr"])
            if capture.overflow.is_set():
                output_limit_exceeded = True
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    with suppress(OSError, ValueError):
                        stream.close()
        except OSError as exc:
            stderr = f"sandbox launch failed: {type(exc).__name__}"
        finally:
            elapsed = round(time.monotonic() - started, 3)
            after = _tree_snapshot(policy.worktree)
            candidate = _candidate_manifest(before, after)
            candidate_json = json.dumps(
                candidate, indent=2, sort_keys=True, ensure_ascii=False
            )
            candidate_digest = _digest(candidate_json)
            (evidence_dir / "candidate.json").write_text(
                candidate_json, encoding="utf-8"
            )
            (evidence_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
            (evidence_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
            changed_files = tuple(change["path"] for change in candidate["changes"])
            for name in changed_files:
                source = policy.worktree / name
                if source.is_file() and not source.is_symlink():
                    destination = evidence_dir / "files" / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
            for path in reversed(created_temp):
                shutil.rmtree(path, ignore_errors=True)
            shutil.rmtree(control_dir, ignore_errors=True)
        returncode = proc.returncode if proc else None
        if timed_out:
            status = "timed_out"
        elif output_limit_exceeded:
            status = "output_limited"
        elif returncode == 0:
            status = "succeeded"
        else:
            status = "failed"
        evidence = {
            "schema_version": 1,
            "execution_id": execution_id,
            "assignment_id": assignment_id,
            "fencing_token": fencing_token,
            "status": status,
            "backend": self.backend.name,
            "returncode": returncode,
            "elapsed_seconds": elapsed,
            "timed_out": timed_out,
            "output_limit_exceeded": output_limit_exceeded,
            "capture_complete": capture_complete,
            "process_tree_contained": True,
            "policy": policy.canonical(),
            "policy_digest": policy.digest,
            "command_digest": command_digest,
            "candidate_digest": candidate_digest,
            "changed_files": list(changed_files),
            "cleanup": cleanup,
        }
        evidence_json = json.dumps(evidence, indent=2, sort_keys=True)
        evidence_digest = _digest(evidence_json)
        (evidence_dir / "evidence.json").write_text(
            evidence_json, encoding="utf-8"
        )
        self.storage.event(
            "sandbox.execution.completed",
            "assignment",
            assignment_id,
            {
                **evidence,
                "evidence_digest": evidence_digest,
                "evidence_directory": str(evidence_dir.relative_to(self.workspace)),
            },
        )
        return SandboxResult(
            execution_id=execution_id,
            status=status,
            backend=self.backend.name,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            elapsed_seconds=elapsed,
            timed_out=timed_out,
            output_limit_exceeded=output_limit_exceeded,
            process_tree_contained=True,
            policy_digest=policy.digest,
            command_digest=command_digest,
            evidence_directory=str(evidence_dir),
            evidence_digest=evidence_digest,
            candidate_digest=candidate_digest,
            changed_files=changed_files,
        )
