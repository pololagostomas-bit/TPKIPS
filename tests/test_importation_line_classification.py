"""Regresión para clasificar SKU de Picking por Importaciones o Stock."""

from pathlib import Path

import app


def run():
    test_db = Path(__file__).parent / ".wms-line-classification-test.db"
    test_db.unlink(missing_ok=True)
    original_db = app.DB_PATH
    app.DB_PATH = test_db
    try:
        app.init_db()
        with app.db() as connection:
            connection.execute(
                """INSERT INTO orders
                   (sap_ov, customer_name, created_at, updated_at)
                   VALUES (?, ?, ?, ?)""",
                ("OV-MIX-001", "TRITON TRADING S.A.", app.now(), app.now()),
            )
            connection.executemany(
                """INSERT INTO order_lines
                   (sap_ov, source_row, item_code, description, pending_qty, is_pending_sap)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                [
                    ("OV-MIX-001", 2, "SKU-AIR/01", "Repuesto aéreo", 2),
                    ("OV-MIX-001", 3, "SKU-STOCK-02", "Repuesto de stock", 1),
                ],
            )
            connection.execute(
                """INSERT INTO order_importation_refs
                   (sap_ov, bl_awb, transport_type, item_code, source_sheet, source_row, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("OV-MIX-001", "AWB-001", "COURIER", "SKU-AIR01", "SUSANA", 2, app.now()),
            )
            context = app.picking_importation_context(connection, "OV-MIX-001")

            connection.execute(
                """INSERT INTO orders
                   (sap_ov, customer_name, created_at, updated_at)
                   VALUES (?, ?, ?, ?)""",
                ("OV-AIR-ONLY", "CLIENTE AEREO", app.now(), app.now()),
            )
            connection.execute(
                """INSERT INTO order_lines
                   (sap_ov, source_row, item_code, description, pending_qty, is_pending_sap)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                ("OV-AIR-ONLY", 2, "SKU-AIR-ONLY", "Solo aéreo", 1),
            )
            connection.execute(
                """INSERT INTO order_importation_refs
                   (sap_ov, bl_awb, transport_type, item_code, source_sheet, source_row, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("OV-AIR-ONLY", "AWB-002", "AEREO", "SKU-AIR-ONLY", "SUSANA", 3, app.now()),
            )
            air_only = app.picking_importation_context(connection, "OV-AIR-ONLY")

        assert app.normalize_transport("Courier") == "AEREO"
        assert context["transport_type"] == "MIXTO (AEREO Y STOCK)"
        assert context["picking_blocked"] is False
        assert context["reception_status"] == "PENDIENTE PARCIAL"
        assert air_only["picking_blocked"] is True
        by_code = {row["item_code"]: row for row in context["line_categories"]}
        assert by_code["SKU-AIR/01"]["classification"] == "AEREO"
        assert by_code["SKU-AIR/01"]["importation_match"] is True
        assert by_code["SKU-STOCK-02"]["classification"] == "STOCK"
        assert by_code["SKU-STOCK-02"]["importation_match"] is False
        assert app.summarize_line_categories(["AEREO", "MARITIMO", "STOCK"]) == (
            "MIXTO (AEREO, MARITIMO Y STOCK)"
        )
        print("CLASIFICACION DE SKU OK: AEREO/COURIER, MARITIMO, STOCK y variantes mixtas")
    finally:
        app.DB_PATH = original_db
        test_db.unlink(missing_ok=True)


if __name__ == "__main__":
    run()
