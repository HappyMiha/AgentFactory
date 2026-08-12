"""Signed extension-pack contracts and reversible lifecycle management."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import asdict, dataclass, replace
from typing import Any

from . import __version__
from .storage import SQLiteStorage


SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
PACK_TYPES = {"domain", "capability", "connector", "policy", "evaluation", "ui"}
KNOWN_PERMISSIONS = {
    "read_project", "create_artifact", "run_tests", "network",
    "mutate_external", "credential_access", "ui_extension",
}
PRIVILEGED_PERMISSIONS = {"network", "mutate_external", "credential_access"}


@dataclass(frozen=True)
class PackDependency:
    pack_key: str
    minimum_version: str


@dataclass(frozen=True)
class SignatureMetadata:
    key_id: str
    algorithm: str = "hmac-sha256"
    value: str = ""


@dataclass(frozen=True)
class PackManifest:
    pack_key: str
    version: str
    pack_type: str
    core_min_version: str
    core_max_version: str
    permissions: tuple[str, ...]
    dependencies: tuple[PackDependency, ...]
    migrations: tuple[str, ...]
    evaluations: tuple[str, ...]
    signature: SignatureMetadata


class PackManager:
    def __init__(
        self, storage: SQLiteStorage, *, core_version: str = __version__,
        trust_material: dict[str, bytes] | None = None,
    ):
        self.storage = storage
        self.core_version = core_version
        self._trust_material = dict(trust_material or {})

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _version(value: str) -> tuple[int, int, int]:
        if not SEMVER.fullmatch(value):
            raise ValueError(f"Invalid semantic version: {value}")
        return tuple(int(part) for part in value.split("."))

    @classmethod
    def _unsigned(cls, manifest: PackManifest, payload: dict[str, Any]) -> str:
        value = asdict(manifest)
        value["signature"] = {
            "key_id": manifest.signature.key_id,
            "algorithm": manifest.signature.algorithm,
        }
        return cls._json({"manifest": value, "payload": payload})

    @classmethod
    def sign(cls, manifest: PackManifest, payload: dict[str, Any], secret: bytes) -> PackManifest:
        signature = hmac.new(
            secret, cls._unsigned(manifest, payload).encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return replace(
            manifest, signature=replace(manifest.signature, value=signature)
        )

    def approve_trust_root(
        self, *, key_id: str, secret: bytes, actor: str, actor_role: str,
    ) -> int:
        if actor_role != "human_administrator":
            raise PermissionError("Only a human administrator may approve pack trust roots")
        if not key_id.strip() or not secret or not actor.strip():
            raise ValueError("Trust-root key, material, and administrator are required")
        fingerprint = hashlib.sha256(secret).hexdigest()
        existing = self.storage.db.execute(
            "SELECT id,key_fingerprint FROM pack_trust_roots WHERE key_id=?", (key_id,)
        ).fetchone()
        if existing:
            if str(existing["key_fingerprint"]) != fingerprint:
                raise ValueError("Trust-root key ID already has different material")
            self._trust_material[key_id] = secret
            return int(existing["id"])
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO pack_trust_roots(
                       identity,key_id,algorithm,key_fingerprint,approved_by,approved_role
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    self.storage._identity("pack-trust-root"), key_id, "hmac-sha256",
                    fingerprint, actor, actor_role,
                ),
            )
            root_id = int(cursor.lastrowid)
            self.storage._event("pack.trust_root.approved", "pack_trust_root", root_id, {
                "key_id": key_id, "fingerprint": fingerprint, "actor": actor,
            })
        self._trust_material[key_id] = secret
        return root_id

    def _validate_manifest(self, manifest: PackManifest, payload: dict[str, Any]) -> None:
        if not manifest.pack_key.strip() or manifest.pack_type not in PACK_TYPES:
            raise ValueError("Pack identity and type are invalid")
        current = self._version(self.core_version)
        if not self._version(manifest.core_min_version) <= current <= self._version(
            manifest.core_max_version
        ):
            raise PermissionError("Pack is incompatible with this core version")
        self._version(manifest.version)
        if len(manifest.permissions) != len(set(manifest.permissions)) \
                or not set(manifest.permissions) <= KNOWN_PERMISSIONS:
            raise PermissionError("Pack declares unknown permissions")
        requested = payload.get("requested_permissions", [])
        if not isinstance(requested, list) or not set(requested) <= set(manifest.permissions):
            raise PermissionError("Pack payload requests undeclared permissions")
        for values, label in (
            (manifest.migrations, "migrations"), (manifest.evaluations, "evaluations")
        ):
            if not values or len(values) != len(set(values)) or any(not value.strip() for value in values):
                raise ValueError(f"Pack must declare unique {label}")
        dependency_keys = [dependency.pack_key for dependency in manifest.dependencies]
        if len(dependency_keys) != len(set(dependency_keys)):
            raise ValueError("Pack dependencies must be unique")
        for dependency in manifest.dependencies:
            self._version(dependency.minimum_version)
        if manifest.signature.algorithm != "hmac-sha256" or not manifest.signature.key_id:
            raise ValueError("Pack signature metadata is invalid")

    def _verify_signature(self, manifest: PackManifest, payload: dict[str, Any]):
        root = self.storage.db.execute(
            "SELECT * FROM pack_trust_roots WHERE key_id=?", (manifest.signature.key_id,)
        ).fetchone()
        secret = self._trust_material.get(manifest.signature.key_id)
        if not root or not secret or hashlib.sha256(secret).hexdigest() != root["key_fingerprint"]:
            raise PermissionError("Pack signature trust root is unavailable or unapproved")
        expected = hmac.new(
            secret, self._unsigned(manifest, payload).encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, manifest.signature.value):
            raise PermissionError("Pack signature is invalid")
        return root

    def _verify_dependencies(self, manifest: PackManifest) -> None:
        for dependency in manifest.dependencies:
            row = self.storage.db.execute(
                """SELECT v.version,i.state FROM pack_installations i
                     JOIN pack_versions v ON v.id=i.active_version_id
                    WHERE i.pack_key=?""",
                (dependency.pack_key,),
            ).fetchone()
            if not row or row["state"] != "active" or self._version(str(row["version"])) < self._version(
                dependency.minimum_version
            ):
                raise PermissionError(f"Pack dependency is not active: {dependency.pack_key}")

    def install(
        self, manifest: PackManifest, payload: dict[str, Any], *,
        qualification_results: dict[str, bool], actor: str,
        actor_role: str = "operator", reason: str = "install",
    ) -> int:
        self._validate_manifest(manifest, payload)
        root = self._verify_signature(manifest, payload)
        self._verify_dependencies(manifest)
        if set(qualification_results) != set(manifest.evaluations) or not all(
            value is True for value in qualification_results.values()
        ):
            raise PermissionError("Pack qualification tests failed or are incomplete")
        privileged = bool(set(manifest.permissions) & PRIVILEGED_PERMISSIONS)
        if privileged and actor_role != "human_administrator":
            raise PermissionError("Privileged packs require human administrator approval")
        if not actor.strip() or not reason.strip():
            raise ValueError("Pack lifecycle actor and reason are required")
        current = self.storage.db.execute(
            """SELECT i.*,v.version AS pack_version FROM pack_installations i
                 LEFT JOIN pack_versions v ON v.id=i.active_version_id WHERE i.pack_key=?""",
            (manifest.pack_key,),
        ).fetchone()
        if current and self._version(manifest.version) <= self._version(
            str(current["pack_version"])
        ):
            raise ValueError("Pack upgrade version must be newer than the active version")
        manifest_json = self._json(asdict(manifest))
        payload_json = self._json(payload)
        content_digest = hashlib.sha256(
            self._unsigned(manifest, payload).encode("utf-8")
        ).hexdigest()
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO pack_versions(
                       identity,pack_key,version,pack_type,manifest_json,payload_json,
                       content_digest,signature,trust_root_id,previous_version_id,installed_by
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("pack-version"), manifest.pack_key,
                    manifest.version, manifest.pack_type, manifest_json, payload_json,
                    content_digest, manifest.signature.value, root["id"],
                    int(current["active_version_id"]) if current else None, actor,
                ),
            )
            version_id = int(cursor.lastrowid)
            results_json = self._json(qualification_results)
            qualification_digest = hashlib.sha256(self._json({
                "pack_version_id": version_id,
                "results": qualification_results,
            }).encode()).hexdigest()
            self.storage.db.execute(
                """INSERT INTO pack_qualifications(
                       identity,pack_version_id,results_json,qualification_digest,verdict
                   ) VALUES(?,?,?,?,'passed')""",
                (
                    self.storage._identity("pack-qualification"), version_id,
                    results_json, qualification_digest,
                ),
            )
            if current:
                self.storage.db.execute(
                    """UPDATE pack_installations SET active_version_id=?,state='active',
                           version=version+1,updated_at=CURRENT_TIMESTAMP WHERE pack_key=?""",
                    (version_id, manifest.pack_key),
                )
                event_type = "upgraded"
                previous_id = int(current["active_version_id"])
            else:
                self.storage.db.execute(
                    "INSERT INTO pack_installations(pack_key,active_version_id,state) VALUES(?,?,'active')",
                    (manifest.pack_key, version_id),
                )
                event_type = "installed"
                previous_id = None
            self._event(
                manifest.pack_key, event_type, previous_id, version_id, actor, reason
            )
        return version_id

    def disable(self, pack_key: str, *, actor: str, reason: str) -> None:
        with self.storage.db:
            row = self.storage.db.execute(
                "SELECT * FROM pack_installations WHERE pack_key=?", (pack_key,)
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown installed pack: {pack_key}")
            if row["state"] == "disabled":
                return
            self.storage.db.execute(
                """UPDATE pack_installations SET state='disabled',version=version+1,
                       updated_at=CURRENT_TIMESTAMP WHERE pack_key=? AND state='active'""",
                (pack_key,),
            )
            self._event(pack_key, "disabled", row["active_version_id"], None, actor, reason)

    def rollback(self, pack_key: str, *, actor: str, reason: str) -> int:
        with self.storage.db:
            current = self.storage.db.execute(
                """SELECT i.*,v.previous_version_id FROM pack_installations i
                     JOIN pack_versions v ON v.id=i.active_version_id WHERE i.pack_key=?""",
                (pack_key,),
            ).fetchone()
            if not current or current["previous_version_id"] is None:
                raise ValueError("Pack has no previous working version")
            previous_id = int(current["previous_version_id"])
            self.storage.db.execute(
                """UPDATE pack_installations SET active_version_id=?,state='active',
                       version=version+1,updated_at=CURRENT_TIMESTAMP WHERE pack_key=?""",
                (previous_id, pack_key),
            )
            self._event(
                pack_key, "rolled_back", current["active_version_id"], previous_id,
                actor, reason,
            )
        return previous_id

    def _event(
        self, pack_key: str, event_type: str, from_id: int | None,
        to_id: int | None, actor: str, reason: str,
    ) -> None:
        if not actor.strip() or not reason.strip():
            raise ValueError("Pack lifecycle actor and reason are required")
        cursor = self.storage.db.execute(
            """INSERT INTO pack_lifecycle_events(
                   identity,pack_key,event_type,from_version_id,to_version_id,actor,reason
               ) VALUES(?,?,?,?,?,?,?)""",
            (
                self.storage._identity("pack-lifecycle"), pack_key, event_type,
                from_id, to_id, actor, reason,
            ),
        )
        self.storage._event(f"pack.{event_type}", "pack_lifecycle", int(cursor.lastrowid), {
            "pack_key": pack_key, "from_version_id": from_id,
            "to_version_id": to_id, "actor": actor,
        })
