"""Loopback-only FastAPI host for the Local Control Center."""

import sqlite3
import os
import json
from datetime import datetime, timezone
from collections.abc import AsyncIterator
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, Generic, Literal, TypeVar

from fastapi import Depends, FastAPI, File, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .application import (
    AgentFactoryService,
    AgentView,
    ApprovalView,
    ArtifactView,
    AuditEventView,
    BacklogFileImportResult,
    EventView,
    FounderDecisionPacket,
    FounderDecisionReceipt,
    OperationalStateView,
    ProjectView,
    ProviderView,
    ReviewView,
    RuntimeSettingView,
    RunView,
    SettingsView,
    WorkItemView,
)
from .storage import MIGRATIONS, SQLiteStorage
from .control_plane import HumanControlPlaneService
from .backlog_analyzer import analyze_specification

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    offset: int
    limit: int
    total: int


class HealthResponse(BaseModel):
    status: str
    database: str
    integrity: dict[str, Any]


class IntegrationStatus(BaseModel):
    name: str
    status: str
    detail: str


class DashboardCounts(BaseModel):
    ready: int
    active: int
    blocked: int
    failed: int
    awaiting_review: int
    awaiting_approval: int


class DashboardResponse(BaseModel):
    counts: DashboardCounts
    runs: list[RunView]
    providers: list[ProviderView]
    pending_approvals: list[ApprovalView]
    recent_failures: list[EventView]
    operations: OperationalStateView


class MonitorResponse(BaseModel):
    status: Literal["ready", "degraded"]
    checked_at: str
    database: dict[str, Any]
    migrations: dict[str, int]
    providers: dict[str, int]
    agents: dict[str, int]
    runtime: dict[str, int]
    safety: dict[str, Any]
    blockers: list[str]


class ConfirmedCommand(BaseModel):
    confirmed: bool


class ClaimCommand(ConfirmedCommand):
    agent_id: str


class RunCommand(ConfirmedCommand):
    workflow_id: str = "delivery"
    mode: Literal["simulation"] = "simulation"


class ReviewCommand(ConfirmedCommand):
    task_id: int
    decision: Literal["approved", "rejected"]
    note: str = ""


class AgentEnabledCommand(ConfirmedCommand):
    enabled: bool


class AgentProviderCommand(ConfirmedCommand):
    provider: str
    model: str = ""


class AgentCommandResult(BaseModel):
    agent: AgentView
    impact_summary: str


class RuntimeSettingCommand(ConfirmedCommand):
    value: int


class GitHubPreviewCommand(ConfirmedCommand):
    repo: str
    backlog_path: str
    existing_issues: list[dict[str, Any]] = Field(default_factory=list)


class FounderDecisionCommand(ConfirmedCommand):
    decision: Literal["approved", "rejected"]
    note: str = ""
    actor: Literal["Founder"] = "Founder"


class BacklogImportCommand(ConfirmedCommand):
    project_name: str
    project_description: str = ""
    backlog_path: str


class UploadedBacklogResponse(BaseModel):
    source_path: str
    source_name: str
    recommended_agent: str
    counts: dict[str, int]
    items: list[dict[str, Any]]


class RunDetail(BaseModel):
    run: RunView
    artifacts: list[ArtifactView]
    reviews: list[ReviewView]
    approval: ApprovalView | None
    stopped_reason: str

class ControlActionCommand(BaseModel):
    tenant_id: str
    actor: str
    role: str
    action: str
    target_type: str
    target_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


Offset = Annotated[int, Query(ge=0, le=1_000_000)]
Limit = Annotated[int, Query(ge=1, le=200)]
Confirmation = Annotated[str | None, Header(alias="X-Agent-Factory-Confirm")]


def validate_loopback_host(host: str) -> str:
    normalized = host.strip().lower()
    allowed = {"127.0.0.1", "localhost", "::1"}
    if normalized not in allowed:
        raise ValueError("Local Control Center must bind to a loopback host")
    return normalized


def _page(items: list[T], offset: int, limit: int) -> Page[T]:
    return Page(items=items[offset : offset + limit], offset=offset, limit=limit, total=len(items))


