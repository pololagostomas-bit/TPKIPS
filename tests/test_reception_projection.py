"""Documentary availability and truck plans never substitute physical receipt."""
import sqlite3
import unittest
from unittest.mock import patch

from backend.services import reception
from backend.services.reception_work import reception_work_report
from backend.services.traceability import init_traceability_schema
from tests.test_reception_work import STAMP, NOW, shipment, complete_refs


class ReceptionProjectionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        reception.init_reception_schema(self.db)
        init_traceability_schema(self.db)
        self.db.execute('CREATE TABLE order_importation_refs '
                        '(bl_awb TEXT,sap_ov TEXT,transport_type TEXT,ip_reference TEXT,oc_number TEXT)')

    def excel_shipment(self, bl='QA-EXCEL', status='ARRIBADO'):
        sid = shipment(self.db, bl=bl, status=status, arrival=STAMP)
        self.db.execute('''INSERT INTO reception_history
            (shipment_id,event_type,field_name,new_value,username,created_at)
            VALUES (?,'IMPORTACION EXCEL','app_status','ARRIBADO','qa',?)''', (sid,STAMP))
        return sid

    def positive_receipt(self, sid, packages=1):
        return self.db.execute('''INSERT INTO reception_receipts
            (shipment_id,sequence_no,received_packages,username,received_at)
            VALUES (?,1,?,'qa',?)''',(sid,packages,STAMP)).lastrowid

    def test_excel_arrival_is_consistent_in_queue_detail_report_and_work(self):
        sid = self.excel_shipment()
        complete_refs(self.db,sid)
        before = self.db.total_changes
        self.db.execute('PRAGMA query_only=ON')
        with patch.object(reception,'global_stock_summary',return_value={}):
            detail = reception.reception_detail(self.db,sid)
        queue = reception.list_receptions(self.db,state='PROGRAMADO')
        report = reception.reception_report(self.db,limit=50,arrival='PROGRAMADO',sla='SIN INICIO')
        waiting = reception_work_report(self.db,view='arrival',now=NOW)
        for item in (detail,queue[0],report['items'][0],waiting['items'][0]):
            self.assertEqual(item['app_status'],'PROGRAMADO')
        self.assertTrue(detail['awaiting_arrival'])
        self.assertIsNone(detail['physical_started_at'])
        self.assertEqual(detail['stored_app_status'],'ARRIBADO')
        self.assertEqual(reception.list_receptions(self.db,state='ARRIBADO'),[])
        self.assertEqual(reception_work_report(self.db,now=NOW)['items'],[])
        self.assertEqual(waiting['summary']['total'],0)
        self.assertEqual(report['summary']['total_pendientes'],0)
        self.assertEqual(self.db.total_changes,before)
        raw = self.db.execute('SELECT app_status,first_arrival_at FROM reception_shipments WHERE id=?',(sid,)).fetchone()
        self.assertEqual(tuple(raw),('ARRIBADO',STAMP))

    def test_confirmed_truck_is_still_waiting_until_positive_arrival(self):
        sid = self.excel_shipment()
        self.db.execute('''INSERT INTO reception_truck_guides
            (guide_code,is_confirmed,created_by,created_at,updated_at)
            VALUES ('QA-TRUCK',1,'qa',?,?)''',(STAMP,STAMP))
        self.db.execute('''INSERT INTO reception_truck_arrivals
            (truck_guide,received_packages,username,received_at,updated_at)
            VALUES ('QA-TRUCK',10,'qa',?,?)''',(STAMP,STAMP))
        self.db.execute('''INSERT INTO reception_truck_bl_manifest
            (truck_guide,shipment_id,planned_packages,created_by,created_at,updated_at)
            VALUES ('QA-TRUCK',?,3,'qa',?,?)''',(sid,STAMP,STAMP))
        self.db.execute("UPDATE reception_shipments SET truck_guide='QA-TRUCK',received_packages=10 WHERE id=?",(sid,))
        self.assertEqual(reception_work_report(self.db,now=NOW)['summary']['total'],0)
        waiting = reception_work_report(self.db,view='arrival',now=NOW)['items'][0]
        self.assertTrue(waiting['pending_arrival'])
        self.assertIsNone(waiting['sla_due_at'])

    def test_zero_truck_arrival_does_not_activate_work_or_sla(self):
        sid = self.excel_shipment()
        self.db.execute('''INSERT INTO reception_truck_bl_arrivals
            (truck_guide,shipment_id,received_packages,arrival_key,username,arrived_at)
            VALUES ('QA-TRUCK',?,0,'QA-ZERO','qa',?)''',(sid,STAMP))
        self.assertEqual(reception_work_report(self.db,now=NOW)['items'],[])
        self.assertIsNone(reception.reception_report(self.db)['items'][0]['report_started_at'])

    def test_positive_receipt_with_invalid_date_stays_visible_without_fictional_sla(self):
        sid = self.excel_shipment()
        receipt = self.positive_receipt(sid)
        self.db.execute("UPDATE reception_receipts SET received_at='invalid' WHERE id=?",(receipt,))
        item = reception_work_report(self.db,now=NOW)['items'][0]
        self.assertEqual(item['work_status'],'ARRIBADO')
        self.assertEqual(item['sla_status'],'SIN INICIO')
        self.assertFalse(item['pending_arrival'])
        self.assertEqual(reception.list_receptions(self.db,state='ARRIBADO')[0]['id'],sid)
        self.assertEqual(reception_work_report(self.db,view='arrival',now=NOW)['items'],[])

    def test_invalid_legacy_date_does_not_make_a_false_physical_arrival(self):
        sid = shipment(self.db,status='ARRIBADO',arrival='invalid')
        self.assertEqual(reception.list_receptions(self.db,state='ARRIBADO'),[])
        self.assertEqual(reception.list_receptions(self.db,state='PROGRAMADO')[0]['id'],sid)
        self.assertEqual(reception_work_report(self.db,now=NOW)['items'],[])

    def test_positive_partial_truck_receipt_activates_zone_without_complete_documents(self):
        sid = self.excel_shipment()
        self.db.execute('UPDATE reception_shipments SET expected_packages=5 WHERE id=?',(sid,))
        self.db.execute('''INSERT INTO reception_truck_bl_arrivals
            (truck_guide,shipment_id,received_packages,arrival_key,username,arrived_at)
            VALUES ('QA-TRUCK',?,2,'QA-PARTIAL','qa',?)''',(sid,STAMP))
        work = reception_work_report(self.db,now=NOW)
        self.assertEqual(work['summary']['total'],1)
        self.assertEqual(work['summary']['pending_arrival'],0)
        self.assertEqual(work['items'][0]['work_status'],'ARRIBADO')
        self.assertEqual(work['items'][0]['remaining_hours'],24)
        self.assertEqual(reception_work_report(self.db,view='arrival',now=NOW)['items'],[])
        self.assertEqual(reception.list_receptions(self.db,state='ARRIBADO')[0]['id'],sid)

    def test_read_filters_apply_to_projected_state_before_limit(self):
        for index in range(110):
            self.excel_shipment(bl=f'QA-WAIT-{index}')
        sid = shipment(self.db,bl='QA-REAL')
        self.positive_receipt(sid)
        queued = reception.list_receptions(self.db,state='ARRIBADO',limit=1)
        self.assertEqual([item['id'] for item in queued],[sid])
        waiting = reception_work_report(self.db,view='arrival',offset=100,limit=10,now=NOW)
        self.assertEqual(len(waiting['items']),10)
        self.assertEqual(waiting['summary']['total'],1)
        self.assertEqual(waiting['summary']['pending_arrival'],110)

    def test_closed_excel_historical_bl_is_never_moved_back_to_arrival(self):
        sid = self.excel_shipment(status='CERRADO')
        complete_refs(self.db,sid)
        before = self.db.total_changes
        self.assertEqual(reception_work_report(self.db,view='arrival',now=NOW)['items'],[])
        history = reception_work_report(self.db,view='history',now=NOW)['items'][0]
        self.assertEqual(history['work_status'],'CERRADO')
        self.assertFalse(history['closure_eligible'])
        self.assertEqual(reception.list_receptions(self.db,state='CERRADO')[0]['id'],sid)
        self.assertEqual(reception.reception_report(self.db)['summary']['total_pendientes'],0)
        self.assertEqual(self.db.total_changes,before)

    def test_advanced_attention_without_date_is_preserved_for_review(self):
        sid = self.excel_shipment()
        self.db.execute('''INSERT INTO reception_attentions
            (shipment_id,sequence_no,app_status,current_assistant,created_at,updated_at)
            VALUES (?,1,'UBICACION','worker.test',?,?)''',(sid,STAMP,STAMP))
        work = reception_work_report(self.db,now=NOW)
        self.assertEqual(work['items'][0]['work_status'],'UBICACION')
        self.assertEqual(work['summary']['sla_missing_start'],1)
        self.assertEqual(work['summary']['pending_arrival'],0)

    def test_arrival_view_keeps_assignment_and_role_permissions(self):
        self.excel_shipment()
        assigned = reception_work_report(self.db,username='worker.test',role='ASISTENTE_RECEPCION',view='arrival')
        self.assertEqual(len(assigned['items']),1)
        self.assertEqual(assigned['summary']['total'],0)
        self.assertFalse(assigned['items'][0]['closure_eligible'])
        self.assertEqual(reception_work_report(self.db,username='other',role='ASISTENTE_RECEPCION',view='arrival')['items'],[])
        with self.assertRaises(PermissionError):
            reception_work_report(self.db,role='PICKER',view='arrival')
        with self.assertRaises(ValueError):
            reception_work_report(self.db,view='unknown')


if __name__ == '__main__':
    unittest.main()
