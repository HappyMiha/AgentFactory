"""Actual Chromium with synthetic age examples; no real children or provider calls."""
from pathlib import Path
import unittest
from tests import test_credential_browser as credentials
from tests.test_connector_eligibility import approval_fixture


@unittest.skipIf(credentials.sync_playwright is None, 'Install Playwright and Chromium')
class EligibilityBrowserTests(unittest.TestCase):
    setUpClass = classmethod(credentials.CredentialBrowserTests.setUpClass.__func__)
    tearDownClass = classmethod(credentials.CredentialBrowserTests.tearDownClass.__func__)
    tearDown = credentials.CredentialBrowserTests.tearDown

    def setUp(self):
        credentials.CredentialBrowserTests.setUp(self)
        self.app.state.connector_setup_approval=None
        self.page.set_viewport_size({'width':390,'height':844})

    def test_age_examples_no_submission_and_actual_offline_demo_and_idea_download(self):
        requests=[];self.page.on('request',lambda request:requests.append((request.method,request.url)))
        self.page.goto(self.url+'/access-guide')
        self.page.wait_for_function("document.querySelector('#connectors').children.length === 10")
        loaded=list(requests)
        for band, text in (('12','У 12 років'),('13-15','У 13–15 років'),('16-17','У 16–17 років'),('adult','Для дорослого')):
            self.page.locator('#age-band').select_option(band)
            self.assertIn(text,self.page.locator('#age-path').inner_text())
        self.assertEqual(requests,loaded)
        self.assertFalse(any(method!='GET' or not url.startswith(self.url) for method,url in requests))
        self.assertFalse((self.root/'.agent-factory').exists())
        self.assertFalse((self.root/'core.db').exists())
        self.assertEqual(self.page.evaluate('JSON.stringify([Object.keys(localStorage),Object.keys(sessionStorage)])'),'[[],[]]')
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'))
        self.context.set_offline(True)
        for _ in range(3):self.page.locator('#collect-star').click()
        self.assertIn('Усі три зірки',self.page.locator('#demo-state').inner_text())
        self.assertTrue(self.page.locator('#collect-star').is_disabled())
        self.page.locator('#reset-demo').click()
        self.assertIn('0 / 3',self.page.locator('#demo-state').inner_text())
        idea='Синтетична ідея <img src=x onerror=alert(1)>: три зірки'
        self.page.locator('#idea').fill(idea)
        with self.page.expect_download() as download:self.page.locator('#download-idea').click()
        self.assertEqual(download.value.suggested_filename,'game-idea.txt')
        self.assertEqual(Path(download.value.path()).read_text(encoding='utf-8'),idea)
        self.assertEqual(requests,loaded)

    def test_default_hidden_key_form_and_http_self_assertion_cannot_unlock(self):
        self.page.goto(self.url+'/settings/credentials')
        self.page.wait_for_function("document.querySelector('#eligibility-notice').textContent.includes('закрите')")
        self.assertTrue(self.page.locator('#connect').is_hidden())
        self.assertTrue(self.page.locator('#secret').is_disabled())
        result=self.context.request.post(self.url+'/api/credential-connections',headers={'X-Agent-Factory-Confirm':'true'},
            data={'provider':'openai','secret':self.secret,'confirmed':True,'age_band':'adult','guardian_consent':True})
        self.assertEqual(result.status,403)
        self.assertFalse(self.store.values)
        self.page.get_by_role('link',name='Що доступно у моєму віці? Зберегти задум і спробувати офлайн-демо').click()
        self.page.locator('#age-band').select_option('adult')
        self.page.get_by_role('link',name='Доступ до AI',exact=True).click()
        self.assertTrue(self.page.locator('#connect').is_hidden())

    def test_revoked_setup_hides_key_entry_but_allows_disconnect(self):
        self.app.state.connector_setup_approval=lambda **scope: approval_fixture(**scope)
        self.page.goto(self.url+'/settings/credentials')
        self.page.locator('#secret').fill(self.secret);self.page.locator('#confirmed').check();self.page.locator('#save').click()
        self.page.wait_for_function("document.querySelector('#connections').textContent.includes('Збережено')")
        self.app.state.connector_setup_approval=None
        self.page.locator('#refresh').click()
        self.page.wait_for_function("document.querySelector('#connect').hidden")
        self.assertEqual(self.page.locator('#secret').input_value(),'')
        self.page.get_by_role('button',name='Відключити',exact=True).click()
        self.page.locator('#disconnect-dialog').get_by_role('button',name='Відключити',exact=True).click()
        self.page.wait_for_function("document.querySelector('#connections').textContent.includes('Відключено')")
        self.assertFalse(self.store.values)
        self.assertTrue(self.page.locator('#connect').is_hidden())

    def test_catalog_failure_preserves_manual_fallback(self):
        self.page.route('**/api/connector-eligibility',lambda route:route.abort())
        self.page.goto(self.url+'/access-guide')
        self.page.wait_for_function("document.querySelector('#catalog-notice').textContent.includes('Не вдалося')")
        self.page.locator('#collect-star').click()
        self.assertIn('1 / 3',self.page.locator('#demo-state').inner_text())
        self.assertTrue(self.page.locator('#download-idea').is_enabled())

    def test_open_form_closes_when_approval_expires(self):
        from datetime import timedelta
        from tests.test_connector_eligibility import AT
        self.app.state.connector_setup_approval=lambda **scope: approval_fixture(**scope,expires_at=AT+timedelta(seconds=3))
        self.page.goto(self.url+'/settings/credentials')
        self.page.locator('#secret').fill(self.secret)
        self.page.clock.fast_forward(4000)
        self.assertTrue(self.page.locator('#connect').is_hidden())
        self.assertEqual(self.page.locator('#secret').input_value(),'')

    def _delayed_allowed_refresh(self):
        held=[]
        def hold_once(route):
            if route.request.method=='GET' and not held:
                response=route.fetch()
                self.assertTrue(response.json()['setup']['openai']['allowed'])
                held.append((route,response))
                self.page.evaluate('window.reviewHeldResponse = true')
            else:
                route.continue_()
        self.page.route('**/api/credential-connections',hold_once)
        # Retain the real refresh promise so assertions run after the late response
        # is fully processed, not merely after its network request completes.
        self.page.evaluate('() => { window.pendingReviewRefresh = refresh(); }')
        self.page.wait_for_function('window.reviewHeldResponse === true')
        return held[0]

    def test_late_allowed_refresh_cannot_override_newer_revocation_response(self):
        self.app.state.connector_setup_approval=lambda **scope: approval_fixture(**scope)
        self.page.goto(self.url+'/settings/credentials')
        self.page.locator('#secret').fill(self.secret)
        route,response=self._delayed_allowed_refresh()
        self.app.state.connector_setup_approval=None
        self.page.locator('#refresh').click()
        self.page.wait_for_function("document.querySelector('#connect').hidden")
        route.fulfill(response=response)
        self.page.evaluate('async () => await window.pendingReviewRefresh')
        self.assertTrue(self.page.locator('#connect').is_hidden())
        self.assertEqual(self.page.locator('#secret').input_value(),'')
        self.assertIn('закрите',self.page.locator('#eligibility-notice').inner_text())

    def test_post_denial_invalidates_pending_allowed_refresh(self):
        self.app.state.connector_setup_approval=lambda **scope: approval_fixture(**scope)
        self.page.goto(self.url+'/settings/credentials')
        self.page.locator('#secret').fill(self.secret)
        route,response=self._delayed_allowed_refresh()
        self.app.state.connector_setup_approval=None
        self.page.locator('#confirmed').check();self.page.locator('#save').click()
        self.page.wait_for_function("document.querySelector('#connect').hidden")
        self.assertFalse(self.store.values)
        route.fulfill(response=response)
        self.page.evaluate('async () => await window.pendingReviewRefresh')
        self.assertTrue(self.page.locator('#connect').is_hidden())
        self.assertEqual(self.page.locator('#secret').input_value(),'')
        self.assertIn('закрите',self.page.locator('#eligibility-notice').inner_text())
