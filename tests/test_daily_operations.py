"""Regresiones de la etapa 1; solo usa SQLite temporal y Excel sintéticos."""
import io
import tempfile
import uuid
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook
import app
from backend.services.daily_operations import data_status


HEADERS = ["STATUS", "Número de documento", "Status de Documento", "Grupo de Articulo", "Almacen", "N° de Línea", "Número de artículo", "Descripción artículo/serv.", "Cantidad", "Cant. Pendiente", "StockDisponible", "Tipo de Atención", "Fecha de contabilización"]


def excel(headers, rows):
    book = Workbook()
    sheet = book.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    content = io.BytesIO()
    book.save(content)
    book.close()
    return content.getvalue()


def dispatch(rows):
    return excel(HEADERS, [["OV ABIERTA", ov, status, "Repuestos", 1, line, sku, "Repuesto " + sku, amount, amount, stock, "PARCIAL", "2026-09-01"] for ov, line, sku, amount, stock, status in rows])


def load(content, source="dispatch", cutoff="2026-09-01T16:00:00"):
    return app.import_daily_excel(content, source + ".xlsx", source, cutoff, "admin.qa", "ADMINISTRADOR", reconcile_delivered=True)


def balance(ov, sku="SKU-A"):
    with app.db() as connection:
        return app.inventory_pool_status(connection, ov, sku, "1")


def assigned(ov, picker):
    attention = app.order_payload(ov)["attentions"][0]
    app.assign_attention(attention["id"], "current_picker", picker, "admin.qa", "ADMINISTRADOR")
    return attention["id"]


def reject(action, kind=(ValueError, PermissionError)):
    try:
        action()
    except kind:
        return
    raise AssertionError("La operación inválida no fue rechazada")


def run():
    old_db = app.DB_PATH
    with nullcontext(app.ROOT) as folder:
        test_db = Path(folder) / (".stage1-" + uuid.uuid4().hex + ".db")
        app.DB_PATH = test_db
        try:
            app.init_db()
            initial = dispatch([("1001", 0, "SKU-A", 6, 10, "Abierto"), ("1002", 0, "SKU-A", 4, 10, "Abierto")])
            load(initial)
            assert balance("1001")["source_total"] == 10, "No sumar stock repetido por OV"
            imports = excel(["GUIA DE IMPORTACION", "CODIGO", "DESCRIPCION", "OV", "MODO DE TRANSPORTE", "ORDEN DE COMPRA", "PEDIDO TRITON", "CANTIDAD"],
                [["AWB-01", "SKU-A", "Repuesto", "1002", "COURIER", "OC-1", "IP-1", 4]])
            result = load(imports, "importation")
            assert result["stock_updated"] is False
            assert balance("1001")["source_total"] == 10
            assert balance("1002")["free_qty"] == 0, "El compromiso por llegar no se puede pickear"
            with app.db() as connection:
                shipment = connection.execute("SELECT id FROM reception_shipments WHERE bl_awb='AWB-01'").fetchone()[0]
                connection.execute("UPDATE reception_shipments SET app_status='ARRIBADO', received_packages=1 WHERE id=?", (shipment,))
            assert balance("1001")["free_qty"] == 6, "Proteger unidades arribadas destinadas a otra OV"
            assert balance("1002")["free_qty"] == 0, "Arribado no significa recepción terminada"
            with app.db() as connection:
                connection.execute("UPDATE reception_shipments SET app_status='CERRADO' WHERE id=?", (shipment,))
            assert balance("1002")["free_qty"] == 4
            ordinary = assigned("1001", "picker.stock")
            aerial = assigned("1002", "picker.air")
            with patch("app.now", return_value="2026-09-02T09:00:00"):
                app.change_attention_status(ordinary, "EN PICKING", "picker.stock", "PICKER")
                app.change_attention_status(aerial, "EN PICKING", "picker.air", "PICKER")
                air_line = app.order_payload("1002")["attentions"][0]["lines"][0]
                assert air_line["picked_qty"] == 4, "Etapa 1 propone cantidades sin exigir lotes"
                assert balance("1001")["free_qty"] == 0
                app.change_attention_status(aerial, "PICKING FINALIZADO", "picker.air", "PICKER")
            duplicate = load(initial)
            assert duplicate["duplicate"]
            assert balance("1001")["free_qty"] == 0, "Reimportar no repone stock"
            load(initial, cutoff="2026-09-02T16:00:00")
            assert balance("1001")["reserved_total"] == 6
            assert balance("1001")["consumed_total"] == 4, "Pick sin entregar sigue descontado tras el corte"
            reject(lambda: load(initial, cutoff="2026-09-01T16:00:00"))
            assert load(imports, "importation")["duplicate"]
            assert balance("1001")["source_total"] == 10
            with patch("app.now", return_value="2026-09-03T09:00:00"):
                app.assign_attention(aerial, "current_guide", "guide.qa", "admin.qa", "ADMINISTRADOR")
                app.change_attention_status(aerial, "EN GUIADO", "guide.qa", "GUIADOR")
                app.change_attention_status(aerial, "GUIADO FINALIZADO", "guide.qa", "GUIADOR")
                app.change_attention_status(aerial, "ENTREGADO", "guide.qa", "GUIADOR")
            reject(lambda: app.create_attention("1002", "admin.qa", "ADMINISTRADOR"))
            updated = dispatch([("1002", 0, "SKU-A", 0, 6, "Cerrado"), ("1001", 0, "SKU-A", 6, 6, "Abierto")])
            load(updated, cutoff="2026-09-03T16:00:00")
            assert balance("1001")["source_total"] == 6
            assert balance("1001")["reserved_total"] == 6
            assert balance("1001")["consumed_total"] == 0, "Entrega ya incluida en SAP no se descuenta dos veces"
            with app.db() as connection:
                assert connection.execute("SELECT COUNT(*) FROM inventory_lots").fetchone()[0] == 0
                assert len(data_status(connection)["history"]) == 4
            app.init_db()
            assert balance("1001")["reserved_total"] == 6, "Persistencia tras reinicio"
            # Un nuevo NP informado por Importaciones no genera existencias.
            missing = dispatch([("2001", 0, "SKU-Z", 5, 0, "Abierto")])
            load(missing, cutoff="2026-09-04T16:00:00")
            imports_z = excel(["GUIA DE IMPORTACION", "CODIGO", "OV", "MODO DE TRANSPORTE", "CANTIDAD"], [["AWB-Z", "SKU-Z", "2001", "AEREO", 5]])
            load(imports_z, "importation", "2026-09-04T16:00:00")
            with app.db() as connection:
                connection.execute("UPDATE reception_shipments SET app_status='CERRADO' WHERE bl_awb='AWB-Z'")
            assert balance("2001", "SKU-Z")["source_total"] == 0
            assert balance("2001", "SKU-Z")["free_qty"] == 0
            reject(lambda: app.import_daily_excel(imports_z, "x.xlsx", "importation", None, "picker.qa", "PICKER"))
            print("ETAPA 1 OK: cortes, idempotencia, stock único, compromisos, recepción, roles, entregas y SQLite.")
        finally:
            app.DB_PATH = old_db
            test_db.unlink(missing_ok=True)


if __name__ == "__main__":
    run()
