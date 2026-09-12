"""Settings you can change from an interface, with the change written down.

A value here has exactly two possible origins: the declared default, or an
override somebody made on purpose. The interface shows which, so nobody has to
open a file to find out whether a number is what shipped or what a colleague
changed last week. Every change and every reset is appended to a history that
the database refuses to rewrite, and a change to a sensitive setting needs a
name, a reason and an explicit confirmation of the consequence it declares.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence, TYPE_CHECKING

from .settings_registry import (
    BY_SECTION,
    DEFINITIONS,
    SECTIONS,
    Finding,
    Setting,
    SettingError,
    section,
    setting,
    verify,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from .storage import SQLiteStorage


SETTINGS_MIGRATION = """
CREATE TABLE setting_overrides(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE setting_changes(
    id INTEGER PRIMARY KEY,
    identity TEXT NOT NULL UNIQUE,
    key TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('set','reset')),
    previous_value TEXT NOT NULL,
    new_value TEXT NOT NULL,
    risk TEXT NOT NULL CHECK(risk IN ('safe','sensitive')),
    actor TEXT NOT NULL CHECK(length(trim(actor))>0),
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX setting_changes_key ON setting_changes(key,id);
CREATE TRIGGER setting_changes_no_update BEFORE UPDATE ON setting_changes
BEGIN SELECT RAISE(ABORT,'settings history is immutable'); END;
CREATE TRIGGER setting_changes_no_delete BEFORE DELETE ON setting_changes
BEGIN SELECT RAISE(ABORT,'settings history is durable'); END;
"""

ORIGINS = ("default", "override")
MAX_REASON = 300


class ConfirmationRequired(PermissionError):
    """Raised when a sensitive setting is changed without acknowledging its cost."""


class NotReconfigurable(PermissionError):
    """Raised when a derived, read-only value is changed through the interface."""


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class SettingChange:
    key: str
    action: str
    previous_value: str
    new_value: str
    risk: str
    actor: str
    reason: str
    created_at: str

    @property
    def record(self) -> dict[str, str]:
        return {
            "key": self.key, "action": self.action,
            "previous_value": self.previous_value, "new_value": self.new_value,
            "risk": self.risk, "actor": self.actor, "reason": self.reason,
            "created_at": self.created_at,
        }


class SettingsCentre:
    """The one place an effective setting is resolved, changed and explained."""

    def __init__(self, storage: "SQLiteStorage"):
        self.storage = storage

    # ------------------------------------------------------------- reading

    def overrides(self) -> dict[str, str]:
        rows = self.storage.db.execute(
            "SELECT key,value FROM setting_overrides"
        ).fetchall()
        stored = {str(row["key"]): str(row["value"]) for row in rows}
        # An override for a setting that no longer exists is ignored rather than
        # crashing the page that is meant to explain the settings.
        return {key: value for key, value in stored.items() if key in
                {definition.key for definition in DEFINITIONS}}

    def raw(self, key: str) -> tuple[str, str]:
        definition = setting(key)
        override = self.storage.db.execute(
            "SELECT value FROM setting_overrides WHERE key=?", (definition.key,)
        ).fetchone()
        if override is None:
            return definition.default, "default"
        try:
            definition.parse(str(override["value"]))
        except SettingError:
            # A stored value the current rules reject is reported as the default,
            # and the section check will say the override was discarded.
            return definition.default, "default"
        return str(override["value"]), "override"

    def value(self, key: str) -> Any:
        definition = setting(key)
        return definition.parse(self.raw(definition.key)[0])

    def values(self, section_id: str | None = None) -> dict[str, Any]:
        chosen = (
            BY_SECTION[section(section_id).section_id] if section_id else DEFINITIONS
        )
        return {item.key: self.value(item.key) for item in chosen}

    def field(self, key: str) -> dict[str, Any]:
        definition = setting(key)
        value, origin = self.raw(definition.key)
        described = definition.describe(value=value, origin=origin)
        if origin == "override":
            row = self.storage.db.execute(
                "SELECT actor,reason,updated_at FROM setting_overrides WHERE key=?",
                (definition.key,),
            ).fetchone()
            described["changed_by"] = str(row["actor"]) if row else ""
            described["changed_reason"] = str(row["reason"]) if row else ""
            described["changed_at"] = str(row["updated_at"]) if row else ""
        return described

    def section_view(self, section_id: str) -> dict[str, Any]:
        item = section(section_id)
        fields = [self.field(entry.key) for entry in BY_SECTION[item.section_id]]
        findings = verify(item.section_id, self.values(item.section_id))
        return {
            "section": item.section_id,
            "title": item.title,
            "summary": item.summary,
            "order": item.order,
            "fields": fields,
            "changed_count": sum(1 for field in fields if field["origin"] == "override"),
            "findings": [finding.record for finding in findings],
            "worst_level": _worst(findings),
        }

    def overview(self) -> dict[str, Any]:
        sections = [
            self.section_view(item.section_id)
            for item in sorted(SECTIONS, key=lambda value: value.order)
        ]
        return {
            "sections": sections,
            "changed_total": sum(item["changed_count"] for item in sections),
            "note": (
                "Значення показані такими, якими їх бачить система. «Типове» — те, "
                "що постачається; «змінено» — те, що хтось задав тут."
            ),
        }

    def changes(self, *, key: str | None = None, limit: int = 50) -> tuple[SettingChange, ...]:
        if limit <= 0 or limit > 500:
            raise ValueError("History limit must be between 1 and 500")
        if key is None:
            rows = self.storage.db.execute(
                "SELECT * FROM setting_changes ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        else:
            rows = self.storage.db.execute(
                "SELECT * FROM setting_changes WHERE key=? ORDER BY id DESC LIMIT ?",
                (setting(key).key, int(limit)),
            ).fetchall()
        return tuple(
            SettingChange(
                str(row["key"]), str(row["action"]), str(row["previous_value"]),
                str(row["new_value"]), str(row["risk"]), str(row["actor"]),
                str(row["reason"]), str(row["created_at"]),
            )
            for row in rows
        )

    def verify_section(self, section_id: str) -> tuple[Finding, ...]:
        return verify(section(section_id).section_id, self.values(section_id))

    # ------------------------------------------------------------- writing

    def set(
        self,
        key: str,
        value: Any,
        *,
        actor: str,
        reason: str = "",
        acknowledged_consequence: bool = False,
    ) -> dict[str, Any]:
        definition = self._writable(key)
        who = _person(actor)
        text = definition.format(value) if not isinstance(value, str) else value.strip()
        definition.parse(text)  # raises SettingError with a readable message
        self._acknowledge(definition, acknowledged_consequence)
        current, origin = self.raw(definition.key)
        if text == current and origin == "override":
            return {**self.field(definition.key), "changed": False}
        if text == definition.default:
            return self.reset(
                definition.key, actor=who, reason=reason or "повернуто до типового",
                acknowledged_consequence=acknowledged_consequence,
            )
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO setting_overrides(key,value,actor,reason,updated_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET
                       value=excluded.value, actor=excluded.actor,
                       reason=excluded.reason, updated_at=excluded.updated_at""",
                (definition.key, text, who, _reason(reason), _stamp()),
            )
            self._record(definition, "set", current, text, who, reason)
        return {**self.field(definition.key), "changed": True}

    def reset(
        self,
        key: str,
        *,
        actor: str,
        reason: str = "",
        acknowledged_consequence: bool = False,
    ) -> dict[str, Any]:
        definition = self._writable(key)
        who = _person(actor)
        current, origin = self.raw(definition.key)
        if origin == "default":
            return {**self.field(definition.key), "changed": False}
        self._acknowledge(definition, acknowledged_consequence)
        with self.storage.db:
            self.storage.db.execute(
                "DELETE FROM setting_overrides WHERE key=?", (definition.key,)
            )
            self._record(
                definition, "reset", current, definition.default, who, reason,
            )
        return {**self.field(definition.key), "changed": True}

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _writable(key: str) -> Setting:
        definition = setting(key)
        if not definition.reconfigurable:
            raise NotReconfigurable(
                f"{definition.label} походить із {definition.source} і змінюється "
                "там, а не тут."
            )
        return definition

    @staticmethod
    def _acknowledge(definition: Setting, acknowledged: bool) -> None:
        if definition.risk == "sensitive" and not acknowledged:
            raise ConfirmationRequired(
                f"{definition.label}: {definition.consequence} Підтвердьте наслідок, "
                "щоб застосувати зміну."
            )

    def _record(
        self,
        definition: Setting,
        action: str,
        previous: str,
        new: str,
        actor: str,
        reason: str,
    ) -> None:
        cursor = self.storage.db.execute(
            """INSERT INTO setting_changes(
                   identity,key,action,previous_value,new_value,risk,actor,reason,
                   created_at
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                self.storage._identity("setting-change"), definition.key, action,
                previous, new, definition.risk, actor, _reason(reason), _stamp(),
            ),
        )
        self.storage._event(
            f"setting.{action}", "setting_change", int(cursor.lastrowid),
            {
                "key": definition.key, "risk": definition.risk, "actor": actor,
                "previous_value": previous, "new_value": new,
            },
        )


def _person(actor: str) -> str:
    cleaned = str(actor or "").strip()
    if not cleaned or len(cleaned) > 120:
        raise ValueError("Зміна налаштування записується на конкретну людину")
    return cleaned


def _reason(reason: str) -> str:
    return str(reason or "").strip()[:MAX_REASON]


def _worst(findings: Sequence[Finding]) -> str:
    levels = {finding.level for finding in findings}
    for level in ("problem", "attention", "ok"):
        if level in levels:
            return level
    return "ok"
