"""Operational queues: synthetic dates, real sessions and zero navigation writes."""
import contextlib,importlib.util,io,unittest
from datetime import datetime
from unittest.mock import patch

from tests import test_internal_dispatch_queue as queue_fixtures


@unittest.skipUnless(importlib.util.find_spec('playwright'),'Optional real-browser QA runtime required')
class InternalQueueBrowserTests(unittest.TestCase):
    def setUp(self):
        from tests.test_dispatch_stage_history import DispatchStageHistoryTests
        self.ui=DispatchStageHistoryTests();self.addCleanup(self.ui.doCleanups);self.ui.setUp()
        self.clock=patch('backend.services.dispatch_queue._now',return_value=datetime(2026,11,17,8))
        self.clock.start();self.addCleanup(self.clock.stop)

    def add(self,*args,**kw):queue_fixtures.InternalDispatchQueueTests.add(self,*args,**kw)

    def test_internal_cut_backlog_regular_lookup_and_pagination(self):
        from playwright.sync_api import expect
        with contextlib.redirect_stderr(io.StringIO()):
            for i in range(23):self.add(f'CURRENT-{i:02}','2026-11-16 15:00:00')
            self.add('OLD','2026-11-12 13:00:00');self.add('REGULAR','2026-11-16 14:00:00','Cliente QA')
            page,errors,posts=self.ui.page('OV','demo.admin',393,873)
            page.once('dialog',lambda d:d.accept())
            page.locator('[data-nav="operation"]').click()
            page.evaluate('loadOrders()')
            expect(page.locator('#internalDispatchQueue')).to_contain_text('23')
            expect(page.locator('#internalDispatchQueue')).to_contain_text('17/11/2026 08:00')
            self.assertEqual(page.locator('[data-open-queue-order]').count(),6)
            page.locator('[data-queue-next]').click()
            expect(page.locator('[data-open-queue-order]').first).to_contain_text('CURRENT-06')
            page.locator('[data-cutoff-scope="carryover"]').click()
            expect(page.locator('[data-open-queue-order]')).to_contain_text('OLD')
            expect(page.locator('#internalDispatchQueue')).to_contain_text('cortes anteriores')
            page.locator('#customerTypeFilter').select_option('regular')
            expect(page.locator('#internalDispatchQueue')).to_contain_text('Busca la OV')
            page.locator('#search').fill('REGULAR')
            expect(page.locator('[data-open-queue-order]')).to_contain_text('REGULAR')
            self.assertEqual(posts,[]);self.assertEqual(errors,[])
            self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'))

    def test_sts_does_not_inherit_internal_client_filter(self):
        from playwright.sync_api import expect
        with contextlib.redirect_stderr(io.StringIO()):
            page,errors,posts=self.ui.page('OV','picker')
            page.once('dialog',lambda d:d.accept())
            page.locator('[data-nav="operation"]').click()
            page.locator('#dispatchDocumentTabs [data-kind="STS"]').click()
            expect(page.locator('#internalDispatchQueue')).to_have_count(0)
            expect(page.locator('.list .row').first).to_be_visible()
            self.assertEqual(posts,[]);self.assertEqual(errors,[])

    def test_cookie_identity_limits_the_queue_despite_spoofed_headers(self):
        from backend import app
        with contextlib.redirect_stderr(io.StringIO()):
            for code,user in [('MINE','picker'),('OTHER','other')]:
                self.add(code,'2026-11-16 12:00:00')
                aid=app.create_attention(code,'demo.admin','ADMINISTRADOR')['id']
                with app.db() as db:db.execute("UPDATE attentions SET app_status='ASIGNADO',current_picker=? WHERE id=?",(user,aid))
            page,errors,posts=self.ui.page('OV','picker')
            response=page.request.get(self.ui.base+'/api/dispatch/queue',headers={'X-Role':'ADMINISTRADOR','X-User':'demo.admin'})
            self.assertEqual(response.status,200)
            self.assertEqual([r['sap_ov'] for r in response.json()['items']],['MINE'])
            for suffix in ('?page=-1','?scope=invalid','?customer_type=invalid'):
                self.assertEqual(page.request.get(self.ui.base+'/api/dispatch/queue'+suffix).status,400)
            self.assertEqual(posts,[]);self.assertEqual(errors,[])


if __name__=='__main__':unittest.main()
