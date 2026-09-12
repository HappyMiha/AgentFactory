"""Two languages, or the catalogue is wrong."""

from __future__ import annotations

import unittest

from agent_factory.localisation import (
    CATALOGUE,
    DEFAULT_LANGUAGE,
    LANGUAGES,
    LocalisedError,
    Message,
    MissingTranslation,
    bundle,
    missing_translations,
    negotiate,
    normalise,
    translate,
)
from agent_factory.settings_registry import DEFINITIONS, SECTIONS, verify


class CatalogueTest(unittest.TestCase):
    def test_every_message_carries_every_language(self) -> None:
        self.assertEqual(missing_translations(CATALOGUE.values()), ())
        for key, message in CATALOGUE.items():
            with self.subTest(key=key):
                for language in LANGUAGES:
                    self.assertTrue(str(getattr(message, language)).strip())

    def test_a_half_translated_message_is_refused_at_construction(self) -> None:
        for pair in (("текст", ""), ("", "text"), ("текст", "   ")):
            with self.subTest(pair=pair):
                with self.assertRaises(MissingTranslation):
                    Message(*pair)

    def test_the_two_languages_actually_differ(self) -> None:
        """A copied Ukrainian string in the English slot is not a translation."""
        # Product names and identifiers are legitimately the same in both.
        allowed = {"app.name"}
        identical = [
            key for key, message in CATALOGUE.items()
            if key not in allowed and message.uk == message.en
        ]
        self.assertEqual(identical, [])

    def test_a_parameter_is_filled_in_both_languages(self) -> None:
        self.assertIn("7", translate("settings.summary.changed", "uk", count=7))
        self.assertIn("7", translate("settings.summary.changed", "en", count=7))

    def test_an_unknown_key_is_refused_rather_than_guessed(self) -> None:
        with self.assertRaises(KeyError):
            translate("nothing.here")

    def test_the_bundle_covers_the_whole_catalogue(self) -> None:
        for language in LANGUAGES:
            with self.subTest(language=language):
                self.assertEqual(len(bundle(language)), len(CATALOGUE))
        self.assertNotEqual(bundle("uk"), bundle("en"))
        self.assertEqual(len(bundle("en", prefix="settings.")),
                         sum(1 for key in CATALOGUE if key.startswith("settings.")))


class NegotiationTest(unittest.TestCase):
    def test_an_explicit_choice_wins(self) -> None:
        self.assertEqual(
            negotiate(explicit="en", stored="uk", accept_language="uk"), "en",
        )

    def test_a_stored_choice_beats_the_browser(self) -> None:
        self.assertEqual(negotiate(stored="en", accept_language="uk"), "en")

    def test_the_browser_preference_is_ranked_by_quality(self) -> None:
        self.assertEqual(negotiate(accept_language="uk;q=0.2, en;q=0.9"), "en")
        self.assertEqual(negotiate(accept_language="en;q=0.3, uk;q=0.8"), "uk")

    def test_a_regional_tag_resolves_to_its_language(self) -> None:
        self.assertEqual(negotiate(accept_language="en-GB,en;q=0.9"), "en")
        self.assertEqual(normalise("uk-UA"), "uk")

    def test_anything_unsupported_falls_back_to_the_default(self) -> None:
        for value in ("fr-FR", "", None, "klingon"):
            with self.subTest(value=value):
                self.assertEqual(negotiate(accept_language=value), DEFAULT_LANGUAGE)
        self.assertEqual(normalise("de"), DEFAULT_LANGUAGE)

    def test_a_malformed_quality_does_not_crash_the_page(self) -> None:
        self.assertEqual(negotiate(accept_language="en;q=abc"), "en")


class SettingsCatalogueTest(unittest.TestCase):
    def test_every_setting_is_described_in_both_languages(self) -> None:
        for definition in DEFINITIONS:
            with self.subTest(key=definition.key):
                self.assertEqual(missing_translations([definition.label]), ())
                self.assertEqual(missing_translations([definition.help]), ())
                self.assertNotEqual(definition.label.uk, definition.label.en)
                if definition.consequence is not None:
                    self.assertEqual(
                        missing_translations([definition.consequence]), (),
                    )

    def test_every_section_is_described_in_both_languages(self) -> None:
        for item in SECTIONS:
            with self.subTest(section=item.section_id):
                self.assertNotEqual(item.title.uk, item.title.en)
                self.assertNotEqual(item.summary.uk, item.summary.en)

    def test_every_finding_speaks_both_languages(self) -> None:
        values = {item.key: item.parse(item.default) for item in DEFINITIONS}
        for item in SECTIONS:
            for finding in verify(item.section_id, values):
                with self.subTest(section=item.section_id, summary=finding.summary.uk):
                    self.assertTrue(finding.record("uk")["summary"].strip())
                    self.assertTrue(finding.record("en")["summary"].strip())

    def test_a_validation_error_reaches_the_person_in_their_language(self) -> None:
        definition = next(item for item in DEFINITIONS if item.kind == "integer")
        try:
            definition.parse("0")
        except LocalisedError as error:
            self.assertNotEqual(error.text("uk"), error.text("en"))
            self.assertIn(definition.label.en, error.text("en"))
        else:  # pragma: no cover - the value is deliberately out of range
            self.fail("an out-of-range value must be refused")


if __name__ == "__main__":
    unittest.main()
