import tempfile
import unittest
from pathlib import Path

from agent_factory.acceptance_mission import AcceptanceMissionService
from agent_factory.storage import SQLiteStorage

class AcceptanceMissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.db = SQLiteStorage(Path(self.tmp.name) / "state.db"); self.service = AcceptanceMissionService(self.db)
    def tearDown(self): self.db.close(); self.tmp.cleanup()
    def payload(self, count=45):
        return {"routing": True, "independent_verification": True, "worker_replacement": True, "recovery": True, "approval": True, "release_artifact": True, "criteria": {f"AC-{i:02d}": {"signed": True} for i in range(count)}}
    def test_acceptance_requires_heterogeneous_flow_and_reproducible_release(self):
        providers = ({"provider": "codex", "role": "worker"}, {"provider": "claude", "role": "worker"}, {"provider": "hermes", "role": "reviewer"})
        result = self.service.require_acceptance(providers=providers, evidence=self.payload())
        self.assertEqual(result["criteria_count"], 45); self.assertEqual(len(result["release_digest"]), 64)
    def test_incomplete_criteria_or_flow_fails(self):
        providers = ({"provider": "a"}, {"provider": "b"}, {"provider": "c"})
        result = self.service.run(providers=providers, evidence=self.payload(44)); self.assertEqual(result["verdict"], "failed")
        with self.assertRaises(ValueError): self.service.run(providers=({"provider": "a"},), evidence=self.payload())

if __name__ == "__main__": unittest.main()
