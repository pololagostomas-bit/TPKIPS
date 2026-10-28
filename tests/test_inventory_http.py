import json
import os
import threading
import unittest
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import quote

import app


class InventoryHttpTests(unittest.TestCase):
    def setUp(self):
        self.original_db = app.DB_PATH
        self.original_mode = os.environ.get("TRITON_AUTH_MODE")
        self.test_db = app.ROOT / f".inventory-http-test-{uuid.uuid4().hex}.db"
        app.DB_PATH = self.test_db
        os.environ["TRITON_AUTH_MODE"] = "demo"
        app.init_db()
        with app.db() as connection:
            connection.execute(
                """INSERT INTO inventory_stock
                   (item_key,warehouse_key,item_code,warehouse,snapshot_qty,snapshot_day,
                    snapshot_at,source_file,default_location,is_current,updated_at)
                   VALUES ('NP900','1','NP900','1',8,'2026-10-01','2026-10-01 16:00',
                           'stock.xlsx','R-01-02',1,'2026-10-01 16:00')"""
            )
        self.server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        app.DB_PATH = self.original_db
        if self.original_mode is None:
            os.environ.pop("TRITON_AUTH_MODE", None)
        else:
            os.environ["TRITON_AUTH_MODE"] = self.original_mode
        for suffix in ("", "-wal", "-shm"):
            Path(str(self.test_db) + suffix).unlink(missing_ok=True)

    def request_json(self, path, role="PICKER", method="GET", payload=None):
        headers = {"X-User": "test-user", "X-Role": role}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()
        request = Request(self.base + path, data=body, headers=headers, method=method)
        with urlopen(request) as response:
            return response.status, json.loads(response.read())

    def test_module_is_visible_and_stock_lookup_uses_existing_operational_api(self):
        status, module = self.request_json("/api/me", role="GUIADOR")
        self.assertEqual(status, 200)
        self.assertIn("inventario", module["modules"])
        status, data = self.request_json("/api/inventory/catalog?search=NP900")
        self.assertEqual(status, 200)
        self.assertEqual(data["items"][0]["available_qty"], 8)
        self.assertEqual(data["items"][0]["default_location"], "R-01-02")

    def test_request_submission_admin_approval_and_inventory_page(self):
        page = urlopen(self.base + "/inventory").read().decode()
        self.assertIn("Gestión de inventario", page)
        status, request = self.request_json("/api/inventory/requests", method="POST", payload={
            "item_code": "NP-NEW-1", "part_number": "PN-1",
            "description": "Filtro de prueba", "justification": "Necesidad operativa",
        })
        self.assertEqual(status, 201)
        status, approved = self.request_json(
            f"/api/inventory/requests/{request['id']}/decision", role="ADMINISTRADOR",
            method="POST", payload={"decision": "APROBAR", "note": "Revisado"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(approved["status"], "APROBADA")
        _, catalog = self.request_json("/api/inventory/catalog?search=NP-NEW-1")
        self.assertEqual(catalog["items"][0]["barcodes"][0]["barcode"], "WMS-NPNEW1")

    def test_generic_label_is_fresh_normalizes_brand_and_contains_no_operational_context(self):
        with app.db() as connection:
            sid = connection.execute("INSERT INTO reception_shipments(bl_awb,created_at,updated_at) VALUES ('QA-PRIVATE-BL','2026-10-14','2026-10-14')").lastrowid
            for brand in ('BOBCAT EUROPA', 'BOBCAT INDIA'):
                connection.execute(
                    """INSERT INTO reception_lines(shipment_id,np_code,brand,ov_number,customer_name)
                       VALUES (?,'NP900',?,'PRIVATE-OV','PRIVATE-CUSTOMER')""", (sid, brand))
        for role in ('PICKER', 'GUIADOR', 'ADMINISTRADOR', 'AUXILIAR_RECEPCION'):
            _, payload = self.request_json('/api/inventory/label?item_code=NP900', role=role)
            label = payload['item']
            self.assertEqual(label['item_code'], 'NP900')
            self.assertEqual(label['label_symbology'], 'DATAMATRIX')
            self.assertEqual(label['label_brand'], 'BOBCAT')
            self.assertEqual(label['default_location'], 'R-01-02')
            self.assertTrue({'ov_number', 'customer_name', 'bl_awb', 'shipment_id'}.isdisjoint(label))
        with app.db() as connection:
            connection.execute("UPDATE inventory_stock SET snapshot_qty=0 WHERE item_code='NP900'")
        _, payload = self.request_json('/api/inventory/label?item_code=NP900')
        self.assertEqual(payload['item']['default_location'], '')

    def test_label_requires_exact_catalog_material_and_inventory_role(self):
        for query in ('', 'NP9', 'NP900%25', 'missing'):
            with self.assertRaises(HTTPError) as caught:
                self.request_json('/api/inventory/label?item_code=' + query)
            self.assertEqual(caught.exception.code, 400)
        with self.assertRaises(HTTPError) as caught:
            self.request_json('/api/inventory/label?item_code=NP900', role='INVALID')
        self.assertEqual(caught.exception.code, 403)

    def test_data_matrix_aim_lookup_preserves_literal_prefix_and_legacy_aliases(self):
        with app.db() as connection:
            connection.execute("""INSERT INTO inventory_governance_barcodes
                (item_key,item_code,barcode,barcode_key,symbology,created_by,created_at)
                VALUES ('NP900','NP900','WMS-NP900','WMSNP900','CODE39','qa','2026-10-14')""")
        for query in ('NP900', '%5Dd1NP900', 'WMS-NP900'):
            _, data = self.request_json('/api/inventory/catalog?search=' + query)
            self.assertEqual(data['items'][0]['item_code'], 'NP900')
            self.assertEqual(data['items'][0]['label_symbology'], 'DATAMATRIX')
        with app.db() as connection:
            connection.execute("""INSERT INTO inventory_governance_items
                (item_key,item_code,description,created_by,created_at)
                VALUES ('D1NP900',']d1NP900','Literal prefix','qa','2026-10-14')""")
        _, data = self.request_json('/api/inventory/catalog?search=%5Dd1NP900')
        self.assertEqual(data['items'][0]['item_code'], ']d1NP900')

    def test_unknown_brand_is_not_guessed_and_ambiguous_brand_has_no_manufacturer_logo(self):
        _, payload = self.request_json('/api/inventory/label?item_code=NP900')
        self.assertEqual(payload['item']['label_brand'], '')
        with app.db() as connection:
            sid = connection.execute("INSERT INTO reception_shipments(bl_awb,created_at,updated_at) VALUES ('QA-MIXED','2026-10-14','2026-10-14')").lastrowid
            for brand in ('BOBCAT EUROPA', 'CROWN'):
                connection.execute("INSERT INTO reception_lines(shipment_id,np_code,brand) VALUES (?,'NP900',?)", (sid, brand))
        _, payload = self.request_json('/api/inventory/label?item_code=NP900')
        self.assertEqual(payload['item']['label_brand'], 'BOBCAT / CROWN')
        self.assertEqual(payload['item']['brand_logo_url'], '')

    def test_label_preserves_canonical_sku_and_does_not_write_or_generate_aliases(self):
        code = 'ICM/2022-273.a'
        with app.db() as connection:
            connection.execute("""INSERT INTO inventory_governance_items
                (item_key,item_code,description,created_by,created_at)
                VALUES ('ICM2022273A',?,'Pieza de prueba','qa','2026-10-14')""", (code,))
            before = connection.total_changes
            result = app.inventory_label(connection, code, 'qa', 'PICKER', db_path=app.DB_PATH)
            self.assertEqual(connection.total_changes, before)
            self.assertEqual(result['item_code'], code)
        _, payload = self.request_json('/api/inventory/label?item_code=' + quote(code, safe=''))
        self.assertEqual(payload['item']['item_code'], code)
        self.assertEqual(payload['item']['default_location'], '')

    def test_bi_exact_articles_remain_separate_in_stock_labels_and_operational_balances(self):
        from backend.services import powerbi_stock_store as store
        from backend.services.powerbi_stock_rows import normalize_rows
        from backend.services.daily_operations import global_stock_summary
        items=normalize_rows([
            dict(item_code='QA-123',warehouse='01',location='BIN-A',quantity=3),
            dict(item_code='QA123',warehouse='01',location='BIN-B',quantity=8)])
        for item in items:item['description']='BI '+item['item_code']
        marker={'key':'qa','started_at':'2026-10-27T08:00:00+00:00','completed_at':'2026-10-27T08:10:00+00:00'}
        with app.db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            store.activate(connection,items,{'fingerprint':'qa'},marker,'qa')
        _,catalog=self.request_json('/api/inventory/catalog?search=QA')
        self.assertEqual({item['item_code']:item['stock_qty'] for item in catalog['items']},{'QA-123':3,'QA123':8})
        for code,quantity,location in [('QA-123',3,'BIN-A'),('QA123',8,'BIN-B')]:
            _,payload=self.request_json('/api/inventory/label?item_code='+quote(code,safe=''))
            self.assertEqual(payload['item']['default_location'],location)
            with app.db() as connection:
                self.assertEqual(global_stock_summary(connection,code)['stock_cut_qty'],quantity)
                self.assertEqual(app.inventory_pool_status(connection,'QA-OV',code,'1','STOCK')['free_qty'],quantity)
        with app.db() as connection:
            self.assertEqual(global_stock_summary(connection,'Q-A123')['stock_cut_qty'],0)
            self.assertEqual(app.inventory_pool_status(connection,'QA-OV','Q-A123','1','STOCK')['free_qty'],0)
        from tests.test_global_stock import create_order,assigned_attention
        with app.db() as connection:
            create_order(connection,'OV-BI-A','QA-123',2,0)
            create_order(connection,'OV-BI-B','QA123',7,0)
            app.seed_initial_attentions(connection)
        for ov in ('OV-BI-A','OV-BI-B'):
            attention=assigned_attention(ov,'picker.qa')
            app.change_attention_status(attention['id'],'EN PICKING','picker.qa','PICKER')
        with app.db() as connection:
            for code in ('QA-123','QA123'):
                self.assertEqual(global_stock_summary(connection,code)['stock_available_qty'],1)
                self.assertEqual(app.inventory_pool_status(connection,'QA-OV',code,'1','STOCK')['free_qty'],1)


if __name__ == "__main__":
    unittest.main()
