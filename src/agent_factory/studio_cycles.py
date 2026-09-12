"""Pause, say what you want changed, continue.

The loop a person actually uses is: watch, play, notice something, pause, say
it in their own words, continue. This module keeps that loop honest.

* **Pause stops the issuing of new tasks, not the world.** Work already in
  flight finishes, and the pause says which work that is rather than pretending
  everything stopped the moment the button was pressed.
* **A comment is kept in the person's own words.** It is not summarised into a
  requirement here, and it cannot be edited later to match what was built.
* **Continuing opens a new cycle and hands the comments to whoever replans.**
  This module does not replan and does not claim the comments were understood;
  it records which comments belong to which cycle, so the answer to "did my
  double jump get planned?" is a fact rather than a feeling.

Cycles are numbered from one. A mission that was never paused is on cycle one,
running.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence, TYPE_CHECKING

from .localisation import DEFAULT_LANGUAGE, LocalisedError, Message, normalise

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from .storage import SQLiteStorage

CYCLE_STATES = ("running", "paused")
COMMENT_SCOPES = ("game", "stage", "task")
MAX_COMMENT = 2000


class CycleRefused(LocalisedError):
    """Raised when the answer would misdescribe what actually happens."""


ACTOR_REQUIRED = Message(
    "Паузу і продовження записують на конкретну людину. Вкажіть імʼя.",
    "A pause and a continue are recorded against a named person. Enter a name.",
)
ALREADY_PAUSED = Message(
    "Робота вже на паузі.", "The work is already paused.",
)
NOT_PAUSED = Message(
    "Робота не на паузі, тож продовжувати нічого.",
    "The work is not paused, so there is nothing to continue.",
)
EMPTY_COMMENT = Message(
    "Порожній коментар нічого не змінить. Напишіть, що саме не так.",
    "An empty comment changes nothing. Say what is wrong.",
)
UNKNOWN_SCOPE = Message(
    "Незрозуміло, чого стосується коментар: {scope}.",
    "It is unclear what the comment is about: {scope}.",
)
STILL_FINISHING = Message(
    "Нові задачі більше не видаються. Те, що вже почалося, доробляється: {work}.",
    "No new task will be handed out. What already started is finishing: {work}.",
)
NOTHING_IN_FLIGHT = Message(
    "Нові задачі більше не видаються, і зараз нічого не виконується.",
    "No new task will be handed out, and nothing is running right now.",
)
NOT_REPLANNED_YET = Message(
    "Коментарі передані планувальнику. Поки він не перепланує, у беклозі їх ще "
    "не видно.",
    "The comments were handed to the planner. Until it replans, they are not in "
    "the backlog yet.",
)

CYCLE_MIGRATION = """
CREATE TABLE studio_cycles(
    id INTEGER PRIMARY KEY,
    mission TEXT NOT NULL,
    number INTEGER NOT NULL CHECK(number > 0),
    state TEXT NOT NULL CHECK(state IN ('running','paused')),
    paused_at TEXT NOT NULL DEFAULT '',
    paused_by TEXT NOT NULL DEFAULT '',
    resumed_at TEXT NOT NULL DEFAULT '',
    resumed_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(mission, number)
);
CREATE INDEX idx_studio_cycles_mission ON studio_cycles(mission, number);

