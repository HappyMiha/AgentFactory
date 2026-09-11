"""A manifest can record what was produced, and cannot claim acceptance without it.

Evidence names where to look and who recorded it. It is not a verdict: a
reviewer still has to read what it names. The gate here is narrow and blunt —
an item marked accepted with nothing recorded is refused by the canonical
loader and by the repository validator, so the two cannot drift apart.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from agent_factory.backlog import (
    EVIDENCE_KINDS,
    MAX_EVIDENCE,
    BacklogManifestError,
    Evidence,
    proposal_from_document,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import validate_backlog as validator  # noqa: E402

ENTRY = {"kind": "test", "reference": "tests/test_example.py", "recorded_by": "Reviewer"}


def item(stable_id: str = "AF-001", **overrides) -> dict:
    document = {
        "stable_id": stable_id,
        "kind": "task",
        "title": f"Title {stable_id}",
        "description": f"Description {stable_id}",
        "acceptance_criteria": ["An operator can verify the result."],
    }
    document.update(overrides)
    return document


def load(*items: dict):
    return proposal_from_document(
        {"schema_version": 1, "items": list(items)},
        source_path="examples/plan.json", source_sha256="a" * 64, source_name="plan",
    )


class EvidenceSchemaTests(unittest.TestCase):
    def test_an_item_without_evidence_stays_valid(self):
        proposal = load(item())
        self.assertEqual(proposal.items[0].evidence, ())
        self.assertFalse(proposal.items[0].accepted)

    def test_a_recorded_entry_keeps_its_kind_reference_and_author(self):
        proposal = load(item(evidence=[{**ENTRY, "note": "covers the criterion"}]))
        entry = proposal.items[0].evidence[0]
        self.assertEqual(entry, Evidence("test", "tests/test_example.py", "Reviewer",
                                         "covers the criterion"))
        self.assertEqual(entry.to_dict()["kind"], "test")

    def test_every_documented_kind_is_accepted(self):
        for kind in sorted(EVIDENCE_KINDS):
            with self.subTest(kind=kind):
                proposal = load(item(evidence=[{**ENTRY, "kind": kind}]))
                self.assertEqual(proposal.items[0].evidence[0].kind, kind)

    def test_an_invented_kind_is_refused(self):
        with self.assertRaises(BacklogManifestError):
            load(item(evidence=[{**ENTRY, "kind": "vibes"}]))

    def test_an_unknown_field_is_refused_rather_than_ignored(self):
        with self.assertRaises(BacklogManifestError) as refusal:
            load(item(evidence=[{**ENTRY, "verdict": "passed"}]))
        self.assertIn("verdict", str(refusal.exception))

    def test_a_reference_and_an_author_are_both_required(self):
        for missing in ("reference", "recorded_by"):
            with self.subTest(missing=missing):
                entry = {key: value for key, value in ENTRY.items() if key != missing}
                with self.assertRaises(BacklogManifestError):
                    load(item(evidence=[entry]))

    def test_an_oversized_reference_or_note_is_refused(self):
        with self.assertRaises(BacklogManifestError):
            load(item(evidence=[{**ENTRY, "reference": "x" * 400}]))
        with self.assertRaises(BacklogManifestError):
            load(item(evidence=[{**ENTRY, "note": "x" * 600}]))

    def test_the_same_reference_cannot_be_recorded_twice(self):
        with self.assertRaises(BacklogManifestError) as refusal:
            load(item(evidence=[ENTRY, dict(ENTRY)]))
        self.assertIn("twice", str(refusal.exception))

    def test_the_list_is_bounded(self):
        entries = [
            {**ENTRY, "reference": f"tests/test_{index}.py"}
            for index in range(MAX_EVIDENCE + 1)
        ]
        with self.assertRaises(BacklogManifestError):
            load(item(evidence=entries))

    def test_evidence_must_be_a_list_of_objects(self):
        for value in ("tests/test_example.py", {"kind": "test"}, ["tests/test_example.py"]):
            with self.subTest(value=value):
                with self.assertRaises(BacklogManifestError):
                    load(item(evidence=value))


class AcceptanceGateTests(unittest.TestCase):
    def test_acceptance_without_evidence_is_refused(self):
        for label in ("status:accepted", "status:done", "status:delivered"):
            with self.subTest(label=label):
                with self.assertRaises(BacklogManifestError) as refusal:
                    load(item(labels=[label]))
                self.assertIn("AF-001", str(refusal.exception))

    def test_acceptance_with_evidence_is_allowed(self):
        proposal = load(item(labels=["status:accepted"], evidence=[ENTRY]))
        self.assertTrue(proposal.items[0].accepted)

    def test_the_label_is_matched_whatever_its_case_or_spacing(self):
        with self.assertRaises(BacklogManifestError):
            load(item(labels=[" Status:Accepted "]))

    def test_a_proposed_item_needs_no_evidence(self):
        self.assertFalse(load(item(labels=["status:proposed"])).items[0].accepted)

    def test_the_refusal_names_every_offending_item(self):
        with self.assertRaises(BacklogManifestError) as refusal:
            load(item("AF-001", labels=["status:accepted"]),
                 item("AF-002", labels=["status:accepted"]))
        self.assertIn("AF-001", str(refusal.exception))
        self.assertIn("AF-002", str(refusal.exception))

    def test_the_round_trip_through_the_document_keeps_evidence(self):
        proposal = load(item(labels=["status:accepted"], evidence=[ENTRY]))
        # Through JSON, the way a manifest actually travels between tools.
        restored = proposal_from_document(
            json.loads(json.dumps(proposal.to_dict(), ensure_ascii=False)),
            source_path="examples/plan.json", source_sha256="a" * 64, source_name="plan",
        )
        self.assertEqual(restored.items[0].evidence, proposal.items[0].evidence)


class RepositoryValidatorTests(unittest.TestCase):
    """The script and the loader refuse the same manifests."""

    def test_the_script_accepts_a_recorded_entry(self):
        self.assertEqual(validator.validate_evidence("AF-001", item(evidence=[ENTRY])), 1)

    def test_the_script_refuses_acceptance_without_evidence(self):
        with self.assertRaises(validator.ValidationError) as refusal:
            validator.validate_evidence("AF-001", item(labels=["status:accepted"]))
        self.assertIn("record what was produced", str(refusal.exception))

    def test_the_script_refuses_an_invented_kind_and_an_unknown_field(self):
        for entry in ({**ENTRY, "kind": "vibes"}, {**ENTRY, "verdict": "passed"}):
            with self.subTest(entry=entry):
                with self.assertRaises(validator.ValidationError):
                    validator.validate_evidence("AF-001", item(evidence=[entry]))

    def test_the_script_reports_the_number_of_recorded_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "examples").mkdir()
            source = Path(__file__).resolve().parents[1] / "examples/game-creator-backlog.json"
            document = json.loads(source.read_text(encoding="utf-8-sig"))
            for entry in document["items"]:
                if entry["stable_id"] == "AF-GC-001":
                    entry["evidence"] = [ENTRY]
            (root / "examples/game-creator-backlog.json").write_text(
                json.dumps(document, ensure_ascii=False), encoding="utf-8"
            )
            baseline = sum(
                len(entry.get("evidence", []))
                for entry in json.loads(source.read_text(encoding="utf-8-sig"))["items"]
            )
            results = validator.validate_repository(root)
            self.assertEqual(results[0][2], baseline + 1)

    def test_the_shipped_backlogs_still_validate(self):
        root = Path(__file__).resolve().parents[1]
        for name, count, recorded in validator.validate_repository(root):
            self.assertGreater(count, 0, name)
            self.assertGreaterEqual(recorded, 0, name)


if __name__ == "__main__":
    unittest.main()

class EvidenceBoundaryTests(unittest.TestCase):
    def test_malformed_evidence_is_rejected_before_acceptance(self):
        invalid = [None, [ENTRY, ENTRY], [ENTRY] * 21,
                   [{**ENTRY, "reference": None}], [{**ENTRY, "recorded_by": False}],
                   [{**ENTRY, "note": {}}], [{**ENTRY, "reference": "x" * 301}],
                   [{**ENTRY, "note": "x" * 501}]]
        for evidence in invalid:
            with self.subTest(evidence=evidence):
                with self.assertRaises(validator.ValidationError):
                    validator.validate_evidence("AF-001", {"evidence": evidence})
                with self.assertRaises(BacklogManifestError):
                    load(item(evidence=evidence))
