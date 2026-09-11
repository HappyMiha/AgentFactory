"""Godot pack materialisation: preview first, never silently overwrite."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_factory.godot_pack import (
    GODOT_PACK_KEY,
    PACK_STATE_PATH,
    SUPPORTED_ENGINE_VERSIONS,
    GameTemplate,
    GodotPack,
    PackConflict,
    TemplateFile,
    export_presets,
)


class GodotPackTemplateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = GodotPack()

    def test_catalogue_ships_two_playable_templates(self) -> None:
        identifiers = [template.template_id for template in self.pack.templates()]
        self.assertEqual(identifiers, ["collector-2d", "platformer-2d"])
        for template in self.pack.templates():
            paths = {entry.path for entry in template.files}
            self.assertIn("project.godot", paths)
            self.assertIn(template.main_scene, paths)
            self.assertIn("scripts/player.gd", paths)
            self.assertIn("export_presets.cfg", paths)
            self.assertEqual(template.renderer, "gl_compatibility")
            self.assertIn(template.engine_version, SUPPORTED_ENGINE_VERSIONS)
            self.assertFalse(template.manifest["external_content"])

    def test_templates_declare_win_lose_and_restart(self) -> None:
        for template in self.pack.templates():
            script = template.file("scripts/main.gd").content
            self.assertIn("_finish(", script)
            self.assertIn("ui_accept", script)
            self.assertIn("Press Enter", script)

    def test_template_digest_changes_with_content(self) -> None:
        template = self.pack.template("collector-2d")
        altered = GameTemplate.create(
            template.template_id, title=template.title, summary=template.summary,
            version=template.version, main_scene=template.main_scene,
            files=tuple(
                TemplateFile.create(entry.path, entry.content + " ")
                if entry.path == "scripts/main.gd" else entry
                for entry in template.files
            ),
        )
        self.assertNotEqual(template.digest, altered.digest)

    def test_template_rejects_unsafe_paths_and_missing_project(self) -> None:
        with self.assertRaises(ValueError):
            TemplateFile.create("../escape.gd", "x")
        with self.assertRaises(ValueError):
            TemplateFile.create("/absolute.gd", "x")
        with self.assertRaises(ValueError):
            GameTemplate.create(
                "broken", title="t", summary="s", version="1.0.0",
                main_scene="scenes/main.tscn",
                files=(TemplateFile.create("scenes/main.tscn", "x"),),
            )

    def test_unknown_template_is_refused(self) -> None:
        with self.assertRaises(KeyError):
            self.pack.template("unreal-2d")

    def test_supported_engine_range(self) -> None:
        self.assertTrue(self.pack.supports("4.3.stable.official"))
        self.assertFalse(self.pack.supports("3.5.stable.official"))


class GodotPackMaterialisationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = GodotPack()
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.target = Path(self.directory.name) / "project"

    def _install(self) -> None:
        plan = self.pack.plan(self.target, "collector-2d")
        self.pack.apply(plan)

    def test_first_plan_creates_every_file(self) -> None:
        plan = self.pack.plan(self.target, "collector-2d")
        self.assertTrue(plan.safe)
        self.assertEqual(len(plan.creations), 6)
        self.assertEqual(plan.conflicts, ())
        preview = plan.preview()
        self.assertEqual(preview["requires_human_approval"], [])
        self.assertEqual(preview["plan_digest"], plan.digest)

        receipt = self.pack.apply(plan)
        self.assertEqual(len(receipt.written), 6)
        self.assertTrue((self.target / "project.godot").is_file())
        self.assertTrue((self.target / "scenes/main.tscn").is_file())
        state = json.loads((self.target / PACK_STATE_PATH).read_text(encoding="utf-8"))
        self.assertEqual(state["pack_key"], GODOT_PACK_KEY)
        self.assertEqual(state["template_id"], "collector-2d")
        self.assertEqual(len(state["files"]), 6)
        self.assertEqual(receipt.project_digest, state["project_digest"])

    def test_second_plan_keeps_everything(self) -> None:
        self._install()
        plan = self.pack.plan(self.target, "collector-2d")
        self.assertEqual(len(plan.kept), 6)
        self.assertEqual(plan.creations, ())
        self.assertTrue(plan.safe)
        receipt = self.pack.apply(plan)
        self.assertEqual(receipt.written, ())

    def test_authored_file_becomes_a_conflict_and_is_not_overwritten(self) -> None:
        self._install()
        authored = self.target / "scripts/main.gd"
        authored.write_text("extends Node2D\n# my own game\n", encoding="utf-8")

        plan = self.pack.plan(self.target, "collector-2d")
        self.assertEqual(plan.conflicts, ("scripts/main.gd",))
        self.assertFalse(plan.safe)
        self.assertEqual(plan.preview()["requires_human_approval"], ["scripts/main.gd"])

        with self.assertRaises(PackConflict):
            self.pack.apply(plan)
        self.assertIn("my own game", authored.read_text(encoding="utf-8"))

    def test_overwrite_requires_named_human_approval(self) -> None:
        self._install()
        authored = self.target / "scripts/main.gd"
        authored.write_text("extends Node2D\n# my own game\n", encoding="utf-8")
        plan = self.pack.plan(self.target, "collector-2d")

        with self.assertRaises(ValueError):
            self.pack.apply(plan, approved_overwrites=("scripts/main.gd",))
        self.assertIn("my own game", authored.read_text(encoding="utf-8"))

        receipt = self.pack.apply(
            plan, approved_overwrites=("scripts/main.gd",), actor="miha",
        )
        self.assertEqual(receipt.overwritten, ("scripts/main.gd",))
        self.assertEqual(receipt.actor, "miha")
        self.assertNotIn("my own game", authored.read_text(encoding="utf-8"))

    def test_approval_must_name_a_conflict_from_this_plan(self) -> None:
        self._install()
        plan = self.pack.plan(self.target, "collector-2d")
        with self.assertRaises(ValueError):
            self.pack.apply(plan, approved_overwrites=("scripts/player.gd",), actor="miha")

    def test_creator_owned_file_is_never_upgraded(self) -> None:
        self._install()
        readme = self.target / "README.md"
        readme.write_text("# My game\n", encoding="utf-8")
        plan = self.pack.plan(self.target, "collector-2d")
        self.assertIn("README.md", plan.kept)
        self.assertNotIn("README.md", plan.conflicts)
        self.pack.apply(plan)
        self.assertEqual(readme.read_text(encoding="utf-8"), "# My game\n")

    def test_untouched_pack_file_upgrades_cleanly(self) -> None:
        self._install()
        base = self.pack.template("collector-2d")
        upgraded_files = tuple(
            TemplateFile.create(entry.path, entry.content + "\n# pack upgrade\n")
            if entry.path == "scripts/player.gd" else entry
            for entry in base.files
        )
        upgraded = GodotPack((GameTemplate.create(
            base.template_id, title=base.title, summary=base.summary,
            version="1.1.0", main_scene=base.main_scene, files=upgraded_files,
        ),))

        plan = upgraded.plan(self.target, "collector-2d")
        self.assertEqual(plan.updates, ("scripts/player.gd",))
        self.assertEqual(plan.conflicts, ())
        self.assertEqual(plan.installed_version, "1.0.0")
        upgraded.apply(plan)
        self.assertIn(
            "# pack upgrade",
            (self.target / "scripts/player.gd").read_text(encoding="utf-8"),
        )

    def test_apply_refuses_a_plan_that_no_longer_matches_the_project(self) -> None:
        plan = self.pack.plan(self.target, "collector-2d")
        self.pack.apply(plan)
        (self.target / "scripts/player.gd").write_text("extends Node\n", encoding="utf-8")
        with self.assertRaises(PackConflict):
            self.pack.apply(plan)

    def test_apply_rejects_a_plan_from_another_template_revision(self) -> None:
        plan = self.pack.plan(self.target, "collector-2d")
        base = self.pack.template("collector-2d")
        other = GodotPack((GameTemplate.create(
            base.template_id, title=base.title, summary=base.summary,
            version="2.0.0", main_scene=base.main_scene,
            files=tuple(
                TemplateFile.create(entry.path, entry.content + "\n")
                if entry.path == "scripts/main.gd" else entry
                for entry in base.files
            ),
        ),))
        with self.assertRaises(ValueError):
            other.apply(plan)

    def test_switching_template_in_the_same_folder_reports_conflicts(self) -> None:
        self._install()
        plan = self.pack.plan(self.target, "platformer-2d")
        self.assertIn("scripts/main.gd", plan.conflicts)
        self.assertIsNone(plan.installed_version)

    def test_export_presets_are_readable_without_the_engine(self) -> None:
        self._install()
        self.assertEqual(
            export_presets(self.target), ("linux-x86_64", "windows-x86_64"),
        )
        self.assertEqual(export_presets(self.target / "missing"), ())

    def test_project_digest_follows_disk_state(self) -> None:
        self._install()
        before = self.pack.project_digest(self.target, "collector-2d")
        (self.target / "scripts/player.gd").write_text("extends Node\n", encoding="utf-8")
        self.assertNotEqual(before, self.pack.project_digest(self.target, "collector-2d"))

    def test_unreadable_state_file_is_treated_as_absent(self) -> None:
        self._install()
        (self.target / PACK_STATE_PATH).write_text("{not json", encoding="utf-8")
        plan = self.pack.plan(self.target, "collector-2d")
        self.assertEqual(plan.creations, ())
        self.assertEqual(len(plan.kept), 6)


if __name__ == "__main__":
    unittest.main()
