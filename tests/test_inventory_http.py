import json
import os
import threading
import unittest
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

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


if __name__ == "__main__":
    unittest.main()
