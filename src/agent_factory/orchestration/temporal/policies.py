from __future__ import annotations

from datetime import timedelta

from temporalio.common import RetryPolicy


NON_RETRYABLE_ERROR_TYPES = (
    "CONFIGURATION",
    "CANCELLED",
    "InvalidConfiguration",
    "UnsupportedAgent",
)


def fast_transient_policy() -> RetryPolicy:
    return RetryPolicy(
        initial_interval=timedelta(seconds=2),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(seconds=30),
        maximum_attempts=5,
        non_retryable_error_types=NON_RETRYABLE_ERROR_TYPES,
    )


def llm_policy() -> RetryPolicy:
    return RetryPolicy(
        initial_interval=timedelta(seconds=5),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(minutes=2),
        maximum_attempts=4,
        non_retryable_error_types=NON_RETRYABLE_ERROR_TYPES,
    )


def coding_policy() -> RetryPolicy:
    return RetryPolicy(
        initial_interval=timedelta(seconds=15),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(minutes=5),
        maximum_attempts=2,
        non_retryable_error_types=NON_RETRYABLE_ERROR_TYPES,
    )


def policy_for_provider(provider: str) -> RetryPolicy:
    return coding_policy() if provider in {"codex", "claude", "hermes"} else llm_policy()


def classify_error(message: str, metadata: dict | None = None) -> tuple[str, bool]:
    text = message.casefold()
    metadata = metadata or {}
    if metadata.get("blocked") or any(
        token in text
        for token in (
            "approval required",
            "not configured",
            "unsupported",
            "workspace does not exist",
            "executable not found",
            "authentication",
        )
    ):
        return "CONFIGURATION", False
    if metadata.get("timed_out") or "timed out" in text:
        return "TIMEOUT", True
    if any(token in text for token in ("429", "rate limit", "temporarily unavailable", "connection")):
        return "TRANSIENT", True
    return "AGENT_ERROR", True
