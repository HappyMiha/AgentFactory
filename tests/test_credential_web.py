import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from agent_factory.web import create_app
from tests.test_connector_eligibility import AT, approval_fixture
from tests.test_credential_connections import MemoryStore

class CredentialWebTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'AGENT_FACTORY_API_TOKEN':'local-synthetic-token','AGENT_FACTORY_API_ACTOR':'Owner','AGENT_FACTORY_API_ROLE':'operations_owner','AGENT_FACTORY_API_SCOPES':'read,write,control','AGENT_FACTORY_API_TENANTS':'local'})
        self.env.start();self.addCleanup(self.env.stop)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.store=MemoryStore();self.app=create_app(self.root,self.root/'core.db',credential_store=self.store)
        clock=patch('agent_factory.connector_eligibility.utc_now',return_value=AT)
        clock.start();self.addCleanup(clock.stop)
        self.app.state.connector_setup_approval=lambda **scope: approval_fixture(**scope)
        self.client=TestClient(self.app,base_url='http://localhost');self.addCleanup(self.client.close)
        self.headers={'Authorization':'Bearer local-synthetic-token','X-Agent-Factory-Confirm':'true'}
        self.secret='synthetic-web-secret-123456'

    def post(self, **changes):
        data={'provider':'openai','secret':self.secret,'confirmed':True};data.update(changes)
        return self.client.post('/api/credential-connections',headers=self.headers,content=json.dumps(data))

    def test_auth_before_storage_and_strict_redacted_validation(self):
        response=self.client.post('/api/credential-connections',json={'secret':self.secret})
        self.assertEqual(response.status_code,401)
        self.assertFalse((self.root/'.agent-factory').exists())
        for changes in ({'confirmed':1},{'confirmed':'true'},{'provider':self.secret},{'secret':'\ud800'},{'secret':{'value':self.secret}}):
            response=self.post(**changes);self.assertEqual(response.status_code,400)
            self.assertNotIn(self.secret,response.text)
            self.assertEqual(response.headers['cache-control'],'no-store')
        response=self.client.post('/api/credential-connections',headers=self.headers,content='['*3000)
        self.assertEqual(response.status_code,400)
        self.assertFalse(self.store.values)

    def test_saved_reference_list_disconnect_and_no_secret_api(self):
        response=self.post();self.assertEqual(response.status_code,201,response.text);ref=response.json()['id']
        for url in ('/api/credential-connections','/api/openapi.json','/settings/credentials'):
            result=self.client.get(url,headers=self.headers)
            self.assertNotIn(self.secret,result.text)
        self.assertEqual(self.client.get('/api/credential-connections/'+ref,headers=self.headers).status_code,405)
        result=self.client.delete('/api/credential-connections/'+ref,headers=self.headers)
        self.assertEqual(result.status_code,200);self.assertEqual(result.json()['status'],'revoked')
        self.assertFalse(self.store.values)
        self.assertNotIn(self.secret,json.dumps(result.json()))

    def test_mutation_needs_control_role_and_confirmation_and_tenant(self):
        for overrides in ({'AGENT_FACTORY_API_SCOPES':'read,write'},{'AGENT_FACTORY_API_ROLE':'mission_owner'},{'AGENT_FACTORY_API_TENANTS':'other'}):
            with patch.dict(os.environ,overrides):self.assertEqual(self.post().status_code,403)
        self.headers.pop('X-Agent-Factory-Confirm');self.assertEqual(self.post().status_code,403)
        self.assertFalse(self.store.values)

    def test_backend_failure_never_echoes_secret(self):
        with patch.object(self.store,'put',side_effect=RuntimeError(self.secret)):
            response=self.post();self.assertEqual(response.status_code,503);self.assertNotIn(self.secret,response.text)
