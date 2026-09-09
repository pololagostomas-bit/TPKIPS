"""Etapa 1: cortes Excel y compromisos, sin ingresos de stock desde Importaciones."""

import hashlib
import json
import math
import os
import sqlite3
import re
import unicodedata
from datetime import datetime, timedelta, timezone

LIMA = timezone(timedelta(hours=-5))
SOURCES = {"dispatch": "OV y stock SAP", "importation": "Importaciones / compromisos", "accounting": "FR / EM"}
READY_RECEPTION = {"SOLICITUD TRANSFERENCIA", "CERRADO"}


class DailyConnection(sqlite3.Connection):
    """Cache local a una consulta HTTP; nunca compartido entre usuarios."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.daily_cache = {}

    def execute(self, sql, parameters=(), /):
        if sql.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE", "ALTER", "CREATE"}:
            self.daily_cache.clear()
        return super().execute(sql, parameters)


def local_now():
    return datetime.now(LIMA).replace(tzinfo=None).isoformat(timespec="seconds")


def advanced_lots_enabled():
    return os.getenv("TRITON_ADVANCED_LOTS", "0").lower() in {"1", "true", "yes"}


def normalize_cutoff(value=None):
    current = datetime.fromisoformat(local_now())
    if not value:
        cutoff = current.replace(hour=16, minute=0, second=0, microsecond=0)
        if cutoff > current:
            cutoff -= timedelta(days=1)
    else:
        try:
            cutoff = datetime.fromisoformat(str(value).strip())
            if cutoff.tzinfo:
                cutoff = cutoff.astimezone(LIMA).replace(tzinfo=None)
        except ValueError as error:
            raise ValueError("Indica la fecha y hora reales del corte Excel") from error
        if cutoff > current + timedelta(minutes=5):
            raise ValueError("La fecha del corte no puede estar en el futuro")
    return cutoff.isoformat(timespec="seconds")


def init_daily_schema(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS data_imports (
        id INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT NOT NULL,
        filename TEXT NOT NULL, file_hash TEXT NOT NULL, cutoff_at TEXT NOT NULL,
        loaded_at TEXT NOT NULL, username TEXT NOT NULL, summary TEXT NOT NULL,
        UNIQUE(source_type, cutoff_at, file_hash))""")
    for table, name, spec in (
        ("order_importation_refs", "quantity", "REAL"),
        ("order_importation_refs", "item_key", "TEXT"),
        ("orders", "source_cutoff_at", "TEXT"),
        ("orders", "source_present", "INTEGER NOT NULL DEFAULT 1"),
        ("order_lines", "source_key", "TEXT"),
        ("stock_allocations", "reconciled_qty", "REAL NOT NULL DEFAULT 0"),
    ):
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if name not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {spec}")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_line_source_key ON order_lines(sap_ov, source_key) WHERE source_key IS NOT NULL")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_ref_item_key ON order_importation_refs(item_key, sap_ov)")
    for row in connection.execute("SELECT id, item_code FROM order_importation_refs WHERE item_key IS NULL").fetchall():
        connection.execute("UPDATE order_importation_refs SET item_key = ? WHERE id = ?", (item_key(row["item_code"]), row["id"]))


def import_identity(content, source_type, cutoff_at, filename, username):
    if source_type not in SOURCES:
        raise ValueError("Tipo de Excel no válido")
    return {"source_type": source_type, "filename": filename,
            "file_hash": hashlib.sha256(content).hexdigest(), "cutoff_at": normalize_cutoff(cutoff_at),
            "loaded_at": local_now(), "username": username}


def check_import(connection, identity):
    latest = connection.execute("SELECT * FROM data_imports WHERE source_type = ? ORDER BY cutoff_at DESC, id DESC LIMIT 1", (identity["source_type"],)).fetchone()
    if latest and identity["cutoff_at"] < latest["cutoff_at"]:
        raise ValueError(f"El corte es anterior al vigente ({latest['cutoff_at']}). No se actualizaron datos.")
    if latest and identity["cutoff_at"] == latest["cutoff_at"] and identity["file_hash"] == latest["file_hash"]:
        return {**json.loads(latest["summary"]), "duplicate": True, "cutoff_at": latest["cutoff_at"], "message": "Este corte ya está cargado; se conservaron los movimientos."}
    # A → B → A en un mismo corte sería una reversión silenciosa.
    previous = connection.execute("SELECT 1 FROM data_imports WHERE source_type=? AND cutoff_at=? AND file_hash=?", (identity["source_type"], identity["cutoff_at"], identity["file_hash"])).fetchone()
    if previous:
        raise ValueError("Este archivo fue reemplazado por una corrección del mismo corte. Usa el archivo vigente.")
    return None


