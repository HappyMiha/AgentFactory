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
    autonomous_workflow_id_prefix: str = "agentfactory-autonomous-mission"
    ui_url: str = "http://localhost:8080"
    namespace_retention_days: int = 7
    connect_timeout_seconds: int = 10
    fast_activity_timeout_seconds: int = 120
    llm_activity_timeout_seconds: int = 3600
    heartbeat_timeout_seconds: int = 60
    heartbeat_interval_seconds: int = 10
    cancellation_grace_seconds: int = 15
    max_repair_iterations: int = 5
    autonomous_continue_as_new_enabled: bool = False
    autonomous_continue_as_new_event_threshold: int = 10_000
    autonomous_continue_as_new_safe_boundary_threshold: int = 100
    worker_build_id: str = "agentfactory-0.1.0-temporal-sdk-1.31.0"
    worker_deployment_name: str = "agentfactory-autonomous"
    worker_versioning_enabled: bool = False

    @classmethod
    def from_env(cls) -> "TemporalSettings":
        settings = cls(
            enabled=_boolean("TEMPORAL_ENABLED", False),
            address=os.getenv("TEMPORAL_ADDRESS", "localhost:7233").strip(),
            namespace=os.getenv("TEMPORAL_NAMESPACE", "agentfactory").strip(),
            task_queue=os.getenv("TEMPORAL_TASK_QUEUE", "agentfactory-main").strip(),
            autonomous_workflow_id_prefix=os.getenv(
                "TEMPORAL_AUTONOMOUS_WORKFLOW_ID_PREFIX",
                "agentfactory-autonomous-mission",
            ).strip(),
            ui_url=os.getenv("TEMPORAL_UI_URL", "http://localhost:8080").strip().rstrip("/"),
            namespace_retention_days=_positive_int(
                "TEMPORAL_NAMESPACE_RETENTION_DAYS", 7
            ),
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
            autonomous_continue_as_new_enabled=_boolean(
                "TEMPORAL_AUTONOMOUS_CONTINUE_AS_NEW_ENABLED", True
            ),
            autonomous_continue_as_new_event_threshold=_positive_int(
                "TEMPORAL_AUTONOMOUS_CONTINUE_AS_NEW_EVENT_THRESHOLD", 10_000
            ),
            autonomous_continue_as_new_safe_boundary_threshold=_positive_int(
                "TEMPORAL_AUTONOMOUS_CONTINUE_AS_NEW_SAFE_BOUNDARY_THRESHOLD",
                100,
            ),
            worker_build_id=os.getenv(
                "TEMPORAL_WORKER_BUILD_ID",
                "agentfactory-0.1.0-temporal-sdk-1.31.0",
            ).strip(),
            worker_deployment_name=os.getenv(
                "TEMPORAL_WORKER_DEPLOYMENT_NAME",
                "agentfactory-autonomous",
            ).strip(),
            worker_versioning_enabled=_boolean(
                "TEMPORAL_WORKER_VERSIONING_ENABLED", False
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        for name, value in (
            ("TEMPORAL_ADDRESS", self.address),
            ("TEMPORAL_NAMESPACE", self.namespace),
            ("TEMPORAL_TASK_QUEUE", self.task_queue),
            (
                "TEMPORAL_AUTONOMOUS_WORKFLOW_ID_PREFIX",
                self.autonomous_workflow_id_prefix,
            ),
            ("TEMPORAL_UI_URL", self.ui_url),
            ("TEMPORAL_WORKER_BUILD_ID", self.worker_build_id),
            ("TEMPORAL_WORKER_DEPLOYMENT_NAME", self.worker_deployment_name),
        ):
            if not value:
                raise ValueError(f"{name} cannot be empty")
        if (
            len(self.autonomous_workflow_id_prefix) > 100
            or any(
                character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
                for character in self.autonomous_workflow_id_prefix
            )
        ):
            raise ValueError(
                "TEMPORAL_AUTONOMOUS_WORKFLOW_ID_PREFIX must be a bounded "
                "identifier"
            )
        if self.heartbeat_interval_seconds >= self.heartbeat_timeout_seconds:
            raise ValueError(
                "TEMPORAL_HEARTBEAT_INTERVAL_SECONDS must be less than "
                "TEMPORAL_HEARTBEAT_TIMEOUT_SECONDS"
            )
        if not 1 <= self.namespace_retention_days <= 365:
            raise ValueError(
                "TEMPORAL_NAMESPACE_RETENTION_DAYS must be between 1 and 365"
            )
        if not 10 <= self.autonomous_continue_as_new_event_threshold <= 50_000:
            raise ValueError(
                "TEMPORAL_AUTONOMOUS_CONTINUE_AS_NEW_EVENT_THRESHOLD must be "
                "between 10 and 50000"
            )
        if not (
            1
            <= self.autonomous_continue_as_new_safe_boundary_threshold
            <= 10_000
        ):
            raise ValueError(
                "TEMPORAL_AUTONOMOUS_CONTINUE_AS_NEW_SAFE_BOUNDARY_THRESHOLD "
                "must be between 1 and 10000"
            )
        for name, value in (
            ("TEMPORAL_WORKER_BUILD_ID", self.worker_build_id),
            ("TEMPORAL_WORKER_DEPLOYMENT_NAME", self.worker_deployment_name),
        ):
            if len(value) > 255:
                raise ValueError(f"{name} must not exceed 255 characters")

    def workflow_url(self, workflow_id: str) -> str:
        return (
            f"{self.ui_url}/namespaces/{self.namespace}/workflows/"
            f"{workflow_id}"
        )
