"""Shell-free, allowlisted project-pack validator execution."""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .sandbox import SandboxManager, SandboxPolicy
from .storage import SQLiteStorage, _sha256_snapshot


VALIDATOR_CATEGORIES = ("test", "lint", "type_check", "build", "security_scan")


@dataclass(frozen=True)
class ValidatorPack:
    pack_id: str
    commands: Mapping[str, tuple[str, ...]]

    @classmethod
    def create(cls, pack_id: str, commands: Mapping[str, Sequence[str]]) -> "ValidatorPack":
        if not pack_id.strip() or set(commands) != set(VALIDATOR_CATEGORIES):
            raise ValueError("Validator pack requires an ID and all five command categories")
        normalized: dict[str, tuple[str, ...]] = {}
        for category in VALIDATOR_CATEGORIES:
            vector = commands[category]
            if isinstance(vector, (str, bytes)):
                raise ValueError("Validator commands must be argument vectors, never shell strings")
            values = tuple(str(value) for value in vector)
            if not values or any(not value or "\x00" in value for value in values):
                raise ValueError(f"Validator command {category} is not a fixed vector")
            normalized[category] = values
        return cls(pack_id.strip(), normalized)

    @property
    def digest(self) -> str:
        value = json.dumps(
            {"pack_id": self.pack_id, "commands": self.commands},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_validator_pack(path: Path, pack_id: str) -> ValidatorPack:
    payload = json.loads(path.read_text(encoding="utf-8"))
    packs = payload.get("packs", []) if isinstance(payload, dict) else []
    for value in packs:
        if isinstance(value, dict) and value.get("id") == pack_id:
            commands = value.get("commands")
            if not isinstance(commands, dict):
                raise ValueError(f"Validator pack {pack_id} has no command map")
            return ValidatorPack.create(pack_id, commands)
    raise KeyError(f"Unknown validator pack: {pack_id}")


@dataclass(frozen=True)
class ValidatorResult:
    id: int
    category: str
    status: str
    exit_code: int | None
    command_digest: str
    evidence_digest: str
    criterion_mappings: tuple[str, ...]


@dataclass(frozen=True)
class ValidationSuiteResult:
    candidate_digest: str
    passed: bool
    results: tuple[ValidatorResult, ...]


class ValidatorRunner:
    def __init__(
        self,
        storage: SQLiteStorage,
        workspace: Path,
        sandbox: SandboxManager,
    ):
        self.storage = storage
        self.workspace = workspace.resolve()
        self.sandbox = sandbox

    def run(
        self,
        *,
        assignment_id: int,
        fencing_token: int,
        attempt_id: int,
        worktree_id: int,
        candidate_digest: str,
        pack: ValidatorPack,
        criterion_mappings: Mapping[str, Sequence[str]],
        max_seconds: int = 120,
        max_output_chars: int = 100_000,
    ) -> ValidationSuiteResult:
        _sha256_snapshot(candidate_digest, "candidate digest")
        if set(criterion_mappings) != set(VALIDATOR_CATEGORIES):
            raise ValueError("Every validator category requires criterion mappings")
        worktree = self.storage.managed_worktree(worktree_id)
        attempt = self.storage.db.execute(
            "SELECT assignment_id,status FROM attempts WHERE id=?", (attempt_id,)
        ).fetchone()
        if (
            int(worktree["assignment_id"]) != assignment_id
            or int(worktree["attempt_id"] or 0) != attempt_id
            or int(worktree["fencing_token"] or 0) != fencing_token
            or str(worktree["status"]) not in {"ready", "dirty"}
            or not attempt
            or int(attempt["assignment_id"]) != assignment_id
        ):
            raise PermissionError("Validator worktree is not owned by the live attempt")
        task = self.storage.get_task(int(worktree["task_id"]))
        accepted = set(task.acceptance_criteria)
        normalized_mappings: dict[str, tuple[str, ...]] = {}
        for category, values in criterion_mappings.items():
            mapped = tuple(sorted({str(value) for value in values if str(value)}))
            if not mapped or not set(mapped) <= accepted:
                raise ValueError(f"Validator {category} must map to declared acceptance criteria")
            normalized_mappings[category] = mapped
        worktree_path = Path(str(worktree["path"])).resolve()
        policy = SandboxPolicy.create(
            self.workspace, worktree_path,
            max_seconds=max_seconds, max_output_chars=max_output_chars,
        )
        recorded: list[ValidatorResult] = []
        for category in VALIDATOR_CATEGORIES:
            command = pack.commands[category]
            result = self.sandbox.execute(
                assignment_id, fencing_token, policy, command
            )
            effective_status = "failed" if result.changed_files else result.status
            effective_stderr = result.stderr
            if result.changed_files:
                effective_stderr = (
                    effective_stderr + "\nValidator modified candidate files: "
                    + ", ".join(result.changed_files)
                ).strip()
            environment = {
                "platform": platform.system().casefold(),
                "python": platform.python_version(),
                "backend": result.backend,
                "cwd_scope": "candidate_worktree",
                "network": policy.network,
                "max_seconds": policy.max_seconds,
                "max_output_chars": policy.max_output_chars,
            }
            with self.storage.db:
                cursor = self.storage.db.execute(
                    """INSERT INTO validator_results(
                           identity,task_id,assignment_id,attempt_id,worktree_id,
                           candidate_digest,pack_id,pack_digest,category,command_json,
                           command_digest,status,exit_code,stdout,stderr,
                           environment_json,criterion_mappings_json,
                           evidence_directory,evidence_digest
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        self.storage._identity("validator-result"), task.id,
                        assignment_id, attempt_id, worktree_id, candidate_digest,
                        pack.pack_id, pack.digest, category,
                        json.dumps(command, separators=(",", ":")),
                        result.command_digest, effective_status, result.returncode,
                        result.stdout, effective_stderr,
                        json.dumps(environment, sort_keys=True),
                        json.dumps(normalized_mappings[category], separators=(",", ":")),
                        str(Path(result.evidence_directory).relative_to(self.workspace)),
                        result.evidence_digest,
                    ),
                )
                result_id = int(cursor.lastrowid)
                self.storage._event(
                    f"validator.{effective_status}", "validator_result", result_id,
                    {
                        "task_id": task.id, "attempt_id": attempt_id,
                        "worktree_id": worktree_id, "candidate_digest": candidate_digest,
                        "category": category, "command_digest": result.command_digest,
                        "criterion_mappings": list(normalized_mappings[category]),
                    },
                )
            recorded.append(ValidatorResult(
                result_id, category, effective_status, result.returncode,
                result.command_digest, result.evidence_digest,
                normalized_mappings[category],
            ))
        return ValidationSuiteResult(
            candidate_digest,
            all(result.status == "succeeded" for result in recorded),
            tuple(recorded),
        )
