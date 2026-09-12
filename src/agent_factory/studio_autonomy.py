"""Who decides, and what is still worth waking a person for.

The checks do not disappear; the clicking does. A person who wants a game has
no idea what a backlog revision is, and asking them to approve one is not
safety, it is a wall. So each gate that used to wait for a click is answered by
a written policy, and the answer is recorded with the policy that produced it.

Three things still deserve a person, and only these three:

* money beyond the limit they set;
* an action that cannot be undone;
* a request outside what this product declares it can do.

Everything else is decided, logged and continued. A question raised here is a
question in the feed, not a wall: work that does not depend on the answer keeps
going, and a question that is never answered blocks only what it gates.

This module decides and records. It starts nothing and stops nothing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence, TYPE_CHECKING

from .localisation import DEFAULT_LANGUAGE, LocalisedError, Message, normalise

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from .storage import SQLiteStorage

GATES = (
    "backlog_revision",
    "execution_authorization",
    "environment_profile",
    "schema_compatibility",
    "engine_evidence",
)
DISPOSITIONS = ("by_policy", "always_automatic", "always_evidence")
ASK_REASONS = ("over_budget", "irreversible", "beyond_capability")
QUESTION_STATES = ("open", "answered", "withdrawn")


class AutonomyRefused(LocalisedError):
    """Raised when a decision would have to claim something that is not true."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class Gate:
    """One place that used to wait for a click."""

    gate_id: str
    title: Message
    disposition: str
    policy: Message

    def __post_init__(self) -> None:
        if self.gate_id not in GATES:
            raise ValueError(f"Unknown gate: {self.gate_id!r}")
        if self.disposition not in DISPOSITIONS:
            raise ValueError(f"Unknown disposition: {self.disposition!r}")

    @property
    def automatic(self) -> bool:
        return self.disposition != "always_evidence"

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "gate": self.gate_id,
            "title": self.title.text(language),
            "disposition": self.disposition,
            "automatic": self.automatic,
            "policy": self.policy.text(language),
        }


CATALOGUE: tuple[Gate, ...] = (
    Gate(
        "backlog_revision",
        Message("Зміна плану робіт", "A change to the plan of work"),
        "by_policy",
        Message(
            "Застосовується автоматично. План видно завжди, і на паузі його можна "
            "правити.",
            "Applied automatically. The plan is always visible, and can be edited "
            "while the work is paused.",
        ),
    ),
    Gate(
        "execution_authorization",
        Message("Дозвіл на виконання", "Permission to run the work"),
        "by_policy",
        Message(
            "Видається на старті місії й записується в журнал.",
            "Granted when the mission starts, and written to the journal.",
        ),
    ),
    Gate(
        "environment_profile",
        Message("Готовність середовища", "Readiness of the environment"),
        "by_policy",
        Message(
            "Провал перевірки стає задачею «полагодити середовище», а не екраном, "
            "що все спиняє.",
            "A failed check becomes a task to fix the environment, not a screen "
            "that stops everything.",
        ),
    ),
    Gate(
        "schema_compatibility",
        Message("Сумісність схеми даних", "Compatibility of the stored data"),
        "always_automatic",
        Message(
            "Лишається обовʼязковою перевіркою: це захист уже збережених даних.",
            "Stays a required check: it protects data that already exists.",
        ),
    ),
    Gate(
        "engine_evidence",
        Message("Докази від движка", "Evidence from the engine"),
        "always_evidence",
        Message(
            "Зріз без реального запуску движка не позначається грабельним. Це "
            "не ворота для людини — це доказ, який ніхто не може підписати за движок.",
            "A slice is not called playable without the engine actually running. "
            "This is not a gate for a person: it is evidence nobody can sign on "
            "the engine's behalf.",
        ),
    ),
)
BY_ID: Mapping[str, Gate] = {gate.gate_id: gate for gate in CATALOGUE}


# ----------------------------------------------------- when a person is needed

