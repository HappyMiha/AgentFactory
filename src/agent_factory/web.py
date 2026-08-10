"""Loopback-only FastAPI host for the Local Control Center."""

import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any, Generic, TypeVar

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
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


Offset = Annotated[int, Query(ge=0, le=1_000_000)]
Limit = Annotated[int, Query(ge=1, le=200)]


def validate_loopback_host(host: str) -> str:
    normalized = host.strip().lower()
    allowed = {"127.0.0.1", "localhost", "::1"}
    if normalized not in allowed:
        raise ValueError("Local Control Center must bind to a loopback host")
    return normalized


def _page(items: list[T], offset: int, limit: int) -> Page[T]:
    return Page(items=items[offset : offset + limit], offset=offset, limit=limit, total=len(items))


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

    @app.get("/api/projects", response_model=Page[ProjectView])
    async def projects(service: Service, offset: Offset = 0, limit: Limit = 50) -> Page[ProjectView]:
        return _page(service.projects(), offset, limit)

    @app.get("/api/work-items", response_model=Page[WorkItemView])
    async def work_items(
        service: Service,
        offset: Offset = 0,
        limit: Limit = 50,
        project_id: int | None = None,
    ) -> Page[WorkItemView]:
        return _page(service.work_items(project_id), offset, limit)

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

    return app
