"""Hermes qualification, quarantine, and controlled runtime transfer."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .adapters import HEALTH_DIMENSIONS
from .hermes_acp import HERMES_ACP_TOOLS, HermesACPHealth
from .storage import SQLiteStorage
from .worker_runtime import FallbackForbiddenError


QUALIFICATION_CHECKS = (
    "executable_resolution", "version_constraints", "hermes_acp_check",
    "session_lifecycle", "cancellation", "workspace_confinement",
    "tool_restrictions", "permission_bridge", "usage_reporting",
    "artifact_contract",
)
MUTABLE_CAPABILITIES = {"worktree_write", "write_project", "mutate", "execute"}


@dataclass(frozen=True)
class HermesQualification:
    id: int
    worker_qualification_id: int
    status: str
    checks: dict[str, bool]
    evidence_digest: str


class HermesQualificationService:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    def qualify(
        self,
        *,
        worker_id: str,
        role: str,
        session_id: int,
        health: HermesACPHealth,
        cancellation_evidence: dict[str, Any],
        ttl_seconds: int = 86_400,
    ) -> HermesQualification:
        if ttl_seconds < 1 or ttl_seconds > 2_592_000:
            raise ValueError("Qualification TTL must be between 1 and 2592000 seconds")
        session = self.storage.runtime_session(session_id)
        request = json.loads(session["request_json"])
        if session["runtime"] != "hermes-acp" or request.get("worker_id") != worker_id:
            raise PermissionError("Qualification session does not belong to this Hermes worker")
        hermes = self.storage.db.execute(
            "SELECT * FROM hermes_acp_sessions WHERE worker_session_id=?", (session_id,)
        ).fetchone()
        if not hermes:
            raise ValueError("Qualification requires a bound Hermes ACP session")
        worktree = self.storage.managed_worktree(int(hermes["worktree_id"]))
        events = self.storage.runtime_events(session_id)
        payloads = [(row["kind"], json.loads(row["payload_json"])) for row in events]
        tools = tuple(json.loads(hermes["allowed_tools_json"]))
        checks = {
            "executable_resolution": bool(health.executable),
            "version_constraints": bool(health.healthy and health.version),
            "hermes_acp_check": bool(health.check_passed),
            "session_lifecycle": session["status"] == "succeeded" and hermes["status"] == "succeeded",
            "cancellation": bool(cancellation_evidence.get("process_tree_terminated")),
            "workspace_confinement": (
                health.workspace_access
                and int(worktree["assignment_id"]) == int(session["assignment_id"])
                and str(worktree["path"]) == str(cancellation_evidence.get("worktree"))
            ),
            "tool_restrictions": tools == HERMES_ACP_TOOLS,
            "permission_bridge": any(
                kind == "tool_call" and payload.get("permission") == "allowed"
                for kind, payload in payloads
            ),
            "usage_reporting": any(
                kind == "status" and payload.get("state") == "usage_update"
                and isinstance(payload.get("usage"), dict)
                for kind, payload in payloads
            ),
            "artifact_contract": any(
                kind == "artifact" and payload.get("kind") == "candidate_diff"
                for kind, payload in payloads
            ),
        }
        if set(checks) != set(QUALIFICATION_CHECKS):  # pragma: no cover
            raise RuntimeError("Hermes qualification matrix is incomplete")
        status = "qualified" if all(checks.values()) else "failed"
        evidence = {
            "schema_version": 1, "worker_id": worker_id, "role": role,
            "session_id": session_id, "health": health.evidence(),
            "checks": checks, "cancellation": cancellation_evidence,
            "event_ids": [int(row["id"]) for row in events],
            "hermes_session_id": int(hermes["id"]),
        }
        dimensions = {
            name: {"status": "pass" if status == "qualified" else "fail", "evidence": "Hermes AF-047 matrix"}
            for name in HEALTH_DIMENSIONS
        }
        qualification_id = self.storage.record_worker_qualification(
            worker_id=worker_id, provider_id="hermes-acp", role=role,
            capabilities=["hermes_acp", "read_project", "structured_artifacts", "usage_reporting"],
            dimensions=dimensions, evidence=evidence, status=status,
            ttl_seconds=ttl_seconds,
        )
        payload = json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO hermes_qualification_runs(
                       identity,worker_qualification_id,worker_session_id,
                       checks_json,evidence_json,evidence_digest,status
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("hermes-qualification"), qualification_id,
                    session_id, json.dumps(checks, sort_keys=True), payload, digest, status,
                ),
            )
            record_id = int(cursor.lastrowid)
            self.storage._event(f"hermes.qualification.{status}", "hermes_qualification", record_id, {
                "worker_id": worker_id, "session_id": session_id,
                "evidence_digest": digest, "failed_checks": [key for key, value in checks.items() if not value],
            })
        return HermesQualification(record_id, qualification_id, status, checks, digest)

    def quarantine_failed_runtime(self, session_id: int, *, reason: str) -> None:
        session = self.storage.runtime_session(session_id)
        request = json.loads(session["request_json"])
        if session["runtime"] != "hermes-acp" or session["status"] != "failed":
            raise ValueError("Only a failed Hermes runtime can be quarantined")
        self.storage.set_worker_lifecycle(str(request["worker_id"]), "quarantined", reason=reason)

    def authorize_readonly_fallback(
        self,
        source_session_id: int,
        *,
        target_worker_id: str,
        target_runtime: str,
        required_capabilities: set[str],
    ) -> int:
        source = self.storage.runtime_session(source_session_id)
        request = json.loads(source["request_json"])
        if source["runtime"] != "hermes-acp":
            raise ValueError("Controlled fallback source must be Hermes ACP")
        if source["status"] != "failed":
            raise ValueError("Controlled fallback requires a failed Hermes session")
        if request.get("mutable") or int(source["mutable_action_count"]) != 0:
            raise FallbackForbiddenError("Fallback is read-only and must precede every mutable action")
        if target_runtime not in {"codex-cli", "claude-cli"}:
            raise ValueError("Fallback runtime must be direct Codex or Claude")
        source_capabilities = set(request.get("permissions") or [])
        if source_capabilities & MUTABLE_CAPABILITIES or required_capabilities != source_capabilities:
            raise PermissionError("Fallback capabilities must remain read-only")
        provider_id = target_runtime.removesuffix("-cli")
        qualification = self.storage.db.execute(
            """SELECT q.* FROM worker_qualifications q
                 JOIN worker_lifecycle l ON l.worker_id=q.worker_id
                WHERE q.worker_id=? AND q.provider_id=? AND q.role=?
                  AND q.status='qualified' AND q.valid_until>CURRENT_TIMESTAMP
                  AND l.state='active' ORDER BY q.id DESC LIMIT 1""",
            (target_worker_id, provider_id, request.get("role")),
        ).fetchone()
        if not qualification or not required_capabilities <= set(json.loads(qualification["capabilities_json"])):
            raise PermissionError("Fallback worker lacks a compatible active qualification")
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO runtime_fallback_authorizations(
                       identity,source_session_id,target_qualification_id,target_worker_id,
                       target_runtime,required_capabilities_json,read_only
                   ) VALUES(?,?,?,?,?,?,1)""",
                (
                    self.storage._identity("runtime-fallback"), source_session_id,
                    qualification["id"], target_worker_id, target_runtime,
                    json.dumps(sorted(required_capabilities)),
                ),
            )
            authorization_id = int(cursor.lastrowid)
            self.storage._event("runtime.fallback.authorized", "runtime_fallback", authorization_id, {
                "source_session_id": source_session_id, "target_worker_id": target_worker_id,
                "target_runtime": target_runtime, "read_only": True,
            })
        return authorization_id

    def authorize_mutable_transfer(
        self,
        source_session_id: int,
        *,
        checkpoint_id: int,
        target_assignment_id: int,
        target_fencing_token: int,
        target_runtime: str,
    ) -> int:
        source = self.storage.runtime_session(source_session_id)
        request = json.loads(source["request_json"])
        binding = request.get("binding") or {}
        if source["runtime"] != "hermes-acp" or not request.get("mutable"):
            raise ValueError("Mutable transfer requires a mutable source session")
        if target_runtime == source["runtime"]:
            raise ValueError("Runtime transfer requires a different target runtime")
        checkpoint = self.storage.db.execute(
            """SELECT c.*,r.task_id,s.stage_key FROM stage_checkpoints c
                 JOIN workflow_runs r ON r.id=c.run_id JOIN workflow_stages s ON s.id=c.stage_id
                WHERE c.id=?""", (checkpoint_id,)
        ).fetchone()
        if not checkpoint or int(checkpoint["run_id"]) != int(binding.get("run_id", -1)) \
                or str(checkpoint["stage_key"]) != str(binding.get("stage_id")):
            raise PermissionError("Runtime transfer requires an exact source-stage checkpoint")
        target = self.storage.db.execute(
            """SELECT a.task_id,a.runtime,l.id AS lease_id,l.fencing_token,l.status
                 FROM assignments a JOIN leases l ON l.assignment_id=a.id
                WHERE a.id=? ORDER BY l.fencing_token DESC LIMIT 1""", (target_assignment_id,)
        ).fetchone()
        old_lease = self.storage.db.execute(
            "SELECT status FROM leases WHERE assignment_id=? ORDER BY fencing_token DESC LIMIT 1",
            (source["assignment_id"],),
        ).fetchone()
        if (
            not target or int(target["task_id"]) != int(checkpoint["task_id"])
            or target["status"] != "active" or int(target["fencing_token"]) != target_fencing_token
            or target_fencing_token <= int(request["fencing_token"])
            or (old_lease and old_lease["status"] == "active")
            or str(target["runtime"]) != target_runtime
        ):
            raise PermissionError("Runtime transfer requires a newer active lease after source release")
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO runtime_transfer_authorizations(
                       identity,source_session_id,checkpoint_id,target_assignment_id,
                       target_lease_id,target_fencing_token,target_runtime
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("runtime-transfer"), source_session_id,
                    checkpoint_id, target_assignment_id, target["lease_id"],
                    target_fencing_token, target_runtime,
                ),
            )
            transfer_id = int(cursor.lastrowid)
            self.storage._event("runtime.transfer.authorized", "runtime_transfer", transfer_id, {
                "source_session_id": source_session_id, "checkpoint_id": checkpoint_id,
                "target_assignment_id": target_assignment_id,
                "target_fencing_token": target_fencing_token,
            })
        return transfer_id
