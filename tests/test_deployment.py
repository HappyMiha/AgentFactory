import tempfile
import unittest
from pathlib import Path

from agent_factory.deployment import DeploymentService
from agent_factory.storage import SQLiteStorage

class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.db = SQLiteStorage(Path(self.tmp.name) / "state.db"); self.service = DeploymentService(self.db)
    def tearDown(self): self.db.close(); self.tmp.cleanup()
    def test_smoke_all_profiles_and_airgap_egress(self):
        for profile in ("single-node", "clustered", "hybrid", "air-gapped"):
            self.assertEqual(self.service.smoke(profile)["status"], "healthy")
        self.assertEqual(self.service.manifest("air-gapped")["egress"]["mode"], "deny-all")
        self.assertEqual(self.service.manifest("hybrid")["model"], "remote-allowlist")
    def test_upgrade_and_rollback_require_continuity_evidence(self):
        evidence = {"active_mission_authority": "m1", "pending_approvals": ["a1"], "accepted_artifacts": ["e1"], "audit_chain": "abc"}
        self.assertEqual(self.service.record("clustered", "upgrade", "2", from_version="1", continuity=evidence)["status"], "verified")
        with self.assertRaises(PermissionError): self.service.record("clustered", "rollback", "1", from_version="2", continuity={})
        self.assertEqual(self.db.db.execute("SELECT status FROM deployment_operations ORDER BY id DESC LIMIT 1").fetchone()[0], "blocked")

if __name__ == "__main__": unittest.main()
