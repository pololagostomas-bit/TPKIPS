import argparse
import base64
import json
import os
import sqlite3
import threading
import shutil
import logging
import tempfile
import unicodedata
from io import BytesIO
from contextlib import nullcontext
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from openpyxl import load_workbook
from backend.services import identity
from backend.services.notifications import init_notifications_schema, notification_summary, retry_notification, GraphConfig
from backend.services.daily_operations import (
    advanced_lots_enabled, local_now, normalize_cutoff, init_daily_schema,
    import_identity, check_import, record_import, data_status,
    operational_balance, commitment_status, reconcile_deliveries, return_reconciled_stock, DailyConnection,
)

from backend.services.reception import (
    RECEPTION_ROLES,
    add_physical_receipt,
    close_physical_receipts,
    change_reception_status,
    create_reception,
    import_reception_accounting_excel_bytes,
    import_reception_accounting_excel_path,
    import_reception_excel_bytes,
    import_reception_excel_path,
    import_reception_workbook,
    init_reception_schema,
    list_receptions,
    reception_links,
    reception_detail,
    reception_history_export_bytes,
    reception_history_report,
    reception_operational_report_bytes,
    reception_report,
    rewind_reception_stage,
    require_reception_access,
    update_reception_references,
    update_reception_line_quantity,
    update_reception_location,
    update_reception_validation,
    confirm_reception_transfer,
)
from backend.services.traceability import (
    assign_lot_manually,
    available_lots_for_line,
    init_traceability_schema,
    line_lot_tracking,
    record_lot_delivery,
    register_label_print,
    release_lot_reservations,
    reserve_lots_for_allocation,
    return_lot_after_picking,
    reverse_lot_consumption,
    traceability_search,
    update_lot_location,
    validate_lot_scan,
    validate_picked_against_scans,
    consume_lots_for_line,
)


ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("TRITON_DB_PATH", str(ROOT / "triton.db")))
STATIC_PATH = ROOT / "frontend" / "static"
LOGO_PATH = STATIC_PATH / "triton-logo.png"
RECEPTION_HTML_PATH = ROOT / "frontend" / "templates" / "reception.html"
PORT = 8000
HOST = "127.0.0.1"

STATUSES = [
    "PENDIENTE",
    "ASIGNADO",
    "EN PICKING",
    "PICKING FINALIZADO",
    "POR GUIAR",
    "EN GUIADO",
    "GUIADO FINALIZADO",
    "ENTREGADO",
    "CERRADO SAP",
]
STATUS_INDEX = {value: index for index, value in enumerate(STATUSES)}
TERMINAL_ATTENTION_STATUSES = {"ENTREGADO", "CERRADO SAP"}
PICKER_ROLES = {"PICKER", "PICKER_GUIADOR"}
GUIDE_ROLES = {"GUIADOR", "PICKER_GUIADOR"}
DISPATCH_ROLES = {"ADMINISTRADOR", "PICKER", "GUIADOR", "PICKER_GUIADOR"}
ROLES = DISPATCH_ROLES | RECEPTION_ROLES
MAX_IMPORT_BYTES = 50 * 1024 * 1024


def now():
    return local_now()


