"""A support bundle an owner can read before sending it.

Asking someone for diagnostics is asking them to trust you with their machine.
So: nothing is collected that was not selected, the selection has a preview that
shows exactly what would be sent, every collected value passes the same
redaction rules the export gate refuses on, and environment variables contribute
their names only - never their values. Credentials, provider auth profiles and
key material have no collector at all, so no selection can include them.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .export_bundle import redact

SUPPORT_MANIFEST = "support-bundle.json"
README_FILE = "READ-BEFORE-SENDING.md"
ALWAYS_INCLUDED = ("versions",)
OPT_IN_CATEGORIES = (
    "environment", "configuration", "audit_events", "logs", "prompts", "game_files",
)
CATEGORIES = (*ALWAYS_INCLUDED, *OPT_IN_CATEGORIES)
NEVER_COLLECTED = (
    "credentials", "provider auth profiles", "private keys", "session tokens",
)
MAX_ITEM_CHARS = 200_000
MAX_ITEMS_PER_CATEGORY = 50
SENSITIVE_ENV_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "KEY", "CREDENTIAL", "AUTH")


class SupportRefused(PermissionError):
    """Raised when a bundle may not be assembled as requested."""


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class SupportItem:
    category: str
    name: str
    content: str
    redactions: tuple[str, ...]
    truncated: bool

    @property
    def size_bytes(self) -> int:
        return len(self.content.encode("utf-8"))

    @property
    def summary(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "name": self.name,
            "size_bytes": self.size_bytes,
            "redactions": list(self.redactions),
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class SupportPreview:
    workspace: str
    selected: tuple[str, ...]
    declined: tuple[str, ...]
    items: tuple[SupportItem, ...]
    failures: tuple[tuple[str, str], ...]

    @property
    def total_bytes(self) -> int:
        return sum(item.size_bytes for item in self.items)

    @property
    def redactions(self) -> tuple[str, ...]:
        return tuple(sorted({rule for item in self.items for rule in item.redactions}))

    @property
    def digest(self) -> str:
        return hashlib.sha256(json.dumps({
            "workspace": self.workspace,
            "selected": list(self.selected),
            "items": [item.summary for item in self.items],
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def record(self) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "selected": list(self.selected),
            "not_selected": list(self.declined),
            "never_collected": list(NEVER_COLLECTED),
            "preview_digest": self.digest,
            "total_bytes": self.total_bytes,
            "redactions_applied": list(self.redactions),
            "items": [item.summary for item in self.items],
            "collection_failures": [
                {"category": category, "reason": reason}
                for category, reason in self.failures
            ],
        }

    def read(self, name: str) -> str:
        """The exact text that would be sent, so an owner can read it first."""
        for item in self.items:
            if item.name == name:
                return item.content
        raise KeyError(f"Nothing named {name!r} is in this preview")


@dataclass(frozen=True)
class SupportBundleResult:
    path: str
    checksum: str
    size_bytes: int
    preview_digest: str
    actor: str
    recorded_at: str
    manifest: Mapping[str, Any]


Collector = Callable[[], Sequence[tuple[str, str]]]


class SupportBundler:
    """Collects only what was selected, and shows it before it is packaged."""

    def __init__(
        self,
        workspace: Path,
        *,
        storage: Any = None,
        collectors: Mapping[str, Collector] | None = None,
        audit_limit: int = 200,
    ):
        self.workspace = Path(workspace)
        self.storage = storage
        self.audit_limit = int(audit_limit)
        self.collectors: dict[str, Collector] = {
            "versions": self._versions,
            "environment": self._environment,
            "configuration": self._configuration,
            "audit_events": self._audit_events,
            "logs": self._logs,
            "prompts": self._prompts,
            "game_files": self._game_files,
        }
        for category, collector in (collectors or {}).items():
            if category not in CATEGORIES:
                raise ValueError(f"Unknown support category: {category!r}")
            self.collectors[category] = collector

    def preview(self, *, include: Sequence[str] = ()) -> SupportPreview:
        requested = {str(value) for value in include}
        unknown = requested - set(CATEGORIES)
        if unknown:
            raise ValueError(
                "Unknown support categories: " + ", ".join(sorted(unknown))
            )
        selected = tuple(
            category for category in CATEGORIES
            if category in ALWAYS_INCLUDED or category in requested
        )
        declined = tuple(
            category for category in CATEGORIES if category not in selected
        )
        items: list[SupportItem] = []
        failures: list[tuple[str, str]] = []
        for category in selected:
            try:
                collected = list(self.collectors[category]())
            except Exception as exc:  # A diagnostic tool must not fail the session.
                failures.append((category, f"{type(exc).__name__}: {exc}"))
                continue
            for name, content in collected[:MAX_ITEMS_PER_CATEGORY]:
                items.append(_item(category, str(name), str(content)))
        return SupportPreview(
            str(self.workspace), selected, declined, tuple(items), tuple(failures),
        )

    def build(
        self,
        preview: SupportPreview,
        *,
        output: Path,
        actor: str,
        acknowledged_digest: str = "",
    ) -> SupportBundleResult:
        if not str(actor).strip():
            raise ValueError("A support bundle records who assembled it")
        if acknowledged_digest and acknowledged_digest != preview.digest:
            raise SupportRefused(
                "The acknowledged preview is not the one being packaged"
            )
        current = self.preview(include=preview.selected)
        if current.digest != preview.digest:
            raise SupportRefused("The diagnostics changed after the preview was read")
        destination = Path(output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema": 1,
            "bundle_kind": "support",
            "selected": list(preview.selected),
            "not_selected": list(preview.declined),
            "never_collected": list(NEVER_COLLECTED),
            "redactions_applied": list(preview.redactions),
            "preview_digest": preview.digest,
            "items": [item.summary for item in preview.items],
            "collection_failures": [
                {"category": category, "reason": reason}
                for category, reason in preview.failures
            ],
            "assembled_by": str(actor).strip(),
            "assembled_at": _stamp(),
        }
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr(
                SUPPORT_MANIFEST, json.dumps(manifest, indent=2, sort_keys=True) + "\n"
            )
            bundle.writestr(README_FILE, _readme(manifest))
            for item in preview.items:
                bundle.writestr(f"{item.category}/{_safe_name(item.name)}", item.content)
        payload = destination.read_bytes()
        return SupportBundleResult(
            str(destination), hashlib.sha256(payload).hexdigest(), len(payload),
            preview.digest, str(actor).strip(), _stamp(), manifest,
        )

    # ------------------------------------------------------------ collectors

    def _versions(self) -> list[tuple[str, str]]:
        from . import __version__

        payload: dict[str, Any] = {
            "core_version": __version__,
            "python": sys.version.split()[0],
            "platform": platform.system(),
            "platform_release": platform.release(),
            "machine": platform.machine(),
            "collected_at": _stamp(),
        }
        if self.storage is not None:
            payload["schema_version"] = self._schema_version()
            payload["packs"] = self._pack_versions()
        return [("versions.json", json.dumps(payload, indent=2, sort_keys=True))]

    def _schema_version(self) -> int | None:
        try:
            row = self.storage.db.execute(
                "SELECT MAX(version) AS version FROM schema_migrations"
            ).fetchone()
            return int(row["version"]) if row and row["version"] is not None else None
        except Exception:
            return None

    def _pack_versions(self) -> list[dict[str, str]]:
        try:
            rows = self.storage.db.execute(
                """SELECT i.pack_key,v.version,i.state FROM pack_installations i
                     LEFT JOIN pack_versions v ON v.id=i.active_version_id"""
            ).fetchall()
        except Exception:
            return []
        return [
            {
                "pack_key": str(row["pack_key"]),
                "version": str(row["version"] or ""),
                "state": str(row["state"]),
            }
            for row in rows
        ]

    def _environment(self) -> list[tuple[str, str]]:
        """Names only. A variable's value is never collected, sensitive or not."""
        import os

        names = sorted(os.environ)
        payload = {
            "note": "Variable names only. No value is collected by this tool.",
            "variables": [
                {
                    "name": name,
                    "set": True,
                    "looks_sensitive": any(
                        marker in name.upper() for marker in SENSITIVE_ENV_MARKERS
                    ),
                }
                for name in names
            ],
        }
        return [("environment.json", json.dumps(payload, indent=2, sort_keys=True))]

    def _configuration(self) -> list[tuple[str, str]]:
        defaults = Path(__file__).resolve().parent / "defaults"
        collected: list[tuple[str, str]] = []
        for path in sorted(defaults.glob("*.json")):
            collected.append((path.name, path.read_text(encoding="utf-8")))
        return collected

    def _audit_events(self) -> list[tuple[str, str]]:
        if self.storage is None:
            return []
        # The event payload is deliberately not selected: an event's shape is
        # diagnostic, its payload is the owner's data.
        rows = self.storage.db.execute(
            """SELECT event_type,entity_type,entity_id,created_at
                 FROM events ORDER BY id DESC LIMIT ?""",
            (self.audit_limit,),
        ).fetchall()
        payload = [
            {
                "event_type": str(row["event_type"]),
                "entity_type": str(row["entity_type"]),
                "entity_id": str(row["entity_id"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]
        return [("audit-events.json", json.dumps(payload, indent=2))]

    def _logs(self) -> list[tuple[str, str]]:
        directory = self.workspace / ".agent-factory" / "logs"
        if not directory.is_dir():
            return []
        return [
            (path.name, path.read_text(encoding="utf-8", errors="replace"))
            for path in sorted(directory.glob("*.log"))
        ]

    def _prompts(self) -> list[tuple[str, str]]:
        if self.storage is None:
            return []
        try:
            rows = self.storage.db.execute(
                """SELECT id,prompt FROM provider_gates
                    WHERE prompt IS NOT NULL ORDER BY id DESC LIMIT ?""",
                (self.audit_limit,),
            ).fetchall()
        except Exception:
            return []
        return [(f"prompt-{int(row['id'])}.txt", str(row["prompt"])) for row in rows]

    def _game_files(self) -> list[tuple[str, str]]:
        directory = self.workspace / "game"
        if not directory.is_dir():
            return []
        collected: list[tuple[str, str]] = []
        for path in sorted(directory.rglob("*")):
            if path.is_file() and not path.is_symlink():
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                collected.append((str(path.relative_to(directory)), text))
        return collected


def _item(category: str, name: str, content: str) -> SupportItem:
    redacted, rules = redact(content)
    truncated = len(redacted) > MAX_ITEM_CHARS
    if truncated:
        redacted = redacted[:MAX_ITEM_CHARS] + "\n[truncated]"
    return SupportItem(category, name, redacted, rules, truncated)


def _safe_name(name: str) -> str:
    cleaned = str(name).replace("\\", "/").strip("/")
    parts = [part for part in cleaned.split("/") if part not in {"", ".", ".."}]
    return "/".join(parts) or "item"


def _readme(manifest: Mapping[str, Any]) -> str:
    lines = [
        "# Read before sending",
        "",
        "This bundle was assembled from a preview that the owner could read in full.",
        "",
        "## What is in it",
        "",
    ]
    for category in manifest["selected"]:
        lines.append(f"- `{category}/`")
    lines += ["", "## What was left out", ""]
    for category in manifest["not_selected"]:
        lines.append(f"- {category} (not selected)")
    for item in manifest["never_collected"]:
        lines.append(f"- {item} (no collector exists; selection cannot include it)")
    if manifest["redactions_applied"]:
        lines += ["", "## Redactions applied", ""]
        for rule in manifest["redactions_applied"]:
            lines.append(f"- {rule}")
    lines += [
        "",
        "Environment variables appear by name only. No variable value is collected.",
        "",
    ]
    return "\n".join(lines)
