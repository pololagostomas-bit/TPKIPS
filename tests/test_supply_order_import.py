import unittest
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

import app


class SupplyOrderImportTest(unittest.TestCase):
    def test_153088_with_supplies_is_imported(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Hoja3"
        sheet.append([
            "STATUS", "Número de documento", "Status de Documento", "N° de Línea",
            "Fecha de contabilización", "Código de cliente/proveedor",
            "Nombre de cliente/proveedor", "Número de artículo", "Descripción artículo/serv.",
            "Grupo de Articulo", "Descripción (Servicios)", "Almacen", "Cantidad", "CostoUnitario", "CostoTotal",
            "Tipo de Atención", "FechaCrea_OV", "HoraCrea_OV", "Situacion de Maquina",
        ])
        sheet.append([
            "OV ABIERTA", 153088, "Abierto", 1, datetime(2026, 7, 11),
            "C20535936669", "TRITON TRADING S.A", "CHA-REF-XXL",
            "CHALECO REFLECTIVO NARANJA TALLA XXL", "SUMINISTROS", None, 1, 1,
            45, 45, "TOTAL", datetime(2026, 7, 21), 822, "MAQUINA EN USO",
        ])
        sheet.append([
            "OV ABIERTA", 153088, "Abierto", 2, datetime(2026, 7, 11),
            "C20535936669", "TRITON TRADING S.A", None,
            "SERVICIO DE INSTALACION", "", "SERVICIO DE INSTALACION", 1, 1,
            10, 10, "TOTAL", datetime(2026, 7, 21), 822, "MAQUINA EN USO",
        ])

        temp_dir = Path(__file__).with_name(".tmp-supply-order")
        temp_dir.mkdir(exist_ok=True)
        excel_path = temp_dir / "QUERYOVS0709.xlsx"
        db_path = Path(__file__).with_name(".wms-supply-order-test.db")
        try:
            workbook.save(excel_path)
            db_path.unlink(missing_ok=True)
            original_db = app.DB_PATH
            app.DB_PATH = db_path
            try:
                app.init_db()
                result = app.import_excel(excel_path, reset=True)
                self.assertEqual(result["orders"], 1)
                with app.db() as connection:
                    order = connection.execute(
                        "SELECT app_status, customer_name, source_order_date FROM orders WHERE sap_ov = '153088'"
                    ).fetchone()
                    line = connection.execute(
                        "SELECT article_group, warehouse, is_pending_sap FROM order_lines "
                        "WHERE sap_ov = '153088'"
                    ).fetchone()
                    self.assertEqual(order["app_status"], "PENDIENTE")
                    self.assertEqual(order["source_order_date"], "2026-07-21 08:22:00")
                    self.assertEqual(line["article_group"], "SUMINISTROS")
                    self.assertEqual(line["warehouse"], "1")
                    self.assertEqual(line["is_pending_sap"], 1)
                    self.assertEqual(
                        connection.execute(
                            "SELECT COUNT(*) FROM order_lines WHERE sap_ov = '153088'"
                        ).fetchone()[0],
                        1,
                    )
                self.assertEqual(
                    len(app.orders_payload(search="153088", role="ADMINISTRADOR", creation_date="2026-07-21")),
                    1,
                )
                self.assertEqual(
                    len(app.orders_payload(search="153088", role="ADMINISTRADOR", creation_date="2026-07-22")),
                    0,
                )
            finally:
                app.DB_PATH = original_db
                db_path.unlink(missing_ok=True)
        finally:
            excel_path.unlink(missing_ok=True)
            temp_dir.rmdir()
            workbook.close()


if __name__ == "__main__":
    unittest.main()
