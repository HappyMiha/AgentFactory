"""Server-side SSO client: one-time codes, PKCE and centrally revocable sessions.

Only browser session references live here. Users, passwords, invitations and
organization membership live exclusively in the identity service.
"""
from contextlib import closing
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlencode
from urllib.request import Request as URLRequest, urlopen

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from .http_auth import COOKIE, LocalAccess, Principal


def challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')


class SsoAccess(LocalAccess):
    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.client = os.environ['LOKVETIA_SSO_CLIENT']
        self.origin = os.environ['LOKVETIA_SSO_ORIGIN'].rstrip('/')
        self.identity = os.environ['LOKVETIA_IDENTITY_ORIGIN'].rstrip('/')
        self.internal = os.environ['LOKVETIA_IDENTITY_INTERNAL'].rstrip('/')
        self.secret = Path(os.environ['LOKVETIA_SSO_SECRET_FILE']).read_text().strip()
        if len(self.secret) < 32 or not self.identity.startswith('https://') or not self.origin.startswith('https://'):
            raise ValueError('Invalid SSO service configuration')
        self.organization = os.environ.get('LOKVETIA_ORGANIZATION', 'lokvetia')
        with closing(self.connect()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sso_transactions (
                    state TEXT PRIMARY KEY, verifier TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sso_sessions (
                    hash TEXT PRIMARY KEY, grant_token TEXT NOT NULL, expires REAL NOT NULL);
            ''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def remote(self, operation, data):
        request = URLRequest(self.internal + '/backchannel/' + operation,
            data=json.dumps(dict(data, client_id=self.client)).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.secret,
                     'Host': 'identity.internal'}, method='POST')
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def begin(self):
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        with closing(self.connect()) as db, db:
            db.execute('DELETE FROM sso_transactions WHERE expires<=?', (time.time(),))
            db.execute('INSERT INTO sso_transactions VALUES (?,?,?)', (self.key(state), verifier, time.time() + 300))
        return state, self.identity + '/authorize?' + urlencode(dict(client_id=self.client,
            redirect_uri=self.origin + '/auth/sso/callback', state=state, code_challenge=challenge(verifier)))

    def finish(self, state, code):
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT verifier FROM sso_transactions WHERE state=? AND expires>?',
                             (self.key(state), time.time())).fetchone()
            if not row:
                raise ValueError('Sign-in request expired; start again')
            db.execute('DELETE FROM sso_transactions WHERE state=?', (self.key(state),))
        result = self.remote('token', dict(code=code, code_verifier=row[0], redirect_uri=self.origin + '/auth/sso/callback'))
        token = 'sso.' + secrets.token_urlsafe(32)
        expires = min(float(result['expires']), time.time() + 30 * 86400)
        with closing(self.connect()) as db, db:
            db.execute('DELETE FROM sso_sessions WHERE expires<=?', (time.time(),))
            db.execute('INSERT INTO sso_sessions VALUES (?,?,?)', (self.key(token), result['token'], expires))
        return token, max(1, int(expires - time.time()))

    def grant(self, cookie):
        with closing(self.connect()) as db:
            row = db.execute('SELECT grant_token FROM sso_sessions WHERE hash=? AND expires>?',
                             (self.key(cookie), time.time())).fetchone()
        return row[0] if row else None

    def authenticate(self, policy, authorization, cookie):
        if authorization is not None or not cookie or not cookie.startswith('sso.'):
            return super().authenticate(policy, authorization, cookie)
        token = self.grant(cookie)
        if not token:
            return None
        try:
            result = self.remote('introspect', {'token': token})
        except (OSError, ValueError):
            return None  # Never grant cached authority when the identity server cannot confirm it.
        if not result.get('active') or result.get('organization') != self.organization:
            return None
        data = result['principal']
        scopes = frozenset(data['scopes']) & policy.principal.scopes
        tenants = frozenset(data['tenants'])
        if '*' not in policy.principal.tenants:
            tenants = policy.principal.tenants if '*' in tenants else tenants & policy.principal.tenants
        return Principal(data['actor'], data['role'], scopes, tenants) if scopes and tenants else None

    def logout(self, cookie):
        if cookie and cookie.startswith('sso.'):
            token = self.grant(cookie)
            if token:
                self.remote('logout', {'token': token})
            with closing(self.connect()) as db, db:
                db.execute('DELETE FROM sso_sessions WHERE hash=?', (self.key(cookie),))
        super().logout(cookie)


def access_for_workspace(path):
    return SsoAccess(path / 'sso-sessions.sqlite3') if os.environ.get('LOKVETIA_SSO_CLIENT') else LocalAccess()


def install_routes(app, access):
    @app.get('/auth/account', include_in_schema=False)
    @app.get('/profile', include_in_schema=False)
    async def profile():
        return RedirectResponse(access.identity + '/profile' if isinstance(access, SsoAccess) else '/login', status_code=303)

    @app.get('/organizations', include_in_schema=False)
    async def organizations():
        return RedirectResponse(access.identity + '/organizations' if isinstance(access, SsoAccess) else '/login', status_code=303)

    @app.get('/register', include_in_schema=False)
    async def register():
        return RedirectResponse(access.identity + '/register' if isinstance(access, SsoAccess) else '/login', status_code=303)

    @app.get('/auth/sso/start', include_in_schema=False)
    async def start():
        if not isinstance(access, SsoAccess):
            return JSONResponse({'error': 'Central identity service is not configured'}, status_code=503)
        state, url = await run_in_threadpool(access.begin)
        response = RedirectResponse(url, status_code=303)
        response.set_cookie('lokvetia_sso_state', state, max_age=300, secure=True, httponly=True, samesite='lax', path='/auth/sso')
        return response

    @app.get('/auth/sso/callback', include_in_schema=False)
    async def callback(request: Request):
        if not isinstance(access, SsoAccess):
            return JSONResponse({'error': 'SSO unavailable'}, status_code=503)
        state = request.query_params.get('state', '')
        cookie_state = request.cookies.get('lokvetia_sso_state', '')
        if not state or not secrets.compare_digest(state, cookie_state):
            return JSONResponse({'error': 'Sign-in state did not match; start again'}, status_code=400)
        try:
            token, ttl = await run_in_threadpool(access.finish, state, request.query_params.get('code', ''))
        except (OSError, ValueError, KeyError):
            return JSONResponse({'error': 'Sign-in expired or identity service is unavailable; start again'}, status_code=400)
        response = RedirectResponse('/', status_code=303)
        response.set_cookie(COOKIE, token, max_age=ttl, secure=True, httponly=True, samesite='lax', path='/')
        response.delete_cookie('lokvetia_sso_state', path='/auth/sso', secure=True, httponly=True, samesite='lax')
        return response
