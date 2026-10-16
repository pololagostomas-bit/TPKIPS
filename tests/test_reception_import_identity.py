"""Changing PRE/OC updates documentary data without inventing another order."""
import unittest
from openpyxl import Workbook
from backend import app
from backend.services import reception
from tests import test_reception_importation_customer as fixtures


class ImportLineIdentityTests(unittest.TestCase):
    setUp = fixtures.ImportationCustomerTests.setUp
    load = fixtures.ImportationCustomerTests.load

    def workbook(self, rows):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "COMPRADOR QA"
        sheet.append(["GUIA DE IMPORTACION", "CODIGO", "PEDIDO TRITON", "OV", "ORDEN DE COMPRA", "CANTIDAD SOLICITADA"])
        for oc, ov, ip in rows:
            sheet.append(["QA-BL", "QA-NP", ip, ov, oc, 5])
        return workbook

    def rows(self):
        with app.db() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM reception_lines ORDER BY id")]

    def test_pre_to_approved_oc_keeps_id_and_is_idempotent_with_audit(self):
        self.load(self.workbook([("PRE-123", "OV-1", "IP-1")]))
        line_id = self.rows()[0]["id"]
        for oc in ("54321", "54321", "65432"):
            result = self.load(self.workbook([(oc, "OV-1", "IP-1")]))
            self.assertEqual((result["lines_created"], result["lines_updated"]), (0, 1))
            self.assertEqual([(row["id"], row["oc_number"]) for row in self.rows()], [(line_id, oc)])
        with app.db() as connection:
            changes = connection.execute(
                "SELECT old_value,new_value FROM reception_history WHERE field_name=? ORDER BY id", (f"linea:{line_id}:oc_number",)
            ).fetchall()
            self.assertEqual([tuple(row) for row in changes], [("PRE-123", "54321"), ("54321", "65432")])

    def test_no_ov_with_stable_ip_also_updates_in_place(self):
        self.load(self.workbook([("PRE", "", "IP-1")]))
        before = self.rows()[0]["id"]
        self.load(self.workbook([("54321", "", "IP-1")]))
        self.assertEqual([row["id"] for row in self.rows()], [before])

    def test_different_ovs_and_no_ov_are_distinct_orders(self):
        self.load(self.workbook([("PRE", "OV-1", "IP-1"), ("PRE", "OV-2", "IP-1"), ("PRE", "", "IP-1")]))
        before = {row["ov_number"]: row["id"] for row in self.rows()}
        self.load(self.workbook([("54321", "OV-1", "IP-1"), ("PRE", "OV-2", "IP-1"), ("PRE", "", "IP-1")]))
        self.assertEqual({row["ov_number"]: row["id"] for row in self.rows()}, before)

    def test_distinct_ips_do_not_merge(self):
        self.load(self.workbook([("PRE", "OV-1", "IP-1"), ("PRE", "OV-1", "IP-2")]))
        before = {row["ip_reference"]: row["id"] for row in self.rows()}
        self.load(self.workbook([("54321", "OV-1", "IP-2"), ("PRE", "OV-1", "IP-1")]))
        self.assertEqual({row["ip_reference"]: row["id"] for row in self.rows()}, before)

    def test_reserve_all_exact_matches_before_replacing_a_pre_in_same_group(self):
        self.load(self.workbook([("PRE", "OV-1", "IP-1"), ("12345", "OV-1", "IP-1")]))
        before = {row["oc_number"]: row["id"] for row in self.rows()}
        result = self.load(self.workbook([("54321", "OV-1", "IP-1"), ("12345", "OV-1", "IP-1")]))
        self.assertEqual(result["lines_created"], 0)
        self.assertEqual({row["oc_number"]: row["id"] for row in self.rows()}, {"54321": before["PRE"], "12345": before["12345"]})

    def test_a_pre_still_in_excel_and_an_additional_oc_are_not_one_line(self):
        self.load(self.workbook([("PRE", "OV-1", "IP-1")]))
        before = self.rows()[0]["id"]
        result = self.load(self.workbook([("54321", "OV-1", "IP-1"), ("PRE", "OV-1", "IP-1")]))
        self.assertEqual(result["lines_created"], 1)
        self.assertEqual(next(row["id"] for row in self.rows() if row["oc_number"] == "PRE"), before)

    def test_ambiguous_updates_fail_before_any_write_instead_of_guessing(self):
        self.load(self.workbook([("PRE-1", "OV-1", "IP-1"), ("PRE-2", "OV-1", "IP-1")]))
        before = self.rows()
        with app.db() as connection:
            history = connection.execute("SELECT COUNT(*) FROM reception_history").fetchone()[0]
            workbook = self.workbook([("54321", "OV-1", "IP-1"), ("65432", "OV-1", "IP-1")])
            try:
                with self.assertRaisesRegex(ValueError, "Actualizacion de OC ambigua"):
                    reception.import_reception_workbook(connection, workbook, "qa.xlsx", "qa.admin", "ADMINISTRADOR")
            finally:
                workbook.close()
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM reception_history").fetchone()[0], history)
        self.assertEqual(self.rows(), before)

    def test_no_ip_or_ov_cannot_silently_guess_an_identity(self):
        self.load(self.workbook([("PRE", "", "")]))
        before = self.rows()
        with self.assertRaisesRegex(ValueError, "Revisa IP/OV"):
            self.load(self.workbook([("54321", "", "")]))
        self.assertEqual(self.rows(), before)

    def test_moving_excel_rows_does_not_change_operational_identity(self):
        self.load(self.workbook([("PRE", "OV-1", "IP-1")]))
        before = self.rows()[0]["id"]
        workbook = self.workbook([("54321", "OV-1", "IP-1")])
        workbook.active.insert_rows(2, amount=4)
        self.load(workbook)
        self.assertEqual([(row["id"], row["source_row"]) for row in self.rows()], [(before, 6)])

    def test_reference_update_preserves_attention_scan_quantity_and_location(self):
        self.load(self.workbook([("PRE", "OV-1", "IP-1")]))
        old = self.rows()[0]
        with app.db() as connection:
            connection.execute("UPDATE reception_shipments SET app_status='REVISION SISTEMA',received_packages=1 WHERE id=?", (old["shipment_id"],))
            shipment = connection.execute("SELECT * FROM reception_shipments WHERE id=?", (old["shipment_id"],)).fetchone()
            attention = reception._create_reception_attention(connection, shipment, None, "qa.admin", "REVISION SISTEMA")
            connection.execute(
                """UPDATE reception_attention_lines SET verified_qty=3,final_location='BIN-QA',count_location_saved=1,
                   np_scanned_at='2026-10-15 09:00:00',np_scanned_by='qa.admin' WHERE attention_id=?""", (attention["id"],)
            )
            before = tuple(connection.execute("SELECT * FROM reception_attention_lines WHERE attention_id=?", (attention["id"],)).fetchone())
        self.load(self.workbook([("54321", "OV-1", "IP-1")]))
        self.assertEqual([row["id"] for row in self.rows()], [old["id"]])
        with app.db() as connection:
            self.assertEqual(tuple(connection.execute("SELECT * FROM reception_attention_lines WHERE attention_id=?", (attention["id"],)).fetchone()), before)


if __name__ == "__main__":
    unittest.main()
