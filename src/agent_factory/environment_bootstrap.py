"""Read-only actual-state observers for recoverable environment mutations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .durable_workflow import (
    MissionOperation,
    ObservationStatus,
    OperationClass,
    OperationObservation,
    canonical_digest,
)


EnvironmentProbe = Callable[[dict[str, Any]], Any]


class EnvironmentOperationReconciler:
    """Compare journal intent with bounded command, install, service, or model state."""

    SUPPORTED = frozenset(
        {
            OperationClass.COMMAND,
            OperationClass.INSTALLATION,
            OperationClass.SERVICE,
            OperationClass.MODEL_LIFECYCLE,
        }
    )
    _SENSITIVE_MARKERS = (
        "authorization",
        "credential",
        "password",
        "secret",
        "token",
        "api_key",
        "private_key",
    )

    def __init__(
        self,
        probes: Mapping[OperationClass | str, EnvironmentProbe] | None = None,
    ):
        self.probes = {
            OperationClass(str(getattr(operation, "value", operation))): probe
            for operation, probe in (probes or {}).items()
        }
        unsupported = set(self.probes) - self.SUPPORTED
        if unsupported:
            raise ValueError(
                "Unsupported environment probes: "
                + ", ".join(sorted(item.value for item in unsupported))
            )

    @classmethod
    def _sanitize(cls, value: Any) -> Any:
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                normalized = str(key).casefold()
                sanitized[str(key)] = (
                    "<redacted>"
                    if any(marker in normalized for marker in cls._SENSITIVE_MARKERS)
                    else cls._sanitize(item)
                )
            return sanitized
        if isinstance(value, (list, tuple)):
            return [cls._sanitize(item) for item in value]
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        return repr(value)

    @staticmethod
    def _desired_state(request: dict[str, Any]) -> Any:
        for name in ("expected_state", "desired_state", "desired"):
            if name in request:
                return request[name]
        return None

    def observe(self, operation: MissionOperation) -> OperationObservation:
        if operation.operation_class not in self.SUPPORTED:
            return OperationObservation.indeterminate(
                evidence={"operation_class": operation.operation_class.value},
                reason="No environment observer exists for this operation class",
            )
        probe = self.probes.get(operation.operation_class)
        if probe is None:
            return OperationObservation.indeterminate(
                evidence={
                    "operation_class": operation.operation_class.value,
                    "probe_configured": False,
                },
                reason="Required actual-state probe is not configured",
            )
        try:
            observed = probe(dict(operation.request))
        except Exception as exc:
            return OperationObservation.indeterminate(
                evidence={
                    "operation_class": operation.operation_class.value,
                    "probe_error": type(exc).__name__,
                },
                reason="Environment actual-state probe failed",
            )
        if isinstance(observed, OperationObservation):
            return observed
        actual = self._sanitize(observed)
        evidence = {
            "operation_class": operation.operation_class.value,
            "probe_configured": True,
            "actual_state_digest": canonical_digest({"actual": actual}),
        }
        if observed is None or (
            isinstance(observed, dict)
            and (
                observed.get("exists") is False
                or observed.get("present") is False
            )
        ):
            return OperationObservation.absent(
                evidence=evidence,
                reason="Environment probe confirms the requested effect is absent",
            )
        desired = self._sanitize(self._desired_state(operation.request))
        comparable_actual = actual
        if desired is not None and isinstance(actual, dict) and "state" in actual:
            comparable_actual = actual["state"]
        actual_document = (
            actual if isinstance(actual, dict) else {"value": actual}
        )
        if desired is None or comparable_actual == desired:
            return OperationObservation.present(
                actual_document,
                evidence=evidence,
                reason="Environment probe confirms the requested effect is present",
            )
        return OperationObservation.conflict(
            actual_document,
            evidence={
                **evidence,
                "desired_state_digest": canonical_digest({"desired": desired}),
            },
            reason="Environment state differs from the journaled desired state",
        )

    def handlers(
        self,
    ) -> dict[
        OperationClass,
        Callable[[MissionOperation], OperationObservation],
    ]:
        return {operation: self.observe for operation in self.SUPPORTED}


__all__ = [
    "EnvironmentOperationReconciler",
    "EnvironmentProbe",
    "ObservationStatus",
]
