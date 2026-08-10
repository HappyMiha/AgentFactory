"""Loopback-only FastAPI host for the Local Control Center."""

import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any, Generic, Literal, TypeVar

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .application import (
    AgentFactoryService,
    AgentView,
    ApprovalView,
    ArtifactView,
    EventView,
    ProjectView,
    ProviderView,
    ReviewView,
    RunView,
    SettingsView,
    WorkItemView,
)
from .storage import SQLiteStorage

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


class RunDetail(BaseModel):
    run: RunView
    artifacts: list[ArtifactView]
    reviews: list[ReviewView]
    approval: ApprovalView | None
    stopped_reason: str


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
        return {"task_id": result.task_id, "worker": result.worker}

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

    @app.get("/api/events", response_model=Page[EventView])
    async def events(
        service: Service, offset: Offset = 0, limit: Limit = 50
    ) -> Page[EventView]:
        rows = service.events(limit=min(10_000, offset + limit))
        return Page(
            items=rows[offset : offset + limit],
            offset=offset,
            limit=limit,
            total=service.storage.db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        )

    @app.get("/api/settings", response_model=SettingsView)
    async def settings(service: Service) -> SettingsView:
        return service.settings()

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

    @app.get("/", include_in_schema=False)
    async def dashboard_shell() -> FileResponse:
        return FileResponse(static_directory / "index.html")

    return app