def _require_confirmation(command: ConfirmedCommand, header: str | None) -> None:
    if command.confirmed is not True or header != "true":
        raise ValueError("Explicit confirmation is required")


def create_app(workspace: Path, database: Path) -> FastAPI:
    workspace = workspace.expanduser().resolve()
    database = database.expanduser().resolve()
    app = FastAPI(
        title="Agent Factory Local Control Center",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    static_directory = Path(__file__).resolve().parent / "static"
    app.mount("/assets", StaticFiles(directory=static_directory), name="assets")

    async def service_dependency() -> AsyncIterator[AgentFactoryService]:
        storage = SQLiteStorage(database)
        try:
            yield AgentFactoryService(storage, workspace=workspace)
        finally:
            storage.close()

    Service = Annotated[AgentFactoryService, Depends(service_dependency)]

    def require_api_auth(authorization: str | None = Header(default=None)) -> None:
        expected = os.getenv("AGENT_FACTORY_API_TOKEN", "").strip()
        if expected and authorization != f"Bearer {expected}":
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="Bearer authentication required")

    @app.exception_handler(KeyError)
    async def not_found(_request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": str(exc).strip("'")}},
        )

    @app.exception_handler(ValueError)
    async def invalid_request(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "invalid_request", "message": str(exc)}},
        )

    @app.exception_handler(sqlite3.Error)
    async def storage_unavailable(_request: Request, exc: sqlite3.Error) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "storage_unavailable",
                    "message": type(exc).__name__,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def malformed_request(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request parameters are invalid",
                    "details": exc.errors(),
                }
            },
        )

    @app.get("/api/health", response_model=HealthResponse)
    async def health(service: Service) -> HealthResponse:
        integrity = service.storage.integrity_check()
        return HealthResponse(
            status="ready" if integrity["ok"] else "degraded",
            database=str(database),
            integrity=integrity,
        )

    @app.get("/api/dashboard", response_model=DashboardResponse)
    async def dashboard(service: Service) -> DashboardResponse:
        items = service.work_items()
        runs = service.runs()
        approvals = service.approvals()
        artifacts = service.artifacts()
        by_id = {item.id: item for item in items}
        blocked = sum(
            item.status == "pending"
            and any(
                dependency not in by_id
                or by_id[dependency].status not in {"completed", "approved"}
                for dependency in item.dependencies
            )
            for item in items
        )
        ready = sum(
            item.status == "pending"
            and all(
                dependency in by_id
                and by_id[dependency].status in {"completed", "approved"}
                for dependency in item.dependencies
            )
            for item in items
        )
        failures = [
            event
            for event in service.events(limit=100)
            if event.event_type.endswith(".failed")
            or event.payload.get("ok") is False
            or "error" in event.payload
        ][:10]
        return DashboardResponse(
            counts=DashboardCounts(
                ready=ready,
                active=sum(run.status == "running" for run in runs),
                blocked=blocked,
                failed=sum(run.status == "failed" for run in runs),
                awaiting_review=sum(artifact.status == "pending" for artifact in artifacts),
                awaiting_approval=sum(item.status == "pending" for item in approvals),
            ),
            runs=runs[-10:][::-1],
            providers=service.providers(),
            pending_approvals=[item for item in approvals if item.status == "pending"],
            recent_failures=failures,
            operations=service.operational_state(),
        )

    @app.get("/api/monitor", response_model=MonitorResponse)
    async def monitor(service: Service) -> MonitorResponse:
        integrity = service.storage.integrity_check()
        migration_row = service.storage.db.execute(
            "SELECT COALESCE(MAX(version), 0) AS current_version FROM schema_migrations"
        ).fetchone()
        current_version = int(migration_row["current_version"])
        latest_version = max(version for version, _ in MIGRATIONS)
        providers = service.providers()
        agents = service.agents()
        operational = service.operational_state()
        safety = service.storage.policy_state()
        blockers: list[str] = []
        if not integrity["ok"]:
            blockers.append("database_integrity_failed")
        if current_version < latest_version:
            blockers.append("database_migrations_pending")
        if any(item.status not in {"ready", "disabled"} for item in providers):
            blockers.append("provider_health_degraded")
        if not any(item.enabled for item in agents):
            blockers.append("no_enabled_agents")
        if safety["emergency_stop"]:
            blockers.append("emergency_stop_active")
        return MonitorResponse(
            status="ready" if not blockers else "degraded",
            checked_at=datetime.now(timezone.utc).isoformat(),
            database={"ok": bool(integrity["ok"]), "path": str(service.storage.path.resolve())},
            migrations={"current": current_version, "latest": latest_version},
            providers={
                "total": len(providers),
                "ready": sum(item.status == "ready" for item in providers),
                "enabled": sum(item.enabled for item in providers),
                "execution_enabled": sum(item.execution_enabled for item in providers),
            },
            agents={"total": len(agents), "enabled": sum(item.enabled for item in agents)},
            runtime={
                "active_sessions": operational.active_sessions,
                "queued_tasks": operational.queued_tasks,
                "active_leases": operational.active_leases,
                "active_worktrees": operational.active_worktrees,
                "failures": operational.failures,
            },
            safety={
                "emergency_stop": bool(safety["emergency_stop"]),
                "reason": safety["reason"],
                "version": safety["version"],
            },
            blockers=blockers,
        )

    @app.get("/api/projects", response_model=Page[ProjectView])
    async def projects(service: Service, offset: Offset = 0, limit: Limit = 50) -> Page[ProjectView]:
        return _page(service.projects(), offset, limit)

    @app.get("/api/work-items", response_model=Page[WorkItemView])
    async def work_items(
        service: Service,
        offset: Offset = 0,
        limit: Limit = 50,
        project_id: int | None = None,
        kind: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        dependency: int | None = None,
        assignee: str | None = None,
    ) -> Page[WorkItemView]:
        rows = service.work_items(project_id)
        if kind is not None:
            rows = [item for item in rows if item.kind == kind]
        if status is not None:
            rows = [item for item in rows if item.status == status]
        if priority is not None:
            rows = [item for item in rows if item.priority == priority]
        if dependency is not None:
            rows = [item for item in rows if dependency in item.dependencies]
        if assignee is not None:
            rows = [item for item in rows if item.assignee == assignee]
        return _page(rows, offset, limit)

    @app.get("/api/work-items/{task_id}", response_model=WorkItemView)
    async def work_item(task_id: int, service: Service) -> WorkItemView:
        return service.work_item(task_id)

    @app.post("/api/backlog/import", response_model=BacklogFileImportResult)
    async def import_backlog(
        command: BacklogImportCommand,
        service: Service,
        confirmation: Confirmation = None,
    ) -> BacklogFileImportResult:
        _require_confirmation(command, confirmation)
        return service.import_backlog_file(
            command.project_name,
            command.backlog_path,
            command.project_description,
        )

    @app.post("/api/backlog/analyze-upload", response_model=UploadedBacklogResponse)
    async def analyze_upload(
        upload: UploadFile = File(...),
    ) -> UploadedBacklogResponse:
        raw = await upload.read()
        if not raw or len(raw) > 10 * 1024 * 1024:
            raise ValueError("Uploaded specification must be between 1 byte and 10 MB")
        source_name = Path(upload.filename or "uploaded-specification.txt").name
        proposal = analyze_specification(raw, source_name)
        upload_dir = (workspace / ".agent-factory" / "uploads").resolve()
        upload_dir.mkdir(parents=True, exist_ok=True)
        manifest_name = f"{proposal.source_sha256}.json"
        manifest = upload_dir / manifest_name
        manifest.write_text(json.dumps(proposal.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        counts = {kind: sum(item.kind == kind for item in proposal.items) for kind in ("epic", "story", "task")}
        return UploadedBacklogResponse(
            source_path=manifest.relative_to(workspace).as_posix(),
            source_name=source_name,
            recommended_agent="backlog-steward",
            counts=counts,
            items=[asdict(item) for item in proposal.items],
        )

    @app.get("/api/runs", response_model=Page[RunView])
    async def runs(
        service: Service,
        offset: Offset = 0,
        limit: Limit = 50,
        task_id: int | None = None,
    ) -> Page[RunView]:
        return _page(service.runs(task_id), offset, limit)

    @app.get("/api/runs/{run_id}", response_model=RunView)
    async def run(run_id: int, service: Service) -> RunView:
        return service.run(run_id)

    @app.get("/api/runs/{run_id}/detail", response_model=RunDetail)
    async def run_detail(run_id: int, service: Service) -> RunDetail:
        run = service.run(run_id)
        artifacts = service.artifacts(run_id)
        reviews = service.reviews(run_id, limit=10_000)
        approval = next(
            (
                item
                for item in service.approvals()
                if item.kind == "workflow" and item.target_id == run_id
            ),
            None,
        )
        reason = {
            "awaiting_approval": "Founder decision required",
            "failed": "Workflow failed; inspect stage evidence and audit events",
            "approved": "Founder approved the accumulated evidence",
            "rejected": "Founder rejected the accumulated evidence",
            "running": "Workflow is still executing",
        }.get(run.status, f"Workflow stopped in state {run.status}")
        return RunDetail(
            run=run,
            artifacts=artifacts,
            reviews=reviews,
            approval=approval,
            stopped_reason=reason,
        )

    @app.post("/api/work-items/{task_id}/claim", response_model=dict[str, Any])
    async def claim_work_item(
        task_id: int, command: ClaimCommand, service: Service, confirmation: Confirmation = None
    ) -> dict[str, Any]:
        _require_confirmation(command, confirmation)
        result = service.claim_work_item(task_id, command.agent_id)
        return asdict(result)

    @app.post("/api/work-items/{task_id}/runs", response_model=RunView)
    async def start_workflow(
        task_id: int, command: RunCommand, service: Service, confirmation: Confirmation = None
    ) -> RunView:
        _require_confirmation(command, confirmation)
        return service.run_workflow(task_id, command.workflow_id, command.mode)

    @app.post("/api/artifacts/{artifact_id}/review", response_model=ArtifactView)
    async def review_artifact(
        artifact_id: int,
        command: ReviewCommand,
        service: Service,
        confirmation: Confirmation = None,
    ) -> ArtifactView:
        _require_confirmation(command, confirmation)
        return service.review_artifact(
            command.task_id, artifact_id, command.decision, command.note
        )

    @app.get("/api/artifacts", response_model=Page[ArtifactView])
    async def artifacts(
        service: Service,
        offset: Offset = 0,
        limit: Limit = 50,
        run_id: int | None = None,
        task_id: int | None = None,
    ) -> Page[ArtifactView]:
        return _page(service.artifacts(run_id, task_id=task_id), offset, limit)

    @app.get("/api/agents", response_model=Page[AgentView])
    async def agents(service: Service, offset: Offset = 0, limit: Limit = 50) -> Page[AgentView]:
        return _page(service.agents(), offset, limit)

    @app.post(
        "/api/agents/{agent_id}/enabled", response_model=AgentCommandResult
    )
    async def set_agent_enabled(
        agent_id: str,
        command: AgentEnabledCommand,
        service: Service,
        confirmation: Confirmation = None,
    ) -> AgentCommandResult:
        _require_confirmation(command, confirmation)
        agent = service.set_agent_enabled(agent_id, command.enabled)
        action = "receive future assignments" if agent.enabled else "be excluded from assignments"
        return AgentCommandResult(
            agent=agent,
            impact_summary=f"{agent.id} will {action}; existing evidence remains immutable",
        )

    @app.post(
        "/api/agents/{agent_id}/provider", response_model=AgentCommandResult
    )
    async def replace_agent_provider(
        agent_id: str,
        command: AgentProviderCommand,
        service: Service,
        confirmation: Confirmation = None,
    ) -> AgentCommandResult:
        _require_confirmation(command, confirmation)
        agent = service.replace_agent_provider(
            agent_id, command.provider, command.model
        )
        return AgentCommandResult(
            agent=agent,
            impact_summary=(
                f"Future {agent.role} assignments use {agent.provider} / {agent.model}; "
                "existing artifacts remain attributed to their original producer"
            ),
        )

    @app.get("/api/providers", response_model=Page[ProviderView])
    async def providers(
        service: Service, offset: Offset = 0, limit: Limit = 50
    ) -> Page[ProviderView]:
        return _page(service.providers(), offset, limit)

    @app.get("/api/reviews", response_model=Page[ReviewView])
    async def reviews(
        service: Service,
        offset: Offset = 0,
        limit: Limit = 50,
        run_id: int | None = None,
    ) -> Page[ReviewView]:
        rows = service.reviews(run_id, limit=10_000)
        return _page(rows, offset, limit)

    @app.get("/api/approvals", response_model=Page[ApprovalView])
    async def approvals(
        service: Service, offset: Offset = 0, limit: Limit = 50
    ) -> Page[ApprovalView]:
        return _page(service.approvals(), offset, limit)

    @app.get("/api/founder-decisions", response_model=list[FounderDecisionPacket])
    async def founder_decisions(
        service: Service, include_decided: bool = False
    ) -> list[FounderDecisionPacket]:
        return service.founder_decisions(pending_only=not include_decided)

    @app.post(
        "/api/founder-decisions/{gate_id}", response_model=FounderDecisionReceipt
    )
    async def founder_decide(
        gate_id: int,
        command: FounderDecisionCommand,
        service: Service,
        confirmation: Confirmation = None,
    ) -> FounderDecisionReceipt:
        _require_confirmation(command, confirmation)
        return service.founder_decide(
            gate_id, command.decision, command.note, command.actor
        )

    @app.get("/api/events", response_model=Page[AuditEventView])
    async def events(
        service: Service,
        offset: Offset = 0,
        limit: Limit = 50,
        from_time: str | None = None,
        to_time: str | None = None,
        project_id: int | None = None,
        task_id: int | None = None,
        run_id: int | None = None,
        agent_id: str | None = None,
        provider: str | None = None,
        action: str | None = None,
        outcome: Literal["success", "failure", "pending", "info"] | None = None,
    ) -> Page[AuditEventView]:
        rows = service.audit_events(
            from_time=from_time,
            to_time=to_time,
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            agent_id=agent_id,
            provider=provider,
            action=action,
            outcome=outcome,
        )
        return _page(rows, offset, limit)

    @app.get("/api/settings", response_model=SettingsView)
    async def settings(service: Service) -> SettingsView:
        return service.settings()

    @app.post(
        "/api/settings/{key}", response_model=RuntimeSettingView
    )
    async def update_runtime_setting(
        key: str,
        command: RuntimeSettingCommand,
        service: Service,
        confirmation: Confirmation = None,
    ) -> RuntimeSettingView:
        _require_confirmation(command, confirmation)
        return service.update_runtime_setting(key, command.value)

    @app.post("/api/github/preview", response_model=dict[str, Any])
    async def github_preview(
        command: GitHubPreviewCommand,
        service: Service,
        confirmation: Confirmation = None,
    ) -> dict[str, Any]:
        _require_confirmation(command, confirmation)
        return service.preview_github_sync(
            command.repo, command.backlog_path, command.existing_issues
        )

    @app.get("/api/integrations", response_model=list[IntegrationStatus])
    async def integrations(service: Service) -> list[IntegrationStatus]:
        provider_states = service.providers()
        unhealthy = sum(item.status not in {"ready", "disabled"} for item in provider_states)
        return [
            IntegrationStatus(
                name="providers",
                status="ready" if unhealthy == 0 else "degraded",
                detail=f"{unhealthy} configured providers unavailable or unhealthy",
            ),
            IntegrationStatus(
                name="github",
                status="unconfigured",
                detail="Repository context is supplied only to explicit dry-run sync requests",
            ),
        ]

    @app.get("/api/control/actions", response_model=list[dict[str, Any]])
    async def control_actions(tenant_id: str, _: None = Depends(require_api_auth)) -> list[dict[str, Any]]:
        storage = SQLiteStorage(database)
        try:
            return HumanControlPlaneService(storage).list_actions(tenant_id)
        finally:
            storage.close()

    @app.post("/api/control/actions", response_model=dict[str, Any], status_code=201)
    async def control_action(command: ControlActionCommand, _: None = Depends(require_api_auth)) -> dict[str, Any]:
        storage = SQLiteStorage(database)
        try:
            return HumanControlPlaneService(storage).act(**command.model_dump())
        finally:
            storage.close()

    @app.get("/", include_in_schema=False)
    async def dashboard_shell() -> FileResponse:
        return FileResponse(static_directory / "index.html")

    return app
