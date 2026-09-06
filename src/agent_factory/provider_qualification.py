"""Trusted-host cloud capability evidence over Core's immutable qualification rows.

This module neither runs a canary nor authenticates its issuer. Only a trusted
host evaluator may record results; browser/provider response fields are not an
issuer. A receipt is qualification evidence, never permission to execute.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import MappingProxyType

from .adapters import HEALTH_DIMENSIONS


SCHEMA = "core.provider-qualification.v1"
CAPABILITIES = {"coding": "cloud_coding", "review": "independent_review"}
CHECKS = {
    "coding": {"bounded_workspace", "candidate_produced", "candidate_tests_passed"},
    "review": {"bounded_workspace", "known_defect_detected", "clean_control_accepted"},
}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _text(value):
    if not isinstance(value, str) or not 0 < len(value) <= 256 or not value.isprintable() or value != value.strip():
        raise ValueError("Invalid qualification identifier")


def _sha(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Invalid qualification digest")


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Qualification time must be timezone-aware")
    return value.astimezone(timezone.utc)


class QualificationDenied(PermissionError):
    """A bounded reason code; never include raw provider output or credentials."""


@dataclass(frozen=True)
class QualificationScope:
    actor: str
    tenant: str
    connection: str
    connection_generation: str
    provider: str
    requested_model: str
    configuration_digest: str
    purpose: str

    def __post_init__(self):
        for value in asdict(self).values():
            _text(value)
        _sha(self.configuration_digest)
        if self.purpose not in CAPABILITIES:
            raise ValueError("Unsupported qualification purpose")


@dataclass(frozen=True)
class QualificationReceipt:
    qualification_id: int
    worker_id: str
    role: str
    scope: QualificationScope
    effective_model: str
    canonical_model: str
    registry_digest: str
    evidence_digest: str
    expires_at: str


class CanonicalModels:
    """Explicit trusted mapping of observed provider IDs, never requested aliases.

    A host must map resellers/aliases of the same underlying model to the same
    canonical ID. Missing or ambiguous observations cannot be guessed from the
    selected model. No provider mappings are shipped or automatically learned.
    """

    def __init__(self, bindings: dict[tuple[str, str], str]):
        copied = {}
        for key, canonical in bindings.items():
            if not isinstance(key, tuple) or len(key) != 2:
                raise ValueError("Invalid observed model binding")
            for value in (*key, canonical):
                _text(value)
            copied[key] = canonical
        self.bindings = MappingProxyType(copied)
        self.digest = _digest(sorted((provider, observed, canonical) for (provider, observed), canonical in copied.items()))

    def resolve(self, provider, observed):
        try:
            return self.bindings[(provider, observed)]
        except (KeyError, TypeError):
            raise QualificationDenied("effective_identity_unqualified") from None


class ProviderQualificationService:
    def __init__(self, storage, identities: CanonicalModels, *, clock=None):
        self.storage, self.identities = storage, identities
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def record(self, *, worker_id: str, role: str, scope: QualificationScope,
               observed_model: str, suite_version: str, artifact_digest: str,
               observation_digest: str, checks: dict[str, bool], ttl_seconds: int = 3600):
        """Record a trusted evaluator result; synthetic fixtures are not live proof.

        The host verifies actual canary execution, current account authority and
        provider-observed identity before calling. Only bounded references enter
        Core; source, credentials and raw provider errors remain outside evidence.
        Failed checks append a failed qualification, superseding older success.
        """
        for value in (worker_id, role, observed_model, suite_version):
            _text(value)
        for value in (artifact_digest, observation_digest):
            _sha(value)
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 86400:
            raise ValueError("Qualification lifetime must be 1..86400 seconds")
        if set(checks) != CHECKS[scope.purpose] or any(type(v) is not bool for v in checks.values()):
            raise ValueError("Purpose-specific evaluator checks are required")
        canonical = self.identities.resolve(scope.provider, observed_model)
        issued = _utc(self.clock())
        evidence = {
            "schema": SCHEMA, "scope": asdict(scope), "effective_model": observed_model,
            "canonical_model": canonical, "registry_digest": self.identities.digest,
            "suite_version": suite_version, "artifact_digest": artifact_digest,
            "observation_digest": observation_digest, "checks": checks,
            "issued_at": issued.isoformat(), "expires_at": (issued + timedelta(seconds=ttl_seconds)).isoformat(),
        }
        passed = all(checks.values())
        return self.storage.record_worker_qualification(
            worker_id=worker_id, provider_id=scope.provider, role=role,
            capabilities=[CAPABILITIES[scope.purpose]] if passed else [],
            dimensions={key: {"status": ("pass" if passed else "fail") if key == "quality" else "unknown", "evidence": SCHEMA}
                        for key in HEALTH_DIMENSIONS},
            evidence=evidence, status="qualified" if passed else "failed", ttl_seconds=ttl_seconds,
        )

    def resolve(self, *, worker_id: str, role: str, scope: QualificationScope,
                qualification_id: int | None = None) -> QualificationReceipt:
        """Recheck current immutable row and lifecycle with trusted current scope.

        Host connection revocation/config changes must change the current scope
        or append failure/quarantine the worker. This API does not inspect secrets.
        """
        row = self.storage.db.execute("""SELECT q.*,l.state AS lifecycle,
            q.valid_until>CURRENT_TIMESTAMP AS current FROM worker_qualifications q
            LEFT JOIN worker_lifecycle l ON l.worker_id=q.worker_id
            WHERE q.worker_id=? ORDER BY q.id DESC LIMIT 1""", (worker_id,)).fetchone()
        if not row or (qualification_id is not None and row["id"] != qualification_id):
            raise QualificationDenied("qualification_superseded_or_missing")
        if row["status"] != "qualified" or not row["current"] or row["lifecycle"] != "active":
            raise QualificationDenied("qualification_not_current")
        if row["provider_id"] != scope.provider or row["role"] != role:
            raise QualificationDenied("qualification_scope_mismatch")
        try:
            evidence = json.loads(row["evidence_json"])
            if evidence.get("schema") != SCHEMA or _digest(evidence) != row["evidence_digest"]:
                raise QualificationDenied("qualification_evidence_unqualified")
            if evidence["scope"] != asdict(scope) or evidence["registry_digest"] != self.identities.digest:
                raise QualificationDenied("qualification_scope_mismatch")
            if evidence["canonical_model"] != self.identities.resolve(scope.provider, evidence["effective_model"]):
                raise QualificationDenied("effective_identity_unqualified")
            issued = _utc(datetime.fromisoformat(evidence["issued_at"]))
            expires = _utc(datetime.fromisoformat(evidence["expires_at"]))
            if not issued <= _utc(self.clock()) < expires or not timedelta(0) < expires - issued <= timedelta(days=1):
                raise QualificationDenied("qualification_expired")
            if (set(evidence["checks"]) != CHECKS[scope.purpose]
                    or any(v is not True for v in evidence["checks"].values())
                    or CAPABILITIES[scope.purpose] not in json.loads(row["capabilities_json"])):
                raise QualificationDenied("purpose_capability_unqualified")
            for name in ("artifact_digest", "observation_digest"):
                _sha(evidence[name])
            _text(evidence["suite_version"])
        except QualificationDenied:
            raise
        except (KeyError, TypeError, ValueError, AttributeError):
            raise QualificationDenied("qualification_evidence_unqualified") from None
        return QualificationReceipt(int(row["id"]), worker_id, role, scope,
            evidence["effective_model"], evidence["canonical_model"], self.identities.digest,
            row["evidence_digest"], evidence["expires_at"])

    def revalidate(self, receipt: QualificationReceipt) -> QualificationReceipt:
        current = self.resolve(worker_id=receipt.worker_id, role=receipt.role,
            scope=receipt.scope, qualification_id=receipt.qualification_id)
        if current != receipt:
            raise QualificationDenied("qualification_receipt_mismatch")
        return current
