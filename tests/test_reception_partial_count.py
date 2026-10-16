"""Confirmed unread SKU deferral, atomic EM transition and later-arrival balance."""
import unittest
from unittest.mock import patch

from backend.services import reception
from backend.services.reception_partial_count import continue_partial_count, DEFERRED_REASON
from backend.services.reception_work import reception_work_report
from tests import test_reception_count_locations as fixtures


class PartialCountTests(unittest.TestCase):
    setUpBase = fixtures.CountLocationTests.setUp
    stock_value = fixtures.CountLocationTests.stock_value
    detail = fixtures.CountLocationTests.detail

    def setUp(self):
        self.setUpBase()
        self.db.execute("UPDATE reception_shipments SET fr_number='QA-FR' WHERE id=?",(self.sid,))
        self.missing = self.db.execute('''INSERT INTO reception_lines
            (shipment_id,np_code,ov_number,expected_qty) VALUES (?,'NP-LATER','OV-2',2)''',
            (self.sid,)).lastrowid
        self.db.execute('''INSERT INTO reception_attention_lines
            (attention_id,reception_line_id,planned_qty,verified_qty) VALUES (?,?,2,2)''',
            (self.attention,self.missing))

    def scan(self, lid=None, qty=8, attention=None):
        return reception.update_reception_line_quantity(self.db,self.sid,lid or self.lid,
            {'attention_id':attention or self.attention,'received_qty':qty,'scan_np':True},
            'receiver','ASISTENTE_RECEPCION')

    def partial(self, **overrides):
        return continue_partial_count(self.db,self.sid,
            {'attention_id':self.attention,'confirmed':True,'line_ids':[self.missing],**overrides},
            'receiver','ASISTENTE_RECEPCION')

    def test_nine_of_ten_skus_continue_without_receiving_the_tenth(self):
        self.scan()
        for number in range(8):
            lid=self.db.execute('''INSERT INTO reception_lines
                (shipment_id,np_code,expected_qty) VALUES (?,?,1)''',(self.sid,f'NP-READ-{number}')).lastrowid
            self.db.execute('''INSERT INTO reception_attention_lines
                (attention_id,reception_line_id,planned_qty) VALUES (?,?,1)''',(self.attention,lid))
            self.scan(lid,1)
        result=self.partial()
        self.assertEqual(result['app_status'],'EM')
        self.assertEqual(sum(bool(line['np_scanned_at']) for line in result['lines']),9)
        missing=next(line for line in result['lines'] if line['id']==self.missing)
        self.assertEqual(missing['attention_verified_qty'],0)
        self.assertEqual(missing['attention_planned_qty'],2)
        self.assertEqual(missing['expected_qty'],2)
        self.assertFalse(missing['np_scanned_at'])
        self.assertEqual(missing['np_unreceived_reason'],DEFERRED_REASON)
        self.assertEqual(self.db.execute('SELECT received_packages FROM reception_shipments WHERE id=?',(self.sid,)).fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_receipts').fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_history WHERE event_type='CONTEO PARCIAL'").fetchone()[0],1)

    def test_uncertain_response_retry_is_idempotent(self):
        self.scan();self.partial()
        before=[tuple(row) for row in self.db.execute('SELECT * FROM reception_attention_lines ORDER BY id')]
        history=self.db.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0]
        self.assertEqual(self.partial()['app_status'],'EM')
        self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM reception_attention_lines ORDER BY id')],before)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0],history)

    def test_unconfirmed_or_empty_or_invalid_line_lists_never_write(self):
        self.scan()
        for overrides in ({'confirmed':False},{'confirmed':'true'},{'line_ids':[]},
                {'line_ids':[True]},{'line_ids':[str(self.missing)]},
                {'line_ids':[self.missing,self.missing]},{'attention_id':None}):
            with self.subTest(overrides=overrides):
                before=self.db.total_changes
                with self.assertRaises(ValueError):self.partial(**overrides)
                self.assertEqual(self.db.total_changes,before)

    def test_without_any_positive_saved_scan_cannot_declare_everything_missing(self):
        before=self.db.total_changes
        with self.assertRaisesRegex(ValueError,'Escanea al menos'):
            self.partial(line_ids=[self.lid,self.missing])
        self.assertEqual(self.db.total_changes,before)

    def test_missing_list_changed_by_another_scan_cannot_zero_that_scan(self):
        self.scan();self.scan(self.missing,2)
        before=self.db.total_changes
        with self.assertRaisesRegex(ValueError,'lecturas cambiaron'):self.partial()
        self.assertEqual(self.db.total_changes,before)
        self.assertEqual(self.detail()['lines'][1]['attention_verified_qty'],2)

    def test_all_unresolved_orders_are_confirmed_not_just_filtered_np(self):
        self.scan()
        another=self.db.execute('''INSERT INTO reception_lines
            (shipment_id,np_code,expected_qty) VALUES (?,'NP-ALSO-LATER',1)''',(self.sid,)).lastrowid
        self.db.execute('''INSERT INTO reception_attention_lines
            (attention_id,reception_line_id,planned_qty,verified_qty) VALUES (?,?,1,1)''',(self.attention,another))
        before=self.db.total_changes
        with self.assertRaisesRegex(ValueError,'lecturas cambiaron'):self.partial()
        self.assertEqual(self.db.total_changes,before)

    def test_other_bl_attention_role_or_assignee_is_rejected(self):
        self.scan()
        for role,user in [('PICKER','receiver'),('ASISTENTE_RECEPCION','stranger')]:
            with self.assertRaises(PermissionError):
                continue_partial_count(self.db,self.sid,
                    {'attention_id':self.attention,'confirmed':True,'line_ids':[self.missing]},user,role)
        with self.assertRaises(ValueError):self.partial(attention_id=99999)

    def test_location_failure_rolls_back_all_missing_quantities_and_audit(self):
        self.scan()
        self.db.execute("UPDATE reception_attention_lines SET final_location='',count_location_saved=1,count_location_manual=0 WHERE reception_line_id=?",(self.lid,))
        history=self.db.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0]
        with self.assertRaisesRegex(PermissionError,'ubicación'):self.partial()
        line=next(line for line in self.detail()['lines'] if line['id']==self.missing)
        self.assertEqual(line['attention_verified_qty'],2)
        self.assertFalse(line['np_unreceived_reason'])
        self.assertEqual(self.detail()['app_status'],'REVISION SISTEMA')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0],history)

    def test_missing_fr_still_blocks_and_rolls_back_deferral(self):
        self.scan()
        self.db.execute('UPDATE reception_shipments SET fr_number=NULL WHERE id=?',(self.sid,))
        with self.assertRaisesRegex(PermissionError,'factura de reserva'):self.partial()
        line=next(line for line in self.detail()['lines'] if line['id']==self.missing)
        self.assertFalse(line['np_unreceived_reason'])
        self.assertEqual(line['attention_verified_qty'],2)

    def test_fr_of_an_unreceived_ip_does_not_block_the_received_ip(self):
        self.db.execute("UPDATE reception_lines SET ip_reference='IP-101' WHERE id=?",(self.lid,))
        self.db.execute("UPDATE reception_lines SET ip_reference='IP-102' WHERE id=?",(self.missing,))
        self.db.execute('''INSERT INTO reception_accounting_refs
            (shipment_id,source_key,ip_reference,fr_number,created_at,updated_at)
            VALUES (?,'qa-received-ip','IP-101','QA-FR','2026-10-16','2026-10-16')''',(self.sid,))
        self.scan()
        self.assertEqual(reception._accounting_status_for_shipment(self.db,self.sid),'PENDIENTE FR')
        self.assertEqual(self.partial()['app_status'],'EM')

    def test_same_sku_different_orders_do_not_zero_the_already_scanned_order(self):
        self.db.execute("UPDATE reception_lines SET np_code='NP-QA' WHERE id=?",(self.missing,))
        self.scan();self.partial()
        lines={line['id']:line for line in self.detail()['lines']}
        self.assertEqual(lines[self.lid]['attention_verified_qty'],8)
        self.assertEqual(lines[self.missing]['attention_verified_qty'],0)
        self.assertNotEqual(lines[self.lid]['ov_number'],lines[self.missing]['ov_number'])

    def test_partial_attention_can_close_but_master_keeps_units_for_next_arrival(self):
        self.scan();self.partial()
        self.db.execute("UPDATE reception_shipments SET em_number='QA-EM' WHERE id=?",(self.sid,))
        self.db.execute("UPDATE reception_attentions SET app_status='SOLICITUD TRANSFERENCIA',transfer_assistant_checked=1 WHERE id=?",(self.attention,))
        reception.change_reception_status(self.db,self.sid,
            {'attention_id':self.attention,'status':'CERRADO'},'receiver','ASISTENTE_RECEPCION')
        master=self.db.execute('SELECT * FROM reception_shipments WHERE id=?',(self.sid,)).fetchone()
        self.assertNotEqual(master['app_status'],'CERRADO')
        self.assertEqual(master['condition_status'],'UNIDADES POR ATENDER')
        work=reception_work_report(self.db,now='2026-10-16 10:00:00')
        self.assertEqual(work['items'],[])
        self.assertEqual(work['summary']['total'],0)
        self.assertEqual(work['summary']['pending_truck'],1)
        self.assertEqual(work['summary']['sla_missing_start'],0)
        waiting=reception_work_report(self.db,view='truck',now='2026-10-16 10:00:00')['items'][0]
        self.assertTrue(waiting['awaiting_next_arrival'])
        self.assertEqual(waiting['pending_sku_count'],1)
        self.assertIsNone(waiting['work_started_at'])
        self.assertIsNone(waiting['scheduled_date'])
        second=reception._create_reception_attention(self.db,master,None,'receiver','REVISION SISTEMA')
        detail=self.detail(second['id'])
        lines={line['id']:line for line in detail['lines']}
        self.assertEqual(lines[self.lid]['attention_planned_qty'],0)
        self.assertEqual(lines[self.missing]['attention_planned_qty'],2)
        self.assertFalse(lines[self.missing]['np_unreceived_reason'])
        self.assertFalse(lines[self.missing]['np_scanned_at'])
        self.scan(self.missing,2,second['id'])
        self.db.execute("UPDATE reception_attentions SET app_status='SOLICITUD TRANSFERENCIA',transfer_assistant_checked=1 WHERE id=?",(second['id'],))
        reception.change_reception_status(self.db,self.sid,
            {'attention_id':second['id'],'status':'CERRADO'},'receiver','ASISTENTE_RECEPCION')
        self.assertEqual(self.db.execute('SELECT app_status FROM reception_shipments WHERE id=?',(self.sid,)).fetchone()[0],'CERRADO')

    def test_new_positive_receipt_without_attention_is_not_mistaken_for_future_stock(self):
        self.scan();self.partial()
        self.db.execute("UPDATE reception_attentions SET app_status='CERRADO' WHERE id=?",(self.attention,))
        self.db.execute("UPDATE reception_shipments SET app_status='ARRIBADO' WHERE id=?",(self.sid,))
        self.db.execute('''INSERT INTO reception_receipts
            (shipment_id,sequence_no,received_packages,username,received_at)
            VALUES (?,1,1,'receiver','2026-10-16 09:00:00')''',(self.sid,))
        report=reception_work_report(self.db,now='2026-10-16 10:00:00')
        self.assertEqual(report['summary']['pending_truck'],0)
        self.assertFalse(report['items'][0]['awaiting_next_arrival'])


if __name__=='__main__':
    unittest.main()
