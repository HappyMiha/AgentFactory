import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent_factory.web import create_app

class ControlPlaneWebTests(unittest.TestCase):
    def test_authenticated_control_action_endpoint_audits_and_filters_tenant(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"AGENT_FACTORY_API_TOKEN": "token", "AGENT_FACTORY_API_ACTOR": "Ops"}):
            root = Path(tmp); client = TestClient(create_app(root, root / "state.db"), base_url="http://localhost")
            denied = client.post("/api/control/actions", json={"tenant_id":"a","actor":"Ops","role":"operations_owner","action":"emergency_stop","target_type":"mission","target_id":"m1","confirmed":True})
            self.assertEqual(denied.status_code, 401)
            headers = {"Authorization":"Bearer token", "X-Agent-Factory-Confirm":"true"}
            response = client.post("/api/control/actions", headers=headers, json={"tenant_id":"a","actor":"Ops","role":"operations_owner","action":"emergency_stop","target_type":"mission","target_id":"m1","confirmed":True})
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(client.get("/api/control/actions", params={"tenant_id":"a"}, headers=headers).json()[0]["tenant_id"], "a")
            self.assertEqual(client.get("/api/control/actions", params={"tenant_id":"b"}, headers=headers).json(), [])
            self.assertIn("/api/control/actions", client.get("/api/openapi.json", headers=headers).json()["paths"])

if __name__ == "__main__": unittest.main()
