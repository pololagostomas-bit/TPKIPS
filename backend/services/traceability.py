"""Trazabilidad física por lote para TRITON WMS.

La capa de lotes complementa, no reemplaza, el stock contable/global:

    Recepción -> lote -> reserva OV -> escaneo -> picking -> entrega

Los movimientos son append-only desde la aplicación. Toda corrección genera
un movimiento inverso y nunca borra el kardex.
"""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime
from backend.services.daily_operations import advanced_lots_enabled, local_now


EPSILON = 0.000001
LOT_RESERVATION_STATES = {
    "PENDIENTE",
    "RESERVADA",
    "PARCIAL",
    "SIN_STOCK",
    "LIBERADA",
    "CONSUMIDA",
}


def trace_now():
    return local_now()


def _text(value):
    return "" if value is None else str(value).strip()


def _number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def normalize_identifier(value):
    normalized = unicodedata.normalize("NFKD", _text(value)).encode("ascii", "ignore").decode("ascii")
    return "".join(character for character in normalized.upper() if character.isalnum())


def normalize_lot_segment(value, fallback="SINREF", maximum=28):
    normalized = unicodedata.normalize("NFKD", _text(value)).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", normalized.upper()).strip("-")
    return (normalized or fallback)[:maximum]


def init_traceability_schema(connection):
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS inventory_lots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lot_code TEXT NOT NULL UNIQUE,
            reception_shipment_id INTEGER REFERENCES reception_shipments(id),
            reception_line_id INTEGER REFERENCES reception_lines(id),
            bl_awb TEXT,
            oc_number TEXT,
            ip_reference TEXT,
            em_number TEXT,
            item_key TEXT NOT NULL,
            item_code TEXT NOT NULL,
            description TEXT,
            received_qty REAL NOT NULL DEFAULT 0 CHECK(received_qty >= 0),
            reserved_qty REAL NOT NULL DEFAULT 0 CHECK(reserved_qty >= 0),
            dispatched_qty REAL NOT NULL DEFAULT 0 CHECK(dispatched_qty >= 0),
            blocked_qty REAL NOT NULL DEFAULT 0 CHECK(blocked_qty >= 0),
            received_at TEXT,
            location TEXT,
            status TEXT NOT NULL DEFAULT 'DISPONIBLE',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS lot_reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_allocation_id INTEGER REFERENCES stock_allocations(id),
            attention_id INTEGER NOT NULL REFERENCES attentions(id),
            attention_line_id INTEGER NOT NULL REFERENCES attention_lines(id),
            inventory_lot_id INTEGER REFERENCES inventory_lots(id),
            requested_qty REAL NOT NULL DEFAULT 0 CHECK(requested_qty >= 0),
            reserved_qty REAL NOT NULL DEFAULT 0 CHECK(reserved_qty >= 0),
            consumed_qty REAL NOT NULL DEFAULT 0 CHECK(consumed_qty >= 0),
            status TEXT NOT NULL DEFAULT 'PENDIENTE',
            match_method TEXT,
            scanned_at TEXT,
            scanned_by TEXT,
            expected_lot_code TEXT,
            actual_lot_code TEXT,
            exception_reason TEXT,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS lot_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inventory_lot_id INTEGER NOT NULL REFERENCES inventory_lots(id),
            lot_reservation_id INTEGER REFERENCES lot_reservations(id),
            movement_type TEXT NOT NULL,
            item_code TEXT NOT NULL,
            lot_code TEXT NOT NULL,
            quantity REAL NOT NULL,
            before_received REAL NOT NULL,
            after_received REAL NOT NULL,
            before_reserved REAL NOT NULL,
            after_reserved REAL NOT NULL,
            before_dispatched REAL NOT NULL,
            after_dispatched REAL NOT NULL,
            before_blocked REAL NOT NULL,
            after_blocked REAL NOT NULL,
            before_available REAL NOT NULL,
            after_available REAL NOT NULL,
            origin_location TEXT,
            destination_location TEXT,
            sap_ov TEXT,
            attention_id INTEGER,
            username TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS label_prints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inventory_lot_id INTEGER NOT NULL REFERENCES inventory_lots(id),
            copies INTEGER NOT NULL DEFAULT 1 CHECK(copies > 0),
            print_type TEXT NOT NULL,
            username TEXT NOT NULL,
            printed_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_lots_item_fifo
            ON inventory_lots(item_key, received_at, id);
        CREATE INDEX IF NOT EXISTS idx_lots_reception
            ON inventory_lots(reception_shipment_id, reception_line_id);
        CREATE INDEX IF NOT EXISTS idx_lot_reservations_attention
            ON lot_reservations(attention_id, attention_line_id, status);
        CREATE INDEX IF NOT EXISTS idx_lot_movements_lot
            ON lot_movements(inventory_lot_id, id);

        CREATE TRIGGER IF NOT EXISTS lot_movements_no_update
        BEFORE UPDATE ON lot_movements
        BEGIN
            SELECT RAISE(ABORT, 'El kardex de lotes es inmutable');
        END;

        CREATE TRIGGER IF NOT EXISTS lot_movements_no_delete
        BEFORE DELETE ON lot_movements
        BEGIN
            SELECT RAISE(ABORT, 'El kardex de lotes es inmutable');
        END;
        """
    )
    _ensure_column(connection, "reception_lines", "lot_status", "TEXT NOT NULL DEFAULT 'PENDIENTE'")
    # El sistema anterior no creaba lotes. Esas recepciones se conservan como
    # historia, pero nunca se les inventa una relación física retroactiva.
    connection.execute(
        """UPDATE reception_lines
           SET lot_status = 'SIN_LOTE_HISTORICO'
           WHERE lot_status = 'PENDIENTE'
             AND shipment_id IN (
                 SELECT id FROM reception_shipments
                 WHERE app_status IN ('EM', 'UBICACION', 'VALIDACION',
                                      'SOLICITUD TRANSFERENCIA', 'CERRADO')
             )
             AND NOT EXISTS (
                 SELECT 1 FROM inventory_lots lot
                 WHERE lot.reception_line_id = reception_lines.id
             )"""
    )


def _ensure_column(connection, table, column, definition):
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def lot_available(lot):
    return max(
        0.0,
        _number(lot["received_qty"])
        - _number(lot["reserved_qty"])
        - _number(lot["dispatched_qty"])
        - _number(lot["blocked_qty"]),
    )


def _as_dict(row):
    return dict(row) if row is not None else None


def lot_payload(connection, lot_id):
    row = connection.execute(
        """SELECT lot.*,
                  (SELECT COUNT(*) FROM label_prints p WHERE p.inventory_lot_id = lot.id) AS print_count
           FROM inventory_lots lot WHERE lot.id = ?""",
        (lot_id,),
    ).fetchone()
    if not row:
        return None
    result = _as_dict(row)
    result["available_qty"] = lot_available(row)
    result["reservations"] = [
        _as_dict(item)
        for item in connection.execute(
            """SELECT lr.*, a.sap_ov
               FROM lot_reservations lr
               JOIN attentions a ON a.id = lr.attention_id
               WHERE lr.inventory_lot_id = ? ORDER BY lr.id DESC""",
            (lot_id,),
        ).fetchall()
    ]
    return result


def lots_for_shipment(connection, shipment_id):
    return [
        lot_payload(connection, row["id"])
        for row in connection.execute(
            "SELECT id FROM inventory_lots WHERE reception_shipment_id = ? ORDER BY received_at, id",
            (shipment_id,),
        ).fetchall()
    ]


def _snapshot(lot):
    return {
        "received": _number(lot["received_qty"]),
        "reserved": _number(lot["reserved_qty"]),
        "dispatched": _number(lot["dispatched_qty"]),
        "blocked": _number(lot["blocked_qty"]),
        "available": lot_available(lot),
    }


def _write_movement(
    connection,
    lot_before,
    lot_after,
    movement_type,
    quantity,
    username,
    reason="",
    reservation_id=None,
    sap_ov="",
    attention_id=None,
    origin_location="",
    destination_location="",
):
    before = _snapshot(lot_before)
    after = _snapshot(lot_after)
    connection.execute(
        """INSERT INTO lot_movements
           (inventory_lot_id, lot_reservation_id, movement_type, item_code, lot_code,
            quantity, before_received, after_received, before_reserved, after_reserved,
            before_dispatched, after_dispatched, before_blocked, after_blocked,
            before_available, after_available, origin_location, destination_location,
            sap_ov, attention_id, username, reason, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            lot_after["id"], reservation_id, movement_type, lot_after["item_code"],
            lot_after["lot_code"], quantity, before["received"], after["received"],
            before["reserved"], after["reserved"], before["dispatched"],
            after["dispatched"], before["blocked"], after["blocked"],
            before["available"], after["available"], origin_location,
            destination_location, sap_ov, attention_id, username, reason, trace_now(),
        ),
    )


