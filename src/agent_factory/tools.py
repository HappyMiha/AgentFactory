"""Normalized tool registry, policy gateway, and connector lifecycle."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Callable

from .storage import SQLiteStorage


VERSION = re.compile(r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]*$")
RISK_TIERS = {"low", "medium", "high", "critical"}


@dataclass(frozen=True)
class ToolDescriptor:
    key: str
    version: str
    connector_key: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    side_effects: tuple[str, ...]
    risk_tier: str
    required_capabilities: tuple[str, ...]
    timeout_seconds: int
    evidence_outputs: tuple[str, ...]

    def __post_init__(self):
        if not IDENTIFIER.fullmatch(self.key) or not IDENTIFIER.fullmatch(self.connector_key):
            raise ValueError("Tool and connector keys are invalid")
        if not VERSION.fullmatch(self.version) or self.risk_tier not in RISK_TIERS:
            raise ValueError("Tool semantic version or risk tier is invalid")
        for schema in (self.input_schema, self.output_schema):
            if not isinstance(schema, dict) or schema.get("type") != "object":
                raise ValueError("Tool input and output schemas must be object schemas")
            if not isinstance(schema.get("properties"), dict):
                raise ValueError("Tool schemas require properties")
        for values, label in (
            (self.side_effects, "side effects"),
            (self.required_capabilities, "capabilities"),
            (self.evidence_outputs, "evidence outputs"),
        ):
            if not values or tuple(sorted(set(values))) != values:
                raise ValueError(f"Tool {label} must be non-empty, unique, and sorted")
        if not 1 <= self.timeout_seconds <= 3600:
            raise ValueError("Tool timeout must be between 1 and 3600 seconds")

    @property
    def mutation_capable(self) -> bool:
        return self.side_effects != ("none",)


class ToolRegistry:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def register(self, descriptor: ToolDescriptor) -> int:
        document = asdict(descriptor)
        payload = self._json(document)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        existing = self.storage.db.execute(
            "SELECT id,descriptor_digest FROM tool_descriptors WHERE tool_key=? AND version=?",
            (descriptor.key, descriptor.version),
        ).fetchone()
        if existing:
            if existing["descriptor_digest"] != digest:
                raise ValueError("Tool version already exists with another descriptor")
            return int(existing["id"])
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO tool_descriptors(
                       identity,tool_key,version,connector_key,descriptor_json,descriptor_digest
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    self.storage._identity("tool-descriptor"), descriptor.key,
                    descriptor.version, descriptor.connector_key, payload, digest,
                ),
            )
            descriptor_id = int(cursor.lastrowid)
            self.storage._event("tool.registered", "tool_descriptor", descriptor_id, {
                "tool_key": descriptor.key, "version": descriptor.version,
                "connector_key": descriptor.connector_key, "risk_tier": descriptor.risk_tier,
                "descriptor_digest": digest,
            })
        return descriptor_id

    def resolve(self, key: str, version: str | None = None) -> tuple[int, ToolDescriptor]:
        row = self.storage.db.execute(
            "SELECT * FROM tool_descriptors WHERE tool_key=? AND version=?" if version else
            "SELECT * FROM tool_descriptors WHERE tool_key=? ORDER BY id DESC LIMIT 1",
            (key, version) if version else (key,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown tool descriptor: {key}@{version or 'latest'}")
        document = json.loads(row["descriptor_json"])
        descriptor = ToolDescriptor(
            key=document["key"], version=document["version"],
            connector_key=document["connector_key"],
            input_schema=document["input_schema"], output_schema=document["output_schema"],
            side_effects=tuple(document["side_effects"]), risk_tier=document["risk_tier"],
            required_capabilities=tuple(document["required_capabilities"]),
            timeout_seconds=int(document["timeout_seconds"]),
            evidence_outputs=tuple(document["evidence_outputs"]),
        )
        return int(row["id"]), descriptor


class ConnectorManager:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def _version(
        self, *, connector_key: str, version: str, kind: str, environment: str,
        mutation_capable: bool, manifest: dict[str, Any], approved_by: str | None,
    ) -> int:
        if not IDENTIFIER.fullmatch(connector_key) or not VERSION.fullmatch(version):
            raise ValueError("Connector key or semantic version is invalid")
        if kind not in {"native", "mcp", "cli", "http"}:
            raise ValueError("Connector kind is invalid")
        if environment not in {"development", "production"} or not manifest:
            raise ValueError("Connector environment and manifest are required")
        if environment == "production" and mutation_capable and not (approved_by or "").strip():
            raise PermissionError(
                "Mutation-capable production connectors require human approval"
            )
        document = {
            "connector_key": connector_key, "version": version, "kind": kind,
            "environment": environment, "mutation_capable": mutation_capable,
            "manifest": manifest,
        }
        payload = self._json(document)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        existing = self.storage.db.execute(
            "SELECT id,manifest_digest FROM connector_versions WHERE connector_key=? AND version=?",
            (connector_key, version),
        ).fetchone()
        if existing:
            if existing["manifest_digest"] != digest:
                raise ValueError("Connector version already exists with another manifest")
            return int(existing["id"])
        cursor = self.storage.db.execute(
            """INSERT INTO connector_versions(
                   identity,connector_key,version,kind,environment,mutation_capable,
                   manifest_json,manifest_digest,approved_by
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                self.storage._identity("connector-version"), connector_key, version,
                kind, environment, int(mutation_capable), self._json(manifest), digest,
                approved_by,
            ),
        )
        return int(cursor.lastrowid)

    def install(
        self, *, connector_key: str, version: str, kind: str, environment: str,
        mutation_capable: bool, manifest: dict[str, Any], actor: str,
        approved_by: str | None = None,
    ) -> int:
        if self.storage.db.execute(
            "SELECT 1 FROM connector_instances WHERE connector_key=?", (connector_key,)
        ).fetchone():
            raise ValueError("Connector is already installed")
        with self.storage.db:
            version_id = self._version(
                connector_key=connector_key, version=version, kind=kind,
                environment=environment, mutation_capable=mutation_capable,
                manifest=manifest, approved_by=approved_by,
            )
            cursor = self.storage.db.execute(
                """INSERT INTO connector_instances(
                       identity,connector_key,connector_version_id,status,health_reason
                   ) VALUES(?,?,?,'installed','awaiting health check')""",
                (self.storage._identity("connector"), connector_key, version_id),
            )
            connector_id = int(cursor.lastrowid)
            self._lifecycle(connector_id, version_id, "installed", actor, "connector installed")
        return connector_id

    def health(self, connector_id: int, *, healthy: bool, actor: str, reason: str) -> None:
        self._transition(
            connector_id, "healthy" if healthy else "unhealthy",
            "healthy" if healthy else "health_failed", actor, reason,
        )

    def disable(self, connector_id: int, *, actor: str, reason: str) -> None:
        self._transition(connector_id, "disabled", "disabled", actor, reason)

    def remove(self, connector_id: int, *, actor: str, reason: str) -> None:
        self._transition(connector_id, "removed", "removed", actor, reason)

    def upgrade(
        self, connector_id: int, *, version: str, kind: str, environment: str,
        mutation_capable: bool, manifest: dict[str, Any], actor: str,
        approved_by: str | None = None,
    ) -> None:
        row = self.storage.db.execute(
            "SELECT * FROM connector_instances WHERE id=?", (connector_id,)
        ).fetchone()
        if not row or row["status"] == "removed":
            raise PermissionError("Removed or unknown connector cannot be upgraded")
        with self.storage.db:
            version_id = self._version(
                connector_key=str(row["connector_key"]), version=version, kind=kind,
                environment=environment, mutation_capable=mutation_capable,
                manifest=manifest, approved_by=approved_by,
            )
            self.storage.db.execute(
                """UPDATE connector_instances SET connector_version_id=?,status='installed',
                          health_reason='awaiting health check',version_counter=version_counter+1,
                          updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (version_id, connector_id),
            )
            self._lifecycle(connector_id, version_id, "upgraded", actor, "connector upgraded")

    def _transition(
        self, connector_id: int, status: str, event: str, actor: str, reason: str,
    ) -> None:
        if not reason.strip() or not actor.strip():
            raise ValueError("Connector transition actor and reason are required")
        row = self.storage.db.execute(
            "SELECT * FROM connector_instances WHERE id=?", (connector_id,)
        ).fetchone()
        if not row or row["status"] == "removed":
            raise PermissionError("Connector is removed or unknown")
        with self.storage.db:
            self.storage.db.execute(
                """UPDATE connector_instances SET status=?,health_reason=?,
                          version_counter=version_counter+1,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (status, reason.strip(), connector_id),
            )
            self._lifecycle(
                connector_id, int(row["connector_version_id"]), event, actor, reason.strip()
            )

    def _lifecycle(
        self, connector_id: int, version_id: int, event: str, actor: str, reason: str,
    ) -> None:
        cursor = self.storage.db.execute(
            """INSERT INTO connector_lifecycle_events(
                   identity,connector_id,connector_version_id,event_type,actor,reason
               ) VALUES(?,?,?,?,?,?)""",
            (
                self.storage._identity("connector-event"), connector_id, version_id,
                event, actor, reason,
            ),
        )
        self.storage._event(f"connector.{event}", "connector", connector_id, {
            "lifecycle_event_id": int(cursor.lastrowid), "version_id": version_id,
            "actor": actor, "reason": reason,
        })


