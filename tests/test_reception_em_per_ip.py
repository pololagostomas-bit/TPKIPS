"""Regression: one FR shared by multiple IP requires one EM per IP."""

import sqlite3
import unittest
from unittest.mock import patch

from backend.services import reception
from backend.services.traceability import init_traceability_schema


class ReceptionEMPerIPTests(unittest.TestCase):
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
        self.shipment_id = reception.create_reception(
            self.db, {"bl_awb": "AWB-SHARED-FR"}, "admin", "ADMINISTRADOR"
        )["id"]
        self.db.execute(
            """INSERT INTO reception_accounting_refs
               (shipment_id, source_key, ip_reference, fr_number, created_at, updated_at)
               VALUES (?, 'shared', 'IP-1, IP-2', '299937', '2026-01-01', '2026-01-01')""",
            (self.shipment_id,),
        )
        self.db.executemany(
            """INSERT INTO reception_lines
               (shipment_id, np_code, ip_reference, expected_qty, received_qty)
               VALUES (?, ?, ?, 1, 1)""",
            [(self.shipment_id, "NP-1", "IP-1"), (self.shipment_id, "NP-2", "IP-2")],
        )
        self.db.execute(
            """INSERT INTO reception_attentions
               (shipment_id, sequence_no, app_status, created_at, updated_at)
               VALUES (?, 1, 'EM', '2026-01-01', '2026-01-01')""",
            (self.shipment_id,),
        )
        attention_id = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        line_ids = [row[0] for row in self.db.execute(
            "SELECT id FROM reception_lines WHERE shipment_id=? ORDER BY id", (self.shipment_id,)
        ).fetchall()]
        self.db.executemany(
            """INSERT INTO reception_attention_lines
               (attention_id, reception_line_id, planned_qty, verified_qty)
               VALUES (?, ?, 1, 1)""",
            [(attention_id, line_id) for line_id in line_ids],
        )
        self.db.execute(
            """UPDATE reception_shipments
               SET app_status='EM', current_assistant='worker', current_auxiliary='aux'
               WHERE id=?""",
            (self.shipment_id,),
        )
        self.db.commit()

    def test_same_fr_is_split_by_ip_and_each_ip_needs_an_em(self):
        with patch.object(reception, "advanced_lots_enabled", return_value=False):
            detail = reception.reception_detail(self.db, self.shipment_id, "ASISTENTE_RECEPCION")
        refs = detail["accounting_refs"]
        self.assertEqual([ref["ip_reference"] for ref in refs], ["IP-1", "IP-2"])
        self.assertEqual([ref["em_status"] for ref in refs], ["EM 0/1", "EM 0/1"])

        with patch.object(reception, "advanced_lots_enabled", return_value=False):
            detail = reception.update_reception_references(
                self.db,
                self.shipment_id,
                {"reference_updates": [{"id": refs[0]["id"], "ip_key": "IP1", "em_number": "EM-1"}]},
                "worker",
                "ASISTENTE_RECEPCION",
            )
        by_ip = {ref["ip_reference"]: ref for ref in detail["accounting_refs"]}
        self.assertEqual(by_ip["IP-1"]["em_status"], "EM COMPLETAS")
        self.assertEqual(by_ip["IP-2"]["em_status"], "EM 0/1")
        self.assertEqual(detail["accounting_status"], "PENDIENTE EM")

        with patch.object(reception, "advanced_lots_enabled", return_value=False):
            detail = reception.update_reception_references(
                self.db,
                self.shipment_id,
                {"reference_updates": [{"id": refs[0]["id"], "ip_key": "IP2", "em_number": "EM-2"}]},
                "worker",
                "ASISTENTE_RECEPCION",
            )
        self.assertEqual(detail["accounting_status"], "EM REGISTRADA")
        self.assertEqual(detail["app_status"], "CERRADO")


if __name__ == "__main__":
    unittest.main()
