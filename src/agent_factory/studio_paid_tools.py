"""When the work needs something you have to pay for.

A task that hits Unity, a paid asset pack or a paid service must not end the
game. It becomes a choice with four ways out, and every one of them leaves the
mission able to continue:

* **use my own subscription** - the person logs in themselves;
* **buy it through the platform**;
* **take the free alternative** the studio suggests;
* **decline** - and the plan is rebuilt without it, saying plainly what that
  costs in features.

Two rules hold whatever they choose. Declining is a real answer, not a failure:
it records the constraint and names what is cut, so the person sees the price of
their decision instead of discovering it later in a game that quietly lacks
something. And credentials for paid software are the person's own: this module
has nowhere to put a licence key, a password or a token, and asks for none. What
it records is which way out was chosen, by whom, and when.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence, TYPE_CHECKING

from .localisation import DEFAULT_LANGUAGE, LocalisedError, Message, normalise, verbatim

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from .storage import SQLiteStorage

WAYS_OUT = ("own_subscription", "buy_through_platform", "free_alternative", "decline")
STATES = ("open", "answered")


class PaidToolRefused(LocalisedError):
    """Raised when answering this would misdescribe what happens next."""


UNKNOWN_WAY_OUT = Message(
    "«{choice}» не є одним із чотирьох варіантів.",
    "'{choice}' is not one of the four ways out.",
)
ACTOR_REQUIRED = Message(
    "Вибір записується на конкретну людину. Вкажіть імʼя.",
    "A choice is recorded against a named person. Enter a name.",
)
ALREADY_ANSWERED = Message(
    "На цей вибір уже відповіли.", "This choice has already been answered.",
)
NOTHING_CUT = Message(
    "Нічого не відрізано.", "Nothing was cut.",
)
CUT_BY_DECLINE = Message(
    "Через відмову від «{tool}» з плану прибрано: {cut}.",
    "Declining {tool} removes this from the plan: {cut}.",
)
NO_CREDENTIALS = Message(
    "Логін і ключі до платного інструмента вводить людина у самому інструменті. "
    "Ми їх не питаємо і не зберігаємо.",
    "The login and keys for a paid tool are entered by the person, in that tool. "
    "We neither ask for them nor store them.",
)

WAY_OUT_LABELS = {
    "own_subscription": Message(
        "Маю власну підписку — увійду сам",
        "I have my own subscription — I will sign in myself",
    ),
    "buy_through_platform": Message(
        "Оформити через платформу", "Arrange it through the platform",
    ),
    "free_alternative": Message(
        "Взяти безкоштовну заміну", "Take the free alternative",
    ),
    "decline": Message(
        "Відмовитись і перебудувати план", "Decline and rebuild the plan",
    ),
}

PAID_TOOL_MIGRATION = """
CREATE TABLE studio_paid_tool_choices(
    id INTEGER PRIMARY KEY,
    mission TEXT NOT NULL,
    tool TEXT NOT NULL,
    task_key TEXT NOT NULL DEFAULT '',
    reason_uk TEXT NOT NULL,
    reason_en TEXT NOT NULL,
    alternative_uk TEXT NOT NULL DEFAULT '',
    alternative_en TEXT NOT NULL DEFAULT '',
    blocks_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(blocks_json)),
    state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','answered')),
    choice TEXT NOT NULL DEFAULT '',
    answered_by TEXT NOT NULL DEFAULT '',
    answered_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_studio_paid_tools ON studio_paid_tool_choices(mission, state, id);

-- The question and what it blocks are the record of why the plan looks the way
-- it does. Only the answer arrives later.
CREATE TRIGGER studio_paid_tool_choices_answer_only
BEFORE UPDATE ON studio_paid_tool_choices
WHEN OLD.state <> 'open' OR OLD.tool <> NEW.tool
  OR OLD.blocks_json <> NEW.blocks_json OR OLD.reason_uk <> NEW.reason_uk
BEGIN SELECT RAISE(ABORT, 'a paid-tool choice may only gain its answer'); END;
CREATE TRIGGER studio_paid_tool_choices_no_delete
BEFORE DELETE ON studio_paid_tool_choices
BEGIN SELECT RAISE(ABORT, 'a paid-tool choice cannot be deleted'); END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Choice:
    """One paid tool in the way, and the four ways past it."""

    choice_id: int
    mission: str
    tool: str
    reason: Message
    blocks: tuple[str, ...]
    alternative: Message | None = None
    task_key: str = ""
    state: str = "open"
    chosen: str = ""
    answered_by: str = ""
    answered_at: str = ""

    @property
    def ways_out(self) -> tuple[str, ...]:
        """Every way out, minus the alternative when there is not one to offer."""
        if self.alternative is None:
            return tuple(way for way in WAYS_OUT if way != "free_alternative")
        return WAYS_OUT

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "choice_id": self.choice_id,
            "mission": self.mission,
            "tool": self.tool,
            "task": self.task_key,
            "reason": self.reason.text(language),
            "alternative": self.alternative.text(language) if self.alternative else "",
            "blocks": list(self.blocks),
            "ways_out": [
                {"key": way, "label": WAY_OUT_LABELS[way].text(language)}
                for way in self.ways_out
            ],
            "state": self.state,
            "chosen": self.chosen,
            "answered_by": self.answered_by,
            "answered_at": self.answered_at,
            "credentials": NO_CREDENTIALS.text(language),
        }