OVER_BUDGET = Message(
    "Наступний крок коштує {amount} {unit}, а залишок ліміту — {remaining} {unit}.",
    "The next step costs {amount} {unit}, and {remaining} {unit} is left of the limit.",
)
OVER_BUDGET_ASK = Message(
    "Підняти ліміт і продовжити, чи зупинитись тут?",
    "Raise the limit and continue, or stop here?",
)
IRREVERSIBLE = Message(
    "Дію «{action}» не можна скасувати.",
    "The action '{action}' cannot be undone.",
)
IRREVERSIBLE_ASK = Message(
    "Виконати її чи пропустити?", "Do it, or skip it?",
)
BEYOND_CAPABILITY = Message(
    "Запит виходить за те, що продукт про себе заявляє: {statement}",
    "The request goes beyond what the product claims it can do: {statement}",
)
BEYOND_CAPABILITY_ASK = Message(
    "Спробувати як дослідження з невідомим результатом, чи звузити задачу?",
    "Try it as an investigation with an unknown outcome, or narrow the task?",
)
DECIDED_BY_POLICY = Message(
    "Вирішено політикою, без людини.", "Decided by policy, with no person involved.",
)
EVIDENCE_REQUIRED = Message(
    "Рішення чекає не на людину, а на доказ.",
    "This waits for evidence, not for a person.",
)


@dataclass(frozen=True)
class Question:
    """One short question in the feed. It blocks only what it is about."""

    reason: str
    subject: Message
    ask: Message
    options: tuple[str, ...]
    blocks: str = ""

    def __post_init__(self) -> None:
        if self.reason not in ASK_REASONS:
            raise ValueError(f"Unknown reason to ask: {self.reason!r}")

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "subject": self.subject.text(language),
            "ask": self.ask.text(language),
            "options": list(self.options),
            "blocks": self.blocks,
        }


@dataclass(frozen=True)
class Decision:
    """What was decided about one gate, and who decided it."""

    gate_id: str
    automatic: bool
    summary: Message
    policy: Message
    question: Question | None = None
    context_digest: str = ""
    decided_at: str = ""

    @property
    def needs_person(self) -> bool:
        return self.question is not None

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "gate": self.gate_id,
            "automatic": self.automatic,
            "needs_person": self.needs_person,
            "summary": self.summary.text(language),
            "policy": self.policy.text(language),
            "question": self.question.record(language) if self.question else None,
            "context": self.context_digest,
            "decided_at": self.decided_at,
        }


def over_budget(
    *, amount: float, remaining: float, unit: str = "USD", blocks: str = ""
) -> Question:
    return Question(
        "over_budget",
        Message(
            OVER_BUDGET.uk.format(amount=amount, remaining=remaining, unit=unit),
            OVER_BUDGET.en.format(amount=amount, remaining=remaining, unit=unit),
        ),
        OVER_BUDGET_ASK,
        ("raise_limit", "stop"),
        blocks,
    )


def irreversible(action: str, *, blocks: str = "") -> Question:
    return Question(
        "irreversible",
        Message(
            IRREVERSIBLE.uk.format(action=action),
            IRREVERSIBLE.en.format(action=action),
        ),
        IRREVERSIBLE_ASK,
        ("do_it", "skip"),
        blocks,
    )


def beyond_capability(statement: str, *, blocks: str = "") -> Question:
    return Question(
        "beyond_capability",
        Message(
            BEYOND_CAPABILITY.uk.format(statement=statement),
            BEYOND_CAPABILITY.en.format(statement=statement),
        ),
        BEYOND_CAPABILITY_ASK,
        ("investigate", "narrow"),
        blocks,
    )


def decide(
    gate_id: str,
    *,
    context: Mapping[str, Any] | None = None,
    question: Question | None = None,
    at: str = "",
) -> Decision:
    """Answer a gate by policy, unless one of the three cases needs a person."""
    gate = BY_ID.get(str(gate_id))
    if gate is None:
        raise ValueError(f"Unknown gate: {gate_id!r}")
    if gate.disposition == "always_evidence":
        # No person may sign for the engine, so this one is never "asked" either.
        return Decision(
            gate.gate_id, False, EVIDENCE_REQUIRED, gate.policy, None,
            _digest(dict(context or {})), at or _now(),
        )
    if question is not None:
        return Decision(
            gate.gate_id, False, question.subject, gate.policy, question,
            _digest(dict(context or {})), at or _now(),
        )
    return Decision(
        gate.gate_id, True, DECIDED_BY_POLICY, gate.policy, None,
        _digest(dict(context or {})), at or _now(),
    )


