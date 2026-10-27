"""Count destinations, readonly confirmation and per-line importation customers."""
import sqlite3
import unittest
from unittest.mock import patch

from backend.services import reception
from backend.services.traceability import init_traceability_schema


class CountLocationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        reception.init_reception_schema(self.db)
        init_traceability_schema(self.db)
        self.db.execute("CREATE TABLE order_importation_refs (bl_awb TEXT, sap_ov TEXT, transport_type TEXT)")
        self.db.execute("CREATE TABLE orders (sap_ov TEXT PRIMARY KEY, customer_name TEXT)")
        self.db.execute("INSERT INTO orders VALUES ('OV-1', 'Cliente uno')")
        self.db.execute("INSERT INTO orders VALUES ('OV-2', 'Cliente dos')")
        self.stock_qty = 12
        self.stock = patch.object(reception, "global_stock_summary", side_effect=self.stock_value)
        self.stock.start()
        self.addCleanup(self.stock.stop)
        self.sid = self.db.execute(
            """INSERT INTO reception_shipments
               (bl_awb,app_status,received_packages,current_assistant,current_auxiliary,created_at,updated_at)
               VALUES ('QA-COUNT','REVISION SISTEMA',2,'receiver','auxiliary','2026-10-12','2026-10-12')"""
        ).lastrowid
        self.lid = self.db.execute(
            """INSERT INTO reception_lines (shipment_id,np_code,ov_number,expected_qty,default_location,customer_name)
               VALUES (?,'NP-QA','OV-1',8,'SAP-01','Cliente de importaciones')""", (self.sid,)
        ).lastrowid
        self.attention = reception._ensure_reception_attention(
            self.db, self.db.execute("SELECT * FROM reception_shipments WHERE id=?", (self.sid,)).fetchone(), "receiver"
        )["id"]

    def stock_value(self, *_args):
        return {"stock_cut_qty": self.stock_qty, "stock_available_qty": self.stock_qty,
                "stock_default_location": "CUT-01"}

    def detail(self, attention=None):
        return reception.reception_detail(self.db, self.sid, "ASISTENTE_RECEPCION", "receiver",
                                           attention or self.attention)

    def count(self, location, attention=None):
        return reception.update_reception_line_quantity(
            self.db, self.sid, self.lid,
            {"received_qty": 3, "count_location": location, "attention_id": attention or self.attention},
            "receiver", "ASISTENTE_RECEPCION",
        )

    def location_stage(self):
        self.db.execute("UPDATE reception_shipments SET app_status='UBICACION' WHERE id=?", (self.sid,))
        self.db.execute("UPDATE reception_attentions SET app_status='UBICACION' WHERE id=?", (self.attention,))

    def confirm(self, **values):
        return reception.update_reception_line_locations(
            self.db, self.sid,
            {"attention_id": self.attention, "locations": [{"line_id": self.lid, "confirmed": True, **values}]},
            "receiver", "ASISTENTE_RECEPCION",
        )

    def test_saved_count_location_does_not_follow_a_new_stock_cut(self):
        line = self.count("BIN-09")["lines"][0]
        self.assertEqual(line["final_location"], "BIN-09")
        self.assertEqual(line["count_location_saved"], 1)
        self.stock_qty = 0
        self.assertEqual(self.detail()["lines"][0]["final_location"], "BIN-09")
        self.location_stage()
        self.assertEqual(self.confirm()["lines"][0]["final_location"], "BIN-09")

    def test_no_stock_explicit_blank_is_manual_and_survives_a_new_cut(self):
        self.stock_qty = 0
        self.assertEqual(self.detail()["lines"][0]["final_location"], "")
        self.count("")
        self.stock_qty = 20
        line = self.detail()["lines"][0]
        self.assertEqual(line["final_location"], "")
        self.assertEqual(line["count_location_manual"], 1)
        self.location_stage()
        with self.assertRaises(ValueError):
            self.confirm()
        line = self.confirm(final_location='REAL-BIN')["lines"][0]
        self.assertEqual(line["final_location"], "REAL-BIN")
        self.assertEqual(line["final_location_confirmed"], 1)
        result = reception.change_reception_status(
            self.db, self.sid, {"status": "VALIDACION", "attention_id": self.attention},
            "receiver", "ASISTENTE_RECEPCION",
        )
        self.assertEqual(result["app_status"], "VALIDACION")

    def test_blank_with_stock_still_requires_a_count_destination(self):
        self.count("")
        self.location_stage()
        with self.assertRaisesRegex(ValueError, "ubicación final"):
            self.confirm()

    def test_em_requires_saved_destination_when_stock_exists(self):
        self.count("")
        with patch.object(reception, "_accounting_status_for_shipment", return_value="PENDIENTE EM"):
            with self.assertRaisesRegex(PermissionError, "ubicación.*Inicio de conteo"):
                reception.change_reception_status(
                    self.db, self.sid, {"status": "EM", "attention_id": self.attention},
                    "receiver", "ASISTENTE_RECEPCION",
                )
        self.assertEqual(self.detail()["app_status"], "REVISION SISTEMA")

    def test_em_allows_saved_handwritten_blank_without_stock(self):
        self.stock_qty = 0
        self.count("")
        with patch.object(reception, "_accounting_status_for_shipment", return_value="PENDIENTE EM"):
            result = reception.change_reception_status(
                self.db, self.sid, {"status": "EM", "attention_id": self.attention},
                "receiver", "ASISTENTE_RECEPCION",
            )
        self.assertEqual(result["app_status"], "EM")
        self.assertEqual(result["lines"][0]["final_location"], "")

    def test_invalid_last_confirmation_does_not_save_earlier_items(self):
        self.count("BIN-09")
        self.location_stage()
        with self.assertRaises(ValueError):
            reception.update_reception_line_locations(
                self.db, self.sid, {"attention_id": self.attention, "locations": [
                    {"line_id": self.lid, "confirmed": True},
                    {"line_id": 999999, "confirmed": True},
                ]}, "receiver", "ASISTENTE_RECEPCION",
            )
        self.assertEqual(self.detail()["lines"][0]["final_location_confirmed"], 0)

    def test_resaving_blank_count_does_not_reclassify_the_saved_stock_snapshot(self):
        self.stock_qty = 0
        self.count("")
        self.stock_qty = 20
        line = self.count("")["lines"][0]
        self.assertEqual(line["count_location_manual"], 1)
        self.assertEqual(line["final_location"], "")
        self.location_stage()
        with self.assertRaises(ValueError):
            self.confirm()

    def test_multiple_ovs_keep_the_customer_from_the_importation_line(self):
        self.db.execute("UPDATE reception_lines SET ov_number='OV-1, OV-2' WHERE id=?", (self.lid,))
        self.assertEqual(self.detail()["lines"][0]["customer_name"], "Cliente de importaciones")

    def test_location_step_can_save_a_new_destination_for_worker_and_admin(self):
        self.count("BIN-09")
        self.location_stage()
        for role in ("ASISTENTE_RECEPCION", "ADMINISTRADOR"):
            with self.subTest(role=role):
                reception.update_reception_line_locations(
                    self.db, self.sid, {"attention_id": self.attention,
                    "locations": [{"line_id": self.lid, "final_location": "OTHER", "confirmed": True}]},
                    "receiver", role,
                )
        self.assertEqual(self.detail()["lines"][0]["final_location"], "OTHER")

    def test_confirm_is_only_allowed_in_the_location_stage(self):
        self.count("BIN-09")
        with self.assertRaises(PermissionError):
            self.confirm()
        self.location_stage()
        self.confirm(final_location="BIN-09")  # compatible readonly old payload

    def test_count_edits_are_rejected_after_count(self):
        self.count("BIN-09")
        self.location_stage()
        with self.assertRaises(PermissionError):
            self.count("OTHER")

    def test_invalid_count_locations_do_not_change_quantities(self):
        for bad in ("X" * 121, "A\nB", "A\x00B", 9):
            with self.subTest(value=repr(bad)), self.assertRaisesRegex(ValueError, "ubicación de conteo"):
                self.count(bad)
        self.assertEqual(self.detail()["lines"][0]["attention_verified_qty"], 0)

    def test_each_arrival_keeps_its_own_destination(self):
        self.count("FIRST")
        shipment = self.db.execute("SELECT * FROM reception_shipments WHERE id=?", (self.sid,)).fetchone()
        second = reception._create_reception_attention(self.db, shipment, None, "receiver", "REVISION SISTEMA")["id"]
        self.count("SECOND", second)
        self.assertEqual(self.detail(self.attention)["lines"][0]["final_location"], "FIRST")
        self.assertEqual(self.detail(second)["lines"][0]["final_location"], "SECOND")

    def test_foreign_attention_and_foreign_line_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "no pertenece"):
            self.count("OTHER", 999999)
        self.location_stage()
        with self.assertRaises(ValueError):
            reception.update_reception_line_locations(
                self.db, self.sid, {"attention_id": self.attention,
                "locations": [{"line_id": 999999, "confirmed": True}]},
                "receiver", "ASISTENTE_RECEPCION",
            )

    def test_customer_comes_from_importations_not_the_ov_or_another_bl_link(self):
        self.db.execute("INSERT INTO order_importation_refs VALUES ('QA-COUNT','OV-2','AEREO')")
        self.assertEqual(self.detail()["lines"][0]["customer_name"], "Cliente de importaciones")
        self.db.execute("UPDATE reception_lines SET ov_number='OV-UNKNOWN' WHERE id=?", (self.lid,))
        self.assertEqual(self.detail()["lines"][0]["customer_name"], "Cliente de importaciones")

    def test_customer_does_not_require_an_ov_cut(self):
        self.db.execute("DROP TABLE orders")
        self.assertEqual(self.detail()["lines"][0]["customer_name"], "Cliente de importaciones")

    def test_nonconformity_returns_to_count_without_discarding_quantities(self):
        self.count("BIN-09")
        self.location_stage()
        self.confirm()
        self.db.execute("UPDATE reception_shipments SET app_status='VALIDACION' WHERE id=?", (self.sid,))
        self.db.execute("UPDATE reception_attentions SET app_status='VALIDACION' WHERE id=?", (self.attention,))
        result = reception.change_reception_status(
            self.db, self.sid, {"status": "UBICACION", "validation_result": "NO CONFORME",
                               "attention_id": self.attention},
            "receiver", "ASISTENTE_RECEPCION",
        )
        self.assertEqual(result["app_status"], "REVISION SISTEMA")
        self.assertEqual(result["lines"][0]["attention_verified_qty"], 3)
        self.assertEqual(result["lines"][0]["final_location"], "BIN-09")
        self.assertEqual(result["lines"][0]["final_location_confirmed"], 0)

    def test_schema_upgrade_is_idempotent_and_preserves_old_destinations(self):
        self.db.execute("UPDATE reception_lines SET final_location='LEGACY' WHERE id=?", (self.lid,))
        reception.init_reception_schema(self.db)
        reception.init_reception_schema(self.db)
        self.assertEqual(self.detail()["lines"][0]["final_location"], "LEGACY")
        self.assertEqual(self.detail()["lines"][0]["count_location_saved"], 0)


if __name__ == "__main__":
    unittest.main()
