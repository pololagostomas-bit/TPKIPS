"""Filtered SLA cards reuse the row classification; no clock or rule changes."""
from io import BytesIO
import unittest
from unittest.mock import patch
from openpyxl import load_workbook
from backend.services import reception,reception_report_export
from tests import test_reception_partial_report as fixtures


class SlaKpiTests(unittest.TestCase):
    setUp=fixtures.PartialReportTests.setUp
    shipment=fixtures.PartialReportTests.shipment

    def report(self):
        for name,stamp in [('RED','2026-10-19 08:00:00'),('YELLOW','2026-10-19 20:00:00'),
                           ('GREEN','2026-10-22 08:00:00')]:
            sid=self.shipment('QA-'+name)
            self.db.execute('''INSERT INTO reception_receipts
                (shipment_id,sequence_no,received_packages,username,received_at)
                VALUES (?,1,1,'qa',?)''',(sid,stamp))
        self.shipment('QA-NO-START','PROGRAMADO')
        with patch.object(reception,'reception_now',return_value='2026-10-22 12:00:00'):
            return reception.reception_report(self.db)

    def test_cards_match_actual_row_sla_and_exclude_no_start(self):
        report=self.report()
        self.assertEqual({row['bl_awb']:row['sla_status'] for row in report['items']},
                         {'QA-RED':'ROJO','QA-YELLOW':'AMARILLO','QA-GREEN':'VERDE','QA-NO-START':'SIN INICIO'})
        self.assertEqual(report['filtered_summary']['semaforizacion'],{'ROJO':1,'AMARILLO':1,'VERDE':1})

    def test_search_and_sla_filters_recompute_counts_instead_of_using_global_totals(self):
        report=self.report()
        for options,want in (({'search':'QA-RED'},{'ROJO':1,'AMARILLO':0,'VERDE':0}),
                             ({'sla':'AMARILLO'},{'ROJO':0,'AMARILLO':1,'VERDE':0}),
                             ({'arrival':'PROGRAMADO'},{'ROJO':0,'AMARILLO':0,'VERDE':0}),
                             ({'transport':'MARITIMO'},{'ROJO':0,'AMARILLO':0,'VERDE':0}),
                             ({'date_to':'2026-10-18'},{'ROJO':0,'AMARILLO':0,'VERDE':0}),
                             ({'state':'CERRADO'},{'ROJO':0,'AMARILLO':0,'VERDE':0})):
            with self.subTest(options=options):
                filtered=reception.filter_reception_report(report,**options)
                self.assertEqual(filtered['filtered_summary']['semaforizacion'],want)
        self.assertEqual(report['summary']['semaforizacion'],{'ROJO':1,'AMARILLO':1,'VERDE':1})

    def test_sla_counts_cover_every_filtered_bl_before_pagination(self):
        template=self.report()['items'][0]
        report={'items':[{**template,'id':index,'bl_awb':f'QA-{index:03}',
                 'sla_status':'ROJO' if index>=63 else 'AMARILLO' if index>=60 else 'VERDE'} for index in range(65)]}
        for offset in (0,50):
            page=reception.filter_reception_report(report,limit=50,offset=offset,sort='bl_awb')
            self.assertEqual(page['filtered_summary']['semaforizacion'],{'ROJO':2,'AMARILLO':3,'VERDE':60})

    def test_empty_result_has_zero_counts_and_does_not_mutate_input(self):
        report=self.report();before=self.db.total_changes
        result=reception.filter_reception_report(report,search='MISSING')
        self.assertEqual(result['filtered_summary']['semaforizacion'],{'ROJO':0,'AMARILLO':0,'VERDE':0})
        self.assertEqual(len(report['items']),4)
        self.assertEqual(self.db.total_changes,before)

    def test_closed_late_bl_keeps_frozen_red_sla_in_closed_filter(self):
        self.report()
        self.db.execute("UPDATE reception_shipments SET app_status='CERRADO',updated_at='2026-10-22 12:00:00' WHERE bl_awb='QA-RED'")
        with patch.object(reception,'reception_now',return_value='2026-11-01 12:00:00'):
            report=reception.reception_report(self.db,limit=50,state='CERRADO')
        self.assertEqual(report['filtered_summary']['semaforizacion'],{'ROJO':1,'AMARILLO':0,'VERDE':0})
        self.assertEqual(report['items'][0]['elapsed_hours'],76)

    def test_excel_has_same_filtered_red_yellow_and_green_totals(self):
        self.report()
        for search,status in [('QA-YELLOW','AMARILLO'),('QA-GREEN','VERDE')]:
            with self.subTest(status=status):
                with patch.object(reception,'reception_now',return_value='2026-10-22 12:00:00'):
                    content=reception_report_export.build(self.db,{'search':search})
                book=load_workbook(BytesIO(content),read_only=True)
                try:
                    summary=dict(row[:2] for row in book['Resumen'].values if len(row)>=2)
                    self.assertEqual(summary['BL rojas (segun filtros)'],0)
                    self.assertEqual(summary['BL amarillas (segun filtros)'],int(status=='AMARILLO'))
                    self.assertEqual(summary['BL verdes (segun filtros)'],int(status=='VERDE'))
                    rows=list(book['Indicadores BL'].values)
                    self.assertEqual(rows[1][rows[0].index('SLA')],status)
                finally:book.close()
