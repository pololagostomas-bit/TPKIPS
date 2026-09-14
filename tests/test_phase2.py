"""Pruebas de regresión de la Fase 2: responsables, estados e historial."""

import sqlite3

import app


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def expect_error(action, contains, error_type=PermissionError):
    try:
        action()
    except error_type as error:
        check(contains in str(error), f"Error inesperado: {error}")
    else:
        raise AssertionError("La operación debió ser rechazada")


def history_count(attention, event_type):
    return sum(1 for event in attention["history"] if event["event_type"] == event_type)


def main():
    original_db = app.DB_PATH
    test_db = app.ROOT / "phase2_test.db"
    if test_db.exists():
        test_db.unlink()
    app.DB_PATH = test_db
    try:
        app.init_db()
        with app.db() as connection:
            connection.execute(
                """INSERT INTO orders
                   (sap_ov, customer_name, attention_type, app_status, created_at, updated_at)
                   VALUES ('TEST-OV-154387', 'Cliente de prueba', 'PARCIAL', 'PENDIENTE', ?, ?)""",
                (app.now(), app.now()),
            )
            connection.execute(
                """INSERT INTO order_lines
                   (sap_ov, source_row, item_code, description, required_qty, pending_qty, available_qty)
                   VALUES ('TEST-OV-154387', 2, 'SKU-001', 'Producto 1', 3, 3, 3)"""
            )
            connection.execute(
                """INSERT INTO order_lines
                   (sap_ov, source_row, item_code, description, required_qty, pending_qty, available_qty)
                   VALUES ('TEST-OV-154387', 3, 'SKU-002', 'Producto 2', 1, 1, 1)"""
            )
            app.seed_initial_attentions(connection)

        first = app.order_payload("TEST-OV-154387")["attentions"][0]
        check(first["sequence_no"] == 1, "La OV debe comenzar con Atención 1")
        check(len(first["lines"]) == 2, "Atención 1 debe conservar las dos líneas")
        check(history_count(first, "CREACION") == 1, "La creación inicial debe registrarse una sola vez")
        with app.db() as connection:
            connection.execute(
                "UPDATE order_lines SET description = 'Producto 1 actualizado desde SAP' WHERE sap_ov = 'TEST-OV-154387' AND source_row = 2"
            )
        first_after_refresh = app.order_payload("TEST-OV-154387")["attentions"][0]
        check(first_after_refresh["lines"][0]["description"] == "Producto 1", "Atención 1 debe conservar su descripción histórica")

        expect_error(
            lambda: app.assign_attention(first["id"], "current_picker", "picker-01", "picker-01", "PICKER"),
            "Solo el administrador",
        )
        expect_error(
            lambda: app.create_attention("TEST-OV-154387", "picker-01", "PICKER"),
            "No tienes permiso",
        )

        app.assign_attention(first["id"], "current_picker", "picker-01", "admin-01", "ADMINISTRADOR")
        app.assign_attention(first["id"], "current_picker", "picker-02", "admin-01", "ADMINISTRADOR")
        changed_type = app.set_attention_type(first["id"], "COMPLETA", "picker-02", "PICKER")
        check(changed_type["attention_type"] == "COMPLETA", "El picker asignado debe poder elegir el tipo antes de iniciar")
        expect_error(
            lambda: app.change_attention_status(first["id"], "EN PICKING", "picker-01", "PICKER"),
            "picker asignado",
        )
        expect_error(
            lambda: app.change_attention_status(first["id"], "EN GUIADO", "guide-01", "GUIADOR"),
            "guiador/entregador asignado",
        )

        app.change_attention_status(first["id"], "EN PICKING", "picker-02", "PICKER")
        picking_defaults = app.order_payload("TEST-OV-154387")["attentions"][0]
        check(picking_defaults["lines"][0]["picked_qty"] == 3, "El picking debe reservar toda la cantidad de una atención completa")
        check(picking_defaults["lines"][1]["picked_qty"] == 1, "El picking debe proponer el stock hasta la cantidad planificada")
        check(history_count(picking_defaults, "RESERVA_STOCK") == 2, "Las reservas automáticas deben quedar auditadas")
        reassigned_picker = app.assign_attention(
            first["id"], "current_picker", "picker-03", "admin-01", "ADMINISTRADOR"
        )
        check(reassigned_picker["current_picker"] == "picker-03", "El administrador debe poder cambiar el picker durante el picking")
        picking = app.order_payload("TEST-OV-154387")["attentions"][0]
        expect_error(
            lambda: app.update_attention_line(first["id"], picking["lines"][0]["id"], "picked_qty", 2, "picker-02", "PICKER"),
            "picker asignado",
        )
        app.update_attention_line(first["id"], picking["lines"][0]["id"], "picked_qty", 2, "picker-03", "PICKER")
        app.update_attention_line(first["id"], picking["lines"][1]["id"], "picked_qty", 1, "picker-03", "PICKER")
        expect_error(
            lambda: app.change_attention_status(first["id"], "PICKING FINALIZADO", "picker-03", "PICKER"),
            "COMPLETA requiere",
            ValueError,
        )
        app.update_attention_line(first["id"], picking["lines"][0]["id"], "picked_qty", 3, "picker-03", "PICKER")
        completed = app.change_attention_status(first["id"], "PICKING FINALIZADO", "picker-03", "PICKER")
        check(completed["app_status"] == "POR GUIAR", "Al finalizar picking debe quedar Por guiar")
        check(any(event["new_value"] == "PICKING FINALIZADO" for event in completed["history"]), "Debe registrar Picking finalizado")
        check(any(event["new_value"] == "POR GUIAR" for event in completed["history"]), "Debe registrar Por guiar")

        app.assign_attention(first["id"], "current_guide", "guide-01", "admin-01", "ADMINISTRADOR")
        app.assign_attention(first["id"], "current_guide", "guide-02", "admin-01", "ADMINISTRADOR")
        expect_error(
            lambda: app.change_attention_status(first["id"], "EN GUIADO", "guide-01", "GUIADOR"),
            "guiador/entregador asignado",
        )
        app.change_attention_status(first["id"], "EN GUIADO", "guide-02", "GUIADOR")
        guided_defaults = app.order_payload("TEST-OV-154387")["attentions"][0]
        check(guided_defaults["lines"][0]["delivered_qty"] == 3, "El guiado debe proponer todo lo recogido")
        check(guided_defaults["lines"][1]["delivered_qty"] == 1, "El guiado debe proponer la cantidad recogida")
        reassigned_guide = app.assign_attention(
            first["id"], "current_guide", "guide-03", "admin-01", "ADMINISTRADOR"
        )
        check(reassigned_guide["current_guide"] == "guide-03", "El administrador debe poder cambiar el guiador durante el guiado")
        guided = app.order_payload("TEST-OV-154387")["attentions"][0]
        expect_error(
            lambda: app.update_attention_line(first["id"], guided["lines"][0]["id"], "delivered_qty", 2, "guide-02", "GUIADOR"),
            "guiador/entregador asignado",
        )
        app.update_attention_line(first["id"], guided["lines"][0]["id"], "delivered_qty", 2, "guide-03", "GUIADOR")
        app.update_attention_line(first["id"], guided["lines"][1]["id"], "delivered_qty", 1, "guide-03", "GUIADOR")
        app.change_attention_status(first["id"], "GUIADO FINALIZADO", "guide-03", "GUIADOR")
        expect_error(
            lambda: app.change_attention_status(first["id"], "ENTREGADO", "guide-03", "GUIADOR"),
            "toda la cantidad recogida",
            ValueError,
        )
        app.update_attention_line(first["id"], guided["lines"][0]["id"], "delivered_qty", 3, "guide-03", "GUIADOR")
        delivered = app.change_attention_status(first["id"], "ENTREGADO", "guide-03", "GUIADOR")
        check(delivered["app_status"] == "ENTREGADO", "El guiador debe poder registrar la entrega")
        check(any(event["new_value"] == "ENTREGADO" and event["username"] == "guide-03" for event in delivered["history"]), "La entrega debe quedar registrada con el guiador reasignado")
        report = app.operational_report()
        report_row = next(row for row in report["rows"] if row["id"] == first["id"])
        check(report_row["picking_minutes"] is not None, "El reporte debe calcular el tiempo de picking")
        check(report_row["guiding_minutes"] is not None, "El reporte debe calcular el tiempo de guiado")

        expect_error(lambda: app.create_attention("TEST-OV-154387", "admin-01", "ADMINISTRADOR"),
                     'no tiene saldo pendiente', ValueError)
        # La etapa 1 permite otra atención solamente si la OV conserva saldo.
        # Simula cantidades adicionales informadas por SAP, sin alterar la foto
        # histórica de la atención ya entregada.
        with app.db() as connection:
            connection.execute("UPDATE order_lines SET pending_qty=pending_qty+1,required_qty=required_qty+1 WHERE sap_ov='TEST-OV-154387'")
        second = app.create_attention("TEST-OV-154387", "admin-01", "ADMINISTRADOR")
        check(second["sequence_no"] == 2, "Después de entregar debe crearse Atención 2")
        check(second["id"] != first["id"], "Atención 2 debe tener un ID diferente")
        check(second["app_status"] == "PENDIENTE", "Atención 2 debe iniciar Pendiente")
        check(len(second["lines"]) == 2, "Atención 2 debe conservar las líneas de la OV")
        check(second["lines"][0]["description"] == "Producto 1 actualizado desde SAP", "Atención 2 debe tomar el detalle vigente de SAP")
        changed_second = app.set_attention_type(second["id"], "PARCIAL", "admin-01", "ADMINISTRADOR")
        check(changed_second["attention_type"] == "PARCIAL", "El administrador debe poder definir una atención PARCIAL")
        check(history_count(second, "CREACION") == 1, "Atención 2 debe tener un único evento de creación")
        expect_error(
            lambda: app.create_attention("TEST-OV-154387", "admin-01", "ADMINISTRADOR"),
            "atención pendiente",
            ValueError,
        )

        all_attentions = app.order_payload("TEST-OV-154387")["attentions"]
        check(len(all_attentions) == 2, "La OV debe tener exactamente dos atenciones")
        print("FASE 2 OK: flujo, responsables, reasignación, historial y segunda atención verificados.")
    finally:
        app.DB_PATH = original_db
        if test_db.exists():
            try:
                test_db.unlink()
            except PermissionError as error:
                raise AssertionError("La prueba dejó bloqueada la base temporal") from error


if __name__ == "__main__":
    main()
