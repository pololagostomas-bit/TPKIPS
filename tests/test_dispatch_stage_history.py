"""Real-browser stage consultation, temporary database and synthetic orders only."""
import contextlib
import importlib.util
import io
import os
import secrets
import threading
import unittest

from backend import app
from backend.services import dispatch_operations as ops
from tests import test_dispatch_sts as fixture_module

PHOTO=fixture_module.PHOTO


@unittest.skipUnless(importlib.util.find_spec('playwright'), 'Optional real-browser QA runtime required')
class DispatchStageHistoryTests(unittest.TestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright
        self.auth=os.environ.get('TRITON_AUTH_MODE')
        os.environ['TRITON_AUTH_MODE']='demo'
        self.fixture=fixture_module.DispatchSTSTests();self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.addCleanup(self.restore_auth)
        self.documents={}
        for kind in ('OV','STS'):
            code=self.fixture.request(key=kind)['sap_ov']
            if kind=='OV':
                with app.db() as db:db.execute("UPDATE dispatch_context SET kind='OV' WHERE sap_ov=?",(code,))
            previous=self.prepare(code,1)
            with app.db() as db:app.save_delivery_evidence(db,previous,PHOTO,'picker','PICKER_GUIADOR')
            app.change_attention_status(previous,'GUIADO FINALIZADO','picker','PICKER_GUIADOR')
            ops.ship(app,previous,{'guide_reference':'QA-GUIDE'},'picker','PICKER_GUIADOR')
            active=self.prepare(code,2)
            self.documents[kind]=(code,previous,active)
        self.password=secrets.token_urlsafe(24)
        with app.db() as db:db.execute("UPDATE users SET password_hash=? WHERE username IN ('demo.admin','picker')",(app.identity.password_hash(self.password),))
        os.environ['TRITON_AUTH_MODE']='local'
        self.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop_server)
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.driver=sync_playwright().start();self.addCleanup(self.driver.stop)
        try:self.browser=self.driver.chromium.launch(headless=True,channel='msedge' if os.name=='nt' else None)
        except Exception as error:
            if "Executable doesn't exist" in str(error):self.skipTest('Install the optional QA browser to run this test')
            raise
        self.addCleanup(self.browser.close)

    def restore_auth(self):
        if self.auth is None:os.environ.pop('TRITON_AUTH_MODE',None)
        else:os.environ['TRITON_AUTH_MODE']=self.auth

    def stop_server(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)

    def prepare(self,code,quantity):
        aid=app.create_attention(code,'admin','ADMINISTRADOR')['id']
        app.assign_attention_responsibles(aid,'picker','picker','admin','ADMINISTRADOR')
        app.change_attention_status(aid,'EN PICKING','picker','PICKER_GUIADOR')
        with app.db() as db:line=app.attention_payload(db,aid)['lines'][0]['id']
        ops.confirm_line(app,aid,line,quantity,'QA preparación parcial','picker','PICKER_GUIADOR')
        ops.finish_picking(app,aid,'picker','PICKER_GUIADOR')
        app.change_attention_status(aid,'EN GUIADO','picker','PICKER_GUIADOR')
        return aid

    def snapshot(self):
        with app.db() as db:
            return {name:[tuple(row) for row in db.execute('SELECT * FROM '+name+' ORDER BY rowid')]
                for name in ('orders','order_lines','attentions','attention_lines','history','attention_history',
                    'stock_allocations','stock_movements','dispatch_reads','dispatch_shipments','delivery_evidence')}

    def page(self,kind,user,width=1366,height=900):
        from playwright.sync_api import expect
        context=self.browser.new_context(viewport={'width':width,'height':height},service_workers='block',extra_http_headers={'X-WMS-Request':'1'})
        self.addCleanup(context.close)
        self.assertEqual(context.request.post(self.base+'/api/login',data={'username':user,'password':self.password}).status,200)
        page=context.new_page();errors=[];posts=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(self.base+'/?kind='+kind);page.wait_for_load_state('networkidle')
        page.evaluate('(code)=>loadDetail(code)',self.documents[kind][0]);page.wait_for_load_state('networkidle')
        expect(page.locator('#dispatchStagePicker')).to_be_visible(timeout=4000)
        return page,errors,posts

    def test_consulting_current_and_previous_attentions_never_changes_work(self):
        from playwright.sync_api import expect
        with contextlib.redirect_stderr(io.StringIO()):
            for kind in ('OV','STS'):
                for user in ('demo.admin','picker'):
                    with self.subTest(kind=kind,user=user):
                        before=self.snapshot();page,errors,posts=self.page(kind,user)
                        code,previous,active=self.documents[kind]
                        page.locator('#dispatchStagePicker summary').click()
                        expect(page.locator('[data-dispatch-stage="6"]')).to_be_disabled()
                        page.locator('[data-dispatch-stage="2"]').click()
                        expect(page.locator('#dispatchStagePreview')).to_contain_text('Consulta: Picking')
                        expect(page.locator('#dispatchStagePreview')).to_contain_text('NP-01')
                        self.assertEqual(page.locator('#dispatchStagePreview input').count(),0)
                        if page.locator('.stage-advance').count():expect(page.locator('.stage-advance')).to_be_hidden()
                        page.evaluate("advanceActive('GUIADO FINALIZADO')")
                        page.locator('[data-dispatch-return]').click()
                        expect(page.locator('#dispatchStagePreview')).to_have_count(0)
                        page.locator('#dispatchAttentionView').select_option(str(previous))
                        expect(page.locator('#dispatchStagePreview a')).to_have_attribute('href',f'/api/attentions/{previous}/delivery-evidence')
                        page.locator('#dispatchStagePicker summary').click();page.locator('[data-dispatch-stage="2"]').click()
                        expect(page.locator('#dispatchStagePreview')).to_contain_text('1')
                        page.locator('#dispatchAttentionView').select_option(str(active))
                        expect(page.locator('#dispatchStagePreview')).to_have_count(0)
                        self.assertEqual(errors,[]);self.assertEqual(posts,[]);self.assertEqual(before,self.snapshot())
                        page.context.close()

    def test_picking_consultation_blocks_camera_and_future_steps_without_records(self):
        from playwright.sync_api import expect
        with contextlib.redirect_stderr(io.StringIO()):
            code=self.fixture.request(key='camera')['sap_ov']
            aid=app.create_attention(code,'admin','ADMINISTRADOR')['id']
            app.assign_attention_responsibles(aid,'picker','picker','admin','ADMINISTRADOR')
            app.change_attention_status(aid,'EN PICKING','picker','PICKER_GUIADOR')
            self.documents['STS']=(code,aid,aid)
            before=self.snapshot();page,errors,posts=self.page('STS','picker')
            expect(page.locator('#dispatchNPScan')).to_be_visible()
            page.locator('#dispatchStagePicker summary').click()
            expect(page.locator('[data-dispatch-stage="4"]')).to_be_disabled()
            page.locator('[data-dispatch-stage="1"]').click()
            expect(page.locator('#dispatchNPScan')).to_be_hidden()
            page.evaluate('WmsCamera.open()')
            expect(page.locator('#dispatchStagePreview')).to_contain_text('Consulta: Asignación')
            page.locator('[data-dispatch-return]').click()
            expect(page.locator('#dispatchNPScan')).to_be_visible()
            self.assertEqual(page.locator('#dispatchNPScan').get_attribute('inputmode'),'none')
            self.assertEqual(errors,[]);self.assertEqual(posts,[]);self.assertEqual(before,self.snapshot())

    def test_closed_partial_keeps_admin_access_to_create_next_attention(self):
        from playwright.sync_api import expect
        with contextlib.redirect_stderr(io.StringIO()):
            code=self.fixture.request(key='closed-partial')['sap_ov']
            aid=self.prepare(code,1)
            with app.db() as db:app.save_delivery_evidence(db,aid,PHOTO,'picker','PICKER_GUIADOR')
            app.change_attention_status(aid,'GUIADO FINALIZADO','picker','PICKER_GUIADOR')
            ops.ship(app,aid,{'guide_reference':'QA-CLOSED-PARTIAL'},'picker','PICKER_GUIADOR')
            self.documents['STS']=(code,aid,aid)
            before=self.snapshot();page,errors,posts=self.page('STS','demo.admin')
            expect(page.locator('#dispatchStagePreview')).to_contain_text('Consulta: Despachado')
            page.locator('[data-dispatch-return]').click()
            expect(page.locator('#dispatchStagePreview')).to_have_count(0)
            expect(page.locator('button[onclick="createAttention()"]')).to_be_visible()
            expect(page.locator('button[onclick="createAttention()"]')).to_be_enabled()
            self.assertEqual(errors,[]);self.assertEqual(posts,[]);self.assertEqual(before,self.snapshot())

    def test_stage_picker_is_usable_on_phone_and_desktop(self):
        from playwright.sync_api import expect
        with contextlib.redirect_stderr(io.StringIO()):
            for width,height in ((1366,900),(393,873),(320,640),(873,393)):
                for kind in ('OV','STS'):
                    with self.subTest(viewport=(width,height),kind=kind):
                        page,errors,posts=self.page(kind,'picker',width,height)
                        page.locator('#dispatchStagePicker summary').click();page.locator('[data-dispatch-stage="2"]').click()
                        expect(page.locator('#dispatchStagePreview')).to_be_visible()
                        self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'))
                        page.locator('[data-dispatch-return]').click()
                        self.assertEqual(errors,[]);self.assertEqual(posts,[])
                        page.context.close()


if __name__=='__main__':unittest.main()
