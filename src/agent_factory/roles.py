"""Provider-neutral versioned role definitions and duty compatibility."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from .storage import SQLiteStorage


IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]*$")
VERSION = re.compile(r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")
FIELD_TYPES = {"string", "integer", "number", "boolean", "object", "array"}


@dataclass(frozen=True)
class ContractField:
    name: str
    type: str
    required: bool = True

    def __post_init__(self):
        if not IDENTIFIER.fullmatch(self.name) or self.type not in FIELD_TYPES:
            raise ValueError(f"Invalid role contract field: {self.name}:{self.type}")


@dataclass(frozen=True)
class RoleDefinition:
    id: str
    version: str
    purpose: str
    responsibilities: tuple[str, ...]
    inputs: tuple[ContractField, ...]
    outputs: tuple[ContractField, ...]
    tools: tuple[str, ...]
    permissions: tuple[str, ...]
    limits: tuple[tuple[str, float], ...]
    evidence: tuple[ContractField, ...]
    incompatible_duties: tuple[str, ...] = ()

    def __post_init__(self):
        if not IDENTIFIER.fullmatch(self.id) or not VERSION.fullmatch(self.version):
            raise ValueError("Role ID or semantic version is invalid")
        if not self.purpose.strip() or not self.responsibilities:
            raise ValueError("Role purpose and responsibilities are required")
        for collection, label in (
            (self.inputs, "input"), (self.outputs, "output"), (self.evidence, "evidence")
        ):
            names = [field.name for field in collection]
            if len(names) != len(set(names)):
                raise ValueError(f"Duplicate {label} contract field")
        if tuple(sorted(set(self.tools))) != self.tools:
            raise ValueError("Role tools must be unique and sorted")
        if tuple(sorted(set(self.permissions))) != self.permissions:
            raise ValueError("Role permissions must be unique and sorted")
        if any(not IDENTIFIER.fullmatch(value) for value in (*self.tools, *self.permissions)):
            raise ValueError("Role tools and permissions require provider-neutral identifiers")
        limits = dict(self.limits)
        if len(limits) != len(self.limits) or any(value <= 0 for value in limits.values()):
            raise ValueError("Role limits must be unique positive values")
        if tuple(sorted(set(self.incompatible_duties))) != self.incompatible_duties:
            raise ValueError("Role incompatible duties must be unique and sorted")
        if self.id in self.incompatible_duties or any(
            not IDENTIFIER.fullmatch(value) for value in self.incompatible_duties
        ):
            raise ValueError("Role incompatible duties are invalid")


class RoleRegistry:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    @staticmethod
    def _document(role: RoleDefinition) -> dict[str, Any]:
        return asdict(role)

    @staticmethod
    def _from_document(document: dict[str, Any]) -> RoleDefinition:
        return RoleDefinition(
            id=document["id"], version=document["version"], purpose=document["purpose"],
            responsibilities=tuple(document["responsibilities"]),
            inputs=tuple(ContractField(**field) for field in document["inputs"]),
            outputs=tuple(ContractField(**field) for field in document["outputs"]),
            tools=tuple(document["tools"]), permissions=tuple(document["permissions"]),
            limits=tuple((str(key), float(value)) for key, value in document["limits"]),
            evidence=tuple(ContractField(**field) for field in document["evidence"]),
            incompatible_duties=tuple(document.get("incompatible_duties", ())),
        )

    def register(self, role: RoleDefinition) -> int:
        document = self._document(role)
        payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        existing = self.storage.db.execute(
            "SELECT id,contract_digest FROM role_definitions WHERE role_id=? AND version=?",
            (role.id, role.version),
        ).fetchone()
        if existing:
            if existing["contract_digest"] != digest:
                raise ValueError("Role version already exists with another contract")
            return int(existing["id"])
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO role_definitions(
                       identity,role_id,version,contract_json,contract_digest
                   ) VALUES(?,?,?,?,?)""",
                (self.storage._identity("role-definition"), role.id, role.version, payload, digest),
            )
            role_definition_id = int(cursor.lastrowid)
            self.storage._event("role.definition.registered", "role_definition", role_definition_id, {
                "role_id": role.id, "version": role.version, "contract_digest": digest,
            })
        return role_definition_id

    def resolve(self, role_id: str, version: str | None = None) -> RoleDefinition:
        row = self.storage.db.execute(
            "SELECT * FROM role_definitions WHERE role_id=? AND version=?" if version else
            "SELECT * FROM role_definitions WHERE role_id=? ORDER BY id DESC LIMIT 1",
            (role_id, version) if version else (role_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown role definition: {role_id}@{version or 'latest'}")
        return self._from_document(json.loads(row["contract_json"]))

    @staticmethod
    def _validate_fields(fields: tuple[ContractField, ...], value: dict[str, Any], label: str) -> None:
        if not isinstance(value, dict):
            raise TypeError(f"Role {label} must be an object")
        expected = {field.name: field for field in fields}
        unknown = set(value) - set(expected)
        missing = {field.name for field in fields if field.required and field.name not in value}
        if unknown or missing:
            raise ValueError(f"Role {label} fields invalid: missing={sorted(missing)}, unknown={sorted(unknown)}")
        python_types = {
            "string": str, "integer": int, "number": (int, float), "boolean": bool,
            "object": dict, "array": list,
        }
        for name, item in value.items():
            field = expected[name]
            if field.type in {"integer", "number"} and isinstance(item, bool):
                raise TypeError(f"Role {label}.{name} must be {field.type}")
            if not isinstance(item, python_types[field.type]):
                raise TypeError(f"Role {label}.{name} must be {field.type}")

    def validate_input(self, role_id: str, version: str, value: dict[str, Any]) -> None:
        self._validate_fields(self.resolve(role_id, version).inputs, value, "input")

    def validate_output(self, role_id: str, version: str, value: dict[str, Any]) -> None:
        self._validate_fields(self.resolve(role_id, version).outputs, value, "output")

    def validate_evidence(self, role_id: str, version: str, value: dict[str, Any]) -> None:
        self._validate_fields(self.resolve(role_id, version).evidence, value, "evidence")

    def require_role(
        self, *, workflow_id: str, workflow_version: str, stage_key: str,
        role_id: str, role_version: str,
    ) -> int:
        role = self.resolve(role_id, role_version)
        requirement = {
            "role_id": role.id, "role_version": role.version,
            "required_tools": role.tools, "required_permissions": role.permissions,
        }
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO workflow_role_requirements(
                       identity,workflow_id,workflow_version,stage_key,
                       role_id,role_version,requirement_json
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("workflow-role"), workflow_id, workflow_version,
                    stage_key, role_id, role_version, json.dumps(requirement, sort_keys=True),
                ),
            )
            requirement_id = int(cursor.lastrowid)
            self.storage._event("workflow.role.required", "workflow_role_requirement", requirement_id, {
                "workflow_id": workflow_id, "workflow_version": workflow_version,
                "stage_key": stage_key, "role_id": role_id, "role_version": role_version,
            })
        return requirement_id

    def assign_decision_role(
        self, *, decision_key: str, agent_id: str, role_id: str, role_version: str,
    ) -> int:
        if not decision_key.strip() or not agent_id.strip():
            raise ValueError("Decision and agent identities are required")
        role = self.resolve(role_id, role_version)
        existing = self.storage.db.execute(
            """SELECT role_id,role_version FROM role_decision_assignments
                WHERE decision_key=? AND agent_id=? ORDER BY id""",
            (decision_key, agent_id),
        ).fetchall()
        for row in existing:
            other = self.resolve(str(row["role_id"]), str(row["role_version"]))
            if other.id in role.incompatible_duties or role.id in other.incompatible_duties:
                raise PermissionError(
                    f"Agent {agent_id} cannot serve incompatible roles {other.id} and {role.id}"
                )
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO role_decision_assignments(
                       identity,decision_key,agent_id,role_id,role_version
                   ) VALUES(?,?,?,?,?)""",
                (
                    self.storage._identity("role-decision-assignment"), decision_key,
                    agent_id, role_id, role_version,
                ),
            )
            assignment_id = int(cursor.lastrowid)
            self.storage._event("role.decision.assigned", "role_decision_assignment", assignment_id, {
                "decision_key": decision_key, "agent_id": agent_id,
                "role_id": role_id, "role_version": role_version,
            })
        return assignment_id
