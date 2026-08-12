import tempfile
import unittest
from pathlib import Path

from agent_factory.soak import SoakService
from agent_factory.storage import SQLiteStorage

class SoakTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.db = SQLiteStorage(Path(self.tmp.name) / "state.db"); self.service = SoakService(self.db)
    def tearDown(self): self.db.close(); self.tmp.cleanup()
    def test_72_hour_profile_preserves_continuity_and_bounds(self):
        result = self.service.require_pass(duration_hours=72)
        self.assertEqual(result["verdict"], "passed"); self.assertEqual(set(result["fault_schedule"]), {"provider", "worker", "process", "network", "queue", "storage", "host"})
    def test_short_or_unbounded_soak_fails(self):
        with self.assertRaises(ValueError): self.service.run(duration_hours=71)
        result = self.service.run(duration_hours=72, resources={"memory_mb": 99999})
        self.assertEqual(result["verdict"], "failed")

if __name__ == "__main__": unittest.main()
