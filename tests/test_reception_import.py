import sys
from pathlib import Path

import app
from backend.services.reception import (
    add_physical_receipt,
    change_reception_status,
    import_reception_excel_path,
    update_reception_references,
)


def run(excel_path):
    excel_path = Path(excel_path)
    if not excel_path.exists():
        raise FileNotFoundError(excel_path)
    test_db = Path(__file__).parent / ".wms-reception-import-test.db"
    test_db.unlink(missing_ok=True)
    original_db = app.DB_PATH
    app.DB_PATH = test_db
    try:
        app.init_db()
        with app.db() as connection:
            first = import_reception_excel_path(connection, excel_path, "admin.import", "ADMINISTRADOR")
            assert first["shipments"] > 0
            assert first["lines_created"] > 0
            assert len(first["sheets"]) >= 8
            shipment_count = connection.execute("SELECT COUNT(*) FROM reception_shipments").fetchone()[0]
            line_count = connection.execute("SELECT COUNT(*) FROM reception_lines").fetchone()[0]
            shipment = connection.execute(
                "SELECT id FROM reception_shipments ORDER BY id LIMIT 1"
            ).fetchone()
            connection.execute(
                """UPDATE reception_shipments
                   SET current_assistant = 'asistente.import', current_auxiliary = 'auxiliar.import'
                   WHERE id = ?""",
                (shipment["id"],),
            )
            add_physical_receipt(
                connection,
                shipment["id"],
                {"received_packages": 1, "notes": "Control de persistencia"},
                "auxiliar.import",
                "AUXILIAR_RECEPCION",
            )
            update_reception_references(
                connection,
                shipment["id"],
                {"fr_number": "FR-IMPORT-TEST"},
                "admin.import",
                "ADMINISTRADOR",
            )
            change_reception_status(
                connection,
                shipment["id"],
                {"status": "REVISION FISICA"},
                "asistente.import",
                "ASISTENTE_RECEPCION",
            )
            not_hidden_yet = connection.execute(
                """SELECT COUNT(*) FROM reception_lines
                   WHERE shipment_id = ? AND received_qty <> 0""",
                (shipment["id"],),
            ).fetchone()[0]
            assert not_hidden_yet == 0
            change_reception_status(
                connection,
                shipment["id"],
                {"status": "REVISION SISTEMA"},
                "asistente.import",
                "ASISTENTE_RECEPCION",
            )
            non_initialized = connection.execute(
                """SELECT COUNT(*) FROM reception_lines
                   WHERE shipment_id = ? AND received_qty <> expected_qty""",
                (shipment["id"],),
            ).fetchone()[0]
            assert non_initialized == 0

        with app.db() as connection:
            second = import_reception_excel_path(connection, excel_path, "admin.import", "ADMINISTRADOR")
            assert second["shipments_created"] == 0
            assert second["lines_created"] == 0
            assert connection.execute("SELECT COUNT(*) FROM reception_shipments").fetchone()[0] == shipment_count
            assert connection.execute("SELECT COUNT(*) FROM reception_lines").fetchone()[0] == line_count
            preserved = connection.execute(
                "SELECT app_status FROM reception_shipments WHERE id = ?", (shipment["id"],)
            ).fetchone()
            assert preserved["app_status"] == "REVISION SISTEMA"
            assert connection.execute(
                "SELECT COUNT(*) FROM reception_receipts WHERE shipment_id = ?", (shipment["id"],)
            ).fetchone()[0] == 1

        print(
            "OK: importación Recepción; "
            f"{shipment_count} BL/AWB, {line_count} líneas, recarga sin duplicados e historial preservado"
        )
    finally:
        app.DB_PATH = original_db
        test_db.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Uso: py test_reception_import.py <IMPORTACIÓN DE REPUESTOS.xlsx>")
    run(sys.argv[1])
