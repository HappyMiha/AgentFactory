"""Native-dialog regression on a disposable page with intercepted mutations.

Run with: pip install playwright; python -m playwright install chromium
Then: python -m unittest discover -s tests -p test_dialog_confirmation.py -v
The optional browser suite is skipped when Playwright is not installed.
"""
import re
import unittest
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

STATIC = Path(__file__).resolve().parents[1] / 'src' / 'agent_factory' / 'static'


@unittest.skipIf(sync_playwright is None, 'Install Playwright to run browser regression')
class DialogConfirmationTests(unittest.TestCase):
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
        self.mutations = []
        html = (STATIC / 'index.html').read_text(encoding='utf-8')
        dialog = re.search(r'<dialog id="confirm-dialog".*?</dialog>', html, re.S).group()
        fixture = '<button id="launch">Archive</button><p id="notice" hidden></p>' + dialog
        self.page.route('http://fixture.test/', lambda route: route.fulfill(body=fixture, content_type='text/html'))
        self.page.route('http://fixture.test/mutation', self.intercept)
        self.page.goto('http://fixture.test/')
        source = (STATIC / 'app.js').read_text(encoding='utf-8')
        start = source.find('let confirmationPending')
        if start < 0:
            start = source.index('function confirmCommand')
        functions = source[start:source.index('async function handleWorkAction')]
        self.page.add_script_tag(content=source[:source.index('function renderDashboard')] + functions + '''
          window.results = [];
          document.getElementById('launch').onclick = () => {
            window.pending = guardedCommand('/mutation', { id: 7 }, 'Archive fixture');
            window.pending.then(value => results.push(value), error => results.push({ error: error.message }));
          };
        ''')

    def tearDown(self):
        self.page.close()

    def intercept(self, route):
        self.mutations.append(route.request.post_data_json)
        route.fulfill(json={'ok': True})

    def open_dialog(self):
        self.page.click('#launch')
        self.page.wait_for_function("document.getElementById('confirm-dialog').open")

    def finish(self):
        self.page.evaluate('() => window.pending')
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'launch')

    def confirm_once(self):
        self.open_dialog()
        self.page.click('#confirm-action')
        self.finish()
        self.assertEqual(len(self.mutations), 1)
        self.assertEqual(self.mutations[0], {'id': 7, 'confirmed': True})

    def test_confirm_then_escape_sends_no_new_mutation(self):
        self.confirm_once()
        self.open_dialog()
        self.page.keyboard.press('Escape')
        self.finish()
        self.assertEqual(len(self.mutations), 1)

    def test_confirm_then_cancel_sends_no_new_mutation(self):
        self.confirm_once()
        self.open_dialog()
        self.page.click('button[value="cancel"]')
        self.finish()
        self.assertEqual(len(self.mutations), 1)

    def test_programmatic_close_cannot_confirm(self):
        self.open_dialog()
        self.page.evaluate("document.getElementById('confirm-dialog').close('confirm')")
        self.finish()
        self.assertEqual(self.mutations, [])

    def test_duplicate_invocations_have_only_one_owner(self):
        self.page.focus('#launch')
        self.page.evaluate("document.getElementById('launch').click(); document.getElementById('launch').click()")
        self.page.click('#confirm-action')
        self.page.wait_for_function('results.length === 2')
        self.assertEqual(len(self.mutations), 1)
        self.assertEqual(self.page.evaluate('results.filter(x => x === null).length'), 1)

    def test_pending_request_prevents_reopening(self):
        self.page.unroute('http://fixture.test/mutation')
        held = []
        self.page.route('http://fixture.test/mutation', lambda route: held.append(route))
        self.open_dialog()
        self.page.click('#confirm-action')
        self.page.wait_for_function("!document.getElementById('confirm-dialog').open")
        self.page.click('#launch')
        self.assertFalse(self.page.evaluate("document.getElementById('confirm-dialog').open"))
        self.assertEqual(len(held), 1)
        held[0].fulfill(json={'ok': True})
        self.page.wait_for_function('results.length === 2')
        self.open_dialog()
        self.page.keyboard.press('Escape')
        self.finish()

    def assert_independent_command_remains_available(self, url, payload):
        self.page.unroute('http://fixture.test/mutation')
        held = []
        completed = []

        def intercept(route):
            if route.request.post_data_json.get('id') == 7:
                held.append(route)
                self.page.evaluate('window.fixtureRequestHeld = true')
            else:
                completed.append(route.request.post_data_json)
                route.fulfill(json={'ok': True})

        self.page.route('http://fixture.test/**', intercept)
        self.open_dialog()
        self.page.click('#confirm-action')
        self.page.wait_for_function("!document.getElementById('confirm-dialog').open")
        self.page.wait_for_function('window.fixtureRequestHeld === true')
        self.assertEqual(len(held), 1)
        self.page.evaluate("""([url, payload]) => {
            window.independent = guardedCommand(url, payload, 'Stop independent execution');
        }""", [url, payload])
        self.assertTrue(self.page.evaluate("document.getElementById('confirm-dialog').open"))
        self.page.click('#confirm-action')
        self.assertEqual(self.page.evaluate('() => window.independent'), {'ok': True})
        self.assertEqual(completed, [{**payload, 'confirmed': True}])
        self.assertEqual(self.page.evaluate('results.length'), 0)
        held[0].fulfill(json={'ok': True})
        self.finish()

    def test_pending_request_does_not_block_independent_cancel(self):
        self.assert_independent_command_remains_available('/api/executions/runs/99/cancel', {'reason': 'stop'})

    def test_pending_request_does_not_block_other_payload_at_same_endpoint(self):
        self.assert_independent_command_remains_available('/mutation', {'id': 8})

    def test_failed_request_releases_command(self):
        self.page.unroute('http://fixture.test/mutation')
        self.page.route('http://fixture.test/mutation', lambda route: route.fulfill(status=500, json={}))
        self.open_dialog()
        self.page.click('#confirm-action')
        self.page.wait_for_function('results.length === 1')
        self.open_dialog()
        self.page.keyboard.press('Escape')
        self.finish()

    def test_show_modal_failure_releases_confirmation(self):
        self.page.evaluate('''() => {
          const d = document.getElementById('confirm-dialog');
          const original = d.showModal;
          d.showModal = () => { throw new Error('fixture failure'); };
          document.getElementById('launch').click();
          d.showModal = original;
        }''')
        self.page.wait_for_function('results.length === 1')
        self.open_dialog()
        self.page.keyboard.press('Escape')
        self.finish()
        self.assertEqual(self.mutations, [])


if __name__ == '__main__':
    unittest.main()
