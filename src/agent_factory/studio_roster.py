"""Who is in the studio, what adding one more costs, and who checks whose work.

A studio of seven roles on a long backlog costs money and needs several
subscriptions. So the default is two roles working one after another - a planner
and a developer - which is one stream of requests to a model, a predictable
bill, and no race for a rate limit.

Everything else is in the catalogue, switched off. Turning one on is a decision
with a consequence, and the consequence is shown before the switch: roughly what
it adds to the bill, and whether it needs another subscription, because roles
that run at the same time are separate streams to a provider.

Two rules keep the roster honest:

* **A separate reviewer changes who may accept work.** While the developer is
  the only one who can look at their own work, acceptance rests on the engine's
  evidence. The moment a tester is on, the developer no longer accepts their own
  work - that switch is derived from who is enabled, not configured by hand.
* **The added cost is an estimate and says so.** A number with no measured tasks
  behind it is presented as an estimate with its basis, never as a price.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence, TYPE_CHECKING

from .localisation import DEFAULT_LANGUAGE, LocalisedError, Message, normalise

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from .storage import SQLiteStorage

MINIMUM_ROSTER = ("planner", "developer")
SEQUENTIAL = "sequential"
PARALLEL = "parallel"


class RosterRefused(LocalisedError):
    """Raised when a change to the studio would misdescribe what it does."""


UNKNOWN_ROLE = Message(
    "У каталозі немає ролі «{role}».", "The catalogue has no role '{role}'.",
)
CANNOT_DISABLE_CORE = Message(
    "«{role}» — це мінімальний склад студії. Без неї працювати нема кому.",
    "'{role}' is the studio's minimum. Without it there is nobody to do the work.",
)
ACTOR_REQUIRED = Message(
    "Зміну складу записують на конкретну людину. Вкажіть імʼя.",
    "A change to the studio is recorded against a named person. Enter a name.",
)
ALREADY_ON = Message(
    "«{role}» вже увімкнена.", "'{role}' is already on.",
)
ALREADY_OFF = Message(
    "«{role}» і так вимкнена.", "'{role}' is already off.",
)
ESTIMATE_BASIS = Message(
    "Оцінка за {samples} виміряними задачами цієї місії: близько {amount} {unit} "
    "за етап.",
    "An estimate from {samples} measured tasks of this mission: about {amount} "
    "{unit} per stage.",
)
NO_BASIS = Message(
    "Скільки це додасть — невідомо: виміряних задач ще замало.",
    "How much this adds is unknown: there are too few measured tasks yet.",
)
NEEDS_SUBSCRIPTION = Message(
    "Ця роль працюватиме паралельно, тобто це окремий потік до моделі й, "
    "найімовірніше, ще одна підписка.",
    "This role runs at the same time as another, which is a separate stream to a "
    "model and most likely another subscription.",
)
SAME_SUBSCRIPTION = Message(
    "Ролі працюють по черзі, тож вистачить однієї підписки.",
    "The roles take turns, so one subscription is enough.",
)
SELF_ACCEPTANCE = Message(
    "Поки окремого тестувальника немає, приймання тримається на доказах движка.",
    "Until there is a separate tester, acceptance rests on the engine's evidence.",
)
SEPARATE_ACCEPTANCE = Message(
    "Є окремий тестувальник, тож розробник більше не приймає власну роботу.",
    "There is a separate tester, so the developer no longer accepts their own work.",
)


@dataclass(frozen=True)
class Role:
    """One role the studio can have."""

    role_id: str
    title: Message
    duty: Message
    core: bool = False
    reviews: tuple[str, ...] = ()

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "role": self.role_id,
            "title": self.title.text(language),
            "duty": self.duty.text(language),
            "core": self.core,
            "reviews": list(self.reviews),
        }


CATALOGUE: tuple[Role, ...] = (
    Role(
        "planner",
        Message("Планувальник", "Planner"),
        Message(
            "Розбирає ідею, ухвалює дизайнерські рішення, ріже роботу на задачі "
            "й етапи та тримає межі зрізів.",
            "Takes the idea apart, makes the design decisions, cuts the work into "
            "tasks and stages, and holds the slice boundaries.",
        ),
        core=True,
    ),
    Role(
        "developer",
        Message("Розробник", "Developer"),
        Message(
            "Виконує задачі в движку, збирає та готує грабельний зріз.",
            "Carries out the tasks in the engine, builds, and prepares the "
            "playable slice.",
        ),
        core=True,
    ),
    Role(
        "tester",
        Message("Тестувальник", "Tester"),
        Message(
            "Перевіряє роботу окремо від того, хто її зробив.",
            "Checks the work separately from whoever did it.",
        ),
        reviews=("developer",),
    ),
    Role(
        "ui-ux",
        Message("UI/UX", "UI/UX"),
        Message(
            "Робить екрани й керування зрозумілими.",
            "Makes the screens and the controls make sense.",
        ),
    ),
    Role(
        "artist",
        Message("Художник", "Artist"),
        Message(
            "Готує спрайти, тло й інші ресурси гри.",
            "Prepares the sprites, backgrounds and other assets.",
        ),
    ),
    Role(
        "build-engineer",
        Message("Інженер збірки", "Build engineer"),
        Message(
            "Тримає збірку відтворюваною й пояснює її провали.",
            "Keeps the build reproducible and explains its failures.",
        ),
    ),
    Role(
        "sound",
        Message("Звукорежисер", "Sound designer"),
        Message("Звуки та музика гри.", "The game's sound and music."),
    ),
    Role(
        "localisation",
        Message("Локалізація", "Localisation"),
        Message(
            "Тексти гри іншими мовами.", "The game's text in other languages.",
        ),
    ),
    Role(
        "analyst",
        Message("Аналітик", "Analyst"),
        Message(
            "Дивиться, як у гру грають, і що з цього випливає.",
            "Looks at how the game is played, and what follows from it.",
        ),
    ),
)
BY_ID = {role.role_id: role for role in CATALOGUE}

ROSTER_MIGRATION = """
CREATE TABLE studio_roster(
    id INTEGER PRIMARY KEY,
    mission TEXT NOT NULL,
    role TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    concurrency TEXT NOT NULL DEFAULT 'sequential'
        CHECK(concurrency IN ('sequential','parallel')),
    actor TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_studio_roster ON studio_roster(mission, role, id);

-- The roster is a history of decisions about who works on the game and what it
-- costs. A superseding row replaces the state; the old one stays as the record.
CREATE TRIGGER studio_roster_no_update
BEFORE UPDATE ON studio_roster
BEGIN SELECT RAISE(ABORT, 'a roster change is superseded, not edited'); END;
CREATE TRIGGER studio_roster_no_delete
BEFORE DELETE ON studio_roster
BEGIN SELECT RAISE(ABORT, 'a roster change cannot be deleted'); END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Assignment:
    """A role as this mission has it: on or off, and on which model."""

    role: Role
    enabled: bool
    provider: str = ""
    model: str = ""
    concurrency: str = SEQUENTIAL

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            **self.role.record(language),
            "enabled": self.enabled,
            "provider": self.provider,
            "model": self.model,
            "concurrency": self.concurrency,
            "uses_default_model": not self.model,
        }


