import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class CLITests(unittest.TestCase):
    def run_cli(self, workspace: Path, *arguments: str):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_factory",
                "--workspace",
                str(workspace),
                *arguments,
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )

    def test_from_zero_init_demo_and_approval_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            initialized = self.run_cli(workspace, "init")
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            details = json.loads(initialized.stdout)
            self.assertTrue(Path(details["database"]).is_file())
            demonstrated = self.run_cli(workspace, "demo")
            self.assertEqual(demonstrated.returncode, 0, demonstrated.stderr)
            self.assertIn("STOPPED AT HUMAN APPROVAL", demonstrated.stdout)
            repeated = self.run_cli(workspace, "demo")
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertIn("Run 1: delivery", repeated.stdout)
            approvals = self.run_cli(workspace, "approvals", "list")
            self.assertEqual(approvals.returncode, 0, approvals.stderr)
            self.assertEqual(json.loads(approvals.stdout)[0]["status"], "pending")

    def test_project_and_work_item_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            created = self.run_cli(
                workspace,
                "project",
                "init",
                "--name",
                "Example Product",
                "--description",
                "Independent example",
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            project_id = json.loads(created.stdout)["project_id"]
            item = self.run_cli(
                workspace,
                "work-item",
                "create",
                "--project-id",
                str(project_id),
                "--title",
                "First capability",
                "--description",
                "Deliver a testable result",
                "--kind",
                "task",
                "--acceptance",
                "The result is observable",
            )
            self.assertEqual(item.returncode, 0, item.stderr)
            listed = self.run_cli(
                workspace, "work-item", "list", "--project-id", str(project_id)
            )
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertEqual(json.loads(listed.stdout)[0]["title"], "First capability")

    def test_backlog_validate_and_idempotent_local_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            manifest = workspace / "backlog.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "items": [
                            {
                                "stable_id": "example:task:first",
                                "kind": "task",
                                "title": "First task",
                                "description": "Produce evidence",
                                "acceptance_criteria": ["Evidence is reviewable"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            project = self.run_cli(workspace, "project", "init", "--name", "Example")
            project_id = json.loads(project.stdout)["project_id"]
            validated = self.run_cli(
                workspace, "backlog", "validate", "--path", str(manifest)
            )
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertTrue(json.loads(validated.stdout)["valid"])
            first = self.run_cli(
                workspace,
                "backlog",
                "import",
                "--path",
                str(manifest),
                "--project-id",
                str(project_id),
            )
            second = self.run_cli(
                workspace,
                "backlog",
                "import",
                "--path",
                str(manifest),
                "--project-id",
                str(project_id),
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(len(json.loads(first.stdout)["created"]), 1)
            self.assertEqual(json.loads(second.stdout)["skipped"], ["example:task:first"])


if __name__ == "__main__":
    unittest.main()
