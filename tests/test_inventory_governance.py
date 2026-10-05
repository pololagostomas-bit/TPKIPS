import sqlite3
import unittest

from backend.services.inventory_governance import (
    create_material_request,
    decide_material_request,
    init_inventory_governance_schema,
    inventory_catalog_search,
    list_material_requests,
)


class InventoryGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE inventory_stock (
                item_key TEXT, warehouse_key TEXT, item_code TEXT, warehouse TEXT,
                snapshot_qty REAL, snapshot_day TEXT, snapshot_at TEXT, source_file TEXT,
                default_location TEXT, is_current INTEGER, updated_at TEXT,
                PRIMARY KEY(item_key, warehouse_key)
            );
            CREATE TABLE stock_allocations (
                sap_ov TEXT, item_key TEXT, warehouse_key TEXT, status TEXT,
                reserved_qty REAL, consumed_qty REAL, reconciled_qty REAL
            );
            CREATE TABLE stock_movements (
                item_key TEXT, warehouse_key TEXT, movement_type TEXT,
                quantity REAL, created_at TEXT
            );
            CREATE TABLE order_importation_refs (
                item_key TEXT, item_code TEXT, quantity REAL, sap_ov TEXT,
                bl_awb TEXT, transport_type TEXT
            );
            CREATE TABLE reception_shipments (
                bl_awb TEXT, app_status TEXT, received_packages INTEGER
            );
            CREATE TABLE order_lines (item_code TEXT, description TEXT);
            CREATE TABLE attention_lines (item_code TEXT, description TEXT);
        """)
        init_inventory_governance_schema(self.connection)
        self.connection.execute(
            """INSERT INTO inventory_stock VALUES
               ('CLAVIJA3X32TIP44','1','CLAVIJA3X32TIP44','1',12,'2026-10-01',
                '2026-10-01 16:00','stock.xlsx','A-01-02',1,'2026-10-01 16:00')"""
        )
        self.connection.execute(
            "INSERT INTO order_lines(item_code,description) VALUES ('NP-EXISTENTE','Adaptador de prueba')"
        )
        self.connection.commit()

    def tearDown(self):
        self.connection.close()

    def test_catalog_uses_stock_summary_and_default_location(self):
        payload = inventory_catalog_search(
            self.connection, "CLAVIJA3X32TIP44", "picker", "PICKER"
        )
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["stock_qty"], 12)
        self.assertEqual(item["available_qty"], 12)
        self.assertEqual(item["default_location"], "A-01-02")

    def test_duplicate_request_is_rejected_and_description_match_is_suggested(self):
        with self.assertRaisesRegex(ValueError, "ya existe"):
            create_material_request(self.connection, {
                "item_code": "NP EXISTENTE", "description": "Adaptador",
                "justification": "Necesario para recepción",
            }, "picker", "PICKER")
        response = create_material_request(self.connection, {
            "item_code": "NP-NUEVO", "description": "Adaptador de prueba",
            "justification": "Necesario para recepción",
        }, "picker", "PICKER")
        self.assertEqual(response["status"], "PENDIENTE")
        self.assertTrue(response["similar_items"])
        self.assertEqual(response["similar_items"][0]["item_code"], "NP-EXISTENTE")

    def test_admin_approval_creates_internal_catalog_and_scannable_barcode(self):
        request = create_material_request(self.connection, {
            "item_code": "NP-NUEVO", "part_number": "PN-44",
            "description": "Repuesto especial", "justification": "Alta aprobada",
        }, "picker", "PICKER")
        result = decide_material_request(
            self.connection, request["id"], "APROBAR", "Validado",
            "admin", "ADMINISTRADOR",
        )
        self.assertEqual(result["status"], "APROBADA")
        self.assertEqual(len(list_material_requests(self.connection, "x", "ADMINISTRADOR")), 1)
        catalog = inventory_catalog_search(self.connection, "NP-NUEVO", "picker", "PICKER")
        self.assertEqual(catalog["items"][0]["item_code"], "NP-NUEVO")
        self.assertFalse(catalog["items"][0]["has_stock_record"])
        self.assertEqual(catalog["items"][0]["barcodes"][0]["barcode"], "WMS-NPNUEVO")

    def test_only_admin_can_decide_and_newly_added_material_blocks_stale_approval(self):
        request = create_material_request(self.connection, {
            "item_code": "NP-NUEVO", "description": "Repuesto especial",
            "justification": "Alta",
        }, "picker", "PICKER")
        with self.assertRaises(PermissionError):
            decide_material_request(self.connection, request["id"], "APROBAR", "", "picker", "PICKER")
        self.connection.execute(
            "INSERT INTO inventory_stock VALUES ('NP-NUEVO','1','NP-NUEVO','1',1,'2026-10-02','2026-10-02 16:00','stock.xlsx','B-01',1,'2026-10-02 16:00')"
        )
        with self.assertRaisesRegex(ValueError, "ya se incorporó"):
            decide_material_request(self.connection, request["id"], "APROBAR", "", "admin", "ADMINISTRADOR")


if __name__ == "__main__":
    unittest.main()
