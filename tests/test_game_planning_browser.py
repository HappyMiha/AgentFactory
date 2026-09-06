"""Real Chromium against the default local app; synthetic game brief, no AI."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch
from agent_factory.storage import SQLiteStorage
from agent_factory.mission_intake import AutonomousMissionIntakeService
from agent_factory.web import create_app
try:
    from playwright.sync_api import sync_playwright
except ImportError:sync_playwright=None

@unittest.skipIf(sync_playwright is None,'Install Playwright and Chromium')
class GamePlanningBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime=sync_playwright().start();cls.browser=cls.runtime.chromium.launch()
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.runtime.stop()
    def setUp(self):
        import uvicorn
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.path=self.root/'state.db'
        self.env=patch.dict(os.environ,{'AGENT_FACTORY_API_TOKEN':'','AGENT_FACTORY_API_ACTOR':'Founder','AGENT_FACTORY_API_ROLE':'operations_owner','AGENT_FACTORY_API_SCOPES':'read,write,approve,control','AGENT_FACTORY_API_TENANTS':'*','AGENT_FACTORY_TEMPORAL_ENABLED':'false'})
        self.env.start()
        storage=SQLiteStorage(self.path)
        result=AutonomousMissionIntakeService(storage).create_from_text(name='Garden',mission_owner='Founder',actor='Founder',specification='<script>window.sourceExecuted=true</script> Build a huge multiplayer garden. Keep the ambition.',command_id=str(uuid.uuid4()))
        self.ident=result.mission.id;storage.close()
        self.server=uvicorn.Server(uvicorn.Config(create_app(self.root,self.path),host='127.0.0.1',port=0,log_level='error',access_log=False));self.thread=threading.Thread(target=self.server.run,daemon=True);self.thread.start()
        deadline=time.monotonic()+10
        while not self.server.started and time.monotonic()<deadline:time.sleep(.01)
        if not self.server.started:raise RuntimeError('Planning server did not start')
        self.url=f'http://127.0.0.1:{self.server.servers[0].sockets[0].getsockname()[1]}/planning/{self.ident}'
        self.context=self.browser.new_context(locale='uk-UA');self.page=self.context.new_page();self.page.set_default_timeout(7000)
        self.errors=[];self.page.on('pageerror',lambda e:self.errors.append(str(e)))
    def tearDown(self):
        self.context.close();self.server.should_exit=True;self.thread.join(5);self.env.stop();self.temp.cleanup()
        self.assertFalse(self.thread.is_alive());self.assertEqual(self.errors,[])
    def open(self,page=None):
        page=page or self.page;page.goto(self.url);page.wait_for_function("!document.getElementById('fields').disabled")
    def save(self,page=None):
        page=page or self.page;page.locator('#confirmed').check();page.locator('#save').click();page.wait_for_function("document.getElementById('notice').textContent==='Збережена ручна версія плану.'")
    def test_explicit_draft_save_restart_history_source_and_mobile(self):
        self.page.set_viewport_size({'width':390,'height':844});self.open()
        self.assertIn('huge multiplayer',self.page.locator('#source').inner_text());self.assertIsNone(self.page.evaluate('window.sourceExecuted'))
        self.assertEqual(self.page.locator('#history li').count(),0)
        self.page.locator('#genre').select_option('platformer');self.page.locator('#use-template').click()
        self.page.locator('#goal').fill('Reach the blue platform.');self.page.locator('#save').click()
        self.assertIn('Підтвердьте',self.page.locator('#notice').inner_text());self.save()
        self.assertIn('Reach the blue platform.',self.page.locator('#tasks').inner_text())
        self.page.reload();self.page.wait_for_function("!document.getElementById('fields').disabled")
        self.assertEqual(self.page.locator('#goal').input_value(),'Reach the blue platform.')
        self.page.locator('#goal').fill('Reach the red platform.');self.save()
        self.page.get_by_role('button',name='Версія 1',exact=True).click()
        self.page.wait_for_function("document.getElementById('notice').textContent==='Перегляд попередньої незмінної версії.'")
        self.assertEqual(self.page.locator('#goal').input_value(),'Reach the blue platform.')
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),390)
        output=os.getenv('GAME_PLAN_SCREENSHOT_DIR')
        if output:
            Path(output).mkdir(parents=True,exist_ok=True);self.page.screenshot(path=str(Path(output)/'planning-mobile.png'),full_page=True)
    def test_stale_tab_retains_typed_text(self):
        self.open();other=self.context.new_page();self.open(other)
        self.page.locator('#goal').fill('First writer.');self.save()
        other.locator('#goal').fill('Second writer retained.');other.locator('#confirmed').check();other.locator('#save').click()
        other.wait_for_function("document.getElementById('notice').textContent.includes('змінилися')")
        self.assertEqual(other.locator('#goal').input_value(),'Second writer retained.')
        self.assertFalse(other.locator('#fields').is_disabled())

    def test_lost_response_replays_original_command_without_losing_new_edits(self):
        self.open()
        def lose_response(route):
            if route.request.method=='POST':
                route.fetch();route.abort()
            else:route.continue_()
        pattern='**/api/game-planning/*'
        self.page.route(pattern,lose_response)
        self.page.locator('#goal').fill('Persisted despite lost response.')
        self.page.locator('#confirmed').check();self.page.locator('#save').click()
        self.page.wait_for_function("document.getElementById('notice').textContent.includes('повторне')")
        self.page.unroute(pattern,lose_response)
        self.page.locator('#goal').fill('New edits while retrying.')
        self.page.locator('#save').click()
        self.page.wait_for_function("document.getElementById('notice').textContent.includes('відновлено')")
        self.assertEqual(self.page.locator('#goal').input_value(),'New edits while retrying.')
        self.assertEqual(self.page.locator('#history li').count(),1)
        self.save();self.assertEqual(self.page.locator('#history li').count(),2)
