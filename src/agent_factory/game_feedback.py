"""A sentence after playing becomes the next version, or an honest refusal.

"Make the jump higher" is the whole interface a twelve-year-old should need.
What must not happen behind that sentence is any of the following: text or a
screenshot leaving the machine without being shown first; a plan that quietly
adds cost or scope; a build that passes its own tests being presented as proof
that the jump is higher; or the version they were happily playing disappearing
because the next one is being made.

So this module keeps four things separate and refuses to blur them:

* what the person said, attached to the build they actually played;
* what would leave this machine, previewed before anything is sent;
* what the change would cost and what it would put at risk, accepted by a
  named person rather than assumed;
* whether the requested behaviour was actually checked afterwards, which is
  not the same question as whether the build succeeded.

It composes and refuses. It does not build, does not call a provider and does
not move the playable pointer; those belong to the caller.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .localisation import DEFAULT_LANGUAGE, LocalisedError, Message, verbatim

ATTACHMENT_KINDS = ("note", "steps", "screenshot", "save")
IMPACTS = ("unaffected", "possibly_affected", "replaced")
VERDICTS = ("holds", "fails", "not_checked")
MAX_WISH = 2000
MAX_STEP = 400
MAX_STEPS = 20

_WHITESPACE = re.compile(r"\s+")


class FeedbackRefused(LocalisedError):
    """Raised when accepting would mean claiming something that is not true."""


EMPTY_WISH = Message(
    "Напишіть, що саме змінити. Порожній відгук нічого не означає.",
    "Say what to change. An empty note means nothing.",
)
TOO_LONG = Message(
    "Відгук задовгий: {length} символів, дозволено {limit}.",
    "The note is too long: {length} characters, {limit} allowed.",
)
UNKNOWN_ATTACHMENT = Message(
    "Невідомий вид вкладення: {kind}.", "Unknown kind of attachment: {kind}.",
)
COST_NOT_ACCEPTED = Message(
    "План додає витрати. Їх приймає названа людина, а не система.",
    "The plan adds cost. A named person accepts it, not the system.",
)
SCOPE_NOT_ACCEPTED = Message(
    "План виходить за межі того, що вже погоджено. Потрібне явне «так».",
    "The plan goes beyond what was already agreed. It needs an explicit yes.",
)
ACTOR_REQUIRED = Message(
    "Прийняття плану записується на конкретну людину. Вкажіть імʼя.",
    "Accepting a plan is recorded against a named person. Enter a name.",
)
NOT_THE_PLAYED_BUILD = Message(
    "Відгук про версію {played}, а зараз грається {current}. Зміну буде "
    "застосовано до поточної версії.",
    "The note is about version {played}, and {current} is the current one. The "
    "change will be applied on top of the current version.",
)
NOTHING_LEAVES = Message(
    "Нічого не залишає цей комп'ютер.", "Nothing leaves this computer.",
)
LEAVES_MACHINE = Message(
    "Це буде надіслано хмарному провайдеру: {items}.",
    "This will be sent to the cloud provider: {items}.",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _tidy(value: str, limit: int) -> str:
    return _WHITESPACE.sub(" ", str(value)).strip()[:limit]


@dataclass(frozen=True)
class PlayedBuild:
    """The version the person actually played, not the newest one."""

    project_key: str
    version_digest: str
    engine: str = ""
    played_at: str = ""

    def record(self) -> dict[str, Any]:
        return {
            "project_key": self.project_key,
            "version_digest": self.version_digest,
            "engine": self.engine,
            "played_at": self.played_at,
        }


@dataclass(frozen=True)
class Attachment:
    """Something offered along with the words, and whether it would be sent."""

    kind: str
    name: str
    size_bytes: int = 0
    digest: str = ""
    leaves_machine: bool = False

    def __post_init__(self) -> None:
        if self.kind not in ATTACHMENT_KINDS:
            raise FeedbackRefused(UNKNOWN_ATTACHMENT, kind=self.kind)

    def record(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "size_bytes": self.size_bytes,
            "digest": self.digest,
            "leaves_machine": self.leaves_machine,
        }


@dataclass(frozen=True)
class Feedback:
    """What the person said, bound to what they played."""

    build: PlayedBuild
    wish: str
    steps: tuple[str, ...] = ()
    attachments: tuple[Attachment, ...] = ()
    created_at: str = ""

    @classmethod
    def create(
        cls,
        *,
        build: PlayedBuild,
        wish: str,
        steps: Sequence[str] = (),
        attachments: Sequence[Attachment] = (),
        created_at: str = "",
    ) -> "Feedback":
        text = _tidy(wish, MAX_WISH + 1)
        if not text:
            raise FeedbackRefused(EMPTY_WISH)
        if len(text) > MAX_WISH:
            raise FeedbackRefused(TOO_LONG, length=len(text), limit=MAX_WISH)
        cleaned = tuple(
            _tidy(step, MAX_STEP) for step in list(steps)[:MAX_STEPS]
            if _tidy(step, MAX_STEP)
        )
        return cls(build, text, cleaned, tuple(attachments), created_at or _now())

    @property
    def digest(self) -> str:
        return _digest(
            self.build.project_key, self.build.version_digest, self.wish,
            *self.steps,
        )

    def preview(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        """Exactly what would be sent, in the person's own words, before sending."""
        leaving = [item for item in self.attachments if item.leaves_machine]
        sentence = (
            LEAVES_MACHINE.text(
                language, items=", ".join(item.name for item in leaving),
            )
            if leaving else NOTHING_LEAVES.text(language)
        )
        return {
            "digest": self.digest,
            "build": self.build.record(),
            "wish": self.wish,
            "steps": list(self.steps),
            "attachments": [item.record() for item in self.attachments],
            "leaves_machine": [item.name for item in leaving],
            "transmission": sentence,
        }


