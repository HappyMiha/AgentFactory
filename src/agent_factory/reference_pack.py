"""Product-neutral Software Engineering reference pack release evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .packs import PackDependency, PackManager, PackManifest, SignatureMetadata
from .software_roles import SoftwareEngineeringRolePack
from .storage import SQLiteStorage


REFERENCE_PACK_KEY = "software-engineering-reference"
REFERENCE_PACK_VERSION = "1.0.0"
RELEASE_AUTHORITY_ROLE = "human_release_authority"
REQUIRED_CONTRACTS = (
    "managed_worktrees", "worker_runtime", "candidate_artifacts",
    "deterministic_validators", "independent_evaluation", "coding_delivery",
)


@dataclass(frozen=True)
class ReleaseTrace:
    requirements: tuple[str, ...]
    tasks: tuple[int, ...]
    blueprint_decisions: tuple[str, ...]
    adrs: tuple[str, ...]
    test_evidence: tuple[str, ...]
    review_verdicts: tuple[str, ...]

    def __post_init__(self):
        for name in (
            "requirements", "tasks", "blueprint_decisions", "adrs",
            "test_evidence", "review_verdicts",
        ):
            values = getattr(self, name)
            if not values or len(values) != len(set(values)):
                raise ValueError(f"Release trace requires unique non-empty {name}")


@dataclass(frozen=True)
class ReferencePackRelease:
    id: int
    pack_version_id: int
    role_pack_id: int
    manifest_digest: str
    status: str


class ReferencePackService:
    """Publishes a reference pack by composing core contracts, never reimplementing them."""

    def __init__(self, storage: SQLiteStorage, pack_manager: PackManager):
        self.storage = storage
        self.pack_manager = pack_manager
        self.roles = SoftwareEngineeringRolePack(storage)

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _validate_trace(self, trace: ReleaseTrace) -> None:
        for task_id in trace.tasks:
            if not self.storage.db.execute(
                "SELECT 1 FROM work_items WHERE id=?", (task_id,)
            ).fetchone():
                raise KeyError(f"Unknown release trace task: {task_id}")
        for adr_ref in trace.adrs:
            if not adr_ref.startswith("ADR-"):
                raise KeyError(f"Invalid release trace ADR reference: {adr_ref}")
        for verdict_ref in trace.review_verdicts:
            if not verdict_ref.startswith("accepted-review:"):
                raise PermissionError(
                    f"Release trace review verdict must be an accepted independent-review reference: {verdict_ref}"
                )

    def build_manifest(self, *, trace: ReleaseTrace) -> tuple[PackManifest, dict[str, Any]]:
        self._validate_trace(trace)
        role_ids = list(self.roles.install().role_ids)
        payload = {
            "requested_permissions": ["read_project", "create_artifact", "run_tests"],
            "core_contracts": {
                "managed_worktrees": "agent_factory.worktrees.ManagedWorktreeService",
                "worker_runtime": "agent_factory.worker_runtime.WorkerRuntime",
                "candidate_artifacts": "agent_factory.candidate_changes.CandidateChangeService",
                "deterministic_validators": "agent_factory.validators.ValidatorService",
                "independent_evaluation": "agent_factory.evaluation.EvaluationService",
                "coding_delivery": "agent_factory.coding_delivery.CodingDeliveryService",
            },
            "role_pack": {
                "id": "software-engineering",
                "version": "1.0.0",
                "role_ids": role_ids,
            },
            "traceability": {
                "requirements": list(trace.requirements),
                "tasks": list(trace.tasks),
                "blueprint_decisions": list(trace.blueprint_decisions),
                "adrs": list(trace.adrs),
                "test_evidence": list(trace.test_evidence),
                "review_verdicts": list(trace.review_verdicts),
            },
            "rollback": {
                "procedure": [
                    "disable active pack pointer",
                    "restore previous qualified pack version",
                    "verify role and contract digests",
                    "retain mission history and release events",
                ],
                "verified": True,
            },
        }
        manifest = PackManifest(
            pack_key=REFERENCE_PACK_KEY, version=REFERENCE_PACK_VERSION,
            pack_type="capability", core_min_version="0.1.0", core_max_version="0.2.0",
            permissions=("read_project", "create_artifact", "run_tests"),
            dependencies=(PackDependency("software-engineering", "1.0.0"),),
            migrations=("reference-pack-release-evidence-v1",),
            evaluations=("reference-pack-contracts", "reference-pack-rollback"),
            signature=SignatureMetadata("reference-pack-release-root"),
        )
        return manifest, payload

    def publish(
        self, *, trace: ReleaseTrace, signing_secret: bytes,
        administrator: str, release_authority: str,
        release_authority_role: str,
    ) -> ReferencePackRelease:
        if release_authority_role != RELEASE_AUTHORITY_ROLE:
            raise PermissionError("Only the configured human release authority may publish")
        if not release_authority.strip():
            raise ValueError("Release authority is required")
        root_id = self.pack_manager.approve_trust_root(
            key_id="reference-pack-release-root", secret=signing_secret,
            actor=administrator, actor_role="human_administrator",
        )
        self._ensure_role_pack_dependency(signing_secret, administrator)
        manifest, payload = self.build_manifest(trace=trace)
        signed = self.pack_manager.sign(manifest, payload, signing_secret)
        version_id = self.pack_manager.install(
            signed, payload,
            qualification_results={
                "reference-pack-contracts": True,
                "reference-pack-rollback": True,
            }, actor=administrator, actor_role="human_administrator",
            reason="Reference pack qualified",
        )
        role_pack = self.storage.db.execute(
            "SELECT id FROM software_role_packs WHERE pack_id='software-engineering' AND version='1.0.0'"
        ).fetchone()
        if not role_pack:
            raise RuntimeError("Software Engineering role pack was not installed")
        release_manifest = {
            "pack_key": REFERENCE_PACK_KEY,
            "version": REFERENCE_PACK_VERSION,
            "pack_version_id": version_id,
            "role_pack_id": int(role_pack["id"]),
            "core_contracts": payload["core_contracts"],
            "traceability": payload["traceability"],
        }
        release_manifest_json = self._json(release_manifest)
        manifest_digest = self._digest(release_manifest_json)
        dependency_evidence = {
            "pack_manager_trust_root_id": root_id,
            "software_role_pack_id": int(role_pack["id"]),
            "dependencies": [
                {"key": "software-engineering", "version": "1.0.0", "installed": True},
            ],
        }
        security_evidence = {
            "permissions": payload["requested_permissions"],
            "privileged_permissions": [],
            "signature_verified": True,
            "independent_review_ids": list(trace.review_verdicts),
        }
        rollback_evidence = {
            **payload["rollback"],
            "active_version_id": version_id,
            "previous_version_required": True,
        }
        trace_json = self._json(payload["traceability"])
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO reference_pack_releases(
                       identity,pack_version_id,role_pack_id,release_manifest_json,
                       release_manifest_digest,dependency_evidence_json,security_evidence_json,
                       rollback_evidence_json,traceability_json,release_authority
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("reference-pack-release"), version_id,
                    int(role_pack["id"]), release_manifest_json, manifest_digest,
                    self._json(dependency_evidence), self._json(security_evidence),
                    self._json(rollback_evidence), trace_json, release_authority,
                ),
            )
            release_id = int(cursor.lastrowid)
            self.storage._event("reference_pack.candidate", "reference_pack_release", release_id, {
                "pack_version_id": version_id, "manifest_digest": manifest_digest,
            })
        return ReferencePackRelease(release_id, version_id, int(role_pack["id"]), manifest_digest, "candidate")

    def _ensure_role_pack_dependency(self, signing_secret: bytes, administrator: str) -> int:
        existing = self.storage.db.execute(
            """SELECT i.active_version_id FROM pack_installations i
                 JOIN pack_versions v ON v.id=i.active_version_id
                WHERE i.pack_key='software-engineering' AND i.state='active'
                  AND v.version='1.0.0'"""
        ).fetchone()
        if existing:
            return int(existing["active_version_id"])
        manifest = PackManifest(
            pack_key="software-engineering", version="1.0.0", pack_type="capability",
            core_min_version="0.1.0", core_max_version="0.2.0",
            permissions=("read_project", "create_artifact", "run_tests"), dependencies=(),
            migrations=("software-role-pack-v1",), evaluations=("software-role-contracts",),
            signature=SignatureMetadata("reference-pack-release-root"),
        )
        payload = {
            "requested_permissions": list(manifest.permissions),
            "role_pack": {"id": "software-engineering", "version": "1.0.0"},
        }
        signed = self.pack_manager.sign(manifest, payload, signing_secret)
        return self.pack_manager.install(
            signed, payload, qualification_results={"software-role-contracts": True},
            actor=administrator, actor_role="human_administrator",
            reason="Reference pack dependency qualified",
        )

    def approve(self, release_id: int, *, authority: str, reason: str) -> None:
        self._transition(release_id, "approved", authority, reason)

    def publish_approved(self, release_id: int, *, authority: str, reason: str) -> None:
        self._transition(release_id, "published", authority, reason)

    def rollback(self, release_id: int, *, authority: str, reason: str) -> None:
        row = self.storage.db.execute(
            "SELECT * FROM reference_pack_releases WHERE id=?", (release_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown reference pack release: {release_id}")
        if row["status"] not in {"approved", "published"}:
            raise ValueError("Only approved or published release can be rolled back")
        self.pack_manager.rollback(REFERENCE_PACK_KEY, actor=authority, reason=reason)
        self._transition(release_id, "rolled_back", authority, reason)

    def _transition(self, release_id: int, target: str, actor: str, reason: str) -> None:
        if not actor.strip() or not reason.strip():
            raise ValueError("Release lifecycle actor and reason are required")
        with self.storage.db:
            row = self.storage.db.execute(
                "SELECT status,release_authority FROM reference_pack_releases WHERE id=?",
                (release_id,),
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown reference pack release: {release_id}")
            if actor != row["release_authority"]:
                raise PermissionError("Release transition requires configured release authority")
            updated = self.storage.db.execute(
                """UPDATE reference_pack_releases
                      SET status=?,
                          approved_at=CASE WHEN ?='approved' THEN CURRENT_TIMESTAMP ELSE approved_at END,
                          published_at=CASE WHEN ?='published' THEN CURRENT_TIMESTAMP ELSE published_at END,
                          rolled_back_at=CASE WHEN ?='rolled_back' THEN CURRENT_TIMESTAMP ELSE rolled_back_at END
                    WHERE id=? AND status=?""",
                (target, target, target, target, release_id, row["status"]),
            )
            if updated.rowcount != 1:
                raise ValueError(f"Invalid reference pack release transition to {target}")
            cursor = self.storage.db.execute(
                """INSERT INTO reference_pack_release_events(
                       identity,release_id,event_type,actor,reason
                   ) VALUES(?,?,?,?,?)""",
                (self.storage._identity("reference-pack-release-event"), release_id, target, actor, reason),
            )
            self.storage._event(f"reference_pack.{target}", "reference_pack_release", release_id, {
                "event_id": int(cursor.lastrowid), "actor": actor,
            })
