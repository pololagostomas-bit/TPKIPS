import sqlite3
import unittest

from backend.services import reception


class ReceptionShowAllHistoryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        reception.init_reception_schema(self.db)
        self.db.execute(
            """CREATE TABLE order_importation_refs (
                   bl_awb TEXT, sap_ov TEXT, transport_type TEXT,
                   ip_reference TEXT, oc_number TEXT
               )"""
        )
        self.shipment_id = self.db.execute(
            """INSERT INTO reception_shipments
               (bl_awb, expected_packages, received_packages, app_status,
                created_at, updated_at)
               VALUES ('BL-HIST-1', 5, 0, 'PROGRAMADO', '2026-09-25', '2026-09-25')"""
        ).lastrowid
        reception.plan_truck_bl_packages(
            self.db, "PRUEBA-HIST-1", self.shipment_id, 4,
            "admin.test", "ADMINISTRADOR",
        )
        self.db.execute(
            "UPDATE reception_shipments SET app_status='CERRADO', received_packages=5 WHERE id=?",
            (self.shipment_id,),
        )
        self.db.execute(
            """UPDATE reception_truck_guides
                  SET source_type='ESTIMACION_PRUEBA', is_confirmed=0,
                      guide_status='LISTA_PARA_CONTEO'
                WHERE lower(guide_code)=lower('PRUEBA-HIST-1')"""
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_all_trucks_includes_closed_guide_but_default_queue_does_not(self):
        pending = reception.list_truck_guides(self.db)
        all_guides = reception.list_truck_guides(self.db, include_completed=True)

        self.assertNotIn("PRUEBA-HIST-1", {item["truck_guide"] for item in pending})
        guide = next(item for item in all_guides if item["truck_guide"] == "PRUEBA-HIST-1")
        self.assertEqual(guide["guide_status"], "FINALIZADA")
        self.assertEqual(guide["closed_bl_count"], 1)

    def test_all_bls_query_includes_closed_shipments(self):
        pending = reception.list_receptions(self.db, role="ADMINISTRADOR")
        all_bls = reception.list_receptions(
            self.db, role="ADMINISTRADOR", limit=1000, state="ALL",
        )

        self.assertNotIn("BL-HIST-1", {item["bl_awb"] for item in pending})
        self.assertIn("BL-HIST-1", {item["bl_awb"] for item in all_bls})


if __name__ == "__main__":
    unittest.main()