def generate_lots_for_shipment(connection, shipment_id, username):
    if not advanced_lots_enabled():
        return []
    shipment = connection.execute(
        "SELECT * FROM reception_shipments WHERE id = ?", (shipment_id,)
    ).fetchone()
    if not shipment:
        raise ValueError("Recepción no encontrada")
    created = []
    lines = connection.execute(
        "SELECT * FROM reception_lines WHERE shipment_id = ? ORDER BY id", (shipment_id,)
    ).fetchall()
    for line in lines:
        if _number(line["received_qty"]) <= 0:
            continue
        existing = connection.execute(
            "SELECT id FROM inventory_lots WHERE reception_line_id = ? ORDER BY id",
            (line["id"],),
        ).fetchall()
        if existing:
            continue
        bl = normalize_lot_segment(shipment["bl_awb"], "SINBL")
        reference = normalize_lot_segment(line["oc_number"] or line["ip_reference"], "SINREF")
        np_code = normalize_lot_segment(line["np_code"], "SINNP")
        prefix = f"BL-{bl}-OC-{reference}-NP-{np_code}-"
        correlation = connection.execute(
            "SELECT COUNT(*) + 1 FROM inventory_lots WHERE lot_code LIKE ?", (prefix + "%",)
        ).fetchone()[0]
        lot_code = f"{prefix}{correlation:03d}"
        timestamp = trace_now()
        received_at = (
            shipment["completed_arrival_at"]
            or shipment["first_arrival_at"]
            or shipment["source_reception_date"]
            or timestamp
        )
        cursor = connection.execute(
            """INSERT INTO inventory_lots
               (lot_code, reception_shipment_id, reception_line_id, bl_awb,
                oc_number, ip_reference, em_number, item_key, item_code,
                description, received_qty, received_at, location, status,
                created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', 'DISPONIBLE', ?, ?, ?)""",
            (
                lot_code, shipment_id, line["id"], shipment["bl_awb"],
                line["oc_number"], line["ip_reference"], shipment["em_number"],
                normalize_identifier(line["np_code"]), _text(line["np_code"]),
                _text(line["description"]), _number(line["received_qty"]), received_at,
                username, timestamp, timestamp,
            ),
        )
        lot_after = connection.execute(
            "SELECT * FROM inventory_lots WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        before = dict(lot_after)
        before["received_qty"] = 0
        _write_movement(
            connection, before, lot_after, "RECEPCION", lot_after["received_qty"],
            username, f"Lote generado al finalizar revisión de sistema de {shipment['bl_awb']}",
        )
        connection.execute(
            "UPDATE reception_lines SET lot_status = 'CREADO' WHERE id = ?", (line["id"],)
        )
        created.append(lot_payload(connection, cursor.lastrowid))
    return created


def sync_shipment_lot_references(connection, shipment_id):
    schema_ready = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'inventory_lots'"
    ).fetchone()
    if not schema_ready:
        return
    shipment = connection.execute(
        "SELECT em_number FROM reception_shipments WHERE id = ?", (shipment_id,)
    ).fetchone()
    if shipment:
        connection.execute(
            "UPDATE inventory_lots SET em_number = ?, updated_at = ? WHERE reception_shipment_id = ?",
            (shipment["em_number"], trace_now(), shipment_id),
        )


