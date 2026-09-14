"""Regresión del inventario global, reservas y stock aéreo exclusivo."""

from pathlib import Path

import app


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def expect_value_error(action, contains):
    try:
        action()
    except ValueError as error:
        check(contains in str(error), f"Error inesperado: {error}")
    else:
        raise AssertionError("La operación debió ser rechazada")


def create_order(connection, ov, item_code, quantity, available, attention_type="COMPLETA"):
    timestamp = app.now()
    connection.execute(
        """INSERT INTO orders
           (sap_ov, customer_name, attention_type, app_status, created_at, updated_at)
           VALUES (?, 'Cliente prueba', ?, 'PENDIENTE', ?, ?)""",
        (ov, attention_type, timestamp, timestamp),
    )
    connection.execute(
        """INSERT INTO order_lines
           (sap_ov, source_row, item_code, description, required_qty, pending_qty,
            available_qty, warehouse, article_group, sap_line_status, is_pending_sap)
           VALUES (?, 2, ?, 'Artículo prueba', ?, ?, ?, '1', 'REPUESTOS', 'OV ABIERTA', 1)""",
        (ov, item_code, quantity, quantity, available),
    )


def assigned_attention(ov, picker):
    attention = app.order_payload(ov)["attentions"][0]
    app.assign_attention(attention["id"], "current_picker", picker, "admin.test", "ADMINISTRADOR")
    return app.order_payload(ov)["attentions"][0]


