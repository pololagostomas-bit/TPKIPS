"""Resolve existing BLs without creating provisional expedients during intake."""
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
            raise ValueError("La BL ya esta cerrada; el administrador debe reabrirla antes de otro arribo")
        return matches[0], False
    raise ValueError("BL no encontrada en la base de Importaciones. Actualiza el corte o solicita su registro al administrador")
