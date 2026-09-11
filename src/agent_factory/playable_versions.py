"""Engine-neutral ledger of verified playable versions with atomic promotion.

Unfinished work must never take away the version a player can already play.
A build is promoted only when every recorded check succeeded; a later failure
leaves the pointer where it is. Promotion is idempotent per command, the
version history is immutable, and a restore adds a new version that points back
at the one it came from instead of rewriting history.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from .storage import SQLiteStorage


PLAYABLE_VERSION_MIGRATION = """
CREATE TABLE playable_versions(
    id INTEGER PRIMARY KEY,
    identity TEXT NOT NULL UNIQUE,
    project_key TEXT NOT NULL,
    version_digest TEXT NOT NULL CHECK(length(version_digest)=64),
    engine TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    source_commit TEXT NOT NULL,
    project_digest TEXT NOT NULL,
    template_id TEXT NOT NULL,
    template_version TEXT NOT NULL,
    preset TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    artifact_checksum TEXT NOT NULL CHECK(length(artifact_checksum)=64),
    artifact_bytes INTEGER NOT NULL CHECK(artifact_bytes>0),
    verification_json TEXT NOT NULL CHECK(json_valid(verification_json)),
    evidence_gap_json TEXT NOT NULL CHECK(json_valid(evidence_gap_json)),
    restored_from_id INTEGER REFERENCES playable_versions(id),
    restore_branch TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(project_key,version_digest)
);
CREATE INDEX playable_versions_project ON playable_versions(project_key,id);
CREATE INDEX playable_versions_identity_scan
    ON playable_versions(project_key,source_commit,project_digest,preset);
CREATE TRIGGER playable_versions_no_update BEFORE UPDATE ON playable_versions
BEGIN SELECT RAISE(ABORT,'playable versions are immutable'); END;
CREATE TRIGGER playable_versions_no_delete BEFORE DELETE ON playable_versions
BEGIN SELECT RAISE(ABORT,'playable versions are durable'); END;

CREATE TABLE playable_pointers(
    project_key TEXT PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES playable_versions(id),
    sequence INTEGER NOT NULL CHECK(sequence>0),
    updated_at TEXT NOT NULL
);