def update_lot_location(connection, lot_id, location, username, reason=""):
    location = _text(location)
    if not location:
        raise ValueError("Indica la ubicación física del lote")
    lot_before = connection.execute("SELECT * FROM inventory_lots WHERE id = ?", (lot_id,)).fetchone()
    if not lot_before:
        raise ValueError("Lote no encontrado")
    old_location = _text(lot_before["location"])
    if old_location == location:
        return lot_payload(connection, lot_id)
    connection.execute(
        "UPDATE inventory_lots SET location = ?, updated_at = ? WHERE id = ?",
        (location, trace_now(), lot_id),
    )
    lot_after = connection.execute("SELECT * FROM inventory_lots WHERE id = ?", (lot_id,)).fetchone()
    movement_type = "TRANSFERENCIA" if old_location else "UBICACION"
    _write_movement(
        connection, lot_before, lot_after, movement_type, 0, username,
        reason or ("Lote transferido entre ubicaciones" if old_location else "Ubicación física registrada"),
        origin_location=old_location,
        destination_location=location,
    )
    return lot_payload(connection, lot_id)


def _related_lot_ids(connection, sap_ov, item_code, pool_type):
    item_key = normalize_identifier(item_code)
    if pool_type != "AEREO":
        return []
    rows = connection.execute(
        """SELECT DISTINCT lot.id
           FROM inventory_lots lot
           JOIN order_importation_refs ref
             ON lower(COALESCE(ref.bl_awb, '')) = lower(COALESCE(lot.bl_awb, ''))
           WHERE ref.sap_ov = ? AND lot.item_key = ?
             AND (COALESCE(ref.item_code, '') = '' OR
                  upper(replace(replace(replace(ref.item_code, '-', ''), '/', ''), ' ', '')) = ?)
             AND (COALESCE(ref.oc_number, '') = '' OR COALESCE(lot.oc_number, '') = '' OR
                  lower(ref.oc_number) = lower(lot.oc_number))""",
        (sap_ov, item_key, item_key),
    ).fetchall()
    return [row["id"] for row in rows]


def _candidate_lots(connection, sap_ov, item_code, pool_type):
    item_key = normalize_identifier(item_code)
    related_ids = _related_lot_ids(connection, sap_ov, item_code, pool_type)
    if pool_type == "AEREO":
        if not related_ids:
            return []
        placeholders = ",".join("?" for _ in related_ids)
        query = f"""SELECT * FROM inventory_lots
                    WHERE id IN ({placeholders}) AND item_key = ?
                    ORDER BY CASE WHEN COALESCE(oc_number, '') <> '' THEN 0 ELSE 1 END,
                             received_at, id"""
        return connection.execute(query, (*related_ids, item_key)).fetchall()
    return connection.execute(
        """SELECT * FROM inventory_lots
           WHERE item_key = ? AND status NOT IN ('ANULADO', 'SIN_LOTE_HISTORICO')
           ORDER BY received_at, id""",
        (item_key,),
    ).fetchall()


def reserve_lots_for_allocation(connection, allocation, attention, line, quantity, username):
    """Reserva FIFO por lote. Devuelve True cuando la línea exige escaneo."""
    if not advanced_lots_enabled():
        return False
    quantity = max(0.0, _number(quantity))
    connection.execute(
        """UPDATE lot_reservations
           SET status = 'LIBERADA', reserved_qty = 0, updated_at = ?
           WHERE attention_line_id = ? AND status IN ('PENDIENTE', 'SIN_STOCK')""",
        (trace_now(), line["id"]),
    )
    candidates = _candidate_lots(
        connection, attention["sap_ov"], line["item_code"], allocation["pool_type"]
    )
    related_air = allocation["pool_type"] == "AEREO" and bool(
        connection.execute(
            """SELECT 1 FROM reception_lines rl
               JOIN reception_shipments rs ON rs.id = rl.shipment_id
               WHERE upper(replace(replace(replace(COALESCE(rl.np_code, ''), '-', ''), '/', ''), ' ', '')) = ?
                 AND (upper(replace(replace(replace(COALESCE(rl.ov_number, ''), '-', ''), '/', ''), ' ', '')) = ?
                      OR lower(COALESCE(rs.bl_awb, '')) IN (
                          SELECT lower(COALESCE(bl_awb, '')) FROM order_importation_refs WHERE sap_ov = ?
                      )) LIMIT 1""",
            (
                normalize_identifier(line["item_code"]),
                normalize_identifier(attention["sap_ov"]),
                attention["sap_ov"],
            ),
        ).fetchone()
    )
    tracked = bool(candidates) or related_air
    if not tracked:
        return False

    remaining = quantity
    timestamp = trace_now()
    for lot in candidates:
        available = lot_available(lot)
        take = min(remaining, available)
        if take <= EPSILON:
            continue
        before = lot
        connection.execute(
            "UPDATE inventory_lots SET reserved_qty = reserved_qty + ?, updated_at = ? WHERE id = ?",
            (take, timestamp, lot["id"]),
        )
        cursor = connection.execute(
            """INSERT INTO lot_reservations
               (stock_allocation_id, attention_id, attention_line_id, inventory_lot_id,
                requested_qty, reserved_qty, status, match_method, expected_lot_code,
                created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'RESERVADA', ?, ?, ?, ?, ?)""",
            (
                allocation["id"], attention["id"], line["id"], lot["id"],
                take, take, "OC_NP" if allocation["pool_type"] == "AEREO" else "FIFO",
                lot["lot_code"], username, timestamp, timestamp,
            ),
        )
        after = connection.execute("SELECT * FROM inventory_lots WHERE id = ?", (lot["id"],)).fetchone()
        _write_movement(
            connection, before, after, "RESERVA", take, username,
            "Reserva automática para picking", cursor.lastrowid,
            attention["sap_ov"], attention["id"],
        )
        remaining -= take
        if remaining <= EPSILON:
            break
    if remaining > EPSILON:
        connection.execute(
            """INSERT INTO lot_reservations
               (stock_allocation_id, attention_id, attention_line_id, inventory_lot_id,
                requested_qty, reserved_qty, status, match_method, created_by,
                created_at, updated_at)
               VALUES (?, ?, ?, NULL, ?, 0, ?, 'PENDIENTE_ASIGNACION', ?, ?, ?)""",
            (
                allocation["id"], attention["id"], line["id"], remaining,
                "SIN_STOCK" if candidates else "PENDIENTE", username, timestamp, timestamp,
            ),
        )
    return True


