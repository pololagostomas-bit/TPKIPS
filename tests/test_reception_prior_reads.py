"""Overlapping arrival plans must not demand already completed source orders."""
import unittest

from backend.services import reception
from backend.services.reception_partial_count import continue_partial_count
from tests import test_reception_count_locations as fixtures


class PriorReadTests(unittest.TestCase):
    stock_value = fixtures.CountLocationTests.stock_value
    detail = fixtures.CountLocationTests.detail

    def setUp(self):
        fixtures.CountLocationTests.setUp(self)
        self.db.execute("UPDATE reception_shipments SET fr_number='QA-FR' WHERE id=?", (self.sid,))
        self.ids = [self.lid]
        for number in range(1, 39):
            self.ids.append(self.db.execute('''INSERT INTO reception_lines
                (shipment_id,np_code,ov_number,expected_qty) VALUES (?,?,?,1)''',
                (self.sid, f'QA-NP-{number}', f'QA-OV-{number}')).lastrowid)
        shipment = self.db.execute('SELECT * FROM reception_shipments WHERE id=?', (self.sid,)).fetchone()
        self.other = reception._create_reception_attention(
            self.db, shipment, None, 'receiver', 'REVISION SISTEMA')['id']
        for lid in self.ids[1:]:
            self.db.execute('''INSERT INTO reception_attention_lines
                (attention_id,reception_line_id,planned_qty) VALUES (?,?,1)''', (self.attention, lid))
        # Both arrivals were planned before counting. Only the second has 38
        # actual reads; the earlier open arrival still contains default amounts.
        self.db.execute('''UPDATE reception_attention_lines SET verified_qty=planned_qty,np_quantity_saved=0,
            final_location='QA-BIN',count_location_saved=1 WHERE attention_id=?''', (self.attention,))
        self.db.execute('''UPDATE reception_attention_lines SET verified_qty=planned_qty,
            np_scanned_at='2026-10-21 09:00:00',np_scanned_by='receiver',
            final_location='QA-BIN',count_location_saved=1
            WHERE attention_id=? AND reception_line_id<>?''', (self.other, self.lid))
        self.db.execute('''UPDATE reception_attention_lines SET verified_qty=0,
            np_unreceived_reason='Pendiente para otra llegada' WHERE attention_id=? AND reception_line_id=?''',
            (self.other, self.lid))
        self.db.execute("UPDATE reception_attentions SET app_status='CERRADO' WHERE id=?", (self.other,))
        self.db.execute('UPDATE reception_attentions SET system_quantities_initialized=1 WHERE id=?', (self.attention,))
        reception._sync_reception_line_totals(self.db, self.sid)

    def scan_last(self, **values):
        return reception.update_reception_line_quantity(self.db, self.sid, self.lid,
            {'attention_id':self.attention,'received_qty':8,'scan_np':True, **values},
            'receiver','ASISTENTE_RECEPCION')

    def advance(self):
        return reception.change_reception_status(self.db,self.sid,
            {'attention_id':self.attention,'status':'EM'},'receiver','ASISTENTE_RECEPCION')

    def test_readonly_detail_marks_the_38_covered_orders_without_writing(self):
        from backend.services.reception_np_progress import covered_orders
        attention = self.db.execute('SELECT * FROM reception_attentions WHERE id=?',(self.attention,)).fetchone()
        before = self.db.total_changes
        self.assertEqual(len(covered_orders(self.db,self.sid,attention)),38)
        self.assertEqual(self.db.total_changes,before)
        rows = [tuple(row) for row in self.db.execute('SELECT * FROM reception_attention_lines ORDER BY id')]
        history = self.db.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0]
        detail = self.detail()
        self.assertEqual(detail['np_progress'], {'read':38,'total':39})
        self.assertEqual(sum(line.get('np_count_covered_elsewhere', False) for line in detail['lines']),38)
        self.assertFalse(detail['lines'][0].get('np_count_covered_elsewhere', False))
        self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM reception_attention_lines ORDER BY id')],rows)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0],history)

    def test_last_scan_removes_only_unconfirmed_overlap_and_em_finishes(self):
        prior = [tuple(row) for row in self.db.execute(
            'SELECT * FROM reception_attention_lines WHERE attention_id=? ORDER BY id',(self.other,))]
        detail = self.scan_last()
        self.assertEqual(detail['np_progress'], {'read':39,'total':39})
        self.assertEqual(self.db.execute('''SELECT COUNT(*) FROM reception_lines
            WHERE shipment_id=? AND received_qty>expected_qty+0.000000001''',(self.sid,)).fetchone()[0],0)
        self.assertEqual(self.db.execute('''SELECT COUNT(*) FROM reception_attention_lines
            WHERE attention_id=? AND verified_qty>0''',(self.attention,)).fetchone()[0],1)
        self.assertEqual([tuple(row) for row in self.db.execute(
            'SELECT * FROM reception_attention_lines WHERE attention_id=? ORDER BY id',(self.other,))],prior)
        events = self.db.execute("SELECT COUNT(*) FROM reception_history WHERE event_type='CONTEO ACUMULADO'").fetchone()[0]
        self.assertEqual(events,38)
        self.assertEqual(self.advance()['app_status'],'EM')
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_history WHERE event_type='CONTEO ACUMULADO'").fetchone()[0],events)

    def test_already_saved_last_read_can_finish_without_rescanning(self):
        self.db.execute("UPDATE reception_attention_lines SET np_scanned_at='2026-10-21 10:00:00' WHERE attention_id=? AND reception_line_id=?",
            (self.attention,self.lid))
        self.assertEqual(self.advance()['app_status'],'EM')
        self.assertEqual(self.db.execute('SELECT SUM(verified_qty) FROM reception_attention_lines WHERE attention_id=?',(self.attention,)).fetchone()[0],8)

    def test_covered_source_order_cannot_be_scanned_or_bulk_saved_again(self):
        for scan in (True,False):
            with self.subTest(scan=scan):
                before = self.db.total_changes
                with self.assertRaisesRegex(PermissionError,'otra llegada'):
                    reception.update_reception_line_quantity(self.db,self.sid,self.ids[1],
                        {'attention_id':self.attention,'received_qty':1,'scan_np':scan},'receiver','ASISTENTE_RECEPCION')
                self.assertEqual(self.db.total_changes,before)

    def test_partial_scan_other_ov_annulment_legacy_or_explicit_difference_are_not_coverage(self):
        for change in (
            ("UPDATE reception_attention_lines SET verified_qty=0.5 WHERE attention_id=?",(self.other,)),
            ("UPDATE reception_attentions SET condition_status='ANULADA' WHERE id=?",(self.other,)),
            ("UPDATE reception_attentions SET legacy_count_snapshot=1 WHERE id=?",(self.attention,)),
            ("UPDATE reception_attention_lines SET verified_qty=0.5 WHERE attention_id=?",(self.attention,)),
            ("UPDATE reception_attention_lines SET np_scanned_at='2026-10-21 08:00:00' WHERE attention_id=?",(self.attention,)),
            ("UPDATE reception_attention_lines SET np_scanned_at=NULL WHERE attention_id=?",(self.other,)),
            ("UPDATE reception_lines SET expected_qty=expected_qty+1 WHERE shipment_id=?",(self.sid,)),
        ):
            with self.subTest(change=change[0]):
                self.db.execute('SAVEPOINT qa')
                self.db.execute(*change)
                self.assertFalse(any(line.get('np_count_covered_elsewhere',False) for line in self.detail()['lines']))
                self.db.execute('ROLLBACK TO qa'); self.db.execute('RELEASE qa')
        self.db.execute("UPDATE reception_lines SET np_code='NP-QA',ov_number='OV-OTHER' WHERE id=?",(self.ids[1],))
        self.assertFalse(self.detail()['lines'][0].get('np_count_covered_elsewhere',False))

    def test_confirmed_current_scan_is_never_erased_even_if_over_expected(self):
        self.db.execute("UPDATE reception_attention_lines SET np_scanned_at='2026-10-21 08:00:00' WHERE attention_id=? AND reception_line_id=?",
            (self.attention,self.ids[1]))
        self.scan_last()
        self.assertEqual(self.db.execute('SELECT verified_qty FROM reception_attention_lines WHERE attention_id=? AND reception_line_id=?',
            (self.attention,self.ids[1])).fetchone()[0],1)

    def test_explicit_manual_save_equal_to_plan_is_never_erased(self):
        lid = self.ids[1]
        self.db.execute('UPDATE reception_attention_lines SET verified_qty=0,np_scanned_at=NULL WHERE attention_id=? AND reception_line_id=?',
            (self.other,lid))
        reception.update_reception_line_quantity(self.db,self.sid,lid,
            {'attention_id':self.attention,'received_qty':1,'reason':'Conteo manual confirmado','count_location':'MANUAL-QA'},
            'receiver','ASISTENTE_RECEPCION')
        self.db.execute("UPDATE reception_attention_lines SET verified_qty=1,np_scanned_at='2026-10-21 11:00:00' WHERE attention_id=? AND reception_line_id=?",
            (self.other,lid))
        self.scan_last()
        self.assertEqual(self.db.execute('SELECT verified_qty FROM reception_attention_lines WHERE attention_id=? AND reception_line_id=?',
            (self.attention,lid)).fetchone()[0],1)

    def test_later_correction_cannot_resurrect_retired_location_work(self):
        self.scan_last();self.advance()
        self.db.execute("UPDATE reception_attentions SET app_status='UBICACION' WHERE id=?",(self.attention,))
        self.db.execute("UPDATE reception_attention_lines SET verified_qty=0,np_unreceived_reason='CORRECCION ADMIN NP: No llego' WHERE attention_id=? AND reception_line_id=?",
            (self.other,self.ids[1]))
        detail = self.detail()
        previous = next(line for line in detail['lines'] if line['id']==self.ids[1])
        self.assertFalse(previous['location_attention_required'])
        self.assertEqual(detail['np_progress'],{'read':38,'total':39})
        self.db.execute('UPDATE reception_lines SET expected_qty=0 WHERE id=?',(self.ids[1],))
        previous=next(line for line in self.detail()['lines'] if line['id']==self.ids[1])
        self.assertFalse(previous['location_attention_required'])

    def test_export_does_not_report_prior_completed_orders_as_new_shortages(self):
        from io import BytesIO
        from openpyxl import load_workbook
        self.scan_last();self.advance()
        book=load_workbook(BytesIO(reception.reception_operational_report_bytes(
            self.db,self.sid,'ADMINISTRADOR','qa.admin',self.attention)),read_only=True)
        self.addCleanup(book.close)
        rows=list(book['Packing List SAP'].values)[1:]
        covered=[row for row in rows if row[1]!='NP-QA']
        self.assertTrue(all(row[5:9]==(0,0,0,'LEIDO EN OTRA LLEGADA') for row in covered))

    def test_finished_positive_manual_quantities_are_not_hidden_as_prefill(self):
        for stage in ('EM','UBICACION','CERRADO'):
            with self.subTest(stage=stage):
                self.db.execute('UPDATE reception_attentions SET app_status=? WHERE id=?',(stage,self.attention))
                self.assertFalse(any(line.get('np_count_covered_elsewhere',False) for line in self.detail()['lines']))

    def unknown_review(self):
        self.db.execute('UPDATE reception_attention_lines SET np_quantity_saved=NULL WHERE attention_id=?', (self.attention,))
        detail=self.detail()
        return {'attention_id':self.attention,'bl_awb':detail['bl_awb'],'confirmed':True,
                **detail['np_prior_read_review']}

    def test_old_unknown_quantities_require_exact_admin_confirmation(self):
        from backend.services.reception_np_progress import regularize_prior_reads
        data=self.unknown_review()
        self.assertEqual(len(data['line_ids']),38)
        self.scan_last()
        with self.assertRaisesRegex(ValueError,'conteo cambio'):
            regularize_prior_reads(self.db,self.sid,data,'qa.admin','ADMINISTRADOR')
        data.update(self.detail()['np_prior_read_review'])
        result=regularize_prior_reads(self.db,self.sid,data,'qa.admin','ADMINISTRADOR')
        self.assertEqual(result['np_prior_read_review']['line_ids'],[])
        self.assertEqual(sum(line['attention_verified_qty']>0 for line in result['lines']),1)
        self.assertEqual(result['np_progress'],{'read':39,'total':39})
        self.assertEqual(self.advance()['app_status'],'EM')

    def test_unknown_counts_cannot_be_silently_cleared_or_rescanned(self):
        self.unknown_review()
        self.scan_last()
        with self.assertRaisesRegex(PermissionError,'administrador'):
            self.advance()
        with self.assertRaisesRegex(PermissionError,'administrador'):
            continue_partial_count(self.db,self.sid,{'attention_id':self.attention,'confirmed':True,
                'line_ids':self.ids[1:]},'receiver','ASISTENTE_RECEPCION')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_attention_lines WHERE attention_id=? AND verified_qty>0',
            (self.attention,)).fetchone()[0],39)
        with self.assertRaisesRegex(PermissionError,'administrador'):
            reception.update_reception_line_quantity(self.db,self.sid,self.ids[1],
                {'attention_id':self.attention,'received_qty':1,'scan_np':True},'receiver','ASISTENTE_RECEPCION')

    def test_prior_reads_cannot_invent_receipt_of_a_sku_in_an_empty_arrival(self):
        with self.assertRaisesRegex(ValueError,'cerrarla conservando el saldo'):
            continue_partial_count(self.db,self.sid,{'attention_id':self.attention,'confirmed':True,
                'line_ids':[self.lid]},'receiver','ASISTENTE_RECEPCION')
        self.assertEqual(self.detail()['app_status'],'REVISION SISTEMA')

    def test_regularization_permission_confirmation_state_and_scope_guards_never_write(self):
        from backend.services.reception_np_progress import regularize_prior_reads
        data=self.unknown_review()
        for change in ({'confirmed':False},{'bl_awb':'OTHER'},{'state_token':'stale'},
                       {'line_ids':data['line_ids'][:-1]},{'line_ids':[True]},{'attention_id':False}):
            with self.subTest(change=change):
                before=self.db.total_changes
                with self.assertRaises((ValueError,PermissionError)):
                    regularize_prior_reads(self.db,self.sid,{**data,**change},'qa.admin','ADMINISTRADOR')
                self.assertEqual(self.db.total_changes,before)
        before=self.db.total_changes
        with self.assertRaises(PermissionError):
            regularize_prior_reads(self.db,self.sid,data,'receiver','ASISTENTE_RECEPCION')
        self.assertEqual(self.db.total_changes,before)

    def test_regularization_is_atomic_and_uncertain_retry_cannot_duplicate_audit(self):
        from unittest.mock import patch
        from backend.services.reception_np_progress import regularize_prior_reads
        data=self.unknown_review()
        before=[tuple(row) for row in self.db.execute('SELECT * FROM reception_attention_lines ORDER BY id')]
        history=self.db.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0]
        with patch.object(reception,'reception_detail',side_effect=RuntimeError('QA failure')):
            with self.assertRaises(RuntimeError):
                regularize_prior_reads(self.db,self.sid,data,'qa.admin','ADMINISTRADOR')
        self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM reception_attention_lines ORDER BY id')],before)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0],history)
        regularize_prior_reads(self.db,self.sid,data,'qa.admin','ADMINISTRADOR')
        history=self.db.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0]
        with self.assertRaises(ValueError):regularize_prior_reads(self.db,self.sid,data,'qa.admin','ADMINISTRADOR')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0],history)

    def test_admin_can_preserve_one_genuine_old_manual_receipt_instead_of_removing_it(self):
        from backend.services.reception_np_progress import regularize_prior_reads
        data=self.unknown_review()
        lid=self.ids[1]
        result=regularize_prior_reads(self.db,self.sid,
            {**data,'action':'keep_quantity','line_ids':[lid]},'qa.admin','ADMINISTRADOR')
        line=next(line for line in result['lines'] if line['id']==lid)
        self.assertEqual(line['attention_verified_qty'],1)
        self.assertTrue(line['np_count_confirmed_manually'])
        self.assertFalse(line['np_scanned_at'])
        self.assertNotIn(lid,result['np_prior_read_review']['line_ids'])
        self.scan_last()
        data.update(self.detail()['np_prior_read_review'])
        regularize_prior_reads(self.db,self.sid,data,'qa.admin','ADMINISTRADOR')
        self.assertEqual(self.advance()['app_status'],'EM')
        self.assertEqual(self.db.execute('SELECT verified_qty FROM reception_attention_lines WHERE attention_id=? AND reception_line_id=?',
            (self.attention,lid)).fetchone()[0],1)

    def test_stale_automatic_scan_cannot_overwrite_a_manual_admin_confirmation(self):
        from backend.services.reception_np_progress import regularize_prior_reads
        data=self.unknown_review();lid=self.ids[1]
        regularize_prior_reads(self.db,self.sid,{**data,'action':'keep_quantity','line_ids':[lid]},'qa.admin','ADMINISTRADOR')
        reception.update_reception_line_quantity(self.db,self.sid,lid,
            {'attention_id':self.attention,'received_qty':2,'reason':'Fisico confirmado por administrador'},'qa.admin','ADMINISTRADOR')
        result=reception.update_reception_line_quantity(self.db,self.sid,lid,
            {'attention_id':self.attention,'received_qty':1,'scan_np':True},'qa.admin','ADMINISTRADOR')
        line=next(line for line in result['lines'] if line['id']==lid)
        self.assertEqual(line['attention_verified_qty'],2)
        self.assertFalse(line['np_scanned_at'])

    def test_partial_confirmation_contains_only_the_genuinely_pending_order(self):
        self.db.execute('UPDATE reception_attention_lines SET np_scanned_at=NULL,verified_qty=0 WHERE attention_id=? AND reception_line_id=?',
            (self.other,self.ids[1]))
        self.scan_last()
        result = continue_partial_count(self.db,self.sid,
            {'attention_id':self.attention,'confirmed':True,'line_ids':[self.ids[1]]},'receiver','ASISTENTE_RECEPCION')
        self.assertEqual(result['app_status'],'EM')
        self.assertEqual(result['np_progress'],{'read':38,'total':39})
        self.assertEqual(sum(bool(line['np_unreceived_reason']) for line in result['lines']),1)

    def test_failed_location_check_never_reconciles_prefill_or_audit(self):
        self.db.execute("UPDATE reception_attention_lines SET np_scanned_at='2026-10-21 10:00:00',final_location='',count_location_manual=0 WHERE attention_id=? AND reception_line_id=?",
            (self.attention,self.lid))
        before = [tuple(row) for row in self.db.execute('SELECT * FROM reception_attention_lines ORDER BY id')]
        history = self.db.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0]
        with self.assertRaisesRegex(PermissionError,'ubicaci.n'):
            self.advance()
        self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM reception_attention_lines ORDER BY id')],before)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0],history)


if __name__=='__main__':
    unittest.main()
