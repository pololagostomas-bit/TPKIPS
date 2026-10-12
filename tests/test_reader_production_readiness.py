"""Synthetic production guards and bounded read paths, never production data."""
import sqlite3
import unittest
from unittest.mock import patch

from openpyxl import Workbook
from backend.services import reception
from backend.services.reception_work import reception_work_report
from backend.services.traceability import init_traceability_schema

STAMP = '2026-09-25 08:00:00'


class ReaderProductionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        reception.init_reception_schema(self.db)
        init_traceability_schema(self.db)

    def shipment(self, index, status='PROGRAMADO'):
        return self.db.execute('''INSERT INTO reception_shipments
            (bl_awb,app_status,ip_reference,transport_type,created_at,updated_at)
            VALUES (?,?,'IP-1','AEREO',?,?)''',
            (f'QA-{index:04}',status,STAMP,STAMP)).lastrowid

    def test_closure_checks_only_visible_page_and_not_worker_rows(self):
        for index in range(250):
            self.shipment(index)
        before=self.db.total_changes
        with patch('backend.services.reception_work.closure_check',return_value=(False,'QA')) as check:
            page=reception_work_report(self.db,limit=25,offset=25,now=STAMP,view='arrival')
            self.assertEqual(check.call_count,25)
            self.assertEqual(page['summary']['total'],0)
            self.assertEqual(page['summary']['pending_arrival'],250)
            self.assertEqual(page['total'],250)
            self.assertEqual(len(page['items']),25)
        self.assertEqual(self.db.total_changes,before)
        with patch('backend.services.reception_work.closure_check') as check:
            page=reception_work_report(self.db,role='ASISTENTE_RECEPCION',username='qa.worker',now=STAMP)
            self.assertEqual(page['items'],[])
            check.assert_not_called()

    def test_report_pagination_keeps_full_totals_and_all_pages(self):
        for index in range(125):
            self.shipment(index)
        pages=[reception.reception_report(self.db,limit=50,offset=offset) for offset in (0,50,100)]
        self.assertEqual([len(page['items']) for page in pages],[50,50,25])
        self.assertEqual([page['has_more'] for page in pages],[True,True,False])
        self.assertTrue(all(page['total']==125 and page['summary']['total_bl']==125 for page in pages))
        self.assertEqual(len({item['id'] for page in pages for item in page['items']}),125)
        self.assertEqual(len(reception.reception_report(self.db)['items']),125)
        with self.assertRaises(PermissionError):
            reception.reception_report(self.db,role='ASISTENTE_RECEPCION',limit=50)

    def test_report_filters_run_before_paging(self):
        for index in range(105):
            sid=self.shipment(index)
            if index<55:
                self.db.execute('UPDATE reception_shipments SET first_arrival_at=? WHERE id=?',(STAMP,sid))
        result=reception.reception_report(self.db,limit=50,arrival='ARRIBADO',offset=50)
        self.assertEqual(result['total'],55)
        self.assertEqual(len(result['items']),5)
        self.assertTrue(all(item['report_started_at'] for item in result['items']))
        self.assertEqual(reception.reception_report(self.db,limit=50,date_from='2027-01-01')['items'],[])
        self.assertEqual(reception.reception_report(self.db,limit=50,sla='SIN INICIO',arrival='PROGRAMADO')['total'],50)
        self.assertEqual(reception.reception_report(self.db,limit=50,sla='AMARILLO',arrival='PROGRAMADO')['total'],0)
        for options in ({'limit':'bad'},{'limit':50,'date_from':'bad'},{'limit':50,'sla':'bad'}):
            with self.assertRaises(ValueError):
                reception.reception_report(self.db,**options)

    def test_closed_history_without_trucks_does_not_reopen_or_reset_quantities(self):
        sid=self.shipment(0,'CERRADO')
        self.db.execute("UPDATE reception_shipments SET condition_status='COMPLETADO',fr_number='FR-1',em_number='EM-1' WHERE id=?",(sid,))
        line=self.db.execute("INSERT INTO reception_lines(shipment_id,np_code,ip_reference,expected_qty,received_qty) VALUES (?,'QA-NP','IP-1',8,0)",(sid,)).lastrowid
        ref=self.db.execute('''INSERT INTO reception_accounting_refs
            (shipment_id,source_key,ip_reference,fr_number,em_number,created_at,updated_at)
            VALUES (?,'QA-REF','IP-1','FR-1','EM-1',?,?)''',(sid,STAMP,STAMP)).lastrowid
        self.db.execute("INSERT INTO reception_accounting_ems(accounting_ref_id,em_number,username,created_at) VALUES (?,'EM-1','qa',?)",(ref,STAMP))
        reception._refresh_accounting_summary(self.db,sid,'qa.admin','qa.xlsx')
        self.assertEqual(self.db.execute('SELECT received_qty FROM reception_lines WHERE id=?',(line,)).fetchone()[0],0)
        self.db.execute('DELETE FROM reception_accounting_ems WHERE accounting_ref_id=?',(ref,))
        self.db.execute('UPDATE reception_accounting_refs SET em_number=NULL WHERE id=?',(ref,))
        reception._refresh_accounting_summary(self.db,sid,'qa.admin','qa.xlsx')
        master=self.db.execute('SELECT app_status,condition_status,accounting_status,truck_guide FROM reception_shipments WHERE id=?',(sid,)).fetchone()
        self.assertEqual(tuple(master),('CERRADO','COMPLETADO','PENDIENTE EM',None))
        work=reception_work_report(self.db,now=STAMP)
        self.assertEqual(work['items'],[])
        self.assertEqual(work['summary']['total'],0)
        historical=reception_work_report(self.db,include_history=True,now=STAMP)['items'][0]
        self.assertEqual(historical['work_status'],'CERRADO')
        self.assertFalse(historical['closure_eligible'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_receipts').fetchone()[0],0)

    def test_manual_excel_import_never_generates_demo_trucks(self):
        book=Workbook();self.addCleanup(book.close)
        sheet=book.active;sheet.title='SUSANA'
        sheet.append(['TIPO DE COMPRA','CODIGO','DESCRIPCION','CANTIDAD SOLICITADA',
                      'CANTIDAD FACTURADA','CANTIDAD PENDIENTE','PEDIDO TRITON',
                      'GUIA DE IMPORTACION','FECHA TRITON ESTIMADA'])
        sheet.append(['AEREO','QA-NP','QA repuesto',3,0,3,'IP-1','QA-IMPORT', '2026-09-25'])
        with patch.object(reception,'assign_demo_truck_guides') as seed:
            result=reception.import_reception_workbook(self.db,book,'qa.xlsx','qa.admin','ADMINISTRADOR')
            seed.assert_not_called()
        self.assertEqual(result['shipments_created'],1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_truck_guides').fetchone()[0],0)

    def test_archived_scan_keeps_trace_without_hiding_future_scans(self):
        sid=self.shipment(0)
        with patch.object(reception,'reception_now',return_value=STAMP):
            old=reception.create_scanner_truck_guide(self.db,'qa.admin','ADMINISTRADOR')['truck_guide']
            self.db.execute("UPDATE reception_truck_guides SET guide_status='CANCELADA',archived_at=?,scanner_enabled=0 WHERE guide_code=?",(STAMP,old))
            arrival=self.db.execute('''INSERT INTO reception_truck_bl_arrivals
                (truck_guide,shipment_id,received_packages,arrival_key,username,arrived_at)
                VALUES (?,?,2,'QA-ARRIVAL','qa.admin',?)''',(old,sid,STAMP)).lastrowid
            self.db.execute('''INSERT INTO reception_truck_bl_locations
                (arrival_id,location_text,package_count,username,created_at,updated_at)
                VALUES (?,'QA-A-01',2,'qa.admin',?,?)''',(arrival,STAMP,STAMP))
            new=reception.create_scanner_truck_guide(self.db,'qa.admin','ADMINISTRADOR')['truck_guide']
        self.assertNotEqual(old,new)
        self.assertTrue(new.endswith('-02'))
        listed=reception.list_truck_guides(self.db,include_completed=True)
        self.assertEqual([item['truck_guide'] for item in listed],[new])
        trace=reception.list_truck_bl_arrival_locations(self.db,sid)
        self.assertEqual(len(trace),1)
        self.assertTrue(trace[0]['truck_archived'])
        self.assertEqual(trace[0]['package_count'],2)
        self.assertEqual(trace[0]['location'],'QA-A-01')

    def test_closed_detail_is_read_only_with_missing_or_saved_sample(self):
        sid=self.shipment(0,'CERRADO')
        line=self.db.execute("INSERT INTO reception_lines(shipment_id,np_code,expected_qty,received_qty) VALUES (?,'QA-NP',8,8)",(sid,)).lastrowid
        self.db.execute('CREATE TABLE order_importation_refs(sap_ov TEXT,transport_type TEXT,bl_awb TEXT)')
        for saved,expected in ((None,[]),(f'[{line}]',[line]),('invalid',[])):
            self.db.execute('UPDATE reception_shipments SET validation_sample_json=? WHERE id=?',(saved,sid))
            before=self.db.total_changes
            self.db.execute('PRAGMA query_only=ON')
            try:
                with patch.object(reception,'global_stock_summary',return_value={}):
                    detail=reception.reception_detail(self.db,sid)
            finally:
                self.db.execute('PRAGMA query_only=OFF')
            self.assertEqual(detail['app_status'],'CERRADO')
            self.assertEqual(detail['validation_sample_ids'],expected)
            self.assertEqual(self.db.total_changes,before)
            self.assertEqual(self.db.execute('SELECT validation_location_checked FROM reception_lines WHERE id=?',(line,)).fetchone()[0],0)

    def test_query_indexes_are_idempotent_and_used_for_shipment_reads(self):
        reception.init_reception_schema(self.db)
        plans=[str(tuple(row)) for row in self.db.execute('EXPLAIN QUERY PLAN SELECT ip_reference FROM reception_lines WHERE shipment_id=1')]
        self.assertTrue(any('idx_reception_lines_shipment' in plan for plan in plans))


if __name__ == '__main__':
    unittest.main()
