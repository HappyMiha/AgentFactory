"""Explicit local hardware scan, composed into the existing Core HTTP boundary."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import threading
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict

from .hardware_inventory import collect_inventory
from .http_auth import LocalAccess, LocalHTTPBoundary


# The machine is shared even when multiple workspaces have HTTP applications.
# A busy caller gets an explicit response; it never queues another scan.
_SCAN_LOCK = threading.Lock()


class HardwareScanCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")


def install_routes(
    app: FastAPI,
    workspace: Path,
    *,
    collector: Callable[[Path], dict[str, Any]] | None = None,
) -> None:
    """Install once before startup; trusted composition supplies the workspace.

    ``collector`` is a host-side test seam, never an HTTP-selectable command.
    Core010 owns the default ``create_app`` call and settings navigation.
    """
    if not isinstance(getattr(app.state, "local_access", None), LocalAccess) or not any(
        middleware.cls is LocalHTTPBoundary for middleware in app.user_middleware
    ):
        raise ValueError("Hardware routes require the Core local HTTP boundary")
    if getattr(app.state, "hardware_routes_installed", False):
        raise ValueError("Hardware routes are already installed")
    root = Path(workspace).expanduser().resolve()
    scan = collector if collector is not None else collect_inventory
    static = Path(__file__).resolve().parent / "static"

    @app.get("/hardware", include_in_schema=False)
    async def hardware_page(request: Request) -> FileResponse:
        name = "hardware.html" if request.state.local_principal else "login.html"
        return FileResponse(static / name, headers={"Cache-Control": "no-store"})

    # FastAPI dispatches this synchronous handler on its worker pool. Bounded
    # OS probes must never run on the HTTP event loop or block home navigation.
    @app.post("/api/hardware/scan")
    def hardware_scan(request: Request, command: HardwareScanCommand) -> JSONResponse:
        if request.query_params:
            return JSONResponse({"error": {"code": "hardware_parameters_not_allowed"}}, status_code=400)
        if not _SCAN_LOCK.acquire(blocking=False):
            return JSONResponse({"error": {"code": "hardware_scan_in_progress"}}, status_code=409)
        try:
            report = scan(root)
            return JSONResponse(report, headers={"Cache-Control": "no-store"})
        except Exception:
            # Driver errors can contain machine paths or other private text.
            # The collector supplies field-level unknowns for expected failures.
            return JSONResponse({"error": {"code": "hardware_scan_failed"}}, status_code=503)
        finally:
            _SCAN_LOCK.release()

    app.state.hardware_routes_installed = True
