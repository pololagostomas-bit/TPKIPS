"""The Importations Cliente cell is authoritative, not the OV customer."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook
from backend import app
from backend.services import reception
from backend.services.cloud_import_policy import documentary_only


class ImportationCustomerTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        db_path = patch.object(app, "DB_PATH", Path(self.scratch.name) / "qa.sqlite")
        db_path.start()
        self.addCleanup(db_path.stop)
        mail = patch.dict("os.environ", {"TRITON_MAIL_ENABLED": "0"})
        mail.start()
        self.addCleanup(mail.stop)
        app.init_db()

    def workbook(self, customers, header="Cliente", ov="QA-OV"):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "COMPRADOR QA"
        sheet.append(["GUIA DE IMPORTACION", "CODIGO", "OV", "CANTIDAD SOLICITADA",
                      "MODO DE TRANSPORTE"] + ([header] if header else []))
        for name in customers:
            sheet.append(["QA-BL", "QA-NP", ov, 5, "AEREO"] + ([name] if header else []))
        return workbook

    def load(self, workbook):
        self.addCleanup(workbook.close)
        with app.db() as connection:
            context = documentary_only.set(True)
            try:
                return reception.import_reception_workbook(connection, workbook, "qa.xlsx", "qa.admin", "ADMINISTRADOR")
            finally:
                documentary_only.reset(context)

    def lines(self):
        with app.db() as connection:
            sid = connection.execute("SELECT id FROM reception_shipments WHERE bl_awb='QA-BL'").fetchone()[0]
            return reception.reception_detail(connection, sid, "ADMINISTRADOR", "qa.admin")["lines"]

    def test_cliente_is_stored_per_row_even_with_same_np_and_ov(self):
        self.load(self.workbook([" Cliente uno & compania ", "Cliente dos"]))
        self.assertEqual([line["customer_name"] for line in self.lines()], ["Cliente uno & compania", "Cliente dos"])

    def test_header_normalizes_case_spaces_and_newlines(self):
        self.load(self.workbook(["Cliente QA"], header=" cliente\n "))
        self.assertEqual(self.lines()[0]["customer_name"], "Cliente QA")

    def test_customer_does_not_depend_on_a_known_or_single_ov(self):
        for ov in ("QA-UNKNOWN", "QA-OV1, QA-OV2", ""):
            with self.subTest(ov=ov):
                self.load(self.workbook(["Cliente de importaciones"], ov=ov))
                self.assertEqual(self.lines()[-1]["customer_name"], "Cliente de importaciones")

    def test_missing_or_empty_cliente_never_uses_the_orders_name(self):
        with app.db() as connection:
            connection.execute("""INSERT INTO orders (sap_ov,customer_name,app_status,created_at,updated_at)
                VALUES ('QA-OV','Nombre incorrecto de OV','ASIGNADO','2026-10-12','2026-10-12')""")
        for header, name in ((None, "Ignored"), ("Cliente", None), ("Cliente", "   ")):
            with self.subTest(header=header, name=name):
                self.load(self.workbook([name], header=header))
                self.assertEqual(self.lines()[0]["customer_name"], "")

    def test_reimport_updates_or_clears_name_without_duplicating_or_resetting_work(self):
        self.load(self.workbook(["Cliente inicial"]))
        line_id = self.lines()[0]["id"]
        with app.db() as connection:
            connection.execute("UPDATE reception_lines SET received_qty=3,final_location='BIN-01',count_location_saved=1 WHERE id=?", (line_id,))
            connection.execute("UPDATE reception_shipments SET app_status='CERRADO',received_packages=2")
        for name in ("Cliente corregido", None):
            result = self.load(self.workbook([name]))
            self.assertEqual(result["lines_created"], 0)
            self.assertEqual(result["lines_updated"], 1)
            line = self.lines()[0]
            self.assertEqual(line["id"], line_id)
            self.assertEqual(line["customer_name"], name or "")
            self.assertEqual(line["received_qty"], 3)
            self.assertEqual(line["final_location"], "BIN-01")
            with app.db() as connection:
                self.assertEqual(connection.execute("SELECT app_status FROM reception_shipments").fetchone()[0], "CERRADO")

    def test_bytes_upload_uses_the_same_customer_mapping(self):
        workbook = self.workbook(["Cliente del archivo"])
        content = io.BytesIO()
        workbook.save(content)
        workbook.close()
        with app.db() as connection:
            reception.import_reception_excel_bytes(connection, content.getvalue(), "qa.xlsx", "qa.admin", "ADMINISTRADOR")
        self.assertEqual(self.lines()[0]["customer_name"], "Cliente del archivo")

    def test_multiple_sheets_keep_their_own_customer(self):
        workbook = self.workbook(["Cliente uno"])
        other = workbook.copy_worksheet(workbook.active)
        other.title = "COMPRADOR OTRO"
        other.cell(2, 6, "Cliente dos")
        self.load(workbook)
        self.assertEqual([line["customer_name"] for line in self.lines()], ["Cliente uno", "Cliente dos"])

    def test_schema_upgrade_defaults_old_lines_to_blank_and_is_idempotent(self):
        self.load(self.workbook([None]))
        with app.db() as connection:
            connection.execute("ALTER TABLE reception_lines DROP COLUMN customer_name")
            connection.execute("UPDATE reception_lines SET received_qty=3")
            reception.init_reception_schema(connection)
            reception.init_reception_schema(connection)
            row = connection.execute("SELECT customer_name,received_qty FROM reception_lines").fetchone()
            self.assertEqual(tuple(row), ("", 3))


if __name__ == "__main__":
    unittest.main()
