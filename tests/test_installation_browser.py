from copy import deepcopy
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from agent_factory.storage import SQLiteStorage
from agent_factory.web import create_app
from test_installation_review import create_game, HOST
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None


@unittest.skipIf(sync_playwright is None,'Install Playwright and Chromium')
class InstallationBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime=sync_playwright().start();cls.browser=cls.runtime.chromium.launch()
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.runtime.stop()
    def setUp(self):
        import uvicorn
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.path=self.root/'state.db'
        storage=SQLiteStorage(self.path);self.mission=create_game(storage);storage.close()
        self.env=patch.dict(os.environ,{'AGENT_FACTORY_API_TOKEN':'synthetic-browser-install','AGENT_FACTORY_API_ACTOR':'Founder',
            'AGENT_FACTORY_API_ROLE':'operations_owner','AGENT_FACTORY_API_SCOPES':'read,write,approve,control',
            'AGENT_FACTORY_API_TENANTS':'local','AGENT_FACTORY_TEMPORAL_ENABLED':'false'})
        self.env.start();self.host=deepcopy(HOST)
        self.probe=patch('agent_factory.installation_review.observe_workspace',side_effect=lambda *_:deepcopy(self.host));self.probe.start()
        self.server=uvicorn.Server(uvicorn.Config(create_app(self.root,self.path),host='127.0.0.1',port=0,log_level='error',access_log=False))
        self.thread=threading.Thread(target=self.server.run,daemon=True);self.thread.start()
        deadline=time.monotonic()+10
        while not self.server.started and time.monotonic()<deadline:time.sleep(.01)
        if not self.server.started:raise RuntimeError('Installation server did not start')
        self.url=f'http://127.0.0.1:{self.server.servers[0].sockets[0].getsockname()[1]}'
        self.context=self.browser.new_context(extra_http_headers={'Authorization':'Bearer synthetic-browser-install'},viewport={'width':390,'height':844})
        self.page=self.context.new_page();self.page.set_default_timeout(7000);self.errors=[]
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
    def tearDown(self):
        try:self.context.close()
        finally:
            self.server.should_exit=True;self.thread.join(5);self.probe.stop();self.env.stop();self.temp.cleanup()
        self.assertFalse(self.thread.is_alive());self.assertEqual(self.errors,[])
    def open(self):
        self.page.goto(self.url+f'/installation/{self.mission}')
        self.page.wait_for_function("document.querySelector('#status').textContent==='Стан оновлено.'")
    def prepare(self):
        self.page.locator('#prepare').click();self.page.wait_for_selector('#proposal:not([hidden])')
    def test_normal_plan_link_review_confirmation_and_reload_at_390px(self):
        self.page.goto(self.url+f'/planning/{self.mission}');self.page.locator('#installation-link').click()
        self.page.wait_for_function("document.querySelector('#status').textContent==='Стан оновлено.'")
        self.prepare();self.assertEqual(self.page.locator('#packages article').count(),2)
        self.assertTrue(self.page.locator('#approve').is_disabled())
        self.page.locator('#confirmed').check();self.page.locator('#approve').click()
        self.page.wait_for_function("document.querySelector('#decision').textContent.includes('Погодження збережено')")
        self.page.reload();self.page.wait_for_function("document.querySelector('#decision').textContent.includes('Погодження збережено')")
        self.assertTrue(self.page.locator('#approve').is_disabled())
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),390)
        output=os.getenv('INSTALLATION_SCREENSHOT_DIR')
        if output:
            Path(output).mkdir(parents=True,exist_ok=True);self.page.screenshot(path=str(Path(output)/'installation-mobile.png'),full_page=True)
    def test_lost_approval_response_replays_exact_command_once(self):
        self.open();self.prepare()
        def lose(route):route.fetch();route.abort()
        pattern='**/api/approvals/installation/*';self.page.route(pattern,lose)
        self.page.locator('#confirmed').check();self.page.locator('#approve').click()
        self.page.wait_for_function("document.querySelector('#status').textContent.includes('Відповідь втрачено')")
        self.assertTrue(self.page.locator('#prepare').is_disabled())
        self.page.unroute(pattern,lose);self.page.locator('#retry').click()
        self.page.wait_for_function("document.querySelector('#decision').textContent.includes('Погодження збережено')")
        storage=SQLiteStorage(self.path)
        try:self.assertEqual(storage.db.execute('SELECT COUNT(*) FROM installation_review_decisions').fetchone()[0],1)
        finally:storage.close()
    def test_changed_host_requires_new_review_and_rejection_persists(self):
        self.open();self.prepare();self.host['free_bytes']=1
        self.page.locator('#confirmed').check();self.page.locator('#approve').click()
        self.page.wait_for_function("document.querySelector('#status').textContent.includes('Вільного місця стало менше')")
        self.assertTrue(self.page.locator('#proposal').is_hidden())
        self.prepare();self.assertTrue(self.page.locator('#approve').is_disabled())
        self.assertIn('місця',self.page.locator('#changes').inner_text());self.page.locator('#reject').click()
        self.page.wait_for_function("document.querySelector('#decision').textContent.includes('відхилено')")
        self.page.reload();self.page.wait_for_function("document.querySelector('#decision').textContent.includes('відхилено')")

    def test_planning_link_keeps_existing_unsaved_navigation_guard(self):
        self.page.goto(self.url+f'/planning/{self.mission}')
        self.page.wait_for_function("!document.querySelector('#fields').disabled")
        self.page.locator('#goal').fill('Keep this unsaved goal.')
        self.page.once('dialog',lambda dialog:dialog.dismiss())
        self.page.locator('#installation-link').click()
        self.assertIn('/planning/',self.page.url)
        self.assertEqual(self.page.locator('#goal').input_value(),'Keep this unsaved goal.')
        self.page.once('dialog',lambda dialog:dialog.accept())
        self.page.locator('#installation-link').click()
        self.page.wait_for_url('**/installation/*')

    def test_default_host_probe_in_actual_browser_without_host_fixture(self):
        import platform
        self.probe.stop()
        self.open();self.prepare()
        response=self.context.request.get(self.url+f'/api/installation-plans/{self.mission}').json()
        document=response['review']['plan']
        expected='windows-x86_64' if platform.system()=='Windows' and platform.machine().casefold() in {'amd64','x86_64'} else 'unsupported-host'
        self.assertEqual(document['platform'],expected)
        self.assertIsInstance(document['free_bytes'],int)
        self.assertFalse(document['execution_eligible'])
        self.assertEqual(self.page.locator('#packages article').count(),2)
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),390)
        output=os.getenv('INSTALLATION_SCREENSHOT_DIR')
        if output:
            Path(output).mkdir(parents=True,exist_ok=True);self.page.screenshot(path=str(Path(output)/'installation-native-mobile.png'),full_page=True)
