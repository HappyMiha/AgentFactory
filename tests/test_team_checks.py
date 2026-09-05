"""Exercise real local Git snapshots and check execution, without network access."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "scripts/team_checks.py"
SPEC = importlib.util.spec_from_file_location("team_checks_under_test", SOURCE)
checks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checks)


class TeamChecksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentfactory-team-checks-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.git("init", "-b", "main")
        self.write("README.md", "Initial planning\n")
        self.write(".gitignore", "__pycache__/\n.ignored\n")
        self.commit()
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")

    def git(self, *args, root=None):
        result = subprocess.run(
            ["git", "-c", "user.name=Team Checks Fixture", "-c", "user.email=team-checks@example.invalid", *args],
            cwd=root or self.root, shell=False, capture_output=True, text=True,
            encoding="utf-8", env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "--allow-empty", "-m", "Fixture change")

    def test_planning_attestation_verifies_exact_snapshot_and_is_git_local(self):
        self.write("README.md", "Updated plan\n")
        self.commit()
        result = checks.run_checks(self.root)
        self.assertEqual(result["profile"], "planning-and-static")
        self.assertEqual(result["changed_paths"], ["README.md"])
        self.assertEqual(result["head"], self.git("rev-parse", "HEAD"))
        self.assertEqual(result["tree"], self.git("rev-parse", "HEAD^{tree}"))
        self.assertFalse(result["full_ci_passed"])
        self.assertEqual(checks.verify(self.root), result)
        self.assertEqual(checks.attestation_path(self.root), self.root / ".git/team-checks.json")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_same_tree_new_head_invalidates_attestation(self):
        checks.run_checks(self.root)
        self.commit()
        with self.assertRaisesRegex(checks.CheckError, "head changed"):
            checks.verify(self.root)

    def test_locally_updated_base_invalidates_attestation(self):
        self.write("README.md", "Updated plan\n")
        self.commit()
        checks.run_checks(self.root)
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        with self.assertRaisesRegex(checks.CheckError, "base_sha changed"):
            checks.verify(self.root)

    def test_dirty_tracked_and_untracked_changes_block_verification(self):
        checks.run_checks(self.root)
        self.write("README.md", "Uncommitted edit\n")
        with self.assertRaisesRegex(checks.CheckError, "clean"):
            checks.verify(self.root)
        self.git("restore", "README.md")
        self.write("untracked.txt", "Must not be missed\n")
        with self.assertRaisesRegex(checks.CheckError, "clean"):
            checks.verify(self.root)
        (self.root / "untracked.txt").unlink()
        self.write(".ignored", "Ignored local state\n")
        checks.verify(self.root)

    def test_failed_rerun_removes_previous_success(self):
        checks.run_checks(self.root)
        self.write("untracked.txt", "Dirty\n")
        with self.assertRaises(checks.CheckError):
            checks.run_checks(self.root)
        (self.root / "untracked.txt").unlink()
        self.assertFalse(checks.attestation_path(self.root).exists())
        with self.assertRaisesRegex(checks.CheckError, "No valid"):
            checks.verify(self.root)

    def test_selected_tests_do_not_claim_full_suite_or_ci(self):
        self.write("tests/test_chosen.py", "import unittest\nclass Chosen(unittest.TestCase):\n def test_ok(self): self.assertEqual(2 + 2, 4)\n")
        self.write("tests/test_not_chosen.py", "import unittest\nclass Other(unittest.TestCase):\n def test_fails(self): self.fail('Must run in full discovery only')\n")
        self.commit()
        result = checks.run_checks(self.root, selected=["test_chosen"])
        self.assertEqual(result["profile"], "selected-unittest-modules")
        self.assertEqual(result["selected_test_modules"], ["test_chosen"])
        self.assertFalse(result["full_ci_passed"])
        executed = [r for r in result["commands"] if r.get("tests_run")]
        self.assertEqual(len(executed), 1)
        self.assertEqual(executed[0]["tests_run"], 1)
        self.assertIn("test_chosen", executed[0]["command"])
        self.assertNotIn("discover", executed[0]["command"])
        with self.assertRaisesRegex(checks.CheckError, "Check failed"):
            checks.run_checks(self.root)
        self.assertFalse(checks.attestation_path(self.root).exists())

    def test_coordination_profile_runs_only_team_tests(self):
        self.write("tests/test_other.py", "raise RuntimeError('Must not be imported by team profile')\n")
        self.commit()
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.write("tests/test_team_fixture.py", "import unittest\nclass Team(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n")
        self.commit()
        result = checks.run_checks(self.root)
        self.assertEqual(result["profile"], "coordination-unittest-discovery")
        self.assertEqual([r["tests_run"] for r in result["commands"] if "tests_run" in r], [1])

    def test_empty_test_selection_and_shell_input_are_rejected(self):
        self.write("tests/test_empty.py", "# No tests\n")
        self.commit()
        with self.assertRaisesRegex(checks.CheckError, "no tests"):
            checks.run_checks(self.root, selected=["test_empty"])
        with self.assertRaisesRegex(checks.CheckError, "Invalid unittest module"):
            checks.test_command(self.root, "selected-unittest-modules", ["test_empty; echo injected"])
        with self.assertRaisesRegex(checks.CheckError, "not in this repository"):
            checks.test_command(self.root, "selected-unittest-modules", ["unittest"])

    def test_all_skipped_tests_do_not_count_as_execution(self):
        self.write("tests/test_skipped.py", "import unittest\nclass Skipped(unittest.TestCase):\n @unittest.skip('No runtime')\n def test_skip(self): self.fail()\n")
        self.commit()
        with self.assertRaisesRegex(checks.CheckError, "All selected tests were skipped"):
            checks.run_checks(self.root, selected=["test_skipped"])
        self.assertFalse(checks.attestation_path(self.root).exists())

    def test_empty_suite_exit_codes_never_produce_attestation(self):
        self.write("tests/test_empty.py", "# No tests\n")
        self.commit()
        real_command = checks.command

        for exit_code in (0, 5):
            with self.subTest(exit_code=exit_code):
                def empty_suite(root, argv, *, env=None):
                    if "unittest" in argv:
                        return subprocess.CompletedProcess(
                            argv, exit_code, "", "Ran 0 tests in 0.000s\nNO TESTS RAN\n"
                        )
                    return real_command(root, argv, env=env)

                with mock.patch.object(checks, "command", side_effect=empty_suite):
                    with self.assertRaisesRegex(checks.CheckError, "no tests"):
                        checks.run_checks(self.root, selected=["test_empty"])
                self.assertFalse(checks.attestation_path(self.root).exists())

    def test_unittest_import_failure_preserves_diagnostic(self):
        self.write("tests/test_broken.py", "raise RuntimeError('fixture import failed')\n")
        self.commit()
        with self.assertRaisesRegex(checks.CheckError, "fixture import failed"):
            checks.run_checks(self.root, selected=["test_broken"])
        self.assertFalse(checks.attestation_path(self.root).exists())

    def test_test_mutation_prevents_attestation(self):
        self.write("tests/test_mutation.py", "import pathlib, unittest\nclass Mutation(unittest.TestCase):\n def test_changes(self): pathlib.Path('unexpected.txt').write_text('changed')\n")
        self.commit()
        with self.assertRaisesRegex(checks.CheckError, "clean"):
            checks.run_checks(self.root, selected=["test_mutation"])
        self.assertFalse(checks.attestation_path(self.root).exists())

    def test_bad_python_and_diff_whitespace_fail_before_attestation(self):
        self.write("scripts/broken.py", "def broken(:\n")
        self.commit()
        with self.assertRaises(SyntaxError):
            checks.run_checks(self.root)
        self.assertFalse(checks.attestation_path(self.root).exists())
        self.write("scripts/broken.py", "# Valid now\n")
        self.write("README.md", "Trailing spaces   \n")
        self.commit()
        with self.assertRaisesRegex(checks.CheckError, "Check failed"):
            checks.run_checks(self.root)

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
        with self.assertRaisesRegex(checks.CheckError, "cycle"):
            checks.validate_backlog(path)
        document["items"][0]["dependencies"] = ["missing"]
        path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(checks.CheckError, "dependencies"):
            checks.validate_backlog(path)
        document["items"][1]["stable_id"] = "A"
        path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(checks.CheckError, "duplicate"):
            checks.validate_backlog(path)

    def test_cloud_readable_acceptance_drift_fails(self):
        item = {"stable_id": "AF-CLD-001", "kind": "spike", "title": "Review support", "priority": "P0", "assigned_role": "reviewer", "labels": ["milestone:m0", "size:s", "track:optional"], "dependencies": [], "acceptance_criteria": ["Evidence will be reviewed."]}
        text = "| [AF-CLD-001](#af-cld-001) | Review support (optional) | M0 | P0 | S | reviewer | None |\n\n### AF-CLD-001\n\nEvidence will be reviewed.\n"
        self.write("docs/backlog.md", text)
        checks.validate_cloud_alignment(self.root, {item["stable_id"]: item})
        self.write("docs/backlog.md", text.replace("Evidence will be reviewed.", "Evidence skipped."))
        with self.assertRaisesRegex(checks.CheckError, "acceptance differs"):
            checks.validate_cloud_alignment(self.root, {item["stable_id"]: item})

    def test_worktree_attestation_uses_its_own_git_path(self):
        worktree = self.root / "linked"
        self.git("worktree", "add", "-b", "fixture-linked", str(worktree))
        path = checks.attestation_path(worktree)
        self.assertNotEqual(path, self.root / ".git/team-checks.json")
        self.assertIn("worktrees", path.parts)
        checks.run_checks(worktree)
        checks.verify(worktree)
        self.assertTrue(path.is_file())
        self.assertFalse((self.root / ".git/team-checks.json").exists())

    def test_corrupt_or_forged_success_cache_is_not_accepted(self):
        with self.assertRaisesRegex(checks.CheckError, "No valid"):
            checks.verify(self.root)
        path = checks.attestation_path(self.root)
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(checks.CheckError, "No valid"):
            checks.verify(self.root)
        path.write_text(json.dumps({"schema_version": 1, "success": True, "commands": []}), encoding="utf-8")
        with self.assertRaisesRegex(checks.CheckError, "Invalid"):
            checks.verify(self.root)
        result = checks.run_checks(self.root)
        result["commands"] = ["not a result object"]
        path.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(checks.CheckError, "Invalid"):
            checks.verify(self.root)


if __name__ == "__main__":
    unittest.main()
