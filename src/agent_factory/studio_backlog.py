"""The plan of work as the person who asked for the game sees it.

The engineering view is right for engineers: stable identifiers, weights,
labels, the difference between an identifier appearing in a commit subject and
work actually being accepted. None of that belongs on the screen of someone who
asked for a game about a cat collecting coins.

This module turns a plan into what that person can read, and refuses the three
ways such a view usually lies:

* an internal code presented as a name - a title that still carries one is
  refused, rather than shown with an apology;
* "done" claimed because an identifier turned up in a commit subject - work is
  done only when it was accepted, and a mention is progress, nothing more;
* a stage that ends in silence - every stage states its boundary, either a
  playable slice with the version behind it, or an explicit "there is nothing
  to test here yet".

The rendering starts nothing and changes nothing. It reads a live mission's own
backlog when asked to, and otherwise works from whatever plan the caller hands
it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .localisation import DEFAULT_LANGUAGE, LocalisedError, Message

PLAN_STATES = ("planned", "in_progress", "done", "blocked")
BOUNDARIES = ("playable", "nothing_to_test")

# Anything shaped like a planning identifier is an internal code: AF-GC-024,
# AF-ST-E3, AF-001. They are how the work is tracked, not what it is called.
INTERNAL_CODE = re.compile(r"\bAF-(?:[A-Z]{1,4}-)?(?:E?\d{1,4})\b")


class BacklogRefused(LocalisedError):
    """Raised when showing this would mean showing something untrue."""


INTERNAL_IN_TITLE = Message(
    "У назві «{title}» лишився внутрішній код. Людині показують назву, а не код.",
    "The title '{title}' still carries an internal code. A person is shown a "
    "name, not a code.",
)
EMPTY_TITLE = Message(
    "Назва не може бути порожньою.", "A title cannot be empty.",
)
PLAYABLE_WITHOUT_VERSION = Message(
    "Етап не можна назвати грабельним без версії, яку справді зібрано.",
    "A stage cannot be called playable without a version that was actually built.",
)
NOTHING_TO_TEST = Message(
    "На цьому етапі ще нема чого тестувати.",
    "There is nothing to test at this stage yet.",
)

STATE_LABELS = {
    "planned": Message("Заплановано", "Planned"),
    "in_progress": Message("В роботі", "In progress"),
    "done": Message("Зроблено", "Done"),
    "blocked": Message("Заблоковано", "Blocked"),
}
MENTIONED_ONLY = Message(
    "Згадано в комітах, але ще не прийнято.",
    "Mentioned in commits, but not accepted yet.",
)


def human_title(title: str) -> str:
    """The title with its internal code taken off the front, if it had one."""
    cleaned = INTERNAL_CODE.sub("", str(title))
    return re.sub(r"\s+", " ", cleaned).strip(" -–—:·").strip()


def state_of(*, accepted: bool, blocked: bool = False, started: bool = False) -> str:
    """Accepted work is done. A mention in a commit is not acceptance."""
    if accepted:
        return "done"
    if blocked:
        return "blocked"
    return "in_progress" if started else "planned"


@dataclass(frozen=True)
class Item:
    """One task, in the words of the person who will read it."""

    key: str
    title: Message
    state: str
    role: Message | None = None
    note: Message | None = None
    blocked_by: tuple[Message, ...] = ()

    @classmethod
    def create(
        cls,
        key: str,
        title: Message,
        state: str,
        *,
        role: Message | None = None,
        note: Message | None = None,
        blocked_by: Sequence[Message] = (),
    ) -> "Item":
        if state not in PLAN_STATES:
            raise ValueError(f"Unknown state: {state!r}")
        for language in ("uk", "en"):
            text = getattr(title, language)
            if not str(text).strip():
                raise BacklogRefused(EMPTY_TITLE)
            if INTERNAL_CODE.search(text):
                raise BacklogRefused(INTERNAL_IN_TITLE, title=text)
        return cls(str(key), title, state, role, note, tuple(blocked_by))

    @property
    def done(self) -> bool:
        return self.state == "done"

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "title": self.title.text(language),
            "state": self.state,
            "state_label": STATE_LABELS[self.state].text(language),
            "role": self.role.text(language) if self.role else "",
            "note": self.note.text(language) if self.note else "",
            "blocked_by": [item.text(language) for item in self.blocked_by],
        }


@dataclass(frozen=True)
class Stage:
    """A group of tasks that ends in something, and says what."""

    stage_id: str
    title: Message
    items: tuple[Item, ...]
    boundary: str = "nothing_to_test"
    playable_version: str = ""
    boundary_note: Message | None = None

    def __post_init__(self) -> None:
        if self.boundary not in BOUNDARIES:
            raise ValueError(f"Unknown boundary: {self.boundary!r}")
        if self.boundary == "playable" and not self.playable_version:
            raise BacklogRefused(PLAYABLE_WITHOUT_VERSION)

    @property
    def counts(self) -> dict[str, int]:
        counted = {state: 0 for state in PLAN_STATES}
        for item in self.items:
            counted[item.state] += 1
        return counted

    @property
    def done(self) -> bool:
        return bool(self.items) and all(item.done for item in self.items)

    def record(
        self, language: str = DEFAULT_LANGUAGE, *, handle: str = "",
    ) -> dict[str, Any]:
        """The stage as the reader sees it.

        The internal identifier is deliberately not here. A screen needs a way
        to address a stage, so it gets a handle that means nothing outside this
        rendering; an identifier in the record is an identifier that ends up on
        the screen.
        """
        note = self.boundary_note or (
            None if self.boundary == "playable" else NOTHING_TO_TEST
        )
        return {
            "handle": handle,
            "title": self.title.text(language),
            "counts": self.counts,
            "done": self.done,
            "boundary": self.boundary,
            "playable_version": self.playable_version,
            "boundary_note": note.text(language) if note else "",
            "items": [item.record(language) for item in self.items],
        }


NOTHING_LEFT = Message(
    "Усе заплановане зроблено.", "Everything planned is done.",
)
WAITING = Message(
    "Наступний крок чекає, поки знімуть блокування.",
    "The next step is waiting for something to be unblocked.",
)


@dataclass(frozen=True)
class Plan:
    """The whole plan, by stage, for one game."""

    project: Message
    stages: tuple[Stage, ...]

    @property
    def items(self) -> tuple[Item, ...]:
        return tuple(item for stage in self.stages for item in stage.items)

    @property
    def next_up(self) -> Item | None:
        """What is being worked on now, or what would be picked up next."""
        for item in self.items:
            if item.state == "in_progress":
                return item
        for item in self.items:
            if item.state == "planned":
                return item
        return None

    @property
    def counts(self) -> dict[str, int]:
        counted = {state: 0 for state in PLAN_STATES}
        for item in self.items:
            counted[item.state] += 1
        return counted

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        following = self.next_up
        if following is not None:
            next_text = following.title.text(language)
        elif any(item.state == "blocked" for item in self.items):
            next_text = WAITING.text(language)
        else:
            next_text = NOTHING_LEFT.text(language)
        return {
            "project": self.project.text(language),
            "counts": self.counts,
            "playable": [
                stage.playable_version for stage in self.stages
                if stage.boundary == "playable"
            ],
            "next": next_text,
            "stages": [
                stage.record(language, handle=f"stage-{index}")
                for index, stage in enumerate(self.stages, start=1)
            ],
        }


ROLE_LABELS = {
    "planner": Message("Планувальник", "Planner"),
    "developer": Message("Розробник", "Developer"),
    "tester": Message("Тестувальник", "Tester"),
    "artist": Message("Художник", "Artist"),
    "ui-ux": Message("UI/UX", "UI/UX"),
    "build-engineer": Message("Інженер збірки", "Build engineer"),
}


def role_label(role_id: str) -> Message | None:
    """A role in words the reader knows, or nothing rather than a raw identifier."""
    return ROLE_LABELS.get(str(role_id).strip().lower())


def from_progress(
    tasks: Iterable[Any],
    *,
    project: Message,
    stage_titles: dict[str, Message] | None = None,
    playable: dict[str, str] | None = None,
) -> Plan:
    """Turn the engineering progress view into the one a person reads.

    ``tasks`` are :class:`agent_factory.progress.TaskProgress` records or
    anything with the same fields. A task that is only mentioned in a commit is
    in progress and carries that as its note: the engineering view calls that
    field ``merged``, and it means an identifier appeared in a commit subject.
    """
    titles = dict(stage_titles or {})
    slices = dict(playable or {})
    grouped: dict[str, list[Item]] = {}
    for task in tasks:
        stage_id = str(getattr(task, "block", "") or getattr(task, "manifest", "") or "plan")
        mentioned = bool(getattr(task, "merged", False))
        blocked_by = tuple(getattr(task, "blocked_by", ()) or ())
        item = Item.create(
            str(getattr(task, "stable_id", "")),
            Message(
                human_title(getattr(task, "title", "")),
                human_title(getattr(task, "title", "")),
            ),
            state_of(
                accepted=bool(getattr(task, "accepted", False)),
                blocked=bool(blocked_by) or bool(getattr(task, "explicitly_blocked", False)),
                started=mentioned,
            ),
            role=role_label(getattr(task, "role", "")),
            note=MENTIONED_ONLY if mentioned and not getattr(task, "accepted", False) else None,
        )
        grouped.setdefault(stage_id, []).append(item)
    stages = []
    for stage_id, items in grouped.items():
        version = slices.get(stage_id, "")
        stages.append(Stage(
            stage_id,
            titles.get(stage_id, Message(stage_id, stage_id)),
            tuple(items),
            boundary="playable" if version else "nothing_to_test",
            playable_version=version,
        ))
    return Plan(project, tuple(stages))


# -------------------------------------------------- the plan of a live mission

MISSION_STATES = {
    "DONE": "done",
    "RUNNING": "in_progress",
    "READY": "planned",
    "PROPOSED": "planned",
    "STALE": "planned",
    "BLOCKED": "blocked",
    "FAILED": "blocked",
}
FAILED_NOTE = Message(
    "Спроба не вдалася; наступна спроба чекає на рішення.",
    "An attempt failed; the next one is waiting on a decision.",
)
STALE_NOTE = Message(
    "План змінився, і цю задачу треба переглянути.",
    "The plan changed, and this task needs a fresh look.",
)
NO_STAGE = Message("Решта роботи", "The rest of the work")
UNKNOWN_MISSION = Message(
    "Такої місії немає: {mission}.", "There is no such mission: {mission}.",
)


def from_mission(
    storage: Any,
    mission_key: str,
    *,
    project: Message | None = None,
    playable: dict[str, str] | None = None,
) -> Plan:
    """Read a live mission's own backlog and render it for the person.

    The engineering statuses are `DONE`, `RUNNING`, `READY`, `BLOCKED`,
    `FAILED`, `STALE` and `PROPOSED`. A person needs four, so `FAILED` reads as
    blocked with the reason attached rather than as a fifth word they have to
    learn, and `STALE` reads as planned with a note that the plan moved.
    """
    mission = storage.db.execute(
        "SELECT id,name FROM autonomous_missions WHERE mission_key=?",
        (str(mission_key),),
    ).fetchone()
    if mission is None:
        raise BacklogRefused(UNKNOWN_MISSION, mission=mission_key)
    revision = storage.db.execute(
        """SELECT id FROM autonomous_backlog_revisions
            WHERE mission_id=? ORDER BY revision_number DESC LIMIT 1""",
        (int(mission["id"]),),
    ).fetchone()
    if revision is None:
        return Plan(project or Message(mission["name"], mission["name"]), ())
    rows = storage.db.execute(
        """SELECT i.stable_id,i.title,i.kind,i.executable,i.parent_stable_id,
                  (SELECT s.status FROM autonomous_backlog_item_states s
                    WHERE s.item_id=i.id ORDER BY s.sequence DESC LIMIT 1) AS status
             FROM autonomous_backlog_items i
            WHERE i.revision_id=? ORDER BY i.id""",
        (int(revision["id"]),),
    ).fetchall()
    titles = {
        row["stable_id"]: human_title(row["title"]) for row in rows
    }
    slices = dict(playable or {})
    grouped: dict[str, list[Item]] = {}
    for row in rows:
        if not int(row["executable"]):
            continue  # an epic is the stage, not a task inside it
        status = str(row["status"] or "PROPOSED")
        note = FAILED_NOTE if status == "FAILED" else (
            STALE_NOTE if status == "STALE" else None
        )
        name = human_title(row["title"])
        item = Item.create(
            str(row["stable_id"]),
            Message(name, name),
            MISSION_STATES.get(status, "planned"),
            note=note,
        )
        grouped.setdefault(str(row["parent_stable_id"] or ""), []).append(item)
    stages = []
    for parent, items in grouped.items():
        title = titles.get(parent) if parent else None
        version = slices.get(parent, "")
        stages.append(Stage(
            parent or "rest",
            Message(title, title) if title else NO_STAGE,
            tuple(items),
            boundary="playable" if version else "nothing_to_test",
            playable_version=version,
        ))
    name = mission["name"]
    return Plan(project or Message(name, name), tuple(stages))
