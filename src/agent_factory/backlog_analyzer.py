"""Deterministic first-pass decomposition of uploaded technical specifications."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from .backlog import BacklogProposal, ProposedItem, load_backlog


def extract_text(raw: bytes, source_name: str) -> str:
    """Extract text from common document uploads without executing the file."""
    suffix = Path(source_name).suffix.lower()
    if suffix == ".pdf" or raw.startswith(b"%PDF"):
        try:
            from pypdf import PdfReader
            import io
            text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
        except ImportError as exc:
            raise ValueError("PDF support requires the web extra: install pypdf") from exc
        except Exception as exc:  # noqa: BLE001 - report malformed document as input data.
            raise ValueError(f"Could not read PDF specification: {type(exc).__name__}") from exc
        if not text.strip():
            raise ValueError("PDF does not contain extractable text; OCR is not enabled")
        return text
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("This file format has no safe text extractor yet; upload text, JSON, Markdown, or PDF") from exc


def _slug(value: str, fallback: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value[:48] or fallback


def _json_items(document: Any, source_name: str) -> list[dict[str, Any]]:
    """Normalize common export shapes into the validated backlog schema."""
    result: list[dict[str, Any]] = []
    counters = {"epic": 0, "story": 0, "task": 0}

    def visit(value: Any, parent: str | None = None, inherited_kind: str = "task") -> None:
        if isinstance(value, list):
            for child in value:
                visit(child, parent, inherited_kind)
            return
        if not isinstance(value, dict):
            return
        raw_kind = str(value.get("kind") or value.get("type") or value.get("level") or inherited_kind).lower()
        kind = "epic" if raw_kind in {"epic", "initiative", "feature", "project"} else ("story" if raw_kind in {"story", "user_story", "requirement"} else "task")
        title = str(value.get("title") or value.get("name") or value.get("summary") or value.get("text") or "").strip()
        children = value.get("children") or value.get("subtasks") or value.get("tasks") or value.get("stories")
        if title:
            counters[kind] += 1
            stable_id = str(value.get("stable_id") or value.get("id") or f"{kind}-{counters[kind]}")
            stable_id = f"uploaded:{_slug(source_name, 'spec')}:{_slug(stable_id, kind)}"
            result.append({
                "stable_id": stable_id,
                "kind": kind,
                "title": title,
                "description": str(value.get("description") or value.get("details") or title),
                "parent_id": parent,
                "dependencies": [],
                "acceptance_criteria": [str(item) for item in (value.get("acceptance_criteria") or value.get("criteria") or [f"Implement and validate '{title}'."])],
                "source_references": [source_name],
                "labels": ["uploaded", "needs-review"],
            })
            parent = stable_id
        for key in ("epics", "features", "stories", "requirements", "tasks", "subtasks", "children", "items", "backlog"):
            if key in value:
                visit(value[key], parent, "task" if key in {"tasks", "subtasks"} else inherited_kind)

    visit(document)
    return result


def analyze_specification(raw: bytes, source_name: str) -> BacklogProposal:
    """Turn a UTF-8 Markdown/text brief into a validated backlog proposal.

    A supplied Agent Factory JSON manifest is preserved and validated as-is. Other
    text is intentionally decomposed conservatively; a human reviews the proposal
    before importing it into the project backlog.
    """
    digest = hashlib.sha256(raw).hexdigest()
    text = extract_text(raw, source_name)
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        document = None
    if isinstance(document, dict) and isinstance(document.get("items"), list):
        # Accept manifests exported without the schema marker; validation still
        # applies before anything can be imported.
        normalized = dict(document)
        normalized["schema_version"] = 1
        normalized.setdefault("source", {"name": source_name})
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", encoding="utf-8", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(normalized, handle, ensure_ascii=False)
        try:
            proposal = load_backlog(temporary)
        finally:
            temporary.unlink(missing_ok=True)
        return BacklogProposal("uploaded://" + source_name, digest, source_name, proposal.items)
    if isinstance(document, (dict, list)):
        normalized_items = _json_items(document, source_name)
        if normalized_items:
            normalized = {"schema_version": 1, "source": {"name": source_name}, "items": normalized_items}
            with tempfile.NamedTemporaryFile(suffix=".json", mode="w", encoding="utf-8", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(normalized, handle, ensure_ascii=False)
            try:
                proposal = load_backlog(temporary)
            finally:
                temporary.unlink(missing_ok=True)
            return BacklogProposal("uploaded://" + source_name, digest, source_name, proposal.items)
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
