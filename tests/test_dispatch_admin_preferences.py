"""Admin corrections and remembered picker; synthetic work only."""
import contextlib
import importlib.util
import io
import os
import unittest

from backend import app
from backend.services import dispatch_operations as ops
from tests import test_dispatch_sts as fixtures


class DispatchAdminBackendTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.DispatchSTSTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)

    def closed_ov(self):
        code,aid=self.fixture.guided(quantity=1)
        with app.db() as db:
            db.execute("UPDATE dispatch_context SET kind='OV' WHERE sap_ov=?",(code,))
            app.save_delivery_evidence(db,aid,fixtures.PHOTO,'picker','PICKER_GUIADOR')
        ops.ship(app,aid,{'guide_reference':'QA-OV-GUIDE'},'picker','PICKER_GUIADOR')
        return code,aid

    def test_reopening_closed_attention_cannot_create_two_active_tasks(self):
        code,aid=self.closed_ov()
        with app.db() as db:db.execute('UPDATE order_lines SET pending_qty=3,required_qty=3 WHERE sap_ov=?',(code,))
        second=app.create_attention(code,'admin','ADMINISTRADOR')['id']
        for method in (app.admin_rollback_attention,app.admin_reset_attention):
            with self.subTest(method=method.__name__),self.assertRaisesRegex(ValueError,'otra atención'):
                method(aid,'admin','ADMINISTRADOR','QA no duplicar atención')
        with app.db() as db:
            self.assertEqual(db.execute('SELECT app_status FROM attentions WHERE id=?',(aid,)).fetchone()[0],'ENTREGADO')
            self.assertEqual(db.execute("SELECT id FROM attentions WHERE sap_ov=? AND app_status NOT IN ('ENTREGADO','CERRADO SAP')",(code,)).fetchone()[0],second)

    def test_picker_preference_is_private_validated_and_keeps_guidance(self):
        auth=os.environ.get('TRITON_AUTH_MODE');os.environ['TRITON_AUTH_MODE']='local'
        try:
            app.save_account_preferences('demo.admin','ADMINISTRADOR',{'show_guidance':True})
            result=app.save_account_preferences('demo.admin','ADMINISTRADOR',{'default_picker':'picker'})
            self.assertTrue(result['show_guidance']);self.assertEqual(result['default_picker'],'picker')
            result=app.save_account_preferences('demo.admin','ADMINISTRADOR',{'show_guidance':False})
            self.assertEqual(result['default_picker'],'picker');self.assertFalse(result['show_guidance'])
            with self.assertRaises(PermissionError):app.save_account_preferences('picker','PICKER_GUIADOR',{'default_picker':'picker'})
            for payload in ({'default_picker':'MISSING'},{'default_picker':False},{'show_guidance':1},{}):
                with self.subTest(payload=payload),self.assertRaises(ValueError):app.save_account_preferences('demo.admin','ADMINISTRADOR',payload)
            with app.db() as db:db.execute("UPDATE users SET active=0 WHERE username='picker'")
            with self.assertRaises(ValueError):app.save_account_preferences('demo.admin','ADMINISTRADOR',{'default_picker':'picker'})
            app.init_db()
            with app.db() as db:self.assertEqual(db.execute("SELECT default_picker FROM user_preferences WHERE username='demo.admin'").fetchone()[0],'picker')
        finally:
            if auth is None:os.environ.pop('TRITON_AUTH_MODE',None)
            else:os.environ['TRITON_AUTH_MODE']=auth

    def test_migration_preserves_existing_guidance(self):
        with app.db() as db:
            db.execute('DROP TABLE user_preferences')
            db.execute('CREATE TABLE user_preferences(username TEXT PRIMARY KEY,show_guidance INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL)')
            db.execute('INSERT INTO user_preferences VALUES(?,?,?)',('demo.admin',1,app.now()))
        app.init_db()
        result=app.save_account_preferences('demo.admin','ADMINISTRADOR',{'default_picker':''})
        self.assertTrue(result['show_guidance']);self.assertEqual(result['default_picker'],'')


