"""Partial BL KPI: distinct real trucks, filtered before pagination. Synthetic only."""
from io import BytesIO
import sqlite3
import unittest
from openpyxl import load_workbook
from backend.services import reception,reception_report_export

STAMP='2026-10-01 08:00:00'


class PartialReportTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.addCleanup(self.db.close);reception.init_reception_schema(self.db)

    def shipment(self,name,status='ARRIBADO',transport='AEREO'):
        return self.db.execute('''INSERT INTO reception_shipments
            (bl_awb,app_status,transport_type,created_at,updated_at)
            VALUES (?,?,?,?,?)''',(name,status,transport,STAMP,STAMP)).lastrowid

    def arrival(self,sid,guide,quantity=1,*,receipt=True,canonical=True,
                status='ARRIBADO',archived='',annulled=False):
        self.db.execute('''INSERT OR IGNORE INTO reception_truck_guides
            (guide_code,guide_status,created_by,created_at,updated_at,archived_at)
            VALUES (?,?,?,?,?,?)''',(guide,status,'qa',STAMP,STAMP,archived))
        if canonical:self.db.execute('''INSERT INTO reception_truck_bl_arrivals
            (truck_guide,shipment_id,received_packages,arrival_key,username,arrived_at)
            VALUES (?,?,?,?,?,?)''',(guide,sid,quantity,f'{sid}:{guide}','qa',STAMP))
        if receipt:
            seq=self.db.execute('SELECT count(*)+1 FROM reception_receipts WHERE shipment_id=?',(sid,)).fetchone()[0]
            rid=self.db.execute('''INSERT INTO reception_receipts
                (shipment_id,sequence_no,received_packages,username,received_at,truck_guide)
                VALUES (?,?,?,?,?,?)''',(sid,seq,quantity,'qa',STAMP,guide)).lastrowid
            if annulled:self.db.execute('''INSERT INTO reception_attentions
                (shipment_id,receipt_id,sequence_no,condition_status,created_at,updated_at)
                VALUES (?,?,?,'ANULADA PRUEBA',?,?)''',(sid,rid,seq,STAMP,STAMP))

    def test_two_or_more_trucks_on_same_day_count_one_partial_bl_read_only(self):
        one=self.shipment('QA-ONE');self.arrival(one,'G1')
        two=self.shipment('QA-TWO');self.arrival(two,'G2');self.arrival(two,'G3')
        three=self.shipment('QA-THREE');self.arrival(three,'G4');self.arrival(three,'G5');self.arrival(three,'G6')
        before=self.db.total_changes
        report=reception.reception_report(self.db)
        self.assertEqual(report['filtered_summary']['partial_bl'],2)
        counts={item['bl_awb']:item['delivery_count'] for item in report['items']}
        self.assertEqual(counts,{'QA-ONE':1,'QA-TWO':2,'QA-THREE':3})
        self.assertEqual(self.db.total_changes,before)

    def test_planned_zero_cancelled_archived_and_annulled_arrivals_do_not_count(self):
        sid=self.shipment('QA-EXCLUDE');self.arrival(sid,'VALID')
        self.arrival(sid,'ZERO',0);self.arrival(sid,'CANCEL',status='CANCELADA')
        self.arrival(sid,'PILOT',archived=STAMP);self.arrival(sid,'VOID',annulled=True)
        self.db.execute('''INSERT INTO reception_truck_bl_manifest
            (shipment_id,truck_guide,planned_packages,created_by,created_at,updated_at)
            VALUES (?,'PLANNED',10,'qa',?,?)''',(sid,STAMP,STAMP))
        report=reception.reception_report(self.db)
        self.assertEqual(report['items'][0]['delivery_count'],1)
        self.assertEqual(report['filtered_summary']['partial_bl'],0)

    def test_receipt_and_arrival_are_the_same_delivery_not_two(self):
        sid=self.shipment('QA-UNION');self.arrival(sid,'GUIDE-ONE')
        self.db.execute("UPDATE reception_receipts SET truck_guide=' guide-one ' WHERE shipment_id=?",(sid,))
        self.assertEqual(reception.reception_report(self.db)['items'][0]['delivery_count'],1)

    def test_legacy_receipt_needs_known_truck_and_dates_alone_do_not_invent_delivery(self):
        sid=self.shipment('QA-LEGACY');self.arrival(sid,'KNOWN',canonical=False)
        self.db.executemany('''INSERT INTO reception_receipts
            (shipment_id,sequence_no,received_packages,username,received_at)
            VALUES (?,?,1,'qa',?)''',[(sid,2,'2026-10-02'),(sid,3,'2026-10-03')])
        report=reception.reception_report(self.db)
        self.assertEqual(report['items'][0]['delivery_count'],1)
        self.assertEqual(report['filtered_summary']['partial_bl'],0)

    def test_partial_kpi_uses_all_filtered_matches_before_paging(self):
        for index in range(65):
            sid=self.shipment(f'QA-{index:03}')
            self.arrival(sid,f'FIRST-{index}')
            if index>=63:self.arrival(sid,f'SECOND-{index}')
        first=reception.reception_report(self.db,limit=50,sort='bl_awb')
        second=reception.reception_report(self.db,limit=50,offset=50,sort='bl_awb')
        self.assertEqual(first['filtered_summary']['partial_bl'],2)
        self.assertEqual(second['filtered_summary']['partial_bl'],2)
        self.assertEqual(sum(item['delivery_count']>=2 for item in first['items']),0)
        full=reception.reception_report(self.db)
        self.assertEqual(reception.filter_reception_report(full,search='QA-064')['filtered_summary']['partial_bl'],1)
        self.assertEqual(reception.filter_reception_report(full,search='QA-000')['filtered_summary']['partial_bl'],0)
        self.assertEqual(full['summary']['total_bl'],65)

    def test_old_cached_cut_without_delivery_evidence_is_unknown_not_false_zero(self):
        self.shipment('QA-OLD')
        report=reception.reception_report(self.db)
        for item in report['items']:item.pop('delivery_count',None)
        self.assertIsNone(reception.filter_reception_report(report)['filtered_summary']['partial_bl'])

    def test_existing_date_status_transport_arrival_and_sla_filters_control_kpi(self):
        closed=self.shipment('QA-CLOSED','CERRADO','MARITIMO')
        opened=self.shipment('QA-OPEN','EM','AEREO')
        for sid,prefix in ((closed,'C'),(opened,'O')):
            self.arrival(sid,prefix+'1');self.arrival(sid,prefix+'2')
        report=reception.reception_report(self.db)
        sla=next(item['sla_status'] for item in report['items'] if item['id']==closed)
        for options,want in (({'state':'CERRADO'},1),({'state':'OPEN'},1),({'transport':'MARITIMO'},1),
                             ({'arrival':'PROGRAMADO'},0),({'date_from':'2026-11-01'},0),
                             ({'date_to':'2026-09-30'},0),({'sla':sla,'search':'QA-CLOSED'},1)):
            with self.subTest(options=options):
                self.assertEqual(reception.filter_reception_report(report,**options)['filtered_summary']['partial_bl'],want)

    def test_filtered_excel_summary_and_delivery_column_match_dashboard(self):
        sid=self.shipment('QA-EXPORT');self.arrival(sid,'EX1');self.arrival(sid,'EX2')
        self.shipment('QA-OTHER')
        book=load_workbook(BytesIO(reception_report_export.build(self.db,{'search':'QA-EXPORT'})),read_only=True)
        try:
            summary=dict(row[:2] for row in book['Resumen'].values if len(row)>=2)
            self.assertEqual(summary['BL parciales (segun filtros)'],1)
            rows=list(book['Indicadores BL'].values)
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[1][rows[0].index('Entregas')],2)
        finally:book.close()