def record_import(connection, identity, summary):
    connection.execute("""INSERT INTO data_imports
        (source_type, filename, file_hash, cutoff_at, loaded_at, username, summary)
        VALUES (?, ?, ?, ?, ?, ?, ?)""", tuple(identity[key] for key in ("source_type", "filename", "file_hash", "cutoff_at", "loaded_at", "username")) + (json.dumps(summary, ensure_ascii=False),))


def data_status(connection):
    rows = connection.execute("SELECT * FROM data_imports ORDER BY cutoff_at DESC, id DESC").fetchall()
    latest = {}
    for row in rows:
        if row["source_type"] not in latest:
            latest[row["source_type"]] = {key: row[key] for key in ("source_type", "filename", "cutoff_at", "loaded_at", "username")}
    expected = normalize_cutoff()
    return {"stage": 1, "advanced_lots": advanced_lots_enabled(), "expected_cutoff": expected,
            "sources": [{"source_type": code, "label": label, **latest.get(code, {}),
                         "status": "SIN CARGAR" if code not in latest else "ACTUALIZAR" if latest[code]["cutoff_at"] < expected else "VIGENTE"}
                        for code, label in SOURCES.items()],
            "history": [{key: row[key] for key in ("source_type", "filename", "cutoff_at", "loaded_at", "username")} for row in rows[:30]]}


def item_key(value):
    return re.sub(r"[^A-Z0-9]", "", unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().upper())


def qty(value):
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, amount) if math.isfinite(amount) else 0.0


def commitment_status(connection, key):
    """El compromiso es una retención del saldo, nunca un ingreso."""
    cache = getattr(connection, "daily_cache", {})
    cache_key = ("commitment", key)
    if cache_key in cache:
        return cache[cache_key]
    refs = connection.execute("""SELECT r.*, s.app_status AS reception_status,
        s.received_packages FROM order_importation_refs r
        LEFT JOIN reception_shipments s ON upper(trim(s.bl_awb)) = upper(trim(r.bl_awb))
        WHERE r.item_key = ? OR r.item_key IS NULL""", (key,)).fetchall()
    result = {}
    for ref in refs:
        if item_key(ref["item_code"]) != key:
            continue
        if ref["transport_type"] not in {"AEREO", "COURIER", "MARITIMO"}:
            continue
        ov = ref["sap_ov"]
        entry = result.setdefault(ov, {"quantity": 0.0, "arrived_qty": 0.0, "ready_qty": 0.0,
                                       "unknown_qty": False, "bls": [], "pending_bls": []})
        pending = sum(qty(row["pending_qty"]) for row in connection.execute(
            "SELECT item_code, pending_qty FROM order_lines WHERE sap_ov = ? AND is_pending_sap = 1", (ov,)
        ) if item_key(row["item_code"]) == key)
        amount = min(qty(ref["quantity"]), pending) if ref["quantity"] is not None else pending
        entry["unknown_qty"] |= ref["quantity"] is None
        entry["quantity"] += amount
        ready = ref["reception_status"] in READY_RECEPTION
        arrived = ready or (ref["reception_status"] not in {None, "PROGRAMADO"})
        if arrived:
            entry["arrived_qty"] += amount
        if ready:
            entry["ready_qty"] += amount
        elif amount > 0:
            entry["pending_bls"].append(ref["bl_awb"] or "Sin BL/AWB")
        if ref["bl_awb"] not in entry["bls"]:
            entry["bls"].append(ref["bl_awb"])
        entry["pending_cap"] = pending
    for entry in result.values():
        for field in ("quantity", "arrived_qty", "ready_qty"):
            entry[field] = min(entry[field], entry["pending_cap"])
    cache[cache_key] = result
    return result


