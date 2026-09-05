#!/usr/bin/env python3
"""Validate the active game-creator plan without providers or state mutations.

Run from any directory with Python 3.11+; installing AgentFactory is unnecessary.
Source references are repository-relative files, optionally followed by a fragment.
HTTP(S) URLs and document-local fragments are accepted without network access;
legacy: IDs must exist in a historical manifest. This checks planning consistency,
not implementation completion.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import fields
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "src"))

from agent_factory.backlog import (  # noqa: E402
    BacklogManifestError,
    BacklogProposal,
    ProposedItem,
    load_backlog,
    proposal_from_document,
)


PRIORITIES = frozenset({"P0", "P1", "P2"})
MILESTONES = frozenset({"m0", "m1", "m2", "m3"})
MILESTONE_RANK = {milestone: rank for rank, milestone in enumerate(sorted(MILESTONES))}
SIZES = frozenset({"s", "m", "l"})
TABLE_ID = re.compile(r"^\s*\|\s*`?(AF-GC-[A-Za-z0-9._:/-]+)`?\s*\|", re.MULTILINE)


def check_label(
    item: ProposedItem,
    prefix: str,
    allowed: frozenset[str],
    errors: list[str],
    *,
    required: bool = True,
) -> str | None:
    """Require one unambiguous, lowercase planning label when applicable."""
    matches = [label for label in item.labels if label.casefold().startswith(prefix)]
    if not required and not matches:
        return None
    if len(matches) != 1:
        errors.append(f"{item.stable_id}: expected exactly one {prefix} label; got {matches}")
        return None
    label = matches[0]
    value = label[len(prefix):]
    if label != label.lower() or value not in allowed:
        choices = ", ".join(f"{prefix}{value}" for value in sorted(allowed))
        errors.append(f"{item.stable_id}: invalid label {label!r}; choose {choices}")
        return None
    return value


def check_reference(
    stable_id: str, reference: str, legacy_ids: set[str], errors: list[str]
) -> None:
    if reference.startswith("#"):
        if len(reference) == 1:
            errors.append(f"{stable_id}: empty document fragment in source_references")
        return
    if reference.startswith("legacy:"):
        legacy_id = reference.removeprefix("legacy:")
        if legacy_id not in legacy_ids:
            errors.append(f"{stable_id}: unknown legacy source ID {legacy_id!r}")
        return
    try:
        parsed = urlsplit(reference)
    except ValueError as exc:
        errors.append(f"{stable_id}: invalid source reference {reference!r}: {exc}")
        return
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return
    if parsed.scheme or parsed.netloc or parsed.query:
        errors.append(f"{stable_id}: unsupported source reference {reference!r}")
        return
    source_path = (ROOT / unquote(parsed.path)).resolve()
    if not source_path.is_relative_to(ROOT):
        errors.append(f"{stable_id}: source reference escapes the repository: {reference!r}")
    elif not source_path.is_file():
        errors.append(f"{stable_id}: source file does not exist: {reference!r}")


def check_release_gates(
    proposal: BacklogProposal,
    by_id: dict[str, ProposedItem],
    milestones: dict[str, str | None],
    errors: list[str],
) -> None:
    gates = proposal.planning_contract.get("release_gates")
    if not isinstance(gates, dict) or not gates:
        errors.append("planning_contract.release_gates must be a non-empty object")
        return
    for milestone, stable_ids in gates.items():
        if milestone not in {value.upper() for value in MILESTONES}:
            errors.append(f"Release gate has an unsupported milestone: {milestone!r}")
            continue
        if (
            not isinstance(stable_ids, list)
            or not stable_ids
            or not all(isinstance(value, str) and value.strip() for value in stable_ids)
        ):
            errors.append(f"Release gate {milestone} must list non-empty executable IDs")
            continue
        if len(set(stable_ids)) != len(stable_ids):
            errors.append(f"Release gate {milestone} repeats an item ID")
        for stable_id in stable_ids:
            item = by_id.get(stable_id)
            if item is None or not item.executable:
                errors.append(f"Release gate {milestone}: {stable_id!r} is not an executable item")
            elif milestones[stable_id] != milestone.lower():
                errors.append(
                    f"Release gate {milestone}: {stable_id} belongs to "
                    f"{milestones[stable_id]!r}, not {milestone.lower()}"
                )


def check_roadmap_table(
    roadmap: str,
    by_id: dict[str, ProposedItem],
    milestones: dict[str, str | None],
    sizes: dict[str, str | None],
    errors: list[str],
) -> None:
    row_counts: Counter[str] = Counter()
    columns = ("ID", "priority", "milestone", "size", "title", "dependencies")
    for line_number, line in enumerate(roadmap.splitlines(), start=1):
        match = TABLE_ID.match(line)
        if match is None:
            continue
        stable_id = match.group(1)
        row_counts[stable_id] += 1
        if stable_id not in by_id:
            errors.append(f"Roadmap table line {line_number} contains unknown item {stable_id}")
            continue
        # An escaped pipe belongs to a title; unescaped pipes delimit table cells.
        parts = re.split(r"(?<!\\)\|", line.strip())
        if parts[-1].strip() or len(parts) != 8:
            errors.append(f"Roadmap table line {line_number}: {stable_id} must have six columns")
            continue
        cells = [value.strip().replace(r"\|", "|") for value in parts[1:-1]]
        cells[0] = cells[0].strip("`")
        item = by_id[stable_id]
        expected = [
            item.stable_id,
            item.priority,
            (milestones[stable_id] or "").upper(),
            (sizes[stable_id] or "").upper(),
            item.title,
        ]
        for column, actual, desired in zip(columns, cells[:5], expected):
            if actual != desired:
                errors.append(
                    f"Roadmap table line {line_number}: {stable_id} {column} is "
                    f"{actual!r}; manifest requires {desired!r}"
                )
        dependencies = (
            ()
            if cells[5] == "—"
            else tuple(value.strip().strip("`") for value in cells[5].split(","))
        )
        if dependencies != item.dependencies:
            errors.append(
                f"Roadmap table line {line_number}: {stable_id} dependencies are "
                f"{dependencies!r}; manifest requires {item.dependencies!r} "
                "(use an em dash for none)"
            )
    for stable_id, count in sorted(row_counts.items()):
        if count != 1:
            errors.append(f"Roadmap table repeats {stable_id} ({count} rows)")
    for item in by_id.values():
        if item.executable and item.stable_id not in row_counts:
            errors.append(f"Roadmap table has no row for executable item {item.stable_id}")


def validate(backlog_path: Path, roadmap_path: Path) -> tuple[BacklogProposal | None, list[str]]:
    errors: list[str] = []
    try:
        proposal = load_backlog(backlog_path)
        document = json.loads(backlog_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, BacklogManifestError, json.JSONDecodeError) as exc:
        return None, [f"Cannot load backlog {backlog_path}: {exc}"]

    if proposal.schema_version != 2:
        errors.append("The active game-creator backlog must use schema_version 2")

    # JSON normalization converts dataclass tuples into schema-compatible lists.
    exported = json.loads(json.dumps(proposal.to_dict(), ensure_ascii=False))
    try:
        reloaded = proposal_from_document(
            exported,
            source_path=proposal.source_path,
            source_sha256=proposal.source_sha256,
            source_name=proposal.source_name,
        )
        if reloaded.to_dict() != proposal.to_dict():
            errors.append("Canonical JSON round-trip changed the proposal")
    except (BacklogManifestError, TypeError, ValueError) as exc:
        errors.append(f"Canonical JSON round-trip failed: {exc}")

    known_fields = {field.name for field in fields(ProposedItem)}
    for raw_item in document["items"]:
        unknown = sorted(set(raw_item) - known_fields)
        if unknown:
            errors.append(
                f"{raw_item['stable_id']}: item fields would be discarded by import: {unknown}; "
                "use supported fields, labels, or root-level metadata"
            )

    legacy_ids: set[str] = set()
    for filename in ("development-backlog.json", "autonomous-mission-backlog.json"):
        try:
            legacy = load_backlog(ROOT / "examples" / filename)
            legacy_ids.update(item.stable_id for item in legacy.items)
        except (OSError, UnicodeError, BacklogManifestError) as exc:
            errors.append(f"Cannot load legacy manifest {filename}: {exc}")

    by_id = {item.stable_id: item for item in proposal.items}
    milestones: dict[str, str | None] = {}
    sizes: dict[str, str | None] = {}
    for item in proposal.items:
        if item.priority not in PRIORITIES:
            errors.append(f"{item.stable_id}: priority must be P0, P1, or P2")
        priority_label = check_label(
            item, "priority:", frozenset(value.lower() for value in PRIORITIES), errors
        )
        if priority_label is not None and priority_label.upper() != item.priority:
            errors.append(f"{item.stable_id}: priority field and label disagree")
        milestones[item.stable_id] = check_label(
            item, "milestone:", MILESTONES, errors, required=item.executable
        )
        sizes[item.stable_id] = check_label(
            item, "size:", SIZES, errors, required=item.executable
        )
        check_label(
            item, "status:", frozenset({"proposed"}), errors, required=item.executable
        )
        if item.executable:
            for dependency in item.dependencies:
                if not by_id[dependency].executable:
                    errors.append(
                        f"{item.stable_id}: dependency {dependency} is a container; "
                        "runtime readiness only waits for executable dependencies"
                    )
        for reference in item.source_references:
            check_reference(item.stable_id, reference, legacy_ids, errors)

    for item in proposal.items:
        item_milestone = milestones[item.stable_id]
        for dependency in item.dependencies:
            dependency_milestone = milestones[dependency]
            if (
                item_milestone is not None
                and dependency_milestone is not None
                and MILESTONE_RANK[dependency_milestone] > MILESTONE_RANK[item_milestone]
            ):
                errors.append(
                    f"{item.stable_id} ({item_milestone}) depends on later-milestone "
                    f"prerequisite {dependency} ({dependency_milestone})"
                )
    check_release_gates(proposal, by_id, milestones, errors)

    try:
        roadmap = roadmap_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        errors.append(f"Cannot read roadmap {roadmap_path}: {exc}")
    else:
        check_roadmap_table(roadmap, by_id, milestones, sizes, errors)

    return proposal, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backlog", type=Path, default=ROOT / "examples" / "game-creator-backlog.json"
    )
    parser.add_argument(
        "--roadmap", type=Path, default=ROOT / "docs" / "game-creator-backlog.uk.md"
    )
    args = parser.parse_args()
    proposal, errors = validate(args.backlog, args.roadmap)
    if errors:
        print(f"Game-creator backlog validation failed ({len(errors)} errors):", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    assert proposal is not None
    executable = [item for item in proposal.items if item.executable]
    kind_counts = Counter(item.kind for item in proposal.items)
    print("Game-creator backlog is valid (schema v2, round-trip, labels, references, "
          "DAG, milestone order, release gates, six-column roadmap agreement).")
    print(f"Items: {len(proposal.items)}; executable: {len(executable)}; kinds: {dict(sorted(kind_counts.items()))}")
    for prefix in ("priority:", "milestone:", "size:"):
        counts = Counter(
            label.removeprefix(prefix)
            for item in executable
            for label in item.labels
            if label.startswith(prefix)
        )
        print(f"Executable {prefix.removesuffix(':')} counts: {dict(sorted(counts.items()))}")
    roots = sorted(item.stable_id for item in executable if not item.dependencies)
    print("Dependency-ready roots (planning only): " + (", ".join(roots) or "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
