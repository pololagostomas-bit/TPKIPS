"""Regression: each FR in a reception requires its own EM."""

import sqlite3
import unittest
from unittest.mock import patch

from backend.services import reception
from backend.services.traceability import init_traceability_schema


class ReceptionEMPerReferenceTests(unittest.TestCase):
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
            self.db, {"bl_awb": "AWB-MULTI-EM"}, "admin", "ADMINISTRADOR"
        )["id"]
        self.db.executemany(
            "INSERT INTO reception_accounting_refs (shipment_id, source_key, ip_reference, fr_number, created_at, updated_at) VALUES (?, ?, ?, ?, '2026-01-01', '2026-01-01')",
            [
                (self.shipment_id, "ref-1", "IP-1", "FR-1"),
                (self.shipment_id, "ref-2", "IP-2", "FR-2"),
            ],
        )
        self.db.executemany(
            "INSERT INTO reception_lines (shipment_id, np_code, ip_reference, expected_qty, received_qty) VALUES (?, ?, ?, 1, 1)",
            [(self.shipment_id, "NP-1", "IP-1"), (self.shipment_id, "NP-2", "IP-2")],
        )
        self.db.execute(
            "INSERT INTO reception_attentions (shipment_id, sequence_no, app_status, created_at, updated_at) VALUES (?, 1, 'EM', ?, ?)",
            (self.shipment_id, "2026-01-01", "2026-01-01"),
        )
        attention_id = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        line_ids = [row[0] for row in self.db.execute(
            "SELECT id FROM reception_lines WHERE shipment_id=? ORDER BY id", (self.shipment_id,)
        ).fetchall()]
        self.db.executemany(
            "INSERT INTO reception_attention_lines (attention_id, reception_line_id, planned_qty, verified_qty) VALUES (?, ?, 1, 1)",
            [(attention_id, line_id) for line_id in line_ids],
        )
        self.db.execute(
            "UPDATE reception_shipments SET app_status='EM', current_assistant='worker', current_auxiliary='aux' WHERE id=?",
            (self.shipment_id,),
        )
        self.db.commit()

    def test_saves_one_em_for_each_fr_and_updates_summary(self):
        refs = self.db.execute(
            "SELECT id FROM reception_accounting_refs WHERE shipment_id=? ORDER BY id",
            (self.shipment_id,),
        ).fetchall()
        with patch.object(reception, "advanced_lots_enabled", return_value=False):
            detail = reception.update_reception_references(
                self.db,
                self.shipment_id,
                {
                    "reference_updates": [
                        {"id": refs[0]["id"], "em_number": "EM-1"},
                        {"id": refs[1]["id"], "em_number": "EM-2"},
                    ]
                },
                "worker",
                "ASISTENTE_RECEPCION",
            )
        values = [row["em_number"] for row in detail["accounting_refs"]]
        self.assertEqual(values, ["EM-1", "EM-2"])
        self.assertEqual(detail["accounting_status"], "EM REGISTRADA")

    def test_same_fr_requires_second_em_for_second_partial_attention(self):
        self.db.execute(
            "UPDATE reception_attention_lines SET verified_qty=0 WHERE reception_line_id=(SELECT id FROM reception_lines WHERE ip_reference='IP-2')"
        )
        self.db.execute(
            "UPDATE reception_lines SET received_qty=0 WHERE ip_reference='IP-2'"
        )
        ref_id = self.db.execute(
            "SELECT id FROM reception_accounting_refs WHERE source_key='ref-1'"
        ).fetchone()[0]
        line_id = self.db.execute(
            "SELECT id FROM reception_lines WHERE ip_reference='IP-1'"
        ).fetchone()[0]
        first_attention = self.db.execute(
            "SELECT id FROM reception_attentions WHERE sequence_no=1"
        ).fetchone()[0]
        self.db.execute(
            "INSERT INTO reception_accounting_ems (accounting_ref_id, attention_id, em_number, username, created_at) VALUES (?, ?, 'EM-1', 'worker', '2026-01-01')",
            (ref_id, first_attention),
        )
        self.db.execute(
            "INSERT INTO reception_attentions (shipment_id, sequence_no, app_status, created_at, updated_at) VALUES (?, 2, 'EM', '2026-01-02', '2026-01-02')",
            (self.shipment_id,),
        )
        second_attention = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.db.execute(
            "INSERT INTO reception_attention_lines (attention_id, reception_line_id, planned_qty, verified_qty) VALUES (?, ?, 1, 1)",
            (second_attention, line_id),
        )
        self.db.commit()
        self.assertEqual(
            reception._accounting_status_for_shipment(self.db, self.shipment_id),
            "PENDIENTE EM",
        )
        self.db.execute(
            "INSERT INTO reception_accounting_ems (accounting_ref_id, attention_id, em_number, username, created_at) VALUES (?, ?, 'EM-2', 'worker', '2026-01-02')",
            (ref_id, second_attention),
        )
        self.db.commit()
        self.assertEqual(
            reception._accounting_status_for_shipment(self.db, self.shipment_id),
            "EM REGISTRADA",
        )

    def test_empty_active_attention_does_not_hide_previous_received_units(self):
        """Una nueva atención vacía no debe cerrar una FR anterior sin EM."""
        first_attention = self.db.execute(
            "SELECT id FROM reception_attentions WHERE sequence_no=1"
        ).fetchone()[0]
        self.db.execute(
            "UPDATE reception_attention_lines SET verified_qty=0 WHERE attention_id=?",
            (first_attention,),
        )
        self.db.execute(
            "UPDATE reception_lines SET received_qty=1 WHERE ip_reference='IP-1'"
        )
        self.db.execute(
            "INSERT INTO reception_attentions (shipment_id, sequence_no, app_status, created_at, updated_at) VALUES (?, 2, 'EM', '2026-01-02', '2026-01-02')",
            (self.shipment_id,),
        )
        second_attention = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        active_attention = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        line_id = self.db.execute(
            "SELECT id FROM reception_lines WHERE ip_reference='IP-1'"
        ).fetchone()[0]
        self.db.execute(
            "INSERT INTO reception_attention_lines (attention_id, reception_line_id, planned_qty, verified_qty) VALUES (?, ?, 1, 0)",
            (active_attention, line_id),
        )
        self.db.commit()

        reference = self.db.execute(
            "SELECT * FROM reception_accounting_refs WHERE source_key='ref-1'"
        ).fetchone()
        self.assertTrue(
            reception._accounting_ref_has_received_sku(
                self.db, self.shipment_id, reference, "IP1"
            )
        )
        self.assertEqual(
            reception._accounting_status_for_shipment(self.db, self.shipment_id),
            "PENDIENTE EM",
        )

    def test_pending_em_can_continue_this_attention_without_closing_accounting(self):
        attention_id = self.db.execute(
            "SELECT id FROM reception_attentions WHERE shipment_id=?", (self.shipment_id,)
        ).fetchone()[0]
        self.db.execute(
            "UPDATE reception_shipments SET accounting_status='PENDIENTE EM' WHERE id=?",
            (self.shipment_id,),
        )
        self.db.commit()
        with self.assertRaisesRegex(PermissionError, "EM"):
            reception.change_reception_status(
                self.db, self.shipment_id,
                {"status": "UBICACION", "attention_id": attention_id},
                "worker", "ASISTENTE_RECEPCION",
            )

        detail = reception.change_reception_status(
            self.db, self.shipment_id,
            {"status": "UBICACION", "attention_id": attention_id, "allow_pending_em": True},
            "worker", "ASISTENTE_RECEPCION",
        )
        self.assertEqual(detail["app_status"], "UBICACION")
        self.assertEqual(detail["accounting_status"], "PENDIENTE EM")
        note = self.db.execute(
            "SELECT reason FROM reception_history WHERE shipment_id=? ORDER BY id DESC LIMIT 1",
            (self.shipment_id,),
        ).fetchone()[0]
        self.assertIn("referencia sin EM queda pendiente", note)

    def test_em_is_saved_to_the_selected_arrival_attention(self):
        second_attention = reception._create_reception_attention(
            self.db,
            self.db.execute("SELECT * FROM reception_shipments WHERE id=?", (self.shipment_id,)).fetchone(),
            None,
            "worker",
            initial_status="EM",
        )
        self.db.execute(
            """UPDATE reception_attention_lines SET verified_qty=1
                 WHERE attention_id=? AND reception_line_id=(
                   SELECT id FROM reception_lines WHERE shipment_id=? AND ip_reference='IP-2'
                 )""",
            (second_attention["id"], self.shipment_id),
        )
        self.db.commit()
        ref_id = self.db.execute(
            "SELECT id FROM reception_accounting_refs WHERE source_key='ref-2'"
        ).fetchone()[0]

        reception.update_reception_references(
            self.db, self.shipment_id,
            {
                "attention_id": second_attention["id"],
                "reference_updates": [{"id": ref_id, "ip_key": "IP2", "em_number": "EM-SECOND"}],
            },
            "worker", "ASISTENTE_RECEPCION",
        )
        saved = self.db.execute(
            "SELECT attention_id FROM reception_accounting_ems WHERE em_number='EM-SECOND'"
        ).fetchone()
        self.assertEqual(saved["attention_id"], second_attention["id"])

    def test_worker_can_correct_em_when_reopened_at_em_stage(self):
        ref_id = self.db.execute(
            "SELECT id FROM reception_accounting_refs WHERE source_key='ref-1'"
        ).fetchone()[0]
        attention_id = self.db.execute(
            "SELECT id FROM reception_attentions WHERE shipment_id=? AND sequence_no=1",
            (self.shipment_id,),
        ).fetchone()[0]
        self.db.execute(
            "UPDATE reception_shipments SET app_status='UBICACION' WHERE id=?",
            (self.shipment_id,),
        )
        self.db.execute(
            "UPDATE reception_attentions SET app_status='UBICACION' WHERE id=?",
            (attention_id,),
        )
        self.db.execute(
            """INSERT INTO reception_accounting_ems
               (accounting_ref_id, ip_reference_key, attention_id, em_number, username, created_at)
               VALUES (?, 'IP1', ?, 'EM-TYPO', 'worker', '2026-01-01')""",
            (ref_id, attention_id),
        )
        em_id = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.db.commit()

        with patch.object(reception, "advanced_lots_enabled", return_value=False):
            reopened = reception.rewind_reception_stage(
                self.db,
                self.shipment_id,
                {
                    "status": "EM",
                    "reason": "Corregir EM de esta atención",
                    "attention_id": attention_id,
                },
                "admin",
                "ADMINISTRADOR",
            )
            self.assertEqual(reopened["app_status"], "EM")
            self.assertEqual(reopened["attention_id"], attention_id)
            detail = reception.update_reception_references(
                self.db,
                self.shipment_id,
                {
                    "reference_updates": [
                        {"id": ref_id, "em_id": em_id, "ip_key": "IP1", "em_number": "EM-CORRECTA"}
                    ]
                },
                "worker",
                "ASISTENTE_RECEPCION",
            )

        saved = self.db.execute(
            "SELECT em_number, attention_id FROM reception_accounting_ems WHERE id=?",
            (em_id,),
        ).fetchone()
        self.assertEqual(saved["em_number"], "EM-CORRECTA")
        self.assertEqual(saved["attention_id"], attention_id)
        self.assertEqual(detail["accounting_refs"][0]["em_numbers"], ["EM-CORRECTA"])
        history = self.db.execute(
            "SELECT new_value, reason FROM reception_history WHERE shipment_id=? AND field_name=? ORDER BY id DESC LIMIT 1",
            (self.shipment_id, f"referencia:{ref_id}:em_number"),
        ).fetchone()
        self.assertEqual(history["new_value"], "EM-CORRECTA")
        self.assertIn("corregida", history["reason"])

    def test_worker_cannot_edit_em_from_another_attention(self):
        ref_id = self.db.execute(
            "SELECT id FROM reception_accounting_refs WHERE source_key='ref-1'"
        ).fetchone()[0]
        self.db.execute(
            "INSERT INTO reception_attentions (shipment_id, sequence_no, app_status, created_at, updated_at) VALUES (?, 2, 'EM', '2026-01-02', '2026-01-02')",
            (self.shipment_id,),
        )
        second_attention = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        line_id = self.db.execute(
            "SELECT id FROM reception_lines WHERE shipment_id=? AND ip_reference='IP-1'",
            (self.shipment_id,),
        ).fetchone()[0]
        self.db.execute(
            "INSERT INTO reception_attention_lines (attention_id, reception_line_id, planned_qty, verified_qty) VALUES (?, ?, 1, 1)",
            (second_attention, line_id),
        )
        old_attention = self.db.execute(
            "SELECT id FROM reception_attentions WHERE shipment_id=? AND sequence_no=1",
            (self.shipment_id,),
        ).fetchone()[0]
        self.db.execute(
            """INSERT INTO reception_accounting_ems
               (accounting_ref_id, ip_reference_key, attention_id, em_number, username, created_at)
               VALUES (?, 'IP1', ?, 'EM-ANTERIOR', 'worker', '2026-01-01')""",
            (ref_id, old_attention),
        )
        em_id = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.db.commit()

        with self.assertRaisesRegex(PermissionError, "atención que estás trabajando"):
            reception.update_reception_references(
                self.db,
                self.shipment_id,
                {"attention_id": second_attention, "reference_updates": [{"id": ref_id, "em_id": em_id, "ip_key": "IP1", "em_number": "EM-OTRA"}]},
                "worker",
                "ASISTENTE_RECEPCION",
            )


if __name__ == "__main__":
    unittest.main()
