"""Token-quota-specific worker failover helpers.

The coding chain is intentionally narrower than a generic provider fallback:
ordinary errors, timeouts, and transient rate limits stay with the selected
worker.  Only an explicit account/token quota exhaustion signal advances the
chain.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from .models import Agent, ProviderResult


TOKEN_EXHAUSTED = "TOKEN_EXHAUSTED"
QUOTA_EXHAUSTED_EVENT = "workflow.provider.token_quota_exhausted"

_TRUE_METADATA_FLAGS = (
    "token_exhausted",
    "quota_exhausted",
    "usage_limit_reached",
)
_METADATA_CODES = frozenset(
    {
        TOKEN_EXHAUSTED,
        "QUOTA_EXHAUSTED",
        "RESOURCE_EXHAUSTED",
        "USAGE_LIMIT_REACHED",
        "INSUFFICIENT_CREDITS",
    }
)
_MESSAGE_MARKERS = (
    "usage limit reached",
    "usage limit has been reached",
    "hit your usage limit",
    "hit your limit",
    "quota exhausted",
    "quota has been exhausted",
    "quota exceeded",
    "exceeded your current quota",
    "resource exhausted",
    "insufficient credits",
    "credit balance is too low",
    "no credits remaining",
    "no credits left",
    "token quota exhausted",
    "token quota exceeded",
    "tokens are exhausted",
    "tokens exhausted",
    "0 weighted tokens left",
)


def token_quota_exhausted(
    message: str | None, metadata: dict[str, Any] | None = None
) -> bool:
    """Return true only for provider/account token exhaustion.

    A bare HTTP 429 is deliberately not enough: it can be a short transient
    rate limit and should follow the normal retry policy instead of promoting a
    standby coding worker.
    """

    details = metadata or {}
    if any(details.get(flag) is True for flag in _TRUE_METADATA_FLAGS):
        return True
    for key in ("error_code", "failure_class", "reason", "status"):
        value = str(details.get(key, "")).strip().upper().replace("-", "_")
        if value in _METADATA_CODES:
            return True
    text = (message or "").casefold()
    return any(marker in text for marker in _MESSAGE_MARKERS)


def result_exhausted_quota(result: ProviderResult) -> bool:
    return not result.ok and token_quota_exhausted(result.error, result.metadata)


def configured_coding_chain(
    stage: dict[str, Any], agents: Iterable[Agent]
) -> tuple[Agent, ...]:
    """Resolve the ordered primary/standby chain from a validated stage."""

    by_id = {agent.id: agent for agent in agents}
    agent_ids = (
        str(stage["agent"]),
        *(str(value) for value in stage.get("token_exhaustion_fallback_agents", [])),
    )
    chain: list[Agent] = []
    for agent_id in agent_ids:
        try:
            agent = by_id[agent_id]
        except KeyError as exc:
            raise KeyError(f"Unknown token-failover agent: {agent_id}") from exc
        if not agent.enabled:
            raise RuntimeError(f"Required token-failover agent is disabled: {agent.id}")
        if agent.role != "Implementation Worker":
            raise RuntimeError(
                f"Token-failover agent {agent.id} must be an Implementation Worker"
            )
        chain.append(agent)
    return tuple(chain)


def exhausted_providers_for_run(storage: Any, run_id: int) -> set[str]:
    """Read provider exhaustion already observed in this durable workflow run."""

    exhausted: set[str] = set()
    rows = storage.db.execute(
        """SELECT payload FROM events
             WHERE event_type=? AND entity_type='run' AND entity_id=?
             ORDER BY id""",
        (QUOTA_EXHAUSTED_EVENT, str(run_id)),
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(str(row["payload"]))
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        provider = str(payload.get("provider", "")).strip().casefold()
        if provider:
            exhausted.add(provider)
    return exhausted


def record_exhausted_providers(
    storage: Any,
    *,
    run_id: int,
    stage_id: str,
    exhausted: Iterable[dict[str, str]],
) -> None:
    """Persist one bounded audit event per newly exhausted provider/run."""

    known = exhausted_providers_for_run(storage, run_id)
    for item in exhausted:
        provider = str(item.get("provider", "")).strip().casefold()
        agent_id = str(item.get("agent_id", "")).strip()
        if not provider or provider in known:
            continue
        storage.event(
            QUOTA_EXHAUSTED_EVENT,
            "run",
            run_id,
            {
                "run_id": run_id,
                "stage_id": stage_id,
                "provider": provider,
                "agent_id": agent_id,
                "reason": "provider reported token quota exhaustion",
            },
        )
        known.add(provider)
