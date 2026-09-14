"""Regression: EM is captured only after entering the EM stage."""

import sqlite3
import unittest
from unittest.mock import patch

from backend.services import reception
from backend.services.traceability import init_traceability_schema


class ReceptionEMStageTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        reception.init_reception_schema(self.db)
        init_traceability_schema(self.db)
        self.db.execute(
            "CREATE TABLE order_importation_refs (bl_awb TEXT, sap_ov TEXT, transport_type TEXT, ip_reference TEXT, oc_number TEXT)"
        )
        self.db.execute("CREATE TABLE attentions (id INTEGER PRIMARY KEY, sap_ov TEXT)")
        self.db.commit()
        self.shipment_id = reception.create_reception(
            self.db, {"bl_awb": "AWB-EM-STAGE"}, "admin", "ADMINISTRADOR"
        )["id"]
        self.db.execute(
            "INSERT INTO reception_lines (shipment_id, np_code, expected_qty) VALUES (?, 'NP-EM', 1)",
            (self.shipment_id,),
        )
        self.db.commit()

    def test_worker_cannot_register_em_during_system_review(self):
        with patch.object(reception, "advanced_lots_enabled", return_value=False):
            reception.update_reception_references(
                self.db,
                self.shipment_id,
                {"current_assistant": "assistant", "current_auxiliary": "auxiliary", "fr_number": "FR-1"},
                "admin",
                "ADMINISTRADOR",
            )
            reception.add_physical_receipt(
                self.db,
                self.shipment_id,
                {"received_packages": 1},
                "auxiliary",
                "AUXILIAR_RECEPCION",
            )
            reception.change_reception_status(
                self.db,
                self.shipment_id,
                {"status": "REVISION SISTEMA"},
                "assistant",
                "ASISTENTE_RECEPCION",
            )

            with self.assertRaisesRegex(PermissionError, "etapa EM"):
                reception.update_reception_references(
                    self.db,
                    self.shipment_id,
                    {"em_number": "EM-1"},
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
            detail = reception.update_reception_references(
                self.db,
                self.shipment_id,
                {"em_number": "EM-1"},
                "assistant",
                "ASISTENTE_RECEPCION",
            )
            self.assertEqual(detail["em_number"], "EM-1")


if __name__ == "__main__":
    unittest.main()
