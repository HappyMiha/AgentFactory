"""Production local HTTP boundary around owner-bound immutable planning."""
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agent_factory.storage import SQLiteStorage
from agent_factory.mission_intake import AutonomousMissionIntakeService
from agent_factory.game_planning_web import install_routes
from agent_factory.web import create_app

class GamePlanningWebTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'state.db'
        self.env=patch.dict(os.environ,{'AGENT_FACTORY_API_TOKEN':'synthetic-plan-token','AGENT_FACTORY_API_ACTOR':'Founder','AGENT_FACTORY_API_ROLE':'operations_owner','AGENT_FACTORY_API_SCOPES':'read,write,approve,control','AGENT_FACTORY_API_TENANTS':'*','AGENT_FACTORY_TEMPORAL_ENABLED':'false'})
        self.env.start();self.addCleanup(self.env.stop)
        storage=SQLiteStorage(self.path)
        result=AutonomousMissionIntakeService(storage).create_from_text(name='Garden',mission_owner='Founder',actor='Founder',specification='<script>window.sourceExecuted=true</script> A garden with tokens.',command_id=str(uuid.uuid4()))
        self.ident=result.mission.id;storage.close()
        self.app=create_app(self.root,self.path);self.client=TestClient(self.app,base_url='http://127.0.0.1')
        self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)
        self.url='/api/game-planning/'+str(self.ident);self.headers={'Authorization':'Bearer synthetic-plan-token','X-Agent-Factory-Confirm':'true'}
    def draft(self):return self.client.get(self.url,headers=self.headers).json()
    def command(self):
        view=self.draft();return dict(fields=view['fields'],command_id=str(uuid.uuid4()),expected_revision_id=view['latest_revision_id'] or 0,expected_source_digest=view['source_digest'],confirmed=True)
    def test_read_has_no_save_and_explicit_save_is_owner_bound(self):
        self.assertEqual(self.client.get(self.url).status_code,401)
        self.assertIn('id="token"',self.client.get('/planning/'+str(self.ident)).text)
        self.assertEqual(self.draft()['history'],[])
        command=self.command()
        self.assertEqual(self.client.post(self.url,json=command,headers={'Authorization':self.headers['Authorization']}).status_code,400)
        response=self.client.post(self.url,json=command,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(len(self.draft()['history']),1)
        with patch.dict(os.environ,{'AGENT_FACTORY_API_ACTOR':'Other'}):
            self.assertEqual(self.client.get(self.url,headers=self.headers).status_code,404)
            self.assertEqual(self.client.post(self.url,json=command,headers=self.headers).status_code,404)
    def test_http_boundary_scopes_origin_tenant_and_input(self):
        command=self.command()
        for env in ({'AGENT_FACTORY_API_SCOPES':'read'},{'AGENT_FACTORY_API_TENANTS':'other'}):
            with patch.dict(os.environ,env):self.assertEqual(self.client.post(self.url,json=command,headers=self.headers).status_code,403)
        self.assertEqual(self.client.post(self.url,json=command,headers=self.headers|{'Origin':'https://untrusted.example'}).status_code,403)
        for changes in ({'confirmed':'true'},{'confirmed':1},{'expected_revision_id':True},{'expected_source_digest':None},{'fields':{'private-source-canary':'bad'}},{'extra':'bad'}):
            response=self.client.post(self.url,json=command|changes,headers=self.headers)
            self.assertEqual(response.status_code,400,response.text);self.assertNotIn('private-source-canary',response.text)
        self.assertEqual(self.client.post(self.url,content=b'x'*80001,headers=self.headers).status_code,400)
        self.assertEqual(self.draft()['history'],[])
    def test_stale_editor_and_history(self):
        command=self.command();one=self.client.post(self.url,json=command,headers=self.headers).json()
        self.assertEqual(self.client.post(self.url,json=command,headers=self.headers).json()['revision_id'],one['revision_id'])
        self.assertEqual(self.client.post(self.url,json=command|{'command_id':str(uuid.uuid4())},headers=self.headers).status_code,409)
        response=self.client.get(self.url+'?revision_id='+str(one['revision_id']),headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get(self.url+'?revision_id=999999',headers=self.headers).status_code,404)
    def test_install_requires_boundary_and_no_duplicate(self):
        with self.assertRaises(ValueError):install_routes(FastAPI(),self.path)
        with self.assertRaises(ValueError):install_routes(self.app,self.path)
