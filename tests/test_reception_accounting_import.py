import sys
from pathlib import Path

import app
from backend.services.reception import (
    import_reception_accounting_excel_path,
    import_reception_excel_path,
    reception_detail,
    update_reception_line_quantity,
)


def expect_permission_error(connection, accounting_path):
    try:
        import_reception_accounting_excel_path(
            connection,
            accounting_path,
            "asistente.test",
            "ASISTENTE_RECEPCION",
        )
    except PermissionError:
        return
    raise AssertionError("Un asistente no debe poder cargar el Excel contable")


def run(reception_path, accounting_path):
    reception_path = Path(reception_path)
    accounting_path = Path(accounting_path)
    if not reception_path.exists():
        raise FileNotFoundError(reception_path)
    if not accounting_path.exists():
        raise FileNotFoundError(accounting_path)

    test_db = Path(__file__).parent / ".wms-accounting-import-test.db"
    test_db.unlink(missing_ok=True)
    original_db = app.DB_PATH
    app.DB_PATH = test_db
    try:
        app.init_db()
        with app.db() as connection:
            reception_result = import_reception_excel_path(
                connection,
                reception_path,
                "admin.test",
                "ADMINISTRADOR",
            )
            assert reception_result["shipments"] > 0
            expect_permission_error(connection, accounting_path)

            first = import_reception_accounting_excel_path(
                connection,
                accounting_path,
                "admin.test",
                "ADMINISTRADOR",
            )
            assert first["records_read"] > 0
            assert first["matched_records"] > 0
            assert first["references_created"] == first["matched_records"]
            assert first["shipments_updated"] > 0
            assert first["ambiguous_count"] == 0
            assert "conflict_ip_count" in first
            if first["conflict_ip_count"]:
                assert connection.execute(
                    "SELECT COUNT(*) FROM reception_shipments WHERE accounting_status = 'CONFLICTO IP'"
                ).fetchone()[0] > 0

            reference_count = connection.execute(
                "SELECT COUNT(*) FROM reception_accounting_refs"
            ).fetchone()[0]
            assert reference_count == first["matched_records"]
            multiple = connection.execute(
                """SELECT shipment_id, COUNT(*) AS total
                   FROM reception_accounting_refs
                   GROUP BY shipment_id HAVING COUNT(*) > 1
                   ORDER BY total DESC LIMIT 1"""
            ).fetchone()
            assert multiple is not None
            shipment_id = multiple["shipment_id"]
            summary = connection.execute(
                """SELECT fr_number, em_number, source_reception_date, em_date,
                          app_status, condition_status
                   FROM reception_shipments WHERE id = ?""",
                (shipment_id,),
            ).fetchone()
            assert summary["fr_number"]
            assert summary["em_number"]
            assert summary["source_reception_date"]
            assert summary["em_date"]
            assert summary["app_status"] == "CERRADO"
            assert summary["condition_status"] == "COMPLETADO"
            complete_lines = connection.execute(
                "SELECT expected_qty, received_qty FROM reception_lines WHERE shipment_id = ? AND expected_qty > 0",
                (shipment_id,),
            ).fetchall()
            assert complete_lines and all(
                float(row["received_qty"] or 0) == float(row["expected_qty"] or 0)
                for row in complete_lines
            ), "Las líneas con FR y EM completas deben tomar la cantidad esperada"

            connection.execute(
                """UPDATE reception_shipments
                   SET current_assistant = 'asistente.preservado', app_status = 'REVISION SISTEMA'
                   WHERE id = ?""",
                (shipment_id,),
            )

        with app.db() as connection:
            detail = reception_detail(
                connection, shipment_id, "ASISTENTE_RECEPCION", "asistente.preservado"
            )
            editable_line = next(
                line for line in detail["lines"] if float(line["expected_qty"] or 0) > 0
            )
            assert editable_line["accounting_locked"] == 1
            half_quantity = float(editable_line["expected_qty"]) / 2
            updated_detail = update_reception_line_quantity(
                connection,
                shipment_id,
                editable_line["id"],
                {"received_qty": half_quantity, "reason": "Validación de prueba"},
                "asistente.preservado",
                "ASISTENTE_RECEPCION",
            )
            updated_line = next(
                line for line in updated_detail["lines"] if line["id"] == editable_line["id"]
            )
            assert float(updated_line["received_qty"]) == half_quantity, (
                "Una línea completa contablemente debe seguir siendo editable durante revisión de sistema"
            )
            second = import_reception_accounting_excel_path(
                connection,
                accounting_path,
                "admin.test",
                "ADMINISTRADOR",
            )
            assert second["references_created"] == 0
            assert second["references_updated"] == 0
            assert second["references_unchanged"] == first["matched_records"]
            assert connection.execute(
                "SELECT COUNT(*) FROM reception_accounting_refs"
            ).fetchone()[0] == reference_count
            preserved = connection.execute(
                """SELECT current_assistant, app_status
                   FROM reception_shipments WHERE id = ?""",
                (shipment_id,),
            ).fetchone()
            assert preserved["current_assistant"] == "asistente.preservado"
            assert preserved["app_status"] == "REVISION SISTEMA"

        print(
            "OK: Excel contable; "
            f"{first['records_read']} filas leídas, {first['matched_records']} referencias "
            f"en {first['shipments_updated']} BL/AWB, recarga idempotente y flujo preservado"
        )
    finally:
        app.DB_PATH = original_db
        test_db.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(
            "Uso: py test_reception_accounting_import.py "
            "<IMPORTACIÓN DE REPUESTOS.xlsx> <FACTURAS DHL...xlsx>"
        )
    run(sys.argv[1], sys.argv[2])
