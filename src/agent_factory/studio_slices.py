"""What you can play at the end of a stage, or why there is nothing yet.

A stage that ends in silence is the failure this module exists to prevent. Every
stage boundary is declared, and there are exactly two honest declarations: a
slice you can play, backed by a build that exists and carries its evidence, or
an explicit "there is nothing to test here yet" with the reason.

The two are not interchangeable, and neither can be faked:

* a playable boundary needs a version that is actually in the playable ledger,
  and one whose evidence has no gap - a build nobody could run is not a slice;
* a "nothing to test" boundary needs a reason, because a stage that produced
  nothing worth playing should say what it did produce.

Declarations are kept, not overwritten. A later slice supersedes an earlier one
for the same stage; the earlier declaration stays in the record, because the
history of what was playable when is part of what makes the claim checkable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from .localisation import DEFAULT_LANGUAGE, LocalisedError, Message, normalise

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from .storage import SQLiteStorage

OUTCOMES = ("playable", "nothing_to_test")


class SliceRefused(LocalisedError):
    """Raised when declaring this would claim something that is not there."""


NO_SUCH_BUILD = Message(
    "Такої зібраної версії немає: {version}. Зріз без збірки — це не зріз.",
    "There is no such built version: {version}. A slice without a build is not "
    "a slice.",
)
EVIDENCE_GAP = Message(
    "У версії {version} бракує доказів: {gap}. Її не можна пропонувати як "
    "грабельну.",
    "Version {version} has a gap in its evidence: {gap}. It cannot be offered "
    "as playable.",
)
STAGE_REQUIRED = Message(
    "Межа належить конкретному етапу.", "A boundary belongs to a named stage.",
)

SLICE_MIGRATION = """
CREATE TABLE studio_stage_boundaries(
    id INTEGER PRIMARY KEY,
    mission TEXT NOT NULL,
    stage_key TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK(outcome IN ('playable','nothing_to_test')),
    project_key TEXT NOT NULL DEFAULT '',
    version_digest TEXT NOT NULL DEFAULT '',
    reason_uk TEXT NOT NULL DEFAULT '',
    reason_en TEXT NOT NULL DEFAULT '',
    declared_by TEXT NOT NULL DEFAULT '',
    declared_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK((outcome='playable' AND length(version_digest)=64)
       OR (outcome='nothing_to_test' AND length(reason_uk)>0 AND length(reason_en)>0))
);
CREATE INDEX idx_studio_boundaries_mission ON studio_stage_boundaries(mission, stage_key, id);

-- What was playable when is part of what makes the claim checkable, so a
-- declaration is superseded by a later one rather than rewritten.
CREATE TRIGGER studio_stage_boundaries_no_update
BEFORE UPDATE ON studio_stage_boundaries
BEGIN SELECT RAISE(ABORT, 'a declared stage boundary cannot be rewritten'); END;
CREATE TRIGGER studio_stage_boundaries_no_delete
BEFORE DELETE ON studio_stage_boundaries
BEGIN SELECT RAISE(ABORT, 'a declared stage boundary cannot be deleted'); END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Boundary:
    """What one stage ended with."""

    stage_key: str
    outcome: str
    version_digest: str = ""
    project_key: str = ""
    reason: Message | None = None
    declared_by: str = ""
    declared_at: str = ""

    @property
    def playable(self) -> bool:
        return self.outcome == "playable"

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "stage": self.stage_key,
            "outcome": self.outcome,
            "playable": self.playable,
            "version": self.version_digest,
            "project": self.project_key,
            "reason": self.reason.text(language) if self.reason else "",
            "declared_by": self.declared_by,
            "declared_at": self.declared_at,
        }


