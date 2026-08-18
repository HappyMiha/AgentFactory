from __future__ import annotations

import os
from dataclasses import dataclass


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        value = default if raw is None else int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True)
class TemporalSettings:
    enabled: bool = False
    address: str = "localhost:7233"
    namespace: str = "agentfactory"
    task_queue: str = "agentfactory-main"
    ui_url: str = "http://localhost:8080"
    connect_timeout_seconds: int = 10
    fast_activity_timeout_seconds: int = 120
    llm_activity_timeout_seconds: int = 3600
    heartbeat_timeout_seconds: int = 60
    heartbeat_interval_seconds: int = 10
    cancellation_grace_seconds: int = 15
    max_repair_iterations: int = 5

    @classmethod
    def from_env(cls) -> "TemporalSettings":
        settings = cls(
            enabled=_boolean("TEMPORAL_ENABLED", False),
            address=os.getenv("TEMPORAL_ADDRESS", "localhost:7233").strip(),
            namespace=os.getenv("TEMPORAL_NAMESPACE", "agentfactory").strip(),
            task_queue=os.getenv("TEMPORAL_TASK_QUEUE", "agentfactory-main").strip(),
            ui_url=os.getenv("TEMPORAL_UI_URL", "http://localhost:8080").strip().rstrip("/"),
            connect_timeout_seconds=_positive_int("TEMPORAL_CONNECT_TIMEOUT_SECONDS", 10),
            fast_activity_timeout_seconds=_positive_int(
                "TEMPORAL_FAST_ACTIVITY_TIMEOUT_SECONDS", 120
            ),
            llm_activity_timeout_seconds=_positive_int(
                "TEMPORAL_LLM_ACTIVITY_TIMEOUT_SECONDS", 3600
            ),
            heartbeat_timeout_seconds=_positive_int(
                "TEMPORAL_HEARTBEAT_TIMEOUT_SECONDS", 60
            ),
            heartbeat_interval_seconds=_positive_int(
                "TEMPORAL_HEARTBEAT_INTERVAL_SECONDS", 10
            ),
            cancellation_grace_seconds=_positive_int(
                "TEMPORAL_CANCELLATION_GRACE_SECONDS", 15
            ),
            max_repair_iterations=_positive_int(
                "AGENTFACTORY_MAX_REPAIR_ITERATIONS", 5
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        for name, value in (
            ("TEMPORAL_ADDRESS", self.address),
            ("TEMPORAL_NAMESPACE", self.namespace),
            ("TEMPORAL_TASK_QUEUE", self.task_queue),
            ("TEMPORAL_UI_URL", self.ui_url),
        ):
            if not value:
                raise ValueError(f"{name} cannot be empty")
        if self.heartbeat_interval_seconds >= self.heartbeat_timeout_seconds:
            raise ValueError(
                "TEMPORAL_HEARTBEAT_INTERVAL_SECONDS must be less than "
                "TEMPORAL_HEARTBEAT_TIMEOUT_SECONDS"
            )

    def workflow_url(self, workflow_id: str) -> str:
        return (
            f"{self.ui_url}/namespaces/{self.namespace}/workflows/"
            f"{workflow_id}"
        )
