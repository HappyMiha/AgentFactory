"""What has to be true before "Create the game" can do anything.

Development needs somebody to do it. There are exactly three ways to have one,
and until at least one of them is real the button stays inactive and says which
of the three is missing — rather than starting work that will stop at the first
call.

* **A subscription you already have.** You connect it; the key stays here.
* **A subscription arranged through the platform**, possibly with a trial limit.
* **A local model**, offered only after the hardware has been looked at, and
  refused plainly when the card will not carry it.

Two rules keep the wizard from lying:

* a source counts only when it was actually checked - a key that was typed in
  but never used is `unverified`, and unverified sources do not unlock the
  button;
* a local model is never "available" on the strength of a wish. It carries the
  verdict of the hardware check that admitted it.

The wizard records what is connected. It never stores the key material itself:
that is what the credential store is for, and this module has nowhere to put it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from .localisation import DEFAULT_LANGUAGE, LocalisedError, Message, normalise

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from .storage import SQLiteStorage

SOURCE_KINDS = ("own_subscription", "platform_subscription", "local_model")
STATES = ("verified", "unverified", "unavailable")


class FirstRunRefused(LocalisedError):
    """Raised when recording this would claim a source that is not there."""


UNKNOWN_KIND = Message(
    "Невідоме джерело виконання: {kind}.",
    "Unknown source of execution: {kind}.",
)
UNKNOWN_STATE = Message(
    "Невідомий стан джерела: {state}.", "Unknown state for a source: {state}.",
)
NAME_REQUIRED = Message(
    "У джерела має бути назва, щоб людина його впізнала.",
    "A source needs a name, so a person can recognise it.",
)
LOCAL_NEEDS_A_VERDICT = Message(
    "Локальну модель можна пропонувати лише після перевірки заліза.",
    "A local model may only be offered after the hardware has been checked.",
)
NOTHING_CONNECTED = Message(
    "Розробка не почнеться: немає жодного джерела виконання. Підключіть свою "
    "підписку, оформіть її через платформу або підніміть локальну модель.",
    "Development will not start: there is no source of execution. Connect your "
    "own subscription, arrange one through the platform, or run a local model.",
)
ONLY_UNVERIFIED = Message(
    "Розробка не почнеться: підключене є, але жодне джерело ще не перевірено.",
    "Development will not start: something is connected, but no source has been "
    "checked yet.",
)
READY = Message(
    "Можна починати: доступних джерел — {count}.",
    "Ready to start: {count} source(s) available.",
)

KIND_LABELS = {
    "own_subscription": Message("Власна підписка", "Your own subscription"),
    "platform_subscription": Message(
        "Підписка через платформу", "A subscription through the platform",
    ),
    "local_model": Message("Локальна модель", "A local model"),
}

FIRST_RUN_MIGRATION = """
CREATE TABLE studio_execution_sources(
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK(kind IN
        ('own_subscription','platform_subscription','local_model')),
    name TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('verified','unverified','unavailable')),
    detail_uk TEXT NOT NULL DEFAULT '',
    detail_en TEXT NOT NULL DEFAULT '',
    machine_key TEXT NOT NULL DEFAULT '',
    connected_by TEXT NOT NULL DEFAULT '',
    checked_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Source:
    """One way this installation can actually get work done."""

    source_key: str
    kind: str
    name: str
    state: str
    detail: Message | None = None
    machine_key: str = ""
    checked_at: str = ""

    @property
    def usable(self) -> bool:
        return self.state == "verified"

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "source": self.source_key,
            "kind": self.kind,
            "kind_label": KIND_LABELS[self.kind].text(language),
            "name": self.name,
            "state": self.state,
            "usable": self.usable,
            "detail": self.detail.text(language) if self.detail else "",
            "machine": self.machine_key,
            "checked_at": self.checked_at,
        }


@dataclass(frozen=True)
class Readiness:
    """Whether the button works, and what is missing when it does not."""

    can_start: bool
    summary: Message
    sources: tuple[Source, ...]

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "can_start": self.can_start,
            "summary": self.summary.text(language),
            "sources": [source.record(language) for source in self.sources],
            "usable": [
                source.source_key for source in self.sources if source.usable
            ],
        }


