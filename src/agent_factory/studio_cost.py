"""What the game has cost so far, and what it would cost to finish this stage.

Three numbers a person actually needs, and the rules that keep each one honest:

* **spent** is what a provider reported. It is gone, and no stop recovers it.
* **reserved** is an estimate for work already committed but not yet billed. A
  stop releases it, so calling it spent would overstate the loss.
* **the forecast** is arithmetic on measured tasks of this very mission. Fewer
  than three measured tasks is not a basis for a number, and the forecast then
  says it does not know, with the reason.

Spend is attributed to the role and provider that incurred it, where that was
recorded. Spend with no role recorded is shown as unattributed rather than
spread across the roles to make the table look complete.

The limit is what a person set, and going over it is a question for them, never
a decision this module makes on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence, TYPE_CHECKING

from .localisation import DEFAULT_LANGUAGE, LocalisedError, Message, normalise

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from .storage import SQLiteStorage

KINDS = ("reported", "estimated")
MINIMUM_SAMPLES_FOR_FORECAST = 3
UNATTRIBUTED = "unattributed"


class CostRefused(LocalisedError):
    """Raised when recording or claiming this would misstate the money."""


NEGATIVE_AMOUNT = Message(
    "Витрата не може бути відʼємною.", "A cost cannot be negative.",
)
UNKNOWN_KIND = Message(
    "Незрозумілий вид витрати: {kind}. Або провайдер її повідомив, або це оцінка.",
    "Unknown kind of cost: {kind}. Either a provider reported it, or it is an "
    "estimate.",
)
LIMIT_REQUIRED = Message(
    "Ліміт встановлює названа людина.", "A limit is set by a named person.",
)
NO_SAMPLES = Message(
    "Прогнозу немає: ще не завершено жодної виміряної задачі.",
    "No forecast: no measured task has finished yet.",
)
TOO_FEW = Message(
    "Прогнозу немає: виміряних задач замало, щоб рахувати чесно.",
    "No forecast: too few measured tasks to be honest about it.",
)
NO_LIMIT = Message(
    "Ліміт не встановлено, тож зупиняти нема на чому.",
    "No limit is set, so there is nothing to stop at.",
)
WITHIN_LIMIT = Message(
    "У межах ліміту: витрачено й зарезервовано {committed} з {limit} {unit}.",
    "Within the limit: {committed} of {limit} {unit} committed.",
)
OVER_LIMIT = Message(
    "Ліміт вичерпано: {committed} з {limit} {unit}.",
    "The limit is used up: {committed} of {limit} {unit}.",
)

COST_MIGRATION = """
CREATE TABLE studio_spend(
    id INTEGER PRIMARY KEY,
    mission TEXT NOT NULL,
    task_key TEXT NOT NULL DEFAULT '',
    stage_key TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL CHECK(kind IN ('reported','estimated')),
    amount REAL NOT NULL CHECK(amount >= 0),
    unit TEXT NOT NULL DEFAULT 'USD',
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_studio_spend_mission ON studio_spend(mission, id);

CREATE TABLE studio_limits(
    id INTEGER PRIMARY KEY,
    mission TEXT NOT NULL,
    amount REAL NOT NULL CHECK(amount >= 0),
    unit TEXT NOT NULL DEFAULT 'USD',
    set_by TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    set_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_studio_limits_mission ON studio_limits(mission, id);

-- Money already spent is a fact about the past. A ledger that can be edited is
-- not a ledger, and a limit whose history can be rewritten cannot show who
-- raised it.
CREATE TRIGGER studio_spend_no_update
BEFORE UPDATE ON studio_spend
BEGIN SELECT RAISE(ABORT, 'recorded spend cannot be rewritten'); END;
CREATE TRIGGER studio_spend_no_delete
BEFORE DELETE ON studio_spend
BEGIN SELECT RAISE(ABORT, 'recorded spend cannot be deleted'); END;
CREATE TRIGGER studio_limits_no_update
BEFORE UPDATE ON studio_limits
BEGIN SELECT RAISE(ABORT, 'a limit is superseded, not edited'); END;
"""


# A reservation is money held for work that has not been billed yet. Once the
# provider reports what that task cost, the estimate stops being a reservation:
# it stays in the ledger as what was expected, and the reported cost is what is
# owed. Counting both would double the money.
STILL_RESERVED = """kind='estimated' AND (task_key='' OR task_key NOT IN (
    SELECT task_key FROM studio_spend billed
     WHERE billed.mission=s.mission AND billed.kind='reported' AND billed.task_key<>''
))"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _round(value: float) -> float:
    return round(float(value), 6)


@dataclass(frozen=True)
class Forecast:
    """What finishing the stage would cost, or why that is not known."""

    amount: float | None
    basis: Message
    unit: str = "USD"

    @property
    def known(self) -> bool:
        return self.amount is not None

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "known": self.known,
            "amount": self.amount,
            "unit": self.unit,
            "basis": self.basis.text(language),
        }


def forecast_remaining(
    *,
    measured: Sequence[float],
    remaining_tasks: int,
    unit: str = "USD",
) -> Forecast:
    """Only measured tasks of this mission may produce a number."""
    samples = [float(value) for value in measured if float(value) > 0]
    if not samples:
        return Forecast(None, NO_SAMPLES, unit)
    if len(samples) < MINIMUM_SAMPLES_FOR_FORECAST:
        return Forecast(None, TOO_FEW, unit)
    if remaining_tasks <= 0:
        return Forecast(0.0, Message(
            "Задач у цьому етапі не лишилось.", "No task remains in this stage.",
        ), unit)
    average = sum(samples) / len(samples)
    return Forecast(_round(average * remaining_tasks), Message(
        f"За {len(samples)} виміряними задачами, у середньому {average:.2f} {unit} кожна.",
        f"From {len(samples)} measured tasks, averaging {average:.2f} {unit} each.",
    ), unit)


@dataclass(frozen=True)
class Limit:
    """What a person allowed, and who allowed it."""

    amount: float
    unit: str
    set_by: str
    set_at: str
    reason: str = ""

    def record(self) -> dict[str, Any]:
        return {
            "amount": self.amount, "unit": self.unit, "set_by": self.set_by,
            "set_at": self.set_at, "reason": self.reason,
        }


class StudioCosts:
    """The money of one mission: what went, what is held, what a step would need."""

    def __init__(self, storage: "SQLiteStorage"):
        self.storage = storage

    # -- recording

    def record(
        self,
        mission: str,
        *,
        amount: float,
        kind: str = "reported",
        task_key: str = "",
        stage_key: str = "",
        role: str = "",
        provider: str = "",
        model: str = "",
        unit: str = "USD",
    ) -> None:
        """Write one cost down, attributed to whoever incurred it."""
        if kind not in KINDS:
            raise CostRefused(UNKNOWN_KIND, kind=kind)
        if float(amount) < 0:
            raise CostRefused(NEGATIVE_AMOUNT)
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO studio_spend
                   (mission,task_key,stage_key,role,provider,model,kind,amount,unit,
                    recorded_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(mission), str(task_key), str(stage_key), str(role),
                    str(provider), str(model), kind, float(amount), str(unit),
                    _now(),
                ),
            )

    def settle(
        self, mission: str, task_key: str, *, amount: float, unit: str = "USD", **rest: Any
    ) -> None:
        """Record what a task actually cost, once the provider has reported it.

        Nothing is rewritten: the estimate stays in the ledger, and stops being
        counted as reserved because the task it was reserved for is now billed.
        A settled task therefore shows both what was expected and what it cost.
        """
        self.record(
            mission, amount=amount, kind="reported", task_key=task_key, unit=unit, **rest,
        )

    def set_limit(
        self, mission: str, *, amount: float, actor: str, unit: str = "USD", reason: str = "",
    ) -> Limit:
        who = str(actor).strip()
        if not who:
            raise CostRefused(LIMIT_REQUIRED)
        if float(amount) < 0:
            raise CostRefused(NEGATIVE_AMOUNT)
        set_at = _now()
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO studio_limits(mission,amount,unit,set_by,reason,set_at)
                   VALUES(?,?,?,?,?,?)""",
                (str(mission), float(amount), str(unit), who, str(reason), set_at),
            )
        return Limit(float(amount), str(unit), who, set_at, str(reason))

    # -- reading

    def limit(self, mission: str) -> Limit | None:
        row = self.storage.db.execute(
            "SELECT * FROM studio_limits WHERE mission=? ORDER BY id DESC LIMIT 1",
            (str(mission),),
        ).fetchone()
        if row is None:
            return None
        return Limit(
            float(row["amount"]), row["unit"], row["set_by"], row["set_at"],
            row["reason"],
        )

    def limit_history(self, mission: str) -> tuple[Limit, ...]:
        rows = self.storage.db.execute(
            "SELECT * FROM studio_limits WHERE mission=? ORDER BY id",
            (str(mission),),
        ).fetchall()
        return tuple(
            Limit(float(row["amount"]), row["unit"], row["set_by"], row["set_at"],
                  row["reason"])
            for row in rows
        )

    def totals(self, mission: str) -> dict[str, float]:
        row = self.storage.db.execute(
            f"""SELECT COALESCE(SUM(CASE WHEN kind='reported' THEN amount END),0) AS spent,
                       COALESCE(SUM(CASE WHEN {STILL_RESERVED} THEN amount END),0) AS reserved
                  FROM studio_spend s WHERE mission=?""",
            (str(mission),),
        ).fetchone()
        spent, reserved = _round(row["spent"]), _round(row["reserved"])
        return {
            "spent": spent, "reserved": reserved, "committed": _round(spent + reserved),
        }

    def by_role(self, mission: str) -> tuple[dict[str, Any], ...]:
        """Per role, with unrecorded roles kept visible as unattributed."""
        rows = self.storage.db.execute(
            f"""SELECT CASE WHEN role='' THEN ? ELSE role END AS role,
                       COALESCE(SUM(CASE WHEN kind='reported' THEN amount END),0) AS spent,
                       COALESCE(SUM(CASE WHEN {STILL_RESERVED} THEN amount END),0) AS reserved,
                       COUNT(DISTINCT CASE WHEN task_key<>'' THEN task_key END) AS tasks
                  FROM studio_spend s WHERE mission=?
                 GROUP BY 1 ORDER BY 2 DESC""",
            (UNATTRIBUTED, str(mission)),
        ).fetchall()
        return tuple(
            {
                "role": row["role"], "spent": _round(row["spent"]),
                "reserved": _round(row["reserved"]), "tasks": int(row["tasks"]),
            }
            for row in rows
        )

    def by_task(self, mission: str, *, limit: int = 50) -> tuple[dict[str, Any], ...]:
        rows = self.storage.db.execute(
            """SELECT task_key,role,provider,model,
                      COALESCE(SUM(CASE WHEN kind='reported' THEN amount END),0) AS spent
                 FROM studio_spend WHERE mission=? AND task_key<>''
                GROUP BY task_key,role,provider,model ORDER BY spent DESC LIMIT ?""",
            (str(mission), int(limit)),
        ).fetchall()
        return tuple(
            {
                "task": row["task_key"], "role": row["role"],
                "provider": row["provider"], "model": row["model"],
                "spent": _round(row["spent"]),
            }
            for row in rows
        )

    def measured_tasks(self, mission: str, *, stage_key: str = "") -> tuple[float, ...]:
        rows = self.storage.db.execute(
            """SELECT task_key, SUM(amount) AS spent FROM studio_spend
                WHERE mission=? AND kind='reported' AND task_key<>''
                  AND (?='' OR stage_key=?)
                GROUP BY task_key HAVING spent > 0""",
            (str(mission), str(stage_key), str(stage_key)),
        ).fetchall()
        return tuple(_round(row["spent"]) for row in rows)

    def forecast(
        self, mission: str, *, remaining_tasks: int, stage_key: str = "", unit: str = "USD",
    ) -> Forecast:
        return forecast_remaining(
            measured=self.measured_tasks(mission, stage_key=stage_key),
            remaining_tasks=remaining_tasks,
            unit=unit,
        )

    # -- the limit

    def check(self, mission: str, *, next_step: float = 0.0) -> dict[str, Any]:
        """Whether the next step fits, and the question to ask if it does not."""
        from .studio_autonomy import over_budget

        limit = self.limit(mission)
        totals = self.totals(mission)
        committed = _round(totals["committed"] + max(0.0, float(next_step)))
        if limit is None:
            return {
                **totals, "limit": None, "remaining": None, "over": False,
                "summary": NO_LIMIT, "question": None,
            }
        remaining = _round(limit.amount - totals["committed"])
        over = committed > limit.amount
        summary = Message(
            (OVER_LIMIT if over else WITHIN_LIMIT).uk.format(
                committed=committed, limit=limit.amount, unit=limit.unit),
            (OVER_LIMIT if over else WITHIN_LIMIT).en.format(
                committed=committed, limit=limit.amount, unit=limit.unit),
        )
        question = over_budget(
            amount=_round(next_step), remaining=max(0.0, remaining), unit=limit.unit,
            blocks=str(mission),
        ) if over else None
        return {
            **totals, "limit": limit.amount, "unit": limit.unit,
            "remaining": remaining, "over": over, "summary": summary,
            "question": question,
        }

    def report(
        self,
        mission: str,
        *,
        language: str = DEFAULT_LANGUAGE,
        remaining_tasks: int = 0,
        stage_key: str = "",
        next_step: float = 0.0,
    ) -> dict[str, Any]:
        chosen = normalise(language)
        state = self.check(mission, next_step=next_step)
        limit = self.limit(mission)
        return {
            "mission": str(mission),
            "spent": state["spent"],
            "reserved": state["reserved"],
            "committed": state["committed"],
            "limit": state["limit"],
            "remaining": state["remaining"],
            "over": state["over"],
            "unit": limit.unit if limit else "USD",
            "summary": state["summary"].text(chosen),
            "question": state["question"].record(chosen) if state["question"] else None,
            "by_role": list(self.by_role(mission)),
            "by_task": list(self.by_task(mission)),
            "forecast": self.forecast(
                mission, remaining_tasks=remaining_tasks, stage_key=stage_key,
                unit=limit.unit if limit else "USD",
            ).record(chosen),
            "limit_history": [item.record() for item in self.limit_history(mission)],
        }
