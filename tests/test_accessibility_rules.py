"""The accessibility rules themselves, judged without a browser."""

from __future__ import annotations

import unittest

from agent_factory.accessibility import (
    COLLECTOR_SCRIPT,
    CRITERIA,
    Element,
    Issue,
    PageSnapshot,
    audit,
    contrast_ratio,
    relative_luminance,
    required_contrast,
    summarise,
)


def page(**overrides) -> dict:
    payload = {
        "url": "/x",
        "title": "Сторінка · Lokvetia Core",
        "lang": "uk",
        "viewport_width": 320,
        "document_width": 320,
        "elements": [],
        "headings": ["h1", "h2"],
        "landmarks": ["main", "nav"],
        "live_regions": ["#status"],
        "status_without_live": [],
        "first_focusable": "a.skip",
        "skip_link_target": "a.skip",
        "navigation_links": 3,
        "focus_order": ["a.skip", "#one"],
    }
    payload.update(overrides)
    return payload


def control(**overrides) -> dict:
    element = {
        "selector": "#one", "tag": "button", "name": "Зберегти", "text": "Зберегти",
        "visible": True, "disabled": False, "focusable": True,
        "focus_style_changes": True, "width": 80, "height": 32,
        "font_size_px": 16, "bold": False,
        "foreground": [16, 44, 53], "background": [255, 255, 255],
    }
    element.update(overrides)
    return element


class ContrastTest(unittest.TestCase):
    def test_known_ratios(self) -> None:
        self.assertEqual(contrast_ratio((255, 255, 255), (0, 0, 0)), 21.0)
        self.assertEqual(contrast_ratio((0, 0, 0), (255, 255, 255)), 21.0)
        self.assertEqual(contrast_ratio((255, 255, 255), (255, 255, 255)), 1.0)
        self.assertAlmostEqual(
            contrast_ratio((119, 119, 119), (255, 255, 255)), 4.48, places=2,
        )

    def test_luminance_endpoints(self) -> None:
        self.assertAlmostEqual(relative_luminance((0, 0, 0)), 0.0)
        self.assertAlmostEqual(relative_luminance((255, 255, 255)), 1.0)

    def test_large_text_has_a_lower_threshold(self) -> None:
        self.assertEqual(required_contrast(16, False), 4.5)
        self.assertEqual(required_contrast(19, False), 3.0)
        self.assertEqual(required_contrast(14, True), 3.0)
        self.assertEqual(required_contrast(13, True), 4.5)

    def test_text_below_the_threshold_is_a_problem(self) -> None:
        result = audit(page(elements=[control(
            foreground=[153, 153, 153], background=[255, 255, 255],
        )]))
        self.assertFalse(result.passed)
        issue = result.problems[0]
        self.assertEqual(issue.criterion, "1.4.3")
        self.assertIn("4.5", issue.summary)

    def test_the_same_colour_passes_as_large_text(self) -> None:
        colours = {"foreground": [140, 140, 140], "background": [255, 255, 255]}
        self.assertFalse(audit(page(elements=[control(**colours)])).passed)
        self.assertTrue(
            audit(page(elements=[control(font_size_px=24, **colours)])).passed
        )

    def test_an_element_without_measured_colours_is_not_judged(self) -> None:
        self.assertTrue(
            audit(page(elements=[control(foreground=None, background=None)])).passed
        )


class TargetSizeTest(unittest.TestCase):
    def test_a_small_control_is_a_problem(self) -> None:
        result = audit(page(elements=[control(width=20, height=20)]))
        self.assertEqual(result.problems[0].criterion, "2.5.8")

    def test_exactly_the_minimum_passes(self) -> None:
        self.assertTrue(audit(page(elements=[control(width=24, height=24)])).passed)

    def test_an_inline_link_in_a_sentence_is_excepted(self) -> None:
        self.assertTrue(audit(page(elements=[control(
            tag="a", inline=True, width=60, height=18,
        )])).passed)

    def test_a_disabled_or_exempt_control_is_not_measured(self) -> None:
        for change in ({"disabled": True}, {"exempt_target": True}):
            with self.subTest(change=change):
                self.assertTrue(
                    audit(page(elements=[control(width=10, height=10, **change)])).passed
                )

    def test_an_unmeasured_control_is_not_guessed_at(self) -> None:
        self.assertTrue(audit(page(elements=[control(width=0, height=0)])).passed)


class NameAndFocusTest(unittest.TestCase):
    def test_a_control_without_a_name_is_a_problem(self) -> None:
        result = audit(page(elements=[control(name="", text="")]))
        self.assertEqual(result.problems[0].criterion, "4.1.2")

    def test_a_hidden_or_disabled_control_is_not_required_to_have_one(self) -> None:
        for change in ({"visible": False}, {"disabled": True}):
            with self.subTest(change=change):
                self.assertTrue(
                    audit(page(elements=[control(name="", text="", **change)])).passed
                )

    def test_a_hidden_input_type_needs_no_name(self) -> None:
        self.assertTrue(audit(page(elements=[control(
            tag="input", input_type="hidden", name="", text="", width=0, height=0,
        )])).passed)

    def test_focus_that_changes_nothing_is_a_problem(self) -> None:
        result = audit(page(elements=[control(focus_style_changes=False)]))
        self.assertEqual(result.problems[0].criterion, "2.4.7")

    def test_a_non_focusable_element_is_not_asked_for_a_focus_ring(self) -> None:
        self.assertTrue(audit(page(elements=[control(
            focusable=False, focus_style_changes=False,
        )])).passed)


