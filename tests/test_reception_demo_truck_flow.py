import sqlite3
import unittest

from backend.services import reception


class DemoTruckFlowTests(unittest.TestCase):
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
               (bl_awb, expected_packages, app_status, current_assistant, current_auxiliary,
                created_at, updated_at)
               VALUES ('BL-DEMO-1', 2, 'PROGRAMADO', 'asistente.test', 'auxiliar.test',
                       '2026-09-25', '2026-09-25')"""
        ).lastrowid
        reception.plan_truck_bl_packages(
            self.db, "PRUEBA-GUIA-1", self.shipment_id, 2,
            "admin.test", "ADMINISTRADOR",
        )
        self.db.execute(
            """UPDATE reception_truck_guides
                  SET source_type='ESTIMACION_PRUEBA', is_confirmed=0
                WHERE lower(guide_code)=lower('PRUEBA-GUIA-1')"""
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_simulation_guide_can_reach_arrival_without_group_confirmation(self):
        arrived = reception.process_truck_guide_arrivals(
            self.db, "PRUEBA-GUIA-1",
            [{"shipment_id": self.shipment_id, "received_packages": 2, "locations": []}],
            "demo-arrival-1", "", "asistente.test", "ASISTENTE_RECEPCION",
        )
        self.assertEqual(arrived["guide_status"], "ZONA_RECEPCION")
        visible_to_reception = reception.list_truck_guides(
            self.db, role="ASISTENTE_RECEPCION", username="asistente.test"
        )
        self.assertIn("PRUEBA-GUIA-1", {item["truck_guide"] for item in visible_to_reception})
        listed_guide = next(item for item in visible_to_reception if item["truck_guide"] == "PRUEBA-GUIA-1")
        self.assertEqual(listed_guide["active_bl_count"], 1)
        closed = reception.process_truck_guide_locations(
            self.db, "PRUEBA-GUIA-1",
            [{"shipment_id": self.shipment_id,
              "locations": [{"location": "ZONA-A", "package_count": 2}]}],
            "auxiliar.test", "AUXILIAR_RECEPCION",
        )
        self.assertEqual(closed["guide_status"], "LISTA_PARA_CONTEO")
        self.assertEqual(closed["received_packages"], 2)
        self.assertEqual(closed["bls"][0]["locations"][0]["location_text"], "ZONA-A")
        completed_guides = reception.list_truck_guides(
            self.db, role="ADMINISTRADOR", username="admin.test"
        )
        completed_guide = next(
            item for item in completed_guides if item["truck_guide"] == "PRUEBA-GUIA-1"
        )
        self.assertEqual(completed_guide["guide_status"], "LISTA_PARA_CONTEO")
        visible_bls = reception.list_receptions(
            self.db, search="BL-DEMO-1", role="ADMINISTRADOR", username="admin.test"
        )
        self.assertEqual([item["bl_awb"] for item in visible_bls], ["BL-DEMO-1"])

    def test_legacy_confirmation_action_does_not_block_a_pilot_guide(self):
        result = reception.confirm_truck_guide(
            self.db, "PRUEBA-GUIA-1", "", "admin.test", "ADMINISTRADOR",
        )
        self.assertEqual(result["is_confirmed"], 1)
        self.assertEqual(result["source_type"], "ADMIN_CONFIRMADA")

    def test_pending_demo_guide_stays_visible_when_bl_already_has_em(self):
        self.db.execute(
            "UPDATE reception_shipments SET em_number='EM-REGISTRADA', accounting_status='EM REGISTRADA' WHERE id=?",
            (self.shipment_id,),
        )
        for role in ("ADMINISTRADOR", "ASISTENTE_RECEPCION"):
            with self.subTest(role=role):
                guides = reception.list_truck_guides(
                    self.db, role=role, username="admin.test",
                )
                guide = next(
                    (item for item in guides if item["truck_guide"] == "PRUEBA-GUIA-1"),
                    None,
                )
                self.assertIsNotNone(guide)
                self.assertEqual(guide["guide_status"], "PENDIENTE")
                self.assertEqual(guide["active_bl_count"], 1)


if __name__ == "__main__":
    unittest.main()