@dataclass(frozen=True)
class Change:
    """One thing the next version would do differently."""

    summary: Message
    touches: tuple[str, ...] = ()

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {"summary": self.summary.text(language), "touches": list(self.touches)}


@dataclass(frozen=True)
class RequirementImpact:
    """What a change does to something that was already agreed."""

    requirement_id: str
    impact: str
    note: Message

    def __post_init__(self) -> None:
        if self.impact not in IMPACTS:
            raise ValueError(f"Unknown impact: {self.impact!r}")

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "requirement": self.requirement_id,
            "impact": self.impact,
            "note": self.note.text(language),
        }


@dataclass(frozen=True)
class Cost:
    """What the change would add, in the currency the caller already uses."""

    amount: float = 0.0
    unit: str = "USD"
    basis: Message | None = None

    @property
    def free(self) -> bool:
        return self.amount <= 0

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "amount": self.amount,
            "unit": self.unit,
            "basis": self.basis.text(language) if self.basis else "",
        }


@dataclass(frozen=True)
class ChangePlan:
    """What would be done, what it disturbs, and what it costs."""

    feedback_digest: str
    changes: tuple[Change, ...]
    impacts: tuple[RequirementImpact, ...]
    added_scope: tuple[Message, ...]
    cost: Cost
    applies_to: str
    note: Message | None = None
    accepted_by: str = ""
    accepted_at: str = ""

    @property
    def accepted(self) -> bool:
        return bool(self.accepted_by)

    @property
    def adds_cost(self) -> bool:
        return not self.cost.free

    @property
    def adds_scope(self) -> bool:
        return bool(self.added_scope)

    def needs_acceptance(self) -> tuple[Message, ...]:
        """Everything a person must say yes to before this may proceed."""
        required: list[Message] = []
        if self.adds_cost:
            required.append(COST_NOT_ACCEPTED)
        if self.adds_scope:
            required.append(SCOPE_NOT_ACCEPTED)
        return tuple(required)

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "feedback": self.feedback_digest,
            "applies_to": self.applies_to,
            "changes": [change.record(language) for change in self.changes],
            "impacts": [impact.record(language) for impact in self.impacts],
            "added_scope": [item.text(language) for item in self.added_scope],
            "cost": self.cost.record(language),
            "note": self.note.text(language) if self.note else "",
            "needs_acceptance": [item.text(language) for item in self.needs_acceptance()],
            "accepted": self.accepted,
            "accepted_by": self.accepted_by,
            "accepted_at": self.accepted_at,
        }


