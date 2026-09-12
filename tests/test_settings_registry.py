"""Every setting declares what it is, what it costs, and where it came from."""

from __future__ import annotations

import unittest

from agent_factory import asset_provenance, godot_pack, unity_setup
from agent_factory.localisation import LANGUAGES, Message
from agent_factory.settings_registry import (
    BY_SECTION,
    DEFINITIONS,
    KINDS,
    SECTIONS,
    Finding,
    Setting,
    SettingError,
    section,
    setting,
    verify,
)


def defaults() -> dict[str, object]:
    return {item.key: item.parse(item.default) for item in DEFINITIONS}


class DeclarationTest(unittest.TestCase):
    def test_every_setting_belongs_to_a_declared_section(self) -> None:
        known = {item.section_id for item in SECTIONS}
        for item in DEFINITIONS:
            with self.subTest(key=item.key):
                self.assertIn(item.section, known)
                self.assertIn(item.kind, KINDS)
                for language in LANGUAGES:
                    self.assertTrue(getattr(item.label, language).strip())
                    self.assertTrue(getattr(item.help, language).strip())
                self.assertTrue(item.source.strip())

    def test_no_section_is_empty_and_keys_are_unique(self) -> None:
        keys = [item.key for item in DEFINITIONS]
        self.assertEqual(len(keys), len(set(keys)))
        for item in SECTIONS:
            self.assertTrue(BY_SECTION[item.section_id], item.section_id)

    def test_every_default_satisfies_its_own_rules(self) -> None:
        for item in DEFINITIONS:
            with self.subTest(key=item.key):
                item.parse(item.default)

    def test_a_sensitive_setting_must_state_its_consequence(self) -> None:
        for item in DEFINITIONS:
            if item.risk == "sensitive":
                with self.subTest(key=item.key):
                    self.assertIsNotNone(item.consequence)
                    for language in LANGUAGES:
                        self.assertTrue(getattr(item.consequence, language).strip())
        with self.assertRaises(ValueError):
            Setting(
                "x.y", "runtime", Message("Мітка", "Label"),
                Message("Довідка", "Help"), "boolean", "true", "src",
                risk="sensitive",
            )

    def test_derived_values_are_read_only_and_match_their_source(self) -> None:
        baseline = setting("godot.baseline_series")
        self.assertFalse(baseline.reconfigurable)
        self.assertEqual(baseline.default, godot_pack.BASELINE_ENGINE_VERSION)
        hub = setting("unity.hub_minimum")
        self.assertFalse(hub.reconfigurable)
        self.assertEqual(hub.default, unity_setup.UNITY_HUB_MINIMUM)

    def test_choices_come_from_the_modules_that_own_them(self) -> None:
        self.assertEqual(
            set(setting("assets.budget_profile").choices), set(asset_provenance.BUDGETS),
        )
        self.assertEqual(
            set(setting("unity.editor").choices), set(unity_setup.SUPPORTED_EDITORS),
        )
        self.assertEqual(
            set(setting("assets.default_licence").choices),
            set(asset_provenance.LICENCES),
        )

    def test_unknown_keys_and_sections_are_refused(self) -> None:
        with self.assertRaises(KeyError):
            setting("nope.nope")
        with self.assertRaises(KeyError):
            section("nowhere")


