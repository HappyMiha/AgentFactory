"""Shared operator-facing application services for the CLI and local web UI."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .backlog import BacklogProposal, diff_issues, issue_operations, load_backlog
from .config import config_path, config_path_for_workspace, load_yaml
from .github import GitHubClient
from .models import Budget, ExecutionApproval, ProviderResult, WorkItem
from .registry import AgentRegistry
from .runtime import AgentRuntime, ExecutionMode
from .storage import SQLiteStorage
from .workflow import WorkflowEngine


@dataclass(frozen=True)
class ProjectView:
    id: int
    name: str
    description: str
    created_at: str


@dataclass(frozen=True)
class BudgetView:
    max_tokens: int
    max_seconds: int
    max_cost_usd: float


@dataclass(frozen=True)
class WorkItemView:
    id: int
    project_id: int
    title: str
    description: str
    kind: str
    status: str
    dependencies: tuple[int, ...]
    inputs: dict[str, Any]
    expected_outputs: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    permissions: tuple[str, ...]
    budget: BudgetView
    artifacts: tuple[int, ...]
    github_number: int | None
    created_at: str
    priority: str | None
    assignee: str | None


@dataclass(frozen=True)
class RunView:
    id: int
    project_id: int
    task_id: int
    workflow_id: str
    status: str
    created_at: str
    completed_at: str | None
    artifact_count: int
    approval_id: int | None
    approval_status: str | None


@dataclass(frozen=True)
class ArtifactView:
    id: int
    run_id: int
    stage: str
    agent_id: str
    provider: str
    content: str
    status: str
    review_note: str | None
    created_at: str


@dataclass(frozen=True)
class AgentView:
    id: str
    name: str
    role: str
    enabled: bool
    provider: str
    model: str
    instructions: str
    permissions: tuple[str, ...]
    last_claimed_task_id: int | None
    reviewer_assignment_count: int
    last_reviewed_run_id: int | None


@dataclass(frozen=True)
class ProviderView:
    id: str
    type: str
    enabled: bool
    executable: str
    execution_enabled: bool
    status: str
    healthy: bool | None
    path: str | None
    version: str | None
    error: str | None
    health_details: dict[str, Any]
    allowed_roles: tuple[str, ...]


@dataclass(frozen=True)
class ReviewView:
    id: int
    run_id: int
    stage: str
    reviewer_agent_id: str
    reviewer_provider: str
    reviewer_model: str
    reviewed_stages: tuple[str, ...]
    reviewed_artifact_ids: tuple[int, ...]
    producer_agents: tuple[dict[str, Any], ...]
    excluded_models: tuple[str, ...]
    excluded_candidates: dict[str, str]
    strategy: str
    review_artifact_id: int | None
    verdict: str | None
    created_at: str
    completed_at: str | None


@dataclass(frozen=True)
class ApprovalView:
    id: int
    kind: str
    status: str
    target_type: str
    target_id: int
    decision_note: str
    created_at: str
    decided_at: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class FounderDecisionPacket:
    approval: ApprovalView
    run: RunView
    work_item: WorkItemView
    artifacts: tuple[ArtifactView, ...]
    reviews: tuple[ReviewView, ...]
    criterion_evidence: dict[str, tuple[str, ...]]
    unresolved_findings: tuple[str, ...]


@dataclass(frozen=True)
class FounderDecisionReceipt:
    approval: ApprovalView
    idempotent: bool
    actor: str
    target: str
    previous_state: str
    resulting_state: str
    timestamp: str


@dataclass(frozen=True)
class EventView:
    id: int
    event_type: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class AuditEventView:
    id: int
    event_type: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    created_at: str
    project_id: int | None
    task_id: int | None
    run_id: int | None
    agent_id: str | None
    provider: str | None
    outcome: str
    related_artifact_ids: tuple[int, ...]


@dataclass(frozen=True)
class ConfigSourceView:
    name: str
    path: str


@dataclass(frozen=True)
class RuntimeSettingView:
    key: str
    value: int
    version: int
    minimum: int
    maximum: int
    description: str


@dataclass(frozen=True)
class SettingsView:
    workspace: str
    database: str
    execution_modes: tuple[str, ...]
    live_provider_approval_required: bool
    automatic_fallback_in_simulation: bool
    max_timeout: int
    max_output_chars: int
    config_sources: tuple[ConfigSourceView, ...]
    runtime_settings: tuple[RuntimeSettingView, ...]


@dataclass(frozen=True)
class BudgetStateView:
    correlation_root: str
    status: str
    tokens: int
    max_tokens: int
    estimated_cost_usd: float
    max_cost_usd: float
    stages_reserved: int
    max_stages: int
    retries: int
    max_retries: int
    tool_calls: int
    max_tool_calls: int
    terminal_reason: str | None


@dataclass(frozen=True)
class OperationalStateView:
    active_sessions: int
    queued_tasks: int
    active_leases: int
    active_worktrees: int
    failures: int
    budgets: tuple[BudgetStateView, ...]


@dataclass(frozen=True)
class ProjectChange:
    project_id: int
    created: bool


@dataclass(frozen=True)
class ClaimResult:
    task_id: int
    worker: str
    assignment_id: int
    lease_id: int
    fencing_token: int
    expires_at: str
    conflict_domains: tuple[str, ...]


RUNTIME_SETTING_SPECS: dict[str, tuple[int, int, int, str]] = {
    "dashboard_refresh_seconds": (
        5,
        2,
        60,
        "Seconds between live Local Control Center refreshes",
    ),
    "audit_page_size": (
        50,
        10,
        200,
        "Maximum audit records loaded per explorer refresh",
    ),
}


@dataclass(frozen=True)
class BacklogImportResult:
    created: tuple[dict[str, Any], ...]
    skipped: tuple[str, ...]
    source_sha256: str


@dataclass(frozen=True)
class BacklogFileImportResult:
    project_id: int
    project_created: bool
    source_path: str
    created: tuple[dict[str, Any], ...]
    skipped: tuple[str, ...]
    source_sha256: str


@dataclass(frozen=True)
class ProviderInvocationResult:
    ok: bool
    provider: str
    artifact_id: int
    content: str
    error: str | None
    metadata: dict[str, Any]


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def provider_snapshot_hashes(
    provider: str, agent: Any, item: WorkItem, workspace: Path | None = None
) -> tuple[str, str]:
    """Bind a provider approval to its canonical request and effective policy."""

    request = {
        "provider": provider,
        "agent": asdict(agent),
        "task": item.to_dict(),
    }
    resolver = (
        (lambda name: config_path_for_workspace(name, workspace))
        if workspace is not None
        else config_path
    )
    definitions = {
        "providers": load_yaml(resolver("providers")),
        "policy": load_yaml(resolver("policy")),
    }
    return canonical_hash(request), canonical_hash(definitions)


def _json_object(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError("Stored JSON value must be an object")
    return value


def _json_list(raw: str) -> list[Any]:
    value = json.loads(raw)
    if not isinstance(value, list):
        raise TypeError("Stored JSON value must be a list")
    return value


def _redact_health_details(value: dict[str, Any]) -> dict[str, Any]:
    sensitive = ("token", "secret", "password", "credential", "api_key")
    return {
        str(key): (
            "[REDACTED]"
            if any(fragment in str(key).casefold() for fragment in sensitive)
            else item
        )
        for key, item in value.items()
    }


def _artifact_document(content: str) -> dict[str, Any]:
    source = content.strip()
    if source.startswith("[execution_mode=") and "\n" in source:
        source = source.split("\n", 1)[1]
    try:
        value = json.loads(source)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


class AgentFactoryService:
    """Reusable query and guarded-command boundary for operator clients."""

    def __init__(
        self,
        storage: SQLiteStorage,
        registry: AgentRegistry | None = None,
        runtime: AgentRuntime | None = None,
        *,
        workspace: Path | None = None,
    ):
        self.storage = storage
        self.workspace = (workspace or storage.path.parent.parent).resolve()
        self.registry = registry or AgentRegistry(workspace=self.workspace)
        self.runtime = runtime or AgentRuntime(workspace=self.workspace)

    # Queries return immutable typed values and never depend on terminal formatting.
    def projects(self) -> list[ProjectView]:
        rows = self.storage.db.execute("SELECT * FROM projects ORDER BY id").fetchall()
        return [
            ProjectView(
                id=int(row["id"]),
                name=str(row["name"]),
                description=str(row["description"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def work_items(self, project_id: int | None = None) -> list[WorkItemView]:
        query = "SELECT id,created_at FROM work_items"
        parameters: tuple[Any, ...] = ()
        if project_id is not None:
            query += " WHERE project_id=?"
            parameters = (project_id,)
        query += " ORDER BY id"
        rows = [
            row for row in self.storage.db.execute(query, parameters).fetchall()
            if not self.storage.get_task(int(row["id"])).inputs.get("archived")
        ]
        return [
            self._work_item_view(int(row["id"]), str(row["created_at"]))
            for row in rows
        ]

    def archive_work_item(self, task_id: int, reason: str = "") -> WorkItemView:
        self.storage.archive_task(task_id, reason=reason)
        return self.work_item(task_id)

    def archive_all_work_items(self, reason: str = "") -> dict[str, Any]:
        ids = self.storage.archive_all_tasks(reason=reason)
        return {"archived": ids, "count": len(ids)}

    def work_item(self, task_id: int) -> WorkItemView:
        row = self.storage.db.execute(
            "SELECT created_at FROM work_items WHERE id=?", (task_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown task: {task_id}")
        return self._work_item_view(task_id, str(row["created_at"]))

    def _work_item_view(self, task_id: int, created_at: str) -> WorkItemView:
        item = self.storage.get_task(task_id)
        claim = self.storage.db.execute(
            """SELECT payload FROM events WHERE entity_type='task' AND entity_id=?
                 AND event_type='task.claimed' ORDER BY id DESC LIMIT 1""",
            (str(task_id),),
        ).fetchone()
        labels = item.inputs.get("labels", [])
        priority = next(
            (str(label).split(":", 1)[1] for label in labels if str(label).startswith("priority:")),
            None,
        )
        return WorkItemView(
            id=task_id,
            project_id=item.project_id,
            title=item.title,
            description=item.description,
            kind=item.kind,
            status=item.status.value,
            dependencies=tuple(item.dependencies),
            inputs=dict(item.inputs),
            expected_outputs=tuple(item.expected_outputs),
            acceptance_criteria=tuple(item.acceptance_criteria),
            permissions=tuple(item.permissions),
            budget=BudgetView(
                item.budget.max_tokens,
                item.budget.max_seconds,
                item.budget.max_cost_usd,
            ),
            artifacts=tuple(item.artifacts),
            github_number=item.github_number,
            created_at=created_at,
            priority=priority,
            assignee=(str(_json_object(claim["payload"]).get("worker")) if claim else None),
        )

    def runs(self, task_id: int | None = None) -> list[RunView]:
        query = """
            SELECT r.*, COUNT(DISTINCT a.id) AS artifact_count,
                   g.id AS approval_id, g.status AS approval_status
              FROM workflow_runs r
              LEFT JOIN artifacts a ON a.run_id=r.id
              LEFT JOIN approval_gates g ON g.run_id=r.id
        """
        parameters: tuple[Any, ...] = ()
        if task_id is not None:
            query += " WHERE r.task_id=?"
            parameters = (task_id,)
        query += " GROUP BY r.id,g.id ORDER BY r.id"
        return [self._run_view(row) for row in self.storage.db.execute(query, parameters)]

    def run(self, run_id: int) -> RunView:
        row = self.storage.db.execute(
            """
            SELECT r.*, COUNT(DISTINCT a.id) AS artifact_count,
                   g.id AS approval_id, g.status AS approval_status
              FROM workflow_runs r
              LEFT JOIN artifacts a ON a.run_id=r.id
              LEFT JOIN approval_gates g ON g.run_id=r.id
             WHERE r.id=? GROUP BY r.id,g.id
            """,
            (run_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown run: {run_id}")
        return self._run_view(row)

    @staticmethod
    def _run_view(row: Any) -> RunView:
        return RunView(
            id=int(row["id"]),
            project_id=int(row["project_id"]),
            task_id=int(row["task_id"]),
            workflow_id=str(row["workflow_id"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            completed_at=str(row["completed_at"]) if row["completed_at"] else None,
            artifact_count=int(row["artifact_count"]),
            approval_id=int(row["approval_id"]) if row["approval_id"] else None,
            approval_status=(
                str(row["approval_status"]) if row["approval_status"] else None
            ),
        )

    def artifacts(self, run_id: int | None = None, *, task_id: int | None = None) -> list[ArtifactView]:
        if run_id is not None and task_id is not None:
            raise ValueError("Filter artifacts by run_id or task_id, not both")
        query = "SELECT a.* FROM artifacts a"
        parameters: tuple[Any, ...] = ()
        if task_id is not None:
            query += " JOIN workflow_runs r ON r.id=a.run_id WHERE r.task_id=?"
            parameters = (task_id,)
        elif run_id is not None:
            query += " WHERE a.run_id=?"
            parameters = (run_id,)
        query += " ORDER BY a.id"
        return [
            ArtifactView(
                id=int(row["id"]),
                run_id=int(row["run_id"]),
                stage=str(row["stage"]),
                agent_id=str(row["agent_id"]),
                provider=str(row["provider"]),
                content=str(row["content"]),
                status=str(row["status"]),
                review_note=str(row["review_note"]) if row["review_note"] else None,
                created_at=str(row["created_at"]),
            )
            for row in self.storage.db.execute(query, parameters)
        ]

    def agents(self) -> list[AgentView]:
        claims: dict[str, int] = {}
        for row in self.storage.db.execute(
            """SELECT entity_id,payload FROM events WHERE event_type='task.claimed'
                 ORDER BY id DESC"""
        ):
            worker = str(_json_object(row["payload"]).get("worker", ""))
            if worker and worker not in claims:
                claims[worker] = int(row["entity_id"])
        return [
            AgentView(
                id=agent.id,
                name=agent.name,
                role=agent.role,
                enabled=agent.enabled,
                provider=agent.provider,
                model=agent.model_identity,
                instructions=agent.instructions,
                permissions=tuple(agent.permissions),
                last_claimed_task_id=claims.get(agent.id),
                reviewer_assignment_count=int(
                    self.storage.db.execute(
                        "SELECT COUNT(*) FROM reviewer_assignments WHERE reviewer_agent_id=?",
                        (agent.id,),
                    ).fetchone()[0]
                ),
                last_reviewed_run_id=(
                    int(review["run_id"])
                    if (
                        review := self.storage.db.execute(
                            """SELECT run_id FROM reviewer_assignments
                                 WHERE reviewer_agent_id=? ORDER BY id DESC LIMIT 1""",
                            (agent.id,),
                        ).fetchone()
                    )
                    else None
                ),
            )
            for agent in self.registry.list()
        ]

    def providers(self) -> list[ProviderView]:
        document = load_yaml(config_path_for_workspace("providers", self.workspace))
        configured = list(document.get("providers", []))
        configured.insert(
            0,
            {
                "id": "deterministic",
                "type": "builtin",
                "enabled": True,
                "executable": "",
                "allow_execution": True,
                "allowed_roles": [],
            },
        )
        try:
            health = {
                str(item.get("provider")): item for item in self.runtime.health()
            }
        except Exception as exc:  # noqa: BLE001 - A query reports runtime failure as data.
            health = {
                provider_id: {
                    "provider": provider_id,
                    "healthy": False,
                    "error": f"health query failed: {type(exc).__name__}",
                }
                for provider_id in self.runtime.providers
            }
        result: list[ProviderView] = []
        for item in configured:
            provider_id = str(item["id"])
            enabled = bool(item.get("enabled", True))
            report = health.get(provider_id)
            if not enabled:
                status = "disabled"
            elif report is None:
                status = "unavailable"
            else:
                status = "ready" if report.get("healthy") else "unhealthy"
            result.append(
                ProviderView(
                    id=provider_id,
                    type=str(item.get("type", "unknown")),
                    enabled=enabled,
                    executable=str(item.get("executable", "")),
                    execution_enabled=bool(item.get("allow_execution", False)),
                    status=status,
                    healthy=(bool(report.get("healthy")) if report is not None else None),
                    path=(str(report["path"]) if report and report.get("path") else None),
                    version=(
                        str(report["version"]) if report and report.get("version") else None
                    ),
                    error=(str(report["error"]) if report and report.get("error") else None),
                    health_details=_redact_health_details(dict(report)) if report else {},
                    allowed_roles=tuple(str(role) for role in item.get("allowed_roles", [])),
                )
            )
        return result

    def reviews(self, run_id: int | None = None, *, limit: int = 100) -> list[ReviewView]:
        if limit < 1 or limit > 10_000:
            raise ValueError("limit must be between 1 and 10000")
        rows = self.storage.reviewer_assignments(run_id)[-limit:]
        return [
            ReviewView(
                id=int(row["id"]),
                run_id=int(row["run_id"]),
                stage=str(row["stage"]),
                reviewer_agent_id=str(row["reviewer_agent_id"]),
                reviewer_provider=str(row["reviewer_provider"]),
                reviewer_model=str(row["reviewer_model"]),
                reviewed_stages=tuple(str(value) for value in _json_list(row["reviewed_stages"])),
                reviewed_artifact_ids=tuple(
                    int(value) for value in _json_list(row["reviewed_artifact_ids"])
                ),
                producer_agents=tuple(_json_list(row["producer_agents"])),
                excluded_models=tuple(str(value) for value in _json_list(row["excluded_models"])),
                excluded_candidates={
                    str(key): str(value)
                    for key, value in _json_object(row["excluded_candidates"]).items()
                },
                strategy=str(row["strategy"]),
                review_artifact_id=(
                    int(row["review_artifact_id"]) if row["review_artifact_id"] else None
                ),
                verdict=str(row["verdict"]) if row["verdict"] else None,
                created_at=str(row["created_at"]),
                completed_at=str(row["completed_at"]) if row["completed_at"] else None,
            )
            for row in rows
        ]

    def approvals(self) -> list[ApprovalView]:
        result = [
            ApprovalView(
                id=int(row["id"]),
                kind="workflow",
                status=str(row["status"]),
                target_type="run",
                target_id=int(row["run_id"]),
                decision_note=str(row["decision_note"]),
                created_at=str(row["created_at"]),
                decided_at=str(row["decided_at"]) if row["decided_at"] else None,
                metadata={},
            )
            for row in self.storage.approvals()
        ]
        result.extend(
            ApprovalView(
                id=int(row["id"]),
                kind="provider",
                status=str(row["status"]),
                target_type="task",
                target_id=int(row["task_id"]),
                decision_note=str(row["decision_note"]),
                created_at=str(row["created_at"]),
                decided_at=str(row["decided_at"]) if row["decided_at"] else None,
                metadata={
                    "provider": str(row["provider"]),
                    "agent_id": str(row["agent_id"]),
                    "task_id": int(row["task_id"]),
                    "request_hash": row["request_hash"],
                    "definition_hash": row["definition_hash"],
                    "consumed_at": row["consumed_at"],
                },
            )
            for row in self.storage.provider_execution_gates()
        )
        result.extend(
            ApprovalView(
                id=int(row["id"]),
                kind="github",
                status=str(row["status"]),
                target_type="github_plan",
                target_id=int(row["plan_id"]),
                decision_note=str(row["decision_note"]),
                created_at=str(row["created_at"]),
                decided_at=str(row["decided_at"]) if row["decided_at"] else None,
                metadata={
                    "repo": str(row["repo"]),
                    "plan_hash": str(row["plan_hash"]),
                    "consumed_at": row["consumed_at"],
                },
            )
            for row in self.storage.github_gates()
        )
        return sorted(result, key=lambda item: (item.created_at, item.kind, item.id))

    def founder_decisions(
        self, *, pending_only: bool = True
    ) -> list[FounderDecisionPacket]:
        packets: list[FounderDecisionPacket] = []
        for approval in self.approvals():
            if approval.kind != "workflow":
                continue
            if pending_only and approval.status != "pending":
                continue
            run = self.run(approval.target_id)
            work_item = self.work_item(run.task_id)
            artifacts = tuple(self.artifacts(run.id))
            reviews = tuple(self.reviews(run.id, limit=10_000))
            evidence: dict[str, list[str]] = {
                criterion: [] for criterion in work_item.acceptance_criteria
            }
            findings: list[str] = []
            for artifact in artifacts:
                document = _artifact_document(artifact.content)
                criteria = document.get("criteria_evidence", {})
                if isinstance(criteria, dict):
                    for criterion, value in criteria.items():
                        if str(value).strip():
                            evidence.setdefault(str(criterion), []).append(
                                f"{artifact.stage}: {value}"
                            )
                for field in ("concerns", "errors"):
                    values = document.get(field, [])
                    if isinstance(values, str):
                        values = [values] if values.strip() else []
                    if isinstance(values, list):
                        findings.extend(
                            f"{artifact.stage}: {value}"
                            for value in values
                            if str(value).strip()
                        )
                if artifact.status == "rejected":
                    findings.append(
                        f"Artifact #{artifact.id} ({artifact.stage}) was rejected"
                    )
            passing = {
                "COMPLETE",
                "PASS",
                "ALIGNED",
                "CONDITIONALLY_ALIGNED",
                "APPROVED",
                "CONDITIONALLY_APPROVED",
            }
            for review in reviews:
                if not review.verdict or review.verdict.upper() not in passing:
                    findings.append(
                        f"{review.stage}: reviewer verdict {review.verdict or 'missing'}"
                    )
            for criterion, values in evidence.items():
                if not values:
                    findings.append(f"No recorded evidence for criterion: {criterion}")
            packets.append(
                FounderDecisionPacket(
                    approval=approval,
                    run=run,
                    work_item=work_item,
                    artifacts=artifacts,
                    reviews=reviews,
                    criterion_evidence={
                        criterion: tuple(values)
                        for criterion, values in evidence.items()
                    },
                    unresolved_findings=tuple(dict.fromkeys(findings)),
                )
            )
        return packets

    def events(self, *, limit: int = 100) -> list[EventView]:
        if limit < 1 or limit > 10_000:
            raise ValueError("limit must be between 1 and 10000")
        rows = self.storage.db.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            EventView(
                id=int(row["id"]),
                event_type=str(row["event_type"]),
                entity_type=str(row["entity_type"]),
                entity_id=str(row["entity_id"]),
                payload=_json_object(row["payload"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def audit_events(
        self,
        *,
        limit: int = 10_000,
        from_time: str | None = None,
        to_time: str | None = None,
        project_id: int | None = None,
        task_id: int | None = None,
        run_id: int | None = None,
        agent_id: str | None = None,
        provider: str | None = None,
        action: str | None = None,
        outcome: str | None = None,
    ) -> list[AuditEventView]:
        normalized_from = from_time.replace("T", " ").removesuffix("Z") if from_time else None
        normalized_to = to_time.replace("T", " ").removesuffix("Z") if to_time else None
        result: list[AuditEventView] = []
        for event in self.events(limit=limit):
            context = self._audit_event(event)
            if normalized_from and context.created_at < normalized_from:
                continue
            if normalized_to and context.created_at > normalized_to:
                continue
            if project_id is not None and context.project_id != project_id:
                continue
            if task_id is not None and context.task_id != task_id:
                continue
            if run_id is not None and context.run_id != run_id:
                continue
            if agent_id is not None and context.agent_id != agent_id:
                continue
            if provider is not None and context.provider != provider:
                continue
            if action is not None and action.casefold() not in context.event_type.casefold():
                continue
            if outcome is not None and context.outcome != outcome:
                continue
            result.append(context)
        return result

    def _audit_event(self, event: EventView) -> AuditEventView:
        def integer(value: Any) -> int | None:
            try:
                return int(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        payload = event.payload
        project_id = integer(payload.get("project_id"))
        task_id = integer(payload.get("task_id"))
        run_id = integer(payload.get("run_id"))
        target = payload.get("target")
        if isinstance(target, dict) and target.get("type") == "workflow_run":
            run_id = run_id or integer(target.get("id"))
        agent_id = next(
            (
                str(payload[key])
                for key in ("agent_id", "worker", "reviewer_agent_id", "agent")
                if payload.get(key)
            ),
            None,
        )
        provider = next(
            (
                str(payload[key])
                for key in ("provider", "reviewer_provider")
                if payload.get(key)
            ),
            None,
        )
        entity_id = integer(event.entity_id)
        entity = event.entity_type.casefold()
        if entity in {"task", "work_item"}:
            task_id = entity_id
        elif "run" in entity:
            run_id = entity_id
        elif entity == "agent":
            agent_id = event.entity_id
        elif entity == "provider":
            provider = event.entity_id

        artifact_ids: set[int] = set()
        artifact_id = integer(payload.get("artifact_id"))
        if artifact_id is not None:
            artifact_ids.add(artifact_id)
        artifact_ids.update(
            value
            for raw in payload.get("artifact_ids", [])
            if (value := integer(raw)) is not None
        )
        if "artifact" in entity and entity_id is not None:
            artifact_ids.add(entity_id)
        if artifact_ids:
            placeholders = ",".join("?" for _ in artifact_ids)
            row = self.storage.db.execute(
                f"""SELECT a.run_id,a.agent_id,a.provider,r.task_id,r.project_id
                       FROM artifacts a JOIN workflow_runs r ON r.id=a.run_id
                      WHERE a.id IN ({placeholders}) ORDER BY a.id LIMIT 1""",
                tuple(sorted(artifact_ids)),
            ).fetchone()
            if row:
                run_id = run_id or int(row["run_id"])
                task_id = task_id or int(row["task_id"])
                project_id = project_id or int(row["project_id"])
                agent_id = agent_id or str(row["agent_id"])
                provider = provider or str(row["provider"])
        if run_id is not None:
            row = self.storage.db.execute(
                "SELECT task_id,project_id FROM workflow_runs WHERE id=?", (run_id,)
            ).fetchone()
            if row:
                task_id = task_id or int(row["task_id"])
                project_id = project_id or int(row["project_id"])
        if task_id is not None:
            row = self.storage.db.execute(
                "SELECT project_id FROM work_items WHERE id=?", (task_id,)
            ).fetchone()
            if row:
                project_id = project_id or int(row["project_id"])
        if run_id is not None:
            artifact_ids.update(
                int(row[0])
                for row in self.storage.db.execute(
                    "SELECT id FROM artifacts WHERE run_id=? ORDER BY id", (run_id,)
                )
            )
        elif task_id is not None:
            artifact_ids.update(
                int(row[0])
                for row in self.storage.db.execute(
                    """SELECT a.id FROM artifacts a JOIN workflow_runs r ON r.id=a.run_id
                         WHERE r.task_id=? ORDER BY a.id""",
                    (task_id,),
                )
            )
        kind = event.event_type.casefold()
        if payload.get("ok") is False or any(
            token in kind
            for token in ("failed", "error", "rejected", "cancelled", "abandoned")
        ):
            event_outcome = "failure"
        elif any(token in kind for token in ("pending", "requested", "claimed", "running")):
            event_outcome = "pending"
        elif any(
            token in kind
            for token in ("succeeded", "approved", "completed", "created", "updated", "enabled", "disabled")
        ):
            event_outcome = "success"
        else:
            event_outcome = "info"
        return AuditEventView(
            **asdict(event),
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            agent_id=agent_id,
            provider=provider,
            outcome=event_outcome,
            related_artifact_ids=tuple(sorted(artifact_ids)),
        )

    def settings(self) -> SettingsView:
        policy = load_yaml(config_path_for_workspace("policy", self.workspace))
        execution = policy.get("execution", {})
        sources = tuple(
            ConfigSourceView(
                name, str(config_path_for_workspace(name, self.workspace))
            )
            for name in ("agents", "providers", "policy", "workflows")
        )
        stored = {
            str(row["key"]): (json.loads(row["value_json"]), int(row["version"]))
            for row in self.storage.runtime_settings()
        }
        runtime_settings = tuple(
            RuntimeSettingView(
                key=key,
                value=int(stored.get(key, (default, 0))[0]),
                version=int(stored.get(key, (default, 0))[1]),
                minimum=minimum,
                maximum=maximum,
                description=description,
            )
            for key, (default, minimum, maximum, description) in RUNTIME_SETTING_SPECS.items()
        )
        return SettingsView(
            workspace=str(self.workspace),
            database=str(self.storage.path.resolve()),
            execution_modes=tuple(mode.value for mode in ExecutionMode),
            live_provider_approval_required=bool(
                execution.get("live_provider_approval_required", True)
            ),
            automatic_fallback_in_simulation=bool(
                execution.get("automatic_fallback_in_simulation", True)
            ),
            max_timeout=int(execution.get("max_timeout", 180)),
            max_output_chars=int(execution.get("max_output_chars", 100_000)),
            config_sources=sources,
            runtime_settings=runtime_settings,
        )

    def operational_state(self) -> OperationalStateView:
        scalar = lambda query: int(self.storage.db.execute(query).fetchone()[0])
        traces = self.storage.db.execute(
            "SELECT * FROM execution_traces ORDER BY id DESC LIMIT 20"
        ).fetchall()
        return OperationalStateView(
            active_sessions=scalar(
                "SELECT COUNT(*) FROM worker_sessions WHERE status IN ('starting','running','suspended')"
            ),
            queued_tasks=scalar("SELECT COUNT(*) FROM work_items WHERE status='pending'"),
            active_leases=scalar("SELECT COUNT(*) FROM leases WHERE status='active'"),
            active_worktrees=scalar(
                "SELECT COUNT(*) FROM worktrees WHERE status IN ('provisioning','ready','dirty','retained')"
            ),
            failures=scalar(
                """SELECT COUNT(*) FROM events WHERE event_type LIKE '%.failed'
                    OR event_type LIKE '%.rejected' OR event_type LIKE '%.blocked'"""
            ),
            budgets=tuple(BudgetStateView(
                correlation_root=str(row["correlation_root"]), status=str(row["status"]),
                tokens=int(row["tokens"]), max_tokens=int(row["max_tokens"]),
                estimated_cost_usd=float(row["estimated_cost_usd"]),
                max_cost_usd=float(row["max_cost_usd"]),
                stages_reserved=int(row["stages_reserved"]), max_stages=int(row["max_stages"]),
                retries=int(row["retries"]), max_retries=int(row["max_retries"]),
                tool_calls=int(row["tool_calls"]), max_tool_calls=int(row["max_tool_calls"]),
                terminal_reason=(str(row["terminal_reason"]) if row["terminal_reason"] else None),
            ) for row in traces),
        )

    # Commands reuse storage, workflow, policy, approval, and audit paths.
    def create_project(self, name: str, description: str = "") -> ProjectChange:
        existing = self.storage.find_project(name)
        if existing:
            return ProjectChange(int(existing["id"]), False)
        return ProjectChange(self.storage.create_project(name, description), True)

    def create_work_item(
        self,
        *,
        project_id: int,
        title: str,
        description: str,
        kind: str = "task",
        dependencies: list[int] | None = None,
        inputs: dict[str, Any] | None = None,
        expected_outputs: list[str] | None = None,
        acceptance_criteria: list[str] | None = None,
        permissions: list[str] | None = None,
        budget: Budget | None = None,
    ) -> WorkItemView:
        if not self.storage.db.execute(
            "SELECT 1 FROM projects WHERE id=?", (project_id,)
        ).fetchone():
            raise KeyError(f"Unknown project: {project_id}")
        task_id = self.storage.create_task(
            WorkItem(
                title=title,
                description=description,
                project_id=project_id,
                kind=kind,
                dependencies=dependencies or [],
                inputs=inputs or {},
                expected_outputs=expected_outputs or [],
                acceptance_criteria=acceptance_criteria or [],
                permissions=(
                    permissions
                    if permissions is not None
                    else ["read_project", "create_artifact"]
                ),
                budget=budget or Budget(),
            )
        )
        return self.work_item(task_id)

    def claim_work_item(self, task_id: int, agent_id: str) -> ClaimResult:
        item = self.storage.get_task(task_id)
        agent = self.registry.get(agent_id)
        if not agent.enabled:
            raise RuntimeError(f"Agent is disabled: {agent.id}")
        configured_domains = item.inputs.get("conflict_domains")
        if configured_domains is not None and not isinstance(configured_domains, list):
            raise ValueError("Work-item conflict_domains must be a list")
        ttl = item.inputs.get("lease_ttl_seconds", 60)
        if not isinstance(ttl, int):
            raise ValueError("Work-item lease_ttl_seconds must be an integer")
        conflict_action = str(item.inputs.get("conflict_action", "serialize"))
        lease = self.storage.claim_runnable_task(
            task_id,
            agent.id,
            agent.provider,
            ttl_seconds=ttl,
            conflict_domains=configured_domains,
            conflict_action=conflict_action,
        )
        return ClaimResult(
            task_id=lease.task_id,
            worker=lease.worker,
            assignment_id=lease.assignment_id,
            lease_id=lease.lease_id,
            fencing_token=lease.fencing_token,
            expires_at=lease.expires_at,
            conflict_domains=lease.conflict_domains,
        )

    def runnable_work_items(self, project_id: int | None = None) -> list[WorkItemView]:
        return [self.work_item(item.id or 0) for item in self.storage.runnable_tasks(project_id)]

    def run_workflow(
        self,
        task_id: int,
        workflow_id: str = "delivery",
        mode: ExecutionMode | str = ExecutionMode.SIMULATION,
    ) -> RunView:
        blockers = tuple(
            blocker
            for blocker in self.storage.task_readiness(task_id)
            if not blocker.startswith("assignment:")
        )
        if blockers:
            raise RuntimeError(
                f"Task {task_id} cannot run: {', '.join(blockers)}"
            )
        run_id = WorkflowEngine(
            self.storage, registry=self.registry, runtime=self.runtime
        ).run(workflow_id, self.storage.get_task(task_id), mode)
        return self.run(run_id)

    def review_artifact(
        self, task_id: int, artifact_id: int, decision: str, note: str = ""
    ) -> ArtifactView:
        row = self.storage.db.execute(
            """SELECT a.run_id FROM artifacts a JOIN workflow_runs r ON r.id=a.run_id
                 WHERE a.id=? AND r.task_id=?""",
            (artifact_id, task_id),
        ).fetchone()
        if not row:
            raise ValueError("Artifact does not belong to the requested work item")
        self.storage.review_artifact(artifact_id, decision, note)
        return next(
            item for item in self.artifacts(int(row["run_id"])) if item.id == artifact_id
        )

    def decide_workflow_approval(
        self, gate_id: int, decision: str, note: str = ""
    ) -> ApprovalView:
        return self.founder_decide(gate_id, decision, note).approval

    def founder_decide(
        self,
        gate_id: int,
        decision: str,
        note: str = "",
        actor: str = "Founder",
    ) -> FounderDecisionReceipt:
        if actor != "Founder":
            raise ValueError("Only the Founder actor can make a final workflow decision")
        previous = next(
            (
                item
                for item in self.approvals()
                if item.kind == "workflow" and item.id == gate_id
            ),
            None,
        )
        if previous is None:
            raise KeyError(f"Unknown workflow approval: {gate_id}")
        changed = self.storage.decide_approval(gate_id, decision, note, actor)
        current = next(
            item
            for item in self.approvals()
            if item.kind == "workflow" and item.id == gate_id
        )
        return FounderDecisionReceipt(
            approval=current,
            idempotent=not changed,
            actor=actor,
            target=f"workflow_run:{current.target_id}",
            previous_state=previous.status,
            resulting_state=current.status,
            timestamp=current.decided_at or current.created_at,
        )

    def update_runtime_setting(self, key: str, value: int) -> RuntimeSettingView:
        specification = RUNTIME_SETTING_SPECS.get(key)
        if specification is None:
            raise ValueError(f"Runtime setting is not allowlisted: {key}")
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"Runtime setting {key} requires an integer")
        _default, minimum, maximum, description = specification
        if value < minimum or value > maximum:
            raise ValueError(
                f"Runtime setting {key} must be between {minimum} and {maximum}"
            )
        version = self.storage.update_runtime_setting(key, value)
        return RuntimeSettingView(
            key=key,
            value=value,
            version=version,
            minimum=minimum,
            maximum=maximum,
            description=description,
        )

    def set_agent_enabled(self, agent_id: str, enabled: bool) -> AgentView:
        previous = self.registry.get(agent_id).enabled
        agent = self.registry.set_enabled(agent_id, enabled)
        self.storage.event(
            "agent.enabled" if agent.enabled else "agent.disabled",
            "agent",
            agent.id,
            {
                "previous_enabled": previous,
                "enabled": agent.enabled,
                "impact": "disabled agents cannot receive work or reviewer assignments",
            },
        )
        return next(item for item in self.agents() if item.id == agent_id)

    def replace_agent_provider(
        self, agent_id: str, provider: str, model: str = ""
    ) -> AgentView:
        current = self.registry.get(agent_id)
        definitions = {
            str(item["id"]): item
            for item in load_yaml(
                config_path_for_workspace("providers", self.workspace)
            ).get("providers", [])
        }
        if provider == "deterministic":
            definition = {"enabled": True, "allowed_roles": []}
        else:
            definition = definitions.get(provider)
            if definition is None:
                raise ValueError(f"Unknown provider: {provider}")
            if not definition.get("enabled", True):
                raise ValueError(f"Provider is disabled: {provider}")
            allowed_roles = [str(role) for role in definition.get("allowed_roles", [])]
            if current.role not in allowed_roles:
                raise ValueError(
                    f"Provider {provider} is incompatible with role {current.role}"
                )
        agent = self.registry.replace_provider(agent_id, provider, model)
        self.storage.event(
            "agent.provider.replaced",
            "agent",
            agent.id,
            {
                "previous_provider": current.provider,
                "previous_model": current.model_identity,
                "provider": agent.provider,
                "model": agent.model_identity,
                "impact": "new provider applies to future assignments and invalidates prior execution snapshots",
            },
        )
        return next(item for item in self.agents() if item.id == agent_id)

    def request_provider_execution(
        self, provider: str, agent_id: str, task_id: int
    ) -> int:
        agent = self.registry.get(agent_id)
        if not agent.enabled:
            raise RuntimeError(f"Agent is disabled: {agent.id}")
        if agent.provider != provider:
            raise ValueError(f"Agent {agent.id} uses {agent.provider}, not {provider}")
        item = self.storage.get_task(task_id)
        request_hash, definition_hash = provider_snapshot_hashes(
            provider, agent, item, self.workspace
        )
        return self.storage.request_provider_execution(
            provider, agent.id, task_id, request_hash, definition_hash
        )

    def decide_provider_execution(
        self, gate_id: int, decision: str, note: str = ""
    ) -> ApprovalView:
        if decision == "cancelled":
            self.storage.cancel_provider_execution(gate_id, note)
        else:
            self.storage.decide_provider_execution(gate_id, decision, note)
        return next(
            item
            for item in self.approvals()
            if item.kind == "provider" and item.id == gate_id
        )

    def invoke_provider(self, gate_id: int) -> ProviderInvocationResult:
        gate = self.storage.db.execute(
            "SELECT * FROM provider_execution_gates WHERE id=?", (gate_id,)
        ).fetchone()
        if not gate:
            raise KeyError(f"Unknown provider gate: {gate_id}")
        agent = self.registry.get(str(gate["agent_id"]))
        item = self.storage.get_task(int(gate["task_id"]))
        request_hash, definition_hash = provider_snapshot_hashes(
            str(gate["provider"]), agent, item, self.workspace
        )
        attempt = self.storage.claim_provider_execution(
            gate_id, request_hash, definition_hash
        )
        approval = ExecutionApproval(
            int(gate["id"]),
            str(gate["provider"]),
            str(gate["agent_id"]),
            int(gate["task_id"]),
        )
        self.storage.mark_provider_attempt_running(int(attempt["id"]))
        try:
            if agent.provider != gate["provider"]:
                raise ValueError(
                    "Agent provider changed after approval; request a new gate"
                )
            result = self.runtime.run(
                agent,
                item,
                {"source": "one-time human-approved invocation"},
                approval,
                allow_fallback=False,
            )
        except Exception as exc:  # noqa: BLE001 - Persist all launcher failures.
            result = ProviderResult(
                False,
                provider=str(gate["provider"]),
                error=str(exc)[:4000],
                metadata={"exception": type(exc).__name__},
            )
        metadata = {
            "ok": result.ok,
            "error": (result.error or "")[:4000],
            **result.metadata,
        }
        metadata["content_sha256"] = hashlib.sha256(result.content.encode()).hexdigest()
        artifact_id = self.storage.finish_provider_attempt(
            int(attempt["id"]),
            "succeeded" if result.ok else "failed",
            result.content if result.ok else (result.error or "provider failed"),
            metadata,
        )
        return ProviderInvocationResult(
            result.ok,
            result.provider,
            artifact_id,
            result.content,
            result.error,
            dict(result.metadata),
        )

    def import_backlog(
        self, proposal: BacklogProposal, project_id: int
    ) -> BacklogImportResult:
        if not self.storage.db.execute(
            "SELECT 1 FROM projects WHERE id=?", (project_id,)
        ).fetchone():
            raise KeyError(f"Unknown project: {project_id}")
        known: dict[str, int] = {}
        for row in self.storage.db.execute(
            "SELECT id,payload FROM work_items WHERE project_id=?", (project_id,)
        ):
            try:
                stable_id = _json_object(row["payload"]).get("inputs", {}).get(
                    "stable_id"
                )
            except (json.JSONDecodeError, AttributeError, TypeError):
                continue
            if isinstance(stable_id, str) and stable_id:
                known[stable_id] = int(row["id"])
        remaining = {item.stable_id: item for item in proposal.items}
        created: list[dict[str, Any]] = []
        skipped: list[str] = []
        for stable_id in list(remaining):
            if stable_id in known:
                skipped.append(stable_id)
                remaining.pop(stable_id)
        while remaining:
            ready = [
                item
                for item in remaining.values()
                if all(
                    reference in known
                    for reference in (
                        *item.dependencies,
                        *([item.parent_id] if item.parent_id else []),
                    )
                )
            ]
            if not ready:
                raise RuntimeError("Validated backlog could not be ordered for local import")
            for item in ready:
                task_id = self.storage.create_task(
                    WorkItem(
                        title=item.title,
                        description=item.description,
                        project_id=project_id,
                        kind=item.kind,
                        dependencies=[known[value] for value in item.dependencies],
                        inputs={
                            "stable_id": item.stable_id,
                            "parent_stable_id": item.parent_id,
                            "source_path": proposal.source_path,
                            "source_sha256": proposal.source_sha256,
                            "source_references": list(item.source_references),
                            "review_notes": list(item.review_notes),
                            "labels": list(item.labels),
                        },
                        acceptance_criteria=list(item.acceptance_criteria),
                        expected_outputs=[
                            "reviewable delivery artifact",
                            "acceptance evidence",
                        ],
                    )
                )
                known[item.stable_id] = task_id
                created.append({"stable_id": item.stable_id, "task_id": task_id})
                remaining.pop(item.stable_id)
        return BacklogImportResult(
            tuple(created), tuple(sorted(skipped)), proposal.source_sha256
        )

    def import_backlog_file(
        self,
        project_name: str,
        backlog_path: str,
        project_description: str = "",
    ) -> BacklogFileImportResult:
        if not project_name.strip():
            raise ValueError("Backlog import requires a project name")
        relative = Path(backlog_path)
        if relative.is_absolute():
            raise ValueError("Backlog import path must be workspace-relative")
        source = (self.workspace / relative).resolve()
        if not source.is_relative_to(self.workspace):
            raise ValueError("Backlog import path escapes the workspace")
        if not source.is_file():
            raise ValueError(f"Backlog manifest does not exist: {backlog_path}")
        proposal = load_backlog(source)
        project = self.create_project(project_name.strip(), project_description.strip())
        result = self.import_backlog(proposal, project.project_id)
        return BacklogFileImportResult(
            project_id=project.project_id,
            project_created=project.created,
            source_path=source.relative_to(self.workspace).as_posix(),
            created=result.created,
            skipped=result.skipped,
            source_sha256=result.source_sha256,
        )

    def seed_example(self) -> tuple[int, int]:
        change = self.create_project(
            "Agent Factory Demo",
            "A neutral example that demonstrates a complete evidence and approval chain.",
        )
        existing = self.storage.db.execute(
            "SELECT id FROM work_items WHERE project_id=? AND title=?",
            (change.project_id, "Deliver the first reviewable capability"),
        ).fetchone()
        if existing:
            return change.project_id, int(existing["id"])
        item = self.create_work_item(
            project_id=change.project_id,
            title="Deliver the first reviewable capability",
            description=(
                "Produce a bounded implementation proposal, validate it against explicit "
                "criteria, and stop for a human decision."
            ),
            kind="task",
            inputs={"example": True},
            expected_outputs=[
                "policy precheck",
                "implementation artifact",
                "validation evidence",
                "policy postcheck",
            ],
            acceptance_criteria=[
                "Every stage produces a typed artifact",
                "Every acceptance criterion has evidence",
                "The workflow stops before final acceptance",
            ],
        )
        return change.project_id, item.id

    def run_demo(self) -> RunView:
        _, task_id = self.seed_example()
        active = self.storage.db.execute(
            """SELECT id FROM workflow_runs
                 WHERE task_id=? AND workflow_id='delivery'
                   AND status IN ('running','awaiting_approval')
                 ORDER BY id DESC LIMIT 1""",
            (task_id,),
        ).fetchone()
        if active:
            return self.run(int(active["id"]))
        return self.run_workflow(task_id, "delivery", ExecutionMode.SIMULATION)

    def decide_github_approval(
        self, gate_id: int, decision: str, note: str = ""
    ) -> ApprovalView:
        self.storage.decide_github_gate(gate_id, decision, note)
        return next(
            item
            for item in self.approvals()
            if item.kind == "github" and item.id == gate_id
        )

    def preview_github_plan(
        self, repo: str, operations: list[dict[str, Any]], client: Any
    ) -> dict[str, Any]:
        if not operations:
            return {}
        plan_id, plan_hash = self.storage.create_github_plan(repo, operations)
        gate = self.storage.db.execute(
            """SELECT * FROM github_mutation_gates
                 WHERE plan_id=? AND status IN ('pending','approved')
                 ORDER BY id DESC LIMIT 1""",
            (plan_id,),
        ).fetchone()
        gate_id = int(gate["id"]) if gate else self.storage.request_github_gate(plan_id)
        return {
            "plan_id": plan_id,
            "plan_hash": plan_hash,
            "gate_id": gate_id,
            "gate_status": str(gate["status"]) if gate else "pending",
            "preview": client.apply(operations),
        }

    def preview_github_sync(
        self,
        repo: str,
        backlog_path: str,
        existing_issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        relative = Path(backlog_path)
        if relative.is_absolute():
            raise ValueError("GitHub preview backlog path must be workspace-relative")
        source = (self.workspace / relative).resolve()
        if not source.is_relative_to(self.workspace):
            raise ValueError("GitHub preview backlog path escapes the workspace")
        proposal = load_backlog(source)
        difference = diff_issues(proposal, existing_issues)
        operations = issue_operations(difference)
        result: dict[str, Any] = {
            "dry_run": True,
            "source_path": source.relative_to(self.workspace).as_posix(),
            "diff": difference,
            "operations": operations,
        }
        if operations:
            result.update(
                self.preview_github_plan(
                    repo, operations, GitHubClient(repo=repo, dry_run=True)
                )
            )
        else:
            result.update(
                {
                    "plan_id": None,
                    "plan_hash": canonical_hash(
                        {"version": 1, "repo": repo, "operations": []}
                    ),
                    "gate_id": None,
                    "gate_status": "not_required",
                    "preview": {"ok": True, "dry_run": True, "results": []},
                }
            )
        return result

    def apply_github_plan(self, plan_id: int, gate_id: int, client: Any) -> dict[str, Any]:
        plan = self.storage.github_plan(plan_id)
        operations = _json_object(plan["plan_json"])["operations"]
        self.storage.claim_github_gate(
            gate_id, plan_id, str(plan["repo"]), str(plan["plan_hash"])
        )
        result = client.apply(
            operations, self.storage.github_completed_keys(str(plan["repo"]))
        )
        report_id = self.storage.finish_github_apply(gate_id, plan_id, result)
        return {"report_id": report_id, **result}

    def reconcile_provider_attempts(self) -> tuple[int, ...]:
        return tuple(self.storage.reconcile_provider_attempts())

    def backup(self, destination: Path) -> Path:
        return self.storage.online_backup(destination)

    def stale_state(self, older_than_seconds: int) -> dict[str, list[dict[str, Any]]]:
        return {
            "workflow_runs": [
                dict(row) for row in self.storage.stale_workflow_runs(older_than_seconds)
            ],
            "provider_attempts": [
                dict(row) for row in self.storage.stale_provider_attempts(older_than_seconds)
            ],
        }
