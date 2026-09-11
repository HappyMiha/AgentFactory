"""A plain description keeps its meaning through a deterministic import (AF-GC-005).

The import never claims to have understood the text. It preserves the source,
splits only where the author separated requirements, and asks a question instead
of presenting a hollow plan as ready.
"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from agent_factory.backlog_analyzer import (
    MAX_REQUIREMENTS,
    analyze_specification,
    split_requirements,
)
from agent_factory.web import create_app

CAT_UK = "Кіт збирає монети, три життя."
CAT_EN = "A cat collects coins, three lives."


def analyze(text: str, name: str = "brief.txt"):
    return analyze_specification(text.encode("utf-8"), name)


@contextmanager
def upload(text: bytes, name: str):
    """Post one upload and keep its workspace alive while the caller inspects it."""
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        with TestClient(
            create_app(workspace, workspace / "state.db"), base_url="http://localhost"
        ) as client:
            response = client.post("/api/backlog/analyze-upload", files={"upload": (name, text)})
        yield response, workspace, (response.json() if response.status_code == 200 else {})


class SplitRequirementsTests(unittest.TestCase):
    def test_a_comma_separates_the_requirements_the_author_listed(self):
        self.assertEqual(split_requirements(CAT_UK), ("Кіт збирає монети", "три життя."))
        self.assertEqual(split_requirements(CAT_EN), ("A cat collects coins", "three lives."))

    def test_a_conjunction_alone_never_splits_one_requirement(self):
        for sentence in (
            "A cat collects coins and has three lives.",
            "Кіт збирає монети та має три життя.",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(split_requirements(sentence), (sentence,))

    def test_a_relative_clause_continues_its_requirement(self):
        for sentence in (
            "Гра про кота, який збирає монети.",
            "A game about a cat, that collects coins.",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(split_requirements(sentence), (sentence,))

    def test_sentences_and_line_breaks_separate_requirements(self):
        self.assertEqual(
            split_requirements("The cat runs. The cat jumps\nThe cat scores"),
            ("The cat runs.", "The cat jumps", "The cat scores"),
        )

    def test_a_leading_connective_is_dropped_from_the_stated_requirement(self):
        self.assertEqual(
            split_requirements("A cat collects coins, and it has three lives."),
            ("A cat collects coins", "it has three lives."),
        )

    def test_a_short_fragment_joins_its_neighbour_rather_than_disappearing(self):
        stated = split_requirements("The cat collects coins, quickly, and loses a life.")
        self.assertEqual(len(stated), 2)
        self.assertIn("quickly", " ".join(stated))

    def test_a_bullet_or_numbered_list_states_one_requirement_per_line(self):
        self.assertEqual(
            split_requirements("- Кіт збирає монети\n- Три життя\n1. Бонуси"),
            ("Кіт збирає монети", "Три життя", "Бонуси"),
        )

    def test_a_repeated_requirement_is_listed_once(self):
        self.assertEqual(split_requirements("Three lives. Three lives."), ("Three lives.",))

    def test_empty_text_states_no_requirement(self):
        self.assertEqual(split_requirements(""), ())
        self.assertEqual(split_requirements("   \n  "), ())

    def test_a_very_long_document_cannot_produce_unbounded_items(self):
        stated = split_requirements(" ".join(f"Requirement number {n}." for n in range(MAX_REQUIREMENTS + 50)))
        self.assertEqual(len(stated), MAX_REQUIREMENTS)


class PlainBriefTests(unittest.TestCase):
    def test_the_stated_requirements_appear_as_separate_editable_items(self):
        for brief in (CAT_UK, CAT_EN):
            with self.subTest(brief=brief):
                proposal = analyze(brief)
                leaves = [item for item in proposal.items if item.executable]
                self.assertEqual(len(leaves), 2)
                descriptions = " ".join(item.description for item in leaves)
                for requirement in split_requirements(brief):
                    self.assertIn(requirement, descriptions)

    def test_every_requirement_item_carries_its_own_acceptance_criterion(self):
        for item in analyze(CAT_EN).items:
            if item.executable:
                self.assertTrue(item.acceptance_criteria)
                self.assertIn(item.description, " ".join(item.acceptance_criteria))

    def test_the_original_text_survives_the_split_verbatim(self):
        for brief in (CAT_UK, CAT_EN):
            with self.subTest(brief=brief):
                self.assertEqual(analyze(brief).source_metadata["original_text"], brief)

    def test_the_split_is_declared_as_deterministic_and_not_as_analysis(self):
        notes = " ".join(
            note for item in analyze(CAT_EN).items for note in item.review_notes
        )
        self.assertIn("no AI analysis was run", notes)
        self.assertIn("Deterministic", notes)

    def test_every_requirement_item_traces_back_to_the_uploaded_source(self):
        digest = hashlib.sha256(CAT_EN.encode("utf-8")).hexdigest()
        for item in analyze(CAT_EN).items:
            self.assertTrue(
                any(digest in reference for reference in item.source_references),
                f"{item.stable_id} has no source trace",
            )

    def test_a_single_sentence_brief_stays_whole(self):
        brief = "A cat collects coins and has three lives."
        leaves = [item for item in analyze(brief).items if item.executable]
        self.assertEqual(len(leaves), 1)
        self.assertEqual(leaves[0].description, brief)


class ReadinessTests(unittest.TestCase):
    def test_a_brief_with_no_stated_title_asks_for_one(self):
        proposal = analyze(CAT_UK)
        self.assertFalse(proposal.source_metadata["plan_ready"])
        self.assertTrue(
            any("file name" in question for question in proposal.source_metadata["clarifications"])
        )

    def test_an_empty_filename_epic_is_never_a_ready_plan(self):
        proposal = analyze("# Гра\n", "game.md")
        self.assertFalse(proposal.source_metadata["plan_ready"])
        self.assertTrue(
            any("Гра" in question for question in proposal.source_metadata["clarifications"])
        )

    def test_a_section_without_requirements_is_named_in_the_question(self):
        proposal = analyze("# Game\nA cat collects coins.\n## Release\n", "game.md")
        questions = " ".join(proposal.source_metadata["clarifications"])
        self.assertIn("Release", questions)
        self.assertNotIn("'Game'", questions)

    def test_a_titled_brief_whose_sections_all_state_requirements_is_ready(self):
        proposal = analyze("# Game\nA cat collects coins.\n## Lives\nThe cat has three lives.", "game.md")
        self.assertEqual(proposal.source_metadata["clarifications"], [])
        self.assertTrue(proposal.source_metadata["plan_ready"])

    def test_a_document_of_empty_sections_cannot_flood_the_reviewer(self):
        from agent_factory.backlog_analyzer import MAX_CLARIFICATIONS

        text = "# Game\n" + "".join(f"## Section {n}\n" for n in range(MAX_CLARIFICATIONS + 10))
        questions = analyze(text, "game.md").source_metadata["clarifications"]
        self.assertEqual(len(questions), MAX_CLARIFICATIONS + 1)
        self.assertIn("further questions", questions[-1])

    def test_a_supplied_manifest_is_not_second_guessed(self):
        document = {
            "schema_version": 1,
            "items": [
                {
                    "stable_id": "E1",
                    "kind": "epic",
                    "title": "Game",
                    "description": "Game",
                    "acceptance_criteria": ["Works"],
                }
            ],
        }
        proposal = analyze_specification(json.dumps(document).encode("utf-8"), "plan.json")
        self.assertEqual(proposal.source_metadata["clarifications"], [])
        self.assertTrue(proposal.source_metadata["plan_ready"])

    def test_text_without_analyzable_content_is_refused_rather_than_guessed(self):
        with self.assertRaises(ValueError):
            analyze("   \n\n  ")


class UploadApiTests(unittest.TestCase):
    def test_the_preview_publishes_the_questions_and_the_readiness_state(self):
        with upload(CAT_UK.encode("utf-8"), "brief.txt") as (response, workspace, payload):
            self.assertEqual(response.status_code, 200)
            self.assertEqual(payload["analysis_method"], "deterministic_import")
            self.assertEqual(payload["analysis_status"], "needs_review")
            self.assertFalse(payload["plan_ready"])
            self.assertTrue(payload["clarifications"])
            self.assertEqual(payload["original_text"], CAT_UK)
            self.assertEqual(
            (workspace / payload["original_path"]).read_bytes(), CAT_UK.encode("utf-8")
            )
            leaves = [item for item in payload["items"] if item["kind"] == "task"]
            self.assertEqual(len(leaves), 2)
            self.assertIn("монети", leaves[0]["description"])
            self.assertIn("три життя", " ".join(item["description"] for item in leaves))

    def test_a_confirmed_manifest_upload_is_reported_as_a_ready_plan(self):
        body = json.dumps(
            {
                "schema_version": 1,
                "items": [
                    {
                        "stable_id": "E1",
                        "kind": "epic",
                        "title": "Game",
                        "description": "Game",
                        "acceptance_criteria": ["Works"],
                    }
                ],
            }
        ).encode("utf-8")
        with upload(body, "plan.json") as (response, _, payload):
            self.assertEqual(response.status_code, 200)
            self.assertTrue(payload["plan_ready"])
            self.assertEqual(payload["clarifications"], [])

    def test_a_pdf_brief_keeps_its_requirements_and_its_original_bytes(self):
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 200 Td (A cat collects coins, three lives.) Tj ET")
        page[NameObject("/Contents")] = stream
        output = io.BytesIO()
        writer.write(output)
        raw = output.getvalue()

        with upload(raw, "game.pdf") as (response, workspace, payload):
            self.assertEqual(response.status_code, 200)
            self.assertEqual((workspace / payload["original_path"]).read_bytes(), raw)
            descriptions = " ".join(
            item["description"] for item in payload["items"] if item["kind"] == "task"
            )
            self.assertIn("collects coins", descriptions)
            self.assertIn("three lives", descriptions)

    def test_an_unreadable_upload_produces_no_plan_at_all(self):
        with upload(b"%PDF-this-is-not-a-valid-document", "bad.pdf") as (response, _, _payload):
            self.assertNotEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
