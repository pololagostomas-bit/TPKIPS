"""Pruebas integradas del MVP de trazabilidad física por lote (casos A-L)."""

from pathlib import Path

import app
from backend.services.traceability import (
    generate_lots_for_shipment,
    init_traceability_schema,
    lot_payload,
    register_label_print,
    traceability_search,
    update_lot_location,
    validate_lot_scan,
)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def expect(error_type, contains, action):
    try:
        action()
    except error_type as error:
        check(contains.lower() in str(error).lower(), f"Error inesperado: {error}")
        return
    raise AssertionError(f"Se esperaba {error_type.__name__}: {contains}")


def create_reception_lots(connection, bl, lines, received_at, transport="MARITIMO"):
    timestamp = app.now()
    shipment_id = connection.execute(
        """INSERT INTO reception_shipments
           (bl_awb, transport_type, app_status, condition_status,
            current_assistant, current_auxiliary, created_at, updated_at)
           VALUES (?, ?, 'REVISION SISTEMA', 'EN PROCESO',
                   'asistente.test', 'auxiliar.test', ?, ?)""",
        (bl, transport, timestamp, timestamp),
    ).lastrowid
    for index, line in enumerate(lines, start=1):
        connection.execute(
            """INSERT INTO reception_lines
               (shipment_id, source_row, source_key, np_code, description,
                oc_number, ov_number, ip_reference, expected_qty, received_qty)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                shipment_id,
                index,
                f"{bl}-{index}",
                line["np"],
                line.get("description", "Repuesto de prueba"),
                line.get("oc", ""),
                line.get("ov", ""),
                line.get("ip", ""),
                line["qty"],
                line["qty"],
            ),
        )
    lots = generate_lots_for_shipment(connection, shipment_id, "asistente.test")
    connection.execute(
        "UPDATE inventory_lots SET received_at = ?, updated_at = ? WHERE reception_shipment_id = ?",
        (received_at, timestamp, shipment_id),
    )
    return [lot_payload(connection, lot["id"]) for lot in lots]


def create_order(connection, ov, np_code, quantity, available=100, attention_type="COMPLETA"):
    timestamp = app.now()
    connection.execute(
        """INSERT INTO orders
           (sap_ov, customer_name, attention_type, app_status, created_at, updated_at)
           VALUES (?, 'Cliente trazabilidad', ?, 'PENDIENTE', ?, ?)""",
        (ov, attention_type, timestamp, timestamp),
    )
    connection.execute(
        """INSERT INTO order_lines
           (sap_ov, source_row, item_code, description, required_qty, pending_qty,
            available_qty, warehouse, article_group, sap_line_status, is_pending_sap)
           VALUES (?, 2, ?, 'Repuesto de prueba', ?, ?, ?, '1', 'REPUESTOS', 'OV ABIERTA', 1)""",
        (ov, np_code, quantity, quantity, available),
    )


def prepare_attention(ov, picker):
    attention = app.order_payload(ov)["attentions"][0]
    app.assign_attention(attention["id"], "current_picker", picker, "admin.test", "ADMINISTRADOR")
    app.change_attention_status(attention["id"], "EN PICKING", picker, "PICKER")
    return app.order_payload(ov)["attentions"][0]


def run():
    test_db = Path(__file__).parent / ".wms-traceability-test.db"
    test_db.unlink(missing_ok=True)
    original_db = app.DB_PATH
    app.DB_PATH = test_db
    try:
        app.init_db()
        with app.db() as connection:
            # A: una BL, una OC, un NP y una OV.
            case_a = create_reception_lots(
                connection,
                "AWB-A",
                [{"np": "NP-A", "qty": 5, "oc": "OC-A", "ov": "OV-A", "ip": "IP-A"}],
                "2026-01-01T08:00:00",
                "AEREO",
            )
            check(len(case_a) == 1 and "BL-AWB-A-OC-OC-A-NP-NP-A" in case_a[0]["lot_code"], "Caso A: código de lote incorrecto")

            # B: una BL con múltiples OC genera lotes físicos independientes.
            case_b = create_reception_lots(
                connection,
                "BL-B",
                [
                    {"np": "NP-B", "qty": 2, "oc": "OC-B1"},
                    {"np": "NP-B", "qty": 3, "oc": "OC-B2"},
                ],
                "2026-01-02T08:00:00",
            )
            check(len(case_b) == 2 and len({lot["oc_number"] for lot in case_b}) == 2, "Caso B: no separó las OC")

            # C y D: mismo NP en dos BL; una OV toma ambos por FIFO.
            old_lot = create_reception_lots(
                connection, "BL-C1", [{"np": "NP-FIFO", "qty": 2, "oc": "OC-C1"}],
                "2026-01-03T08:00:00",
            )[0]
            new_lot = create_reception_lots(
                connection, "BL-C2", [{"np": "NP-FIFO", "qty": 4, "oc": "OC-C2"}],
                "2026-01-04T08:00:00",
            )[0]
            create_order(connection, "OV-FIFO", "NP-FIFO", 5, 10)

            # E: un lote puede abastecer más de una OV sin perder su identidad.
            shared_lot = create_reception_lots(
                connection, "BL-E", [{"np": "NP-SHARED", "qty": 8, "oc": "OC-E"}],
                "2026-01-05T08:00:00",
            )[0]
            create_order(connection, "OV-E1", "NP-SHARED", 3, 8)
            create_order(connection, "OV-E2", "NP-SHARED", 2, 8)
            app.seed_initial_attentions(connection)

        fifo_attention = prepare_attention("OV-FIFO", "picker.fifo")
        fifo_line = fifo_attention["lines"][0]
        fifo_codes = [item["lot_code"] for item in fifo_line["reservations"] if item["lot_code"]]
        check(fifo_codes == [old_lot["lot_code"], new_lot["lot_code"]], "Casos C/D: FIFO o división entre lotes incorrecta")

        # G: no se puede escanear un lote distinto al reservado.
        def scan_wrong_lot():
            with app.db() as connection:
                return validate_lot_scan(
                    connection, fifo_line["id"], shared_lot["lot_code"],
                    "picker.fifo", "PICKER",
                )

        expect(
            ValueError,
            "lote incorrecto",
            scan_wrong_lot,
        )
        with app.db() as connection:
            validate_lot_scan(connection, fifo_line["id"], old_lot["lot_code"], "picker.fifo", "PICKER")
            validate_lot_scan(connection, fifo_line["id"], new_lot["lot_code"], "picker.fifo", "PICKER")
        app.change_attention_status(fifo_attention["id"], "PICKING FINALIZADO", "picker.fifo", "PICKER")

        first_shared = prepare_attention("OV-E1", "picker.e1")
        first_reservation = first_shared["lines"][0]["reservations"][0]
        check(first_reservation["lot_code"] == shared_lot["lot_code"], "Caso E: primera OV no tomó el lote compartido")

        # H: un reinicio administrativo libera el lote y permite reasignar.
        app.admin_reset_attention(first_shared["id"], "admin.test", "ADMINISTRADOR", "Prueba de reasignación")
        reset_attention = app.order_payload("OV-E1")["attentions"][0]
        app.set_attention_type(reset_attention["id"], "COMPLETA", "admin.test", "ADMINISTRADOR")
        app.assign_attention(reset_attention["id"], "current_picker", "picker.nuevo", "admin.test", "ADMINISTRADOR")
        app.change_attention_status(reset_attention["id"], "EN PICKING", "picker.nuevo", "PICKER")
        reassigned = app.order_payload("OV-E1")["attentions"][0]
        check(reassigned["current_picker"] == "picker.nuevo", "Caso H: no permitió reasignar")

        # E y K: otra OV reserva el saldo; no hay negativos ni sobre-reserva.
        second_shared = prepare_attention("OV-E2", "picker.e2")
        with app.db() as connection:
            shared = lot_payload(connection, shared_lot["id"])
            check(shared["available_qty"] == 3, "Casos E/K: saldo compartido incorrecto")
            check(shared["reserved_qty"] == 5, "Casos E/K: reserva concurrente incorrecta")

            # F: la excepción manual no puede superar el plan ni la disponibilidad.
            line_id = second_shared["lines"][0]["id"]
            expect(
                ValueError,
                "solo faltan 0",
                lambda: app.assign_lot_manually(
                    connection, line_id, shared_lot["id"], 1, "admin.test", "Intento excedente"
                ),
            )

            # Ubicación y etiqueta/reimpresión quedan auditadas.
            update_lot_location(connection, shared_lot["id"], "RACK-A-01", "auxiliar.test")
            first_print = register_label_print(connection, shared_lot["id"], 1, "auxiliar.test")
            second_print = register_label_print(connection, shared_lot["id"], 2, "auxiliar.test", True)
            check(first_print["print_type"] == "IMPRESION", "Caso L: primera impresión incorrecta")
            check(second_print["print_type"] == "REIMPRESION", "Caso L: reimpresión no auditada")
            check("OV-E1" in second_print["html"] and "RACK-A-01" in second_print["html"], "Caso L: etiqueta incompleta")

            # J: una recepción histórica no recibe una relación inventada.
            timestamp = app.now()
            historical_shipment = connection.execute(
                """INSERT INTO reception_shipments
                   (bl_awb, app_status, condition_status, created_at, updated_at)
                   VALUES ('BL-HIST', 'CERRADO', 'COMPLETADO', ?, ?)""",
                (timestamp, timestamp),
            ).lastrowid
            historical_line = connection.execute(
                """INSERT INTO reception_lines
                   (shipment_id, source_key, np_code, expected_qty, received_qty)
                   VALUES (?, 'HIST-1', 'NP-HIST', 1, 1)""",
                (historical_shipment,),
            ).lastrowid
            init_traceability_schema(connection)
            status = connection.execute(
                "SELECT lot_status FROM reception_lines WHERE id = ?", (historical_line,)
            ).fetchone()[0]
            check(status == "SIN_LOTE_HISTORICO", "Caso J: historial sin lote no fue identificado")

            results = traceability_search(connection, "NP-SHARED")
            check(results and any(item["movements"] for item in results), "La consulta no devolvió el kardex")
            check(
                not connection.execute(
                    """SELECT 1 FROM inventory_lots
                       WHERE reserved_qty < 0 OR dispatched_qty < 0 OR blocked_qty < 0"""
                ).fetchone(),
                "Caso K: se produjo stock negativo",
            )

        # I: después de picking y antes de entrega se permite devolución auditada.
        reassigned = app.order_payload("OV-E1")["attentions"][0]
        reassigned_line = reassigned["lines"][0]
        with app.db() as connection:
            validate_lot_scan(
                connection, reassigned_line["id"], shared_lot["lot_code"],
                "picker.nuevo", "PICKER",
            )
        app.change_attention_status(reassigned["id"], "PICKING FINALIZADO", "picker.nuevo", "PICKER")
        consumed = app.order_payload("OV-E1")["attentions"][0]["lines"][0]["reservations"][0]
        with app.db() as connection:
            app.return_lot_after_picking(
                connection, consumed["id"], 1, "admin.test", "Devolución de prueba"
            )
            returned = lot_payload(connection, shared_lot["id"])
            check(returned["available_qty"] == 4, "Caso I: la devolución no restituyó el lote")
            movement_types = {
                row[0]
                for row in connection.execute(
                    "SELECT movement_type FROM lot_movements WHERE inventory_lot_id = ?",
                    (shared_lot["id"],),
                ).fetchall()
            }
            check("DEVOLUCION" in movement_types, "Caso I: falta movimiento de devolución")

        print("TRAZABILIDAD OK: casos A-L, FIFO, escaneo, devolución, etiqueta y kardex verificados.")
    finally:
        app.DB_PATH = original_db
        test_db.unlink(missing_ok=True)


if __name__ == "__main__":
    run()
