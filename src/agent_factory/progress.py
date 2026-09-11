"""Development progress reporting for the operator progress page.

Merged code and accepted work are separate facts. Every task carries both
tracks side by side. This module never derives acceptance from a merge, a
document, a passing simulation, or the existence of a source file: acceptance
is only what the backlog manifest declares. A percentage published here
describes coverage of a planning baseline, not a delivered product.

Repository content and command output are untrusted input. Commit subjects are
truncated, commit identifiers are checked against a hexadecimal pattern, and
the scan is bounded so that a large or hostile history cannot exhaust the
controller.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .backlog import BacklogManifestError, ProposedItem, proposal_from_document

MAX_COMMITS = 20000
MAX_SUBJECT = 160
MAX_EVIDENCE_COMMITS = 10
MANIFEST_BYTE_LIMIT = 4 * 1024 * 1024
GIT_TIMEOUT_SECONDS = 120

SIZE_WEIGHTS = {"s": 2, "m": 5, "l": 10}
DEFAULT_WEIGHT = 5

ACCEPTED_LABELS = frozenset({"status:accepted", "status:done", "status:delivered"})
IN_PROGRESS_LABELS = frozenset(
    {"status:in_progress", "status:in-progress", "status:started"}
)
BLOCKED_LABELS = frozenset({"status:blocked"})

STATES = ("accepted", "merged", "in_progress", "blocked", "todo")
UNGROUPED = "ungrouped"

_SHA_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")
_RECORD_SEPARATOR = "\x1e"
_FIELD_SEPARATOR = "\x1f"


class ProgressError(RuntimeError):
    """Raised when a progress source cannot be read or is inconsistent."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class CommitRecord:
    """One commit observed in a repository's own history."""

    sha: str
    subject: str

    def __post_init__(self) -> None:
        if not _SHA_PATTERN.fullmatch(self.sha):
            raise ProgressError(f"Commit identifier is not hexadecimal: {self.sha!r}")


@dataclass(frozen=True)
class TaskProgress:
    stable_id: str
    title: str
    kind: str
    priority: str
    size: str
    weight: int
    role: str
    accepted: bool
    merged: bool
    state: str
    dependencies: tuple[str, ...]
    blocked_by: tuple[str, ...]
    commits: tuple[CommitRecord, ...]
    manifest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.stable_id,
            "title": self.title,
            "kind": self.kind,
            "priority": self.priority,
            "size": self.size,
            "weight": self.weight,
            "role": self.role,
            "accepted": self.accepted,
            "merged": self.merged,
            "state": self.state,
            "dependencies": list(self.dependencies),
            "blocked_by": list(self.blocked_by),
            "manifest": self.manifest,
            "commits": [
                {"sha": commit.sha, "subject": commit.subject}
                for commit in self.commits[:MAX_EVIDENCE_COMMITS]
            ],
            "commit_count": len(self.commits),
        }


def _counts(tasks: Sequence[TaskProgress]) -> dict[str, Any]:
    weight = sum(task.weight for task in tasks) or 0
    accepted_weight = sum(task.weight for task in tasks if task.accepted)
    merged_weight = sum(task.weight for task in tasks if task.merged)
    by_state = {state: 0 for state in STATES}
    for task in tasks:
        by_state[task.state] += 1
    return {
        "tasks": len(tasks),
        "weight": weight,
        "accepted": sum(1 for task in tasks if task.accepted),
        "merged": sum(1 for task in tasks if task.merged),
        "remaining": sum(1 for task in tasks if not task.merged),
        "by_state": by_state,
        "percent": {
            "accepted": _percent(accepted_weight, weight),
            "merged": _percent(merged_weight, weight),
            "accepted_by_count": _percent(
                sum(1 for task in tasks if task.accepted), len(tasks)
            ),
            "merged_by_count": _percent(
                sum(1 for task in tasks if task.merged), len(tasks)
            ),
        },
    }


