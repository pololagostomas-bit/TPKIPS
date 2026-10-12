import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.services import reception
from backend.services.reception_work import reception_work_report, _deadline

STAMP = '2026-09-25 08:00:00'
NOW = '2026-09-28 08:00:00'


def shipment(db, bl='TEST-BL', status='PROGRAMADO', arrival=None, ips='IP-101, IP-102, IP-103'):
    return db.execute('''INSERT INTO reception_shipments
        (bl_awb,app_status,ip_reference,current_assistant,current_auxiliary,
         first_arrival_at,created_at,updated_at)
        VALUES (?,?,?,'worker.test','aux.test',?,?,?)''',
        (bl,status,ips,arrival,STAMP,STAMP)).lastrowid


def complete_refs(db, sid, count=3):
    for i in range(count):
        reference=db.execute('''INSERT INTO reception_accounting_refs
            (shipment_id,source_key,ip_reference,fr_number,em_number,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?)''', (sid,f'{sid}-REF-{i}',f'IP-{101+i}',f'FR-{i}',f'EM-{i}',STAMP,STAMP)).lastrowid
        db.execute('''INSERT INTO reception_accounting_ems
            (accounting_ref_id,ip_reference_key,em_number,username,created_at)
            VALUES (?,?,?,'system.test',?)''',(reference,next(iter(reception._ip_tokens(f'IP-{101+i}'))),f'EM-{i}',STAMP))


class ReceptionWorkTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.row_factory=sqlite3.Row
        reception.init_reception_schema(self.db)

    def tearDown(self):
        self.db.close()

    def report(self, **options):
        options.setdefault('now',NOW)
        return reception_work_report(self.db,**options)

    def test_complete_refs_without_receipt_stay_in_arrival_not_history_or_work(self):
        sid=shipment(self.db)
        complete_refs(self.db,sid)
        before=self.db.total_changes
        report=self.report()
        self.assertEqual(report['items'],[])
        self.assertEqual(report['summary']['total'],0)
        self.assertEqual(report['summary']['pending_arrival'],1)
        self.assertEqual(report['summary']['documentary_complete_count'],1)
        self.assertEqual(self.report(view='history')['items'],[])
        item=self.report(view='arrival')['items'][0]
        self.assertEqual(item['work_status'],'PROGRAMADO')
        self.assertEqual(item['app_status'],'PROGRAMADO')
        self.assertEqual(item['sla_status'],'SIN INICIO')
        self.assertFalse(item['work_pending'])
        self.assertTrue(item['documentary_complete'])
        self.assertIsNone(item['work_started_at'])
        self.assertEqual(self.db.total_changes,before)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_receipts').fetchone()[0],0)

    def test_partial_documentation_does_not_disappear_based_on_received_ips(self):
        sid=shipment(self.db)
        complete_refs(self.db,sid,1)
        self.db.execute('INSERT INTO reception_lines(shipment_id,np_code,ip_reference,expected_qty,received_qty) VALUES (?,?,?,?,?)',
                        (sid,'NP-1','IP-101',1,1))
        self.db.execute('INSERT INTO reception_lines(shipment_id,np_code,ip_reference,expected_qty) VALUES (?,?,?,?)',
                        (sid,'NP-2','IP-102',1))
        self.assertEqual(reception._accounting_status_for_shipment(self.db,sid),'EM REGISTRADA')
        self.assertEqual(self.report()['items'],[])
        item=self.report(view='arrival')['items'][0]
        self.assertFalse(item['documentary_complete'])
        self.assertFalse(item['work_pending'])

    def test_missing_em_or_conflict_keeps_pending_arrival(self):
        sid=shipment(self.db)
        complete_refs(self.db,sid)
        self.db.execute('UPDATE reception_accounting_refs SET em_number=NULL WHERE shipment_id=? AND ip_reference=?',(sid,'IP-103'))
        self.db.execute('DELETE FROM reception_accounting_ems WHERE accounting_ref_id IN (SELECT id FROM reception_accounting_refs WHERE shipment_id=? AND ip_reference=?)',(sid,'IP-103'))
        self.assertEqual(self.report(view='arrival')['items'][0]['accounting_status'],'PENDIENTE EM')
        self.db.execute('UPDATE reception_shipments SET accounting_conflict_count=1 WHERE id=?',(sid,))
        self.assertEqual(self.report(view='arrival')['items'][0]['accounting_status'],'CONFLICTO IP')
        self.assertEqual(self.report()['items'],[])

    def test_existing_wms_receipt_keeps_documented_bl_in_work(self):
        sid=shipment(self.db,arrival=STAMP)
        complete_refs(self.db,sid)
        item=self.report()['items'][0]
        self.assertEqual(item['work_status'],'ARRIBADO')
        self.assertFalse(item['pending_arrival'])
        self.assertEqual(item['remaining_hours'],24)

    def test_advanced_state_without_date_is_not_pending_arrival(self):
        sid=shipment(self.db,status='UBICACION')
        complete_refs(self.db,sid)
        item=self.report()['items'][0]
        self.assertEqual(item['work_status'],'UBICACION')
        self.assertFalse(item['pending_arrival'])
        self.assertEqual(item['sla_status'],'SIN INICIO')
        self.assertEqual(self.report()['summary']['sla_missing_start'],1)

    def test_arrived_label_without_physical_evidence_is_waiting_for_arrival(self):
        sid=shipment(self.db,status='ARRIBADO')
        complete_refs(self.db,sid)
        self.assertEqual(self.report()['items'],[])
        self.assertEqual(self.report(view='arrival')['items'][0]['work_status'],'PROGRAMADO')
        self.assertEqual(self.db.execute('SELECT app_status FROM reception_shipments WHERE id=?',(sid,)).fetchone()[0],'ARRIBADO')

    def test_import_date_does_not_start_sla(self):
        sid=shipment(self.db)
        self.db.execute('UPDATE reception_shipments SET source_reception_date=?,em_date=? WHERE id=?',(STAMP,STAMP,sid))
        item=self.report(view='arrival')['items'][0]
        self.assertIsNone(item['work_started_at'])
        self.assertIsNone(item['sla_due_at'])

    def test_excel_inherited_arrival_is_not_worker_sla_or_documented_pending(self):
        sid=shipment(self.db,status='ARRIBADO',arrival=STAMP)
        self.db.execute('''INSERT INTO reception_history
            (shipment_id,event_type,field_name,new_value,username,created_at)
            VALUES (?,'IMPORTACION EXCEL','app_status','ARRIBADO','system.test',?)''',(sid,STAMP))
        self.assertEqual(self.report()['items'],[])
        item=self.report(view='arrival')['items'][0]
        self.assertEqual(item['work_status'],'PROGRAMADO')
        self.assertEqual(item['sla_status'],'SIN INICIO')
        self.assertIsNone(item['work_started_at'])
        self.assertEqual(self.report()['summary']['sla_overdue'],0)
        self.assertIn('camion',item['work_reason'])
        complete_refs(self.db,sid)
        self.assertEqual(self.report()['items'],[])
        self.assertEqual(self.report(view='arrival')['items'][0]['work_status'],'PROGRAMADO')
        self.assertEqual(self.report(view='history')['items'],[])

    def test_actual_receipt_overrides_excel_date_without_ignoring_live_work(self):
        sid=shipment(self.db,status='ARRIBADO',arrival='2020-01-01 08:00:00')
        self.db.execute('''INSERT INTO reception_history
            (shipment_id,event_type,field_name,new_value,username,created_at)
            VALUES (?,'IMPORTACION EXCEL','app_status','ARRIBADO','system.test',?)''',(sid,STAMP))
        self.db.execute('''INSERT INTO reception_receipts
            (shipment_id,sequence_no,received_packages,username,received_at)
            VALUES (?,1,1,'worker.test',?)''',(sid,STAMP))
        complete_refs(self.db,sid)
        self.assertEqual(self.report()['items'][0]['work_started_at'],'2026-09-25T08:00:00')
        self.assertTrue(self.report()['items'][0]['work_pending'])

    def test_positive_receipt_backfills_view_only_not_shipment(self):
        sid=shipment(self.db)
        self.db.execute('''INSERT INTO reception_receipts
            (shipment_id,sequence_no,received_packages,username,received_at)
            VALUES (?,1,2,'worker.test',?)''',(sid,STAMP))
        item=self.report()['items'][0]
        self.assertEqual(item['work_started_at'],'2026-09-25T08:00:00')
        self.assertEqual(item['work_status'],'ARRIBADO')
        self.assertIsNone(self.db.execute('SELECT first_arrival_at FROM reception_shipments WHERE id=?',(sid,)).fetchone()[0])

    def test_zero_package_receipt_does_not_start_sla(self):
        sid=shipment(self.db)
        self.db.execute('''INSERT INTO reception_receipts
            (shipment_id,sequence_no,received_packages,username,received_at)
            VALUES (?,1,0,'worker.test',?)''',(sid,STAMP))
        self.assertIsNone(self.report(view='arrival')['items'][0]['work_started_at'])
        self.assertEqual(self.report()['summary']['total'],0)

    def test_multi_arrival_count_is_distinct_and_workers_see_only_their_attention(self):
        sid=shipment(self.db,status='CERRADO',arrival=STAMP)
        for sequence,owner in [(1,'other.worker'),(2,'worker.test')]:
            receipt=self.db.execute('''INSERT INTO reception_receipts
                (shipment_id,sequence_no,received_packages,username,received_at)
                VALUES (?,?,1,?,?)''',(sid,sequence,owner,f'2026-09-{24+sequence} 08:00:00')).lastrowid
            self.db.execute('''INSERT INTO reception_attentions
                (shipment_id,sequence_no,receipt_id,app_status,current_assistant,created_at,updated_at)
                VALUES (?,?,?,'UBICACION',?,?,?)''',(sid,sequence,receipt,owner,STAMP,STAMP))
        report=self.report()
        self.assertEqual(len(report['items']),2)
        self.assertEqual(report['summary']['total'],1)
        self.assertEqual(sum(report['summary']['by_status'].values()),1)
        self.assertEqual(report['summary']['open_attentions'],2)
        own=self.report(username='worker.test',role='ASISTENTE_RECEPCION')
        self.assertEqual(len(own['items']),1)
        self.assertEqual(own['items'][0]['attention_sequence'],2)
        self.assertEqual(own['items'][0]['work_started_at'],'2026-09-26T08:00:00')
        self.assertEqual(self.report(username='stranger',role='ASISTENTE_RECEPCION')['items'],[])

    def test_no_identity_and_other_roles_cannot_query_reception_work(self):
        with self.assertRaises(PermissionError):
            self.report(role='ASISTENTE_RECEPCION')
        with self.assertRaises(PermissionError):
            self.report(username='picker',role='PICKER')

    def test_zero_package_attention_does_not_start_sla(self):
        sid=shipment(self.db)
        receipt=self.db.execute('''INSERT INTO reception_receipts
            (shipment_id,sequence_no,received_packages,username,received_at)
            VALUES (?,1,0,'worker.test',?)''',(sid,STAMP)).lastrowid
        self.db.execute('''INSERT INTO reception_attentions
            (shipment_id,sequence_no,receipt_id,app_status,created_at,updated_at)
            VALUES (?,1,?,'PROGRAMADO',?,?)''',(sid,receipt,STAMP,STAMP))
        self.assertIsNone(self.report(view='arrival')['items'][0]['work_started_at'])
        self.assertEqual(self.report()['summary']['total'],0)

    def test_closed_attentions_with_open_master_need_reconciliation_not_a_false_timer(self):
        sid=shipment(self.db,status='UBICACION',arrival=STAMP)
        self.db.execute('''INSERT INTO reception_attentions
            (shipment_id,sequence_no,app_status,completed_at,created_at,updated_at)
            VALUES (?,1,'CERRADO',?,?,?)''',(sid,NOW,STAMP,NOW))
        item=self.report()['items'][0]
        self.assertIsNone(item['attention_id'])
        self.assertEqual(item['sla_status'],'SIN INICIO')
        self.assertIn('revisar saldo',item['work_reason'])
        self.assertEqual(self.report()['summary']['open_attentions'],0)

    def test_worst_partial_sla_counts_bl_once_in_urgency_metrics(self):
        sid=shipment(self.db,arrival=STAMP)
        for sequence,date in [(1,STAMP),(2,'2026-09-25 20:00:00')]:
            receipt=self.db.execute('''INSERT INTO reception_receipts
                (shipment_id,sequence_no,received_packages,username,received_at)
                VALUES (?,?,1,'worker.test',?)''',(sid,sequence,date)).lastrowid
            self.db.execute('''INSERT INTO reception_attentions
                (shipment_id,sequence_no,receipt_id,app_status,created_at,updated_at)
                VALUES (?,?,?,'UBICACION',?,?)''',(sid,sequence,receipt,STAMP,STAMP))
        report=self.report(now='2026-09-29 10:00:00')
        self.assertEqual({item['sla_status'] for item in report['items']},{'ROJO','AMARILLO'})
        self.assertEqual(report['summary']['sla_overdue'],1)
        self.assertEqual(report['summary']['sla_at_risk'],0)
        self.assertEqual(self.report(now='2026-09-29 10:00:00',sla='AMARILLO')['items'],[])

    def test_closed_attention_is_not_in_active_work(self):
        sid=shipment(self.db,status='CERRADO',arrival=STAMP)
        self.db.execute('''INSERT INTO reception_attentions
            (shipment_id,sequence_no,app_status,completed_at,created_at,updated_at)
            VALUES (?,1,'CERRADO',?,?,?)''',(sid,NOW,STAMP,NOW))
        self.assertEqual(self.report()['items'],[])
        item=self.report(include_history=True)['items'][0]
        self.assertEqual(item['sla_status'],'FINALIZADO')
        self.assertEqual(item['elapsed_hours'],48)

    def test_closed_without_finish_does_not_keep_accumulating_time(self):
        shipment(self.db,status='CERRADO',arrival=STAMP)
        self.assertIsNone(self.report(include_history=True)['items'][0]['elapsed_hours'])

    def test_deadline_and_remaining_exclude_sunday_and_normalize_utc(self):
        shipment(self.db,status='UBICACION',arrival='2026-09-25T13:00:00Z')
        item=self.report()['items'][0]
        self.assertEqual(item['remaining_hours'],24)
        self.assertEqual(item['sla_due_at'],'2026-09-29T08:00:00')
        self.assertEqual(_deadline('2026-09-26 12:00:00',72),'2026-09-30T12:00:00')

    def test_sea_sla_and_warning_threshold(self):
        sid=shipment(self.db,status='UBICACION',arrival=STAMP)
        self.db.execute("UPDATE reception_shipments SET transport_type='MARITIMO' WHERE id=?",(sid,))
        item=self.report()['items'][0]
        self.assertEqual(item['sla_hours'],96)
        self.assertEqual(item['remaining_hours'],48)
        self.db.execute("UPDATE reception_shipments SET transport_type='AEREO' WHERE id=?",(sid,))
        item=self.report(now='2026-09-28 20:00:00')['items'][0]
        self.assertEqual(item['sla_status'],'AMARILLO')
        self.assertEqual(item['remaining_hours'],12)
        self.assertEqual(self.report(now='2026-09-29 08:01:00')['items'][0]['sla_status'],'ROJO')

    def test_future_physical_date_does_not_create_false_remaining_hours(self):
        shipment(self.db,status='UBICACION',arrival='2027-01-01 10:00:00')
        item=self.report()['items'][0]
        self.assertIsNone(item['remaining_hours'])
        self.assertIsNone(item['sla_due_at'])

    def test_filters_precede_bounded_pagination_and_totals_use_entire_workload(self):
        for i in range(105):
            shipment(self.db,bl=f'TEST-PAGE-{i:03d}',ips='')
        first=self.report(limit=9999,view='arrival')
        self.assertEqual(len(first['items']),100)
        self.assertEqual(first['summary']['total'],0)
        self.assertEqual(first['summary']['pending_arrival'],105)
        self.assertTrue(first['has_more'])
        self.assertEqual(len(self.report(offset=100,view='arrival')['items']),5)
        result=self.report(search='104',view='arrival')
        self.assertEqual(len(result['items']),1)
        self.assertEqual(result['summary']['total'],0)
        self.assertEqual(result['summary']['pending_arrival'],105)


def serve():
    from backend import app
    from http.server import ThreadingHTTPServer
    handle,name=tempfile.mkstemp(prefix='wms-work-qa-',suffix='.db')
    os.close(handle)
    app.DB_PATH=Path(name)
    os.environ['TRITON_AUTH_MODE']='demo'
    app.init_db()
    with app.db() as db:
        sid=shipment(db,bl='TEST-DOCUMENTED')
        complete_refs(db,sid)
        shipment(db,bl='TEST-HISTORY',status='CERRADO',ips='')
        for i in range(212):
            arrival=STAMP if i<106 else None
            shipment(db,bl=f'TEST-WORK-{i:03d}',status='UBICACION' if arrival else 'PROGRAMADO',arrival=arrival,ips='')
    server=ThreadingHTTPServer((os.environ.get('WMS_QA_BIND','127.0.0.1'),
                               int(os.environ.get('WMS_QA_PORT','0'))),app.Handler)
    print('QA_URL='+f'http://127.0.0.1:{server.server_port}',flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        for suffix in ('','-wal','-shm'):
            Path(name+suffix).unlink(missing_ok=True)


if __name__=='__main__':
    import sys
    if '--serve' in sys.argv:
        serve()
    else:
        unittest.main()
