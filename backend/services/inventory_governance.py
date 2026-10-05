"""Shared, staged inventory catalog and NPS-governance workflows."""

import re
import sqlite3
import unicodedata
from difflib import SequenceMatcher

from backend.services.daily_operations import global_stock_summary, item_key, local_now


INVENTORY_ROLES = {
    "ADMINISTRADOR", "PICKER", "GUIADOR", "PICKER_GUIADOR",
    "ASISTENTE_RECEPCION", "AUXILIAR_RECEPCION",
}


def init_inventory_governance_schema(connection):
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS inventory_governance_items (
            item_key TEXT PRIMARY KEY,
            item_code TEXT NOT NULL UNIQUE,
            part_number TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inventory_material_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_code TEXT NOT NULL,
            item_key TEXT NOT NULL,
            part_number TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL,
            justification TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDIENTE',
            requested_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            decided_by TEXT,
            decided_at TEXT,
            decision_note TEXT
        );
        CREATE TABLE IF NOT EXISTS inventory_governance_barcodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_key TEXT NOT NULL,
            item_code TEXT NOT NULL,
            barcode TEXT NOT NULL,
            barcode_key TEXT NOT NULL UNIQUE,
            symbology TEXT NOT NULL DEFAULT 'CODE39',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(item_key, barcode_key)
        );
        CREATE INDEX IF NOT EXISTS idx_inventory_requests_status
            ON inventory_material_requests(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_inventory_requests_owner
            ON inventory_material_requests(requested_by, created_at);
        CREATE INDEX IF NOT EXISTS idx_inventory_barcodes_item
            ON inventory_governance_barcodes(item_key);
    """)


def _require_role(role):
    if str(role or "").upper() not in INVENTORY_ROLES:
        raise PermissionError("Tu usuario no tiene acceso al módulo Inventario")


def _clean(value, label, limit, required=False):
    result = " ".join(str(value or "").strip().split())
    if required and not result:
        raise ValueError(f"Completa {label}")
    if len(result) > limit:
        raise ValueError(f"{label} supera el máximo de {limit} caracteres")
    return result


def _normalize_text(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(character for character in value if not unicodedata.combining(character))
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _known_materials(connection):
    records = {}
    queries = (
        ("SELECT item_code, description FROM order_lines WHERE trim(COALESCE(item_code,''))<>''",),
        ("SELECT item_code, description FROM attention_lines WHERE trim(COALESCE(item_code,''))<>''",),
        ("SELECT item_code, '' AS description FROM inventory_stock WHERE trim(COALESCE(item_code,''))<>''",),
        ("SELECT item_code, description FROM inventory_governance_items",),
    )
    for (sql,) in queries:
        try:
            rows = connection.execute(sql).fetchall()
        except sqlite3.OperationalError:
            continue
        for row in rows:
            code = str(row["item_code"] or "").strip()
            key = item_key(code)
            if not key:
                continue
            record = records.setdefault(key, {"item_code": code, "descriptions": set()})
            if len(code) > len(record["item_code"]):
                record["item_code"] = code
            description = " ".join(str(row["description"] or "").split())
            if description:
                record["descriptions"].add(description)
    return records


def inventory_catalog_search(connection, search="", username="", role=""):
    _require_role(role)
    token = _clean(search, "la búsqueda", 100)
    if len(token) < 2:
        return {"items": [], "has_more": False, "hint": "Escribe al menos 2 caracteres o escanea un NP."}
    like = f"%{token}%"
    stock_rows = connection.execute(
        """SELECT s.item_key, s.item_code, s.warehouse, s.snapshot_qty,
                  s.snapshot_day, s.snapshot_at, s.default_location,
                  COALESCE(i.description,
                    (SELECT ol.description FROM order_lines ol
                      WHERE upper(trim(ol.item_code))=upper(trim(s.item_code))
                        AND trim(COALESCE(ol.description,''))<>'' LIMIT 1),
                    (SELECT al.description FROM attention_lines al
                      WHERE upper(trim(al.item_code))=upper(trim(s.item_code))
                        AND trim(COALESCE(al.description,''))<>'' LIMIT 1), '') AS description,
                  COALESCE(i.part_number,'') AS part_number
             FROM inventory_stock s
             LEFT JOIN inventory_governance_items i ON i.item_key=s.item_key
            WHERE s.is_current=1 AND s.warehouse_key='1'
              AND (s.item_code LIKE ? OR i.description LIKE ? OR i.part_number LIKE ?
                   OR EXISTS (SELECT 1 FROM inventory_governance_barcodes b
                               WHERE b.item_key=s.item_key AND b.barcode LIKE ?))
            ORDER BY s.item_code LIMIT 101""",
        (like, like, like, like),
    ).fetchall()
    items = {}
    for row in stock_rows:
        code = str(row["item_code"] or "").strip()
        key = item_key(code)
        if not key:
            continue
        stock = global_stock_summary(connection, code, str(row["warehouse"] or "1"))
        item = dict(row)
        item.update({
            "stock_qty": float(stock.get("stock_cut_qty") or 0),
            "committed_qty": float(stock.get("stock_ov_commitment_qty") or 0),
            "available_qty": float(stock.get("stock_available_qty") or 0),
            "default_location": str(stock.get("stock_default_location") or row["default_location"] or "").strip(),
            "snapshot_day": stock.get("stock_snapshot_at") or row["snapshot_day"],
            "barcode": code,
            "has_stock_record": True,
        })
        items[key] = item
    master_rows = connection.execute(
        """SELECT i.item_key, i.item_code, i.part_number, i.description,
                  '' AS warehouse, 0 AS snapshot_qty, '' AS snapshot_day,
                  '' AS snapshot_at, '' AS default_location
             FROM inventory_governance_items i
            WHERE (i.item_code LIKE ? OR i.description LIKE ? OR i.part_number LIKE ?
                   OR EXISTS (SELECT 1 FROM inventory_governance_barcodes b
                               WHERE b.item_key=i.item_key AND b.barcode LIKE ?))
              AND NOT EXISTS (SELECT 1 FROM inventory_stock s
                               WHERE s.item_key=i.item_key AND s.warehouse_key='1' AND s.is_current=1)
            ORDER BY i.item_code LIMIT 101""",
        (like, like, like, like),
    ).fetchall()
    for row in master_rows:
        key = str(row["item_key"])
        items[key] = {
            **dict(row), "stock_qty": 0.0, "committed_qty": 0.0,
            "available_qty": 0.0, "barcode": str(row["item_code"]),
            "has_stock_record": False,
        }
    all_items = sorted(items.values(), key=lambda item: str(item["item_code"]).casefold())
    has_more = len(all_items) > 100
    all_items = all_items[:100]
    for item in all_items:
        aliases = connection.execute(
            "SELECT barcode, symbology FROM inventory_governance_barcodes WHERE item_key=? ORDER BY id",
            (item["item_key"],),
        ).fetchall()
        item["barcodes"] = [dict(alias) for alias in aliases]
        item.pop("item_key", None)
    return {"items": all_items, "has_more": has_more, "hint": ""}


def list_material_requests(connection, username="", role=""):
    _require_role(role)
    if str(role).upper() == "ADMINISTRADOR":
        rows = connection.execute(
            "SELECT * FROM inventory_material_requests ORDER BY CASE status WHEN 'PENDIENTE' THEN 0 ELSE 1 END, created_at DESC LIMIT 300"
        ).fetchall()
    else:
        rows = connection.execute(
            "SELECT * FROM inventory_material_requests WHERE requested_by=? ORDER BY created_at DESC LIMIT 100",
            (str(username or ""),),
        ).fetchall()
    return [dict(row) for row in rows]


def create_material_request(connection, payload, username="", role=""):
    _require_role(role)
    item_code = _clean(payload.get("item_code"), "el número de parte/NPS", 80, required=True)
    part_number = _clean(payload.get("part_number"), "el número de parte del fabricante", 100)
    description = _clean(payload.get("description"), "la descripción", 240, required=True)
    justification = _clean(payload.get("justification"), "el motivo de solicitud", 500, required=True)
    key = item_key(item_code)
    if not key:
        raise ValueError("El NPS debe contener letras o números")
    known = _known_materials(connection)
    if key in known:
        existing = known[key]["item_code"]
        raise ValueError(f"El NPS {existing} ya existe en el inventario o en operaciones")
    existing_request = connection.execute(
        "SELECT id FROM inventory_material_requests WHERE item_key=? AND status='PENDIENTE' LIMIT 1",
        (key,),
    ).fetchone()
    if existing_request:
        raise ValueError("Ya existe una solicitud pendiente para este NPS")
    normalized_description = _normalize_text(description)
    suggestions = []
    if normalized_description:
        for record in known.values():
            for current_description in record["descriptions"]:
                current_key = _normalize_text(current_description)
                if not current_key:
                    continue
                similarity = SequenceMatcher(None, normalized_description, current_key).ratio()
                if similarity >= 0.78:
                    suggestions.append({"item_code": record["item_code"],
                                        "description": current_description,
                                        "similarity": round(similarity, 2)})
                    break
    suggestions.sort(key=lambda item: item["similarity"], reverse=True)
    timestamp = local_now()
    cursor = connection.execute(
        """INSERT INTO inventory_material_requests
           (item_code,item_key,part_number,description,justification,status,requested_by,created_at)
           VALUES (?,?,?,?,?,'PENDIENTE',?,?)""",
        (item_code, key, part_number, description, justification, str(username or ""), timestamp),
    )
    return {"id": int(cursor.lastrowid), "item_code": item_code, "status": "PENDIENTE",
            "similar_items": suggestions[:5]}


def decide_material_request(connection, request_id, decision, note, username="", role=""):
    _require_role(role)
    if str(role).upper() != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede aprobar o rechazar NPS")
    try:
        request_id = int(request_id)
    except (TypeError, ValueError):
        raise ValueError("Selecciona una solicitud válida")
    choice = str(decision or "").strip().upper()
    if choice not in {"APROBAR", "RECHAZAR"}:
        raise ValueError("La decisión debe ser Aprobar o Rechazar")
    decision_note = _clean(note, "el comentario de decisión", 500)
    if choice == "RECHAZAR" and len(decision_note) < 5:
        raise ValueError("Indica el motivo del rechazo (mínimo 5 caracteres)")
    request = connection.execute(
        "SELECT * FROM inventory_material_requests WHERE id=?", (request_id,)
    ).fetchone()
    if not request:
        raise ValueError("No existe la solicitud seleccionada")
    if request["status"] != "PENDIENTE":
        raise ValueError("La solicitud ya fue atendida")
    timestamp = local_now()
    if choice == "APROBAR":
        if request["item_key"] in _known_materials(connection):
            raise ValueError("Este NPS ya se incorporó a los datos operativos; actualiza la consulta antes de aprobar")
        connection.execute(
            """INSERT INTO inventory_governance_items
               (item_key,item_code,part_number,description,created_by,created_at)
               VALUES (?,?,?,?,?,?)""",
            (request["item_key"], request["item_code"], request["part_number"],
             request["description"], str(username or ""), timestamp),
        )
        # El NP aprobado funciona como código escaneable desde el primer día.
        connection.execute(
            """INSERT OR IGNORE INTO inventory_governance_barcodes
               (item_key,item_code,barcode,barcode_key,symbology,created_by,created_at)
               VALUES (?,?,?,?, 'CODE39', ?, ?)""",
            (request["item_key"], request["item_code"], f"WMS-{request['item_key']}",
             item_key(f"WMS-{request['item_key']}"), str(username or ""), timestamp),
        )
    status = "APROBADA" if choice == "APROBAR" else "RECHAZADA"
    connection.execute(
        """UPDATE inventory_material_requests
              SET status=?, decided_by=?, decided_at=?, decision_note=? WHERE id=?""",
        (status, str(username or ""), timestamp, decision_note, request_id),
    )
    return {"id": request_id, "item_code": request["item_code"], "status": status}


def generate_item_barcode(connection, item_code, username="", role=""):
    _require_role(role)
    if str(role).upper() != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede generar códigos internos")
    code = _clean(item_code, "el NPS", 80, required=True)
    key = item_key(code)
    known = _known_materials(connection)
    if key not in known:
        if not connection.execute("SELECT 1 FROM inventory_governance_items WHERE item_key=?", (key,)).fetchone():
            raise ValueError("El NPS no existe en el inventario")
    barcode = f"WMS-{key}"
    barcode_key = item_key(barcode)
    if connection.execute(
        "SELECT 1 FROM inventory_governance_barcodes WHERE barcode_key=? AND item_key<>? LIMIT 1",
        (barcode_key, key),
    ).fetchone():
        raise ValueError("El código generado ya pertenece a otro NPS")
    timestamp = local_now()
    connection.execute(
        """INSERT OR IGNORE INTO inventory_governance_barcodes
           (item_key,item_code,barcode,barcode_key,symbology,created_by,created_at)
           VALUES (?,?,?,?, 'CODE39', ?, ?)""",
        (key, code, barcode, barcode_key, str(username or ""), timestamp),
    )
    return {"item_code": code, "barcode": barcode, "symbology": "CODE39"}