def _percent(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round(100.0 * part / whole, 1)


@dataclass(frozen=True)
class BlockProgress:
    """A large planning block: a milestone, an epic, or a release group."""

    key: str
    title: str
    kind: str
    track: str
    tasks: tuple[TaskProgress, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "kind": self.kind,
            "track": self.track,
            **_counts(self.tasks),
            "items": [task.to_dict() for task in self.tasks],
        }


@dataclass(frozen=True)
class ProjectProgress:
    project_id: str
    name: str
    repository: str
    revision: str
    blocks: tuple[BlockProgress, ...]
    manifests: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def tasks(self) -> tuple[TaskProgress, ...]:
        return tuple(task for block in self.blocks for task in block.tasks)

    def to_dict(self) -> dict[str, Any]:
        tasks = self.tasks
        ready = [
            task.stable_id
            for task in tasks
            if task.state == "todo" and not task.blocked_by
        ]
        return {
            "id": self.project_id,
            "name": self.name,
            "repository": self.repository,
            "revision": self.revision,
            **_counts(tasks),
            "ready": ready[:20],
            "ready_count": len(ready),
            "blocks": [block.to_dict() for block in self.blocks],
            "manifests": list(self.manifests),
            "warnings": list(self.warnings),
        }


def _label_value(item: ProposedItem, namespace: str) -> str | None:
    prefix = namespace + ":"
    for label in item.labels:
        lowered = label.strip().lower()
        if lowered.startswith(prefix):
            value = lowered[len(prefix) :].strip()
            if value:
                return value
    return None


def _weight(item: ProposedItem) -> tuple[str, int]:
    size = _label_value(item, "size") or ""
    return size.upper(), SIZE_WEIGHTS.get(size, DEFAULT_WEIGHT)


def _declared_state(item: ProposedItem) -> str | None:
    labels = {label.strip().lower() for label in item.labels}
    if labels & ACCEPTED_LABELS:
        return "accepted"
    if labels & IN_PROGRESS_LABELS:
        return "in_progress"
    if labels & BLOCKED_LABELS:
        return "blocked"
    return None


def _root_ancestor(
    item: ProposedItem, parents: Mapping[str, ProposedItem]
) -> ProposedItem | None:
    """Walk to the topmost planning ancestor, so a block stays a large block.

    A manifest may nest task under story under epic. Grouping by the immediate
    parent would publish many small groups that no one plans against.
    """

    seen: set[str] = set()
    current = parents.get(item.parent_id or "")
    root = current
    while current is not None and current.stable_id not in seen:
        seen.add(current.stable_id)
        root = current
        current = parents.get(current.parent_id or "")
    return root


def _block_of(
    item: ProposedItem, parents: Mapping[str, ProposedItem], track: str
) -> tuple[str, str, str]:
    """Choose the large block an executable item belongs to.

    A declared milestone wins, then the topmost epic, then a release label. The
    key carries its track so that one manifest's M0 is never merged into
    another manifest's M0.
    """

    milestone = _label_value(item, "milestone")
    if milestone:
        return f"{track}/milestone:{milestone}", milestone.upper(), "milestone"
    root = _root_ancestor(item, parents)
    if root is not None:
        return f"{track}/epic:{root.stable_id}", root.title, "epic"
    release = _label_value(item, "release")
    if release:
        return f"{track}/release:{release}", release.upper(), "release"
    return f"{track}/{UNGROUPED}", "Unassigned", "unassigned"


def commit_index(
    commits: Iterable[CommitRecord], stable_ids: Iterable[str]
) -> dict[str, tuple[CommitRecord, ...]]:
    """Map each stable id to the commits whose subject references it.

    Matching requires a full-token match so that ``AF-CLD-001`` is never
    credited with work described by ``AF-CLD-0012``.
    """

    known = {stable_id for stable_id in stable_ids if stable_id}
    if not known:
        return {}
    pattern = re.compile(
        r"(?<![A-Za-z0-9_-])(" + "|".join(sorted(map(re.escape, known), key=len, reverse=True)) + r")(?![A-Za-z0-9_-])"
    )
    found: dict[str, list[CommitRecord]] = {}
    for index, commit in enumerate(commits):
        if index >= MAX_COMMITS:
            break
        for stable_id in dict.fromkeys(pattern.findall(commit.subject)):
            found.setdefault(stable_id, []).append(commit)
    return {stable_id: tuple(records) for stable_id, records in found.items()}


def build_project(
    *,
    project_id: str,
    name: str,
    repository: str,
    revision: str,
    manifests: Sequence[tuple[str, dict[str, Any], str]],
    commits: Sequence[CommitRecord] = (),
    warnings: Sequence[str] = (),
) -> ProjectProgress:
    """Build one project's report from loaded manifests and observed commits.

    ``manifests`` holds ``(path, document, sha256)`` triples so that callers can
    read a manifest from a working tree or from a bare repository ref without
    this module choosing a transport.
    """

    items: list[tuple[ProposedItem, str, str]] = []
    parents: dict[str, ProposedItem] = {}
    descriptors: list[dict[str, Any]] = []
    problems = list(warnings)
    for path, document, digest in manifests:
        try:
            proposal = proposal_from_document(
                document,
                source_path=path,
                source_sha256=digest,
                source_name=Path(path).stem,
            )
        except BacklogManifestError as error:
            problems.append(f"{path}: {error}")
            continue
        executable = [item for item in proposal.items if item.executable]
        descriptors.append(
            {
                "path": path,
                "name": proposal.source_name,
                "sha256": digest,
                "schema_version": proposal.schema_version,
                "items": len(executable),
            }
        )
        for item in proposal.items:
            if item.executable:
                items.append((item, path, proposal.source_name))
            else:
                parents.setdefault(item.stable_id, item)

    known_ids = {item.stable_id for item, _, _ in items}
    index = commit_index(commits, known_ids)
    accepted_ids = {
        item.stable_id for item, _, _ in items if _declared_state(item) == "accepted"
    }
    merged_ids = {stable_id for stable_id in index if stable_id in known_ids}

    grouped: dict[str, list[TaskProgress]] = {}
    titles: dict[str, tuple[str, str, str]] = {}
    for item, path, track in items:
        size, weight = _weight(item)
        declared = _declared_state(item)
        accepted = declared == "accepted"
        records = index.get(item.stable_id, ())
        merged = bool(records)
        dependencies = tuple(item.dependencies)
        blocked_by = tuple(
            dependency
            for dependency in dependencies
            if dependency in known_ids
            and dependency not in accepted_ids
            and dependency not in merged_ids
        )
        if accepted:
            state = "accepted"
        elif merged:
            state = "merged"
        elif declared == "in_progress":
            state = "in_progress"
        elif declared == "blocked" or blocked_by:
            state = "blocked"
        else:
            state = "todo"
        key, block_title, block_kind = _block_of(item, parents, track)
        titles.setdefault(key, (block_title, block_kind, track))
        grouped.setdefault(key, []).append(
            TaskProgress(
                stable_id=item.stable_id,
                title=item.title,
                kind=item.kind,
                priority=(item.priority or "P2").upper(),
                size=size,
                weight=weight,
                role=item.assigned_role,
                accepted=accepted,
                merged=merged,
                state=state,
                dependencies=dependencies,
                blocked_by=blocked_by,
                commits=records,
                manifest=path,
            )
        )

    blocks = tuple(
        BlockProgress(
            key=key,
            title=titles[key][0],
            kind=titles[key][1],
            track=titles[key][2],
            tasks=tuple(sorted(tasks, key=lambda task: task.stable_id)),
        )
        for key, tasks in sorted(grouped.items(), key=lambda entry: entry[0])
    )
    if not items:
        problems.append("No executable backlog items were loaded for this project")
    return ProjectProgress(
        project_id=project_id,
        name=name,
        repository=repository,
        revision=revision,
        blocks=blocks,
        manifests=tuple(descriptors),
        warnings=tuple(problems),
    )


def report(projects: Sequence[ProjectProgress]) -> dict[str, Any]:
    """Build the published document. Both tracks stay separate at every level."""

    documents = [project.to_dict() for project in projects]
    every_task = [task for project in projects for task in project.tasks]
    return {
        "generated_at": _now(),
        "evidence_note": (
            "A merged commit records engineering delivery only. Acceptance is "
            "declared by the backlog manifest and its release gate, and is never "
            "inferred from a merge."
        ),
        "totals": _counts(every_task),
        "projects": documents,
    }


def read_commits(
    repo: Path,
    ref: str = "HEAD",
    *,
    limit: int = MAX_COMMITS,
    runner: Any = subprocess,
) -> tuple[CommitRecord, ...]:
    """Read bounded commit subjects from a repository, bare or with a worktree."""

    output = _git(
        repo,
        [
            "log",
            f"--max-count={max(1, int(limit))}",
            f"--format=%H{_FIELD_SEPARATOR}%s{_RECORD_SEPARATOR}",
            ref,
        ],
        runner=runner,
    )
    records: list[CommitRecord] = []
    for chunk in output.split(_RECORD_SEPARATOR):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        sha, _, subject = chunk.partition(_FIELD_SEPARATOR)
        sha = sha.strip()
        if not _SHA_PATTERN.fullmatch(sha):
            continue
        records.append(CommitRecord(sha=sha, subject=subject.strip()[:MAX_SUBJECT]))
    return tuple(records)


def read_manifest(
    repo: Path, ref: str, path: str, *, runner: Any = subprocess
) -> tuple[dict[str, Any], str]:
    """Read one manifest blob from a ref. Works against a bare repository."""

    raw = _git(repo, ["show", f"{ref}:{path}"], runner=runner, binary=True)
    if len(raw) > MANIFEST_BYTE_LIMIT:
        raise ProgressError(f"Manifest {path!r} is larger than the supported limit")
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProgressError(f"Manifest {path!r} is not valid UTF-8 JSON: {error}") from error
    return document, hashlib.sha256(raw).hexdigest()


def read_manifest_file(path: Path) -> tuple[dict[str, Any], str]:
    """Read one manifest from a working tree."""

    raw = path.read_bytes()
    if len(raw) > MANIFEST_BYTE_LIMIT:
        raise ProgressError(f"Manifest {str(path)!r} is larger than the supported limit")
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProgressError(f"Manifest {str(path)!r} is not valid UTF-8 JSON: {error}") from error
    return document, hashlib.sha256(raw).hexdigest()


def revision(repo: Path, ref: str = "HEAD", *, runner: Any = subprocess) -> str:
    value = _git(repo, ["rev-parse", ref], runner=runner).strip()
    if not re.fullmatch("[0-9a-f]{40}", value):
        raise ProgressError("Repository did not return a resolved revision")
    return value


def _git(repo: Path, arguments: Sequence[str], *, runner: Any, binary: bool = False) -> Any:
    completed = runner.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        timeout=GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", "replace")
        raise ProgressError(
            f"git {' '.join(arguments[:2])} failed: {(detail or '').strip()[:200]}"
        )
    output = completed.stdout
    if binary:
        return output if isinstance(output, bytes) else str(output).encode()
    if isinstance(output, bytes):
        return output.decode("utf-8", "replace")
    return str(output)
