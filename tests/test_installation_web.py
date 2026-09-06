from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agent_factory.installation_web import install_routes
from agent_factory.storage import SQLiteStorage
from agent_factory.web import create_app
from test_installation_review import create_game, HOST


class InstallationWebTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'state.db'
        storage=SQLiteStorage(self.path);self.mission=create_game(storage);storage.close()
        self.env=patch.dict(os.environ,{'AGENT_FACTORY_API_TOKEN':'synthetic-install-token','AGENT_FACTORY_API_ACTOR':'Founder',
            'AGENT_FACTORY_API_ROLE':'operations_owner','AGENT_FACTORY_API_SCOPES':'read,write,approve,control',
            'AGENT_FACTORY_API_TENANTS':'local','AGENT_FACTORY_TEMPORAL_ENABLED':'false'})
        self.env.start();self.addCleanup(self.env.stop)
        self.host=deepcopy(HOST)
        self.probe=patch('agent_factory.installation_review.observe_workspace',side_effect=lambda *_:deepcopy(self.host))
        self.probe.start();self.addCleanup(self.probe.stop)
        self.app=create_app(self.root,self.path);self.client=TestClient(self.app,base_url='http://127.0.0.1')
        self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)
        self.url=f'/api/installation-plans/{self.mission}';self.decision=f'/api/approvals/installation/{self.mission}'
        self.headers={'Authorization':'Bearer synthetic-install-token','X-Agent-Factory-Confirm':'true'}

    def prepare(self):
        response=self.client.post(self.url,headers=self.headers,json={'command_id':str(uuid.uuid4()),'offline':False})
        self.assertEqual(response.status_code,200,response.text);return response.json()

    def command(self, plan):
        return {'command_id':str(uuid.uuid4()),'plan_id':plan['id'],'digest':plan['digest'],'decision':'approved'}

    def test_default_composition_explicit_preparation_and_approval(self):
        self.assertEqual(self.client.get(self.url).status_code,401)
        self.assertIn('id="token"',self.client.get(f'/installation/{self.mission}').text)
        response=self.client.get(self.url,headers=self.headers)
        self.assertIsNone(response.json()['review']);self.assertTrue(response.json()['can_decide'])
        self.assertEqual(response.headers['cache-control'],'no-store')
        plan=self.prepare();response=self.client.post(self.decision,headers=self.headers,json=self.command(plan))
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['decision']['decision'],'approved');self.assertFalse(response.json()['execution_eligible'])
        self.assertIn('installation-link',self.client.get(f'/planning/{self.mission}',headers=self.headers).text)

    def test_scopes_identity_tenant_and_origin_are_enforced(self):
        plan=self.prepare();command=self.command(plan)
        for changes in ({'AGENT_FACTORY_API_SCOPES':'read,write'},{'AGENT_FACTORY_API_TENANTS':'other'},
                        {'AGENT_FACTORY_API_ROLE':'security_reviewer'}):
            with self.subTest(changes=changes),patch.dict(os.environ,changes):
                self.assertEqual(self.client.post(self.decision,headers=self.headers,json=command).status_code,403)
        with patch.dict(os.environ,{'AGENT_FACTORY_API_ACTOR':'Other'}):
            self.assertEqual(self.client.post(self.decision,headers=self.headers,json=command).status_code,404)
            self.assertEqual(self.client.get(self.url,headers=self.headers).status_code,404)
        self.assertEqual(self.client.post(self.decision,headers=self.headers|{'Origin':'https://other.example'},json=command).status_code,403)
        self.assertIsNone(self.client.get(self.url,headers=self.headers).json()['review']['decision'])

    def test_local_open_mode_cannot_record_a_decision(self):
        with patch.dict(os.environ,{'AGENT_FACTORY_API_TOKEN':''}):
            with TestClient(create_app(self.root,self.path),base_url='http://127.0.0.1') as client:
                result=client.get(self.url).json();self.assertFalse(result['can_decide'])
                plan=client.post(self.url,headers={'X-Agent-Factory-Confirm':'true'},json={'command_id':str(uuid.uuid4()),'offline':False}).json()
                self.assertEqual(client.post(self.decision,headers={'X-Agent-Factory-Confirm':'true'},json=self.command(plan)).status_code,403)

    def test_changed_capacity_catalogue_input_and_duplicate_fields_fail_closed(self):
        plan=self.prepare();command=self.command(plan);self.host['free_bytes']=1
        self.assertEqual(self.client.post(self.decision,headers=self.headers,json=command).status_code,409)
        for changes in ({'plan_id':True},{'decision':'execute'},{'catalog':{}},{'actor':'Other'}):
            self.assertEqual(self.client.post(self.decision,headers=self.headers,json=command|changes).status_code,400)
        self.assertEqual(self.client.post(self.url,headers=self.headers,content=b'{"offline":false,"offline":true}').status_code,400)
        self.assertEqual(self.client.post(self.url,headers=self.headers,content=b'x'*4097).status_code,400)
        self.assertEqual(self.client.post(self.decision,headers={'Authorization':self.headers['Authorization']},json=command).status_code,400)
        self.assertEqual(self.client.get(self.url+'?unexpected=1',headers=self.headers).status_code,400)

    def test_boundary_required_and_duplicate_install_rejected(self):
        with self.assertRaises(ValueError):install_routes(FastAPI(),self.path,self.root)
        with self.assertRaises(ValueError):install_routes(self.app,self.path,self.root)
