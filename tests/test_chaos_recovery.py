import tempfile
import unittest
from pathlib import Path

from agent_factory.chaos_recovery import ChaosRecoveryService
from agent_factory.storage import SQLiteStorage

class ChaosRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.db = SQLiteStorage(Path(self.tmp.name) / "state.db"); self.service = ChaosRecoveryService(self.db)
    def tearDown(self): self.db.close(); self.tmp.cleanup()
    def test_all_mutation_boundaries_require_identity_continuity_and_restore(self):
        identities = {key: key + "-1" for key in ("stage", "lease", "runtime_session", "context", "worktree", "budget", "approval", "external_operation")}
        for boundary in ("before_commit", "after_external_operation", "host_termination", "network_partition", "queue_restart", "storage_restart"):
            self.assertEqual(self.service.run(fault_boundary=boundary, identities=identities)["verdict"], "passed")
        self.assertTrue(self.service.restore_exercise()["verified"])
    def test_missing_identity_fails_without_claiming_recovery(self):
        result = self.service.run(fault_boundary="before_commit", identities={"stage": "s"})
        self.assertEqual(result["verdict"], "failed")

if __name__ == "__main__": unittest.main()
