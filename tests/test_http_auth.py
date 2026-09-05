"""Synthetic access matrix; no real credential or private reproduction data."""
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from agent_factory.http_auth import COOKIE, LocalAccess, Policy, trusted_origin
from agent_factory.web import create_app

TOKEN = 'synthetic-local-test-credential'


class LocalHttpAccessTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'AGENT_FACTORY_API_TOKEN': TOKEN, 'AGENT_FACTORY_API_ACTOR': 'Founder',
            'AGENT_FACTORY_API_ROLE': 'operations_owner',
            'AGENT_FACTORY_API_SCOPES': 'read,write,approve,control',
            'AGENT_FACTORY_API_TENANTS': 'a', 'AGENT_FACTORY_SESSION_TTL_SECONDS': '900',
        })
        self.env.start(); self.addCleanup(self.env.stop)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.db = self.root/'state.db'
        self.app = create_app(self.root, self.db)
        self.client = TestClient(self.app, base_url='http://localhost')
        self.addCleanup(self.client.close)
        self.headers = {'Authorization': f'Bearer {TOKEN}', 'X-Agent-Factory-Confirm': 'true'}

    def login(self):
        return self.client.post('/auth/session', headers={'X-Agent-Factory-Session':'true', 'Origin':'http://localhost'}, json={'token':TOKEN})

    def test_every_api_route_authenticates_before_validation_or_storage(self):
        count = 0
        for route in self.app.routes:
            if not route.path.startswith('/api'):
                continue
            for method in route.methods:
                path = re.sub(r'\{[^}]+\}', '1', route.path)
                for headers in ({}, {'Authorization':'Bearer incorrect'}):
                    with self.subTest(path=path, method=method, headers=bool(headers)):
                        response = self.client.request(method, path, headers=headers)
                        self.assertEqual(response.status_code, 401, response.text)
                        self.assertNotIn(TOKEN, response.text)
                count += 1
        self.assertGreater(count, 40)
        self.assertFalse(self.db.exists(), 'Unauthorized requests must not instantiate a storage service')

    def test_read_write_approval_and_control_scopes_are_separate(self):
        cases = [('GET','/api/settings','write'), ('POST','/api/work-items/1/runs','read'),
                 ('POST','/api/founder-decisions/1','write'), ('POST','/api/artifacts/1/review','write'),
                 ('POST','/api/control/actions','write')]
        for method,path,scope in cases:
            with self.subTest(path=path), patch.dict(os.environ, {'AGENT_FACTORY_API_SCOPES':scope}):
                self.assertEqual(self.client.request(method,path,headers=self.headers).status_code,403)
        self.assertFalse(self.db.exists())

    def test_live_browser_session_is_httponly_and_revoked_on_logout(self):
        response=self.login(); self.assertEqual(response.status_code,200)
        cookie=self.client.cookies.get(COOKIE)
        self.assertNotEqual(cookie,TOKEN)
        self.assertIn('HttpOnly',response.headers['set-cookie'])
        self.assertIn('SameSite=strict',response.headers['set-cookie'])
        self.assertEqual(self.client.get('/api/openapi.json').status_code,200)
        self.assertNotIn(COOKIE, self.app.state.local_access.sessions)
        self.assertNotIn(cookie, self.app.state.local_access.sessions)
        self.assertEqual(self.client.delete('/auth/session',headers={'X-Agent-Factory-Session':'true'}).status_code,200)
        self.client.cookies.set(COOKIE,cookie)
        self.assertEqual(self.client.get('/api/openapi.json').status_code,401)

    def test_expiry_and_policy_changes_revoke_existing_session(self):
        clock=[1.0]; self.app.state.local_access.clock=lambda:clock[0]
        self.assertEqual(self.login().status_code,200)
        clock[0]=901.0
        self.assertEqual(self.client.get('/api/settings').status_code,401)
        self.login()
        with patch.dict(os.environ,{'AGENT_FACTORY_API_ROLE':'mission_owner'}):
            self.assertEqual(self.client.get('/api/settings').status_code,401)
        self.login()
        with patch.dict(os.environ,{'AGENT_FACTORY_API_TOKEN':'rotated-synthetic'}):
            self.assertEqual(self.client.get('/api/settings').status_code,401)
            self.assertEqual(self.client.get('/api/settings',headers=self.headers).status_code,401)
        with patch.dict(os.environ,{'AGENT_FACTORY_API_TOKEN':''}):
            self.assertEqual(self.client.get('/api/settings').status_code,503)

    def test_restart_invalidates_session_and_bad_bearer_never_falls_back(self):
        self.login(); cookie=self.client.cookies.get(COOKIE)
        self.assertEqual(self.client.get('/api/settings',headers={'Authorization':'Bearer wrong'}).status_code,401)
        replacement=LocalAccess()
        self.assertIsNone(replacement.authenticate(Policy.environment(),None,cookie))

    def test_host_and_origin_are_checked_for_api_static_and_session(self):
        for path in ['/api/openapi.json','/','/assets/login.html','/auth/session']:
            for header in [{'Host':'example.invalid'},{'Origin':'https://example.invalid'},
                           {'Origin':'http://localhost:9999'},{'Origin':'null'},
                           {'Host':'localhost#'},{'Origin':'http://localhost:0'}]:
                with self.subTest(path=path,header=header):
                    self.assertEqual(self.client.get(path,headers=self.headers|header).status_code,403)
        self.assertFalse(trusted_origin('http','localhost','http://localhost/'))
        self.assertTrue(trusted_origin('http','localhost:80','http://localhost'))
        self.assertTrue(trusted_origin('http','[::1]:8000','http://[::1]:8000'))
        self.assertEqual(self.client.get('/api/openapi.json',headers=[('Host','localhost'),('Host','example.invalid')]).status_code,403)

    def test_login_requires_explicit_intent_and_never_echoes_invalid_input(self):
        self.assertEqual(self.client.post('/auth/session',json={'token':TOKEN}).status_code,403)
        for data in [{'token':TOKEN,'actor':'Impersonation'}, {'token':[TOKEN]}, {'other':TOKEN}]:
            response=self.client.post('/auth/session',headers={'X-Agent-Factory-Session':'true'},json=data)
            self.assertEqual(response.status_code,400); self.assertNotIn(TOKEN,response.text)
        self.assertEqual(self.client.post('/auth/session',headers={'X-Agent-Factory-Session':'true'},content='x'*4097).status_code,400)
        response=self.client.post('/auth/session',headers={'X-Agent-Factory-Session':'true'},json={'token':'wrong'})
        self.assertEqual(response.status_code,401)

    def test_authenticated_control_identity_tenant_and_confirmation(self):
        command=dict(tenant_id='a',actor='Founder',role='operations_owner',action='emergency_stop',target_type='mission',target_id='fixture',confirmed=True)
        for change in [{'actor':'Another'},{'role':'mission_owner'},{'tenant_id':'b'}]:
            response=self.client.post('/api/control/actions',headers=self.headers,json=command|change)
            self.assertEqual(response.status_code,403,response.text)
        self.assertEqual(self.client.post('/api/control/actions',headers={'Authorization':f'Bearer {TOKEN}'},json=command).status_code,400)
        self.assertEqual(self.client.post('/api/control/actions',headers=self.headers,json=command).status_code,201)
        self.assertEqual(self.client.get('/api/control/actions?tenant_id=b',headers=self.headers).status_code,403)
        rows=self.client.get('/api/control/actions?tenant_id=a',headers=self.headers).json()
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['actor'],'Founder')

    def test_founder_identity_cannot_be_claimed_in_body(self):
        with patch.dict(os.environ, {'AGENT_FACTORY_API_ACTOR':'Ops'}):
            response=self.client.post('/api/founder-decisions/1',headers=self.headers,json={'actor':'Founder','decision':'approved','confirmed':True})
            self.assertEqual(response.status_code,403,response.text)

    def test_authenticated_access_still_requires_existing_human_gate(self):
        response=self.client.post('/api/settings/max_concurrent_runs',headers={'Authorization':f'Bearer {TOKEN}'},json={'confirmed':True,'value':1})
        self.assertEqual(response.status_code,400)

    def test_shell_login_and_no_store_do_not_expose_configuration(self):
        response=self.client.get('/'); self.assertIn('Operator access token',response.text)
        self.assertNotIn(TOKEN,response.text); self.assertEqual(response.headers['cache-control'],'no-store')
        self.login(); response=self.client.get('/'); self.assertNotIn('Operator access token',response.text)
        self.assertEqual(response.headers['x-frame-options'],'DENY')

    def test_local_open_mode_remains_loopback_only_and_is_explicit(self):
        with patch.dict(os.environ,{'AGENT_FACTORY_API_TOKEN':''}):
            with TestClient(create_app(self.root,self.db),base_url='http://localhost') as client:
                state=client.get('/auth/session').json()
                self.assertFalse(state['authentication_required']);self.assertTrue(state['authenticated'])
                self.assertEqual(client.get('/api/openapi.json').status_code,200)
                self.assertEqual(client.get('/api/openapi.json',headers={'Host':'example.invalid'}).status_code,403)
