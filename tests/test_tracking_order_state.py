"""Tracking reconciles a formatted numeric NP without creating another order line."""
import sqlite3
import unittest

from backend.services import tracking
from tests.test_tracking import book


class TrackingOrderStateTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        tracking.init_schema(self.db)
        self.db.executescript("""
            CREATE TABLE orders(sap_ov TEXT,updated_at TEXT);
            CREATE TABLE order_lines(sap_ov TEXT,source_row INTEGER,item_code TEXT,description TEXT,required_qty REAL,pending_qty REAL);
            CREATE TABLE powerbi_stock_items(item_code_key TEXT,item_key TEXT,cutoff_at TEXT);
            CREATE TABLE inventory_stock(item_key TEXT,warehouse_key TEXT,is_current INTEGER,snapshot_at TEXT,source_file TEXT);
            INSERT INTO orders VALUES('OV-TEST','2026-11-23');
            INSERT INTO order_lines VALUES('OV-TEST',1,'1234','piece',2,2);
            INSERT INTO powerbi_stock_items VALUES('001234','001234','2026-11-23');
            INSERT INTO inventory_stock VALUES('001234','1',1,'2026-11-23','Stock Power BI');
        """)
        tracking.store_workbook(self.db, book([
            ['OV-TEST', '12345', '001234', 'BL-TEST', 'piece', 2]
        ]), 'synthetic.xlsx', '2026-11-23')

    def tearDown(self):
        self.db.close()

    def result(self, **kwargs):
        return tracking.search(self.db, 'OV', 'OV-TEST', **kwargs)

    def test_current_catalog_identifies_same_numeric_code_in_same_order(self):
        self.db.execute('PRAGMA query_only=ON')
        result = self.result()
        self.assertEqual(result['summary']['total'], 1)
        self.assertEqual(result['lines'][0]['item'], '001234')
        self.assertNotIn('coverage_warning', result['source'])
        self.assertEqual(self.result(details=False)['summary']['total'], 1)

    def test_distinct_current_catalog_codes_are_not_merged(self):
        self.db.execute("INSERT INTO powerbi_stock_items VALUES('1234','1234','2026-11-23')")
        self.db.execute("INSERT INTO inventory_stock VALUES('1234','1',1,'2026-11-23','Stock Power BI')")
        result = self.result()
        self.assertEqual(result['summary']['total'], 2)
        self.assertTrue(result['source']['coverage_warning'])

    def test_alias_does_not_remove_zeroes_from_the_order_code(self):
        self.db.execute("UPDATE order_lines SET item_code='001234'")
        self.db.execute("UPDATE powerbi_stock_items SET item_code_key='1234'")
        tracking.store_workbook(self.db, book([
            ['OV-TEST', '12345', '1234', 'BL-TEST', 'piece', 2]
        ]), 'synthetic.xlsx', '2026-11-23')
        result = self.result()
        self.assertEqual(result['summary']['total'], 2)
        self.assertTrue(result['source']['coverage_warning'])

    def test_missing_or_stale_catalog_does_not_guess_identity(self):
        for sql in ("UPDATE inventory_stock SET is_current=0",
                    "UPDATE inventory_stock SET snapshot_at='2026-11-22'",
                    "UPDATE inventory_stock SET source_file='manual.xlsx'"):
            with self.subTest(sql=sql):
                self.db.execute('SAVEPOINT guard')
                self.db.execute(sql)
                self.assertEqual(self.result()['summary']['total'], 2)
                self.db.execute('ROLLBACK TO guard')
                self.db.execute('RELEASE guard')

    def test_changed_quantity_or_description_preserves_coverage_warning(self):
        for field, value in (('required_qty', 3), ('description', 'another part')):
            with self.subTest(field=field):
                self.db.execute('SAVEPOINT guard')
                self.db.execute('UPDATE order_lines SET '+field+'=?', (value,))
                self.assertEqual(self.result()['summary']['total'], 2)
                self.assertTrue(self.result()['source']['coverage_warning'])
                self.db.execute('ROLLBACK TO guard')
                self.db.execute('RELEASE guard')

    def test_multiple_source_or_order_variants_remain_separate(self):
        self.db.execute("INSERT INTO order_lines VALUES('OV-TEST',2,'001234','piece',2,2)")
        self.assertEqual(self.result()['summary']['total'], 2)
        self.assertTrue(self.result()['source']['coverage_warning'])
        self.db.execute("DELETE FROM order_lines WHERE item_code='001234'")
        tracking.store_workbook(self.db, book([
            ['OV-TEST', '12345', '001234', 'BL-TEST', 'piece', 2],
            ['OV-TEST', '54321', '01234', 'OTHER-BL', 'piece', 2],
        ]), 'synthetic.xlsx', '2026-11-23')
        self.assertEqual(self.result()['summary']['total'], 3)

    def test_punctuation_is_not_a_numeric_format_alias(self):
        self.db.execute("UPDATE order_lines SET item_code='AB1234'")
        self.db.execute("UPDATE powerbi_stock_items SET item_code_key='AB-1234'")
        tracking.store_workbook(self.db, book([
            ['OV-TEST', '12345', 'AB-1234', 'BL-TEST', 'piece', 2]
        ]), 'synthetic.xlsx', '2026-11-23')
        self.assertEqual(self.result()['summary']['total'], 2)
        self.assertTrue(self.result()['source']['coverage_warning'])

    def warehouse(self):
        self.db.executescript("""
            CREATE TABLE reception_shipments(id INTEGER,bl_awb TEXT,app_status TEXT,location_text TEXT,transfer_assistant_checked INTEGER,first_arrival_at TEXT,transport_type TEXT,updated_at TEXT,condition_status TEXT);
            CREATE TABLE reception_lines(id INTEGER,shipment_id INTEGER,source_sheet TEXT,ov_number TEXT,oc_number TEXT,np_code TEXT,ip_reference TEXT,received_qty REAL,final_location TEXT,final_location_confirmed INTEGER);
            CREATE TABLE reception_receipts(id INTEGER,shipment_id INTEGER,received_at TEXT,received_packages REAL);
            CREATE TABLE reception_truck_bl_arrivals(shipment_id INTEGER,arrived_at TEXT,received_packages REAL);
            CREATE TABLE reception_history(id INTEGER,shipment_id INTEGER,field_name TEXT,new_value TEXT,event_type TEXT,created_at TEXT);
            CREATE TABLE reception_attentions(id INTEGER,shipment_id INTEGER,app_status TEXT,condition_status TEXT,receipt_id INTEGER,completed_at TEXT,transfer_assistant_checked INTEGER);
            CREATE TABLE reception_attention_lines(attention_id INTEGER,reception_line_id INTEGER,verified_qty REAL);
            CREATE TABLE reception_attention_costing(attention_id INTEGER,shipment_id INTEGER,costing_date TEXT,source_current INTEGER);
            INSERT INTO reception_shipments VALUES(1,'BL-TEST','CERRADO','',0,NULL,'AEREO','2026-11-23','COMPLETADO');
            INSERT INTO reception_lines VALUES(1,1,'IMPORTACIONES','OV-TEST','12345','001234','',2,'',0);
            INSERT INTO reception_receipts VALUES(1,1,'2026-11-20',1);
            INSERT INTO reception_attentions VALUES(1,1,'CERRADO','COMPLETADO',1,'2026-11-23',0);
            INSERT INTO reception_attention_lines VALUES(1,1,2);
            INSERT INTO reception_attention_costing VALUES(1,1,'2026-11-23',1);
        """)

    def test_complete_current_costing_does_not_require_manual_transfer_check(self):
        self.warehouse()
        self.db.execute("UPDATE reception_lines SET final_location='R1',final_location_confirmed=1")
        self.db.execute('PRAGMA query_only=ON')
        result = self.result()
        self.assertEqual(result['summary']['status'], 'Ingresado y costeado')
        self.assertEqual(result['summary']['total'], 1)
        self.assertEqual(result['summary']['received'], 1)
        self.assertEqual(result['summary']['transferred'], 0)
        self.assertTrue(result['lines'][0]['costed'])
        self.assertFalse(result['lines'][0]['transferred'])
        self.assertEqual(self.result(details=False)['summary']['status'], 'Ingresado y costeado')
        self.assertEqual(tracking.search(self.db, 'OC', '12345')['summary']['status'], 'Ingresado y costeado')

    def test_contradictory_costing_quantities_show_a_warning(self):
        self.warehouse()
        self.db.execute('UPDATE reception_attention_lines SET verified_qty=3')
        line = self.result()['lines'][0]
        self.assertFalse(line.get('costed'))
        self.assertIn('cantidades de costeo contradictorias', line['warning'] or '')

    def test_partial_retired_or_excluded_costing_does_not_complete_order(self):
        self.warehouse()
        for sql in ("UPDATE reception_attention_costing SET source_current=0",
                    "UPDATE reception_attention_costing SET costing_date=''",
                    "UPDATE reception_attention_costing SET shipment_id=2",
                    "UPDATE reception_attention_lines SET verified_qty=1",
                    "UPDATE reception_attention_lines SET verified_qty=3",
                    "UPDATE reception_attentions SET app_status='SOLICITUD TRANSFERENCIA'",
                    "UPDATE reception_attentions SET condition_status='CIERRE ADMINISTRATIVO'"):
            with self.subTest(sql=sql):
                self.db.execute('SAVEPOINT guard'); self.db.execute(sql)
                result = self.result()
                self.assertNotEqual(result['summary']['status'], 'Ingresado y costeado')
                self.assertFalse(result['lines'][0].get('costed'))
                self.db.execute('ROLLBACK TO guard'); self.db.execute('RELEASE guard')

    def test_other_order_line_blocks_whole_order_completion(self):
        self.warehouse()
        self.db.execute("INSERT INTO order_lines VALUES('OV-TEST',2,'STOCK-PART','stock part',1,1)")
        result = self.result()
        self.assertEqual(result['summary']['total'], 2)
        self.assertNotEqual(result['summary']['status'], 'Ingresado y costeado')
        self.assertTrue(result['source']['coverage_warning'])

    def test_importation_date_alone_is_not_proof_of_costing(self):
        self.warehouse()
        self.db.execute('DELETE FROM reception_attention_costing')
        self.db.execute("UPDATE tracking_lines SET payload=json_set(payload,'$.dates.costing','2026-11-23')")
        result = self.result()
        self.assertEqual(result['summary']['status'], 'Recibido')
        self.assertFalse(result['lines'][0]['costed'])


if __name__ == '__main__':
    unittest.main()
