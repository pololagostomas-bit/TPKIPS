"""Regresión: una OV que SAP cerró debe salir de la cola al recargar Excel."""

from pathlib import Path

from openpyxl import Workbook

import app


HEADERS = [
    "STATUS",
    "Número de documento",
    "Status de Documento",
    "N° de Línea",
    "Nombre de cliente/proveedor",
    "Número de artículo",
    "Descripción artículo/serv.",
    "Grupo de Articulo",
    "Almacen",
    "Cantidad",
    "StockDisponible",
    "Tipo de Atención",
]


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def write_snapshot(path, document_status, line_status):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    sheet.append(
        [
            line_status,
            "OV-CIERRE-SAP",
            document_status,
            0,
            "Cliente prueba",
            "SKU-CIERRE",
            "Repuesto de prueba",
            "REPUESTOS",
            1,
            2,
            5,
            "TOTAL",
        ]
    )
    workbook.save(path)
    workbook.close()


def run():
    root = Path(__file__).parent
    test_db = root / ".wms-closed-sap-test.db"
    snapshot = root / ".wms-closed-sap-test.xlsx"
    test_db.unlink(missing_ok=True)
    snapshot.unlink(missing_ok=True)
    original_db = app.DB_PATH
    app.DB_PATH = test_db
    try:
        app.init_db()
        write_snapshot(snapshot, "Abierto", "OV ABIERTA")
        opened = app.import_excel(snapshot, reset=False)
        check(opened["orders"] == 1, "La OV abierta debe importarse")

        attention = app.order_payload("OV-CIERRE-SAP")["attentions"][0]
        attention_id = attention["id"]
        app.assign_attention(
            attention_id, "current_picker", "picker.prueba", "admin", "ADMINISTRADOR"
        )
        app.change_attention_status(
            attention_id, "EN PICKING", "picker.prueba", "PICKER"
        )
        with app.db() as connection:
            allocation = connection.execute(
                "SELECT status, reserved_qty FROM stock_allocations WHERE attention_id = ?",
                (attention_id,),
            ).fetchone()
            check(allocation and allocation["status"] == "ACTIVA", "Debe existir una reserva activa")

        write_snapshot(snapshot, "Cerrado", "FACTURA DE DEUDORES")
        closed = app.import_excel(snapshot, reset=False)
        check(closed["closed_orders_updated"] == 1, "Debe reconocer la OV cerrada")

        with app.db() as connection:
            order = connection.execute(
                "SELECT * FROM orders WHERE sap_ov = 'OV-CIERRE-SAP'"
            ).fetchone()
            attention = connection.execute(
                "SELECT * FROM attentions WHERE id = ?", (attention_id,)
            ).fetchone()
            allocation = connection.execute(
                "SELECT * FROM stock_allocations WHERE attention_id = ?", (attention_id,)
            ).fetchone()
            events = {
                row["event_type"]
                for row in connection.execute(
                    "SELECT event_type FROM attention_history WHERE attention_id = ?",
                    (attention_id,),
                )
            }
            check(order["document_status"] == "Cerrado", "Debe conservar el estado documental SAP")
            check(order["app_status"] == "CERRADO SAP", "La OV debe cerrarse en el WMS")
            check(order["sap_open_sku_count"] == 0, "No deben quedar SKU abiertos")
            check(attention["app_status"] == "CERRADO SAP", "La atención activa debe cerrarse")
            check(allocation["status"] == "ANULADA", "Debe liberar la reserva de stock")
            check("CIERRE_SAP" in events, "El cierre debe quedar en el historial")

        visible = app.orders_payload(search="OV-CIERRE-SAP")
        check(not visible, "Una OV cerrada en SAP no debe aparecer en la cola operativa")
        detail = app.order_payload("OV-CIERRE-SAP")
        check(len(detail["lines"]) == 0, "Una OV cerrada no debe tener líneas pendientes")
        check(len(detail["attended_lines"]) == 1, "Las líneas atendidas deben conservarse en el detalle")
        check(detail["attended_lines"][0]["is_pending_sap"] == 0, "La línea atendida debe estar marcada como atendida en SAP")
        print("CIERRE SAP OK: actualización, liberación, historial y ocultamiento verificados.")
    finally:
        app.DB_PATH = original_db
        snapshot.unlink(missing_ok=True)
        test_db.unlink(missing_ok=True)


if __name__ == "__main__":
    run()
