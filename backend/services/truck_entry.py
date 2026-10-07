"""Register physically entered BLs without inventing expected quantities."""
import re

from backend.services import reception


def resolve_entered_bl(connection, code, username, role):
    reception.require_reception_access(role)
    if role not in {"ADMINISTRADOR", "ASISTENTE_RECEPCION"}:
        raise PermissionError("Solo un administrador o asistente puede ingresar una BL")
    raw = str(code or "").strip()
    if not raw or len(raw) > 120 or any(ord(char) < 32 for char in raw):
        raise ValueError("Ingresa una BL/AWB valida")
    normalized = re.sub(r"\s+", "", raw).replace("-", "").upper()
    matches = connection.execute(
        """SELECT * FROM reception_shipments
           WHERE upper(replace(replace(trim(bl_awb),' ',''),'-','')) = ?""",
        (normalized,),
    ).fetchall()
    if len(matches) > 1:
        raise ValueError("Hay varios expedientes para esta BL; revisa sus camiones antes de ingresarla")
    if matches:
        if str(matches[0]["app_status"] or "").upper() == "CERRADO":
            raise ValueError("La BL ya esta cerrada y no puede recibirse nuevamente")
        return matches[0], False
    timestamp = reception.reception_now()
    shipment_id = connection.execute(
        """INSERT INTO reception_shipments
           (bl_awb, transport_type, expected_packages, created_at, updated_at)
           VALUES (?, 'AEREO', 0, ?, ?)""",
        (raw, timestamp, timestamp),
    ).lastrowid
    reception._write_history(connection, shipment_id, "CREACION", "bl_awb", "", raw,
                             username, "BL ingresada en recepcion; fuente documental pendiente")
    reception._ensure_default_reception_assignees(
        connection, shipment_id, username, "Ingreso de BL en recepcion")
    return connection.execute("SELECT * FROM reception_shipments WHERE id=?",
                              (shipment_id,)).fetchone(), True
