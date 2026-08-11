from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .models import Agent, ExecutionApproval, ProviderResult, WorkItem
from .providers import Provider
from .storage import SQLiteStorage


HEALTH_DIMENSIONS = (
    "availability",
    "reliability",
    "quality",
    "safety",
    "performance",
    "cost",
    "freshness",
    "drift",
)


@dataclass(frozen=True)
class AdapterHealth:
    provider_id: str
    dimensions: dict[str, dict[str, Any]]
    raw: dict[str, Any]

    @property
    def available(self) -> bool:
        return self.dimensions["availability"]["status"] == "ready"


class NormalizedAdapter:
    """Provider-neutral AF-005 health/execute contract below Worker Runtime."""

    operations = frozenset({"health", "execute"})

    def __init__(self, provider: Provider):
        self.provider = provider
        self.provider_id = provider.name

    def health(self) -> AdapterHealth:
        raw = self.provider.health()
        healthy = bool(raw.get("healthy"))
        now = datetime.now(timezone.utc).isoformat()
        dimensions = {
            "availability": {
                "status": "ready" if healthy else "missing",
                "evidence": raw.get("path") or raw.get("error"),
            },
            "reliability": {
                "status": "pass" if healthy else "unknown",
                "evidence": raw.get("error") or "health probe completed",
            },
            "quality": {"status": "unknown", "evidence": "requires evaluation evidence"},
            "safety": {
                "status": "pass" if raw.get("execution_enabled", True) else "restricted",
                "evidence": "adapter execution policy",
            },
            "performance": {"status": "unknown", "evidence": "requires benchmark evidence"},
            "cost": {"status": "unknown", "evidence": "provider usage not yet observed"},
            "freshness": {"status": "current", "evidence": now},
            "drift": {"status": "unknown", "evidence": raw.get("version")},
        }
        return AdapterHealth(self.provider_id, dimensions, raw)

    def execute(
        self,
        agent: Agent,
        item: WorkItem,
        context: dict[str, str],
        approval: ExecutionApproval | None = None,
    ) -> ProviderResult:
        return self.provider.execute(agent, item, context, approval)

    def contract_evidence(self) -> dict[str, Any]:
        health = self.health()
        return {
            "provider_id": self.provider_id,
            "operations": sorted(self.operations),
            "health_dimensions": health.dimensions,
            "raw_health": health.raw,
            "contract_version": 1,
        }


class WorkerQualificationRegistry:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    def qualify(
        self,
        *,
        worker_id: str,
        provider_id: str,
        role: str,
        capabilities: set[str],
        adapter: NormalizedAdapter,
        ttl_seconds: int = 86_400,
    ) -> int:
        if ttl_seconds < 1 or ttl_seconds > 2_592_000:
            raise ValueError("Qualification TTL must be between 1 and 2592000 seconds")
        evidence = adapter.contract_evidence()
        dimensions = evidence["health_dimensions"]
        if set(dimensions) != set(HEALTH_DIMENSIONS):
            raise ValueError("Qualification health dimensions are incomplete")
        status = (
            "qualified"
            if dimensions["availability"]["status"] == "ready"
            else "failed"
        )
        return self.storage.record_worker_qualification(
            worker_id=worker_id,
            provider_id=provider_id,
            role=role,
            capabilities=sorted(capabilities),
            dimensions=dimensions,
            evidence=evidence,
            status=status,
            ttl_seconds=ttl_seconds,
        )

    def replacement_and_handoff(
        self,
        *,
        failed_worker_id: str,
        role: str,
        required_capabilities: set[str],
        task_id: int,
        run_id: int | None,
        stage_id: str,
        attempt_id: str | None,
        context_digest: str,
        evidence: dict[str, Any],
        reason: str,
    ) -> str:
        self.storage.set_worker_lifecycle(
            failed_worker_id, "quarantined", reason=reason
        )
        replacement = self.storage.select_qualified_worker(
            role=role,
            required_capabilities=required_capabilities,
            excluded_workers={failed_worker_id},
        )
        if replacement is None:
            raise RuntimeError("No compatible qualified replacement is available")
        self.storage.create_worker_handoff(
            source_worker_id=failed_worker_id,
            replacement_worker_id=replacement,
            task_id=task_id,
            run_id=run_id,
            stage_id=stage_id,
            attempt_id=attempt_id,
            context_digest=context_digest,
            evidence=evidence,
            reason=reason,
        )
        return replacement
