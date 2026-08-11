"""Immutable, bounded execution context packages for worker dispatch."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import config_path_for_workspace, load_yaml
from .storage import SQLiteStorage


SHA_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class ContextPackageError(RuntimeError):
    """Raised when a valid bounded package cannot be produced."""


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Execution context values must be JSON serializable") from exc


def estimated_tokens(canonical: str) -> int:
    """Stable, provider-independent upper-bound estimator used by the MVP."""

    return (len(canonical.encode("utf-8")) + 3) // 4


@dataclass(frozen=True)
class ContextSource:
    source_id: str
    kind: str
    content: Any
    authority: str
    priority: int = 0
    supersedes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionContextPackage:
    id: int
    identity: str
    digest: str
    canonical: str
    byte_count: int
    token_count: int
    compacted: bool

    @property
    def payload(self) -> dict[str, Any]:
        value = json.loads(self.canonical)
        if not isinstance(value, dict):
            raise TypeError("Stored execution context package must be an object")
        return value


@dataclass(frozen=True)
class _PreparedSource:
    source_id: str
    kind: str
    content: Any
    authority: str
    priority: int
    supersedes: tuple[str, ...]
    digest: str

    def included_record(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "content": self.content,
            "digest": self.digest,
            "kind": self.kind,
            "priority": self.priority,
            "source_id": self.source_id,
        }

    def excluded_record(self, reason: str) -> dict[str, Any]:
        return {
            "digest": self.digest,
            "kind": self.kind,
            "reason": reason,
            "source_id": self.source_id,
        }


class ContextPackageBuilder:
    """Build and persist the AF-055 deterministic dispatch snapshot."""

    def __init__(
        self,
        storage: SQLiteStorage,
        workspace: Path,
        *,
        max_bytes: int | None = None,
        max_tokens: int | None = None,
    ):
        self.storage = storage
        self.workspace = workspace.resolve()
        policy = load_yaml(config_path_for_workspace("policy", self.workspace))
        configured = policy.get("context_packages", {})
        self.default_policy = policy
        self.max_bytes = int(
            max_bytes if max_bytes is not None else configured.get("max_bytes", 50_000)
        )
        self.max_tokens = int(
            max_tokens
            if max_tokens is not None
            else configured.get("max_tokens", 12_500)
        )
        if self.max_bytes <= 0 or self.max_tokens <= 0:
            raise ValueError("Context package limits must be positive")

    @staticmethod
    def _json_value(value: Any) -> Any:
        return json.loads(canonical_json(value))

    @classmethod
    def _prepare_source(cls, source: ContextSource) -> _PreparedSource:
        source_id = source.source_id.strip()
        kind = source.kind.strip().casefold()
        authority = source.authority.strip()
        if not source_id or not kind or not authority:
            raise ValueError("Context source identity, kind, and authority are required")
        supersedes = tuple(sorted({value.strip() for value in source.supersedes if value.strip()}))
        if source_id in supersedes:
            raise ValueError("A context source cannot supersede itself")
        content = cls._json_value(source.content)
        digest = hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()
        return _PreparedSource(
            source_id=source_id,
            kind=kind,
            content=content,
            authority=authority,
            priority=int(source.priority),
            supersedes=supersedes,
            digest=digest,
        )

    @staticmethod
    def _automatic_sources(inputs: dict[str, Any]) -> list[ContextSource]:
        sources: list[ContextSource] = []
        for input_key, kind in (
            ("requirements", "requirement"),
            ("previous_decisions", "decision"),
        ):
            values = inputs.get(input_key, [])
            if values is None:
                continue
            if not isinstance(values, list):
                values = [values]
            for index, value in enumerate(values, 1):
                sources.append(
                    ContextSource(
                        source_id=f"task-input:{input_key}:{index:04d}",
                        kind=kind,
                        content=value,
                        authority="task-input",
                        priority=100 if kind == "requirement" else 90,
                    )
                )
        return sources

    def _package(
        self,
        *,
        core: dict[str, Any],
        required_sources: tuple[dict[str, Any], ...],
        sources: dict[str, _PreparedSource],
        included_ids: set[str],
        budget_excluded_ids: set[str],
        superseded_by: dict[str, str],
    ) -> dict[str, Any]:
        included = [
            sources[source_id].included_record()
            for source_id in sorted(included_ids)
        ]
        excluded = [
            sources[source_id].excluded_record("budget")
            for source_id in sorted(budget_excluded_ids)
        ]
        superseded = [
            {
                "digest": sources[source_id].digest,
                "source_id": source_id,
                "superseded_by": superseded_by[source_id],
            }
            for source_id in sorted(superseded_by)
        ]
        package = {
            **core,
            "compaction": {
                "applied": bool(excluded or superseded),
                "strategy": "priority-descending-then-source-id",
                "token_estimator": "ceil(utf8-bytes/4)",
            },
            "relevant_requirements": sorted(
                source.source_id
                for source in sources.values()
                if source.kind == "requirement" and source.source_id in included_ids
            ),
            "previous_decisions": sorted(
                source.source_id
                for source in sources.values()
                if source.kind == "decision" and source.source_id in included_ids
            ),
            "source_manifest": {
                "excluded": excluded,
                "included": sorted(
                    [
                        *(source["source_id"] for source in required_sources),
                        *included_ids,
                    ]
                ),
                "required": list(required_sources),
                "superseded": superseded,
            },
            "sources": included,
        }
        return package

    def _fits(self, package: dict[str, Any]) -> bool:
        encoded = canonical_json(package).encode("utf-8")
        return len(encoded) <= self.max_bytes and (len(encoded) + 3) // 4 <= self.max_tokens

    def build(
        self,
        *,
        task_id: int,
        run_id: int,
        assignment_id: int,
        fencing_token: int,
        base_sha: str,
        sources: Iterable[ContextSource] = (),
        policies: dict[str, Any] | None = None,
    ) -> ExecutionContextPackage:
        approved_base = base_sha.strip().casefold()
        if not SHA_PATTERN.fullmatch(approved_base):
            raise ValueError("Context base_sha must be a full lowercase Git commit SHA")
        self.storage.assert_fenced_lease(assignment_id, fencing_token)
        assignment = self.storage.db.execute(
            "SELECT task_id FROM assignments WHERE id=?", (assignment_id,)
        ).fetchone()
        if not assignment or int(assignment["task_id"]) != task_id:
            raise PermissionError("Context package task is not owned by its assignment")
        run = self.storage.durable_run(run_id)
        if int(run["task_id"]) != task_id:
            raise PermissionError("Context package run belongs to another task")
        task = self.storage.get_task(task_id)
        dependencies = []
        for dependency_id in sorted(set(task.dependencies)):
            dependency = self.storage.get_task(int(dependency_id))
            dependencies.append(
                {
                    "acceptance_criteria": dependency.acceptance_criteria,
                    "description": dependency.description,
                    "id": dependency.id,
                    "status": dependency.status.value,
                    "title": dependency.title,
                }
            )

        prepared: dict[str, _PreparedSource] = {}
        for source in [*self._automatic_sources(task.inputs), *list(sources)]:
            value = self._prepare_source(source)
            if value.source_id in prepared:
                raise ValueError(f"Duplicate context source: {value.source_id}")
            prepared[value.source_id] = value
        superseders: dict[str, list[_PreparedSource]] = {}
        for source in prepared.values():
            for superseded_id in source.supersedes:
                if superseded_id in prepared:
                    superseders.setdefault(superseded_id, []).append(source)
        direct_superseded_by = {
            source_id: sorted(
                candidates, key=lambda value: (-value.priority, value.source_id)
            )[0].source_id
            for source_id, candidates in superseders.items()
        }
        superseded_by: dict[str, str] = {}
        for source_id in sorted(direct_superseded_by):
            seen = {source_id}
            replacement = direct_superseded_by[source_id]
            while replacement in direct_superseded_by:
                if replacement in seen:
                    raise ValueError("Context source supersession contains a cycle")
                seen.add(replacement)
                replacement = direct_superseded_by[replacement]
            superseded_by[source_id] = replacement
        active = [
            source for source in prepared.values() if source.source_id not in superseded_by
        ]
        active.sort(key=lambda source: (-source.priority, source.source_id))

        core = {
            "acceptance_criteria": task.acceptance_criteria,
            "base_sha": approved_base,
            "dependencies": dependencies,
            "limits": {
                "max_bytes": self.max_bytes,
                "max_tokens": self.max_tokens,
            },
            "policies": self._json_value(
                self.default_policy if policies is None else policies
            ),
            "schema_version": "agent-factory.execution-context.v1",
            "scope": {
                "assignment_id": assignment_id,
                "fencing_token": fencing_token,
                "project_id": task.project_id,
                "run_id": run_id,
                "task_id": task_id,
            },
            "task": {
                "budget": {
                    "max_cost_usd": task.budget.max_cost_usd,
                    "max_seconds": task.budget.max_seconds,
                    "max_tokens": task.budget.max_tokens,
                },
                "description": task.description,
                "expected_outputs": task.expected_outputs,
                "inputs": task.inputs,
                "permissions": sorted(set(task.permissions)),
                "title": task.title,
            },
        }
        required_source_values = (
            (f"task:{task_id}", "task", core["task"]),
            (
                f"acceptance-criteria:{task_id}",
                "acceptance_criteria",
                core["acceptance_criteria"],
            ),
            (f"dependencies:{task_id}", "dependencies", core["dependencies"]),
            (f"base:{approved_base}", "base", core["base_sha"]),
            ("policies:effective", "policy", core["policies"]),
            (f"dispatch:{assignment_id}:{fencing_token}", "scope", core["scope"]),
        )
        required_sources = tuple(
            {
                "authority": "control-plane",
                "digest": hashlib.sha256(
                    canonical_json(content).encode("utf-8")
                ).hexdigest(),
                "kind": kind,
                "required": True,
                "source_id": source_id,
            }
            for source_id, kind, content in required_source_values
        )
        included_ids: set[str] = set()
        budget_excluded_ids = {source.source_id for source in active}
        package = self._package(
            core=core,
            required_sources=required_sources,
            sources=prepared,
            included_ids=included_ids,
            budget_excluded_ids=budget_excluded_ids,
            superseded_by=superseded_by,
        )
        if not self._fits(package):
            raise ContextPackageError(
                "Mandatory context and source manifest exceed package limits"
            )
        for source in active:
            candidate_included = {*included_ids, source.source_id}
            candidate_excluded = budget_excluded_ids - {source.source_id}
            candidate = self._package(
                core=core,
                required_sources=required_sources,
                sources=prepared,
                included_ids=candidate_included,
                budget_excluded_ids=candidate_excluded,
                superseded_by=superseded_by,
            )
            if self._fits(candidate):
                package = candidate
                included_ids = candidate_included
                budget_excluded_ids = candidate_excluded

        serialized = canonical_json(package)
        encoded = serialized.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        package_id = self.storage.store_execution_context_package(
            task_id=task_id,
            run_id=run_id,
            assignment_id=assignment_id,
            fencing_token=fencing_token,
            digest=digest,
            package_json=serialized,
            byte_count=len(encoded),
            token_count=estimated_tokens(serialized),
            compacted=bool(package["compaction"]["applied"]),
        )
        return self.load(digest, expected_id=package_id)

    def load(
        self, digest: str, *, expected_id: int | None = None
    ) -> ExecutionContextPackage:
        row = self.storage.execution_context_package(digest)
        if expected_id is not None and int(row["id"]) != expected_id:
            raise ContextPackageError("Stored context package identity changed")
        canonical = str(row["package_json"])
        encoded = canonical.encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() != digest:
            raise ContextPackageError("Stored context package digest is invalid")
        if int(row["byte_count"]) != len(encoded):
            raise ContextPackageError("Stored context package byte count is invalid")
        return ExecutionContextPackage(
            id=int(row["id"]),
            identity=str(row["identity"]),
            digest=digest,
            canonical=canonical,
            byte_count=int(row["byte_count"]),
            token_count=int(row["token_count"]),
            compacted=bool(row["compacted"]),
        )