def run():
    test_db = Path(__file__).parent / ".wms-global-stock-test.db"
    test_db.unlink(missing_ok=True)
    original_db = app.DB_PATH
    app.DB_PATH = test_db
    try:
        app.init_db()
        with app.db() as connection:
            create_order(connection, "OV-STOCK-1", "SKU-GLOBAL", 6, 10)
            create_order(connection, "OV-STOCK-2", "SKU-GLOBAL", 5, 10)
            create_order(connection, "OV-AIR-1", "SKU-AIR", 3, 99, "PARCIAL")
            connection.execute(
                """INSERT INTO order_importation_refs
                   (sap_ov, bl_awb, transport_type, item_code, source_sheet, source_row, quantity, item_key, updated_at)
                   VALUES ('OV-AIR-1', 'AWB-TEST', 'AEREO', 'SKU-AIR', 'TEST', 2, 2, 'SKUAIR', ?)""",
                (app.now(),),
            )
            shipment_id = connection.execute(
                """INSERT INTO reception_shipments
                   (bl_awb, transport_type, app_status, condition_status, created_at, updated_at)
                   VALUES ('AWB-TEST', 'AEREO', 'REVISION SISTEMA', 'EN PROCESO', ?, ?)""",
                (app.now(), app.now()),
            ).lastrowid
            connection.execute(
                """INSERT INTO reception_lines
                   (shipment_id, np_code, ov_number, expected_qty, received_qty)
                   VALUES (?, 'SKU-AIR', 'OV-AIR-1', 3, 2)""",
                (shipment_id,),
            )
            app.seed_initial_attentions(connection)

        first = assigned_attention("OV-STOCK-1", "picker.1")
        second = assigned_attention("OV-STOCK-2", "picker.2")
        aerial = assigned_attention("OV-AIR-1", "picker.air")

        app.change_attention_status(first["id"], "EN PICKING", "picker.1", "PICKER")
        second_after_reservation = app.order_payload("OV-STOCK-2")["attentions"][0]
        check(second_after_reservation["lines"][0]["stock_free_qty"] == 4, "La segunda OV debe ver 4 unidades libres")
        expect_value_error(
            lambda: app.change_attention_status(second["id"], "EN PICKING", "picker.2", "PICKER"),
            "Stock insuficiente",
        )

        app.set_attention_type(second["id"], "PARCIAL", "admin.test", "ADMINISTRADOR")
        app.change_attention_status(second["id"], "EN PICKING", "picker.2", "PICKER")
        second_picking = app.order_payload("OV-STOCK-2")["attentions"][0]
        check(second_picking["lines"][0]["picked_qty"] == 4, "La atención parcial debe reservar solo el saldo global")

        app.change_attention_status(first["id"], "PICKING FINALIZADO", "picker.1", "PICKER")
        app.change_attention_status(second["id"], "PICKING FINALIZADO", "picker.2", "PICKER")
        with app.db() as connection:
            stock_status = app.inventory_pool_status(connection, "OV-STOCK-1", "SKU-GLOBAL", "1", "STOCK")
            check(stock_status["consumed_total"] == 10, "El consumo global debe sumar 10")
            check(stock_status["free_qty"] == 0, "No debe quedar stock global libre")

        try:
            app.change_attention_status(aerial["id"], "EN PICKING", "picker.air", "PICKER")
        except PermissionError:
            pass
        else:
            raise AssertionError('La importación debe esperar la validación de Recepción')
        with app.db() as connection:
            connection.execute("UPDATE reception_shipments SET app_status='CERRADO' WHERE id=?", (shipment_id,))
        app.change_attention_status(aerial["id"], "EN PICKING", "picker.air", "PICKER")
        aerial_picking = app.order_payload("OV-AIR-1")["attentions"][0]
        aerial_line = aerial_picking["lines"][0]
        check(aerial_line["origin_type"] == "AEREO", "La línea debe usar la bolsa aérea")
        check(aerial_line["stock_source_qty"] == 99, "Recepción no debe reemplazar el saldo fuente SAP")
        check(aerial_line["stock_aerial_ov_count"] == 1, "Debe informar cuántas OVs aéreas reservan el SKU")
        check(aerial_line["stock_aerial_reserved_qty"] == 2, "Debe informar la cantidad comprometida por OVs aéreas")
        check(aerial_line["stock_aerial_ovs"] == ["OV-AIR-1"], "Debe identificar la OV aérea comprometida")
        check(aerial_line["picked_qty"] == 2, "Solo se proponen las dos unidades comprometidas a la OV")
        check(not aerial_line.get("tracked"), "La etapa 1 no requiere lotes ni ubicaciones")
        with app.db() as connection:
            allocation = connection.execute(
                "SELECT pool_type, reserved_qty FROM stock_allocations WHERE attention_id = ?",
                (aerial["id"],),
            ).fetchone()
            check(allocation["pool_type"] == "AEREO", "El stock aéreo no debe mezclarse con stock general")
            check(allocation["reserved_qty"] == 2, "La bolsa aérea debe reservar exactamente lo recibido")
            movement_count = connection.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0]
            check(movement_count >= 5, "Reservas y consumos deben quedar auditados")

            # Simula una atención que estaba en picking antes de instalar esta
            # versión: el siguiente arranque debe proteger su cantidad.
            create_order(connection, "OV-MIGRADA", "SKU-MIGRADO", 2, 5)
            app.seed_initial_attentions(connection)
            migrated = connection.execute(
                "SELECT id FROM attentions WHERE sap_ov = 'OV-MIGRADA'"
            ).fetchone()
            connection.execute(
                "UPDATE attentions SET app_status = 'EN PICKING' WHERE id = ?",
                (migrated["id"],),
            )
            connection.execute(
                "UPDATE attention_lines SET picked_qty = 2 WHERE attention_id = ?",
                (migrated["id"],),
            )

        app.init_db()
        with app.db() as connection:
            migrated_allocation = connection.execute(
                "SELECT reserved_qty, status FROM stock_allocations WHERE attention_id = ?",
                (migrated["id"],),
            ).fetchone()
            check(migrated_allocation is not None, "El arranque debe migrar reservas de picking activas")
            check(migrated_allocation["reserved_qty"] == 2, "La migración debe conservar la cantidad recogida")
            check(migrated_allocation["status"] == "ACTIVA", "La reserva migrada debe quedar activa")

        print("STOCK GLOBAL OK: reserva, consumo, migración y bolsa aérea exclusiva verificados.")
    finally:
        app.DB_PATH = original_db
        test_db.unlink(missing_ok=True)


if __name__ == "__main__":
    run()