def line_lot_tracking(connection, attention_line_id):
    reservations = [
        _as_dict(row)
        for row in connection.execute(
            """SELECT lr.*, lot.lot_code, lot.location, lot.bl_awb, lot.oc_number,
                      lot.ip_reference, lot.em_number, lot.item_code, lot.description
               FROM lot_reservations lr
               LEFT JOIN inventory_lots lot ON lot.id = lr.inventory_lot_id
               WHERE lr.attention_line_id = ? AND lr.status <> 'LIBERADA'
               ORDER BY lr.id""",
            (attention_line_id,),
        ).fetchall()
    ]
    scanned = sum(
        _number(item["reserved_qty"])
        for item in reservations
        if item["scanned_at"] and item["status"] in {"RESERVADA", "PARCIAL", "CONSUMIDA"}
    )
    return {
        "tracked": bool(reservations),
        "scanned_qty": scanned,
        "pending_qty": sum(
            _number(item["requested_qty"])
            for item in reservations
            if item["status"] in {"PENDIENTE", "SIN_STOCK"}
        ),
        "reservations": reservations,
    }


def available_lots_for_line(connection, attention_line_id):
    line = connection.execute(
        """SELECT al.*, a.sap_ov, COALESCE(sa.pool_type, 'STOCK') AS pool_type
           FROM attention_lines al
           JOIN attentions a ON a.id = al.attention_id
           LEFT JOIN stock_allocations sa ON sa.attention_line_id = al.id
           WHERE al.id = ?""",
        (attention_line_id,),
    ).fetchone()
    if not line:
        return []
    return [
        {**_as_dict(lot), "available_qty": lot_available(lot)}
        for lot in _candidate_lots(connection, line["sap_ov"], line["item_code"], line["pool_type"])
        if lot_available(lot) > EPSILON
    ]