def plan_change(
    *,
    feedback: Feedback,
    changes: Sequence[Change],
    impacts: Sequence[RequirementImpact] = (),
    added_scope: Sequence[Message] = (),
    cost: Cost | None = None,
    current_version: str = "",
) -> ChangePlan:
    """Assemble a plan, and say out loud when it is not built on what was played."""
    applies_to = current_version or feedback.build.version_digest
    note = None
    if current_version and current_version != feedback.build.version_digest:
        note = Message(
            NOT_THE_PLAYED_BUILD.uk.format(
                played=feedback.build.version_digest[:12], current=current_version[:12],
            ),
            NOT_THE_PLAYED_BUILD.en.format(
                played=feedback.build.version_digest[:12], current=current_version[:12],
            ),
        )
    return ChangePlan(
        feedback_digest=feedback.digest,
        changes=tuple(changes),
        impacts=tuple(impacts),
        added_scope=tuple(added_scope),
        cost=cost or Cost(),
        applies_to=applies_to,
        note=note,
    )


def accept_plan(
    plan: ChangePlan,
    *,
    actor: str,
    accept_cost: bool = False,
    accept_scope: bool = False,
    at: str = "",
) -> ChangePlan:
    """Accept a plan on behalf of a named person, and only what they accepted."""
    who = str(actor).strip()
    if not who:
        raise FeedbackRefused(ACTOR_REQUIRED)
    if plan.adds_cost and not accept_cost:
        raise FeedbackRefused(COST_NOT_ACCEPTED)
    if plan.adds_scope and not accept_scope:
        raise FeedbackRefused(SCOPE_NOT_ACCEPTED)
    return replace(plan, accepted_by=who, accepted_at=at or _now())


# ------------------------------------------------------ did it do what I asked

@dataclass(frozen=True)
class BehaviourCheck:
    """A check that claims to be about this wish, and what it did."""

    wish_digest: str
    description: Message
    ran: bool
    passed: bool
    evidence: str = ""

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "wish": self.wish_digest,
            "description": self.description.text(language),
            "ran": self.ran,
            "passed": self.passed,
            "evidence": self.evidence,
        }


HOLDS = Message(
    "Перевірено саме те, що ви просили, і воно працює.",
    "The thing you asked for was checked, and it works.",
)
FAILS = Message(
    "Перевірено саме те, що ви просили, і воно ще не працює.",
    "The thing you asked for was checked, and it does not work yet.",
)
NOT_CHECKED = Message(
    "Ніхто не перевіряв саме те, що ви просили. Успішна збірка цього не доводить.",
    "Nobody checked the thing you asked for. A build that succeeded is not "
    "evidence that it does.",
)
NO_EVIDENCE = Message(
    "Перевірка є, але без доказу, тож вона нічого не підтверджує.",
    "There is a check but no evidence, so it confirms nothing.",
)


@dataclass(frozen=True)
class Verdict:
    """Whether the requested behaviour was checked - not whether the build passed."""

    state: str
    summary: Message
    checks: tuple[BehaviourCheck, ...]
    previous_version: str = ""

    @property
    def confirmed(self) -> bool:
        return self.state == "holds"

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "state": self.state,
            "confirmed": self.confirmed,
            "summary": self.summary.text(language),
            "checks": [check.record(language) for check in self.checks],
            "previous_version": self.previous_version,
            "revert_available": bool(self.previous_version),
        }


def judge(
    feedback: Feedback,
    checks: Iterable[BehaviourCheck],
    *,
    previous_version: str = "",
) -> Verdict:
    """A build that succeeded is not evidence that the wish came true."""
    mine = tuple(
        check for check in checks
        if check.wish_digest == feedback.digest and check.ran
    )
    if not mine:
        return Verdict("not_checked", NOT_CHECKED, tuple(), previous_version)
    without_evidence = [check for check in mine if check.passed and not check.evidence]
    if any(not check.passed for check in mine):
        return Verdict("fails", FAILS, mine, previous_version)
    if without_evidence:
        return Verdict("not_checked", NO_EVIDENCE, mine, previous_version)
    return Verdict("holds", HOLDS, mine, previous_version)


