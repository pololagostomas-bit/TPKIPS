"""Creation date/time from a synthetic SAP workbook, never from load time."""
from datetime import datetime,time
import unittest

from backend import app
from tests.test_daily_operations import HEADERS,excel
from tests import test_dispatch_sts as fixtures


class DispatchCreationHeadersTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.DispatchSTSTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)

    def test_creation_date_and_time_win_over_accounting_and_import_dates(self):
        headers=HEADERS+['Nombre/Razon Social','Fecha creación OV','Hora creación OV']
        row=['OV ABIERTA','QA-CREATION','Abierto','Repuestos',1,1,'NP-01','Repuesto QA',1,1,10,'COMPLETA',
             datetime(2026,11,15),'TRITON TRADING S.A.',datetime(2026,11,16),time(16,1)]
        app.import_daily_excel(excel(headers,[row]),'qa.xlsx','dispatch','2026-11-20T08:00:00','admin','ADMINISTRADOR')
        self.assertEqual(app.order_payload('QA-CREATION')['source_order_date'],'2026-11-16 16:01:00')

    def test_creation_clock_accepts_excel_and_sap_second_precision(self):
        for value,expected in ((1600,'16:00:00'),(160001,'16:00:01'),('16:00:01','16:00:01'),
                               ('000001','00:00:01'),(2/3,'16:00:00'),(time(8,30),'08:30:00')):
            data={'source_creation_date':datetime(2026,11,16),'source_order_time':value}
            with self.subTest(clock=value):
                self.assertEqual(app.source_order_timestamp(data.get),'2026-11-16 '+expected)

    def test_invalid_clocks_do_not_silently_move_an_order_into_a_cutoff(self):
        for value in (-1,930.5,2400,1699,'16:00:00:01',float('nan')):
            data={'source_creation_date':datetime(2026,11,16),'source_order_time':value}
            with self.subTest(clock=value),self.assertRaises(ValueError):
                app.source_order_timestamp(data.get)


if __name__=='__main__':unittest.main()
