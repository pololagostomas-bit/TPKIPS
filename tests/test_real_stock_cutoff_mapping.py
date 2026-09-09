"""Regresión: una OV real debe mostrar el corte de la hoja de stock SAP."""

import unittest
from pathlib import Path

from openpyxl import Workbook

import app


class RealStockCutoffMappingTest(unittest.TestCase):
    """Protege el mapeo observado para OV 156528 y NP CLAVIJA3X32TIP44."""

    def test_stock_sheet_is_shown_for_the_matching_order_line(self):
        original_db = app.DB_PATH
        test_dir = Path(__file__).parent
        app.DB_PATH = test_dir / ".real-stock-cutoff.db"
        workbook_path = test_dir / ".real-stock-cutoff.xlsx"
        workbook_path.unlink(missing_ok=True)
        app.DB_PATH.unlink(missing_ok=True)
        try:
            book = Workbook()
            ovs = book.active
            ovs.title = "ovs"
            ovs.append([
                "STATUS", "Número de documento", "Status de Documento", "Grupo de Articulo",
                "Almacen", "N° de Línea", "Número de artículo", "Descripción artículo/serv.",
                "Cantidad", "Cant. Pendiente", "Fecha de contabilización",
            ])
            ovs.append([
                "OV ABIERTA", "156528", "Abierto", "REPUESTOS", 1, 1,
                "CLAVIJA3X32TIP44", "CLAVIJA 3X32 TIPO 44", 4, 4, "2026-09-08",
            ])
            stock = book.create_sheet("stock")
            stock.append([])
            stock.append([
                "Número de artículo", "Descripción del artículo", "Unidad de medida de inventario",
                "Primera ubicación", "En stock", "Comprometido", "Solicitado", "Disponible",
            ])
            stock.append(["Almacén", 1])
            # Valores observados en queryovs0809.xlsx para este NP.
            stock.append(["CLAVIJA3X32TIP44", "CLAVIJA 3X32 TIPO 44", "UNIDAD", "01-01-A", 4, 3, 0, 1])
            book.save(workbook_path)
            book.close()

            app.init_db()
            result = app.import_excel(workbook_path, reset=True, cutoff_at="2026-09-08T16:00:00")
            line = app.order_payload("156528")["lines"][0]

            self.assertEqual(result["stock_sheet"], "stock")
            self.assertEqual(line["item_code"], "CLAVIJA3X32TIP44")
            self.assertEqual(line["stock_source_qty"], 4)
            self.assertEqual(line["stock_free_qty"], 4)
        finally:
            app.DB_PATH.unlink(missing_ok=True)
            workbook_path.unlink(missing_ok=True)
            app.DB_PATH = original_db


if __name__ == "__main__":
    unittest.main()
