"""Installation review behind the existing local HTTP authority."""
import asyncio
from contextlib import closing
import json
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from .game_planning import PlanningConflict
from .game_planning_web import MissionId
from .http_auth import LocalAccess, LocalHTTPBoundary
from .installation_review import InstallationConflict, InstallationReview
from .local_games import local_games_lock
from .storage import SQLiteStorage


def install_routes(app, database, workspace):
    if not isinstance(getattr(app.state, 'local_access', None), LocalAccess) or not any(m.cls is LocalHTTPBoundary for m in app.user_middleware):
        raise ValueError('Installation review requires the Core HTTP boundary')
    if getattr(app.state, 'installation_review_installed', False):
        raise ValueError('Installation review already installed')
    static = Path(__file__).parent / 'static'

    def principal(request, *, decide=False):
        who = request.state.local_principal
        if who is None or not ({'local', '*'} & who.tenants):
            raise HTTPException(403, 'installation_access_denied')
        if decide and (not request.state.local_policy.token or 'approve' not in who.scopes
                       or who.role not in {'operations_owner', 'mission_owner'}):
            raise HTTPException(403, 'installation_approval_access_denied')
        return who

    def call(request, operation):
        who = principal(request)
        try:
            with local_games_lock(database):
                storage = SQLiteStorage(database)
            with closing(storage):
                result = operation(InstallationReview(storage, workspace), who.actor)
            return JSONResponse(result, headers={'Cache-Control': 'no-store'})
        except KeyError:
            raise HTTPException(404, 'installation_review_not_found') from None
        except (InstallationConflict, PlanningConflict) as error:
            raise HTTPException(409, str(error)) from None
        except (ValueError, TypeError, OverflowError):
            raise HTTPException(400, 'invalid_installation_request') from None
        except OSError:
            raise HTTPException(503, 'installation_observation_unavailable') from None

    async def body(request):
        if request.query_params or request.headers.get('X-Agent-Factory-Confirm') != 'true':
            raise HTTPException(400, 'confirmation_required')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate_field')
                result[key] = value
            return result
        data = bytearray()
        try:
            async for chunk in request.stream():
                if len(data) + len(chunk) > 4096:
                    raise ValueError('too_large')
                data.extend(chunk)
            result = json.loads(data, object_pairs_hook=unique)
            if not isinstance(result, dict):
                raise ValueError('invalid_shape')
            return result
        except (ValueError, TypeError, RecursionError):
            raise HTTPException(400, 'invalid_installation_request') from None

    @app.get('/installation/{mission_id}', include_in_schema=False)
    async def page(mission_id: MissionId, request: Request):
        return FileResponse(static / ('installation.html' if request.state.local_principal else 'login.html'), headers={'Cache-Control': 'no-store'})

    @app.get('/api/installation-plans/{mission_id}')
    def view(mission_id: MissionId, request: Request):
        if request.query_params:
            raise HTTPException(400, 'invalid_installation_request')
        allowed = bool(request.state.local_policy.token and request.state.local_principal
                       and 'approve' in request.state.local_principal.scopes
                       and request.state.local_principal.role in {'operations_owner', 'mission_owner'})
        return call(request, lambda service, actor: service.view(mission_id, actor) | {'can_decide': allowed})

    @app.post('/api/installation-plans/{mission_id}')
    async def prepare(mission_id: MissionId, request: Request):
        principal(request)
        command = await body(request)
        if set(command) != {'command_id', 'offline'}:
            raise HTTPException(400, 'invalid_installation_request')
        return await asyncio.to_thread(call, request, lambda service, actor: service.prepare(mission_id, actor, **command))

    @app.post('/api/approvals/installation/{mission_id}')
    async def decide(mission_id: MissionId, request: Request):
        principal(request, decide=True)
        command = await body(request)
        if set(command) != {'command_id', 'plan_id', 'digest', 'decision'}:
            raise HTTPException(400, 'invalid_installation_request')
        return await asyncio.to_thread(call, request, lambda service, actor: service.decide(mission_id, actor, **command))

    app.state.installation_review_installed = True
