import os
import unittest
from unittest.mock import patch
from fastapi import FastAPI
import test_game_planning_web as fixture
from agent_factory.configuration_advice_web import install_routes
from agent_factory.game_planning import template
from test_configuration_advice import report

class ConfigurationAdviceWebTests(unittest.TestCase):
    setUp=fixture.GamePlanningWebTests.setUp
    def test_advice_requires_existing_boundary_and_never_creates_revision(self):
        command={"fields":template(),"report":report()};url="/api/configuration-advice"
        self.assertEqual(self.client.post(url,json=command).status_code,401)
        response=self.client.post(url,json=command,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertFalse(response.json()['execution_ready'])
        self.assertEqual(self.client.get(self.url,headers=self.headers).json()['history'],[])
        for env in ({'AGENT_FACTORY_API_SCOPES':'read'},{'AGENT_FACTORY_API_TENANTS':'other'}):
            with patch.dict(os.environ,env):self.assertEqual(self.client.post(url,json=command,headers=self.headers).status_code,403)
        self.assertEqual(self.client.post(url,json=command,headers=self.headers|{'Origin':'https://untrusted.example'}).status_code,403)
    def test_bounded_input_errors_and_installation(self):
        url='/api/configuration-advice'
        for command in ({'fields':{},'report':{}},{'fields':template(),'report':{'memory':[]}}, {'fields':template(),'report':{},'extra':'private-canary'}):
            response=self.client.post(url,json=command,headers=self.headers)
            self.assertEqual(response.status_code,400);self.assertNotIn('private-canary',response.text)
        self.assertEqual(self.client.post(url,content=b'x'*40001,headers=self.headers).status_code,400)
        with self.assertRaises(ValueError):install_routes(FastAPI())
        with self.assertRaises(ValueError):install_routes(self.app)
