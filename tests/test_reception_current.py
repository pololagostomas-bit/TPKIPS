"""Prueba del flujo vigente de Recepción, sin el estado retirado REVISION FISICA."""

from pathlib import Path

import app
from backend.services.reception import (
    add_physical_receipt,
    change_reception_status,
<<<<<<< HEAD
    confirm_reception_transfer,
=======
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312
    create_reception,
    reception_detail,
    update_reception_references,
)


def run():
    test_db = Path(__file__).parent / ".wms-reception-current-test.db"
    test_db.unlink(missing_ok=True)
    original_db = app.DB_PATH
    app.DB_PATH = test_db
    try:
        app.init_db()
        with app.db() as connection:
            shipment = create_reception(
                connection,
                {
                    "bl_awb": "BL-CURRENT-001",
                    "transport_type": "AEREO",
                    "expected_packages": 1,
                    "supplier": "Proveedor piloto",
                    "ip_reference": "IP-CURRENT-001",
                    "current_assistant": "asistente.actual",
                    "current_auxiliary": "auxiliar.actual",
                },
                "admin.actual",
                "ADMINISTRADOR",
            )
            shipment_id = shipment["id"]
            connection.execute(
                """INSERT INTO reception_lines
                   (shipment_id, source_key, np_code, description, expected_qty)
                   VALUES (?, ?, ?, ?, ?)""",
                (shipment_id, "current-line-001", "NP-001", "Repuesto piloto", 4),
            )

            add_physical_receipt(
                connection,
                shipment_id,
                {"received_packages": 1, "notes": "Arribo completo"},
                "auxiliar.actual",
                "AUXILIAR_RECEPCION",
            )
            update_reception_references(
                connection,
                shipment_id,
                {"fr_number": "FR-CURRENT-001"},
                "admin.actual",
                "ADMINISTRADOR",
            )

            # Con FR pero sin EM, el asistente sí puede iniciar la revisión de sistema.
            current = change_reception_status(
                connection,
                shipment_id,
                {"status": "REVISION SISTEMA"},
                "asistente.actual",
                "ASISTENTE_RECEPCION",
            )
            assert current["app_status"] == "REVISION SISTEMA"
            assert current["accounting_status"] == "PENDIENTE EM"
            assert float(current["lines"][0]["received_qty"]) == 4

            change_reception_status(
                connection,
                shipment_id,
                {"status": "EM"},
                "asistente.actual",
                "ASISTENTE_RECEPCION",
            )
            update_reception_references(
                connection,
                shipment_id,
                {"em_number": "EM-CURRENT-001"},
                "admin.actual",
                "ADMINISTRADOR",
            )
            change_reception_status(
                connection,
                shipment_id,
                {"status": "UBICACION"},
                "asistente.actual",
                "ASISTENTE_RECEPCION",
            )
            change_reception_status(
                connection,
                shipment_id,
                {"status": "VALIDACION"},
                "asistente.actual",
                "ASISTENTE_RECEPCION",
            )
            change_reception_status(
                connection,
                shipment_id,
                {"status": "SOLICITUD TRANSFERENCIA", "validation_result": "CONFORME"},
                "asistente.actual",
                "ASISTENTE_RECEPCION",
            )
<<<<<<< HEAD
            confirm_reception_transfer(
                connection,
                shipment_id,
                {"checked": True},
                "asistente.actual",
                "ASISTENTE_RECEPCION",
            )
=======
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312
            final = change_reception_status(
                connection,
                shipment_id,
                {"status": "CERRADO"},
                "asistente.actual",
                "ASISTENTE_RECEPCION",
            )
            assert final["app_status"] == "CERRADO"
            notification = connection.execute(
                """SELECT notification_type, status
                   FROM reception_notifications
                   WHERE shipment_id = ?""",
                (shipment_id,),
            ).fetchone()
            assert notification["notification_type"] == "SOLICITUD_TRANSFERENCIA"
            assert notification["status"] == "PENDIENTE ENVIO"

        with app.db() as connection:
            detail = reception_detail(
                connection, shipment_id, "ASISTENTE_RECEPCION", "asistente.actual"
            )
            assert detail["app_status"] == "CERRADO"
<<<<<<< HEAD
            # El packing list de Recepción conserva su cantidad requerida y
            # siempre expone los tres indicadores del corte SAP, incluso
            # antes de que exista un NP en el snapshot de inventario.
            line = detail["lines"][0]
            assert float(line["expected_qty"]) == 4
            assert {"stock_ov_commitment_qty", "stock_cut_qty", "stock_available_qty"} <= set(line)
=======
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312
            history_count = connection.execute(
                "SELECT COUNT(*) FROM reception_history WHERE shipment_id = ?",
                (shipment_id,),
            ).fetchone()[0]
            assert history_count >= 7

        print("RECEPCION ACTUAL OK: FR pendiente EM, flujo completo, historial y aviso verificados.")
    finally:
        app.DB_PATH = original_db
        test_db.unlink(missing_ok=True)


if __name__ == "__main__":
    run()
