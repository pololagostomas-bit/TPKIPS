"""Persisted, per-attention NP reads on a disposable in-memory database."""
import unittest
from unittest.mock import patch

from backend.services import reception
from tests import test_reception_count_locations as fixtures


class FastNpTests(unittest.TestCase):
    setUp = fixtures.CountLocationTests.setUp
    stock_value = fixtures.CountLocationTests.stock_value
    detail = fixtures.CountLocationTests.detail

    def scan(self, quantity=8, line=None, attention=None):
        return reception.update_reception_line_quantity(
            self.db, self.sid, line or self.lid,
            {"received_qty": quantity, "scan_np": True, "attention_id": attention or self.attention},
            "receiver", "ASISTENTE_RECEPCION",
        )

    def test_scan_records_actor_and_survives_schema_reload(self):
        line = self.scan()["lines"][0]
        self.assertTrue(line["np_scanned_at"])
        self.assertEqual(line["np_scanned_by"], "receiver")
        self.assertEqual(line["attention_verified_qty"], 8)
        reception.init_reception_schema(self.db)
        self.assertEqual(self.detail()["lines"][0]["np_scanned_at"], line["np_scanned_at"])

    def test_repeat_or_uncertain_retry_never_adds_or_overwrites_a_correction(self):
        first = self.scan()["lines"][0]["np_scanned_at"]
        reception.update_reception_line_quantity(
            self.db, self.sid, self.lid,
            {"attention_id": self.attention, "received_qty": 3}, "receiver", "ASISTENTE_RECEPCION",
        )
        line = self.scan()["lines"][0]
        self.assertEqual(line["attention_verified_qty"], 3)
        self.assertEqual(line["np_scanned_at"], first)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM reception_history WHERE field_name=?", (f"linea:{self.lid}:np_scan",)
        ).fetchone()[0], 1)

    def test_scan_marker_is_not_inherited_by_a_new_attention(self):
        self.scan()
        shipment = self.db.execute("SELECT * FROM reception_shipments WHERE id=?", (self.sid,)).fetchone()
        self.db.execute("UPDATE reception_attentions SET app_status='CERRADO' WHERE id=?", (self.attention,))
        second = reception._create_reception_attention(self.db, shipment, None, "receiver", "REVISION SISTEMA")
        self.assertFalse(self.detail(second["id"])["lines"][0]["np_scanned_at"])
        self.assertTrue(self.detail(self.attention)["lines"][0]["np_scanned_at"])

    def test_invalid_quantity_cannot_mark_a_read(self):
        for quantity in (None, "", True, -1, 1.5, "NaN", "Infinity", 9007199254740992):
            with self.subTest(quantity=quantity), self.assertRaises((ValueError, OverflowError)):
                self.scan(quantity)
        self.assertFalse(self.detail()["lines"][0]["np_scanned_at"])

    def test_scan_is_only_allowed_in_count_stage(self):
        self.db.execute("UPDATE reception_attentions SET app_status='EM' WHERE id=?", (self.attention,))
        with self.assertRaises(PermissionError):
            self.scan()

    def test_manual_zero_with_reason_records_a_real_missing_item_not_a_scan(self):
        data = {"attention_id": self.attention, "received_qty": 0, "reason": "No llego el repuesto"}
        line = reception.update_reception_line_quantity(
            self.db, self.sid, self.lid, data, "receiver", "ASISTENTE_RECEPCION",
        )["lines"][0]
        self.assertFalse(line["np_scanned_at"])
        self.assertEqual(line["np_unreceived_reason"], "No llego el repuesto")
        data.update(received_qty=3, reason="Llegada corregida")
        line = reception.update_reception_line_quantity(
            self.db, self.sid, self.lid, data, "receiver", "ASISTENTE_RECEPCION",
        )["lines"][0]
        self.assertFalse(line["np_unreceived_reason"])
        self.assertFalse(line["np_scanned_at"])

    def test_partial_scan_cannot_advance_to_em_and_full_scan_can(self):
        other = self.db.execute(
            "INSERT INTO reception_lines(shipment_id,np_code,expected_qty) VALUES (?,'NP-OTHER',2)",
            (self.sid,),
        ).lastrowid
        self.db.execute(
            "INSERT INTO reception_attention_lines(attention_id,reception_line_id,planned_qty) VALUES (?,?,2)",
            (self.attention, other),
        )
        self.scan()
        with patch.object(reception, "_accounting_status_for_shipment", return_value="PENDIENTE EM"):
            with self.assertRaisesRegex(PermissionError, "Faltan NP.*NP-OTHER"):
                reception.change_reception_status(
                    self.db, self.sid, {"status": "EM", "attention_id": self.attention},
                    "receiver", "ASISTENTE_RECEPCION",
                )
            self.scan(2, line=other)
            result = reception.change_reception_status(
                self.db, self.sid, {"status": "EM", "attention_id": self.attention},
                "receiver", "ASISTENTE_RECEPCION",
            )
            self.assertEqual(result["app_status"], "EM")

    def test_legacy_manual_api_without_scans_keeps_its_partial_receipt_path(self):
        other = self.db.execute(
            "INSERT INTO reception_lines(shipment_id,np_code,expected_qty) VALUES (?,'NP-LEGACY',2)",
            (self.sid,),
        ).lastrowid
        self.db.execute(
            "INSERT INTO reception_attention_lines(attention_id,reception_line_id,planned_qty) VALUES (?,?,2)",
            (self.attention, other),
        )
        for line, quantity, reason in ((self.lid, 0, "No llego"), (other, 2, "")):
            reception.update_reception_line_quantity(
                self.db, self.sid, line,
                {"received_qty": quantity, "reason": reason, "attention_id": self.attention},
                "receiver", "ASISTENTE_RECEPCION",
            )
        with patch.object(reception, "_accounting_status_for_shipment", return_value="PENDIENTE EM"):
            result = reception.change_reception_status(
                self.db, self.sid, {"status": "EM", "attention_id": self.attention},
                "receiver", "ASISTENTE_RECEPCION",
            )
        self.assertEqual(result["app_status"], "EM")


if __name__ == "__main__":
    unittest.main()
