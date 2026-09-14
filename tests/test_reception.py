import os
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import app
from backend.services.reception import (
    add_physical_receipt,
    change_reception_status,
    create_reception,
    list_receptions,
    reception_detail,
    update_reception_line_quantity,
    update_reception_references,
)


def expect_error(error_type, function, *args):
    try:
        function(*args)
    except error_type:
        return
    raise AssertionError(f"Se esperaba {error_type.__name__}")


@contextmanager
def isolated_database():
    test_db = Path(__file__).parent / f".wms-reception-{uuid4().hex}.db"
    try:
        with patch.object(app, "DB_PATH", test_db), patch.dict(
            os.environ, {"TRITON_IMPORTACIONES_EMAILS": "recepcion@example.test", "TRITON_MAIL_ENABLED": "0"}
        ):
            yield test_db
    finally:
        test_db.unlink(missing_ok=True)


def run():
    with isolated_database():
        app.init_db()
        with app.db() as connection:
            expect_error(
                PermissionError,
                create_reception,
                connection,
                {"bl_awb": "AWB-BLOQUEADA"},
                "asistente.1",
                "ASISTENTE_RECEPCION",
            )
            shipment = create_reception(
                connection,
                {
                    "bl_awb": "AWB-TEST-001",
                    "transport_type": "AEREO",
                    "expected_packages": 10,
                    "supplier": "Proveedor piloto",
                    "primary_oc": "OC-100",
                    "primary_ov": "OV-200",
                    "current_assistant": "asistente.1",
                    "current_auxiliary": "auxiliar.1",
                },
                "admin.test",
                "ADMINISTRADOR",
            )
            shipment_id = shipment["id"]
            connection.execute(
                "UPDATE reception_shipments SET expected_packages = 10 WHERE id = ?",
                (shipment_id,),
            )
            connection.execute(
                """INSERT INTO reception_lines
                   (shipment_id, source_key, np_code, description, expected_qty)
                   VALUES (?, ?, ?, ?, ?)""",
                (shipment_id, "test-line-100", "NP-100", "Repuesto de prueba", 5),
            )
            shipment = add_physical_receipt(
                connection,
                shipment_id,
                {"received_packages": 6, "notes": "Primer arribo"},
                "auxiliar.1",
                "AUXILIAR_RECEPCION",
            )
            assert shipment["app_status"] == "ARRIBADO"
            assert shipment["condition_status"] == "SALDO POR ARRIBAR"
            assert any(
                row["id"] == shipment_id
                for row in list_receptions(connection, "AWB-TEST-001", "ASISTENTE_RECEPCION", "asistente.1")
            )
            expect_error(
                PermissionError,
                change_reception_status,
                connection,
                shipment_id,
                {"status": "REVISION SISTEMA"},
                "auxiliar.1",
                "AUXILIAR_RECEPCION",
            )
            shipment = add_physical_receipt(
                connection,
                shipment_id,
                {"received_packages": 4, "notes": "Saldo final"},
                "auxiliar.1",
                "AUXILIAR_RECEPCION",
            )
            assert shipment["condition_status"] == "ARRIBO COMPLETO"
            assert len(shipment["receipts"]) == 2

            expect_error(
                PermissionError,
                update_reception_line_quantity,
                connection,
                shipment_id,
                shipment["lines"][0]["id"],
                {"received_qty": 4, "reason": "No debe editarse todavía"},
                "auxiliar.1",
                "AUXILIAR_RECEPCION",
            )
            assert shipment["accounting_status"] == "PENDIENTE CONTABILIDAD"
            assert shipment["accounting_warning"]
            assert any(
                row["id"] == shipment_id
                for row in list_receptions(connection, "AWB-TEST-001", "ASISTENTE_RECEPCION")
            )

            shipment = change_reception_status(
                connection, shipment_id, {"status": "REVISION SISTEMA"}, "asistente.1", "ASISTENTE_RECEPCION"
            )
            assert shipment["lines"][0]["received_qty"] == 5
            shipment = update_reception_line_quantity(
                connection,
                shipment_id,
                shipment["lines"][0]["id"],
                {"received_qty": 4, "reason": "Faltante de una unidad"},
                "auxiliar.1",
                "AUXILIAR_RECEPCION",
            )
            assert shipment["lines"][0]["received_qty"] == 4
            notification = connection.execute(
                """SELECT notification_type, recipient, status
                   FROM reception_notifications WHERE shipment_id = ?""",
                (shipment_id,),
            ).fetchone()
            assert notification["notification_type"] == "OBSERVACION_IMPORTACIONES"
            assert notification["recipient"] == "recepcion@example.test"
            assert notification["status"] == "PENDIENTE ENVIO"
            expect_error(
                PermissionError, change_reception_status, connection, shipment_id,
                {"status": "EM"}, "asistente.1", "ASISTENTE_RECEPCION",
            )
            shipment = update_reception_references(
                connection, shipment_id, {"fr_number": "FR-900"}, "admin.test", "ADMINISTRADOR"
            )
            assert shipment["accounting_status"] == "PENDIENTE EM"
            assert not shipment["accounting_warning"]
            change_reception_status(
                connection, shipment_id, {"status": "EM"}, "asistente.1", "ASISTENTE_RECEPCION"
            )
            expect_error(
                PermissionError,
                change_reception_status,
                connection,
                shipment_id,
                {"status": "UBICACION"},
                "asistente.1",
                "ASISTENTE_RECEPCION",
            )
            update_reception_references(
                connection,
                shipment_id,
                {"em_number": "EM-901"},
                "admin.test",
                "ADMINISTRADOR",
            )
            change_reception_status(
                connection, shipment_id, {"status": "UBICACION"}, "auxiliar.1", "AUXILIAR_RECEPCION"
            )
            change_reception_status(
                connection, shipment_id, {"status": "VALIDACION"}, "asistente.1", "ASISTENTE_RECEPCION"
            )
            shipment = change_reception_status(
                connection,
                shipment_id,
                {"status": "UBICACION", "validation_result": "NO CONFORME"},
                "asistente.1",
                "ASISTENTE_RECEPCION",
            )
            assert shipment["app_status"] == "UBICACION"
            assert shipment["condition_status"] == "REUBICACION REQUERIDA"
            change_reception_status(
                connection, shipment_id, {"status": "VALIDACION"}, "auxiliar.1", "AUXILIAR_RECEPCION"
            )
            change_reception_status(
                connection,
                shipment_id,
                {"status": "SOLICITUD TRANSFERENCIA", "validation_result": "CONFORME"},
                "asistente.1",
                "ASISTENTE_RECEPCION",
            )
            transfer_notification = connection.execute(
                """SELECT notification_type FROM reception_notifications
                   WHERE shipment_id = ? AND notification_type = 'SOLICITUD_TRANSFERENCIA'""",
                (shipment_id,),
            ).fetchone()
            assert transfer_notification is not None
            shipment = change_reception_status(
                connection, shipment_id, {"status": "CERRADO"}, "asistente.1", "ASISTENTE_RECEPCION"
            )
            assert shipment["app_status"] == "CERRADO"
            assert shipment["condition_status"] == "COMPLETADO"

            admin_detail = reception_detail(connection, shipment_id, "ADMINISTRADOR")
            assistant_detail = reception_detail(connection, shipment_id, "ASISTENTE_RECEPCION")
            assert len(admin_detail["history"]) >= 10
            assert "history" not in assistant_detail
            assert list_receptions(
                connection, "AWB-TEST-001", "ASISTENTE_RECEPCION", "asistente.1"
            )[0]["id"] == shipment_id
            expect_error(
                PermissionError,
                reception_detail,
                connection,
                shipment_id,
                "ASISTENTE_RECEPCION",
                "otro.asistente",
            )
            assert list_receptions(connection, "FR-900", "ADMINISTRADOR")[0]["id"] == shipment_id
            expect_error(PermissionError, list_receptions, connection, "", "PICKER")

    print("OK: módulo Recepción, permisos, arribos parciales, FR/EM, validación e historial")


if __name__ == "__main__":
    run()
