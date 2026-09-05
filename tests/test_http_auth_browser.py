"""Real loopback HTTP and Chromium session flow with synthetic credentials."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, 'Install Playwright and Chromium for browser session checks')
class LocalAccessBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import uvicorn
        from agent_factory.web import create_app
        cls.temp = tempfile.TemporaryDirectory()
        cls.env = patch.dict(os.environ, {'AGENT_FACTORY_API_TOKEN':'synthetic-browser-access',
            'AGENT_FACTORY_API_ACTOR':'Founder','AGENT_FACTORY_API_ROLE':'operations_owner',
            'AGENT_FACTORY_API_SCOPES':'read,write,approve,control','AGENT_FACTORY_API_TENANTS':'*',
            'AGENT_FACTORY_SESSION_TTL_SECONDS':'900','AGENT_FACTORY_TEMPORAL_ENABLED':'false'})
        cls.env.start()
        cls.app = create_app(Path(cls.temp.name),Path(cls.temp.name)/'state.db')
        cls.server = uvicorn.Server(uvicorn.Config(cls.app,host='127.0.0.1',port=0,log_level='error',access_log=False))
        cls.thread = threading.Thread(target=cls.server.run,daemon=True);cls.thread.start()
        try:
            deadline=time.monotonic()+10
            while not cls.server.started and time.monotonic()<deadline:
                time.sleep(.01)
            if not cls.server.started:
                raise RuntimeError('Local browser fixture server did not start')
            cls.url=f'http://127.0.0.1:{cls.server.servers[0].sockets[0].getsockname()[1]}'
            cls.runtime=sync_playwright().start()
            cls.browser=cls.runtime.chromium.launch()
        except Exception:
            cls.server.should_exit=True;cls.thread.join(5)
            if hasattr(cls,'runtime'):cls.runtime.stop()
            cls.env.stop();cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.runtime.stop()
        cls.server.should_exit=True;cls.thread.join(5)
        cls.env.stop();cls.temp.cleanup()
        if cls.thread.is_alive():raise RuntimeError('Local browser server did not stop')

    def setUp(self):
        self.context=self.browser.new_context()
        self.page=self.context.new_page()
        self.app.state.local_access.clock=time.monotonic

    def tearDown(self):
        self.context.close()
        self.app.state.local_access.clock=time.monotonic

    def login(self):
        self.page.goto(self.url+'/')
        self.page.locator('#token').fill('synthetic-browser-access')
        self.page.get_by_role('button',name='Sign in',exact=True).click()
        self.page.get_by_role('heading',name='Delivery overview').wait_for()

    def test_login_http_only_cookie_and_logout_replay(self):
        self.page.goto(self.url)
        self.assertEqual(self.page.evaluate("async () => (await fetch('/api/openapi.json')).status"),401)
        self.login()
        self.assertEqual(self.page.evaluate("async () => (await fetch('/api/openapi.json')).status"),200)
        cookies=self.context.cookies()
        session=next(c for c in cookies if c['name']=='agent_factory_session')
        self.assertTrue(session['httpOnly']);self.assertEqual(session['sameSite'],'Strict')
        self.assertNotIn('agent_factory_session',self.page.evaluate('document.cookie'))
        self.assertEqual(self.page.evaluate('[localStorage.length,sessionStorage.length]'),[0,0])
        self.page.get_by_role('link',name='Access & sign out').click()
        self.page.get_by_role('button',name='Sign out',exact=True).click()
        self.page.locator('#token').wait_for(state='visible')
        self.assertEqual(self.page.evaluate("async () => (await fetch('/api/openapi.json')).status"),401)
        self.context.add_cookies([session])
        self.assertEqual(self.page.evaluate("async () => (await fetch('/api/openapi.json')).status"),401)

    def test_bad_token_and_expired_session_return_to_supported_login_flow(self):
        self.page.goto(self.url)
        self.page.locator('#token').fill('wrong-synthetic-token')
        self.page.get_by_role('button',name='Sign in',exact=True).click()
        self.page.wait_for_function("document.querySelector('#status').textContent.startsWith('Sign-in failed')")
        self.assertEqual(self.page.locator('#token').input_value(),'')
        clock=[10.0];self.app.state.local_access.clock=lambda:clock[0]
        self.login();clock[0]=911.0
        self.assertEqual(self.page.evaluate("async () => (await fetch('/api/openapi.json')).status"),401)
        self.page.get_by_role('link',name='Access & sign out').click()
        self.page.locator('#token').wait_for(state='visible')
