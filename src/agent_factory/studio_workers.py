"""Which machine did this, and which machine may do the next thing.

The demo showing the container's CPU as if it were the user's PC is not a
cosmetic bug: it is a report that names the wrong machine. Every report about
hardware, an environment or a build carries the machine it ran on, and there is
no way to produce one without naming it.

The rules:

* **The web container is never a place to build.** Asking it to run an engine
  adapter or scan hardware is refused, with the reason, rather than answered
  with the container's own numbers.
* **A machine only gets work it can actually do.** A machine declares what it
  has - an engine, a licence, a GPU, disk - and a task that needs something it
  does not have is refused with the missing thing named, not queued in hope.
* **A worker never receives raw keys.** There is nowhere in a machine's record
  to put one, and admitting a task carries no credential.

A local AI model is a machine capability like any other: it is offered only
after the hardware has been looked at, and when it will not fit, that is said
plainly rather than as "give it a try".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence, TYPE_CHECKING

from .localisation import DEFAULT_LANGUAGE, LocalisedError, Message, normalise, verbatim

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from .storage import SQLiteStorage

KINDS = ("cloud_worker", "this_pc", "web_container")
WORK = ("build", "hardware_scan", "engine_command", "local_inference")
NEVER_ON_THE_WEB_CONTAINER = ("build", "hardware_scan", "engine_command", "local_inference")


class WorkerRefused(LocalisedError):
    """Raised when a machine would be asked to answer for another machine."""


WRONG_MACHINE = Message(
    "Вебконтейнер сайту не збирає ігор і не сканує залізо: його показники — це "
    "показники контейнера, а не вашого ПК.",
    "The site's web container does not build games or scan hardware: its numbers "
    "are the container's, not your PC's.",
)
UNKNOWN_MACHINE = Message(
    "Такої машини не зареєстровано: {machine}.",
    "No such machine is registered: {machine}.",
)
UNKNOWN_KIND = Message(
    "Невідомий вид машини: {kind}.", "Unknown kind of machine: {kind}.",
)
UNKNOWN_WORK = Message(
    "Невідомий вид роботи: {work}.", "Unknown kind of work: {work}.",
)
MISSING_CAPABILITY = Message(
    "Машина «{machine}» не має того, що потрібно: {missing}.",
    "The machine '{machine}' does not have what this needs: {missing}.",
)
NOT_ENOUGH_MEMORY = Message(
    "Для моделі потрібно {needed} ГБ памʼяті відеокарти, а є {available} ГБ. "
    "Локально вона не піде.",
    "The model needs {needed} GB of video memory and {available} GB is available. "
    "It will not run locally.",
)
FITS_LOCALLY = Message(
    "Моделі вистачить памʼяті відеокарти: потрібно {needed} ГБ, є {available} ГБ.",
    "The model fits in video memory: it needs {needed} GB and {available} GB is "
    "available.",
)
NO_GPU = Message(
    "На цій машині немає відеокарти, придатної для локальної моделі.",
    "This machine has no video card suitable for a local model.",
)

WORKER_MIGRATION = """
CREATE TABLE studio_machines(
    id INTEGER PRIMARY KEY,
    machine_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('cloud_worker','this_pc','web_container')),
    capabilities_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(capabilities_json)),
    video_memory_gb REAL NOT NULL DEFAULT 0 CHECK(video_memory_gb >= 0),
    registered_by TEXT NOT NULL DEFAULT '',
    registered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE studio_machine_reports(
    id INTEGER PRIMARY KEY,
    machine_key TEXT NOT NULL REFERENCES studio_machines(machine_key),
    kind TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    body_json TEXT NOT NULL CHECK(json_valid(body_json)),
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_studio_machine_reports ON studio_machine_reports(machine_key, id);

-- A report that can be edited afterwards cannot answer "which machine was this".
CREATE TRIGGER studio_machine_reports_no_update
BEFORE UPDATE ON studio_machine_reports
BEGIN SELECT RAISE(ABORT, 'a machine report cannot be rewritten'); END;
CREATE TRIGGER studio_machine_reports_no_delete
BEFORE DELETE ON studio_machine_reports
BEGIN SELECT RAISE(ABORT, 'a machine report cannot be deleted'); END;
"""

KIND_LABELS = {
    "cloud_worker": Message("хмарний воркер", "cloud worker"),
    "this_pc": Message("ваш ПК", "your PC"),
    "web_container": Message("вебконтейнер сайту", "the site's web container"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Machine:
    """One machine that can be asked to do something."""

    machine_key: str
    name: str
    kind: str
    capabilities: tuple[str, ...] = ()
    video_memory_gb: float = 0.0

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise WorkerRefused(UNKNOWN_KIND, kind=self.kind)

    @property
    def builds(self) -> bool:
        return self.kind != "web_container"

    def signature(self, language: str = DEFAULT_LANGUAGE) -> str:
        """The line every report carries: which machine this came from."""
        return f"{KIND_LABELS[self.kind].text(language)}: {self.name}"

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "machine": self.machine_key,
            "name": self.name,
            "kind": self.kind,
            "kind_label": KIND_LABELS[self.kind].text(language),
            "capabilities": list(self.capabilities),
            "video_memory_gb": self.video_memory_gb,
            "builds": self.builds,
            "signature": self.signature(language),
        }


@dataclass(frozen=True)
class LocalModelVerdict:
    """Whether a model will run on this machine, said plainly either way."""

    fits: bool
    needed_gb: float
    available_gb: float
    reason: Message

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "fits": self.fits,
            "needed_gb": self.needed_gb,
            "available_gb": self.available_gb,
            "reason": self.reason.text(language),
        }


class StudioMachines:
    """Every machine the studio may use, and what each one is allowed to answer."""

    def __init__(self, storage: "SQLiteStorage"):
        self.storage = storage

    # -- registering

    def register(
        self,
        machine_key: str,
        *,
        name: str,
        kind: str,
        capabilities: Sequence[str] = (),
        video_memory_gb: float = 0.0,
        registered_by: str = "",
    ) -> Machine:
        machine = Machine(
            str(machine_key), str(name), str(kind),
            tuple(sorted({str(item) for item in capabilities})),
            float(video_memory_gb),
        )
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO studio_machines
                   (machine_key,name,kind,capabilities_json,video_memory_gb,
                    registered_by,registered_at)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(machine_key) DO UPDATE SET
                     name=excluded.name, kind=excluded.kind,
                     capabilities_json=excluded.capabilities_json,
                     video_memory_gb=excluded.video_memory_gb""",
                (
                    machine.machine_key, machine.name, machine.kind,
                    json.dumps(list(machine.capabilities)), machine.video_memory_gb,
                    str(registered_by), _now(),
                ),
            )
        return machine

    def machine(self, machine_key: str) -> Machine:
        row = self.storage.db.execute(
            "SELECT * FROM studio_machines WHERE machine_key=?", (str(machine_key),)
        ).fetchone()
        if row is None:
            raise WorkerRefused(UNKNOWN_MACHINE, machine=machine_key)
        return Machine(
            row["machine_key"], row["name"], row["kind"],
            tuple(json.loads(row["capabilities_json"])), float(row["video_memory_gb"]),
        )

    def machines(self) -> tuple[Machine, ...]:
        rows = self.storage.db.execute(
            "SELECT machine_key FROM studio_machines ORDER BY id"
        ).fetchall()
        return tuple(self.machine(row["machine_key"]) for row in rows)

    # -- admitting work

    def admit(
        self, machine_key: str, work: str, *, needs: Sequence[str] = (),
    ) -> Machine:
        """Let this machine do this work, or refuse with the reason."""
        if work not in WORK:
            raise WorkerRefused(UNKNOWN_WORK, work=work)
        machine = self.machine(machine_key)
        if machine.kind == "web_container" and work in NEVER_ON_THE_WEB_CONTAINER:
            raise WorkerRefused(WRONG_MACHINE)
        missing = [item for item in needs if item not in machine.capabilities]
        if missing:
            raise WorkerRefused(
                MISSING_CAPABILITY, machine=machine.name, missing=", ".join(missing),
            )
        return machine

    def local_model_fits(
        self, machine_key: str, *, needed_gb: float
    ) -> LocalModelVerdict:
        """Look at the hardware before offering a local model, and say either way."""
        machine = self.machine(machine_key)
        available = float(machine.video_memory_gb)
        if available <= 0:
            return LocalModelVerdict(False, float(needed_gb), available, NO_GPU)
        if available < float(needed_gb):
            return LocalModelVerdict(False, float(needed_gb), available, Message(
                NOT_ENOUGH_MEMORY.uk.format(needed=needed_gb, available=available),
                NOT_ENOUGH_MEMORY.en.format(needed=needed_gb, available=available),
            ))
        return LocalModelVerdict(True, float(needed_gb), available, Message(
            FITS_LOCALLY.uk.format(needed=needed_gb, available=available),
            FITS_LOCALLY.en.format(needed=needed_gb, available=available),
        ))

    # -- reports

    def report(
        self,
        machine_key: str,
        *,
        kind: str,
        body: Mapping[str, Any],
        subject: str = "",
        language: str = DEFAULT_LANGUAGE,
    ) -> dict[str, Any]:
        """Record a report, signed by the machine that produced it."""
        machine = self.admit(machine_key, kind) if kind in WORK else self.machine(machine_key)
        signed = {
            **dict(body),
            "machine": machine.machine_key,
            "machine_name": machine.name,
            "machine_kind": machine.kind,
            "signature": machine.signature(normalise(language)),
        }
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO studio_machine_reports
                   (machine_key,kind,subject,body_json,recorded_at)
                   VALUES(?,?,?,?,?)""",
                (
                    machine.machine_key, str(kind), str(subject),
                    json.dumps(signed, ensure_ascii=False), _now(),
                ),
            )
        return signed

    def reports(
        self, *, machine_key: str = "", limit: int = 50
    ) -> tuple[dict[str, Any], ...]:
        rows = self.storage.db.execute(
            """SELECT * FROM studio_machine_reports
                WHERE (?='' OR machine_key=?) ORDER BY id DESC LIMIT ?""",
            (str(machine_key), str(machine_key), int(limit)),
        ).fetchall()
        return tuple(
            {
                "report_id": int(row["id"]), "machine": row["machine_key"],
                "kind": row["kind"], "subject": row["subject"],
                "recorded_at": row["recorded_at"],
                **json.loads(row["body_json"]),
            }
            for row in rows
        )

    def overview(self, *, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        chosen = normalise(language)
        return {
            "machines": [machine.record(chosen) for machine in self.machines()],
            "never_on_the_web_container": list(NEVER_ON_THE_WEB_CONTAINER),
            "reports": list(self.reports()),
        }


def machine_name(name: str) -> Message:
    """A machine's own name, the same in every language."""
    return verbatim(name)