class FirstRun:
    """The provider wizard: what is connected, and whether work can start."""

    def __init__(self, storage: "SQLiteStorage"):
        self.storage = storage

    def connect(
        self,
        source_key: str,
        *,
        kind: str,
        name: str,
        state: str = "unverified",
        detail: Message | None = None,
        machine_key: str = "",
        connected_by: str = "",
    ) -> Source:
        """Record a source. Connecting is not the same as having checked it."""
        if kind not in SOURCE_KINDS:
            raise FirstRunRefused(UNKNOWN_KIND, kind=kind)
        if state not in STATES:
            raise FirstRunRefused(UNKNOWN_STATE, state=state)
        if not str(name).strip():
            raise FirstRunRefused(NAME_REQUIRED)
        if kind == "local_model" and state == "verified" and detail is None:
            # "It fits" is a claim about this machine, so it arrives with the
            # verdict that supports it or not at all.
            raise FirstRunRefused(LOCAL_NEEDS_A_VERDICT)
        checked_at = _now() if state != "unverified" else ""
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO studio_execution_sources
                   (source_key,kind,name,state,detail_uk,detail_en,machine_key,
                    connected_by,checked_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source_key) DO UPDATE SET
                     kind=excluded.kind, name=excluded.name, state=excluded.state,
                     detail_uk=excluded.detail_uk, detail_en=excluded.detail_en,
                     machine_key=excluded.machine_key,
                     checked_at=excluded.checked_at, updated_at=excluded.updated_at""",
                (
                    str(source_key), kind, str(name).strip(), state,
                    detail.uk if detail else "", detail.en if detail else "",
                    str(machine_key), str(connected_by), checked_at, _now(),
                ),
            )
        return Source(
            str(source_key), kind, str(name).strip(), state, detail,
            str(machine_key), checked_at,
        )

    def verify(
        self, source_key: str, *, works: bool, detail: Message | None = None,
    ) -> Source:
        """Record the result of actually trying the source."""
        current = self.source(source_key)
        return self.connect(
            source_key, kind=current.kind, name=current.name,
            state="verified" if works else "unavailable",
            detail=detail or current.detail, machine_key=current.machine_key,
        )

    def offer_local_model(
        self,
        source_key: str,
        *,
        name: str,
        machines: Any,
        machine_key: str,
        needed_gb: float,
    ) -> Source:
        """Offer a local model only if this machine will really carry it."""
        verdict = machines.local_model_fits(machine_key, needed_gb=needed_gb)
        return self.connect(
            source_key, kind="local_model", name=name,
            state="verified" if verdict.fits else "unavailable",
            detail=verdict.reason, machine_key=machine_key,
        )

    # -- reading

    def source(self, source_key: str) -> Source:
        row = self.storage.db.execute(
            "SELECT * FROM studio_execution_sources WHERE source_key=?",
            (str(source_key),),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown source {source_key}")
        detail = (
            Message(row["detail_uk"], row["detail_en"])
            if row["detail_uk"] and row["detail_en"] else None
        )
        return Source(
            row["source_key"], row["kind"], row["name"], row["state"], detail,
            row["machine_key"], row["checked_at"],
        )

    def sources(self) -> tuple[Source, ...]:
        rows = self.storage.db.execute(
            "SELECT source_key FROM studio_execution_sources ORDER BY id"
        ).fetchall()
        return tuple(self.source(row["source_key"]) for row in rows)

    def readiness(self) -> Readiness:
        """Whether "Create the game" does anything, and why not when it does not."""
        sources = self.sources()
        usable = [source for source in sources if source.usable]
        if usable:
            summary = Message(
                READY.uk.format(count=len(usable)),
                READY.en.format(count=len(usable)),
            )
            return Readiness(True, summary, sources)
        if sources:
            return Readiness(False, ONLY_UNVERIFIED, sources)
        return Readiness(False, NOTHING_CONNECTED, sources)

    def report(self, *, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        chosen = normalise(language)
        return {
            **self.readiness().record(chosen),
            "kinds": [
                {"kind": kind, "label": KIND_LABELS[kind].text(chosen)}
                for kind in SOURCE_KINDS
            ],
        }