def summarise(
    feedback: Feedback,
    plan: ChangePlan,
    verdict: Verdict | None = None,
    *,
    language: str = DEFAULT_LANGUAGE,
) -> dict[str, Any]:
    """One record of the whole round trip, in one language."""
    return {
        "feedback": feedback.preview(language),
        "plan": plan.record(language),
        "verdict": verdict.record(language) if verdict else None,
    }


# ------------------------------------------------------------------- storage

FEEDBACK_MIGRATION = """
CREATE TABLE game_feedback(
    id INTEGER PRIMARY KEY,
    digest TEXT NOT NULL UNIQUE CHECK(length(digest)=64),
    project_key TEXT NOT NULL,
    played_version TEXT NOT NULL,
    engine TEXT NOT NULL DEFAULT '',
    played_at TEXT NOT NULL DEFAULT '',
    wish TEXT NOT NULL CHECK(length(wish)>0),
    steps_json TEXT NOT NULL CHECK(json_valid(steps_json)),
    attachments_json TEXT NOT NULL CHECK(json_valid(attachments_json)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_game_feedback_project ON game_feedback(project_key, id);

CREATE TABLE game_feedback_plans(
    id INTEGER PRIMARY KEY,
    feedback_id INTEGER NOT NULL REFERENCES game_feedback(id),
    applies_to TEXT NOT NULL,
    plan_json TEXT NOT NULL CHECK(json_valid(plan_json)),
    cost_amount REAL NOT NULL DEFAULT 0 CHECK(cost_amount>=0),
    cost_unit TEXT NOT NULL DEFAULT 'USD',
    accepted_by TEXT NOT NULL DEFAULT '',
    accepted_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_game_feedback_plans_feedback ON game_feedback_plans(feedback_id, id);

CREATE TABLE game_feedback_checks(
    id INTEGER PRIMARY KEY,
    feedback_id INTEGER NOT NULL REFERENCES game_feedback(id),
    description_uk TEXT NOT NULL,
    description_en TEXT NOT NULL,
    ran INTEGER NOT NULL CHECK(ran IN (0,1)),
    passed INTEGER NOT NULL CHECK(passed IN (0,1)),
    evidence TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_game_feedback_checks_feedback ON game_feedback_checks(feedback_id, id);

-- A note, a plan and a check are a record of what a person asked and what was
-- done about it. Rewriting one later would make that record a fiction.
CREATE TRIGGER game_feedback_no_update
BEFORE UPDATE ON game_feedback
BEGIN SELECT RAISE(ABORT, 'recorded feedback cannot be rewritten'); END;
CREATE TRIGGER game_feedback_no_delete
BEFORE DELETE ON game_feedback
BEGIN SELECT RAISE(ABORT, 'recorded feedback cannot be deleted'); END;
CREATE TRIGGER game_feedback_checks_no_update
BEFORE UPDATE ON game_feedback_checks
BEGIN SELECT RAISE(ABORT, 'a recorded check cannot be rewritten'); END;
-- A plan may be accepted after it is written, and nothing else about it may
-- change: acceptance is the one fact that arrives later.
CREATE TRIGGER game_feedback_plans_only_acceptance
BEFORE UPDATE ON game_feedback_plans
WHEN OLD.plan_json <> NEW.plan_json OR OLD.feedback_id <> NEW.feedback_id
     OR OLD.applies_to <> NEW.applies_to OR OLD.cost_amount <> NEW.cost_amount
     OR OLD.accepted_by <> ''
BEGIN SELECT RAISE(ABORT, 'a plan may only gain its acceptance'); END;
"""


