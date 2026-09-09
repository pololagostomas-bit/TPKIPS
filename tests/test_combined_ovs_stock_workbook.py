"""Regresión: el query diario puede traer OVs y stock en hojas separadas."""

import unittest
from pathlib import Path

from openpyxl import Workbook

import app


class CombinedOvsStockWorkbookTest(unittest.TestCase):
    def test_imports_stock_sheet_as_global_cutoff(self):
        original_db = app.DB_PATH
        test_dir = Path(__file__).parent
        app.DB_PATH = test_dir / ".combined-ovs-stock.db"
        workbook_path = test_dir / ".combined-ovs-stock-query.xlsx"
        workbook_path.unlink(missing_ok=True)
        app.DB_PATH.unlink(missing_ok=True)
        try:
                book = Workbook()
                ovs = book.active
                ovs.title = "Detalle diario"
                ovs.append([
                    "STATUS", "Número de documento", "Status de Documento", "Grupo de Articulo",
                    "Almacen", "N° de Línea", "Número de artículo", "Descripción artículo/serv.",
                    "Cantidad", "Cant. Pendiente", "Fecha de contabilización",
                ])
                ovs.append(["OV ABIERTA", "OV-1", "Abierto", "REPUESTOS", 1, 1, "SKU-CORTE", "Repuesto", 2, 2, "2026-09-08"])
                stock = book.create_sheet("Corte SAP")
                stock.append([])
                stock.append(["Número de artículo", "Descripción del artículo", "Unidad de medida de inventario", "Primera ubicación", "En stock", "Comprometido", "Solicitado", "Disponible"])
                stock.append(["Almacén", 1])
                stock.append(["SKU-CORTE", "Repuesto", "UNIDAD", "01-01-A", 4, 3, 0, 1])
                book.save(workbook_path)
                book.close()

                app.init_db()
                result = app.import_excel(workbook_path, reset=True, cutoff_at="2026-09-08T16:00:00")
                payload = app.order_payload("OV-1")

                self.assertTrue(result["stock_updated"])
                self.assertEqual(result["stock_sheet"], "Corte SAP")
                self.assertEqual(payload["lines"][0]["stock_source_qty"], 4)
                self.assertEqual(payload["lines"][0]["stock_free_qty"], 4)
        finally:
            app.DB_PATH.unlink(missing_ok=True)
            workbook_path.unlink(missing_ok=True)
            app.DB_PATH = original_db


if __name__ == "__main__":
    unittest.main()
