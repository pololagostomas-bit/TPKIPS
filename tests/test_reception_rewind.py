"""Regression: el administrador puede reabrir una etapa sin borrar auditoría."""

import sqlite3
import unittest
from unittest.mock import patch

from backend.services import reception
from backend.services.traceability import init_traceability_schema


class ReceptionRewindTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        reception.init_reception_schema(self.db)
        init_traceability_schema(self.db)
        self.db.execute(
            """CREATE TABLE order_importation_refs (
               bl_awb TEXT, sap_ov TEXT, transport_type TEXT,
               ip_reference TEXT, oc_number TEXT
            )"""
        )
        self.shipment_id = reception.create_reception(
            self.db,
            {
                "bl_awb": "BL-REOPEN-001",
                "transport_type": "AEREO",
                "expected_packages": 1,
                "current_assistant": "assistant",
                "current_auxiliary": "auxiliary",
            },
            "admin",
            "ADMINISTRADOR",
        )["id"]
        self.db.execute(
            "INSERT INTO reception_lines (shipment_id, np_code, expected_qty) VALUES (?, 'NP-REOPEN', 4)",
            (self.shipment_id,),
        )
        self.db.commit()

    def test_admin_reopens_stage_and_worker_sees_prior_stage_read_only(self):
        with patch.object(reception, "advanced_lots_enabled", return_value=False):
            reception.add_physical_receipt(
                self.db,
                self.shipment_id,
                {"received_packages": 1},
                "auxiliary",
                "AUXILIAR_RECEPCION",
            )
            reception.update_reception_references(
                self.db,
                self.shipment_id,
                {"fr_number": "FR-REOPEN-001"},
                "admin",
                "ADMINISTRADOR",
            )
            reception.change_reception_status(
                self.db,
                self.shipment_id,
                {"status": "REVISION SISTEMA"},
                "assistant",
                "ASISTENTE_RECEPCION",
            )
            reception.change_reception_status(
                self.db,
                self.shipment_id,
                {"status": "EM"},
                "assistant",
                "ASISTENTE_RECEPCION",
            )
            reception.update_reception_references(
                self.db,
                self.shipment_id,
                {"em_number": "EM-REOPEN-001"},
                "assistant",
                "ASISTENTE_RECEPCION",
            )
            before = reception.reception_detail(
                self.db, self.shipment_id, "ASISTENTE_RECEPCION", "assistant"
            )
            self.assertEqual(before["app_status"], "EM")

            reopened = reception.rewind_reception_stage(
                self.db,
                self.shipment_id,
                {"status": "ARRIBADO", "reason": "Repetir revisión operativa"},
                "admin",
                "ADMINISTRADOR",
            )
            self.assertEqual(reopened["app_status"], "ARRIBADO")
            self.assertEqual(reopened["condition_status"], "ARRIBO REGISTRADO")
            self.assertEqual(reopened["system_quantities_initialized"], 0)
            self.assertEqual(reopened["transfer_assistant_checked"], 0)
            self.assertEqual(reopened["em_number"], "EM-REOPEN-001")

            with self.assertRaisesRegex(PermissionError, "REVISIÓN DE SISTEMA"):
                reception.update_reception_line_quantity(
                    self.db,
                    self.shipment_id,
                    reopened["lines"][0]["id"],
                    {"received_qty": 3},
                    "assistant",
                    "ASISTENTE_RECEPCION",
                )
            self.assertTrue(
                self.db.execute(
                    "SELECT 1 FROM reception_history WHERE shipment_id = ? AND event_type = 'RETROCESO_ADMIN'",
                    (self.shipment_id,),
                ).fetchone()
            )

            with self.assertRaisesRegex(PermissionError, "Solo el administrador"):
                reception.rewind_reception_stage(
                    self.db,
                    self.shipment_id,
                    {"status": "PROGRAMADO", "reason": "No permitido"},
                    "assistant",
                    "ASISTENTE_RECEPCION",
                )


if __name__ == "__main__":
    unittest.main()