@dataclass(frozen=True)
class Consequence:
    """What turning a role on would mean, before it is turned on."""

    role: Role
    added_cost: float | None
    unit: str
    basis: Message
    another_subscription: bool
    subscription_note: Message
    acceptance_changes: bool

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "role": self.role.role_id,
            "title": self.role.title.text(language),
            "added_cost": self.added_cost,
            "unit": self.unit,
            "basis": self.basis.text(language),
            "another_subscription": self.another_subscription,
            "subscription_note": self.subscription_note.text(language),
            "acceptance_changes": self.acceptance_changes,
        }


class StudioRoster:
    """Who is on this game, and what changing that would cost."""

    def __init__(self, storage: "SQLiteStorage"):
        self.storage = storage

    # -- state

    def _rows(self, mission: str) -> dict[str, Any]:
        rows = self.storage.db.execute(
            "SELECT * FROM studio_roster WHERE mission=? ORDER BY id",
            (str(mission),),
        ).fetchall()
        latest: dict[str, Any] = {}
        for row in rows:
            latest[row["role"]] = row
        return latest

    def assignments(self, mission: str) -> tuple[Assignment, ...]:
        latest = self._rows(mission)
        result = []
        for role in CATALOGUE:
            row = latest.get(role.role_id)
            if row is None:
                result.append(Assignment(role, role.core))
                continue
            result.append(Assignment(
                role, bool(row["enabled"]), row["provider"], row["model"],
                row["concurrency"],
            ))
        return tuple(result)

    def enabled(self, mission: str) -> tuple[str, ...]:
        return tuple(
            item.role.role_id for item in self.assignments(mission) if item.enabled
        )

    def developer_accepts_own_work(self, mission: str) -> bool:
        """True only while nobody else can check the developer's work."""
        working = set(self.enabled(mission))
        return not any(
            "developer" in BY_ID[role].reviews for role in working if role in BY_ID
        )

    # -- consequences

    def consequence(
        self, mission: str, role_id: str, *, concurrency: str = SEQUENTIAL,
    ) -> Consequence:
        """What adding this role would add, measured where measurement exists."""
        from .studio_cost import MINIMUM_SAMPLES_FOR_FORECAST, StudioCosts

        role = BY_ID.get(str(role_id))
        if role is None:
            raise RosterRefused(UNKNOWN_ROLE, role=role_id)
        costs = StudioCosts(self.storage)
        measured = costs.measured_tasks(mission)
        limit = costs.limit(mission)
        unit = limit.unit if limit else "USD"
        if len(measured) < MINIMUM_SAMPLES_FOR_FORECAST:
            amount, basis = None, NO_BASIS
        else:
            average = sum(measured) / len(measured)
            amount = round(average * len(measured), 6)
            basis = Message(
                ESTIMATE_BASIS.uk.format(
                    samples=len(measured), amount=f"{amount:.2f}", unit=unit),
                ESTIMATE_BASIS.en.format(
                    samples=len(measured), amount=f"{amount:.2f}", unit=unit),
            )
        parallel = concurrency == PARALLEL
        return Consequence(
            role, amount, unit, basis, parallel,
            NEEDS_SUBSCRIPTION if parallel else SAME_SUBSCRIPTION,
            acceptance_changes=(
                "developer" in role.reviews and self.developer_accepts_own_work(mission)
            ),
        )

    # -- changing

    def _write(
        self,
        mission: str,
        role_id: str,
        *,
        enabled: bool,
        actor: str,
        provider: str = "",
        model: str = "",
        concurrency: str = SEQUENTIAL,
        reason: str = "",
    ) -> None:
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO studio_roster
                   (mission,role,enabled,provider,model,concurrency,actor,reason,changed_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    str(mission), str(role_id), int(enabled), str(provider),
                    str(model), concurrency, str(actor), str(reason), _now(),
                ),
            )

    def enable(
        self,
        mission: str,
        role_id: str,
        *,
        actor: str,
        provider: str = "",
        model: str = "",
        concurrency: str = SEQUENTIAL,
        reason: str = "",
    ) -> Consequence:
        """Turn a role on, after the consequence has been produced for it."""
        who = str(actor).strip()
        if not who:
            raise RosterRefused(ACTOR_REQUIRED)
        role = BY_ID.get(str(role_id))
        if role is None:
            raise RosterRefused(UNKNOWN_ROLE, role=role_id)
        if role.role_id in self.enabled(mission):
            raise RosterRefused(ALREADY_ON, role=role.role_id)
        if concurrency not in (SEQUENTIAL, PARALLEL):
            raise ValueError(f"Unknown concurrency: {concurrency!r}")
        consequence = self.consequence(mission, role.role_id, concurrency=concurrency)
        self._write(
            mission, role.role_id, enabled=True, actor=who, provider=provider,
            model=model, concurrency=concurrency, reason=reason,
        )
        return consequence

    def disable(self, mission: str, role_id: str, *, actor: str, reason: str = "") -> None:
        who = str(actor).strip()
        if not who:
            raise RosterRefused(ACTOR_REQUIRED)
        role = BY_ID.get(str(role_id))
        if role is None:
            raise RosterRefused(UNKNOWN_ROLE, role=role_id)
        if role.core:
            raise RosterRefused(CANNOT_DISABLE_CORE, role=role.role_id)
        if role.role_id not in self.enabled(mission):
            raise RosterRefused(ALREADY_OFF, role=role.role_id)
        self._write(mission, role.role_id, enabled=False, actor=who, reason=reason)

    def assign_model(
        self,
        mission: str,
        role_id: str,
        *,
        provider: str,
        model: str,
        actor: str,
        reason: str = "",
    ) -> Assignment:
        """Give one role its own provider and model. No model means the default."""
        who = str(actor).strip()
        if not who:
            raise RosterRefused(ACTOR_REQUIRED)
        role = BY_ID.get(str(role_id))
        if role is None:
            raise RosterRefused(UNKNOWN_ROLE, role=role_id)
        current = {item.role.role_id: item for item in self.assignments(mission)}[
            role.role_id
        ]
        self._write(
            mission, role.role_id, enabled=current.enabled, actor=who,
            provider=provider, model=model, concurrency=current.concurrency,
            reason=reason,
        )
        return Assignment(role, current.enabled, str(provider), str(model),
                          current.concurrency)

    # -- reading

    def history(self, mission: str, *, limit: int = 50) -> tuple[dict[str, Any], ...]:
        rows = self.storage.db.execute(
            "SELECT * FROM studio_roster WHERE mission=? ORDER BY id DESC LIMIT ?",
            (str(mission), int(limit)),
        ).fetchall()
        return tuple(
            {
                "role": row["role"], "enabled": bool(row["enabled"]),
                "provider": row["provider"], "model": row["model"],
                "concurrency": row["concurrency"], "actor": row["actor"],
                "reason": row["reason"], "changed_at": row["changed_at"],
            }
            for row in rows
        )

    def report(self, mission: str, *, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        chosen = normalise(language)
        assignments = self.assignments(mission)
        own_work = self.developer_accepts_own_work(mission)
        return {
            "mission": str(mission),
            "enabled": list(self.enabled(mission)),
            "minimum": list(MINIMUM_ROSTER),
            "roles": [item.record(chosen) for item in assignments],
            "acceptance": (
                SELF_ACCEPTANCE if own_work else SEPARATE_ACCEPTANCE
            ).text(chosen),
            "developer_accepts_own_work": own_work,
            "history": list(self.history(mission)),
        }
