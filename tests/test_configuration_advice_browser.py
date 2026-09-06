import json
from datetime import datetime,timezone
import unittest
import test_game_planning_browser as fixture
from test_configuration_advice import report

@unittest.skipIf(fixture.sync_playwright is None,'Install Playwright and Chromium')
class ConfigurationAdviceBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixture.GamePlanningBrowserTests.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):fixture.GamePlanningBrowserTests.tearDownClass.__func__(cls)
    setUp=fixture.GamePlanningBrowserTests.setUp
    tearDown=fixture.GamePlanningBrowserTests.tearDown
    open=fixture.GamePlanningBrowserTests.open
    save=fixture.GamePlanningBrowserTests.save
    def scan(self,callback=None):
        data=report();data['observed_at']=datetime.now(timezone.utc).isoformat()
        def respond(route):
            if callback:callback()
            route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
        self.page.route('**/api/hardware/scan',respond)
    def test_explicit_selection_preserves_source_and_requires_separate_save(self):
        self.scan();self.open();self.page.locator('#deferred_scope').fill('Keep the large multiplayer ambition')
        self.page.locator('#cost_notes').fill('My existing budget note')
        source=self.page.locator('#source').inner_text()
        self.page.locator('#compare-configuration').click();self.page.wait_for_selector('#advice-results article')
        self.assertEqual(self.page.locator('#history li').count(),0)
        card=self.page.locator('#advice-results article').filter(has_text='локальний qwen2.5-coder:7b')
        card.locator('button').click()
        self.assertEqual(self.page.locator('#source').inner_text(),source)
        self.assertEqual(self.page.locator('#deferred_scope').input_value(),'Keep the large multiplayer ambition')
        self.assertIn('My existing budget note',self.page.locator('#cost_notes').input_value())
        self.assertIn('qwen2.5-coder',self.page.locator('#cost_notes').input_value())
        self.assertFalse(self.page.locator('#confirmed').is_checked());self.assertEqual(self.page.locator('#history li').count(),0)
        self.save();self.assertEqual(self.page.locator('#history li').count(),1)
    def test_delayed_scan_does_not_overwrite_user_edit(self):
        self.scan(lambda:self.page.locator('#goal').fill('Edited while scanning'));self.open()
        self.page.locator('#compare-configuration').click()
        self.page.wait_for_function("document.getElementById('advice-status').textContent.includes('Поля або версія змінилися')")
        self.assertEqual(self.page.locator('#goal').input_value(),'Edited while scanning')
        self.assertEqual(self.page.locator('#advice-results article').count(),0)
    def test_selection_rechecks_current_form_and_long_notes(self):
        self.scan();self.open();self.page.locator('#cost_notes').fill('x'*1500)
        self.page.locator('#compare-configuration').click();self.page.wait_for_selector('#advice-results article')
        self.page.locator('#advice-results article').first.locator('button').click()
        self.assertEqual(self.page.locator('#cost_notes').input_value(),'x'*1500)
        self.page.locator('#goal').fill('New goal')
        self.page.locator('#advice-results article').nth(1).locator('button').click()
        self.assertEqual(self.page.locator('#goal').input_value(),'New goal');self.assertEqual(self.page.locator('#history li').count(),0)
    def test_scan_failure_can_retry_without_old_options(self):
        self.page.route('**/api/hardware/scan',lambda route:route.fulfill(status=503,body='{}'))
        self.open();self.page.locator('#compare-configuration').click()
        self.page.wait_for_function("document.getElementById('advice-status').textContent.includes('Не вдалося')")
        self.assertEqual(self.page.locator('#advice-results article').count(),0)
        self.page.unroute('**/api/hardware/scan');self.scan();self.page.locator('#compare-configuration').click()
        self.page.wait_for_selector('#advice-results article')

    def test_delayed_advice_response_is_discarded_after_edit(self):
        self.scan();self.open()
        def delayed(route):
            response=route.fetch()
            self.page.locator('#goal').fill('Changed after advice request')
            route.fulfill(response=response)
        self.page.route('**/api/configuration-advice',delayed)
        self.page.locator('#compare-configuration').click()
        self.page.wait_for_function("document.getElementById('advice-status').textContent.includes('Попередню відповідь відхилено')")
        self.assertEqual(self.page.locator('#goal').input_value(),'Changed after advice request')
        self.assertEqual(self.page.locator('#advice-results article').count(),0)
    def test_expired_selection_does_not_apply(self):
        self.scan();self.open();notes=self.page.locator('#cost_notes').input_value()
        self.page.locator('#compare-configuration').click();self.page.wait_for_selector('#advice-results article')
        self.page.evaluate('Date.now = () => new Date().getTime() + 960000')
        self.page.locator('#advice-results article').nth(1).locator('button').click()
        self.assertIn('застаріла',self.page.locator('#advice-status').inner_text())
        self.assertEqual(self.page.locator('#cost_notes').input_value(),notes)
        self.assertEqual(self.page.locator('#advice-results article').count(),0)
