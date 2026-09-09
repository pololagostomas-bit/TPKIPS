"""Verifica endpoints de salud, PWA y la interfaz servida localmente."""

import io
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from openpyxl import Workbook

import app
from backend.services.reception import create_reception


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    original_db = app.DB_PATH
    test_db = app.ROOT / "http_test.db"
    if test_db.exists():
        test_db.unlink()
    app.DB_PATH = test_db
    server = None
    try:
        app.init_db()
        with app.db() as connection:
            create_reception(
                connection,
                {"bl_awb": "BL-MAR-REPORT", "transport_type": "MARITIMO", "scheduled_date": "2026-09-05"},
                "admin.http",
                "ADMINISTRADOR",
            )
            create_reception(
                connection,
                {"bl_awb": "BL-AIR-REPORT", "transport_type": "AEREO", "scheduled_date": "2026-09-03"},
                "admin.http",
                "ADMINISTRADOR",
            )
            connection.execute(
                "UPDATE reception_shipments SET app_status = 'ARRIBADO', first_arrival_at = ? WHERE bl_awb = ?",
                ("2026-09-01T08:00:00", "BL-MAR-REPORT"),
            )
        server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        health = json.loads(urlopen(base + "/health").read())
        check(health["status"] == "ok", "Health check inválido")
        manifest = json.loads(urlopen(base + "/manifest.webmanifest").read())
        check(manifest["display"] == "standalone", "Manifest PWA inválido")
        worker = urlopen(base + "/service-worker.js").read().decode("utf-8")
        check("CACHE" in worker, "Service worker inválido")
        icon = urlopen(base + "/icon.svg").read().decode("utf-8")
        check("<svg" in icon, "Ícono PWA inválido")
        logo = urlopen(base + "/assets/triton-logo.png").read()
        check(logo.startswith(b"\x89PNG\r\n\x1a\n"), "Logo Triton inválido")
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["STATUS", "Número de documento", "Status de Documento", "Grupo de Articulo", "Almacen", "Número de artículo", "Descripción artículo/serv.", "Cantidad", "Cant. Pendiente", "StockDisponible", "Tipo de Atención", "Situacion de Maquina"])
        sheet.append(["OV ABIERTA", "OV-PRUEBA-HTTP", "Abierta", "Repuestos", 1, "SKU-1", "Artículo de prueba", 2, 2, 2, "PARCIAL", "MAQUINA EN USO"])
        sheet.append(["FACTURA DE RESERVA", "OV-PRUEBA-HTTP", "Abierta", "Repuestos", 1, "SKU-ATENDIDO", "Artículo ya atendido", 1, 1, 1, "PARCIAL", "MAQUINA EN USO"])
        sheet.append(["OV ABIERTA", "OV-NO-ASIGNADA", "Abierta", "Accesorios", 1, "SKU-2", "Artículo restringido", 1, 1, 1, "COMPLETA", "MAQUINA PARADA"])
        sheet.append(["OV ABIERTA", "OV-CON-FALTANTE", "Abierta", "Repuestos", 1, "SKU-3", "Artículo con faltante", 5, 5, 2, "PARCIAL", "MAQUINA EN USO"])
        sheet.append(["OV ABIERTA", "OV-GRUPO-FUERA", "Abierta", "Servicios", 1, "SKU-4", "No debe entrar", 1, 1, 1, "PARCIAL", "MAQUINA EN USO"])
        sheet.append(["OV ABIERTA", "OV-ALMACEN-FUERA", "Abierta", "Repuestos", 2, "SKU-5", "No debe entrar", 1, 1, 1, "PARCIAL", "MAQUINA EN USO"])
        sheet.append(["OV ABIERTA", "OV-CERRADA", "Cerrada", "Repuestos", 1, "SKU-6", "No debe entrar", 1, 1, 1, "PARCIAL", "MAQUINA EN USO"])
        content = io.BytesIO()
        workbook.save(content)
        request = Request(
            base + "/api/import/excel",
            data=content.getvalue(),
            method="POST",
            headers={"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "X-File-Name": "prueba.xlsx", "X-User": "admin.http", "X-Role": "ADMINISTRADOR"},
        )
        try:
            imported = json.loads(urlopen(request).read())
        except HTTPError as error:
            raise AssertionError(f"La carga Excel del administrador devolvió {error.code}: {error.read().decode('utf-8')}") from error
        check(imported["orders"] == 3 and imported["lines"] == 3, "La carga Excel por HTTP falló")
        check(imported["source_rows"] == 7 and imported["skipped_rows"] == 0 and imported["stock_shortage_orders"] == 1, "El resumen de carga no refleja las filas ni faltantes")
        check(imported["sap_attended_rows"] == 1 and imported["excluded_group_rows"] == 1 and imported["excluded_warehouse_rows"] == 1 and imported["excluded_document_rows"] == 1, "Los filtros SAP no se aplicaron correctamente")
        admin_orders = Request(base + "/api/orders", headers={"X-User": "admin.http", "X-Role": "ADMINISTRADOR"})
        queue = {row["sap_ov"]: row for row in json.loads(urlopen(admin_orders).read())}
        check(queue["OV-PRUEBA-HTTP"]["stock_shortage_lines"] == 0, "La cola debe reconocer stock completo")
        check(queue["OV-CON-FALTANTE"]["stock_shortage_lines"] == 1 and queue["OV-CON-FALTANTE"]["stock_shortage_qty"] == 3, "La cola debe señalar el faltante de stock")
        check(set(queue) == {"OV-PRUEBA-HTTP", "OV-NO-ASIGNADA", "OV-CON-FALTANTE"}, "Solo Repuestos/Accesorios del almacén 1 y documento abierto deben entrar a la cola")
        check(queue["OV-PRUEBA-HTTP"]["sap_open_sku_count"] == 1 and queue["OV-PRUEBA-HTTP"]["sap_attended_sku_count"] == 1 and queue["OV-PRUEBA-HTTP"]["document_status"] == "Abierta", "La cola debe conservar los indicadores SAP por OV")
        with app.db() as connection:
            connection.execute("UPDATE attention_lines SET item_code = 'DATO-OBSOLETO', planned_qty = 999 WHERE attention_id = 1")
        refreshed = Request(
            base + "/api/import/excel", data=content.getvalue(), method="POST",
            headers={"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "X-File-Name": "prueba.xlsx", "X-User": "admin.http", "X-Role": "ADMINISTRADOR"},
        )
        urlopen(refreshed).read()
        refreshed_line = app.order_payload("OV-PRUEBA-HTTP")["attentions"][0]["lines"][0]
        check(refreshed_line["item_code"] == "SKU-1" and refreshed_line["planned_qty"] == 2, "Una reimportación debe corregir atenciones no iniciadas")
        operational_order = app.order_payload("OV-PRUEBA-HTTP")
        check(len(operational_order["lines"]) == 1 and operational_order["sap_status_summary"] == "FACTURA DE RESERVA: 1 · OV ABIERTA: 1", "Solo los SKU OV ABIERTA deben ser operativos y el resumen SAP debe permanecer visible")
        admin_detail = Request(
            base + "/api/orders/OV-PRUEBA-HTTP",
            headers={"X-User": "admin.http", "X-Role": "ADMINISTRADOR"},
        )
        admin_payload = json.loads(urlopen(admin_detail).read())
        check("history" in admin_payload and "history" in admin_payload["attentions"][0], "El administrador debe ver el historial")
        app.assign_attention(
            admin_payload["attentions"][0]["id"], "current_picker", "picker.http", "admin.http", "ADMINISTRADOR"
        )
        picker_detail = Request(
            base + "/api/orders/OV-PRUEBA-HTTP",
            headers={"X-User": "picker.http", "X-Role": "PICKER"},
        )
        picker_payload = json.loads(urlopen(picker_detail).read())
        check("history" not in picker_payload and "history" not in picker_payload["attentions"][0], "El picker no debe recibir historial")
        picker_orders = Request(base + "/api/orders", headers={"X-User": "picker.http", "X-Role": "PICKER"})
        picker_list = json.loads(urlopen(picker_orders).read())
        check([row["sap_ov"] for row in picker_list] == ["OV-PRUEBA-HTTP"], "El picker solo debe recibir sus OVs asignadas")
        forbidden_order = Request(base + "/api/orders/OV-NO-ASIGNADA", headers={"X-User": "picker.http", "X-Role": "PICKER"})
        try:
            urlopen(forbidden_order)
        except HTTPError as error:
            check(error.code == 403, "Un picker no debe abrir una OV no asignada")
        else:
            raise AssertionError("Una OV no asignada debe rechazar al picker")
        attention_id = admin_payload["attentions"][0]["id"]
        app.set_attention_type(attention_id, "PARCIAL", "admin.http", "ADMINISTRADOR")
        app.change_attention_status(attention_id, "EN PICKING", "picker.http", "PICKER")
        line = app.order_payload("OV-PRUEBA-HTTP")["attentions"][0]["lines"][0]
        check(line["planned_qty"] > 0, "La atención importada debe tener cantidad planificada")
        app.update_attention_line(attention_id, line["id"], "picked_qty", line["planned_qty"], "picker.http", "PICKER")
        app.change_attention_status(attention_id, "PICKING FINALIZADO", "picker.http", "PICKER")
        app.assign_attention(attention_id, "current_guide", "guide.http", "admin.http", "ADMINISTRADOR")
        guide_orders = Request(base + "/api/orders", headers={"X-User": "guide.http", "X-Role": "GUIADOR"})
        guide_list = json.loads(urlopen(guide_orders).read())
        check([row["sap_ov"] for row in guide_list] == ["OV-PRUEBA-HTTP"], "El guiador solo debe recibir sus OVs asignadas")
        app.change_attention_status(attention_id, "EN GUIADO", "guide.http", "GUIADOR")
        app.change_attention_status(attention_id, "GUIADO FINALIZADO", "guide.http", "GUIADOR")
        delivered = app.change_attention_status(attention_id, "ENTREGADO", "guide.http", "GUIADOR")
        check(delivered["app_status"] == "ENTREGADO", "El guiador debe completar la entrega asignada")
        admin_report = Request(base + "/api/reports/operational", headers={"X-User": "admin.http", "X-Role": "ADMINISTRADOR"})
        report = json.loads(urlopen(admin_report).read())
        check(report["by_status"].get("ENTREGADO") == 1, "El reporte debe incluir la entrega completada")
        check(report["alerts"]["without_picker"] == 2 and report["alerts"]["stock_shortage_orders"] == 1, "Las alertas operativas deben reflejar la cola pendiente")
        picker_report = Request(base + "/api/reports/operational", headers={"X-User": "picker.http", "X-Role": "PICKER"})
        try:
            urlopen(picker_report)
        except HTTPError as error:
            check(error.code == 403, "La reportería debe ser exclusiva del administrador")
        else:
            raise AssertionError("Un picker no debe abrir la reportería")
        reception_report = Request(base + "/api/receptions/report", headers={"X-User": "admin.http", "X-Role": "ADMINISTRADOR"})
        report = json.loads(urlopen(reception_report).read())
        check(report["summary"]["total_pendientes"] == 2, "La reportería de Recepción debe mostrar solo BL abiertas")
        check(report["items"][0]["bl_awb"] == "BL-AIR-REPORT", "Los próximos arribos deben ordenarse por fecha más próxima")
        check(report["items"][1]["sla_hours"] == 96 and report["items"][1]["sla_status"] in {"DENTRO SLA", "VENCE PRONTO", "VENCIDO"}, "El SLA marítimo debe medirse en horas")
        reception_picker_report = Request(base + "/api/receptions/report", headers={"X-User": "asistente.http", "X-Role": "ASISTENTE_RECEPCION"})
        try:
            urlopen(reception_picker_report)
        except HTTPError as error:
            check(error.code == 403, "La reportería de Recepción debe ser exclusiva del administrador")
        else:
            raise AssertionError("Un asistente no debe abrir la reportería de Recepción")
        blocked = Request(
            base + "/api/import/excel", data=content.getvalue(), method="POST",
            headers={"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "X-File-Name": "prueba.xlsx", "X-User": "picker.http", "X-Role": "PICKER"},
        )
        try:
            urlopen(blocked)
        except HTTPError as error:
            check(error.code == 403, "Un picker no debe cargar el Excel")
        else:
            raise AssertionError("La carga Excel debe estar restringida al administrador")
        print("HTTP Y PWA OK: health, PWA, carga Excel y privacidad de historial verificados.")
    finally:
        if server:
            server.shutdown()
            server.server_close()
        app.DB_PATH = original_db
        if test_db.exists():
            test_db.unlink()


if __name__ == "__main__":
    main()
