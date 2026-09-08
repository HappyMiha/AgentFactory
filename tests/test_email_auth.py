from contextlib import closing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from agent_factory.email_auth import Accounts, EmailAccess
from agent_factory.http_auth import COOKIE, Policy, Principal
from agent_factory.identity_service import create_identity_app
from agent_factory.sso import challenge


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'accounts.sqlite3'
        self.env = patch.dict(os.environ, {'AGENT_FACTORY_API_TOKEN': 'operator-secret-' * 4,
            'AGENT_FACTORY_API_ACTOR': 'existing-owner', 'AGENT_FACTORY_API_ROLE': 'operations_owner',
            'AGENT_FACTORY_API_SCOPES': 'read,write,approve,control', 'AGENT_FACTORY_API_TENANTS': '*'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.policy = Policy.environment()
        self.accounts = Accounts(self.path)
        self.email = 'owner@example.com'
        self.password = 'a long unique test password'
        invitation = self.accounts.invite(self.email, self.policy.principal)
        self.accounts.register(self.email, self.password, invitation)

    def test_remembered_session_survives_new_service_instance(self):
        token, ttl = self.accounts.login(self.email, self.password, self.policy, remember=True)
        self.assertEqual(ttl, 30 * 86400)
        reloaded = Accounts(self.path)
        self.assertEqual(reloaded.authenticate(token, self.policy).actor, 'existing-owner')
        reloaded.logout(token)
        self.assertIsNone(self.accounts.authenticate(token, self.policy))

    def test_registration_requires_invitation_for_exact_email(self):
        invitation = self.accounts.invite('invited@example.com', self.policy.principal)
        with self.assertRaises(ValueError):
            self.accounts.register('other@example.com', self.password, invitation)
        self.accounts.register('invited@example.com', self.password, invitation)
        with self.assertRaises(ValueError):
            self.accounts.register('invited@example.com', self.password, invitation)

    def test_invalid_explicit_bearer_cannot_use_valid_cookie(self):
        token, _ = self.accounts.login(self.email, self.password, self.policy)
        access = EmailAccess(self.path)
        self.assertIsNone(access.authenticate(self.policy, 'Bearer wrong', token))

    def test_wrong_password_is_rejected(self):
        with self.assertRaises(ValueError):
            self.accounts.login(self.email, 'wrong-password', self.policy)

    def test_password_and_cookie_are_not_stored_as_plaintext(self):
        token, _ = self.accounts.login(self.email, self.password, self.policy)
        raw = self.path.read_bytes()
        self.assertNotIn(self.password.encode(), raw)
        self.assertNotIn(token.encode(), raw)

    def test_sso_code_binds_client_pkce_redirect_and_is_one_time(self):
        clients = {'core': dict(origin='https://test.lokvetia.com', name='Core', secret='core-secret-' * 4),
                   'cloud': dict(origin='https://test.lokiravia.com', name='Cloud', secret='cloud-secret-' * 4)}
        app = create_identity_app(Path(self.folder.name), clients)
        with TestClient(app, base_url='http://localhost') as browser:
            token, _ = self.accounts.login(self.email, self.password, self.policy)
            browser.cookies.set(COOKIE, token)
            verifier = 'v' * 64
            response = browser.get('/authorize', params=dict(client_id='core', redirect_uri='https://test.lokvetia.com/auth/sso/callback',
                state='s' * 43, code_challenge=challenge(verifier)), follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            code = parse_qs(urlsplit(response.headers['location']).query)['code'][0]
            headers = {'Authorization': 'Bearer ' + clients['core']['secret'], 'Host': 'localhost'}
            body = dict(client_id='core', code=code, code_verifier='x' * 64, redirect_uri='https://test.lokvetia.com/auth/sso/callback')
            self.assertEqual(browser.post('/backchannel/token', json=body, headers=headers).status_code, 400)
            body['code_verifier'] = verifier
            result = browser.post('/backchannel/token', json=body, headers=headers)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(browser.post('/backchannel/token', json=body, headers=headers).status_code, 400)
            grant = result.json()['token']
            introspection = browser.post('/backchannel/introspect', json={'client_id': 'core', 'token': grant}, headers=headers)
            self.assertTrue(introspection.json()['active'])
            browser.post('/backchannel/logout', json={'client_id': 'core', 'token': grant}, headers=headers)
            self.assertFalse(browser.post('/backchannel/introspect', json={'client_id': 'core', 'token': grant}, headers=headers).json()['active'])

    def test_external_redirect_is_never_accepted(self):
        clients = {'core': dict(origin='https://test.lokvetia.com', name='Core', secret='secret' * 10)}
        with TestClient(create_identity_app(Path(self.folder.name), clients), base_url='http://localhost') as browser:
            response = browser.get('/authorize', params=dict(client_id='core', redirect_uri='https://evil.example/callback',
                state='s' * 43, code_challenge=challenge('v' * 64)), follow_redirects=False)
            self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
