"""Changing a setting from an interface: who, why, and what it replaced."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.settings_registry import SettingError, setting
from agent_factory.settings_store import (
    ConfirmationRequired,
    NotReconfigurable,
    SettingsCentre,
)
from agent_factory.storage import SQLiteStorage


class SettingsFixture(unittest.TestCase):
    """Shared helpers; no test methods are inherited by the suites below."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.storage = SQLiteStorage(Path(self.directory.name) / "state.db")
        self.addCleanup(self.storage.close)
        self.centre = SettingsCentre(self.storage)


class ReadTest(SettingsFixture):
    def test_a_fresh_workspace_is_entirely_default(self) -> None:
        overview = self.centre.overview()
        self.assertEqual(overview["changed_total"], 0)
        self.assertTrue(overview["sections"])
        for view in overview["sections"]:
            for field in view["fields"]:
                self.assertEqual(field["origin"], "default")
                self.assertFalse(field["changed"])

    def test_a_section_view_carries_fields_and_findings(self) -> None:
        view = self.centre.section_view("assets")
        self.assertEqual(view["section"], "assets")
        self.assertTrue(view["fields"])
        self.assertTrue(view["findings"])
        self.assertIn(view["worst_level"], {"ok", "attention", "problem"})

    def test_values_are_typed_not_text(self) -> None:
        self.assertIsInstance(self.centre.value("godot.max_seconds"), int)
        self.assertIsInstance(self.centre.value("updates.protect_pins"), bool)
        self.assertIsInstance(self.centre.value("godot.additional_series"), tuple)

    def test_an_unknown_key_is_refused(self) -> None:
        with self.assertRaises(KeyError):
            self.centre.value("nope.nope")
        with self.assertRaises(KeyError):
            self.centre.section_view("nowhere")


class WriteTest(SettingsFixture):
    def test_a_safe_change_needs_only_a_name(self) -> None:
        field = self.centre.set("godot.max_seconds", 300, actor="miha")
        self.assertEqual(field["value"], "300")
        self.assertEqual(field["origin"], "override")
        self.assertEqual(field["changed_by"], "miha")
        self.assertEqual(self.centre.value("godot.max_seconds"), 300)
        self.assertEqual(self.centre.overview()["changed_total"], 1)

    def test_a_change_without_a_person_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.centre.set("godot.max_seconds", 300, actor="   ")
        self.assertEqual(self.centre.value("godot.max_seconds"), 120)

    def test_an_invalid_value_is_refused_with_a_readable_reason(self) -> None:
        with self.assertRaises(SettingError) as caught:
            self.centre.set("godot.max_seconds", 2, actor="miha")
        self.assertIn("нижче", str(caught.exception).casefold().replace("below", "нижче"))
        self.assertEqual(self.centre.value("godot.max_seconds"), 120)

    def test_a_sensitive_change_needs_the_consequence_acknowledged(self) -> None:
        with self.assertRaises(ConfirmationRequired) as caught:
            self.centre.set("updates.protect_pins", False, actor="miha")
        self.assertIn(setting("updates.protect_pins").consequence, str(caught.exception))
        self.assertTrue(self.centre.value("updates.protect_pins"))

        self.centre.set(
            "updates.protect_pins", False, actor="miha", reason="міграція рушія",
            acknowledged_consequence=True,
        )
        self.assertFalse(self.centre.value("updates.protect_pins"))

    def test_a_derived_value_cannot_be_changed_here(self) -> None:
        for key in ("godot.baseline_series", "unity.hub_minimum", "godot.renderer"):
            with self.subTest(key=key):
                with self.assertRaises(NotReconfigurable):
                    self.centre.set(key, "x", actor="miha")

    def test_setting_the_default_value_clears_the_override(self) -> None:
        self.centre.set("godot.max_seconds", 300, actor="miha")
        field = self.centre.set("godot.max_seconds", 120, actor="miha")
        self.assertEqual(field["origin"], "default")
        self.assertEqual(self.centre.overview()["changed_total"], 0)
        actions = [item.action for item in self.centre.changes()]
        self.assertEqual(actions, ["reset", "set"])

    def test_writing_the_same_override_twice_records_one_change(self) -> None:
        self.centre.set("godot.max_seconds", 300, actor="miha")
        again = self.centre.set("godot.max_seconds", 300, actor="miha")
        self.assertFalse(again["changed"])
        self.assertEqual(len(self.centre.changes()), 1)

    def test_reset_returns_the_default_and_is_recorded(self) -> None:
        self.centre.set("godot.smoke_frames", 30, actor="miha")
        field = self.centre.reset("godot.smoke_frames", actor="olena", reason="назад")
        self.assertEqual(field["origin"], "default")
        self.assertEqual(field["value"], "180")
        latest = self.centre.changes()[0]
        self.assertEqual((latest.action, latest.actor, latest.reason), ("reset", "olena", "назад"))

    def test_resetting_an_untouched_setting_changes_nothing(self) -> None:
        field = self.centre.reset("godot.smoke_frames", actor="miha")
        self.assertFalse(field["changed"])
        self.assertEqual(self.centre.changes(), ())

    def test_resetting_a_sensitive_setting_also_needs_acknowledgement(self) -> None:
        self.centre.set(
            "updates.protect_pins", False, actor="miha", acknowledged_consequence=True,
        )
        with self.assertRaises(ConfirmationRequired):
            self.centre.reset("updates.protect_pins", actor="miha")
        self.centre.reset(
            "updates.protect_pins", actor="miha", acknowledged_consequence=True,
        )
        self.assertTrue(self.centre.value("updates.protect_pins"))

    def test_a_list_setting_round_trips(self) -> None:
        self.centre.set(
            "support.default_categories", "logs, configuration", actor="miha",
            acknowledged_consequence=True,
        )
        self.assertEqual(
            self.centre.value("support.default_categories"), ("logs", "configuration"),
        )


