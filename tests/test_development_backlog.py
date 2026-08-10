import re
import unittest
from pathlib import Path

from agent_factory.backlog import load_backlog


ROOT = Path(__file__).resolve().parents[1]
BACKLOG = ROOT / "examples" / "development-backlog.json"
ROADMAP = ROOT / "docs" / "development-roadmap.md"


class DevelopmentBacklogTests(unittest.TestCase):
    def test_roadmap_manifest_is_complete_and_importable(self):
        proposal = load_backlog(BACKLOG)
        by_id = {item.stable_id: item for item in proposal.items}

        self.assertEqual(proposal.source_name, "Agent Factory Technical Specification v1.0")
        self.assertEqual(len(proposal.items), 40)
        self.assertEqual(
            {item.stable_id for item in proposal.items if item.kind == "epic"},
            {f"AF-E0{number}" for number in range(1, 6)},
        )
        self.assertEqual(
            {item.stable_id for item in proposal.items if item.kind == "task"},
            {f"AF-{number:03d}" for number in range(1, 36)},
        )

        for item in proposal.items:
            with self.subTest(stable_id=item.stable_id):
                self.assertTrue(item.source_references)
                self.assertGreaterEqual(len(item.acceptance_criteria), 2)
                priorities = [label for label in item.labels if label.startswith("priority:")]
                releases = [label for label in item.labels if label.startswith("release:")]
                self.assertEqual(len(priorities), 1)
                self.assertEqual(len(releases), 1)
                if item.kind == "task":
                    self.assertIn(item.parent_id, {f"AF-E0{number}" for number in range(1, 6)})
                    self.assertGreaterEqual(len(item.acceptance_criteria), 3)

        self.assertEqual(by_id["AF-001"].dependencies, ())
        self.assertIn("AF-001", by_id["AF-002"].dependencies)
        self.assertIn("AF-033", by_id["AF-034"].dependencies)
        self.assertIn("AF-034", by_id["AF-035"].dependencies)

    def test_readable_roadmap_matches_importable_manifest(self):
        proposal = load_backlog(BACKLOG)
        by_id = {item.stable_id: item for item in proposal.items}
        rows = re.findall(
            r"^\| (AF-\d{3}) \| (P\d) \| ([^|]+?) \| ([^|]+?) \|",
            ROADMAP.read_text(encoding="utf-8"),
            re.MULTILINE,
        )

        self.assertEqual(len(rows), 35)
        for stable_id, priority, title, dependency_cell in rows:
            with self.subTest(stable_id=stable_id):
                item = by_id[stable_id]
                self.assertEqual(title.strip(), item.title)
                self.assertIn(f"priority:{priority.lower()}", item.labels)
                self.assertEqual(
                    re.findall(r"AF-\d{3}", dependency_cell),
                    list(item.dependencies),
                )


if __name__ == "__main__":
    unittest.main()
