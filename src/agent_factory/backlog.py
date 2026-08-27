"""Project-neutral backlog manifests and deterministic GitHub issue plans."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2})
STABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
SUPPORTED_KINDS = frozenset(
    {"epic", "feature", "story", "task", "bug", "research", "change"}
)
EXECUTABLE_KINDS = frozenset({"task", "bug", "research", "change"})
MARKER_PATTERN = re.compile(r"<!--\s*agent-factory-id:([^\s]+)\s*-->")


class BacklogManifestError(ValueError):
    """Raised when a backlog manifest is incomplete or internally inconsistent."""


@dataclass(frozen=True)
class ProposedItem:
    stable_id: str
    kind: str
    title: str
    description: str
    parent_id: str | None = None
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    acceptance_criteria: tuple[str, ...] = field(default_factory=tuple)
    source_references: tuple[str, ...] = field(default_factory=tuple)
    review_notes: tuple[str, ...] = field(default_factory=tuple)
    labels: tuple[str, ...] = field(default_factory=tuple)
    priority: str = "P2"
    validation_method: tuple[str, ...] = field(default_factory=tuple)
    required_components: tuple[str, ...] = field(default_factory=tuple)
    required_infrastructure: tuple[str, ...] = field(default_factory=tuple)
    expected_artifacts: tuple[str, ...] = field(default_factory=tuple)
    definition_of_done: tuple[str, ...] = field(default_factory=tuple)
    assigned_role: str = "Developer"

    @property
    def executable(self) -> bool:
        return self.kind in EXECUTABLE_KINDS

    @property
    def level(self) -> str:
        if self.kind == "story" and "level:feature" in self.labels:
            return "feature"
        return self.kind

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def issue(self) -> dict[str, Any]:
        body = [
            f"<!-- agent-factory-id:{self.stable_id} -->",
            "",
            self.description,
            "",
            "## Acceptance criteria",
            *[f"- [ ] {criterion}" for criterion in self.acceptance_criteria],
            "",
            "## Dependencies",
            *(
                [f"- `{dependency}`" for dependency in self.dependencies]
                or ["- None"]
            ),
        ]
        if self.parent_id:
            body += ["", "## Parent", f"- `{self.parent_id}`"]
        if self.source_references:
            body += [
                "",
                "## Source references",
                *[f"- {reference}" for reference in self.source_references],
            ]
        if self.review_notes:
            body += [
                "",
                "## Human review notes",
                *[f"- {note}" for note in self.review_notes],
            ]
        body += [
            "",
            "## Execution contract",
            f"- Priority: `{self.priority}`",
            f"- Assigned role: `{self.assigned_role}`",
            "",
            "### Validation method",
            *[f"- {value}" for value in self.validation_method],
            "",
            "### Required components",
            *([f"- {value}" for value in self.required_components] or ["- None declared"]),
            "",
            "### Required infrastructure",
            *(
                [f"- {value}" for value in self.required_infrastructure]
                or ["- None declared"]
            ),
            "",
            "### Expected artifacts",
            *[f"- {value}" for value in self.expected_artifacts],
            "",
            "### Definition of Done",
            *[f"- [ ] {value}" for value in self.definition_of_done],
        ]
        labels = [f"type:{self.kind}", "status:triage", *self.labels]
        return {
            "stable_id": self.stable_id,
            "kind": self.kind,
            "title": f"[{self.kind.title()}] {self.title}",
            "body": "\n".join(body).strip(),
            "labels": list(dict.fromkeys(labels)),
        }


@dataclass(frozen=True)
class BacklogProposal:
    source_path: str
    source_sha256: str
    source_name: str
    items: tuple[ProposedItem, ...]
    schema_version: int = 1
    source_metadata: dict[str, Any] = field(default_factory=dict)
    extension_schema: str | None = None
    planning_contract: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise BacklogManifestError(
                f"Unsupported schema_version {self.schema_version!r}; expected one of "
                f"{sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        if not self.source_path.strip() or not self.source_name.strip():
            raise BacklogManifestError("Backlog source path and name are required")
        if (
            len(self.source_sha256) != 64
            or any(value not in "0123456789abcdef" for value in self.source_sha256)
        ):
            raise BacklogManifestError("Backlog source_sha256 must be a lowercase digest")
        if not self.items:
            raise BacklogManifestError("Backlog proposal cannot be empty")
        _validate_graph(self.items)
        if self.schema_version >= 2:
            for item in self.items:
                if not item.executable:
                    continue
                required = {
                    "priority": item.priority,
                    "validation_method": item.validation_method,
                    "required_components": item.required_components,
                    "required_infrastructure": item.required_infrastructure,
                    "expected_artifacts": item.expected_artifacts,
                    "definition_of_done": item.definition_of_done,
                    "assigned_role": item.assigned_role,
                }
                missing = sorted(name for name, value in required.items() if not value)
                if missing:
                    raise BacklogManifestError(
                        f"Executable item {item.stable_id!r} is missing schema v2 "
                        f"fields: {missing}"
                    )

    def to_dict(self) -> dict[str, Any]:
        source = dict(self.source_metadata)
        source.setdefault("name", self.source_name)
        document = {
            "schema_version": self.schema_version,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "source_name": self.source_name,
            "source": source,
            "items": [item.to_dict() for item in self.items],
        }
        if self.extension_schema:
            document["extension_schema"] = self.extension_schema
        if self.planning_contract:
            document["planning_contract"] = self.planning_contract
        for key, value in self.extensions.items():
            if key not in document:
                document[key] = value
        return document


def _strings(value: Any, field_name: str, stable_id: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(entry, str) and entry.strip() for entry in value
    ):
        raise BacklogManifestError(
            f"Item {stable_id!r} field {field_name!r} must be a list of non-empty strings"
        )
    return tuple(entry.strip() for entry in value)


def _item(
    document: dict[str, Any], index: int, *, schema_version: int
) -> ProposedItem:
    if not isinstance(document, dict):
        raise BacklogManifestError(f"Item at index {index} must be an object")
    stable_id = str(document.get("stable_id", "")).strip()
    if not STABLE_ID_PATTERN.fullmatch(stable_id):
        raise BacklogManifestError(
            f"Item at index {index} has an invalid stable_id: {stable_id!r}"
        )
    kind = str(document.get("kind", "")).strip().lower()
    if kind not in SUPPORTED_KINDS:
        raise BacklogManifestError(
            f"Item {stable_id!r} has unsupported kind {kind!r}; "
            f"choose one of {sorted(SUPPORTED_KINDS)}"
        )
    title = str(document.get("title", "")).strip()
    description = str(document.get("description", "")).strip()
    if not title or not description:
        raise BacklogManifestError(f"Item {stable_id!r} requires title and description")
    criteria = _strings(
        document.get("acceptance_criteria"), "acceptance_criteria", stable_id
    )
    if not criteria:
        raise BacklogManifestError(f"Item {stable_id!r} requires acceptance criteria")
    parent = document.get("parent_id")
    if parent is not None and not isinstance(parent, str):
        raise BacklogManifestError(f"Item {stable_id!r} parent_id must be a string or null")
    dependencies = _strings(
        document.get("dependencies", []), "dependencies", stable_id
    )
    labels = _strings(document.get("labels", []), "labels", stable_id)
    executable = kind in EXECUTABLE_KINDS
    raw_priority = str(document.get("priority", "")).strip()
    label_priority = next(
        (
            label.split(":", 1)[1]
            for label in labels
            if label.casefold().startswith("priority:")
        ),
        "",
    )
    priority = raw_priority or label_priority.upper() or "P2"
    validation_method = _strings(
        document.get("validation_method", []), "validation_method", stable_id
    )
    required_components = _strings(
        document.get("required_components", []), "required_components", stable_id
    )
    required_infrastructure = _strings(
        document.get("required_infrastructure", []),
        "required_infrastructure",
        stable_id,
    )
    expected_artifacts = _strings(
        document.get("expected_artifacts", []), "expected_artifacts", stable_id
    )
    definition_of_done = _strings(
        document.get("definition_of_done", []), "definition_of_done", stable_id
    )
    assigned_role = str(document.get("assigned_role", "")).strip()
    if schema_version >= 2 and executable:
        required_fields = {
            "priority": raw_priority,
            "validation_method": validation_method,
            "required_components": required_components,
            "required_infrastructure": required_infrastructure,
            "expected_artifacts": expected_artifacts,
            "definition_of_done": definition_of_done,
            "assigned_role": assigned_role,
        }
        missing = sorted(name for name, value in required_fields.items() if not value)
        if "dependencies" not in document:
            missing.append("dependencies")
        if missing:
            raise BacklogManifestError(
                f"Executable item {stable_id!r} is missing schema v2 fields: "
                f"{sorted(missing)}"
            )
    validation_method = validation_method or (
        "Verify every acceptance criterion with deterministic evidence.",
    )
    expected_artifacts = expected_artifacts or (
        "reviewable delivery artifact",
        "acceptance evidence",
    )
    definition_of_done = definition_of_done or criteria
    assigned_role = assigned_role or (
        "Developer" if executable else "Backlog Planner"
    )
    return ProposedItem(
        stable_id=stable_id,
        kind=kind,
        title=title,
        description=description,
        parent_id=parent.strip() if isinstance(parent, str) and parent.strip() else None,
        dependencies=dependencies,
        acceptance_criteria=criteria,
        source_references=_strings(
            document.get("source_references", []), "source_references", stable_id
        ),
        review_notes=_strings(document.get("review_notes", []), "review_notes", stable_id),
        labels=labels,
        priority=priority.upper(),
        validation_method=validation_method,
        required_components=required_components,
        required_infrastructure=required_infrastructure,
        expected_artifacts=expected_artifacts,
        definition_of_done=definition_of_done,
        assigned_role=assigned_role,
    )


def _validate_graph(items: tuple[ProposedItem, ...]) -> None:
    ids = [item.stable_id for item in items]
    duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
    if duplicates:
        raise BacklogManifestError(f"Duplicate stable IDs: {duplicates}")
    known = set(ids)
    for item in items:
        references = {*item.dependencies}
        if item.parent_id:
            references.add(item.parent_id)
        missing = sorted(references - known)
        if missing:
            raise BacklogManifestError(
                f"Item {item.stable_id!r} references unknown items: {missing}"
            )
        if item.stable_id in references:
            raise BacklogManifestError(f"Item {item.stable_id!r} cannot reference itself")

    edges = {
        item.stable_id: [*item.dependencies, *([item.parent_id] if item.parent_id else [])]
        for item in items
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(item_id: str) -> None:
        if item_id in visiting:
            raise BacklogManifestError(f"Backlog relationship cycle includes {item_id!r}")
        if item_id in visited:
            return
        visiting.add(item_id)
        for dependency in edges[item_id]:
            visit(dependency)
        visiting.remove(item_id)
        visited.add(item_id)

    for item_id in ids:
        visit(item_id)


def load_backlog(path: Path) -> BacklogProposal:
    """Load and validate a versioned JSON or JSON-compatible YAML manifest."""

    raw = path.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BacklogManifestError(f"Backlog manifest is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise BacklogManifestError("Backlog manifest root must be an object")
    schema_version = document.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise BacklogManifestError(
            f"Unsupported schema_version {schema_version!r}; expected one of "
            f"{sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )
    raw_items = document.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise BacklogManifestError("Backlog manifest must contain a non-empty items list")
    items = tuple(
        _item(value, index, schema_version=int(schema_version))
        for index, value in enumerate(raw_items)
    )
    _validate_graph(items)
    source = document.get("source", {})
    if source is None:
        source = {}
    if not isinstance(source, dict):
        raise BacklogManifestError("source must be an object when present")
    source_name = str(source.get("name") or path.stem).strip()
    known_root_fields = {
        "schema_version",
        "source_path",
        "source_sha256",
        "source_name",
        "source",
        "extension_schema",
        "planning_contract",
        "items",
    }
    return BacklogProposal(
        source_path=path.resolve().as_posix(),
        source_sha256=hashlib.sha256(raw).hexdigest(),
        source_name=source_name,
        items=items,
        schema_version=int(schema_version),
        source_metadata=dict(source),
        extension_schema=(
            str(document["extension_schema"]).strip()
            if document.get("extension_schema")
            else None
        ),
        planning_contract=(
            dict(document.get("planning_contract", {}))
            if isinstance(document.get("planning_contract", {}), dict)
            else {}
        ),
        extensions={
            key: value for key, value in document.items() if key not in known_root_fields
        },
    )


def _stable_id(issue: dict[str, Any]) -> str | None:
    if issue.get("stable_id"):
        return str(issue["stable_id"])
    match = MARKER_PATTERN.search(str(issue.get("body", "")))
    return match.group(1) if match else None


def _normalized_issue(issue: dict[str, Any]) -> dict[str, Any]:
    labels = issue.get("labels", [])
    labels = [
        label.get("name", "") if isinstance(label, dict) else str(label) for label in labels
    ]
    return {
        "title": str(issue.get("title", "")).strip(),
        "body": str(issue.get("body", "")).replace("\r\n", "\n").strip(),
        "labels": sorted(labels),
    }


def _key(action: str, stable_id: str, desired: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(desired, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    return f"backlog:{action}:{stable_id}:{digest}"


def diff_issues(
    proposal: BacklogProposal, existing: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Compare desired items to issues without executing any external command."""

    result: dict[str, list[dict[str, Any]]] = {
        name: [] for name in ("create", "update", "unchanged", "duplicate", "conflict")
    }
    by_id: dict[str, list[dict[str, Any]]] = {}
    by_title: dict[str, list[dict[str, Any]]] = {}
    for issue in existing:
        stable_id = _stable_id(issue)
        if stable_id:
            by_id.setdefault(stable_id, []).append(issue)
        by_title.setdefault(str(issue.get("title", "")).strip().casefold(), []).append(issue)
    for item in proposal.items:
        desired = item.issue()
        matches = by_id.get(item.stable_id, [])
        if len(matches) > 1:
            result["duplicate"].append(
                {
                    "stable_id": item.stable_id,
                    "issue_numbers": sorted(
                        issue.get("number") for issue in matches if issue.get("number") is not None
                    ),
                    "reason": "multiple issues claim one stable ID",
                }
            )
            continue
        if not matches:
            collisions = by_title.get(desired["title"].casefold(), [])
            if collisions:
                result["conflict"].append(
                    {
                        "stable_id": item.stable_id,
                        "issue_numbers": sorted(
                            issue.get("number")
                            for issue in collisions
                            if issue.get("number") is not None
                        ),
                        "reason": "title exists without the expected stable ID",
                    }
                )
            else:
                result["create"].append(
                    {
                        "stable_id": item.stable_id,
                        "desired": desired,
                        "idempotency_key": _key("create", item.stable_id, desired),
                    }
                )
            continue
        current = _normalized_issue(matches[0])
        normalized_desired = _normalized_issue(desired)
        entry = {
            "stable_id": item.stable_id,
            "issue_number": matches[0].get("number"),
            "idempotency_key": _key("update", item.stable_id, normalized_desired),
        }
        if current == normalized_desired:
            result["unchanged"].append(entry)
        else:
            result["update"].append(
                {**entry, "current": current, "desired": normalized_desired}
            )
    return result


def issue_operations(diff: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Convert an unambiguous diff into the mutation allowlist understood by GitHubClient."""

    if diff.get("duplicate") or diff.get("conflict"):
        raise BacklogManifestError("Resolve duplicate and conflicting issues before sync")
    operations: list[dict[str, Any]] = []
    for entry in diff.get("create", []):
        desired = entry["desired"]
        operations.append(
            {
                "action": "create_issue",
                "idempotency_key": entry["idempotency_key"],
                "title": desired["title"],
                "body": desired["body"],
                "labels": desired["labels"],
            }
        )
    for entry in diff.get("update", []):
        desired = entry["desired"]
        operations.append(
            {
                "action": "update_issue",
                "idempotency_key": entry["idempotency_key"],
                "number": entry["issue_number"],
                "title": desired["title"],
                "body": desired["body"],
                "add_labels": desired["labels"],
            }
        )
    return operations
