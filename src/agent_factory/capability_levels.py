"""Declared support levels, and an honest answer to "can you build this?".

"Almost any complexity" is not a capability claim; it is a sales line. This
module replaces it with a small catalogue of levels, each with a declared
engine, feature set, hardware budget, performance target and playable
acceptance criteria - and with the rule that a level is only *supported* once a
real reference project passed every one of those criteria and a named person
reviewed the gameplay.

Nothing here defaults to yes. A level with no recorded evidence is proposed, a
request that a level only partly covers gets a scoped prototype with the
dropped parts named, and multiplayer, open world, console and VR are separate
investigations that no level silently absorbs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .asset_provenance import BUDGETS
from .godot_pack import SUPPORTED_ENGINE_VERSIONS

FEATURES = (
    "input", "ui", "audio", "save_load", "multi_level", "three_d",
)
DIMENSIONS = ("2d", "3d")
LEVEL_STATES = ("supported", "partial", "proposed")
SCOPE_OUTCOMES = ("supported", "scoped_prototype", "investigation", "unsupported")

INVESTIGATIONS: Mapping[str, str] = {
    "multiplayer": (
        "Netcode, hosting and abuse handling are a product of their own; no "
        "reference project has been run, so there is nothing to promise."
    ),
    "open_world": (
        "Streaming, budgets and content volume change every other requirement; "
        "it needs its own reference project before it can be offered."
    ),
    "console": (
        "Console needs a platform partner agreement and a qualified toolchain "
        "that this project does not have."
    ),
    "vr": (
        "VR has comfort, input and performance requirements that none of the "
        "current levels measure."
    ),
}


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class PerformanceTarget:
    frames_per_second: int
    resolution: str
    max_load_seconds: float
    max_build_minutes: float

    @property
    def record(self) -> dict[str, Any]:
        return {
            "frames_per_second": self.frames_per_second,
            "resolution": self.resolution,
            "max_load_seconds": self.max_load_seconds,
            "max_build_minutes": self.max_build_minutes,
        }


@dataclass(frozen=True)
class Level:
    level_id: str
    title: str
    summary: str
    dimension: str
    engine: str
    engine_versions: tuple[str, ...]
    features: frozenset[str]
    budget_profile: str
    performance: PerformanceTarget
    acceptance: Mapping[str, str]

    @classmethod
    def create(
        cls,
        level_id: str,
        *,
        title: str,
        summary: str,
        dimension: str,
        engine: str,
        engine_versions: Sequence[str],
        features: Iterable[str],
        budget_profile: str,
        performance: PerformanceTarget,
        acceptance: Mapping[str, str],
    ) -> "Level":
        if dimension not in DIMENSIONS:
            raise ValueError(f"Unknown dimension: {dimension!r}")
        if budget_profile not in BUDGETS:
            raise ValueError(f"Unknown asset budget profile: {budget_profile!r}")
        chosen = frozenset(str(value) for value in features)
        unknown = chosen - set(FEATURES)
        if unknown:
            raise ValueError("Unknown features: " + ", ".join(sorted(unknown)))
        overlap = chosen & set(INVESTIGATIONS)
        if overlap:
            raise ValueError(
                "A level may not claim an open investigation: "
                + ", ".join(sorted(overlap))
            )
        if not acceptance:
            raise ValueError("A level without acceptance criteria cannot be verified")
        if not engine_versions:
            raise ValueError("A level declares the engine versions it was measured on")
        return cls(
            str(level_id), str(title), str(summary), dimension, str(engine),
            tuple(str(value) for value in engine_versions), chosen,
            str(budget_profile), performance, dict(acceptance),
        )

    @property
    def record(self) -> dict[str, Any]:
        return {
            "level_id": self.level_id,
            "title": self.title,
            "summary": self.summary,
            "dimension": self.dimension,
            "engine": self.engine,
            "engine_versions": list(self.engine_versions),
            "features": sorted(self.features),
            "budget": BUDGETS[self.budget_profile].record,
            "performance": self.performance.record,
            "acceptance": dict(self.acceptance),
        }


@dataclass(frozen=True)
class LevelEvidence:
    """One real project that was built, played and reviewed at a level."""

    level_id: str
    reference_project: str
    version_digest: str
    checks: Mapping[str, bool]
    gameplay_reviewer: str
    recorded_at: str
    notes: str = ""

    @classmethod
    def create(
        cls,
        *,
        level_id: str,
        reference_project: str,
        version_digest: str,
        checks: Mapping[str, bool],
        gameplay_reviewer: str,
        recorded_at: str = "",
        notes: str = "",
    ) -> "LevelEvidence":
        if not str(reference_project).strip():
            raise ValueError("Evidence names the project it came from")
        if not str(version_digest).strip():
            raise ValueError("Evidence names the exact version it was taken from")
        if not str(gameplay_reviewer).strip():
            raise ValueError(
                "A level is not verified without a named person who played it"
            )
        if not checks:
            raise ValueError("Evidence records the criteria it checked")
        return cls(
            str(level_id), str(reference_project).strip(), str(version_digest).strip(),
            {str(key): bool(value) for key, value in checks.items()},
            str(gameplay_reviewer).strip(), str(recorded_at).strip() or _stamp(),
            str(notes)[:1000],
        )

    @property
    def record(self) -> dict[str, Any]:
        return {
            "level_id": self.level_id,
            "reference_project": self.reference_project,
            "version_digest": self.version_digest,
            "checks": dict(self.checks),
            "gameplay_reviewer": self.gameplay_reviewer,
            "recorded_at": self.recorded_at,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class LevelStatus:
    level: Level
    state: str
    evidence: tuple[LevelEvidence, ...]
    unmet: tuple[str, ...]
    unchecked: tuple[str, ...]

    @property
    def supported(self) -> bool:
        return self.state == "supported"

    @property
    def record(self) -> dict[str, Any]:
        return {
            "level_id": self.level.level_id,
            "state": self.state,
            "supported": self.supported,
            "evidence_count": len(self.evidence),
            "reviewers": sorted({item.gameplay_reviewer for item in self.evidence}),
            "criteria_failed": list(self.unmet),
            "criteria_without_evidence": list(self.unchecked),
        }


@dataclass(frozen=True)
class ScopeRequest:
    description: str
    features: frozenset[str]
    dimension: str = "2d"
    engine: str = "godot"

    @classmethod
    def create(
        cls,
        description: str,
        *,
        features: Iterable[str],
        dimension: str = "2d",
        engine: str = "godot",
    ) -> "ScopeRequest":
        chosen = frozenset(str(value) for value in features)
        unknown = chosen - set(FEATURES) - set(INVESTIGATIONS)
        if unknown:
            raise ValueError("Unknown features: " + ", ".join(sorted(unknown)))
        if dimension not in DIMENSIONS:
            raise ValueError(f"Unknown dimension: {dimension!r}")
        return cls(str(description)[:500], chosen, dimension, str(engine))


@dataclass(frozen=True)
class ScopeAnswer:
    outcome: str
    level_id: str | None
    guarantee: bool
    included: tuple[str, ...]
    excluded: tuple[str, ...]
    investigations: tuple[tuple[str, str], ...]
    missing_evidence: tuple[str, ...]
    statement: str

    @property
    def record(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "level_id": self.level_id,
            "guarantee": self.guarantee,
            "included": list(self.included),
            "excluded": list(self.excluded),
            "separate_investigations": [
                {"area": area, "reason": reason} for area, reason in self.investigations
            ],
            "missing_evidence": list(self.missing_evidence),
            "statement": self.statement,
        }


class CapabilityCatalogue:
    """What has actually been built at each level, and what that permits saying."""

    def __init__(
        self,
        evidence: Sequence[LevelEvidence] = (),
        *,
        levels: Sequence[Level] | None = None,
    ):
        catalogue = tuple(levels) if levels is not None else default_levels()
        identifiers = [level.level_id for level in catalogue]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Level identifiers must be unique")
        self._levels = {level.level_id: level for level in catalogue}
        self._evidence: list[LevelEvidence] = []
        for item in evidence:
            self.record_evidence(item)

    def levels(self) -> tuple[Level, ...]:
        return tuple(self._levels[key] for key in sorted(self._levels))

    def level(self, level_id: str) -> Level:
        try:
            return self._levels[str(level_id)]
        except KeyError as exc:
            raise KeyError(f"Unknown support level: {level_id}") from exc

    def record_evidence(self, evidence: LevelEvidence) -> None:
        level = self.level(evidence.level_id)
        unknown = set(evidence.checks) - set(level.acceptance)
        if unknown:
            raise ValueError(
                "Evidence refers to criteria this level does not declare: "
                + ", ".join(sorted(unknown))
            )
        self._evidence.append(evidence)

    def evidence(self, level_id: str) -> tuple[LevelEvidence, ...]:
        return tuple(
            item for item in self._evidence if item.level_id == str(level_id)
        )

    def status(self, level_id: str) -> LevelStatus:
        level = self.level(level_id)
        records = self.evidence(level.level_id)
        unmet: list[str] = []
        unchecked: list[str] = []
        for criterion in sorted(level.acceptance):
            results = [
                item.checks[criterion] for item in records if criterion in item.checks
            ]
            if not results:
                unchecked.append(criterion)
            elif not all(results):
                unmet.append(criterion)
        if not records:
            state = "proposed"
        elif unmet or unchecked:
            state = "partial"
        else:
            state = "supported"
        return LevelStatus(level, state, records, tuple(unmet), tuple(unchecked))

    def statuses(self) -> tuple[LevelStatus, ...]:
        return tuple(self.status(level.level_id) for level in self.levels())

    def scope(self, request: ScopeRequest) -> ScopeAnswer:
        """Answer a capability question without ever promising more than evidence."""
        investigations = tuple(
            (area, INVESTIGATIONS[area])
            for area in sorted(request.features & set(INVESTIGATIONS))
        )
        wanted = request.features - set(INVESTIGATIONS)
        candidates = [
            level for level in self.levels()
            if level.engine == request.engine and level.dimension == request.dimension
        ]
        if not candidates:
            return ScopeAnswer(
                "unsupported", None, False, (), tuple(sorted(wanted)), investigations, (),
                f"No level covers {request.engine} {request.dimension}; this is not "
                "something the factory can offer today.",
            )
        best = min(
            candidates,
            key=lambda level: (len(wanted - level.features), len(level.features)),
        )
        excluded = tuple(sorted(wanted - best.features))
        included = tuple(sorted(wanted & best.features))
        status = self.status(best.level_id)
        missing = tuple(sorted({*status.unmet, *status.unchecked}))
        if not excluded and status.supported and not investigations:
            return ScopeAnswer(
                "supported", best.level_id, True, included, (), (), (),
                f"{best.title} covers this, and a reference project passed every "
                f"acceptance criterion with a recorded gameplay review.",
            )
        if investigations and not included:
            return ScopeAnswer(
                "investigation", None, False, (), excluded, investigations, missing,
                "Everything asked for is in an area that has no reference project: "
                + ", ".join(area for area, _ in investigations)
                + ". It can be investigated, not scheduled as a build.",
            )
        parts = [
            f"{best.title} is the closest level, and a scoped prototype is possible."
        ]
        if excluded:
            parts.append("Left out of that prototype: " + ", ".join(excluded) + ".")
        if investigations:
            parts.append(
                "Handled as separate investigations, not part of the build: "
                + ", ".join(area for area, _ in investigations) + "."
            )
        if missing:
            parts.append(
                "This level is not verified yet - no recorded evidence for "
                + ", ".join(missing)
                + " - so the prototype is an attempt, not a guarantee."
            )
        else:
            parts.append(
                "The level itself is verified, but the prototype drops part of the "
                "request, so the result is not guaranteed to be what was asked for."
            )
        return ScopeAnswer(
            "scoped_prototype", best.level_id, False, included, excluded,
            investigations, missing, " ".join(parts),
        )

    @property
    def record(self) -> dict[str, Any]:
        return {
            "levels": [status.level.record for status in self.statuses()],
            "statuses": [status.record for status in self.statuses()],
            "separate_investigations": [
                {"area": area, "reason": reason}
                for area, reason in sorted(INVESTIGATIONS.items())
            ],
            "note": (
                "A level is supported only when a reference project passed every "
                "acceptance criterion and a named person reviewed the gameplay."
            ),
        }


def load_evidence(payload: Any) -> tuple[LevelEvidence, ...]:
    """Read an evidence document. An empty document is the honest default."""
    if isinstance(payload, (str, bytes)):
        payload = json.loads(payload)
    if not isinstance(payload, Mapping):
        raise ValueError("An evidence document is a JSON object")
    entries = payload.get("evidence", [])
    if not isinstance(entries, list):
        raise ValueError("An evidence document holds a list under 'evidence'")
    return tuple(
        LevelEvidence.create(
            level_id=str(entry["level_id"]),
            reference_project=str(entry["reference_project"]),
            version_digest=str(entry["version_digest"]),
            checks=dict(entry["checks"]),
            gameplay_reviewer=str(entry["gameplay_reviewer"]),
            recorded_at=str(entry.get("recorded_at", "")),
            notes=str(entry.get("notes", "")),
        )
        for entry in entries
    )


def default_levels() -> tuple[Level, ...]:
    return (
        Level.create(
            "simple-2d",
            title="Simple 2D game",
            summary="One screen, one goal, keyboard input and an on-screen result.",
            dimension="2d", engine="godot", engine_versions=SUPPORTED_ENGINE_VERSIONS,
            features={"input", "ui"},
            budget_profile="handheld",
            performance=PerformanceTarget(60, "1152x648", 3.0, 5.0),
            acceptance={
                "playable_round": "A player can start, play and finish a round.",
                "win_lose": "Both the winning and the losing end are reachable.",
                "restart": "A finished round can be restarted without relaunching.",
                "headless_build": "The project imports, parses and exports headless.",
                "budget": "Every asset is inside the level's hardware budget.",
            },
        ),
        Level.create(
            "multi-level-2d",
            title="Multi-level 2D game",
            summary="Several levels with progress that survives closing the game.",
            dimension="2d", engine="godot", engine_versions=SUPPORTED_ENGINE_VERSIONS,
            features={"input", "ui", "audio", "save_load", "multi_level"},
            budget_profile="low-end-laptop",
            performance=PerformanceTarget(60, "1920x1080", 5.0, 10.0),
            acceptance={
                "playable_round": "A player can start, play and finish a level.",
                "win_lose": "Both the winning and the losing end are reachable.",
                "restart": "A finished level can be restarted without relaunching.",
                "level_progression": "Finishing a level leads to the next one.",
                "save_load": "Progress survives closing and reopening the game.",
                "audio": "Sound plays and can be turned off.",
                "headless_build": "The project imports, parses and exports headless.",
                "budget": "Every asset is inside the level's hardware budget.",
            },
        ),
        Level.create(
            "small-3d",
            title="Small 3D game",
            summary="A small 3D space with movement, a goal and saved progress.",
            dimension="3d", engine="godot", engine_versions=SUPPORTED_ENGINE_VERSIONS,
            features={"input", "ui", "audio", "save_load", "three_d"},
            budget_profile="baseline-pc",
            performance=PerformanceTarget(60, "1920x1080", 10.0, 20.0),
            acceptance={
                "playable_round": "A player can start, play and finish a run.",
                "win_lose": "Both the winning and the losing end are reachable.",
                "restart": "A finished run can be restarted without relaunching.",
                "save_load": "Progress survives closing and reopening the game.",
                "audio": "Sound plays and can be turned off.",
                "frame_rate": "The declared frame rate holds on the baseline machine.",
                "headless_build": "The project imports, parses and exports headless.",
                "budget": "Every asset is inside the level's hardware budget.",
            },
        ),
    )