class ParsingTest(unittest.TestCase):
    def field(self, **overrides) -> Setting:
        base = dict(
            key="t.key", section="runtime", label=Message("Поле", "Field"),
            help=Message("Довідка", "Help"),
            kind="integer", default="10", source="test", minimum=1, maximum=100,
        )
        base.update(overrides)
        return Setting(**base)

    def test_numbers_respect_their_bounds(self) -> None:
        item = self.field()
        self.assertEqual(item.parse("42"), 42)
        for bad in ("0", "101", "abc", ""):
            with self.subTest(value=bad):
                with self.assertRaises(SettingError):
                    item.parse(bad)

    def test_booleans_accept_words_and_refuse_nonsense(self) -> None:
        item = self.field(kind="boolean", default="true", minimum=None, maximum=None)
        self.assertTrue(item.parse("yes"))
        self.assertFalse(item.parse("off"))
        with self.assertRaises(SettingError):
            item.parse("maybe")

    def test_choices_are_exact(self) -> None:
        item = self.field(
            kind="choice", default="a", choices=("a", "b"), minimum=None, maximum=None,
        )
        self.assertEqual(item.parse("b"), "b")
        with self.assertRaises(SettingError):
            item.parse("c")

    def test_lists_are_trimmed_unique_and_bounded(self) -> None:
        item = self.field(kind="list", default="", minimum=None, maximum=None)
        self.assertEqual(item.parse(" a , b "), ("a", "b"))
        self.assertEqual(item.parse(""), ())
        with self.assertRaises(SettingError):
            item.parse("a, a")
        restricted = self.field(
            kind="list", default="", choices=("a", "b"), minimum=None, maximum=None,
        )
        with self.assertRaises(SettingError):
            restricted.parse("a, zzz")

    def test_text_is_bounded_and_control_free(self) -> None:
        item = self.field(kind="text", default="x", minimum=None, maximum=None)
        self.assertEqual(item.parse("  hello  "), "hello")
        with self.assertRaises(SettingError):
            item.parse("x" * 600)
        with self.assertRaises(SettingError):
            item.parse("bad\x00value")

    def test_values_round_trip_through_format(self) -> None:
        self.assertEqual(Setting.format(True), "true")
        self.assertEqual(Setting.format(("a", "b")), "a, b")
        self.assertEqual(Setting.format(7), "7")

    def test_describe_reports_origin_and_change(self) -> None:
        item = self.field()
        described = item.describe(value="10", origin="default")
        self.assertEqual(described["label"], "Поле")
        self.assertEqual(
            item.describe(value="10", origin="default", language="en")["label"],
            "Field",
        )
        self.assertFalse(described["changed"])
        self.assertEqual(described["default_source"], "test")
        self.assertTrue(item.describe(value="11", origin="override")["changed"])


class CheckTest(unittest.TestCase):
    def test_defaults_produce_no_problem_anywhere(self) -> None:
        values = defaults()
        for item in SECTIONS:
            with self.subTest(section=item.section_id):
                levels = {finding.level for finding in verify(item.section_id, values)}
                self.assertNotIn("problem", levels)

    def test_the_godot_check_names_unverified_series(self) -> None:
        findings = verify("engine-godot", defaults())
        summaries = " ".join(finding.summary.uk for finding in findings)
        self.assertIn(godot_pack.BASELINE_ENGINE_VERSION, summaries)
        self.assertIn("без підтвердженого запуску", summaries)

    def test_an_asset_budget_that_cannot_be_met_is_a_problem(self) -> None:
        values = defaults()
        values["assets.max_asset_bytes"] = values["assets.max_total_bytes"] + 1
        findings = verify("assets", values)
        self.assertEqual(findings[0].level, "problem")

    def test_raising_a_budget_above_the_profile_is_flagged(self) -> None:
        values = defaults()
        values["assets.max_total_bytes"] = values["assets.max_total_bytes"] * 4
        levels = {finding.level for finding in verify("assets", values)}
        self.assertIn("attention", levels)

    def test_turning_off_a_guard_is_a_problem_not_a_note(self) -> None:
        for key, section_id in (
            ("updates.protect_pins", "updates"),
            ("updates.preserve_projects", "updates"),
            ("runtime.live_provider_approval_required", "runtime"),
        ):
            with self.subTest(key=key):
                values = defaults()
                values[key] = False
                levels = {
                    finding.level for finding in verify(section_id, values)
                }
                self.assertIn("problem", levels)

    def test_the_support_check_states_what_is_never_collected(self) -> None:
        findings = verify("support", defaults())
        self.assertIn("Облікові дані", findings[0].summary.uk)
        self.assertIn("Credentials", findings[0].summary.en)

    def test_the_unity_check_says_the_licence_is_not_read_here(self) -> None:
        summaries = " ".join(
            finding.summary.uk for finding in verify("engine-unity", defaults())
        )
        self.assertIn("ліцензії тут не читається", summaries)

    def test_a_public_default_visibility_is_flagged(self) -> None:
        values = defaults()
        values["export.default_visibility"] = "public"
        levels = {finding.level for finding in verify("export", values)}
        self.assertIn("attention", levels)

    def test_findings_serialise_in_the_asked_language(self) -> None:
        finding = Finding("ok", Message("так", "yes"), Message("бо", "because"))
        self.assertEqual(
            finding.record("uk"), {"level": "ok", "summary": "так", "detail": "бо"},
        )
        self.assertEqual(
            finding.record("en"),
            {"level": "ok", "summary": "yes", "detail": "because"},
        )


if __name__ == "__main__":
    unittest.main()
