#!/usr/bin/env python3
"""Safe deploy helper used by CI/CD for automated release rollout.

Features:
- checks whether git head changed since last recorded deployment;
- creates a timestamped backup for configured data paths;
- runs configurable prepare / activate commands for rollout;
- runs configurable health checks with retries;
- rolls back data and runs rollback command on failure;
- prints machine-readable JSON summary for CI logging.

The script intentionally does not include project-specific shell commands;
all runtime commands are injected through environment variables / CLI arguments.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence


class DeployError(RuntimeError):
    """Raised when a deployment or rollback step fails."""


def _run_command(command: str, *, cwd: Path, env: Dict[str, str], label: str, timeout: int) -> subprocess.CompletedProcess[str]:
    rendered = command.strip()
    if not rendered:
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

    result = subprocess.run(
        rendered,
        shell=True,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()
        if output:
            preview = f"{output}\n{error}" if error else output
        else:
            preview = error
        if len(preview) > 4000:
            preview = preview[:4000] + "…"
        raise DeployError(f"{label} failed (exit {result.returncode}): {preview or '[empty output]'}")
    return result


def _git_head_sha(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _split_paths(raw: str | None) -> List[str]:
    if not raw:
        return []
    return [item.strip() for item in re.split(r"[,\n;]+", raw) if item.strip()]


def _is_sqlite_file(path: Path) -> bool:
    return path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}


def _copy_path(source: Path, target_root: Path) -> list[tuple[Path, Path]]:
    items: list[tuple[Path, Path]] = []
    target = target_root / source.name
    if source.is_dir():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target, symlinks=False)
        return [(target, source)]

    if not source.is_file():
        raise DeployError(f"Path does not exist: {source}")

    if _is_sqlite_file(source):
        _backup_sqlite(source, target.with_suffix(source.suffix + ".backup"))
        backup_main = target.with_suffix(source.suffix + ".backup")
        items.append((backup_main, source))
        for suffix in (".wal", ".shm"):
            companion = source.with_suffix(source.suffix + suffix)
            if companion.exists():
                companion_target = backup_main.with_suffix(backup_main.suffix + suffix)
                shutil.copy2(companion, companion_target)
                items.append((companion_target, companion))
        return items

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return [(target, source)]


def _backup_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(str(source))
    destination_conn = sqlite3.connect(str(destination))
    try:
        source_conn.backup(destination_conn)
    finally:
        source_conn.close()
        destination_conn.close()
    check_connection = sqlite3.connect(str(destination))
    try:
        result = check_connection.execute("PRAGMA integrity_check;").fetchone()
        if not result or result[0] != "ok":
            raise DeployError(f"Backup integrity check failed for {source}: {result}")
    finally:
        check_connection.close()


@dataclass
class BackupItem:
    source: str
    kind: str
    snapshots: list[tuple[str, str]]


@dataclass
class BackupPlan:
    root: Path
    created_at: str
    items: list[BackupItem]


def _build_backup(data_paths: Sequence[Path], repo_root: Path, project_name: str, commit_sha: str, backup_root: Path) -> BackupPlan:
    created_at = _now_iso().replace(":", "-")
    snapshot_root = backup_root / f"{_slug(project_name)}-{commit_sha[:8]}-{created_at}"
    snapshot_root.mkdir(parents=True, exist_ok=True)

    items: list[BackupItem] = []
    for source in data_paths:
        if not source.is_absolute():
            source = (repo_root / source).resolve()

        if not source.exists():
            raise DeployError(f"Configured backup path does not exist: {source}")
        relative_snapshot: list[str] = []
        for snapshot, destination in _copy_path(source, snapshot_root):
            relative_snapshot.append(f"{snapshot}|{destination}")
        items.append(
            BackupItem(
                source=str(source),
                kind="sqlite" if _is_sqlite_file(source) else "path",
                snapshots=relative_snapshot,
            )
        )
    return BackupPlan(root=snapshot_root, created_at=created_at, items=items)


def _restore_backup(plan: BackupPlan) -> None:
    for item in reversed(plan.items):
        for mapping in item.snapshots:
            snapshot_str, destination_str = mapping.split("|", 1)
            snapshot = Path(snapshot_str)
            destination = Path(destination_str)
            if not snapshot.exists():
                continue
            if snapshot.is_dir():
                if destination.exists():
                    if destination.is_dir():
                        shutil.rmtree(destination)
                    else:
                        destination.unlink()
                shutil.copytree(snapshot, destination)
                continue

            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(snapshot, destination)


def _load_state(state_file: Path) -> Dict[str, Any]:
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_state(state_file: Path, state: Dict[str, Any]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _release_notes(command: str | None, repo_root: Path, sha: str) -> str:
    if command:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        text = (result.stdout or "").strip()
        if text:
            return text
    result = subprocess.run(
        ["git", "log", "-1", "--pretty=%B", sha],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    return (result.stdout or "").strip()[:1200]


def _env_or_default(name: str, default: str = "") -> str:
    return os.environ.get(name, default) or ""


def _normalize_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deploy workflow with backup/rollback support.")
    parser.add_argument("--project-name", required=True, help="Human-readable project name for reports.")
    parser.add_argument("--state-file", default=".github/autodeploy/state.json", help="Path to state snapshot file.")
    parser.add_argument("--backup-root", default=".github/autodeploy/backups", help="Directory for persistent local backups.")
    parser.add_argument("--data-path", action="append", default=[], help="Additional backup path. May be repeated.")
    parser.add_argument("--data-paths", default="", help="Comma/semicolon/newline separated backup paths.")
    parser.add_argument("--prepare-command", default=_env_or_default("DEPLOY_PREPARE_COMMAND"), help="Command executed before activate.")
    parser.add_argument("--activate-command", default=_env_or_default("DEPLOY_ACTIVATE_COMMAND"), help="Command that performs actual rollout.")
    parser.add_argument("--rollback-command", default=_env_or_default("DEPLOY_ROLLBACK_COMMAND"), help="Command to rollback code/runtime.")
    parser.add_argument("--health-command", default=_env_or_default("DEPLOY_HEALTH_COMMAND"), help="Health command after activate.")
    parser.add_argument("--release-notes-command", default=_env_or_default("DEPLOY_RELEASE_NOTES_COMMAND"), help="Command that prints release notes.")
    parser.add_argument("--health-retries", type=int, default=5, help="Health-check retry count.")
    parser.add_argument("--health-timeout", type=int, default=120, help="Per health check timeout.")
    parser.add_argument("--command-timeout", type=int, default=600, help="Per command timeout.")
    parser.add_argument("--repo-root", default=".", help="Deployment root path (current directory by default).")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _normalize_args(argv)
    repo_root = Path(args.repo_root).resolve()
    state_file = (repo_root / args.state_file).resolve()
    backup_root = (repo_root / args.backup_root).resolve()

    if not args.activate_command:
        print(json.dumps({"status": "failure", "error": "DEPLOY_ACTIVATE_COMMAND is required."}, indent=2), file=sys.stderr)
        return 1

    data_paths = list(args.data_path)
    data_paths.extend(_split_paths(args.data_paths))
    resolved_data_paths = [Path(os.path.expandvars(p)).expanduser() for p in data_paths]

    state: Dict[str, Any] = _load_state(state_file)
    current_sha = _git_head_sha(repo_root)
    last_sha = state.get("deployed_sha")
    started = _now_iso()

    if last_sha and last_sha == current_sha:
        summary = {
            "project": args.project_name,
            "status": "no_change",
            "commit": current_sha,
            "previous_commit": last_sha,
            "state_file": str(state_file),
            "started_at": started,
            "finished_at": _now_iso(),
            "data_backup": None,
        }
        print(json.dumps(summary, indent=2))
        return 0

    env = dict(os.environ)
    env.update(
        {
            "DEPLOY_PROJECT": args.project_name,
            "DEPLOY_PROJECT_SLUG": _slug(args.project_name),
            "DEPLOY_PREVIOUS_SHA": last_sha or "",
            "DEPLOY_CURRENT_SHA": current_sha,
            "DEPLOY_REPO_ROOT": str(repo_root),
        }
    )

    backup_plan: BackupPlan | None = None
    try:
        backup_plan = _build_backup(resolved_data_paths, repo_root, args.project_name, current_sha, backup_root) if resolved_data_paths else None

        if args.prepare_command:
            _run_command(
                args.prepare_command,
                cwd=repo_root,
                env=env,
                label="prepare",
                timeout=args.command_timeout,
            )

        _run_command(
            args.activate_command,
            cwd=repo_root,
            env=env,
            label="activate",
            timeout=args.command_timeout,
        )

        if args.health_command:
            health_error: str | None = None
            for attempt in range(1, args.health_retries + 1):
                try:
                    _run_command(
                        args.health_command,
                        cwd=repo_root,
                        env=env,
                        label=f"health (attempt {attempt}/{args.health_retries})",
                        timeout=args.health_timeout,
                    )
                    health_error = None
                    break
                except DeployError as error:
                    health_error = str(error)
                    if attempt >= args.health_retries:
                        break
                    time.sleep(3)
            if health_error:
                raise DeployError(health_error)

        release_notes = _release_notes(args.release_notes_command, repo_root, current_sha)
        state.update(
            {
                "project": args.project_name,
                "deployed_sha": current_sha,
                "updated_at": _now_iso(),
                "last_attempt_sha": current_sha,
                "last_attempt_status": "success",
                "last_attempt_error": "",
                "last_backup": str(backup_plan.root) if backup_plan else "",
                "last_release_notes": release_notes,
                "runner": "scripts/autodeploy.py",
            }
        )
        _save_state(state_file, state)

        summary = {
            "project": args.project_name,
            "status": "success",
            "commit": current_sha,
            "previous_commit": last_sha,
            "state_file": str(state_file),
            "started_at": started,
            "finished_at": _now_iso(),
            "data_backup": str(backup_plan.root) if backup_plan else None,
            "release_notes": release_notes,
        }
        print(json.dumps(summary, indent=2))
        return 0
    except Exception as error:
        error_text = str(error)
        if args.rollback_command and last_sha:
            try:
                _run_command(
                    args.rollback_command,
                    cwd=repo_root,
                    env=env,
                    label="rollback",
                    timeout=args.command_timeout,
                )
            except DeployError as rollback_error:
                error_text = f"{error_text} | rollback_command_failed={rollback_error}"

        if backup_plan:
            try:
                _restore_backup(backup_plan)
            except Exception as restore_error:
                error_text = f"{error_text} | restore_failed={restore_error}"

        state.update(
            {
                "project": args.project_name,
                "deployed_sha": last_sha,
                "updated_at": _now_iso(),
                "last_attempt_sha": current_sha,
                "last_attempt_status": "failure",
                "last_attempt_error": error_text,
                "last_backup": str(backup_plan.root) if backup_plan else "",
                "runner": "scripts/autodeploy.py",
            }
        )
        _save_state(state_file, state)

        summary = {
            "project": args.project_name,
            "status": "failure",
            "commit": current_sha,
            "previous_commit": last_sha,
            "state_file": str(state_file),
            "started_at": started,
            "finished_at": _now_iso(),
            "data_backup": str(backup_plan.root) if backup_plan else None,
            "error": error_text,
        }
        print(json.dumps(summary, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
