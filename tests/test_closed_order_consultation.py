import unittest
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

import app


class ClosedOrderConsultationTest(unittest.TestCase):
    def test_139716_is_saved_as_closed_and_searchable(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Hoja3"
        sheet.append([
            "STATUS", "Número de documento", "Status de Documento", "N° de Línea",
            "Fecha de contabilización", "Código de cliente/proveedor",
            "Nombre de cliente/proveedor", "Número de artículo", "Descripción artículo/serv.",
            "Grupo de Articulo", "Almacen", "Cantidad", "CostoUnitario", "CostoTotal",
            "Tipo de Atención", "FechaCrea_OV", "HoraCrea_OV", "Situacion de Maquina",
        ])
        for status, item_code in (("FACTURA DE DEUDORES", "14980439"), ("OV ABIERTA", "14980439")):
            sheet.append([
                status, 139716, "Cerrado", 1, datetime(2026, 1, 7), "C20535936669",
                "TRITON TRADING S.A", item_code, "CONVERSION KIT", "REPUESTOS", 1,
                1, 132.23, 132.23, "SELECCIONAR", datetime(2026, 1, 7), 1159,
                "SIN SELECCIONAR",
            ])

        temp_dir = Path(__file__).with_name(".tmp-closed-order")
        temp_dir.mkdir(exist_ok=True)
        excel_path = temp_dir / "QUERYOVS0709.xlsx"
        try:
            workbook.save(excel_path)
            db_path = Path(__file__).with_name(".wms-closed-order-test.db")
            db_path.unlink(missing_ok=True)
            original_db = app.DB_PATH
            app.DB_PATH = db_path
            try:
                app.init_db()
                result = app.import_excel(excel_path, reset=True)
                self.assertEqual(result["closed_orders_updated"], 1)
                with app.db() as connection:
                    order = connection.execute(
                        "SELECT app_status, document_status, sap_open_sku_count "
                        "FROM orders WHERE sap_ov = '139716'"
                    ).fetchone()
                    self.assertEqual(order["app_status"], "CERRADO SAP")
                    self.assertEqual(order["document_status"], "Cerrado")
                    self.assertEqual(order["sap_open_sku_count"], 0)
                    self.assertEqual(
                        connection.execute(
                            "SELECT COUNT(*) FROM attentions WHERE sap_ov = '139716'"
                        ).fetchone()[0],
                        0,
                    )
                results = app.orders_payload(search="139716", role="ADMINISTRADOR")
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["app_status"], "CERRADO SAP")
            finally:
                app.DB_PATH = original_db
                db_path.unlink(missing_ok=True)
                excel_path.unlink(missing_ok=True)
                temp_dir.rmdir()
        finally:
            workbook.close()


if __name__ == "__main__":
    unittest.main()
