import tempfile
import unittest
from pathlib import Path

from agent_factory.control_plane import HumanControlPlaneService
from agent_factory.storage import SQLiteStorage

class ControlPlaneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.db = SQLiteStorage(Path(self.tmp.name) / "state.db"); self.service = HumanControlPlaneService(self.db)
    def tearDown(self): self.db.close(); self.tmp.cleanup()
    def test_authenticated_role_actions_are_audited_and_scoped(self):
        result = self.service.act(tenant_id="tenant-a", actor="Mina", role="operations_owner", action="emergency_stop", target_type="mission", target_id="m1")
        self.assertEqual(result["outcome"], "accepted"); self.assertEqual(len(self.service.list_actions("tenant-a")), 1); self.assertEqual(self.service.list_actions("tenant-b"), [])
        with self.assertRaises(PermissionError): self.service.act(tenant_id="tenant-a", actor="agent", role="worker", action="approve", target_type="run", target_id="1")
    def test_retire_requires_explicit_irreversible_confirmation(self):
        with self.assertRaises(PermissionError): self.service.act(tenant_id="tenant-a", actor="Ops", role="operations_owner", action="retire", target_type="agent_definition", target_id="v1", payload={})
        self.assertEqual(self.service.act(tenant_id="tenant-a", actor="Ops", role="operations_owner", action="retire", target_type="agent_definition", target_id="v1", payload={"irreversible": True})["outcome"], "accepted")

if __name__ == "__main__": unittest.main()
