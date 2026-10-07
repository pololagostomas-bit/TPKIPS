"""Cancel a truck atomically without removing documents or audit history."""
from backend.services import reception


def cancel_truck_guide(connection, truck_guide, username, role):
    reception.require_reception_access(role)
    if role not in {"ADMINISTRADOR", "ASISTENTE_RECEPCION"}:
        raise PermissionError("Tu rol no puede cancelar un camion")
    guide = str(truck_guide or "").strip()
    row = reception._truck_guide_header(connection, guide, create_if_missing=False)
    if not row:
        raise ValueError("La guia de camion no existe")
    header = dict(row)
    status = reception._truck_guide_status(header)
    if status == "CANCELADA":
        return {"truck_guide": guide, "cancelled": True, "guide_status": status}
    if role != "ADMINISTRADOR":
        assigned = connection.execute(
            """SELECT shipment_id FROM reception_truck_bl_manifest
               WHERE lower(truck_guide)=lower(?) AND COALESCE(operational_active,1)=1""",
            (guide,),
        ).fetchall()
        if not assigned and header.get("created_by") != username:
            raise PermissionError("Solo puedes cancelar un camion propio o con BL asignadas a tu usuario")
        for item in assigned:
            reception._get_reception_shipment(connection, item["shipment_id"], username, role)
    arrived = connection.execute(
        "SELECT 1 FROM reception_truck_bl_arrivals WHERE lower(truck_guide)=lower(?) LIMIT 1",
        (guide,),
    ).fetchone()
    if (arrived or status not in {"PENDIENTE", "EN_CURSO"}) and role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede anular una llegada ya guardada")
    connection.execute("SAVEPOINT cancel_truck_control")
    try:
        if arrived or status not in {"PENDIENTE", "EN_CURSO"}:
            reception.revert_truck_guide(connection, guide, username, role, "PENDIENTE")
        if int(header.get("scanner_enabled") or 0):
            result = reception.cancel_scanned_truck_arrival(connection, guide, username, role)
        else:
            timestamp = reception.reception_now()
            manifests = connection.execute(
                """SELECT shipment_id FROM reception_truck_bl_manifest
                   WHERE lower(truck_guide)=lower(?) AND COALESCE(operational_active,1)=1""",
                (guide,),
            ).fetchall()
            for item in manifests:
                sid = int(item["shipment_id"])
                previous = connection.execute(
                    """SELECT m.truck_guide FROM reception_truck_bl_manifest m
                       JOIN reception_truck_guides g ON lower(g.guide_code)=lower(m.truck_guide)
                       WHERE m.shipment_id=? AND lower(m.truck_guide)<>lower(?)
                         AND COALESCE(m.operational_active,1)=1 AND g.guide_status<>'CANCELADA'
                       ORDER BY m.updated_at DESC, m.truck_guide DESC LIMIT 1""", (sid, guide)
                ).fetchone()
                previous_guide = previous["truck_guide"] if previous else None
                connection.execute(
                    """UPDATE reception_shipments SET truck_guide=?, updated_at=?
                       WHERE id=? AND lower(COALESCE(truck_guide,''))=lower(?)""",
                    (previous_guide, timestamp, sid, guide),
                )
                reception._write_history(
                    connection, sid, "CANCELACION CAMION", f"guia:{guide}:bl",
                    guide, previous_guide or "", username,
                    "Camion cancelado; documentos y otras llegadas conservados",
                )
            connection.execute(
                """UPDATE reception_truck_bl_manifest SET operational_active=0, updated_at=?
                   WHERE lower(truck_guide)=lower(?)""", (timestamp, guide)
            )
            connection.execute(
                """UPDATE reception_truck_guides SET guide_status='CANCELADA',
                     planned_packages=0, count_enabled_at=NULL, count_enabled_by=NULL, updated_at=?
                   WHERE lower(guide_code)=lower(?)""", (timestamp, guide)
            )
            result = {"truck_guide": guide, "cancelled": True, "guide_status": "CANCELADA",
                      "cancelled_bls": len(manifests)}
        connection.execute("RELEASE cancel_truck_control")
        return result
    except Exception:
        connection.execute("ROLLBACK TO cancel_truck_control")
        connection.execute("RELEASE cancel_truck_control")
        raise
