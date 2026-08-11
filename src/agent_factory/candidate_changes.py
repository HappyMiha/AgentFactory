"""Immutable candidate commits and separately gated pull-request plans."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .providers import SENSITIVE_ENV_MARKERS
from .storage import SQLiteStorage


STABLE_TASK = re.compile(r"^AF-[0-9]{3}$")


@dataclass(frozen=True)
class CandidateChange:
    id: int
    base_sha: str
    head_sha: str
    branch: str
    diff_digest: str
    changed_files: tuple[str, ...]
    commit_message: str


class CandidateChangeService:
    def __init__(self, storage: SQLiteStorage, workspace: Path, *, git_executable: str | None = None):
        self.storage = storage
        self.workspace = workspace.resolve()
        git = git_executable or shutil.which("git")
        if not git:
            raise RuntimeError("Git executable is required for candidate changes")
        self.git = str(Path(git).resolve())

    @staticmethod
    def _environment() -> dict[str, str]:
        return {
            key: value for key, value in os.environ.items()
            if not key.startswith("GIT_")
            and not any(marker in key.upper() for marker in SENSITIVE_ENV_MARKERS)
        } | {"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}

    def _git(self, cwd: Path, *args: str) -> str:
        result = subprocess.run(
            [self.git, "-C", str(cwd), *args], shell=False, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=30,
            check=False, env=self._environment(),
        )
        if result.returncode:
            raise RuntimeError((result.stderr or "Git failed").strip()[:500])
        return result.stdout.strip()

    def create(self, codex_result_id: int, *, stable_task_id: str) -> CandidateChange:
        if not STABLE_TASK.fullmatch(stable_task_id):
            raise ValueError("Candidate commit requires a stable AF-NNN task ID")
        existing = self.storage.db.execute(
            "SELECT * FROM candidate_change_artifacts WHERE codex_result_id=?",
            (codex_result_id,),
        ).fetchone()
        if existing:
            if existing["stable_task_id"] != stable_task_id:
                raise ValueError("Codex result is already bound to another stable task ID")
            return CandidateChange(
                int(existing["id"]), str(existing["base_sha"]), str(existing["head_sha"]),
                str(existing["branch"]), str(existing["diff_digest"]),
                tuple(json.loads(existing["changed_files_json"])),
                str(existing["commit_message"]),
            )
        result = self.storage.db.execute(
            "SELECT * FROM codex_worker_results WHERE id=?", (codex_result_id,)
        ).fetchone()
        if not result or str(result["status"]) != "succeeded":
            raise ValueError("Candidate requires a successful writable-worker result")
        validations = self.storage.db.execute(
            """SELECT * FROM validator_results
                WHERE task_id=? AND attempt_id=? AND candidate_digest=? ORDER BY category""",
            (result["task_id"], result["attempt_id"], result["diff_digest"]),
        ).fetchall()
        if len(validations) != 5 or any(row["status"] != "succeeded" for row in validations):
            raise PermissionError("Failed or incomplete validation cannot become PR-ready")
        validation_json = json.dumps([
            {"category": row["category"], "evidence_digest": row["evidence_digest"]}
            for row in validations
        ], sort_keys=True, separators=(",", ":"))
        validation_digest = hashlib.sha256(validation_json.encode()).hexdigest()
        worktree = self.storage.managed_worktree(int(result["worktree_id"]))
        path = Path(str(worktree["path"])).resolve()
        repository = Path(str(worktree["repository"])).resolve()
        branch = self._git(path, "branch", "--show-current")
        if branch != str(worktree["branch"]) or not branch.startswith("agent-factory/task-"):
            raise PermissionError("Candidate is not on its Control-Plane-owned task branch")
        base_branch = self._git(repository, "branch", "--show-current")
        base_before = self._git(repository, "rev-parse", base_branch)
        changed_files = tuple(json.loads(result["changed_files_json"]))
        if not changed_files:
            raise ValueError("Candidate has no changed files")
        self._git(path, "add", "--", *changed_files)
        message = f"{stable_task_id}: candidate change"
        self._git(path, "commit", "-m", message)
        head_sha = self._git(path, "rev-parse", "HEAD").casefold()
        if self._git(repository, "rev-parse", base_branch) != base_before:
            raise RuntimeError("Base branch changed while creating candidate")
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO candidate_change_artifacts(
                       identity,codex_result_id,task_id,stable_task_id,worktree_id,
                       base_sha,head_sha,branch,diff_digest,changed_files_json,
                       commit_message,validation_digest
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("candidate-change"), codex_result_id,
                    result["task_id"], stable_task_id, result["worktree_id"],
                    worktree["base_sha"], head_sha, branch, result["diff_digest"],
                    result["changed_files_json"], message, validation_digest,
                ),
            )
            candidate_id = int(cursor.lastrowid)
            self.storage._event("candidate.change.created", "candidate_change", candidate_id, {
                "task_id": result["task_id"], "stable_task_id": stable_task_id,
                "base_sha": worktree["base_sha"], "head_sha": head_sha,
                "diff_digest": result["diff_digest"], "worktree_id": result["worktree_id"],
            })
        return CandidateChange(candidate_id, str(worktree["base_sha"]), head_sha, branch,
                               str(result["diff_digest"]), changed_files, message)

    def plan_pull_request(
        self, candidate_id: int, *, repo: str, base_branch: str, title: str, body: str
    ) -> tuple[int, int]:
        candidate = self.storage.db.execute(
            "SELECT * FROM candidate_change_artifacts WHERE id=?", (candidate_id,)
        ).fetchone()
        if not candidate:
            raise KeyError(f"Unknown candidate: {candidate_id}")
        existing = self.storage.db.execute(
            "SELECT github_plan_id,github_gate_id FROM candidate_pr_plans WHERE candidate_id=?",
            (candidate_id,),
        ).fetchone()
        if existing:
            return int(existing["github_plan_id"]), int(existing["github_gate_id"])
        operation = {
            "action": "create_pull_request",
            "idempotency_key": f"candidate:{candidate_id}:pr",
            "title": title, "body": body, "base": base_branch,
            "head": candidate["branch"],
        }
        plan_id, _ = self.storage.create_github_plan(repo, [operation])
        gate_id = self.storage.request_github_gate(plan_id)
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO candidate_pr_plans(
                       identity,candidate_id,github_plan_id,github_gate_id,dry_run
                   ) VALUES(?,?,?,?,1)""",
                (self.storage._identity("candidate-pr-plan"), candidate_id, plan_id, gate_id),
            )
        return plan_id, gate_id
