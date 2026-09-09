import sqlite3
import sys
import unittest
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

import app
from backend.services.reception import import_reception_workbook


class ReceptionArrivalImportTest(unittest.TestCase):
    def test_5096672696_is_arrived_when_source_confirms_it(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "SUSANA"
        sheet.append(
            [
                "TIPO DE COMPRA", "MARCA", "SOLICITANTE", "OV", "ORDEN DE COMPRA",
                "CODIGO", "DESCRIPCION", "CANTIDAD SOLICITADA", "CANTIDAD FACTURADA",
                "CANTIDAD PENDIENTE", "ESTADO POR NP", "PEDIDO TRITON", "STATUS",
                "GUIA DE IMPORTACION", "FECHA TRITON ESTIMADA", "FECHA CONFIRMADA TRITON",
            ]
        )
        sheet.append(
            [
                "REGULAR", "LIEBHERR", "NADIM DAGA", 140038, 76067, "12263990",
                "WIPER MOTOR", 1, 1, 0, "COMPLETO", "IP260049", "DISPONIBLE",
                5096672696, None, datetime(2026, 1, 28),
            ]
        )
        db_path = Path(__file__).with_name(".wms-reception-arrival-test.db")
        db_path.unlink(missing_ok=True)
        original_db = app.DB_PATH
        app.DB_PATH = db_path
        try:
            app.init_db()
            with app.db() as connection:
                result = import_reception_workbook(
                    connection, workbook, "IMPORTACIÓN DE REPUESTOS 0709.xlsx",
                    "admin.test", "ADMINISTRADOR",
                )
                shipment = connection.execute(
                    "SELECT app_status, condition_status, scheduled_date, first_arrival_at "
                    "FROM reception_shipments WHERE bl_awb = ?", ("5096672696",)
                ).fetchone()
                self.assertEqual(result["shipments"], 1)
                self.assertEqual(shipment["app_status"], "ARRIBADO")
                self.assertEqual(shipment["condition_status"], "ARRIBO REGISTRADO")
                self.assertEqual(shipment["scheduled_date"], "2026-01-28")
                self.assertEqual(shipment["first_arrival_at"], "2026-01-28")
                history = connection.execute(
                    "SELECT new_value FROM reception_history WHERE shipment_id = "
                    "(SELECT id FROM reception_shipments WHERE bl_awb = ?) "
                    "AND field_name = 'app_status' ORDER BY id DESC LIMIT 1",
                    ("5096672696",),
                ).fetchone()
                self.assertEqual(history["new_value"], "ARRIBADO")
        finally:
            app.DB_PATH = original_db
            db_path.unlink(missing_ok=True)
            workbook.close()


if __name__ == "__main__":
    unittest.main()