class StageBoundaries:
    """Every stage's ending, declared once and kept."""

    def __init__(self, storage: "SQLiteStorage"):
        self.storage = storage

    # -- declaring

    def playable(
        self,
        mission: str,
        stage_key: str,
        *,
        project_key: str,
        version_digest: str,
        declared_by: str = "",
    ) -> Boundary:
        """Offer a slice, but only one that was really built and really checked."""
        stage = str(stage_key).strip()
        if not stage:
            raise SliceRefused(STAGE_REQUIRED)
        row = self.storage.db.execute(
            """SELECT evidence_gap_json FROM playable_versions
                WHERE project_key=? AND version_digest=?""",
            (str(project_key), str(version_digest)),
        ).fetchone()
        if row is None:
            raise SliceRefused(NO_SUCH_BUILD, version=str(version_digest)[:12])
        gap = json.loads(row["evidence_gap_json"] or "[]")
        if gap:
            raise SliceRefused(
                EVIDENCE_GAP,
                version=str(version_digest)[:12],
                gap=", ".join(str(item) for item in gap),
            )
        declared_at = _now()
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO studio_stage_boundaries
                   (mission,stage_key,outcome,project_key,version_digest,
                    declared_by,declared_at)
                   VALUES(?,?,'playable',?,?,?,?)""",
                (
                    str(mission), stage, str(project_key), str(version_digest),
                    str(declared_by), declared_at,
                ),
            )
        return Boundary(
            stage, "playable", str(version_digest), str(project_key),
            None, str(declared_by), declared_at,
        )

    def nothing_to_test(
        self, mission: str, stage_key: str, *, reason: Message, declared_by: str = "",
    ) -> Boundary:
        """Say a stage produced nothing to play, and say what it did produce.

        The reason is a ``Message``, which cannot exist empty or in one language
        only, so "nothing to test" always arrives with something to read.
        """
        stage = str(stage_key).strip()
        if not stage:
            raise SliceRefused(STAGE_REQUIRED)
        declared_at = _now()
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO studio_stage_boundaries
                   (mission,stage_key,outcome,reason_uk,reason_en,declared_by,declared_at)
                   VALUES(?,?,'nothing_to_test',?,?,?,?)""",
                (str(mission), stage, reason.uk, reason.en, str(declared_by), declared_at),
            )
        return Boundary(
            stage, "nothing_to_test", "", "", reason, str(declared_by), declared_at,
        )

    # -- reading

    def _boundary(self, row: Any) -> Boundary:
        reason = (
            Message(row["reason_uk"], row["reason_en"])
            if row["reason_uk"] and row["reason_en"] else None
        )
        return Boundary(
            row["stage_key"], row["outcome"], row["version_digest"],
            row["project_key"], reason, row["declared_by"], row["declared_at"],
        )

    def current(self, mission: str) -> dict[str, Boundary]:
        """The latest declaration for each stage of this mission."""
        rows = self.storage.db.execute(
            """SELECT * FROM studio_stage_boundaries
                WHERE mission=? ORDER BY id""",
            (str(mission),),
        ).fetchall()
        latest: dict[str, Boundary] = {}
        for row in rows:
            latest[row["stage_key"]] = self._boundary(row)
        return latest

    def playable_map(self, mission: str) -> dict[str, str]:
        """Stage to version, for the stages that really do have something to play."""
        return {
            stage: boundary.version_digest
            for stage, boundary in self.current(mission).items()
            if boundary.playable
        }

    def history(self, mission: str, *, limit: int = 50) -> tuple[Boundary, ...]:
        rows = self.storage.db.execute(
            """SELECT * FROM studio_stage_boundaries
                WHERE mission=? ORDER BY id DESC LIMIT ?""",
            (str(mission), int(limit)),
        ).fetchall()
        return tuple(self._boundary(row) for row in rows)

    def report(
        self, mission: str, *, language: str = DEFAULT_LANGUAGE
    ) -> dict[str, Any]:
        chosen = normalise(language)
        current = self.current(mission)
        return {
            "mission": str(mission),
            "playable": [
                boundary.record(chosen) for boundary in current.values()
                if boundary.playable
            ],
            "stages": {
                stage: boundary.record(chosen) for stage, boundary in current.items()
            },
            "history": [item.record(chosen) for item in self.history(mission)],
        }
