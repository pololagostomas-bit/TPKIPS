"""Location progress is physical work, separate from stock and temporary bins."""
import unittest
from unittest.mock import patch
from backend.services import reception
from tests import test_reception_final_locations as fixtures


class LocationProgressTests(unittest.TestCase):
    setUp=fixtures.ReceptionFinalLocationTests.setUp
    tearDown=fixtures.ReceptionFinalLocationTests.tearDown
    record_count_location=fixtures.ReceptionFinalLocationTests.record_count_location

    def save(self, location, **overrides):
        item={'line_id':self.line_id,'final_location':location,'confirmed':True,**overrides}
        return reception.update_reception_line_locations(self.connection,self.shipment_id,
            {'locations':[item]},'asistente.test','ASISTENTE_RECEPCION')

    def test_worker_changes_destination_during_location_and_audit_keeps_count(self):
        self.record_count_location('COUNT-BIN')
        before=tuple(self.connection.execute('SELECT planned_qty,verified_qty,np_scanned_at,np_scanned_by FROM reception_attention_lines').fetchone())
        result=self.save('FINAL-BIN')
        self.assertEqual(result['lines'][0]['final_location'],'FINAL-BIN')
        self.assertEqual(result['lines'][0]['final_location_confirmed'],1)
        self.assertEqual(tuple(self.connection.execute('SELECT planned_qty,verified_qty,np_scanned_at,np_scanned_by FROM reception_attention_lines').fetchone()),before)
        self.assertEqual(self.connection.execute('SELECT location_text FROM reception_receipts').fetchone()[0],'TEMP-CAMION-01')
        self.assertTrue(self.connection.execute("SELECT 1 FROM reception_history WHERE event_type='UBICACION' AND old_value='COUNT-BIN' AND new_value='FINAL-BIN'").fetchone())

    def test_partial_save_retains_other_np_and_requires_all_before_advancing(self):
        self.record_count_location('BIN-A')
        aid=self.connection.execute('SELECT id FROM reception_attentions').fetchone()[0]
        other=self.connection.execute('INSERT INTO reception_lines(shipment_id,np_code,expected_qty) VALUES (?,?,1)',(self.shipment_id,'NP-OTHER')).lastrowid
        self.connection.execute('INSERT INTO reception_attention_lines(attention_id,reception_line_id,planned_qty,verified_qty) VALUES (?,?,1,1)',(aid,other))
        self.save('BIN-A')
        with self.assertRaises(PermissionError):
            reception.change_reception_status(self.connection,self.shipment_id,{'status':'VALIDACION'},'asistente.test','ASISTENTE_RECEPCION')
        self.assertEqual(self.connection.execute('SELECT final_location_confirmed FROM reception_attention_lines WHERE reception_line_id=?',(self.line_id,)).fetchone()[0],1)
        self.assertEqual(self.connection.execute('SELECT final_location_confirmed FROM reception_attention_lines WHERE reception_line_id=?',(other,)).fetchone()[0],0)
        reception.update_reception_line_locations(self.connection,self.shipment_id,
            {'locations':[{'line_id':other,'final_location':'BIN-B','confirmed':True}]},'asistente.test','ASISTENTE_RECEPCION')
        result=reception.change_reception_status(self.connection,self.shipment_id,{'status':'VALIDACION'},'asistente.test','ASISTENTE_RECEPCION')
        self.assertEqual(result['app_status'],'VALIDACION')

    def test_blank_without_stock_still_requires_a_destination_at_location(self):
        reception.global_stock_summary.return_value={'stock_cut_qty':0,'stock_available_qty':0,'stock_default_location':''}
        self.record_count_location('')
        with self.assertRaises(ValueError):self.save('')
        self.connection.execute('UPDATE reception_attention_lines SET final_location_confirmed=1')
        with self.assertRaises(PermissionError):
            reception.change_reception_status(self.connection,self.shipment_id,{'status':'VALIDACION'},'asistente.test','ASISTENTE_RECEPCION')
        self.assertEqual(self.save('MANUAL-BIN')['lines'][0]['final_location'],'MANUAL-BIN')

    def test_stale_row_save_cannot_overwrite_a_new_location(self):
        self.record_count_location('BIN-A')
        self.save('BIN-B',previous_location='BIN-A',previous_confirmed=False)
        with self.assertRaises(ValueError):self.save('BIN-C',previous_location='BIN-A',previous_confirmed=False)
        self.assertEqual(self.connection.execute('SELECT final_location FROM reception_attention_lines').fetchone()[0],'BIN-B')

    def test_bad_type_line_or_location_does_not_write_first_row(self):
        self.record_count_location('BIN-A')
        for bad in ({'line_id':True,'confirmed':True},{'line_id':self.line_id,'final_location':['bad'],'confirmed':True},
                    {'line_id':self.line_id,'final_location':'a\nb','confirmed':True}):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                reception.update_reception_line_locations(self.connection,self.shipment_id,
                    {'locations':[{'line_id':self.line_id,'final_location':'NEW','confirmed':True},bad]},
                    'asistente.test','ASISTENTE_RECEPCION')
        self.assertEqual(self.connection.execute('SELECT final_location FROM reception_attention_lines').fetchone()[0],'BIN-A')

    def test_scope_and_stage_permissions_apply_to_editable_locations(self):
        self.record_count_location('BIN-A')
        body={'locations':[{'line_id':self.line_id,'final_location':'BIN-B','confirmed':True}]}
        for user,role in [('outsider','ASISTENTE_RECEPCION'),('picker','PICKER')]:
            with self.subTest(user=user),self.assertRaises(PermissionError):
                reception.update_reception_line_locations(self.connection,self.shipment_id,body,user,role)
        for stage in ('REVISION SISTEMA','EM','VALIDACION','CERRADO'):
            self.connection.execute('UPDATE reception_attentions SET app_status=?',(stage,))
            with self.subTest(stage=stage),self.assertRaises(PermissionError):
                reception.update_reception_line_locations(self.connection,self.shipment_id,body,'admin','ADMINISTRADOR')
        self.connection.execute("UPDATE reception_attentions SET app_status='UBICACION'")
        result=reception.update_reception_line_locations(self.connection,self.shipment_id,body,'auxiliar.test','AUXILIAR_RECEPCION')
        self.assertEqual(result['lines'][0]['final_location'],'BIN-B')

    def test_savepoint_rolls_back_even_when_caller_catches_a_late_failure(self):
        self.record_count_location('BIN-A')
        with patch.object(reception,'reception_detail',side_effect=ValueError('Injected response failure')):
            with self.assertRaisesRegex(ValueError,'Injected'):self.save('BIN-B')
        self.assertEqual(self.connection.execute('SELECT final_location FROM reception_attention_lines').fetchone()[0],'BIN-A')

    def test_another_arrival_and_unreceived_np_do_not_share_location_work(self):
        self.record_count_location('BIN-A')
        original=self.connection.execute('SELECT id FROM reception_attentions').fetchone()[0]
        shipment=self.connection.execute('SELECT * FROM reception_shipments WHERE id=?',(self.shipment_id,)).fetchone()
        other=reception._create_reception_attention(self.connection,shipment,None,'admin','UBICACION')['id']
        self.connection.execute("UPDATE reception_attention_lines SET final_location='OTHER',final_location_confirmed=1 WHERE attention_id=?",(other,))
        reception.update_reception_line_locations(self.connection,self.shipment_id,
            {'attention_id':original,'locations':[{'line_id':self.line_id,'final_location':'FIRST','confirmed':True}]},
            'asistente.test','ASISTENTE_RECEPCION')
        self.assertEqual(self.connection.execute('SELECT final_location FROM reception_attention_lines WHERE attention_id=?',(other,)).fetchone()[0],'OTHER')
        # An assigned but absent NP is not a putaway requirement for this arrival.
        missing=self.connection.execute('INSERT INTO reception_lines(shipment_id,np_code,expected_qty) VALUES (?,?,1)',(self.shipment_id,'NOT-RECEIVED')).lastrowid
        self.connection.execute("INSERT INTO reception_attention_lines(attention_id,reception_line_id,planned_qty,verified_qty,np_unreceived_reason) VALUES (?,?,1,0,'Arrives later')",(original,missing))
        result=reception.change_reception_status(self.connection,self.shipment_id,{'attention_id':original,'status':'VALIDACION'},'asistente.test','ASISTENTE_RECEPCION')
        self.assertEqual(result['app_status'],'VALIDACION')