CREATE TABLE playable_promotions(
    id INTEGER PRIMARY KEY,
    identity TEXT NOT NULL UNIQUE,
    project_key TEXT NOT NULL,
    command_id TEXT NOT NULL,
    request_digest TEXT NOT NULL CHECK(length(request_digest)=64),
    version_id INTEGER REFERENCES playable_versions(id),
    previous_version_id INTEGER REFERENCES playable_versions(id),
    outcome TEXT NOT NULL CHECK(outcome IN ('promoted','rejected','unchanged','restored')),
    pointer_moved INTEGER NOT NULL CHECK(pointer_moved IN (0,1)),
    reproducible INTEGER NOT NULL CHECK(reproducible IN (0,1)),
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(project_key,command_id)
);
CREATE INDEX playable_promotions_project ON playable_promotions(project_key,id);
CREATE TRIGGER playable_promotions_no_update BEFORE UPDATE ON playable_promotions
BEGIN SELECT RAISE(ABORT,'promotion history is immutable'); END;
CREATE TRIGGER playable_promotions_no_delete BEFORE DELETE ON playable_promotions
BEGIN SELECT RAISE(ABORT,'promotion history is durable'); END;
"""

OUTCOMES = ("promoted", "rejected", "unchanged", "restored")
PROJECT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_REASON = 500


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: Any, label: str, *, limit: int = 200) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or len(cleaned) > limit or "\x00" in cleaned:
        raise ValueError(f"{label} must be non-empty text of at most {limit} characters")
    return cleaned


def _project_key(value: str) -> str:
    cleaned = str(value or "").strip()
    if not PROJECT_KEY.fullmatch(cleaned):
        raise ValueError(f"Invalid project key: {value!r}")
    return cleaned


@dataclass(frozen=True)
class CandidateBuild:
    """One engine build offered for promotion, with the checks that judged it."""

    engine: str
    engine_version: str
    source_commit: str
    project_digest: str
    template_id: str
    template_version: str
    preset: str
    artifact_path: str
    artifact_checksum: str
    artifact_bytes: int
    succeeded: bool
    verification: tuple[Mapping[str, Any], ...]
    evidence_gap: tuple[str, ...]
    failure_reason: str = ""

    @classmethod
    def from_artifact(cls, artifact: Any, *, engine: str) -> "CandidateBuild":
        """Adapt an engine adapter's build record without importing that engine."""
        manifest = artifact.manifest if hasattr(artifact, "manifest") else dict(artifact)
        failure = getattr(artifact, "failure", None)
        return cls(
            engine=_text(engine, "engine"),
            engine_version=_text(manifest.get("engine_version"), "engine version"),
            source_commit=_text(manifest.get("source_commit"), "source commit"),
            project_digest=_text(manifest.get("project_digest"), "project digest"),
            template_id=_text(manifest.get("template_id"), "template id"),
            template_version=_text(manifest.get("template_version"), "template version"),
            preset=_text(manifest.get("preset"), "preset"),
            artifact_path=str(manifest.get("artifact_path") or ""),
            artifact_checksum=str(manifest.get("artifact_checksum") or ""),
            artifact_bytes=int(manifest.get("artifact_bytes") or 0),
            succeeded=bool(manifest.get("succeeded")),
            verification=tuple(dict(run) for run in manifest.get("runs", ())),
            evidence_gap=tuple(str(value) for value in manifest.get("evidence_gap", ())),
            failure_reason=str(getattr(failure, "detail", "") or ""),
        )

    def rejection(self) -> str:
        """Why this build may not become the playable version, or an empty string."""
        if not self.succeeded:
            return self.failure_reason or "the build did not succeed"
        if not SHA256.fullmatch(self.artifact_checksum or ""):
            return "the build has no artifact checksum"
        if self.artifact_bytes <= 0 or not self.artifact_path:
            return "the build has no artifact file"
        if not self.verification:
            return "the build recorded no verification runs"
        failed = [
            str(run.get("operation", "unknown"))
            for run in self.verification
            if str(run.get("status")) != "succeeded"
        ]
        if failed:
            return "verification failed: " + ", ".join(sorted(set(failed)))
        return ""

    @property
    def identity(self) -> dict[str, str]:
        """The source identity a reproducible build is expected to preserve."""
        return {
            "engine": self.engine,
            "source_commit": self.source_commit,
            "project_digest": self.project_digest,
            "preset": self.preset,
        }

    @property
    def version_digest(self) -> str:
        return _digest({
            **self.identity,
            "engine_version": self.engine_version,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "artifact_checksum": self.artifact_checksum,
        })


