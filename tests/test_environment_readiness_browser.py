"""Actual Chromium against production readiness UI; HTTP responses are synthetic."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import unittest
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

STATIC = Path(__file__).resolve().parents[1] / 'src/agent_factory/static'


@unittest.skipIf(sync_playwright is None, "Install Playwright for actual browser checks")
class EnvironmentReadinessBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = sync_playwright().start()
        cls.browser = cls.runtime.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.runtime.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.posts = 0; self.fail = False; self.pages = []
        self.report = {'status': 'blocked', 'mode': 'unknown', 'next_action': 'Qualify the selected model.',
                       'checks': [{'key': 'model:Developer', 'installed': True, 'authenticated': False,
                                   'qualified': False, 'mode': 'unknown', 'ready': False,
                                   'detail': 'No qualification receipt.', 'next_action': 'Run the trusted verifier.'}]}
        self.page.route('http://fixture.test/api/**', self.respond)
        html = re.search(r'<details id="environment-panel".*?</details>', (STATIC/'index.html').read_text(), re.S).group()
        self.page.route('http://fixture.test/', lambda r: r.fulfill(body=html,content_type='text/html'))
        self.page.goto('http://fixture.test/')
        source=(STATIC/'app.js').read_text()
        common=source[:source.index('function renderDashboard')]
        functions=source[source.index('// This panel is separate'):source.index('const agentEditors')]
        events=source[source.index('$("environment-panel").addEventListener'):source.index('$("refresh").addEventListener')]
        self.page.add_script_tag(content=common+functions+events)
        self.page.locator('summary').click()
        self.page.wait_for_function('document.querySelectorAll("#environment-mission option").length > 1')
        self.page.select_option('#environment-mission','1')
        self.page.wait_for_function('!document.getElementById("environment-check").disabled')

    def respond(self, route):
        if '/api/environment/missions?' in route.request.url:
            self.pages.append(route.request.url)
            offset=200 if 'offset=200' in route.request.url else 0
            items=[{'id':i+1,'name':f'Approved mission {i+1}'} for i in range(offset,min(offset+200,201))]
            route.fulfill(json={'items':items,'total':201});return
        if route.request.method == 'POST':self.posts+=1
        if self.fail:route.fulfill(status=503,json={'error':{}})
        else:route.fulfill(json=self.report)

    def ready(self, seconds=60):
        self.report.update(status='ready', mode='live', next_action='Continue approved development.',
            checked_at=datetime.now(timezone.utc).isoformat(),
            expires_at=(datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat())
        self.report['checks'][0].update(authenticated=True,qualified=True,mode='live',ready=True)

    def check(self):
        self.page.locator('#environment-check').click()
        self.page.wait_for_function('!document.getElementById("environment-check").disabled')

    def test_distinct_states_and_no_automatic_probe(self):
        self.assertEqual(self.posts,0)
        text=self.page.locator('#environment-checks').inner_text()
        self.assertIn('Installed: yes',text);self.assertIn('Authenticated: not verified',text)
        self.assertIn('Qualified: not verified',text);self.assertIn('Mode: unknown',text)
        self.check();self.assertEqual(self.posts,1)

    def test_expiry_removes_positive_status_without_another_request(self):
        self.ready(seconds=1);self.check()
        self.assertIn('Selected route ready',self.page.locator('#environment-status').inner_text())
        self.page.wait_for_function('document.getElementById("environment-status").textContent.includes("expired")')
        self.assertEqual(self.page.locator('#environment-checks .ready').count(),0)
        self.assertEqual(self.posts,1)

    def test_failed_refresh_clears_previous_success(self):
        self.ready();self.check();self.fail=True;self.check()
        self.assertIn('unavailable',self.page.locator('#environment-status').inner_text())
        self.assertEqual(self.page.locator('#environment-checks article').count(),0)

    def test_simulation_or_empty_checks_never_show_ready(self):
        self.ready();self.report['mode']='simulation';self.check()
        self.assertIn('needs checks',self.page.locator('#environment-status').inner_text())
        self.ready();self.report['checks']=[];self.check()
        self.assertIn('needs checks',self.page.locator('#environment-status').inner_text())

    def test_mobile_readiness_cards_use_readable_full_width(self):
        self.page.add_style_tag(path=str(STATIC/'styles.css'))
        self.page.set_viewport_size({'width':390,'height':844})
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'))
        self.assertGreater(self.page.locator('#environment-checks article').bounding_box()['width'], 300)

    def test_missions_beyond_first_page_are_selectable(self):
        self.assertEqual(self.page.locator('#environment-mission option').count(),202)
        self.assertTrue(any('offset=200' in url for url in self.pages))
        self.page.select_option('#environment-mission','201')
        self.page.wait_for_function('!document.getElementById("environment-check").disabled')
        self.assertEqual(self.page.locator('#environment-mission').input_value(),'201')
