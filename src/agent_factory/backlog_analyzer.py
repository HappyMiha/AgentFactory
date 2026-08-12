"""Deterministic first-pass decomposition of uploaded technical specifications."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from .backlog import BacklogProposal, ProposedItem, load_backlog


def _slug(value: str, fallback: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value[:48] or fallback


def analyze_specification(raw: bytes, source_name: str) -> BacklogProposal:
    """Turn a UTF-8 Markdown/text brief into a validated backlog proposal.

    A supplied Agent Factory JSON manifest is preserved and validated as-is. Other
    text is intentionally decomposed conservatively; a human reviews the proposal
    before importing it into the project backlog.
    """
    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Uploaded specification must be a UTF-8 text, Markdown, or JSON file") from exc
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        document = None
    if isinstance(document, dict) and document.get("schema_version") == 1:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(raw)
        try:
            proposal = load_backlog(temporary)
        finally:
            temporary.unlink(missing_ok=True)
        return BacklogProposal("uploaded://" + source_name, digest, source_name, proposal.items)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    headings = [(len(match.group(1)), match.group(2).strip()) for line in lines if (match := re.match(r"^(#{1,6})\s+(.+)$", line))]
    if not headings:
        bullets = [re.sub(r"^[-*+]\s+", "", line) for line in lines if re.match(r"^[-*+]\s+", line)]
        headings = [(1, Path(source_name).stem or "Technical specification")]
        headings += [(2, bullet) for bullet in bullets]
    items: list[ProposedItem] = []
    parents: dict[int, str] = {}
    for index, (level, title) in enumerate(headings, 1):
        kind = "epic" if level <= 1 else ("story" if level == 2 else "task")
        stable_id = f"uploaded:{_slug(source_name, 'spec')}:{index:03d}:{_slug(title, 'item')}"
        parent = next((parents[parent_level] for parent_level in range(level - 1, 0, -1) if parent_level in parents), None)
        items.append(ProposedItem(
            stable_id=stable_id,
            kind=kind,
            title=title,
            description=f"Derived from uploaded specification section: {title}.",
            parent_id=parent,
            acceptance_criteria=(f"Implement and validate the requirements described in '{title}'.",),
            labels=("uploaded", "needs-review") + (("subtask",) if level >= 3 else ()),
            source_references=(source_name,),
        ))
        parents[level] = stable_id
        for old_level in list(parents):
            if old_level > level:
                del parents[old_level]
    if not items:
        raise ValueError("Uploaded specification did not contain analyzable text")
    return BacklogProposal("uploaded://" + source_name, digest, source_name, tuple(items))