class FeedbackJournal:
    """Everything a person asked for, kept exactly as they asked it."""

    def __init__(self, storage: Any):
        self.storage = storage

    # -- writing

    def record(self, feedback: Feedback) -> int:
        existing = self.storage.db.execute(
            "SELECT id FROM game_feedback WHERE digest=?", (feedback.digest,)
        ).fetchone()
        if existing:
            # The same words about the same build are the same note, not a new one.
            return int(existing["id"])
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO game_feedback
                   (digest,project_key,played_version,engine,played_at,wish,
                    steps_json,attachments_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    feedback.digest, feedback.build.project_key,
                    feedback.build.version_digest, feedback.build.engine,
                    feedback.build.played_at, feedback.wish,
                    json.dumps(list(feedback.steps), ensure_ascii=False),
                    json.dumps(
                        [item.record() for item in feedback.attachments],
                        ensure_ascii=False,
                    ),
                    feedback.created_at or _now(),
                ),
            )
        return int(cursor.lastrowid)

    def record_plan(self, feedback_id: int, plan: ChangePlan) -> int:
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO game_feedback_plans
                   (feedback_id,applies_to,plan_json,cost_amount,cost_unit,
                    accepted_by,accepted_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    int(feedback_id), plan.applies_to,
                    json.dumps(plan.record("uk"), ensure_ascii=False),
                    plan.cost.amount, plan.cost.unit,
                    plan.accepted_by, plan.accepted_at,
                ),
            )
        return int(cursor.lastrowid)

    def accept(self, plan_id: int, *, actor: str, at: str = "") -> None:
        """Record that a named person accepted a plan. Nothing else may change."""
        who = str(actor).strip()
        if not who:
            raise FeedbackRefused(ACTOR_REQUIRED)
        with self.storage.db:
            self.storage.db.execute(
                "UPDATE game_feedback_plans SET accepted_by=?,accepted_at=? WHERE id=?",
                (who, at or _now(), int(plan_id)),
            )

    def record_check(self, feedback_id: int, check: BehaviourCheck) -> int:
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO game_feedback_checks
                   (feedback_id,description_uk,description_en,ran,passed,evidence)
                   VALUES(?,?,?,?,?,?)""",
                (
                    int(feedback_id), check.description.uk, check.description.en,
                    int(check.ran), int(check.passed), check.evidence,
                ),
            )
        return int(cursor.lastrowid)

    # -- reading

    def feedback(self, feedback_id: int) -> Feedback:
        row = self.storage.db.execute(
            "SELECT * FROM game_feedback WHERE id=?", (int(feedback_id),)
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown feedback {feedback_id}")
        return Feedback(
            build=PlayedBuild(
                row["project_key"], row["played_version"], row["engine"],
                row["played_at"],
            ),
            wish=row["wish"],
            steps=tuple(json.loads(row["steps_json"])),
            attachments=tuple(
                Attachment(**item) for item in json.loads(row["attachments_json"])
            ),
            created_at=row["created_at"],
        )

    def checks(self, feedback_id: int) -> tuple[BehaviourCheck, ...]:
        note = self.feedback(feedback_id)
        rows = self.storage.db.execute(
            "SELECT * FROM game_feedback_checks WHERE feedback_id=? ORDER BY id",
            (int(feedback_id),),
        ).fetchall()
        return tuple(
            BehaviourCheck(
                note.digest,
                Message(row["description_uk"], row["description_en"]),
                bool(row["ran"]), bool(row["passed"]), row["evidence"],
            )
            for row in rows
        )

    def verdict(self, feedback_id: int, *, previous_version: str = "") -> Verdict:
        return judge(
            self.feedback(feedback_id), self.checks(feedback_id),
            previous_version=previous_version,
        )

    def history(self, project_key: str, *, limit: int = 20) -> tuple[dict[str, Any], ...]:
        rows = self.storage.db.execute(
            """SELECT f.id,f.digest,f.wish,f.played_version,f.created_at,
                      (SELECT COUNT(*) FROM game_feedback_plans p WHERE p.feedback_id=f.id)
                          AS plans,
                      (SELECT COUNT(*) FROM game_feedback_plans p
                        WHERE p.feedback_id=f.id AND p.accepted_by<>'') AS accepted
                 FROM game_feedback f WHERE f.project_key=?
                ORDER BY f.id DESC LIMIT ?""",
            (str(project_key), int(limit)),
        ).fetchall()
        return tuple(dict(row) for row in rows)