def operational_balance(connection, inventory, sap_ov, origin_type):
    key, warehouse = inventory["item_key"], inventory["warehouse_key"]
    allocations = connection.execute("""SELECT sap_ov, status, reserved_qty,
        consumed_qty, reconciled_qty FROM stock_allocations
        WHERE item_key = ? AND warehouse_key = ? AND status IN ('ACTIVA', 'CONSUMIDA')""", (key, warehouse)).fetchall()
    usage = {}
    active = consumed = 0.0
    for row in allocations:
        amount = qty(row["reserved_qty"]) if row["status"] == "ACTIVA" else max(0, qty(row["consumed_qty"]) - qty(row["reconciled_qty"]))
        usage[row["sap_ov"]] = usage.get(row["sap_ov"], 0) + amount
        if row["status"] == "ACTIVA": active += amount
        else: consumed += amount
    returns = qty(connection.execute("""SELECT COALESCE(SUM(quantity), 0) FROM stock_movements
        WHERE item_key=? AND warehouse_key=? AND movement_type='REINTEGRO_CORTE' AND created_at > ?""", (key, warehouse, inventory["snapshot_at"])).fetchone()[0])
    source = qty(inventory["snapshot_qty"]) if inventory["is_current"] else 0.0
    commitments = commitment_status(connection, key)
    own = commitments.get(sap_ov, {})
    other_hold = sum(max(0, entry["arrived_qty"] - usage.get(ov, 0)) for ov, entry in commitments.items() if ov != sap_ov)
    free = max(0, source + returns - active - consumed - other_hold)
    if origin_type in {"AEREO", "MARITIMO"} and own:
        free = min(free, max(0, own.get("ready_qty", 0) - usage.get(sap_ov, 0)))
    reason = ""
    if not inventory["is_current"]:
        reason = "NP sin stock en el último corte"
    elif own.get("pending_bls") and own.get("ready_qty", 0) == 0:
        reason = "Pendiente de completar Recepción: " + ", ".join(dict.fromkeys(own["pending_bls"]))
    elif free == 0:
        reason = "Sin saldo libre del corte Excel"
    return {"origin_type": origin_type, "pool_type": "AEREO" if origin_type == "AEREO" else "STOCK",
            "source_total": source, "reserved_total": active, "consumed_total": consumed,
            "free_qty": free, "committed_other_qty": other_hold, "committed_for_ov": own.get("quantity", 0),
            "snapshot_at": inventory["snapshot_at"], "stock_reason": reason,
            "adjustment_qty": returns, "stock_deficit": max(0, active + consumed + other_hold - source - returns)}


def reconcile_deliveries(connection, cutoff):
    # El administrador declara que el corte SAP incluye las entregas finalizadas
    # hasta esa hora. Las reservas y los picks sin entregar siguen descontándose.
    connection.execute("""UPDATE stock_allocations SET reconciled_qty = consumed_qty
        WHERE status = 'CONSUMIDA' AND (attention_id IN
          (SELECT id FROM attentions WHERE app_status = 'CERRADO SAP') OR attention_id IN
          (SELECT a.id FROM attentions a WHERE a.app_status = 'ENTREGADO'
           AND EXISTS(SELECT 1 FROM attention_history h WHERE h.attention_id=a.id
             AND h.event_type='ESTADO' AND h.new_value='ENTREGADO' AND h.created_at<=?)))""", (cutoff,))


def return_reconciled_stock(connection, allocation, username, timestamp):
    amount = qty(allocation["reconciled_qty"])
    if amount <= 0:
        return
    connection.execute("""INSERT INTO stock_movements
        (allocation_id,attention_id,attention_line_id,sap_ov,item_key,item_code,warehouse_key,warehouse,pool_type,movement_type,quantity,username,reason,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,'REINTEGRO_CORTE',?,?,?,?)""",
        tuple(allocation[key] for key in ("id","attention_id","attention_line_id","sap_ov","item_key","item_code","warehouse_key","warehouse","pool_type")) +
        (amount, username, "Corrección de consumo ya incluido en el corte SAP", timestamp))
    connection.execute("UPDATE stock_allocations SET reconciled_qty=0 WHERE id=?", (allocation["id"],))
