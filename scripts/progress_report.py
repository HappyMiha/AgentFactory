#!/usr/bin/env python3
"""Publish the development progress document read by the /progress page.

Every task carries evidence, commit-reference and acceptance tracks. ``merged``
means an ID was mentioned in history; ``accepted`` is declared by the manifest. A
merge never sets acceptance here, and this script neither writes to a
repository nor contacts an external service.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_factory.progress import (  # noqa: E402
    ProgressError,
    build_project,
    read_commits,
    read_manifest,
    report,
    revision,
)

APPROVED_REPOSITORIES = frozenset({"HappyMiha/Lokvetia-Core", "HappyMiha/Lokiravia"})


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def collect(entry: dict) -> object:
    project_id = str(entry.get("id", "")).strip()
    repository = str(entry.get("repository", "")).strip()
    if not project_id or repository not in APPROVED_REPOSITORIES:
        raise ProgressError(f"Unapproved or incomplete project entry: {entry!r}")
    repo = Path(str(entry["repo_path"])).resolve()
    ref = str(entry.get("ref") or "refs/heads/main")
    warnings: list[str] = []
    documents = []
    for relative in entry.get("manifests", []):
        try:
            document, digest = read_manifest(repo, ref, str(relative))
        except ProgressError as error:
            warnings.append(str(error))
            continue
        documents.append((str(relative), document, digest))
    result = build_project(
        project_id=project_id,
        name=str(entry.get("name") or project_id),
        repository=repository,
        revision=revision(repo, ref),
        manifests=documents,
        commits=read_commits(repo, ref),
        warnings=warnings,
    )
    if result.warnings:
        raise ProgressError("; ".join(result.warnings))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--print", action="store_true", dest="echo")
    arguments = parser.parse_args()

    config = json.loads(arguments.config.read_text(encoding="utf-8-sig"))
    projects = []
    failures = []
    for entry in config.get("projects", []):
        try:
            projects.append(collect(entry))
        except (ProgressError, KeyError, OSError) as error:
            failures.append(f"{entry.get('id', '?')}: {error}")
    if failures or not projects:
        print("Progress refresh failed: " + ("; ".join(failures) or "empty configuration"),
              file=sys.stderr)
        return 1

    document = report(projects)
    if failures:
        document["errors"] = failures
    if arguments.output:
        atomic_json(arguments.output, document)
    if arguments.echo or not arguments.output:
        json.dump(document, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    for failure in failures:
        print("warning: " + failure, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
