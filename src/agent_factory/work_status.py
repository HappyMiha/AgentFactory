"""What is happening, what it will cost, and what a stop actually stops.

A progress bar that invents a finishing time is worse than no progress bar. So
an estimate exists only when completed comparable steps support one, and is
labelled unknown - with the reason - the rest of the time. A heartbeat that
stopped is a blocker, not a silence. A stop says which of the things now running
it can interrupt and which will finish anyway, because a paid call already sent
cannot be un-sent. And after a restart nothing is relaunched: an unfinished
operation becomes something to check, never something to repeat.

This module composes facts it is given. It starts nothing, stops nothing and
reads no database; the caller supplies the state and performs the actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from .localisation import DEFAULT_LANGUAGE, Message

STAGES = (
    "planning", "environment", "development", "validation", "review", "delivery",
)
LIVENESS = ("alive", "quiet", "stalled", "waiting")
STOPPABLE = ("scheduling", "inference", "build", "spending")
QUIET_AFTER_SECONDS = 90
STALLED_AFTER_SECONDS = 600
MINIMUM_SAMPLES_FOR_ESTIMATE = 3
ORPHAN_DISPOSITIONS = ("check", "preserved")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(moment: str | datetime | None) -> datetime | None:
    if isinstance(moment, datetime):
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    if not moment:
        return None
    try:
        parsed = datetime.fromisoformat(str(moment).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Stage:
    stage_id: str
    index: int
    total: int
    label: Message

    @classmethod
    def create(cls, stage_id: str, label: Message) -> "Stage":
        if stage_id not in STAGES:
            raise ValueError(f"Unknown stage: {stage_id!r}")
        return cls(stage_id, STAGES.index(stage_id) + 1, len(STAGES), label)

    @classmethod
    def within(cls, stage_id: str, label: Message, *, index: int, total: int) -> "Stage":
        """A stage numbered by the workflow it actually belongs to.

        A run follows the workflow it was configured with, not this module's
        vocabulary. Counting inside that workflow tells the truth about how far
        along the work is; mapping a configured stage onto a fixed list would
        invent a position it does not have.
        """
        if total < 1 or not 1 <= index <= total:
            raise ValueError(f"Stage {index} of {total} is not a position")
        return cls(str(stage_id), int(index), int(total), label)

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "stage": self.stage_id,
            "label": self.label.text(language),
            "index": self.index,
            "total": self.total,
        }


@dataclass(frozen=True)
class Blocker:
    """Something in the way, with what the person can do about it."""

    code: str
    summary: Message
    action: Message
    since: str = ""

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "code": self.code,
            "summary": self.summary.text(language),
            "action": self.action.text(language),
            "since": self.since,
        }


@dataclass(frozen=True)
class Spend:
    """Money or credit: what is committed, and what is already gone."""

    reserved: float = 0.0
    spent: float = 0.0
    cap: float | None = None
    unit: str = "credit"

    @property
    def committed(self) -> float:
        return round(self.reserved + self.spent, 6)

    @property
    def remaining(self) -> float | None:
        return None if self.cap is None else round(self.cap - self.committed, 6)

    @property
    def over_cap(self) -> bool:
        return self.cap is not None and self.committed > self.cap

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "reserved": self.reserved,
            "spent": self.spent,
            "committed": self.committed,
            "cap": self.cap,
            "remaining": self.remaining,
            "over_cap": self.over_cap,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class Estimate:
    """A finishing time, or an honest statement that there is not one."""

    seconds: float | None
    basis: Message

    @property
    def known(self) -> bool:
        return self.seconds is not None

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "known": self.known,
            "seconds": self.seconds,
            "basis": self.basis.text(language),
        }


UNKNOWN_NO_SAMPLES = Message(
    "Оцінки немає: ще не завершено жодного порівнянного кроку.",
    "No estimate: no comparable step has finished yet.",
)
UNKNOWN_TOO_FEW = Message(
    "Оцінки немає: завершених кроків замало, щоб рахувати чесно.",
    "No estimate: too few finished steps to be honest about it.",
)
UNKNOWN_STALLED = Message(
    "Оцінки немає: робота не подає ознак життя, і час до завершення невідомий.",
    "No estimate: the work is not reporting, so time to finish is unknown.",
)
UNKNOWN_BLOCKED = Message(
    "Оцінки немає: робота чекає на рішення людини.",
    "No estimate: the work is waiting on a person's decision.",
)
UNKNOWN_IDLE = Message(
    "Оцінки немає: зараз нічого не виконується.",
    "No estimate: nothing is running right now.",
)


def estimate_remaining(
    *,
    finished_step_seconds: Sequence[float],
    remaining_steps: int,
    alive: bool = True,
    blocked: bool = False,
    running: bool = True,
) -> Estimate:
    """Estimate only from measured steps. Anything else is labelled unknown."""
    if blocked:
        return Estimate(None, UNKNOWN_BLOCKED)
    if not alive:
        return Estimate(None, UNKNOWN_STALLED)
    if not running:
        return Estimate(None, UNKNOWN_IDLE)
    samples = [float(value) for value in finished_step_seconds if float(value) > 0]
    if not samples:
        return Estimate(None, UNKNOWN_NO_SAMPLES)
    if len(samples) < MINIMUM_SAMPLES_FOR_ESTIMATE:
        return Estimate(None, UNKNOWN_TOO_FEW)
    if remaining_steps <= 0:
        return Estimate(0.0, Message(
            "Кроків не лишилось.", "No steps remain.",
        ))
    average = sum(samples) / len(samples)
    seconds = round(average * remaining_steps, 1)
    return Estimate(seconds, Message(
        f"За {len(samples)} завершеними кроками, у середньому {average:.0f} с кожен.",
        f"From {len(samples)} finished steps, averaging {average:.0f}s each.",
    ))


@dataclass(frozen=True)
class WorkStatus:
    project: str
    stage: Stage
    liveness: str
    heartbeat_at: str
    heartbeat_age_seconds: float | None
    blockers: tuple[Blocker, ...]
    spend: Spend
    estimate: Estimate
    next_action: Message
    playable_version: str = ""

    @property
    def alive(self) -> bool:
        return self.liveness == "alive"

    @property
    def blocked(self) -> bool:
        return bool(self.blockers)

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "project": self.project,
            "stage": self.stage.record(language),
            "liveness": self.liveness,
            "alive": self.alive,
            "heartbeat_at": self.heartbeat_at,
            "heartbeat_age_seconds": self.heartbeat_age_seconds,
            "blockers": [blocker.record(language) for blocker in self.blockers],
            "spend": self.spend.record(language),
            "estimate": self.estimate.record(language),
            "next_action": self.next_action.text(language),
            "playable_version": self.playable_version,
        }


NO_HEARTBEAT = Blocker(
    "no_heartbeat",
    Message(
        "Робота не подавала ознак життя.",
        "The work has not reported for a while.",
    ),
    Message(
        "Перевірте, чи живий воркер, і зупиніть роботу, якщо він зник.",
        "Check whether the worker is alive, and stop the work if it is gone.",
    ),
)
OVER_CAP = Blocker(
    "over_cap",
    Message(
        "Зарезервоване й витрачене разом перевищують межу.",
        "Reserved and spent together are over the cap.",
    ),
    Message(
        "Підніміть межу свідомо або зупиніть роботу.",
        "Raise the cap deliberately, or stop the work.",
    ),
)
NEXT_WAIT = Message(
    "Нічого робити не потрібно: робота триває.",
    "Nothing to do: the work is running.",
)
NEXT_IDLE = Message(
    "Зараз нічого не виконується: запустіть наступний крок, коли будете готові.",
    "Nothing is running right now: start the next step when you are ready.",
)
NEXT_PLAY = Message(
    "Можна запустити останню перевірену версію, поки решта триває.",
    "You can launch the last verified version while the rest continues.",
)


def compose(
    *,
    project: str,
    stage: Stage,
    heartbeat_at: str | datetime | None,
    spend: Spend | None = None,
    blockers: Sequence[Blocker] = (),
    finished_step_seconds: Sequence[float] = (),
    remaining_steps: int = 0,
    playable_version: str = "",
    expects_heartbeat: bool = True,
    now: datetime | None = None,
) -> WorkStatus:
    """One truthful account, composed from facts the caller already has.

    ``expects_heartbeat`` is how the caller says whether anything is supposed
    to be running. A run parked on a person's decision is not silent, it is
    waiting, and reporting it as a dead worker would send someone chasing a
    process that was never started.
    """
    moment = now or _now()
    beat = _parse(heartbeat_at)
    age = None if beat is None else round((moment - beat).total_seconds(), 1)
    if not expects_heartbeat:
        liveness = "waiting"
    elif age is None or age >= STALLED_AFTER_SECONDS:
        liveness = "stalled"
    elif age >= QUIET_AFTER_SECONDS:
        liveness = "quiet"
    else:
        liveness = "alive"
    money = spend or Spend()
    found = list(blockers)
    if liveness == "stalled":
        found.append(
            NO_HEARTBEAT if beat is None
            else Blocker(
                NO_HEARTBEAT.code, NO_HEARTBEAT.summary, NO_HEARTBEAT.action,
                since=beat.isoformat(),
            )
        )
    if money.over_cap:
        found.append(OVER_CAP)
    estimate = estimate_remaining(
        finished_step_seconds=finished_step_seconds,
        remaining_steps=remaining_steps,
        alive=liveness != "stalled",
        blocked=bool(found),
        running=expects_heartbeat,
    )
    if found:
        next_action = found[0].action
    elif playable_version:
        next_action = NEXT_PLAY
    elif not expects_heartbeat:
        next_action = NEXT_IDLE
    else:
        next_action = NEXT_WAIT
    return WorkStatus(
        project=str(project),
        stage=stage,
        liveness=liveness,
        heartbeat_at=beat.isoformat() if beat else "",
        heartbeat_age_seconds=age,
        blockers=tuple(found),
        spend=money,
        estimate=estimate,
        next_action=next_action,
        playable_version=str(playable_version),
    )


# ------------------------------------------------------------------- stopping

@dataclass(frozen=True)
class Operation:
    """Something running right now, and whether it can be cut short."""

    kind: str
    label: Message
    interruptible: bool
    started_at: str = ""
    typical_seconds: float | None = None
    paid: bool = False

    def __post_init__(self) -> None:
        if self.kind not in STOPPABLE:
            raise ValueError(f"Unknown operation kind: {self.kind!r}")

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label.text(language),
            "interruptible": self.interruptible,
            "started_at": self.started_at,
            "typical_seconds": self.typical_seconds,
            "paid": self.paid,
        }


@dataclass(frozen=True)
class StopPlan:
    covers: tuple[str, ...]
    stops_now: tuple[Operation, ...]
    finishes_anyway: tuple[Operation, ...]
    spending: Message
    longest_wait_seconds: float | None
    warnings: tuple[Message, ...] = ()

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "covers": list(self.covers),
            "stops_now": [item.record(language) for item in self.stops_now],
            "finishes_anyway": [item.record(language) for item in self.finishes_anyway],
            "spending": self.spending.text(language),
            "longest_wait_seconds": self.longest_wait_seconds,
            "warnings": [warning.text(language) for warning in self.warnings],
        }


SPENDING_STOPPED = Message(
    "Нові платні виклики не почнуться. Резерв під незапущені кроки звільняється.",
    "No new paid call will start. The reservation for unstarted steps is released.",
)
SPENDING_IN_FLIGHT = Message(
    "Уже надісланий платний виклик скасувати не можна: його вартість лишиться "
    "витраченою, і буде звірена окремо.",
    "A paid call already sent cannot be recalled: its cost stays spent and is "
    "reconciled separately.",
)
UNKNOWN_WAIT = Message(
    "Скільки триватиме поточна дія — невідомо: подібних завершених дій ще не було.",
    "How long the current action will take is unknown: no similar action has "
    "finished yet.",
)


def plan_stop(operations: Sequence[Operation]) -> StopPlan:
    """Say what a stop stops, and what it honestly cannot."""
    stops_now = tuple(item for item in operations if item.interruptible)
    finishes = tuple(item for item in operations if not item.interruptible)
    paid_in_flight = any(item.paid for item in operations)
    waits = [
        item.typical_seconds for item in finishes if item.typical_seconds is not None
    ]
    warnings: list[Message] = []
    if finishes and not waits:
        warnings.append(UNKNOWN_WAIT)
    return StopPlan(
        covers=STOPPABLE,
        stops_now=stops_now,
        finishes_anyway=finishes,
        spending=SPENDING_IN_FLIGHT if paid_in_flight else SPENDING_STOPPED,
        longest_wait_seconds=max(waits) if waits else None,
        warnings=tuple(warnings),
    )


# --------------------------------------------------------------- after restart

@dataclass(frozen=True)
class Record:
    """One thing that existed before the restart."""

    kind: str
    identity: str
    state: str
    detail: Message
    accepted: bool = False


@dataclass(frozen=True)
class Reconciliation:
    preserved: tuple[Record, ...]
    to_check: tuple[Record, ...]
    relaunched: tuple[Record, ...] = ()

    @property
    def safe(self) -> bool:
        return not self.relaunched

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "preserved": [
                {
                    "kind": item.kind, "identity": item.identity,
                    "state": item.state, "detail": item.detail.text(language),
                }
                for item in self.preserved
            ],
            "to_check": [
                {
                    "kind": item.kind, "identity": item.identity,
                    "state": item.state, "detail": item.detail.text(language),
                }
                for item in self.to_check
            ],
            "relaunched": [item.identity for item in self.relaunched],
            "safe": self.safe,
            "note": _RESTART_NOTE.text(language),
        }


_RESTART_NOTE = Message(
    "Ніщо не перезапускається автоматично. Незавершена дія могла завершитися вже "
    "після падіння, тож її треба перевірити, а не повторити.",
    "Nothing is relaunched automatically. An unfinished action may have completed "
    "after the crash, so it is checked rather than repeated.",
)


def reconcile_after_restart(records: Iterable[Record]) -> Reconciliation:
    """Keep what was accepted, and hand every orphan back as something to check."""
    preserved: list[Record] = []
    to_check: list[Record] = []
    for item in records:
        if item.accepted or item.state in {"completed", "accepted", "saved"}:
            preserved.append(item)
        else:
            to_check.append(item)
    return Reconciliation(tuple(preserved), tuple(to_check))
