"""Physical preparation without a fictitious FR/EM; isolated SQLite only."""
from io import BytesIO
import unittest
from unittest.mock import patch
from openpyxl import load_workbook
from backend.services import reception, reception_report_export, reception_transfer
from tests import test_reception_count_locations as fixtures


class ReceptionNoFRTests(unittest.TestCase):
    setUp = fixtures.CountLocationTests.setUp
    stock_value = fixtures.CountLocationTests.stock_value

    def scan(self):
        return reception.update_reception_line_quantity(self.db,self.sid,self.lid,
            {'attention_id':self.attention,'received_qty':8,'count_location':'CUT-01','scan_np':True},
            'receiver','ASISTENTE_RECEPCION')

    def change(self,status,**values):
        return reception.change_reception_status(self.db,self.sid,
            {'attention_id':self.attention,'status':status,**values},'receiver','ASISTENTE_RECEPCION')

    def admin(self):
        return reception.reception_detail(self.db,self.sid,'ADMINISTRADOR','admin',self.attention)

    def enter(self):
        self.scan()
        with patch.object(reception,'reception_now',return_value='2026-10-26T09:00:00'):
            return self.change('EM')

    def fr(self,value,stamp):
        with patch.object(reception,'reception_now',return_value=stamp):
            return reception.update_reception_references(self.db,self.sid,
                {'attention_id':self.attention,'fr_number':value},'admin','ADMINISTRADOR')

    def test_complete_count_enters_em_and_preserves_documentary_debt(self):
        result=self.enter()
        self.assertEqual(result['app_status'],'EM')
        self.assertEqual(result['accounting_status'],'PENDIENTE CONTABILIDAD')
        self.assertFalse(result['fr_number']);self.assertFalse(result['em_number'])
        self.assertIn('factura de reserva',result['accounting_warning'].lower())
        self.assertEqual(result['lines'][0]['attention_verified_qty'],8)
        self.assertEqual(result['lines'][0]['final_location'],'CUT-01')
        self.assertNotIn('fr_wait',result,'Only the administrator sees the timer')
        self.assertEqual(self.db.execute('SELECT count(*) FROM reception_accounting_refs').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM reception_transfer_requests').fetchone()[0],0)

    def test_existing_explicit_pending_action_allows_physical_location_without_fr(self):
        self.enter()
        with self.assertRaisesRegex(PermissionError,'Registra la EM'):
            self.change('UBICACION')
        result=self.change('UBICACION',allow_pending_em=True)
        self.assertEqual(result['app_status'],'UBICACION')
        self.assertFalse(result['em_number']);self.assertFalse(result['fr_number'])

    def test_real_em_registration_and_unassigned_or_wrong_role_remain_blocked(self):
        self.enter()
        with self.assertRaises(PermissionError):
            reception.update_reception_references(self.db,self.sid,
                {'attention_id':self.attention,'em_number':'QA-NOT-REAL'},'receiver','ASISTENTE_RECEPCION')
        self.assertFalse(self.admin()['em_number'])
        for role,user in [('PICKER','receiver'),('ASISTENTE_RECEPCION','unassigned')]:
            with self.subTest(role=role,user=user),self.assertRaises(PermissionError):
                reception.change_reception_status(self.db,self.sid,
                    {'attention_id':self.attention,'status':'UBICACION','allow_pending_em':True},user,role)

    def test_previous_delivery_quantity_cannot_substitute_positive_current_count(self):
        self.scan()
        self.db.execute('UPDATE reception_attention_lines SET verified_qty=0 WHERE attention_id=?',(self.attention,))
        with self.assertRaisesRegex(PermissionError,'SKU encontrado'):
            self.change('EM')

    def test_no_stock_saved_handwritten_destination_can_enter_em_without_fr(self):
        self.stock_qty=0
        reception.update_reception_line_quantity(self.db,self.sid,self.lid,
            {'attention_id':self.attention,'received_qty':8,'count_location':'','scan_np':True},
            'receiver','ASISTENTE_RECEPCION')
        result=self.change('EM')
        self.assertEqual(result['app_status'],'EM')
        self.assertEqual(result['lines'][0]['final_location'],'')
        self.assertEqual(result['lines'][0]['count_location_manual'],1)

    def test_missing_scans_still_block_and_do_not_start_documentary_clock(self):
        self.scan()
        lid=self.db.execute("INSERT INTO reception_lines(shipment_id,np_code,expected_qty) VALUES (?,'QA-MISSING',1)",(self.sid,)).lastrowid
        self.db.execute('INSERT INTO reception_attention_lines(attention_id,reception_line_id,planned_qty) VALUES (?,?,1)',(self.attention,lid))
        with self.assertRaisesRegex(PermissionError,'Faltan NP'):
            self.change('EM')
        self.assertEqual(self.db.execute("SELECT count(*) FROM reception_history WHERE field_name='fr_wait'").fetchone()[0],0)

    def test_timer_resolves_on_real_fr_and_is_idempotent_read_only(self):
        self.enter()
        with patch.object(reception,'reception_now',return_value='2026-10-26T10:00:00'):
            from backend.services.reception_fr_wait import summaries
            before=self.db.total_changes
            wait=summaries(self.db,self.sid)[self.sid]
            self.assertTrue(wait['pending']);self.assertEqual(wait['hours'],1)
            self.assertEqual(self.db.total_changes,before)
            self.assertEqual(self.admin()['fr_wait'],wait)
        result=self.fr('QA-FR','2026-10-26T11:00:00')
        self.assertEqual(result['accounting_status'],'PENDIENTE EM')
        self.assertFalse(result['em_number'])
        self.assertFalse(result['fr_wait']['pending']);self.assertEqual(result['fr_wait']['hours'],2)
        count=self.db.execute("SELECT count(*) FROM reception_history WHERE field_name='fr_wait'").fetchone()[0]
        reception._refresh_accounting_summary(self.db,self.sid,'admin','qa-repeat.xlsx')
        self.assertEqual(self.db.execute("SELECT count(*) FROM reception_history WHERE field_name='fr_wait'").fetchone()[0],count)

    def test_distinct_wait_episodes_accumulate_without_retroactive_invention(self):
        self.enter();self.fr('QA-FR','2026-10-26T11:00:00')
        self.fr('','2026-10-26T12:00:00')
        result=self.fr('QA-FR-2','2026-10-26T13:00:00')
        self.assertEqual(result['fr_wait']['hours'],3)
        self.assertFalse(result['fr_wait']['pending'])

    def test_old_unobserved_fr_gap_has_no_invented_duration(self):
        result=self.admin()
        self.assertIsNone(result['fr_wait'])
        row=reception.reception_report(self.db)['items'][0]
        self.assertIsNone(row['fr_wait_hours'])
        self.assertEqual(row['fr_wait_note'],'')

    def test_repeated_observation_of_same_bl_does_not_double_wait_time(self):
        self.enter()
        from backend.services.reception_fr_wait import observe,summaries
        with patch.object(reception,'reception_now',return_value='2026-10-26T10:00:00'):
            for _ in range(3):observe(self.db,self.sid,'admin',allow_start=True)
            self.assertEqual(summaries(self.db,self.sid)[self.sid]['hours'],1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM reception_history WHERE field_name='fr_wait' AND new_value='1'").fetchone()[0],1)

    def test_filtered_report_and_excel_include_documentary_wait_comment(self):
        self.enter();self.fr('QA-FR','2026-10-26T11:00:00')
        before=self.db.total_changes
        report=reception.reception_report(self.db)
        self.assertEqual(report['items'][0]['fr_wait_hours'],2)
        self.assertIn('FR',report['items'][0]['fr_wait_note'])
        book=load_workbook(BytesIO(reception_report_export.build(self.db,{'search':'QA-COUNT'})),read_only=True)
        try:
            rows=list(book['Indicadores BL'].values)
            self.assertEqual(rows[1][rows[0].index('Espera documental FR (h)')],2)
            self.assertIn('FR',rows[1][rows[0].index('Observacion documental')])
        finally:book.close()
        self.assertEqual(self.db.total_changes,before)

    def test_transfer_mail_marks_missing_fr_red_without_claiming_documentary_completion(self):
        payload=reception_transfer.mail_payload(
            {'public_origin':'https://wms.example','recipient':'qa@example.com'},
            {'bl_awb':'QA-NO-FR','em_number':'','accounting_status':'PENDIENTE CONTABILIDAD',
             'fr_wait':{'hours':2,'note':'Espera documental FR: 2 h'}},None,'qa-token')
        content=payload['message']['body']['content']
        self.assertIn('Pendiente de FR',content)
        self.assertIn('#b43c36',content)
        self.assertIn('2 h',content)
        self.assertIn('regulariz',content.lower())