class DocumentTest(unittest.TestCase):
    def test_a_page_without_a_language_or_title_fails(self) -> None:
        criteria = {issue.criterion for issue in audit(page(lang="", title="")).problems}
        self.assertEqual(criteria, {"3.1.1", "2.4.2"})

    def test_a_language_outside_the_supported_pair_is_noted(self) -> None:
        issues = audit(page(lang="fr")).issues
        self.assertEqual(issues[0].criterion, "3.1.1")
        self.assertEqual(issues[0].level, "attention")

    def test_a_regional_tag_of_a_supported_language_passes(self) -> None:
        self.assertEqual(audit(page(lang="en-GB")).issues, ())

    def test_heading_and_landmark_structure_is_checked(self) -> None:
        levels = {issue.summary for issue in audit(page(headings=["h2"])).issues}
        self.assertTrue(any("першого рівня" in text for text in levels))
        self.assertTrue(any(
            "main" in issue.summary for issue in audit(page(landmarks=["nav"])).issues
        ))

    def test_two_visible_first_level_headings_are_noted(self) -> None:
        issues = audit(page(headings=["h1", "h1"])).issues
        self.assertIn("2", issues[0].summary)

    def test_a_bypass_link_is_expected_only_where_there_is_navigation(self) -> None:
        self.assertEqual(
            audit(page(skip_link_target="", navigation_links=0)).issues, (),
        )
        issues = audit(page(skip_link_target="", navigation_links=5)).issues
        self.assertEqual(issues[0].criterion, "2.4.1")

    def test_a_bypass_link_that_is_not_first_is_noted(self) -> None:
        issues = audit(page(first_focusable="#other")).issues
        self.assertEqual(issues[0].criterion, "2.4.1")
        self.assertEqual(issues[0].level, "attention")

    def test_overflow_is_reflow_on_a_narrow_screen_and_resize_on_a_wide_one(self) -> None:
        narrow = audit(page(viewport_width=320, document_width=400)).problems[0]
        self.assertEqual(narrow.criterion, "1.4.10")
        wide = audit(page(viewport_width=1280, document_width=1400)).problems[0]
        self.assertEqual(wide.criterion, "1.4.4")

    def test_one_pixel_of_rounding_is_tolerated(self) -> None:
        self.assertTrue(audit(page(document_width=320.5)).passed)

    def test_a_status_message_without_a_live_region_is_noted(self) -> None:
        issues = audit(page(status_without_live=["#status"])).issues
        self.assertEqual(issues[0].criterion, "4.1.3")
        self.assertEqual(issues[0].target, "#status")

    def test_a_repeated_focus_stop_is_noted(self) -> None:
        issues = audit(page(focus_order=["#a", "#a"])).issues
        self.assertEqual(issues[0].criterion, "2.4.3")


class ReportingTest(unittest.TestCase):
    def test_a_clean_page_reports_nothing(self) -> None:
        result = audit(page(elements=[control()]))
        self.assertTrue(result.passed)
        self.assertEqual(result.issues, ())
        self.assertIn("ok", result.report())

    def test_the_record_counts_problems_and_notes_separately(self) -> None:
        result = audit(page(
            lang="fr", elements=[control(width=10, height=10)],
        ))
        record = result.record
        self.assertEqual(record["problems"], 1)
        self.assertEqual(record["attention"], 1)
        self.assertFalse(record["passed"])

    def test_the_summary_lists_the_criteria_that_were_checked(self) -> None:
        summary = summarise([audit(page()), audit(page(title=""))])
        self.assertFalse(summary["passed"])
        self.assertEqual(summary["problems"], 1)
        self.assertEqual(len(summary["criteria_checked"]), len(CRITERIA))

    def test_an_issue_must_name_a_real_criterion_and_level(self) -> None:
        with self.assertRaises(ValueError):
            Issue("9.9.9", "problem", "x")
        with self.assertRaises(ValueError):
            Issue("1.4.3", "whatever", "x")

    def test_a_snapshot_tolerates_a_sparse_payload(self) -> None:
        snapshot = PageSnapshot.from_payload({"url": "/x"})
        self.assertEqual(snapshot.elements, ())
        self.assertEqual(snapshot.viewport_width, 0)
        self.assertIsInstance(audit(snapshot).issues, tuple)

    def test_the_collector_script_is_a_single_expression(self) -> None:
        self.assertTrue(COLLECTOR_SCRIPT.strip().startswith("() => {"))
        self.assertIn("getBoundingClientRect", COLLECTOR_SCRIPT)
        self.assertIn("focus-visible", COLLECTOR_SCRIPT)

    def test_an_element_knows_whether_it_is_interactive(self) -> None:
        self.assertTrue(Element("#a", "button").interactive)
        self.assertTrue(Element("#a", "div", role="link").interactive)
        self.assertFalse(Element("#a", "div").interactive)


if __name__ == "__main__":
    unittest.main()
