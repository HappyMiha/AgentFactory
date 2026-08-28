"""Control-Plane-owned Git worktree provisioning and reconciliation."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import config_path_for_workspace, load_yaml
from .durable_workflow import (
    MissionOperation,
    OperationClass,
    OperationObservation,
)
from .providers import SENSITIVE_ENV_MARKERS
from .storage import SQLiteStorage


SHA_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class WorktreeError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorktreeView:
    id: int
    identity: str
    assignment_id: int
    task_id: int
    lease_id: int
    fencing_token: int
    owner: str
    repository: str
    base_sha: str
    branch: str
    path: str
    status: str
    retention_until: str | None
    reconciled_at: str | None


@dataclass(frozen=True)
class WorktreeReconciliation:
    repository: str
    ready_ids: tuple[int, ...]
    dirty_ids: tuple[int, ...]
    missing_ids: tuple[int, ...]
    retained_ids: tuple[int, ...]
    orphaned_paths: tuple[str, ...]
    conflicts: tuple[str, ...]


@dataclass(frozen=True)
class _GitResult:
    returncode: int
    stdout: str
    stderr: str


class GitOperationReconciler:
    """Observe worktree and integration effects without changing Git state."""

    SUPPORTED = frozenset(
        {
            OperationClass.WORKTREE,
            OperationClass.GIT_INTEGRATION,
            OperationClass.CHECKPOINT,
        }
    )

    def __init__(self, *, git_executable: str | None = None):
        executable = git_executable or shutil.which("git")
        self.git_executable = str(Path(executable).resolve()) if executable else None

    @staticmethod
    def _request_path(request: dict[str, Any], *names: str) -> Path | None:
        for name in names:
            value = request.get(name)
            if isinstance(value, str) and value.strip():
                return Path(value).expanduser().resolve()
        return None

    def _git(
        self,
        repository: Path,
        *arguments: str,
        timeout: int = 15,
    ) -> _GitResult:
        if self.git_executable is None:
            return _GitResult(127, "", "Git executable is unavailable")
        try:
            result = subprocess.run(
                [self.git_executable, "-C", str(repository), *arguments],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=timeout,
                env=WorktreeManager._environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return _GitResult(126, "", type(exc).__name__)
        return _GitResult(
            result.returncode,
            result.stdout.strip(),
            result.stderr.strip(),
        )

    @staticmethod
    def _expected_sha(request: dict[str, Any]) -> str | None:
        for name in ("commit_sha", "git_commit_sha", "head_sha", "base_sha"):
            value = request.get(name)
            if isinstance(value, str) and SHA_PATTERN.fullmatch(value.casefold()):
                return value.casefold()
        return None

    @staticmethod
    def _expected_branch(request: dict[str, Any]) -> str | None:
        for name in ("branch", "git_branch", "epoch_branch"):
            value = request.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _observe_worktree(self, operation: MissionOperation) -> OperationObservation:
        request = operation.request
        path = self._request_path(request, "worktree_path", "path")
        if path is None:
            return OperationObservation.indeterminate(
                evidence={"field": "worktree_path"},
                reason="Journaled worktree path is missing",
            )
        if not path.is_dir():
            return OperationObservation.absent(
                evidence={"worktree_path": str(path)},
                reason="Journaled worktree directory does not exist",
            )
        head = self._git(path, "rev-parse", "HEAD")
        branch = self._git(path, "symbolic-ref", "--quiet", "--short", "HEAD")
        root = self._git(path, "rev-parse", "--show-toplevel")
        dirty = self._git(path, "status", "--porcelain=v1", "--untracked-files=all")
        if any(result.returncode for result in (head, branch, root, dirty)):
            return OperationObservation.indeterminate(
                evidence={
                    "worktree_path": str(path),
                    "git_returncodes": [
                        head.returncode,
                        branch.returncode,
                        root.returncode,
                        dirty.returncode,
                    ],
                },
                reason="Worktree Git authority could not be read safely",
            )
        actual = {
            "worktree_path": str(path),
            "repository_path": str(Path(root.stdout).resolve()),
            "head_sha": head.stdout.casefold(),
            "branch": branch.stdout,
            "dirty": bool(dirty.stdout),
        }
        expected_sha = self._expected_sha(request)
        expected_branch = self._expected_branch(request)
        if (
            (expected_sha is not None and actual["head_sha"] != expected_sha)
            or (expected_branch is not None and actual["branch"] != expected_branch)
        ):
            return OperationObservation.conflict(
                actual,
                evidence={"observer": "git-worktree"},
                reason="Worktree exists but its branch or HEAD differs from intent",
            )
        return OperationObservation.present(
            actual,
            evidence={"observer": "git-worktree"},
            reason="Worktree path, branch, and HEAD match journaled intent",
        )

    def _observe_integration(
        self, operation: MissionOperation
    ) -> OperationObservation:
        return self._observe_integration_request(operation.request)

    def _observe_integration_request(
        self, request: dict[str, Any]
    ) -> OperationObservation:
        repository = self._request_path(
            request,
            "repository_path",
            "repository",
            "git_worktree_path",
        )
        commit_sha = self._expected_sha(request)
        branch = self._expected_branch(request)
        if repository is None or commit_sha is None or branch is None:
            return OperationObservation.indeterminate(
                evidence={
                    "repository_supplied": repository is not None,
                    "commit_supplied": commit_sha is not None,
                    "branch_supplied": branch is not None,
                },
                reason="Git reconciliation requires repository, commit, and branch",
            )
        if not repository.is_dir():
            return OperationObservation.indeterminate(
                evidence={"repository_path": str(repository)},
                reason="Journaled Git repository is unavailable",
            )
        valid_branch = self._git(repository, "check-ref-format", "--branch", branch)
        if valid_branch.returncode:
            return OperationObservation.indeterminate(
                evidence={"branch": branch},
                reason="Journaled Git branch is not a valid local branch name",
            )
        commit = self._git(
            repository,
            "rev-parse",
            "--verify",
            f"{commit_sha}^{{commit}}",
        )
        if commit.returncode:
            return OperationObservation.absent(
                evidence={
                    "repository_path": str(repository),
                    "commit_sha": commit_sha,
                },
                reason="Journaled commit does not exist in the repository",
            )
        branch_ref = f"refs/heads/{branch}"
        branch_head = self._git(
            repository,
            "rev-parse",
            "--verify",
            f"{branch_ref}^{{commit}}",
        )
        if branch_head.returncode:
            return OperationObservation.absent(
                evidence={
                    "repository_path": str(repository),
                    "commit_sha": commit_sha,
                    "branch": branch,
                },
                reason="Journaled branch does not exist",
            )
        ancestor = self._git(
            repository,
            "merge-base",
            "--is-ancestor",
            commit_sha,
            branch_ref,
        )
        actual = {
            "repository_path": str(repository),
            "commit_sha": commit.stdout.casefold(),
            "branch": branch,
            "branch_head_sha": branch_head.stdout.casefold(),
        }
        if ancestor.returncode == 0:
            return OperationObservation.present(
                actual,
                evidence={"observer": "git-ancestry"},
                reason="Journaled commit is reachable from the authoritative branch",
            )
        if ancestor.returncode == 1:
            return OperationObservation.conflict(
                actual,
                evidence={"observer": "git-ancestry"},
                reason="Commit exists but is not integrated into the branch",
            )
        return OperationObservation.indeterminate(
            evidence={
                "observer": "git-ancestry",
                "returncode": ancestor.returncode,
            },
            reason="Git ancestry could not be determined safely",
        )

    def observe_authority(
        self,
        *,
        repository: Path,
        commit_sha: str,
        branch: str,
    ) -> OperationObservation:
        return self._observe_integration_request(
            {
                "repository_path": str(repository),
                "commit_sha": commit_sha,
                "branch": branch,
            }
        )

    def observe(self, operation: MissionOperation) -> OperationObservation:
        if operation.operation_class == OperationClass.WORKTREE:
            return self._observe_worktree(operation)
        if operation.operation_class in self.SUPPORTED:
            return self._observe_integration(operation)
        return OperationObservation.indeterminate(
            evidence={"operation_class": operation.operation_class.value},
            reason="No Git observer exists for this operation class",
        )


class WorktreeManager:
    def __init__(
        self,
        storage: SQLiteStorage,
        workspace: Path,
        *,
        worktree_root: Path | None = None,
        retention_seconds: int | None = None,
        git_executable: str | None = None,
    ):
        self.storage = storage
        self.workspace = workspace.resolve()
        policy: dict[str, Any] = load_yaml(
            config_path_for_workspace("policy", self.workspace)
        )
        configured = policy.get("worktrees", {})
        configured_root = Path(str(configured.get("root", ".agent-factory/worktrees")))
        root = worktree_root or (
            configured_root
            if configured_root.is_absolute()
            else self.workspace / configured_root
        )
        self.worktree_root = root.resolve()
        if not self._within(self.worktree_root, self.workspace):
            raise ValueError("Managed worktree root must stay inside the workspace")
        self.retention_seconds = int(
            retention_seconds
            if retention_seconds is not None
            else configured.get("retention_seconds", 86400)
        )
        if not 0 <= self.retention_seconds <= 31_536_000:
            raise ValueError("Worktree retention must be between 0 and 31536000 seconds")
        executable = git_executable or shutil.which("git")
        if not executable or not Path(executable).is_file():
            raise WorktreeError("Git executable is unavailable")
        self.git_executable = str(Path(executable).resolve())

    @staticmethod
    def _within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True

    @staticmethod
    def _environment() -> dict[str, str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
            and not any(marker in key.upper() for marker in SENSITIVE_ENV_MARKERS)
        }
        environment.update(
            {
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_NOSYSTEM": "1",
                "LC_ALL": "C",
            }
        )
        return environment

    def _git(
        self,
        repository: Path,
        *arguments: str,
        check: bool = True,
        timeout: int = 30,
    ) -> _GitResult:
        try:
            completed = subprocess.run(
                [self.git_executable, "-C", str(repository), *arguments],
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                env=self._environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WorktreeError(
                f"Git command failed before completion: {type(exc).__name__}"
            ) from exc
        result = _GitResult(
            int(completed.returncode),
            completed.stdout.strip(),
            completed.stderr.strip(),
        )
        if check and result.returncode:
            diagnostic = result.stderr.splitlines()[0] if result.stderr else "git failed"
            raise WorktreeError(f"Git command failed: {diagnostic[:500]}")
        return result

    def _repository(self, repository: Path) -> Path:
        resolved = repository.resolve()
        if not resolved.is_dir() or not self._within(resolved, self.workspace):
            raise ValueError("Repository must be a directory inside the workspace")
        top = Path(
            self._git(resolved, "rev-parse", "--show-toplevel").stdout
        ).resolve()
        if top != resolved:
            raise ValueError("Repository path must name the Git toplevel")
        return resolved

    def _base(self, repository: Path, base_sha: str) -> str:
        value = base_sha.strip().casefold()
        if not SHA_PATTERN.fullmatch(value):
            raise ValueError("Approved base must be a full lowercase Git commit SHA")
        resolved = self._git(
            repository, "rev-parse", "--verify", f"{value}^{{commit}}"
        ).stdout.casefold()
        if resolved != value:
            raise ValueError("Approved base SHA does not resolve exactly")
        return value

    @staticmethod
    def _branch(task_id: int, fencing_token: int) -> str:
        return f"agent-factory/task-{task_id}/lease-{fencing_token}"

    def _path(self, task_id: int, fencing_token: int) -> Path:
        return (
            self.worktree_root / f"task-{task_id}-lease-{fencing_token}"
        ).resolve()

    @staticmethod
    def _view(row: Any) -> WorktreeView:
        return WorktreeView(
            id=int(row["id"]),
            identity=str(row["identity"]),
            assignment_id=int(row["assignment_id"]),
            task_id=int(row["task_id"]),
            lease_id=int(row["lease_id"]),
            fencing_token=int(row["fencing_token"]),
            owner=str(row["owner"]),
            repository=str(row["repository"]),
            base_sha=str(row["base_sha"]),
            branch=str(row["branch"]),
            path=str(row["path"]),
            status=str(row["status"]),
            retention_until=(
                str(row["retention_until"]) if row["retention_until"] else None
            ),
            reconciled_at=(
                str(row["reconciled_at"]) if row["reconciled_at"] else None
            ),
        )

    def get(self, worktree_id: int) -> WorktreeView:
        return self._view(self.storage.managed_worktree(worktree_id))

    def _inspect(self, view: WorktreeView) -> tuple[str, str, bool]:
        path = Path(view.path)
        head = self._git(path, "rev-parse", "HEAD").stdout.casefold()
        branch = self._git(path, "branch", "--show-current").stdout
        dirty = bool(
            self._git(
                path, "status", "--porcelain=v1", "--untracked-files=all"
            ).stdout
        )
        return head, branch, dirty

    def provision(
        self,
        *,
        assignment_id: int,
        fencing_token: int,
        repository: Path,
        base_sha: str,
        attempt_id: int | None = None,
    ) -> WorktreeView:
        self.storage.assert_fenced_lease(assignment_id, fencing_token)
        repo = self._repository(repository)
        approved_base = self._base(repo, base_sha)
        assignment = self.storage.db.execute(
            "SELECT task_id FROM assignments WHERE id=?", (assignment_id,)
        ).fetchone()
        if not assignment:
            raise KeyError(f"Unknown assignment: {assignment_id}")
        task_id = int(assignment["task_id"])
        branch = self._branch(task_id, fencing_token)
        path = self._path(task_id, fencing_token)
        worktree_id = self.storage.create_managed_worktree(
            assignment_id=assignment_id,
            fencing_token=fencing_token,
            repository=str(repo),
            base_sha=approved_base,
            branch=branch,
            path=str(path),
            attempt_id=attempt_id,
        )
        view = self.get(worktree_id)
        if view.status in {"ready", "dirty", "retained"} and Path(view.path).is_dir():
            _, actual_branch, _ = self._inspect(view)
            if actual_branch != branch:
                raise WorktreeError(
                    "Existing worktree branch no longer matches its authority"
                )
            return view
        if view.status in {"ready", "dirty", "retained"}:
            raise WorktreeError(
                "Managed worktree disappeared; reconcile before reprovisioning"
            )
        if view.status == "missing":
            self.storage.transition_managed_worktree(worktree_id, "provisioning")
            view = self.get(worktree_id)
        if path.exists():
            head, actual_branch, dirty = self._inspect(view)
            if head != approved_base or actual_branch != branch:
                raise WorktreeError(
                    "Existing worktree does not match its approved base and branch"
                )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            branch_ref = f"refs/heads/{branch}"
            exists = self._git(
                repo, "show-ref", "--verify", "--quiet", branch_ref, check=False
            ).returncode == 0
            if exists:
                branch_head = self._git(repo, "rev-parse", branch_ref).stdout.casefold()
                if branch_head != approved_base:
                    raise WorktreeError(
                        "Existing deterministic branch has diverged from approved base"
                    )
                self._git(repo, "worktree", "add", str(path), branch)
            else:
                self._git(
                    repo,
                    "worktree",
                    "add",
                    "-b",
                    branch,
                    str(path),
                    approved_base,
                )
            head, actual_branch, dirty = self._inspect(view)
            if head != approved_base or actual_branch != branch:
                raise WorktreeError("Git created a worktree with unexpected authority")
        self.storage.transition_managed_worktree(worktree_id, "ready")
        if dirty:
            self.storage.transition_managed_worktree(worktree_id, "dirty")
        return self.get(worktree_id)

    def assert_owned(
        self, worktree_id: int, assignment_id: int, fencing_token: int
    ) -> Path:
        self.storage.assert_fenced_lease(assignment_id, fencing_token)
        view = self.get(worktree_id)
        if (
            view.assignment_id != assignment_id
            or view.fencing_token != fencing_token
            or view.status not in {"ready", "dirty"}
        ):
            raise PermissionError("Worktree is not owned by the active assignment lease")
        path = Path(view.path)
        if not path.is_dir():
            raise WorktreeError("Owned worktree is missing")
        _, branch, _ = self._inspect(view)
        if branch != view.branch:
            raise PermissionError("Owned worktree branch no longer matches its authority")
        return path

    def retain(
        self, worktree_id: int, *, now: datetime | None = None
    ) -> WorktreeView:
        view = self.get(worktree_id)
        assignment = self.storage.db.execute(
            "SELECT status FROM assignments WHERE id=?", (view.assignment_id,)
        ).fetchone()
        if not assignment or str(assignment["status"]) not in {
            "succeeded",
            "failed",
            "cancelled",
        }:
            raise PermissionError("Worktree retention requires a terminal assignment")
        instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        retention_until = (
            instant + timedelta(seconds=self.retention_seconds)
        ).isoformat(timespec="microseconds")
        if view.status not in {"ready", "dirty", "retained"}:
            raise WorktreeError(f"Worktree cannot be retained from {view.status}")
        self.storage.transition_managed_worktree(
            worktree_id,
            "retained",
            retention_until=retention_until,
        )
        return self.get(worktree_id)

    def cleanup(
        self, worktree_id: int, *, now: datetime | None = None
    ) -> WorktreeView:
        view = self.get(worktree_id)
        assignment = self.storage.db.execute(
            "SELECT status FROM assignments WHERE id=?", (view.assignment_id,)
        ).fetchone()
        if not assignment or str(assignment["status"]) not in {
            "succeeded",
            "failed",
            "cancelled",
        }:
            raise PermissionError("Worktree cleanup requires a terminal assignment")
        if view.status not in {"retained", "missing"} or not view.retention_until:
            raise PermissionError("Worktree is not in retained cleanup state")
        instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        deadline = datetime.fromisoformat(view.retention_until).astimezone(timezone.utc)
        if instant < deadline:
            raise PermissionError("Worktree retention period has not elapsed")
        path = Path(view.path)
        if path.exists():
            self._git(
                Path(view.repository),
                "worktree",
                "remove",
                "--force",
                str(path),
            )
        self._git(Path(view.repository), "worktree", "prune")
        self.storage.transition_managed_worktree(
            worktree_id,
            "cleaned",
            details={"branch_preserved": True},
        )
        return self.get(worktree_id)

    def _registered_paths(self, repository: Path) -> set[Path]:
        output = self._git(repository, "worktree", "list", "--porcelain").stdout
        return {
            Path(line.split(" ", 1)[1]).resolve()
            for line in output.splitlines()
            if line.startswith("worktree ")
        }

    def reconcile(self, repository: Path) -> WorktreeReconciliation:
        repo = self._repository(repository)
        registered = self._registered_paths(repo)
        rows = self.storage.managed_worktrees(str(repo))
        managed_paths = {Path(str(row["path"])).resolve() for row in rows}
        ready: list[int] = []
        dirty_ids: list[int] = []
        missing: list[int] = []
        retained: list[int] = []
        conflicts: list[str] = []
        for row in rows:
            view = self._view(row)
            if view.status == "cleaned":
                continue
            path = Path(view.path).resolve()
            if not path.is_dir() or path not in registered:
                if view.status != "missing":
                    self.storage.transition_managed_worktree(view.id, "missing")
                missing.append(view.id)
                continue
            try:
                head, branch, is_dirty = self._inspect(view)
            except WorktreeError as exc:
                conflicts.append(f"worktree:{view.id}:{type(exc).__name__}")
                continue
            authority_conflict = False
            if head != view.base_sha and view.status == "provisioning":
                conflicts.append(f"worktree:{view.id}:base-diverged")
                authority_conflict = True
            if branch != view.branch:
                conflicts.append(f"worktree:{view.id}:branch-mismatch")
                authority_conflict = True
            if authority_conflict:
                continue
            if view.status == "missing":
                self.storage.transition_managed_worktree(view.id, "provisioning")
                view = self.get(view.id)
            if view.status == "provisioning":
                self.storage.transition_managed_worktree(view.id, "ready")
                view = self.get(view.id)
            if is_dirty:
                if view.status == "ready":
                    self.storage.transition_managed_worktree(view.id, "dirty")
                dirty_ids.append(view.id)
            elif view.status == "dirty":
                self.storage.transition_managed_worktree(view.id, "ready")
                ready.append(view.id)
            elif view.status == "retained":
                self.storage.transition_managed_worktree(view.id, "retained")
                retained.append(view.id)
            else:
                self.storage.transition_managed_worktree(view.id, view.status)
                ready.append(view.id)
        filesystem_paths = {
            path.resolve()
            for path in self.worktree_root.iterdir()
            if path.is_dir()
        } if self.worktree_root.is_dir() else set()
        orphaned = sorted(
            str(path)
            for path in (registered | filesystem_paths) - managed_paths
            if self._within(path, self.worktree_root)
        )
        report = WorktreeReconciliation(
            repository=str(repo),
            ready_ids=tuple(sorted(ready)),
            dirty_ids=tuple(sorted(dirty_ids)),
            missing_ids=tuple(sorted(missing)),
            retained_ids=tuple(sorted(retained)),
            orphaned_paths=tuple(orphaned),
            conflicts=tuple(conflicts),
        )
        self.storage.event(
            "worktree.reconciled",
            "repository",
            str(repo),
            {
                "ready_ids": list(report.ready_ids),
                "dirty_ids": list(report.dirty_ids),
                "missing_ids": list(report.missing_ids),
                "retained_ids": list(report.retained_ids),
                "orphaned_paths": list(report.orphaned_paths),
                "conflicts": list(report.conflicts),
            },
        )
        return report
