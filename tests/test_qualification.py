import tempfile
import unittest
from pathlib import Path

from agent_factory.qualification import QualificationService
from agent_factory.storage import SQLiteStorage

class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.db = SQLiteStorage(Path(self.tmp.name) / "state.db"); self.service = QualificationService(self.db)
    def tearDown(self): self.db.close(); self.tmp.cleanup()
    def test_pass_records_all_nfr_capacity_and_raw_evidence(self):
        result = self.service.require_pass(profile="clustered")
        self.assertEqual(result["verdict"], "passed"); self.assertEqual(set(result["criteria"]), {"nfr_thresholds", "capacity", "accessibility", "tenant_isolation", "backup_restore"})
        self.assertEqual(result["raw_evidence"]["load"], {"active_runs": 10, "runnable_tasks": 25, "registered_agents": 100})
        self.assertTrue(result["environment"]["python"])
    def test_missing_or_below_gate_fails_and_is_retained(self):
        result = self.service.run(profile="air-gapped", accessibility=None, load={"active_runs": 9, "runnable_tasks": 25, "registered_agents": 100})
        self.assertEqual(result["verdict"], "failed"); self.assertFalse(result["criteria"]["accessibility"]); self.assertFalse(result["criteria"]["capacity"])
        with self.assertRaises(PermissionError): self.service.require_pass(profile="air-gapped", isolation=False)
        self.assertEqual(self.db.db.execute("SELECT COUNT(*) FROM qualification_runs").fetchone()[0], 2)

if __name__ == "__main__": unittest.main()
