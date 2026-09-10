"""Check backlog contracts with temporary files and no Git or network access."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "scripts/validate_backlog.py"
SPEC = importlib.util.spec_from_file_location("backlog_validation_under_test", SOURCE)
checks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checks)


class BacklogValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="backlog-validation-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def test_backlog_missing_duplicate_and_cyclic_ids_fail(self):
        path = self.root / "backlog.json"
        document = {"schema_version": 2, "items": [
            {"stable_id": "A", "dependencies": []},
            {"stable_id": "B", "dependencies": ["A"]},
        ]}
        path.write_text(json.dumps(document), encoding="utf-8")
        self.assertEqual(len(checks.validate_backlog(path)), 2)
        document["items"][0]["dependencies"] = ["B"]
        path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(checks.ValidationError, "cycle"):
            checks.validate_backlog(path)
        document["items"][0]["dependencies"] = ["missing"]
        path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(checks.ValidationError, "dependencies"):
            checks.validate_backlog(path)
        document["items"][1]["stable_id"] = "A"
        path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(checks.ValidationError, "duplicate"):
            checks.validate_backlog(path)

    def test_cloud_readable_acceptance_drift_fails(self):
        item = {"stable_id": "AF-CLD-001", "kind": "spike", "title": "Review support", "priority": "P0", "assigned_role": "reviewer", "labels": ["milestone:m0", "size:s", "track:optional"], "dependencies": [], "acceptance_criteria": ["Evidence will be reviewed."]}
        text = "| [AF-CLD-001](#af-cld-001) | Review support (optional) | M0 | P0 | S | reviewer | None |\n\n### AF-CLD-001\n\nEvidence will be reviewed.\n"
        self.write("docs/backlog.md", text)
        checks.validate_cloud_alignment(self.root, {item["stable_id"]: item})
        self.write("docs/backlog.md", text.replace("Evidence will be reviewed.", "Evidence skipped."))
        with self.assertRaisesRegex(checks.ValidationError, "acceptance differs"):
            checks.validate_cloud_alignment(self.root, {item["stable_id"]: item})

    def test_invalid_hierarchy_and_release_gates_fail(self):
        path = self.root / "backlog.json"
        document = {"schema_version": 2, "items": [
            {"stable_id": "A", "dependencies": []},
            {"stable_id": "B", "dependencies": ["A"]},
        ]}
        document["items"][0]["parent_id"] = "missing"
        path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(checks.ValidationError, "parent reference"):
            checks.validate_backlog(path)
        document["items"][0]["parent_id"] = "B"
        document["items"][1]["parent_id"] = "A"
        path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(checks.ValidationError, "parent_id cycle"):
            checks.validate_backlog(path)
        for item in document["items"]:
            item.pop("parent_id")
        for values in ([], ["missing"], "A"):
            with self.subTest(values=values):
                document["planning_contract"] = {"release_gates": {"alpha": values}}
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(checks.ValidationError, "release gate"):
                    checks.validate_backlog(path)

    def test_malformed_backlog_structure_fails(self):
        path = self.root / "backlog.json"
        for document in (
            [], {"schema_version": 1, "items": []},
            {"schema_version": 2, "items": []},
            {"schema_version": 2, "items": ["not an item"]},
            {"schema_version": 2, "items": [{}]},
        ):
            with self.subTest(document=document):
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(checks.ValidationError):
                    checks.validate_backlog(path)

    def test_auto_detection_checks_each_manifest_and_cloud_alignment(self):
        core = {"schema_version": 2, "items": [
            {"stable_id": "AF-GC-001", "dependencies": []},
        ]}
        item = {
            "stable_id": "AF-CLD-001", "kind": "task", "title": "Review support",
            "priority": "P0", "assigned_role": "reviewer",
            "labels": ["milestone:m0", "size:s"], "dependencies": [],
            "acceptance_criteria": ["Evidence will be reviewed."],
        }
        cloud = {"schema_version": 2, "items": [item]}
        self.write(checks.ACTIVE_BACKLOGS[0], json.dumps(core))
        self.assertEqual(checks.validate_repository(self.root), [(checks.ACTIVE_BACKLOGS[0], 1)])
        self.write(checks.ACTIVE_BACKLOGS[1], json.dumps(cloud))
        with self.assertRaisesRegex(checks.ValidationError, "missing its readable"):
            checks.validate_repository(self.root)
        text = (
            "| [AF-CLD-001](#af-cld-001) | Review support | M0 | P0 | S | reviewer | None |\n"
            "\n### AF-CLD-001\n\nEvidence will be reviewed.\n"
        )
        self.write("docs/backlog.md", text)
        self.assertEqual(checks.validate_repository(self.root), [(name, 1) for name in checks.ACTIVE_BACKLOGS])
        (self.root / checks.ACTIVE_BACKLOGS[0]).unlink()
        self.assertEqual(checks.validate_repository(self.root), [(checks.ACTIVE_BACKLOGS[1], 1)])
        self.write("docs/backlog.md", text.replace("Review support", "Wrong title"))
        with self.assertRaisesRegex(checks.ValidationError, "index differs"):
            checks.validate_repository(self.root)

    def test_cli_reports_missing_or_invalid_input_and_success_without_git(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(checks.main(["--root", str(self.root)]), 1)
        self.assertIn("No supported active backlog", errors.getvalue())
        self.write(checks.ACTIVE_BACKLOGS[0], "{broken")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(checks.main(["--root", str(self.root)]), 1)
        self.write(checks.ACTIVE_BACKLOGS[0], json.dumps({
            "schema_version": 2, "items": [{"stable_id": "AF-GC-001"}],
        }))
        before = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(checks.main(["--root", str(self.root)]), 0)
        self.assertIn("(1 items)", output.getvalue())
        self.assertEqual(before, sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*")))


if __name__ == "__main__":
    unittest.main()
