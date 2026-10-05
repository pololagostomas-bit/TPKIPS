import sqlite3
import unittest

from backend.services import reception
from backend.services.traceability import init_traceability_schema


class ReceptionTruckReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        reception.init_reception_schema(self.connection)
        init_traceability_schema(self.connection)

    def tearDown(self):
        self.connection.close()

    def shipment(self, bl, expected, received=0, status="PROGRAMADO"):
        cursor = self.connection.execute(
            """INSERT INTO reception_shipments
               (bl_awb, expected_packages, received_packages, app_status,
                current_assistant, current_auxiliary, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'asistente.test', 'auxiliar.test', '2026-09-24', '2026-09-24')""",
            (bl, expected, received, status),
        )
        return cursor.lastrowid

    def guide(self, code, plans):
        self.connection.execute(
            """INSERT INTO reception_truck_guides
               (guide_code, guide_status, source_type, is_confirmed,
                created_by, created_at, updated_at)
               VALUES (?, 'PENDIENTE', 'ADMINISTRADOR', 1,
                       'admin.test', '2026-09-24', '2026-09-24')""",
            (code,),
        )
        for shipment_id, packages in plans:
            self.connection.execute(
                """INSERT INTO reception_truck_bl_manifest
                   (truck_guide, shipment_id, planned_packages, created_by, created_at, updated_at)
                   VALUES (?, ?, ?, 'admin.test', '2026-09-24', '2026-09-24')""",
                (code, shipment_id, packages),
            )
        self.connection.commit()

    def test_truck_sums_only_related_bls_that_still_have_a_balance(self):
        received = self.shipment("BL-RECIBIDA", 4, received=4)
        pending = self.shipment("BL-PENDIENTE", 7, received=2)
        unrelated = self.shipment("BL-OTRO-CAMION", 99)
        self.guide("CAMION-JOSE-01", [(received, 4), (pending, 7)])
        self.guide("CAMION-JOSE-02", [(unrelated, 99)])

        summary = reception.truck_guide_summary(
            self.connection, "CAMION-JOSE-01", "admin.test", "ADMINISTRADOR"
        )
        queue = reception.list_truck_guides(
            self.connection, role="ADMINISTRADOR", username="admin.test"
        )
        jose = next(item for item in queue if item["truck_guide"] == "CAMION-JOSE-01")

        self.assertEqual(summary["open_expected_packages"], 5)
        self.assertEqual(summary["remaining_packages"], 5)
        self.assertEqual(jose["active_bl_count"], 1)
        self.assertEqual(jose["expected_packages"], 5)
        self.assertFalse(next(row for row in summary["bls"] if row["bl_awb"] == "BL-RECIBIDA")["truck_work_pending"])

    def test_truck_with_every_bl_already_received_is_not_pending(self):
        first = self.shipment("BL-LISTA-1", 3, received=3)
        second = self.shipment("BL-LISTA-2", 2, received=2, status="CERRADO")
        self.guide("CAMION-JOSE-COMPLETO", [(first, 3), (second, 2)])

        summary = reception.truck_guide_summary(
            self.connection, "CAMION-JOSE-COMPLETO", "admin.test", "ADMINISTRADOR"
        )
        queue = reception.list_truck_guides(
            self.connection, role="ADMINISTRADOR", username="admin.test"
        )

        self.assertEqual(summary["guide_status"], "FINALIZADA")
        self.assertEqual(summary["open_expected_packages"], 0)
        self.assertEqual(summary["remaining_packages"], 0)
        self.assertNotIn("CAMION-JOSE-COMPLETO", {item["truck_guide"] for item in queue})

    def test_current_truck_arrival_remains_visible_until_location_is_saved(self):
        shipment_id = self.shipment("BL-EN-ZONA", 2)
        self.guide("CAMION-JOSE-ZONA", [(shipment_id, 2)])
        reception.process_truck_guide_arrivals(
            self.connection,
            "CAMION-JOSE-ZONA",
            [{"shipment_id": shipment_id, "received_packages": 2, "locations": []}],
            "arrival-zone-1",
            "",
            "admin.test",
            "ADMINISTRADOR",
        )

        summary = reception.truck_guide_summary(
            self.connection, "CAMION-JOSE-ZONA", "admin.test", "ADMINISTRADOR"
        )

        self.assertEqual(summary["guide_status"], "ZONA_RECEPCION")
        self.assertEqual(summary["open_expected_packages"], 2)
        self.assertEqual(summary["remaining_packages"], 0)
        self.assertTrue(summary["bls"][0]["truck_work_pending"])

    def test_zero_arrival_closes_the_truck_without_locations(self):
        shipment_id = self.shipment("BL-NO-LLEGO", 2)
        self.guide("CAMION-JOSE-CERO", [(shipment_id, 2)])
        reception.process_truck_guide_arrivals(
            self.connection,
            "CAMION-JOSE-CERO",
            [{"shipment_id": shipment_id, "received_packages": 0, "locations": []}],
            "arrival-zero-1",
            "",
            "admin.test",
            "ADMINISTRADOR",
        )

        summary = reception.process_truck_guide_locations(
            self.connection, "CAMION-JOSE-CERO", [], "admin.test", "ADMINISTRADOR"
        )

        self.assertEqual(summary["guide_status"], "CERRADA_SIN_BULTOS")
        self.assertFalse(summary["counting_enabled"])
        self.assertEqual(summary["received_packages"], 0)

    def test_bl_completed_in_another_truck_removes_previous_guide_from_pending(self):
        shipment_id = self.shipment("BL-DIVIDIDA", 5)
        self.guide("CAMION-JOSE-A", [(shipment_id, 2)])
        self.guide("CAMION-JOSE-B", [(shipment_id, 3)])
        reception.process_truck_guide_arrivals(
            self.connection,
            "CAMION-JOSE-B",
            [{
                "shipment_id": shipment_id,
                "received_packages": 5,
                "excess_reason": "Llegó el saldo completo en este camión",
                "locations": [],
            }],
            "arrival-split-complete",
            "",
            "admin.test",
            "ADMINISTRADOR",
        )

        old_guide = reception.truck_guide_summary(
            self.connection, "CAMION-JOSE-A", "admin.test", "ADMINISTRADOR"
        )
        queue_codes = {
            item["truck_guide"]
            for item in reception.list_truck_guides(
                self.connection, role="ADMINISTRADOR", username="admin.test"
            )
        }

        self.assertEqual(old_guide["guide_status"], "FINALIZADA")
        self.assertEqual(old_guide["remaining_packages"], 0)
        self.assertNotIn("CAMION-JOSE-A", queue_codes)
        self.assertIn("CAMION-JOSE-B", queue_codes)


if __name__ == "__main__":
    unittest.main()
