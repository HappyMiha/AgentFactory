#!/usr/bin/env python3
"""Local, exact-commit checks for cooperative development; not a CI approval.

Run from a clean committed worktree. --base defaults to origin/main, which the
caller must fetch separately. --test test_example may be repeated for explicit
repository-local unittest modules. --verify only reads the stored attestation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tokenize


SCHEMA_VERSION = 1
ACTIVE_BACKLOGS = (
    "examples/game-creator-backlog.json",
    "examples/agentfactory-cloud-backlog.json",
)


class CheckError(RuntimeError):
    """A failed, unavailable or stale local check."""


def command(root: Path, argv: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, cwd=root, env=env, text=True, encoding="utf-8",
                              errors="replace", capture_output=True, shell=False,
                              timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CheckError(f"Cannot finish {argv!r}: {exc}") from exc


def git(root: Path, *args: str, raw: bool = False) -> str:
    result = command(root, ["git", *args])
    if result.returncode:
        raise CheckError(result.stderr.strip() or f"Git failed: {args!r}")
    return result.stdout if raw else result.stdout.strip()


def repository(path: Path) -> Path:
    return Path(git(path.resolve(), "rev-parse", "--show-toplevel")).resolve()


def attestation_path(root: Path) -> Path:
    path = Path(git(root, "rev-parse", "--git-path", "team-checks.json"))
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def snapshot(root: Path, base: str) -> dict:
    if not base or base.startswith("-") or any(c in base for c in "\r\n\x00"):
        raise CheckError("Invalid base ref")
    if git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all"):
        raise CheckError("Worktree must be clean, including non-ignored untracked files")
    head = git(root, "rev-parse", "--verify", "HEAD^{commit}")
    base_sha = git(root, "rev-parse", "--verify", "--end-of-options", base + "^{commit}")
    merge_base = git(root, "merge-base", head, base_sha)
    paths = git(root, "diff", "--name-only", "-z", "--no-renames", merge_base, head, "--", raw=True)
    return {
        "head": head,
        "tree": git(root, "rev-parse", "HEAD^{tree}"),
        "base_ref": base,
        "base_sha": base_sha,
        "merge_base": merge_base,
        "diff_range": [merge_base, head],
        "changed_paths": sorted(p for p in paths.split("\x00") if p),
        "checker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def validate_backlog(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("schema_version") != 2:
        raise CheckError(f"{path.name}: active backlog must use schema v2")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise CheckError(f"{path.name}: items must be a nonempty list")
    by_id: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            raise CheckError(f"{path.name}: each item must be an object")
        stable_id = item.get("stable_id")
        if not isinstance(stable_id, str) or not stable_id.strip() or stable_id in by_id:
            raise CheckError(f"{path.name}: missing or duplicate stable_id {stable_id!r}")
        by_id[stable_id] = item
    for stable_id, item in by_id.items():
        parent = item.get("parent_id")
        if parent is not None and (not isinstance(parent, str) or parent not in by_id or parent == stable_id):
            raise CheckError(f"{stable_id}: invalid parent reference")
        dependencies = item.get("dependencies", [])
        if (not isinstance(dependencies, list)
                or not all(isinstance(d, str) and d in by_id for d in dependencies)
                or len(set(dependencies)) != len(dependencies)):
            raise CheckError(f"{stable_id}: invalid or duplicate dependencies")
    for relationship in ("dependencies", "parent_id"):
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(stable_id: str) -> None:
            if stable_id in visiting:
                raise CheckError(f"{path.name}: {relationship} cycle at {stable_id}")
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
        raise CheckError(f"{path.name}: planning_contract must be an object")
    gates = contract.get("release_gates", {})
    if not isinstance(gates, dict):
        raise CheckError(f"{path.name}: release_gates must be an object")
    for stage, values in gates.items():
        if (not isinstance(values, list) or not values
                or not all(isinstance(value, str) and value in by_id for value in values)):
            raise CheckError(f"{path.name}: invalid release gate {stage}")
    return by_id


def validate_cloud_alignment(root: Path, by_id: dict[str, dict]) -> None:
    path = root / "docs/backlog.md"
    if not path.is_file():
        raise CheckError("Cloud backlog is missing its readable docs/backlog.md")
    text = path.read_text(encoding="utf-8-sig")
    tasks = {key: value for key, value in by_id.items() if value.get("kind") != "epic"}
    rows: dict[str, list[str]] = {}
    for line in text.splitlines():
        match = re.match(r"^\|\s*\[(AF-CLD-[0-9]+)\]\([^)]*\)\s*\|", line)
        if match:
            if match[1] in rows:
                raise CheckError(f"Duplicate Cloud index row: {match[1]}")
            rows[match[1]] = [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", line)[1:-1]]
    if set(rows) != set(tasks):
        raise CheckError("Cloud readable task index IDs differ from JSON")
    for stable_id, item in tasks.items():
        row = rows[stable_id]
        labels = item.get("labels", [])
        label = lambda prefix: next((v.split(":", 1)[1].upper() for v in labels if v.startswith(prefix + ":")), "")
        title = item["title"] + (" (optional)" if "track:optional" in labels else "")
        expected = [title, label("milestone"), item.get("priority", ""),
                    label("size"), item.get("assigned_role", ""),
                    ", ".join(d.removeprefix("AF-CLD-") for d in item.get("dependencies", [])) or "None"]
        if row[1:] != expected:
            raise CheckError(f"Cloud readable index differs from JSON: {stable_id}")
        heading = re.search(r"^###\s+" + re.escape(stable_id) + r"\b[^\n]*", text, re.MULTILINE)
        if not heading:
            raise CheckError(f"Missing Cloud task detail: {stable_id}")
        end = re.search(r"^###\s+AF-CLD-", text[heading.end():], re.MULTILINE)
        section = text[heading.end():heading.end() + end.start()] if end else text[heading.end():]
        for criterion in item.get("acceptance_criteria", []):
            if criterion not in section:
                raise CheckError(f"Cloud readable acceptance differs from JSON: {stable_id}")


def profile_for(paths: list[str], selected: list[str]) -> str:
    if selected:
        return "selected-unittest-modules"
    runtime = any(p.startswith("src/") or (p.startswith("tests/") and not Path(p).name.startswith("test_team"))
                  or p in {"pyproject.toml", "setup.py", "setup.cfg"}
                  or Path(p).name.startswith("requirements") for p in paths)
    if runtime:
        return "full-unittest-discovery"
    if any(Path(p).name.startswith("test_team") or p in {"scripts/team.py", "scripts/team_checks.py"} for p in paths):
        return "coordination-unittest-discovery"
    return "planning-and-static"


def test_command(root: Path, profile: str, selected: list[str]) -> list[str] | None:
    if selected:
        modules = []
        for value in selected:
            module = value.removeprefix("tests.")
            if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", module):
                raise CheckError(f"Invalid unittest module: {value!r}")
            if not (root / "tests" / (module.replace(".", "/") + ".py")).is_file():
                raise CheckError(f"Selected module is not in this repository's tests: {value}")
            modules.append(module)
        return [sys.executable, "-m", "unittest", *modules, "-v"]
    if profile == "full-unittest-discovery":
        return [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    if profile == "coordination-unittest-discovery":
        return [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_team*.py", "-v"]
    return None


def run_checks(root: Path, base: str = "origin/main", selected: list[str] | None = None) -> dict:
    selected = list(selected or [])
    path = attestation_path(root)
    path.unlink(missing_ok=True)  # A failed rerun must invalidate earlier success.
    before = snapshot(root, base)
    results: list[dict] = []
    profile = profile_for(before["changed_paths"], selected)
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join([str(root / "tests"), str(root / "src"), env.get("PYTHONPATH", "")])

    def execute(argv: list[str], *, unittest: bool = False) -> None:
        result = command(root, argv, env=env)
        record = {"command": argv, "returncode": result.returncode,
                  "stdout": result.stdout[-32000:], "stderr": result.stderr[-32000:]}
        results.append(record)
        count = re.search(r"Ran (\d+) tests? in", result.stderr + result.stdout) if unittest else None
        # Python 3.12+ exits with 5 for an empty suite; 3.11 exits with 0.
        # Both must produce the same actionable failure, never an attestation.
        if count and int(count[1]) == 0 and result.returncode in {0, 5}:
            raise CheckError("Unittest ran no tests; this is not a passing test profile")
        if result.returncode:
            raise CheckError(f"Check failed: {argv!r}\n{result.stdout}\n{result.stderr}")
        if unittest:
            if not count or int(count[1]) == 0:
                raise CheckError("Unittest ran no tests; this is not a passing test profile")
            record["tests_run"] = int(count[1])
            skipped = re.search(r"skipped=(\d+)", result.stderr + result.stdout)
            record["tests_skipped"] = int(skipped[1]) if skipped else 0
            if record["tests_skipped"] == record["tests_run"]:
                raise CheckError("All selected tests were skipped; no checks executed")

    execute(["git", "diff", "--check", *before["diff_range"], "--"])
    compiled = []
    for name in before["changed_paths"]:
        source = root / name
        if source.suffix == ".py" and source.is_file():
            with tokenize.open(source) as handle:
                compile(handle.read(), name, "exec")
            compiled.append(name)
        if source.suffix == ".json" and source.is_file():
            json.loads(source.read_text(encoding="utf-8-sig"))
    results.append({"check": "compile-changed-python-in-memory-and-parse-changed-json", "files": before["changed_paths"], "compiled": compiled, "returncode": 0})
    for name in ACTIVE_BACKLOGS:
        if (root / name).is_file():
            items = validate_backlog(root / name)
            if name.endswith("agentfactory-cloud-backlog.json"):
                validate_cloud_alignment(root, items)
            results.append({"check": "active-backlog-v2-references-dag-and-readable-alignment", "path": name, "items": len(items), "returncode": 0})
    validator = root / "scripts/validate-game-creator-backlog.py"
    if validator.is_file():
        execute([sys.executable, str(validator)])
    tests = test_command(root, profile, selected)
    if tests:
        execute(tests, unittest=True)
    if snapshot(root, base) != before:
        raise CheckError("Repository or base changed during checks; rerun on the final clean commit")
    attestation = {"schema_version": SCHEMA_VERSION, **before, "profile": profile,
                   "selected_test_modules": selected, "full_ci_passed": False,
                   "success": True, "commands": results,
                   "created_at": datetime.now(timezone.utc).isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="team-checks-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(attestation, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return attestation


def verify(root: Path, base: str = "origin/main") -> dict:
    current = snapshot(root, base)
    try:
        attestation = json.loads(attestation_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CheckError("No valid local test attestation; run scripts/team_checks.py first") from exc
    if not isinstance(attestation, dict):
        raise CheckError("Invalid local test attestation object")
    results = attestation.get("commands")
    selected = attestation.get("selected_test_modules")
    if (attestation.get("schema_version") != SCHEMA_VERSION
            or attestation.get("success") is not True
            or attestation.get("full_ci_passed") is not False
            or not isinstance(results, list) or not results
            or any(not isinstance(result, dict) or result.get("returncode") != 0 for result in results)
            or not isinstance(selected, list) or not all(isinstance(value, str) for value in selected)
            or attestation.get("profile") != profile_for(current["changed_paths"], selected)):
        raise CheckError("Invalid or failed local test attestation")
    for key, value in current.items():
        if attestation.get(key) != value:
            raise CheckError(f"Stale local test attestation: {key} changed; rerun checks")
    return attestation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main", help="Already-fetched comparison ref (default: origin/main)")
    parser.add_argument("--test", action="append", default=[], metavar="TEST_MODULE", help="Run a specific local tests module; repeatable")
    parser.add_argument("--verify", action="store_true", help="Verify the saved exact-commit attestation without running checks")
    args = parser.parse_args(argv)
    if args.verify and args.test:
        parser.error("--test cannot be combined with --verify")
    try:
        root = repository(Path(__file__).resolve().parents[1])
        result = verify(root, args.base) if args.verify else run_checks(root, args.base, args.test)
        print(f"Local checks {'verified' if args.verify else 'passed'}: {result['head']} ({result['profile']}). This does not claim full CI acceptance.")
        return 0
    except (CheckError, OSError, ValueError, SyntaxError, TypeError, RecursionError) as exc:
        print(f"Team checks blocked: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
