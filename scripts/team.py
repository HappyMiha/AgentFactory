#!/usr/bin/env python3
"""Coordinate named workers through a shared, optimistic Git registry.

Only public task IDs, worker names, path scopes and short coordination notes
belong in the registry. This is a cooperative development guard, not a security
boundary against someone who can bypass local hooks or rewrite remote history.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Callable
import uuid


DEFAULT_REGISTRY = "https://github.com/HappyMiha/AgentFactory.git"
REPOSITORIES = {"core": "HappyMiha/AgentFactory", "cloud": "HappyMiha/AgentFactory-Cloud"}
ACTIVE = {"claimed", "review"}
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
KEY = re.compile(r"^(core|cloud):(AF-[A-Z]+-[0-9]+|TEAM-SETUP)$")
MIGRATION_TASKS = {repo: f"{repo}:AF-TEAM-001" for repo in REPOSITORIES}
MIGRATION_FILES = ("scripts/team.py", ".github/workflows/team-policy.yml")


class TeamError(RuntimeError):
    """A coordination rule or required external operation failed."""


def run(args: list[str], cwd: Path | None = None, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(args, cwd=cwd, text=True, encoding="utf-8", errors="replace",
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
    except subprocess.TimeoutExpired as exc:
        raise TeamError(f"{args[0]} timed out; inspect status before retrying an external operation.") from exc
    if check and result.returncode:
        # Do not echo command arguments: remote URLs can contain credentials.
        raise TeamError(f"{args[0]} failed (exit {result.returncode}); check access and local configuration.")
    return result


def git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    return run(["git", *args], cwd, check=check).stdout.strip()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def worker_names(state: dict[str, Any]) -> set[str]:
    return {entry if isinstance(entry, str) else entry["name"] for entry in state.get("workers", [])}


def validate_state(state: dict[str, Any]) -> None:
    if state.get("version") not in {1, 2} or not isinstance(state.get("tasks"), dict):
        raise TeamError("Registry needs a supported version (1 or 2) and a tasks object; update both clones.")
    if not isinstance(state.get("events", []), list):
        raise TeamError("Registry events must be a list.")
    for key, task in state["tasks"].items():
        if not KEY.fullmatch(key) or task.get("status") not in {"planned", "claimed", "review", "blocked", "done"}:
            raise TeamError(f"Invalid task key or status: {key}.")
        for dependency in task.get("dependencies", []):
            if dependency not in state["tasks"]:
                raise TeamError(f"Unknown dependency {dependency} for {key}.")
        if task["status"] in ACTIVE:
            if task.get("owner") not in worker_names(state) or not task.get("scopes"):
                raise TeamError(f"Active task {key} needs a registered owner and path scopes.")
            validate_branch(task.get("branch") or "", task["owner"], key.split(":", 1)[0], key)
            if state["version"] == 1 and task["branch"].startswith("agent/"):
                raise TeamError("Agent branches require the coordinated version 2 cutover.")
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(key: str) -> None:
        if key in visiting:
            raise TeamError(f"Dependency cycle at {key}.")
        if key in visited:
            return
        visiting.add(key)
        for dependency in state["tasks"][key].get("dependencies", []):
            visit(dependency)
        visiting.remove(key)
        visited.add(key)
    for key in state["tasks"]:
        visit(key)
    branches: set[str] = set()
    for key, task in state["tasks"].items():
        if task["status"] in ACTIVE:
            if task["branch"] in branches:
                raise TeamError("Multiple active tasks use the same branch.")
            branches.add(task["branch"])
            check_locks(state, key, task["scopes"])


class Registry:
    """Each operation uses its own checkout; normal pushes arbitrate races."""

    def __init__(self, remote: str, attempts: int = 5):
        self.remote = remote
        self.attempts = attempts

    def _directory(self) -> tempfile.TemporaryDirectory[str]:
        parent = os.environ.get("TEAM_STATE_DIR")
        if parent:
            Path(parent).mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(prefix="team-state-", dir=parent)

    def _fetch(self, path: Path) -> dict[str, Any]:
        git("fetch", "--quiet", "--no-tags", "registry", "refs/heads/team-state", cwd=path)
        git("checkout", "--quiet", "-B", "transaction", "FETCH_HEAD", cwd=path)
        try:
            state = json.loads((path / "team-state.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise TeamError("Cannot read team-state.json on the registry branch.") from exc
        validate_state(state)
        return state

    def _init(self, path: Path) -> None:
        git("init", "--quiet", cwd=path)
        git("remote", "add", "registry", self.remote, cwd=path)
        git("config", "user.name", "AgentFactory Team Coordination", cwd=path)
        git("config", "user.email", "team-coordination@agentfactory.invalid", cwd=path)
        # Registry transactions must not inherit a global application hook.
        git("config", "core.hooksPath", str(path / "no-hooks"), cwd=path)
        git("config", "commit.gpgsign", "false", cwd=path)

    def read(self) -> dict[str, Any]:
        with self._directory() as directory:
            path = Path(directory)
            self._init(path)
            return self._fetch(path)

    def change(self, action: str, key: str, worker: str, note: str,
               mutation: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        operation = str(uuid.uuid4())
        with self._directory() as directory:
            path = Path(directory)
            self._init(path)
            for attempt in range(self.attempts):
                state = self._fetch(path)
                if any(event.get("operation_id") == operation for event in state.get("events", [])):
                    return state  # The previous push succeeded but its response was lost.
                mutation(state)
                validate_state(state)
                stamp = now()
                state["tasks"][key]["updated_at"] = stamp
                state["tasks"][key]["note"] = note
                state.setdefault("events", []).append({"operation_id": operation, "at": stamp,
                    "action": action, "task": key, "worker": worker, "note": note,
                    "branch": state["tasks"][key].get("branch"), "claim_id": state["tasks"][key].get("claim_id")})
                (path / "team-state.json").write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                git("add", "team-state.json", cwd=path)
                git("commit", "--quiet", "-m", f"team: {action} {key} ({worker})", cwd=path)
                try:
                    result = run(["git", "push", "--porcelain", "registry", "HEAD:refs/heads/team-state"], path, check=False)
                except TeamError:
                    result = None  # A timeout may occur after the server accepts the push.
                if result is not None and result.returncode == 0:
                    return state
                time.sleep(min(0.05 * (attempt + 1), 0.25))
            # One final read resolves an ambiguous last push without rerunning the action.
            state = self._fetch(path)
            if any(event.get("operation_id") == operation for event in state.get("events", [])):
                return state
        raise TeamError("Registry update was not confirmed; no claim should be assumed. Retry after checking status.")


def scope(value: str) -> tuple[str, str]:
    if ":" not in value:
        raise TeamError("Scopes use core:path or cloud:path.")
    repo, path = value.split(":", 1)
    path = path.replace("\\", "/")
    if path.startswith("/"):
        raise TeamError("Scopes must be repository-relative paths.")
    path = path.rstrip("/")
    if repo not in REPOSITORIES or not path or path.startswith("-") or any(part == ".." for part in path.split("/")):
        raise TeamError(f"Invalid scope: {value}.")
    if ":" in path or any(ord(char) < 32 for char in path):
        raise TeamError("Scope contains an invalid path.")
    if path in {".", "*"}:
        path = "."
    elif any(part in {"", "."} for part in path.split("/")) or "*" in path:
        raise TeamError("Use a literal path prefix or '.' for a repository root.")
    return repo, path


def covers(parent: str, child: str) -> bool:
    left_repo, left = scope(parent)
    right_repo, right = scope(child)
    return left_repo == right_repo and (left == "." or left.casefold() == right.casefold()
        or right.casefold().startswith(left.casefold() + "/"))


def overlap(left: str, right: str) -> bool:
    return covers(left, right) or covers(right, left)


def task_for(state: dict[str, Any], key: str, worker: str) -> dict[str, Any]:
    if worker not in worker_names(state) or not NAME.fullmatch(worker):
        raise TeamError("Worker is not registered. Ask the registry maintainer to add the name.")
    if key not in state["tasks"]:
        raise TeamError(f"Unknown task: {key}.")
    return state["tasks"][key]


def dependencies_done(state: dict[str, Any], task: dict[str, Any]) -> None:
    missing = [key for key in task.get("dependencies", []) if state["tasks"][key]["status"] != "done"]
    if missing:
        raise TeamError("Dependencies are not done: " + ", ".join(missing))


def check_locks(state: dict[str, Any], key: str, scopes: list[str]) -> None:
    resources = set(state["tasks"][key].get("resources", []))
    for other_key, other in state["tasks"].items():
        if other_key == key or other.get("status") not in ACTIVE:
            continue
        if any(overlap(left, right) for left in scopes for right in other.get("scopes", [])):
            raise TeamError(f"A path scope overlaps active task {other_key}.")
        if resources.intersection(other.get("resources", [])):
            raise TeamError(f"A shared resource is held by {other_key}.")


def branch_for(key: str, worker: str, version: int = 1) -> str:
    if version == 2:
        return f"agent/{worker}/{key.split(':', 1)[1]}"
    return f"team/{worker}/{key.replace(':', '-').lower()}"


def validate_branch(branch: str, worker: str, repo: str | None = None, key: str | None = None) -> None:
    prefix = f"team/{worker}/" + (repo + "-" if repo else "")
    task_id = re.escape(key.split(":", 1)[1]) if key else r"AF-[A-Z]+-[0-9]+"
    agent = re.fullmatch(r"agent/" + re.escape(worker) + "/" + task_id + r"-[0-9a-f]{8}", branch)
    if (not branch.startswith(prefix) and not agent) or run(["git", "check-ref-format", "--branch", branch], check=False).returncode:
        raise TeamError(f"Branch must be a valid {prefix}... or agent/{worker}/TASK-ID-xxxxxxxx branch.")


def claim(registry: Registry, key: str, worker: str, scopes: list[str], branch: str, note: str = "") -> dict[str, Any]:
    validate_branch(branch, worker, key.split(":", 1)[0], key)
    claim_id = str(uuid.uuid4())
    def mutate(state: dict[str, Any]) -> None:
        task = task_for(state, key, worker)
        expected = "agent/" if state["version"] == 2 else "team/"
        if not branch.startswith(expected):
            raise TeamError(f"New claims require {expected} branches under registry version {state['version']}; refresh and retry.")
        if task["status"] != "planned" or task.get("owner"):
            raise TeamError("Task is not available. Claims never expire automatically; its owner must release it.")
        dependencies_done(state, task)
        all_scopes = sorted({f"{repo}:{path}" for repo, path in map(scope, [*task.get("required_scopes", []), *scopes])})
        if not all_scopes:
            raise TeamError("Claim needs at least one explicit or catalog-required scope.")
        check_locks(state, key, all_scopes)
        if any(other.get("branch") == branch and other.get("status") in ACTIVE for other in state["tasks"].values()):
            raise TeamError("Branch is already assigned to an active task.")
        if any(event.get("action") == "claim" and event.get("branch") == branch for event in state.get("events", [])):
            raise TeamError("Task branches cannot be reused after release; choose a new unique branch.")
        task.update(status="claimed", owner=worker, branch=branch, scopes=all_scopes, pr=None, claim_id=claim_id)
        task.pop("review_head", None)
    return registry.change("claim", key, worker, note, mutate)


def own(task: dict[str, Any], worker: str, allowed: set[str]) -> None:
    if task.get("owner") != worker or task.get("status") not in allowed:
        raise TeamError("Only the current owner can perform this action in the current state.")


def pr_details(url: str, key: str, branch: str) -> dict[str, Any]:
    repo = REPOSITORIES[key.split(":", 1)[0]]
    if not re.fullmatch(r"https://github\.com/" + re.escape(repo) + r"/pull/[1-9][0-9]*", url):
        raise TeamError("PR URL must identify the task's GitHub repository.")
    result = run(["gh", "pr", "view", url, "--json", "state,mergedAt,mergeCommit,baseRefName,headRefName,headRefOid,url"])
    try:
        data = json.loads(result.stdout)
    except ValueError as exc:
        raise TeamError("GitHub returned invalid PR evidence.") from exc
    if data.get("url", "").casefold() != url.casefold() or data.get("baseRefName") != "main" or data.get("headRefName") != branch:
        raise TeamError("PR must target main from the exact claimed branch in the task repository.")
    if not re.fullmatch(r"[0-9a-f]{40,64}", data.get("headRefOid", "")):
        raise TeamError("PR evidence is missing its head commit.")
    return data


def transition(registry: Registry, action: str, key: str, worker: str, note: str = "", pr: str | None = None,
               claim_id: str | None = None, scopes: list[str] | None = None) -> dict[str, Any]:
    def mutate(state: dict[str, Any]) -> None:
        task = task_for(state, key, worker)
        allowed = ACTIVE | {"blocked"} if action == "release" else ACTIVE
        own(task, worker, allowed)
        if not claim_id or claim_id != task.get("claim_id"):
            raise TeamError("Claim token is missing or stale; inspect status and use the current claim's token.")
        if action == "heartbeat":
            return
        if action == "rescope":
            revised = sorted({f"{repo}:{path}" for repo, path in map(scope, [*task.get("required_scopes", []), *(scopes or [])])})
            if not revised:
                raise TeamError("An active claim must retain at least one scope.")
            check_locks(state, key, revised)
            task["scopes"] = revised
        elif action == "block":
            task.update(status="blocked", scopes=[])
        elif action == "release":
            task.update(status="planned", owner=None, branch=None, scopes=[], pr=None)
            task.pop("review_head", None)
        elif action in {"review", "complete"}:
            dependencies_done(state, task)
            if not pr:
                raise TeamError("This action needs --pr with the exact GitHub PR URL.")
            evidence = pr_details(pr, key, task["branch"])
            if action == "review":
                if evidence["state"] != "OPEN":
                    raise TeamError("Review requires an open pull request.")
                task.update(status="review", pr=pr, review_head=evidence["headRefOid"])
            else:
                if task["status"] != "review" or task.get("pr") != pr:
                    raise TeamError("Complete requires the registered review PR.")
                if evidence["state"] != "MERGED" or not evidence.get("mergedAt") or evidence["headRefOid"] != task.get("review_head"):
                    raise TeamError("PR is not merged at the reviewed head; refresh review after changes and merge first.")
                merged_commit = (evidence.get("mergeCommit") or {}).get("oid", "")
                if not re.fullmatch(r"[0-9a-f]{40,64}", merged_commit):
                    raise TeamError("Merged PR evidence lacks its actual merge commit.")
                task.update(status="done", scopes=[], completed_commit=merged_commit, reviewed_head=evidence["headRefOid"])
        else:
            raise TeamError("Unknown task action.")
    return registry.change(action, key, worker, note, mutate)


def repository(cwd: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    remote = git("remote", "get-url", "origin", cwd=cwd)
    for name, expected in REPOSITORIES.items():
        if remote.rstrip("/").removesuffix(".git").casefold().endswith(expected.casefold()):
            return name
    raise TeamError("Cannot infer repository; use --repo core or --repo cloud for local test remotes.")


def current_worker(cwd: Path, explicit: str | None) -> str:
    worker = explicit or os.environ.get("TEAM_WORKER") or git("config", "--get", "team.worker", cwd=cwd, check=False)
    if not worker or not NAME.fullmatch(worker):
        raise TeamError("Set a worker with configure --worker NAME, TEAM_WORKER, or --worker.")
    return worker


def clean(cwd: Path) -> None:
    if git("status", "--porcelain", "--untracked-files=all", cwd=cwd):
        raise TeamError("Working tree must be clean, including untracked files.")


def migration_pins(state: dict[str, Any]) -> dict[str, str]:
    pins = {}
    for repo, key in MIGRATION_TASKS.items():
        task = state["tasks"].get(key, {})
        commit = task.get("completed_commit", "")
        if task.get("status") != "done" or not re.fullmatch(r"[0-9a-f]{40,64}", commit):
            raise TeamError(f"Migration requires reviewed and completed {key} first.")
        pins[repo] = commit
    return pins


def reader_proof(root: Path, repo: str, commit: str) -> dict[str, str]:
    """Prove the clean owning checkout includes the reviewed reader and CI parser."""
    clean(root)
    if repository(root, None) != repo:
        raise TeamError("Migration proof uses the wrong repository.")
    git("fetch", "--quiet", "origin", "refs/heads/main:refs/remotes/origin/main", cwd=root)
    for ref in ("HEAD", "origin/main"):
        if run(["git", "merge-base", "--is-ancestor", commit, ref], root, check=False).returncode:
            raise TeamError(f"Update {repo} checkout from main before acknowledging migration.")
    proof = {}
    for path in MIGRATION_FILES:
        approved = git("rev-parse", f"{commit}:{path}", cwd=root)
        if git("rev-parse", f"HEAD:{path}", cwd=root) != approved:
            raise TeamError(f"{repo} reader or CI parser differs from its reviewed migration: {path}.")
        proof[path] = approved
    return proof


def acknowledge_migration(registry: Registry, cwd: Path, peer: Path, worker: str) -> dict[str, Any]:
    state = registry.read()
    pins = migration_pins(state)
    own_repo = repository(cwd, None)
    other_repo = "cloud" if own_repo == "core" else "core"
    roots = {own_repo: cwd, other_repo: peer}
    for root in roots.values():
        if git("config", "--local", "--get", "team.worker", cwd=root) != worker:
            raise TeamError("Both local clones must belong to the acknowledging worker.")
    proofs = {repo: reader_proof(root, repo, pins[repo]) for repo, root in roots.items()}
    def mutate(current: dict[str, Any]) -> None:
        task_for(current, MIGRATION_TASKS["core"], worker)
        if migration_pins(current) != pins:
            raise TeamError("Migration pins changed during verification; verify both clones again.")
        current.setdefault("migration", {}).setdefault("acknowledgements", {})[worker] = {
            "pins": pins, "readers": proofs, "at": now()}
    return registry.change("migration-ack", MIGRATION_TASKS["core"], worker,
                           "Verified both local repository readers and CI parsers at reviewed migration commits.", mutate)


def activate_migration(registry: Registry, worker: str) -> dict[str, Any]:
    def mutate(state: dict[str, Any]) -> None:
        if worker != "HappyDucky02":
            raise TeamError("Only the agreed integration coordinator can activate migration.")
        task_for(state, MIGRATION_TASKS["core"], worker)
        pins = migration_pins(state)
        acks = state.get("migration", {}).get("acknowledgements", {})
        expected_workers = {"HappyDucky02", "HappySnowman", "HappyHahahaker"}
        if worker_names(state) != expected_workers:
            raise TeamError("Migration requires exactly the three agreed workers.")
        for name in expected_workers:
            ack = acks.get(name, {})
            if ack.get("pins") != pins or set(ack.get("readers", {})) != set(REPOSITORIES):
                raise TeamError(f"Missing or stale two-repository migration acknowledgement: {name}.")
            for repo in REPOSITORIES:
                if set(ack["readers"][repo]) != set(MIGRATION_FILES) or any(
                    not re.fullmatch(r"[0-9a-f]{40,64}", blob) for blob in ack["readers"][repo].values()
                ):
                    raise TeamError(f"Invalid reader proof from {name}.")
        if any(acks[name]["readers"] != acks[worker]["readers"] for name in expected_workers):
            raise TeamError("The three nodes must agree on the exact reader blobs.")
        # Old clients reject version 2 at every fetch, including after a lost push race.
        # Existing branches/tokens are unchanged; only new claims change namespace.
        state["version"] = 2
        state["migration"]["activated_at"] = now()
        state["migration"]["authority"] = "core:team-state"
    return registry.change("migration-activate", MIGRATION_TASKS["core"], worker,
                           "All three workers verified both readers; new claims now use agent branches.", mutate)


def push_line(text: str, branch: str, head: str) -> str:
    lines = [line.split() for line in text.splitlines() if line.strip()]
    if len(lines) != 1 or len(lines[0]) != 4:
        raise TeamError("Push exactly one claimed branch; missing or multiple ref updates are rejected.")
    local_ref, local_sha, remote_ref, remote_sha = lines[0]
    expected = "refs/heads/" + branch
    if local_ref not in {expected, "HEAD"} or remote_ref != expected or local_sha != head or set(local_sha) == {"0"}:
        raise TeamError("Push must update the current owned branch only; tags, deletion and alternate refs are rejected.")
    if not re.fullmatch(r"[0-9a-f]{40,64}", remote_sha):
        raise TeamError("Invalid remote commit in pre-push input.")
    return remote_sha


def preflight(registry: Registry, cwd: Path, worker: str, repo: str,
              branch: str | None = None, diff_range: str | None = None,
              push: list[str] | None = None, stdin: str = "", claim_id: str | None = None) -> str:
    clean(cwd)
    actual = git("symbolic-ref", "--quiet", "--short", "HEAD", cwd=cwd, check=False)
    branch = branch or actual
    validate_branch(branch, worker, repo)
    if actual and actual != branch:
        raise TeamError("Requested branch is not the current checkout branch.")
    if push and actual != branch:
        raise TeamError("Push requires the actual symbolic checkout branch, not detached HEAD.")
    state = registry.read()
    matches = [(key, task) for key, task in state["tasks"].items()
               if task.get("branch") == branch and key.startswith(repo + ":") and task.get("status") in ACTIVE]
    if len(matches) != 1:
        raise TeamError("Current branch must have exactly one active task claim.")
    key, task = matches[0]
    task_for(state, key, worker)
    own(task, worker, ACTIVE)
    if push and (not claim_id or task.get("claim_id") != claim_id):
        raise TeamError("Push claim token is missing or stale; use the checkout that owns this claim.")
    dependencies_done(state, task)
    check_locks(state, key, task.get("scopes", []))
    if any(not any(covers(active, required) for active in task.get("scopes", [])) for required in task.get("required_scopes", [])):
        raise TeamError("Claim does not cover its catalog-required scopes.")
    remote = push[0] if push else "origin"
    if remote != "origin":
        raise TeamError("The guarded development remote must be origin.")
    if push and git("remote", "get-url", "--push", remote, cwd=cwd) != push[1]:
        raise TeamError("Push URL does not match the configured remote.")
    if push or not diff_range:
        git("fetch", "--quiet", "--no-tags", remote, "refs/heads/main:refs/remotes/origin/main", cwd=cwd)
    head = git("rev-parse", "HEAD", cwd=cwd)
    if run(["git", "merge-base", "--is-ancestor", "refs/remotes/origin/main", head], cwd, check=False).returncode:
        raise TeamError("Branch must include the current origin/main. Update it and rerun checks.")
    if push:
        remote_sha = push_line(stdin, branch, head)
        current_remote = git("ls-remote", remote, "refs/heads/" + branch, cwd=cwd)
        current_sha = current_remote.split()[0] if current_remote else "0" * len(remote_sha)
        if current_sha != remote_sha:
            raise TeamError("Remote branch changed during push; refresh and retry.")
        if set(remote_sha) != {"0"}:
            git("fetch", "--quiet", "--no-tags", remote, "refs/heads/" + branch, cwd=cwd)
            if run(["git", "merge-base", "--is-ancestor", remote_sha, head], cwd, check=False).returncode:
                raise TeamError("Non-fast-forward pushes are forbidden.")
    comparison = diff_range or "refs/remotes/origin/main...HEAD"
    if comparison.startswith("-") or not comparison.strip():
        raise TeamError("Invalid comparison range.")
    run(["git", "diff", "--check", comparison, "--"], cwd)
    paths = run(["git", "diff", "--name-only", "--no-renames", "-z", comparison, "--"], cwd).stdout.split("\0")
    outside = [path for path in paths if path and not any(covers(held, f"{repo}:{path}") for held in task.get("scopes", []))]
    if outside:
        raise TeamError("Changed paths are outside the claim: " + ", ".join(outside[:8]))
    return key


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    result.add_argument("--registry", default=DEFAULT_REGISTRY, help="Git remote containing team-state branch; local bare remotes work for tests")
    result.add_argument("--repo", choices=sorted(REPOSITORIES), help="Repository identity (normally inferred from origin)")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Show all tasks and their current owners")
    commands.add_parser("ready", help="Show unclaimed tasks whose internal dependencies are done")
    command = commands.add_parser("migration-ack", help="Verify both updated local clones and record this worker's cutover acknowledgement")
    command.add_argument("--peer-repo", type=Path, required=True, help="Local path to the other repository's updated owning clone")
    commands.add_parser("migration-activate", help="Coordinator activates version 2 only after both migration PRs and all three acknowledgements")
    for name in ("claim", "start", "rescope", "heartbeat", "block", "release", "review", "complete"):
        command = commands.add_parser(name, help={"claim":"Claim a task atomically and save its token in local Git config", "start":"Claim and create a branch from freshly fetched main", "rescope":"Atomically replace this claim's scopes after conflict checks", "heartbeat":"Record activity; claims never expire automatically", "block":"Mark blocked and release path/resource locks, keeping ownership", "release":"Owner returns a claimed/blocked task to planned", "review":"Register an open PR and its exact head commit", "complete":"Mark done only after the reviewed PR head is merged into main"}[name])
        command.add_argument("key", help="core:AF-GC-001 or cloud:AF-CLD-001")
        command.add_argument("--worker", help="Registered worker (or TEAM_WORKER / local team.worker config)")
        command.add_argument("--note", default="", help="Short PUBLIC coordination note; never include secrets or private source")
        if name in {"claim", "start", "rescope"}:
            command.add_argument("--scope", action="append", default=[], help="Repeatable core:path or cloud:path; catalog required_scopes are added")
        if name in {"claim", "start"}:
            command.add_argument("--branch", help="Owned branch matching the live registry version; unique default if omitted")
        else:
            command.add_argument("--claim-id", help="Expected claim generation; default local team.claimId config")
        if name in {"review", "complete"}:
            command.add_argument("--pr", required=True, help="Exact https://github.com/OWNER/REPO/pull/NUMBER URL")
    command = commands.add_parser("preflight", help="Check claim, ownership, fresh main, scopes and whitespace; this does not run application tests")
    command.add_argument("--worker")
    command.add_argument("--branch", help="Actual PR head branch when CI uses detached HEAD")
    command.add_argument("--range", dest="diff_range", help="Git diff range for CI; default origin/main...HEAD")
    command.add_argument("--push", nargs=2, metavar=("REMOTE", "REMOTE_URL"), help="Pre-push mode: consume exactly one standard ref-update line from stdin")
    command = commands.add_parser("configure", help="Set this checkout's worker and reviewed hook directory")
    command.add_argument("--worker", required=True)
    command.add_argument("--hooks-path", default=".githooks")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    registry = Registry(args.registry)
    cwd = Path.cwd()
    try:
        if args.command in {"status", "ready"}:
            state = registry.read()
            print(f"Registry version {state['version']}; sole claim authority: Core team-state; Bus is transport only.")
            ordering = lambda pair: (pair[1].get("milestone", ""), pair[1].get("priority", "P2"),
                -sum(pair[0] in child.get("dependencies", []) for child in state["tasks"].values()), pair[0])
            for key, task in sorted(state["tasks"].items(), key=ordering):
                if args.command == "ready" and (task["status"] != "planned" or any(state["tasks"][dep]["status"] != "done" for dep in task.get("dependencies", []))):
                    continue
                if args.command == "ready":
                    try:
                        check_locks(state, key, task.get("required_scopes", []))
                    except TeamError:
                        continue
                print(f"{key:20} {task['status']:8} {task.get('owner') or '-':12} {task.get('branch') or '-'} {task.get('claim_id') or ''}")
            return 0
        worker = current_worker(cwd, getattr(args, "worker", None))
        if args.command == "migration-ack":
            acknowledge_migration(registry, cwd, args.peer_repo.resolve(), worker)
            print(f"Recorded two-repository migration acknowledgement for {worker}.")
            return 0
        if args.command == "migration-activate":
            activate_migration(registry, worker)
            print("Registry version 2 active. Preserve existing claims; new branches use agent/WORKER/TASK-ID-xxxxxxxx.")
            return 0
        if args.command == "configure":
            if worker not in worker_names(registry.read()):
                raise TeamError("Worker is not registered.")
            hooks = (cwd / args.hooks_path).resolve()
            if not (hooks / "pre-push").is_file():
                raise TeamError("Reviewed pre-push hook does not exist at the requested path.")
            configured_hooks = git("config", "--get", "core.hooksPath", cwd=cwd, check=False)
            if configured_hooks and (cwd / configured_hooks).resolve() != hooks:
                raise TeamError("An existing custom hooksPath is configured; review and change it explicitly first.")
            git("config", "--local", "team.worker", worker, cwd=cwd)
            git("config", "--local", "team.python", sys.executable, cwd=cwd)
            git("config", "--local", "core.hooksPath", args.hooks_path, cwd=cwd)
            print(f"Configured {worker}; hooks: {args.hooks_path}")
            return 0
        if args.command == "preflight":
            key = preflight(registry, cwd, worker, repository(cwd, args.repo), args.branch, args.diff_range,
                            args.push, sys.stdin.read() if args.push else "",
                            git("config", "--get", "team.claimId", cwd=cwd, check=False))
            print(f"Preflight passed: {key}. Application tests are a separate requirement.")
            return 0
        if not KEY.fullmatch(args.key):
            raise TeamError("Use a qualified core:AF-GC-... or cloud:AF-CLD-... task key.")
        if len(args.note) > 160 or any(ord(char) < 32 for char in args.note):
            raise TeamError("Public note must be one line of at most 160 characters.")
        if args.command in {"claim", "start"}:
            branch = args.branch or (branch_for(args.key, worker, registry.read()["version"]) + "-" + uuid.uuid4().hex[:8])
            # Verify local config can be used before publishing a remote claim.
            git("rev-parse", "--git-dir", cwd=cwd)
            if args.command == "start":
                clean(cwd)
                if repository(cwd, args.repo) != args.key.split(":", 1)[0]:
                    raise TeamError("Start must run in the task's repository.")
                git("fetch", "--quiet", "--no-tags", "origin", "refs/heads/main:refs/remotes/origin/main", cwd=cwd)
                if run(["git", "show-ref", "--verify", "--quiet", "refs/heads/" + branch], cwd, check=False).returncode == 0:
                    raise TeamError("Local task branch already exists; inspect it before making a new claim.")
            state = claim(registry, args.key, worker, args.scope, branch, args.note)
            claim_id = state["tasks"][args.key]["claim_id"]
            try:
                git("config", "--local", "team.claimId", claim_id, cwd=cwd)
                git("config", "--local", "team.task", args.key, cwd=cwd)
            except TeamError:
                raise TeamError(f"Claim succeeded but saving local config failed. Claim token: {claim_id}. Inspect status before retrying.")
            if args.command == "start":
                try:
                    git("switch", "--create", branch, "refs/remotes/origin/main", cwd=cwd)
                except TeamError:
                    try:
                        transition(registry, "release", args.key, worker, "Branch creation failed; claim released.", claim_id=claim_id)
                    except TeamError:
                        raise TeamError("Branch creation failed and claim release was not confirmed; inspect status and release explicitly.")
                    raise
            print(f"Claimed {args.key} for {worker}; branch {branch}.")
        else:
            token = args.claim_id or git("config", "--get", "team.claimId", cwd=cwd, check=False)
            transition(registry, args.command, args.key, worker, args.note, getattr(args, "pr", None),
                       claim_id=token, scopes=getattr(args, "scope", None))
            print(f"{args.command}: {args.key}")
        return 0
    except (TeamError, OSError, KeyError, TypeError) as exc:
        print(f"team: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
