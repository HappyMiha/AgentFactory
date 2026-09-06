import json
from pathlib import Path
from unittest.mock import patch
import unittest
from tests import test_credential_web as credentials
from tests.test_connector_eligibility import AT, approval_fixture


class EligibilityWebTests(unittest.TestCase):
    """Use the production app and credential boundary, with synthetic approvals."""
    setUp = credentials.CredentialWebTests.setUp
    post = credentials.CredentialWebTests.post
    def test_default_denial_before_secret_body_read_and_no_identity_submission(self):
        self.app.state.connector_setup_approval=None
        with patch('starlette.requests.Request.stream', side_effect=AssertionError('body must not be read')):
            result=self.post(age_band='adult',guardian_consent=True)
        self.assertEqual(result.status_code,403)
        self.assertEqual(result.json()['error'],'connector_eligibility_required')
        self.assertFalse(self.store.values)
        self.assertFalse((self.root/'.agent-factory').exists())
        for url in ('/access-guide','/api/connector-eligibility'):
            result=self.client.get(url,headers=self.headers)
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.headers['cache-control'],'no-store')
        self.assertFalse((self.root/'.agent-factory').exists())
        self.assertEqual(self.client.post('/api/connector-eligibility',headers=self.headers,json={'age':18}).status_code,405)

    def test_provider_swap_revocation_and_disconnect_remains_available(self):
        self.app.state.connector_setup_approval=lambda **scope: approval_fixture(**(scope | {'provider': 'openai'}))
        self.assertEqual(self.post(provider='anthropic').status_code,403)
        ref=self.post().json()['id']
        self.app.state.connector_setup_approval=None
        self.assertEqual(self.post().status_code,403)
        listing=self.client.get('/api/credential-connections',headers=self.headers).json()
        self.assertFalse(any(x['allowed'] for x in listing['setup'].values()))
        self.assertEqual(listing['connections'][0]['id'],ref)
        self.assertEqual(self.client.delete('/api/credential-connections/'+ref,headers=self.headers).status_code,200)
        self.assertFalse(self.store.values)

    def test_resolver_rechecks_after_body_and_failure_is_redacted(self):
        calls=[]
        def resolve(**scope):
            calls.append(scope)
            return approval_fixture(**scope) if len(calls)<=2 else None
        self.app.state.connector_setup_approval=resolve
        self.assertEqual(self.post().status_code,403)
        self.assertEqual(len(calls),3)
        self.assertEqual(set(calls[0]),{'actor','tenant','provider','workspace'})
        self.assertFalse(self.store.values)
        def broken(**scope):raise RuntimeError(self.secret)
        self.app.state.connector_setup_approval=broken
        result=self.post();self.assertEqual(result.status_code,403)
        self.assertNotIn(self.secret,result.text)

    def test_actual_http_boundary_and_stale_policy(self):
        result=self.client.get('/api/connector-eligibility')
        self.assertEqual(result.status_code,401)
        result=self.client.get('/api/connector-eligibility',headers={**self.headers,'Origin':'https://foreign.example'})
        self.assertEqual(result.status_code,403)
        from datetime import timedelta
        with patch('agent_factory.connector_eligibility.utc_now',return_value=AT+timedelta(days=31)):
            self.assertFalse(self.client.get('/api/connector-eligibility',headers=self.headers).json()['current'])
            self.assertEqual(self.post().status_code,403)
        public=json.dumps(self.client.get('/api/credential-connections',headers=self.headers).json())
        for private in ('synthetic-review','synthetic-jurisdiction',str(self.root),self.secret):self.assertNotIn(private,public)