@dataclass(frozen=True)
class PlayableVersion:
    id: int
    project_key: str
    version_digest: str
    engine: str
    engine_version: str
    source_commit: str
    project_digest: str
    template_id: str
    template_version: str
    preset: str
    artifact_path: str
    artifact_checksum: str
    artifact_bytes: int
    verification: tuple[Mapping[str, Any], ...]
    evidence_gap: tuple[str, ...]
    restored_from_id: int | None
    restore_branch: str
    created_at: str

    @property
    def checkpoint(self) -> dict[str, Any]:
        return {
            "project_key": self.project_key,
            "version_digest": self.version_digest,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "source_commit": self.source_commit,
            "project_digest": self.project_digest,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "preset": self.preset,
            "artifact_checksum": self.artifact_checksum,
            "artifact_bytes": self.artifact_bytes,
            "verification": [dict(run) for run in self.verification],
            "evidence_gap": list(self.evidence_gap),
            "restored_from_id": self.restored_from_id,
            "restore_branch": self.restore_branch,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class PromotionResult:
    outcome: str
    project_key: str
    command_id: str
    version: PlayableVersion | None
    previous: PlayableVersion | None
    pointer_moved: bool
    reproducible: bool
    reason: str
    replayed: bool = False

    @property
    def accepted(self) -> bool:
        return self.outcome in {"promoted", "restored"}


@dataclass(frozen=True)
class RestorePreview:
    project_key: str
    target: PlayableVersion
    current: PlayableVersion | None
    branch: str
    changes_pointer: bool
    preserved_versions: int

    @property
    def summary(self) -> dict[str, Any]:
        return {
            "project_key": self.project_key,
            "restore_to": self.target.version_digest,
            "current": self.current.version_digest if self.current else None,
            "branch": self.branch,
            "changes_pointer": self.changes_pointer,
            "preserved_versions": self.preserved_versions,
            "history_rewritten": False,
        }


class PlayableVersions:
    """Append-only playable history with a pointer that only verified builds move."""

    def __init__(self, storage: "SQLiteStorage"):
        self.storage = storage

    # ----------------------------------------------------------------- reads

    def current(self, project_key: str) -> PlayableVersion | None:
        key = _project_key(project_key)
        row = self.storage.db.execute(
            """SELECT v.* FROM playable_pointers p
                 JOIN playable_versions v ON v.id=p.version_id
                WHERE p.project_key=?""",
            (key,),
        ).fetchone()
        return _version(row) if row else None

    def sequence(self, project_key: str) -> int:
        row = self.storage.db.execute(
            "SELECT sequence FROM playable_pointers WHERE project_key=?",
            (_project_key(project_key),),
        ).fetchone()
        return int(row["sequence"]) if row else 0

    def history(self, project_key: str, *, limit: int = 50) -> tuple[PlayableVersion, ...]:
        if limit <= 0 or limit > 500:
            raise ValueError("History limit must be between 1 and 500")
        rows = self.storage.db.execute(
            "SELECT * FROM playable_versions WHERE project_key=? ORDER BY id DESC LIMIT ?",
            (_project_key(project_key), int(limit)),
        ).fetchall()
        return tuple(_version(row) for row in rows)

    def version(self, project_key: str, version_digest: str) -> PlayableVersion:
        row = self.storage.db.execute(
            "SELECT * FROM playable_versions WHERE project_key=? AND version_digest=?",
            (_project_key(project_key), str(version_digest)),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown playable version: {version_digest}")
        return _version(row)

    def promotions(self, project_key: str, *, limit: int = 50) -> tuple[dict[str, Any], ...]:
        rows = self.storage.db.execute(
            "SELECT * FROM playable_promotions WHERE project_key=? ORDER BY id DESC LIMIT ?",
            (_project_key(project_key), int(limit)),
        ).fetchall()
        return tuple({
            "command_id": str(row["command_id"]),
            "outcome": str(row["outcome"]),
            "pointer_moved": bool(row["pointer_moved"]),
            "reproducible": bool(row["reproducible"]),
            "reason": str(row["reason"]),
            "actor": str(row["actor"]),
            "created_at": str(row["created_at"]),
        } for row in rows)

    # ---------------------------------------------------------------- writes

    def promote(
        self,
        project_key: str,
        build: CandidateBuild,
        *,
        command_id: str,
        actor: str,
    ) -> PromotionResult:
        """Offer a build. Only a fully verified build may move the pointer."""
        key = _project_key(project_key)
        command = _text(command_id, "command id", limit=128)
        who = _text(actor, "actor")
        request_digest = _digest({
            "project_key": key, "command_id": command,
            "version_digest": build.version_digest,
        })
        replay = self._replay(key, command, request_digest)
        if replay is not None:
            return replay
        rejection = build.rejection()
        previous = self.current(key)
        if rejection:
            self._record(
                key, command, request_digest, None, previous, "rejected",
                pointer_moved=False, reproducible=True, reason=rejection, actor=who,
            )
            return PromotionResult(
                "rejected", key, command, None, previous, False, True, rejection,
            )
        reproducible = self._reproducible(key, build)
        existing = self.storage.db.execute(
            "SELECT * FROM playable_versions WHERE project_key=? AND version_digest=?",
            (key, build.version_digest),
        ).fetchone()
        if existing is not None:
            version = _version(existing)
            unchanged = previous is not None and previous.id == version.id
            reason = (
                "this build is already the playable version" if unchanged
                else "this build was already recorded; the pointer was restored to it"
            )
            with self.storage.db:
                if not unchanged:
                    self._move(key, version.id)
                self._record(
                    key, command, request_digest, version.id,
                    previous.id if previous else None,
                    "unchanged" if unchanged else "promoted",
                    pointer_moved=not unchanged, reproducible=reproducible,
                    reason=reason, actor=who, atomic=False,
                )
            return PromotionResult(
                "unchanged" if unchanged else "promoted", key, command, version,
                previous, not unchanged, reproducible, reason,
            )
        with self.storage.db:
            version_id = self._insert(key, build)
            self._move(key, version_id)
            reason = (
                "verified build promoted" if reproducible else
                "verified build promoted; the same source identity produced a "
                "different artifact checksum"
            )
            self._record(
                key, command, request_digest, version_id,
                previous.id if previous else None, "promoted",
                pointer_moved=True, reproducible=reproducible, reason=reason,
                actor=who, atomic=False,
            )
        return PromotionResult(
            "promoted", key, command, self.version(key, build.version_digest),
            previous, True, reproducible, reason,
        )

    def restore_preview(
        self, project_key: str, version_digest: str, *, branch: str,
    ) -> RestorePreview:
        key = _project_key(project_key)
        target = self.version(key, version_digest)
        current = self.current(key)
        total = self.storage.db.execute(
            "SELECT COUNT(*) AS total FROM playable_versions WHERE project_key=?", (key,),
        ).fetchone()
        return RestorePreview(
            key, target, current, _text(branch, "branch"),
            current is None or current.id != target.id, int(total["total"]),
        )

    def restore(
        self,
        project_key: str,
        version_digest: str,
        *,
        branch: str,
        command_id: str,
        actor: str,
        preview: RestorePreview | None = None,
    ) -> PromotionResult:
        """Bring back an earlier version as a new version, preserving the original."""
        key = _project_key(project_key)
        command = _text(command_id, "command id", limit=128)
        who = _text(actor, "actor")
        target_branch = _text(branch, "branch")
        request_digest = _digest({
            "project_key": key, "command_id": command,
            "restore_to": str(version_digest), "branch": target_branch,
        })
        replay = self._replay(key, command, request_digest)
        if replay is not None:
            return replay
        target = self.version(key, version_digest)
        if preview is not None and (
            preview.target.id != target.id or preview.branch != target_branch
        ):
            raise ValueError("The reviewed preview does not match this restore")
        previous = self.current(key)
        source = target.restored_from_id or target.id
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO playable_versions(
                       identity,project_key,version_digest,engine,engine_version,
                       source_commit,project_digest,template_id,template_version,
                       preset,artifact_path,artifact_checksum,artifact_bytes,
                       verification_json,evidence_gap_json,restored_from_id,
                       restore_branch,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("playable-version"), key,
                    _digest({
                        "restore_of": target.version_digest,
                        "branch": target_branch, "sequence": self.sequence(key) + 1,
                    }),
                    target.engine, target.engine_version, target.source_commit,
                    target.project_digest, target.template_id, target.template_version,
                    target.preset, target.artifact_path, target.artifact_checksum,
                    target.artifact_bytes, _canonical([dict(r) for r in target.verification]),
                    _canonical(list(target.evidence_gap)), source, target_branch, _stamp(),
                ),
            )
            version_id = int(cursor.lastrowid)
            self._move(key, version_id)
            reason = f"restored {target.version_digest[:12]} onto branch {target_branch}"
            self._record(
                key, command, request_digest, version_id,
                previous.id if previous else None, "restored",
                pointer_moved=True, reproducible=True, reason=reason,
                actor=who, atomic=False,
            )
        restored = _version(self.storage.db.execute(
            "SELECT * FROM playable_versions WHERE id=?", (version_id,),
        ).fetchone())
        return PromotionResult(
            "restored", key, command, restored, previous, True, True, reason,
        )

    def verify_artifact(self, version: PlayableVersion, *, read_bytes: Any = None) -> tuple[bool, str]:
        """Re-check the stored artifact before it is offered for play."""
        from pathlib import Path

        reader = read_bytes or (lambda path: Path(path).read_bytes())
        try:
            payload = reader(version.artifact_path)
        except OSError:
            return False, "the artifact file is missing or unreadable"
        if len(payload) != version.artifact_bytes:
            return False, "the artifact size no longer matches the recorded build"
        if hashlib.sha256(payload).hexdigest() != version.artifact_checksum:
            return False, "the artifact checksum no longer matches the recorded build"
        return True, "artifact matches the recorded build"

    # --------------------------------------------------------------- helpers

    def _replay(
        self, key: str, command: str, request_digest: str,
    ) -> PromotionResult | None:
        row = self.storage.db.execute(
            "SELECT * FROM playable_promotions WHERE project_key=? AND command_id=?",
            (key, command),
        ).fetchone()
        if not row:
            return None
        if str(row["request_digest"]) != request_digest:
            raise PermissionError(
                "This promotion command id was already used for a different build"
            )
        version = self._by_id(row["version_id"])
        previous = self._by_id(row["previous_version_id"])
        return PromotionResult(
            str(row["outcome"]), key, command, version, previous,
            bool(row["pointer_moved"]), bool(row["reproducible"]),
            str(row["reason"]), replayed=True,
        )

    def _by_id(self, version_id: Any) -> PlayableVersion | None:
        if version_id is None:
            return None
        row = self.storage.db.execute(
            "SELECT * FROM playable_versions WHERE id=?", (int(version_id),),
        ).fetchone()
        return _version(row) if row else None

    def _reproducible(self, key: str, build: CandidateBuild) -> bool:
        rows = self.storage.db.execute(
            """SELECT artifact_checksum FROM playable_versions
                WHERE project_key=? AND engine=? AND source_commit=?
                  AND project_digest=? AND preset=? AND restored_from_id IS NULL""",
            (key, build.engine, build.source_commit, build.project_digest, build.preset),
        ).fetchall()
        return all(
            str(row["artifact_checksum"]) == build.artifact_checksum for row in rows
        )

    def _insert(self, key: str, build: CandidateBuild) -> int:
        cursor = self.storage.db.execute(
            """INSERT INTO playable_versions(
                   identity,project_key,version_digest,engine,engine_version,
                   source_commit,project_digest,template_id,template_version,preset,
                   artifact_path,artifact_checksum,artifact_bytes,verification_json,
                   evidence_gap_json,restored_from_id,restore_branch,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,'',?)""",
            (
                self.storage._identity("playable-version"), key, build.version_digest,
                build.engine, build.engine_version, build.source_commit,
                build.project_digest, build.template_id, build.template_version,
                build.preset, build.artifact_path, build.artifact_checksum,
                int(build.artifact_bytes),
                _canonical([dict(run) for run in build.verification]),
                _canonical(list(build.evidence_gap)), _stamp(),
            ),
        )
        return int(cursor.lastrowid)

    def _move(self, key: str, version_id: int) -> None:
        updated = self.storage.db.execute(
            """UPDATE playable_pointers SET version_id=?,sequence=sequence+1,
                   updated_at=? WHERE project_key=?""",
            (version_id, _stamp(), key),
        ).rowcount
        if not updated:
            self.storage.db.execute(
                """INSERT INTO playable_pointers(project_key,version_id,sequence,updated_at)
                   VALUES(?,?,1,?)""",
                (key, version_id, _stamp()),
            )

    def _record(
        self,
        key: str,
        command: str,
        request_digest: str,
        version_id: int | None,
        previous: PlayableVersion | int | None,
        outcome: str,
        *,
        pointer_moved: bool,
        reproducible: bool,
        reason: str,
        actor: str,
        atomic: bool = True,
    ) -> None:
        if outcome not in OUTCOMES:
            raise ValueError(f"Unknown promotion outcome: {outcome}")
        previous_id = previous.id if isinstance(previous, PlayableVersion) else previous
        payload = (
            self.storage._identity("playable-promotion"), key, command, request_digest,
            version_id, previous_id, outcome, int(bool(pointer_moved)),
            int(bool(reproducible)), reason[:MAX_REASON], actor, _stamp(),
        )
        statement = """INSERT INTO playable_promotions(
                identity,project_key,command_id,request_digest,version_id,
                previous_version_id,outcome,pointer_moved,reproducible,reason,
                actor,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"""
        if atomic:
            with self.storage.db:
                cursor = self.storage.db.execute(statement, payload)
                self._event(key, command, outcome, version_id, cursor)
            return
        cursor = self.storage.db.execute(statement, payload)
        self._event(key, command, outcome, version_id, cursor)

    def _event(
        self, key: str, command: str, outcome: str, version_id: int | None, cursor: Any,
    ) -> None:
        self.storage._event(
            f"playable.{outcome}", "playable_promotion", int(cursor.lastrowid),
            {"project_key": key, "command_id": command, "version_id": version_id},
        )


def _version(row: Any) -> PlayableVersion:
    return PlayableVersion(
        int(row["id"]), str(row["project_key"]), str(row["version_digest"]),
        str(row["engine"]), str(row["engine_version"]), str(row["source_commit"]),
        str(row["project_digest"]), str(row["template_id"]),
        str(row["template_version"]), str(row["preset"]), str(row["artifact_path"]),
        str(row["artifact_checksum"]), int(row["artifact_bytes"]),
        tuple(json.loads(str(row["verification_json"]))),
        tuple(json.loads(str(row["evidence_gap_json"]))),
        int(row["restored_from_id"]) if row["restored_from_id"] is not None else None,
        str(row["restore_branch"] or ""), str(row["created_at"]),
    )
