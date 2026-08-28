"""Replay-safe integration of the first complete coding-delivery slice."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .autonomous_authorization import (
    AuthorizationOperation,
    AuthorizationOutcome,
    AutonomousAuthorizationRequest,
    AutonomousAuthorizationService,
)
from .autonomous_backlog_approval import AutonomousBacklogApprovalService
from .autonomous_mission import (
    AutonomousMissionService,
    MissionDisposition,
    MissionPhase,
)
from .backlog_revisions import (
    BacklogItemStatus,
    BacklogRevisionService,
)
from .candidate_changes import CandidateChangeService
from .control_plane import MissionControlFenceService
from .engineering_loop import EngineeringLoopService, IterationUsage, LoopLimits
from .evaluation import EvaluationService, ReviewFunction
from .mission_checkpoints import MissionCheckpointService, MissionCheckpointType
from .models import Agent, Budget, ProviderCapabilities, Status, WorkItem
from .storage import SQLiteStorage
from .validators import VALIDATOR_CATEGORIES


ReplacementSelector = Callable[[str, dict[str, object]], str | None]


@dataclass(frozen=True)
class DeliveryState:
    id: int
    status: str
    repair_iterations: int
    current_worker_id: str
    candidate_id: int | None
    evaluation_id: int | None
    founder_gate_id: int | None
    github_plan_id: int | None
    github_gate_id: int | None


class CodingDeliveryService:
    """Connect persisted AF-049 output through review, Founder, and PR planning."""

    def __init__(
        self,
        storage: SQLiteStorage,
        candidate_changes: CandidateChangeService,
        evaluations: EvaluationService,
    ):
        self.storage = storage
        self.candidates = candidate_changes
        self.evaluations = evaluations
        self.loops = EngineeringLoopService(storage)

    @staticmethod
    def _snapshot(rows) -> list[dict[str, object]]:
        return [
            {
                "id": int(row["id"]), "category": str(row["category"]),
                "status": str(row["status"]), "command_digest": str(row["command_digest"]),
                "evidence_digest": str(row["evidence_digest"]),
            }
            for row in rows
        ]

    def _state(self, row) -> DeliveryState:
        return DeliveryState(
            int(row["id"]), str(row["status"]), int(row["repair_iterations"]),
            str(row["current_worker_id"]),
            int(row["candidate_id"]) if row["candidate_id"] is not None else None,
            int(row["evaluation_id"]) if row["evaluation_id"] is not None else None,
            int(row["founder_gate_id"]) if row["founder_gate_id"] is not None else None,
            int(row["github_plan_id"]) if row["github_plan_id"] is not None else None,
            int(row["github_gate_id"]) if row["github_gate_id"] is not None else None,
        )

    def state(self, delivery_id: int) -> DeliveryState:
        row = self.storage.db.execute(
            "SELECT * FROM coding_delivery_runs WHERE id=?", (delivery_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown coding delivery: {delivery_id}")
        return self._state(row)

    def start(
        self,
        codex_result_id: int,
        *,
        logical_attempt_key: str,
        stable_task_id: str,
        max_repair_iterations: int,
    ) -> DeliveryState:
        logical_attempt_key = logical_attempt_key.strip()
        if not logical_attempt_key or max_repair_iterations <= 0:
            raise ValueError("Delivery requires a logical attempt key and positive repair cap")
        result = self.storage.db.execute(
            """SELECT w.*,a.agent_id FROM codex_worker_results w
                 JOIN assignments a ON a.id=w.assignment_id WHERE w.id=?""",
            (codex_result_id,),
        ).fetchone()
        if not result:
            raise KeyError(f"Unknown Codex result: {codex_result_id}")
        existing = self.storage.db.execute(
            "SELECT * FROM coding_delivery_runs WHERE logical_attempt_key=?",
            (logical_attempt_key,),
        ).fetchone()
        if existing:
            if (
                int(existing["task_id"]) != int(result["task_id"])
                or str(existing["stable_task_id"]) != stable_task_id
                or int(existing["max_repair_iterations"]) != max_repair_iterations
            ):
                raise ValueError("Logical attempt key is already bound to another delivery scope")
            return self._state(existing)
        task = self.storage.get_task(int(result["task_id"]))
        loop_id = self.loops.create(
            run_id=int(result["run_id"]), objective=task.description or task.title,
            worker_id=str(result["agent_id"]),
            limits=LoopLimits(
                max_repair_iterations, max(1, task.budget.max_seconds),
                max(1, task.budget.max_tokens), max(0.0, task.budget.max_cost_usd),
                max_repair_iterations,
            ),
            repeated_failure_action="replace_worker",
        )
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO coding_delivery_runs(
                       identity,logical_attempt_key,task_id,run_id,stable_task_id,
                       engineering_loop_id,initial_worker_id,current_worker_id,
                       max_repair_iterations
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("coding-delivery"), logical_attempt_key,
                    result["task_id"], result["run_id"], stable_task_id, loop_id,
                    result["agent_id"], result["agent_id"], max_repair_iterations,
                ),
            )
            delivery_id = int(cursor.lastrowid)
            self.storage._event("coding.delivery.started", "coding_delivery", delivery_id, {
                "task_id": result["task_id"], "run_id": result["run_id"],
                "logical_attempt_key": logical_attempt_key,
                "assignment_id": result["assignment_id"], "worktree_id": result["worktree_id"],
            })
        return self.state(delivery_id)

    def process(
        self,
        delivery_id: int,
        codex_result_id: int,
        *,
        reviewer: Agent,
        rubric_id: str,
        rubric_version: str,
        review: ReviewFunction,
        replacement_selector: ReplacementSelector | None = None,
    ) -> DeliveryState:
        """Preserve the standard delivery path while autonomous delivery is opt-in."""

        return AutonomousCodingDeliveryService._standard_process_impl(
            self,
            delivery_id,
            codex_result_id,
            reviewer=reviewer,
            rubric_id=rubric_id,
            rubric_version=rubric_version,
            review=review,
            replacement_selector=replacement_selector,
        )

    def founder_decide(
        self,
        delivery_id: int,
        decision: str,
        *,
        actor: str,
        note: str,
        repo: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> DeliveryState:
        """Keep the standard per-delivery Founder gate unchanged."""

        return AutonomousCodingDeliveryService._standard_founder_decide_impl(
            self,
            delivery_id,
            decision,
            actor=actor,
            note=note,
            repo=repo,
            base_branch=base_branch,
            title=title,
            body=body,
        )


@dataclass(frozen=True)
class AutonomousChildJob:
    id: int
    mission_id: int
    backlog_revision_id: int
    backlog_revision_digest: str
    execution_epoch_id: int
    authorization_id: int
    backlog_item_id: int
    stable_item_id: str
    item_digest: str
    logical_attempt: int
    control_fencing_token: int
    task_id: int
    run_id: int
    job_id: str
    child_workflow_id: str
    workflow_definition_id: str
    execution_mode: str
    context: dict[str, Any]
    context_digest: str
    prepared_by: str
    command_id: str
    created_at: str


@dataclass(frozen=True)
class AutonomousChildAuthorization:
    id: int
    child_job_id: int
    mission_id: int
    authorization_id: int
    decision_id: int
    decision_digest: str
    provider_id: str
    role: str
    model: str
    command_id: str
    created_at: str


@dataclass(frozen=True)
class AutonomousChildCompletion:
    id: int
    child_job_id: int
    mission_id: int
    run_id: int
    authorization_decision_id: int
    stage_evidence: tuple[dict[str, Any], ...]
    stage_evidence_digest: str
    validation_evidence: dict[str, Any]
    validation_evidence_digest: str
    review_evidence: dict[str, Any]
    review_evidence_digest: str
    integration_evidence: dict[str, Any]
    integration_evidence_digest: str
    git_commit_sha: str
    completion_digest: str
    command_id: str
    created_at: str


@dataclass(frozen=True)
class AutonomousChildReconciliation:
    id: int
    child_job_id: int
    completion_id: int
    mission_id: int
    backlog_item_state_id: int
    checkpoint_id: int
    result_mission_version: int
    reconciliation_digest: str
    command_id: str
    created_at: str


def autonomous_child_workflow_id(
    mission_id: int,
    revision_id: int,
    epoch_id: int,
    stable_item_id: str,
    logical_attempt: int,
) -> str:
    """Return a bounded deterministic ID for one logical item attempt."""

    if min(mission_id, revision_id, epoch_id, logical_attempt) <= 0:
        raise ValueError("Autonomous child workflow scope must be positive")
    stable = str(stable_item_id).strip()
    if not stable:
        raise ValueError("Stable item id is required")
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", stable).strip("-")[:40] or "item"
    suffix = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:12]
    return (
        f"agentfactory-autonomous-child-{mission_id}-r{revision_id}-"
        f"e{epoch_id}-{slug}-{suffix}-a{logical_attempt}"
    )


class AutonomousCodingDeliveryService:
    """Persist and reconcile opt-in autonomous AgentFactory child jobs."""

    def __init__(
        self,
        storage: SQLiteStorage,
        provider_capabilities: Mapping[str, ProviderCapabilities] | None = None,
    ):
        self.storage = storage
        self.capabilities = dict(provider_capabilities or {})
        self.missions = AutonomousMissionService(storage)
        self.revisions = BacklogRevisionService(storage)
        self.approvals = AutonomousBacklogApprovalService(
            storage, self.capabilities
        )
        self.authorizations = AutonomousAuthorizationService(
            storage, self.capabilities
        )
        self.checkpoints = MissionCheckpointService(storage)

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    @classmethod
    def _digest(cls, value: Any) -> str:
        return hashlib.sha256(cls._json(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    @staticmethod
    def _required(value: str, label: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError(f"{label} is required")
        return normalized

    @staticmethod
    def _git(repository: Path, *arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout.strip()

    def _job_from_row(self, row: Any) -> AutonomousChildJob:
        context = json.loads(row["context_json"])
        if self._digest(context) != row["context_digest"]:
            raise RuntimeError("Autonomous child context digest is corrupt")
        return AutonomousChildJob(
            id=int(row["id"]),
            mission_id=int(row["mission_id"]),
            backlog_revision_id=int(row["backlog_revision_id"]),
            backlog_revision_digest=str(row["backlog_revision_digest"]),
            execution_epoch_id=int(row["execution_epoch_id"]),
            authorization_id=int(row["authorization_id"]),
            backlog_item_id=int(row["backlog_item_id"]),
            stable_item_id=str(row["stable_item_id"]),
            item_digest=str(row["item_digest"]),
            logical_attempt=int(row["logical_attempt"]),
            control_fencing_token=int(row["control_fencing_token"]),
            task_id=int(row["task_id"]),
            run_id=int(row["run_id"]),
            job_id=str(context["job_id"]),
            child_workflow_id=str(row["child_workflow_id"]),
            workflow_definition_id=str(row["workflow_definition_id"]),
            execution_mode=str(row["execution_mode"]),
            context=context,
            context_digest=str(row["context_digest"]),
            prepared_by=str(row["prepared_by"]),
            command_id=str(row["command_id"]),
            created_at=str(row["created_at"]),
        )

    def get_job(self, child_job_id: int) -> AutonomousChildJob:
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_child_jobs WHERE id=?", (child_job_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown autonomous child job: {child_job_id}")
        return self._job_from_row(row)

    def open_job(self, mission_id: int) -> AutonomousChildJob | None:
        row = self.storage.db.execute(
            """SELECT job.* FROM autonomous_child_jobs job
               JOIN autonomous_missions mission ON mission.id=job.mission_id
               LEFT JOIN autonomous_child_reconciliations reconciliation
                 ON reconciliation.child_job_id=job.id
               LEFT JOIN autonomous_mission_retry_requests retry
                 ON retry.child_job_id=job.id
              WHERE job.mission_id=?
                AND job.backlog_revision_id=mission.active_backlog_revision_id
                AND job.execution_epoch_id=mission.active_execution_epoch_id
                AND reconciliation.id IS NULL
                AND retry.id IS NULL
              ORDER BY job.id LIMIT 1""",
            (mission_id,),
        ).fetchone()
        return self._job_from_row(row) if row else None

    def enter_development(
        self,
        mission_id: int,
        *,
        expected_mission_version: int,
        command_id: str,
    ):
        command_id = self._required(command_id, "Environment command id")
        historical = self.missions.get(
            mission_id, version=expected_mission_version
        )
        if historical.phase is not MissionPhase.APPROVED:
            raise PermissionError(
                "Environment orchestration requires the approved mission phase"
            )
        if historical.disposition is not MissionDisposition.RUNNING:
            raise PermissionError("Mission scheduling is fenced")
        approval_row = self.storage.db.execute(
            "SELECT id FROM autonomous_backlog_approvals WHERE mission_id=? "
            "ORDER BY id DESC LIMIT 1",
            (mission_id,),
        ).fetchone()
        if not approval_row:
            raise PermissionError("Mission has no persisted backlog approval")
        approval = self.approvals.get(int(approval_row["id"]))
        if approval.result_mission_version != expected_mission_version:
            raise ValueError("Approval version does not match environment start")
        authorization = self.authorizations.get_authorization(
            approval.authorization_id
        )
        if authorization.revoked:
            raise PermissionError("Autonomous authorization was revoked")
        model = authorization.role_model_manifest.get("role_models", {}).get(
            "Environment Bootstrap"
        )
        if not model:
            raise PermissionError(
                "Approved role/model manifest omits Environment Bootstrap"
            )
        decision = self.authorizations.resolve(
            AutonomousAuthorizationRequest(
                mission_id=mission_id,
                operation=AuthorizationOperation.ENVIRONMENT_BOOTSTRAP,
                role="Environment Bootstrap",
                model=str(model),
                backlog_revision_id=approval.revision_id,
                backlog_revision_digest=approval.revision_digest,
                execution_epoch_id=approval.execution_epoch_id,
                repository_path=authorization.repository_path,
                epoch_branch=authorization.epoch_branch,
                tool_profile=authorization.tool_profile,
                permissions=("environment_bootstrap",),
                authorization_id=authorization.id,
            )
        )
        if decision.outcome is not AuthorizationOutcome.ALLOW_AUTONOMOUS:
            raise PermissionError(
                "Environment bootstrap did not resolve autonomous authority: "
                + decision.reason
            )
        next_version = expected_mission_version
        for ordinal, target in enumerate(
            (
                MissionPhase.ENVIRONMENT_DISCOVERY,
                MissionPhase.ENVIRONMENT_BOOTSTRAP,
                MissionPhase.DEVELOPMENT,
            ),
            start=1,
        ):
            self.missions.transition_phase(
                mission_id,
                target,
                actor=historical.mission_owner,
                command_id=f"{command_id}:phase:{ordinal}",
                expected_version=next_version,
                reason="Advance authorized autonomous environment orchestration",
            )
            next_version += 1
        return self.missions.get(mission_id, version=next_version)

    def prepare_job(
        self,
        mission_id: int,
        stable_item_id: str,
        *,
        execution_mode: str,
        workflow_definition_id: str,
        command_id: str,
        expected_fencing_token: int | None = None,
    ) -> AutonomousChildJob:
        command_id = self._required(command_id, "Child preparation command id")
        execution_mode = self._required(execution_mode, "Child execution mode")
        if execution_mode not in {"simulation", "live"}:
            raise ValueError("Child execution mode must be simulation or live")
        workflow_definition_id = self._required(
            workflow_definition_id, "Child workflow definition id"
        )
        mission = self.missions.get(mission_id)
        if (
            mission.phase is not MissionPhase.DEVELOPMENT
            or mission.disposition is not MissionDisposition.RUNNING
            or mission.active_backlog_revision_id is None
            or mission.active_execution_epoch_id is None
        ):
            raise PermissionError("Mission is not schedulable for a child job")
        control_fence = MissionControlFenceService(self.storage).current(mission_id)
        selected_fencing_token = (
            control_fence.fencing_token
            if expected_fencing_token is None
            else int(expected_fencing_token)
        )
        MissionControlFenceService(self.storage).assert_allows(
            mission_id,
            expected_fencing_token=selected_fencing_token,
            execution_epoch_id=mission.active_execution_epoch_id,
        )
        revision = self.revisions.get_revision(
            mission.active_backlog_revision_id
        )
        item = self.revisions.item(revision.id, stable_item_id)
        if item.status is BacklogItemStatus.READY:
            try:
                item = self.revisions.record_item_state(
                    mission_id=mission_id,
                    stable_id=stable_item_id,
                    target=BacklogItemStatus.RUNNING,
                    actor=mission.mission_owner,
                    command_id=f"{command_id}:item-running",
                    expected_sequence=item.sequence,
                    reason="Reserve ready item for deterministic Temporal child",
                    attempt_count=item.attempt_count + 1,
                )
            except ValueError:
                concurrent = self.revisions.item(revision.id, stable_item_id)
                if concurrent.status is not BacklogItemStatus.RUNNING:
                    raise
                item = concurrent
        if item.status is not BacklogItemStatus.RUNNING:
            raise ValueError(
                f"Backlog item {stable_item_id} is not ready or running"
            )
        logical_attempt = item.attempt_count
        child_workflow_id = autonomous_child_workflow_id(
            mission_id,
            revision.id,
            mission.active_execution_epoch_id,
            stable_item_id,
            logical_attempt,
        )
        job_id = child_workflow_id.removeprefix("agentfactory-")
        item_row = self.storage.db.execute(
            "SELECT item_digest FROM autonomous_backlog_items WHERE id=?",
            (item.item_id,),
        ).fetchone()
        if not item_row:
            raise RuntimeError("Active backlog item disappeared")
        approval_row = self.storage.db.execute(
            """SELECT authorization.id AS authorization_id
                 FROM autonomous_local_authorizations authorization
                 LEFT JOIN autonomous_authorization_revocations revoked
                   ON revoked.authorization_id=authorization.id
                WHERE authorization.mission_id=?
                  AND authorization.backlog_revision_id=?
                  AND authorization.execution_epoch_id=?
                  AND revoked.id IS NULL
                ORDER BY authorization.id DESC LIMIT 1""",
            (
                mission_id,
                revision.id,
                mission.active_execution_epoch_id,
            ),
        ).fetchone()
        if not approval_row:
            raise PermissionError("Active mission scope has no approval authorization")
        authorization_id = int(approval_row["authorization_id"])
        request_document = {
            "type": "prepare_autonomous_child_job",
            "mission_id": mission_id,
            "backlog_revision_id": revision.id,
            "backlog_revision_digest": revision.revision_digest,
            "execution_epoch_id": mission.active_execution_epoch_id,
            "authorization_id": authorization_id,
            "backlog_item_id": item.item_id,
            "stable_item_id": stable_item_id,
            "item_digest": str(item_row["item_digest"]),
            "logical_attempt": logical_attempt,
            "control_fencing_token": selected_fencing_token,
            "child_workflow_id": child_workflow_id,
            "workflow_definition_id": workflow_definition_id,
            "execution_mode": execution_mode,
            "prepared_by": mission.mission_owner,
        }
        request_digest = self._digest(request_document)
        existing = self.storage.db.execute(
            "SELECT * FROM autonomous_child_jobs WHERE command_id=?",
            (command_id,),
        ).fetchone()
        if existing:
            if existing["request_digest"] != request_digest:
                raise ValueError("Child preparation command is already bound")
            return self._job_from_row(existing)
        scoped = self.storage.db.execute(
            """SELECT * FROM autonomous_child_jobs
                WHERE mission_id=? AND backlog_revision_id=?
                  AND execution_epoch_id=? AND stable_item_id=?
                  AND logical_attempt=?""",
            (
                mission_id,
                revision.id,
                mission.active_execution_epoch_id,
                stable_item_id,
                logical_attempt,
            ),
        ).fetchone()
        if scoped:
            if scoped["request_digest"] != request_digest:
                raise ValueError("Logical child attempt has conflicting scope")
            return self._job_from_row(scoped)

        work_item = WorkItem(
            title=item.item.title,
            description=item.item.description,
            project_id=mission.project_id,
            inputs={
                "autonomous_mission_id": mission_id,
                "autonomous_revision_id": revision.id,
                "autonomous_epoch_id": mission.active_execution_epoch_id,
                "autonomous_stable_item_id": stable_item_id,
                "logical_attempt": logical_attempt,
                "control_fencing_token": selected_fencing_token,
            },
            expected_outputs=list(item.item.expected_artifacts),
            acceptance_criteria=list(item.item.acceptance_criteria),
            permissions=["read_project", "create_artifact"],
            budget=Budget(max_tokens=8_000, max_seconds=600, max_cost_usd=0.0),
            status=Status.RUNNING,
            kind=item.item.kind,
        )
        self.storage._assert_dispatch_allowed()
        created_at = self._timestamp()
        with self.storage.db:
            self.storage._begin_immediate()
            existing = self.storage.db.execute(
                "SELECT * FROM autonomous_child_jobs WHERE command_id=?",
                (command_id,),
            ).fetchone()
            if existing:
                if existing["request_digest"] != request_digest:
                    raise ValueError("Child preparation command is already bound")
                return self._job_from_row(existing)
            task_document = work_item.to_dict()
            task_cursor = self.storage.db.execute(
                """INSERT INTO work_items(
                       identity,project_id,title,description,payload,status,kind,
                       dependencies_json,inputs_json,expected_outputs_json,
                       acceptance_criteria_json,permissions_json,budget_max_tokens,
                       budget_max_seconds,budget_max_cost_usd,artifact_ids_json,
                       github_number,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                (
                    self.storage._identity("work-item"),
                    work_item.project_id,
                    work_item.title,
                    work_item.description,
                    self._json(task_document),
                    work_item.status.value,
                    work_item.kind,
                    "[]",
                    self._json(work_item.inputs),
                    self._json(work_item.expected_outputs),
                    self._json(work_item.acceptance_criteria),
                    self._json(work_item.permissions),
                    work_item.budget.max_tokens,
                    work_item.budget.max_seconds,
                    work_item.budget.max_cost_usd,
                    "[]",
                    None,
                ),
            )
            task_id = int(task_cursor.lastrowid)
            task_document["id"] = task_id
            self.storage._event(
                "task.created", "task", task_id, task_document
            )
            run_cursor = self.storage.db.execute(
                """INSERT INTO workflow_runs(
                       identity,project_id,task_id,workflow_id,status
                   ) VALUES(?,?,?,?, 'running')""",
                (
                    self.storage._identity("run"),
                    mission.project_id,
                    task_id,
                    workflow_definition_id,
                ),
            )
            run_id = int(run_cursor.lastrowid)
            self.storage.db.execute(
                """INSERT INTO workflow_stages(identity,run_id,stage_key,status)
                   VALUES(?,?,?,'running')""",
                (self.storage._identity("stage"), run_id, "workflow"),
            )
            self.storage.db.execute(
                """INSERT INTO active_workflow_claims(task_id,workflow_id,run_id)
                   VALUES(?,?,?)""",
                (task_id, workflow_definition_id, run_id),
            )
            self.storage._event(
                "workflow.started",
                "run",
                run_id,
                {
                    "workflow": workflow_definition_id,
                    "autonomous_mission_id": mission_id,
                    "stable_item_id": stable_item_id,
                },
            )
            context = {
                **request_document,
                "job_id": job_id,
                "task_id": task_id,
                "run_id": run_id,
                "project_id": mission.project_id,
                "repository_path": mission.configuration.repository_path,
                "control_fencing_token": selected_fencing_token,
            }
            context_digest = self._digest(context)
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_child_jobs(
                       identity,mission_id,backlog_revision_id,
                       backlog_revision_digest,execution_epoch_id,
                       authorization_id,backlog_item_id,stable_item_id,item_digest,
                       logical_attempt,control_fencing_token,task_id,run_id,child_workflow_id,
                       workflow_definition_id,execution_mode,context_json,
                       context_digest,prepared_by,command_id,request_digest,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-child-job"),
                    mission_id,
                    revision.id,
                    revision.revision_digest,
                    mission.active_execution_epoch_id,
                    authorization_id,
                    item.item_id,
                    stable_item_id,
                    item_row["item_digest"],
                    logical_attempt,
                    selected_fencing_token,
                    task_id,
                    run_id,
                    child_workflow_id,
                    workflow_definition_id,
                    execution_mode,
                    self._json(context),
                    context_digest,
                    mission.mission_owner,
                    command_id,
                    request_digest,
                    created_at,
                ),
            )
            child_job_id = int(cursor.lastrowid)
            self.storage._event(
                "autonomous_child.prepared",
                "autonomous_child_job",
                child_job_id,
                {
                    "mission_id": mission_id,
                    "task_id": task_id,
                    "run_id": run_id,
                    "stable_item_id": stable_item_id,
                    "logical_attempt": logical_attempt,
                    "child_workflow_id": child_workflow_id,
                },
            )
        return self.get_job(child_job_id)

    def authorize_job(
        self,
        child_job_id: int,
        *,
        command_id: str,
    ) -> AutonomousChildAuthorization:
        command_id = self._required(command_id, "Child authorization command id")
        existing = self.storage.db.execute(
            "SELECT * FROM autonomous_child_job_authorizations WHERE child_job_id=?",
            (child_job_id,),
        ).fetchone()
        if existing:
            if existing["command_id"] != command_id:
                raise ValueError("Child job already has another authorization command")
            return self._authorization_from_row(existing)
        job = self.get_job(child_job_id)
        mission = self.missions.get(job.mission_id)
        authorization = self.authorizations.get_authorization(job.authorization_id)
        item = self.revisions.item(job.backlog_revision_id, job.stable_item_id)
        role = item.item.assigned_role
        role_models = authorization.role_model_manifest.get("role_models", {})
        model = role_models.get(role)
        if not model:
            raise PermissionError(
                f"Approved role/model manifest omits child role {role!r}"
            )
        provider_id = authorization.provider_ids[0]
        decision = self.authorizations.resolve(
            AutonomousAuthorizationRequest(
                mission_id=job.mission_id,
                operation=AuthorizationOperation.LOCAL_INFERENCE,
                provider_id=provider_id,
                agent_id=f"autonomous-child-{job.stable_item_id}",
                task_id=job.task_id,
                role=role,
                model=str(model),
                backlog_revision_id=job.backlog_revision_id,
                backlog_revision_digest=job.backlog_revision_digest,
                execution_epoch_id=job.execution_epoch_id,
                repository_path=authorization.repository_path,
                epoch_branch=authorization.epoch_branch,
                tool_profile=authorization.tool_profile,
                permissions=("execute_provider",),
                authorization_id=authorization.id,
            )
        )
        if decision.outcome is not AuthorizationOutcome.ALLOW_AUTONOMOUS:
            raise PermissionError(
                "Autonomous child inference authority was denied: "
                + decision.reason
            )
        created_at = self._timestamp()
        with self.storage.db:
            row = self.storage.db.execute(
                "SELECT * FROM autonomous_child_job_authorizations WHERE child_job_id=?",
                (child_job_id,),
            ).fetchone()
            if row:
                if row["command_id"] != command_id:
                    raise ValueError(
                        "Child job already has another authorization command"
                    )
                return self._authorization_from_row(row)
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_child_job_authorizations(
                       identity,child_job_id,mission_id,authorization_id,
                       decision_id,decision_digest,provider_id,role,model,
                       command_id,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-child-authorization"),
                    job.id,
                    job.mission_id,
                    authorization.id,
                    decision.id,
                    decision.decision_digest,
                    provider_id,
                    role,
                    model,
                    command_id,
                    created_at,
                ),
            )
            record_id = int(cursor.lastrowid)
            self.storage._event(
                "autonomous_child.authorized",
                "autonomous_child_job",
                job.id,
                {
                    "mission_id": job.mission_id,
                    "task_id": job.task_id,
                    "run_id": job.run_id,
                    "authorization_decision_id": decision.id,
                    "provider_id": provider_id,
                    "role": role,
                    "model": model,
                },
            )
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_child_job_authorizations WHERE id=?",
            (record_id,),
        ).fetchone()
        return self._authorization_from_row(row)

    @staticmethod
    def _authorization_from_row(row: Any) -> AutonomousChildAuthorization:
        return AutonomousChildAuthorization(
            id=int(row["id"]),
            child_job_id=int(row["child_job_id"]),
            mission_id=int(row["mission_id"]),
            authorization_id=int(row["authorization_id"]),
            decision_id=int(row["decision_id"]),
            decision_digest=str(row["decision_digest"]),
            provider_id=str(row["provider_id"]),
            role=str(row["role"]),
            model=str(row["model"]),
            command_id=str(row["command_id"]),
            created_at=str(row["created_at"]),
        )

    def _completion_from_row(self, row: Any) -> AutonomousChildCompletion:
        stage_evidence = tuple(json.loads(row["stage_evidence_json"]))
        validation = json.loads(row["validation_evidence_json"])
        review = json.loads(row["review_evidence_json"])
        integration = json.loads(row["integration_evidence_json"])
        values = (
            (stage_evidence, row["stage_evidence_digest"], "stage"),
            (validation, row["validation_evidence_digest"], "validation"),
            (review, row["review_evidence_digest"], "review"),
            (integration, row["integration_evidence_digest"], "integration"),
        )
        for value, digest, label in values:
            if self._digest(value) != digest:
                raise RuntimeError(f"Autonomous child {label} evidence is corrupt")
        binding = {
            "child_job_id": int(row["child_job_id"]),
            "mission_id": int(row["mission_id"]),
            "run_id": int(row["run_id"]),
            "authorization_decision_id": int(row["authorization_decision_id"]),
            "stage_evidence_digest": str(row["stage_evidence_digest"]),
            "validation_evidence_digest": str(row["validation_evidence_digest"]),
            "review_evidence_digest": str(row["review_evidence_digest"]),
            "integration_evidence_digest": str(row["integration_evidence_digest"]),
            "git_commit_sha": str(row["git_commit_sha"]),
        }
        if self._digest(binding) != row["completion_digest"]:
            raise RuntimeError("Autonomous child completion digest is corrupt")
        return AutonomousChildCompletion(
            id=int(row["id"]),
            child_job_id=int(row["child_job_id"]),
            mission_id=int(row["mission_id"]),
            run_id=int(row["run_id"]),
            authorization_decision_id=int(row["authorization_decision_id"]),
            stage_evidence=stage_evidence,
            stage_evidence_digest=str(row["stage_evidence_digest"]),
            validation_evidence=validation,
            validation_evidence_digest=str(row["validation_evidence_digest"]),
            review_evidence=review,
            review_evidence_digest=str(row["review_evidence_digest"]),
            integration_evidence=integration,
            integration_evidence_digest=str(row["integration_evidence_digest"]),
            git_commit_sha=str(row["git_commit_sha"]),
            completion_digest=str(row["completion_digest"]),
            command_id=str(row["command_id"]),
            created_at=str(row["created_at"]),
        )

    def get_completion(self, completion_id: int) -> AutonomousChildCompletion:
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_child_delivery_completions WHERE id=?",
            (completion_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown autonomous child completion: {completion_id}")
        return self._completion_from_row(row)

    def completion_for_job(
        self, child_job_id: int
    ) -> AutonomousChildCompletion | None:
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_child_delivery_completions WHERE child_job_id=?",
            (child_job_id,),
        ).fetchone()
        return self._completion_from_row(row) if row else None

    def _converge_child_transport(self, job: AutonomousChildJob) -> None:
        run = self.storage.db.execute(
            "SELECT status FROM workflow_runs WHERE id=?", (job.run_id,)
        ).fetchone()
        if not run:
            raise RuntimeError("Autonomous child workflow run disappeared")
        status = str(run["status"])
        if status == "running":
            self.storage.finish_run(
                job.run_id,
                "awaiting_approval",
                event_payload={
                    "autonomous_child_job_id": job.id,
                    "per_item_founder_gate": False,
                },
            )
            status = "awaiting_approval"
        if status == "awaiting_approval":
            self.storage.finish_run(
                job.run_id,
                "approved",
                event_payload={
                    "autonomous_child_job_id": job.id,
                    "authority": "persisted_autonomous_completion",
                },
            )
        task = self.storage.get_task(job.task_id)
        if task.status is Status.PENDING:
            self.storage.transition_task(job.task_id, Status.RUNNING.value)
            task = self.storage.get_task(job.task_id)
        if task.status is Status.RUNNING:
            self.storage.transition_task(job.task_id, Status.COMPLETED.value)

    def complete_job(
        self,
        child_job_id: int,
        *,
        command_id: str,
        expected_fencing_token: int | None = None,
    ) -> AutonomousChildCompletion:
        command_id = self._required(command_id, "Child completion command id")
        job = self.get_job(child_job_id)
        existing = self.completion_for_job(child_job_id)
        if existing:
            if existing.command_id != command_id:
                raise ValueError("Child job already has another completion command")
            self._converge_child_transport(job)
            return existing
        authorized = self.storage.db.execute(
            "SELECT * FROM autonomous_child_job_authorizations WHERE child_job_id=?",
            (child_job_id,),
        ).fetchone()
        if not authorized:
            raise PermissionError("Autonomous child job has no persisted authorization")
        mission = self.missions.get(job.mission_id)
        selected_fencing_token = (
            job.control_fencing_token
            if expected_fencing_token is None
            else int(expected_fencing_token)
        )
        MissionControlFenceService(self.storage).assert_allows(
            job.mission_id,
            expected_fencing_token=selected_fencing_token,
            execution_epoch_id=job.execution_epoch_id,
        )
        authorization = self.authorizations.get_authorization(job.authorization_id)
        if (
            mission.phase is not MissionPhase.DEVELOPMENT
            or mission.disposition is not MissionDisposition.RUNNING
            or mission.active_backlog_revision_id != job.backlog_revision_id
            or mission.active_execution_epoch_id != job.execution_epoch_id
            or authorization.revoked
            or self._digest(
                self.authorizations._policy_snapshot(authorization.provider_ids)
            )
            != authorization.policy_digest
        ):
            raise PermissionError(
                "Autonomous authority changed before child completion"
            )
        mutations = self.storage.db.execute(
            """SELECT id,idempotency_key,result_json FROM workflow_mutations
                WHERE run_id=? AND operation='provider_call' ORDER BY id""",
            (job.run_id,),
        ).fetchall()
        if not mutations:
            raise ValueError("Autonomous child has no provider-stage evidence")
        mutation_results: list[tuple[Any, dict[str, Any]]] = []
        for row in mutations:
            if row["result_json"] is None:
                raise ValueError("Autonomous child stage evidence is incomplete")
            mutation_results.append((row, json.loads(row["result_json"])))
        required_stages = (
            "policy-precheck",
            "implementation",
            "validation",
            "policy-postcheck",
        )
        terminal_mutations: dict[str, tuple[Any, dict[str, Any]]] = {}
        for row, result in mutation_results:
            key = str(row["idempotency_key"])
            for stage in required_stages:
                if key.endswith(f":{stage}") or f":{stage}:repair:" in key:
                    terminal_mutations[stage] = (row, result)
                    break
        if set(terminal_mutations) != set(required_stages) or any(
            result.get("success") is not True
            or result.get("passed") is not True
            for _row, result in terminal_mutations.values()
        ):
            raise ValueError(
                "Autonomous child terminal stage evidence is incomplete or failed"
            )
        artifacts = self.storage.db.execute(
            "SELECT * FROM artifacts WHERE run_id=? ORDER BY id", (job.run_id,)
        ).fetchall()
        terminal_artifacts: dict[str, Any] = {}
        for row in artifacts:
            base_stage = str(row["stage"]).split(":repair:", 1)[0]
            if base_stage in required_stages:
                terminal_artifacts[base_stage] = row
        if set(terminal_artifacts) != set(required_stages):
            raise ValueError(
                "Autonomous child lacks implementation/validation/review evidence"
            )
        stage_evidence = tuple(
            {
                "artifact_id": int(row["id"]),
                "stage": stage,
                "attempt_stage": str(row["stage"]),
                "agent_id": str(row["agent_id"]),
                "provider": str(row["provider"]),
                "digest": str(row["digest"]),
            }
            for stage in required_stages
            for row in (terminal_artifacts[stage],)
        )
        validation_rows = [
            value for value in stage_evidence if value["stage"] == "validation"
        ]
        review_rows = [
            value
            for value in stage_evidence
            if value["stage"] in {"validation", "policy-postcheck"}
        ]
        validation = {
            "ok": True,
            "artifacts": validation_rows,
            "all_stage_results_passed": True,
        }
        review = {
            "accepted": True,
            "artifacts": review_rows,
            "separate_review_stage": True,
        }
        repository = Path(
            mission.configuration.repository_path or ""
        ).expanduser().resolve()
        status = self._git(repository, "status", "--porcelain")
        if status:
            raise ValueError("Autonomous child integration requires a clean repository")
        commit = self._git(repository, "rev-parse", "HEAD").lower()
        branch = self._git(
            repository, "symbolic-ref", "--quiet", "--short", "HEAD"
        )
        epoch = self.checkpoints.get_epoch(job.execution_epoch_id)
        if branch != epoch.epoch_branch:
            raise ValueError("Autonomous child integration is outside epoch branch")
        baseline_commit = (
            self.checkpoints.get_checkpoint(mission.current_checkpoint_id).git_commit_sha
            if mission.current_checkpoint_id is not None
            else epoch.base_git_commit_sha
        )
        self._git(
            repository,
            "merge-base",
            "--is-ancestor",
            baseline_commit,
            commit,
        )
        if job.execution_mode == "live" and commit == baseline_commit:
            raise ValueError(
                "Live autonomous child requires an integrated commit, not only "
                "advisory provider artifacts"
            )
        integration = {
            "accepted": True,
            "repository_path": str(repository),
            "branch": branch,
            "commit_sha": commit,
            "baseline_commit_sha": baseline_commit,
            "clean_head": True,
            "simulation": job.execution_mode == "simulation",
            "child_workflow_id": job.child_workflow_id,
        }
        stage_digest = self._digest(stage_evidence)
        validation_digest = self._digest(validation)
        review_digest = self._digest(review)
        integration_digest = self._digest(integration)
        binding = {
            "child_job_id": job.id,
            "mission_id": job.mission_id,
            "run_id": job.run_id,
            "authorization_decision_id": int(authorized["decision_id"]),
            "stage_evidence_digest": stage_digest,
            "validation_evidence_digest": validation_digest,
            "review_evidence_digest": review_digest,
            "integration_evidence_digest": integration_digest,
            "git_commit_sha": commit,
        }
        completion_digest = self._digest(binding)
        created_at = self._timestamp()
        with self.storage.db:
            current_scope = self.storage.db.execute(
                """SELECT mission.disposition,mission.active_execution_epoch_id,
                          fence.fencing_token,fence.disposition AS fence_disposition
                     FROM autonomous_missions mission
                     JOIN autonomous_mission_control_fences fence
                       ON fence.mission_id=mission.id
                    WHERE mission.id=?""",
                (job.mission_id,),
            ).fetchone()
            if (
                not current_scope
                or current_scope["disposition"]
                != MissionDisposition.RUNNING.value
                or current_scope["fence_disposition"]
                != MissionDisposition.RUNNING.value
                or int(current_scope["fencing_token"])
                != selected_fencing_token
                or int(current_scope["active_execution_epoch_id"])
                != job.execution_epoch_id
            ):
                raise PermissionError(
                    "Mission control fence changed before child completion commit"
                )
            row = self.storage.db.execute(
                "SELECT * FROM autonomous_child_delivery_completions WHERE child_job_id=?",
                (child_job_id,),
            ).fetchone()
            if row:
                if row["command_id"] != command_id:
                    raise ValueError(
                        "Child job already has another completion command"
                    )
                completion = self._completion_from_row(row)
            else:
                cursor = self.storage.db.execute(
                    """INSERT INTO autonomous_child_delivery_completions(
                           identity,child_job_id,mission_id,run_id,
                           authorization_decision_id,stage_evidence_json,
                           stage_evidence_digest,validation_evidence_json,
                           validation_evidence_digest,review_evidence_json,
                           review_evidence_digest,integration_evidence_json,
                           integration_evidence_digest,git_commit_sha,
                           completion_digest,command_id,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        self.storage._identity("autonomous-child-completion"),
                        job.id,
                        job.mission_id,
                        job.run_id,
                        authorized["decision_id"],
                        self._json(stage_evidence),
                        stage_digest,
                        self._json(validation),
                        validation_digest,
                        self._json(review),
                        review_digest,
                        self._json(integration),
                        integration_digest,
                        commit,
                        completion_digest,
                        command_id,
                        created_at,
                    ),
                )
                completion = self.get_completion(int(cursor.lastrowid))
                self.storage._event(
                    "autonomous_child.completed",
                    "autonomous_child_job",
                    job.id,
                    {
                        "mission_id": job.mission_id,
                        "task_id": job.task_id,
                        "run_id": job.run_id,
                        "completion_id": completion.id,
                        "completion_digest": completion.completion_digest,
                        "git_commit_sha": commit,
                        "per_item_founder_gate": False,
                    },
                )
        self._converge_child_transport(job)
        return completion

    def _reconciliation_from_row(
        self, row: Any
    ) -> AutonomousChildReconciliation:
        binding = {
            "child_job_id": int(row["child_job_id"]),
            "completion_id": int(row["completion_id"]),
            "mission_id": int(row["mission_id"]),
            "backlog_item_state_id": int(row["backlog_item_state_id"]),
            "checkpoint_id": int(row["checkpoint_id"]),
            "result_mission_version": int(row["result_mission_version"]),
        }
        if self._digest(binding) != row["reconciliation_digest"]:
            raise RuntimeError("Autonomous child reconciliation digest is corrupt")
        return AutonomousChildReconciliation(
            id=int(row["id"]),
            child_job_id=int(row["child_job_id"]),
            completion_id=int(row["completion_id"]),
            mission_id=int(row["mission_id"]),
            backlog_item_state_id=int(row["backlog_item_state_id"]),
            checkpoint_id=int(row["checkpoint_id"]),
            result_mission_version=int(row["result_mission_version"]),
            reconciliation_digest=str(row["reconciliation_digest"]),
            command_id=str(row["command_id"]),
            created_at=str(row["created_at"]),
        )

    def reconciliation_for_job(
        self, child_job_id: int
    ) -> AutonomousChildReconciliation | None:
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_child_reconciliations WHERE child_job_id=?",
            (child_job_id,),
        ).fetchone()
        return self._reconciliation_from_row(row) if row else None

    def reconcile_job(
        self,
        child_job_id: int,
        *,
        expected_mission_version: int,
        command_id: str,
    ) -> AutonomousChildReconciliation:
        command_id = self._required(command_id, "Child reconciliation command id")
        existing = self.reconciliation_for_job(child_job_id)
        if existing:
            if existing.command_id != command_id:
                raise ValueError("Child job already has another reconciliation command")
            return existing
        job = self.get_job(child_job_id)
        completion = self.completion_for_job(child_job_id)
        if completion is None:
            raise PermissionError("Child result has no persisted accepted completion")
        mission = self.missions.get(
            job.mission_id, version=expected_mission_version
        )
        item = self.revisions.item(job.backlog_revision_id, job.stable_item_id)
        if item.status is not BacklogItemStatus.DONE:
            try:
                item = self.revisions.record_item_state(
                    mission_id=job.mission_id,
                    stable_id=job.stable_item_id,
                    target=BacklogItemStatus.DONE,
                    actor=mission.mission_owner,
                    command_id=f"{command_id}:item-done",
                    expected_sequence=item.sequence,
                    reason=(
                        "Accept persisted validation, review, and integration evidence"
                    ),
                    validation_result={
                        "ok": True,
                        "completion_id": completion.id,
                        "validation_evidence_digest": (
                            completion.validation_evidence_digest
                        ),
                        "review_evidence_digest": (
                            completion.review_evidence_digest
                        ),
                        "integration_evidence_digest": (
                            completion.integration_evidence_digest
                        ),
                    },
                    git_commit_sha=completion.git_commit_sha,
                    evidence=(
                        {
                            "kind": "autonomous_child_completion",
                            "id": completion.id,
                            "digest": completion.completion_digest,
                        },
                        {
                            "kind": "validation",
                            "digest": completion.validation_evidence_digest,
                        },
                        {
                            "kind": "review",
                            "digest": completion.review_evidence_digest,
                        },
                        {
                            "kind": "integration",
                            "digest": completion.integration_evidence_digest,
                        },
                    ),
                    attempt_count=job.logical_attempt,
                )
            except ValueError:
                concurrent = self.revisions.item(
                    job.backlog_revision_id, job.stable_item_id
                )
                if concurrent.status is not BacklogItemStatus.DONE:
                    raise
                item = concurrent
        state_row = self.storage.db.execute(
            """SELECT state.id FROM autonomous_backlog_item_states state
                 JOIN autonomous_backlog_items item ON item.id=state.item_id
                WHERE item.id=? AND state.status='DONE'
                ORDER BY state.sequence DESC LIMIT 1""",
            (job.backlog_item_id,),
        ).fetchone()
        if not state_row:
            raise RuntimeError("Accepted backlog item state is missing")
        projections = tuple(
            projection
            for projection in self.revisions.active_items(job.mission_id)
            if projection.item.executable
        )
        completed_items = tuple(
            sorted(
                projection.item.stable_id
                for projection in projections
                if projection.status is BacklogItemStatus.DONE
            )
        )
        pending_items = tuple(
            sorted(
                projection.item.stable_id
                for projection in projections
                if projection.status is not BacklogItemStatus.DONE
            )
        )
        epoch = self.checkpoints.get_epoch(job.execution_epoch_id)
        checkpoint = self.checkpoints.record_checkpoint(
            job.mission_id,
            expected_mission_version=expected_mission_version,
            expected_backlog_revision_id=job.backlog_revision_id,
            expected_execution_epoch_id=job.execution_epoch_id,
            actor=mission.mission_owner,
            command_id=f"{command_id}:checkpoint",
            reason=f"Accepted autonomous child {job.stable_item_id}",
            checkpoint_type=MissionCheckpointType.WORK_ITEM_ACCEPTED,
            git_commit_sha=completion.git_commit_sha,
            git_branch=epoch.epoch_branch,
            git_worktree_path=str(
                Path(mission.configuration.repository_path or "").resolve()
            ),
            completed_work_items=completed_items,
            pending_work_items=pending_items,
            artifacts=(
                {
                    "kind": "autonomous_child_completion",
                    "id": completion.id,
                    "digest": completion.completion_digest,
                },
            ),
            validation_state={
                "ok": True,
                "child_job_id": job.id,
                "completion_id": completion.id,
                "validation_digest": completion.validation_evidence_digest,
                "review_digest": completion.review_evidence_digest,
                "integration_digest": completion.integration_evidence_digest,
            },
        )
        result_mission_version = int(
            checkpoint.document["mission"]["version_before_checkpoint"]
        ) + 1
        binding = {
            "child_job_id": job.id,
            "completion_id": completion.id,
            "mission_id": job.mission_id,
            "backlog_item_state_id": int(state_row["id"]),
            "checkpoint_id": checkpoint.id,
            "result_mission_version": result_mission_version,
        }
        reconciliation_digest = self._digest(binding)
        created_at = self._timestamp()
        with self.storage.db:
            row = self.storage.db.execute(
                "SELECT * FROM autonomous_child_reconciliations WHERE child_job_id=?",
                (child_job_id,),
            ).fetchone()
            if row:
                if row["command_id"] != command_id:
                    raise ValueError(
                        "Child job already has another reconciliation command"
                    )
                return self._reconciliation_from_row(row)
            cursor = self.storage.db.execute(
                """INSERT INTO autonomous_child_reconciliations(
                       identity,child_job_id,completion_id,mission_id,
                       backlog_item_state_id,checkpoint_id,result_mission_version,
                       reconciliation_digest,command_id,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("autonomous-child-reconciliation"),
                    job.id,
                    completion.id,
                    job.mission_id,
                    state_row["id"],
                    checkpoint.id,
                    result_mission_version,
                    reconciliation_digest,
                    command_id,
                    created_at,
                ),
            )
            reconciliation_id = int(cursor.lastrowid)
            self.storage._event(
                "autonomous_child.reconciled",
                "autonomous_child_job",
                job.id,
                {
                    "mission_id": job.mission_id,
                    "task_id": job.task_id,
                    "run_id": job.run_id,
                    "stable_item_id": job.stable_item_id,
                    "completion_id": completion.id,
                    "checkpoint_id": checkpoint.id,
                    "mission_version": result_mission_version,
                },
            )
        row = self.storage.db.execute(
            "SELECT * FROM autonomous_child_reconciliations WHERE id=?",
            (reconciliation_id,),
        ).fetchone()
        return self._reconciliation_from_row(row)

    def complete_mission(
        self,
        mission_id: int,
        *,
        expected_mission_version: int,
        command_id: str,
    ):
        command_id = self._required(command_id, "Mission completion command id")
        progress = self.revisions.progress(mission_id)
        if progress["total"] == 0 or progress["completed"] != progress["total"]:
            raise PermissionError("Mission backlog is not completely accepted")
        historical = self.missions.get(
            mission_id, version=expected_mission_version
        )
        if historical.phase is not MissionPhase.DEVELOPMENT:
            raise PermissionError("Mission completion requires DEVELOPMENT phase")
        first = self.missions.transition_phase(
            mission_id,
            MissionPhase.FINAL_VALIDATION,
            actor=historical.mission_owner,
            command_id=f"{command_id}:final-validation",
            expected_version=expected_mission_version,
            reason="All active revision work items have accepted checkpoints",
        )
        self.missions.transition_phase(
            mission_id,
            MissionPhase.COMPLETED,
            actor=historical.mission_owner,
            command_id=f"{command_id}:completed",
            expected_version=first.version,
            reason="Autonomous mission active revision is complete",
        )
        return self.missions.get(mission_id, version=first.version + 1)

    # These two implementation helpers keep the established standard-delivery
    # behavior byte-for-byte separate from the opt-in autonomous finalization.
    def _standard_process_impl(
        self,
        delivery_id: int,
        codex_result_id: int,
        *,
        reviewer: Agent,
        rubric_id: str,
        rubric_version: str,
        review: ReviewFunction,
        replacement_selector: ReplacementSelector | None = None,
    ) -> DeliveryState:
        delivery = self.storage.db.execute(
            "SELECT * FROM coding_delivery_runs WHERE id=?", (delivery_id,)
        ).fetchone()
        if not delivery:
            raise KeyError(f"Unknown coding delivery: {delivery_id}")
        existing = self.storage.db.execute(
            "SELECT id FROM coding_delivery_iterations WHERE codex_result_id=?",
            (codex_result_id,),
        ).fetchone()
        if existing or delivery["status"] != "active":
            return self.state(delivery_id)
        result = self.storage.db.execute(
            """SELECT w.*,a.agent_id FROM codex_worker_results w
                 JOIN assignments a ON a.id=w.assignment_id WHERE w.id=?""",
            (codex_result_id,),
        ).fetchone()
        if not result or int(result["task_id"]) != int(delivery["task_id"]):
            raise PermissionError("Implementation result belongs to another delivery task")
        rows = self.storage.db.execute(
            """SELECT * FROM validator_results
                WHERE task_id=? AND attempt_id=? AND candidate_digest=? ORDER BY category""",
            (result["task_id"], result["attempt_id"], result["diff_digest"]),
        ).fetchall()
        snapshot = self._snapshot(rows)
        complete = len(rows) == len(VALIDATOR_CATEGORIES) and {
            str(row["category"]) for row in rows
        } == set(VALIDATOR_CATEGORIES)
        passed = complete and all(row["status"] == "succeeded" for row in rows)
        number = int(self.storage.db.execute(
            "SELECT COUNT(*) FROM coding_delivery_iterations WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()[0]) + 1
        failure: dict[str, object] | None = None
        candidate_id = evaluation_id = None
        if not passed:
            failure = {
                "kind": "validation", "complete": complete,
                "failed_categories": [row["category"] for row in rows if row["status"] != "succeeded"],
            }
        else:
            candidate = self.candidates.create(
                codex_result_id, stable_task_id=str(delivery["stable_task_id"])
            )
            candidate_id = candidate.id
            evaluation = self.evaluations.evaluate(
                candidate.id, reviewer=reviewer, rubric_id=rubric_id,
                rubric_version=rubric_version, review=review,
            )
            evaluation_id = evaluation.id
            if not evaluation.accepted:
                failure = {
                    "kind": "review", "evaluation_id": evaluation.id,
                    "failed_criteria": [item.criterion for item in evaluation.verdicts if item.verdict == "fail"],
                }

        handoff = json.loads(result["handoff_json"])
        if failure is None:
            self.loops.record_iteration(
                int(delivery["engineering_loop_id"]),
                plan={"worker": result["agent_id"], "handoff": handoff},
                diff_digest=str(result["diff_digest"]), validator_results=snapshot,
                critic_result={"verdict": "pass", "evaluation_id": evaluation_id},
                usage=IterationUsage(), accept=True, accepted_evidence=True,
            )
            founder_gate_id = self.storage.create_approval_gate(int(delivery["run_id"]))
            outcome, status, selected = "awaiting_founder", "awaiting_founder", None
        else:
            signature = hashlib.sha256(
                json.dumps(failure, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            selected = str(delivery["current_worker_id"])
            if replacement_selector:
                replacement = replacement_selector(selected, failure)
                if replacement and replacement.strip():
                    selected = replacement.strip()
            loop_result = self.loops.record_iteration(
                int(delivery["engineering_loop_id"]),
                plan={"worker": result["agent_id"], "handoff": handoff},
                diff_digest=str(result["diff_digest"]), validator_results=snapshot or [{"status": "missing"}],
                critic_result={"verdict": "repair", "failure": failure},
                usage=IterationUsage(tool_failures=int(not passed)), failure=failure,
            )
            repairs = int(delivery["repair_iterations"]) + 1
            exhausted = repairs >= int(delivery["max_repair_iterations"])
            outcome = "repair_exhausted" if exhausted else (
                "validation_failed" if not passed else "review_rejected"
            )
            status = "failed" if exhausted else "active"
            founder_gate_id = None
        if failure is None:
            repairs = int(delivery["repair_iterations"])

        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO coding_delivery_iterations(
                       identity,delivery_id,iteration_number,codex_result_id,
                       assignment_id,worktree_id,worker_id,validator_snapshot_json,
                       candidate_id,evaluation_id,outcome,selected_repair_worker_id,
                       failure_signature
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("coding-delivery-iteration"), delivery_id,
                    number, codex_result_id, result["assignment_id"], result["worktree_id"],
                    result["agent_id"], json.dumps(snapshot, sort_keys=True),
                    candidate_id, evaluation_id, outcome, selected,
                    hashlib.sha256(json.dumps(failure, sort_keys=True).encode()).hexdigest()
                    if failure else None,
                ),
            )
            iteration_id = int(cursor.lastrowid)
            self.storage.db.execute(
                """UPDATE coding_delivery_runs
                      SET status=?,repair_iterations=?,current_worker_id=?,
                          last_failure_signature=?,candidate_id=?,evaluation_id=?,
                          founder_gate_id=?,terminal_reason=?,updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='active'""",
                (
                    status, repairs, selected or delivery["current_worker_id"],
                    signature if failure else None, candidate_id, evaluation_id,
                    founder_gate_id, "maximum repair iterations reached" if status == "failed" else None,
                    delivery_id,
                ),
            )
            self.storage._event(f"coding.delivery.{outcome}", "coding_delivery_iteration", iteration_id, {
                "delivery_id": delivery_id, "iteration": number,
                "worker_id": result["agent_id"], "selected_repair_worker_id": selected,
                "candidate_id": candidate_id, "evaluation_id": evaluation_id,
                "founder_gate_id": founder_gate_id,
            })
        return self.state(delivery_id)

    def _standard_founder_decide_impl(
        self,
        delivery_id: int,
        decision: str,
        *,
        actor: str,
        note: str,
        repo: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> DeliveryState:
        delivery = self.storage.db.execute(
            "SELECT * FROM coding_delivery_runs WHERE id=?", (delivery_id,)
        ).fetchone()
        if not delivery:
            raise KeyError(f"Unknown coding delivery: {delivery_id}")
        if delivery["status"] in {"pr_ready", "rejected"}:
            return self._state(delivery)
        if delivery["status"] != "awaiting_founder" or delivery["founder_gate_id"] is None:
            raise ValueError("Coding delivery is not awaiting Founder decision")
        self.storage.decide_approval(
            int(delivery["founder_gate_id"]), decision, note, actor=actor
        )
        plan_id = gate_id = None
        status = "rejected"
        if decision == "approved":
            plan_id, gate_id = self.candidates.plan_pull_request(
                int(delivery["candidate_id"]), repo=repo, base_branch=base_branch,
                title=title, body=body,
            )
            status = "pr_ready"
        with self.storage.db:
            self.storage.db.execute(
                """UPDATE coding_delivery_runs
                      SET status=?,github_plan_id=?,github_gate_id=?,terminal_reason=?,
                          updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='awaiting_founder'""",
                (
                    status, plan_id, gate_id,
                    None if status == "pr_ready" else "Founder rejected delivery",
                    delivery_id,
                ),
            )
            self.storage._event(f"coding.delivery.{status}", "coding_delivery", delivery_id, {
                "actor": actor, "founder_gate_id": delivery["founder_gate_id"],
                "github_plan_id": plan_id, "github_gate_id": gate_id,
                "external_mutation_executed": False,
            })
        return self.state(delivery_id)
