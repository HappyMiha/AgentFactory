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
    counters = {"epic": 0, "feature": 0, "story": 0, "task": 0}

    def visit(value: Any, parent: str | None = None, inherited_kind: str = "task") -> None:
        if isinstance(value, list):
            for child in value:
                visit(child, parent, inherited_kind)
            return
        if not isinstance(value, dict):
            return
        raw_kind = str(value.get("kind") or value.get("type") or value.get("level") or inherited_kind).lower()
        kind = (
            "epic"
            if raw_kind in {"epic", "initiative", "feature", "project"}
            else "story"
            if raw_kind in {"story", "user_story", "requirement"}
            else "task"
        )
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
        normalized.setdefault("schema_version", 1)
        normalized.setdefault("source", {"name": source_name})
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", encoding="utf-8", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(normalized, handle, ensure_ascii=False)
        try:
            proposal = load_backlog(temporary)
        finally:
            temporary.unlink(missing_ok=True)
        return BacklogProposal(
            "uploaded://" + source_name,
            digest,
            source_name,
            proposal.items,
            proposal.schema_version,
            {**proposal.source_metadata, "original_text": text},
            proposal.extension_schema,
            proposal.planning_contract,
            proposal.extensions,
        )
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
            return BacklogProposal(
                "uploaded://" + source_name,
                digest,
                source_name,
                proposal.items,
                proposal.schema_version,
                {**proposal.source_metadata, "original_text": text},
                proposal.extension_schema,
                proposal.planning_contract,
                proposal.extensions,
            )
    if isinstance(document, dict) and document.get("schema_version") == 1:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(raw)
        try:
            proposal = load_backlog(temporary)
        finally:
            temporary.unlink(missing_ok=True)
        return BacklogProposal(
            "uploaded://" + source_name,
            digest,
            source_name,
            proposal.items,
            proposal.schema_version,
            {**proposal.source_metadata, "original_text": text},
            proposal.extension_schema,
            proposal.planning_contract,
            proposal.extensions,
        )

    if not text.strip():
        raise ValueError("Uploaded specification did not contain analyzable text")
    # Keep section bodies verbatim. Headings alone are not the requirements.
    sections: list[tuple[int, str, list[str]]] = []
    for line in text.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
        if heading:
            sections.append((len(heading.group(1)), heading.group(2).strip(), []))
        else:
            if not sections and not line.strip():
                continue
            if not sections:
                sections.append((1, Path(source_name).stem or "Specification", []))
            sections[-1][2].append(line)
    items: list[ProposedItem] = []
    parents: dict[int, str] = {}
    for index, (level, title, body) in enumerate(sections, 1):
        description = "\n".join(body).strip() or title
        kind = "epic" if level == 1 else ("story" if level == 2 else "task")
        stable_id = f"uploaded:{_slug(source_name, 'spec')}:{index:03d}:{_slug(title, 'item')}"
        parent = next((parents[n] for n in range(level - 1, 0, -1) if n in parents), None)
        items.append(ProposedItem(
            stable_id=stable_id, kind=kind, title=title, description=description,
            parent_id=parent,
            acceptance_criteria=(f"Verify the source requirement: {description}",),
            labels=("uploaded", "needs-review") + (("subtask",) if level >= 3 else ()),
            source_references=(f"uploaded://{source_name}#sha256={digest}",),
            review_notes=("Deterministic import; review scope and acceptance criteria before confirming. No AI analysis was run.",),
        ))
        parents[level] = stable_id
        for old_level in list(parents):
            if old_level > level:
                del parents[old_level]
    # A plain paragraph or a leaf section needs an executable proposal, not an
    # empty filename epic. Preserve its full text instead of inventing mechanics.
    parent_ids = {item.parent_id for item in items}
    for item in tuple(items):
        if not item.executable and (item.stable_id not in parent_ids or item.description != item.title):
            items.append(ProposedItem(
                stable_id=item.stable_id + ":implement", kind="task",
                title=f"Implement: {item.title}", description=item.description,
                parent_id=item.stable_id, acceptance_criteria=item.acceptance_criteria,
                labels=("uploaded", "needs-review"),
                source_references=item.source_references, review_notes=item.review_notes,
            ))
    return BacklogProposal("uploaded://" + source_name, digest, source_name, tuple(items),
                           source_metadata={"original_text": text})
