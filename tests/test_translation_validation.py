"""Negative cases for bilingual documentation currency and invariant checks."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("translations", Path(__file__).resolve().parents[1] / "scripts/validate_translations.py")
translation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(translation)


class TranslationValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "docs/evolution"
        self.directory.mkdir(parents=True)
        self.source = "# Вимога\n\nAF-RSI-001: перевірка.\n"
        self.english = "# Requirement\n\nAF-RSI-001: verification.\n"
        self.write_pair()

    def write_pair(self):
        source_hash = translation.digest(self.source)
        english = f"<!-- translation-metadata:start -->\nSource SHA-256 (UTF-8/LF): `{source_hash}`\n<!-- translation-metadata:end -->\n" + self.english
        (self.directory / "one.md").write_bytes(self.source.encode("utf-8"))
        (self.directory / "one.en.md").write_bytes(english.encode("utf-8"))
        manifest = {"schema_version": 1, "hash_basis": "utf8_lf", "translations": [{"source": "docs/evolution/one.md", "translation": "docs/evolution/one.en.md", "source_sha256": source_hash, "translation_sha256": translation.digest(english)}]}
        (self.directory / "translations.json").write_text(json.dumps(manifest), encoding="utf-8")

    def errors(self):
        return translation.validate(self.root)[0]

    def test_current_pair_passes_with_crlf_checkout(self):
        for name in ("one.md", "one.en.md"):
            p = self.directory / name
            p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual([], self.errors())

    def test_source_edit_is_visibly_stale(self):
        (self.directory / "one.md").write_text(self.source + "Нова умова.\n", encoding="utf-8")
        self.assertTrue(any("STALE:" in error for error in self.errors()))

    def test_unreviewed_translation_edit_fails(self):
        p = self.directory / "one.en.md"
        p.write_text(p.read_text(encoding="utf-8") + "Different claim.\n", encoding="utf-8")
        self.assertTrue(any("UNREVIEWED:" in error for error in self.errors()))

    def test_changed_task_id_fails_even_with_refreshed_hash(self):
        self.english = self.english.replace("AF-RSI-001", "AF-RSI-002")
        self.write_pair()
        self.assertTrue(any("task-ID occurrence mismatch" in error for error in self.errors()))

    def test_missing_page_or_anchor_fails(self):
        self.english += "\n[missing](absent.en.md) · [heading](one.en.md#absent)\n"
        self.write_pair()
        self.assertEqual(2, sum("missing" in error for error in self.errors()))

    def test_new_source_needs_english_coverage(self):
        (self.directory / "two.md").write_text("# Нове\n", encoding="utf-8")
        self.assertTrue(any("Missing English coverage" in error for error in self.errors()))

    def test_traversal_path_is_rejected(self):
        with self.assertRaises(ValueError):
            translation.safe_path(self.root, "../outside.md")

    def test_dependencies_cannot_move_between_cards(self):
        source = "## AF-LW-001 — A\n\n**Залежності:** 002\n\n## AF-LW-002 — B\n\n**Залежності:** 003\n"
        english = "## AF-LW-001 — A\n\n**Dependencies:** 003\n\n## AF-LW-002 — B\n\n**Dependencies:** 002\n"
        errors = translation.check_card_fields("docs/evolution/backlog.en.md", source, english)
        self.assertEqual(2, len(errors))
        self.assertTrue(all("changed Dependencies" in error for error in errors))

    def test_dependency_namespaces_cannot_swap_with_equal_numeric_ids(self):
        source = "## AF-LW-001 — A\n\n**Залежності:** core:AF-RSI-003\n\n## AF-LW-002 — B\n\n**Залежності:** cloud:AF-LW-003\n"
        english = "## AF-LW-001 — A\n\n**Dependencies:** cloud:AF-LW-003\n\n## AF-LW-002 — B\n\n**Dependencies:** core:AF-RSI-003\n"
        self.assertEqual(translation.Counter(translation.TASK_ID.findall(source)), translation.Counter(translation.TASK_ID.findall(english)))
        errors = translation.check_card_fields("docs/evolution/backlog.en.md", source, english)
        self.assertEqual(2, len(errors))
        self.assertTrue(all("changed Dependencies" in error for error in errors))

    def test_abbreviated_dependencies_preserve_source_notation(self):
        source = "### AF-RSI-001 — A\n\n**Залежності:** 002, 003. **Reuse:** AF-004 policy.\n"
        english = "### AF-RSI-001 — A\n\n**Dependencies:** 002, 003. **Reuse:** AF-004 policy.\n"
        self.assertEqual([], translation.check_card_fields("docs/evolution/backlog.en.md", source, english))

    def test_reuse_bindings_cannot_move_between_cards(self):
        source = "### AF-RSI-001 — A\n\n**Reuse:** AF-004 policy.\n\n### AF-RSI-002 — B\n\n**Reuse:** AF-005 adapter.\n"
        english = "### AF-RSI-001 — A\n\n**Reuse:** AF-005 adapter.\n\n### AF-RSI-002 — B\n\n**Reuse:** AF-004 policy.\n"
        errors = translation.check_card_fields("docs/evolution/backlog.en.md", source, english)
        self.assertEqual(2, len(errors))
        self.assertTrue(all("changed Reuse identities" in error for error in errors))

    def test_duplicate_detailed_card_is_not_collapsed_by_dictionary(self):
        source = "## AF-LW-001 — A\n\n**Залежності:** 002\n"
        english = "## AF-LW-001 — A\n\n**Dependencies:** 002\n" * 2
        self.assertTrue(translation.check_card_fields("docs/evolution/backlog.en.md", source, english))

    def test_fenced_heading_is_not_a_rendered_anchor(self):
        self.english += "\n```markdown\n## Example-only\n```\n\n[broken](#example-only)\n"
        self.write_pair()
        self.assertTrue(any("missing heading anchor" in error for error in self.errors()))
        self.assertFalse(any("heading-count mismatch" in error for error in self.errors()))

    def test_links_and_headings_in_examples_are_not_rendered(self):
        text = "# Real\n~~~markdown\n# Hidden\n[example](missing.md)\n~~~~\n`[inline example](also-missing.md)`\n[real](#real)\n"
        (self.directory / "example.md").write_text(text, encoding="utf-8")
        self.assertEqual({"real"}, translation.anchors(text))
        self.assertEqual([], translation.check_links(self.root, "docs/evolution/example.md", text))

    def test_percent_encoded_link_cannot_escape_repository(self):
        errors = translation.check_links(self.root, "docs/evolution/one.en.md", "[escape](%2e%2e/%2e%2e/%2e%2e/outside.md)")
        self.assertTrue(any("link escapes repository" in error for error in errors))

    def test_empty_manifest_cannot_claim_success(self):
        for name in ("one.md", "one.en.md"):
            (self.directory / name).unlink()
        (self.directory / "translations.json").write_text(json.dumps({"schema_version": 1, "hash_basis": "utf8_lf", "translations": []}), encoding="utf-8")
        self.assertTrue(any("nonempty" in error for error in self.errors()))

    def test_task_id_suffix_is_not_a_valid_identity(self):
        self.english = self.english.replace("AF-RSI-001", "AF-RSI-001wrong")
        self.write_pair()
        self.assertTrue(any("task-ID occurrence mismatch" in error for error in self.errors()))

    def test_global_queue_allocations_remain_bound_to_each_requirement(self):
        source = "| 1 | **C-PILOT** — Scope | 2 | 2 | Gate |\n| 1 | `core:AF-001` | C-PILOT | One |\n| 2 | `core:AF-002` | C-SELF | Two |\n"
        english = source.replace("`core:AF-001` | C-PILOT", "`core:AF-001` | C-SELF").replace("`core:AF-002` | C-SELF", "`core:AF-002` | C-PILOT")
        errors = translation.check_planning_tables("docs/evolution/implementation-order.en.md", source, english)
        self.assertEqual(1, len(errors))
        self.assertIn("requirement order/allocation", errors[0])

    def test_legacy_table_dependencies_remain_bound_to_each_task(self):
        source = "| AF-GC-001 | P0 | M0 | M | A | AF-GC-003 |\n| AF-GC-002 | P0 | M0 | M | B | AF-GC-004 |\n"
        english = "| AF-GC-001 | P0 | M0 | M | A | AF-GC-004 |\n| AF-GC-002 | P0 | M0 | M | B | AF-GC-003 |\n"
        self.assertTrue(translation.check_planning_tables("docs/game-creator-backlog.en.md", source, english))


if __name__ == "__main__":
    unittest.main()
