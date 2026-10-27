"""Explicit late-order inclusion; synthetic source and disposable SQLite only."""
import unittest
from unittest.mock import patch
from backend import app
from backend.services import reception
from tests import test_reception_count_snapshot as fixtures


class CountPlanTests(unittest.TestCase):
    setUp = fixtures.CountSnapshotTests.setUp
    workbook = fixtures.CountSnapshotTests.workbook
    load = fixtures.CountSnapshotTests.load
    start = fixtures.CountSnapshotTests.start
    detail = fixtures.CountSnapshotTests.detail

    def case(self, stage='REVISION SISTEMA'):
        old = [('QA-BL', 'NP-A', 'IP-A', 'OV-A', '12345', 2)]
        self.load(self.workbook(old))
        self.sid, self.aid = self.start(verified=2)
        self.load(self.workbook(old + [('QA-BL', 'NP-B', 'IP-B', 'OV-B', '54321', 4)]))
        with app.db() as db:
            db.execute('UPDATE reception_attentions SET app_status=? WHERE id=?',(stage,self.aid))
            db.execute('UPDATE reception_shipments SET app_status=? WHERE id=?',(stage,self.sid))
            self.lid = db.execute("SELECT id FROM reception_lines WHERE np_code='NP-B'").fetchone()[0]
        return self.detail(self.sid,self.aid)

    def apply(self, **overrides):
        from backend.services.reception_count_plan import include_lines
        preview = self.detail(self.sid,self.aid)['count_plan']
        body = dict(attention_id=self.aid,line_ids=[self.lid],confirmed=True,
                    state_token=preview['state_token'],reason='This order belongs to this physical arrival')
        body.update(overrides)
        with app.db() as db:
            return include_lines(db,self.sid,body,'qa.admin','ADMINISTRADOR')

    def test_source_only_np_is_visible_without_changing_automatic_frozen_plan(self):
        data=self.case()
        self.assertEqual(data['np_progress'],{'read':1,'total':2})
        self.assertEqual([line['np_code'] for line in data['count_plan']['lines']],['NP-B'])
        self.assertFalse(next(l for l in data['lines'] if l['id']==self.lid)['in_selected_attention'])
        with app.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reception_attention_lines WHERE attention_id=?',(self.aid,)).fetchone()[0],1)
        worker=self.detail(self.sid,self.aid,'ASISTENTE_RECEPCION')
        self.assertEqual(worker['count_plan']['lines'][0]['np_code'],'NP-B')
        self.assertFalse(worker['count_plan']['can_include'])
        self.assertNotIn('state_token',worker['count_plan'])

    def test_admin_adds_only_selected_source_plan_without_fabricating_reception(self):
        self.case()
        with app.db() as db:
            before=tuple(db.execute('SELECT * FROM reception_attention_lines WHERE attention_id=?',(self.aid,)).fetchone())
            receipts=[tuple(r) for r in db.execute('SELECT * FROM reception_receipts')]
        result=self.apply()
        line=next(l for l in result['lines'] if l['id']==self.lid)
        self.assertTrue(line['in_selected_attention'])
        self.assertEqual((line['attention_planned_qty'],line['attention_verified_qty']),(4,0))
        self.assertFalse(line['np_scanned_at'])
        self.assertEqual(result['count_plan']['lines'],[])
        self.assertEqual(result['np_progress'],{'read':1,'total':2})
        with app.db() as db:
            self.assertEqual(tuple(db.execute('SELECT * FROM reception_attention_lines WHERE id=?',(before[0],)).fetchone()),before)
            self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM reception_receipts')],receipts)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reception_history WHERE event_type='PLAN CONTEO'").fetchone()[0],1)

    def test_reopening_location_for_inclusion_keeps_old_reads_and_count(self):
        self.case('UBICACION')
        result=self.apply()
        self.assertEqual(result['app_status'],'REVISION SISTEMA')
        old=next(l for l in result['lines'] if l['np_code']=='NP-A')
        self.assertEqual(old['attention_verified_qty'],2)
        self.assertTrue(old['np_scanned_at'])
        self.assertEqual(old['final_location'],'BIN-QA')

    def test_worker_and_cross_shipment_ids_and_missing_confirmation_are_rejected(self):
        self.case()
        from backend.services.reception_count_plan import include_lines
        with app.db() as db, self.assertRaises(PermissionError):
            include_lines(db,self.sid,{},'qa.worker','ASISTENTE_RECEPCION')
        for change in ({'confirmed':False},{'line_ids':[999999]},{'attention_id':True},
                       {'line_ids':[True]},{'reason':'x'},{'state_token':'obsolete'}):
            with self.subTest(change=change),self.assertRaises((ValueError,PermissionError)):
                self.apply(**change)
        with app.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reception_attention_lines WHERE attention_id=?',(self.aid,)).fetchone()[0],1)

    def test_stale_source_or_count_and_replay_cannot_add_or_duplicate(self):
        self.case()
        token=self.detail(self.sid,self.aid)['count_plan']['state_token']
        with app.db() as db:
            db.execute('UPDATE reception_lines SET expected_qty=7 WHERE id=?',(self.lid,))
        with self.assertRaises(ValueError):self.apply(state_token=token)
        self.apply()
        with self.assertRaises(ValueError):self.apply(state_token=token)
        with app.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reception_attention_lines WHERE reception_line_id=?',(self.lid,)).fetchone()[0],1)

    def test_legacy_saved_zero_or_location_is_not_treated_as_an_unworked_new_order(self):
        self.case()
        with app.db() as db:
            db.execute('UPDATE reception_lines SET count_location_saved=1,final_location=? WHERE id=?',('QA-SAVED',self.lid))
        self.assertEqual(self.detail(self.sid,self.aid)['count_plan']['lines'],[])

    def test_parent_closed_and_annulled_or_transfer_checked_attention_cannot_expand(self):
        self.case()
        with app.db() as db:
            db.execute("UPDATE reception_shipments SET app_status='CERRADO' WHERE id=?",(self.sid,))
        self.assertFalse(self.detail(self.sid,self.aid)['count_plan']['can_include'])
        with self.assertRaises(PermissionError):self.apply()
        with app.db() as db:
            db.execute("UPDATE reception_shipments SET app_status='REVISION SISTEMA' WHERE id=?",(self.sid,))
            db.execute('UPDATE reception_attentions SET transfer_assistant_checked=1 WHERE id=?',(self.aid,))
        with self.assertRaises(PermissionError):self.apply()


    def test_other_arrival_assignment_and_late_stages_are_not_silently_reassigned(self):
        self.case()
        for stage in ('VALIDACION','SOLICITUD TRANSFERENCIA','CERRADO'):
            with app.db() as db:
                db.execute('UPDATE reception_attentions SET app_status=? WHERE id=?',(stage,self.aid))
            with self.subTest(stage=stage),self.assertRaises(PermissionError):self.apply()
        with app.db() as db:
            shipment=db.execute('SELECT * FROM reception_shipments WHERE id=?',(self.sid,)).fetchone()
            reception._create_reception_attention(db,shipment,None,'qa.admin','ARRIBADO')
        self.assertEqual(self.detail(self.sid,self.aid)['count_plan']['lines'],[])

    def test_partial_failure_rolls_back_added_line_and_rewind(self):
        self.case('UBICACION')
        from backend.services import reception_count_plan as plan
        preview=self.detail(self.sid,self.aid)['count_plan']
        with app.db() as db,patch.object(plan,'_reopen_count',side_effect=ValueError('Injected rewind failure')):
            with self.assertRaisesRegex(ValueError,'Injected'):
                plan.include_lines(db,self.sid,{'attention_id':self.aid,'line_ids':[self.lid],
                    'confirmed':True,'state_token':preview['state_token'],'reason':'Test atomic administrative correction'},
                    'qa.admin','ADMINISTRADOR')
            self.assertFalse(db.execute('SELECT 1 FROM reception_attention_lines WHERE reception_line_id=?',(self.lid,)).fetchone())
        self.assertEqual(self.detail(self.sid,self.aid)['app_status'],'UBICACION')
        with app.db() as db:
            self.assertFalse(db.execute('SELECT 1 FROM reception_attention_lines WHERE reception_line_id=?',(self.lid,)).fetchone())

    def test_other_arrival_and_line_validation_evidence_survives_reopening(self):
        self.case('UBICACION')
        with app.db() as db:
            shipment=db.execute('SELECT * FROM reception_shipments WHERE id=?',(self.sid,)).fetchone()
            other=reception._create_reception_attention(db,shipment,None,'qa.admin','VALIDACION')['id']
            db.execute('DELETE FROM reception_attention_lines WHERE attention_id=? AND reception_line_id=?',(other,self.lid))
            db.execute('UPDATE reception_lines SET validation_sap_checked=1,validation_location_checked=1 WHERE id<>?',(self.lid,))
            old_attention=tuple(db.execute('SELECT * FROM reception_attentions WHERE id=?',(other,)).fetchone())
            old_lines=[tuple(r) for r in db.execute('SELECT * FROM reception_attention_lines WHERE attention_id=?',(other,))]
            old_sample=db.execute('SELECT validation_sample_json FROM reception_shipments WHERE id=?',(self.sid,)).fetchone()[0]
        self.apply()
        with app.db() as db:
            self.assertEqual(tuple(db.execute('SELECT * FROM reception_attentions WHERE id=?',(other,)).fetchone()),old_attention)
            self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM reception_attention_lines WHERE attention_id=?',(other,))],old_lines)
            self.assertEqual(db.execute('SELECT validation_sap_checked FROM reception_lines WHERE id<>?',(self.lid,)).fetchone()[0],1)
            self.assertEqual(db.execute('SELECT validation_sample_json FROM reception_shipments WHERE id=?',(self.sid,)).fetchone()[0],old_sample)