def assign_lot_manually(connection, attention_line_id, lot_id, quantity, username, reason):
    reason = _text(reason)
    if not reason:
        raise ValueError("La asignación manual requiere una observación")
    quantity = _number(quantity)
    if quantity <= 0:
        raise ValueError("La cantidad a reservar debe ser mayor que cero")
    line = connection.execute(
        """SELECT al.*, a.sap_ov, sa.id AS allocation_id
           FROM attention_lines al
           JOIN attentions a ON a.id = al.attention_id
           LEFT JOIN stock_allocations sa ON sa.attention_line_id = al.id
           WHERE al.id = ?""",
        (attention_line_id,),
    ).fetchone()
    lot_before = connection.execute("SELECT * FROM inventory_lots WHERE id = ?", (lot_id,)).fetchone()
    if not line or not lot_before:
        raise ValueError("Línea o lote no encontrado")
    if normalize_identifier(line["item_code"]) != lot_before["item_key"]:
        raise ValueError("El lote seleccionado pertenece a otro NP")
    if quantity - lot_available(lot_before) > EPSILON:
        raise ValueError(f"El lote solo tiene {lot_available(lot_before):g} disponibles")
    # La excepción administrativa puede cambiar el lote, pero nunca ampliar la
    # reserva global/planiﬁcada de la línea ni provocar doble asignación.
    line_limit = _number(line["planned_qty"])
    if line["allocation_id"]:
        allocation = connection.execute(
            "SELECT reserved_qty, consumed_qty FROM stock_allocations WHERE id = ?",
            (line["allocation_id"],),
        ).fetchone()
        # Si existe reserva global, ese valor es el techo real. Usar la cantidad
        # planificada permitiría adjudicar lotes que el stock global no reservó.
        line_limit = max(_number(allocation["reserved_qty"]), _number(allocation["consumed_qty"]))
    already_assigned = connection.execute(
        """SELECT COALESCE(SUM(reserved_qty + consumed_qty), 0)
           FROM lot_reservations
           WHERE attention_line_id = ? AND status IN ('RESERVADA', 'PARCIAL', 'CONSUMIDA')""",
        (attention_line_id,),
    ).fetchone()[0]
    remaining_limit = max(0.0, line_limit - _number(already_assigned))
    if quantity - remaining_limit > EPSILON:
        raise ValueError(
            f"Solo faltan {remaining_limit:g} unidades por asignar en esta línea"
        )
    timestamp = trace_now()
    connection.execute(
        "UPDATE inventory_lots SET reserved_qty = reserved_qty + ?, updated_at = ? WHERE id = ?",
        (quantity, timestamp, lot_id),
    )
    cursor = connection.execute(
        """INSERT INTO lot_reservations
           (stock_allocation_id, attention_id, attention_line_id, inventory_lot_id,
            requested_qty, reserved_qty, status, match_method, expected_lot_code,
            exception_reason, created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 'RESERVADA', 'MANUAL_ADMIN', ?, ?, ?, ?, ?)""",
        (
            line["allocation_id"], line["attention_id"], attention_line_id, lot_id,
            quantity, quantity, lot_before["lot_code"], reason, username, timestamp, timestamp,
        ),
    )
    # Reduce primero los pendientes, sin borrar su evidencia.
    remaining = quantity
    for pending in connection.execute(
        """SELECT * FROM lot_reservations
           WHERE attention_line_id = ? AND status IN ('PENDIENTE', 'SIN_STOCK')
           ORDER BY id""",
        (attention_line_id,),
    ).fetchall():
        pending_qty = _number(pending["requested_qty"])
        applied = min(remaining, pending_qty)
        new_pending = pending_qty - applied
        connection.execute(
            "UPDATE lot_reservations SET requested_qty = ?, status = ?, updated_at = ? WHERE id = ?",
            (new_pending, "LIBERADA" if new_pending <= EPSILON else pending["status"], timestamp, pending["id"]),
        )
        remaining -= applied
        if remaining <= EPSILON:
            break
    lot_after = connection.execute("SELECT * FROM inventory_lots WHERE id = ?", (lot_id,)).fetchone()
    _write_movement(
        connection, lot_before, lot_after, "RESERVA", quantity, username,
        reason, cursor.lastrowid, line["sap_ov"], line["attention_id"],
    )
    return line_lot_tracking(connection, attention_line_id)


def validate_lot_scan(connection, attention_line_id, scanned_code, username, role, reason=""):
    # El código completo puede superar la longitud máxima de cada segmento
    # individual (BL/OC/NP); truncarlo convertiría un escaneo correcto en error.
    scanned_code = normalize_lot_segment(scanned_code, "", 120)
    if not scanned_code:
        raise ValueError("Escanea o escribe el código del lote")
    line = connection.execute(
        """SELECT al.*, a.sap_ov, a.app_status, a.current_picker
           FROM attention_lines al JOIN attentions a ON a.id = al.attention_id
           WHERE al.id = ?""",
        (attention_line_id,),
    ).fetchone()
    if not line:
        raise ValueError("Línea de picking no encontrada")
    if role != "ADMINISTRADOR":
        if role not in {"PICKER", "PICKER_GUIADOR"} or _text(line["current_picker"]).casefold() != _text(username).casefold():
            raise PermissionError("Solo el picker asignado puede validar el lote")
        if line["app_status"] != "EN PICKING":
            raise PermissionError("El lote se valida durante EN PICKING")
    expected = connection.execute(
        """SELECT lr.*, lot.lot_code
           FROM lot_reservations lr JOIN inventory_lots lot ON lot.id = lr.inventory_lot_id
           WHERE lr.attention_line_id = ? AND lr.status IN ('RESERVADA', 'PARCIAL')
             AND upper(lot.lot_code) = upper(?)""",
        (attention_line_id, scanned_code),
    ).fetchone()
    if not expected:
        expected_codes = [
            row["lot_code"]
            for row in connection.execute(
                """SELECT lot.lot_code FROM lot_reservations lr
                   JOIN inventory_lots lot ON lot.id = lr.inventory_lot_id
                   WHERE lr.attention_line_id = ? AND lr.status IN ('RESERVADA', 'PARCIAL')""",
                (attention_line_id,),
            ).fetchall()
        ]
        if role != "ADMINISTRADOR":
            raise ValueError(
                "Lote incorrecto. Esperado: " + (", ".join(expected_codes) or "asignación administrativa")
            )
        reason = _text(reason)
        if not reason:
            raise ValueError("La excepción administrativa requiere un motivo")
        actual_lot = connection.execute(
            "SELECT * FROM inventory_lots WHERE upper(lot_code) = upper(?)", (scanned_code,)
        ).fetchone()
        if not actual_lot or actual_lot["item_key"] != normalize_identifier(line["item_code"]):
            raise ValueError("El lote excepcional no existe o pertenece a otro NP")
        raise ValueError("Primero asigna administrativamente el lote excepcional a esta OV")
    timestamp = trace_now()
    connection.execute(
        """UPDATE lot_reservations
           SET scanned_at = ?, scanned_by = ?, actual_lot_code = ?, updated_at = ?
           WHERE id = ?""",
        (timestamp, username, expected["lot_code"], timestamp, expected["id"]),
    )
    tracking = line_lot_tracking(connection, attention_line_id)
    # El escaneo confirma físicamente la porción reservada y propone la
    # cantidad. El picker aún puede reducirla si encontró una diferencia.
    connection.execute(
        "UPDATE attention_lines SET picked_qty = ? WHERE id = ?",
        (tracking["scanned_qty"], attention_line_id),
    )
    return line_lot_tracking(connection, attention_line_id)


