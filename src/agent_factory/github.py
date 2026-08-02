"""Constrained GitHub CLI integration with dry-run and immutable-plan support."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

Runner = Callable[[list[str]], dict[str, Any]]
ALLOWED_ACTIONS = frozenset({"create_issue", "update_issue", "comment", "project_field"})
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ACTION_FIELDS = {
    "create_issue": frozenset(
        {"action", "idempotency_key", "title", "body", "labels"}
    ),
    "update_issue": frozenset(
        {"action", "idempotency_key", "number", "title", "body", "add_labels"}
    ),
    "comment": frozenset({"action", "idempotency_key", "number", "body"}),
    "project_field": frozenset(
        {
            "action",
            "idempotency_key",
            "item_id",
            "project_id",
            "field_id",
            "option_id",
        }
    ),
}


def _default_runner(command: list[str]) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)[:4000]}
    if proc.returncode:
        return {
            "ok": False,
            "error": (proc.stderr or "GitHub CLI failed").strip()[:4000],
            "returncode": proc.returncode,
        }
    try:
        data: Any = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = proc.stdout.strip()
    return {"ok": True, "data": data}


@dataclass
class GitHubClient:
    """Read GitHub state and apply only a small, explicit mutation allowlist."""

    repo: str | None = None
    dry_run: bool = True
    runner: Runner = field(default=_default_runner, repr=False)

    def __post_init__(self) -> None:
        self.repo = self.repo or os.getenv("AGENT_FACTORY_GITHUB_REPOSITORY")

    def available(self) -> bool:
        return shutil.which("gh") is not None

    def _repository(self) -> str:
        repo = str(self.repo or "").strip()
        if not REPOSITORY_PATTERN.fullmatch(repo):
            raise ValueError(
                "A GitHub repository is required in OWNER/REPOSITORY form; "
                "pass --repo or set AGENT_FACTORY_GITHUB_REPOSITORY"
            )
        return repo

    def _run(self, args: list[str], *, mutate: bool = False) -> dict[str, Any]:
        command = ["gh", *args]
        if mutate and self.dry_run:
            return {"dry_run": True, "command": command, "executed": False, "ok": True}
        if not self.available() and self.runner is _default_runner:
            return {"ok": False, "error": "GitHub CLI executable not found", "command": command}
        return self.runner(command)

    def issues(self) -> dict[str, Any]:
        repo = self._repository()
        return self._run(
            [
                "issue",
                "list",
                "--repo",
                repo,
                "--state",
                "all",
                "--limit",
                "1000",
                "--json",
                "number,title,state,labels,body",
            ]
        )

    def project_items(self, owner: str, number: int) -> dict[str, Any]:
        return self._run(
            ["project", "item-list", str(number), "--owner", owner, "--format", "json"]
        )

    def verify_target(self) -> dict[str, Any]:
        repo = self._repository()
        identity = self._run(["api", "user"])
        target = self._run(
            ["repo", "view", repo, "--json", "nameWithOwner,viewerPermission"]
        )
        if not identity.get("ok") or not target.get("ok"):
            return {
                "ok": False,
                "error": "Could not verify GitHub identity and repository access",
            }
        identity_data = identity.get("data") or {}
        repository = target.get("data") or {}
        login = str(identity_data.get("login", "")) if isinstance(identity_data, dict) else ""
        actual = str(repository.get("nameWithOwner", "")) if isinstance(repository, dict) else ""
        permission = repository.get("viewerPermission") if isinstance(repository, dict) else None
        if actual.casefold() != repo.casefold():
            return {
                "ok": False,
                "error": "Repository returned by GitHub does not match the approved target",
                "login": login,
                "repo": actual,
            }
        if permission not in {"ADMIN", "MAINTAIN", "WRITE"}:
            return {
                "ok": False,
                "error": "Authenticated account lacks write permission",
                "login": login,
                "repo": actual,
                "permission": permission,
            }
        return {"ok": True, "login": login, "repo": actual, "permission": permission}

    @staticmethod
    def _operation_args(operation: dict[str, Any], repo: str) -> list[str]:
        action = str(operation.get("action", ""))
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"GitHub mutation action is not allowlisted: {action}")
        unknown = set(operation) - ACTION_FIELDS[action]
        if unknown:
            raise ValueError(
                f"GitHub {action} operation contains unsupported fields: {sorted(unknown)}"
            )
        key = operation.get("idempotency_key")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Every GitHub mutation requires a non-empty idempotency_key")
        if action == "create_issue":
            args = [
                "issue",
                "create",
                "--repo",
                repo,
                "--title",
                str(operation["title"]),
                "--body",
                str(operation["body"]),
            ]
            for label in operation.get("labels", []):
                args += ["--label", str(label)]
            return args
        if action == "update_issue":
            args = ["issue", "edit", str(int(operation["number"])), "--repo", repo]
            if "title" in operation:
                args += ["--title", str(operation["title"])]
            if "body" in operation:
                args += ["--body", str(operation["body"])]
            for label in operation.get("add_labels", []):
                args += ["--add-label", str(label)]
            if len(args) == 5:
                raise ValueError("update_issue has no allowlisted changes")
            return args
        if action == "comment":
            return [
                "issue",
                "comment",
                str(int(operation["number"])),
                "--repo",
                repo,
                "--body",
                str(operation["body"]),
            ]
        return [
            "project",
            "item-edit",
            "--id",
            str(operation["item_id"]),
            "--project-id",
            str(operation["project_id"]),
            "--field-id",
            str(operation["field_id"]),
            "--single-select-option-id",
            str(operation["option_id"]),
        ]

    def create_issue(self, title: str, body: str, labels: list[str], key: str) -> dict[str, Any]:
        repo = self._repository()
        operation = {
            "action": "create_issue",
            "idempotency_key": key,
            "title": title,
            "body": body,
            "labels": labels,
        }
        return self._run(self._operation_args(operation, repo), mutate=True)

    def comment(self, number: int, body: str, key: str) -> dict[str, Any]:
        repo = self._repository()
        operation = {
            "action": "comment",
            "idempotency_key": key,
            "number": number,
            "body": body,
        }
        return self._run(self._operation_args(operation, repo), mutate=True)

    def apply(
        self,
        operations: list[dict[str, Any]],
        completed_keys: set[str] | None = None,
    ) -> dict[str, Any]:
        repo = self._repository()
        completed_keys = completed_keys or set()
        prepared = [(operation, self._operation_args(operation, repo)) for operation in operations]
        keys = [str(operation["idempotency_key"]) for operation, _ in prepared]
        if len(keys) != len(set(keys)):
            raise ValueError("GitHub mutation plan contains duplicate idempotency keys")
        if self.dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "repo": repo,
                "results": [
                    {
                        "idempotency_key": operation["idempotency_key"],
                        "action": operation["action"],
                        "executed": False,
                        "command": ["gh", *args],
                    }
                    for operation, args in prepared
                ],
            }
        verified = self.verify_target()
        if not verified.get("ok"):
            return {"ok": False, "repo": repo, "verification": verified, "results": []}
        results: list[dict[str, Any]] = []
        for operation, args in prepared:
            key = str(operation["idempotency_key"])
            if key in completed_keys:
                results.append(
                    {
                        "ok": True,
                        "skipped": True,
                        "idempotency_key": key,
                        "action": operation["action"],
                    }
                )
                continue
            result = self._run(args, mutate=True)
            results.append(
                {"idempotency_key": key, "action": operation["action"], **result}
            )
        return {
            "ok": all(result.get("ok") for result in results),
            "repo": repo,
            "verification": verified,
            "results": results,
        }
