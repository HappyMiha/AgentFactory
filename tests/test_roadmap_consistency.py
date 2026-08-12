import unittest
from pathlib import Path

class RoadmapConsistencyTests(unittest.TestCase):
    def test_roadmap_does_not_claim_completed_capabilities_are_missing(self):
        root = Path(__file__).resolve().parent.parent
        roadmap = (root / "docs" / "development-roadmap.md").read_text(encoding="utf-8")
        self.assertIn("As of 12 August 2026, all 57 of 57 tasks", roadmap)
        self.assertIn("REST API, PostgreSQL/object-storage contract", roadmap)
        self.assertNotIn("| REST API, PostgreSQL, Redis, Qdrant, multi-tenancy, hosted UI, and clustered deployment | Missing", roadmap)
        self.assertNotIn("| Pack SDK, production qualification, soak test, and acceptance mission | Missing", roadmap)

if __name__ == "__main__": unittest.main()
