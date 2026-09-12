"""Read what a run is actually doing out of the database it already writes to.

Nothing here records new state. The controller already stores stages, provider
attempts, heartbeats and a cost ledger; this module reads those rows and hands
them to :mod:`agent_factory.work_status`, which decides what may honestly be
claimed from them. Two consequences are deliberate:

* An estimate comes from measured attempts of this very run, never from a
  configured expectation. A run with nothing measured yet says so.
* Money is split the way the ledger splits it. A provider-reported cost is
  spent and cannot be recovered; an estimate is a reservation that a stop
  releases. Calling both "spent" would overstate the loss, and calling both
  "reserved" would understate it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence, TYPE_CHECKING

from .localisation import DEFAULT_LANGUAGE, Message, verbatim
from .work_status import (
    Blocker,
    Operation,
    Record,
    Reconciliation,
    Spend,
    Stage,
    StopPlan,
    WorkStatus,
    compose,
    plan_stop,
    reconcile_after_restart,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from .storage import SQLiteStorage

RUNNING_ATTEMPTS = ("claimed", "running")
OPEN_STAGES = ("pending", "running", "waiting_approval")
LOCAL_PROVIDERS = frozenset({"ollama", "local", "lmstudio", "llamacpp"})

WAITING_APPROVAL = Message(
    "Етап чекає на рішення людини.",
    "A stage is waiting for a person to decide.",
)
WAITING_ACTION = Message(
    "Погодьте або відхиліть етап у центрі керування.",
    "Approve or refuse the stage in the control centre.",
)
STAGE_FAILED = Message(
    "Етап завершився невдало.",
    "A stage failed.",
)
STAGE_FAILED_ACTION = Message(
    "Подивіться, що саме не вдалося, і вирішіть: повторити чи зупинити.",
    "Look at what failed, then decide whether to retry or stop.",
)
NO_STAGES = Message(
    "У цього запуску ще немає жодного етапу.",
    "This run has no stage yet.",
)
SCHEDULING_LABEL = Message(
    "Постановка наступних етапів у чергу",
    "Queueing the stages that come next",
)


def _seconds_between(start: Any, finish: Any) -> float | None:
    first, last = _moment(start), _moment(finish)
    if first is None or last is None:
        return None
    span = (last - first).total_seconds()
    return span if span > 0 else None


def _moment(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class WorkStatusReader:
    """One truthful account of a run, assembled from rows the run already wrote."""

    def __init__(self, storage: "SQLiteStorage"):
        self.storage = storage

    # ------------------------------------------------------------------ runs

    def open_runs(self, *, limit: int = 20) -> tuple[dict[str, Any], ...]:
        rows = self.storage.db.execute(
            """SELECT r.id AS run_id, r.workflow_id, r.status, r.task_id,
                      w.title AS title, p.name AS project
                 FROM workflow_runs r
                 JOIN work_items w ON w.id=r.task_id
                 JOIN projects p ON p.id=r.project_id
                WHERE r.completed_at IS NULL
                ORDER BY r.id DESC LIMIT ?""",
            (int(limit),),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    # ---------------------------------------------------------------- status

    def for_run(
        self,
        run_id: int,
        *,
        project_key: str = "",
        playable_version: str = "",
        now: datetime | None = None,
    ) -> WorkStatus:
        run = self.storage.db.execute(
            """SELECT r.id, r.task_id, r.workflow_id, r.status,
                      w.title AS title, p.name AS project
                 FROM workflow_runs r
                 JOIN work_items w ON w.id=r.task_id
                 JOIN projects p ON p.id=r.project_id
                WHERE r.id=?""",
            (int(run_id),),
        ).fetchone()
        if run is None:
            raise KeyError(f"Unknown run {run_id}")
        stages = self.storage.db.execute(
            "SELECT stage_key,status,updated_at FROM workflow_stages WHERE run_id=? ORDER BY id",
            (int(run_id),),
        ).fetchall()
        stage = self._stage(stages)
        blockers = self._blockers(stages)
        attempts = self._attempts(int(run["task_id"]))
        running = any(row["status"] == "running" for row in stages) or any(
            row["status"] in RUNNING_ATTEMPTS for row in attempts
        )
        return compose(
            project=project_key or str(run["project"]),
            stage=stage,
            heartbeat_at=self._heartbeat(attempts, stages),
            spend=self.spend(int(run_id)),
            blockers=blockers,
            finished_step_seconds=self._measured(attempts),
            remaining_steps=sum(1 for row in stages if row["status"] in OPEN_STAGES),
            playable_version=playable_version,
            expects_heartbeat=running,
            now=now,
        )

    def _stage(self, stages: Sequence[Any]) -> Stage:
        if not stages:
            return Stage.within("none", NO_STAGES, index=1, total=1)
        current = next(
            (row for row in stages if row["status"] in ("running", "waiting_approval")),
            None,
        )
        if current is None:
            current = next(
                (row for row in stages if row["status"] == "pending"), stages[-1]
            )
        index = [row["stage_key"] for row in stages].index(current["stage_key"]) + 1
        return Stage.within(
            str(current["stage_key"]),
            verbatim(str(current["stage_key"])),
            index=index,
            total=len(stages),
        )

    def _blockers(self, stages: Sequence[Any]) -> tuple[Blocker, ...]:
        found = []
        for row in stages:
            if row["status"] == "waiting_approval":
                found.append(Blocker(
                    "waiting_approval", WAITING_APPROVAL, WAITING_ACTION,
                    since=str(row["updated_at"] or ""),
                ))
            elif row["status"] == "failed":
                found.append(Blocker(
                    "stage_failed", STAGE_FAILED, STAGE_FAILED_ACTION,
                    since=str(row["updated_at"] or ""),
                ))
        return tuple(found)

    def _attempts(self, task_id: int) -> tuple[Any, ...]:
        return tuple(self.storage.db.execute(
            """SELECT provider,status,started_at,finished_at,heartbeat_at
                 FROM provider_execution_attempts WHERE task_id=? ORDER BY id""",
            (int(task_id),),
        ).fetchall())

    def _heartbeat(self, attempts: Sequence[Any], stages: Sequence[Any]) -> str:
        """The most recent sign of life, from a worker if there is one."""
        beats = [
            str(row["heartbeat_at"]) for row in attempts
            if row["status"] in RUNNING_ATTEMPTS and row["heartbeat_at"]
        ]
        if beats:
            return max(beats)
        touched = [
            str(row["updated_at"]) for row in stages
            if row["status"] == "running" and row["updated_at"]
        ]
        return max(touched) if touched else ""

    def _measured(self, attempts: Sequence[Any]) -> tuple[float, ...]:
        spans = [
            _seconds_between(row["started_at"], row["finished_at"])
            for row in attempts if row["status"] == "succeeded"
        ]
        return tuple(span for span in spans if span is not None)

    # ----------------------------------------------------------------- money

    def spend(self, run_id: int) -> Spend:
        """Reported cost is spent; an estimate is still only reserved."""
        trace = self.storage.db.execute(
            "SELECT id,max_cost_usd FROM execution_traces WHERE run_id=?",
            (int(run_id),),
        ).fetchone()
        if trace is None:
            return Spend(unit="USD")
        totals = self.storage.db.execute(
            """SELECT COALESCE(SUM(CASE WHEN source='provider_reported' THEN cost_usd END),0) AS reported,
                      COALESCE(SUM(CASE WHEN source='estimated' THEN cost_usd END),0) AS estimated
                 FROM cost_ledger_entries WHERE trace_id=?""",
            (int(trace["id"]),),
        ).fetchone()
        raised = self.storage.db.execute(
            """SELECT new_max_cost_usd FROM budget_authorizations
                WHERE trace_id=? ORDER BY id DESC LIMIT 1""",
            (int(trace["id"]),),
        ).fetchone()
        cap = float(raised["new_max_cost_usd"]) if raised else float(trace["max_cost_usd"])
        return Spend(
            reserved=round(float(totals["estimated"]), 6),
            spent=round(float(totals["reported"]), 6),
            cap=cap,
            unit="USD",
        )

    # --------------------------------------------------------------- stopping

    def operations(self, run_id: int) -> tuple[Operation, ...]:
        """What is running right now, and whether a stop could cut it short."""
        run = self.storage.db.execute(
            "SELECT task_id FROM workflow_runs WHERE id=?", (int(run_id),)
        ).fetchone()
        if run is None:
            raise KeyError(f"Unknown run {run_id}")
        attempts = self._attempts(int(run["task_id"]))
        typical = self._typical_by_provider(attempts)
        running = [
            Operation(
                "inference",
                verbatim(str(row["provider"])),
                interruptible=False,
                started_at=str(row["started_at"] or ""),
                typical_seconds=typical.get(str(row["provider"])),
                paid=str(row["provider"]).casefold() not in LOCAL_PROVIDERS,
            )
            for row in attempts if row["status"] in RUNNING_ATTEMPTS
        ]
        pending = self.storage.db.execute(
            "SELECT COUNT(*) AS open FROM workflow_stages WHERE run_id=? AND status='pending'",
            (int(run_id),),
        ).fetchone()
        if int(pending["open"]):
            running.append(Operation("scheduling", SCHEDULING_LABEL, interruptible=True))
        return tuple(running)

    def _typical_by_provider(self, attempts: Sequence[Any]) -> dict[str, float]:
        gathered: dict[str, list[float]] = {}
        for row in attempts:
            if row["status"] != "succeeded":
                continue
            span = _seconds_between(row["started_at"], row["finished_at"])
            if span is not None:
                gathered.setdefault(str(row["provider"]), []).append(span)
        return {
            provider: round(sum(spans) / len(spans), 1)
            for provider, spans in gathered.items()
        }

    def stop_plan(self, run_id: int) -> StopPlan:
        return plan_stop(self.operations(run_id))

    # ---------------------------------------------------------- after restart

    def after_restart(self, run_id: int) -> Reconciliation:
        """Hand every unfinished attempt back as something to check, never to repeat."""
        run = self.storage.db.execute(
            "SELECT task_id FROM workflow_runs WHERE id=?", (int(run_id),)
        ).fetchone()
        if run is None:
            raise KeyError(f"Unknown run {run_id}")
        rows = self.storage.db.execute(
            """SELECT id,provider,status FROM provider_execution_attempts
                WHERE task_id=? ORDER BY id""",
            (int(run["task_id"]),),
        ).fetchall()
        records = [
            Record(
                "provider_attempt",
                f"attempt-{int(row['id'])}",
                str(row["status"]),
                Message(
                    f"Спроба провайдера {row['provider']} у стані «{row['status']}».",
                    f"A {row['provider']} attempt in state '{row['status']}'.",
                ),
                accepted=str(row["status"]) == "succeeded",
            )
            for row in rows
        ]
        return reconcile_after_restart(records)

    # ---------------------------------------------------------------- reports

    def report(
        self,
        run_id: int,
        *,
        language: str = DEFAULT_LANGUAGE,
        project_key: str = "",
        playable_version: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        status = self.for_run(
            run_id, project_key=project_key,
            playable_version=playable_version, now=now,
        )
        record = status.record(language)
        record["run_id"] = int(run_id)
        record["stop"] = self.stop_plan(run_id).record(language)
        return record