class HistoryTest(SettingsFixture):
    def test_history_records_what_was_replaced(self) -> None:
        self.centre.set("godot.max_seconds", 300, actor="miha", reason="повільний ПК")
        change = self.centre.changes()[0]
        self.assertEqual(change.key, "godot.max_seconds")
        self.assertEqual((change.previous_value, change.new_value), ("120", "300"))
        self.assertEqual(change.risk, "safe")
        self.assertEqual(change.reason, "повільний ПК")

    def test_history_can_be_filtered_and_is_bounded(self) -> None:
        self.centre.set("godot.max_seconds", 300, actor="miha")
        self.centre.set("godot.smoke_frames", 30, actor="miha")
        self.assertEqual(len(self.centre.changes(key="godot.max_seconds")), 1)
        with self.assertRaises(ValueError):
            self.centre.changes(limit=0)
        with self.assertRaises(ValueError):
            self.centre.changes(limit=1000)

    def test_history_cannot_be_rewritten(self) -> None:
        self.centre.set("godot.max_seconds", 300, actor="miha")
        for statement in (
            "UPDATE setting_changes SET actor='someone else'",
            "DELETE FROM setting_changes",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(sqlite3.IntegrityError):
                    with self.storage.db:
                        self.storage.db.execute(statement)

    def test_a_change_is_also_an_audit_event(self) -> None:
        self.centre.set("godot.max_seconds", 300, actor="miha")
        row = self.storage.db.execute(
            "SELECT event_type FROM events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(str(row["event_type"]), "setting.set")


class ResilienceTest(SettingsFixture):
    def test_an_override_the_rules_now_reject_falls_back_to_the_default(self) -> None:
        self.centre.set("godot.max_seconds", 300, actor="miha")
        with self.storage.db:
            self.storage.db.execute(
                "UPDATE setting_overrides SET value='999999' WHERE key='godot.max_seconds'"
            )
        self.assertEqual(self.centre.value("godot.max_seconds"), 120)
        self.assertEqual(
            self.centre.field("godot.max_seconds")["origin"], "default",
        )

    def test_an_override_for_a_removed_setting_is_ignored(self) -> None:
        with self.storage.db:
            self.storage.db.execute(
                """INSERT INTO setting_overrides(key,value,actor,reason,updated_at)
                   VALUES('gone.away','1','miha','','2026-01-01T00:00:00+00:00')"""
            )
        self.assertNotIn("gone.away", self.centre.overrides())
        self.assertEqual(self.centre.overview()["changed_total"], 0)


if __name__ == "__main__":
    unittest.main()
