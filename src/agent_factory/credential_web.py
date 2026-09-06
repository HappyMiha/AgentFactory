"""Dedicated bounded secret entry; values never appear in API response models."""
import asyncio
import json
import os
from pathlib import Path
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse
from .credential_connections import CredentialConnections
from .connector_eligibility import CREDENTIAL_ROUTES, request_setup_decision
from .eligibility_web import install_routes as install_eligibility_routes
from .provider_connection_catalog import connection_catalog


def install_routes(app, workspace: Path, *, store=None):
    service = CredentialConnections(workspace / '.agent-factory' / 'credential-connections.db', store=store)
    static = Path(__file__).parent / 'static'
    install_eligibility_routes(app)

    def owner(request, mutation=False):
        p = request.state.local_principal
        if p is None or p.role != 'operations_owner' or not ({'read'} if not mutation else {'write','control'}) <= p.scopes:
            raise PermissionError()
        if 'local' not in p.tenants and '*' not in p.tenants:
            raise PermissionError()
        if mutation and request.headers.get('X-Agent-Factory-Confirm') != 'true':
            raise PermissionError()
        return {'actor': p.actor, 'tenant': 'local'}

    def response(body, status=200):
        return JSONResponse(body, status_code=status, headers={'Cache-Control':'no-store'})

    @app.get('/settings/credentials', include_in_schema=False)
    async def page():
        return FileResponse(static / 'credentials.html')

    @app.get('/api/credential-connections')
    async def listing(request: Request):
        try:
            scope = owner(request)
            values = await asyncio.to_thread(service.list, **scope)
            decisions = {provider: request_setup_decision(request, provider, workspace=workspace, **scope) for provider in CREDENTIAL_ROUTES}
            return response({'connections':values, 'supported':os.name == 'nt' or store is not None,
                             'setup': decisions, 'catalog': connection_catalog()})
        except PermissionError:
            return response({'error':'connection_access_denied'},403)
        except Exception:
            return response({'error':'connection_store_unavailable'},503)

    @app.post('/api/credential-connections')
    async def connect(request: Request):
        try:
            scope = owner(request, True)
        except PermissionError:
            return response({'error':'connection_access_denied'},403)
        # Check trusted eligibility before reading a body that can contain a key.
        decisions = {provider: request_setup_decision(request, provider, workspace=workspace, **scope) for provider in CREDENTIAL_ROUTES}
        if not any(value['allowed'] for value in decisions.values()):
            return response({'error': 'connector_eligibility_required', 'guide': '/access-guide'}, 403)
        body = bytearray()
        try:
            async for chunk in request.stream():
                if len(body) + len(chunk) > 4096:
                    return response({'error':'invalid_connection_request'},400)
                body.extend(chunk)
            data = json.loads(body)
            if (not isinstance(data, dict) or set(data) != {'provider','secret','confirmed'}
                    or data['confirmed'] is not True or data['provider'] not in ('openai','anthropic')
                    or not isinstance(data['secret'],str) or '\x00' in data['secret']
                    or not 12 <= len(data['secret'].encode('utf-8')) <= 2048):
                raise ValueError()
        except (ValueError,TypeError,KeyError,RecursionError):
            return response({'error':'invalid_connection_request'},400)
        finally:
            body[:] = b'\x00' * len(body)
        try:
            # Re-resolve the specific route after bounded input; revocation is not cached.
            if not request_setup_decision(request, data['provider'], workspace=workspace, **scope)['allowed']:
                return response({'error': 'connector_eligibility_required', 'guide': '/access-guide'}, 403)
            result = await asyncio.to_thread(service.connect, **scope, provider=data['provider'], secret=data['secret'])
            return response(result,201)
        except Exception:
            return response({'error':'connection_store_unavailable'},503)
        finally:
            data.clear()

    @app.delete('/api/credential-connections/{reference}')
    async def disconnect(reference: str, request: Request):
        try:
            scope = owner(request, True)
            return response(await asyncio.to_thread(service.disconnect, reference, **scope))
        except PermissionError:
            return response({'error':'connection_access_denied'},403)
        except Exception:
            return response({'error':'connection_store_unavailable'},503)
