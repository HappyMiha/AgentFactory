"""A support bundle collects only what was selected, and shows it first."""

from __future__ import annotations

import json
import os
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_factory.support_bundle import (
    ALWAYS_INCLUDED,
    CATEGORIES,
    NEVER_COLLECTED,
    OPT_IN_CATEGORIES,
    README_FILE,
    SUPPORT_MANIFEST,
    SupportBundler,
    SupportRefused,
)


class SupportFixture(unittest.TestCase):
    """Shared helpers; no test methods are inherited by the suites below."""

    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Path(self.directory.name)
        logs = self.workspace / ".agent-factory" / "logs"
        logs.mkdir(parents=True)
        (logs / "worker.log").write_text(
            "started\nAKIAABCDEFGHIJKLMNOP used\nfinished\n", encoding="utf-8",
        )
        game = self.workspace / "game" / "scripts"
        game.mkdir(parents=True)
        (game / "main.gd").write_text("extends Node2D\n", encoding="utf-8")
        self.bundler = SupportBundler(self.workspace)
        self.output = self.workspace / "out" / "support.zip"


class SelectionTest(SupportFixture):
    def test_nothing_optional_is_collected_without_selection(self) -> None:
        preview = self.bundler.preview()
        self.assertEqual(preview.selected, ALWAYS_INCLUDED)
        self.assertEqual(set(preview.declined), set(OPT_IN_CATEGORIES))
        self.assertEqual({item.category for item in preview.items}, {"versions"})

    def test_logs_prompts_and_game_files_need_explicit_selection(self) -> None:
        for category in ("logs", "game_files"):
            with self.subTest(category=category):
                self.assertNotIn(
                    category, {item.category for item in self.bundler.preview().items},
                )
                chosen = self.bundler.preview(include=[category])
                self.assertIn(category, chosen.selected)
                self.assertIn(
                    category, {item.category for item in chosen.items},
                )

    def test_unknown_categories_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.bundler.preview(include=["credentials"])
        with self.assertRaises(ValueError):
            SupportBundler(self.workspace, collectors={"secrets": lambda: []})

    def test_credentials_have_no_collector_at_all(self) -> None:
        for never in NEVER_COLLECTED:
            self.assertNotIn(never, CATEGORIES)
        self.assertNotIn("credentials", self.bundler.collectors)

    def test_a_failing_collector_is_reported_not_raised(self) -> None:
        def broken():
            raise RuntimeError("disk went away")

        bundler = SupportBundler(self.workspace, collectors={"logs": broken})
        preview = bundler.preview(include=["logs"])
        self.assertEqual(preview.failures[0][0], "logs")
        self.assertIn("disk went away", preview.failures[0][1])
        self.assertTrue(preview.items)


class RedactionTest(SupportFixture):
    def test_secrets_in_logs_are_redacted_but_context_is_kept(self) -> None:
        preview = self.bundler.preview(include=["logs"])
        text = preview.read("worker.log")
        self.assertNotIn("AKIAABCDEFGHIJKLMNOP", text)
        self.assertIn("[redacted: aws access key]", text)
        self.assertIn("started", text)
        self.assertIn("aws access key", preview.redactions)

    def test_environment_collects_names_but_never_values(self) -> None:
        with patch.dict(
            os.environ,
            {"LOKVETIA_TEST_TOKEN": "super-secret-value-123", "LOKVETIA_TEST_PLAIN": "x"},
        ):
            preview = self.bundler.preview(include=["environment"])
            payload = json.loads(preview.read("environment.json"))
        names = {entry["name"]: entry for entry in payload["variables"]}
        self.assertIn("LOKVETIA_TEST_TOKEN", names)
        self.assertTrue(names["LOKVETIA_TEST_TOKEN"]["looks_sensitive"])
        self.assertFalse(names["LOKVETIA_TEST_PLAIN"]["looks_sensitive"])
        self.assertNotIn("super-secret-value-123", preview.read("environment.json"))
        self.assertNotIn("value", set(names["LOKVETIA_TEST_TOKEN"]))

    def test_a_local_path_in_a_log_is_redacted(self) -> None:
        (self.workspace / ".agent-factory/logs/paths.log").write_text(
            "wrote /home/miha/games/build.log\n", encoding="utf-8",
        )
        preview = self.bundler.preview(include=["logs"])
        self.assertNotIn("/home/miha/", preview.read("paths.log"))
        self.assertIn("local home path", preview.redactions)

    def test_the_preview_shows_size_and_redaction_counts(self) -> None:
        record = self.bundler.preview(include=["logs"]).record()
        entry = next(item for item in record["items"] if item["name"] == "worker.log")
        self.assertGreater(entry["size_bytes"], 0)
        self.assertIn("aws access key", entry["redactions"])
        self.assertEqual(record["never_collected"], list(NEVER_COLLECTED))


