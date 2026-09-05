"""Real Chromium checks of production editor, refresh and confirmation functions."""
from copy import deepcopy
import re
import unittest
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

STATIC = Path(__file__).resolve().parents[1] / 'src/agent_factory/static'


@unittest.skipIf(sync_playwright is None, 'Install Playwright for browser regression')
class AgentDraftTests(unittest.TestCase):
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
        self.agent = dict(id='builder', name='Builder', role='developer', provider='deterministic',
                          model='simulation-v1', enabled=True, last_claimed_task_id=None,
                          reviewer_assignment_count=0, last_reviewed_run_id=None, permissions=['workspace:read'])
        self.providers = [dict(id=name, enabled=True, allowed_roles=['developer'], status='ready')
                          for name in ['deterministic', 'local-example']]
        self.agent_reads = 0
        self.posts = []
        self.fail_save = False
        self.removed = False
        html = (STATIC / 'index.html').read_text(encoding='utf-8')
        dialog = re.search(r'<dialog id="confirm-dialog".*?</dialog>', html, re.S).group()
        fixture = dialog + '<div id="agent-list"></div><div id="routing-list"></div><button id="refresh">Refresh</button><p id="notice" hidden></p><span id="connection-dot"></span><span id="connection-text"></span><span id="updated"></span>'
        self.page.route('http://fixture.test/', lambda route: route.fulfill(body=fixture, content_type='text/html; charset=utf-8'))
        self.page.route('http://fixture.test/api/**', self.respond)
        self.page.goto('http://fixture.test/')
        source = (STATIC / 'app.js').read_text(encoding='utf-8')
        common = source[:source.index('function renderDashboard')]
        editors = source[source.index('const agentEditors'):source.index('function renderFounderInbox')]
        confirmation = source[source.index('let confirmationPending'):source.index('async function handleWorkAction')]
        action = source[source.index('async function handleAgentAction'):source.index('async function handleSettingAction')]
        refresh = source[source.index('async function refresh()'):source.index('$("execution-list").addEventListener')]
        events = source[source.index('$("agent-list").addEventListener("click"'):source.index('$("audit-filters").addEventListener')]
        stubs = 'function renderDashboard() {} function renderMonitor() {} function renderExecutions() {} function renderFounderInbox() {} async function loadProjects() {} async function loadWork() {} async function loadAudit() {} async function loadSettings() {}'
        self.page.add_script_tag(content=common + editors + confirmation + action + refresh + stubs + events)
        self.page.evaluate('refresh()')
        self.model = self.page.locator('.agent-model')
        self.select = self.page.locator('.agent-provider')
        self.save = self.page.get_by_role('button', name='Save changes', exact=True)
        self.status = self.page.locator('[data-agent-edit-status]')

    def tearDown(self):
        self.page.close()

    def respond(self, route):
        url = route.request.url
        if route.request.method == 'POST':
            self.posts.append(route.request.post_data_json)
            if self.fail_save:
                route.fulfill(status=400, json={'error': {'message': 'Example rejected model'}})
            else:
                self.agent.update(provider=self.posts[-1]['provider'], model=self.posts[-1]['model'])
                route.fulfill(json={'agent': deepcopy(self.agent), 'impact_summary': 'Example updated'})
        elif '/api/agents?' in url:
            self.agent_reads += 1
            self.agent['last_claimed_task_id'] = self.agent_reads
            route.fulfill(json={'items': [] if self.removed else [deepcopy(self.agent)]})
        elif '/api/providers?' in url:
            route.fulfill(json={'items': deepcopy(self.providers)})
        else:
            route.fulfill(json={'items': []})

    def draft(self):
        self.select.select_option('local-example')
        self.model.fill('my-unsaved-model')

    def confirm(self):
        self.page.locator('#confirm-action').click()

    def test_three_real_five_second_cycles_preserve_nodes_draft_selection_and_caret(self):
        self.draft()
        self.model.focus()
        self.model.evaluate('(node) => { window.originalModel = node; node.setSelectionRange(3, 8); }')
        self.page.evaluate('window.editorRefreshTimer = setInterval(refresh, 5000)')
        self.page.wait_for_function("document.querySelector('.agent-facts').textContent.includes('Task #4')", timeout=20000)
        self.assertEqual(self.model.input_value(), 'my-unsaved-model')
        self.assertEqual(self.select.input_value(), 'local-example')
        self.assertTrue(self.page.evaluate('document.activeElement === window.originalModel && document.querySelector(".agent-model") === window.originalModel'))
        self.assertEqual(self.model.evaluate('(node) => [node.selectionStart, node.selectionEnd]'), [3, 8])
        self.assertEqual(self.posts, [])

    def test_server_change_preserves_draft_and_offers_both_versions(self):
        self.draft()
        self.agent['model'] = 'server-v2'
        self.page.evaluate('refresh()')
        self.assertTrue(self.page.locator('[data-agent-conflict]').is_visible())
        self.assertFalse(self.save.is_enabled())
        self.assertEqual(self.model.input_value(), 'my-unsaved-model')
        self.page.get_by_role('button', name='Use server version').click()
        self.assertEqual(self.model.input_value(), 'server-v2')
        self.assertEqual(self.select.input_value(), 'deterministic')
        self.assertIn('cancelled', self.status.inner_text())
        self.assertEqual(self.posts, [])

    def test_keep_draft_then_explicit_save_updates_server(self):
        self.draft()
        self.agent['model'] = 'server-v2'
        self.page.evaluate('refresh()')
        self.page.get_by_role('button', name='Keep my draft').click()
        self.assertTrue(self.save.is_enabled())
        self.save.click()
        self.confirm()
        self.page.wait_for_function("document.querySelector('[data-agent-edit-status]').textContent.startsWith('Changes saved')")
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.posts[0]['model'], 'my-unsaved-model')
        self.assertTrue(self.posts[0]['confirmed'])
        self.assertFalse(self.save.is_enabled())

    def test_cancel_resets_to_latest_server_without_post(self):
        self.draft()
        self.page.get_by_role('button', name='Cancel changes').click()
        self.assertEqual(self.model.input_value(), 'simulation-v1')
        self.assertIn('cancelled', self.status.inner_text())
        self.assertFalse(self.save.is_enabled())
        self.assertEqual(self.posts, [])

    def test_cancel_dialog_keeps_unsaved_draft(self):
        self.draft()
        self.save.click()
        self.page.keyboard.press('Escape')
        self.page.wait_for_function("document.querySelector('[data-agent-edit-status]').textContent.includes('Save cancelled')")
        self.assertEqual(self.model.input_value(), 'my-unsaved-model')
        self.assertTrue(self.save.is_enabled())
        self.assertEqual(self.posts, [])

    def test_change_while_confirmation_open_blocks_post_and_preserves_draft(self):
        self.draft()
        self.save.click()
        self.agent['model'] = 'changed-during-dialog'
        self.confirm()
        self.page.locator('[data-agent-conflict]').wait_for(state='visible')
        self.assertEqual(self.posts, [])
        self.assertEqual(self.model.input_value(), 'my-unsaved-model')
        self.assertFalse(self.save.is_enabled())

    def test_failed_save_keeps_draft_and_reports_failure(self):
        self.draft()
        self.fail_save = True
        self.save.click()
        self.confirm()
        self.page.wait_for_function("document.querySelector('[data-agent-edit-status]').textContent.startsWith('Save failed')")
        self.assertEqual(self.model.input_value(), 'my-unsaved-model')
        self.assertTrue(self.save.is_enabled())
        self.assertEqual(len(self.posts), 1)

    def test_missing_provider_keeps_selection_and_removed_agent_keeps_draft(self):
        self.draft()
        self.providers = [self.providers[0]]
        self.page.evaluate('refresh()')
        self.assertEqual(self.select.input_value(), 'local-example')
        self.assertIn('not currently available', self.select.inner_text())
        self.removed = True
        self.page.evaluate('refresh()')
        self.assertEqual(self.model.input_value(), 'my-unsaved-model')
        self.assertFalse(self.save.is_enabled())
        self.assertIn('no longer available', self.status.inner_text())

    def test_untouched_card_adopts_server_changes_without_replacing_controls(self):
        self.model.evaluate('(node) => window.originalModel = node')
        self.agent['model'] = 'server-v2'
        self.page.evaluate('refresh()')
        self.assertEqual(self.model.input_value(), 'server-v2')
        self.assertTrue(self.page.evaluate('document.querySelector(".agent-model") === window.originalModel'))
        self.assertFalse(self.page.locator('[data-agent-conflict]').is_visible())

    def test_late_refresh_response_cannot_restore_old_server_version(self):
        old = deepcopy(self.agent)
        self.page.evaluate('''(old) => {
          const realFetch = fetchJson;
          let hold = true;
          fetchJson = (url, options) => {
            if (url === '/api/agents?limit=200' && hold) {
              hold = false;
              return new Promise((resolve) => { window.releaseOldSnapshot = () => resolve({items: [old]}); });
            }
            return realFetch(url, options);
          };
          window.oldRefresh = refresh();
        }''', old)
        self.agent['model'] = 'newest-server-version'
        self.page.evaluate('refresh()')
        self.page.evaluate('async () => { window.releaseOldSnapshot(); await window.oldRefresh; }')
        self.assertEqual(self.model.input_value(), 'newest-server-version')
        self.assertFalse(self.page.locator('[data-agent-conflict]').is_visible())


if __name__ == '__main__':
    unittest.main()
