"""A level is supported only when a real project proved it, and nothing else."""

from __future__ import annotations

import json
import unittest

from agent_factory.capability_levels import (
    FEATURES,
    INVESTIGATIONS,
    SCOPE_OUTCOMES,
    CapabilityCatalogue,
    Level,
    LevelEvidence,
    PerformanceTarget,
    ScopeRequest,
    default_levels,
    load_evidence,
)


def full_evidence(catalogue: CapabilityCatalogue, level_id: str, **overrides):
    level = catalogue.level(level_id)
    checks = {criterion: True for criterion in level.acceptance}
    checks.update(overrides.pop("checks", {}))
    return LevelEvidence.create(
        level_id=level_id,
        reference_project=overrides.pop("reference_project", "reference/collector"),
        version_digest=overrides.pop("version_digest", "a" * 64),
        checks=checks,
        gameplay_reviewer=overrides.pop("gameplay_reviewer", "miha"),
        **overrides,
    )


class CatalogueTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalogue = CapabilityCatalogue()

    def test_every_level_starts_proposed_with_no_evidence(self) -> None:
        states = {status.level.level_id: status.state for status in self.catalogue.statuses()}
        self.assertEqual(
            set(states), {"simple-2d", "multi-level-2d", "small-3d"},
        )
        self.assertEqual(set(states.values()), {"proposed"})
        for status in self.catalogue.statuses():
            self.assertFalse(status.supported)
            self.assertEqual(status.evidence, ())
            self.assertEqual(len(status.unchecked), len(status.level.acceptance))

    def test_the_catalogue_covers_the_three_declared_shapes(self) -> None:
        levels = {level.level_id: level for level in default_levels()}
        self.assertEqual(levels["simple-2d"].dimension, "2d")
        self.assertIn("save_load", levels["multi-level-2d"].features)
        self.assertIn("multi_level", levels["multi-level-2d"].features)
        self.assertEqual(levels["small-3d"].dimension, "3d")
        for level in levels.values():
            self.assertIn("budget", level.acceptance)
            self.assertGreater(level.performance.frames_per_second, 0)
            self.assertTrue(level.record["budget"]["max_total_bytes"] > 0)

    def test_investigations_are_never_part_of_a_level(self) -> None:
        for level in default_levels():
            self.assertEqual(level.features & set(INVESTIGATIONS), frozenset())
        with self.assertRaises(ValueError):
            Level.create(
                "bad", title="t", summary="s", dimension="2d", engine="godot",
                engine_versions=("4.3",), features={"input", "multiplayer"},
                budget_profile="handheld",
                performance=PerformanceTarget(60, "1x1", 1.0, 1.0),
                acceptance={"a": "b"},
            )

    def test_level_definitions_are_validated(self) -> None:
        base = dict(
            title="t", summary="s", dimension="2d", engine="godot",
            engine_versions=("4.3",), features={"input"}, budget_profile="handheld",
            performance=PerformanceTarget(60, "1x1", 1.0, 1.0),
            acceptance={"a": "b"},
        )
        for change in (
            {"dimension": "4d"},
            {"budget_profile": "supercomputer"},
            {"features": {"telepathy"}},
            {"acceptance": {}},
            {"engine_versions": ()},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    Level.create("x", **{**base, **change})

    def test_duplicate_level_identifiers_are_refused(self) -> None:
        level = default_levels()[0]
        with self.assertRaises(ValueError):
            CapabilityCatalogue(levels=(level, level))

    def test_unknown_level_is_refused(self) -> None:
        with self.assertRaises(KeyError):
            self.catalogue.level("mmo")


class EvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalogue = CapabilityCatalogue()

    def test_complete_passing_evidence_makes_a_level_supported(self) -> None:
        self.catalogue.record_evidence(full_evidence(self.catalogue, "simple-2d"))
        status = self.catalogue.status("simple-2d")
        self.assertEqual(status.state, "supported")
        self.assertTrue(status.supported)
        self.assertEqual(status.unmet, ())
        self.assertEqual(status.unchecked, ())
        self.assertEqual(status.record["reviewers"], ["miha"])

    def test_a_missing_criterion_leaves_the_level_partial(self) -> None:
        level = self.catalogue.level("simple-2d")
        checks = {criterion: True for criterion in level.acceptance}
        checks.pop("restart")
        self.catalogue.record_evidence(LevelEvidence.create(
            level_id="simple-2d", reference_project="reference/collector",
            version_digest="a" * 64, checks=checks, gameplay_reviewer="miha",
        ))
        status = self.catalogue.status("simple-2d")
        self.assertEqual(status.state, "partial")
        self.assertEqual(status.unchecked, ("restart",))

    def test_a_failing_criterion_leaves_the_level_partial(self) -> None:
        self.catalogue.record_evidence(
            full_evidence(self.catalogue, "simple-2d", checks={"win_lose": False})
        )
        status = self.catalogue.status("simple-2d")
        self.assertEqual(status.state, "partial")
        self.assertEqual(status.unmet, ("win_lose",))

    def test_a_later_failure_removes_support(self) -> None:
        self.catalogue.record_evidence(full_evidence(self.catalogue, "simple-2d"))
        self.assertTrue(self.catalogue.status("simple-2d").supported)
        self.catalogue.record_evidence(full_evidence(
            self.catalogue, "simple-2d", checks={"restart": False},
            reference_project="reference/second", version_digest="b" * 64,
        ))
        self.assertEqual(self.catalogue.status("simple-2d").state, "partial")

    def test_two_projects_can_together_cover_a_level(self) -> None:
        level = self.catalogue.level("multi-level-2d")
        criteria = sorted(level.acceptance)
        half, rest = criteria[:4], criteria[4:]
        for index, group in enumerate((half, rest)):
            self.catalogue.record_evidence(LevelEvidence.create(
                level_id="multi-level-2d", reference_project=f"reference/{index}",
                version_digest=str(index) * 64,
                checks={criterion: True for criterion in group},
                gameplay_reviewer=f"reviewer-{index}",
            ))
        status = self.catalogue.status("multi-level-2d")
        self.assertEqual(status.state, "supported")
        self.assertEqual(status.record["reviewers"], ["reviewer-0", "reviewer-1"])

    def test_evidence_needs_a_named_person_who_played_it(self) -> None:
        with self.assertRaises(ValueError):
            LevelEvidence.create(
                level_id="simple-2d", reference_project="p", version_digest="d",
                checks={"playable_round": True}, gameplay_reviewer="  ",
            )

    def test_evidence_input_is_validated(self) -> None:
        base = dict(
            level_id="simple-2d", reference_project="p", version_digest="d",
            checks={"playable_round": True}, gameplay_reviewer="miha",
        )
        for change in (
            {"reference_project": ""}, {"version_digest": " "}, {"checks": {}},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    LevelEvidence.create(**{**base, **change})

    def test_evidence_cannot_invent_criteria(self) -> None:
        with self.assertRaises(ValueError):
            self.catalogue.record_evidence(LevelEvidence.create(
                level_id="simple-2d", reference_project="p", version_digest="d",
                checks={"looks_nice": True}, gameplay_reviewer="miha",
            ))

    def test_evidence_for_an_unknown_level_is_refused(self) -> None:
        with self.assertRaises(KeyError):
            self.catalogue.record_evidence(LevelEvidence.create(
                level_id="mmo", reference_project="p", version_digest="d",
                checks={"a": True}, gameplay_reviewer="miha",
            ))


class ScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalogue = CapabilityCatalogue()

    def request(self, *features, dimension="2d", engine="godot"):
        return ScopeRequest.create(
            "a game", features=features, dimension=dimension, engine=engine,
        )

    def test_without_evidence_nothing_is_guaranteed(self) -> None:
        answer = self.catalogue.scope(self.request("input", "ui"))
        self.assertEqual(answer.outcome, "scoped_prototype")
        self.assertFalse(answer.guarantee)
        self.assertIn("not verified yet", answer.statement)
        self.assertTrue(answer.missing_evidence)

    def test_a_verified_level_can_be_promised(self) -> None:
        self.catalogue.record_evidence(full_evidence(self.catalogue, "simple-2d"))
        answer = self.catalogue.scope(self.request("input", "ui"))
        self.assertEqual(answer.outcome, "supported")
        self.assertTrue(answer.guarantee)
        self.assertEqual(answer.level_id, "simple-2d")
        self.assertEqual(answer.excluded, ())

    def test_features_beyond_the_level_are_named_as_dropped(self) -> None:
        self.catalogue.record_evidence(full_evidence(self.catalogue, "simple-2d"))
        answer = self.catalogue.scope(self.request("input", "ui", "three_d"))
        self.assertEqual(answer.outcome, "scoped_prototype")
        self.assertFalse(answer.guarantee)
        self.assertIn("three_d", answer.excluded)
        self.assertIn("Left out of that prototype", answer.statement)

    def test_an_investigation_only_request_is_not_a_build(self) -> None:
        answer = self.catalogue.scope(self.request("multiplayer", "vr"))
        self.assertEqual(answer.outcome, "investigation")
        self.assertFalse(answer.guarantee)
        self.assertEqual(
            [area for area, _ in answer.investigations], ["multiplayer", "vr"],
        )
        self.assertIn("not scheduled as a build", answer.statement)

    def test_a_mixed_request_splits_the_investigation_out(self) -> None:
        self.catalogue.record_evidence(full_evidence(self.catalogue, "simple-2d"))
        answer = self.catalogue.scope(self.request("input", "ui", "multiplayer"))
        self.assertEqual(answer.outcome, "scoped_prototype")
        self.assertFalse(answer.guarantee)
        self.assertEqual([area for area, _ in answer.investigations], ["multiplayer"])
        self.assertIn("separate investigations", answer.statement)
        self.assertIn("input", answer.included)

    def test_every_investigation_states_why(self) -> None:
        for area, reason in INVESTIGATIONS.items():
            with self.subTest(area=area):
                self.assertGreater(len(reason), 40)
                answer = self.catalogue.scope(self.request(area))
                self.assertEqual(answer.investigations[0][1], reason)

    def test_an_unoffered_engine_is_not_a_prototype(self) -> None:
        answer = self.catalogue.scope(self.request("input", engine="unreal"))
        self.assertEqual(answer.outcome, "unsupported")
        self.assertFalse(answer.guarantee)
        self.assertIsNone(answer.level_id)
        self.assertIn("not something the factory can offer", answer.statement)

    def test_the_closest_level_is_the_one_missing_least(self) -> None:
        answer = self.catalogue.scope(self.request("input", "ui", "save_load"))
        self.assertEqual(answer.level_id, "multi-level-2d")
        simple = self.catalogue.scope(self.request("input", "ui"))
        self.assertEqual(simple.level_id, "simple-2d")

    def test_a_three_d_request_reaches_the_three_d_level(self) -> None:
        answer = self.catalogue.scope(
            self.request("input", "ui", "three_d", dimension="3d")
        )
        self.assertEqual(answer.level_id, "small-3d")

    def test_unknown_features_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            ScopeRequest.create("x", features={"time_travel"})
        with self.assertRaises(ValueError):
            ScopeRequest.create("x", features={"input"}, dimension="7d")

    def test_a_guarantee_never_appears_without_a_supported_outcome(self) -> None:
        self.catalogue.record_evidence(full_evidence(self.catalogue, "simple-2d"))
        requests = [
            self.request(*combination)
            for combination in (
                ("input",), ("input", "ui"), ("input", "ui", "audio"),
                ("input", "multiplayer"), ("three_d",), ("save_load", "vr"),
                ("input", "ui", "console"), ("open_world",),
            )
        ] + [self.request("input", engine="unity")]
        for request in requests:
            answer = self.catalogue.scope(request)
            with self.subTest(features=sorted(request.features)):
                self.assertIn(answer.outcome, SCOPE_OUTCOMES)
                if answer.guarantee:
                    self.assertEqual(answer.outcome, "supported")
                    self.assertEqual(answer.investigations, ())
                    self.assertEqual(answer.excluded, ())
                    self.assertTrue(
                        self.catalogue.status(answer.level_id).supported
                    )


class EvidenceDocumentTest(unittest.TestCase):
    def test_an_empty_document_is_the_honest_default(self) -> None:
        self.assertEqual(load_evidence({"evidence": []}), ())
        catalogue = CapabilityCatalogue(load_evidence({"evidence": []}))
        self.assertEqual(
            {status.state for status in catalogue.statuses()}, {"proposed"},
        )

    def test_a_document_round_trips(self) -> None:
        catalogue = CapabilityCatalogue()
        entry = full_evidence(catalogue, "simple-2d")
        document = json.dumps({"evidence": [entry.record]})
        loaded = load_evidence(document)
        self.assertEqual(loaded[0].reference_project, "reference/collector")
        rebuilt = CapabilityCatalogue(loaded)
        self.assertTrue(rebuilt.status("simple-2d").supported)

    def test_a_malformed_document_is_refused(self) -> None:
        for payload in ([], {"evidence": {}}, "[]"):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    load_evidence(payload)

    def test_the_catalogue_record_states_the_rule(self) -> None:
        record = CapabilityCatalogue().record
        self.assertEqual(len(record["levels"]), 3)
        self.assertEqual(len(record["separate_investigations"]), len(INVESTIGATIONS))
        self.assertIn("named person reviewed the gameplay", record["note"])
        self.assertEqual(len(FEATURES), 6)


if __name__ == "__main__":
    unittest.main()
