import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "src" / "agent_factory" / "static" / "index.html").read_text(
    encoding="utf-8"
)
CSS = (ROOT / "src" / "agent_factory" / "static" / "styles.css").read_text(
    encoding="utf-8"
)
CHECKLIST = (ROOT / "docs" / "accessibility-checklist.md").read_text(
    encoding="utf-8"
)


class AccessibilityParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: set[str] = set()
        self.duplicate_ids: set[str] = set()
        self.label_for: set[str] = set()
        self.unlabelled_controls: list[str] = []
        self.dialog_labels: list[str] = []
        self.label_depth = 0
        self.landmarks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        values = dict(attrs)
        element_id = values.get("id")
        if element_id:
            if element_id in self.ids:
                self.duplicate_ids.add(element_id)
            self.ids.add(element_id)
        if tag == "label":
            self.label_depth += 1
            if values.get("for"):
                self.label_for.add(str(values["for"]))
        if tag in {"input", "select", "textarea"}:
            labelled = self.label_depth > 0 or bool(values.get("aria-label"))
            if not labelled and (not element_id or element_id not in self.label_for):
                self.unlabelled_controls.append(element_id or f"<{tag}>")
        if tag == "dialog":
            self.dialog_labels.append(str(values.get("aria-labelledby", "")))
        if tag in {"main", "nav", "aside"}:
            self.landmarks.append(tag)

    def handle_endtag(self, tag: str):
        if tag == "label":
            self.label_depth -= 1


def luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    converted = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * converted[0] + 0.7152 * converted[1] + 0.0722 * converted[2]


def contrast(first: str, second: str) -> float:
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


class LocalControlCenterAccessibilityTests(unittest.TestCase):
    def test_semantics_labels_landmarks_and_dialog_names(self):
        parser = AccessibilityParser()
        parser.feed(HTML)
        self.assertIn('<html lang="en">', HTML)
        self.assertIn('<a class="skip-link" href="#main">', HTML)
        self.assertEqual(parser.landmarks.count("main"), 1)
        self.assertIn("nav", parser.landmarks)
        self.assertIn('aria-label="Primary navigation"', HTML)
        self.assertEqual(parser.duplicate_ids, set())
        self.assertEqual(parser.unlabelled_controls, [])
        self.assertTrue(parser.dialog_labels)
        self.assertTrue(all(label in parser.ids for label in parser.dialog_labels))
        self.assertNotRegex(HTML, r'tabindex="[1-9]')

    def test_keyboard_focus_motion_responsiveness_and_live_paths(self):
        self.assertIn(":focus-visible", CSS)
        self.assertIn("prefers-reduced-motion:reduce", CSS)
        self.assertGreaterEqual(CSS.count("@media(max-width:"), 3)
        for marker in (
            'role="status" aria-live="polite"',
            'id="work-detail" class="detail-pane" aria-live="polite"',
            'id="run-detail" class="run-detail" aria-live="polite"',
            'id="founder-detail" class="founder-detail" aria-live="polite"',
        ):
            self.assertIn(marker, HTML)
        self.assertNotRegex(HTML, r"<(div|span)[^>]+onclick=")

    def test_documented_contrast_and_manual_critical_path(self):
        self.assertGreaterEqual(contrast("#f3f7fb", "#09101b"), 4.5)
        self.assertGreaterEqual(contrast("#91a2b8", "#111b2a"), 4.5)
        for requirement in (
            "Skip to dashboard",
            "320 CSS pixels",
            "200% zoom",
            "reduced motion",
            "independent reviewer identity",
            "unresolved findings",
        ):
            self.assertIn(requirement, CHECKLIST)
        self.assertTrue(re.search(r"Escape.*without executing", CHECKLIST))


if __name__ == "__main__":
    unittest.main()
