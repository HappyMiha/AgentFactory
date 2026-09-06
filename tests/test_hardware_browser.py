"""Real Chromium and production HTTP boundary with explicit read-only scan fixtures.

Use the exported installer also consumed by the central app composition task.
No engine, model inference, or hardware qualification is claimed by these fixtures.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from agent_factory.hardware_web import install_routes
from agent_factory.web import create_app

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


def inventory_fixture():
    return {
        'schema_version': 1, 'observed_at': '2026-09-06T03:00:00+00:00',
        'source': 'local_read_only',
        'os': {'name': 'Windows', 'release': '11', 'architecture': 'AMD64'},
        'cpu': {'name': 'Fixture CPU', 'logical_cores': 8},
        'memory': {'total_bytes': 16 * 1024 ** 3, 'available_bytes': None},
        'gpus': [], 'gpu_status': 'unknown',
        'disk': {'total_bytes': 512 * 1024 ** 3, 'free_bytes': 24 * 1024 ** 3,
                 'location': 'workspace_volume'},
        'software': [
            {'id': 'python', 'label': 'Python', 'status': 'detected', 'version': None},
            {'id': 'unreal', 'label': 'Unreal Engine', 'status': 'not_detected', 'version': None},
        ],
        'unknowns': [{'field': 'memory.available_bytes', 'reason': 'unavailable'},
                     {'field': 'gpus', 'reason': 'unavailable'}],
    }


@unittest.skipIf(sync_playwright is None, 'Install Playwright and Chromium for browser checks')
class HardwareBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = sync_playwright().start()
        cls.browser = cls.runtime.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.runtime.stop()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.report = inventory_fixture()
        self.calls = []
        self.collect = lambda: deepcopy(self.report)
        self.env = patch.dict(os.environ, {
            'AGENT_FACTORY_API_TOKEN': '', 'AGENT_FACTORY_API_ACTOR': 'Founder',
            'AGENT_FACTORY_API_ROLE': 'operations_owner',
            'AGENT_FACTORY_API_SCOPES': 'read,write,approve,control',
            'AGENT_FACTORY_API_TENANTS': '*', 'AGENT_FACTORY_SESSION_TTL_SECONDS': '900',
            'AGENT_FACTORY_TEMPORAL_ENABLED': 'false',
        })
        self.env.start()
        self.start_server()
        self.context = self.browser.new_context(accept_downloads=True, locale='uk-UA')
        self.page = self.context.new_page()
        self.page.set_default_timeout(7000)
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))

    def start_server(self):
        import uvicorn

        def collect(workspace):
            self.calls.append(workspace)
            return self.collect()

        # Bind before create_app so both the Core007 base and Core010's default
        # composition exercise this fixture through the same real installer.
        with patch('agent_factory.hardware_web.collect_inventory', collect):
            self.app = create_app(self.root, self.root / 'state.db')
            if not getattr(self.app.state, 'hardware_routes_installed', False):
                install_routes(self.app, self.root)
        self.server = uvicorn.Server(uvicorn.Config(
            self.app, host='127.0.0.1', port=0, log_level='error', access_log=False))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started and time.monotonic() < deadline:
            time.sleep(.01)
        if not self.server.started:
            raise RuntimeError('Hardware browser server did not start')
        self.url = f'http://127.0.0.1:{self.server.servers[0].sockets[0].getsockname()[1]}'

    def stop_server(self):
        self.server.should_exit = True
        self.thread.join(5)
        if self.thread.is_alive():
            raise RuntimeError('Hardware browser server did not stop')

    def tearDown(self):
        self.context.close()
        self.stop_server()
        self.env.stop()
        self.temp.cleanup()
        self.assertEqual(self.errors, [])

    def open_hardware(self):
        self.page.goto(self.url + '/hardware')
        self.page.get_by_role('heading', name='Можливості ПК', exact=True).wait_for()

    def scan(self):
        self.page.locator('#scan-pc').click()
        self.page.wait_for_function(
            "document.querySelector('#status').textContent.startsWith('Перевірку завершено')")

    def screenshot(self, name):
        output = os.environ.get('HARDWARE_SCREENSHOT_DIR')
        if output:
            Path(output).mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(Path(output) / name), full_page=True)

    def test_explicit_scan_unknown_is_not_zero_and_download_is_local_only(self):
        requests = []
        self.page.on('request', lambda request: requests.append(request.url))
        self.open_hardware()
        self.assertEqual(self.calls, [])
        self.assertTrue(self.page.locator('#inventory').is_hidden())
        self.assertTrue(self.page.locator('#download-report').is_disabled())
        self.assertFalse(any('/api/hardware/' in url for url in requests))
        self.scan()
        self.assertEqual(self.calls, [self.root])
        self.assertIn('Невідомо', self.page.locator('#memory-card').inner_text())
        self.assertNotIn('0 Б', self.page.locator('#memory-card').inner_text())
        self.assertIn('не означає, що її немає', self.page.locator('#gpu-card').inner_text())
        self.assertTrue(self.page.locator('#unknown-note').is_visible())
        self.assertIn('Не виявлено у відомих місцях', self.page.locator('#software-list').inner_text())
        self.assertIn('Виявлено · версія: Невідомо', self.page.locator('#software-list').inner_text())
        self.assertTrue(self.page.get_by_role('link', name='Повернутися до моїх ігор →').is_visible())
        self.screenshot('hardware-desktop.png')
        with self.page.expect_download() as download:
            self.page.locator('#download-report').click()
        self.assertEqual(download.value.suggested_filename, 'agentfactory-hardware.json')
        self.assertEqual(json.loads(Path(download.value.path()).read_text(encoding='utf-8')), self.report)
        self.assertEqual(self.calls, [self.root], 'Downloading must not trigger another scan')
        self.assertTrue(all(url.startswith(self.url + '/') or url.startswith('blob:') for url in requests))
        self.assertEqual(self.page.evaluate('[localStorage.length, sessionStorage.length]'), [0, 0])
        self.page.reload()
        self.assertTrue(self.page.locator('#inventory').is_hidden())
        self.assertTrue(self.page.locator('#download-report').is_disabled())
        self.assertEqual(self.calls, [self.root], 'Reload must neither persist nor refresh a report')

    def test_integrated_shared_memory_real_zero_and_untrusted_label_on_mobile(self):
        hostile = 'Графіка ☃ <img src=x onerror="window.injected=true">'
        self.report['gpus'] = [{
            'name': hostile, 'kind': 'integrated', 'dedicated_total_bytes': None,
            'dedicated_free_bytes': None, 'shared_total_bytes': 4 * 1024 ** 3,
        }]
        self.report['gpu_status'] = 'detected'
        self.report['disk']['free_bytes'] = 0
        self.open_hardware()
        self.scan()
        self.assertEqual(self.page.locator('.gpu-name').inner_text(), hostile)
        self.assertEqual(self.page.locator('#gpu-card img').count(), 0)
        self.assertFalse(self.page.evaluate('Boolean(window.injected)'))
        graphics = self.page.locator('#gpu-card').inner_text()
        self.assertIn('Вбудована', graphics)
        self.assertIn('4 ГіБ', graphics)
        self.assertIn('Невідомо', graphics)
        self.assertIn('0 Б', self.page.locator('#disk-card').inner_text())
        self.assertNotIn('Невідомо', self.page.locator('#disk-card').inner_text())
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'))
        self.assertTrue(self.page.locator('#scan-pc').is_visible())
        self.screenshot('hardware-mobile.png')

    def test_failed_rescan_retains_dated_report_and_omits_probe_exception(self):
        self.open_hardware()
        self.scan()
        before = self.page.locator('#hardware-cards').inner_text()
        stamp = self.page.locator('#observed-at').get_attribute('datetime')

        def fail():
            raise RuntimeError('PRIVATE-PROBE-DETAIL-DO-NOT-EXPOSE')

        self.collect = fail
        self.page.locator('#scan-pc').click()
        self.page.wait_for_function("document.querySelector('#status').dataset.state === 'error'")
        self.assertIn('попередній звіт; його не оновлено', self.page.locator('#status').inner_text())
        self.assertEqual(self.page.locator('#hardware-cards').inner_text(), before)
        self.assertEqual(self.page.locator('#observed-at').get_attribute('datetime'), stamp)
        self.assertNotIn('PRIVATE-PROBE', self.page.locator('body').inner_text())
        self.assertTrue(self.page.locator('#download-report').is_enabled())
        self.collect = lambda: deepcopy(self.report)
        self.scan()
        self.assertEqual(len(self.calls), 3, 'A later explicit retry must work')

    def test_slow_actual_scan_keeps_home_responsive_and_rejects_duplicate(self):
        entered, release = threading.Event(), threading.Event()

        def slow():
            entered.set()
            if not release.wait(10):
                raise RuntimeError('Synthetic scan barrier timed out')
            return deepcopy(self.report)

        self.collect = slow
        self.open_hardware()
        try:
            self.page.locator('#scan-pc').click()
            self.assertTrue(entered.wait(2), 'The actual scan endpoint must reach the collector')
            self.assertTrue(self.page.locator('#scan-pc').is_disabled())
            self.page.evaluate("""() => {
                window.concurrentReads = Promise.all([
                    fetch('/'), fetch('/api/games/starts'),
                    fetch('/api/hardware/scan', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'})
                ]).then(responses => {window.readStatuses = responses.map(response => response.status);});
            }""")
            self.page.wait_for_function('Array.isArray(window.readStatuses)', timeout=2500)
            self.assertEqual(self.page.evaluate('window.readStatuses'), [200, 200, 409])
            self.assertEqual(len(self.calls), 1)
        finally:
            release.set()
        self.page.wait_for_function(
            "document.querySelector('#status').textContent.startsWith('Перевірку завершено')")
        self.assertTrue(self.page.locator('#scan-pc').is_enabled())

    def test_expired_session_clears_report_and_returns_to_login_without_probe(self):
        self.stop_server()
        os.environ['AGENT_FACTORY_API_TOKEN'] = 'synthetic-hardware-browser-access'
        self.start_server()
        clock = [10.0]
        self.app.state.local_access.clock = lambda: clock[0]
        self.page.goto(self.url + '/hardware')
        self.page.locator('#token').fill('synthetic-hardware-browser-access')
        self.page.get_by_role('button', name='Sign in', exact=True).click()
        self.page.get_by_role('heading', name='Мої ігри', exact=True).wait_for()
        self.open_hardware()
        self.scan()
        clock[0] = 911.0
        self.page.locator('#scan-pc').click()
        self.page.wait_for_url(self.url + '/login')
        self.page.locator('#token').wait_for(state='visible')
        self.assertEqual(len(self.calls), 1, 'An expired session must be rejected before probing')
        self.assertEqual(self.page.locator('#inventory').count(), 0)
        self.assertEqual(self.page.evaluate('[localStorage.length, sessionStorage.length]'), [0, 0])


if __name__ == '__main__':
    unittest.main()
