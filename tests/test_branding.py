"""Compatibility checks for the branded CLI and distributed UI resources."""
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from agent_factory.cli import parser
from agent_factory.application import AgentFactoryService
from agent_factory.storage import SQLiteStorage

ROOT = Path(__file__).resolve().parents[1]


class BrandingTests(unittest.TestCase):
    def test_new_and_legacy_commands_share_entrypoints(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        scripts = project["scripts"]
        self.assertEqual(scripts["lokvetia"], scripts["agent-factory"])
        self.assertEqual(scripts["lokvetia-temporal-worker"], scripts["agent-factory-temporal-worker"])
        self.assertEqual(project["name"], "agent-factory-orchestrator")

    def test_help_uses_invoked_brand_or_legacy_alias(self):
        for executable, expected in (("lokvetia.exe", "lokvetia"), ("agent-factory", "agent-factory"), ("__main__.py", "lokvetia")):
            with self.subTest(executable=executable), patch.object(sys, "argv", [executable]):
                command = parser()
                self.assertEqual(command.prog, expected)
                self.assertIn("Lokvetia Core", command.format_help())
                self.assertEqual(command.parse_args(["demo"]).command, "demo")

    def test_rebranding_preserves_workspace_configuration(self):
        with patch.dict("os.environ", {"AGENT_FACTORY_WORKSPACE": "existing-work", "AGENT_FACTORY_DB": "existing.db"}):
            options = parser().parse_args(["demo"])
        self.assertEqual(options.workspace, "existing-work")
        self.assertEqual(options.db, "existing.db")

    def test_upgrade_reuses_legacy_demo_and_pending_run(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            storage = SQLiteStorage(workspace / "state.db")
            try:
                service = AgentFactoryService(storage, workspace=workspace)
                project, task = service.seed_example()
                before = service.run_demo()
                storage.db.execute("UPDATE projects SET name=? WHERE id=?", ("Agent Factory Demo", project))
                storage.db.commit()
                self.assertEqual(service.seed_example(), (project, task))
                self.assertEqual(service.run_demo().id, before.id)
                self.assertEqual(storage.db.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 1)
            finally:
                storage.close()

    def test_flat_brand_assets_are_in_package_data(self):
        static = ROOT / "src" / "agent_factory" / "static"
        for name in ("brand-mark.svg", "brand-wordmark.svg"):
            self.assertEqual(ET.parse(static / name).getroot().tag, "{http://www.w3.org/2000/svg}svg")
        self.assertTrue((static / "brand.css").is_file())
        for page in static.glob("*.html"):
            content = page.read_text(encoding="utf-8")
            with self.subTest(page=page.name):
                self.assertIn("brand.css", content)
                self.assertIn("brand-mark.svg", content)


if __name__ == "__main__":
    unittest.main()