@dataclass(frozen=True)
class Rebuild:
    """What declining actually costs, named rather than discovered later."""

    tool: str
    cut: tuple[str, ...]
    summary: Message

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "cut": list(self.cut),
            "summary": self.summary.text(language),
        }


class PaidTools:
    """Every paid tool the work ran into, and what was decided about it."""

    def __init__(self, storage: "SQLiteStorage"):
        self.storage = storage

    def ask(
        self,
        mission: str,
        tool: str,
        *,
        reason: Message,
        blocks: Sequence[str] = (),
        alternative: Message | None = None,
        task_key: str = "",
    ) -> Choice:
        """Put the choice to the person. The rest of the plan keeps moving."""
        created_at = _now()
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO studio_paid_tool_choices
                   (mission,tool,task_key,reason_uk,reason_en,alternative_uk,
                    alternative_en,blocks_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    str(mission), str(tool), str(task_key), reason.uk, reason.en,
                    alternative.uk if alternative else "",
                    alternative.en if alternative else "",
                    json.dumps([str(item) for item in blocks]), created_at,
                ),
            )
        return Choice(
            int(cursor.lastrowid), str(mission), str(tool), reason,
            tuple(str(item) for item in blocks), alternative, str(task_key),
        )

    def answer(
        self, choice_id: int, *, choice: str, actor: str,
    ) -> tuple[Choice, Rebuild | None]:
        """Record the way out, and say what declining removes from the plan."""
        who = str(actor).strip()
        if not who:
            raise PaidToolRefused(ACTOR_REQUIRED)
        stored = self._row(choice_id)
        if stored.state != "open":
            raise PaidToolRefused(ALREADY_ANSWERED)
        if choice not in stored.ways_out:
            raise PaidToolRefused(UNKNOWN_WAY_OUT, choice=choice)
        answered_at = _now()
        with self.storage.db:
            self.storage.db.execute(
                """UPDATE studio_paid_tool_choices
                      SET state='answered',choice=?,answered_by=?,answered_at=?
                    WHERE id=?""",
                (str(choice), who, answered_at, int(choice_id)),
            )
        answered = Choice(
            stored.choice_id, stored.mission, stored.tool, stored.reason,
            stored.blocks, stored.alternative, stored.task_key, "answered",
            str(choice), who, answered_at,
        )
        if choice != "decline":
            return answered, None
        summary = Message(
            CUT_BY_DECLINE.uk.format(
                tool=stored.tool,
                cut=", ".join(stored.blocks) if stored.blocks else NOTHING_CUT.uk,
            ),
            CUT_BY_DECLINE.en.format(
                tool=stored.tool,
                cut=", ".join(stored.blocks) if stored.blocks else NOTHING_CUT.en,
            ),
        )
        return answered, Rebuild(stored.tool, stored.blocks, summary)

    # -- reading

    def _row(self, choice_id: int) -> Choice:
        row = self.storage.db.execute(
            "SELECT * FROM studio_paid_tool_choices WHERE id=?", (int(choice_id),)
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown paid-tool choice {choice_id}")
        alternative = (
            Message(row["alternative_uk"], row["alternative_en"])
            if row["alternative_uk"] and row["alternative_en"] else None
        )
        return Choice(
            int(row["id"]), row["mission"], row["tool"],
            Message(row["reason_uk"], row["reason_en"]),
            tuple(json.loads(row["blocks_json"])), alternative, row["task_key"],
            row["state"], row["choice"], row["answered_by"], row["answered_at"],
        )

    def open_choices(self, mission: str) -> tuple[Choice, ...]:
        rows = self.storage.db.execute(
            "SELECT id FROM studio_paid_tool_choices WHERE mission=? AND state='open' ORDER BY id",
            (str(mission),),
        ).fetchall()
        return tuple(self._row(int(row["id"])) for row in rows)

    def declined(self, mission: str) -> tuple[Choice, ...]:
        rows = self.storage.db.execute(
            """SELECT id FROM studio_paid_tool_choices
                WHERE mission=? AND state='answered' AND choice='decline' ORDER BY id""",
            (str(mission),),
        ).fetchall()
        return tuple(self._row(int(row["id"])) for row in rows)

    def cut(self, mission: str) -> tuple[str, ...]:
        """Everything the plan no longer contains because a paid tool was declined."""
        return tuple(sorted({
            item for choice in self.declined(mission) for item in choice.blocks
        }))

    def blocked(self, mission: str) -> tuple[str, ...]:
        """What is waiting on an unanswered choice - and nothing else."""
        return tuple(sorted({
            item for choice in self.open_choices(mission) for item in choice.blocks
        }))

    def report(
        self, mission: str, *, language: str = DEFAULT_LANGUAGE
    ) -> dict[str, Any]:
        chosen = normalise(language)
        rows = self.storage.db.execute(
            "SELECT id FROM studio_paid_tool_choices WHERE mission=? ORDER BY id",
            (str(mission),),
        ).fetchall()
        history = [self._row(int(row["id"])) for row in rows]
        return {
            "mission": str(mission),
            "open": [item.record(chosen) for item in history if item.state == "open"],
            "blocked": list(self.blocked(mission)),
            "cut": list(self.cut(mission)),
            "history": [item.record(chosen) for item in history],
            "credentials": NO_CREDENTIALS.text(chosen),
        }


def alternative_of(name: str) -> Message:
    """A named free replacement, taken as given rather than translated."""
    return verbatim(name)