class BuildTest(SupportFixture):
    def test_the_package_matches_the_preview(self) -> None:
        preview = self.bundler.preview(include=["logs", "environment"])
        result = self.bundler.build(preview, output=self.output, actor="miha")
        self.assertEqual(result.preview_digest, preview.digest)
        self.assertEqual(len(result.checksum), 64)
        with zipfile.ZipFile(self.output) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read(SUPPORT_MANIFEST))
            readme = archive.read(README_FILE).decode("utf-8")
            log_text = archive.read("logs/worker.log").decode("utf-8")
        self.assertIn("versions/versions.json", names)
        self.assertIn("logs/worker.log", names)
        self.assertNotIn("game_files/scripts/main.gd", names)
        self.assertEqual(manifest["assembled_by"], "miha")
        self.assertIn("game_files", manifest["not_selected"])
        self.assertNotIn("AKIAABCDEFGHIJKLMNOP", log_text)
        self.assertIn("no collector exists", readme)

    def test_building_requires_a_named_owner(self) -> None:
        preview = self.bundler.preview()
        with self.assertRaises(ValueError):
            self.bundler.build(preview, output=self.output, actor="  ")
        self.assertFalse(self.output.exists())

    def test_a_changed_workspace_invalidates_the_reviewed_preview(self) -> None:
        preview = self.bundler.preview(include=["logs"])
        (self.workspace / ".agent-factory/logs/extra.log").write_text(
            "new\n", encoding="utf-8",
        )
        with self.assertRaises(SupportRefused):
            self.bundler.build(preview, output=self.output, actor="miha")
        self.assertFalse(self.output.exists())

    def test_acknowledging_a_different_preview_is_refused(self) -> None:
        preview = self.bundler.preview()
        with self.assertRaises(SupportRefused):
            self.bundler.build(
                preview, output=self.output, actor="miha", acknowledged_digest="f" * 64,
            )

    def test_item_paths_cannot_escape_their_category(self) -> None:
        bundler = SupportBundler(
            self.workspace,
            collectors={"logs": lambda: [("../../escape.txt", "content")]},
        )
        preview = bundler.preview(include=["logs"])
        bundler.build(preview, output=self.output, actor="miha")
        with zipfile.ZipFile(self.output) as archive:
            self.assertIn("logs/escape.txt", archive.namelist())

    def test_versions_are_always_present(self) -> None:
        preview = self.bundler.preview()
        payload = json.loads(preview.read("versions.json"))
        self.assertIn("core_version", payload)
        self.assertIn("python", payload)
        self.assertIn("platform", payload)


class StorageTest(SupportFixture):
    def setUp(self) -> None:
        super().setUp()
        from agent_factory.storage import SQLiteStorage

        self.storage = SQLiteStorage(self.workspace / "state.db")
        self.addCleanup(self.storage.close)
        self.bundler = SupportBundler(self.workspace, storage=self.storage)

    def test_versions_include_the_schema_version(self) -> None:
        payload = json.loads(self.bundler.preview().read("versions.json"))
        self.assertIsInstance(payload["schema_version"], int)
        self.assertGreaterEqual(payload["schema_version"], 78)

    def test_audit_events_are_opt_in_and_carry_no_payload(self) -> None:
        self.storage._event("test.event", "thing", 1, {"secret": "AKIAABCDEFGHIJKLMNOP"})
        self.assertNotIn(
            "audit_events", {item.category for item in self.bundler.preview().items},
        )
        preview = self.bundler.preview(include=["audit_events"])
        text = preview.read("audit-events.json")
        self.assertIn("test.event", text)
        self.assertNotIn("AKIAABCDEFGHIJKLMNOP", text)
        self.assertNotIn("payload", text)


if __name__ == "__main__":
    unittest.main()
