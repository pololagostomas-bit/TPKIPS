"""Valida la importación idempotente de un Excel real exportado desde SAP."""

import argparse
import sqlite3
from pathlib import Path

import app


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def counts():
    with app.db() as connection:
        return {
            "orders": connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
            "sap_lines": connection.execute("SELECT COUNT(*) FROM order_lines").fetchone()[0],
            "pending_lines": connection.execute("SELECT COUNT(*) FROM order_lines WHERE is_pending_sap = 1").fetchone()[0],
            "attentions": connection.execute("SELECT COUNT(*) FROM attentions").fetchone()[0],
            "attention_lines": connection.execute("SELECT COUNT(*) FROM attention_lines").fetchone()[0],
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("excel", type=Path)
    args = parser.parse_args()
    check(args.excel.exists(), f"No existe el Excel: {args.excel}")

    original_db = app.DB_PATH
    test_db = app.ROOT / "real_import_test.db"
    if test_db.exists():
        test_db.unlink()
    app.DB_PATH = test_db
    try:
        app.init_db()
        first = app.import_excel(args.excel, reset=True)
        first_counts = counts()
        check(first["orders"] > 0 and first["lines"] > 0, "El Excel no importó OVs o líneas")
        check(first_counts["orders"] == first["orders"], "Cantidad de OVs inconsistente")
        check(first_counts["pending_lines"] == first["lines"], "Cantidad de SKU pendientes inconsistente")
        check(first_counts["attentions"] <= first_counts["orders"], "Una OV no debe tener más de una Atención 1")
        check(first_counts["attention_lines"] == first_counts["pending_lines"], "Cada SKU pendiente debe estar vinculado a Atención 1")
        initial_list = app.orders_payload()
        check(0 < len(initial_list) <= 200, "La pantalla debe mostrar hasta 200 OVs operativas")
        sample_ov = initial_list[0]["sap_ov"]
        check(any(order["sap_ov"] == sample_ov for order in app.orders_payload(sample_ov)), "La búsqueda por OV debe encontrar el registro")
        check(app.orders_payload("OV-QUE-NO-EXISTE-999") == [], "La búsqueda inexistente debe devolver una lista vacía")

        second = app.import_excel(args.excel, reset=False)
        second_counts = counts()
        check(second == first, "La segunda importación debe leer el mismo volumen")
        check(second_counts == first_counts, "Reimportar no debe duplicar OVs, líneas ni atenciones")
        print(
            "IMPORTACIÓN REAL OK: "
            f"{first_counts['orders']} OVs, {first_counts['pending_lines']} SKU pendientes y "
            f"{first_counts['attentions']} atenciones sin duplicados al reimportar."
        )
    finally:
        app.DB_PATH = original_db
        if test_db.exists():
            try:
                test_db.unlink()
            except PermissionError as error:
                raise AssertionError("La prueba dejó bloqueada la base temporal") from error


if __name__ == "__main__":
    main()
