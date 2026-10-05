import sqlite3
import unittest

from backend.services import reception
from backend.services.traceability import init_traceability_schema


class ReceptionFinalLocationTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        reception.init_reception_schema(self.connection)
        init_traceability_schema(self.connection)
        self.connection.execute(
            "CREATE TABLE order_importation_refs (bl_awb TEXT, sap_ov TEXT, transport_type TEXT, ip_reference TEXT, oc_number TEXT)"
        )
        shipment = self.connection.execute(
            """INSERT INTO reception_shipments
               (bl_awb, app_status, condition_status, expected_packages, received_packages,
                current_assistant, current_auxiliary, created_at, updated_at)
               VALUES ('BL-FINAL-LOC', 'UBICACION', 'EN PROCESO', 2, 2,
                       'asistente.test', 'auxiliar.test', '2026-09-25', '2026-09-25')"""
        )
        self.shipment_id = shipment.lastrowid
        first = self.connection.execute(
            """INSERT INTO reception_lines
               (shipment_id, np_code, description, ov_number, expected_qty, received_qty,
                default_location)
               VALUES (?, 'NP-1', 'Artículo uno', 'OV-1', 2, 2, 'SAP-A01')""",
            (self.shipment_id,),
        )
        self.line_id = first.lastrowid
        receipt = self.connection.execute(
            """INSERT INTO reception_receipts
               (shipment_id, sequence_no, received_packages, location_text, username, received_at)
               VALUES (?, 1, 2, 'TEMP-CAMION-01', 'asistente.test', '2026-09-25')""",
            (self.shipment_id,),
        )
        attention = self.connection.execute(
            """INSERT INTO reception_attentions
               (shipment_id, receipt_id, sequence_no, app_status, condition_status,
                current_assistant, current_auxiliary, created_at, updated_at)
               VALUES (?, ?, 1, 'UBICACION', 'EN PROCESO', 'asistente.test',
                       'auxiliar.test', '2026-09-25', '2026-09-25')""",
            (self.shipment_id, receipt.lastrowid),
        )
        self.connection.execute(
            """INSERT INTO reception_attention_lines
               (attention_id, reception_line_id, planned_qty, verified_qty)
               VALUES (?, ?, 2, 2)""",
            (attention.lastrowid, self.line_id),
        )

    def tearDown(self):
        self.connection.close()

    def test_final_sap_location_is_separate_from_temporary_truck_location(self):
        detail = reception.update_reception_line_locations(
            self.connection,
            self.shipment_id,
            {"locations": [{"line_id": self.line_id, "final_location": "RACK-B-04", "confirmed": True}]},
            "asistente.test",
            "ASISTENTE_RECEPCION",
        )

        line = self.connection.execute(
            "SELECT final_location, final_location_confirmed FROM reception_lines WHERE id = ?",
            (self.line_id,),
        ).fetchone()
        receipt = self.connection.execute(
            "SELECT location_text FROM reception_receipts WHERE shipment_id = ?",
            (self.shipment_id,),
        ).fetchone()
        self.assertEqual(line["final_location"], "RACK-B-04")
        self.assertEqual(line["final_location_confirmed"], 1)
        self.assertEqual(receipt["location_text"], "TEMP-CAMION-01")
        self.assertEqual(detail["lines"][0]["default_location"], "SAP-A01")

    def test_cannot_advance_to_validation_until_every_current_np_is_confirmed(self):
        with self.assertRaisesRegex(PermissionError, "ubicación final"):
            reception.change_reception_status(
                self.connection,
                self.shipment_id,
                {"status": "VALIDACION"},
                "asistente.test",
                "ASISTENTE_RECEPCION",
            )

        reception.update_reception_line_locations(
            self.connection,
            self.shipment_id,
            {"locations": [{"line_id": self.line_id, "final_location": "SAP-A01", "confirmed": True}]},
            "asistente.test",
            "ASISTENTE_RECEPCION",
        )
        detail = reception.change_reception_status(
            self.connection,
            self.shipment_id,
            {"status": "VALIDACION"},
            "asistente.test",
            "ASISTENTE_RECEPCION",
        )
        self.assertEqual(detail["app_status"], "VALIDACION")

    def test_confirmed_location_cannot_be_blank(self):
        with self.assertRaisesRegex(ValueError, "Indica la ubicación final"):
            reception.update_reception_line_locations(
                self.connection,
                self.shipment_id,
                {"locations": [{"line_id": self.line_id, "final_location": " ", "confirmed": True}]},
                "asistente.test",
                "ASISTENTE_RECEPCION",
            )


if __name__ == "__main__":
    unittest.main()
