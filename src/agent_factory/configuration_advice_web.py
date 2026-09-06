"""Bounded read-only advice behind Core's existing local authentication."""
import json
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from .configuration_advice import advise
from .http_auth import LocalAccess, LocalHTTPBoundary


def install_routes(app):
    if not isinstance(getattr(app.state, "local_access", None), LocalAccess) or not any(m.cls is LocalHTTPBoundary for m in app.user_middleware):
        raise ValueError("Advice requires the Core local HTTP boundary")
    if getattr(app.state, "configuration_advice_installed", False):
        raise ValueError("Advice routes already installed")

    @app.post("/api/configuration-advice")
    async def configuration_advice(request: Request):
        principal = request.state.local_principal
        if principal is None or not ({"local", "*"} & principal.tenants):
            raise HTTPException(403, "advice_access_denied")
        if request.query_params:
            raise HTTPException(400, "invalid_advice_request")
        body = bytearray()
        try:
            async for chunk in request.stream():
                if len(body) + len(chunk) > 40000: raise ValueError()
                body.extend(chunk)
            command = json.loads(body)
            if not isinstance(command, dict) or set(command) != {"fields", "report"}: raise ValueError()
            result = advise(**command)
        except (ValueError, TypeError, RecursionError, OverflowError):
            raise HTTPException(400, "invalid_advice_request") from None
        return JSONResponse(result, headers={"Cache-Control":"no-store"})

    app.state.configuration_advice_installed = True