class ToolGateway:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage
        self.registry = ToolRegistry(storage)

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _validate(schema: dict[str, Any], value: dict[str, Any], label: str) -> None:
        if not isinstance(value, dict):
            raise TypeError(f"Tool {label} must be an object")
        properties = schema["properties"]
        required = set(schema.get("required", []))
        missing = required - set(value)
        unknown = set(value) - set(properties) if schema.get("additionalProperties", True) is False else set()
        if missing or unknown:
            raise ValueError(f"Tool {label} schema mismatch: missing={sorted(missing)}, unknown={sorted(unknown)}")
        types = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
                 "object": dict, "array": list}
        for key, item in value.items():
            expected = properties.get(key, {}).get("type")
            if expected in types and (isinstance(item, bool) and expected in {"integer", "number"}
                                      or not isinstance(item, types[expected])):
                raise TypeError(f"Tool {label}.{key} must be {expected}")

    def discover(
        self, *, connector_id: int, mission_id: str, role_id: str,
        discovered_tools: tuple[str, ...], mission_allowlist: set[str],
        role_allowlist: set[str], policy_allowlist: set[str],
    ) -> tuple[str, ...]:
        connector = self.storage.db.execute(
            "SELECT * FROM connector_instances WHERE id=?", (connector_id,)
        ).fetchone()
        if not connector or connector["status"] not in {"healthy", "installed"}:
            raise PermissionError("Dynamic discovery requires an available connector")
        discovered = tuple(sorted(set(discovered_tools)))
        allowed = mission_allowlist & role_allowlist & policy_allowlist
        authorized = tuple(tool for tool in discovered if tool in allowed)
        document = {
            "connector_id": connector_id, "mission_id": mission_id, "role_id": role_id,
            "discovered": discovered, "authorized": authorized,
        }
        digest = hashlib.sha256(self._json(document).encode()).hexdigest()
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT OR IGNORE INTO tool_discoveries(
                       identity,connector_id,mission_id,role_id,discovered_json,
                       authorized_json,discovery_digest
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("tool-discovery"), connector_id, mission_id,
                    role_id, self._json(discovered), self._json(authorized), digest,
                ),
            )
            if cursor.lastrowid:
                self.storage._event("tool.discovered", "connector", connector_id, {
                    "mission_id": mission_id, "role_id": role_id,
                    "discovered": discovered, "authorized": authorized,
                })
        return authorized

    def invoke(
        self, *, tool_key: str, tool_version: str, connector_id: int,
        mission_id: str, role_id: str, arguments: dict[str, Any],
        mission_allowlist: set[str], role_allowlist: set[str],
        policy_allowlist: set[str], capabilities: set[str],
        executor: Callable[[dict[str, Any], int], dict[str, Any]],
    ) -> int:
        descriptor_id, descriptor = self.registry.resolve(tool_key, tool_version)
        connector = self.storage.db.execute(
            """SELECT i.*,v.mutation_capable FROM connector_instances i
                 JOIN connector_versions v ON v.id=i.connector_version_id WHERE i.id=?""",
            (connector_id,),
        ).fetchone()
        allowed = mission_allowlist & role_allowlist & policy_allowlist
        if tool_key not in allowed:
            raise PermissionError("Tool invocation exceeds mission, role, or policy allowlist")
        if not connector or connector["status"] != "healthy" \
                or connector["connector_key"] != descriptor.connector_key:
            raise PermissionError("Tool connector is not healthy or does not match")
        if not set(descriptor.required_capabilities) <= capabilities:
            raise PermissionError("Tool invocation lacks required capabilities")
        self._validate(descriptor.input_schema, arguments, "input")
        request = {
            "tool_key": tool_key, "tool_version": tool_version, "connector_id": connector_id,
            "mission_id": mission_id, "role_id": role_id, "arguments": arguments,
            "timeout_seconds": descriptor.timeout_seconds,
        }
        request_json = self._json(request)
        request_digest = hashlib.sha256(request_json.encode()).hexdigest()
        try:
            output = executor(arguments, descriptor.timeout_seconds)
            self._validate(descriptor.output_schema, output, "output")
            missing_evidence = set(descriptor.evidence_outputs) - set(output)
            if missing_evidence:
                raise ValueError(f"Tool output lacks evidence: {sorted(missing_evidence)}")
            outcome, evidence = "succeeded", output
        except Exception as exc:
            outcome, evidence = "failed", {"error": str(exc)}
        evidence_json = self._json(evidence)
        evidence_digest = hashlib.sha256(
            self._json({"request_digest": request_digest, "outcome": outcome, "evidence": evidence}).encode()
        ).hexdigest()
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO tool_invocations(
                       identity,tool_descriptor_id,connector_id,mission_id,role_id,
                       request_json,request_digest,outcome,evidence_json,evidence_digest
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("tool-invocation"), descriptor_id, connector_id,
                    mission_id, role_id, request_json, request_digest, outcome,
                    evidence_json, evidence_digest,
                ),
            )
            invocation_id = int(cursor.lastrowid)
            self.storage._event(f"tool.invocation.{outcome}", "tool_invocation", invocation_id, {
                "tool_key": tool_key, "connector_id": connector_id,
                "mission_id": mission_id, "role_id": role_id,
                "request_digest": request_digest, "evidence_digest": evidence_digest,
            })
        if outcome == "failed":
            raise RuntimeError(evidence["error"])
        return invocation_id