def validate_picked_against_scans(connection, attention_line_id, quantity):
    if not advanced_lots_enabled():
        return
    tracking = line_lot_tracking(connection, attention_line_id)
    if tracking["tracked"] and quantity - tracking["scanned_qty"] > EPSILON:
        expected = [
            item["lot_code"]
            for item in tracking["reservations"]
            if item.get("lot_code") and not item.get("scanned_at")
        ]
        raise ValueError(
            f"Primero escanea el lote autorizado: {', '.join(expected) or 'pendiente de asignación'}"
        )


def consume_lots_for_line(connection, attention_line_id, picked_qty, username, sap_ov, attention_id):
    remaining = max(0.0, _number(picked_qty))
    reservations = connection.execute(
        """SELECT lr.*, lot.lot_code FROM lot_reservations lr
           JOIN inventory_lots lot ON lot.id = lr.inventory_lot_id
           WHERE lr.attention_line_id = ? AND lr.status IN ('RESERVADA', 'PARCIAL')
           ORDER BY lr.id""",
        (attention_line_id,),
    ).fetchall()
    if reservations:
        validate_picked_against_scans(connection, attention_line_id, remaining)
    timestamp = trace_now()
    for reservation in reservations:
        reserved = _number(reservation["reserved_qty"])
        consume = min(remaining, reserved)
        release = reserved - consume
        lot_before = connection.execute(
            "SELECT * FROM inventory_lots WHERE id = ?", (reservation["inventory_lot_id"],)
        ).fetchone()
        connection.execute(
            """UPDATE inventory_lots
               SET reserved_qty = reserved_qty - ?, dispatched_qty = dispatched_qty + ?,
                   updated_at = ? WHERE id = ?""",
            (reserved, consume, timestamp, reservation["inventory_lot_id"]),
        )
        status = "CONSUMIDA" if consume > EPSILON else "LIBERADA"
        connection.execute(
            """UPDATE lot_reservations
               SET reserved_qty = 0, consumed_qty = ?, status = ?, updated_at = ?
               WHERE id = ?""",
            (consume, status, timestamp, reservation["id"]),
        )
        lot_after = connection.execute(
            "SELECT * FROM inventory_lots WHERE id = ?", (reservation["inventory_lot_id"],)
        ).fetchone()
        if consume > EPSILON:
            _write_movement(
                connection, lot_before, lot_after, "PICKING", consume, username,
                "Picking finalizado", reservation["id"], sap_ov, attention_id,
            )
        if release > EPSILON:
            release_before = dict(lot_after)
            release_before["reserved_qty"] = _number(lot_after["reserved_qty"]) + release
            _write_movement(
                connection, release_before, lot_after, "LIBERACION", release, username,
                "Saldo reservado no recogido", reservation["id"], sap_ov, attention_id,
            )
        remaining -= consume
    if reservations and remaining > EPSILON:
        raise ValueError("La cantidad recogida supera los lotes escaneados")


def release_lot_reservations(connection, attention_id, username, reason, movement_type="LIBERACION"):
    timestamp = trace_now()
    for reservation in connection.execute(
        """SELECT * FROM lot_reservations
           WHERE attention_id = ? AND status IN ('RESERVADA', 'PARCIAL')""",
        (attention_id,),
    ).fetchall():
        lot_before = connection.execute(
            "SELECT * FROM inventory_lots WHERE id = ?", (reservation["inventory_lot_id"],)
        ).fetchone()
        reserved = _number(reservation["reserved_qty"])
        connection.execute(
            "UPDATE inventory_lots SET reserved_qty = MAX(0, reserved_qty - ?), updated_at = ? WHERE id = ?",
            (reserved, timestamp, reservation["inventory_lot_id"]),
        )
        connection.execute(
            "UPDATE lot_reservations SET reserved_qty = 0, status = 'LIBERADA', updated_at = ? WHERE id = ?",
            (timestamp, reservation["id"]),
        )
        lot_after = connection.execute(
            "SELECT * FROM inventory_lots WHERE id = ?", (reservation["inventory_lot_id"],)
        ).fetchone()
        _write_movement(
            connection, lot_before, lot_after, movement_type, reserved, username,
            reason, reservation["id"], "", attention_id,
        )
    connection.execute(
        """UPDATE lot_reservations SET status = 'LIBERADA', requested_qty = 0, updated_at = ?
           WHERE attention_id = ? AND status IN ('PENDIENTE', 'SIN_STOCK')""",
        (timestamp, attention_id),
    )


def reverse_lot_consumption(connection, attention_id, username, reason):
    timestamp = trace_now()
    for reservation in connection.execute(
        "SELECT * FROM lot_reservations WHERE attention_id = ? AND status = 'CONSUMIDA'",
        (attention_id,),
    ).fetchall():
        consumed = _number(reservation["consumed_qty"])
        lot_before = connection.execute(
            "SELECT * FROM inventory_lots WHERE id = ?", (reservation["inventory_lot_id"],)
        ).fetchone()
        connection.execute(
            """UPDATE inventory_lots
               SET dispatched_qty = MAX(0, dispatched_qty - ?), reserved_qty = reserved_qty + ?,
                   updated_at = ? WHERE id = ?""",
            (consumed, consumed, timestamp, reservation["inventory_lot_id"]),
        )
        connection.execute(
            """UPDATE lot_reservations
               SET consumed_qty = 0, reserved_qty = ?, status = 'RESERVADA', updated_at = ?
               WHERE id = ?""",
            (consumed, timestamp, reservation["id"]),
        )
        lot_after = connection.execute(
            "SELECT * FROM inventory_lots WHERE id = ?", (reservation["inventory_lot_id"],)
        ).fetchone()
        _write_movement(
            connection, lot_before, lot_after, "REVERSA_PICKING", consumed, username,
            reason, reservation["id"], "", attention_id,
        )


