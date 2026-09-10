#!/usr/bin/env python3
"""Check documentation translation currency and mechanical invariants.

This checks identity, coverage and links, not semantic translation quality.
The Ukrainian documents and existing backlog manifests remain authoritative.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "docs/evolution/translations.json"
TASK_ID = re.compile(r"(?<![\w-])(?:core:|world:|cloud:)?AF-(?:(?:RSI|LW|GC|CLD|AMM)-?)?(?:\d{3}|E\d+)(?![\w-])")
LINK = re.compile(r"(?<!!)\[[^\]\n]*\]\(([^)\n]+)\)")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.M)


def normalized_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def body(text: str) -> str:
    """Ignore generated provenance, language switches and compatibility aliases."""
    text = re.sub(r"<!-- translation-metadata:start -->.*?<!-- translation-metadata:end -->\n?", "", text, flags=re.S)
    text = re.sub(r'^<a id="[^"]+"></a>\s*$', "", text, flags=re.M)
    return text


def slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[^\w\-\s]", "", text.lower())
    return text.replace(" ", "-")


def prose(text: str) -> str:
    """Exclude fenced examples from rendered headings, tables and links.

    Keep line breaks so diagnostics and callers can retain source positions.
    An unterminated fence consumes the rest of the document, as in Markdown.
    """
    lines = []
    fence = None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence is not None:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            lines.append("\n" if line.endswith("\n") else "")
        elif marker and not (marker[1][0] == "`" and "`" in marker[2]):
            fence = marker[1]
            lines.append("\n" if line.endswith("\n") else "")
        else:
            lines.append(line)
    return "".join(lines)


def anchors(text: str) -> set[str]:
    text = prose(text)
    result = set(re.findall(r'<a\s+id="([^"]+)"', text))
    counts: Counter[str] = Counter()
    for _, heading in HEADING.findall(text):
        key = slug(heading)
        suffix = f"-{counts[key]}" if counts[key] else ""
        result.add(key + suffix)
        counts[key] += 1
    return result


def safe_path(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes repository: {relative}")
    return target


def field(block: str, label: str) -> str | None:
    match = re.search(r"\*\*" + re.escape(label) + r":\*\*\s*([^\n]+)", block)
    return re.split(r"\s+\*\*", match.group(1))[0].strip() if match else None


def dependency_tokens(value: str) -> list[str]:
    """Preserve both qualified identities and source-style abbreviated IDs."""
    return re.findall(TASK_ID.pattern + r"|(?<![\w-])\d{3}(?![\w-])", value)


def check_card_fields(relative: str, source: str, translated: str) -> list[str]:
    """Compare planning fields within each card, so swapped edges cannot pass."""
    if not relative.endswith("evolution/backlog.en.md"):
        return []
    pattern = re.compile(r"^#{2,3} (AF-(?:RSI|LW)-\d{3})[^\n]*\n(.*?)(?=^#{1,3} |\Z)", re.M | re.S)
    source_entries = pattern.findall(prose(source))
    translated_entries = pattern.findall(prose(translated))
    source_cards = dict(source_entries)
    translated_cards = dict(translated_entries)
    errors = []
    if (not source_cards or source_cards.keys() != translated_cards.keys()
            or len(source_entries) != len(source_cards) or len(translated_entries) != len(translated_cards)):
        return [f"{relative}: missing or unexpected detailed backlog cards"]
    labels = {"Результат": "Outcome", "Приймання": "Acceptance", "Залежності": "Dependencies", "Reuse": "Reuse"}
    labels.update({"Негативні перевірки": "Negative checks", "Артефакт": "Artifact", "Фаза/пріоритет": "Phase/priority", "Підстави": "Rationale"} if "AF-RSI-001" in source_cards else {"Неприйнятний випадок": "Unacceptable case", "Контракти Core": "Core contracts", "Підстави": "Basis", "Межа": "Boundary"})
    for task, source_card in source_cards.items():
        target_card = translated_cards[task]
        for original_label, english_label in labels.items():
            a, b = field(source_card, original_label), field(target_card, english_label)
            if (a is None) != (b is None):
                errors.append(f"{relative}: {task}: missing/extra {english_label} field")
            if a is None or b is None:
                continue
            if english_label in {"Dependencies", "Core contracts"}:
                if dependency_tokens(a) != dependency_tokens(b):
                    errors.append(f"{relative}: {task}: changed {english_label}")
            if english_label == "Reuse" and TASK_ID.findall(a) != TASK_ID.findall(b):
                errors.append(f"{relative}: {task}: changed Reuse identities")
            if english_label in {"Phase/priority", "Rationale", "Basis"}:
                if a.rstrip(". ") != b.rstrip(". "):
                    errors.append(f"{relative}: {task}: changed {english_label}")
    return errors


def check_planning_tables(relative: str, source: str, translated: str) -> list[str]:
    """Bind machine-like table columns to their row, not a global ID count."""
    patterns = []
    if relative.endswith("evolution/implementation-order.en.md"):
        patterns = [
            ("requirement order/allocation", r"^\|\s*(\d+)\s*\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|"),
            ("release order/closure/allocation", r"^\|\s*(\d+)\s*\|\s*\*\*([CLW]-[A-Z-]+)\*\*[^|]*\|\s*(\d+)\s*\|\s*(\d+)\s*\|"),
        ]
    elif relative.endswith("game-creator-backlog.en.md"):
        patterns = [("task priority/milestone/size/dependencies", r"^\|\s*(AF-GC-\d{3})\s*\|\s*(P\d+)\s*\|\s*(M\d+)\s*\|\s*([SML])\s*\|[^|]*\|\s*([^|]+?)\s*\|")]
    errors = []
    for label, pattern in patterns:
        a = re.findall(pattern, prose(source), re.M)
        b = re.findall(pattern, prose(translated), re.M)
        if not a or a != b:
            errors.append(f"{relative}: changed {label} table rows")
    return errors


def check_links(root: Path, relative: str, text: str) -> list[str]:
    errors = []
    page = root / relative
    # Inline code can contain literal Markdown examples rather than links.
    text = re.sub(r"(`+)(?!`)(.*?)\1(?!`)", "", prose(text), flags=re.S)
    for raw in LINK.findall(text):
        raw = raw.strip("<>").split(' "', 1)[0]
        parsed = urlsplit(raw)
        if parsed.scheme or raw.startswith("//"):
            continue
        target = (page.parent / unquote(parsed.path)).resolve() if parsed.path else page.resolve()
        if not target.is_relative_to(root.resolve()):
            errors.append(f"{relative}: link escapes repository: {raw}")
        elif not target.exists():
            errors.append(f"{relative}: missing link target: {raw}")
        elif parsed.fragment and target.suffix == ".md":
            if unquote(parsed.fragment) not in anchors(normalized_text(target)):
                errors.append(f"{relative}: missing heading anchor: {raw}")
    return errors


def validate(root: Path) -> tuple[list[str], int]:
    errors = []
    manifest = json.loads(normalized_text(root / MANIFEST))
    if manifest.get("schema_version") != 1 or manifest.get("hash_basis") != "utf8_lf":
        return ["Unsupported translation manifest schema/hash basis"], 0
    pairs = manifest.get("translations", [])
    if not isinstance(pairs, list) or not pairs:
        return ["Translation manifest must contain a nonempty translations list"], 0
    by_source = {p["source"]: p for p in pairs}
    by_target = {p["translation"]: p for p in pairs}
    if len(by_source) != len(pairs) or len(by_target) != len(pairs):
        errors.append("Duplicate source or translation in manifest")
    expected = {p.relative_to(root).as_posix() for p in (root / "docs/evolution").glob("*.md") if not p.name.endswith(".en.md")}
    missing = expected - by_source.keys()
    if missing:
        errors.append(f"Missing English coverage: {sorted(missing)}")
    english = {p.relative_to(root).as_posix() for p in (root / "docs/evolution").glob("*.en.md")}
    if english - by_target.keys():
        errors.append(f"Unregistered English documents: {sorted(english - by_target.keys())}")
    for pair in pairs:
        label = pair["translation"]
        try:
            source_path = safe_path(root, pair["source"])
            target_path = safe_path(root, label)
            source = normalized_text(source_path)
            translated = normalized_text(target_path)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"{label}: {exc}")
            continue
        if digest(source) != pair["source_sha256"]:
            errors.append(f"STALE: {label}; Ukrainian source changed. Review and synchronise the translation.")
        if digest(translated) != pair["translation_sha256"]:
            errors.append(f"UNREVIEWED: {label}; translation changed since its recorded review.")
        if f"Source SHA-256 (UTF-8/LF): `{pair['source_sha256']}`" not in translated:
            errors.append(f"{label}: missing or incorrect visible source hash")
        source_body, translated_body = body(source), body(translated)
        source_ids = Counter(TASK_ID.findall(source_body))
        translated_ids = Counter(TASK_ID.findall(translated_body))
        if source_ids != translated_ids:
            errors.append(f"{label}: task-ID occurrence mismatch; missing={dict(source_ids-translated_ids)}, added={dict(translated_ids-source_ids)}")
        if len(HEADING.findall(prose(source_body))) != len(HEADING.findall(prose(translated_body))):
            errors.append(f"{label}: heading-count mismatch; check omitted or added sections")
        source_rows = sum(line.startswith("|") for line in prose(source_body).splitlines())
        target_rows = sum(line.startswith("|") for line in prose(translated_body).splitlines())
        if source_rows != target_rows:
            errors.append(f"{label}: table-row count differs ({source_rows} vs {target_rows})")
        errors.extend(check_card_fields(label, source_body, translated_body))
        errors.extend(check_planning_tables(label, source_body, translated_body))
        errors.extend(check_links(root, label, translated))
    for item in manifest.get("canonical_sources", []):
        path = safe_path(root, item["path"])
        if digest(normalized_text(path)) != item["sha256"]:
            errors.append(f"CANONICAL SOURCE CHANGED: {item['path']}; recheck affected English requirements before updating the pin.")
    return errors, len(pairs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        errors, count = validate(args.root.resolve())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Translation validation failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"PASS: {count} translations; current source hashes, reviewed translation hashes, task IDs, headings, table rows and local links. Semantic quality requires separate review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