@contextmanager
def db():
    connection = sqlite3.connect(DB_PATH, timeout=30, factory=DailyConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()
    finally:
        connection.close()


def init_db():
    # La ruta puede apuntar a almacenamiento persistente del entorno (por ejemplo
    # /home/data en el piloto de Azure).  Crear la carpeta evita que el primer
    # arranque falle cuando aún no existe la base.
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                sap_ov TEXT PRIMARY KEY,
                internal_id TEXT,
                customer_code TEXT,
                customer_name TEXT,
                delivery_date TEXT,
                source_order_date TEXT,
                destination TEXT,
                shipping_method TEXT,
                transport_type TEXT NOT NULL DEFAULT 'SIN DEFINIR',
                salesperson TEXT,
                source_status TEXT,
                document_status TEXT,
                sap_status_summary TEXT,
                sap_open_sku_count INTEGER NOT NULL DEFAULT 0,
                sap_attended_sku_count INTEGER NOT NULL DEFAULT 0,
                attention_type TEXT NOT NULL DEFAULT 'SELECCIONAR',
                app_status TEXT NOT NULL DEFAULT 'PENDIENTE',
                current_picker TEXT,
                current_guide TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS order_importation_refs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sap_ov TEXT NOT NULL,
                bl_awb TEXT,
                transport_type TEXT NOT NULL DEFAULT 'SIN DEFINIR',
                ip_reference TEXT,
                oc_number TEXT,
                source_sheet TEXT,
                source_row INTEGER,
                source_date TEXT,
                source_file TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(sap_ov, bl_awb, transport_type, ip_reference, oc_number, source_sheet, source_row)
            );

            CREATE TABLE IF NOT EXISTS order_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sap_ov TEXT NOT NULL REFERENCES orders(sap_ov),
                source_row INTEGER NOT NULL,
                item_code TEXT,
                description TEXT,
                required_qty REAL DEFAULT 0,
                pending_qty REAL DEFAULT 0,
                available_qty REAL DEFAULT 0,
                unit_price REAL DEFAULT 0,
                total_amount REAL DEFAULT 0,
                warehouse TEXT,
                cost_center TEXT,
                article_group TEXT,
                sap_line_status TEXT,
                is_pending_sap INTEGER NOT NULL DEFAULT 1,
                UNIQUE(sap_ov, source_row)
            );

            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sap_ov TEXT NOT NULL,
                event_type TEXT NOT NULL,
                field_name TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                username TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sap_ov TEXT NOT NULL,
                role TEXT NOT NULL,
                old_user TEXT,
                new_user TEXT NOT NULL,
                username TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS attentions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sap_ov TEXT NOT NULL REFERENCES orders(sap_ov),
                sequence_no INTEGER NOT NULL,
                attention_type TEXT NOT NULL DEFAULT 'SELECCIONAR',
                app_status TEXT NOT NULL DEFAULT 'PENDIENTE',
                current_picker TEXT,
                current_guide TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(sap_ov, sequence_no)
            );

            CREATE TABLE IF NOT EXISTS attention_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attention_id INTEGER NOT NULL REFERENCES attentions(id) ON DELETE CASCADE,
                order_line_id INTEGER NOT NULL REFERENCES order_lines(id),
                planned_qty REAL NOT NULL DEFAULT 0,
                picked_qty REAL NOT NULL DEFAULT 0,
                delivered_qty REAL NOT NULL DEFAULT 0,
                source_row INTEGER,
                item_code TEXT,
                description TEXT,
                required_qty REAL,
                pending_qty REAL,
                available_qty REAL,
                warehouse TEXT,
                UNIQUE(attention_id, order_line_id)
            );

            CREATE TABLE IF NOT EXISTS attention_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attention_id INTEGER NOT NULL REFERENCES attentions(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                field_name TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                username TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS attention_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attention_id INTEGER NOT NULL REFERENCES attentions(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                old_user TEXT,
                new_user TEXT NOT NULL,
                username TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS inventory_stock (
                item_key TEXT NOT NULL,
                warehouse_key TEXT NOT NULL,
                item_code TEXT NOT NULL,
                warehouse TEXT NOT NULL,
                snapshot_qty REAL NOT NULL DEFAULT 0,
                snapshot_day TEXT NOT NULL,
                snapshot_at TEXT NOT NULL,
                source_file TEXT,
                is_current INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(item_key, warehouse_key)
            );

            CREATE TABLE IF NOT EXISTS stock_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attention_id INTEGER NOT NULL REFERENCES attentions(id) ON DELETE CASCADE,
                attention_line_id INTEGER NOT NULL UNIQUE REFERENCES attention_lines(id) ON DELETE CASCADE,
                sap_ov TEXT NOT NULL,
                item_key TEXT NOT NULL,
                item_code TEXT NOT NULL,
                warehouse_key TEXT NOT NULL,
                warehouse TEXT NOT NULL,
                pool_type TEXT NOT NULL,
                origin_type TEXT NOT NULL,
                reserved_qty REAL NOT NULL DEFAULT 0,
                consumed_qty REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'ACTIVA',
                reserved_at TEXT NOT NULL,
                consumed_at TEXT,
                released_at TEXT,
                username TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS stock_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                allocation_id INTEGER REFERENCES stock_allocations(id) ON DELETE SET NULL,
                attention_id INTEGER NOT NULL,
                attention_line_id INTEGER NOT NULL,
                sap_ov TEXT NOT NULL,
                item_key TEXT NOT NULL,
                item_code TEXT NOT NULL,
                warehouse_key TEXT NOT NULL,
                warehouse TEXT NOT NULL,
                pool_type TEXT NOT NULL,
                movement_type TEXT NOT NULL,
                quantity REAL NOT NULL,
                username TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL,
                shift TEXT NOT NULL DEFAULT 'DÍA',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        ensure_column(connection, "attention_lines", "source_row", "INTEGER")
        ensure_column(connection, "attention_lines", "item_code", "TEXT")
        ensure_column(connection, "attention_lines", "description", "TEXT")
        ensure_column(connection, "attention_lines", "required_qty", "REAL")
        ensure_column(connection, "attention_lines", "pending_qty", "REAL")
        ensure_column(connection, "attention_lines", "available_qty", "REAL")
        ensure_column(connection, "attention_lines", "warehouse", "TEXT")
        ensure_column(connection, "orders", "document_status", "TEXT")
        ensure_column(connection, "orders", "sap_status_summary", "TEXT")
        ensure_column(connection, "orders", "source_order_date", "TEXT")
        ensure_column(connection, "orders", "transport_type", "TEXT NOT NULL DEFAULT 'SIN DEFINIR'")
        ensure_column(connection, "orders", "sap_open_sku_count", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection, "orders", "sap_attended_sku_count", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection, "order_lines", "article_group", "TEXT")
        ensure_column(connection, "order_lines", "sap_line_status", "TEXT")
        ensure_column(connection, "order_lines", "is_pending_sap", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(connection, "order_importation_refs", "item_code", "TEXT")
        ensure_column(connection, "order_importation_refs", "item_key", "TEXT")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_order_importation_refs_ov ON order_importation_refs(sap_ov)")
        # La consulta de reservas aéreas se hace por NP al abrir una OV. Este
        # índice evita recorrer referencias de otras importaciones cuando el
        # corte contiene miles de SKU y solo una fracción tiene stock.
        connection.execute("CREATE INDEX IF NOT EXISTS idx_order_importation_refs_item_key ON order_importation_refs(item_key)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_inventory_stock_item ON inventory_stock(item_key, warehouse_key)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_stock_allocations_pool ON stock_allocations(pool_type, item_key, warehouse_key, status)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_stock_allocations_ov ON stock_allocations(sap_ov, item_key, status)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_stock_movements_item ON stock_movements(item_key, warehouse_key, created_at)")
        connection.execute(
            """UPDATE attention_lines
               SET source_row = COALESCE(source_row, (SELECT source_row FROM order_lines WHERE id = order_line_id)),
                   item_code = COALESCE(item_code, (SELECT item_code FROM order_lines WHERE id = order_line_id)),
                   description = COALESCE(description, (SELECT description FROM order_lines WHERE id = order_line_id)),
                   required_qty = COALESCE(required_qty, (SELECT required_qty FROM order_lines WHERE id = order_line_id)),
                   pending_qty = COALESCE(pending_qty, (SELECT pending_qty FROM order_lines WHERE id = order_line_id)),
                   available_qty = COALESCE(available_qty, (SELECT available_qty FROM order_lines WHERE id = order_line_id)),
                   warehouse = COALESCE(warehouse, (SELECT warehouse FROM order_lines WHERE id = order_line_id))
               WHERE source_row IS NULL OR item_code IS NULL OR description IS NULL"""
        )
        init_reception_schema(connection)
        init_traceability_schema(connection)
        init_daily_schema(connection)
        identity.init_identity_schema(connection)
        init_notifications_schema(connection)
        timestamp = now()
        if os.getenv('TRITON_AUTH_MODE','demo') == 'demo':
            connection.execute(
                """INSERT OR IGNORE INTO users
                   (username, display_name, role, shift, active, created_at, updated_at)
                   VALUES ('demo.admin', 'Administrador demo', 'ADMINISTRADOR', 'DÍA', 1, ?, ?)""",
                (timestamp, timestamp),
            )
        bootstrap_inventory_from_order_lines(connection)
        bootstrap_active_stock_allocations(connection)


def ensure_column(connection, table, column, definition):
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def clean_header(value):
    if value is None:
        return ""
    value = str(value).strip()
    if "[" in value and value.endswith("]"):
        value = value[value.find("[") + 1 : -1]
    return " ".join(value.lower().replace("°", "").replace(".", "").split())


def normalized_value(value):
    """Normaliza valores SAP para comparar grupos, almacenes y estados."""
    value = unicodedata.normalize("NFKD", text(value)).encode("ascii", "ignore").decode("ascii")
    return " ".join(value.lower().replace(".", " ").replace("_", " ").split())


def allowed_article_group(value):
    # El grupo puede venir vacío en el query; en ese caso no debe ocultarse.
    # Solo se excluyen las filas de servicios, que no representan un SKU.
    return not normalized_value(value).startswith("servicio")


def is_warehouse_one(value):
    return normalized_value(value) in {"1", "1 0"}


def is_open_document(value):
    return normalized_value(value).startswith("abiert")


def is_pending_sap_line(value):
    return normalized_value(value) in {"ov abierta", "orden de venta abierta"}


def normalize_transport(value):
    normalized = normalized_value(value)
    if "aere" in normalized:
        return "AEREO"
    if "marit" in normalized:
        return "MARITIMO"
    if "courier" in normalized:
        # En el flujo operativo Courier es una vía aérea, no una categoría
        # distinta. Así evitamos que una misma OV aparezca como dos medios.
        return "AEREO"
    return "SIN DEFINIR"


def is_air_transport(value):
    return normalize_transport(value) == "AEREO"


def transport_line_category(value):
    """Clasifica una línea importada para el control operativo de Picking."""
    normalized = normalize_transport(value)
    return normalized if normalized in {"AEREO", "MARITIMO"} else "STOCK"


def summarize_line_categories(categories):
    """Devuelve el texto operativo del origen de las líneas de una OV."""
    order = ("AEREO", "MARITIMO", "STOCK")
    present = {category for category in categories if category in order}
    if not present:
        return "SIN DEFINIR"
    selected = [category for category in order if category in present]
    if len(selected) == 1:
        return selected[0]
    if len(selected) == 2:
        return f"MIXTO ({selected[0]} Y {selected[1]})"
    return "MIXTO (AEREO, MARITIMO Y STOCK)"


def is_triton_customer(value):
    return normalized_value(value).startswith("triton trading")


ALIASES = {
    "internal_id": {"número interno", "numero interno", "numero interno de sap"},
    "sap_ov": {"n sap ov", "n sapov", "sap ov", "ov", "n°sap_ov", "número de documento", "numero de documento"},
    "source_line": {"n° de línea", "n de linea", "n línea", "n linea"},
    "customer_code": {"cod cliente", "codigo cliente", "código de cliente/proveedor", "codigo de cliente/proveedor"},
    "customer_name": {"nombre/razon social", "nombre razon social", "nombre de cliente/proveedor"},
    "delivery_date": {"fecha entrega"},
    "source_order_date": {
        "fecha de contabilización", "fecha contabilización", "fecha emisión", "fecha de emisión",
        "fechacrea ov", "fechacrea_ov", "fecha crea ov", "fecha_crea_ov",
        "fecha creacion ov", "fecha_creacion_ov", "fecha contabilizacion",
        "fecha_contabilizacion", "fecha de contabilizacion", "fecha_de_contabilizacion",
        "fecha emision", "fecha_emision", "fecha de emision", "fecha_de_emision",
    },
    "source_creation_date": {"fechacrea ov", "fechacrea_ov", "fecha crea ov", "fecha_crea_ov"},
    "source_order_time": {"horacrea_ov", "horacrea ov", "hora crea ov", "hora de creación"},
    "destination": {"destino"},
    "shipping_method": {"forma envio", "forma envío"},
    "salesperson": {"vendedor", "ejecutivo de ventas"},
    "source_status": {"situacion de maquina", "situacion de maquina2"},
    "document_status": {"status de documento", "estado de documento"},
    "sap_line_status": {"status", "estado"},
    "article_group": {"grupo de articulo", "grupo de artículo"},
    "item_code": {"cod articulo", "codigo articulo", "número de artículo", "numero de articulo"},
    "description": {"descripción", "descripcion", "descripción artículo/serv", "descripcion articulo/serv"},
    "service_description": {"descripción (servicios)", "descripcion (servicios)", "descripcion servicios"},
    "required_qty": {"cant requerida", "cantidad requerida", "cantidad"},
    "pending_qty": {"cant pendiente", "cantidad pendiente"},
    "available_qty": {"stockdisponible", "stock disponible"},
    "attention_type": {"tipo de atención", "tipo de atencion"},
    "attention_type_2": {"tipo de atención2", "tipo de atencion2"},
    "unit_price": {"p unit", "punit", "costounitario", "costo unitario"},
    "total_amount": {"importe total", "costototal", "costo total"},
    "warehouse": {"almacen", "almacén"},
    "cost_center": {"ceco", "centro de costo"},
}


def pick_column(headers, field):
    aliases = {clean_header(alias) for alias in ALIASES[field]}
    for header, original in headers.items():
        if header in aliases:
            return original
    return None


def source_order_timestamp(get):
    """Creation time wins over accounting date; never use an import arrival."""
    from backend.services.workload import _timestamp
    creation = get('source_creation_date')
    raw = creation or get('source_order_date')
    parsed = _timestamp(raw)
    if parsed is None:
        return text(raw)
    hour = get('source_order_time') if creation else None
    if hour is not None and str(hour).strip():
        try:
            if hasattr(hour, 'hour'):
                h, m, s = hour.hour, hour.minute, hour.second
            elif isinstance(hour, float) and 0 <= hour < 1:
                seconds = round(hour * 86400)
                h, rest = divmod(seconds, 3600)
                m, s = divmod(rest, 60)
            elif ':' in str(hour):
                parts = [int(v) for v in str(hour).split(':')]
                h, m, s = (parts + [0])[:3]
            else:
                number = str(int(float(hour))).zfill(4)
                h, m, s = int(number[:-2]), int(number[-2:]), 0
            parsed = parsed.replace(hour=h, minute=m, second=s)
            return parsed.isoformat(sep=' ', timespec='seconds')
        except (ValueError, TypeError, OverflowError):
            raise ValueError('Hora de creación OV inválida: ' + str(hour))
    if parsed.hour or parsed.minute or parsed.second:
        return parsed.isoformat(sep=' ', timespec='seconds')
    return parsed.date().isoformat()


def text(value):
    return "" if value is None else str(value).strip()


def same_username(first, second):
    """Compares demo and Entra usernames without case/space surprises."""
    return text(first).casefold() == text(second).casefold()


def number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def normalize_attention(value):
    value = text(value).upper()
    if value in {"TOTAL", "COMPLETA", "COMPLETO"}:
        return "COMPLETA"
    if value in {"PARCIAL", "PARCIALMENTE"}:
        return "PARCIAL"
    return "SELECCIONAR"


def stable_source_row(connection, sap_ov, line_number, item_code, warehouse, pending, excel_row, counters):
    base = json.dumps([text(line_number), normalized_identifier(item_code), normalized_warehouse(warehouse), bool(pending)])
    counters[base] = counters.get(base, 0) + 1
    key = base + ":" + str(counters[base])
    existing = connection.execute("SELECT source_row FROM order_lines WHERE sap_ov=? AND source_key=?", (sap_ov, key)).fetchone()
    if existing:
        return existing["source_row"]
    # Adopta el ID anterior por NP; cambiar el orden físico del Excel no cambia
    # el artículo al que apunta el historial de una atención.
    legacy = next((row for row in connection.execute(
        "SELECT id,source_row,item_code,warehouse FROM order_lines WHERE sap_ov=? AND source_key IS NULL ORDER BY source_row", (sap_ov,)
    ) if normalized_identifier(row["item_code"]) == normalized_identifier(item_code)
                  and normalized_warehouse(row["warehouse"]) == normalized_warehouse(warehouse)), None)
    if legacy:
        connection.execute("UPDATE order_lines SET source_key=? WHERE id=?", (key, legacy["id"]))
        return legacy["source_row"]
    next_row = max(excel_row, connection.execute("SELECT COALESCE(MAX(source_row),0)+1 FROM order_lines WHERE sap_ov=?", (sap_ov,)).fetchone()[0])
    connection.execute("INSERT INTO order_lines(sap_ov,source_row,item_code,source_key,is_pending_sap) VALUES (?,?,?,?,0)", (sap_ov, next_row, item_code, key))
    return next_row


def remaining_line_quantity(connection, sap_ov, line):
    order = connection.execute("SELECT source_cutoff_at FROM orders WHERE sap_ov=?", (sap_ov,)).fetchone()
    cutoff = order["source_cutoff_at"] or "" if order else ""
    local_deliveries = connection.execute("""SELECT COALESCE(SUM(al.delivered_qty),0)
        FROM attention_lines al JOIN attentions a ON a.id=al.attention_id
        WHERE al.order_line_id=? AND a.app_status='ENTREGADO'
        AND EXISTS(SELECT 1 FROM attention_history h WHERE h.attention_id=a.id
          AND h.event_type='ESTADO' AND h.new_value='ENTREGADO' AND h.created_at>?)""", (line["id"], cutoff)).fetchone()[0]
    return max(0, number(line["pending_qty"]) - number(local_deliveries))


def import_excel(path, reset=False, cutoff_at=None, username="sistema.local", source_filename=None, reconcile_delivered=True):
    workbook = load_workbook(path, data_only=True, read_only=True)
    try:
        identity = import_identity(Path(path).read_bytes(), "dispatch", cutoff_at,
                                   source_filename or Path(path).name, username)
        return _import_dispatch_workbook(workbook, path, reset, identity, reconcile_delivered)
    finally:
        workbook.close()


def stock_sheet_candidates(workbook):
    """Lee la hoja de stock del query consolidado de SAP.

    El archivo diario puede traer `ovs` y `stock` en el mismo libro. La hoja
    de OVs define las líneas de despacho y `stock` contiene el corte global
    por NP y almacén. No usamos `Disponible`: ya viene afectado por SAP;
    partimos de `En stock` y el WMS descuenta sus propias reservas trazables.
    """
    # El nombre es solo una recomendación. La detección real se hace por los
    # encabezados para aceptar archivos del query con pestañas renombradas.
    wanted_names = {"stock", "stocks", "inventario", "existencias"}
    matches = []
    for sheet in workbook.worksheets:
        header_row = None
        code_column = stock_column = None
        for row_number, row in enumerate(sheet.iter_rows(min_row=1, max_row=20, values_only=True), start=1):
            headers = {normalized_value(value): index for index, value in enumerate(row) if value is not None}
            code_column = next((index for header, index in headers.items()
                                if header in {"numero de articulo", "codigo de articulo", "cod articulo"}), None)
            stock_column = next((index for header, index in headers.items()
                                 if header in {"en stock", "stock", "existencia", "existencias"}), None)
            if code_column is not None and stock_column is not None:
                header_row = row_number
                break
        if header_row is None:
            continue
        candidates = {}
        current_warehouse = "1"
        for raw in sheet.iter_rows(min_row=header_row + 1, values_only=True):
            label = text(raw[0] if raw else "")
            if normalized_value(label) in {"almacen", "almacen:"}:
                if len(raw) > 1 and text(raw[1]):
                    current_warehouse = text(raw[1])
                continue
            item_code = text(raw[code_column]) if code_column < len(raw) else ""
            if not item_code:
                continue
            warehouse = current_warehouse or "1"
            candidate = candidates.setdefault(
                (normalized_identifier(item_code), normalized_warehouse(warehouse)),
                {"item_code": item_code, "warehouse": warehouse, "values": []},
            )
            candidate["values"].append(number(raw[stock_column] if stock_column < len(raw) else 0))
        # Si hay más de una hoja con este formato, se prioriza la que tiene el
        # nombre recomendado; así una hoja auxiliar no reemplaza el corte SAP.
        matches.append((clean_header(sheet.title) in wanted_names, candidates, sheet.title))
    if not matches:
        return {}, None
    _, candidates, sheet_name = max(matches, key=lambda match: (match[0], len(match[1])))
    return candidates, sheet_name


def _import_dispatch_workbook(workbook, path, reset, identity, reconcile_delivered):
    sheet = None
    header_row = None
    headers = None
    columns = None
    # Algunos archivos del query tienen el encabezado dentro de una hoja
    # auxiliar o dejan filas de título antes de la tabla. Buscamos en todas
    # las hojas y en las primeras filas para no depender de la hoja activa.
    for candidate in workbook.worksheets:
        for row_number, candidate_row in enumerate(candidate.iter_rows(min_row=1, max_row=20, values_only=True), start=1):
            candidate_headers = {clean_header(value): index for index, value in enumerate(candidate_row) if value is not None}
            candidate_columns = {field: pick_column(candidate_headers, field) for field in ALIASES}
            if candidate_columns["sap_ov"] is not None and candidate_columns["item_code"] is not None:
                sheet = candidate
                header_row = row_number
                headers = candidate_headers
                columns = candidate_columns
                break
        if sheet is not None:
            break
    if sheet is None:
        raise ValueError("No encontré las columnas N°SAP_OV y Cod Articulo en las primeras 20 filas de ninguna hoja")

    rows = sheet.iter_rows(min_row=header_row + 1, values_only=True)
    stock_candidates, stock_sheet = stock_sheet_candidates(workbook)

    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if not reset:
            duplicate = check_import(connection, identity)
            if duplicate:
                return duplicate
        if reset:
            traced_reservations = connection.execute(
                "SELECT COUNT(*) FROM lot_reservations"
            ).fetchone()[0]
            if traced_reservations:
                raise ValueError(
                    "No se puede usar --reset después de iniciar la trazabilidad por lotes. "
                    "Carga el Excel sin --reset para conservar el kardex."
                )
            # Las tablas de stock dependen de atenciones y líneas. Se limpian
            # primero para que el reinicio explícito del importador no deje
            # reservas huérfanas ni falle por integridad referencial.
            connection.executescript(
                "DELETE FROM stock_movements; "
                "DELETE FROM stock_allocations; "
                "DELETE FROM inventory_stock; "
                "DELETE FROM attention_history; "
                "DELETE FROM attention_assignments; "
                "DELETE FROM attention_lines; "
                "DELETE FROM attentions; "
                "DELETE FROM history; "
                "DELETE FROM assignments; "
                "DELETE FROM order_lines; "
                "DELETE FROM orders;"
            )
        imported = 0
        source_rows = 0
        skipped_rows = 0
        excluded_group_rows = 0
        excluded_warehouse_rows = 0
        excluded_document_rows = 0
        sap_attended_rows = 0
        grouped = {}
        closed_grouped = {}
        seen_ovs = set()
        inventory_candidates = {}
        for source_row, raw in enumerate(rows, start=header_row + 1):
            source_rows += 1
            get = lambda field: raw[columns[field]] if field in columns and columns[field] is not None and columns[field] < len(raw) else None
            sap_ov = text(get("sap_ov"))
            if not sap_ov:
                skipped_rows += 1
                continue
            if columns["article_group"] is not None and not allowed_article_group(get("article_group")):
                excluded_group_rows += 1
                continue
            if (
                columns.get("service_description") is not None
                and not text(get("item_code"))
                and text(get("service_description"))
            ):
                excluded_group_rows += 1
                continue
            if columns["warehouse"] is not None and not is_warehouse_one(get("warehouse")):
                excluded_warehouse_rows += 1
                continue
            # El NP puede aparecer solo en documentos cerrados y aun así traer
            # una existencia válida. El corte de stock se lee antes de filtrar OVs.
            if columns["available_qty"] is not None and text(get("item_code")):
                item_code = text(get("item_code"))
                warehouse = text(get("warehouse")) or "1"
                candidate = inventory_candidates.setdefault(
                    (normalized_identifier(item_code), normalized_warehouse(warehouse)),
                    {"item_code": item_code, "warehouse": warehouse, "values": []},
                )
                candidate["values"].append(number(get("available_qty")))
            if columns["document_status"] is not None and not is_open_document(get("document_status")):
                excluded_document_rows += 1
                closed_grouped.setdefault(sap_ov, []).append((source_row, raw))
                continue
            seen_ovs.add(sap_ov)
            # Guardamos la fila física, no el lambda `get`: el lambda cerraría
            # sobre la última variable `raw` del bucle y mezclaría datos entre OVs.
            grouped.setdefault(sap_ov, []).append((source_row, raw))

        shortage_orders = 0
        for sap_ov in seen_ovs:
            # El Excel es una foto actual de SAP. Las líneas que ya no califican
            # no deben volver a aparecer en una nueva atención.
            connection.execute("UPDATE order_lines SET is_pending_sap = 0 WHERE sap_ov = ?", (sap_ov,))
        for sap_ov, lines in grouped.items():
            source_keys = {}
            _, first_raw = lines[0]
            first_get = lambda field: first_raw[columns[field]] if field in columns and columns[field] is not None and columns[field] < len(first_raw) else None
            status_counts = {}
            open_sku_count = 0
            attended_sku_count = 0
            prepared_lines = []
            for source_row, current_raw in lines:
                get = lambda field: current_raw[columns[field]] if field in columns and columns[field] is not None and columns[field] < len(current_raw) else None
                sap_line_status = text(get("sap_line_status")) if columns["sap_line_status"] is not None else "OV ABIERTA"
                pending_sap = is_pending_sap_line(sap_line_status)
                status_label = sap_line_status or "SIN ESTADO"
                status_counts[status_label] = status_counts.get(status_label, 0) + 1
                open_sku_count += int(pending_sap)
                attended_sku_count += int(not pending_sap)
                prepared_lines.append((source_row, current_raw, pending_sap, sap_line_status))
            sap_status_summary = " · ".join(f"{status}: {count}" for status, count in sorted(status_counts.items()))
            timestamp = now()
            connection.execute(
                """INSERT INTO orders (sap_ov, internal_id, customer_code, customer_name, delivery_date,
                   source_order_date, destination, shipping_method, transport_type, salesperson, source_status, document_status, sap_status_summary,
                   sap_open_sku_count, sap_attended_sku_count, attention_type, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(sap_ov) DO UPDATE SET
                     internal_id=excluded.internal_id, customer_code=excluded.customer_code,
                     customer_name=excluded.customer_name, delivery_date=excluded.delivery_date,
                     source_order_date=excluded.source_order_date, destination=excluded.destination,
                     shipping_method=excluded.shipping_method, transport_type=excluded.transport_type,
                     salesperson=excluded.salesperson, source_status=excluded.source_status,
                     document_status=excluded.document_status, sap_status_summary=excluded.sap_status_summary,
                     sap_open_sku_count=excluded.sap_open_sku_count, sap_attended_sku_count=excluded.sap_attended_sku_count,
                     attention_type=excluded.attention_type, updated_at=excluded.updated_at""",
                (sap_ov, text(first_get("internal_id")), text(first_get("customer_code")),
                 text(first_get("customer_name")), text(first_get("delivery_date")),
                 source_order_timestamp(first_get), text(first_get("destination")),
                 text(first_get("shipping_method")), normalize_transport(first_get("shipping_method")),
                 text(first_get("salesperson")), text(first_get("source_status")),
                 text(first_get("document_status")) if columns["document_status"] is not None else "ABIERTA",
                 sap_status_summary, open_sku_count, attended_sku_count,
                 normalize_attention(first_get("attention_type") or first_get("attention_type_2")), timestamp, timestamp),
            )
            has_shortage = False
            for source_row, current_raw, pending_sap, sap_line_status in prepared_lines:
                get = lambda field: current_raw[columns[field]] if field in columns and columns[field] is not None and columns[field] < len(current_raw) else None
                required_qty = number(get("required_qty"))
                pending_value = get("pending_qty")
                pending_qty = number(pending_value) if pending_value not in (None, "") else required_qty
                available_qty = number(get("available_qty"))
                has_shortage = has_shortage or (pending_sap and available_qty < pending_qty)
                item_code = text(get("item_code"))
                warehouse = text(get("warehouse"))
                item_key = normalized_identifier(item_code)
                warehouse_key = normalized_warehouse(warehouse)
                source_row = stable_source_row(connection, sap_ov, get("source_line"), item_code,
                                               warehouse, pending_sap, source_row, source_keys)
                connection.execute(
                    """INSERT INTO order_lines
                    (sap_ov, source_row, item_code, description, required_qty, pending_qty, available_qty,
                     unit_price, total_amount, warehouse, cost_center, article_group, sap_line_status, is_pending_sap)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(sap_ov, source_row) DO UPDATE SET
                      item_code=excluded.item_code, description=excluded.description,
                      required_qty=excluded.required_qty, pending_qty=excluded.pending_qty,
                      available_qty=excluded.available_qty, unit_price=excluded.unit_price,
                      total_amount=excluded.total_amount, warehouse=excluded.warehouse,
                      cost_center=excluded.cost_center, article_group=excluded.article_group,
                      sap_line_status=excluded.sap_line_status, is_pending_sap=excluded.is_pending_sap""",
                    # La fila física del Excel es el identificador único del
                    # detalle; el N° de Línea del reporte puede repetirse.
                    (sap_ov, source_row, item_code, text(get("description")),
                     required_qty, pending_qty, available_qty,
                     number(get("unit_price")), number(get("total_amount")), warehouse,
                     text(get("cost_center")), text(get("article_group")), sap_line_status, int(pending_sap)),
                )
                imported += int(pending_sap)
                sap_attended_rows += int(not pending_sap)
            shortage_orders += int(has_shortage)

        closed_orders_updated = 0
        for sap_ov, closed_lines in closed_grouped.items():
            existing_order = connection.execute(
                "SELECT * FROM orders WHERE sap_ov = ?", (sap_ov,)
            ).fetchone()
            _, first_raw = closed_lines[0]
            first_get = lambda field: first_raw[columns[field]] if field in columns and columns[field] is not None and columns[field] < len(first_raw) else None
            status_counts = {}
            for _, current_raw in closed_lines:
                get = lambda field: current_raw[columns[field]] if field in columns and columns[field] is not None and columns[field] < len(current_raw) else None
                status_label = text(get("sap_line_status")) or "ATENDIDO EN SAP"
                status_counts[status_label] = status_counts.get(status_label, 0) + 1
            sap_status_summary = " · ".join(
                f"{status}: {count}" for status, count in sorted(status_counts.items())
            )
            timestamp = now()
            if not existing_order:
                connection.execute(
                    """INSERT INTO orders
                       (sap_ov, internal_id, customer_code, customer_name, delivery_date,
                        source_order_date, destination, shipping_method, transport_type,
                        salesperson, source_status, document_status, sap_status_summary,
                        sap_open_sku_count, sap_attended_sku_count, attention_type,
                        app_status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 'CERRADO SAP', ?, ?)""",
                    (
                        sap_ov, text(first_get("internal_id")), text(first_get("customer_code")),
                        text(first_get("customer_name")), text(first_get("delivery_date")),
                        source_order_timestamp(first_get), text(first_get("destination")),
                        text(first_get("shipping_method")), normalize_transport(first_get("shipping_method")),
                        text(first_get("salesperson")), text(first_get("source_status")),
                        text(first_get("document_status")) or "Cerrado", sap_status_summary,
                        len(closed_lines), normalize_attention(first_get("attention_type") or first_get("attention_type_2")),
                        timestamp, timestamp,
                    ),
                )
                existing_order = connection.execute(
                    "SELECT * FROM orders WHERE sap_ov = ?", (sap_ov,)
                ).fetchone()
            else:
                connection.execute(
                    """UPDATE orders
                       SET internal_id = ?, customer_code = ?, customer_name = ?, delivery_date = ?,
                           source_order_date = ?, destination = ?, shipping_method = ?,
                           transport_type = ?, salesperson = ?, source_status = ?, document_status = ?,
                           sap_status_summary = ?, sap_open_sku_count = 0, sap_attended_sku_count = ?,
                           app_status = 'CERRADO SAP', updated_at = ?
                       WHERE sap_ov = ?""",
                    (
                        text(first_get("internal_id")), text(first_get("customer_code")),
                        text(first_get("customer_name")), text(first_get("delivery_date")),
                        source_order_timestamp(first_get), text(first_get("destination")),
                        text(first_get("shipping_method")), normalize_transport(first_get("shipping_method")),
                        text(first_get("salesperson")), text(first_get("source_status")),
                        text(first_get("document_status")) or "Cerrado", sap_status_summary,
                        len(closed_lines), timestamp, sap_ov,
                    ),
                )
            # Una OV puede traer líneas atendidas y líneas todavía abiertas.
            # El corte SAP debe cerrar únicamente las filas que reporta como atendidas.
            source_keys = {}
            closed_source_rows = []
            for source_row, current_raw in closed_lines:
                get = lambda field: current_raw[columns[field]] if field in columns and columns[field] is not None and columns[field] < len(current_raw) else None
                item_code = text(get("item_code"))
                warehouse = text(get("warehouse")) or "1"
                existing_line = connection.execute(
                    """SELECT source_row FROM order_lines
                       WHERE sap_ov = ? AND is_pending_sap = 1
                         AND item_code = ? AND warehouse = ?
                       ORDER BY source_row LIMIT 1""",
                    (sap_ov, item_code, warehouse),
                ).fetchone()
                # La tabla no tiene una columna calculada normalized_item_code;
                # la comparación principal se hace por el NP y almacén exactos.
                if existing_line:
                    stable_row = existing_line["source_row"]
                else:
                    stable_row = stable_source_row(
                        connection, sap_ov, get("source_line"), item_code,
                        warehouse, False, source_row, source_keys,
                    )
                closed_source_rows.append(stable_row)
                get = lambda field: current_raw[columns[field]] if field in columns and columns[field] is not None and columns[field] < len(current_raw) else None
                required_qty = number(get("required_qty"))
                pending_qty = number(get("pending_qty"))
                if pending_qty == 0 and required_qty > 0:
                    pending_qty = required_qty
                connection.execute(
                    """INSERT INTO order_lines
                       (sap_ov, source_row, item_code, description, required_qty, pending_qty,
                        available_qty, unit_price, total_amount, warehouse, cost_center,
                        article_group, sap_line_status, is_pending_sap)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                       ON CONFLICT(sap_ov, source_row) DO UPDATE SET
                         item_code = excluded.item_code, description = excluded.description,
                         required_qty = excluded.required_qty, pending_qty = excluded.pending_qty,
                         available_qty = excluded.available_qty, unit_price = excluded.unit_price,
                         total_amount = excluded.total_amount, warehouse = excluded.warehouse,
                         cost_center = excluded.cost_center, article_group = excluded.article_group,
                         sap_line_status = excluded.sap_line_status, is_pending_sap = 0""",
                    (
                        sap_ov, stable_row, text(get("item_code")), text(get("description")),
                        required_qty, pending_qty, number(get("available_qty")), number(get("unit_price")),
                        number(get("total_amount")), text(get("warehouse")), text(get("cost_center")),
                        text(get("article_group")), text(get("sap_line_status")) or "ATENDIDO EN SAP",
                    ),
                )
            pending_after_close = connection.execute(
                "SELECT COUNT(*) FROM order_lines WHERE sap_ov = ? AND is_pending_sap = 1",
                (sap_ov,),
            ).fetchone()[0]
            active_attentions = connection.execute(
                """SELECT * FROM attentions
                   WHERE sap_ov = ? AND app_status NOT IN ('ENTREGADO', 'CERRADO SAP')""",
                (sap_ov,),
            ).fetchall()
            for attention in active_attentions if pending_after_close == 0 else []:
                release_active_attention_stock(
                    connection, attention, "sistema-sap",
                    "El documento fue reportado como cerrado por SAP",
                    "LIBERACION_CIERRE_SAP",
                )
                connection.execute(
                    "UPDATE attentions SET app_status = 'CERRADO SAP', updated_at = ? WHERE id = ?",
                    (timestamp, attention["id"]),
                )
                write_attention_history(
                    connection, attention["id"], "CIERRE_SAP", "app_status",
                    attention["app_status"], "CERRADO SAP", "sistema-sap",
                    "Actualización del Excel: documento cerrado en SAP",
                )
            connection.execute(
                """UPDATE orders
                   SET document_status = ?, sap_status_summary = ?,
                       sap_open_sku_count = ?, sap_attended_sku_count = ?,
                       app_status = ?, updated_at = ?
                   WHERE sap_ov = ?""",
                (
                    text(first_get("document_status")) or "Cerrado",
                    sap_status_summary, pending_after_close, len(closed_lines),
                    "CERRADO SAP" if pending_after_close == 0 else "PENDIENTE",
                    timestamp, sap_ov,
                ),
            )
            write_history(
                connection, sap_ov,
                "CIERRE_SAP" if pending_after_close == 0 else "ACTUALIZACION_SAP",
                "document_status",
                existing_order["document_status"], text(first_get("document_status")) or "Cerrado",
                "sistema-sap", "Actualización del Excel",
            )
            closed_orders_updated += 1
        if not grouped and not closed_grouped:
            raise ValueError("No hay OVs de repuestos/accesorios del almacén 1 utilizables. Se conservó el corte anterior.")
        connection.execute("UPDATE orders SET source_present=0")
        for sap_ov in set(grouped) | set(closed_grouped):
            connection.execute("UPDATE orders SET source_present=1 WHERE sap_ov=?", (sap_ov,))
        inventory_conflicts = 0
        # El query consolidado usa una hoja separada llamada `stock`. Si no
        # existe, conservamos la compatibilidad con los queries que traen
        # StockDisponible junto a las OVs.
        if stock_candidates:
            inventory_candidates = stock_candidates
        if inventory_candidates:
            inventory_conflicts = sync_inventory_snapshot(
                connection, inventory_candidates, identity["filename"], identity["cutoff_at"]
            )
            if reconcile_delivered:
                reconcile_deliveries(connection, identity["cutoff_at"])
            else:
                # SAP closed documents are already included in this stock snapshot.
                connection.execute("""UPDATE stock_allocations SET reconciled_qty=consumed_qty
                    WHERE status='CONSUMIDA' AND attention_id IN
                    (SELECT id FROM attentions WHERE app_status='CERRADO SAP')""")
        for sap_ov in grouped:
            connection.execute("UPDATE orders SET source_cutoff_at=? WHERE sap_ov=?", (identity["cutoff_at"], sap_ov))
        seed_initial_attentions(connection)
        # Una carga posterior debe corregir el detalle de las atenciones que
        # todavía no empiezan. Nunca se recalculan líneas con picking o entrega
        # registrados: esas cantidades son parte de la trazabilidad operativa.
        for sap_ov in grouped:
            connection.execute(
                """DELETE FROM attention_lines
                   WHERE attention_id IN (SELECT id FROM attentions WHERE sap_ov = ? AND app_status IN ('PENDIENTE', 'ASIGNADO'))
                     AND COALESCE(picked_qty, 0) = 0 AND COALESCE(delivered_qty, 0) = 0
                     AND order_line_id IN (SELECT id FROM order_lines WHERE sap_ov = ? AND is_pending_sap = 0)""",
                (sap_ov, sap_ov),
            )
            connection.execute(
                """UPDATE attention_lines
                   SET source_row = COALESCE((SELECT source_row FROM order_lines ol WHERE ol.id = attention_lines.order_line_id), source_row),
                       item_code = COALESCE((SELECT item_code FROM order_lines ol WHERE ol.id = attention_lines.order_line_id), item_code),
                       description = COALESCE((SELECT description FROM order_lines ol WHERE ol.id = attention_lines.order_line_id), description),
                       required_qty = COALESCE((SELECT required_qty FROM order_lines ol WHERE ol.id = attention_lines.order_line_id), required_qty),
                       pending_qty = COALESCE((SELECT pending_qty FROM order_lines ol WHERE ol.id = attention_lines.order_line_id), pending_qty),
                       available_qty = COALESCE((SELECT available_qty FROM order_lines ol WHERE ol.id = attention_lines.order_line_id), available_qty),
                       warehouse = COALESCE((SELECT warehouse FROM order_lines ol WHERE ol.id = attention_lines.order_line_id), warehouse),
                       planned_qty = CASE
                           WHEN COALESCE((SELECT pending_qty FROM order_lines ol WHERE ol.id = attention_lines.order_line_id), 0) > 0
                           THEN (SELECT pending_qty FROM order_lines ol WHERE ol.id = attention_lines.order_line_id)
                           ELSE 0 END
                   WHERE attention_id IN (
                       SELECT id FROM attentions
                       WHERE sap_ov = ? AND app_status IN ('PENDIENTE', 'ASIGNADO')
                   )
                     AND COALESCE(picked_qty, 0) = 0 AND COALESCE(delivered_qty, 0) = 0""",
                (sap_ov,),
            )
            # Agrega SKU nuevos solo a atenciones aún no iniciadas.
            connection.execute("""INSERT INTO attention_lines
                (attention_id,order_line_id,planned_qty,source_row,item_code,description,required_qty,pending_qty,available_qty,warehouse)
                SELECT a.id,l.id,l.pending_qty,l.source_row,l.item_code,l.description,l.required_qty,l.pending_qty,l.available_qty,l.warehouse
                FROM attentions a JOIN order_lines l ON l.sap_ov=a.sap_ov
                WHERE a.sap_ov=? AND a.app_status IN ('PENDIENTE','ASIGNADO') AND l.is_pending_sap=1
                AND NOT EXISTS(SELECT 1 FROM attention_lines al WHERE al.attention_id=a.id AND al.order_line_id=l.id)""", (sap_ov,))
            for line in connection.execute("SELECT * FROM order_lines WHERE sap_ov=? AND is_pending_sap=1", (sap_ov,)).fetchall():
                remaining = remaining_line_quantity(connection, sap_ov, line)
                connection.execute("""UPDATE attention_lines SET planned_qty=? WHERE order_line_id=?
                    AND attention_id IN (SELECT id FROM attentions WHERE sap_ov=? AND app_status IN ('PENDIENTE','ASIGNADO'))""", (remaining, line["id"], sap_ov))
        result = {
            "orders": len(grouped), "lines": imported, "source_rows": source_rows,
            "skipped_rows": skipped_rows, "stock_shortage_orders": shortage_orders,
            "sap_attended_rows": sap_attended_rows, "excluded_group_rows": excluded_group_rows,
            "excluded_warehouse_rows": excluded_warehouse_rows, "excluded_document_rows": excluded_document_rows,
            "closed_orders_updated": closed_orders_updated,
            "inventory_skus": len(inventory_candidates), "inventory_conflicts": inventory_conflicts,
            "cutoff_at": identity["cutoff_at"], "stock_updated": bool(inventory_candidates),
            "stock_sheet": stock_sheet,
        }
        record_import(connection, identity, result)
    # read_only=True mantiene el ZIP abierto hasta cerrar explícitamente el
    # libro. Es indispensable en Windows para poder borrar el temporal subido.
    workbook.close()
    return result


def import_uploaded_excel(content, filename, username, role, cutoff_at=None, reconcile_delivered=True):
    """Imports an .xlsx received by an administrator without retaining the file."""
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede actualizar las OVs desde Excel")
    filename = Path(filename or "exportacion.xlsx").name
    if not filename.lower().endswith(".xlsx"):
        raise ValueError("Solo se permiten archivos .xlsx exportados desde el query")
    if not content:
        raise ValueError("El archivo está vacío")
    if len(content) > MAX_IMPORT_BYTES:
        raise ValueError("El archivo supera el límite de 50 MB")
    temporary = tempfile.NamedTemporaryFile(prefix="triton-import-", suffix=".xlsx", delete=False)
    try:
        temporary.write(content)
        temporary.close()
        result = import_excel(Path(temporary.name), reset=False, cutoff_at=cutoff_at,
                              username=username, source_filename=filename, reconcile_delivered=reconcile_delivered)
        return {**result, "message": f"Excel actualizado por {username}"}
    finally:
        try:
            temporary.close()
        except Exception:
            pass
        Path(temporary.name).unlink(missing_ok=True)


IMPORTATION_ALIASES = {
    "quantity": {"cantidad", "cant", "cantidad solicitada", "cantidad requerida", "cant requerida", "quantity"},
    "ov": {"ov", "orden de venta"},
    "bl": {"guia de importacion", "guia importacion", "bl", "awb"},
    "transport": {"modo de transporte", "medio de transporte", "transporte"},
    "ip": {"pedido triton", "ip"},
    "oc": {"orden de compra", "oc"},
    "item_code": {
        "codigo", "código", "cod articulo", "cod artículo", "codigo articulo",
        "código artículo", "número de artículo", "numero de articulo", "item code",
    },
    "source_date": {
        "fecha de solicitud de imp ov", "fecha solicitud de imp ov",
        "fecha confirmada triton", "fecha triton estimada", "fecha de pedido",
    },
}


def find_importation_column(headers, field):
    aliases = {clean_header(alias) for alias in IMPORTATION_ALIASES[field]}
    for header, index in headers.items():
        if header in aliases:
            return index
    return None


def identifier_text(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return text(value)


def normalized_identifier(value):
    """Compara SKU aunque Excel los traiga con espacios, guiones o /."""
    return "".join(character for character in identifier_text(value).upper() if character.isalnum())


def normalized_warehouse(value):
    if not identifier_text(value):
        return "1"
    if is_warehouse_one(value):
        return "1"
    return normalized_identifier(value)


def conservative_stock_quantity(values):
    """Evita duplicar el stock repetido por cada OV en el reporte SAP."""
    usable = [max(0, number(value)) for value in values]
    return min(usable) if usable else 0


def bootstrap_inventory_from_order_lines(connection):
    """Crea el primer inventario sin alterar snapshots ya controlados por el WMS."""
    candidates = {}
    for line in connection.execute(
        """SELECT item_code, warehouse, available_qty FROM order_lines
           WHERE is_pending_sap = 1 AND COALESCE(item_code, '') <> ''"""
    ).fetchall():
        item_key = normalized_identifier(line["item_code"])
        warehouse_key = normalized_warehouse(line["warehouse"])
        if not item_key:
            continue
        candidate = candidates.setdefault(
            (item_key, warehouse_key),
            {"item_code": identifier_text(line["item_code"]), "warehouse": identifier_text(line["warehouse"]), "values": []},
        )
        candidate["values"].append(line["available_qty"])
    timestamp = now()
    for (item_key, warehouse_key), candidate in candidates.items():
        connection.execute(
            """INSERT OR IGNORE INTO inventory_stock
               (item_key, warehouse_key, item_code, warehouse, snapshot_qty,
                snapshot_day, snapshot_at, source_file, is_current, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'BASE EXISTENTE', 1, ?)""",
            (
                item_key, warehouse_key, candidate["item_code"], candidate["warehouse"] or warehouse_key,
                conservative_stock_quantity(candidate["values"]), timestamp[:10], timestamp, timestamp,
            ),
        )


def sync_inventory_snapshot(connection, candidates, source_file, timestamp):
    """Sustituye el saldo oficial a la hora del corte; no borra movimientos."""
    connection.execute("UPDATE inventory_stock SET is_current = 0")
    conflicts = 0
    for (item_key, warehouse_key), candidate in candidates.items():
        values = {max(0, number(value)) for value in candidate["values"]}
        conflicts += int(len(values) > 1)
        connection.execute(
            """INSERT INTO inventory_stock
               (item_key, warehouse_key, item_code, warehouse, snapshot_qty,
                snapshot_day, snapshot_at, source_file, is_current, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
               ON CONFLICT(item_key, warehouse_key) DO UPDATE SET
                 item_code=excluded.item_code, warehouse=excluded.warehouse,
                 snapshot_qty=excluded.snapshot_qty, snapshot_day=excluded.snapshot_day,
                 snapshot_at=excluded.snapshot_at, source_file=excluded.source_file,
                 is_current=1, updated_at=excluded.updated_at""",
            (item_key, warehouse_key, candidate["item_code"],
             candidate["warehouse"] or warehouse_key, conservative_stock_quantity(values),
             timestamp[:10], timestamp, source_file, now()),
        )
    return conflicts



def classify_order_line_origin(connection, sap_ov, item_code):
    item_key = normalized_identifier(item_code)
    categories = []
    for ref in connection.execute(
        "SELECT item_code, transport_type FROM order_importation_refs WHERE sap_ov = ?",
        (sap_ov,),
    ).fetchall():
        if item_key and normalized_identifier(ref["item_code"]) == item_key:
            category = transport_line_category(ref["transport_type"])
            if category not in categories:
                categories.append(category)
    if "AEREO" in categories:
        return "AEREO"
    if "MARITIMO" in categories:
        return "MARITIMO"
    return "STOCK"


def received_air_quantity(connection, sap_ov, item_code):
    target_ov = normalized_identifier(sap_ov)
    target_item = normalized_identifier(item_code)
    total = 0.0
    rows = connection.execute(
        """SELECT l.ov_number, l.np_code, l.received_qty
           FROM reception_lines l
           JOIN reception_shipments s ON s.id = l.shipment_id
           WHERE COALESCE(l.received_qty, 0) > 0
             AND upper(COALESCE(s.transport_type, '')) IN ('AEREO', 'COURIER')"""
    ).fetchall()
    for row in rows:
        if normalized_identifier(row["ov_number"]) == target_ov and normalized_identifier(row["np_code"]) == target_item:
            total += max(0, number(row["received_qty"]))
    return total


def ensure_inventory_item(connection, item_code, warehouse):
    item_key = normalized_identifier(item_code)
    warehouse_key = normalized_warehouse(warehouse)
    row = connection.execute(
        "SELECT * FROM inventory_stock WHERE item_key = ? AND warehouse_key = ?",
        (item_key, warehouse_key),
    ).fetchone()
    if row:
        return row
    values = []
    display_code = identifier_text(item_code)
    display_warehouse = identifier_text(warehouse) or warehouse_key
    for line in connection.execute(
        "SELECT item_code, warehouse, available_qty FROM order_lines WHERE is_pending_sap = 1"
    ).fetchall():
        if normalized_identifier(line["item_code"]) == item_key and normalized_warehouse(line["warehouse"]) == warehouse_key:
            values.append(line["available_qty"])
    timestamp = now()
    connection.execute(
        """INSERT INTO inventory_stock
           (item_key, warehouse_key, item_code, warehouse, snapshot_qty,
            snapshot_day, snapshot_at, source_file, is_current, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'BASE EXISTENTE', 1, ?)""",
        (
            item_key, warehouse_key, display_code, display_warehouse,
            conservative_stock_quantity(values), timestamp[:10], timestamp, timestamp,
        ),
    )
    return connection.execute(
        "SELECT * FROM inventory_stock WHERE item_key = ? AND warehouse_key = ?",
        (item_key, warehouse_key),
    ).fetchone()


def inventory_pool_status(connection, sap_ov, item_code, warehouse, origin_type=None):
    origin_type = origin_type or classify_order_line_origin(connection, sap_ov, item_code)
    inventory = ensure_inventory_item(connection, item_code, warehouse)
    return operational_balance(connection, inventory, sap_ov, origin_type)


def aerial_reservation_summary(connection, item_code):
    """Informa las OVs aéreas abiertas que reservan un SKU, sin sumar stock."""
    key = normalized_identifier(item_code)
    by_ov = {}
    rows = connection.execute(
        """SELECT sap_ov, item_code, quantity, transport_type
           FROM order_importation_refs
           WHERE item_key = ? OR item_key IS NULL""", (key,)
    ).fetchall()
    for ref in rows:
        if normalized_identifier(ref["item_code"]) != key:
            continue
        if transport_line_category(ref["transport_type"]) != "AEREO":
            continue
        ov = identifier_text(ref["sap_ov"])
        pending = sum(
            max(0, number(line["pending_qty"]))
            for line in connection.execute(
                "SELECT item_code, pending_qty FROM order_lines WHERE sap_ov = ? AND is_pending_sap = 1",
                (ref["sap_ov"],),
            ).fetchall()
            if normalized_identifier(line["item_code"]) == key
        )
        if not ov or pending <= 0:
            continue
        amount = pending if ref["quantity"] is None else min(max(0, number(ref["quantity"])), pending)
        if amount > 0:
            by_ov[ov] = by_ov.get(ov, 0) + amount
    return {"count": len(by_ov), "quantity": sum(by_ov.values()), "ovs": sorted(by_ov)}



def inventory_line_payload(connection, sap_ov, line, attention_line_id=None, origin_type=None):
    item_code = identifier_text(line.get("item_code") if isinstance(line, dict) else line["item_code"])
    warehouse = identifier_text(line.get("warehouse") if isinstance(line, dict) else line["warehouse"]) or "1"
    origin_type = origin_type or classify_order_line_origin(connection, sap_ov, item_code)
    status = inventory_pool_status(connection, sap_ov, item_code, warehouse, origin_type)
    aerial = aerial_reservation_summary(connection, item_code)
    item_key = normalized_identifier(item_code)
    warehouse_key = normalized_warehouse(warehouse)
    reserved_for_ov = connection.execute(
        """SELECT COALESCE(SUM(reserved_qty), 0) FROM stock_allocations
           WHERE sap_ov = ? AND item_key = ? AND warehouse_key = ? AND status = 'ACTIVA'""",
        (sap_ov, item_key, warehouse_key),
    ).fetchone()[0]
    reserved_for_line = 0
    allocation_status = "SIN RESERVA"
    if attention_line_id:
        allocation = connection.execute(
            "SELECT reserved_qty, consumed_qty, status FROM stock_allocations WHERE attention_line_id = ?",
            (attention_line_id,),
        ).fetchone()
        if allocation:
            reserved_for_line = number(allocation["reserved_qty"])
            allocation_status = allocation["status"]
    return {
        "origin_type": origin_type,
        "stock_source_qty": status["source_total"],
        "stock_reserved_qty": status["reserved_total"],
        "stock_consumed_qty": status["consumed_total"],
        "stock_free_qty": status["free_qty"],
        "stock_reserved_for_ov": number(reserved_for_ov),
        "stock_reserved_for_line": reserved_for_line,
        "stock_allocation_status": allocation_status,
        "stock_committed_other_qty": status["committed_other_qty"],
        "stock_committed_for_ov": status["committed_for_ov"],
        "stock_aerial_ov_count": aerial["count"],
        "stock_aerial_reserved_qty": aerial["quantity"],
        "stock_aerial_ovs": aerial["ovs"],
        "stock_cutoff_at": status["snapshot_at"],
        "stock_reason": status["stock_reason"],
        "stock_deficit": status["stock_deficit"],
    }


def write_stock_movement(connection, allocation, movement_type, quantity, username, reason=""):
    connection.execute(
        """INSERT INTO stock_movements
           (allocation_id, attention_id, attention_line_id, sap_ov, item_key, item_code,
            warehouse_key, warehouse, pool_type, movement_type, quantity, username, reason, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            allocation["id"], allocation["attention_id"], allocation["attention_line_id"], allocation["sap_ov"],
            allocation["item_key"], allocation["item_code"], allocation["warehouse_key"], allocation["warehouse"],
            allocation["pool_type"], movement_type, quantity, username, reason, now(),
        ),
    )


def import_importation_workbook(path, username, role, connection=None, source_filename=None):
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede cargar el Excel de Importaciones")
    workbook = load_workbook(path, data_only=True, read_only=True)
    try:
        imported_rows = 0
        skipped_rows = 0
        valid_sheets = []
        records = []
        for worksheet in workbook.worksheets:
            header_row = None
            columns = None
            for row_number, candidate in enumerate(
                worksheet.iter_rows(min_row=1, max_row=min(worksheet.max_row, 20), values_only=True), 1
            ):
                headers = {
                    clean_header(value): index
                    for index, value in enumerate(candidate)
                    if value is not None
                }
                candidate_columns = {
                    field: find_importation_column(headers, field)
                    for field in IMPORTATION_ALIASES
                }
                if candidate_columns["ov"] is not None and candidate_columns["transport"] is not None:
                    header_row = row_number
                    columns = candidate_columns
                    break
            if header_row is None:
                continue
            valid_sheets.append(worksheet.title)
            for source_row, row in enumerate(
                worksheet.iter_rows(min_row=header_row + 1, values_only=True), header_row + 1
            ):
                get = lambda field: row[columns[field]] if columns[field] is not None and columns[field] < len(row) else None
                sap_ov = identifier_text(get("ov"))
                if not sap_ov or sap_ov.upper() in {"S/N", "N/A", "NA", "NONE"}:
                    skipped_rows += 1
                    continue
                records.append({
                    "sap_ov": sap_ov,
                    "bl_awb": identifier_text(get("bl")),
                    "transport_type": normalize_transport(get("transport")),
                    "ip_reference": identifier_text(get("ip")),
                    "oc_number": identifier_text(get("oc")),
                    "item_code": identifier_text(get("item_code")),
                    "quantity": number(get("quantity")) if get("quantity") not in (None, "") else None,
                    "source_sheet": worksheet.title,
                    "source_row": source_row,
                    "source_date": text(get("source_date")),
                })
                imported_rows += 1
        if not valid_sheets:
            raise ValueError("No encontré hojas con OV y MODO DE TRANSPORTE en las primeras 20 filas")
        with (nullcontext(connection) if connection is not None else db()) as connection:
            timestamp = now()
            previous_transports = {
                row["sap_ov"]: row["transport_type"]
                for row in connection.execute(
                    "SELECT sap_ov, transport_type FROM orders WHERE COALESCE(transport_type, '') <> 'SIN DEFINIR'"
                )
            }
            # El archivo representa el estado vigente de Importaciones. Se
            # reemplaza el mapa para no dejar bloqueadas OVs que ya salieron
            # del reporte más reciente.
            connection.execute("DELETE FROM order_importation_refs")
            connection.execute(
                "UPDATE orders SET transport_type = 'SIN DEFINIR', updated_at = ? WHERE COALESCE(transport_type, '') <> 'SIN DEFINIR'",
                (timestamp,),
            )
            for record in records:
                connection.execute(
                    """INSERT INTO order_importation_refs
                       (sap_ov, bl_awb, transport_type, ip_reference, oc_number,
                        item_code, source_sheet, source_row, source_date, source_file, updated_at, quantity, item_key)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(sap_ov, bl_awb, transport_type, ip_reference, oc_number, source_sheet, source_row)
                       DO UPDATE SET source_date=excluded.source_date,
                                     item_code=excluded.item_code, quantity=excluded.quantity, item_key=excluded.item_key,
                                     source_file=excluded.source_file,
                                     updated_at=excluded.updated_at""",
                    (
                        record["sap_ov"], record["bl_awb"], record["transport_type"],
                        record["ip_reference"], record["oc_number"], record["item_code"], record["source_sheet"],
                        record["source_row"], record["source_date"], source_filename or str(path), timestamp,
                        record["quantity"], normalized_identifier(record["item_code"]),
                    ),
                )
            for sap_ov in {record["sap_ov"] for record in records}:
                source_date = connection.execute(
                    """SELECT source_date FROM order_importation_refs
                       WHERE sap_ov = ? AND COALESCE(source_date, '') <> ''
                       ORDER BY source_date ASC LIMIT 1""",
                    (sap_ov,),
                ).fetchone()
                context = picking_importation_context(connection, sap_ov)
                current = connection.execute(
                    "SELECT transport_type, source_order_date FROM orders WHERE sap_ov = ?",
                    (sap_ov,),
                ).fetchone()
                connection.execute(
                    """UPDATE orders
                       SET transport_type = ?,
                           updated_at = ?
                       WHERE sap_ov = ?""",
                    (
                        context["transport_type"],
                        timestamp,
                        sap_ov,
                    ),
                )
                old_transport = previous_transports.get(sap_ov, "SIN DEFINIR")
                if current and old_transport != context["transport_type"]:
                    write_history(
                        connection,
                        sap_ov,
                        "IMPORTACIÓN EXCEL",
                        "transport_type",
                        old_transport,
                        context["transport_type"],
                        username,
                        "Actualización desde IMPORTACIÓN DE REPUESTOS",
                    )
            for sap_ov, old_transport in previous_transports.items():
                if not connection.execute("SELECT 1 FROM order_importation_refs WHERE sap_ov = ? LIMIT 1", (sap_ov,)).fetchone():
                    write_history(
                        connection,
                        sap_ov,
                        "IMPORTACIÓN EXCEL",
                        "transport_type",
                        old_transport,
                        "SIN DEFINIR",
                        username,
                        "OV ya no aparece en IMPORTACIÓN DE REPUESTOS",
                    )
        return {
            "filename": str(path),
            "sheets": valid_sheets,
            "rows": imported_rows,
            "skipped_rows": skipped_rows,
            "ovs": len({record["sap_ov"] for record in records}),
        }
    finally:
        workbook.close()


def import_daily_excel(content, filename, source_type, cutoff_at, username, role, reconcile_delivered=True):
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede cargar cortes Excel")
    filename = Path(filename or "datos.xlsx").name
    if not filename.lower().endswith(".xlsx") or not content:
        raise ValueError("Selecciona un archivo Excel .xlsx con datos")
    if len(content) > MAX_IMPORT_BYTES:
        raise ValueError("El archivo supera el límite de 50 MB")
    if source_type == "dispatch":
        return import_uploaded_excel(content, filename, username, role, cutoff_at, reconcile_delivered)
    identity = import_identity(content, source_type, cutoff_at, filename, username)
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        duplicate = check_import(connection, identity)
        if duplicate:
            return duplicate
        if source_type == "importation":
            workbook = load_workbook(BytesIO(content), data_only=True, read_only=True)
            try:
                reception_result = import_reception_workbook(connection, workbook, filename, username, role)
            finally:
                workbook.close()
            refs_result = import_importation_workbook(BytesIO(content), username, role, connection, filename)
            result = {**reception_result, "ovs": refs_result["ovs"], "rows": refs_result["rows"],
                      "stock_updated": False, "message": "Recepciones y compromisos actualizados; el saldo de stock no aumentó."}
        else:
            result = import_reception_accounting_excel_bytes(connection, content, filename, username, role)
            result["stock_updated"] = False
        result["cutoff_at"] = identity["cutoff_at"]
        record_import(connection, identity, result)
        return result


def import_importation_uploaded_excel(content, filename, username, role):
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede cargar el Excel de Importaciones")
    filename = Path(filename or "IMPORTACION DE REPUESTOS.xlsx").name
    if not filename.lower().endswith(".xlsx"):
        raise ValueError("El archivo de Importaciones debe ser .xlsx")
    if not content:
        raise ValueError("El archivo de Importaciones está vacío")
    if len(content) > MAX_IMPORT_BYTES:
        raise ValueError("El archivo supera el límite de 50 MB")
    temporary = tempfile.NamedTemporaryFile(prefix="triton-importation-", suffix=".xlsx", delete=False)
    try:
        temporary.write(content)
        temporary.close()
        return import_importation_workbook(Path(temporary.name), username, role)
    finally:
        try:
            temporary.close()
        except Exception:
            pass
        Path(temporary.name).unlink(missing_ok=True)


def picking_importation_context(connection, sap_ov):
    refs = connection.execute(
        """SELECT * FROM order_importation_refs
           WHERE sap_ov = ? ORDER BY source_date ASC, id ASC""",
        (sap_ov,),
    ).fetchall()
    lines = connection.execute(
        """SELECT source_row, item_code FROM order_lines
           WHERE sap_ov = ? AND is_pending_sap = 1 ORDER BY source_row""",
        (sap_ov,),
    ).fetchall()
    importation_map_loaded = bool(connection.execute(
        "SELECT 1 FROM order_importation_refs LIMIT 1"
    ).fetchone())
    refs_by_item = {}
    for ref in refs:
        item_key = normalized_identifier(ref["item_code"])
        if item_key:
            refs_by_item.setdefault(item_key, []).append(ref)

    line_categories = []
    for line in lines:
        item_key = normalized_identifier(line["item_code"])
        matching_refs = refs_by_item.get(item_key, [])
        matching_categories = [transport_line_category(ref["transport_type"]) for ref in matching_refs]
        if matching_refs:
            if "AEREO" in matching_categories:
                classification = "AEREO"
            elif "MARITIMO" in matching_categories:
                classification = "MARITIMO"
            else:
                classification = "STOCK"
        elif importation_map_loaded:
            # La ausencia del SKU en el archivo de Importaciones significa
            # que la línea pertenece a stock y no a una llegada importada.
            classification = "STOCK"
        else:
            classification = "SIN DEFINIR"
        matched_bls = []
        matched_transports = []
        for ref in matching_refs:
            bl = identifier_text(ref["bl_awb"])
            if bl and bl not in matched_bls:
                matched_bls.append(bl)
            transport = transport_line_category(ref["transport_type"])
            if transport not in matched_transports:
                matched_transports.append(transport)
        line_categories.append({
            "source_row": line["source_row"],
            "item_code": identifier_text(line["item_code"]),
            "classification": classification,
            "transport_type": ", ".join(matched_transports) if matched_transports else classification,
            "bl_awb": ", ".join(matched_bls),
            "importation_match": bool(matching_refs),
        })

    present_line_categories = [item["classification"] for item in line_categories if item["classification"] != "SIN DEFINIR"]
    if not refs:
        return {
            "transport_type": summarize_line_categories(present_line_categories) if present_line_categories else "SIN DEFINIR",
            "bl_awb": "", "reception_status": "NO IDENTIFICADA",
            "picking_blocked": False, "picking_block_reason": "",
            "line_categories": line_categories,
        }
    transports = []
    bls = []
    pending_bls = []
    pending_item_keys = {
        normalized_identifier(line["item_code"])
        for line in lines if normalized_identifier(line["item_code"])
    }
    for ref in refs:
        transport = normalize_transport(ref["transport_type"])
        if transport not in transports:
            transports.append(transport)
        bl = str(ref["bl_awb"] or "").strip()
        if bl and bl not in bls:
            bls.append(bl)
        # Una OV puede contener referencias históricas o mezclar stock y aéreo.
        # Solo una referencia aérea del SKU todavía pendiente puede bloquear.
        ref_item_key = normalized_identifier(ref["item_code"])
        if not is_air_transport(transport) or not ref_item_key or ref_item_key not in pending_item_keys:
            continue
        if not bl or bl.upper() in {"S/N", "N/A", "NONE"}:
            pending_bls.append("BL sin identificar")
            continue
        shipment = connection.execute(
            "SELECT app_status FROM reception_shipments WHERE bl_awb = ?",
            (bl,),
        ).fetchone()
        if not shipment or shipment["app_status"] not in {"SOLICITUD TRANSFERENCIA", "CERRADO"}:
            pending_bls.append(bl)
    transport_summary = summarize_line_categories(present_line_categories)
    if transport_summary == "SIN DEFINIR":
        transport_summary = summarize_line_categories([transport_line_category(transport) for transport in transports])
    actionable_non_air = any(
        item["classification"] in {"STOCK", "MARITIMO"} for item in line_categories
    )
    if pending_bls and not actionable_non_air:
        reason = "OV AÉREA bloqueada: pendiente recepción de " + ", ".join(pending_bls[:4])
        if len(pending_bls) > 4:
            reason += f" (+{len(pending_bls) - 4})"
        return {
            "transport_type": transport_summary,
            "bl_awb": ", ".join(bls),
            "reception_status": "PENDIENTE RECEPCIÓN",
            "picking_blocked": True,
            "picking_block_reason": reason,
            "line_categories": line_categories,
        }
    return {
        "transport_type": transport_summary,
        "bl_awb": ", ".join(bls),
        "reception_status": (
            "PENDIENTE PARCIAL" if pending_bls else
            "RECEPCIÓN LIBERADA" if any(is_air_transport(transport) for transport in transports) else
            "NO REQUERIDA"
        ),
        "picking_blocked": False,
        "picking_block_reason": (
            "SKU aéreo pendiente de recepción: " + ", ".join(pending_bls[:4])
            if pending_bls else ""
        ),
        "line_categories": line_categories,
    }


def seed_initial_attentions(connection):
    """Creates Atención 1 for imported OVs without changing existing attentions."""
    orders = connection.execute("SELECT * FROM orders ORDER BY sap_ov").fetchall()
    for order in orders:
        exists = connection.execute("SELECT 1 FROM attentions WHERE sap_ov = ? LIMIT 1", (order["sap_ov"],)).fetchone()
        if exists:
            continue
        lines = connection.execute(
            """SELECT id, source_row, item_code, description, required_qty, pending_qty,
                      available_qty, warehouse
               FROM order_lines WHERE sap_ov = ? AND is_pending_sap = 1 ORDER BY source_row""",
            (order["sap_ov"],),
        ).fetchall()
        if not lines:
            continue
        timestamp = now()
        cursor = connection.execute(
            """INSERT INTO attentions
               (sap_ov, sequence_no, attention_type, app_status, current_picker, current_guide, created_at, updated_at)
               VALUES (?, 1, ?, 'PENDIENTE', NULL, NULL, ?, ?)""",
            (order["sap_ov"], order["attention_type"], timestamp, timestamp),
        )
        attention_id = cursor.lastrowid
        for line in lines:
            connection.execute(
                """INSERT INTO attention_lines
                   (attention_id, order_line_id, planned_qty, source_row, item_code, description,
                    required_qty, pending_qty, available_qty, warehouse)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (attention_id, line["id"], max(0, line["pending_qty"]), line["source_row"],
                 line["item_code"], line["description"], line["required_qty"], line["pending_qty"],
                 line["available_qty"], line["warehouse"]),
            )
        connection.execute(
            "INSERT INTO attention_history (attention_id, event_type, field_name, old_value, new_value, username, created_at) VALUES (?, 'CREACION', 'attention', NULL, 'Atención 1', 'sistema', ?)",
            (attention_id, timestamp),
        )


def attention_payload(connection, attention_id):
    attention = connection.execute("SELECT * FROM attentions WHERE id = ?", (attention_id,)).fetchone()
    if not attention:
        return None
    result = row_to_dict(attention)
    result["lines"] = [row_to_dict(row) for row in connection.execute(
        """SELECT al.id, al.attention_id, al.order_line_id, al.planned_qty, al.picked_qty,
                  al.delivered_qty, COALESCE(al.source_row, ol.source_row) AS source_row,
                  COALESCE(al.item_code, ol.item_code) AS item_code,
                  COALESCE(al.description, ol.description) AS description,
                  COALESCE(al.required_qty, ol.required_qty) AS required_qty,
                  COALESCE(al.pending_qty, ol.pending_qty) AS pending_qty,
                  COALESCE(al.available_qty, ol.available_qty) AS available_qty,
                  COALESCE(al.warehouse, ol.warehouse) AS warehouse
           FROM attention_lines al LEFT JOIN order_lines ol ON ol.id = al.order_line_id
           WHERE al.attention_id = ? ORDER BY source_row""", (attention_id,)
    )]
    for line in result["lines"]:
        line.update(inventory_line_payload(connection, result["sap_ov"], line, line["id"]))
        if advanced_lots_enabled():
            line.update(line_lot_tracking(connection, line["id"]))
            line["available_lots"] = available_lots_for_line(connection, line["id"])
    calculated = calculated_attention_type(result["lines"])
    if calculated:
        result["attention_type"] = calculated
    result["history"] = [row_to_dict(row) for row in connection.execute(
        "SELECT * FROM attention_history WHERE attention_id = ? ORDER BY id DESC", (attention_id,)
    )]
    result["assignments"] = [row_to_dict(row) for row in connection.execute(
        "SELECT * FROM attention_assignments WHERE attention_id = ? ORDER BY id DESC", (attention_id,)
    )]
    return result


def calculated_attention_type(lines):
    """Derive COMPLETA/PARCIAL from picked quantities, not a manual selector."""
    def value(line, field):
        return line.get(field) if isinstance(line, dict) else line[field]

    if not lines or not any(number(value(line, "picked_qty")) > 0 for line in lines):
        return None
    return "COMPLETA" if all(
        abs(number(value(line, "picked_qty")) - number(value(line, "planned_qty"))) < 0.000001
        for line in lines
    ) else "PARCIAL"


def list_attentions(connection, sap_ov):
    return [attention_payload(connection, row["id"]) for row in connection.execute(
        "SELECT id FROM attentions WHERE sap_ov = ? ORDER BY sequence_no", (sap_ov,)
    )]


def active_attention_id(connection, sap_ov):
    row = connection.execute(
        "SELECT id FROM attentions WHERE sap_ov = ? AND app_status NOT IN ('ENTREGADO', 'CERRADO SAP') ORDER BY sequence_no DESC LIMIT 1",
        (sap_ov,),
    ).fetchone()
    return row["id"] if row else None


def create_attention(sap_ov, username, role):
    if role != "ADMINISTRADOR":
        raise PermissionError("No tienes permiso para crear una atención")
    with db() as connection:
        order = connection.execute("SELECT * FROM orders WHERE sap_ov = ?", (sap_ov,)).fetchone()
        if not order:
            raise ValueError("OV no encontrada")
        active = connection.execute(
            "SELECT id FROM attentions WHERE sap_ov = ? AND app_status NOT IN ('ENTREGADO', 'CERRADO SAP') LIMIT 1", (sap_ov,)
        ).fetchone()
        if active:
            raise ValueError("La OV ya tiene una atención pendiente")
        lines = connection.execute(
            """SELECT id, source_row, item_code, description, required_qty, pending_qty,
                      available_qty, warehouse
               FROM order_lines WHERE sap_ov = ? AND is_pending_sap = 1 ORDER BY source_row""",
            (sap_ov,),
        ).fetchall()
        lines = [(line, remaining_line_quantity(connection, sap_ov, line)) for line in lines]
        lines = [(line, remaining) for line, remaining in lines if remaining > 0]
        if not lines:
            raise ValueError("Esta OV no tiene saldo pendiente después de las entregas locales; espera el siguiente corte SAP")
        sequence = connection.execute("SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM attentions WHERE sap_ov = ?", (sap_ov,)).fetchone()[0]
        timestamp = now()
        cursor = connection.execute(
            "INSERT INTO attentions (sap_ov, sequence_no, attention_type, app_status, created_at, updated_at) VALUES (?, ?, ?, 'PENDIENTE', ?, ?)",
            (sap_ov, sequence, order["attention_type"], timestamp, timestamp),
        )
        attention_id = cursor.lastrowid
        for line, remaining in lines:
            connection.execute(
                """INSERT INTO attention_lines
                   (attention_id, order_line_id, planned_qty, source_row, item_code, description,
                    required_qty, pending_qty, available_qty, warehouse)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (attention_id, line["id"], remaining, line["source_row"],
                 line["item_code"], line["description"], line["required_qty"], line["pending_qty"],
                 line["available_qty"], line["warehouse"]),
            )
        connection.execute(
            "INSERT INTO attention_history (attention_id, event_type, field_name, old_value, new_value, username, created_at) VALUES (?, 'CREACION', 'attention', NULL, ?, ?, ?)",
            (attention_id, f"Atención {sequence}", username, timestamp),
        )
        connection.execute(
            "UPDATE orders SET app_status = 'PENDIENTE', current_picker = NULL, current_guide = NULL, updated_at = ? WHERE sap_ov = ?",
            (timestamp, sap_ov),
        )
        return attention_payload(connection, attention_id)


def change_attention_status(attention_id, new_status, username, role):
    if new_status not in STATUS_INDEX:
        raise ValueError("Estado no válido")
    with db() as connection:
        # Serializa reservas y consumos para que dos pickers no puedan tomar
        # simultáneamente la misma unidad del stock global.
        connection.execute("BEGIN IMMEDIATE")
        attention = connection.execute("SELECT * FROM attentions WHERE id = ?", (attention_id,)).fetchone()
        if not attention:
            raise ValueError("Atención no encontrada")
        if attention["app_status"] == "CERRADO SAP":
            raise PermissionError("La OV está cerrada en SAP y no puede reabrirse desde el WMS")
        old_status = attention["app_status"]
        if old_status == new_status:
            return attention_payload(connection, attention_id)
        old_index = STATUS_INDEX[old_status]
        new_index = STATUS_INDEX[new_status]
        if new_status == "EN PICKING":
            order = connection.execute("SELECT source_present FROM orders WHERE sap_ov=?", (attention["sap_ov"],)).fetchone()
            if order and not order["source_present"]:
                raise ValueError("La OV no figura en el último corte SAP. Actualiza el Excel antes de iniciar.")
            importation = picking_importation_context(connection, attention["sap_ov"])
            if importation["picking_blocked"]:
                raise PermissionError(importation["picking_block_reason"] + ". Completa Recepción y valida el saldo del corte Excel.")
        if new_index < old_index:
            if role != "ADMINISTRADOR":
                raise PermissionError("Solo el administrador puede retroceder estados")
            raise PermissionError("Usa Corrección administrativa para retroceder sin desordenar el stock")
        if role != "ADMINISTRADOR":
            if role in PICKER_ROLES and new_status in {"EN PICKING", "PICKING FINALIZADO"}:
                if not attention["current_picker"] or not same_username(username, attention["current_picker"]):
                    raise PermissionError("Solo el picker asignado puede cambiar el estado de picking")
            elif role in GUIDE_ROLES and new_status in {"EN GUIADO", "GUIADO FINALIZADO", "ENTREGADO"}:
                if not attention["current_guide"] or not same_username(username, attention["current_guide"]):
                    raise PermissionError("Solo el guiador/entregador asignado puede cambiar el estado de guiado o entrega")
            else:
                raise PermissionError("Este usuario no puede controlar esta etapa")
        if new_index > old_index + 1 and role != "ADMINISTRADOR":
            raise PermissionError("El flujo debe avanzar paso a paso")
        if new_status == "PICKING FINALIZADO":
            validate_picking_completion(connection, attention)
            consume_attention_inventory(connection, attention, username)
        if new_status == "ENTREGADO":
            validate_delivery_completion(connection, attention)
            record_lot_delivery(connection, attention_id, username)
        # Al comenzar cada tramo, la aplicación propone cantidades para que el
        # responsable solo tenga que corregir excepciones. No se vuelve a
        # aplicar fuera de la transición inicial, por lo que nunca sobreescribe
        # una cantidad ya registrada manualmente.
        if old_status == "ASIGNADO" and new_status == "EN PICKING":
            prefill_picking_quantities(connection, attention, username)
        if old_status == "POR GUIAR" and new_status == "EN GUIADO":
            prefill_delivery_quantities(connection, attention, username)
        timestamp = now()
        calculated_type = calculated_attention_type(attention_lines(connection, attention_id)) if new_status == "PICKING FINALIZADO" else None
        if calculated_type:
            connection.execute(
                "UPDATE attentions SET app_status = ?, attention_type = ?, updated_at = ? WHERE id = ?",
                (new_status, calculated_type, timestamp, attention_id),
            )
            connection.execute(
                "UPDATE orders SET attention_type = ?, updated_at = ? WHERE sap_ov = ?",
                (calculated_type, timestamp, attention["sap_ov"]),
            )
            write_attention_history(
                connection, attention_id, "CALCULO_AUTOMATICO", "attention_type",
                attention["attention_type"], calculated_type, "sistema",
                "Tipo calculado por cantidades recogidas al finalizar picking",
            )
        else:
            connection.execute("UPDATE attentions SET app_status = ?, updated_at = ? WHERE id = ?", (new_status, timestamp, attention_id))
        connection.execute(
            "UPDATE orders SET app_status = ?, updated_at = ? WHERE sap_ov = ?",
            (new_status, timestamp, attention["sap_ov"]),
        )
        write_attention_history(connection, attention_id, "ESTADO", "app_status", old_status, new_status, username)
        if role in PICKER_ROLES and new_status == "PICKING FINALIZADO":
            queue_time = now()
            connection.execute("UPDATE attentions SET app_status = 'POR GUIAR', updated_at = ? WHERE id = ?", (queue_time, attention_id))
            connection.execute("UPDATE orders SET app_status = 'POR GUIAR', updated_at = ? WHERE sap_ov = ?", (queue_time, attention["sap_ov"]))
            write_attention_history(connection, attention_id, "ESTADO", "app_status", "PICKING FINALIZADO", "POR GUIAR", "sistema", "Picking finalizado; atención enviada a la cola de guiado")
        return attention_payload(connection, attention_id)


ADMIN_PREVIOUS_STATUS = {
    "ASIGNADO": "PENDIENTE",
    "EN PICKING": "ASIGNADO",
    "PICKING FINALIZADO": "EN PICKING",
    "POR GUIAR": "EN PICKING",
    "EN GUIADO": "POR GUIAR",
    "GUIADO FINALIZADO": "EN GUIADO",
    "ENTREGADO": "GUIADO FINALIZADO",
}


def restore_consumed_stock_for_picking(connection, attention, username, reason):
    """Revierte el consumo y vuelve a reservar solo lo realmente recogido."""
    timestamp = now()
    allocations = connection.execute(
        "SELECT * FROM stock_allocations WHERE attention_id = ?",
        (attention["id"],),
    ).fetchall()
    for allocation in allocations:
        consumed = max(0, number(allocation["consumed_qty"]))
        if allocation["status"] != "CONSUMIDA" or consumed <= 0:
            continue
        return_reconciled_stock(connection, allocation, username, timestamp)
        write_stock_movement(
            connection, allocation, "REVERSA_CONSUMO", consumed, username,
            reason or "Retroceso administrativo a picking",
        )
        connection.execute(
            """UPDATE stock_allocations
               SET reserved_qty = ?, consumed_qty = 0, status = 'ACTIVA',
                   consumed_at = NULL, released_at = NULL, updated_at = ?
               WHERE id = ?""",
            (consumed, timestamp, allocation["id"]),
        )
    reverse_lot_consumption(connection, attention["id"], username, reason)


def release_active_attention_stock(connection, attention, username, reason, movement_type):
    """Libera reservas activas para que vuelvan a estar disponibles globalmente."""
    timestamp = now()
    allocations = connection.execute(
        "SELECT * FROM stock_allocations WHERE attention_id = ? AND status = 'ACTIVA'",
        (attention["id"],),
    ).fetchall()
    for allocation in allocations:
        reserved = max(0, number(allocation["reserved_qty"]))
        if reserved > 0:
            write_stock_movement(connection, allocation, movement_type, reserved, username, reason)
        connection.execute(
            """UPDATE stock_allocations
               SET reserved_qty = 0, status = 'ANULADA', released_at = ?, updated_at = ?
               WHERE id = ?""",
            (timestamp, timestamp, allocation["id"]),
        )
    release_lot_reservations(
        connection, attention["id"], username, reason, movement_type
    )


def admin_rollback_attention(attention_id, username, role, reason):
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede retroceder una atención")
    reason = text(reason).strip()
    if not reason:
        raise ValueError("Indica el motivo del retroceso")
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        attention = connection.execute("SELECT * FROM attentions WHERE id = ?", (attention_id,)).fetchone()
        if not attention:
            raise ValueError("Atención no encontrada")
        if attention["app_status"] == "CERRADO SAP":
            raise PermissionError("La OV está cerrada en SAP y no puede reabrirse desde el WMS")
        old_status = attention["app_status"]
        new_status = ADMIN_PREVIOUS_STATUS.get(old_status)
        if not new_status:
            raise ValueError("La atención ya se encuentra en la etapa inicial")

        if old_status in {"PICKING FINALIZADO", "POR GUIAR"}:
            restore_consumed_stock_for_picking(connection, attention, username, reason)
        elif old_status == "EN PICKING":
            release_active_attention_stock(
                connection, attention, username, reason, "LIBERACION_RETROCESO"
            )
            connection.execute(
                "UPDATE attention_lines SET picked_qty = 0, delivered_qty = 0 WHERE attention_id = ?",
                (attention_id,),
            )
        elif old_status == "EN GUIADO":
            connection.execute(
                "UPDATE attention_lines SET delivered_qty = 0 WHERE attention_id = ?",
                (attention_id,),
            )

        picker = attention["current_picker"]
        guide = attention["current_guide"]
        if new_status == "PENDIENTE":
            picker = None
            guide = None
        timestamp = now()
        connection.execute(
            """UPDATE attentions
               SET app_status = ?, current_picker = ?, current_guide = ?, updated_at = ?
               WHERE id = ?""",
            (new_status, picker, guide, timestamp, attention_id),
        )
        connection.execute(
            """UPDATE orders
               SET app_status = ?, current_picker = ?, current_guide = ?, updated_at = ?
               WHERE sap_ov = ?""",
            (new_status, picker, guide, timestamp, attention["sap_ov"]),
        )
        write_attention_history(
            connection, attention_id, "RETROCESO_ADMIN", "app_status",
            old_status, new_status, username, reason,
        )
        return attention_payload(connection, attention_id)


def admin_reset_attention(attention_id, username, role, reason):
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede reiniciar una atención")
    reason = text(reason).strip()
    if not reason:
        raise ValueError("Indica el motivo del reinicio")
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        attention = connection.execute("SELECT * FROM attentions WHERE id = ?", (attention_id,)).fetchone()
        if not attention:
            raise ValueError("Atención no encontrada")
        if attention["app_status"] == "CERRADO SAP":
            raise PermissionError("La OV está cerrada en SAP y no puede reiniciarse desde el WMS")

        allocations = connection.execute(
            "SELECT * FROM stock_allocations WHERE attention_id = ?",
            (attention_id,),
        ).fetchall()
        timestamp = now()
        reverse_lot_consumption(connection, attention_id, username, reason)
        release_lot_reservations(
            connection, attention_id, username, reason, "LIBERACION_REINICIO"
        )
        for allocation in allocations:
            consumed = max(0, number(allocation["consumed_qty"]))
            reserved = max(0, number(allocation["reserved_qty"]))
            if allocation["status"] == "CONSUMIDA" and consumed > 0:
                return_reconciled_stock(connection, allocation, username, timestamp)
                write_stock_movement(
                    connection, allocation, "REVERSA_REINICIO", consumed,
                    username, reason,
                )
            elif allocation["status"] == "ACTIVA" and reserved > 0:
                write_stock_movement(
                    connection, allocation, "LIBERACION_REINICIO", reserved,
                    username, reason,
                )
            connection.execute(
                """UPDATE stock_allocations
                   SET reserved_qty = 0, consumed_qty = 0, status = 'ANULADA',
                       consumed_at = NULL, released_at = ?, updated_at = ?
                   WHERE id = ?""",
                (timestamp, timestamp, allocation["id"]),
            )

        connection.execute(
            """UPDATE attention_lines
               SET planned_qty = MAX(0, COALESCE(pending_qty, 0)),
                   picked_qty = 0, delivered_qty = 0
               WHERE attention_id = ?""",
            (attention_id,),
        )
        connection.execute(
            """UPDATE attentions
               SET attention_type = 'SELECCIONAR', app_status = 'PENDIENTE',
                   current_picker = NULL, current_guide = NULL, updated_at = ?
               WHERE id = ?""",
            (timestamp, attention_id),
        )
        connection.execute(
            """UPDATE orders
               SET attention_type = 'SELECCIONAR', app_status = 'PENDIENTE',
                   current_picker = NULL, current_guide = NULL, updated_at = ?
               WHERE sap_ov = ?""",
            (timestamp, attention["sap_ov"]),
        )
        write_attention_history(
            connection, attention_id, "REINICIO_ADMIN", "attention",
            attention["app_status"], "PENDIENTE", username, reason,
        )
        return attention_payload(connection, attention_id)


def attention_lines(connection, attention_id):
    return connection.execute(
        "SELECT id, item_code, planned_qty, picked_qty, delivered_qty FROM attention_lines WHERE attention_id = ? ORDER BY source_row",
        (attention_id,),
    ).fetchall()


def attention_inventory_lines(connection, attention_id):
    return connection.execute(
        """SELECT al.id, al.attention_id, al.item_code, al.planned_qty, al.picked_qty,
                  COALESCE(al.warehouse, ol.warehouse, '1') AS warehouse
           FROM attention_lines al
           LEFT JOIN order_lines ol ON ol.id = al.order_line_id
           WHERE al.attention_id = ? ORDER BY al.source_row, al.id""",
        (attention_id,),
    ).fetchall()


def reserve_attention_inventory(connection, attention, username):
    existing = connection.execute(
        "SELECT * FROM stock_allocations WHERE attention_id = ?",
        (attention["id"],),
    ).fetchall()
    if existing:
        if all(row["status"] == "ACTIVA" for row in existing):
            return
        if any(row["status"] == "CONSUMIDA" for row in existing):
            raise ValueError("Esta atención ya consumió stock; usa Corrección administrativa antes de reiniciarla")
        if any(row["status"] == "ACTIVA" for row in existing):
            raise ValueError("La atención tiene reservas inconsistentes; reiníciala desde Corrección administrativa")
    existing_by_line = {row["attention_line_id"]: row for row in existing}

    lines = attention_inventory_lines(connection, attention["id"])
    remaining_by_pool = {}
    decisions = []
    shortages = []
    for line in lines:
        item_code = identifier_text(line["item_code"])
        if not item_code:
            raise ValueError("Existe una línea sin código de artículo; corrige el Excel antes de iniciar")
        origin_type = classify_order_line_origin(connection, attention["sap_ov"], item_code)
        pool_type = "AEREO" if origin_type == "AEREO" else "STOCK"
        item_key = normalized_identifier(item_code)
        warehouse = identifier_text(line["warehouse"]) or "1"
        warehouse_key = normalized_warehouse(warehouse)
        pool_key = (
            pool_type,
            attention["sap_ov"] if pool_type == "AEREO" else "GLOBAL",
            item_key,
            warehouse_key,
        )
        if pool_key not in remaining_by_pool:
            remaining_by_pool[pool_key] = inventory_pool_status(
                connection, attention["sap_ov"], item_code, warehouse, origin_type
            )["free_qty"]
        requested = max(0, number(line["planned_qty"]))
        reservable = min(requested, remaining_by_pool[pool_key])
        remaining_by_pool[pool_key] -= reservable
        decisions.append((line, item_key, warehouse, warehouse_key, pool_type, origin_type, requested, reservable))
        if requested - reservable > 0.000001:
            shortages.append(f"{item_code}: faltan {requested - reservable:g}")

    if attention["attention_type"] == "COMPLETA" and shortages:
        raise ValueError("Stock insuficiente para atención COMPLETA. " + "; ".join(shortages[:5]))
    if not any(decision[-1] > 0 for decision in decisions):
        air_pending = any(decision[4] == "AEREO" for decision in decisions)
        if air_pending:
            raise ValueError("No hay saldo del corte Excel liberado por Recepción para esta OV")
        raise ValueError("No existe stock libre para iniciar esta atención")

    timestamp = now()
    for line, item_key, warehouse, warehouse_key, pool_type, origin_type, requested, reservable in decisions:
        if reservable <= 0:
            connection.execute("UPDATE attention_lines SET picked_qty = 0 WHERE id = ?", (line["id"],))
            continue
        previous = existing_by_line.get(line["id"])
        if previous:
            connection.execute(
                """UPDATE stock_allocations
                   SET sap_ov = ?, item_key = ?, item_code = ?, warehouse_key = ?,
                       warehouse = ?, pool_type = ?, origin_type = ?, reserved_qty = ?,
                       consumed_qty = 0, status = 'ACTIVA', reserved_at = ?,
                       consumed_at = NULL, released_at = NULL, username = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    attention["sap_ov"], item_key, identifier_text(line["item_code"]),
                    warehouse_key, warehouse, pool_type, origin_type, reservable,
                    timestamp, username, timestamp, previous["id"],
                ),
            )
            allocation = connection.execute(
                "SELECT * FROM stock_allocations WHERE id = ?", (previous["id"],)
            ).fetchone()
        else:
            cursor = connection.execute(
                """INSERT INTO stock_allocations
                   (attention_id, attention_line_id, sap_ov, item_key, item_code, warehouse_key,
                    warehouse, pool_type, origin_type, reserved_qty, consumed_qty, status,
                    reserved_at, username, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'ACTIVA', ?, ?, ?)""",
                (
                    attention["id"], line["id"], attention["sap_ov"], item_key,
                    identifier_text(line["item_code"]), warehouse_key, warehouse,
                    pool_type, origin_type, reservable, timestamp, username, timestamp,
                ),
            )
            allocation = connection.execute(
                "SELECT * FROM stock_allocations WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        write_stock_movement(
            connection, allocation, "RESERVA", reservable, username,
            "Reserva automática al iniciar picking",
        )
        lot_tracked = reserve_lots_for_allocation(
            connection, allocation, attention, line, reservable, username
        )
        proposed_picked = 0 if lot_tracked else reservable
        connection.execute(
            "UPDATE attention_lines SET picked_qty = ? WHERE id = ?",
            (proposed_picked, line["id"]),
        )
        write_attention_history(
            connection, attention["id"], "RESERVA_STOCK", "picked_qty",
            str(line["picked_qty"]), str(proposed_picked), username,
            (
                f"{line['item_code']}: {origin_type}, reservado {reservable:g} de {requested:g}"
                + ("; requiere escaneo de lote" if lot_tracked else "; saldo operativo del corte Excel")
            ),
        )


def bootstrap_active_stock_allocations(connection):
    """Migra reservas de atenciones que ya estaban en picking al actualizar."""
    active_attentions = connection.execute(
        "SELECT * FROM attentions WHERE app_status = 'EN PICKING'"
    ).fetchall()
    for attention in active_attentions:
        ensure_legacy_attention_allocations(connection, attention, "migracion-sistema")


def ensure_legacy_attention_allocations(connection, attention, username):
    """Protege picking iniciado antes de instalar el control global de stock."""
    for line in attention_inventory_lines(connection, attention["id"]):
        exists = connection.execute(
            "SELECT 1 FROM stock_allocations WHERE attention_line_id = ?", (line["id"],)
        ).fetchone()
        picked = max(0, number(line["picked_qty"]))
        if exists or picked <= 0:
            continue
        item_code = identifier_text(line["item_code"])
        origin_type = classify_order_line_origin(connection, attention["sap_ov"], item_code)
        pool_type = "AEREO" if origin_type == "AEREO" else "STOCK"
        timestamp = now()
        cursor = connection.execute(
            """INSERT INTO stock_allocations
               (attention_id, attention_line_id, sap_ov, item_key, item_code, warehouse_key,
                warehouse, pool_type, origin_type, reserved_qty, consumed_qty, status,
                reserved_at, username, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'ACTIVA', ?, ?, ?)""",
            (
                attention["id"], line["id"], attention["sap_ov"], normalized_identifier(item_code),
                item_code, normalized_warehouse(line["warehouse"]), identifier_text(line["warehouse"]) or "1",
                pool_type, origin_type, picked, timestamp, username, timestamp,
            ),
        )
        allocation = connection.execute("SELECT * FROM stock_allocations WHERE id = ?", (cursor.lastrowid,)).fetchone()
        write_stock_movement(
            connection, allocation, "RESERVA_MIGRADA", picked, username,
            "Picking ya estaba iniciado antes del control global",
        )


def consume_attention_inventory(connection, attention, username):
    ensure_legacy_attention_allocations(connection, attention, username)
    timestamp = now()
    for line in attention_inventory_lines(connection, attention["id"]):
        picked = max(0, number(line["picked_qty"]))
        allocation = connection.execute(
            "SELECT * FROM stock_allocations WHERE attention_line_id = ?", (line["id"],)
        ).fetchone()
        if picked <= 0 and not allocation:
            continue
        if not allocation or allocation["status"] != "ACTIVA":
            raise ValueError(f"La línea {line['item_code']} no tiene una reserva activa")
        reserved = max(0, number(allocation["reserved_qty"]))
        if picked - reserved > 0.000001:
            raise ValueError(f"La cantidad recogida de {line['item_code']} supera su reserva")
        released = max(0, reserved - picked)
        status = "CONSUMIDA" if picked > 0 else "LIBERADA"
        connection.execute(
            """UPDATE stock_allocations
               SET consumed_qty = ?, status = ?, consumed_at = ?,
                   released_at = CASE WHEN ? > 0 THEN ? ELSE released_at END,
                   updated_at = ? WHERE id = ?""",
            (picked, status, timestamp if picked > 0 else None, released, timestamp, timestamp, allocation["id"]),
        )
        if picked > 0:
            write_stock_movement(connection, allocation, "CONSUMO", picked, username, "Picking finalizado")
        if released > 0:
            write_stock_movement(connection, allocation, "LIBERACION", released, username, "Saldo no recogido")
        consume_lots_for_line(
            connection, line["id"], picked, username,
            attention["sap_ov"], attention["id"],
        )


def ensure_line_reservation(connection, attention, line, requested_qty, username):
    allocation = connection.execute(
        "SELECT * FROM stock_allocations WHERE attention_line_id = ?", (line["id"],)
    ).fetchone()
    if allocation and allocation["status"] not in {"ACTIVA", "ANULADA", "LIBERADA"}:
        raise ValueError("La reserva de esta línea ya fue cerrada")
    current_reserved = number(allocation["reserved_qty"]) if allocation and allocation["status"] == "ACTIVA" else 0
    if requested_qty <= current_reserved:
        return current_reserved

    item_code = identifier_text(line["item_code"])
    origin_type = classify_order_line_origin(connection, attention["sap_ov"], item_code)
    warehouse = identifier_text(line["warehouse"]) or "1"
    status = inventory_pool_status(connection, attention["sap_ov"], item_code, warehouse, origin_type)
    additional = requested_qty - current_reserved
    if additional - status["free_qty"] > 0.000001:
        source = "saldo del corte Excel disponible para esta OV"
        raise ValueError(
            f"{item_code}: solo hay {status['free_qty']:g} adicionales en {source}; "
            f"la reserva actual es {current_reserved:g}"
        )
    timestamp = now()
    if allocation:
        connection.execute(
            """UPDATE stock_allocations
               SET reserved_qty = ?, consumed_qty = 0, status = 'ACTIVA',
                   reserved_at = ?, consumed_at = NULL, released_at = NULL,
                   username = ?, updated_at = ? WHERE id = ?""",
            (requested_qty, timestamp, username, timestamp, allocation["id"]),
        )
        allocation = connection.execute("SELECT * FROM stock_allocations WHERE id = ?", (allocation["id"],)).fetchone()
    else:
        cursor = connection.execute(
            """INSERT INTO stock_allocations
               (attention_id, attention_line_id, sap_ov, item_key, item_code, warehouse_key,
                warehouse, pool_type, origin_type, reserved_qty, consumed_qty, status,
                reserved_at, username, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'ACTIVA', ?, ?, ?)""",
            (
                attention["id"], line["id"], attention["sap_ov"], normalized_identifier(item_code),
                item_code, normalized_warehouse(warehouse), warehouse, status["pool_type"], origin_type,
                requested_qty, timestamp, username, timestamp,
            ),
        )
        allocation = connection.execute("SELECT * FROM stock_allocations WHERE id = ?", (cursor.lastrowid,)).fetchone()
    write_stock_movement(
        connection, allocation, "RESERVA_ADICIONAL", additional, username,
        "Ajuste de cantidad durante picking",
    )
    return requested_qty


def prefill_picking_quantities(connection, attention, username):
    """Reserva globalmente y propone solo la cantidad realmente disponible."""
    reserve_attention_inventory(connection, attention, username)


def prefill_delivery_quantities(connection, attention, username):
    """Proposes delivery of everything actually collected by the picker."""
    lines = attention_lines(connection, attention["id"])
    for line in lines:
        proposed = max(0, line["picked_qty"])
        if line["delivered_qty"] == proposed:
            continue
        connection.execute("UPDATE attention_lines SET delivered_qty = ? WHERE id = ?", (proposed, line["id"]))
        write_attention_history(
            connection, attention["id"], "CANTIDAD_PREDETERMINADA", "delivered_qty",
            str(line["delivered_qty"]), str(proposed), username,
            f"{line['item_code'] or 'Línea'}: cantidad recogida",
        )


def validate_picking_completion(connection, attention):
    lines = attention_lines(connection, attention["id"])
    if not lines or not any(line["picked_qty"] > 0 for line in lines):
        raise ValueError("Registra al menos una cantidad recogida antes de finalizar picking")
    if attention["attention_type"] == "COMPLETA" and any(line["picked_qty"] != line["planned_qty"] for line in lines):
        raise ValueError("Una atención COMPLETA requiere recoger toda la cantidad planificada")


def validate_delivery_completion(connection, attention):
    lines = attention_lines(connection, attention["id"])
    if any(line["delivered_qty"] != line["picked_qty"] for line in lines):
        raise ValueError("Registra como entregada toda la cantidad recogida antes de cerrar la atención")


def update_attention_line(attention_id, line_id, field, value, username, role):
    if field not in {"picked_qty", "delivered_qty"}:
        raise ValueError("Campo de cantidad no válido")
    amount = number(value)
    if amount < 0:
        raise ValueError("La cantidad no puede ser negativa")
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        attention = connection.execute("SELECT * FROM attentions WHERE id = ?", (attention_id,)).fetchone()
        if not attention:
            raise ValueError("Atención no encontrada")
        line = connection.execute(
            "SELECT * FROM attention_lines WHERE id = ? AND attention_id = ?", (line_id, attention_id)
        ).fetchone()
        if not line:
            raise ValueError("Línea no encontrada")
        if role in PICKER_ROLES:
            if field != "picked_qty" or attention["app_status"] != "EN PICKING" or not same_username(username, attention["current_picker"]):
                raise PermissionError("Solo el picker asignado puede registrar cantidades recogidas durante el picking")
            maximum = line["planned_qty"]
        elif role in GUIDE_ROLES:
            if field != "delivered_qty" or attention["app_status"] not in {"EN GUIADO", "GUIADO FINALIZADO"} or not same_username(username, attention["current_guide"]):
                raise PermissionError("Solo el guiador/entregador asignado puede registrar cantidades entregadas")
            maximum = line["picked_qty"]
        else:
            raise PermissionError("El administrador supervisa; las cantidades las registra el responsable operativo")
        if amount > maximum:
            raise ValueError("La cantidad excede el máximo permitido para esta línea")
        if role in PICKER_ROLES:
            validate_picked_against_scans(connection, line_id, amount)
            ensure_line_reservation(connection, attention, line, amount, username)
        old_value = line[field]
        connection.execute(f"UPDATE attention_lines SET {field} = ? WHERE id = ?", (amount, line_id))
        write_attention_history(connection, attention_id, "CANTIDAD", field, str(old_value), str(amount), username, line["item_code"] or "")
        return attention_payload(connection, attention_id)


def set_attention_type(attention_id, attention_type, username, role):
    attention_type = normalize_attention(attention_type)
    if attention_type not in {"PARCIAL", "COMPLETA"}:
        raise ValueError("Selecciona PARCIAL o COMPLETA")
    with db() as connection:
        attention = connection.execute("SELECT * FROM attentions WHERE id = ?", (attention_id,)).fetchone()
        if not attention:
            raise ValueError("Atención no encontrada")
        can_change_before_picking = attention["app_status"] in {"PENDIENTE", "ASIGNADO"}
        picker_can_change = (
            role in PICKER_ROLES
            and same_username(username, attention["current_picker"])
            and can_change_before_picking
        )
        admin_can_change = role == "ADMINISTRADOR" and can_change_before_picking
        if not admin_can_change and not picker_can_change:
            raise PermissionError("Solo el administrador o el picker asignado antes de iniciar puede cambiar el tipo")
        old_value = attention["attention_type"]
        connection.execute("UPDATE attentions SET attention_type = ?, updated_at = ? WHERE id = ?", (attention_type, now(), attention_id))
        connection.execute("UPDATE orders SET attention_type = ?, updated_at = ? WHERE sap_ov = ?", (attention_type, now(), attention["sap_ov"]))
        write_attention_history(connection, attention_id, "TIPO_ATENCION", "attention_type", old_value, attention_type, username)
        return attention_payload(connection, attention_id)


def write_attention_history(connection, attention_id, event_type, field_name, old_value, new_value, username, reason=""):
    connection.execute(
        "INSERT INTO attention_history (attention_id, event_type, field_name, old_value, new_value, username, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (attention_id, event_type, field_name, old_value, new_value, username, reason, now()),
    )


def assign_attention(attention_id, field, value, username, role):
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede asignar responsables")
    if field not in {"current_picker", "current_guide"}:
        raise ValueError("Responsable no válido")
    with db() as connection:
        identity.require_assignee(connection, value, 'PICKER' if field == 'current_picker' else 'GUIADOR')
        attention = connection.execute("SELECT * FROM attentions WHERE id = ?", (attention_id,)).fetchone()
        if not attention:
            raise ValueError("Atención no encontrada")
        if field == "current_picker" and STATUS_INDEX[attention["app_status"]] >= STATUS_INDEX["PICKING FINALIZADO"]:
            raise PermissionError("El picker solo puede reasignarse mientras el picking está pendiente o en curso")
        if field == "current_guide" and STATUS_INDEX[attention["app_status"]] >= STATUS_INDEX["GUIADO FINALIZADO"]:
            raise PermissionError("El guiador/entregador solo puede reasignarse mientras el guiado está pendiente o en curso")
        old_value = attention[field] or ""
        timestamp = now()
        connection.execute(f"UPDATE attentions SET {field} = ?, app_status = CASE WHEN app_status = 'PENDIENTE' THEN 'ASIGNADO' ELSE app_status END, updated_at = ? WHERE id = ?", (value, timestamp, attention_id))
        connection.execute(
            f"UPDATE orders SET {field} = ?, app_status = CASE WHEN app_status = 'PENDIENTE' THEN 'ASIGNADO' ELSE app_status END, updated_at = ? WHERE sap_ov = ?",
            (value, timestamp, attention["sap_ov"]),
        )
        role_name = "PICKER" if field == "current_picker" else "GUIADOR"
        connection.execute("INSERT INTO attention_assignments (attention_id, role, old_user, new_user, username, created_at) VALUES (?, ?, ?, ?, ?, ?)", (attention_id, role_name, old_value, value, username, timestamp))
        write_attention_history(connection, attention_id, "ASIGNACION", field, old_value, value, username)
        return attention_payload(connection, attention_id)


def row_to_dict(row):
    result = dict(row)
    return result


def enrich_order_lines_inventory(connection, sap_ov, lines, line_categories=None):
    category_by_item = {
        normalized_identifier(item.get("item_code")): item.get("classification")
        for item in (line_categories or [])
    }
    for line in lines:
        origin = category_by_item.get(normalized_identifier(line.get("item_code")))
        line.update(inventory_line_payload(connection, sap_ov, line, origin_type=origin))
    return lines


def order_inventory_summary(connection, sap_ov, line_categories=None):
    lines = [row_to_dict(row) for row in connection.execute(
        """SELECT item_code, warehouse, pending_qty FROM order_lines
           WHERE sap_ov = ? AND is_pending_sap = 1 ORDER BY source_row""",
        (sap_ov,),
    ).fetchall()]
    category_by_item = {
        normalized_identifier(item.get("item_code")): item.get("classification")
        for item in (line_categories or [])
    }
    remaining_by_pool = {}
    shortage_lines = 0
    shortage_qty = 0.0
    pending_total = 0.0
    attendable_total = 0.0
    for line in lines:
        item_code = line["item_code"]
        warehouse = line["warehouse"] or "1"
        origin = category_by_item.get(normalized_identifier(item_code)) or classify_order_line_origin(
            connection, sap_ov, item_code
        )
        pool_type = "AEREO" if origin == "AEREO" else "STOCK"
        pool_key = (
            pool_type,
            sap_ov if pool_type == "AEREO" else "GLOBAL",
            normalized_identifier(item_code),
            normalized_warehouse(warehouse),
        )
        if pool_key not in remaining_by_pool:
            remaining_by_pool[pool_key] = inventory_pool_status(
                connection, sap_ov, item_code, warehouse, origin
            )["free_qty"]
        demand = max(0, number(line["pending_qty"]))
        supplied = min(demand, remaining_by_pool[pool_key])
        remaining_by_pool[pool_key] -= supplied
        pending_total += demand
        attendable_total += supplied
        if demand - supplied > 0.000001:
            shortage_lines += 1
            shortage_qty += demand - supplied
    return {
        "stock_shortage_lines": shortage_lines,
        "stock_shortage_qty": shortage_qty,
        "pending_total": pending_total,
        "stock_attendable_total": attendable_total,
        "stock_complete_available": bool(lines) and shortage_lines == 0,
    }


def orders_payload(search="", limit=20, username="", role="ADMINISTRADOR",
                  creation_date="", creation_date_end=""):
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 20
    with db() as connection:
        search = text(search).lower()
        filters = []
        params = []
        if creation_date:
            creation_date = date.fromisoformat(text(creation_date)).isoformat()
            creation_date_end = date.fromisoformat(text(creation_date_end or creation_date)).isoformat()
            if creation_date_end < creation_date:
                raise ValueError("La fecha final no puede ser anterior a la fecha inicial")
            filters.append("substr(COALESCE(o.source_order_date, ''), 1, 10) BETWEEN ? AND ?")
            params.extend((creation_date, creation_date_end))
        elif creation_date_end:
            creation_date_end = date.fromisoformat(text(creation_date_end)).isoformat()
            filters.append("substr(COALESCE(o.source_order_date, ''), 1, 10) <= ?")
            params.append(creation_date_end)
        if search:
            match = f"%{search}%"
            filters.append("""(lower(o.sap_ov) LIKE ? OR lower(o.customer_name) LIKE ?
                OR EXISTS (SELECT 1 FROM order_importation_refs r WHERE r.sap_ov = o.sap_ov
                           AND (lower(COALESCE(r.bl_awb, '')) LIKE ?
                                OR lower(COALESCE(r.ip_reference, '')) LIKE ?
                                OR lower(COALESCE(r.oc_number, '')) LIKE ?))
                OR EXISTS (SELECT 1 FROM order_lines l WHERE l.sap_ov = o.sap_ov
                           AND l.is_pending_sap = 1
                           AND (lower(l.item_code) LIKE ? OR lower(l.description) LIKE ?)))""")
            params.extend((match, match, match, match, match, match, match))
        # Sin búsqueda mostramos únicamente la cola activa. Cuando el usuario
        # consulta una OV/cliente/artículo concreto, también incluimos las OVs
        # cerradas para poder revisar su histórico sin devolverlas al trabajo.
        if not search:
            filters.append("""(EXISTS (SELECT 1 FROM order_lines l WHERE l.sap_ov = o.sap_ov AND l.is_pending_sap = 1)
                               OR EXISTS (SELECT 1 FROM attentions a WHERE a.sap_ov = o.sap_ov AND a.app_status NOT IN ('ENTREGADO', 'CERRADO SAP')))""")
        if role == "PICKER":
            filters.append("""EXISTS (SELECT 1 FROM attentions a WHERE a.sap_ov = o.sap_ov
                AND lower(COALESCE(a.current_picker, '')) = ?
                AND a.app_status IN ('ASIGNADO', 'EN PICKING', 'POR GUIAR'))""")
            params.append(text(username).lower())
        elif role == "PICKER_GUIADOR":
            filters.append("""(EXISTS (SELECT 1 FROM attentions a WHERE a.sap_ov = o.sap_ov
                AND lower(COALESCE(a.current_picker, '')) = ?
                AND a.app_status IN ('ASIGNADO', 'EN PICKING', 'POR GUIAR'))
                OR EXISTS (SELECT 1 FROM attentions a WHERE a.sap_ov = o.sap_ov
                AND lower(COALESCE(a.current_guide, '')) = ?
                AND a.app_status IN ('POR GUIAR', 'EN GUIADO', 'GUIADO FINALIZADO')))""")
            params.extend((text(username).lower(), text(username).lower()))
        elif role == "GUIADOR":
            filters.append("""EXISTS (SELECT 1 FROM attentions a WHERE a.sap_ov = o.sap_ov
                AND lower(COALESCE(a.current_guide, '')) = ?
                AND a.app_status IN ('POR GUIAR', 'EN GUIADO', 'GUIADO FINALIZADO'))""")
            params.append(text(username).lower())
        where = " WHERE " + " AND ".join(filters) if filters else ""
        orders = connection.execute(
            f"""SELECT o.* FROM orders o{where}
                ORDER BY CASE WHEN COALESCE(o.source_order_date, '') = '' THEN 1 ELSE 0 END,
                         o.source_order_date DESC, o.updated_at DESC, o.sap_ov ASC LIMIT ?""",
            (*params, limit),
        ).fetchall()
        payload = []
        for order in orders:
            item = row_to_dict(order)
            item["line_count"] = connection.execute("SELECT COUNT(*) FROM order_lines WHERE sap_ov = ? AND is_pending_sap = 1", (order["sap_ov"],)).fetchone()[0]
            if item["line_count"] == 0 and order["app_status"] == "CERRADO SAP":
                item["line_count"] = connection.execute("SELECT COUNT(*) FROM order_lines WHERE sap_ov = ?", (order["sap_ov"],)).fetchone()[0]
            item["pending_total"] = connection.execute("SELECT COALESCE(SUM(pending_qty), 0) FROM order_lines WHERE sap_ov = ? AND is_pending_sap = 1", (order["sap_ov"],)).fetchone()[0]
            item["available_total"] = connection.execute("SELECT COALESCE(SUM(available_qty), 0) FROM order_lines WHERE sap_ov = ? AND is_pending_sap = 1", (order["sap_ov"],)).fetchone()[0]
            importation = picking_importation_context(connection, order["sap_ov"])
            item.update(order_inventory_summary(connection, order["sap_ov"], importation.get("line_categories")))
            item["attention_count"] = connection.execute("SELECT COUNT(*) FROM attentions WHERE sap_ov = ?", (order["sap_ov"],)).fetchone()[0]
            active = connection.execute("SELECT id, app_status FROM attentions WHERE sap_ov = ? AND app_status NOT IN ('ENTREGADO', 'CERRADO SAP') ORDER BY sequence_no DESC LIMIT 1", (order["sap_ov"],)).fetchone()
            item["active_attention_id"] = active["id"] if active else None
            item["active_status"] = active["app_status"] if active else order["app_status"]
            item.update(importation)
            payload.append(item)
        return payload


def work_summary(module="dispatch", username="", role="ADMINISTRADOR"):
    """Resume todos los expedientes asignados, sin limitarse a la cola visible."""
    module = text(module).strip().lower()
    username_key = text(username).strip().lower()
    with db() as connection:
        if module == "reception":
            conditions = []
            params = []
            if role != "ADMINISTRADOR":
                if role not in RECEPTION_ROLES or not username_key:
                    return {"module": module, "total": 0, "by_status": {}}
                conditions.append("(lower(COALESCE(s.current_assistant, '')) = ? OR lower(COALESCE(s.current_auxiliary, '')) = ?)")
                params.extend((username_key, username_key))
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            rows = connection.execute(
                f"SELECT s.app_status AS status, COUNT(*) AS total FROM reception_shipments s{where} GROUP BY s.app_status ORDER BY s.app_status",
                params,
            ).fetchall()
        else:
            if role == "ADMINISTRADOR":
                conditions = []
                params = []
            elif role == "PICKER":
                conditions = ["EXISTS (SELECT 1 FROM attentions a2 WHERE a2.sap_ov = o.sap_ov AND lower(COALESCE(a2.current_picker, '')) = ?)"]
                params = [username_key]
            elif role == "GUIADOR":
                conditions = ["EXISTS (SELECT 1 FROM attentions a2 WHERE a2.sap_ov = o.sap_ov AND lower(COALESCE(a2.current_guide, '')) = ?)"]
                params = [username_key]
            elif role == "PICKER_GUIADOR":
                conditions = ["EXISTS (SELECT 1 FROM attentions a2 WHERE a2.sap_ov = o.sap_ov AND (lower(COALESCE(a2.current_picker, '')) = ? OR lower(COALESCE(a2.current_guide, '')) = ?))"]
                params = [username_key, username_key]
            else:
                return {"module": module, "total": 0, "by_status": {}}
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            rows = connection.execute(
                f"""SELECT COALESCE((SELECT a.app_status FROM attentions a
                                      WHERE a.sap_ov = o.sap_ov
                                      ORDER BY a.sequence_no DESC, a.id DESC LIMIT 1), o.app_status) AS status,
                                  COUNT(*) AS total
                           FROM orders o{where}
                           GROUP BY status ORDER BY status""",
                params,
            ).fetchall()
        by_status = {text(row["status"] or "SIN ESTADO"): int(row["total"] or 0) for row in rows}
        return {"module": module, "total": sum(by_status.values()), "by_status": by_status}


def can_view_order(sap_ov, username, role):
    if role == "ADMINISTRADOR":
        return True
    if role == "PICKER_GUIADOR":
        fields = (("current_picker", ("ASIGNADO", "EN PICKING", "POR GUIAR")), ("current_guide", ("POR GUIAR", "EN GUIADO", "GUIADO FINALIZADO")))
    else:
        field = "current_picker" if role == "PICKER" else "current_guide"
        statuses = ("ASIGNADO", "EN PICKING", "POR GUIAR") if role == "PICKER" else ("POR GUIAR", "EN GUIADO", "GUIADO FINALIZADO")
        fields = ((field, statuses),)
    with db() as connection:
        for field, statuses in fields:
            row = connection.execute(
                f"""SELECT 1 FROM attentions WHERE sap_ov = ?
                    AND lower(COALESCE({field}, '')) = ?
                    AND app_status IN ({','.join('?' for _ in statuses)}) LIMIT 1""",
                (sap_ov, text(username).lower(), *statuses),
            ).fetchone()
            if row:
                return True
    return False


def order_payload(sap_ov):
    with db() as connection:
        order = connection.execute("SELECT * FROM orders WHERE sap_ov = ?", (sap_ov,)).fetchone()
        if not order:
            return None
        result = row_to_dict(order)
        result["lines"] = [row_to_dict(row) for row in connection.execute("SELECT * FROM order_lines WHERE sap_ov = ? AND is_pending_sap = 1 ORDER BY source_row", (sap_ov,))]
        result["attended_lines"] = [row_to_dict(row) for row in connection.execute(
            "SELECT * FROM order_lines WHERE sap_ov = ? AND is_pending_sap = 0 ORDER BY source_row",
            (sap_ov,),
        )]
        result["history"] = [row_to_dict(row) for row in connection.execute("SELECT * FROM history WHERE sap_ov = ? ORDER BY id DESC", (sap_ov,))]
        result["assignments"] = [row_to_dict(row) for row in connection.execute("SELECT * FROM assignments WHERE sap_ov = ? ORDER BY id DESC", (sap_ov,))]
        importation = picking_importation_context(connection, sap_ov)
        result.update(importation)
        enrich_order_lines_inventory(connection, sap_ov, result["lines"], importation.get("line_categories"))
        enrich_order_lines_inventory(connection, sap_ov, result["attended_lines"], importation.get("line_categories"))
        result["fulfillment"] = fulfillment_summary(connection, sap_ov)
        result["attentions"] = list_attentions(connection, sap_ov)
        return result


def fulfillment_summary(connection, sap_ov):
    importation = picking_importation_context(connection, sap_ov)
    summary = order_inventory_summary(connection, sap_ov, importation.get("line_categories"))
    line_count = connection.execute(
        "SELECT COUNT(*) FROM order_lines WHERE sap_ov = ? AND is_pending_sap = 1", (sap_ov,)
    ).fetchone()[0]
    pending_total = summary["pending_total"]
    partial_total = summary["stock_attendable_total"]
    return {
        "line_count": line_count,
        "pending_total": pending_total,
        "available_total": partial_total,
        "partial_attendable_total": partial_total,
        "complete_available": summary["stock_complete_available"],
        "remaining_after_partial": max(0, pending_total - partial_total),
    }


def minutes_between(start, end):
    if not start or not end:
        return None
    return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 60, 2)


def operational_report(limit=100):
    with db() as connection:
        attentions = connection.execute(
            """SELECT a.*, o.customer_name FROM attentions a
               JOIN orders o ON o.sap_ov = a.sap_ov
               ORDER BY a.updated_at DESC"""
        ).fetchall()
        events_by_attention = {}
        for event in connection.execute(
            """SELECT attention_id, new_value, created_at FROM attention_history
               WHERE new_value IN ('EN PICKING', 'PICKING FINALIZADO', 'EN GUIADO',
                                   'GUIADO FINALIZADO', 'ENTREGADO') ORDER BY id"""
        ):
            events_by_attention.setdefault(event["attention_id"], {}).setdefault(event["new_value"], event["created_at"])
        all_rows = []
        for attention in attentions:
            timestamps = events_by_attention.get(attention["id"], {})
            row = row_to_dict(attention)
            row["picking_minutes"] = minutes_between(timestamps.get("EN PICKING"), timestamps.get("PICKING FINALIZADO"))
            row["waiting_guide_minutes"] = minutes_between(timestamps.get("PICKING FINALIZADO"), timestamps.get("EN GUIADO"))
            row["guiding_minutes"] = minutes_between(timestamps.get("EN GUIADO"), timestamps.get("GUIADO FINALIZADO"))
            row["waiting_delivery_minutes"] = minutes_between(timestamps.get("GUIADO FINALIZADO"), timestamps.get("ENTREGADO"))
            all_rows.append(row)
        by_status = {}
        for row in all_rows:
            by_status[row["app_status"]] = by_status.get(row["app_status"], 0) + 1
        averages = {}
        for field in ("picking_minutes", "waiting_guide_minutes", "guiding_minutes", "waiting_delivery_minutes"):
            values = [row[field] for row in all_rows if row[field] is not None]
            averages[field] = round(sum(values) / len(values), 2) if values else None
        active_order_ids = {
            row["sap_ov"] for row in all_rows if row["app_status"] not in TERMINAL_ATTENTION_STATUSES
        }
        stock_shortage_orders = sum(
            order_inventory_summary(connection, sap_ov)["stock_shortage_lines"] > 0
            for sap_ov in active_order_ids
        )
        alerts = {
            "without_picker": sum(
                row["app_status"] in {"PENDIENTE", "ASIGNADO"} and not text(row["current_picker"])
                for row in all_rows
            ),
            "waiting_guide": by_status.get("POR GUIAR", 0),
            "ready_delivery": by_status.get("GUIADO FINALIZADO", 0),
            "stock_shortage_orders": stock_shortage_orders,
        }
        return {"total_attentions": len(all_rows), "by_status": by_status, "averages_minutes": averages, "alerts": alerts, "rows": all_rows[:limit]}


def workload_report(period="day", start=None, end=None):
    from backend.services.workload import workload_report as build_report
    with db() as connection:
        return build_report(connection, period, start=start, end=end)


def list_users():
    with db() as connection:
        return [row_to_dict(row) for row in connection.execute(
            "SELECT username, display_name, first_name, last_name, document_id, role, shift, active, created_at, updated_at FROM users ORDER BY active DESC, display_name"
        ).fetchall()]


def list_assignees(role_name, include_reception=False):
    role_name = text(role_name).strip().upper()
    role_groups = {
        "PICKER": {"PICKER", "PICKER_GUIADOR"},
        "GUIADOR": {"GUIADOR", "PICKER_GUIADOR"},
        "ASISTENTE_RECEPCION": {"ASISTENTE_RECEPCION"},
        "AUXILIAR_RECEPCION": {"AUXILIAR_RECEPCION"},
    }
    if role_name not in role_groups:
        raise ValueError("Rol de responsable no válido")
    roles = set(role_groups[role_name])
    if include_reception and role_name in {"PICKER", "GUIADOR"}:
        roles.update({"ASISTENTE_RECEPCION", "AUXILIAR_RECEPCION"})
    placeholders = ",".join("?" for _ in roles)
    with db() as connection:
        query = f"""SELECT username, display_name, role, shift
                    FROM users WHERE active=1 AND role IN ({placeholders})
                    ORDER BY display_name COLLATE NOCASE, username"""
        return [row_to_dict(row) for row in connection.execute(query, tuple(sorted(roles))).fetchall()]


def save_user(data, actor, role):
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede gestionar usuarios")
    with db() as connection:
        connection.execute('BEGIN IMMEDIATE')
        return identity.save(connection, data, actor, ROLES)


def deactivate_user(username, actor, role):
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede gestionar usuarios")
    username = text(username).strip().lower()
    with db() as connection:
        connection.execute('BEGIN IMMEDIATE')
        identity.deactivate(connection, username, actor)
    return list_users()


def write_history(connection, sap_ov, event_type, field_name, old_value, new_value, username, reason=""):
    connection.execute(
        "INSERT INTO history (sap_ov, event_type, field_name, old_value, new_value, username, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (sap_ov, event_type, field_name, old_value, new_value, username, reason, now()),
    )


def current_user(handler):
    mode = os.getenv('TRITON_AUTH_MODE', 'demo').lower()
    if mode == 'local':
        try:
            with db() as connection:
                user = identity.session_user(connection, handler.headers)
        except PermissionError:
            handler._unauthenticated = True
            raise
        return user['username'], user['role']
    if mode not in {'demo', 'entra'}:
        raise PermissionError('Modo de autenticación no válido')
    if os.getenv("TRITON_AUTH_MODE", "demo").lower() == "entra":
        principal = handler.headers.get("X-MS-CLIENT-PRINCIPAL")
        if not principal:
            raise PermissionError("Autenticación Microsoft Entra requerida")
        try:
            decoded = base64.b64decode(principal).decode("utf-8")
            payload = json.loads(decoded)
        except Exception as error:
            raise PermissionError("Identidad Microsoft Entra no válida") from error
        username = payload.get("userDetails") or payload.get("userId")
        roles = {str(value).upper() for value in payload.get("userRoles", [])}
        if not username:
            raise PermissionError("La identidad Microsoft Entra no contiene un usuario")
        role = next(
            (
                candidate
                for candidate in (
                    "ADMINISTRADOR",
                    "ASISTENTE_RECEPCION",
                    "AUXILIAR_RECEPCION",
                    "PICKER",
                    "GUIADOR",
                    "PICKER_GUIADOR",
                )
                if candidate in roles
            ),
            None,
        )
        if not role:
            raise PermissionError("El usuario no tiene un rol válido para TRITON WMS")
        return username, role
    username = handler.headers.get("X-User", "demo.admin")
    role = handler.headers.get("X-Role", "ADMINISTRADOR").upper()
    if role not in ROLES:
        raise PermissionError("El rol indicado no existe en TRITON WMS")
    return username, role


def require_dispatch_access(role):
    if role not in DISPATCH_ROLES:
        raise PermissionError("Tu usuario no tiene acceso al módulo Despacho")


def payload_for_role(payload, role):
    """Removes audit records from operational roles before returning JSON."""
    if not payload or role == "ADMINISTRADOR":
        return payload
    payload.pop("history", None)
    payload.pop("assignments", None)
    for attention in payload.get("attentions", []):
        attention.pop("history", None)
        attention.pop("assignments", None)
        for line in attention.get("lines", []):
            line.pop("available_lots", None)
    return payload


def change_status(sap_ov, new_status, username, role):
    if new_status not in STATUS_INDEX:
        raise ValueError("Estado no válido")
    with db() as connection:
        order = connection.execute("SELECT * FROM orders WHERE sap_ov = ?", (sap_ov,)).fetchone()
        if not order:
            raise ValueError("OV no encontrada")
        importation = picking_importation_context(connection, sap_ov)
        if importation["picking_blocked"] and new_status in {
            "ASIGNADO", "EN PICKING", "PICKING FINALIZADO", "POR GUIAR", "EN GUIADO",
            "GUIADO FINALIZADO", "ENTREGADO",
        }:
            raise PermissionError(importation["picking_block_reason"] + ". El picking se habilitará cuando Recepción registre el arribo.")
        old_status = order["app_status"]
        old_index = STATUS_INDEX[old_status]
        new_index = STATUS_INDEX[new_status]
        if role != "ADMINISTRADOR" and new_index < old_index:
            raise PermissionError("Solo el administrador puede retroceder estados")
        if role != "ADMINISTRADOR":
            if role in PICKER_ROLES and new_status in {"EN PICKING", "PICKING FINALIZADO"}:
                if not order["current_picker"] or not same_username(username, order["current_picker"]):
                    raise PermissionError("Solo el picker asignado puede cambiar el estado de picking")
            elif role in GUIDE_ROLES and new_status in {"EN GUIADO", "GUIADO FINALIZADO", "ENTREGADO"}:
                if not order["current_guide"] or not same_username(username, order["current_guide"]):
                    raise PermissionError("Solo el guiador/entregador asignado puede cambiar el estado de guiado o entrega")
            else:
                raise PermissionError("Este usuario no puede controlar esta etapa")
        guiador_start_after_picking = role in GUIDE_ROLES and old_status == "PICKING FINALIZADO" and new_status == "EN GUIADO"
        if new_index > old_index + 1 and role != "ADMINISTRADOR" and not guiador_start_after_picking:
            raise PermissionError("El flujo debe avanzar paso a paso")
        connection.execute("UPDATE orders SET app_status = ?, updated_at = ? WHERE sap_ov = ?", (new_status, now(), sap_ov))
        write_history(connection, sap_ov, "ESTADO", "app_status", old_status, new_status, username)


def assign_order(sap_ov, field, value, username, role):
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede asignar responsables")
    if field not in {"current_picker", "current_guide"}:
        raise ValueError("Responsable no válido")
    with db() as connection:
        identity.require_assignee(connection, value, 'PICKER' if field == 'current_picker' else 'GUIADOR')
        order = connection.execute("SELECT * FROM orders WHERE sap_ov = ?", (sap_ov,)).fetchone()
        if not order:
            raise ValueError("OV no encontrada")
        if field == "current_picker":
            importation = picking_importation_context(connection, sap_ov)
            if importation["picking_blocked"]:
                raise PermissionError(importation["picking_block_reason"] + ". Primero registra el arribo en Recepción.")
        if field == "current_picker" and STATUS_INDEX[order["app_status"]] >= STATUS_INDEX["PICKING FINALIZADO"]:
            raise PermissionError("El picker solo puede reasignarse mientras el picking está pendiente o en curso")
        if field == "current_guide" and STATUS_INDEX[order["app_status"]] >= STATUS_INDEX["GUIADO FINALIZADO"]:
            raise PermissionError("El guiador/entregador solo puede reasignarse mientras el guiado está pendiente o en curso")
        old_value = order[field] or ""
        connection.execute(f"UPDATE orders SET {field} = ?, app_status = CASE WHEN app_status = 'PENDIENTE' THEN 'ASIGNADO' ELSE app_status END, updated_at = ? WHERE sap_ov = ?", (value, now(), sap_ov))
        role_name = "PICKER" if field == "current_picker" else "GUIADOR"
        connection.execute("INSERT INTO assignments (sap_ov, role, old_user, new_user, username, created_at) VALUES (?, ?, ?, ?, ?, ?)", (sap_ov, role_name, old_value, value, username, now()))
        write_history(connection, sap_ov, "ASIGNACION", field, old_value, value, username)


HTML = r"""
<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>TRITON WMS · Despacho</title><link rel="icon" href="/icon.svg" type="image/svg+xml"><link rel="apple-touch-icon" href="/assets/triton-wms-app-icon.png">
<style>
:root{--orange:#f58200;--orange-dark:#d96e00;--ink:#343a40;--ink-deep:#252a2f;--bg:#eef1f3;--panel:#fff;--line:#dce1e5;--text:#343a40;--muted:#6e7881;--green:#179b61;--blue:#2775a8;--purple:#6568a8;--yellow:#c98400}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Arial,sans-serif}
/* ── Base de botones — los estilos se limitan a controles accionables ── */
.btn,.primary,.dark,.ghost{display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:8px;padding:10px 16px;font-size:14px;font:inherit;font-weight:600;min-height:44px;cursor:pointer;white-space:nowrap;line-height:1.2;background:#fff;color:var(--ink)}
 .toolbar button,.actions button{display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:8px;padding:10px 16px;font-size:14px;font:inherit;font-weight:600;min-height:44px;cursor:pointer;white-space:nowrap;line-height:1.2;background:#fff;color:var(--ink)}
.btn:focus-visible,.primary:focus-visible,.dark:focus-visible,.ghost:focus-visible,.toolbar button:focus-visible{outline:3px solid var(--orange);outline-offset:2px}
.primary,.actions button{background:var(--orange);border-color:var(--orange);color:#fff}
.primary:hover,.actions button:hover{background:var(--orange-dark);border-color:var(--orange-dark)}
.dark,.toolbar button{background:var(--ink);border-color:var(--ink);color:#fff}
.dark:hover,.toolbar button:hover{background:var(--ink-deep);border-color:var(--ink-deep)}
.ghost{background:transparent;border-color:var(--line);padding:11px 13px;font-size:14px}
.ghost:hover{background:#f4f6f8}
.actions button:disabled{opacity:.35;cursor:not-allowed}
/* ── Top bar ── */
.top{min-height:64px;background:#fff;border-top:5px solid var(--orange);border-bottom:1px solid var(--line);display:flex;align-items:center;padding:10px 22px;gap:12px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:12px;min-width:260px}.brand img{width:118px;height:auto;display:block}.brand strong{display:block;font-size:18px;letter-spacing:.1px}.brand span{display:block;margin-top:2px;color:var(--muted);font-size:11px;letter-spacing:1.1px;text-transform:uppercase}
.toolbar{display:flex;flex-direction:column;gap:8px;align-items:stretch;margin-left:auto;flex:1 1 100%;width:100%}
.toolbar-context,.toolbar-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap;width:100%}.toolbar-actions{justify-content:flex-end}
.toolbar select,.toolbar input{border:1px solid var(--line);border-radius:8px;padding:10px 13px;font-size:15px;background:#fff;color:var(--ink);min-height:44px;font:inherit}
.toolbar input{min-width:220px}
#importButton{background:var(--orange);border-color:var(--orange);color:#fff}
/* ── Layout ── */
.layout{display:grid;grid-template-columns:minmax(310px,.78fr) minmax(0,1.72fr);min-height:calc(100vh - 64px)}
.list{background:#fff;border-right:1px solid var(--line);overflow:auto}
.row{padding:16px 20px;border-bottom:1px solid var(--line);cursor:pointer;position:relative;padding-right:78px}
.row:hover,.row.active{background:#fff7ec;box-shadow:inset 4px 0 0 var(--orange)}
.row h3{margin:0;color:var(--ink);font-size:20px}.row p{margin:5px 0;color:#56616b}
.badge{display:inline-block;padding:4px 9px;border-radius:12px;font-size:11px;font-weight:bold;background:#edf0f2;color:#53606a}
.badge.pendiente,.badge.asignado{background:#fff3d6;color:#a66a00}
.badge.en-picking,.badge.en-guiado{background:#e1f5e9;color:#11733f}
.badge.picking-finalizado,.badge.por-guiar,.badge.guiado-finalizado{background:#e2f0fa;color:#1e6999}
.badge.entregado{background:#dff4e8;color:#11733f}
.badge.cerrado-sap{background:#e8ecef;color:#53606a}
/* ── Botones de acción circulares en la fila ── */
.state-action{position:absolute;right:18px;top:50%;transform:translateY(-50%);width:44px;height:44px;border-radius:50%;border:0;color:#fff;font-size:22px;line-height:44px;text-align:center;cursor:pointer;box-shadow:0 3px 10px #26323c33;flex-shrink:0}
.state-action.start{background:var(--green)}.state-action.finish{background:var(--blue)}.state-action.guide{background:var(--purple)}.state-action.disabled{background:#c9d0d5;cursor:default;opacity:.8}
/* ── Detalle ── */
.detail{padding:28px;overflow:auto}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px;margin-bottom:16px;box-shadow:0 4px 14px #26323c0d}
.title{display:flex;justify-content:space-between;gap:14px;align-items:start}.title h1{margin:0;color:var(--ink)}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:16px}
.label{color:var(--muted);font-size:12px;font-weight:bold;letter-spacing:.4px}.value{font-size:16px;margin-top:4px}
 .actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}.actions button{min-height:44px;font-size:14px;padding:10px 16px}
/* Botones de acción circulares en el panel de detalle */
.detail-state-action{width:64px;height:64px;border-radius:50%;border:0;color:#fff;font-size:30px;cursor:pointer;box-shadow:0 3px 12px #26323c33;flex:0 0 auto}
.tablewrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line)}th{color:var(--ink);font-size:12px}
.empty{color:var(--muted);padding:40px;text-align:center}
/* ── Toast ── */
.operation-toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%) translateY(20px);background:var(--ink);color:#fff;padding:12px 22px;border-radius:10px;font-size:14px;opacity:0;pointer-events:none;transition:opacity .25s,transform .25s;z-index:50;max-width:90vw;text-align:center}
.operation-toast.visible{opacity:1;transform:translateX(-50%) translateY(0)}.operation-toast.error{background:#b43c36}.operation-toast.success{background:var(--green)}
/* ── Welcome / homepage ── */
.welcome{display:grid;grid-template-columns:1.1fr .9fr;gap:24px;min-height:340px;background:linear-gradient(135deg,#303940,#20262b);color:#fff;border-radius:18px;padding:38px;overflow:hidden;position:relative;box-shadow:0 12px 28px #26323c26}
.eyebrow{display:inline-block;color:#ffb35a;font-size:12px;font-weight:bold;letter-spacing:1.7px}.welcome h1{font-size:35px;line-height:1.08;margin:12px 0}.welcome p{max-width:500px;color:#d3d9dc;font-size:15px;line-height:1.55}
.warehouse-art{align-self:center;justify-self:end;width:100%;max-width:340px;padding:10px}.warehouse-art svg{display:block;width:100%;height:auto}
.quick-flow{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:18px}
.flow-step{background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px;box-shadow:0 3px 10px #26323c0b}.flow-step b{display:block;color:var(--orange);font-size:19px}.flow-step span{display:block;color:var(--muted);font-size:12px;margin-top:4px}
.welcome-note{margin-top:12px;font-size:12px;color:#afbbc1}
/* ── Reporte ── */
.report-section-title{display:flex;justify-content:space-between;gap:12px;align-items:start;margin-bottom:14px}
.alert-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:14px}
.alert-tile{border:1px solid var(--line);border-radius:12px;padding:14px;text-align:center;cursor:pointer;background:#fff;display:flex;flex-direction:column;align-items:center;gap:4px}
.alert-tile b{font-size:26px;display:block}.alert-tile span{font-size:13px;font-weight:600}.alert-tile small{font-size:11px;color:var(--muted)}
.alert-tile.attention{border-color:#ffd080;background:#fffbf0}.alert-tile.guide{border-color:#b3d8f0;background:#f0f8ff}
.alert-tile.delivery{border-color:#a8e6c8;background:#f0fff8}.alert-tile.stock{border-color:#f0b3a4;background:#fff8f6}
.status-chart{margin-top:10px}.status-chart-row{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.status-chart-row span:first-child{min-width:120px;font-size:12px;color:var(--muted);text-align:right}
.status-chart-track{flex:1;height:18px;background:#edf0f2;border-radius:9px;overflow:hidden}
.status-chart-track i{display:block;height:100%;background:var(--orange);border-radius:9px;transition:width .3s}
.status-chart-count{min-width:28px;font-size:12px;font-weight:bold;text-align:left}
.report-alerts{margin-bottom:16px}.sap-summary{font-size:12px;color:var(--muted);word-break:break-all}
.section-note{font-size:12px;color:var(--muted);margin:4px 0 0}.sku{font-family:monospace;font-size:12px}
.optional-data{margin-top:18px;border-top:1px solid var(--line);padding-top:13px}.optional-data summary{cursor:pointer;color:var(--blue);font-size:13px;font-weight:700;min-height:32px;display:flex;align-items:center}.optional-data[open] summary{margin-bottom:12px}.grid.compact{margin-top:0;padding:14px;border-radius:10px;background:#f7f9fa}.line-origin.aereo{background:#e7f3fb;color:#17658f}.line-origin.maritimo{background:#e9eef8;color:#46558e}.line-origin.stock{background:#e6f4ec;color:#167044}
/* ── Botón flotante para toggle de lista en móvil ── */
.list-toggle{display:none;align-items:center;gap:6px;background:var(--orange);color:#fff;border:0;border-radius:24px;padding:12px 18px;font-size:14px;font-weight:700;cursor:pointer;min-height:48px;position:fixed;bottom:20px;right:18px;z-index:25;box-shadow:0 4px 16px #f5820055}
.list-overlay{display:none;position:fixed;inset:0;background:#00000040;z-index:14}.list-overlay.open{display:block}
/* Botón "← Volver" dentro del detalle */
 .back-to-list{display:none;align-items:center;gap:5px;background:transparent;border:1px solid var(--line);border-radius:8px;padding:9px 14px;font-size:14px;font-weight:600;cursor:pointer;color:var(--ink);min-height:44px;margin-bottom:12px;font:inherit}
 .user-modal{position:fixed;inset:0;display:none;align-items:center;justify-content:center;padding:18px;background:#17202766;z-index:70}.user-modal.open{display:flex}.user-modal-card{width:min(620px,100%);max-height:min(90vh,720px);overflow:auto;background:#fff;border:1px solid #dce3e7;border-radius:16px;box-shadow:0 18px 50px #17202738;padding:22px}.user-modal-head{display:flex;align-items:start;justify-content:space-between;gap:16px;margin-bottom:18px}.user-modal-head h2{margin:0;font-size:22px;color:var(--ink)}.user-modal-close{width:42px;height:42px;border:1px solid var(--line);border-radius:50%;background:#fff;color:var(--ink);font-size:22px;cursor:pointer}.user-form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.user-form-grid label{display:grid;gap:6px;color:var(--muted);font-size:12px;font-weight:800}.user-form-grid input,.user-form-grid select{min-height:44px;border:1px solid var(--line);border-radius:9px;padding:10px 12px;font:inherit;color:var(--ink);background:#fff}.user-form-grid input:focus,.user-form-grid select:focus{outline:0;border-color:var(--orange);box-shadow:0 0 0 3px #f5820020}.user-modal-actions{display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap;margin-top:20px}.user-modal-note{margin:0 0 16px;color:var(--muted);font-size:13px;line-height:1.45}
/* ── Media queries ── */
@media(max-width:1050px){.welcome{grid-template-columns:1fr}.warehouse-art{display:none}.quick-flow{grid-template-columns:repeat(2,1fr)}}
@media(max-width:900px){
  .layout{grid-template-columns:1fr}
  .list{border-right:0;position:fixed;top:0;left:0;bottom:0;width:88vw;max-width:360px;z-index:15;overflow-y:auto;transform:translateX(-105%);transition:transform .25s ease;box-shadow:4px 0 24px #26323c22}
  .list.open{transform:translateX(0)}
  .detail{border-top:1px solid var(--line);padding:16px}
  .grid{grid-template-columns:repeat(2,1fr)}
  .top{padding:10px 14px;gap:8px}
  .toolbar{margin-left:0;width:100%}.toolbar-context>*{flex:1 1 140px;min-width:0}.toolbar-actions{justify-content:stretch}.toolbar-actions button{flex:1 1 140px}
  .toolbar input{min-width:120px;font-size:15px}
  .welcome{padding:24px}.welcome h1{font-size:28px}
  .alert-grid{grid-template-columns:repeat(2,1fr)}
  .list-toggle{display:flex}
  .back-to-list{display:inline-flex}
}
@media(max-width:820px){
  .top{padding:8px 12px;gap:6px}.brand{min-width:0;gap:8px}.brand img{width:94px}.brand strong{font-size:16px}.brand span{font-size:9px}.toolbar{gap:6px}.toolbar-context{gap:6px}.toolbar-context #user{display:none}.toolbar-context #moduleSelector,.toolbar-context #role{flex:1 1 calc(50% - 3px)}.toolbar-context #search{flex:1 1 100%;order:3}.toolbar-context .creation-date-filter{order:4;flex:1 1 100%;justify-content:space-between}.toolbar-context .creation-date-filter input{width:auto;flex:0 1 180px}.toolbar-actions{gap:6px}.toolbar-actions button{flex:1 1 120px;padding:9px 10px}.layout{min-height:calc(100vh - 54px)}
  .toolbar button{min-height:44px}
  .toolbar input,.toolbar select{font-size:16px;min-height:44px}
  .list{width:min(88vw,360px)}
  .detail-state-action{width:56px;height:56px;font-size:24px}
  .actions{align-items:stretch}
  .actions button{min-height:44px;max-width:100%;white-space:normal}
}
@media(max-width:820px){.user-form-grid{grid-template-columns:1fr}.user-modal{padding:10px}.user-modal-card{padding:17px;border-radius:13px}.user-modal-actions button{flex:1 1 140px}.list:not(.open){pointer-events:none}.detail{overflow:visible}.list.open{overflow-y:auto}.list-toggle{bottom:14px;right:14px}}
 </style></head><body><div class="list-overlay" id="listOverlay" onclick="closeList()"></div><button class="list-toggle" id="listToggle" type="button" aria-controls="list" aria-expanded="false" onclick="toggleList()"><span id="listToggleText">☰ Ver lista</span></button><header class="top"><div class="brand"><img src="/assets/triton-logo.png" alt="Triton"><div><strong>Triton Picking</strong><span>Operaciones de almacén</span></div></div><div class="toolbar"><div class="toolbar-context"><input id="user" value="demo.admin" placeholder="Usuario asignado" title="Escribe el mismo usuario al que el administrador asignó la OV"><input id="search" placeholder="Escanear o buscar OV, cliente o artículo" title="Escanea un código o escribe una OV y presiona Enter para abrirla"><select id="role"><option>ADMINISTRADOR</option><option>PICKER</option><option>GUIADOR</option></select></div><div class="toolbar-actions" hidden><button onclick="loadOrders()">Actualizar</button></div></div></header><main class="layout"><section class="list" id="list"><div class="empty">Cargando órdenes…</div></section><section class="detail" id="detail"><div id="adminWelcome"><div class="welcome"><div><span class="eyebrow">TRITON · CONTROL OPERATIVO</span><h1>Almacén en movimiento.<br>Atenciones bajo control.</h1><p>Organiza el picking, guiado y entrega de cada orden de venta en un solo flujo trazable.</p><div class="welcome-note">Selecciona una OV para ver líneas, responsables, cantidades e historial.</div></div><div class="warehouse-art"><svg viewBox="0 0 420 250" role="img" aria-label="Flujo operativo: asignar, preparar, guiar y entregar"><g fill="none" stroke-linecap="round" stroke-linejoin="round" stroke-width="5"><path d="M43 169H373" stroke="#3e4a52"/><path d="M92 169h45m14 0h45m14 0h45m14 0h45" stroke="#ff9b22"/><path d="m126 159 10 10-10 10m73-20 10 10-10 10m73-20 10 10-10 10" stroke="#ff9b22"/><rect x="31" y="93" width="62" height="56" rx="5" stroke="#dce3e7"/><path d="M31 111h62M52 93v18m20-18v18M46 125h32v15H46z" stroke="#ff9b22"/><circle cx="152" cy="103" r="13" stroke="#dce3e7"/><path d="M132 148c2-19 10-29 20-29s18 10 20 29m-34-14 14 8 15-8" stroke="#ff9b22"/><path d="M202 126h51l13 22h-59l-5-22Zm11 22v12m42-12v12m-43 0h53" stroke="#dce3e7"/><circle cx="220" cy="171" r="7" stroke="#ff9b22"/><circle cx="255" cy="171" r="7" stroke="#ff9b22"/><rect x="305" y="92" width="50" height="57" rx="5" stroke="#dce3e7"/><path d="M318 111h24m-24 14h24m-24 14h15" stroke="#ff9b22"/><circle cx="370" cy="169" r="22" stroke="#179b61"/><path d="m359 169 8 8 15-17" stroke="#179b61"/></g><g fill="#ff9b22" font-family="Arial, sans-serif" font-size="12" font-weight="700" text-anchor="middle"><text x="62" y="66">01</text><text x="152" y="66">02</text><text x="235" y="66">03</text></g><text x="370" y="66" fill="#179b61" font-family="Arial, sans-serif" font-size="12" font-weight="700" text-anchor="middle">04</text><g fill="#dce3e7" font-family="Arial, sans-serif" font-size="11" text-anchor="middle"><text x="62" y="207">ASIGNAR</text><text x="152" y="207">PICKING</text><text x="235" y="207">GUIAR</text><text x="370" y="207">ENTREGAR</text></g></svg></div></div><div class="quick-flow"><div class="flow-step"><b>01</b><span>Asignar responsables</span></div><div class="flow-step"><b>02</b><span>Preparar picking</span></div><div class="flow-step"><b>03</b><span>Guiar despacho</span></div><div class="flow-step"><b>04</b><span>Confirmar entrega</span></div></div></div></section></main>
<script>
let orders=[]; let selected=null; let mutationPending=false; let toastTimer=null;
const $=id=>document.getElementById(id);
document.querySelector('.brand strong').textContent='TRITON WMS';
document.querySelector('.brand span').textContent='Despacho de almacén';
document.querySelector('#role').insertAdjacentHTML('beforeend','<option>PICKER_GUIADOR</option><option>ASISTENTE_RECEPCION</option><option>AUXILIAR_RECEPCION</option>');
document.querySelector('#role').insertAdjacentHTML('beforebegin','<select id="moduleSelector" onchange="changeModule(this.value)"><option value="despacho" selected>Despacho</option><option value="recepcion">Recepción</option></select>');
document.querySelector('.toolbar-context').append($('moduleSelector'),$('role'),$('search'));
document.querySelector('.toolbar-context').insertAdjacentHTML('beforeend','<label class="creation-date-filter" title="Filtrar por fecha de creación de la OV">Fecha OV <input id="creationDate" type="date" aria-label="Fecha de creación de la OV" onchange="loadOrders()"></label>');
document.querySelector('.toolbar-actions').insertAdjacentHTML('beforeend','<button id="reportButton" onclick="showReport()">Reportes</button><button id="workloadButton" onclick="showWorkload()">Carga picker</button><button id="userAdminButton" onclick="showUsers()">Usuarios</button>');
document.querySelector('.toolbar-actions').insertAdjacentHTML('beforeend','<button id="traceButton" onclick="showTraceability()">Trazabilidad</button>');
document.querySelector('.toolbar-actions').insertAdjacentHTML('beforeend','<input id="excelFile" type="file" style="display:none" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onchange="uploadExcel()"><button id="importButton" onclick="$(\'excelFile\').click()">Cargar Excel</button>');
document.querySelector('.toolbar-actions').insertAdjacentHTML('beforeend','<input id="importationFile" type="file" style="display:none" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onchange="uploadImportation()"><button id="importationButton" onclick="$(\'importationFile\').click()">Cargar Importaciones</button>');
document.querySelector('.toolbar-actions').insertAdjacentHTML('beforeend','<button id="moreButton" onclick="showMore()">Más opciones</button>');
document.querySelector('.toolbar-actions').querySelectorAll('button:not(:first-child),input').forEach(element=>{if(element.id!=='moreButton')element.hidden=true});
document.head.insertAdjacentHTML('beforeend','<link rel="manifest" href="/manifest.webmanifest"><meta name="theme-color" content="#f58200">');
document.body.insertAdjacentHTML('beforeend','<div id="operationToast" class="operation-toast" role="status" aria-live="polite"></div>');
document.body.insertAdjacentHTML('beforeend','<nav class="bottom-nav" id="bottomNav" aria-label="Navegación principal"><button class="nav-item active" data-nav="home" type="button" onclick="goHome()"><span class="nav-icon" aria-hidden="true">⌂</span><span>Inicio</span></button><button class="nav-item" data-nav="profile" type="button" onclick="showAccount()"><span class="nav-icon" aria-hidden="true">◉</span><span>Perfil</span></button><button class="nav-item" data-nav="work" type="button" onclick="showMyWork()"><span class="nav-icon" aria-hidden="true">≡</span><span>Mi trabajo</span></button><button class="nav-item" data-nav="more" type="button" onclick="showMore()"><span class="nav-icon" aria-hidden="true">⋯</span><span>Más</span></button></nav>');
document.head.insertAdjacentHTML('beforeend','<style id="triton-bottom-nav">.bottom-nav{position:fixed;left:0;right:0;bottom:0;z-index:22;display:flex;justify-content:center;gap:6px;padding:8px 14px 8px;background:#ffffffee;border-top:1px solid #dce3e7;box-shadow:0 -6px 20px #26323c14;backdrop-filter:blur(10px)}.nav-item{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-width:138px;min-height:48px;padding:9px 14px;border:1px solid transparent;border-radius:10px;background:transparent;color:#6e7881;font-size:13px;font-weight:700;cursor:pointer}.nav-item:hover{background:#f4f7f8;color:#252d33}.nav-item.active{background:#fff4e5;border-color:#ffd7a4;color:#f58200}.nav-item:focus-visible{outline:3px solid #f58200;outline-offset:2px}.nav-icon{font-size:20px;line-height:1;font-weight:400}.detail-grid,.performance-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.detail-grid>div,.performance-grid>div{padding:13px;border:1px solid #dce3e7;border-radius:10px;background:#f8fafb}.detail-grid b,.performance-grid b{display:block;color:#6e7881;font-size:11px;text-transform:uppercase;letter-spacing:.04em}.detail-grid span,.performance-grid span{display:block;margin-top:5px;color:#252d33;font-size:15px;font-weight:700}.performance-grid b{font-size:25px;color:#f58200;letter-spacing:0}.performance-grid span{font-size:12px}@media(max-width:900px){.detail-grid,.performance-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}body{padding-bottom:76px}.operation-toast{bottom:90px!important}@media(max-width:820px){.bottom-nav{justify-content:stretch;gap:4px;padding:6px 8px calc(6px + env(safe-area-inset-bottom))}.nav-item{flex:1;min-width:0;min-height:52px;padding:7px 4px;flex-direction:column;gap:3px;font-size:11px}.list-toggle{bottom:82px!important}}</style>');
document.head.insertAdjacentHTML('beforeend','<style id="triton-creation-date">.creation-date-filter{display:flex;align-items:center;gap:6px;color:#6e7881;font-size:11px;font-weight:700;white-space:nowrap}.creation-date-filter input{min-height:42px;border:1px solid #dce3e7;border-radius:9px;padding:8px 10px;background:#fff;color:#3e4a52;font:inherit;font-weight:600}.creation-meta{color:#6e7881!important;font-size:11px!important;margin:2px 0 5px!important}@media(max-width:820px){.creation-date-filter{flex:1 1 140px}.creation-date-filter input{min-height:44px;font-size:16px;width:100%}}</style>');
if('serviceWorker' in navigator)navigator.serviceWorker.register('/service-worker.js');
function notify(message,variant='success'){const toast=$('operationToast');if(!toast)return;toast.textContent=message;toast.className='operation-toast '+variant;clearTimeout(toastTimer);requestAnimationFrame(()=>toast.classList.add('visible'));toastTimer=setTimeout(()=>toast.classList.remove('visible'),4200)}
function setOperationBusy(busy){
 document.querySelectorAll('.state-action:not(:disabled),.detail-state-action,.actions button:not(:disabled)').forEach(button=>{
  if(busy){button.dataset.operationBusy='1';button.disabled=true}
  else if(button.dataset.operationBusy==='1'){button.disabled=false;delete button.dataset.operationBusy}
 });
 document.body.classList.toggle('operation-busy',busy);
}
function currentUserName(){return $('user').value.trim()||('demo.'+$('role').value.toLowerCase())}
function apiFetch(url){return fetch(url,{headers:{'X-User':currentUserName(),'X-Role':$('role').value}})}
function changeModule(value){if(value==='recepcion')location.href='/reception'}
function setActiveNav(key){const target=key==='account'?'profile':key;document.querySelectorAll('.nav-item').forEach(item=>item.classList.toggle('active',item.dataset.nav===target))}
function goHome(){setActiveNav('home');blankDetail();renderHomeDashboard()}
function goPending(){showMyWork()}
function renderHomeDashboard(){setActiveNav('home');const active=orders.filter(order=>!['ENTREGADO','CERRADO SAP'].includes(order.active_status||order.app_status)).length;const picking=orders.filter(order=>['ASIGNADO','EN PICKING'].includes(order.active_status||order.app_status)).length;const guide=orders.filter(order=>['POR GUIAR','EN GUIADO'].includes(order.active_status||order.app_status)).length;const delivered=orders.filter(order=>(order.active_status||order.app_status)==='ENTREGADO').length;$('detail').innerHTML=`<section class="card hero"><div class="title"><div><span class="eyebrow">Inicio · Despacho</span><h1>Organiza tu jornada.</h1><p>Selecciona una OV para revisar cantidades, responsables y avance de atención.</p></div><span class="badge orange">Cola operativa</span></div><div class="performance-grid"><div><b>${orders.length}</b><span>OV visibles</span></div><div><b>${active}</b><span>Pendientes</span></div><div><b>${picking}</b><span>En picking</span></div><div><b>${guide}</b><span>Por guiar</span></div></div><div class="notice">Empieza en <strong>Mi trabajo</strong> para revisar tus pendientes y su estado. Las alertas y herramientas se encuentran en <strong>Más</strong>.</div></section>`}
async function showAccount(){setActiveNav('account');const account={username:currentUserName(),display_name:currentUserName(),role:$('role').value,shift:'',document_id:'',first_name:'',last_name:''};try{const response=await fetch('/api/account',{headers:{'X-User':currentUserName(),'X-Role':$('role').value}});const data=await response.json();if(response.ok)Object.assign(account,data)}catch(error){}$('detail').innerHTML=`<section class="card account-card"><div class="section-title"><div><span class="eyebrow">Perfil operativo</span><h2>Mi cuenta</h2></div><span class="badge green">Sesión activa</span></div><div class="detail-grid"><div><b>Nombre visible</b><span>${esc(account.display_name||account.username)}</span></div><div><b>Usuario</b><span>${esc(account.username)}</span></div><div><b>Rol</b><span>${esc(account.role)}</span></div><div><b>Turno</b><span>${esc(account.shift||'No indicado')}</span></div></div><details class="optional-data"><summary>Ver información adicional</summary><div class="detail-grid"><div><b>Nombres</b><span>${esc(account.first_name||'No registrado')}</span></div><div><b>Apellidos</b><span>${esc(account.last_name||'No registrado')}</span></div><div><b>Documento</b><span>${esc(account.document_id||'No registrado')}</span></div></div></details></section>`}
function showMyWork(){setActiveNav('work');const counts=orders.reduce((acc,order)=>{const state=order.active_status||order.app_status||'PENDIENTE';acc.total++;acc[state]=(acc[state]||0)+1;return acc},{});const rows=orders.map(order=>`<tr><td><button class="ghost" type="button" onclick="loadDetail('${esc(order.sap_ov)}')">${esc(order.sap_ov)}</button></td><td>${esc(order.customer_name||'Cliente')}</td><td>${esc(stateLabel(order.active_status||order.app_status||'PENDIENTE'))}</td><td>${qty(order.pending_total||0)}</td></tr>`).join('')||'<tr><td colspan="4">No tienes OV pendientes actualmente.</td></tr>';$('detail').innerHTML=`<section class="card"><div class="section-title"><div><span class="eyebrow">Mi trabajo</span><h2>Pendientes y desempeño</h2></div><span class="badge orange">${orders.length} visible(s)</span></div><div class="performance-grid"><div><b>${counts.total||0}</b><span>OV visibles</span></div><div><b>${counts['EN PICKING']||0}</b><span>En picking</span></div><div><b>${counts['POR GUIAR']||0}</b><span>Por guiar</span></div><div><b>${counts.ENTREGADO||0}</b><span>Entregadas</span></div></div><div class="tablewrap"><table><thead><tr><th>OV</th><th>Cliente</th><th>Estado</th><th>Pendiente</th></tr></thead><tbody>${rows}</tbody></table></div><div class="notice">Los indicadores históricos y metas se consultan en Reportes cuando el usuario tiene permisos de administrador.</div></section>`}
function showMore(){setActiveNav('more');const admin=$('role').value==='ADMINISTRADOR';const excelHelp=admin?'<div class="notice"><strong>Formato del corte diario.</strong> El archivo puede tener cualquier nombre de pestañas. El WMS reconoce OVs por sus columnas de documento y artículo; reconoce stock por <strong>Número de artículo</strong> y <strong>En stock</strong>. Recomendación: nombra las hojas <strong>ovs</strong> y <strong>stock</strong>. No necesitas convertirlas en tabla de Excel.</div>':'';$('detail').innerHTML=`<section class="card"><div class="section-title"><div><span class="eyebrow">Herramientas</span><h2>Más opciones</h2></div></div><div class="more-actions"><button class="dark" type="button" onclick="loadOrders()">Actualizar cola</button>${admin?'<button class="dark" type="button" onclick="showReport()">Reportes</button><button class="dark" type="button" onclick="showWorkload()">Indicadores de carga</button><button class="dark" type="button" onclick="showUsers()">Usuarios</button><button class="dark" type="button" onclick="showTraceability()">Trazabilidad</button><button class="primary" type="button" onclick="$(\'excelFile\').click()">Cargar Excel</button><button class="dark" type="button" onclick="$(\'importationFile\').click()">Cargar importaciones</button>':''}<button class="dark" type="button" onclick="showNotices()">Avisos</button></div>${excelHelp}${admin?'':'<div class="notice">Las funciones administrativas solo están disponibles para el administrador.</div>'}</section>`}
function showNotices(){setActiveNav('more');const alerts=orders.filter(order=>order.picking_blocked||Number(order.stock_shortage_lines||0)>0||['PENDIENTE','ASIGNADO'].includes(order.active_status||order.app_status));const rows=alerts.map(order=>`<tr><td><button class="ghost" type="button" onclick="loadDetail('${esc(order.sap_ov)}')">${esc(order.sap_ov)}</button></td><td>${order.picking_blocked?'Recepción pendiente':Number(order.stock_shortage_lines||0)>0?'Stock parcial':'Pendiente de atención'}</td><td>${esc(stateLabel(order.active_status||order.app_status||'PENDIENTE'))}</td></tr>`).join('')||'<tr><td colspan="3">No hay avisos operativos.</td></tr>';$('detail').innerHTML=`<section class="card"><div class="section-title"><div><span class="eyebrow">Control operativo</span><h2>Avisos de Despacho</h2></div><span class="badge orange">${alerts.length}</span></div><div class="tablewrap"><table><thead><tr><th>OV</th><th>Aviso</th><th>Estado</th></tr></thead><tbody>${rows}</tbody></table></div></section>`}
async function initializeIdentity(){
 const r=await fetch('/api/me'); if(r.ok){const me=await r.json();window.installSessionControls?.(me);if(me.mode!=='demo'){$('user').value=me.username;$('user').disabled=true;$('role').value=me.role;$('role').disabled=true;}}else{return}
 applyRoleInterface();
 await loadOrders();
 renderHomeDashboard();
}
function blankDetail(){
 closeList();
 $('detail').innerHTML='<div class="empty">Selecciona una OV para ver sus líneas, responsables e historial.</div>';
}
function applyRoleInterface(){
 const role=$('role').value;
 if(['ASISTENTE_RECEPCION','AUXILIAR_RECEPCION'].includes(role)){location.href='/reception';return}
 const isAdmin=$('role').value==='ADMINISTRADOR';
 $('moduleSelector').innerHTML=isAdmin?'<option value="despacho" selected>Despacho</option><option value="recepcion">Recepción</option>':'<option value="despacho" selected>Despacho</option>';
 $('importButton').hidden=true;
 $('userAdminButton').hidden=true;
 $('workloadButton').hidden=true;
 $('importationButton').hidden=true;
 $('traceButton').hidden=true;
 $('reportButton').hidden=true;
 $('moreButton').hidden=false;
 if(selected)return;
 const welcome=$('adminWelcome');
 if(!isAdmin || localStorage.getItem('triton-admin-welcome-seen')==='1'){
  if(welcome)blankDetail();
  return;
 }
 localStorage.setItem('triton-admin-welcome-seen','1');
}
function esc(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function cls(v){return v.toLowerCase().replaceAll(' ','-')}
let orderRequest=0; async function loadOrders(){const request=++orderRequest;try{const q=$('search').value;const date=$('creationDate')?.value||'';const dateEnd=$('creationDateEnd')?.value||'';const r=await apiFetch('/api/orders?search='+encodeURIComponent(q)+'&date='+encodeURIComponent(date)+'&date_end='+encodeURIComponent(dateEnd));const data=await r.json();if(request!==orderRequest)return orders;if(!r.ok)throw new Error(data.error||'No se pudo cargar la cola');orders=data;renderList();if(selected)await loadDetail(selected);window.refreshDailyStatus?.();return orders}catch(error){notify(error.message||'Sin conexión con el servidor','error');return []}}
async function openScannedOrder(){
 const value=$('search').value.trim();
 if(!value)return;
 await loadOrders();
 const visible=orders.filter(visibleForRole);
 const normalized=value.toLocaleLowerCase();
 const exact=visible.find(order=>String(order.sap_ov).toLocaleLowerCase()===normalized);
 const target=exact||(visible.length===1?visible[0]:null);
 if(target){await loadDetail(target.sap_ov);return;}
 if(!visible.length)notify('No se encontró una OV disponible para este código.','error');
 else notify('El código coincide con más de una OV. Selecciona la orden de la lista.','error');
}
function sameUser(first,second){return String(first||'').trim().toLocaleLowerCase()===String(second||'').trim().toLocaleLowerCase()}
function visibleForRole(o){const role=$('role').value;const user=currentUserName();const s=o.active_status||o.app_status;if(role==='ADMINISTRADOR')return true;if(role==='PICKER')return ['ASIGNADO','EN PICKING','POR GUIAR'].includes(s)&&sameUser(o.current_picker,user);if(role==='GUIADOR')return ['POR GUIAR','EN GUIADO','GUIADO FINALIZADO'].includes(s)&&sameUser(o.current_guide,user);if(role==='PICKER_GUIADOR')return (['ASIGNADO','EN PICKING','POR GUIAR'].includes(s)&&sameUser(o.current_picker,user))||(['POR GUIAR','EN GUIADO','GUIADO FINALIZADO'].includes(s)&&sameUser(o.current_guide,user));return true}
function stockSignal(o){const shortageLines=Number(o.stock_shortage_lines||0);if(shortageLines){const qty=Number(o.stock_shortage_qty||0);return `<span class="stock-signal shortage" title="${shortageLines} SKU con disponibilidad menor a lo pendiente">Stock parcial · faltan ${qty}</span>`}return '<span class="stock-signal ready">Stock completo</span>'}
function stateLabel(value){return ({'PENDIENTE':'PENDIENTE','ASIGNADO':'ASIGNADO','EN PICKING':'EN PICKING','PICKING FINALIZADO':'PICKING FINALIZADO','POR GUIAR':'POR GUIAR','EN GUIADO':'EN GUIADO','GUIADO FINALIZADO':'GUIADO FINALIZADO','ENTREGADO':'ENTREGADO','CERRADO SAP':'CERRADO SAP'}[value]||value||'SIN ESTADO')}
function transportLabel(value){return String(value||'').replaceAll('AEREO','AÉREO').replaceAll('MARITIMO','MARÍTIMO')}
function normalizeCode(value){return String(value??'').toUpperCase().replace(/[^A-Z0-9]/g,'')}
function lineCategory(line,order){const code=normalizeCode(line.item_code);const match=(order.line_categories||[]).find(item=>normalizeCode(item.item_code)===code);return match||{classification:'STOCK',transport_type:'STOCK',bl_awb:''}}
function lineOriginLabel(line,order){const item=lineCategory(line,order);const label=item.classification==='AEREO'?'AÉREO':item.classification==='MARITIMO'?'MARÍTIMO':item.classification==='STOCK'?'STOCK':'SIN DEFINIR';const details=item.bl_awb?` · ${esc(item.bl_awb)}`:'';return `<span class="badge line-origin ${item.classification.toLowerCase()}" title="${esc(item.transport_type||label)}${details}">${label}</span>`}
function qty(value){const amount=Number(value||0);return Number.isInteger(amount)?amount:amount.toFixed(2)}
function orderAdditionalInfo(o){return `<details class="optional-data"><summary>Información adicional de la OV</summary><div class="grid compact"><div><div class="label">BL / AWB IMPORTACIÓN</div><div class="value">${esc(o.bl_awb||'—')}</div></div><div><div class="label">ESTADO RECEPCIÓN</div><div class="value">${esc(o.reception_status||'NO IDENTIFICADA')}</div></div><div><div class="label">FECHA Y HORA DE CREACIÓN OV</div><div class="value">${esc(o.source_order_date||'—')}</div></div><div><div class="label">DESTINO</div><div class="value">${esc(o.destination||'—')}</div></div><div><div class="label">STATUS DOCUMENTO SAP</div><div class="value">${esc(o.document_status||'Sin información')}</div></div><div><div class="label">ESTADO DE SKU EN SAP</div><div class="value sap-summary">${esc(o.sap_status_summary||'Sin información')}</div></div></div></details>`}
function inventoryAdditionalInfo(o){return `<details class="optional-data"><summary>Información adicional de stock</summary><p class="section-note">El saldo procede únicamente del corte Excel de stock. Importaciones identifica compromisos por OV y no suma unidades.</p><div class="tablewrap"><table><thead><tr><th>Artículo</th><th>Grupo</th><th>Almacén</th><th>Cantidad fuente</th><th>Reservado global</th><th>Consumido</th></tr></thead><tbody>${o.lines.map(line=>`<tr><td class="sku">${esc(line.item_code)}</td><td>${esc(line.article_group||'—')}</td><td>${esc(line.warehouse||'—')}</td><td>${qty(line.stock_source_qty)}</td><td>${qty(line.stock_reserved_qty)}</td><td>${qty(line.stock_consumed_qty)}</td></tr>`).join('')}</tbody></table></div></details>`}
function attendedLinesInfo(o){const lines=o.attended_lines||[];if(!lines.length)return '';return `<details class="optional-data attended-lines"><summary>Ver más: ${lines.length} línea${lines.length===1?'':'s'} atendida${lines.length===1?'':'s'} en SAP</summary><p class="section-note">Estas líneas ya fueron atendidas según el último corte SAP y no se pueden volver a picar. Se muestran para conservar el contexto completo de la OV.</p><div class="tablewrap"><table><thead><tr><th>Artículo</th><th>Descripción</th><th>Estado SAP</th><th>Requerida</th><th>Cantidad atendida</th></tr></thead><tbody>${lines.map(line=>`<tr><td class="sku">${esc(line.item_code)}</td><td>${esc(line.description||'—')}</td><td><span class="line-state done">${esc(line.sap_line_status||'ATENDIDO EN SAP')}</span></td><td>${qty(line.required_qty)}</td><td>${qty(Math.max(0,Number(line.required_qty||0)-Number(line.pending_qty||0)))}</td></tr>`).join('')}</tbody></table></div></details>`}
function importationSignal(o){if(o.reception_status==='PENDIENTE PARCIAL')return '<span class="stock-signal shortage">Importación parcialmente pendiente</span>';const transport=String(o.transport_type||'');if(o.picking_blocked)return `<span class="stock-signal blocked" title="${esc(o.picking_block_reason||'Pendiente de recepción')}">${transport.includes('AEREO')?'Aérea':'Importación'} · pendiente Recepción</span>`;if(transport.includes('MARITIMO'))return `<span class="stock-signal ready">${transportLabel(transport)} · liberada</span>`;if(transport.includes('AEREO'))return `<span class="stock-signal ready">${transportLabel(transport)} · recepción liberada</span>`;return ''}
function customerTag(o){const internal=String(o.customer_name||'').trim().toLocaleLowerCase().startsWith('triton trading');return `<span class="customer-tag ${internal?'internal':'external'}">${internal?'Cliente interno':'Cliente regular'}</span>`}
function sapIndicators(o){const documentStatus=esc(o.document_status||'Sin estado');const pending=Number(o.sap_open_sku_count||0);const attended=Number(o.sap_attended_sku_count||0);const transport=o.transport_type&&o.transport_type!=='SIN DEFINIR'?`<span>Origen: <b>${esc(transportLabel(o.transport_type))}</b></span>`:'';return `<div class="sap-indicators"><span>Doc. SAP: <b>${documentStatus}</b></span><span>${pending} SKU pendiente${pending===1?'':'s'} · ${attended} atendido${attended===1?'':'s'}</span>${transport}</div>`}
function creationLabel(value){return value?`Creada ${String(value).replace('T',' ')}`:'Creación sin fecha'}
function renderList(){
 const q=$('search').value.toLowerCase();const filter=$('statusFilter')?.value||'ALL';
 const available=orders.filter(o=>visibleForRole(o)&&JSON.stringify(o).toLowerCase().includes(q));
 const rows=filter==='ALL'?available:filter==='STOCK_PARCIAL'?available.filter(o=>Number(o.stock_shortage_lines||0)>0):available.filter(o=>(o.active_status||o.app_status)===filter);
 const filters=['ALL','STOCK_PARCIAL',...statuses]; const roleLabel=$('role').value==='ADMINISTRADOR'?'Cola operativa':$('role').value==='PICKER'?'Mi cola de picking':'Mi cola de guiado';
 const filterLabel=value=>value==='ALL'?'Todas':value==='STOCK_PARCIAL'?'Stock parcial':value;
 const controls=`<div class="queue-controls"><div><span class="queue-label">${roleLabel}</span><strong>${rows.length} ${rows.length===1?'OV visible':'OVs visibles'}</strong></div><label class="queue-filter">Etapa <select id="statusFilter" onchange="renderList()">${filters.map(value=>`<option value="${value}" ${filter===value?'selected':''}>${filterLabel(value)}</option>`).join('')}</select></label></div>`;
 const content=rows.length?rows.map(o=>{const status=o.active_status||o.app_status;return `<div class="row state-${cls(status)} ${selected===o.sap_ov?'active':''}" onclick="loadDetail('${esc(o.sap_ov)}')"><h3>${esc(o.sap_ov)}</h3><p>${customerTag(o)}${esc(o.customer_name)} · ${o.line_count} líneas</p><p class="creation-meta">${esc(creationLabel(o.source_order_date))}</p>${sapIndicators(o)}<span class="badge ${cls(status)}">${esc(status)}</span><span class="badge">${esc(o.attention_type)}</span>${importationSignal(o)}${stockSignal(o)}${listAction(o)}</div>`}).join(''):'<div class="empty">No hay órdenes para este filtro</div>';
 $('list').innerHTML=controls+content;
}
function updateListToggle(){const open=$('list').classList.contains('open');$('listToggleText').textContent=open?'✕ Cerrar lista':'☰ Ver lista';$('listToggle').setAttribute('aria-expanded',String(open))}
function openList(){$('list').classList.add('open');$('listOverlay').classList.add('open');updateListToggle()}
function closeList(){$('list').classList.remove('open');$('listOverlay').classList.remove('open');updateListToggle()}
function toggleList(){if($('list').classList.contains('open'))closeList();else openList()}
function focusQueue(filter){
 selected=null; const statusFilter=$('statusFilter'); if(statusFilter)statusFilter.value=filter;
 renderList();blankDetail();document.querySelector('.list').scrollTo({top:0,behavior:'smooth'});
 if(window.innerWidth<900)document.querySelector('.list').scrollIntoView({behavior:'smooth',block:'start'});
}
function listAction(o){const role=$('role').value;const s=o.active_status||o.app_status;const combined=role==='PICKER_GUIADOR';let next=null,kind='disabled',title='Solo el responsable puede avanzar';if(o.picking_blocked){title=o.picking_block_reason||'Bloqueada hasta registrar recepción';return `<button class="state-action disabled" title="${esc(title)}" aria-label="${esc(title)}" disabled>•</button>`}if((role==='PICKER'||combined)&&s==='ASIGNADO'){next='EN PICKING';kind='start';title='Iniciar picking'}if((role==='PICKER'||combined)&&s==='EN PICKING'){next='PICKING FINALIZADO';kind='finish';title='Finalizar picking'}if(role==='PICKER'&&s==='POR GUIAR'){title='Picking finalizado; esperando guiado'}if((role==='GUIADOR'||combined)&&s==='POR GUIAR'){next='EN GUIADO';kind='guide';title='Iniciar guiado'}if((role==='GUIADOR'||combined)&&s==='EN GUIADO'){next='GUIADO FINALIZADO';kind='finish';title='Finalizar guiado'}return `<button class="state-action ${kind}" title="${esc(title)}" ${next?`onclick="event.stopPropagation();advanceActive('${next}')"`:'disabled'}>${next?'▶':'•'}</button>`}
async function loadDetail(ov){
 selected=ov;renderList();
 const r=await apiFetch('/api/orders/'+encodeURIComponent(ov));
 const o=await r.json();
 if(!r.ok)throw new Error(o.error||'No se pudo cargar la OV');
 closeList();
 const role=$('role').value;const next=nextStatus(o.app_status);
 const historyCard=role==='ADMINISTRADOR'?`<div class="card"><h2>Historial</h2>${o.history?.length?`<div class="tablewrap"><table><thead><tr><th>Fecha</th><th>Evento</th><th>Campo</th><th>Cambio</th><th>Usuario</th></tr></thead><tbody>${o.history.map(h=>`<tr><td>${esc(h.created_at)}</td><td>${esc(h.event_type)}</td><td>${esc(h.field_name)}</td><td>${esc(h.old_value)} → ${esc(h.new_value)}</td><td>${esc(h.username)}</td></tr>`).join('')}</tbody></table></div>`:'<p class="label">Sin cambios todavía.</p>'}</div>`:'';
 const blockNotice=o.picking_blocked?`<div class="notice error"><strong>Picking bloqueado.</strong> ${esc(o.picking_block_reason||'La OV aérea aún no tiene recepción liberada.')} El administrador podrá asignarla cuando Recepción registre el arribo.</div>`:'';
 $('detail').innerHTML='<button class="back-to-list" type="button" onclick="openList()">← Volver a la lista</button>'+`<div class="card order-summary"><div class="title"><div><div class="label">ORDEN DE VENTA</div><h1>${esc(o.sap_ov)}</h1></div><span class="badge ${cls(o.app_status)}">${esc(o.app_status)}</span></div><div class="grid"><div><div class="label">CLIENTE</div><div class="value">${esc(o.customer_name)}</div></div><div><div class="label">TIPO DE ATENCIÓN</div><div class="value">${esc(o.attention_type)}</div></div><div><div class="label">PICKER</div><div class="value">${esc(o.current_picker)||'Sin asignar'}</div></div><div><div class="label">GUIADOR / ENTREGADOR</div><div class="value">${esc(o.current_guide)||'Sin asignar'}</div></div><div><div class="label">ORIGEN DE ABASTECIMIENTO</div><div class="value">${esc(transportLabel(o.transport_type||'STOCK'))}</div></div><div><div class="label">SITUACIÓN MÁQUINA</div><div class="value">${esc(o.source_status)||'Sin información'}</div></div></div>${orderAdditionalInfo(o)}${blockNotice}<div class="actions"><button onclick="assign('current_picker')" ${role==='ADMINISTRADOR'&&!o.picking_blocked?'':'disabled'}>${o.current_picker?'Cambiar picker':'Asignar picker'}</button><button onclick="assign('current_guide')" ${role==='ADMINISTRADOR'?'':'disabled'}>${o.current_guide?'Cambiar guiador / entregador':'Asignar guiador / entregador'}</button>${next?`<button onclick="advance('${next}')" ${o.picking_blocked?'disabled':''}>Pasar a ${esc(next)}</button>`:''}</div></div><div class="card"><h2>SKU pendientes de despacho</h2><p class="section-note">Stock de corte SAP, reservas aéreas y saldo libre por artículo.</p><div class="tablewrap"><table><thead><tr><th>Artículo</th><th>Descripción</th><th>Origen</th><th>Requerida</th><th>OVs aéreas</th><th>Stock corte</th><th>Stock libre</th></tr></thead><tbody>${o.lines.map(l=>`<tr><td class="sku">${esc(l.item_code)}</td><td>${esc(l.description)}</td><td>${lineOriginLabel(l,o)}</td><td>${qty(l.required_qty)}</td><td title="${esc((l.stock_aerial_ovs||[]).join(', ')||'Sin OVs aéreas pendientes')}">${qty(l.stock_aerial_ov_count)}${l.stock_aerial_reserved_qty?` <small>(${qty(l.stock_aerial_reserved_qty)} und.)</small>`:''}</td><td>${qty(l.stock_source_qty)}</td><td><strong>${qty(l.stock_free_qty)}</strong></td></tr>`).join('')}</tbody></table>${attendedLinesInfo(o)}${inventoryAdditionalInfo(o)}</div></div>${historyCard}`;
}
document.head.insertAdjacentHTML('beforeend','<style>.state-action{padding:0;display:flex;align-items:center;justify-content:center;line-height:1}.detail-state-action{padding:0;display:flex;align-items:center;justify-content:center;line-height:1}.actions input,.actions select,.tablewrap input{border:1px solid #666;border-radius:6px;padding:10px 12px;background:#fff;color:#171717;min-width:120px}.tablewrap input{padding:6px;min-width:72px;width:90px}.detail-tabs{display:flex;gap:8px;overflow-x:auto;margin:0 0 14px;padding-bottom:2px}.detail-tab{background:#fff;border:1px solid #dce1e5;color:#343a40;padding:10px 14px;white-space:nowrap;font-weight:bold;cursor:pointer}.detail-tab.active{background:#f58200;border-color:#f58200;color:#fff}.detail-tab-panel>.card{margin-top:0}.quantity-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:14px 0}.quantity-metric{border:1px solid #dce1e5;border-radius:9px;padding:11px;background:#f8fafb}.quantity-metric b{display:block;color:#343a40;font-size:20px;margin-top:3px}.progress-summary{margin:12px 0 18px}.progress-heading{display:flex;justify-content:space-between;gap:12px;font-size:13px;color:#56616b;margin-bottom:7px}.progress-track{height:8px;background:#e6eaed;border-radius:99px;overflow:hidden}.progress-track i{display:block;height:100%;background:#f58200;border-radius:inherit}.line-state{font-size:11px;font-weight:bold;white-space:nowrap}.line-state.done{color:#11733f}.line-state.pending{color:#a66a00}@media(max-width:900px){.top{height:auto;min-height:68px;flex-wrap:wrap;padding:10px 14px;gap:10px}.toolbar{margin-left:0;width:100%;flex-wrap:wrap}.toolbar input{min-width:120px;flex:1}.toolbar button{white-space:nowrap}.detail-tabs{position:sticky;top:0;background:#eef1f3;padding-top:4px;z-index:2}.quantity-summary{grid-template-columns:1fr}}</style>');
document.head.insertAdjacentHTML('beforeend','<style>.status-chart{display:grid;gap:11px}.status-chart-row{display:grid;grid-template-columns:minmax(120px,180px) 1fr 34px;align-items:center;gap:10px;font-size:13px}.status-chart-track{height:11px;background:#e6eaed;border-radius:99px;overflow:hidden}.status-chart-track i{display:block;height:100%;background:#f58200;border-radius:inherit}.status-chart-count{text-align:right;font-weight:bold;color:#343a40}</style>');
document.head.insertAdjacentHTML('beforeend','<style id="triton-visual-system">:root{--navy:#252d33;--slate:#3e4a52;--cloud:#f4f7f8;--soft-orange:#fff4e5;--orange:#f58200;--orange-bright:#ff9b22;--green:#179b61;--blue:#2775a8;--purple:#6568a8}.top{position:relative;min-height:84px;padding:12px 26px;gap:20px;box-shadow:0 2px 12px #26323c0a}.top:after{content:"";position:absolute;inset:auto 0 0;height:2px;background:linear-gradient(90deg,var(--orange) 0 22%,#dce3e7 22% 100%)}.brand{min-width:272px}.brand strong{font-weight:800;letter-spacing:-.25px}.toolbar input,.toolbar select,.toolbar button{min-height:42px;border-radius:9px;transition:border-color .15s,box-shadow .15s,transform .15s}.toolbar input:focus,.toolbar select:focus,.actions input:focus,.actions select:focus,.tablewrap input:focus{outline:0;border-color:var(--orange);box-shadow:0 0 0 3px #f5820020}.toolbar button:hover,.actions button:hover{transform:translateY(-1px);box-shadow:0 4px 10px #26323c18}.layout{background:var(--cloud)}.list{background:#fff}.row{min-height:110px;padding:18px 84px 18px 24px;border-bottom:1px solid #e7ecee;transition:background .15s,box-shadow .15s}.row:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:transparent}.row:hover{background:#fffbf6;box-shadow:inset 4px 0 0 var(--orange)}.row.active{background:var(--soft-orange);box-shadow:inset 4px 0 0 var(--orange)}.row.state-pendiente:before,.row.state-asignado:before{background:#f3b928}.row.state-en-picking:before{background:var(--blue)}.row.state-picking-finalizado:before,.row.state-por-guiar:before{background:#66a9d2}.row.state-en-guiado:before,.row.state-guiado-finalizado:before{background:var(--purple)}.row.state-entregado:before{background:var(--green)}.row h3{font-size:22px;letter-spacing:-.4px}.row p{font-size:13px;line-height:1.35}.badge{padding:5px 9px;border-radius:99px;font-size:10px;letter-spacing:.15px}.state-action{width:48px;height:48px;right:22px;border:2px solid #fff;box-shadow:0 5px 15px #26323c26}.state-action:disabled{border-color:#edf1f3}.detail{padding:28px 30px 42px;max-width:1260px;width:100%;margin:0 auto}.card{border-color:#e1e7ea;border-radius:16px;padding:24px;box-shadow:0 6px 18px #26323c0c}.card h2{letter-spacing:-.45px;font-size:23px;margin:0 0 17px}.order-summary{position:relative;overflow:hidden}.order-summary:before{content:"";display:block;position:absolute;left:0;top:0;right:0;height:4px;background:linear-gradient(90deg,var(--orange),var(--orange-bright) 36%,#ffe0b2)}.title{padding-top:2px}.title h1{font-size:31px;letter-spacing:-.8px}.grid{gap:20px 26px}.grid>div{min-width:0}.label{font-size:11px;letter-spacing:.7px}.value{font-size:15px;line-height:1.35;word-break:break-word}.actions{align-items:center;padding-top:4px}.actions button{border-radius:9px;padding:11px 14px}.detail-state-action{flex:0 0 auto;width:54px;height:54px;font-size:23px;border:3px solid #fff;box-shadow:0 4px 12px #26323c25}.detail-tabs{gap:6px;margin:0 0 16px;padding:2px}.detail-tab{border:0;border-radius:9px;padding:10px 15px;font-size:13px;background:#e9eef0;color:#3e4a52}.detail-tab.active{background:var(--orange);box-shadow:0 4px 10px #f5820030}.tablewrap{border:1px solid #e5eaed;border-radius:11px;background:#fff}.tablewrap table{min-width:620px}.tablewrap th{background:#f5f7f8;color:#53606a;font-size:10px;letter-spacing:.5px;text-transform:uppercase;padding:12px 10px;white-space:nowrap}.tablewrap td{padding:12px 10px;color:#3e4a52}.tablewrap tbody tr:nth-child(even){background:#fbfcfc}.tablewrap tbody tr:hover{background:#fff7ec}.tablewrap td:nth-child(n+3),.tablewrap th:nth-child(n+3){text-align:right}.tablewrap .sku{font-family:Consolas,monospace;font-weight:700;font-size:12px;color:#343a40}.quantity-summary{gap:12px;margin:17px 0}.quantity-metric{position:relative;overflow:hidden;border-color:#e1e7ea;border-radius:12px;padding:13px;background:#f9fbfb}.quantity-metric:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--orange)}.quantity-metric:nth-child(2):before{background:var(--blue)}.quantity-metric:nth-child(3):before{background:var(--green)}.quantity-metric b{font-size:25px;letter-spacing:-.5px}.progress-summary{padding:14px 15px;border-radius:11px;background:#f7f9fa}.progress-track{height:10px}.progress-track i{background:linear-gradient(90deg,var(--orange),var(--orange-bright))}.line-state{display:inline-flex;align-items:center;min-width:58px;justify-content:center;padding:4px 7px;border-radius:99px;background:#fff2d8;color:#9b6800}.line-state.done{background:#e0f4e9;color:#11733f}.workflow{margin:22px 0 2px;padding:16px 5px 4px;border-top:1px solid #e8edef}.workflow-caption{display:flex;align-items:center;justify-content:space-between;margin:0 9px 14px;color:#56616b;font-size:12px}.workflow-caption b{color:#343a40}.workflow-steps{display:flex;min-width:650px;justify-content:space-between;gap:0}.workflow-scroll{overflow-x:auto;padding-bottom:5px}.workflow-step{flex:1;position:relative;min-width:84px;text-align:center;color:#8a959c}.workflow-step:before{content:"";display:block;width:22px;height:22px;border-radius:50%;margin:0 auto 7px;background:#fff;border:3px solid #cbd4d9;position:relative;z-index:2}.workflow-step:not(:last-child):after{content:"";position:absolute;left:50%;right:-50%;top:10px;height:3px;background:#dce3e7}.workflow-step.done{color:#56616b}.workflow-step.done:before{background:var(--orange);border-color:var(--orange);box-shadow:inset 0 0 0 4px #fff}.workflow-step.done:not(:last-child):after{background:var(--orange)}.workflow-step.current{color:#343a40;font-weight:700}.workflow-step.current:before{background:var(--orange);border-color:#fff;box-shadow:0 0 0 3px var(--orange),0 3px 7px #f5820040}.workflow-step.final:before{background:var(--green);border-color:var(--green);box-shadow:inset 0 0 0 4px #fff}.workflow-step span{display:block;font-size:10px;line-height:1.2;text-transform:uppercase;letter-spacing:.3px}.attention-item{padding:14px 0;border-bottom:1px solid #e7ecee}.attention-item:last-of-type{border-bottom:0}.attention-item strong{font-size:15px;color:#343a40}.attention-meta{margin-top:5px}.status-chart{gap:14px}.status-chart-row{grid-template-columns:minmax(130px,185px) 1fr 42px;gap:12px}.status-chart-row>span:first-child{font-size:11px;font-weight:700;color:#56616b;letter-spacing:.25px}.status-chart-track{height:12px;background:#edf1f3}.status-chart-track i{background:var(--orange)}.status-chart-track i.state-entregado{background:var(--green)}.status-chart-track i.state-en-picking{background:var(--blue)}.status-chart-track i.state-picking-finalizado,.status-chart-track i.state-por-guiar{background:#5ca4cf}.status-chart-track i.state-en-guiado,.status-chart-track i.state-guiado-finalizado{background:var(--purple)}.status-chart-track i.state-asignado{background:#e6a719}.status-chart-count{font-size:14px}.report-summary .grid>div{padding:3px 0 3px 13px;border-left:3px solid #dce3e7}.report-summary .grid>div:first-child{border-left-color:var(--orange)}.report-summary .grid>div:nth-child(2){border-left-color:var(--blue)}.report-summary .grid>div:nth-child(3){border-left-color:#5ca4cf}.report-summary .grid>div:nth-child(4){border-left-color:var(--purple)}.report-summary .grid>div:nth-child(5){border-left-color:var(--green)}.report-summary .value{font-size:24px;font-weight:800;letter-spacing:-.6px}@media(max-width:900px){.detail{padding:18px 14px 28px}.card{padding:18px;border-radius:13px}.grid{gap:15px}.workflow{margin-left:-4px;margin-right:-4px}.workflow-steps{min-width:620px}.row{min-height:98px;padding:15px 74px 15px 19px}.top:after{display:none}.toolbar{gap:7px}.toolbar input,.toolbar select,.toolbar button{min-height:40px}.tablewrap th,.tablewrap td{padding:10px 8px}.status-chart-row{grid-template-columns:112px minmax(110px,1fr) 30px}.quick-flow{gap:8px}.flow-step{padding:12px}}</style>');
document.head.insertAdjacentHTML('beforeend','<style id="triton-mobile-navigation">@media(max-width:900px){.list{max-height:46vh;min-height:230px;overflow-y:auto;border-bottom:1px solid #dce3e7}}</style>');
document.head.insertAdjacentHTML('beforeend','<style id="triton-queue-system">.queue-controls{position:sticky;top:0;z-index:3;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:13px 18px 12px 22px;background:#fff;border-bottom:1px solid #dfe6e9;box-shadow:0 4px 10px #26323c08}.queue-controls>div{display:grid;gap:2px}.queue-label{font-size:10px;font-weight:800;letter-spacing:.9px;color:#6e7881;text-transform:uppercase}.queue-controls strong{font-size:14px;color:#343a40}.queue-filter{display:flex;align-items:center;gap:6px;color:#6e7881;font-size:11px;font-weight:700}.queue-filter select{max-width:148px;border:1px solid #dce3e7;border-radius:7px;padding:7px 24px 7px 8px;background:#f7f9fa;color:#3e4a52;font-size:11px;font-weight:700}.stock-signal{display:inline-flex;align-items:center;gap:4px;margin:8px 0 0;font-size:10px;font-weight:800;letter-spacing:.1px}.stock-signal:before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}.stock-signal.ready{color:#168352}.stock-signal.shortage{color:#b46b00}.row .stock-signal+ .state-action{margin-top:0}@media(max-width:900px){.queue-controls{padding:10px 14px;position:sticky;top:0}.queue-filter select{max-width:132px}.row{padding-top:14px}.stock-signal{margin-top:6px}}</style>');
document.head.insertAdjacentHTML('beforeend','<style id="triton-sap-indicators">.sap-indicators{display:flex;flex-wrap:wrap;gap:5px 9px;margin:5px 0 7px;color:#66737c;font-size:10px;line-height:1.25}.sap-indicators span+span:before{content:"";display:inline-block;width:3px;height:3px;margin:0 7px 2px 0;border-radius:50%;background:#a8b2b8}.sap-indicators b{color:#3e4a52}.sap-summary{font-size:13px;color:#3e4a52}.section-note{margin:-8px 0 15px;color:#6e7881;font-size:12px}.stock-signal.blocked{color:#b43c36}.customer-tag{display:inline-flex;align-items:center;margin-right:5px;padding:3px 7px;border-radius:999px;font-size:10px;font-weight:800;letter-spacing:.02em;vertical-align:middle}.customer-tag.internal{background:#fff0dc;color:#b45d00}.customer-tag.external{background:#e8eef2;color:#52616b}@media(max-width:900px){.sap-indicators{gap:3px 6px}.sap-summary{font-size:12px}.section-note{line-height:1.4}.customer-tag{font-size:9px}}</style>');
document.head.insertAdjacentHTML('beforeend','<style id="triton-stock-clarity">.stock-summary-note{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:-7px 0 15px;color:#627079;font-size:12px}.stock-summary-note b{color:#3e4a52}.stock-summary-note .stock-rule{padding:6px 9px;border:1px solid #dfe6e9;border-radius:8px;background:#f8fafb;font-size:11px;white-space:nowrap}.stock-cell{font-weight:800;font-size:15px}.stock-cell.free-positive{color:#11733f}.stock-cell.free-zero{color:#a16600}.air-cell{display:inline-flex;justify-content:center;min-width:76px;padding:4px 7px;border-radius:999px;background:#f1f4f5;color:#64717a;font-size:11px;font-weight:700;white-space:nowrap}.air-cell.has-reservation{background:#eaf2f8;color:#1f6087}@media(max-width:900px){.stock-summary-note{align-items:flex-start;flex-direction:column}.stock-summary-note .stock-rule{white-space:normal}}</style>');
const tritonBaseLoadDetail=loadDetail;
loadDetail=async function(ov){
 await tritonBaseLoadDetail(ov);
 const card=[...document.querySelectorAll('#detail > .card')].find(item=>item.querySelector('h2')?.textContent.includes('SKU pendientes de despacho'));
 if(!card)return;
 const heading=card.querySelector('h2');
 if(heading)heading.textContent='Disponibilidad por SKU';
 const note=card.querySelector('.section-note');
 if(note)note.outerHTML='<div class="stock-summary-note"><span><b>Corte SAP</b>, reservas aéreas y saldo libre para decidir esta atención.</span><span class="stock-rule">Corte SAP − reservas WMS = libre</span></div>';
 const headers=[...card.querySelectorAll('thead th')];
 if(headers.length>=7){headers[4].textContent='Reservas aéreas';headers[5].textContent='Corte SAP';headers[6].textContent='Libre';}
 [...card.querySelectorAll('tbody tr')].forEach(row=>{
  const cells=[...row.children]; if(cells.length<7)return;
  const aerial=cells[4];const raw=aerial.textContent.trim();const match=raw.match(/^(\\d+)(?:\\s*\\(([^)]+)\\))?$/);
  const count=match?Number(match[1]):0;const quantity=match?.[2]||'';
  aerial.innerHTML=`<span class="air-cell ${count?'has-reservation':''}" title="${esc(aerial.getAttribute('title')||'')}">${count?`${count} ${count===1?'OV':'OVs'}${quantity?` · ${esc(quantity)}`:''}`:'Sin reserva'}</span>`;
  cells[5].innerHTML=`<span class="stock-cell">${esc(cells[5].textContent.trim())}</span>`;
  const free=Number(cells[6].textContent.trim())||0;
  cells[6].innerHTML=`<span class="stock-cell ${free>0?'free-positive':'free-zero'}" aria-label="Stock libre: ${free}">${free}</span>`;
 });
};
document.head.insertAdjacentHTML('beforeend','<style id="triton-operation-feedback">.operation-toast{position:fixed;right:22px;bottom:22px;z-index:30;max-width:min(420px,calc(100vw - 44px));padding:13px 16px;border-radius:11px;background:#343a40;color:#fff;font-size:13px;font-weight:700;line-height:1.35;box-shadow:0 12px 28px #252d3340;opacity:0;transform:translateY(16px);pointer-events:none;transition:opacity .18s,transform .18s}.operation-toast.visible{opacity:1;transform:translateY(0)}.operation-toast.success{border-left:5px solid #179b61}.operation-toast.error{border-left:5px solid #e26d55}.operation-busy .detail-state-action,.operation-busy .state-action{opacity:.65;cursor:wait}@media(max-width:900px){.operation-toast{right:14px;bottom:14px;max-width:calc(100vw - 28px)}}</style>');
document.head.insertAdjacentHTML('beforeend','<style id="triton-report-alerts">.report-section-title{display:flex;justify-content:space-between;gap:18px;align-items:start;margin-bottom:17px}.report-section-title h2{margin-bottom:5px}.report-section-title p{margin:0;color:#6e7881;font-size:13px}.alert-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.alert-tile{min-width:0;padding:14px;text-align:left;border:1px solid #e0e7e9;border-radius:12px;background:#fff;cursor:pointer;transition:transform .15s,box-shadow .15s,border-color .15s}.alert-tile:hover{transform:translateY(-2px);box-shadow:0 7px 15px #26323c14}.alert-tile b{display:block;font-size:27px;line-height:1;color:#343a40;letter-spacing:-1px}.alert-tile span{display:block;margin-top:8px;font-size:13px;font-weight:800;color:#3e4a52}.alert-tile small{display:block;margin-top:4px;color:#6e7881;font-size:10px}.alert-tile.attention{border-top:4px solid #f3b928}.alert-tile.guide{border-top:4px solid #5ca4cf}.alert-tile.delivery{border-top:4px solid #6568a8}.alert-tile.stock{border-top:4px solid #f58200}.alert-tile.stock b{color:#b46b00}@media(max-width:900px){.alert-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.alert-tile{padding:12px}.report-section-title{align-items:end}.report-section-title p{display:none}}</style>');
document.head.insertAdjacentHTML('beforeend','<style id="triton-mobile-ux-final">[hidden]{display:none!important}.toolbar-context,.toolbar-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;width:100%}.toolbar-actions{justify-content:flex-end}.toolbar button,.actions button{min-height:42px;font-size:14px;padding:10px 16px}.detail-state-action{flex:0 0 auto}@media(max-width:820px){.toolbar-context>*{flex:1 1 140px;min-width:0}.toolbar-actions{justify-content:stretch}.toolbar-actions button{flex:1 1 140px;min-height:44px}.toolbar input,.toolbar select{min-height:44px;font-size:16px}.list-toggle{min-height:48px}.back-to-list{min-height:44px}.actions{align-items:stretch}.actions button{min-height:44px;max-width:100%;white-space:normal}.detail-state-action{width:56px;height:56px;font-size:24px;flex-shrink:0}}</style>');
document.head.insertAdjacentHTML('beforeend','<style id="triton-admin-correction">.admin-correction{flex:1 0 100%;margin-top:8px;border:1px solid #dce3e7;border-radius:10px;background:#f8fafb;padding:0 13px}.admin-correction summary{min-height:42px;display:flex;align-items:center;cursor:pointer;color:#56616b;font-size:13px;font-weight:800}.admin-correction[open]{padding-bottom:13px}.admin-correction p{margin:0 0 10px;color:#6e7881;font-size:12px;line-height:1.4}.admin-correction-actions{display:flex;gap:8px;flex-wrap:wrap}.actions .admin-secondary{background:#fff;color:#343a40;border-color:#aebac1}.actions .admin-secondary:hover{background:#eef2f4;border-color:#8f9da5}.actions .admin-danger{background:#fff;color:#b43c36;border-color:#d9a19c}.actions .admin-danger:hover{background:#fff0ee;border-color:#b43c36}@media(max-width:820px){.admin-correction-actions button{flex:1 1 145px}}</style>');
document.head.insertAdjacentHTML('beforeend','<style id="triton-lot-traceability">.lot-line{padding:15px 0;border-top:1px solid #e4eaed}.lot-line:first-of-type{border-top:0}.lot-line-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}.lot-line-head>strong{font:700 14px Consolas,monospace;color:#252d33}.lot-line-head>span:not(.badge){flex:1;min-width:180px;color:#65717a;font-size:12px}.lot-reservation{display:grid;grid-template-columns:minmax(230px,1.5fr) 2fr auto auto;align-items:center;gap:9px;padding:9px 11px;margin:6px 0;border:1px solid #dfe6e9;border-radius:9px;background:#f8fafb;font-size:12px}.lot-reservation>strong{font-family:Consolas,monospace}.lot-reservation.pending{display:block;color:#a45f00;background:#fff6e8;border-color:#f0d2a4}.lot-control{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px}.lot-control input,.lot-control select{min-height:42px;border:1px solid #cfd8dd;border-radius:8px;padding:9px 11px;min-width:150px;background:#fff}.lot-control input:first-child{flex:1}.lot-control button{min-height:42px}@media(max-width:820px){.lot-reservation{grid-template-columns:1fr}.lot-control>*{flex:1 1 150px;min-width:0}}</style>');
const baseLoadDetail=loadDetail;
loadDetail=async function(ov){
 try{await baseLoadDetail(ov);document.querySelectorAll('.detail .label').forEach(el=>{if(el.textContent==='GUIADOR')el.textContent='GUIADOR / ENTREGADOR'});document.querySelectorAll('.detail button').forEach(el=>{if(el.textContent==='Asignar guiador')el.textContent='Asignar guiador / entregador'});const actions=document.querySelector('.detail .card .actions');if($('role').value==='ADMINISTRADOR'&&actions&&!$('pickerAssignee')){actions.insertAdjacentHTML('afterbegin','<select id="pickerAssignee" aria-label="Picker a asignar"><option value="">Cargando pickers...</option></select><select id="guideAssignee" aria-label="Guiador a asignar"><option value="">Cargando guiadores...</option></select><label class="assignee-more"><input type="checkbox" id="showReceptionAssignees" onchange="loadAssignees()"> Mostrar más: usuarios de recepción</label>');await loadAssignees()}await renderAttentions()}
 catch(error){console.error(error);$('detail').innerHTML='<div class="card"><h2>No se pudo cargar la OV</h2><p class="label">'+esc(error.message||error)+'</p><p class="label">Revisa que el servidor esté usando la versión actualizada de app.py.</p></div>'}
}
async function loadAssignees(){
 for(const [requestedRole,id,label] of [['PICKER','pickerAssignee','picker'],['GUIADOR','guideAssignee','guiador']]){
  const select=$(id);if(!select)continue;
  const includeReception=$('showReceptionAssignees')?.checked?'&include_reception=1':'';
  const response=await apiFetch('/api/assignees?role='+requestedRole+includeReception);
  const data=await response.json();
  if(!response.ok)throw new Error(data.error||'No se pudo cargar la lista de responsables');
  select.innerHTML='<option value="">Selecciona un '+label+'</option>'+(data.users||[]).map(user=>`<option value="${esc(user.username)}">${esc(user.display_name)} · ${esc(user.username)} · ${esc(user.shift||'')}</option>`).join('');
 }
}
async function renderAttentions(){
 const r=await apiFetch('/api/orders/'+encodeURIComponent(selected)); const o=await r.json();
 renderWorkflow(o);
 renderRoleActions(o);
 const card=document.createElement('div'); card.className='card';
 const role=$('role').value;
 card.innerHTML='<h2>Atenciones de la OV</h2>'+(o.attentions||[]).map(a=>`<div class="attention-item"><strong>Atención ${a.sequence_no}</strong> <span class="badge ${cls(a.app_status)}">${esc(a.app_status)}</span> <span class="badge">${esc(a.attention_type)}</span><div class="label attention-meta">Picker: ${esc(a.current_picker)||'Sin asignar'} · Guiador: ${esc(a.current_guide)||'Sin asignar'} · Líneas: ${a.lines.length}</div></div>`).join('')+`<div class="actions"><button onclick="createAttention()" ${role==='ADMINISTRADOR'?'':'disabled'}>Crear nueva atención</button></div>`;
 $('detail').appendChild(card);
 renderAttentionHistory(o);
 renderOperationalCard(o);
 renderLotTraceabilityCard(o);
 renderDetailTabs(role);
}
function renderWorkflow(o){
 const active=(o.attentions||[]).find(a=>!isTerminalStatus(a.app_status))||(o.attentions||[]).at(-1);
 const status=active?.app_status||o.app_status;
 const position={PENDIENTE:0,ASIGNADO:1,'EN PICKING':2,'PICKING FINALIZADO':3,'POR GUIAR':3,'EN GUIADO':4,'GUIADO FINALIZADO':5,ENTREGADO:6,'CERRADO SAP':6}[status]??0;
 const steps=['Pendiente','Asignado','Picking','Cola guiado','Guiado','Entrega','Cerrado'];
 const summary=document.querySelector('.order-summary'); if(!summary||summary.querySelector('.workflow'))return;
 summary.insertAdjacentHTML('beforeend',`<div class="workflow" aria-label="Flujo de la atención"><div class="workflow-caption"><span>FLUJO OPERATIVO</span><b>${esc(status)}</b></div><div class="workflow-scroll"><div class="workflow-steps">${steps.map((step,index)=>`<div class="workflow-step ${index<=position?'done':''} ${index===position?'current':''} ${status==='ENTREGADO'&&index===6?'final':''}"><span>${step}</span></div>`).join('')}</div></div></div>`);
}
function renderAttentionHistory(o){
 if($('role').value!=='ADMINISTRADOR')return;
 const active=(o.attentions||[]).find(a=>!isTerminalStatus(a.app_status))||(o.attentions||[]).at(-1);
 const cards=Array.from(document.querySelectorAll('.detail .card'));
 const card=cards.find(item=>item.querySelector('h2')?.textContent==='Historial');
 if(!card||!active)return;
 const events=active.history||[];
 card.innerHTML='<h2>Historial de Atención '+active.sequence_no+'</h2>'+(events.length?`<div class="tablewrap"><table><thead><tr><th>Fecha</th><th>Evento</th><th>Cambio</th><th>Usuario</th></tr></thead><tbody>${events.map(event=>`<tr><td>${esc(event.created_at)}</td><td>${esc(event.event_type)}</td><td>${esc(event.old_value)} → ${esc(event.new_value)}</td><td>${esc(event.username)}</td></tr>`).join('')}</tbody></table></div>`:'<p class="label">Sin cambios todavía.</p>');
}
function renderDetailTabs(role){
 const detail=$('detail');
 const cards=Array.from(detail.querySelectorAll(':scope > .card'));
 const findCard=title=>cards.find(card=>card.querySelector('h2')?.textContent.startsWith(title));
 const sections=[
  {id:'lines',label:'Líneas OV',card:findCard('Líneas de la OV')},
  {id:'control',label:'Cantidades',card:findCard('Control de Atención')},
  {id:'lots',label:'Lotes',card:findCard('Trazabilidad por lote')},
  {id:'attentions',label:'Atenciones',card:findCard('Atenciones de la OV')},
  {id:'history',label:'Historial',card:role==='ADMINISTRADOR'?findCard('Historial'):null},
 ].filter(section=>section.card);
 if(!sections.length)return;
 const tabs=document.createElement('nav');tabs.className='detail-tabs';tabs.setAttribute('aria-label','Secciones de la OV');
 const panel=document.createElement('div');panel.className='detail-tab-panel';
 sections.forEach(section=>{section.card.dataset.detailTab=section.id;section.card.hidden=true;panel.appendChild(section.card);tabs.insertAdjacentHTML('beforeend',`<button class="detail-tab" data-detail-tab="${section.id}" onclick="activateDetailTab('${section.id}')">${section.label}</button>`)});
 detail.append(tabs,panel);
 activateDetailTab((role==='PICKER'||role==='GUIADOR'||role==='PICKER_GUIADOR')&&sections.some(section=>section.id==='control')?'control':sections[0].id);
}
function lotReservationRows(line){const reservations=line.reservations||[];if(!reservations.length)return '<span class="label">Stock histórico sin lote</span>';return reservations.map(reservation=>{if(!reservation.lot_code)return `<div class="lot-reservation pending"><strong>${esc(reservation.status)}</strong> · ${qty(reservation.requested_qty)} pendientes de asignación</div>`;return `<div class="lot-reservation"><strong>${esc(reservation.lot_code)}</strong><span>${esc(reservation.location||'Sin ubicación')} · Reservado ${qty(reservation.reserved_qty)} · Recogido ${qty(reservation.consumed_qty)}</span><span class="badge ${reservation.scanned_at?'entregado':'pendiente'}">${reservation.scanned_at?'ESCANEADO':'POR ESCANEAR'}</span>${$('role').value==='ADMINISTRADOR'&&reservation.status==='CONSUMIDA'?`<button class="admin-secondary" onclick="returnLot(${reservation.id},${reservation.consumed_qty})">Devolver</button>`:''}</div>`}).join('')}
function renderLotTraceabilityCard(o){if(!window.wmsFeatures?.advanced_lots)return;const active=(o.attentions||[]).find(a=>!isTerminalStatus(a.app_status));if(!active)return;const role=$('role').value;const card=document.createElement('div');card.className='card';card.innerHTML=`<h2>Trazabilidad por lote</h2><p class="section-note">El NP identifica el repuesto; el lote identifica la recepción física autorizada para esta OV.</p>${active.lines.map(line=>{const scan=role==='PICKER'&&active.app_status==='EN PICKING'&&line.tracked?`<div class="lot-control"><input id="scan-lot-${line.id}" placeholder="Escanear lote autorizado"><button onclick="scanLot(${line.id})">Validar lote</button></div>`:'';const available=line.available_lots||[];const manual=role==='ADMINISTRADOR'&&line.tracked?`<details class="optional-data"><summary>Asignación manual / excepción</summary><div class="lot-control"><select id="lot-option-${line.id}">${available.map(lot=>`<option value="${lot.id}">${esc(lot.lot_code)} · libre ${qty(lot.available_qty)}</option>`).join('')}</select><input id="lot-qty-${line.id}" type="number" min="0.01" step="0.01" value="${qty(line.pending_qty||line.planned_qty)}" placeholder="Cantidad"><input id="lot-reason-${line.id}" placeholder="Motivo obligatorio"><button onclick="assignLot(${line.id})" ${available.length?'':'disabled'}>Asignar lote</button></div></details>`:'';return `<section class="lot-line"><div class="lot-line-head"><strong>${esc(line.item_code)}</strong><span>${esc(line.description||'')}</span><span class="badge ${line.tracked?'asignado':'pendiente'}">${line.tracked?'CONTROL POR LOTE':'SIN LOTE HISTÓRICO'}</span></div>${lotReservationRows(line)}${scan}${manual}</section>`}).join('')}</div>`;$('detail').appendChild(card)}
async function scanLot(lineId){const lotCode=$('scan-lot-'+lineId).value.trim();try{const r=await fetch('/api/attention-lines/'+lineId+'/scan-lot',{method:'POST',headers:{'Content-Type':'application/json','X-User':currentUserName(),'X-Role':$('role').value},body:JSON.stringify({lot_code:lotCode})});const data=await r.json();if(!r.ok)throw new Error(data.error||'No se pudo validar el lote');await loadDetail(selected);notify('Lote validado; cantidad recogida actualizada','success')}catch(error){notify(error.message,'error')}}
async function assignLot(lineId){const lotId=Number($('lot-option-'+lineId).value);const quantity=$('lot-qty-'+lineId).value;const reason=$('lot-reason-'+lineId).value.trim();try{const r=await fetch('/api/attention-lines/'+lineId+'/assign-lot',{method:'POST',headers:{'Content-Type':'application/json','X-User':currentUserName(),'X-Role':$('role').value},body:JSON.stringify({lot_id:lotId,quantity,reason})});const data=await r.json();if(!r.ok)throw new Error(data.error||'No se pudo asignar el lote');await loadDetail(selected);notify('Lote asignado con auditoría','success')}catch(error){notify(error.message,'error')}}
async function returnLot(reservationId,maximum){const quantity=prompt('Cantidad a devolver',String(maximum));if(quantity===null)return;const reason=prompt('Motivo obligatorio de la devolución');if(reason===null)return;try{const r=await fetch('/api/lot-reservations/'+reservationId+'/return',{method:'POST',headers:{'Content-Type':'application/json','X-User':currentUserName(),'X-Role':$('role').value},body:JSON.stringify({quantity,reason})});const data=await r.json();if(!r.ok)throw new Error(data.error||'No se pudo registrar la devolución');await loadDetail(selected);notify('Devolución registrada en el kardex','success')}catch(error){notify(error.message,'error')}}
function activateDetailTab(id){
 document.querySelectorAll('[data-detail-tab]').forEach(element=>{
  const active=element.dataset.detailTab===id;
  if(element.classList.contains('detail-tab'))element.classList.toggle('active',active);
  else element.hidden=!active;
 });
}
function renderOperationalCard(o){
 const active=(o.attentions||[]).find(a=>!isTerminalStatus(a.app_status)); if(!active)return;
 const role=$('role').value; const user=currentUserName();
 const pickingEditable=(role==='PICKER'||role==='PICKER_GUIADOR')&&sameUser(user,active.current_picker)&&active.app_status==='EN PICKING';
 const deliveryEditable=(role==='GUIADOR'||role==='PICKER_GUIADOR')&&sameUser(user,active.current_guide)&&['EN GUIADO','GUIADO FINALIZADO'].includes(active.app_status);
 const totals=active.lines.reduce((result,line)=>({planned:result.planned+Number(line.planned_qty||0),picked:result.picked+Number(line.picked_qty||0),delivered:result.delivered+Number(line.delivered_qty||0)}),{planned:0,picked:0,delivered:0});
 const missingLines=active.lines.filter(line=>Number(line.picked_qty||0)<Number(line.planned_qty||0));
 const automaticType=active.attention_type==='SELECCIONAR'?'Pendiente de finalizar picking':(active.attention_type||'Pendiente de finalizar picking');
 const guideNotice=['POR GUIAR','EN GUIADO','GUIADO FINALIZADO','ENTREGADO'].includes(active.app_status)?`<div class="notice"><strong>Resultado del picking: ${esc(automaticType)}.</strong> ${missingLines.length?`NP pendientes o incompletos: ${missingLines.map(line=>esc(line.item_code||'Sin NP')).join(', ')}.`:'Se recogieron todos los NP planificados.'} El guiador/entregador debe revisar esta información antes de entregar.</div>`:'';
 const isDelivery=(role==='GUIADOR'||role==='PICKER_GUIADOR')||['EN GUIADO','GUIADO FINALIZADO','ENTREGADO'].includes(active.app_status);
 const target=isDelivery?totals.picked:totals.planned;
 const processed=isDelivery?totals.delivered:totals.picked;
 const percent=target?Math.min(100,Math.round(processed/target*100)):0;
 const progressName=isDelivery?'Entrega registrada':'Picking registrado';
 const lineState=(processedLine,targetLine)=>{const remaining=Math.max(0,Number(targetLine||0)-Number(processedLine||0));return remaining===0?'<span class="line-state done">LISTO</span>':`<span class="line-state pending">PEND. ${remaining}</span>`};
 const card=document.createElement('div');card.className='card';
 card.innerHTML=`<h2>Control de Atención ${active.sequence_no}</h2><p class="section-note">El tipo se calcula automáticamente al finalizar el picking: COMPLETA si se recoge todo; PARCIAL si queda al menos un NP o cantidad pendiente.</p>${guideNotice}<div class="quantity-summary"><div class="quantity-metric"><span class="label">PLANIFICADA</span><b>${totals.planned}</b></div><div class="quantity-metric"><span class="label">RECOGIDA</span><b>${totals.picked}</b></div><div class="quantity-metric"><span class="label">ENTREGADA</span><b>${totals.delivered}</b></div></div><div class="progress-summary"><div class="progress-heading"><span>${progressName}</span><strong>${processed} / ${target} · ${percent}%</strong></div><div class="progress-track" role="progressbar" aria-label="${progressName}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><i style="width:${percent}%"></i></div></div><div class="tablewrap"><table><thead><tr><th>Artículo</th><th>Origen</th><th>Libre</th><th>Reservado</th><th>Planificada</th><th>Recogida</th><th>Entregada</th><th>Control</th></tr></thead><tbody>${active.lines.map(line=>{const lineTarget=isDelivery?line.picked_qty:line.planned_qty;const lineProcessed=isDelivery?line.delivered_qty:line.picked_qty;return `<tr><td>${esc(line.item_code)}</td><td>${lineOriginLabel(line,o)}</td><td>${qty(line.stock_free_qty)}</td><td>${qty(line.stock_reserved_for_line)}</td><td>${qty(line.planned_qty)}</td><td>${pickingEditable?`<input type="number" min="0" max="${line.planned_qty}" step="0.01" value="${line.picked_qty}" onchange="saveLine(${active.id},${line.id},'picked_qty',this.value)">`:qty(line.picked_qty)}</td><td>${deliveryEditable?`<input type="number" min="0" max="${line.picked_qty}" step="0.01" value="${line.delivered_qty}" onchange="saveLine(${active.id},${line.id},'delivered_qty',this.value)">`:qty(line.delivered_qty)}</td><td>${lineState(lineProcessed,lineTarget)}</td></tr>`}).join('')}</tbody></table></div>`;
 $('detail').appendChild(card);
}
async function createAttention(){await mutate('/api/orders/'+encodeURIComponent(selected)+'/attentions',{});}
function renderRoleActions(o){
 const actions=document.querySelector('.detail .card .actions'); if(!actions) return;
 const role=$('role').value; const buttons=Array.from(actions.querySelectorAll('button'));
 if(buttons[2]) buttons[2].remove();
 const active=(o.attentions||[]).find(a=>!isTerminalStatus(a.app_status));
 if(!active) return;
 let status=null,label=null;
 if((role==='PICKER'||role==='PICKER_GUIADOR') && active.app_status==='ASIGNADO'){status='EN PICKING';label='Iniciar picking'}
 if((role==='PICKER'||role==='PICKER_GUIADOR') && active.app_status==='EN PICKING'){status='PICKING FINALIZADO';label='Finalizar picking'}
 if((role==='GUIADOR'||role==='PICKER_GUIADOR') && active.app_status==='POR GUIAR'){status='EN GUIADO';label='Iniciar guiado'}
 if(role==='PICKER' && active.app_status==='POR GUIAR'){const note=document.createElement('span');note.className='label';note.textContent='Picking finalizado; esperando guiado';actions.appendChild(note)}
 if((role==='GUIADOR'||role==='PICKER_GUIADOR') && active.app_status==='EN GUIADO'){status='GUIADO FINALIZADO';label='Finalizar guiado'}
 if((role==='GUIADOR'||role==='PICKER_GUIADOR') && active.app_status==='GUIADO FINALIZADO'){status='ENTREGADO';label='Registrar entrega'}
 if(status){const b=document.createElement('button');b.className='detail-state-action '+(status.includes('GUIADO')?'guide':status.includes('FINALIZADO')?'finish':'start');b.textContent='▶';b.title=label;b.setAttribute('aria-label',label);b.onclick=()=>advanceActive(status);actions.appendChild(b);const t=document.createElement('span');t.className='label';t.textContent=label;actions.appendChild(t)}
 if(role==='ADMINISTRADOR'){
  const correction=document.createElement('details');correction.className='admin-correction';
  correction.innerHTML=`<summary>Corrección administrativa</summary><p>Úsalo para corregir un inicio equivocado. Todo cambio conserva una marca de auditoría.</p><div class="admin-correction-actions">${active.app_status!=='PENDIENTE'?`<button class="admin-secondary" onclick="rollbackAttention(${active.id},'${esc(active.app_status)}')">← Retroceder una etapa</button>`:''}<button class="admin-danger" onclick="resetAttention(${active.id})">Reiniciar atención</button></div>`;
  actions.appendChild(correction)
 }
}
async function advanceActive(status){await mutate('/api/orders/'+encodeURIComponent(selected)+'/status',{status})}
const statuses=['PENDIENTE','ASIGNADO','EN PICKING','PICKING FINALIZADO','POR GUIAR','EN GUIADO','GUIADO FINALIZADO','ENTREGADO'];
function isTerminalStatus(status){return status==='ENTREGADO'||status==='CERRADO SAP'}
function nextStatus(s){let i=statuses.indexOf(s);return i>=0&&i<statuses.length-1?statuses[i+1]:null}
async function advance(status){await mutate('/api/orders/'+encodeURIComponent(selected)+'/status',{status})}
async function assign(field){const id=field==='current_picker'?'pickerAssignee':'guideAssignee';const value=$(id)?.value.trim();if(!value){alert('Selecciona el responsable');return}await mutate('/api/orders/'+encodeURIComponent(selected)+'/assign',{field,value})}
async function saveAttentionType(attentionId,value){await mutate('/api/attentions/'+attentionId+'/type',{attention_type:value})}
async function saveLine(attentionId,lineId,field,value){await mutate('/api/attentions/'+attentionId+'/lines/'+lineId,{field,value})}
async function rollbackAttention(attentionId,currentStatus){const reason=prompt(`Motivo para retroceder desde ${currentStatus}:`);if(reason===null)return;if(!reason.trim()){notify('Debes indicar el motivo del retroceso','error');return}if(!confirm('¿Confirmas que deseas retroceder una etapa?'))return;await mutate('/api/attentions/'+attentionId+'/rollback',{reason:reason.trim()})}
async function resetAttention(attentionId){const reason=prompt('Motivo para reiniciar la atención:');if(reason===null)return;if(!reason.trim()){notify('Debes indicar el motivo del reinicio','error');return}if(!confirm('Esto devolverá la atención a PENDIENTE, quitará responsables, pondrá las cantidades en cero y restaurará el stock. ¿Continuar?'))return;await mutate('/api/attentions/'+attentionId+'/reset',{reason:reason.trim()})}
function minutes(value){return value===null||value===undefined?'—':value+' min'}
async function showReport(){
 if($('role').value!=='ADMINISTRADOR'){alert('La reportería es para el administrador');return}
 selected=null;renderList();const r=await apiFetch('/api/reports/operational');const report=await r.json();
 const averages=report.averages_minutes; const alerts=report.alerts||{};
 const counts=Object.entries(report.by_status||{}).sort((first,second)=>second[1]-first[1]);
 const maxCount=Math.max(1,...counts.map(([,count])=>count));
 const chart=counts.length?`<div class="status-chart">${counts.map(([status,count])=>`<div class="status-chart-row"><span>${esc(status)}</span><div class="status-chart-track" aria-label="${esc(status)}: ${count}"><i class="state-${cls(status)}" style="width:${Math.round(count/maxCount*100)}%"></i></div><span class="status-chart-count">${count}</span></div>`).join('')}</div>`:'<p class="label">Aún no hay atenciones para visualizar.</p>';
 const alertCard=`<div class="card report-alerts"><div class="report-section-title"><div><h2>Alertas operativas</h2><p>Prioriza la cola sin buscar OV por OV.</p></div><span class="label">ACCESO RÁPIDO</span></div><div class="alert-grid"><button class="alert-tile attention" onclick="focusQueue('PENDIENTE')"><b>${alerts.without_picker||0}</b><span>Sin picker</span><small>Asignar responsable</small></button><button class="alert-tile guide" onclick="focusQueue('POR GUIAR')"><b>${alerts.waiting_guide||0}</b><span>Por guiar</span><small>Iniciar despacho</small></button><button class="alert-tile delivery" onclick="focusQueue('GUIADO FINALIZADO')"><b>${alerts.ready_delivery||0}</b><span>Por entregar</span><small>Confirmar entrega</small></button><button class="alert-tile stock" onclick="focusQueue('STOCK_PARCIAL')"><b>${alerts.stock_shortage_orders||0}</b><span>Stock parcial</span><small>Revisar disponibilidad</small></button></div></div>`;
 $('detail').innerHTML=`<div class="card report-summary"><h2>Reporte Operativo</h2><div class="grid"><div><div class="label">ATENCIONES</div><div class="value">${report.total_attentions}</div></div><div><div class="label">PROM. PICKING</div><div class="value">${minutes(averages.picking_minutes)}</div></div><div><div class="label">ESPERA GUIADO</div><div class="value">${minutes(averages.waiting_guide_minutes)}</div></div><div><div class="label">PROM. GUIADO</div><div class="value">${minutes(averages.guiding_minutes)}</div></div><div><div class="label">ESPERA ENTREGA</div><div class="value">${minutes(averages.waiting_delivery_minutes)}</div></div></div></div>${alertCard}<div class="card"><h2>Atenciones por estado</h2>${chart}</div><div class="card"><h2>Atenciones recientes</h2><div class="tablewrap"><table><thead><tr><th>OV</th><th>Atención</th><th>Estado</th><th>Picker</th><th>Guiador</th><th>Picking</th><th>Espera guiado</th></tr></thead><tbody>${report.rows.map(row=>`<tr><td>${esc(row.sap_ov)}</td><td>${row.sequence_no}</td><td><span class="badge ${cls(row.app_status)}">${esc(row.app_status)}</span></td><td>${esc(row.current_picker)}</td><td>${esc(row.current_guide)}</td><td>${minutes(row.picking_minutes)}</td><td>${minutes(row.waiting_guide_minutes)}</td></tr>`).join('')}</tbody></table></div></div>`;
}
async function showUsers(){
  if($('role').value!=='ADMINISTRADOR'){notify('La administración de usuarios es solo para el administrador','error');return}
  const r=await apiFetch('/api/users');const data=await r.json();if(!r.ok){notify(data.error||'No se pudo cargar usuarios','error');return}
  window.userDirectory=data.users||[];
  const rows=window.userDirectory.map(user=>`<tr><td><strong>${esc(user.display_name)}</strong><br><small>${esc([user.first_name,user.last_name].filter(Boolean).join(' ')||'Ficha sin completar')}</small></td><td>${esc(user.username)}</td><td>${esc(user.role)}</td><td>${esc(user.shift)}</td><td>${user.active?'ACTIVO':'INACTIVO'}</td><td><button class="ghost" onclick="openUserProfile('${encodeURIComponent(user.username)}')">Ver ficha</button> ${user.active&&user.username!=='demo.admin'?`<button class="admin-danger" onclick="deactivateUser('${esc(user.username)}')">Desactivar</button>`:''}</td></tr>`).join('');
  $('detail').innerHTML=`<div class="card"><h2>Administrar usuarios</h2><p class="section-note">Crea responsables y abre su ficha para completar o corregir nombres, apellidos e identificación. Las contraseñas nunca se muestran.</p><div class="actions"><input id="newUserName" placeholder="Usuario / correo"><input id="newUserDisplay" placeholder="Nombre visible"><select id="newUserRole"><option>PICKER</option><option>GUIADOR</option><option>PICKER_GUIADOR</option><option>ASISTENTE_RECEPCION</option><option>AUXILIAR_RECEPCION</option><option>ADMINISTRADOR</option></select><select id="newUserShift"><option>DÍA</option><option>NOCHE</option></select><button onclick="saveNewUser()">Guardar usuario</button></div><div class="tablewrap"><table><thead><tr><th>Nombre</th><th>Usuario</th><th>Rol</th><th>Turno</th><th>Estado</th><th>Acción</th></tr></thead><tbody>${rows||'<tr><td colspan="6">No hay usuarios creados.</td></tr>'}</tbody></table></div></div><div id="userModal" class="user-modal" role="dialog" aria-modal="true" aria-labelledby="userModalTitle" onclick="if(event.target===this)closeUserProfile()"></div>`;
}
function openUserProfile(encodedUsername){
  const username=decodeURIComponent(encodedUsername);const user=(window.userDirectory||[]).find(item=>item.username===username);if(!user)return;
  $('userModal').innerHTML=`<div class="user-modal-card"><div class="user-modal-head"><div><h2 id="userModalTitle">Ficha del usuario</h2><p class="section-note">Identidad operativa y datos usados para asignaciones.</p></div><button class="user-modal-close" type="button" aria-label="Cerrar ficha" onclick="closeUserProfile()">×</button></div><p class="user-modal-note"><strong>${esc(user.username)}</strong> · ${user.active?'Cuenta activa':'Cuenta inactiva'}. La contraseña se gestiona aparte y no se visualiza.</p><div class="user-form-grid"><label>Nombre visible<input id="profileDisplayName" value="${esc(user.display_name||'')}"></label><label>Nombres<input id="profileFirstName" value="${esc(user.first_name||'')}"></label><label>Apellidos<input id="profileLastName" value="${esc(user.last_name||'')}"></label><label>Documento de identidad<input id="profileDocumentId" value="${esc(user.document_id||'')}" placeholder="DNI / CE"></label><label>Rol<select id="profileRole"><option ${user.role==='PICKER'?'selected':''}>PICKER</option><option ${user.role==='GUIADOR'?'selected':''}>GUIADOR</option><option ${user.role==='PICKER_GUIADOR'?'selected':''}>PICKER_GUIADOR</option><option ${user.role==='ASISTENTE_RECEPCION'?'selected':''}>ASISTENTE_RECEPCION</option><option ${user.role==='AUXILIAR_RECEPCION'?'selected':''}>AUXILIAR_RECEPCION</option><option ${user.role==='ADMINISTRADOR'?'selected':''}>ADMINISTRADOR</option></select></label><label>Turno<select id="profileShift"><option ${user.shift==='DÍA'?'selected':''}>DÍA</option><option ${user.shift==='NOCHE'?'selected':''}>NOCHE</option></select></label></div><div class="user-modal-actions"><button class="ghost" type="button" onclick="closeUserProfile()">Cancelar</button><button class="primary" type="button" onclick="saveUserProfile('${encodeURIComponent(username)}')">Guardar cambios</button></div></div>`;
  $('userModal').classList.add('open');$('profileDisplayName').focus();
}
function closeUserProfile(){if($('userModal'))$('userModal').classList.remove('open')}
async function saveUserProfile(encodedUsername){const username=decodeURIComponent(encodedUsername);const body={username,display_name:$('profileDisplayName').value,first_name:$('profileFirstName').value,last_name:$('profileLastName').value,document_id:$('profileDocumentId').value,role:$('profileRole').value,shift:$('profileShift').value};const r=await fetch('/api/users',{method:'POST',headers:{'Content-Type':'application/json','X-User':currentUserName(),'X-Role':$('role').value},body:JSON.stringify(body)});const data=await r.json();if(!r.ok){notify(data.error||'No se pudo actualizar la ficha','error');return}closeUserProfile();notify('Ficha actualizada','success');showUsers()}
async function saveNewUser(){const body={username:$('newUserName').value,display_name:$('newUserDisplay').value,role:$('newUserRole').value,shift:$('newUserShift').value};const r=await fetch('/api/users',{method:'POST',headers:{'Content-Type':'application/json','X-User':currentUserName(),'X-Role':$('role').value},body:JSON.stringify(body)});const data=await r.json();if(!r.ok){notify(data.error||'No se pudo guardar el usuario','error');return}notify('Usuario guardado','success');showUsers()}
async function deactivateUser(username){const r=await fetch('/api/users/'+encodeURIComponent(username)+'/deactivate',{method:'POST',headers:{'X-User':currentUserName(),'X-Role':$('role').value}});const data=await r.json();if(!r.ok){notify(data.error||'No se pudo desactivar','error');return}notify('Usuario desactivado','success');showUsers()}
async function showWorkload(){
 if($('role').value!=='ADMINISTRADOR'){notify('La reportería es solo para el administrador','error');return}
 const period=$('workloadPeriod')?.value||'all';const r=await apiFetch('/api/reports/workload?period='+period);const data=await r.json();if(!r.ok){notify(data.error||'No se pudo cargar la carga','error');return}
 const cutoffs=(data.cutoffs||[]).map(row=>`<tr><td>${esc(row.cutoff_at)}</td><td>${esc(row.window_start)} → ${esc(row.cutoff_at)}</td><td>${esc(row.work_day)}</td><td>${row.total_ovs}</td><td>${row.pending_ovs}</td><td>${row.closed_ovs}</td><td>${row.unstarted_ovs}</td></tr>`).join('');
 const metrics=(data.picker_metrics||[]).map(row=>`<tr><td>${esc(row.username)}</td><td>${esc(row.shift)}</td><td>${row.assigned_ovs}</td><td>${row.completed_ovs}</td><td>${qty(row.picked_units)} / ${row.target_units}</td><td>${row.compliance_pct}% <span class="line-state ${row.traffic_light==='VERDE'?'done':'pending'}">${row.traffic_light}</span></td></tr>`).join('');
 $('detail').innerHTML=`<div class="card"><h2>Carga y desempeño de picking</h2><p class="section-note">Metas iniciales por picker: ${data.targets.ovs} OVs y ${data.targets.units} unidades. La semaforización usa el menor cumplimiento entre ambos indicadores.</p><div class="actions report-filters"><label>Periodo <select id="workloadPeriod" onchange="showWorkload()"><option value="all" ${period==='all'?'selected':''}>Todos</option><option value="day" ${period==='day'?'selected':''}>Hoy</option><option value="week" ${period==='week'?'selected':''}>Semana actual</option><option value="weekdays" ${period==='weekdays'?'selected':''}>Lunes a viernes</option></select></label></div><h3>Pendientes por corte de las 4:00 p. m.</h3><p class="section-note">Cada corte representa la ventana de las últimas 24 horas, el trabajo nocturno y la fecha objetivo de preparación.</p><div class="tablewrap"><table><thead><tr><th>Corte</th><th>Ventana</th><th>Trabajo</th><th>OVs</th><th>Pendientes</th><th>Cerradas</th><th>Sin iniciar</th></tr></thead><tbody>${cutoffs||'<tr><td colspan="7">Aún no hay cortes registrados para este periodo.</td></tr>'}</tbody></table></div><h3>Desempeño por picker</h3><div class="tablewrap"><table><thead><tr><th>Picker</th><th>Turno</th><th>OVs asignadas</th><th>OVs terminadas</th><th>Unidades</th><th>Cumplimiento</th></tr></thead><tbody>${metrics||'<tr><td colspan="6">Aún no hay actividad registrada.</td></tr>'}</tbody></table></div></div>`;
}
async function showTraceability(){if($('role').value!=='ADMINISTRADOR')return;const search=prompt('Buscar por NP, lote, BL, OC/IP, EM, OV o atención');if(search===null||!search.trim())return;selected=null;renderList();const r=await apiFetch('/api/traceability?search='+encodeURIComponent(search.trim()));const lots=await r.json();if(!r.ok){notify(lots.error||'No se pudo consultar','error');return}const movements=lot=>`<details class="optional-data"><summary>Kardex (${(lot.movements||[]).length} movimientos)</summary><div class="tablewrap"><table><thead><tr><th>Fecha</th><th>Movimiento</th><th>Cantidad</th><th>Disponible antes</th><th>Disponible después</th><th>OV</th><th>Usuario</th></tr></thead><tbody>${(lot.movements||[]).map(m=>`<tr><td>${esc(m.created_at)}</td><td>${esc(m.movement_type)}</td><td>${qty(m.quantity)}</td><td>${qty(m.before_available)}</td><td>${qty(m.after_available)}</td><td>${esc(m.sap_ov||'—')}</td><td>${esc(m.username)}</td></tr>`).join('')}</tbody></table></div></details>`;$('detail').innerHTML=`<div class="card"><h2>Consulta de trazabilidad</h2><p class="section-note">Resultado para <strong>${esc(search)}</strong>: ${lots.length} lote(s).</p>${lots.map(lot=>`<section class="lot-line"><div class="lot-line-head"><strong>${esc(lot.lot_code)}</strong><span>${esc(lot.item_code)} · ${esc(lot.description||'')}</span><span class="badge asignado">DISPONIBLE ${qty(lot.available_qty)}</span></div><div class="grid compact"><div><div class="label">BL/AWB</div><div class="value">${esc(lot.bl_awb||'—')}</div></div><div><div class="label">OC/IP</div><div class="value">${esc(lot.oc_number||lot.ip_reference||'—')}</div></div><div><div class="label">EM</div><div class="value">${esc(lot.em_number||'—')}</div></div><div><div class="label">UBICACIÓN</div><div class="value">${esc(lot.location||'—')}</div></div></div>${movements(lot)}</section>`).join('')||'<div class="empty">No se encontraron lotes.</div>'}</div>`}
function mutationMessage(url,body){if(url.endsWith('/rollback'))return 'Atención retrocedida correctamente';if(url.endsWith('/reset'))return 'Atención reiniciada y stock restaurado';if(url.endsWith('/assign'))return 'Responsable actualizado';if(url.endsWith('/status'))return 'Estado actualizado';if(url.endsWith('/type'))return 'Tipo de atención actualizado';if(url.includes('/lines/'))return 'Cantidad registrada';if(url.endsWith('/attentions'))return 'Nueva atención creada';return 'Cambio guardado'}
async function mutate(url,body){
 if(mutationPending)return;
 mutationPending=true;setOperationBusy(true);
 try{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-User':currentUserName(),'X-Role':$('role').value},body:JSON.stringify(body)});const data=await r.json();if(!r.ok){notify(data.error||'No se pudo completar','error');return}await loadOrders();notify(mutationMessage(url,body),'success')}
 catch(error){notify(error.message||'No se pudo completar','error')}
 finally{mutationPending=false;setOperationBusy(false)}
}
async function uploadExcel(){const file=$('excelFile').files[0];if(!file)return;if($('role').value!=='ADMINISTRADOR'){notify('Solo el administrador puede cargar el Excel','error');return}if(!file.name.toLowerCase().endsWith('.xlsx')){notify('Selecciona el Excel .xlsx exportado por el query','error');return}const button=$('importButton');button.disabled=true;button.textContent='Cargando…';try{const r=await fetch('/api/import/excel',{method:'POST',headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','X-File-Name':file.name,'X-User':currentUserName(),'X-Role':$('role').value},body:file});const data=await r.json();if(!r.ok)throw new Error(data.error||'No se pudo importar');const warning=data.stock_shortage_orders?` · ${data.stock_shortage_orders} con faltante`:'';const attended=data.sap_attended_rows?` · ${data.sap_attended_rows} SKU ya atendidos por SAP`:'';const closed=data.closed_orders_updated?` · ${data.closed_orders_updated} OVs cerradas por SAP`:'';const excluded=Number(data.excluded_group_rows||0)+Number(data.excluded_warehouse_rows||0)+Number(data.excluded_document_rows||0);const skipped=data.skipped_rows?` · ${data.skipped_rows} filas vacías`:'';const filtered=excluded?` · ${excluded} fuera del filtro`:'';notify(`Excel actualizado: ${data.orders} OVs y ${data.lines} SKU pendientes${warning}${attended}${closed}${filtered}${skipped}.`,'success');selected=null;await loadOrders()}catch(error){notify(error.message||error,'error')}finally{button.disabled=false;button.textContent='Cargar Excel';$('excelFile').value=''}}
async function uploadImportation(){const file=$('importationFile').files[0];if(!file)return;if($('role').value!=='ADMINISTRADOR'){notify('Solo el administrador puede cargar Importaciones','error');return}if(!file.name.toLowerCase().endsWith('.xlsx')){notify('Selecciona el Excel IMPORTACIÓN DE REPUESTOS .xlsx','error');return}const button=$('importationButton');button.disabled=true;button.textContent='Cargando…';try{const r=await fetch('/api/import/importation',{method:'POST',headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','X-File-Name':file.name,'X-User':currentUserName(),'X-Role':$('role').value},body:file});const data=await r.json();if(!r.ok)throw new Error(data.error||'No se pudo importar Importaciones');notify(`Importaciones actualizadas: ${data.ovs} OVs identificadas en ${data.rows} filas.`, 'success');selected=null;await loadOrders()}catch(error){notify(error.message||error,'error')}finally{button.disabled=false;button.textContent='Cargar Importaciones';$('importationFile').value=''}}
$('search').addEventListener('input',()=>{clearTimeout(window.orderSearchTimer);window.orderSearchTimer=setTimeout(loadOrders,250)});$('search').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();openScannedOrder()}});$('user').addEventListener('change',()=>{selected=null;blankDetail();loadOrders()});$('role').addEventListener('change',()=>{selected=null;blankDetail();applyRoleInterface();loadOrders()});initializeIdentity();
</script><script src="/assets/daily-work.js"></script></body></html>
"""

MANIFEST = {
    "name": "TRITON WMS",
    "short_name": "Triton WMS",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#eef1f3",
    "theme_color": "#f58200",
    "icons": [{"src": "/assets/triton-wms-app-icon.png", "sizes": "1024x1024", "type": "image/png", "purpose": "any maskable"}],
}

APP_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
<rect width="128" height="128" rx="24" fill="#f58200"/>
<path d="M30 38h68v14H30zm12 26h44v28H42z" fill="#1d1d1d"/>
<path d="M52 72h24v10H52z" fill="#f58200"/>
</svg>"""

SERVICE_WORKER = """const CACHE = 'triton-wms-pilot-v1';
self.addEventListener('install', event => event.waitUntil(
  caches.open(CACHE).then(cache => cache.addAll(['/','/reception'])).then(() => self.skipWaiting())
));
self.addEventListener('activate', event => event.waitUntil(
  caches.keys().then(keys => Promise.all(
    keys.filter(key => (key.startsWith('triton-picking-') || key.startsWith('triton-wms-')) && key !== CACHE).map(key => caches.delete(key))
  )).then(() => self.clients.claim())
));
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || new URL(event.request.url).pathname.startsWith('/api/')) return;
  event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
});
"""


class Handler(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        super().end_headers()

    def send_json(self, payload, status=200):
        if status == 403 and getattr(self, '_unauthenticated', False):
            status = 401
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length < 0 or length > 1024 * 1024:
            raise ValueError('Solicitud demasiado grande')
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise ValueError('El cuerpo debe ser un objeto JSON')
        return data

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/login':
            body = (ROOT / 'frontend/templates/login.html').read_bytes()
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path in {'/', '/reception'} and os.getenv('TRITON_AUTH_MODE','demo') == 'local':
            try:
                current_user(self)
            except PermissionError:
                self.send_response(303); self.send_header('Location','/login'); self.end_headers(); return
        if parsed.path in {"/assets/daily-work.js", "/assets/daily-work.css", '/assets/auth-client.js', '/assets/wms-ui.css', '/assets/management.js', '/assets/workspace-shell.js', '/assets/workspace-shell.css'}:
            asset = STATIC_PATH / Path(parsed.path).name
            body = asset.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8" if asset.suffix == ".js" else "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers(); self.wfile.write(body); return
        if parsed.path in {"/api/data-status", "/api/inventory"}:
            try:
                _, role = current_user(self)
                if parsed.path == "/api/inventory" and role != "ADMINISTRADOR":
                    raise PermissionError("La consulta global de stock es solo para el administrador")
                with db() as connection:
                    if parsed.path == "/api/data-status":
                        payload = data_status(connection)
                        if role != "ADMINISTRADOR":
                            payload.pop("history", None)
                            for source in payload["sources"]:
                                source.pop("username", None)
                                source.pop("filename", None)
                    else:
                        search = text(parse_qs(parsed.query).get("search", [""])[0])
                        items = connection.execute("SELECT * FROM inventory_stock WHERE item_code LIKE ? ORDER BY item_code LIMIT 201", ("%"+search+"%",)).fetchall()
                        payload = {"items": [{**dict(item), **operational_balance(connection,item,"","STOCK"), "commitments": commitment_status(connection,item["item_key"])} for item in items[:200]], "has_more":len(items)>200}
                self.send_json(payload)
            except PermissionError as error:
                self.send_json({"error":str(error)},403)
            return
        if parsed.path == "/health":
            try:
                with db() as connection:
                    connection.execute('SELECT 1 FROM orders LIMIT 1').fetchone()
                free = shutil.disk_usage(DB_PATH.parent).free
                if free < 100 * 1024 * 1024:
                    raise RuntimeError('Espacio insuficiente')
                self.send_json({'status':'ok'})
            except Exception:
                self.send_json({'status':'unavailable'},503)
            return
        if parsed.path == "/manifest.webmanifest":
            body = json.dumps(MANIFEST).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "application/manifest+json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/service-worker.js":
            body = SERVICE_WORKER.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "application/javascript"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/icon.svg":
            body = APP_ICON_SVG.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "image/svg+xml"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/assets/triton-logo.png":
            if not LOGO_PATH.exists():
                self.send_json({"error": "Logo no encontrado"}, 404); return
            body = LOGO_PATH.read_bytes()
            self.send_response(200); self.send_header("Content-Type", "image/png"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/assets/triton-wms-app-icon.png":
            asset = STATIC_PATH / "triton-wms-app-icon.png"
            if not asset.exists():
                self.send_json({"error": "Ícono de aplicación no encontrado"}, 404); return
            body = asset.read_bytes()
            self.send_response(200); self.send_header("Content-Type", "image/png"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/":
            body = HTML.replace('</head>', '<link rel="stylesheet" href="/assets/wms-ui.css"><link rel="stylesheet" href="/assets/workspace-shell.css"><script src="/assets/auth-client.js"></script></head>').replace('</body>', '<script src="/assets/management.js"></script><script src="/assets/workspace-shell.js"></script></body>').encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/reception":
            if not RECEPTION_HTML_PATH.exists():
                self.send_json({"error": "Interfaz de Recepción no encontrada"}, 404); return
            body = RECEPTION_HTML_PATH.read_bytes()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/api/me":
            try:
                username, role = current_user(self)
                modules = ["despacho", "recepcion"] if role == "ADMINISTRADOR" else (["recepcion"] if role in RECEPTION_ROLES else ["despacho"])
                self.send_json({"username": username, "role": role, "modules": modules, "mode": os.getenv("TRITON_AUTH_MODE", "demo")})
            except PermissionError as error:
                self.send_json({"error": str(error)}, 401)
            return
        if parsed.path == "/api/account":
            try:
                username, role = current_user(self)
                payload = {"username": username, "display_name": username, "first_name": "", "last_name": "", "document_id": "", "role": role, "shift": "", "mode": os.getenv("TRITON_AUTH_MODE", "demo")}
                if os.getenv("TRITON_AUTH_MODE", "demo") == "local":
                    with db() as connection:
                        account = identity.session_user(connection, self.headers)
                    payload.update(account)
                self.send_json(payload)
            except PermissionError as error:
                self.send_json({"error": str(error)}, 401)
            return
        if parsed.path == "/api/traceability":
            if not advanced_lots_enabled():
                self.send_json({"error":"Trazabilidad avanzada reservada para la etapa 3"},404); return
            try:
                _, role = current_user(self)
                if role != "ADMINISTRADOR":
                    raise PermissionError("La consulta completa de trazabilidad es solo para el administrador")
            except PermissionError as error:
                self.send_json({"error": str(error)}, 403); return
            search = parse_qs(parsed.query).get("search", [""])[0]
            with db() as connection:
                self.send_json(traceability_search(connection, search))
            return
        if parsed.path == "/api/receptions":
            try:
                username, role = current_user(self)
                require_reception_access(role)
            except PermissionError as error:
                self.send_json({"error": str(error)}, 403); return
            query = parse_qs(parsed.query)
            search = query.get("search", [""])[0]
            try:
                with db() as connection:
                    self.send_json(list_receptions(connection, search, role, username,
                        arrival_date=query.get("date", [""])[0],
                        arrival_date_end=query.get("date_end", [""])[0],
                        state=query.get("state", [""])[0]))
            except ValueError:
                self.send_json({"error": "Selecciona una fecha de llegada válida"}, 400)
            return
        if parsed.path == "/api/receptions/report":
            try:
                _, role = current_user(self)
                require_reception_access(role)
            except PermissionError as error:
                self.send_json({"error": str(error)}, 403); return
            if role != "ADMINISTRADOR":
                self.send_json({"error": "La reportería de Recepción es solo para el administrador"}, 403); return
            with db() as connection:
                self.send_json(reception_report(connection, role)); return
        if parsed.path == "/api/work-summary":
            query = parse_qs(parsed.query)
            module = query.get("module", ["dispatch"])[0]
            try:
                username, role = current_user(self)
                if module == "reception":
                    require_reception_access(role)
                else:
                    require_dispatch_access(role)
                self.send_json(work_summary(module, username, role))
            except PermissionError as error:
                self.send_json({"error": str(error)}, 403)
            return
        if parsed.path == "/api/receptions/history/report":
            try:
                _, role = current_user(self)
                if role != "ADMINISTRADOR":
                    raise PermissionError("El historial de Recepción es solo para el administrador")
            except PermissionError as error:
                self.send_json({"error": str(error)}, 403); return
            with db() as connection:
                self.send_json(reception_history_report(connection, role)); return
        if parsed.path == "/api/receptions/history/export":
            try:
                _, role = current_user(self)
                if role != "ADMINISTRADOR":
                    raise PermissionError("El historial de Recepción es solo para el administrador")
            except PermissionError as error:
                self.send_json({"error": str(error)}, 403); return
            with db() as connection:
                body = reception_history_export_bytes(connection, role)
            filename = f"triton_recepcion_historial_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path.startswith("/api/receptions/") and parsed.path.endswith("/system-report"):
            try:
                username, role = current_user(self)
                require_reception_access(role)
                shipment_id = int(parsed.path.split("/")[3])
            except PermissionError as error:
                self.send_json({"error": str(error)}, 403); return
            except (IndexError, ValueError):
                self.send_json({"error": "Expediente de recepción no válido"}, 400); return
            with db() as connection:
                body = reception_operational_report_bytes(connection, shipment_id, role, username)
            filename = f"triton_recepcion_{shipment_id}_reporte.xlsx"
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path.startswith("/api/receptions/"):
            try:
                username, role = current_user(self)
                require_reception_access(role)
                shipment_id = int(parsed.path.split("/")[3])
            except PermissionError as error:
                self.send_json({"error": str(error)}, 403); return
            except (IndexError, ValueError):
                self.send_json({"error": "Expediente de recepción no válido"}, 400); return
            with db() as connection:
                if parsed.path.endswith("/links"):
                    payload = reception_links(connection, shipment_id, role, username)
                else:
                    payload = reception_detail(connection, shipment_id, role, username)
            self.send_json(payload or {"error": "BL/AWB no encontrada"}, 200 if payload else 404); return
        if parsed.path == "/api/orders":
            try:
                username, role = current_user(self)
                require_dispatch_access(role)
            except PermissionError as error:
                self.send_json({"error": str(error)}, 403); return
            search = parse_qs(parsed.query).get("search", [""])[0]
            creation_date = parse_qs(parsed.query).get("date", [""])[0]
            creation_date_end = parse_qs(parsed.query).get("date_end", [""])[0]
            try:
                self.send_json(orders_payload(search, username=username, role=role,
                    creation_date=creation_date, creation_date_end=creation_date_end))
            except ValueError as error:
                self.send_json({"error": str(error)}, 400)
            return
        if parsed.path == "/api/reports/operational":
            try:
                _, role = current_user(self)
                require_dispatch_access(role)
            except PermissionError as error:
                self.send_json({"error": str(error)}, 401); return
            if role != "ADMINISTRADOR":
                self.send_json({"error": "La reportería es solo para el administrador"}, 403); return
            self.send_json(operational_report()); return
        if parsed.path == "/api/reports/workload":
            try:
                _, role = current_user(self)
                if role != "ADMINISTRADOR":
                    raise PermissionError("La reportería es solo para el administrador")
                period = parse_qs(parsed.query).get("period", ["day"])[0].lower()
                if period not in {"all", "day", "week", "weekdays"}:
                    raise ValueError("Periodo no válido")
                params = parse_qs(parsed.query)
                self.send_json(workload_report(period, params.get('start',[None])[0], params.get('end',[None])[0]))
            except PermissionError as error:
                self.send_json({"error": str(error)}, 403)
            except ValueError as error:
                self.send_json({"error": str(error)}, 400)
            return
        if parsed.path == '/api/notifications':
            try:
                _, role = current_user(self)
                if role != 'ADMINISTRADOR':
                    raise PermissionError('La bandeja de correos es solo para el administrador')
                with db() as connection:
                    payload = notification_summary(connection)
                    payload['rows'] = [dict(row) for row in connection.execute('''SELECT n.id,n.status,n.recipient,n.subject,n.body,n.created_at,n.sent_at,n.error,n.attempt_count,s.bl_awb
                        FROM reception_notifications n JOIN reception_shipments s ON s.id=n.shipment_id ORDER BY n.id DESC LIMIT 200''')]
                config = GraphConfig.from_environ()
                payload['configured'] = config.enabled and not config.missing
                payload['sender'] = config.sender
                self.send_json(payload)
            except PermissionError as error:
                self.send_json({'error':str(error)},403)
            return
        if parsed.path == "/api/users":
            try:
                _, role = current_user(self)
                if role != "ADMINISTRADOR":
                    raise PermissionError("La administración de usuarios es solo para el administrador")
                self.send_json({"users": list_users()})
            except PermissionError as error:
                self.send_json({"error": str(error)}, 403)
            return
        if parsed.path == "/api/assignees":
            try:
                _, role = current_user(self)
                if role != "ADMINISTRADOR":
                    raise PermissionError("Solo el administrador puede consultar responsables")
                query = parse_qs(urlparse(self.path).query)
                requested_role = query.get("role", [""])[0]
                include_reception = query.get("include_reception", ["0"])[0] == "1"
                self.send_json({"users": list_assignees(requested_role, include_reception=include_reception)})
            except PermissionError as error:
                self.send_json({"error": str(error)}, 403)
            except ValueError as error:
                self.send_json({"error": str(error)}, 400)
            return
        if parsed.path.startswith("/api/orders/") and parsed.path.endswith("/fulfillment"):
            ov = parsed.path.split("/")[3]
            try:
                username, role = current_user(self)
                require_dispatch_access(role)
            except PermissionError as error:
                self.send_json({"error": str(error)}, 401); return
            if not can_view_order(ov, username, role):
                self.send_json({"error": "No tienes acceso a esta OV"}, 403); return
            with db() as connection:
                order = connection.execute("SELECT 1 FROM orders WHERE sap_ov = ?", (ov,)).fetchone()
                if not order:
                    self.send_json({"error": "OV no encontrada"}, 404)
                else:
                    self.send_json(fulfillment_summary(connection, ov))
            return
        if parsed.path.startswith("/api/attentions/"):
            try:
                username, role = current_user(self)
                require_dispatch_access(role)
            except PermissionError as error:
                self.send_json({"error": str(error)}, 401); return
            try:
                attention_id = int(parsed.path.split("/")[3])
            except (IndexError, ValueError):
                self.send_json({"error": "Atención no válida"}, 400); return
            with db() as connection:
                payload = attention_payload(connection, attention_id)
            if payload and not can_view_order(payload["sap_ov"], username, role):
                self.send_json({"error": "No tienes acceso a esta atención"}, 403); return
            self.send_json(payload_for_role(payload, role) or {"error": "Atención no encontrada"}, 200 if payload else 404); return
        if parsed.path.startswith("/api/orders/"):
            try:
                username, role = current_user(self)
                require_dispatch_access(role)
            except PermissionError as error:
                self.send_json({"error": str(error)}, 401); return
            ov = parsed.path.split("/", 3)[3]
            if not can_view_order(ov, username, role):
                self.send_json({"error": "No tienes acceso a esta OV"}, 403); return
            payload = order_payload(ov)
            self.send_json(payload_for_role(payload, role) or {"error": "OV no encontrada"}, 200 if payload else 404); return
        self.send_json({"error": "No encontrado"}, 404)

    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            if os.getenv('TRITON_AUTH_MODE','demo') == 'local':
                if self.headers.get('X-WMS-Request') != '1' or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                    raise PermissionError('Actualiza la página antes de enviar cambios')
            if parsed.path == '/api/login':
                if os.getenv('TRITON_AUTH_MODE','demo') != 'local':
                    raise ValueError('El inicio de sesión local no está habilitado')
                data = self.body()
                with db() as connection:
                    connection.execute('BEGIN IMMEDIATE')
                    token, user = identity.login(connection,data.get('username'),data.get('password'),self.client_address[0])
                if not token:
                    self.send_json({'error':'Usuario o contraseña incorrectos. Tras varios intentos espera 15 minutos.'},401); return
                body = json.dumps(user).encode()
                self.send_response(200); self.send_header('Set-Cookie',identity.cookie_header(token)); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
            if parsed.path == '/api/logout':
                with db() as connection:
                    identity.logout(connection,self.headers)
                self.send_response(200); self.send_header('Set-Cookie',identity.cookie_header('',expired=True)); self.send_header('Content-Length','0'); self.end_headers(); return
            username, role = current_user(self)
            if parsed.path.startswith('/api/notifications/') and parsed.path.endswith('/retry'):
                if role != 'ADMINISTRADOR':
                    raise PermissionError('Solo el administrador puede reintentar correos')
                with db() as connection:
                    connection.execute('BEGIN IMMEDIATE')
                    payload = retry_notification(connection,int(parsed.path.split('/')[3]),username)
                self.send_json(payload); return
            import_routes = {"/api/import/excel":"dispatch", "/api/import/importation":"importation", "/api/receptions/import":"importation", "/api/receptions/import-accounting":"accounting"}
            if parsed.path == "/api/daily-import" or parsed.path in import_routes:
                if role != "ADMINISTRADOR":
                    raise PermissionError("Solo el administrador puede cargar cortes Excel")
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > MAX_IMPORT_BYTES:
                    raise ValueError("Selecciona un Excel de hasta 50 MB")
                payload = import_daily_excel(self.rfile.read(length),
                    unquote(self.headers.get("X-File-Name", "datos.xlsx")),
                    import_routes.get(parsed.path, self.headers.get("X-Source-Type", "")),
                    self.headers.get("X-Cutoff-At"), username, role,
                    self.headers.get("X-Reconcile-Delivered", "0") == "1")
                self.send_json(payload); return
            if parsed.path == "/api/users":
                payload = save_user(self.body(), username, role)
                self.send_json(payload); return
            if parsed.path.startswith("/api/users/") and parsed.path.endswith("/deactivate"):
                user = unquote(parsed.path.split("/")[3])
                self.send_json({"users": deactivate_user(user, username, role)}); return
            if not advanced_lots_enabled() and (parsed.path.startswith("/api/lots/") or parsed.path.startswith("/api/lot-reservations/") or parsed.path.endswith(("/scan-lot","/assign-lot"))):
                raise PermissionError("El control por lote corresponde a la etapa 3")
            if parsed.path == "/api/import/excel":
                require_dispatch_access(role)
                try:
                    length = int(self.headers.get("Content-Length", 0))
                except ValueError:
                    raise ValueError("Tamaño de archivo inválido")
                if length <= 0:
                    raise ValueError("Selecciona un archivo Excel")
                if length > MAX_IMPORT_BYTES:
                    raise ValueError("El archivo supera el límite de 50 MB")
                content = self.rfile.read(length)
                result = import_uploaded_excel(
                    content,
                    unquote(self.headers.get("X-File-Name", "exportacion.xlsx")),
                    username,
                    role,
                )
                self.send_json(result); return
            if parsed.path == "/api/import/importation":
                require_dispatch_access(role)
                if role != "ADMINISTRADOR":
                    raise PermissionError("Solo el administrador puede cargar el Excel de Importaciones")
                try:
                    length = int(self.headers.get("Content-Length", 0))
                except ValueError:
                    raise ValueError("Tamaño de archivo inválido")
                if length <= 0:
                    raise ValueError("Selecciona el archivo IMPORTACIÓN DE REPUESTOS .xlsx")
                if length > MAX_IMPORT_BYTES:
                    raise ValueError("El archivo supera el límite de 50 MB")
                content = self.rfile.read(length)
                result = import_importation_uploaded_excel(
                    content,
                    unquote(self.headers.get("X-File-Name", "IMPORTACION DE REPUESTOS.xlsx")),
                    username,
                    role,
                )
                self.send_json(result); return
            if parsed.path == "/api/receptions/import":
                require_reception_access(role)
                if role != "ADMINISTRADOR":
                    raise PermissionError("Solo el administrador puede cargar el Excel de Recepción")
                try:
                    length = int(self.headers.get("Content-Length", 0))
                except ValueError:
                    raise ValueError("Tamaño de archivo inválido")
                if length <= 0:
                    raise ValueError("Selecciona el archivo IMPORTACIÓN DE REPUESTOS .xlsx")
                if length > MAX_IMPORT_BYTES:
                    raise ValueError("El archivo supera el límite de 50 MB")
                content = self.rfile.read(length)
                with db() as connection:
                    result = import_reception_excel_bytes(
                        connection,
                        content,
                        unquote(self.headers.get("X-File-Name", "IMPORTACION DE REPUESTOS.xlsx")),
                        username,
                        role,
                    )
                self.send_json(result); return
            if parsed.path == "/api/receptions/import-accounting":
                require_reception_access(role)
                if role != "ADMINISTRADOR":
                    raise PermissionError("Solo el administrador puede cargar el Excel de FR/EM")
                try:
                    length = int(self.headers.get("Content-Length", 0))
                except ValueError:
                    raise ValueError("Tamaño de archivo inválido")
                if length <= 0:
                    raise ValueError("Selecciona el archivo contable de FR/EM .xlsx")
                if length > MAX_IMPORT_BYTES:
                    raise ValueError("El archivo supera el límite de 50 MB")
                content = self.rfile.read(length)
                with db() as connection:
                    result = import_reception_accounting_excel_bytes(
                        connection,
                        content,
                        unquote(self.headers.get("X-File-Name", "FACTURAS DHL.xlsx")),
                        username,
                        role,
                    )
                self.send_json(result); return
            data = self.body()
            if parsed.path.startswith("/api/lots/"):
                try:
                    lot_id = int(parsed.path.split("/")[3])
                except (IndexError, TypeError, ValueError):
                    raise ValueError("Lote no válido")
                require_reception_access(role)
                with db() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    owner = connection.execute(
                        """SELECT s.current_assistant, s.current_auxiliary
                           FROM inventory_lots lot
                           JOIN reception_shipments s ON s.id = lot.reception_shipment_id
                           WHERE lot.id = ?""",
                        (lot_id,),
                    ).fetchone()
                    if not owner:
                        raise ValueError("Lote no encontrado")
                    assigned = text(username).casefold() in {
                        text(owner["current_assistant"]).casefold(),
                        text(owner["current_auxiliary"]).casefold(),
                    }
                    if role != "ADMINISTRADOR" and not assigned:
                        raise PermissionError("El lote no pertenece a una recepción asignada a tu usuario")
                    if parsed.path.endswith("/location"):
                        payload = update_lot_location(
                            connection, lot_id, data.get("location", ""), username,
                            data.get("reason", ""),
                        )
                    elif parsed.path.endswith("/print"):
                        payload = register_label_print(
                            connection, lot_id, data.get("copies", 1), username,
                            bool(data.get("reprint")),
                        )
                    else:
                        self.send_json({"error": "Acción de lote no encontrada"}, 404); return
                self.send_json(payload); return
            if parsed.path == "/api/receptions":
                with db() as connection:
                    identity.require_assignee(connection, data.get('current_assistant'), 'ASISTENTE_RECEPCION')
                    identity.require_assignee(connection, data.get('current_auxiliary'), 'AUXILIAR_RECEPCION')
                    payload = create_reception(connection, data, username, role)
                self.send_json(payload, 201); return
            if parsed.path.startswith("/api/receptions/"):
                try:
                    shipment_id = int(parsed.path.split("/")[3])
                except (IndexError, TypeError, ValueError):
                    raise ValueError("Selecciona nuevamente una BL/AWB válida")
                with db() as connection:
                    if parsed.path.endswith("/receipts"):
                        payload = add_physical_receipt(connection, shipment_id, data, username, role)
                    elif parsed.path.endswith("/receipts/close"):
                        payload = close_physical_receipts(connection, shipment_id, data, username, role)
                    elif parsed.path.endswith("/references"):
                        identity.require_assignee(connection, data.get('current_assistant'), 'ASISTENTE_RECEPCION')
                        identity.require_assignee(connection, data.get('current_auxiliary'), 'AUXILIAR_RECEPCION')
                        payload = update_reception_references(connection, shipment_id, data, username, role)
                    elif parsed.path.endswith("/location"):
                        payload = update_reception_location(connection, shipment_id, data, username, role)
                    elif parsed.path.endswith("/validation"):
                        payload = update_reception_validation(connection, shipment_id, data, username, role)
                    elif parsed.path.endswith("/transfer-check"):
                        payload = confirm_reception_transfer(connection, shipment_id, data, username, role)
                    elif parsed.path.endswith("/rewind"):
                        payload = rewind_reception_stage(connection, shipment_id, data, username, role)
                    elif parsed.path.endswith("/status"):
                        payload = change_reception_status(connection, shipment_id, data, username, role)
                    elif "/lines/" in parsed.path:
                        line_id = int(parsed.path.split("/")[5])
                        payload = update_reception_line_quantity(
                            connection, shipment_id, line_id, data, username, role
                        )
                    else:
                        self.send_json({"error": "Ruta de Recepción no encontrada"}, 404); return
                self.send_json(payload); return
            require_dispatch_access(role)
            if parsed.path.startswith("/api/attention-lines/") and parsed.path.endswith("/scan-lot"):
                line_id = int(parsed.path.split("/")[3])
                with db() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    payload = validate_lot_scan(
                        connection, line_id, data.get("lot_code", ""), username, role,
                        data.get("reason", ""),
                    )
                self.send_json(payload); return
            if parsed.path.startswith("/api/attention-lines/") and parsed.path.endswith("/assign-lot"):
                if role != "ADMINISTRADOR":
                    raise PermissionError("Solo el administrador puede asignar un lote manualmente")
                line_id = int(parsed.path.split("/")[3])
                with db() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    payload = assign_lot_manually(
                        connection, line_id, int(data.get("lot_id") or 0),
                        data.get("quantity", 0), username, data.get("reason", ""),
                    )
                self.send_json(payload); return
            if parsed.path.startswith("/api/lot-reservations/") and parsed.path.endswith("/return"):
                if role != "ADMINISTRADOR":
                    raise PermissionError("Solo el administrador puede registrar una devolución")
                reservation_id = int(parsed.path.split("/")[3])
                with db() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    payload = return_lot_after_picking(
                        connection, reservation_id, data.get("quantity", 0), username,
                        data.get("reason", ""),
                    )
                self.send_json(payload); return
            if parsed.path.startswith("/api/orders/") and parsed.path.endswith("/attentions"):
                ov = parsed.path.split("/")[3]
                payload = create_attention(ov, username, role)
                self.send_json(payload, 201); return
            if parsed.path.startswith("/api/attentions/") and parsed.path.endswith("/status"):
                attention_id = int(parsed.path.split("/")[3])
                payload = change_attention_status(attention_id, data.get("status", ""), username, role)
                self.send_json(payload); return
            if parsed.path.startswith("/api/attentions/") and parsed.path.endswith("/rollback"):
                attention_id = int(parsed.path.split("/")[3])
                payload = admin_rollback_attention(
                    attention_id, username, role, data.get("reason", "")
                )
                self.send_json(payload); return
            if parsed.path.startswith("/api/attentions/") and parsed.path.endswith("/reset"):
                attention_id = int(parsed.path.split("/")[3])
                payload = admin_reset_attention(
                    attention_id, username, role, data.get("reason", "")
                )
                self.send_json(payload); return
            if parsed.path.startswith("/api/attentions/") and parsed.path.endswith("/assign"):
                attention_id = int(parsed.path.split("/")[3])
                payload = assign_attention(attention_id, data.get("field", ""), text(data.get("value")), username, role)
                self.send_json(payload); return
            if parsed.path.startswith("/api/attentions/") and parsed.path.endswith("/type"):
                attention_id = int(parsed.path.split("/")[3])
                payload = set_attention_type(attention_id, data.get("attention_type", ""), username, role)
                self.send_json(payload); return
            if parsed.path.startswith("/api/attentions/") and "/lines/" in parsed.path:
                parts = parsed.path.split("/")
                attention_id = int(parts[3])
                line_id = int(parts[5])
                payload = update_attention_line(attention_id, line_id, data.get("field", ""), data.get("value"), username, role)
                self.send_json(payload); return
            if parsed.path.endswith("/status"):
                ov = parsed.path.split("/", 4)[3]
                with db() as connection:
                    attention_id = active_attention_id(connection, ov)
                if attention_id:
                    change_attention_status(attention_id, data.get("status", ""), username, role)
                else:
                    change_status(ov, data.get("status", ""), username, role)
            elif parsed.path.endswith("/assign"):
                ov = parsed.path.split("/", 4)[3]
                with db() as connection:
                    attention_id = active_attention_id(connection, ov)
                if attention_id:
                    assign_attention(attention_id, data.get("field", ""), text(data.get("value")), username, role)
                else:
                    assign_order(ov, data.get("field", ""), text(data.get("value")), username, role)
            else:
                self.send_json({"error": "Ruta no encontrada"}, 404); return
            self.send_json(order_payload(ov))
        except PermissionError as error:
            self.send_json({"error": str(error)}, 403)
        except Exception as error:
            self.send_json({"error": str(error)}, 400)


def main():
    global DB_PATH, PORT, HOST
    parser = argparse.ArgumentParser()
    parser.add_argument("--excel", help="Ruta al Excel exportado del query")
    parser.add_argument("--reception-excel", help="Ruta al Excel IMPORTACIÓN DE REPUESTOS")
    parser.add_argument("--accounting-excel", help="Ruta al Excel contable con FR, EM y fechas")
    parser.add_argument("--reset", action="store_true", help="Reemplaza los datos importados")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    args = parser.parse_args()
    os.environ.setdefault('TRITON_AUTH_MODE','local')
    PORT = args.port
    HOST = args.host
    init_db()
    if os.environ['TRITON_AUTH_MODE'] == 'local':
        with db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            identity.bootstrap_admin(connection,ROLES)
    with db() as connection:
        seed_initial_attentions(connection)
    if args.excel:
        result = import_excel(Path(args.excel), reset=args.reset)
        print(f"Importadas {result['orders']} OVs y {result['lines']} líneas")
    if args.reception_excel:
        with db() as connection:
            result = import_reception_excel_path(connection, Path(args.reception_excel))
        print(
            f"Recepción: {result['shipments']} BL/AWB y "
            f"{result['lines_created']} líneas nuevas ({result['lines_updated']} actualizadas)"
        )
    if args.accounting_excel:
        with db() as connection:
            result = import_reception_accounting_excel_path(
                connection, Path(args.accounting_excel)
            )
        print(
            f"FR/EM: {result['matched_records']} referencias enlazadas con "
            f"{result['shipments_updated']} BL/AWB "
            f"({result['unmatched_count']} sin coincidencia)"
        )
    print(f"TRITON WMS Piloto disponible en http://{HOST}:{PORT}")
    from backend.wsgi import serve
    serve(HOST, PORT)


if __name__ == "__main__":
    main()
