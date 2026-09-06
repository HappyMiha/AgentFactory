"""Owner-bound local manual planning, through the existing HTTP boundary."""
import asyncio
from contextlib import closing
import json
from pathlib import Path
from typing import Annotated
from fastapi import HTTPException, Request, Query, Path as APIPath
from fastapi.responses import FileResponse, JSONResponse
from .game_planning import GamePlanning, PlanningConflict, GENRES, template
from .http_auth import LocalAccess, LocalHTTPBoundary
from .local_games import local_games_lock
from .storage import SQLiteStorage


MissionId=Annotated[int,APIPath(ge=1,le=9223372036854775807)]

def install_routes(app, database):
    if not isinstance(getattr(app.state,'local_access',None),LocalAccess) or not any(m.cls is LocalHTTPBoundary for m in app.user_middleware):
        raise ValueError('Game planning requires the Core local HTTP boundary')
    if getattr(app.state,'game_planning_routes_installed',False):
        raise ValueError('Game planning routes already installed')
    static=Path(__file__).parent/'static'

    def call(request, operation):
        principal=request.state.local_principal
        if principal is None or not ({'local','*'} & principal.tenants):
            raise HTTPException(403,'planning_access_denied')
        try:
            with local_games_lock(database):storage=SQLiteStorage(database)
            with closing(storage):result=operation(GamePlanning(storage),principal.actor)
            return JSONResponse(result,headers={'Cache-Control':'no-store'})
        except KeyError:raise HTTPException(404,'plan_not_found') from None
        except PlanningConflict as error:raise HTTPException(409,str(error)) from None
        except ValueError:raise HTTPException(400,'invalid_plan_request') from None

    @app.get('/planning/{mission_id}',include_in_schema=False)
    async def page(mission_id: MissionId,request: Request):
        return FileResponse(static/('game-plan.html' if request.state.local_principal else 'login.html'),headers={'Cache-Control':'no-store'})

    @app.get('/api/game-planning/{mission_id}')
    def view(mission_id: MissionId,request: Request,revision_id: int | None=Query(None,ge=1,le=9223372036854775807)):
        if set(request.query_params)-{'revision_id'}:raise HTTPException(400,'invalid_plan_request')
        return call(request,lambda service,actor: service.view(mission_id,actor,revision_id)|{'templates':{genre:template(genre) for genre in GENRES}})

    @app.post('/api/game-planning/{mission_id}')
    async def save(mission_id: MissionId,request: Request):
        if request.query_params or request.headers.get('X-Agent-Factory-Confirm')!='true':
            raise HTTPException(400,'confirmation_required')
        body=bytearray()
        try:
            async for chunk in request.stream():
                if len(body)+len(chunk)>80000:raise ValueError()
                body.extend(chunk)
            command=json.loads(body)
            if not isinstance(command,dict) or set(command)!={'fields','command_id','expected_revision_id','expected_source_digest','confirmed'} or command.pop('confirmed') is not True:
                raise ValueError()
        except (ValueError,TypeError,RecursionError):raise HTTPException(400,'invalid_plan_request') from None
        return await asyncio.to_thread(call,request,lambda service,actor:service.save(mission_id,actor,**command))

    app.state.game_planning_routes_installed=True