@unittest.skipUnless(importlib.util.find_spec('playwright'),'Optional real-browser QA runtime required')
class DispatchAdminBrowserTests(unittest.TestCase):
    def setUp(self):
        from tests import test_dispatch_stage_history as ui
        self.ui=ui.DispatchStageHistoryTests();self.addCleanup(self.ui.doCleanups);self.ui.setUp()

    def close_current_ov(self):
        code,previous,aid=self.ui.documents['OV']
        with app.db() as db:app.save_delivery_evidence(db,aid,fixtures.PHOTO,'picker','PICKER_GUIADOR')
        app.change_attention_status(aid,'GUIADO FINALIZADO','picker','PICKER_GUIADOR')
        ops.ship(app,aid,{'guide_reference':'QA-CLOSED'},'picker','PICKER_GUIADOR')
        return code,aid

    def test_closed_ov_admin_controls_and_step_activity_are_visible(self):
        from playwright.sync_api import expect
        with contextlib.redirect_stderr(io.StringIO()):
            code,aid=self.close_current_ov();page,errors,posts=self.ui.page('OV','demo.admin')
            panel=page.locator('#dispatchAdministration');expect(panel).to_be_visible()
            expect(panel.locator('[data-admin-rollback]')).to_be_enabled()
            page.locator('#dispatchStagePicker summary').click();page.locator('[data-dispatch-stage="2"]').click()
            expect(panel).to_be_visible();expect(page.locator('#dispatchStageActivity')).to_contain_text('NP verificado')
            self.assertEqual(posts,[])
            def confirm(dialog):dialog.accept('QA corregir estado' if dialog.type=='prompt' else None)
            page.on('dialog',confirm)
            with page.expect_response(lambda r:r.url.endswith('/rollback')) as response:panel.locator('[data-admin-rollback]').click()
            self.assertEqual(response.value.status,200)
            with app.db() as db:
                self.assertEqual(db.execute('SELECT app_status FROM attentions WHERE id=?',(aid,)).fetchone()[0],'GUIADO FINALIZADO')
                event=db.execute("SELECT reason FROM attention_history WHERE attention_id=? AND event_type='RETROCESO_ADMIN' ORDER BY id DESC",(aid,)).fetchone()
                self.assertEqual(event[0],'QA corregir estado')
            self.assertEqual(errors,[])

    def test_worker_has_no_admin_controls_and_shipped_sts_remains_locked(self):
        from playwright.sync_api import expect
        with contextlib.redirect_stderr(io.StringIO()):
            page,errors,posts=self.ui.page('STS','picker')
            expect(page.locator('#dispatchAdministration')).to_have_count(0)
            page.context.close()
            page,errors,posts=self.ui.page('STS','demo.admin')
            page.locator('#dispatchAttentionView').select_option(str(self.ui.documents['STS'][1]))
            panel=page.locator('#dispatchAdministration');expect(panel).to_be_visible()
            expect(panel.locator('[data-admin-rollback]')).to_be_disabled()
            expect(panel).to_contain_text('salió del almacén')
            self.assertEqual(posts,[]);self.assertEqual(errors,[])

    def test_picker_choice_survives_other_document_and_new_browser_session(self):
        from playwright.sync_api import expect
        with contextlib.redirect_stderr(io.StringIO()):
            with app.db() as db:
                stamp=app.now();db.execute("INSERT INTO users(username,display_name,role,active,created_at,updated_at) VALUES('qa.second','Segundo picker','PICKER',1,?,?)",(stamp,stamp))
            requests={kind:self.ui.fixture.request(key='pending-'+kind)['sap_ov'] for kind in ('OV','STS')}
            with app.db() as db:db.execute("UPDATE dispatch_context SET kind='OV' WHERE sap_ov=?",(requests['OV'],))
            page,errors,posts=self.ui.page('OV','demo.admin')
            with page.expect_response(lambda r:r.url.endswith('/api/account/preferences')):page.locator('#pickerAssignee').select_option('qa.second')
            page.once('dialog',lambda d:d.accept())
            page.evaluate('(code)=>loadDetail(code)',requests['STS'])
            expect(page.locator('#pickerAssignee')).to_have_value('qa.second')
            self.assertIsNone(app.order_payload(requests['STS'])['current_picker'])
            page.context.close()
            page,errors,posts=self.ui.page('OV','demo.admin')
            page.once('dialog',lambda d:d.accept())
            page.evaluate('(code)=>loadDetail(code)',requests['OV'])
            expect(page.locator('#pickerAssignee')).to_have_value('qa.second')
            page.locator('#showReceptionAssignees').check()
            expect(page.locator('#pickerAssignee')).to_have_value('qa.second')
            with app.db() as db:self.assertEqual(db.execute("SELECT default_picker FROM user_preferences WHERE username='demo.admin'").fetchone()[0],'qa.second')
            self.assertEqual(errors,[])

    def test_admin_corrections_fit_mobile_and_desktop(self):
        from playwright.sync_api import expect
        with contextlib.redirect_stderr(io.StringIO()):
            for width,height in ((1366,900),(393,873),(320,640),(873,393)):
                with self.subTest(viewport=(width,height)):
                    page,errors,posts=self.ui.page('OV','demo.admin',width,height)
                    page.locator('#dispatchStagePicker summary').click();page.locator('[data-dispatch-stage="2"]').click()
                    expect(page.locator('#dispatchAdministration [data-admin-rollback]')).to_be_visible()
                    expect(page.locator('#dispatchStageActivity')).to_contain_text('NP verificado')
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'))
                    self.assertEqual(posts,[]);self.assertEqual(errors,[])
                    page.context.close()


if __name__=='__main__':unittest.main()