def catalogue(language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
    """What is automatic, what needs evidence, and what a person is still asked."""
    return {
        "gates": [gate.record(language) for gate in CATALOGUE],
        "asks_a_person_only_for": list(ASK_REASONS),
    }


# ------------------------------------------------------------------- storage

AUTONOMY_MIGRATION = """
CREATE TABLE studio_decisions(
    id INTEGER PRIMARY KEY,
    mission TEXT NOT NULL DEFAULT '',
    gate TEXT NOT NULL,
    automatic INTEGER NOT NULL CHECK(automatic IN (0,1)),
    summary_uk TEXT NOT NULL,
    summary_en TEXT NOT NULL,
    policy_uk TEXT NOT NULL,
    policy_en TEXT NOT NULL,
    context_digest TEXT NOT NULL DEFAULT '',
    decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_studio_decisions_mission ON studio_decisions(mission, id);

CREATE TABLE studio_questions(
    id INTEGER PRIMARY KEY,
    decision_id INTEGER NOT NULL REFERENCES studio_decisions(id),
    mission TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL,
    subject_uk TEXT NOT NULL,
    subject_en TEXT NOT NULL,
    ask_uk TEXT NOT NULL,
    ask_en TEXT NOT NULL,
    options_json TEXT NOT NULL CHECK(json_valid(options_json)),
    blocks TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'open'
        CHECK(state IN ('open','answered','withdrawn')),
    answer TEXT NOT NULL DEFAULT '',
    answered_by TEXT NOT NULL DEFAULT '',
    answered_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_studio_questions_state ON studio_questions(state, id);

-- A decision is a record of what the machine did on its own. If it could be
-- edited afterwards, it would stop being a reason to trust the automation.
CREATE TRIGGER studio_decisions_no_update
BEFORE UPDATE ON studio_decisions
BEGIN SELECT RAISE(ABORT, 'a recorded decision cannot be rewritten'); END;
CREATE TRIGGER studio_decisions_no_delete
BEFORE DELETE ON studio_decisions
BEGIN SELECT RAISE(ABORT, 'a recorded decision cannot be deleted'); END;
-- A question may be answered once, or withdrawn. Its text never changes.
CREATE TRIGGER studio_questions_answer_once
BEFORE UPDATE ON studio_questions
WHEN OLD.state <> 'open'
  OR OLD.subject_uk <> NEW.subject_uk OR OLD.ask_uk <> NEW.ask_uk
  OR OLD.reason <> NEW.reason OR OLD.blocks <> NEW.blocks
BEGIN SELECT RAISE(ABORT, 'a question may be answered once and never rewritten'); END;
"""

ANSWER_REQUIRED = Message(
    "Відповідь записується на конкретну людину. Вкажіть імʼя.",
    "An answer is recorded against a named person. Enter a name.",
)
NOT_AN_OPTION = Message(
    "«{answer}» не є одним із запропонованих варіантів.",
    "'{answer}' is not one of the offered options.",
)
ALREADY_ANSWERED = Message(
    "На це питання вже відповіли.", "This question has already been answered.",
)


class AutonomyJournal:
    """Every decision the studio made without asking, and every time it asked."""

    def __init__(self, storage: "SQLiteStorage"):
        self.storage = storage

    def record(self, decision: Decision, *, mission: str = "") -> int:
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO studio_decisions
                   (mission,gate,automatic,summary_uk,summary_en,policy_uk,policy_en,
                    context_digest,decided_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    str(mission), decision.gate_id, int(decision.automatic),
                    decision.summary.uk, decision.summary.en,
                    decision.policy.uk, decision.policy.en,
                    decision.context_digest, decision.decided_at or _now(),
                ),
            )
            decision_id = int(cursor.lastrowid)
            if decision.question is not None:
                question = decision.question
                self.storage.db.execute(
                    """INSERT INTO studio_questions
                       (decision_id,mission,reason,subject_uk,subject_en,ask_uk,ask_en,
                        options_json,blocks)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        decision_id, str(mission), question.reason,
                        question.subject.uk, question.subject.en,
                        question.ask.uk, question.ask.en,
                        json.dumps(list(question.options)), question.blocks,
                    ),
                )
        return decision_id

    def decisions(
        self, *, mission: str = "", limit: int = 50, language: str = DEFAULT_LANGUAGE
    ) -> tuple[dict[str, Any], ...]:
        chosen = normalise(language)
        rows = self.storage.db.execute(
            """SELECT * FROM studio_decisions
                WHERE (?='' OR mission=?) ORDER BY id DESC LIMIT ?""",
            (str(mission), str(mission), int(limit)),
        ).fetchall()
        return tuple(
            {
                "decision_id": int(row["id"]),
                "mission": row["mission"],
                "gate": row["gate"],
                "automatic": bool(row["automatic"]),
                "summary": row[f"summary_{chosen}"],
                "policy": row[f"policy_{chosen}"],
                "context": row["context_digest"],
                "decided_at": row["decided_at"],
            }
            for row in rows
        )

    def open_questions(
        self, *, mission: str = "", language: str = DEFAULT_LANGUAGE
    ) -> tuple[dict[str, Any], ...]:
        chosen = normalise(language)
        rows = self.storage.db.execute(
            """SELECT * FROM studio_questions
                WHERE state='open' AND (?='' OR mission=?) ORDER BY id""",
            (str(mission), str(mission)),
        ).fetchall()
        return tuple(
            {
                "question_id": int(row["id"]),
                "mission": row["mission"],
                "reason": row["reason"],
                "subject": row[f"subject_{chosen}"],
                "ask": row[f"ask_{chosen}"],
                "options": json.loads(row["options_json"]),
                "blocks": row["blocks"],
            }
            for row in rows
        )

    def blocked_by_questions(self, *, mission: str = "") -> tuple[str, ...]:
        """Only what an unanswered question is actually about is held up."""
        return tuple(
            sorted({
                item["blocks"] for item in self.open_questions(mission=mission)
                if item["blocks"]
            })
        )

    def answer(self, question_id: int, *, answer: str, actor: str) -> dict[str, Any]:
        who = str(actor).strip()
        if not who:
            raise AutonomyRefused(ANSWER_REQUIRED)
        row = self.storage.db.execute(
            "SELECT state,options_json FROM studio_questions WHERE id=?",
            (int(question_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown question {question_id}")
        if row["state"] != "open":
            raise AutonomyRefused(ALREADY_ANSWERED)
        if str(answer) not in json.loads(row["options_json"]):
            raise AutonomyRefused(NOT_AN_OPTION, answer=answer)
        answered_at = _now()
        with self.storage.db:
            self.storage.db.execute(
                """UPDATE studio_questions
                      SET state='answered',answer=?,answered_by=?,answered_at=?
                    WHERE id=?""",
                (str(answer), who, answered_at, int(question_id)),
            )
        return {
            "question_id": int(question_id), "answer": str(answer),
            "answered_by": who, "answered_at": answered_at,
        }

    def withdraw(self, question_id: int) -> None:
        """A question whose subject went away stops waiting for an answer."""
        with self.storage.db:
            self.storage.db.execute(
                "UPDATE studio_questions SET state='withdrawn' WHERE id=? AND state='open'",
                (int(question_id),),
            )

    def report(
        self, *, mission: str = "", language: str = DEFAULT_LANGUAGE, limit: int = 50
    ) -> dict[str, Any]:
        return {
            **catalogue(language),
            "mission": mission,
            "decisions": list(self.decisions(mission=mission, limit=limit, language=language)),
            "questions": list(self.open_questions(mission=mission, language=language)),
            "blocked": list(self.blocked_by_questions(mission=mission)),
        }