def record_lot_delivery(connection, attention_id, username):
    timestamp = trace_now()
    for reservation in connection.execute(
        "SELECT * FROM lot_reservations WHERE attention_id = ? AND status = 'CONSUMIDA'",
        (attention_id,),
    ).fetchall():
        duplicate = connection.execute(
            """SELECT 1 FROM lot_movements
               WHERE lot_reservation_id = ? AND movement_type = 'ENTREGA' LIMIT 1""",
            (reservation["id"],),
        ).fetchone()
        if duplicate:
            continue
        lot = connection.execute(
            "SELECT * FROM inventory_lots WHERE id = ?", (reservation["inventory_lot_id"],)
        ).fetchone()
        _write_movement(
            connection, lot, lot, "ENTREGA", reservation["consumed_qty"], username,
            "Entrega confirmada", reservation["id"], "", attention_id,
        )
        connection.execute(
            "UPDATE lot_reservations SET updated_at = ? WHERE id = ?", (timestamp, reservation["id"])
        )


def return_lot_after_picking(connection, reservation_id, quantity, username, reason):
    reason = _text(reason)
    if not reason:
        raise ValueError("La devolución requiere un motivo")
    quantity = _number(quantity)
    reservation = connection.execute(
        """SELECT lr.*, al.delivered_qty, a.sap_ov
           FROM lot_reservations lr
           JOIN attention_lines al ON al.id = lr.attention_line_id
           JOIN attentions a ON a.id = lr.attention_id
           WHERE lr.id = ?""",
        (reservation_id,),
    ).fetchone()
    if not reservation or reservation["status"] != "CONSUMIDA":
        raise ValueError("La reserva no tiene picking consumido")
    if _number(reservation["delivered_qty"]) > EPSILON:
        raise PermissionError("No se puede devolver un lote después de registrar la entrega")
    if quantity <= 0 or quantity - _number(reservation["consumed_qty"]) > EPSILON:
        raise ValueError("Cantidad de devolución no válida")
    timestamp = trace_now()
    lot_before = connection.execute(
        "SELECT * FROM inventory_lots WHERE id = ?", (reservation["inventory_lot_id"],)
    ).fetchone()
    new_consumed = _number(reservation["consumed_qty"]) - quantity
    connection.execute(
        "UPDATE inventory_lots SET dispatched_qty = MAX(0, dispatched_qty - ?), updated_at = ? WHERE id = ?",
        (quantity, timestamp, reservation["inventory_lot_id"]),
    )
    connection.execute(
        "UPDATE lot_reservations SET consumed_qty = ?, status = ?, updated_at = ? WHERE id = ?",
        (new_consumed, "CONSUMIDA" if new_consumed > EPSILON else "LIBERADA", timestamp, reservation_id),
    )
    connection.execute(
        "UPDATE attention_lines SET picked_qty = MAX(0, picked_qty - ?) WHERE id = ?",
        (quantity, reservation["attention_line_id"]),
    )
    if reservation["stock_allocation_id"]:
        connection.execute(
            """UPDATE stock_allocations
               SET consumed_qty = MAX(0, consumed_qty - ?),
                   status = CASE WHEN consumed_qty - ? <= 0 THEN 'LIBERADA' ELSE 'CONSUMIDA' END,
                   updated_at = ? WHERE id = ?""",
            (quantity, quantity, timestamp, reservation["stock_allocation_id"]),
        )
    lot_after = connection.execute(
        "SELECT * FROM inventory_lots WHERE id = ?", (reservation["inventory_lot_id"],)
    ).fetchone()
    _write_movement(
        connection, lot_before, lot_after, "DEVOLUCION", quantity, username,
        reason, reservation_id, reservation["sap_ov"], reservation["attention_id"],
    )
    return lot_payload(connection, reservation["inventory_lot_id"])


def register_label_print(connection, lot_id, copies, username, reprint=False):
    copies = int(copies or 1)
    if copies < 1 or copies > 100:
        raise ValueError("La cantidad de copias debe estar entre 1 y 100")
    lot = lot_payload(connection, lot_id)
    if not lot:
        raise ValueError("Lote no encontrado")
    prior = connection.execute(
        "SELECT COUNT(*) FROM label_prints WHERE inventory_lot_id = ?", (lot_id,)
    ).fetchone()[0]
    print_type = "REIMPRESION" if reprint or prior else "IMPRESION"
    connection.execute(
        "INSERT INTO label_prints (inventory_lot_id, copies, print_type, username, printed_at) VALUES (?, ?, ?, ?, ?)",
        (lot_id, copies, print_type, username, trace_now()),
    )
    return {"lot": lot_payload(connection, lot_id), "html": label_html(lot, copies), "print_type": print_type}


CODE39 = {
    "0": "nnnwwnwnn", "1": "wnnwnnnnw", "2": "nnwwnnnnw", "3": "wnwwnnnnn",
    "4": "nnnwwnnnw", "5": "wnnwwnnnn", "6": "nnwwwnnnn", "7": "nnnwnnwnw",
    "8": "wnnwnnwnn", "9": "nnwwnnwnn", "A": "wnnnnwnnw", "B": "nnwnnwnnw",
    "C": "wnwnnwnnn", "D": "nnnnwwnnw", "E": "wnnnwwnnn", "F": "nnwnwwnnn",
    "G": "nnnnnwwnw", "H": "wnnnnwwnn", "I": "nnwnnwwnn", "J": "nnnnwwwnn",
    "K": "wnnnnnnww", "L": "nnwnnnnww", "M": "wnwnnnnwn", "N": "nnnnwnnww",
    "O": "wnnnwnnwn", "P": "nnwnwnnwn", "Q": "nnnnnnwww", "R": "wnnnnnwwn",
    "S": "nnwnnnwwn", "T": "nnnnwnwwn", "U": "wwnnnnnnw", "V": "nwwnnnnnw",
    "W": "wwwnnnnnn", "X": "nwnnwnnnw", "Y": "wwnnwnnnn", "Z": "nwwnwnnnn",
    "-": "nwnnnnwnw", ".": "wwnnnnwnn", " ": "nwwnnnwnn", "$": "nwnwnwnnn",
    "/": "nwnwnnnwn", "+": "nwnnnwnwn", "%": "nnnwnwnwn", "*": "nwnnwnwnn",
}


