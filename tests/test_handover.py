import tempfile
import unittest
from pathlib import Path

from agent_factory.handover import CHECKLIST, HandoverService
from agent_factory.storage import SQLiteStorage

class HandoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.db = SQLiteStorage(Path(self.tmp.name) / "state.db"); self.service = HandoverService(self.db)
    def tearDown(self): self.db.close(); self.tmp.cleanup()
    def test_complete_runbook_and_evidence_index_is_ready(self):
        checklist = {key: True for key in CHECKLIST}; index = {key: (f"docs/{key}.md",) for key in ("requirements", "risks", "criteria", "tests", "artifacts", "decisions", "exceptions", "recovery")}
        self.assertEqual(self.service.require_ready(checklist=checklist, evidence_index=index, second_mission=True)["verdict"], "ready")
    def test_missing_restore_or_second_mission_blocks(self):
        checklist = {key: True for key in CHECKLIST}; checklist["restore"] = False
        result = self.service.build(checklist=checklist, evidence_index={}, second_mission=False)
        self.assertEqual(result["verdict"], "blocked")

if __name__ == "__main__": unittest.main()
