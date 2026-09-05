"""Chromium checks for the production specification preview and native dialog."""
import re
import unittest
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

STATIC = Path(__file__).resolve().parents[1] / "src/agent_factory/static"


@unittest.skipIf(sync_playwright is None, "Install Playwright for browser regression")
class SpecificationPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = sync_playwright().start()
        try:
            cls.browser = cls.runtime.chromium.launch()
        except Exception:
            cls.runtime.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.runtime.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.imports = []
        self.fail_import = False
        self.requirement = "Кіт збирає монети та має три життя."
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        upload = re.search(r'<details class="backlog-import"><summary>Upload technical specification.*?</details>', html, re.S).group()
        dialog = re.search(r'<dialog id="confirm-dialog".*?</dialog>', html, re.S).group()
        fixture = upload + dialog + '<p id="notice" hidden></p>'
        self.page.route("http://fixture.test/", lambda route: route.fulfill(body=fixture, content_type="text/html; charset=utf-8"))
        self.page.route("http://fixture.test/api/backlog/analyze-upload", lambda route: route.fulfill(json={
            "analysis_method": "deterministic_import", "analysis_status": "needs_review",
            "source_path": ".agent-factory/uploads/proposal.json", "original_path": ".agent-factory/uploads/original",
            "original_text": self.requirement + '<script>window.injected = true</script>',
            "items": [{"stable_id": "cat:task", "kind": "task", "title": 'Cat "game"', "description": self.requirement,
                       "acceptance_criteria": ["Collect coins", "Start with three lives"]}],
        }))
        self.page.route("http://fixture.test/api/backlog/import", self.intercept_import)
        self.page.goto("http://fixture.test/")
        source = (STATIC / "app.js").read_text(encoding="utf-8")
        common = source[:source.index("function renderDashboard")]
        confirm = source[source.index("let confirmationPending"):source.index("async function handleWorkAction")]
        preview = source[source.index("async function handleSpecificationUpload"):source.index("async function handleFounderDecision")]
        listener = next(line for line in source.splitlines() if line.startswith('$("spec-analysis").addEventListener("submit"'))
        upload_listener = next(line for line in source.splitlines() if line.startswith('$("spec-upload-form").addEventListener'))
        self.page.add_script_tag(content=common + confirm + preview + "async function refresh() {}\n" + listener + "\n" + upload_listener)
        self.page.locator("details > summary").first.click()
        self.page.locator('[name="project_name"]').fill("Cat game")
        self.page.locator('[name="specification"]').set_input_files({"name": "brief.txt", "mimeType": "text/plain", "buffer": self.requirement.encode("utf-8")})
        self.page.get_by_role("button", name="Prepare editable preview").click()
        self.page.locator("#spec-preview-form").wait_for()

    def tearDown(self):
        self.page.close()

    def intercept_import(self, route):
        self.imports.append(route.request.post_data_json)
        if self.fail_import:
            route.fulfill(status=400, json={"error": "Invalid fixture preview"})
        else:
            route.fulfill(json={"created": [1], "skipped": []})

    def test_upload_is_honest_reviewable_and_does_not_import_or_execute_source(self):
        self.assertEqual(self.imports, [])
        self.assertIn("No AI analysis was run", self.page.locator("#spec-analysis").inner_text())
        self.assertEqual(self.page.locator('[name="description"]').input_value(), self.requirement)
        self.assertEqual(self.page.locator('[name="title"]').input_value(), 'Cat "game"')
        self.assertIsNone(self.page.evaluate("window.injected"))

    def test_edits_survive_cancel_and_are_imported_only_after_confirmation(self):
        self.page.locator('[name="description"]').fill("Cat collects coins and has five lives.")
        self.page.locator('[name="acceptance_criteria"]').fill("Collect a coin\nStart with five lives")
        self.page.get_by_role("button", name="Confirm and import edited plan").click()
        self.page.keyboard.press("Escape")
        self.assertEqual(self.imports, [])
        self.assertIn("five lives", self.page.locator('[name="description"]').input_value())
        self.page.get_by_role("button", name="Confirm and import edited plan").click()
        self.page.locator("#confirm-action").click()
        self.page.wait_for_function("document.querySelector('[data-preview-status]').textContent.includes('Plan confirmed')")
        self.assertEqual(len(self.imports), 1)
        request = self.imports[0]
        self.assertTrue(request["confirmed"])
        self.assertEqual(request["reviewed_items"][0]["acceptance_criteria"], ["Collect a coin", "Start with five lives"])
        self.assertEqual(request["reviewed_items"][0]["description"], "Cat collects coins and has five lives.")

    def test_rejected_import_keeps_editable_draft_and_does_not_claim_confirmation(self):
        self.fail_import = True
        self.page.get_by_role("button", name="Confirm and import edited plan").click()
        self.page.locator("#confirm-action").click()
        self.page.wait_for_function("!document.getElementById('notice').hidden")
        self.assertEqual(self.page.locator('[data-preview-status]').inner_text(), "")
        self.assertTrue(self.page.locator('[data-import-analyzed]').is_enabled())
        self.assertEqual(self.page.locator('[name="description"]').input_value(), self.requirement)