def code39_svg(value, height=62):
    value = normalize_lot_segment(value, "SIN-CODIGO", 120)
    encoded = "*" + value + "*"
    narrow, wide, gap = 2, 5, 2
    x = 10
    bars = []
    for character in encoded:
        pattern = CODE39.get(character, CODE39["-"])
        for index, width_kind in enumerate(pattern):
            width = wide if width_kind == "w" else narrow
            if index % 2 == 0:
                bars.append(f'<rect x="{x}" y="6" width="{width}" height="{height}" fill="#111"/>')
            x += width
        x += gap
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {x + 10} {height + 12}" '
        f'role="img" aria-label="Código de barras {html.escape(value)}">'
        + "".join(bars)
        + "</svg>"
    )


def label_html(lot, copies=1):
    reserved_ovs = ", ".join(
        dict.fromkeys(
            _text(reservation.get("sap_ov"))
            for reservation in lot.get("reservations", [])
            if _text(reservation.get("sap_ov"))
        )
    ) or "SIN RESERVA"
    label = f"""<section class="label">
      <header><strong>TRITON</strong><span>TRAZABILIDAD WMS</span></header>
      <h1>{html.escape(_text(lot['item_code']))}</h1>
      <p class="description">{html.escape(_text(lot['description'])[:90])}</p>
      <div class="barcode">{code39_svg(lot['lot_code'])}</div>
      <div class="lot-code">{html.escape(lot['lot_code'])}</div>
      <dl>
        <div><dt>BL/AWB</dt><dd>{html.escape(_text(lot['bl_awb']) or '—')}</dd></div>
        <div><dt>OC/IP</dt><dd>{html.escape(_text(lot['oc_number'] or lot['ip_reference']) or '—')}</dd></div>
        <div><dt>CANTIDAD</dt><dd>{_number(lot['received_qty']):g}</dd></div>
        <div><dt>UBICACIÓN</dt><dd>{html.escape(_text(lot['location']) or 'POR DEFINIR')}</dd></div>
        <div><dt>OV RESERVADA</dt><dd>{html.escape(reserved_ovs)}</dd></div>
      </dl>
    </section>"""
    pages = "".join(label for _ in range(int(copies)))
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Etiqueta {html.escape(lot['lot_code'])}</title>
    <style>@page{{size:100mm 70mm;margin:3mm}}*{{box-sizing:border-box}}body{{margin:0;font-family:Arial,sans-serif;color:#20282d}}.label{{width:94mm;height:64mm;border:1px solid #222;padding:4mm;break-after:page;overflow:hidden}}header{{display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #f58200;padding-bottom:2mm}}header strong{{font-size:20pt;letter-spacing:2px}}header span,dt{{font-size:7pt;color:#56616b;font-weight:bold}}h1{{margin:2mm 0 0;font-size:18pt}}.description{{margin:1mm 0;font-size:8pt;height:9mm;overflow:hidden}}.barcode svg{{display:block;width:100%;height:17mm}}.lot-code{{font:7pt Consolas,monospace;text-align:center}}dl{{display:grid;grid-template-columns:1fr 1fr;gap:1mm 4mm;margin:2mm 0 0}}dl div{{display:flex;gap:2mm}}dd{{margin:0;font-size:8pt;font-weight:bold}}@media screen{{body{{background:#eef1f3;padding:12px}}.label{{background:#fff;margin:0 auto 12px}}}}</style></head><body>{pages}<script>window.addEventListener('load',()=>window.print())</script></body></html>"""


def traceability_search(connection, search):
    token = f"%{_text(search).lower()}%"
    if token == "%%":
        return []
    rows = connection.execute(
        """SELECT DISTINCT lot.id
           FROM inventory_lots lot
           LEFT JOIN lot_reservations lr ON lr.inventory_lot_id = lot.id
           LEFT JOIN attentions a ON a.id = lr.attention_id
           WHERE lower(COALESCE(lot.item_code, '')) LIKE ?
              OR lower(COALESCE(lot.lot_code, '')) LIKE ?
              OR lower(COALESCE(lot.bl_awb, '')) LIKE ?
              OR lower(COALESCE(lot.oc_number, '')) LIKE ?
              OR lower(COALESCE(lot.ip_reference, '')) LIKE ?
              OR lower(COALESCE(lot.em_number, '')) LIKE ?
              OR lower(COALESCE(a.sap_ov, '')) LIKE ?
              OR CAST(COALESCE(a.id, '') AS TEXT) LIKE ?
           ORDER BY lot.received_at DESC, lot.id DESC LIMIT 100""",
        (token,) * 8,
    ).fetchall()
    result = []
    for row in rows:
        lot = lot_payload(connection, row["id"])
        lot["movements"] = [
            _as_dict(item)
            for item in connection.execute(
                "SELECT * FROM lot_movements WHERE inventory_lot_id = ? ORDER BY id",
                (row["id"],),
            ).fetchall()
        ]
        result.append(lot)
    return result
