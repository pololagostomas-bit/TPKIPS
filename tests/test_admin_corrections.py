"""Regresión de reasignación, retroceso y reinicio administrativo."""

from pathlib import Path

import app


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def expect_permission(action, contains):
    try:
        action()
    except PermissionError as error:
        check(contains in str(error), f"Error inesperado: {error}")
    else:
        raise AssertionError("La operación debió ser rechazada")


def run():
    test_db = Path(__file__).parent / ".wms-admin-corrections-test.db"
    test_db.unlink(missing_ok=True)
    original_db = app.DB_PATH
    app.DB_PATH = test_db
    try:
        app.init_db()
        timestamp = app.now()
        with app.db() as connection:
            connection.execute(
                """INSERT INTO orders
                   (sap_ov, customer_name, attention_type, app_status,
                    document_status, created_at, updated_at)
                   VALUES ('OV-CORRECCION', 'Cliente prueba', 'COMPLETA',
                           'PENDIENTE', 'Abierto', ?, ?)""",
                (timestamp, timestamp),
            )
            connection.execute(
                """INSERT INTO order_lines
                   (sap_ov, source_row, item_code, description, required_qty,
                    pending_qty, available_qty, warehouse, article_group,
                    sap_line_status, is_pending_sap)
                   VALUES ('OV-CORRECCION', 2, 'SKU-CORRECCION', 'Artículo',
                           5, 5, 10, '1', 'REPUESTOS', 'OV ABIERTA', 1)"""
            )
            app.seed_initial_attentions(connection)

        attention = app.order_payload("OV-CORRECCION")["attentions"][0]
        attention_id = attention["id"]
        app.assign_attention(attention_id, "current_picker", "picker.uno", "admin", "ADMINISTRADOR")
        app.change_attention_status(attention_id, "EN PICKING", "picker.uno", "PICKER")

        reassigned = app.assign_attention(
            attention_id, "current_picker", "picker.dos", "admin", "ADMINISTRADOR"
        )
        check(reassigned["current_picker"] == "picker.dos", "Debe permitir cambiar el picker en curso")
        expect_permission(
            lambda: app.change_attention_status(attention_id, "PICKING FINALIZADO", "picker.uno", "PICKER"),
            "picker asignado",
        )

        rolled_back = app.admin_rollback_attention(
            attention_id, "admin", "ADMINISTRADOR", "Picking iniciado por error"
        )
        check(rolled_back["app_status"] == "ASIGNADO", "Debe volver de picking a asignado")
        check(rolled_back["lines"][0]["picked_qty"] == 0, "El retroceso debe limpiar la cantidad recogida")
        with app.db() as connection:
            stock = app.inventory_pool_status(connection, "OV-CORRECCION", "SKU-CORRECCION", "1", "STOCK")
            check(stock["free_qty"] == 10, "El retroceso debe liberar la reserva")

        app.change_attention_status(attention_id, "EN PICKING", "picker.dos", "PICKER")
        app.change_attention_status(attention_id, "PICKING FINALIZADO", "picker.dos", "PICKER")
        restored = app.admin_rollback_attention(
            attention_id, "admin", "ADMINISTRADOR", "Corregir cantidades terminadas"
        )
        check(restored["app_status"] == "EN PICKING", "Debe volver de Por guiar a En picking")
        check(restored["lines"][0]["stock_allocation_status"] == "ACTIVA", "El consumo debe volver a reserva")

        expect_permission(
            lambda: app.admin_reset_attention(attention_id, "picker.dos", "PICKER", "Sin permiso"),
            "Solo el administrador",
        )
        reset = app.admin_reset_attention(
            attention_id, "admin", "ADMINISTRADOR", "Anular trabajo equivocado"
        )
        check(reset["app_status"] == "PENDIENTE", "El reinicio debe volver a Pendiente")
        check(reset["attention_type"] == "SELECCIONAR", "El reinicio debe limpiar el tipo de atención")
        check(not reset["current_picker"] and not reset["current_guide"], "El reinicio debe quitar responsables")
        check(reset["lines"][0]["picked_qty"] == 0 and reset["lines"][0]["delivered_qty"] == 0, "El reinicio debe limpiar cantidades")
        check(any(event["event_type"] == "RETROCESO_ADMIN" for event in reset["history"]), "El retroceso debe quedar auditado")
        check(any(event["event_type"] == "REINICIO_ADMIN" for event in reset["history"]), "El reinicio debe quedar auditado")
        with app.db() as connection:
            stock = app.inventory_pool_status(connection, "OV-CORRECCION", "SKU-CORRECCION", "1", "STOCK")
            check(stock["free_qty"] == 10, "El reinicio debe restaurar todo el stock")

        # La misma atención debe poder comenzar nuevamente reutilizando de
        # forma segura el registro de reserva anulado.
        app.assign_attention(attention_id, "current_picker", "picker.tres", "admin", "ADMINISTRADOR")
        app.set_attention_type(attention_id, "COMPLETA", "admin", "ADMINISTRADOR")
        restarted = app.change_attention_status(attention_id, "EN PICKING", "picker.tres", "PICKER")
        check(restarted["app_status"] == "EN PICKING", "La atención reiniciada debe poder comenzar de nuevo")
        check(restarted["lines"][0]["stock_reserved_for_line"] == 5, "Debe crear nuevamente la reserva")

        print("CORRECCIONES ADMIN OK: reasignación, retroceso, reinicio, stock y auditoría verificados.")
    finally:
        app.DB_PATH = original_db
        test_db.unlink(missing_ok=True)


if __name__ == "__main__":
    run()
