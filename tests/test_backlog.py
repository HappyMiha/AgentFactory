import json
import tempfile
import unittest
from pathlib import Path

from agent_factory.backlog import (
    BacklogManifestError,
    diff_issues,
    issue_operations,
    load_backlog,
)


def manifest() -> dict:
    return {
        "schema_version": 1,
        "source": {"name": "Example specification"},
        "items": [
            {
                "stable_id": "example:epic:first",
                "kind": "epic",
                "title": "First capability",
                "description": "Deliver a bounded, testable outcome.",
                "acceptance_criteria": ["The outcome can be independently verified"],
                "source_references": ["Specification section 1"],
            },
            {
                "stable_id": "example:task:evidence",
                "kind": "task",
                "title": "Capture acceptance evidence",
                "description": "Record evidence for every criterion.",
                "parent_id": "example:epic:first",
                "dependencies": ["example:epic:first"],
                "acceptance_criteria": ["Every criterion has non-empty evidence"],
                "review_notes": ["A human decides final acceptance"],
            },
        ],
    }


class BacklogManifestTests(unittest.TestCase):
    def write(self, root: str, document: dict | None = None) -> Path:
        path = Path(root) / "backlog.json"
        path.write_text(json.dumps(document or manifest()), encoding="utf-8")
        return path

    def test_load_is_deterministic_traceable_and_neutral(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp)
            first = load_backlog(path)
            second = load_backlog(path)
            self.assertEqual(first, second)
            self.assertEqual(first.source_name, "Example specification")
            self.assertEqual(len(first.source_sha256), 64)
            issue = first.items[0].issue()
            self.assertIn("agent-factory-id:example:epic:first", issue["body"])
            self.assertIn("Source references", issue["body"])

    def test_missing_reference_duplicate_and_cycle_are_rejected(self):
        cases = []
        missing = manifest()
        missing["items"][1]["dependencies"] = ["unknown"]
        cases.append(missing)
        duplicate = manifest()
        duplicate["items"][1]["stable_id"] = duplicate["items"][0]["stable_id"]
        cases.append(duplicate)
        cycle = manifest()
        cycle["items"][0]["dependencies"] = ["example:task:evidence"]
        cases.append(cycle)
        with tempfile.TemporaryDirectory() as tmp:
            for index, document in enumerate(cases):
                path = Path(tmp) / f"case-{index}.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.subTest(index=index), self.assertRaises(BacklogManifestError):
                    load_backlog(path)

    def test_diff_reports_create_update_duplicate_conflict_and_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            proposal = load_backlog(self.write(tmp))
            desired_first = proposal.items[0].issue()
            existing = [
                {
                    "number": 1,
                    "title": desired_first["title"],
                    "body": desired_first["body"],
                    "labels": desired_first["labels"],
                },
                {
                    "number": 2,
                    "title": "[Task] Capture acceptance evidence",
                    "body": "<!-- agent-factory-id:example:task:evidence -->\nold",
                    "labels": [],
                },
            ]
            result = diff_issues(proposal, existing)
            self.assertEqual(len(result["unchanged"]), 1)
            self.assertEqual(len(result["update"]), 1)
            operations = issue_operations(result)
            self.assertEqual([entry["action"] for entry in operations], ["update_issue"])
            self.assertTrue(operations[0]["idempotency_key"].startswith("backlog:update:"))

            duplicate = existing + [{**existing[1], "number": 3}]
            duplicated = diff_issues(proposal, duplicate)
            self.assertEqual(len(duplicated["duplicate"]), 1)
            with self.assertRaises(BacklogManifestError):
                issue_operations(duplicated)

            collision = [
                {
                    "number": 4,
                    "title": "[Epic] First capability",
                    "body": "No marker",
                    "labels": [],
                }
            ]
            conflicted = diff_issues(proposal, collision)
            self.assertEqual(len(conflicted["conflict"]), 1)

    def test_create_keys_are_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            proposal = load_backlog(self.write(tmp))
            first = issue_operations(diff_issues(proposal, []))
            second = issue_operations(diff_issues(proposal, []))
            self.assertEqual(first, second)
            self.assertEqual(len(first), 2)


if __name__ == "__main__":
    unittest.main()
