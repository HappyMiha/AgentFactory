"""Idempotent approved-Blueprint mission bootstrap and compensation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Callable

from .storage import SQLiteStorage
from .workflow_contracts import validate_workflow


MANIFEST_KINDS = ("agent", "role", "tool", "policy", "context", "budget", "environment")
RESOURCE_TABLES = (
    "projects", "work_items", "workflow_runs", "workflow_stages",
    "bootstrapped_missions", "mission_manifests", "mission_initial_checkpoints",
)


@dataclass(frozen=True)
class MissionManifests:
    agent: dict[str, Any]
    role: dict[str, Any]
    tool: dict[str, Any]
    policy: dict[str, Any]
    context: dict[str, Any]
    budget: dict[str, Any]
    environment: dict[str, Any]

    def __post_init__(self):
        for kind in MANIFEST_KINDS:
            value = getattr(self, kind)
            if not isinstance(value, dict) or not value:
                raise ValueError(f"Mission {kind} manifest must be a non-empty object")


@dataclass(frozen=True)
class BootstrappedMission:
    id: int
    blueprint_id: int
    blueprint_digest: str
    project_id: int
    task_id: int
    workflow_run_id: int
    manifest_digests: dict[str, str]
    checkpoint_id: int


class MissionBootstrapService:
    def __init__(
        self,
        storage: SQLiteStorage,
        failure_injector: Callable[[str], None] | None = None,
    ):
        self.storage = storage
        self.failure_injector = failure_injector

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def _inject(self, phase: str) -> None:
        if self.failure_injector:
            self.failure_injector(phase)

    def _resource_state(self) -> dict[str, int]:
        return {
            table: int(self.storage.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in RESOURCE_TABLES
        }

    def _blueprint(self, blueprint_id: int):
        row = self.storage.db.execute(
            "SELECT * FROM factory_blueprints WHERE id=?", (blueprint_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown Factory Blueprint: {blueprint_id}")
        latest = self.storage.db.execute(
            "SELECT MAX(version) FROM factory_blueprints WHERE blueprint_key=?",
            (row["blueprint_key"],),
        ).fetchone()[0]
        authorization = self.storage.db.execute(
            """SELECT x.* FROM blueprint_execution_authorizations x
                 JOIN blueprint_approvals a ON a.id=x.approval_id
                WHERE x.blueprint_id=? AND a.decision='approved'
                  AND x.blueprint_version=? AND x.blueprint_digest=?""",
            (blueprint_id, row["version"], row["blueprint_digest"]),
        ).fetchone()
        if row["version"] != latest or not authorization:
            raise PermissionError("Mission bootstrap requires the latest authorized Blueprint")
        return row, authorization

    def _rollback_point(self, blueprint: Any) -> tuple[int, dict[str, int]]:
        state = self._resource_state()
        state_json = self._json(state)
        digest = hashlib.sha256(self._json({
            "blueprint_id": int(blueprint["id"]),
            "blueprint_digest": str(blueprint["blueprint_digest"]),
            "state": state,
        }).encode()).hexdigest()
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO mission_bootstrap_rollback_points(
                       identity,blueprint_id,blueprint_digest,state_json,state_digest
                   ) VALUES(?,?,?,?,?)""",
                (
                    self.storage._identity("mission-rollback"), blueprint["id"],
                    blueprint["blueprint_digest"], state_json, digest,
                ),
            )
            rollback_id = int(cursor.lastrowid)
            self.storage._event("mission.bootstrap.rollback.recorded", "factory_blueprint", blueprint["id"], {
                "rollback_point_id": rollback_id, "blueprint_digest": blueprint["blueprint_digest"],
                "state_digest": digest,
            })
        return rollback_id, state

    def bootstrap(
        self,
        *,
        blueprint_id: int,
        workflow: dict[str, Any],
        workflow_version: str,
        manifests: MissionManifests,
    ) -> BootstrappedMission:
        blueprint, authorization = self._blueprint(blueprint_id)
        stages = list(validate_workflow(workflow))
        if not workflow_version.strip():
            raise ValueError("Bootstrap workflow version is required")
        request = {
            "blueprint_id": blueprint_id,
            "blueprint_digest": str(blueprint["blueprint_digest"]),
            "authorization_id": int(authorization["id"]),
            "workflow": workflow,
            "workflow_version": workflow_version,
            "manifests": asdict(manifests),
        }
        request_json = self._json(request)
        request_digest = hashlib.sha256(request_json.encode()).hexdigest()
        existing = self.storage.db.execute(
            "SELECT * FROM bootstrapped_missions WHERE blueprint_digest=?",
            (blueprint["blueprint_digest"],),
        ).fetchone()
        if existing:
            if existing["request_digest"] != request_digest:
                raise ValueError("Blueprint digest is already bound to another bootstrap request")
            return self._result(existing)

        rollback_id, rollback_state = self._rollback_point(blueprint)
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO mission_bootstrap_attempts(
                       identity,blueprint_id,blueprint_digest,rollback_point_id,
                       request_json,request_digest
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    self.storage._identity("mission-bootstrap-attempt"), blueprint_id,
                    blueprint["blueprint_digest"], rollback_id, request_json, request_digest,
                ),
            )
            attempt_id = int(cursor.lastrowid)
        try:
            self.storage.db.execute("BEGIN IMMEDIATE")
            project = self.storage.db.execute(
                "INSERT INTO projects(name,description) VALUES(?,?)",
                (
                    f"Mission {blueprint['blueprint_key']}",
                    f"Bootstrapped from Blueprint {blueprint['blueprint_key']} v{blueprint['version']}",
                ),
            )
            project_id = int(project.lastrowid)
            self._inject("project")
            task_payload = {
                "blueprint_id": blueprint_id,
                "blueprint_digest": str(blueprint["blueprint_digest"]),
                "kind": "mission_root",
            }
            task = self.storage.db.execute(
                """INSERT INTO work_items(
                       identity,project_id,title,description,payload,status,kind,
                       inputs_json,expected_outputs_json,acceptance_criteria_json,
                       permissions_json,budget_max_tokens,budget_max_seconds,
                       budget_max_cost_usd,updated_at
                   ) VALUES(?,?,?,?,?,'pending','task',?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                (
                    self.storage._identity("work-item"), project_id,
                    f"Run {blueprint['blueprint_key']}", "Execute the approved Factory Blueprint",
                    self._json(task_payload),
                    self._json({"blueprint_digest": blueprint["blueprint_digest"]}),
                    self._json(["mission_result"]),
                    self._json(["Complete approved Blueprint workflow"]),
                    self._json(manifests.policy.get("permissions", [])),
                    int(manifests.budget.get("max_tokens", 4000)),
                    int(manifests.budget.get("max_seconds", 120)),
                    float(manifests.budget.get("max_cost_usd", 0)),
                ),
            )
            task_id = int(task.lastrowid)
            definition_json = self._json(workflow)
            definition_digest = hashlib.sha256(definition_json.encode()).hexdigest()
            run = self.storage.db.execute(
                """INSERT INTO workflow_runs(
                       identity,project_id,task_id,workflow_id,status,workflow_version,
                       definition_digest,definition_json
                   ) VALUES(?,?,?,?, 'running',?,?,?)""",
                (
                    self.storage._identity("run"), project_id, task_id, workflow["id"],
                    workflow_version, definition_digest, definition_json,
                ),
            )
            run_id = int(run.lastrowid)
            self.storage.db.execute(
                "INSERT INTO active_workflow_claims(task_id,workflow_id,run_id) VALUES(?,?,?)",
                (task_id, workflow["id"], run_id),
            )
            for stage in stages:
                self.storage.db.execute(
                    """INSERT INTO workflow_stages(
                           identity,run_id,stage_key,status,dependencies_json,definition_json
                       ) VALUES(?,?,?,'pending',?,?)""",
                    (
                        self.storage._identity("stage"), run_id, stage["id"],
                        self._json(stage.get("depends_on", [])), self._json(stage),
                    ),
                )
            self._inject("workflow")
            mission = self.storage.db.execute(
                """INSERT INTO bootstrapped_missions(
                       identity,blueprint_id,blueprint_digest,bootstrap_attempt_id,
                       project_id,task_id,workflow_run_id,request_digest,status
                   ) VALUES(?,?,?,?,?,?,?,?, 'ready')""",
                (
                    self.storage._identity("mission"), blueprint_id,
                    blueprint["blueprint_digest"], attempt_id, project_id, task_id,
                    run_id, request_digest,
                ),
            )
            mission_id = int(mission.lastrowid)
            for kind in MANIFEST_KINDS:
                value = getattr(manifests, kind)
                manifest_json = self._json(value)
                manifest_digest = hashlib.sha256(
                    f"{mission_id}:{kind}:{manifest_json}".encode()
                ).hexdigest()
                self.storage.db.execute(
                    """INSERT INTO mission_manifests(
                           identity,mission_id,manifest_kind,manifest_json,manifest_digest
                       ) VALUES(?,?,?,?,?)""",
                    (
                        self.storage._identity("mission-manifest"), mission_id,
                        kind, manifest_json, manifest_digest,
                    ),
                )
            self._inject("manifests")
            checkpoint = {
                "schema_version": 1, "mission_id": mission_id, "blueprint_id": blueprint_id,
                "blueprint_digest": str(blueprint["blueprint_digest"]),
                "project_id": project_id, "task_id": task_id, "workflow_run_id": run_id,
                "workflow_definition_digest": definition_digest,
                "stage_states": {stage["id"]: "pending" for stage in stages},
            }
            checkpoint_json = self._json(checkpoint)
            checkpoint_digest = hashlib.sha256(checkpoint_json.encode()).hexdigest()
            checkpoint_cursor = self.storage.db.execute(
                """INSERT INTO mission_initial_checkpoints(
                       identity,mission_id,workflow_run_id,state_json,state_digest
                   ) VALUES(?,?,?,?,?)""",
                (
                    self.storage._identity("mission-checkpoint"), mission_id, run_id,
                    checkpoint_json, checkpoint_digest,
                ),
            )
            checkpoint_id = int(checkpoint_cursor.lastrowid)
            self._inject("checkpoint")
            self.storage.db.execute(
                """INSERT INTO mission_bootstrap_outcomes(
                       identity,attempt_id,status,mission_id,compensation_json,error
                   ) VALUES(?,?,'succeeded',?,'[]','')""",
                (self.storage._identity("mission-bootstrap-outcome"), attempt_id, mission_id),
            )
            self.storage._event("mission.bootstrap.succeeded", "mission", mission_id, {
                "blueprint_id": blueprint_id, "blueprint_digest": blueprint["blueprint_digest"],
                "workflow_run_id": run_id, "checkpoint_id": checkpoint_id,
            })
            self.storage.db.commit()
        except Exception as exc:
            self.storage.db.rollback()
            restored = self._resource_state()
            compensation = {
                "strategy": "transactional_rollback",
                "resources": list(RESOURCE_TABLES),
                "rollback_point_id": rollback_id,
                "expected_state": rollback_state,
                "restored_state": restored,
                "verified": restored == rollback_state,
            }
            with self.storage.db:
                self.storage.db.execute(
                    """INSERT INTO mission_bootstrap_outcomes(
                           identity,attempt_id,status,mission_id,compensation_json,error
                       ) VALUES(?,?,'failed',NULL,?,?)""",
                    (
                        self.storage._identity("mission-bootstrap-outcome"), attempt_id,
                        self._json(compensation), str(exc),
                    ),
                )
                self.storage._event("mission.bootstrap.failed", "mission_bootstrap_attempt", attempt_id, {
                    "blueprint_id": blueprint_id, "compensation": compensation,
                })
            if not compensation["verified"]:
                raise RuntimeError("Mission bootstrap failed and rollback verification failed") from exc
            raise
        row = self.storage.db.execute(
            "SELECT * FROM bootstrapped_missions WHERE id=?", (mission_id,)
        ).fetchone()
        return self._result(row)

    def _result(self, row: Any) -> BootstrappedMission:
        manifests = {
            str(item["manifest_kind"]): str(item["manifest_digest"])
            for item in self.storage.db.execute(
                "SELECT * FROM mission_manifests WHERE mission_id=? ORDER BY manifest_kind",
                (row["id"],),
            )
        }
        checkpoint = self.storage.db.execute(
            "SELECT id FROM mission_initial_checkpoints WHERE mission_id=?", (row["id"],)
        ).fetchone()
        return BootstrappedMission(
            int(row["id"]), int(row["blueprint_id"]), str(row["blueprint_digest"]),
            int(row["project_id"]), int(row["task_id"]), int(row["workflow_run_id"]),
            manifests, int(checkpoint["id"]),
        )
