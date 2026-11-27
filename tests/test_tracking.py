import sqlite3
import unittest
from openpyxl import Workbook
from backend.services import tracking

HEADERS = ['OV', 'ORDEN DE COMPRA', 'CODIGO', 'GUIA DE IMPORTACION', 'DESCRIPCION', 'CANTIDAD SOLICITADA', 'CANTIDAD FACTURADA', 'CANTIDAD PENDIENTE', 'FECHA CONFIRMADA TRITON', 'FECHA TRITON ESTIMADA', 'FECHA DE PEDIDO']

def book(rows, title='IMPORTACIONES'):
    wb = Workbook()
    wb.active.title = title
    wb.active.append(HEADERS)
    for row in rows:
        wb.active.append(row)
    return wb

class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        tracking.init_schema(self.db)

    def tearDown(self):
        self.db.close()

    def test_exact_documents_early_rows_dates_and_no_private_fields(self):
        tracking.store_workbook(self.db, book([
            ['123', '456', 'NP', '', 'pieza', 10, 3, 7, '2020-01-01', '2019-01-01', '2018-01-01'],
            ['456', '123', 'NP', '', 'otra', 2],
            ['COT-8', 'PRE-7', '', '', 'documento'],
        ]), 'synthetic.xlsx', cutoff='2026-11-23')
        result = tracking.search(self.db, 'OV', '123')
        self.assertEqual(result['summary']['total'], 1)
        self.assertEqual(result['source']['cutoff_at'], '2026-11-23')
        self.assertEqual(result['summary']['received'], 0)
        self.assertEqual(result['lines'][0]['dates']['order'], '2018-01-01')
        self.assertEqual(result['lines'][0]['dates']['confirmed'], '2020-01-01')
        self.assertEqual(result['lines'][0]['received_qty'], None)
        self.assertEqual(tracking.search(self.db, 'OC', '123')['lines'][0]['description'], 'otra')
        self.assertEqual(tracking.search(self.db, 'OV', 'COT-8')['lines'][0]['oc'], 'PRE-7')
        self.assertEqual(tracking.search(self.db, 'OV', '12')['summary']['total'], 0)
        self.assertNotIn('price', str(result))

    def test_signed_pending_does_not_reject_the_cut_or_imply_arrival(self):
        workbook = book([
            ['OV-SIGNED', 'OC-SIGNED', 'P', '', 'piece', 10, 12, -2],
            ['OV-OTHER', 'OC-OTHER', 'Q', '', 'other piece', 3, 1, 2],
        ])
        self.assertTrue(tracking.store_workbook(self.db, workbook, 'synthetic.xlsx'))
        line = tracking.search(self.db, 'OV', 'OV-SIGNED')['lines'][0]
        self.assertEqual(line['pending_qty'], -2)
        self.assertIsNone(line['received_qty'])
        self.assertEqual(tracking.search(self.db, 'OC', 'OC-OTHER')['lines'][0]['pending_qty'], 2)

        invalid = book([['OV-SIGNED', 'OC-SIGNED', 'P', '', 'piece', -10, 12, -2]])
        self.assertFalse(tracking.store_workbook(self.db, invalid, 'invalid.xlsx'))
        self.assertEqual(tracking.search(self.db, 'OV', 'OV-SIGNED')['source']['filename'], 'synthetic.xlsx')

    def test_analyst_document_filters_and_purchase_format(self):
        workbook = book([
            ['1', '12345', 'A', 'BL-ABC'],
            ['2', 'pre12345', 'B', 'BL-ABC-2'],
            ['3', '12345 / 67890', 'C', 'BL-ABC'],
            ['', '', 'D', 'BL-ONLY'],
        ])
        for row, ip in enumerate(('IP-1', 'IP-10', 'IP-3', 'IP-ONLY'), 2):
            workbook.active.cell(row, len(HEADERS) + 1, ip)
        workbook.active.cell(1, len(HEADERS) + 1, 'PEDIDO TRITON')
        self.assertTrue(tracking.store_workbook(self.db, workbook, 'synthetic.xlsx'))
        self.assertEqual(tracking.search(self.db, 'IP', 'ip-1')['lines'][0]['approval'], 'Aprobada según formato')
        self.assertEqual(tracking.search(self.db, 'IP', 'ip-10')['lines'][0]['approval'], 'Preliminar por regularizar')
        self.assertEqual([l['item'] for l in tracking.search(self.db, 'BL', 'bl-abc')['lines']], ['A', 'C'])
        self.assertEqual(tracking.search(self.db, 'OV', '3')['lines'][0]['approval'], 'Preliminar por regularizar')
        self.assertEqual(tracking.search(self.db, 'BL', 'BL-ONLY')['lines'][0]['item'], 'D')
        self.assertEqual(tracking.search(self.db, 'IP', 'IP-ONLY')['lines'][0]['item'], 'D')
        self.assertEqual(tracking.search(self.db, 'BL', 'BL-A')['lines'], [])

    def test_warehouse_exact_link_partials_and_duplicate_source(self):
        self.db.executescript("""CREATE TABLE reception_shipments(id INTEGER,bl_awb TEXT,app_status TEXT,location_text TEXT,transfer_assistant_checked INTEGER,first_arrival_at TEXT,transport_type TEXT,updated_at TEXT,condition_status TEXT);
            CREATE TABLE reception_lines(id INTEGER,shipment_id INTEGER,source_sheet TEXT,ov_number TEXT,oc_number TEXT,np_code TEXT,ip_reference TEXT,received_qty REAL,final_location TEXT,final_location_confirmed INTEGER);
            CREATE TABLE reception_receipts(id INTEGER,shipment_id INTEGER,received_at TEXT,received_packages REAL);
            CREATE TABLE reception_truck_bl_arrivals(shipment_id INTEGER,arrived_at TEXT,received_packages REAL);
            CREATE TABLE reception_history(id INTEGER,shipment_id INTEGER,field_name TEXT,new_value TEXT,event_type TEXT,created_at TEXT);
            CREATE TABLE reception_attentions(id INTEGER,shipment_id INTEGER,app_status TEXT,condition_status TEXT,receipt_id INTEGER,completed_at TEXT,transfer_assistant_checked INTEGER);
            INSERT INTO reception_shipments VALUES(1,'BL','CERRADO','R1',1,NULL,'AEREO','2026-11-20','EN PROCESO');
            INSERT INTO reception_lines VALUES(1,1,'IMPORTACIONES','1','2','P','',3,'R1',1);
            INSERT INTO reception_lines VALUES(2,1,'IMPORTACIONES','9','9','Q','',99,'R1',1);""")
        tracking.store_workbook(self.db, book([['1', '2', 'P', 'BL', 'partial', 10], ['1', '3', 'Q', 'BL', 'other', 10]]), 'first.xlsx')
        self.assertIsNone(tracking.search(self.db, 'OV', '1')['lines'][0]['received_qty'])
        self.db.execute("INSERT INTO reception_receipts VALUES(1,1,'2026-11-20',1)")
        result = tracking.search(self.db, 'OV', '1')
        self.assertEqual(result['summary']['status'], 'Parcial')
        self.assertEqual(result['summary']['transferred'], 0)
        self.assertEqual(result['summary']['received'], 0)
        self.assertEqual(result['summary']['partially_received'], 1)
        self.assertEqual(result['lines'][0]['sla']['sla_hours'], 72)
        self.assertEqual(tracking.search(self.db, 'BL', 'bl')['lines'][0]['received_qty'], 3)
        self.assertIsNone(result['lines'][1]['received_qty'])
        self.db.executescript("""CREATE TABLE reception_attention_lines(attention_id INTEGER,reception_line_id INTEGER,verified_qty REAL);
            INSERT INTO reception_receipts VALUES(2,1,'2026-11-22',1);
            INSERT INTO reception_attentions VALUES(1,1,'REVISION SISTEMA','EN PROCESO',2,NULL,0);
            INSERT INTO reception_attention_lines VALUES(1,1,3);""")
        self.assertTrue(tracking.search(self.db, 'OV', '1')['lines'][0]['sla']['work_started_at'].startswith('2026-11-22'))
        self.db.execute("UPDATE reception_attentions SET app_status='CERRADO',completed_at='2026-11-23',transfer_assistant_checked=1")
        partial = tracking.search(self.db, 'OV', '1')
        self.assertEqual(partial['lines'][0]['transferred_qty'], 3)
        self.assertEqual(partial['summary']['transferred'], 0)
        self.db.execute('UPDATE reception_lines SET received_qty=10 WHERE id=1')
        self.db.execute('UPDATE reception_attention_lines SET verified_qty=10')
        self.assertTrue(tracking.search(self.db, 'OV', '1')['lines'][0]['transferred'])
        for condition in ('CIERRE ADMINISTRATIVO', 'ANULADA POR ERROR'):
            with self.subTest(condition=condition, scope='attention'):
                self.db.execute('UPDATE reception_attentions SET condition_status=?', (condition,))
                excluded = tracking.search(self.db, 'OV', '1')['lines'][0]
                self.assertFalse(excluded['transferred'])
                self.assertNotEqual(excluded['stage'], 'Atención de almacén completada')
                self.assertNotEqual(excluded['sla']['sla_status'], 'FINALIZADO')
            with self.subTest(condition=condition, scope='shipment'):
                self.db.execute('DELETE FROM reception_attention_lines')
                self.db.execute('DELETE FROM reception_attentions')
                self.db.execute('UPDATE reception_shipments SET condition_status=?', (condition,))
                self.assertFalse(tracking.search(self.db, 'OV', '1')['lines'][0]['transferred'])
            self.db.execute("UPDATE reception_shipments SET condition_status='EN PROCESO'")
            self.db.execute("INSERT INTO reception_attentions VALUES(1,1,'CERRADO','EN PROCESO',2,'2026-11-23',1)")
            self.db.execute('INSERT INTO reception_attention_lines VALUES(1,1,10)')
        for column in ('ov_number', 'oc_number'):
            plan = self.db.execute(f'EXPLAIN QUERY PLAN SELECT * FROM reception_lines WHERE {column}=?', ('1',)).fetchall()
            self.assertTrue(any(f'tracking_reception_{column}' in row[3] for row in plan))
        tracking.store_workbook(self.db, book([['1', '2', 'P', 'BL', 'duplicate', 10]] * 2), 'second.xlsx')
        result = tracking.search(self.db, 'OV', '1')
        self.assertIsNone(result['lines'][0]['received_qty'])
        self.assertTrue(result['lines'][0]['warning'])

    def test_failed_sync_retains_good_snapshot_with_generic_warning(self):
        tracking.store_workbook(self.db, book([['1', '2', 'P']]), 'good.xlsx')
        self.db.executescript("""CREATE TABLE cloud_sync_status(source_type TEXT,state TEXT,checked_at TEXT,detail TEXT);
            INSERT INTO cloud_sync_status VALUES('importation','ERROR','2026-11-23','secret@example.test');""")
        self.db.execute('PRAGMA query_only=ON')
        result = tracking.search(self.db, 'OV', '1')
        self.assertTrue(result['source']['warning'])
        self.assertEqual(result['source']['sync_checked_at'], '2026-11-23')
        self.assertNotIn('secret', str(result))

    def test_stock_alias_is_not_a_sales_order(self):
        tracking.store_workbook(self.db, book([['PARA STOCK', '777', 'P', '', 'stock']]), 'stock.xlsx')
        self.assertEqual(tracking.search(self.db, 'OC', '777')['lines'][0]['ov'], '')
        with self.assertRaises(ValueError):
            tracking.search(self.db, 'OV', 'STOCK')

    def test_pre_revision_prefers_current_rows_and_bounds_document(self):
        tracking.store_workbook(self.db, book([['1', 'PRE-2', 'P']]), 'first.xlsx')
        tracking.store_workbook(self.db, book([['1', '54321', 'P']]), 'second.xlsx')
        result = tracking.search(self.db, 'OV', '1')
        self.assertEqual(result['summary']['total'], 1)
        self.assertEqual(result['lines'][0]['oc'], '54321')
        self.assertEqual(tracking.search(self.db, 'OC', 'PRE-2')['summary']['total'], 1)
        tracking.store_workbook(self.db, book([['99', '2', str(i)] for i in range(tracking.MAX_DOCUMENT_LINES + 1)]), 'large.xlsx')
        with self.assertRaises(ValueError):
            tracking.search(self.db, 'OV', '99')

    def test_orders_without_importations_and_transaction_ownership(self):
        self.db.executescript("""CREATE TABLE orders(sap_ov TEXT,updated_at TEXT);
            CREATE TABLE order_lines(sap_ov TEXT,source_row INTEGER,item_code TEXT,description TEXT,required_qty REAL,pending_qty REAL);
            INSERT INTO orders VALUES('88','2026-11-22');
            INSERT INTO order_lines VALUES('88',2,'P','part',10,10);""")
        result = tracking.search(self.db, 'OV', '88')
        self.assertEqual(result['summary']['total'], 1)
        self.assertEqual(result['source']['orders_updated_at'], '2026-11-22')
        self.assertTrue(result['source']['warning'])
        self.assertIsNone(result['lines'][0]['received_qty'])
        self.db.execute("INSERT INTO orders VALUES('99','date')")
        tracking.store_workbook(self.db, book([['1', '2', 'P']]), 'new.xlsx')
        self.db.rollback()
        self.assertIsNone(self.db.execute("SELECT * FROM orders WHERE sap_ov='99'").fetchone())
        self.assertEqual(tracking.search(self.db, 'OV', '1')['summary']['total'], 0)

    def test_invalid_incomplete_source_retains_snapshot(self):
        first = book([['1', '2', 'P', '', 'ok']])
        second = first.create_sheet('OTRA')
        second.append(HEADERS)
        second.append(['1', '3', 'Q'])
        tracking.store_workbook(self.db, first, 'first.xlsx')
        tracking.store_workbook(self.db, book([['1', '2', 'P']]), 'partial.xlsx')
        result = tracking.search(self.db, 'OV', '1')
        self.assertEqual(result['summary']['total'], 2)
        self.assertTrue(result['source']['warning'])
        self.assertEqual(result['source']['filename'], 'first.xlsx')
        tracking.store_workbook(self.db, Workbook(), 'broken.xlsx')
        self.assertEqual(tracking.search(self.db, 'OV', '1')['summary']['total'], 2)

    def test_disappeared_rows_are_not_cancelled_and_reads_are_query_only(self):
        tracking.store_workbook(self.db, book([['1', '2', 'P'], ['1', '3', 'Q']]), 'first.xlsx')
        tracking.store_workbook(self.db, book([['2', '2', 'P']]), 'next.xlsx')
        statements = []
        self.db.set_trace_callback(statements.append)
        self.db.execute('PRAGMA query_only=ON')
        result = tracking.search(self.db, 'OV', '1', limit=1, offset=1)
        self.assertEqual(result['pagination']['total'], 2)
        self.assertTrue(result['lines'][0]['warning'])
        self.assertLessEqual(sum(s.lstrip().upper().startswith(('SELECT', 'WITH')) for s in statements), 6)
        plan = self.db.execute('EXPLAIN QUERY PLAN SELECT * FROM tracking_lines WHERE ov=?', ('1',)).fetchall()
        self.assertTrue(any('tracking_ov' in row[3] for row in plan))
        with self.assertRaises(ValueError):
            tracking.search(self.db, 'NP', '1')
        with self.assertRaises(ValueError):
            tracking.search(self.db, 'OV', '')

    def test_importation_subset_does_not_certify_whole_sales_order(self):
        self.db.executescript("CREATE TABLE orders(sap_ov TEXT,updated_at TEXT); CREATE TABLE order_lines(sap_ov TEXT,source_row INTEGER,item_code TEXT,description TEXT,required_qty REAL,pending_qty REAL); INSERT INTO orders VALUES('OV-SUBSET','2026-11-23'); INSERT INTO order_lines VALUES('OV-SUBSET',1,'P','part',10,10);")
        tracking.store_workbook(self.db, book([['OV-SUBSET','12345','P','BL', 'part',2]]),'synthetic.xlsx','2026-11-23')
        result=tracking.search(self.db,'OV','OV-SUBSET')
        self.assertTrue(result['source'].get('coverage_warning'))
        self.db.execute("UPDATE orders SET updated_at='2026-11-22' WHERE sap_ov='OV-SUBSET'")
        commercial = tracking.search(self.db, 'OV', 'OV-SUBSET', details=False)
        self.assertEqual(commercial['source']['orders_updated_at'], '2026-11-22')
        self.assertTrue(commercial['source']['orders_warning'])

    def test_partially_disappeared_document_warns_without_duplicating_revisions(self):
        tracking.store_workbook(self.db, book([['1','2','P'],['1','2','Q']]), 'first.xlsx')
        tracking.store_workbook(self.db, book([['1','2','P']]), 'second.xlsx')
        result = tracking.search(self.db, 'OC', '2')
        self.assertEqual(result['summary']['total'], 1)
        self.assertTrue(result['source']['coverage_warning'])

    def test_previously_populated_sheet_cannot_become_empty_silently(self):
        first = book([['1','2','P']])
        sheet = first.create_sheet('OTRA'); sheet.append(HEADERS); sheet.append(['1','3','Q'])
        self.assertTrue(tracking.store_workbook(self.db, first, 'first.xlsx'))
        truncated = book([['1','2','P']]); truncated.create_sheet('OTRA').append(HEADERS)
        self.assertFalse(tracking.store_workbook(self.db, truncated, 'truncated.xlsx'))
        result = tracking.search(self.db, 'OV', '1')
        self.assertEqual(result['summary']['total'], 2)
        self.assertEqual(result['source']['filename'], 'first.xlsx')
        self.assertTrue(result['source']['warning'])

if __name__ == '__main__':
    unittest.main()