CREATE TABLE studio_cycle_comments(
    id INTEGER PRIMARY KEY,
    cycle_id INTEGER NOT NULL REFERENCES studio_cycles(id),
    mission TEXT NOT NULL,
    scope TEXT NOT NULL CHECK(scope IN ('game','stage','task')),
    subject TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL CHECK(length(text) > 0),
    author TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_studio_cycle_comments ON studio_cycle_comments(cycle_id, id);

-- What a person asked for is evidence. Editing it later to match what was
-- delivered would turn the history of a game into a story about it.
CREATE TRIGGER studio_cycle_comments_no_update
BEFORE UPDATE ON studio_cycle_comments
BEGIN SELECT RAISE(ABORT, 'a comment cannot be rewritten'); END;
CREATE TRIGGER studio_cycle_comments_no_delete
BEFORE DELETE ON studio_cycle_comments
BEGIN SELECT RAISE(ABORT, 'a comment cannot be deleted'); END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Comment:
    """One thing the person wants different, in their words."""

    comment_id: int
    cycle: int
    scope: str
    subject: str
    text: str
    author: str = ""
    created_at: str = ""

    def record(self) -> dict[str, Any]:
        return {
            "comment_id": self.comment_id,
            "cycle": self.cycle,
            "scope": self.scope,
            "subject": self.subject,
            "text": self.text,
            "author": self.author,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class Pause:
    """What a pause actually did."""

    cycle: int
    paused_at: str
    paused_by: str
    finishing: tuple[str, ...]

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        summary = (
            STILL_FINISHING.text(language, work=", ".join(self.finishing))
            if self.finishing else NOTHING_IN_FLIGHT.text(language)
        )
        return {
            "cycle": self.cycle,
            "paused_at": self.paused_at,
            "paused_by": self.paused_by,
            "finishing": list(self.finishing),
            "summary": summary,
        }


@dataclass(frozen=True)
class Resume:
    """What continuing hands to whoever replans."""

    closed_cycle: int
    new_cycle: int
    resumed_at: str
    resumed_by: str
    comments: tuple[Comment, ...]

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "closed_cycle": self.closed_cycle,
            "cycle": self.new_cycle,
            "resumed_at": self.resumed_at,
            "resumed_by": self.resumed_by,
            "comments": [comment.record() for comment in self.comments],
            "note": NOT_REPLANNED_YET.text(language),
        }


class StudioCycles:
    """Pause, comments and the cycles they produced."""

    def __init__(self, storage: "SQLiteStorage"):
        self.storage = storage

    # -- state

    def _current_row(self, mission: str) -> Any:
        return self.storage.db.execute(
            "SELECT * FROM studio_cycles WHERE mission=? ORDER BY number DESC LIMIT 1",
            (str(mission),),
        ).fetchone()

    def _ensure(self, mission: str) -> Any:
        row = self._current_row(mission)
        if row is not None:
            return row
        with self.storage.db:
            self.storage.db.execute(
                "INSERT INTO studio_cycles(mission,number,state) VALUES(?,1,'running')",
                (str(mission),),
            )
        return self._current_row(mission)

    def current(self, mission: str) -> dict[str, Any]:
        row = self._ensure(mission)
        return {
            "mission": str(mission),
            "cycle": int(row["number"]),
            "state": row["state"],
            "paused_at": row["paused_at"],
            "paused_by": row["paused_by"],
        }

    def paused(self, mission: str) -> bool:
        return self._ensure(mission)["state"] == "paused"

    # -- the loop

    def pause(
        self, mission: str, *, actor: str, finishing: Sequence[str] = (),
    ) -> Pause:
        """Stop handing out new tasks. Say what is still finishing."""
        who = str(actor).strip()
        if not who:
            raise CycleRefused(ACTOR_REQUIRED)
        row = self._ensure(mission)
        if row["state"] == "paused":
            raise CycleRefused(ALREADY_PAUSED)
        paused_at = _now()
        with self.storage.db:
            self.storage.db.execute(
                "UPDATE studio_cycles SET state='paused',paused_at=?,paused_by=? WHERE id=?",
                (paused_at, who, int(row["id"])),
            )
        return Pause(int(row["number"]), paused_at, who, tuple(str(x) for x in finishing))

    def comment(
        self,
        mission: str,
        text: str,
        *,
        scope: str = "game",
        subject: str = "",
        author: str = "",
    ) -> Comment:
        """Keep what the person said, exactly as they said it."""
        if scope not in COMMENT_SCOPES:
            raise CycleRefused(UNKNOWN_SCOPE, scope=scope)
        body = str(text).strip()[:MAX_COMMENT]
        if not body:
            raise CycleRefused(EMPTY_COMMENT)
        row = self._ensure(mission)
        created_at = _now()
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO studio_cycle_comments
                   (cycle_id,mission,scope,subject,text,author,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    int(row["id"]), str(mission), scope, str(subject), body,
                    str(author), created_at,
                ),
            )
        return Comment(
            int(cursor.lastrowid), int(row["number"]), scope, str(subject),
            body, str(author), created_at,
        )

    def resume(self, mission: str, *, actor: str) -> Resume:
        """Close this cycle, open the next, and hand over what was said."""
        who = str(actor).strip()
        if not who:
            raise CycleRefused(ACTOR_REQUIRED)
        row = self._ensure(mission)
        if row["state"] != "paused":
            raise CycleRefused(NOT_PAUSED)
        resumed_at = _now()
        comments = self.comments(mission, cycle=int(row["number"]))
        with self.storage.db:
            self.storage.db.execute(
                "UPDATE studio_cycles SET state='running',resumed_at=?,resumed_by=? WHERE id=?",
                (resumed_at, who, int(row["id"])),
            )
            self.storage.db.execute(
                "INSERT INTO studio_cycles(mission,number,state) VALUES(?,?,'running')",
                (str(mission), int(row["number"]) + 1),
            )
        return Resume(
            int(row["number"]), int(row["number"]) + 1, resumed_at, who, comments,
        )

    # -- reading

    def comments(
        self, mission: str, *, cycle: int | None = None, limit: int = 100
    ) -> tuple[Comment, ...]:
        if cycle is None:
            rows = self.storage.db.execute(
                """SELECT c.*, y.number AS number FROM studio_cycle_comments c
                     JOIN studio_cycles y ON y.id=c.cycle_id
                    WHERE c.mission=? ORDER BY c.id DESC LIMIT ?""",
                (str(mission), int(limit)),
            ).fetchall()
        else:
            rows = self.storage.db.execute(
                """SELECT c.*, y.number AS number FROM studio_cycle_comments c
                     JOIN studio_cycles y ON y.id=c.cycle_id
                    WHERE c.mission=? AND y.number=? ORDER BY c.id LIMIT ?""",
                (str(mission), int(cycle), int(limit)),
            ).fetchall()
        return tuple(
            Comment(
                int(row["id"]), int(row["number"]), row["scope"], row["subject"],
                row["text"], row["author"], row["created_at"],
            )
            for row in rows
        )

    def history(self, mission: str) -> tuple[dict[str, Any], ...]:
        """Every cycle, and which comments belong to it."""
        rows = self.storage.db.execute(
            "SELECT * FROM studio_cycles WHERE mission=? ORDER BY number",
            (str(mission),),
        ).fetchall()
        return tuple(
            {
                "cycle": int(row["number"]),
                "state": row["state"],
                "paused_at": row["paused_at"],
                "paused_by": row["paused_by"],
                "resumed_at": row["resumed_at"],
                "resumed_by": row["resumed_by"],
                "comments": [
                    comment.record()
                    for comment in self.comments(mission, cycle=int(row["number"]))
                ],
            }
            for row in rows
        )

    def report(
        self, mission: str, *, language: str = DEFAULT_LANGUAGE
    ) -> dict[str, Any]:
        chosen = normalise(language)
        state = self.current(mission)
        return {
            **state,
            "note": NOT_REPLANNED_YET.text(chosen),
            "history": list(self.history(mission)),
        }
