#!/usr/bin/env python3
"""Validate active backlog structure and readable Lokiravia alignment.

Uses only local files and the Python standard library. It does not require Git,
credentials, a clean checkout or a task claim, and writes no validation cache.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


ACTIVE_BACKLOGS = (
    "examples/game-creator-backlog.json",
    "examples/agentfactory-cloud-backlog.json",
)


ACCEPTED_STATUS_LABELS = frozenset({"status:accepted", "status:done", "status:delivered"})
EVIDENCE_KINDS = frozenset({"code", "test", "document", "run", "review", "deployment"})
EVIDENCE_FIELDS = frozenset({"kind", "reference", "recorded_by", "note"})


class ValidationError(ValueError):
    """An active backlog or its readable representation is inconsistent."""


def validate_evidence(stable_id: str, item: dict) -> int:
    """A manifest may record evidence; it may not claim acceptance without it."""

    entries = item.get("evidence", [])
    if not isinstance(entries, list):
        raise ValidationError(f"{stable_id}: evidence must be a list")
    for position, entry in enumerate(entries):
        where = f"{stable_id}: evidence entry {position}"
        if not isinstance(entry, dict) or set(entry) - EVIDENCE_FIELDS:
            raise ValidationError(f"{where} must be an object with supported fields only")
        if str(entry.get("kind", "")).strip().lower() not in EVIDENCE_KINDS:
            raise ValidationError(f"{where} needs a kind from {sorted(EVIDENCE_KINDS)}")
        if not str(entry.get("reference", "")).strip():
            raise ValidationError(f"{where} needs a reference")
        if not str(entry.get("recorded_by", "")).strip():
            raise ValidationError(f"{where} must name who recorded it")
    labels = {str(value).strip().lower() for value in item.get("labels", [])}
    if labels & ACCEPTED_STATUS_LABELS and not entries:
        raise ValidationError(
            f"{stable_id}: marked accepted without evidence; record what was produced "
            "or leave the status as proposed"
        )
    return len(entries)


def validate_backlog(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("schema_version") != 2:
        raise ValidationError(f"{path.name}: active backlog must use schema v2")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValidationError(f"{path.name}: items must be a nonempty list")
    by_id: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValidationError(f"{path.name}: each item must be an object")
        stable_id = item.get("stable_id")
        if not isinstance(stable_id, str) or not stable_id.strip() or stable_id in by_id:
            raise ValidationError(f"{path.name}: missing or duplicate stable_id {stable_id!r}")
        by_id[stable_id] = item
    for stable_id, item in by_id.items():
        validate_evidence(stable_id, item)
        parent = item.get("parent_id")
        if parent is not None and (not isinstance(parent, str) or parent not in by_id or parent == stable_id):
            raise ValidationError(f"{stable_id}: invalid parent reference")
        dependencies = item.get("dependencies", [])
        if (not isinstance(dependencies, list)
                or not all(isinstance(d, str) and d in by_id for d in dependencies)
                or len(set(dependencies)) != len(dependencies)):
            raise ValidationError(f"{stable_id}: invalid or duplicate dependencies")
    for relationship in ("dependencies", "parent_id"):
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(stable_id: str) -> None:
            if stable_id in visiting:
                raise ValidationError(f"{path.name}: {relationship} cycle at {stable_id}")
            if stable_id in visited:
                return
            visiting.add(stable_id)
            values = by_id[stable_id].get(relationship)
            for target in ([values] if relationship == "parent_id" and values else values or []):
                visit(target)
            visiting.remove(stable_id)
            visited.add(stable_id)

        for stable_id in by_id:
            visit(stable_id)
    contract = data.get("planning_contract", {})
    if not isinstance(contract, dict):
        raise ValidationError(f"{path.name}: planning_contract must be an object")
    gates = contract.get("release_gates", {})
    if not isinstance(gates, dict):
        raise ValidationError(f"{path.name}: release_gates must be an object")
    for stage, values in gates.items():
        if (not isinstance(values, list) or not values
                or not all(isinstance(value, str) and value in by_id for value in values)):
            raise ValidationError(f"{path.name}: invalid release gate {stage}")
    return by_id


def validate_cloud_alignment(root: Path, by_id: dict[str, dict]) -> None:
    path = root / "docs/backlog.md"
    if not path.is_file():
        raise ValidationError("Cloud backlog is missing its readable docs/backlog.md")
    text = path.read_text(encoding="utf-8-sig")
    tasks = {key: value for key, value in by_id.items() if value.get("kind") != "epic"}
    rows: dict[str, list[str]] = {}
    for line in text.splitlines():
        match = re.match(r"^\|\s*\[(AF-CLD-[0-9]+)\]\([^)]*\)\s*\|", line)
        if match:
            if match[1] in rows:
                raise ValidationError(f"Duplicate Cloud index row: {match[1]}")
            rows[match[1]] = [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", line)[1:-1]]
    if set(rows) != set(tasks):
        raise ValidationError("Cloud readable task index IDs differ from JSON")
    for stable_id, item in tasks.items():
        row = rows[stable_id]
        labels = item.get("labels", [])
        label = lambda prefix: next((v.split(":", 1)[1].upper() for v in labels if v.startswith(prefix + ":")), "")
        title = item["title"] + (" (optional)" if "track:optional" in labels else "")
        expected = [title, label("milestone"), item.get("priority", ""),
                    label("size"), item.get("assigned_role", ""),
                    ", ".join(d.removeprefix("AF-CLD-") for d in item.get("dependencies", [])) or "None"]
        if row[1:] != expected:
            raise ValidationError(f"Cloud readable index differs from JSON: {stable_id}")
        heading = re.search(r"^###\s+" + re.escape(stable_id) + r"\b[^\n]*", text, re.MULTILINE)
        if not heading:
            raise ValidationError(f"Missing Cloud task detail: {stable_id}")
        end = re.search(r"^###\s+AF-CLD-", text[heading.end():], re.MULTILINE)
        section = text[heading.end():heading.end() + end.start()] if end else text[heading.end():]
        for criterion in item.get("acceptance_criteria", []):
            if criterion not in section:
                raise ValidationError(f"Cloud readable acceptance differs from JSON: {stable_id}")


def validate_repository(root: Path) -> list[tuple[str, int, int]]:
    results = []
    for name in ACTIVE_BACKLOGS:
        path = root / name
        if not path.is_file():
            continue
        items = validate_backlog(path)
        if name.endswith("agentfactory-cloud-backlog.json"):
            validate_cloud_alignment(root, items)
        recorded = sum(len(item.get("evidence", [])) for item in items.values())
        results.append((name, len(items), recorded))
    if not results:
        raise ValidationError("No supported active backlog found in examples/")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1],
        help="Repository directory (default: this script's repository)",
    )
    args = parser.parse_args(argv)
    try:
        results = validate_repository(args.root)
        for name, count, recorded in results:
            print(f"Valid: {name} ({count} items, {recorded} evidence entries)")
        return 0
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        print(f"Backlog validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
