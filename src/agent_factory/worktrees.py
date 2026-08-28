"""Control-Plane-owned Git worktree provisioning and reconciliation."""

from __future__ import annotations

import hashlib
import json
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
from .mission_checkpoints import (
    MissionCheckpointService,
    mission_epoch_branch,
    normalize_mission_git_segment,
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
class EpochWorktreeView:
    id: int
    identity: str
    authority_key: str
    mission_id: int
    mission_key: str
    execution_epoch_id: int
    epoch_number: int
    repository: str
    base_sha: str
    base_checkpoint_id: int | None
    base_checkpoint_digest: str | None
    branch: str
    path: str
    mission_segment: str
    policy_version: int
    status: str
    event_sequence: int
    reservation: dict[str, Any]
    observation: dict[str, Any]
    event_reason: str
    created_at: str
    observed_at: str


@dataclass(frozen=True)
class EpochWorktreeReconciliation:
    repository: str
    ready_ids: tuple[int, ...]
    dirty_ids: tuple[int, ...]
    missing_ids: tuple[int, ...]
    conflict_ids: tuple[int, ...]
    orphaned_paths: tuple[str, ...]


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
        self.epoch_worktree_root = (self.worktree_root / "autonomous").resolve()
        if not self._within(self.epoch_worktree_root, self.worktree_root):
            raise ValueError("Epoch worktree root must stay inside the managed root")
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

    @staticmethod
    def _path_key(path: Path) -> str:
        return os.path.normcase(str(path.resolve())).casefold()

    @staticmethod
    def _branch_key(branch: str) -> str:
        return str(branch).casefold()

    def _epoch_path(self, mission_segment: str, epoch_number: int) -> Path:
        path = (
            self.epoch_worktree_root
            / mission_segment
            / f"epoch-{int(epoch_number)}"
        ).resolve()
        if not self._within(path, self.epoch_worktree_root):
            raise ValueError("Epoch worktree path escaped its managed root")
        return path

    @staticmethod
    def _epoch_view(row: Any) -> EpochWorktreeView:
        reservation_json = str(row["reservation_json"])
        observation_json = str(row["observation_json"])
        authority_scope = {
            "mission_id": int(row["mission_id"]),
            "mission_key": str(row["mission_key"]),
            "execution_epoch_id": int(row["execution_epoch_id"]),
            "epoch_number": int(row["epoch_number"]),
            "repository_path": str(row["repository_path"]),
            "repository_key": str(row["repository_key"]),
            "base_git_commit_sha": str(row["base_git_commit_sha"]),
            "base_checkpoint_id": (
                int(row["base_checkpoint_id"])
                if row["base_checkpoint_id"] is not None
                else None
            ),
            "base_checkpoint_digest": (
                str(row["base_checkpoint_digest"])
                if row["base_checkpoint_digest"] is not None
                else None
            ),
            "epoch_branch": str(row["epoch_branch"]),
            "branch_key": str(row["branch_key"]),
            "worktree_path": str(row["worktree_path"]),
            "worktree_path_key": str(row["worktree_path_key"]),
            "mission_segment": str(row["mission_segment"]),
            "policy_version": int(row["policy_version"]),
        }
        authority_json = json.dumps(
            authority_scope,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        if (
            hashlib.sha256(authority_json.encode("utf-8")).hexdigest()
            != str(row["authority_key"])
            or hashlib.sha256(reservation_json.encode("utf-8")).hexdigest()
            != str(row["reservation_digest"])
            or hashlib.sha256(observation_json.encode("utf-8")).hexdigest()
            != str(row["observation_digest"])
        ):
            raise WorktreeError("Epoch worktree evidence digest is corrupt")
        try:
            reservation = json.loads(reservation_json)
            observation = json.loads(observation_json)
        except json.JSONDecodeError as exc:
            raise WorktreeError("Epoch worktree evidence is invalid JSON") from exc
        if not isinstance(reservation, dict) or not isinstance(observation, dict):
            raise WorktreeError("Epoch worktree evidence must be a JSON object")
        return EpochWorktreeView(
            id=int(row["id"]),
            identity=str(row["identity"]),
            authority_key=str(row["authority_key"]),
            mission_id=int(row["mission_id"]),
            mission_key=str(row["mission_key"]),
            execution_epoch_id=int(row["execution_epoch_id"]),
            epoch_number=int(row["epoch_number"]),
            repository=str(row["repository_path"]),
            base_sha=str(row["base_git_commit_sha"]),
            base_checkpoint_id=(
                int(row["base_checkpoint_id"])
                if row["base_checkpoint_id"] is not None
                else None
            ),
            base_checkpoint_digest=(
                str(row["base_checkpoint_digest"])
                if row["base_checkpoint_digest"] is not None
                else None
            ),
            branch=str(row["epoch_branch"]),
            path=str(row["worktree_path"]),
            mission_segment=str(row["mission_segment"]),
            policy_version=int(row["policy_version"]),
            status=str(row["status"]),
            event_sequence=int(row["event_sequence"]),
            reservation=reservation,
            observation=observation,
            event_reason=str(row["event_reason"]),
            created_at=str(row["created_at"]),
            observed_at=str(row["observed_at"]),
        )

    def get_epoch_worktree(self, worktree_id: int) -> EpochWorktreeView:
        return self._epoch_view(
            self.storage.autonomous_epoch_worktree(worktree_id)
        )

    def epoch_worktree(self, execution_epoch_id: int) -> EpochWorktreeView:
        return self._epoch_view(
            self.storage.autonomous_epoch_worktree_for_epoch(execution_epoch_id)
        )

    get_epoch_worktree_for_epoch = epoch_worktree

    def _epoch_scope(self, execution_epoch_id: int, repository: Path):
        checkpoints = MissionCheckpointService(self.storage)
        epoch = checkpoints.get_epoch(execution_epoch_id)
        mission = checkpoints.missions.get(epoch.mission_id)
        repo = self._repository(repository)
        configured = mission.configuration.repository_path
        if not configured or Path(configured).expanduser().resolve() != repo:
            raise ValueError(
                "Epoch repository must equal the mission's configured repository"
            )
        mission_segment = normalize_mission_git_segment(mission.mission_key)
        expected_branch = mission_epoch_branch(
            mission.mission_key, epoch.epoch_number
        )
        if epoch.epoch_branch != expected_branch:
            raise WorktreeError(
                "Persisted epoch branch does not match the deterministic naming policy"
            )
        self._git(repo, "check-ref-format", "--branch", expected_branch)
        base_sha = self._base(repo, epoch.base_git_commit_sha)
        if epoch.epoch_number == 1:
            if epoch.base_checkpoint_id is not None:
                raise WorktreeError("Epoch 1 cannot be rooted at a checkpoint")
        else:
            if epoch.base_checkpoint_id is None:
                raise WorktreeError("A restart epoch requires a base checkpoint")
            checkpoint = checkpoints.verify_checkpoint(epoch.base_checkpoint_id)
            if (
                checkpoint.mission_id != mission.id
                or checkpoint.checkpoint_digest != epoch.base_checkpoint_digest
                or checkpoint.git_commit_sha != base_sha
            ):
                raise WorktreeError(
                    "Restart epoch authority does not match its verified checkpoint"
                )
        path = self._epoch_path(mission_segment, epoch.epoch_number)
        if path == repo or not self._within(path, self.workspace):
            raise ValueError("Epoch worktree must be isolated inside the workspace")
        return checkpoints, mission, epoch, repo, base_sha, mission_segment, path

    @staticmethod
    def _parse_worktree_porcelain(output: str) -> tuple[dict[str, str], ...]:
        entries: list[dict[str, str]] = []
        current: dict[str, str] = {}
        for line in (*output.splitlines(), ""):
            if not line:
                if current:
                    entries.append(current)
                    current = {}
                continue
            key, _, value = line.partition(" ")
            if key in {"worktree", "HEAD", "branch"}:
                current[key] = value
        return tuple(entries)

    def _registered_epoch_entries(
        self, repository: Path
    ) -> tuple[dict[str, str], ...]:
        entries = self._parse_worktree_porcelain(
            self._git(repository, "worktree", "list", "--porcelain").stdout
        )
        normalized: list[dict[str, str]] = []
        for entry in entries:
            if "worktree" not in entry:
                continue
            branch = entry.get("branch", "")
            if branch.startswith("refs/heads/"):
                branch = branch[len("refs/heads/") :]
            normalized.append(
                {
                    "path": str(Path(entry["worktree"]).resolve()),
                    "head": entry.get("HEAD", "").casefold(),
                    "branch": branch,
                }
            )
        return tuple(normalized)

    def _branch_head(self, repository: Path, branch: str) -> str | None:
        reference = f"refs/heads/{branch}"
        exists = self._git(
            repository,
            "show-ref",
            "--verify",
            "--quiet",
            reference,
            check=False,
        )
        if exists.returncode == 1:
            return None
        if exists.returncode != 0:
            raise WorktreeError("Git branch authority could not be inspected safely")
        return self._git(repository, "rev-parse", reference).stdout.casefold()

    @staticmethod
    def _nul_paths(output: str) -> tuple[str, ...]:
        return tuple(value for value in output.split("\0") if value)

    def _epoch_dirty_observation(self, path: Path) -> tuple[bool, dict[str, Any]]:
        """Compare candidate files to index blobs, bypassing racy stat-cache hits."""

        modified = self._nul_paths(
            self._git(path, "ls-files", "--modified", "--deleted", "-z").stdout
        )
        staged = self._nul_paths(
            self._git(path, "diff", "--cached", "--name-only", "-z", "--").stdout
        )
        untracked = self._nul_paths(
            self._git(
                path, "ls-files", "--others", "--exclude-standard", "-z"
            ).stdout
        )
        unmerged = bool(self._git(path, "ls-files", "--unmerged", "-z").stdout)
        filemode_result = self._git(
            path, "config", "--bool", "core.filemode", check=False
        )
        check_filemode = (
            filemode_result.returncode == 0
            and filemode_result.stdout.casefold() == "true"
        )
        content_mismatches: list[str] = []
        mode_mismatches: list[str] = []
        unverifiable: list[str] = []
        for relative in modified:
            entry = self._git(
                path, "ls-files", "--stage", "-z", "--", relative, check=False
            )
            target = path / relative
            if entry.returncode or not entry.stdout or not os.path.lexists(target):
                content_mismatches.append(relative)
                continue
            metadata, _, indexed_path = entry.stdout.partition("\t")
            parts = metadata.split()
            if len(parts) != 3 or indexed_path.rstrip("\0") != relative:
                unverifiable.append(relative)
                continue
            mode, index_sha, stage = parts
            if stage != "0" or mode == "160000":
                content_mismatches.append(relative)
                continue
            hashed = self._git(
                path,
                "hash-object",
                "--filters",
                f"--path={relative}",
                "--",
                relative,
                check=False,
            )
            if hashed.returncode or hashed.stdout.casefold() != index_sha.casefold():
                content_mismatches.append(relative)
                continue
            if check_filemode and mode in {"100644", "100755"}:
                actual_executable = bool(target.stat().st_mode & 0o100)
                if actual_executable != (mode == "100755"):
                    mode_mismatches.append(relative)
        dirty = bool(
            staged
            or untracked
            or unmerged
            or content_mismatches
            or mode_mismatches
            or unverifiable
        )
        return dirty, {
            "modified_candidates": list(modified[:100]),
            "staged_entries": list(staged[:100]),
            "untracked_entries": list(untracked[:100]),
            "unmerged": unmerged,
            "content_mismatches": content_mismatches[:100],
            "mode_mismatches": mode_mismatches[:100],
            "unverifiable_entries": unverifiable[:100],
        }

    def _epoch_reservation_observation(
        self,
        *,
        repository: Path,
        path: Path,
        branch: str,
        base_sha: str,
    ) -> dict[str, Any]:
        entries = self._registered_epoch_entries(repository)
        branch_head = self._branch_head(repository, branch)
        path_kind = (
            "directory"
            if path.is_dir()
            else "other"
            if path.exists()
            else "missing"
        )
        return {
            "schema_version": 1,
            "repository_path": str(repository),
            "worktree_path": str(path),
            "expected_branch": branch,
            "expected_base_sha": base_sha,
            "path_kind": path_kind,
            "branch_present": branch_head is not None,
            "branch_head": branch_head,
            "registered_branch_paths": sorted(
                entry["path"] for entry in entries if entry["branch"] == branch
            ),
            "registered_expected_path": any(
                Path(entry["path"]) == path for entry in entries
            ),
        }

    def reserve_epoch(
        self,
        *,
        execution_epoch_id: int,
        repository: Path,
    ) -> EpochWorktreeView:
        (
            _,
            mission,
            epoch,
            repo,
            base_sha,
            mission_segment,
            path,
        ) = self._epoch_scope(execution_epoch_id, repository)
        reservation = self._epoch_reservation_observation(
            repository=repo,
            path=path,
            branch=epoch.epoch_branch,
            base_sha=base_sha,
        )
        worktree_id = self.storage.reserve_autonomous_epoch_worktree(
            mission_id=mission.id,
            mission_key=mission.mission_key,
            execution_epoch_id=epoch.id,
            epoch_number=epoch.epoch_number,
            repository_path=str(repo),
            repository_key=self._path_key(repo),
            base_git_commit_sha=base_sha,
            base_checkpoint_id=epoch.base_checkpoint_id,
            base_checkpoint_digest=epoch.base_checkpoint_digest,
            epoch_branch=epoch.epoch_branch,
            branch_key=self._branch_key(epoch.epoch_branch),
            worktree_path=str(path),
            worktree_path_key=self._path_key(path),
            mission_segment=mission_segment,
            reservation=reservation,
        )
        return self.get_epoch_worktree(worktree_id)

    reserve_epoch_worktree = reserve_epoch

    def _authorized_epoch_head(
        self, view: EpochWorktreeView, head_sha: str
    ) -> str | None:
        head = head_sha.casefold()
        if head == view.base_sha:
            return "EPOCH_BASE"
        checkpoint = self.storage.db.execute(
            """SELECT id FROM autonomous_mission_checkpoints
                WHERE execution_epoch_id=? AND git_commit_sha=?
                ORDER BY sequence DESC LIMIT 1""",
            (view.execution_epoch_id, head),
        ).fetchone()
        if not checkpoint:
            return None
        ancestry = self._git(
            Path(view.repository),
            "merge-base",
            "--is-ancestor",
            view.base_sha,
            head,
            check=False,
        )
        if ancestry.returncode == 0:
            return f"CHECKPOINT:{int(checkpoint['id'])}"
        if ancestry.returncode == 1:
            return None
        raise WorktreeError("Git ancestry could not be inspected safely")

    def _observe_epoch_worktree(
        self, view: EpochWorktreeView
    ) -> tuple[str, dict[str, Any], str]:
        repository = Path(view.repository)
        path = Path(view.path)
        entries = self._registered_epoch_entries(repository)
        expected_entry = next(
            (entry for entry in entries if Path(entry["path"]) == path), None
        )
        branch_entries = tuple(
            entry for entry in entries if entry["branch"] == view.branch
        )
        branch_head = self._branch_head(repository, view.branch)
        observation: dict[str, Any] = {
            "schema_version": 1,
            "repository_path": str(repository),
            "worktree_path": str(path),
            "expected_branch": view.branch,
            "expected_base_sha": view.base_sha,
            "path_exists": path.exists(),
            "path_is_directory": path.is_dir(),
            "branch_present": branch_head is not None,
            "branch_head": branch_head,
            "registered_branch_paths": sorted(
                entry["path"] for entry in branch_entries
            ),
        }
        if branch_head is not None:
            head_authority = self._authorized_epoch_head(view, branch_head)
            observation["branch_head_authority"] = head_authority
            if head_authority is None:
                return (
                    "CONFLICT",
                    observation,
                    "Epoch branch head is not the base or a checkpointed descendant",
                )
        if not path.exists():
            if branch_entries:
                return (
                    "CONFLICT",
                    observation,
                    "Epoch branch remains registered at a missing or different path",
                )
            return "MISSING", observation, "Epoch worktree path is absent"
        if not path.is_dir():
            return (
                "CONFLICT",
                observation,
                "Epoch worktree path is occupied by a non-directory",
            )
        if expected_entry is None:
            return (
                "CONFLICT",
                observation,
                "Epoch worktree path is not registered by the repository",
            )
        try:
            root = Path(
                self._git(path, "rev-parse", "--show-toplevel").stdout
            ).resolve()
            head = self._git(path, "rev-parse", "HEAD").stdout.casefold()
            branch = self._git(path, "branch", "--show-current").stdout
            status_snapshot = self._git(
                path, "status", "--porcelain=v1", "--untracked-files=all"
            ).stdout
            dirty, dirty_evidence = self._epoch_dirty_observation(path)
        except WorktreeError:
            observation["inspection"] = "FAILED"
            return (
                "CONFLICT",
                observation,
                "Epoch worktree Git authority cannot be inspected",
            )
        observation.update(
            {
                "git_toplevel": str(root),
                "actual_head": head,
                "actual_branch": branch,
                "dirty": dirty,
                "porcelain_entries": status_snapshot.splitlines()[:100],
                **dirty_evidence,
                "registered_head": expected_entry["head"],
                "registered_branch": expected_entry["branch"],
            }
        )
        if root != path or branch != view.branch or expected_entry["branch"] != view.branch:
            return (
                "CONFLICT",
                observation,
                "Epoch worktree branch or repository root differs from authority",
            )
        if branch_head is None or head != branch_head or expected_entry["head"] != head:
            return (
                "CONFLICT",
                observation,
                "Epoch worktree HEAD differs from its authoritative branch ref",
            )
        head_authority = self._authorized_epoch_head(view, head)
        observation["head_authority"] = head_authority
        if head_authority is None:
            return (
                "CONFLICT",
                observation,
                "Epoch worktree HEAD is not an authorized checkpoint lineage head",
            )
        if dirty:
            return "DIRTY", observation, "Epoch worktree contains uncommitted changes"
        return "READY", observation, "Epoch worktree matches durable Git authority"

    def _record_epoch_observation(
        self,
        view: EpochWorktreeView,
        status: str,
        observation: dict[str, Any],
        reason: str,
    ) -> EpochWorktreeView:
        self.storage.append_autonomous_epoch_worktree_event(
            view.id,
            status=status,
            observation=observation,
            reason=reason,
        )
        return self.get_epoch_worktree(view.id)

    def reconcile_epoch_worktree(self, worktree_id: int) -> EpochWorktreeView:
        view = self.get_epoch_worktree(worktree_id)
        try:
            status, observation, reason = self._observe_epoch_worktree(view)
        except WorktreeError as exc:
            status = "CONFLICT"
            observation = {
                "schema_version": 1,
                "repository_path": view.repository,
                "worktree_path": view.path,
                "expected_branch": view.branch,
                "expected_base_sha": view.base_sha,
                "inspection_error": type(exc).__name__,
            }
            reason = "Epoch worktree reconciliation could not establish Git authority"
        return self._record_epoch_observation(view, status, observation, reason)

    def reconcile_epoch(self, execution_epoch_id: int) -> EpochWorktreeView:
        return self.reconcile_epoch_worktree(
            self.epoch_worktree(execution_epoch_id).id
        )

    def provision_epoch(
        self,
        *,
        execution_epoch_id: int,
        repository: Path,
    ) -> EpochWorktreeView:
        """Create one deterministic epoch worktree without rewriting any Git ref."""

        view = self.reserve_epoch(
            execution_epoch_id=execution_epoch_id,
            repository=repository,
        )
        status, observation, reason = self._observe_epoch_worktree(view)
        view = self._record_epoch_observation(
            view, status, observation, reason
        )
        if status == "READY":
            return view
        if status == "DIRTY":
            raise WorktreeError(
                "Existing epoch worktree is dirty; refusing destructive adoption"
            )
        if status == "CONFLICT":
            raise WorktreeError(
                "Existing epoch branch or worktree conflicts with durable authority"
            )

        repository_path = Path(view.repository)
        worktree_path = Path(view.path)
        preflight = self._epoch_reservation_observation(
            repository=repository_path,
            path=worktree_path,
            branch=view.branch,
            base_sha=view.base_sha,
        )
        branch_head = preflight["branch_head"]
        if preflight["registered_branch_paths"]:
            return self._raise_epoch_provision_conflict(
                view,
                preflight,
                "Epoch branch is already registered at another or stale worktree path",
            )
        if branch_head is not None and self._authorized_epoch_head(
            view, str(branch_head)
        ) is None:
            return self._raise_epoch_provision_conflict(
                view,
                preflight,
                "Existing deterministic epoch branch has diverged from authority",
            )
        provisioning = {
            **preflight,
            "mutation": "git-worktree-add",
            "create_branch": branch_head is None,
        }
        view = self._record_epoch_observation(
            view,
            "PROVISIONING",
            provisioning,
            "Epoch authority persisted; Git worktree mutation may begin",
        )
        try:
            worktree_path.parent.mkdir(parents=True, exist_ok=True)
            resolved_after_mkdir = worktree_path.resolve()
            if (
                resolved_after_mkdir != worktree_path
                or not self._within(resolved_after_mkdir, self.epoch_worktree_root)
            ):
                raise WorktreeError("Epoch worktree parent escaped the managed root")
            if branch_head is None:
                self._git(
                    repository_path,
                    "worktree",
                    "add",
                    "-b",
                    view.branch,
                    str(worktree_path),
                    view.base_sha,
                )
            else:
                self._git(
                    repository_path,
                    "worktree",
                    "add",
                    str(worktree_path),
                    view.branch,
                )
        except (OSError, WorktreeError) as exc:
            failure = {
                **provisioning,
                "mutation_result": "FAILED_OR_INDETERMINATE",
                "error_type": type(exc).__name__,
            }
            self._record_epoch_observation(
                view,
                "CONFLICT",
                failure,
                "Git epoch worktree mutation did not converge",
            )
            raise WorktreeError(
                "Git could not provision the reserved epoch worktree safely"
            ) from exc

        status, observation, reason = self._observe_epoch_worktree(view)
        result = self._record_epoch_observation(
            view, status, observation, reason
        )
        if status != "READY":
            raise WorktreeError(
                "Provisioned epoch worktree did not match its durable authority"
            )
        return result

    def _raise_epoch_provision_conflict(
        self,
        view: EpochWorktreeView,
        observation: dict[str, Any],
        reason: str,
    ) -> EpochWorktreeView:
        self._record_epoch_observation(
            view, "CONFLICT", observation, reason
        )
        raise WorktreeError(reason)

    provision_epoch_worktree = provision_epoch

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
            and path != self.epoch_worktree_root
            and not self._within(path, self.epoch_worktree_root)
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

    def reconcile_epochs(self, repository: Path) -> EpochWorktreeReconciliation:
        """Observe every epoch worktree for a repository without changing Git."""

        repo = self._repository(repository)
        rows = self.storage.autonomous_epoch_worktrees(self._path_key(repo))
        ready: list[int] = []
        dirty: list[int] = []
        missing: list[int] = []
        conflicts: list[int] = []
        managed_paths: set[Path] = set()
        for row in rows:
            view = self._epoch_view(row)
            managed_paths.add(Path(view.path).resolve())
            reconciled = self.reconcile_epoch_worktree(view.id)
            if reconciled.status == "READY":
                ready.append(view.id)
            elif reconciled.status == "DIRTY":
                dirty.append(view.id)
            elif reconciled.status == "MISSING":
                missing.append(view.id)
            else:
                conflicts.append(view.id)
        registered_paths = {
            Path(entry["path"]).resolve()
            for entry in self._registered_epoch_entries(repo)
            if self._within(Path(entry["path"]).resolve(), self.epoch_worktree_root)
        }
        filesystem_paths = (
            {
                path.resolve()
                for path in self.epoch_worktree_root.glob("*/epoch-*")
                if path.is_dir()
            }
            if self.epoch_worktree_root.is_dir()
            else set()
        )
        orphaned = tuple(
            sorted(str(path) for path in (registered_paths | filesystem_paths) - managed_paths)
        )
        report = EpochWorktreeReconciliation(
            repository=str(repo),
            ready_ids=tuple(sorted(ready)),
            dirty_ids=tuple(sorted(dirty)),
            missing_ids=tuple(sorted(missing)),
            conflict_ids=tuple(sorted(conflicts)),
            orphaned_paths=orphaned,
        )
        self.storage.event(
            "autonomous_epoch_worktrees.reconciled",
            "repository",
            str(repo),
            {
                "ready_ids": list(report.ready_ids),
                "dirty_ids": list(report.dirty_ids),
                "missing_ids": list(report.missing_ids),
                "conflict_ids": list(report.conflict_ids),
                "orphaned_paths": list(report.orphaned_paths),
            },
        )
        return report

    reconcile_epoch_worktrees = reconcile_epochs


class MissionEpochWorktreeManager(WorktreeManager):
    """Named autonomous API backed by the sole AgentFactory worktree authority."""

    pass
