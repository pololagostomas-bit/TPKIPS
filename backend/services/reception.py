"""Dominio inicial del módulo Recepción de TRITON WMS.

El módulo comparte la base SQLite del piloto, pero usa tablas y estados propios.
Esto permite desplegarlo junto a Despacho sin mezclar sus tiempos ni historiales.
"""

import hashlib
import json
import math
import os
import re
import unicodedata
import uuid
import warnings
from datetime import date, datetime, timedelta
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from backend.services.daily_operations import (
    local_now,
    advanced_lots_enabled,
    global_stock_summary,
)

from backend.services.traceability import (
    generate_lots_for_shipment,
    lots_for_shipment,
    sync_shipment_lot_references,
)


RECEPTION_ROLES = {"ADMINISTRADOR", "ASISTENTE_RECEPCION", "AUXILIAR_RECEPCION"}
ACCOUNTING_SHEET_NAME = "FACTURAS IMPORTACIONES Repuesto"
LEGACY_ACCOUNTING_SHEET_NAME = "FACTURAS DHL"
RECEPTION_STATES = (
    "PROGRAMADO",
    "ARRIBADO",
    "REVISION SISTEMA",
    "EM",
    "UBICACION",
    "VALIDACION",
    "SOLICITUD TRANSFERENCIA",
    "CERRADO",
)
RECEPTION_STATE_INDEX = {state: index for index, state in enumerate(RECEPTION_STATES)}

# El camión tiene un flujo propio.  No reutilizamos ``app_status`` de la BL
# porque recibir/ubicar un camión no es evidencia de que una BL haya sido
# contada.  La BL conserva su flujo y sólo se habilita para conteo cuando su
# guía llega a LISTA_PARA_CONTEO.
TRUCK_GUIDE_STATES = (
    "PENDIENTE",
    "EN_CURSO",
    "ZONA_RECEPCION",
    "LISTA_PARA_CONTEO",
    "CANCELADA",
)
TRUCK_GUIDE_STATE_INDEX = {state: index for index, state in enumerate(TRUCK_GUIDE_STATES)}


def reception_now():
    return local_now()


def init_reception_schema(connection):
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS reception_shipments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bl_awb TEXT NOT NULL UNIQUE,
            transport_type TEXT NOT NULL DEFAULT 'AEREO',
            supplier TEXT,
            brand_summary TEXT,
            country_origin TEXT,
            source_sheets TEXT,
            ip_reference TEXT,
            primary_oc TEXT,
            primary_ov TEXT,
            expected_packages REAL NOT NULL DEFAULT 0,
            received_packages REAL NOT NULL DEFAULT 0,
            app_status TEXT NOT NULL DEFAULT 'PROGRAMADO',
            condition_status TEXT NOT NULL DEFAULT 'POR ARRIBAR',
            current_assistant TEXT,
            current_auxiliary TEXT,
            fr_number TEXT,
            em_number TEXT,
            accounting_status TEXT NOT NULL DEFAULT 'PENDIENTE CONTABILIDAD',
            accounting_conflict_count INTEGER NOT NULL DEFAULT 0,
            accounting_conflict_detail TEXT,
            accounting_email_date TEXT,
            source_reception_date TEXT,
            em_date TEXT,
            costing_date TEXT,
            scheduled_date TEXT,
            truck_guide TEXT,
            first_arrival_at TEXT,
            completed_arrival_at TEXT,
            physical_initialized INTEGER NOT NULL DEFAULT 0,
            system_quantities_initialized INTEGER NOT NULL DEFAULT 0,
            bultos_closed INTEGER NOT NULL DEFAULT 0,
            location_text TEXT,
            validation_sample_json TEXT,
            transfer_assistant_checked INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reception_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id INTEGER NOT NULL REFERENCES reception_shipments(id) ON DELETE CASCADE,
            source_row INTEGER,
            source_sheet TEXT,
            source_key TEXT,
            np_code TEXT,
            description TEXT,
            oc_number TEXT,
            ov_number TEXT,
            expected_qty REAL NOT NULL DEFAULT 0,
            requested_qty REAL NOT NULL DEFAULT 0,
            invoiced_qty REAL NOT NULL DEFAULT 0,
            pending_qty REAL NOT NULL DEFAULT 0,
            received_qty REAL NOT NULL DEFAULT 0,
            purchase_type TEXT,
            brand TEXT,
            applicant TEXT,
            source_status TEXT,
            source_invoice TEXT,
            ip_reference TEXT,
            default_location TEXT,
            is_replacement INTEGER NOT NULL DEFAULT 0,
            replacement_np TEXT,
            blocked_reason TEXT
        );

        CREATE TABLE IF NOT EXISTS reception_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id INTEGER NOT NULL REFERENCES reception_shipments(id) ON DELETE CASCADE,
            sequence_no INTEGER NOT NULL,
            received_packages REAL NOT NULL,
            notes TEXT,
            location_text TEXT,
            username TEXT NOT NULL,
            received_at TEXT NOT NULL,
            UNIQUE(shipment_id, sequence_no)
        );

        -- La llegada del camión es seguimiento físico de la guía, no un
        -- conteo ni una recepción definitiva de cada BL/AWB.
        CREATE TABLE IF NOT EXISTS reception_truck_guides (
            guide_code TEXT PRIMARY KEY,
            planned_packages REAL NOT NULL DEFAULT 0,
            guide_status TEXT NOT NULL DEFAULT 'PENDIENTE',
            source_type TEXT NOT NULL DEFAULT 'PROPUESTA_FECHA',
            is_confirmed INTEGER NOT NULL DEFAULT 0,
            carrier_reference TEXT,
            confirmed_by TEXT,
            confirmed_at TEXT,
            count_enabled_at TEXT,
            count_enabled_by TEXT,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        -- Manifiesto DHL piloto persistido por BL. No es el conteo real de
        -- recepción y nunca modifica expected_packages de la BL.
        CREATE TABLE IF NOT EXISTS reception_truck_manifest (
            truck_guide TEXT NOT NULL REFERENCES reception_truck_guides(guide_code) ON DELETE CASCADE,
            shipment_id INTEGER NOT NULL REFERENCES reception_shipments(id) ON DELETE CASCADE,
            expected_packages REAL NOT NULL,
            source TEXT NOT NULL DEFAULT 'DHL_PILOTO',
            created_at TEXT NOT NULL,
            PRIMARY KEY (truck_guide, shipment_id),
            UNIQUE (shipment_id)
        );

        -- Manifiesto canónico: una BL puede tener asignaciones en varios
        -- camiones. La cantidad esperada de BL nunca se copia por camión.
        CREATE TABLE IF NOT EXISTS reception_truck_bl_manifest (
            truck_guide TEXT NOT NULL REFERENCES reception_truck_guides(guide_code) ON DELETE CASCADE,
            shipment_id INTEGER NOT NULL REFERENCES reception_shipments(id) ON DELETE CASCADE,
            planned_packages REAL NOT NULL CHECK (planned_packages >= 0),
            operational_active INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (truck_guide, shipment_id)
        );

        -- Una confirmación física por pareja camión/BL. arrival_key hace
        -- idempotentes los reintentos de red y received_packages admite 0.
        CREATE TABLE IF NOT EXISTS reception_truck_bl_arrivals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            truck_guide TEXT NOT NULL,
            shipment_id INTEGER NOT NULL REFERENCES reception_shipments(id) ON DELETE CASCADE,
            received_packages REAL NOT NULL CHECK (received_packages >= 0),
            arrival_key TEXT NOT NULL UNIQUE,
            excess_reason TEXT,
            notes TEXT,
            username TEXT NOT NULL,
            arrived_at TEXT NOT NULL,
            UNIQUE (truck_guide, shipment_id)
        );

        -- Lecturas individuales del flujo nuevo de escaneo. Se conservan al
        -- revertir; los códigos activos son únicos para evitar dobles ingresos.
        CREATE TABLE IF NOT EXISTS reception_truck_package_scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            truck_guide TEXT NOT NULL REFERENCES reception_truck_guides(guide_code),
            shipment_id INTEGER NOT NULL REFERENCES reception_shipments(id),
            package_code TEXT NOT NULL,
            normalized_code TEXT NOT NULL,
            scan_status TEXT NOT NULL DEFAULT 'ACTIVO',
            scanned_by TEXT NOT NULL,
            scanned_at TEXT NOT NULL,
            voided_by TEXT,
            voided_at TEXT,
            void_reason TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_reception_truck_package_active_code
            ON reception_truck_package_scans(normalized_code) WHERE scan_status='ACTIVO';
        CREATE INDEX IF NOT EXISTS idx_reception_truck_package_guide_bl
            ON reception_truck_package_scans(truck_guide, shipment_id, scan_status);

        -- La ubicación se conserva por llegada, BL, ubicación y cantidad.
        CREATE TABLE IF NOT EXISTS reception_truck_bl_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            arrival_id INTEGER NOT NULL REFERENCES reception_truck_bl_arrivals(id) ON DELETE CASCADE,
            location_text TEXT NOT NULL,
            package_count REAL NOT NULL CHECK (package_count > 0),
            username TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (arrival_id, location_text)
        );

        CREATE TABLE IF NOT EXISTS reception_truck_arrivals (
            truck_guide TEXT PRIMARY KEY,
            expected_packages REAL NOT NULL DEFAULT 0,
            received_packages REAL NOT NULL DEFAULT 0,
            notes TEXT,
            username TEXT NOT NULL,
            received_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reception_truck_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            truck_guide TEXT NOT NULL REFERENCES reception_truck_arrivals(truck_guide) ON DELETE CASCADE,
            location_text TEXT NOT NULL,
            package_count REAL NOT NULL,
            UNIQUE(truck_guide, location_text)
        );

        -- Una BL puede llegar en más de una recepción. Cada llegada que se
        -- trabaja después de cerrar la anterior tiene su propia atención,
        -- responsable, estado y cantidades remanentes.
        CREATE TABLE IF NOT EXISTS reception_attentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id INTEGER NOT NULL REFERENCES reception_shipments(id) ON DELETE CASCADE,
            receipt_id INTEGER REFERENCES reception_receipts(id) ON DELETE SET NULL,
            sequence_no INTEGER NOT NULL,
            app_status TEXT NOT NULL DEFAULT 'ARRIBADO',
            condition_status TEXT NOT NULL DEFAULT 'EN PROCESO',
            current_assistant TEXT,
            current_auxiliary TEXT,
            location_text TEXT,
            system_quantities_initialized INTEGER NOT NULL DEFAULT 0,
            transfer_assistant_checked INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            UNIQUE(shipment_id, sequence_no),
            UNIQUE(receipt_id)
        );

        CREATE TABLE IF NOT EXISTS reception_attention_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attention_id INTEGER NOT NULL REFERENCES reception_attentions(id) ON DELETE CASCADE,
            reception_line_id INTEGER NOT NULL REFERENCES reception_lines(id) ON DELETE CASCADE,
            planned_qty REAL NOT NULL DEFAULT 0,
            verified_qty REAL NOT NULL DEFAULT 0,
            UNIQUE(attention_id, reception_line_id)
        );

        CREATE TABLE IF NOT EXISTS reception_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id INTEGER NOT NULL REFERENCES reception_shipments(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            field_name TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            username TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reception_accounting_refs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id INTEGER NOT NULL REFERENCES reception_shipments(id) ON DELETE CASCADE,
            source_key TEXT NOT NULL UNIQUE,
            source_sheet TEXT,
            source_row INTEGER,
            awb_reference TEXT,
            ip_reference TEXT,
            fr_number TEXT,
            em_number TEXT,
            email_date TEXT,
            reception_date TEXT,
            em_date TEXT,
            costing_date TEXT,
            import_status TEXT,
            source_file TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        -- Una FR puede tener varias EM cuando una IP llega en varias atenciones.
        -- em_number en reception_accounting_refs se conserva como resumen.
        CREATE TABLE IF NOT EXISTS reception_accounting_ems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            accounting_ref_id INTEGER NOT NULL REFERENCES reception_accounting_refs(id) ON DELETE CASCADE,
            ip_reference_key TEXT,
            attention_id INTEGER REFERENCES reception_attentions(id) ON DELETE SET NULL,
            em_number TEXT NOT NULL,
            em_date TEXT,
            username TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(accounting_ref_id, em_number)
        );

        CREATE TABLE IF NOT EXISTS reception_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id INTEGER NOT NULL REFERENCES reception_shipments(id) ON DELETE CASCADE,
            notification_type TEXT NOT NULL,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDIENTE ENVIO',
            created_at TEXT NOT NULL,
            sent_at TEXT,
            error TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_reception_shipments_status
            ON reception_shipments(app_status);
        CREATE INDEX IF NOT EXISTS idx_reception_lines_np
            ON reception_lines(np_code);
        CREATE INDEX IF NOT EXISTS idx_reception_accounting_shipment
            ON reception_accounting_refs(shipment_id);
        CREATE INDEX IF NOT EXISTS idx_reception_accounting_ems_ref
            ON reception_accounting_ems(accounting_ref_id);
        CREATE INDEX IF NOT EXISTS idx_reception_notifications_shipment
            ON reception_notifications(shipment_id);
        CREATE INDEX IF NOT EXISTS idx_reception_truck_locations_guide
            ON reception_truck_locations(truck_guide);
        """
    )
    _ensure_column(connection, "reception_shipments", "brand_summary", "TEXT")
    _ensure_column(connection, "reception_shipments", "country_origin", "TEXT")
    _ensure_column(connection, "reception_shipments", "source_sheets", "TEXT")
    _ensure_column(connection, "reception_shipments", "physical_initialized", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "reception_shipments", "system_quantities_initialized", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "reception_shipments", "bultos_closed", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "reception_shipments", "location_text", "TEXT")
    _ensure_column(connection, "reception_shipments", "validation_sample_json", "TEXT")
    _ensure_column(connection, "reception_shipments", "transfer_assistant_checked", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "reception_shipments", "accounting_email_date", "TEXT")
    _ensure_column(connection, "reception_shipments", "source_reception_date", "TEXT")
    _ensure_column(connection, "reception_shipments", "em_date", "TEXT")
    _ensure_column(connection, "reception_shipments", "costing_date", "TEXT")
    _ensure_column(connection, "reception_shipments", "truck_guide", "TEXT")
    _ensure_column(connection, "reception_truck_guides", "guide_status", "TEXT NOT NULL DEFAULT 'PENDIENTE'")
    _ensure_column(connection, "reception_truck_guides", "planned_packages", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "reception_truck_guides", "count_enabled_at", "TEXT")
    _ensure_column(connection, "reception_truck_guides", "count_enabled_by", "TEXT")
    _ensure_column(connection, "reception_truck_guides", "source_type", "TEXT NOT NULL DEFAULT 'PROPUESTA_FECHA'")
    _ensure_column(connection, "reception_truck_guides", "is_confirmed", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "reception_truck_guides", "carrier_reference", "TEXT")
    _ensure_column(connection, "reception_truck_guides", "confirmed_by", "TEXT")
    _ensure_column(connection, "reception_truck_guides", "confirmed_at", "TEXT")
    _ensure_column(connection, "reception_truck_guides", "scanner_enabled", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "reception_truck_guides", "archived_at", "TEXT")
    _ensure_column(connection, "reception_truck_guides", "archived_by", "TEXT")
    _ensure_column(connection, "reception_truck_guides", "archive_reason", "TEXT")
    _ensure_column(
        connection, "reception_truck_bl_manifest", "operational_active",
        "INTEGER NOT NULL DEFAULT 1",
    )
    # Las guías creadas manualmente o que ya tienen una llegada son evidencia
    # operativa. Las generadas solo por fecha permanecen como propuestas hasta
    # que un administrador confirme el grupo o registre la referencia real.
    connection.execute(
        """UPDATE reception_truck_guides
                  SET source_type = CASE
                    WHEN COALESCE(source_type,'') = 'ESTIMACION_PRUEBA'
                         THEN 'ESTIMACION_PRUEBA'
                    WHEN COALESCE(source_type,'') = 'ESCANEO'
                         OR COALESCE(scanner_enabled,0)=1
                         OR upper(guide_code) LIKE 'SCAN-%'
                         THEN 'ESCANEO'
                    WHEN EXISTS (SELECT 1 FROM reception_truck_bl_arrivals a
                                  WHERE lower(a.truck_guide)=lower(reception_truck_guides.guide_code))
                         THEN 'HISTORICO_CONFIRMADO'
                    WHEN lower(COALESCE(created_by,'')) NOT IN ('sistema.prueba','sistema.migracion')
                         THEN 'ADMINISTRADOR'
                    ELSE COALESCE(NULLIF(source_type,''),'PROPUESTA_FECHA') END,
                  is_confirmed = CASE
                    WHEN COALESCE(source_type,'') = 'ESTIMACION_PRUEBA' THEN 0
                    WHEN COALESCE(source_type,'') = 'ESCANEO'
                         OR COALESCE(scanner_enabled,0)=1
                         OR upper(guide_code) LIKE 'SCAN-%'
                         THEN COALESCE(is_confirmed,0)
                    WHEN EXISTS (SELECT 1 FROM reception_truck_bl_arrivals a
                                  WHERE lower(a.truck_guide)=lower(reception_truck_guides.guide_code)) THEN 1
                    WHEN lower(COALESCE(created_by,'')) NOT IN ('sistema.prueba','sistema.migracion') THEN 1
                    ELSE COALESCE(is_confirmed,0) END"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_reception_shipments_truck_guide ON reception_shipments(truck_guide)"
    )
    seed_pilot_truck_manifest(connection)
    # La generación piloto se ejecuta únicamente como migración explícita.
    # El arranque debe ser de sólo lectura respecto a la relación guía ↔ BL:
    # volver a agrupar al abrir la app puede alterar la operación en curso.
    connection.execute(
        """INSERT OR IGNORE INTO reception_accounting_ems
           (accounting_ref_id, em_number, em_date, username, created_at)
           SELECT id, trim(em_number), em_date, 'sistema.migracion',
                  COALESCE(updated_at, created_at)
             FROM reception_accounting_refs
            WHERE trim(COALESCE(em_number, '')) <> ''"""
    )
    _ensure_column(
        connection,
        "reception_shipments",
        "accounting_status",
        "TEXT NOT NULL DEFAULT 'PENDIENTE CONTABILIDAD'",
    )
    _ensure_column(
        connection,
        "reception_shipments",
        "accounting_conflict_count",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _ensure_column(connection, "reception_shipments", "accounting_conflict_detail", "TEXT")
    _ensure_column(connection, "reception_accounting_ems", "ip_reference_key", "TEXT")
    for reference in connection.execute(
        "SELECT id, ip_reference FROM reception_accounting_refs"
    ).fetchall():
        ip_keys = _ip_tokens(reference["ip_reference"])
        if len(ip_keys) != 1:
            continue
        connection.execute(
            """UPDATE reception_accounting_ems
                  SET ip_reference_key = ?
                WHERE accounting_ref_id = ?
                  AND ip_reference_key IS NULL""",
            (ip_keys[0], reference["id"]),
        )
    _ensure_column(connection, "reception_receipts", "location_text", "TEXT")
    _ensure_column(connection, "reception_receipts", "truck_guide", "TEXT")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_reception_receipts_truck_bl "
        "ON reception_receipts(shipment_id, truck_guide) "
        "WHERE COALESCE(TRIM(truck_guide), '') <> ''"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_reception_truck_bl_manifest_shipment "
        "ON reception_truck_bl_manifest(shipment_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_reception_truck_bl_arrivals_shipment "
        "ON reception_truck_bl_arrivals(shipment_id)"
    )
    # Migra asociaciones previas una sola vez; la tabla legacy queda intacta
    # para que el piloto conserve compatibilidad e historial.
    connection.execute(
        """INSERT OR IGNORE INTO reception_truck_bl_manifest
           (truck_guide, shipment_id, planned_packages, created_by, created_at, updated_at)
           SELECT m.truck_guide, m.shipment_id, MAX(0, COALESCE(s.expected_packages, 0)),
                  'sistema.migracion', m.created_at, m.created_at
             FROM reception_truck_manifest m
             JOIN reception_shipments s ON s.id = m.shipment_id
             JOIN reception_truck_guides g ON lower(g.guide_code) = lower(m.truck_guide)"""
    )
    # Las asociaciones automáticas antiguas se conservan como historial, pero
    # no participan en la operación si no corresponden a repuestos aéreos.
    # Así no borramos el vínculo heredado ni confirmamos por accidente una BL
    # marítima/servicio mezclada dentro de una propuesta por fecha.
    connection.execute(
        """UPDATE reception_truck_bl_manifest AS m
              SET operational_active = 0
            WHERE COALESCE(m.operational_active,1) = 1
              AND EXISTS (
                    SELECT 1
                      FROM reception_truck_guides g
                      JOIN reception_shipments s ON s.id=m.shipment_id
                     WHERE lower(g.guide_code)=lower(m.truck_guide)
                       AND COALESCE(g.is_confirmed,0)=0
                       AND COALESCE(g.source_type,'PROPUESTA_FECHA')='PROPUESTA_FECHA'
                       AND (
                           UPPER(TRIM(COALESCE(s.transport_type,''))) NOT IN ('AEREO','COURIER')
                           OR NOT EXISTS (
                               SELECT 1 FROM reception_lines l
                                WHERE l.shipment_id=s.id
                                  AND TRIM(COALESCE(l.np_code,''))<>''
                           )
                       )
              )"""
    )
    _ensure_column(connection, "reception_lines", "source_sheet", "TEXT")
    _ensure_column(connection, "reception_lines", "source_key", "TEXT")
    _ensure_column(connection, "reception_lines", "requested_qty", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "reception_lines", "invoiced_qty", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "reception_lines", "pending_qty", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "reception_lines", "purchase_type", "TEXT")
    _ensure_column(connection, "reception_lines", "brand", "TEXT")
    _ensure_column(connection, "reception_lines", "applicant", "TEXT")
    _ensure_column(connection, "reception_lines", "source_status", "TEXT")
    _ensure_column(connection, "reception_lines", "source_invoice", "TEXT")
    _ensure_column(connection, "reception_lines", "ip_reference", "TEXT")
    # Ubicación sugerida proveniente del Excel de Importaciones. Es solo una
    # referencia para el conteo; no sustituye la ubicación manual por bulto.
    _ensure_column(connection, "reception_lines", "default_location", "TEXT")
    # La ubicación física temporal del camión vive en reception_receipts /
    # reception_truck_arrival_locations. Esta es la ubicación final por NP.
    _ensure_column(connection, "reception_lines", "final_location", "TEXT")
    _ensure_column(connection, "reception_lines", "final_location_confirmed", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "reception_lines", "validation_sap_checked", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "reception_lines", "validation_location_checked", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "reception_lines", "validation_comment_checked", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "reception_lines", "validation_comment", "TEXT")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_reception_lines_source_key ON reception_lines(source_key)"
    )
    legacy_physical_review = connection.execute(
        """SELECT id, app_status, current_assistant, current_auxiliary
           FROM reception_shipments
           WHERE app_status = 'REVISION FISICA'"""
    ).fetchall()
    for shipment in legacy_physical_review:
        has_assistant = bool(str(shipment["current_assistant"] or "").strip())
        has_auxiliary = bool(str(shipment["current_auxiliary"] or "").strip())
        target_status = "REVISION SISTEMA" if has_assistant and has_auxiliary else "ARRIBADO"
        target_condition = "EN PROCESO" if target_status == "REVISION SISTEMA" else "ARRIBO REGISTRADO"
        connection.execute(
            "UPDATE reception_shipments SET app_status = ?, condition_status = ?, updated_at = ? WHERE id = ?",
            (target_status, target_condition, reception_now(), shipment["id"]),
        )
        _write_history(
            connection,
            shipment["id"],
            "MIGRACION",
            "app_status",
            "REVISION FISICA",
            target_status,
            "sistema.migracion",
            "Se retiró REVISION FISICA como estado; el conteo físico continúa fuera del app y el sistema valida en REVISION SISTEMA",
        )
    legacy_system_review = connection.execute(
        """SELECT id, physical_initialized FROM reception_shipments
           WHERE system_quantities_initialized = 0
             AND app_status IN ('REVISION SISTEMA', 'EM', 'UBICACION', 'VALIDACION',
                                'SOLICITUD TRANSFERENCIA', 'CERRADO')"""
    ).fetchall()
    for shipment in legacy_system_review:
        migration_value = "PRESERVADAS" if shipment["physical_initialized"] else "100%"
        if not shipment["physical_initialized"]:
            connection.execute(
                "UPDATE reception_lines SET received_qty = expected_qty WHERE shipment_id = ?",
                (shipment["id"],),
            )
        connection.execute(
            "UPDATE reception_shipments SET system_quantities_initialized = 1 WHERE id = ?",
            (shipment["id"],),
        )
        _write_history(
            connection,
            shipment["id"],
            "MIGRACION",
            "cantidades_revision_sistema",
            0,
            migration_value,
            "sistema.migracion",
            "Habilitación de cantidades para expedientes que ya habían iniciado revisión de sistema",
        )
    for shipment in connection.execute("SELECT id FROM reception_shipments").fetchall():
        _refresh_accounting_summary(
            connection,
            shipment["id"],
            "sistema.migracion",
            "recalculo de estados contables al iniciar",
        )
    _migrate_reception_attentions(connection)


def _ensure_column(connection, table, column, definition):
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _attention_rows(connection, shipment_id):
    return connection.execute(
        "SELECT * FROM reception_attentions WHERE shipment_id = ? ORDER BY sequence_no",
        (shipment_id,),
    ).fetchall()


def _active_reception_attention(connection, shipment_id, attention_id=None):
    """Return a requested arrival attention, or the oldest open one by default."""
    rows = _attention_rows(connection, shipment_id)
    if not rows:
        return None
    if attention_id:
        selected = next((row for row in rows if int(row["id"]) == int(attention_id)), None)
        if selected:
            return selected
    pending = [row for row in rows if row["app_status"] != "CERRADO"]
    return (pending[0] if pending else rows[-1])


def _attention_verified_total(connection, reception_line_id):
    row = connection.execute(
        """SELECT COALESCE(SUM(verified_qty), 0) AS total
             FROM reception_attention_lines
            WHERE reception_line_id = ?""",
        (reception_line_id,),
    ).fetchone()
    return float(row["total"] or 0) if row else 0.0


def _create_reception_attention(connection, shipment, receipt_id, username,
                                initial_status="ARRIBADO"):
    """Create an attention for a later arrival using the unverified balance.

    Every physical arrival creates its own attention, even while a previous
    attention remains open. Each can be resumed and completed independently.
    """
    shipment_id = int(shipment["id"])
    sequence = connection.execute(
        "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM reception_attentions WHERE shipment_id = ?",
        (shipment_id,),
    ).fetchone()[0]
    timestamp = reception_now()
    cursor = connection.execute(
        """INSERT INTO reception_attentions
           (shipment_id, receipt_id, sequence_no, app_status, condition_status,
            current_assistant, current_auxiliary, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'EN PROCESO', ?, ?, ?, ?)""",
        (
            shipment_id,
            receipt_id,
            sequence,
            initial_status,
            shipment["current_assistant"],
            shipment["current_auxiliary"],
            timestamp,
            timestamp,
        ),
    )
    attention_id = cursor.lastrowid
    for line in connection.execute(
        "SELECT * FROM reception_lines WHERE shipment_id = ? ORDER BY id", (shipment_id,)
    ).fetchall():
        previous = _attention_verified_total(connection, line["id"])
        planned = max(0.0, float(line["expected_qty"] or 0) - previous)
        connection.execute(
            """INSERT INTO reception_attention_lines
               (attention_id, reception_line_id, planned_qty, verified_qty)
               VALUES (?, ?, ?, 0)""",
            (attention_id, line["id"], planned),
        )
    _write_history(
        connection,
        shipment_id,
        "ATENCION",
        "attention",
        "",
        f"Atención {sequence} · recepción {receipt_id}",
        username,
        "Nueva llegada física separada de la atención anterior",
    )
    return connection.execute(
        "SELECT * FROM reception_attentions WHERE id = ?", (attention_id,)
    ).fetchone()


def _migrate_reception_attentions(connection):
    """Add attention tracking to existing databases without deleting data."""
    shipments = connection.execute(
        "SELECT * FROM reception_shipments WHERE EXISTS "
        "(SELECT 1 FROM reception_receipts r WHERE r.shipment_id = reception_shipments.id)"
    ).fetchall()
    for shipment in shipments:
        if connection.execute(
            "SELECT 1 FROM reception_attentions WHERE shipment_id = ? LIMIT 1",
            (shipment["id"],),
        ).fetchone():
            continue
        receipts = connection.execute(
            "SELECT * FROM reception_receipts WHERE shipment_id = ? ORDER BY sequence_no",
            (shipment["id"],),
        ).fetchall()
        for index, receipt in enumerate(receipts):
            status = shipment["app_status"] if index == len(receipts) - 1 else "CERRADO"
            timestamp = receipt["received_at"] or reception_now()
            cursor = connection.execute(
                """INSERT INTO reception_attentions
                   (shipment_id, receipt_id, sequence_no, app_status, condition_status,
                    current_assistant, current_auxiliary, created_at, updated_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    shipment["id"], receipt["id"], receipt["sequence_no"], status,
                    "COMPLETADO" if status == "CERRADO" else "EN PROCESO",
                    shipment["current_assistant"], shipment["current_auxiliary"],
                    timestamp, timestamp, timestamp if status == "CERRADO" else None,
                ),
            )
            attention_id = cursor.lastrowid
            for line in connection.execute(
                "SELECT * FROM reception_lines WHERE shipment_id = ? ORDER BY id",
                (shipment["id"],),
            ).fetchall():
                planned = float(line["expected_qty"] or 0) if index == 0 else 0.0
                verified = float(line["received_qty"] or 0) if status == "CERRADO" and index == len(receipts) - 1 else 0.0
                connection.execute(
                    """INSERT INTO reception_attention_lines
                       (attention_id, reception_line_id, planned_qty, verified_qty)
                       VALUES (?, ?, ?, ?)""",
                    (attention_id, line["id"], planned, verified),
                )

    # Recover later arrivals saved by older builds as receipts only. Do not
    # skip a shipment just because its first arrival already has an attention.
    orphaned_receipts = connection.execute(
        """SELECT s.*, r.id AS orphan_receipt_id FROM reception_receipts r
             JOIN reception_shipments s ON s.id = r.shipment_id
            WHERE COALESCE(r.received_packages, 0) > 0
              AND NOT EXISTS (SELECT 1 FROM reception_attentions a WHERE a.receipt_id = r.id)
            ORDER BY r.shipment_id, r.sequence_no"""
    ).fetchall()
    for receipt in orphaned_receipts:
        _create_reception_attention(
            connection, receipt, int(receipt["orphan_receipt_id"]), "sistema.migracion", "ARRIBADO"
        )


def _ensure_reception_attention(connection, shipment, username):
    """Create a compatibility attention for older rows that have no receipt."""
    active = _active_reception_attention(connection, shipment["id"])
    if active:
        return active
    if shipment["app_status"] == "PROGRAMADO" and not float(shipment["received_packages"] or 0):
        return None
    return _create_reception_attention(connection, shipment, None, username, shipment["app_status"])


def _sync_reception_line_totals(connection, shipment_id):
    """Mirror the sum of all arrival-attention quantities for legacy reports."""
    for line in connection.execute(
        "SELECT id FROM reception_lines WHERE shipment_id = ?", (shipment_id,)
    ).fetchall():
        total = _attention_verified_total(connection, line["id"])
        connection.execute(
            "UPDATE reception_lines SET received_qty = ? WHERE id = ?",
            (total, line["id"]),
        )


def require_reception_access(role):
    if role not in RECEPTION_ROLES:
        raise PermissionError("Tu usuario no tiene acceso al módulo Recepción")


def _is_assigned_to(shipment, username):
    current_user = str(username or "").strip().casefold()
    if not current_user:
        return False
    return current_user in {
        str(shipment["current_assistant"] or "").strip().casefold(),
        str(shipment["current_auxiliary"] or "").strip().casefold(),
    }


def _default_reception_user(connection, role, setting_name):
    """Resolve the default responsible without hard-coding a person.

    TI can pin the operational users with environment variables. If they are
    not configured, the first active user of the exact reception role is used.
    This keeps imported BLs out of an unassigned queue while preserving the
    administrator's ability to change the assignment later.
    """
    users_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'"
    ).fetchone()
    if not users_table:
        return ""
    configured = str(os.getenv(setting_name, "") or "").strip().lower()
    if configured:
        selected = connection.execute(
            """SELECT username FROM users
               WHERE lower(username) = ? AND active = 1 AND role = ?
               LIMIT 1""",
            (configured, role),
        ).fetchone()
        if selected:
            return selected["username"]
    selected = connection.execute(
        """SELECT username FROM users
           WHERE active = 1 AND role = ?
           ORDER BY datetime(created_at) ASC, username ASC
           LIMIT 1""",
        (role,),
    ).fetchone()
    return selected["username"] if selected else ""


def _ensure_default_reception_assignees(connection, shipment_id, username,
                                        reason="Asignación automática de recepción"):
    """Assign the default assistant and auxiliary only when a slot is empty."""
    shipment = connection.execute(
        "SELECT current_assistant, current_auxiliary FROM reception_shipments WHERE id = ?",
        (shipment_id,),
    ).fetchone()
    if not shipment:
        return
    changes = {}
    if not str(shipment["current_assistant"] or "").strip():
        changes["current_assistant"] = _default_reception_user(
            connection, "ASISTENTE_RECEPCION", "TRITON_DEFAULT_RECEPTION_ASSISTANT"
        )
    if not str(shipment["current_auxiliary"] or "").strip():
        changes["current_auxiliary"] = _default_reception_user(
            connection, "AUXILIAR_RECEPCION", "TRITON_DEFAULT_RECEPTION_AUXILIARY"
        )
    for field, value in changes.items():
        if not value:
            continue
        old_value = str(shipment[field] or "")
        connection.execute(
            f"UPDATE reception_shipments SET {field} = ?, updated_at = ? WHERE id = ?",
            (value, reception_now(), shipment_id),
        )
        _write_history(connection, shipment_id, "ASIGNACION AUTOMATICA", field,
                       old_value, value, username, reason)


def _get_reception_shipment(connection, shipment_id, username, role):
    require_reception_access(role)
    shipment = connection.execute(
        "SELECT * FROM reception_shipments WHERE id = ?", (shipment_id,)
    ).fetchone()
    if not shipment:
        raise ValueError("BL/AWB no encontrada")
    if role != "ADMINISTRADOR" and not _is_assigned_to(shipment, username):
        raise PermissionError("Esta BL/AWB no está asignada a tu usuario")
    return shipment


def _as_dict(row):
    return dict(row) if row else None


def _write_history(connection, shipment_id, event_type, field_name, old_value,
                   new_value, username, reason=""):
    connection.execute(
        """INSERT INTO reception_history
           (shipment_id, event_type, field_name, old_value, new_value,
            username, reason, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            shipment_id,
            event_type,
            field_name,
            "" if old_value is None else str(old_value),
            "" if new_value is None else str(new_value),
            username,
            reason,
            reception_now(),
        ),
    )


def _notification_recipients(setting_name, default):
    configured = os.getenv(setting_name, default)
    return [item.strip() for item in configured.split(",") if item.strip()]


def _enqueue_notification(connection, shipment_id, notification_type, subject, body,
                          setting_name, default_recipient):
    recipients = _notification_recipients(setting_name, default_recipient)
    for recipient in recipients:
        duplicate = connection.execute(
            """SELECT 1 FROM reception_notifications
               WHERE shipment_id = ? AND notification_type = ?
                 AND recipient = ? AND subject = ? AND body = ?
               LIMIT 1""",
            (shipment_id, notification_type, recipient, subject, body),
        ).fetchone()
        if duplicate:
            continue
        connection.execute(
            """INSERT INTO reception_notifications
               (shipment_id, notification_type, recipient, subject, body, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'PENDIENTE ENVIO', ?)""",
            (shipment_id, notification_type, recipient, subject, body, reception_now()),
        )


def _ip_tokens(value):
    """Devuelve IP individuales sin separar guiones que forman parte del código."""
    raw = str(value or "").replace("\r", "\n")
    tokens = re.split(r"[,;\n]|\s+-\s+", raw)
    result = []
    for token in tokens:
        normalized = _normalized_identifier(token)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _ip_display_tokens(value):
    """Devuelve pares (clave normalizada, texto original) para mostrar la IP."""
    raw = str(value or "").replace("\r", "\n")
    tokens = re.split(r"[,;\n]|\s+-\s+", raw)
    result = []
    seen = set()
    for token in tokens:
        display = str(token or "").strip()
        key = _normalized_identifier(display)
        if key and key not in seen:
            result.append((key, display))
            seen.add(key)
    return result


def _accounting_rows_by_ip(rows):
    by_ip = {}
    for row in rows:
        for ip_key in _ip_tokens(row["ip_reference"]):
            by_ip.setdefault(ip_key, []).append(row)
    return by_ip


def _accounting_ref_has_received_sku(connection, shipment_id, reference, ip_key=None, attention_id=None):
    """Indica si esta IP tiene al menos un SKU ingresado en la recepción.

    Una BL puede traer varias IP y una llegada puede ser parcial. La FR/EM de
    una IP solo debe habilitarse cuando existe una cantidad verificada mayor a
    cero para alguno de sus SKU; las demás referencias quedan pendientes para
    una atención futura.
    """
    reference_ips = {ip_key} if ip_key else set(_ip_tokens(reference["ip_reference"]))
    if not reference_ips:
        return False
    active = (
        _active_reception_attention(connection, shipment_id, attention_id)
        if attention_id else _active_reception_attention(connection, shipment_id)
    )
    if active:
        rows = connection.execute(
            """SELECT l.ip_reference, al.verified_qty
                 FROM reception_attention_lines al
                 JOIN reception_lines l ON l.id = al.reception_line_id
                WHERE al.attention_id = ? AND l.shipment_id = ?""",
            (active["id"], shipment_id),
        ).fetchall()
        if any(
            reference_ips.intersection(_ip_tokens(line["ip_reference"]))
            and float(line["verified_qty"] or 0) > 0
            for line in rows
        ):
            return True
        if attention_id:
            return False
        # La atención activa puede ser una segunda llegada todavía vacía. No
        # debe ocultar los SKU que sí fueron recibidos en atenciones anteriores.
        # El acumulado de reception_lines conserva ese trabajo ya realizado.
    for line in connection.execute(
        "SELECT ip_reference, received_qty FROM reception_lines WHERE shipment_id = ?",
        (shipment_id,),
    ).fetchall():
        if reference_ips.intersection(_ip_tokens(line["ip_reference"])) and float(line["received_qty"] or 0) > 0:
            return True
    return False


def _accounting_em_values(connection, reference_id, ip_key=None):
    """Devuelve EM de una FR, filtradas por IP cuando la referencia tiene varias."""
    reference = connection.execute(
        "SELECT ip_reference FROM reception_accounting_refs WHERE id = ?",
        (reference_id,),
    ).fetchone()
    ip_count = len(_ip_tokens(reference["ip_reference"])) if reference else 0
    if ip_key and ip_count > 1:
        rows = connection.execute(
            """SELECT em_number FROM reception_accounting_ems
               WHERE accounting_ref_id = ? AND ip_reference_key = ? ORDER BY id""",
            (reference_id, ip_key),
        ).fetchall()
        # Compatibilidad con el trabajo realizado antes del WMS: una EM
        # importada en la fila FR puede cubrir la referencia histórica aunque
        # la hoja no haya separado todavía la EM por cada IP.
        if not rows:
            rows = connection.execute(
                """SELECT em_number FROM reception_accounting_ems
                   WHERE accounting_ref_id = ?
                     AND ip_reference_key IS NULL ORDER BY id""",
                (reference_id,),
            ).fetchall()
    elif ip_key:
        rows = connection.execute(
            """SELECT em_number FROM reception_accounting_ems
               WHERE accounting_ref_id = ?
                 AND (ip_reference_key = ? OR ip_reference_key IS NULL)
               ORDER BY id""",
            (reference_id, ip_key),
        ).fetchall()
    else:
        rows = connection.execute(
            """SELECT em_number FROM reception_accounting_ems
               WHERE accounting_ref_id = ? ORDER BY id""",
            (reference_id,),
        ).fetchall()
    return [str(row["em_number"] or "").strip() for row in rows if str(row["em_number"] or "").strip()]


def _accounting_em_entries(connection, reference_id, ip_key=None):
    """Devuelve los registros de EM editables con su atención de origen."""
    reference = connection.execute(
        "SELECT ip_reference FROM reception_accounting_refs WHERE id = ?",
        (reference_id,),
    ).fetchone()
    ip_count = len(_ip_tokens(reference["ip_reference"])) if reference else 0
    if ip_key and ip_count > 1:
        rows = connection.execute(
            """SELECT id, attention_id, ip_reference_key, em_number
                 FROM reception_accounting_ems
                WHERE accounting_ref_id = ? AND ip_reference_key = ? ORDER BY id""",
            (reference_id, ip_key),
        ).fetchall()
        if not rows:
            rows = connection.execute(
                """SELECT id, attention_id, ip_reference_key, em_number
                     FROM reception_accounting_ems
                    WHERE accounting_ref_id = ? AND ip_reference_key IS NULL ORDER BY id""",
                (reference_id,),
            ).fetchall()
    elif ip_key:
        rows = connection.execute(
            """SELECT id, attention_id, ip_reference_key, em_number
                 FROM reception_accounting_ems
                WHERE accounting_ref_id = ?
                  AND (ip_reference_key = ? OR ip_reference_key IS NULL)
                ORDER BY id""",
            (reference_id, ip_key),
        ).fetchall()
    else:
        rows = connection.execute(
            """SELECT id, attention_id, ip_reference_key, em_number
                 FROM reception_accounting_ems WHERE accounting_ref_id = ? ORDER BY id""",
            (reference_id,),
        ).fetchall()
    return [_as_dict(row) for row in rows]


def _accounting_em_tokens(value):
    return [token.strip() for token in re.split(r"[,;\n]+", str(value or "")) if token.strip()]


def _accounting_required_attention_count(connection, shipment_id, reference, ip_key=None):
    """Cuenta las atenciones de esa IP que realmente ingresaron algún SKU."""
    ips = {ip_key} if ip_key else set(_ip_tokens(reference["ip_reference"]))
    if not ips:
        return 0
    rows = connection.execute(
        """SELECT DISTINCT al.attention_id
             FROM reception_attention_lines al
             JOIN reception_lines l ON l.id = al.reception_line_id
            WHERE l.shipment_id = ? AND al.verified_qty > 0""",
        (shipment_id,),
    ).fetchall()
    count = 0
    for row in rows:
        matched = connection.execute(
            """SELECT 1 FROM reception_attention_lines al
                 JOIN reception_lines l ON l.id = al.reception_line_id
                WHERE al.attention_id = ? AND al.verified_qty > 0
                  AND l.shipment_id = ? AND EXISTS (
                      SELECT 1 FROM reception_lines same_line
                       WHERE same_line.id = al.reception_line_id
                         AND same_line.ip_reference IS NOT NULL
                  )""",
            (row["attention_id"], shipment_id),
        ).fetchone()
        if not matched:
            continue
        attention_ips = connection.execute(
            """SELECT DISTINCT l.ip_reference
                 FROM reception_attention_lines al
                 JOIN reception_lines l ON l.id = al.reception_line_id
                WHERE al.attention_id = ? AND al.verified_qty > 0
                  AND l.shipment_id = ?""",
            (row["attention_id"], shipment_id),
        ).fetchall()
        if any(ips.intersection(_ip_tokens(item["ip_reference"])) for item in attention_ips):
            count += 1
    if count:
        return count
    # Compatibilidad con bases antiguas que tenían cantidades recibidas pero
    # aún no tenían el desglose reception_attentions.
    return int(_accounting_ref_has_received_sku(connection, shipment_id, reference, ip_key))


def _accounting_ref_em_complete(connection, shipment_id, reference, ip_key=None):
    if not str(reference["fr_number"] or "").strip():
        return False
    required = _accounting_required_attention_count(connection, shipment_id, reference, ip_key)
    return required > 0 and len(set(_accounting_em_values(connection, reference["id"], ip_key))) >= required


def _accounting_em_summary(connection, reference):
    values = _accounting_em_values(connection, reference["id"])
    return ", ".join(values) if values else str(reference["em_number"] or "").strip()


def _eligible_accounting_rows(connection, shipment_id, rows):
    return [row for row in rows if _accounting_ref_has_received_sku(connection, shipment_id, row)]


def _shipment_expected_ips(connection, shipment_id, shipment=None):
    if shipment is None:
        shipment = connection.execute(
            "SELECT * FROM reception_shipments WHERE id = ?", (shipment_id,)
        ).fetchone()
    line_ips = set()
    for row in connection.execute(
        "SELECT ip_reference FROM reception_lines WHERE shipment_id = ?", (shipment_id,)
    ).fetchall():
        line_ips.update(_ip_tokens(row["ip_reference"]))
    return line_ips or set(_ip_tokens(shipment["ip_reference"] if shipment else ""))


def _all_expected_ips_received(connection, shipment_id, shipment=None):
    expected = _shipment_expected_ips(connection, shipment_id, shipment)
    if not expected:
        return True
    received = set()
    for line in connection.execute(
        "SELECT ip_reference FROM reception_lines WHERE shipment_id = ? AND received_qty > 0",
        (shipment_id,),
    ).fetchall():
        received.update(_ip_tokens(line["ip_reference"]))
    return expected.issubset(received)


def _accounting_status_for_shipment(connection, shipment_id, shipment=None, rows=None):
    if shipment is None:
        shipment = connection.execute(
            "SELECT * FROM reception_shipments WHERE id = ?", (shipment_id,)
        ).fetchone()
    if rows is None:
        rows = connection.execute(
            "SELECT * FROM reception_accounting_refs WHERE shipment_id = ?",
            (shipment_id,),
        ).fetchall()
    if int(shipment["accounting_conflict_count"] or 0):
        return "CONFLICTO IP"
    by_ip = _accounting_rows_by_ip(rows)
    all_expected_ips = _shipment_expected_ips(connection, shipment_id, shipment)
    expected_ips = set(all_expected_ips)
    # En una llegada parcial solo se exige FR/EM para las IP que tienen algún
    # SKU ingresado. Las IP sin unidades encontradas quedan para otra atención.
    received_ips = set()
    for line in connection.execute(
        "SELECT ip_reference FROM reception_lines WHERE shipment_id = ? AND received_qty > 0",
        (shipment_id,),
    ).fetchall():
        received_ips.update(_ip_tokens(line["ip_reference"]))
    if received_ips:
        expected_ips = expected_ips.intersection(received_ips)
    if not rows and str(shipment["fr_number"] or "").strip():
        return "EM REGISTRADA" if str(shipment["em_number"] or "").strip() else "PENDIENTE EM"
    if not expected_ips:
        if not rows:
            if not str(shipment["fr_number"] or "").strip():
                return "PENDIENTE CONTABILIDAD"
            return "EM REGISTRADA" if str(shipment["em_number"] or "").strip() else "PENDIENTE EM"
        if rows and any(not str(row["fr_number"] or "").strip() for row in rows):
            return "PENDIENTE FR"
        if rows and any(not str(row["em_number"] or "").strip() for row in rows):
            return "PENDIENTE EM"
        return "EM REGISTRADA" if str(shipment["em_number"] or "").strip() or rows else "PENDIENTE CONTABILIDAD"
    missing_fr = 0
    missing_em = 0
    any_fr = False
    for ip_key in expected_ips:
        refs = by_ip.get(ip_key, [])
        has_fr = any(str(row["fr_number"] or "").strip() for row in refs)
        any_fr = any_fr or has_fr
        if not has_fr:
            missing_fr += 1
        else:
            # Una FR puede tener una EM por cada atención parcial de su IP.
            # Se agrupan filas duplicadas por FR para no exigir EM de más.
            fr_groups = {}
            for row in refs:
                fr = str(row["fr_number"] or "").strip()
                if fr:
                    fr_groups.setdefault(fr, []).append(row)
            for fr_rows in fr_groups.values():
                required = max(
                    _accounting_required_attention_count(connection, shipment_id, row, ip_key)
                    for row in fr_rows
                )
                em_values = {
                    value
                    for row in fr_rows
                    for value in _accounting_em_values(connection, row["id"], ip_key)
                }
                # Cero atenciones calculadas nunca equivale a una EM completa.
                # Ante datos antiguos o inconsistentes, exigir una EM real evita
                # cerrar automáticamente una BL solo porque la FR existe.
                if not em_values or (required and len(em_values) < required):
                    missing_em += 1
    if missing_fr:
        return "PENDIENTE FR" if any_fr else "PENDIENTE CONTABILIDAD"
    if missing_em:
        return "PENDIENTE EM"
    return "EM REGISTRADA"


def _line_has_complete_accounting(line, accounting_by_ip, connection=None, shipment_id=None):
    line_ips = _ip_tokens(line["ip_reference"])
    if not line_ips:
        return False
    for ip_key in line_ips:
        refs = accounting_by_ip.get(ip_key, [])
        groups = {}
        for row in refs:
            fr = str(row["fr_number"] or "").strip()
            if fr:
                groups.setdefault(fr, []).append(row)
        if not groups:
            return False
        for fr_rows in groups.values():
            if connection is not None and shipment_id is not None:
                if not any(_accounting_ref_em_complete(connection, shipment_id, row, ip_key) for row in fr_rows):
                    return False
            elif not any(str(row["em_number"] or "").strip() for row in fr_rows):
                return False
    return True


def _accounting_warning(accounting_status):
    if accounting_status in {"PENDIENTE CONTABILIDAD", "PENDIENTE FR"}:
        return (
            "Falta factura de reserva para una o más referencias. "
            "Puedes registrar el arribo, asignar responsables y revisar el sistema; "
            "debes completar la FR antes de entrar a EM."
        )
    if accounting_status == "CONFLICTO IP":
        return (
            "Hay una IP relacionada con más de una FR/EM. "
            "Puedes continuar los pasos previos a EM; corrige el conflicto antes de entrar a EM."
        )
    return ""


def assign_demo_truck_guides(connection):
    """Assign pilot guides only to ungrouped BL/AWB records.

    This idempotent import-time proposal groups up to twenty DHL records from
    the same planned arrival day. Only BLs still programmed, with no recorded
    arrival, EM, or active manifest assignment are eligible. A missing package
    count stays visible as data pending; it is never replaced with a guess.
    Existing guides and operational state are kept.
    """
    rows = connection.execute(
        """SELECT id, scheduled_date FROM reception_shipments s
             WHERE COALESCE(TRIM(truck_guide), '') = ''
               AND UPPER(TRIM(COALESCE(s.app_status, ''))) = 'PROGRAMADO'
               AND COALESCE(s.received_packages, 0) <= 0
               AND TRIM(COALESCE(s.em_number, '')) = ''
               AND UPPER(TRIM(COALESCE(s.transport_type, ''))) IN ('AEREO', 'COURIER')
               AND EXISTS (
                   SELECT 1 FROM reception_lines l
                    WHERE l.shipment_id = s.id
                      AND TRIM(COALESCE(l.np_code, '')) <> ''
               )
               AND NOT EXISTS (
                   SELECT 1 FROM reception_accounting_refs r
                    WHERE r.shipment_id = s.id
                      AND TRIM(COALESCE(r.em_number, '')) <> ''
               )
               AND NOT EXISTS (
                   SELECT 1 FROM reception_accounting_ems e
                   JOIN reception_accounting_refs r ON r.id = e.accounting_ref_id
                    WHERE r.shipment_id = s.id
                      AND TRIM(COALESCE(e.em_number, '')) <> ''
               )
               AND NOT EXISTS (
                   SELECT 1 FROM reception_truck_bl_manifest m
                    WHERE m.shipment_id = s.id
                      AND COALESCE(m.operational_active, 1) = 1
               )
               AND NOT EXISTS (
                   SELECT 1 FROM reception_truck_bl_arrivals a
                    WHERE a.shipment_id = s.id
               )
               AND NOT EXISTS (
                   SELECT 1 FROM reception_history h
                    WHERE h.shipment_id = s.id
                      AND h.field_name = 'truck_auto_excluded'
                      AND h.new_value = '1'
               )
             ORDER BY COALESCE(NULLIF(substr(s.scheduled_date, 1, 10), ''), '9999-12-31'), s.id"""
    ).fetchall()
    positions = {}
    generated_guides = set()
    timestamp = reception_now()
    for row in rows:
        raw_day = str(row["scheduled_date"] or "")[:10]
        date_key = raw_day.replace("-", "") if len(raw_day) == 10 and raw_day[4:5] == "-" else "SIN-FECHA"
        position = positions.get(date_key, 0)
        guide = f"CAMION-{date_key}-{position // 20 + 1:02d}"
        connection.execute(
            """INSERT OR IGNORE INTO reception_truck_guides
               (guide_code, planned_packages, source_type, is_confirmed,
                created_by, created_at, updated_at)
               VALUES (?, 0, 'PROPUESTA_FECHA', 0, 'sistema.prueba', ?, ?)""",
            (guide, timestamp, timestamp),
        )
        connection.execute("UPDATE reception_shipments SET truck_guide = ? WHERE id = ?", (guide, row["id"]))
        generated_guides.add(guide)
        positions[date_key] = position + 1
    seed_pilot_truck_manifest(connection)
    sync_truck_guide_totals(connection, generated_guides)


def seed_pilot_truck_manifest(connection):
    """Mirror source-provided BL package totals into the legacy/current plan.

    Missing package expectations stay at zero; a guide identifier can be
    synthetic, but physical package counts must come from an operational file.
    """
    rows = connection.execute(
        """SELECT id, truck_guide, expected_packages
             FROM reception_shipments
            WHERE COALESCE(TRIM(truck_guide), '') <> ''"""
    ).fetchall()
    timestamp = reception_now()
    for row in rows:
        actual = float(row["expected_packages"] or 0)
        planned = max(0.0, actual)
        connection.execute(
            """INSERT OR IGNORE INTO reception_truck_manifest
               (truck_guide, shipment_id, expected_packages, source, created_at)
               VALUES (?, ?, ?, 'DHL_PILOTO', ?)""",
            (row["truck_guide"], row["id"], planned, timestamp),
        )
        # Do not replace a saved physical plan with a guessed value.
        connection.execute(
            """UPDATE reception_truck_manifest
                  SET expected_packages = ?
                WHERE lower(truck_guide) = lower(?) AND shipment_id = ?
                  AND COALESCE(expected_packages, 0) <= 0 AND ? > 0""",
            (planned, row["truck_guide"], row["id"], planned),
        )
        connection.execute(
            """INSERT OR IGNORE INTO reception_truck_bl_manifest
               (truck_guide, shipment_id, planned_packages, created_by, created_at, updated_at)
               VALUES (?, ?, ?, 'sistema.migracion', ?, ?)""",
            (row["truck_guide"], row["id"], planned, timestamp, timestamp),
        )


def normalize_single_bl_truck_plans(connection):
    """Kept for schema-migration compatibility; totals are synced as BL sums."""
    sync_truck_guide_totals(connection)


def sync_truck_guide_totals(connection, guide_codes=None):
    """Set each guide total to the sum of its open BL DHL expectations."""
    if guide_codes is not None:
        guide_codes = sorted({str(guide or "").strip().casefold() for guide in guide_codes if str(guide or "").strip()})
        if not guide_codes:
            return
        placeholders = ",".join("?" for _ in guide_codes)
        scope = f" AND lower(g.guide_code) IN ({placeholders})"
    else:
        scope = ""
        guide_codes = []
    guides = connection.execute(
        """SELECT g.guide_code,
                  COALESCE(SUM(CASE WHEN s.app_status <> 'CERRADO' THEN
                      COALESCE(m.planned_packages, 0) ELSE 0 END), 0) AS bl_total
             FROM reception_truck_guides g
             JOIN reception_truck_bl_manifest m ON lower(m.truck_guide) = lower(g.guide_code)
             JOIN reception_shipments s ON s.id = m.shipment_id
            WHERE COALESCE(g.guide_status, 'PENDIENTE') = 'PENDIENTE'
              AND COALESCE(m.operational_active,1)=1
            """ + scope + " GROUP BY g.guide_code",
        guide_codes,
    ).fetchall()
    timestamp = reception_now()
    for guide_row in guides:
        connection.execute(
            "UPDATE reception_truck_guides SET planned_packages = ?, updated_at = ? WHERE lower(guide_code) = lower(?)",
            (float(guide_row["bl_total"] or 0), timestamp, guide_row["guide_code"]),
        )


def _truck_guide_header(connection, guide, create_if_missing=True):
    """Resolve the persistent header for a guide without touching its BLs."""
    row = connection.execute(
        """SELECT * FROM reception_truck_guides
             WHERE lower(guide_code) = lower(?) LIMIT 1""",
        (guide,),
    ).fetchone()
    if row or not create_if_missing:
        return row
    timestamp = reception_now()
    connection.execute(
        """INSERT OR IGNORE INTO reception_truck_guides
           (guide_code, created_by, created_at, updated_at)
           VALUES (?, 'sistema.migracion', ?, ?)""",
        (guide, timestamp, timestamp),
    )
    return connection.execute(
        """SELECT * FROM reception_truck_guides
             WHERE lower(guide_code) = lower(?) LIMIT 1""",
        (guide,),
    ).fetchone()


def _truck_guide_status(header):
    status = str((header or {}).get("guide_status") if isinstance(header, dict)
                 else (header["guide_status"] if header else "") or "").strip().upper()
    return status if status in TRUCK_GUIDE_STATE_INDEX else "PENDIENTE"


def _require_confirmed_truck_guide(connection, guide):
    header = _truck_guide_header(connection, guide, create_if_missing=False)
    if not header:
        raise ValueError("No existe la guía de camión seleccionada")
    # Esta copia local es el simulador operativo de José: sus guías de prueba
    # deben recorrer Llegada y Zona de recepción. Las propuestas por fecha
    # normales siguen requiriendo confirmación administrativa.
    if str(header["source_type"] or "").strip().upper() == "ESTIMACION_PRUEBA":
        return header
    if not int(header["is_confirmed"] or 0):
        raise PermissionError(
            "La agrupación por fecha es solo una propuesta; el administrador debe confirmarla antes de registrar la llegada"
        )
    return header


def _set_truck_guide_status(connection, guide, status, username=""):
    """Persist a forward-only truck state transition on its header."""
    target = str(status or "").strip().upper()
    if target not in TRUCK_GUIDE_STATE_INDEX:
        raise ValueError("Estado de guía de camión no válido")
    header = _truck_guide_header(connection, guide)
    current = _truck_guide_status(header)
    if TRUCK_GUIDE_STATE_INDEX[target] < TRUCK_GUIDE_STATE_INDEX[current]:
        raise PermissionError("La guía de camión no puede retroceder de estado")
    if target == current:
        return current
    timestamp = reception_now()
    if target == "LISTA_PARA_CONTEO":
        connection.execute(
            """UPDATE reception_truck_guides
                  SET guide_status = ?, count_enabled_at = ?, count_enabled_by = ?, updated_at = ?
                WHERE lower(guide_code) = lower(?)""",
            (target, timestamp, username, timestamp, guide),
        )
    else:
        connection.execute(
            """UPDATE reception_truck_guides
                  SET guide_status = ?, updated_at = ?
                WHERE lower(guide_code) = lower(?)""",
            (target, timestamp, guide),
        )
    return target


def list_receptions(connection, search="", role="ADMINISTRADOR", username="", limit=10,
                    arrival_date="", arrival_date_end="", state="", truck_guide=""):
    require_reception_access(role)
    query = """SELECT s.*,
                       (SELECT GROUP_CONCAT(DISTINCT r.sap_ov)
                          FROM order_importation_refs r
                         WHERE lower(COALESCE(r.bl_awb, '')) = lower(COALESCE(s.bl_awb, ''))) AS linked_ovs,
                       (SELECT GROUP_CONCAT(DISTINCT r.transport_type)
                          FROM order_importation_refs r
                         WHERE lower(COALESCE(r.bl_awb, '')) = lower(COALESCE(s.bl_awb, ''))) AS linked_transport,
                       (SELECT COUNT(*) FROM reception_lines l WHERE l.shipment_id = s.id) AS line_count,
                       (SELECT COUNT(*) FROM reception_receipts r WHERE r.shipment_id = s.id) AS receipt_count,
                       (SELECT COUNT(*) FROM reception_attentions a WHERE a.shipment_id = s.id) AS attention_count,
                       (SELECT MAX(a.sequence_no) FROM reception_attentions a
                         WHERE a.shipment_id = s.id AND a.app_status <> 'CERRADO') AS active_attention_sequence,
                       (SELECT COUNT(*) FROM reception_receipts r
                          WHERE r.shipment_id = s.id AND TRIM(COALESCE(r.location_text, '')) = '') AS location_missing_count,
                       (SELECT GROUP_CONCAT(DISTINCT m.truck_guide) FROM reception_truck_bl_manifest m
                         WHERE m.shipment_id = s.id AND COALESCE(m.operational_active,1)=1) AS linked_truck_guides,
                       (SELECT COALESCE(SUM(a.received_packages), 0) FROM reception_truck_bl_arrivals a
                         WHERE a.shipment_id = s.id) AS truck_received_packages
                FROM reception_shipments s"""
    conditions = []
    params = []
    if arrival_date:
        from datetime import date
        arrival_date = date.fromisoformat(str(arrival_date)).isoformat()
        if arrival_date_end:
            arrival_date_end = date.fromisoformat(str(arrival_date_end)).isoformat()
            if arrival_date_end < arrival_date:
                raise ValueError("La fecha final no puede ser anterior a la fecha inicial")
            conditions.append("substr(COALESCE(s.scheduled_date, ''), 1, 10) BETWEEN ? AND ?")
            params.extend([arrival_date, arrival_date_end])
        else:
            conditions.append("substr(COALESCE(s.scheduled_date, ''), 1, 10) = ?")
            params.append(arrival_date)
    elif arrival_date_end:
        from datetime import date
        arrival_date_end = date.fromisoformat(str(arrival_date_end)).isoformat()
        conditions.append("substr(COALESCE(s.scheduled_date, ''), 1, 10) <= ?")
        params.append(arrival_date_end)
    if state and state != "ALL":
        conditions.append("s.app_status = ?")
        params.append(state)
    if truck_guide and truck_guide != "ALL":
        conditions.append("""EXISTS (
            SELECT 1 FROM reception_truck_bl_manifest m
             WHERE m.shipment_id = s.id AND lower(m.truck_guide) = lower(?)
               AND COALESCE(m.operational_active,1)=1
        )""")
        params.append(str(truck_guide).strip())
    else:
        # Las etapas 1 y 2 de BL vinculadas a una guía se ejecutan en Camión.
        # Recepción (BLs) empieza cuando la guía habilita el conteo.
        conditions.append("NOT (EXISTS (SELECT 1 FROM reception_truck_bl_manifest m WHERE m.shipment_id = s.id AND COALESCE(m.operational_active,1)=1) AND s.app_status IN ('PROGRAMADO', 'ARRIBADO') AND COALESCE((SELECT g.guide_status FROM reception_truck_guides g WHERE lower(g.guide_code) = lower(s.truck_guide)), 'PENDIENTE') = 'PENDIENTE')")
    normalized = _normalized_identifier(search)
    # La cola operativa muestra trabajo pendiente por defecto. Las BL cerradas
    # siguen consultables al buscarlas o al elegir explícitamente Todas/Cerrado.
    if not state and not normalized:
        conditions.append("s.app_status <> 'CERRADO'")
    if normalized:
        # BL/AWB no tiene índice intencionalmente: sus formatos cambian entre
        # courier, aéreo y marítimo. Para una búsqueda numérica se usa la
        # clave normalizada y sus últimos cuatro caracteres.
        if normalized.isdigit() and len(normalized) >= 4:
            tail = f"%{normalized[-4:]}%"
            conditions.append("""(
                REPLACE(REPLACE(REPLACE(REPLACE(UPPER(COALESCE(s.bl_awb, '')), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ?
                OR EXISTS (SELECT 1 FROM reception_truck_bl_manifest m WHERE m.shipment_id = s.id AND COALESCE(m.operational_active,1)=1 AND lower(m.truck_guide) LIKE ?)
                OR EXISTS (
                    SELECT 1 FROM reception_lines l
                    WHERE l.shipment_id = s.id
                      AND REPLACE(REPLACE(REPLACE(UPPER(COALESCE(l.np_code, '')), '-', ''), ' ', ''), '/', '') LIKE ?
                )
            )""")
            params.extend([tail, tail, tail])
        else:
            token = f"%{str(search or '').strip().casefold()}%"
            conditions.append("""(lower(COALESCE(s.bl_awb, '')) LIKE ?
                             OR lower(COALESCE(s.supplier, '')) LIKE ?
                             OR lower(COALESCE(s.ip_reference, '')) LIKE ?
                             OR lower(COALESCE(s.primary_oc, '')) LIKE ?
                             OR lower(COALESCE(s.primary_ov, '')) LIKE ?
                             OR lower(COALESCE(s.fr_number, '')) LIKE ?
                             OR lower(COALESCE(s.em_number, '')) LIKE ?
                             OR EXISTS (SELECT 1 FROM reception_truck_bl_manifest m WHERE m.shipment_id = s.id AND COALESCE(m.operational_active,1)=1 AND lower(m.truck_guide) LIKE ?)
                             OR EXISTS (
                                 SELECT 1 FROM order_importation_refs r
                                 WHERE lower(COALESCE(r.bl_awb, '')) = lower(COALESCE(s.bl_awb, ''))
                                   AND (lower(COALESCE(r.sap_ov, '')) LIKE ?
                                        OR lower(COALESCE(r.bl_awb, '')) LIKE ?
                                        OR lower(COALESCE(r.ip_reference, '')) LIKE ?
                                        OR lower(COALESCE(r.oc_number, '')) LIKE ?)
                             )
                             OR EXISTS (
                                SELECT 1 FROM reception_accounting_refs a
                                WHERE a.shipment_id = s.id
                                  AND (lower(COALESCE(a.awb_reference, '')) LIKE ?
                                       OR lower(COALESCE(a.ip_reference, '')) LIKE ?
                                       OR lower(COALESCE(a.fr_number, '')) LIKE ?
                                       OR lower(COALESCE(a.em_number, '')) LIKE ?)
                            )
                             OR EXISTS (
                                SELECT 1 FROM reception_lines l
                                WHERE l.shipment_id = s.id
                                  AND lower(COALESCE(l.np_code, '')) LIKE ?
                             ))""")
            params.extend([token] * 17)
    if role != "ADMINISTRADOR" and username:
        current_user = str(username).strip().casefold()
        conditions.append("""(lower(COALESCE(s.current_assistant, '')) = ?
                              OR lower(COALESCE(s.current_auxiliary, '')) = ?)""")
        params.extend([current_user, current_user])
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += """ ORDER BY CASE
                             -- FR completa y pendiente de EM: trabajo listo para avanzar.
                             WHEN s.accounting_status = 'PENDIENTE EM' THEN 0
                             -- Próximas llegadas: se muestran antes que el resto de la cola.
                             WHEN s.app_status = 'PROGRAMADO' AND COALESCE(s.scheduled_date, '') <> '' THEN 1
                             WHEN s.app_status = 'PROGRAMADO' THEN 2
                             -- Referencias ya cerradas contablemente, pero aún visibles para seguimiento.
                             WHEN s.accounting_status = 'EM REGISTRADA' THEN 3
                             WHEN s.app_status = 'CERRADO' THEN 5
                             ELSE 4
                         END,
                         CASE WHEN s.accounting_status = 'PENDIENTE EM' THEN COALESCE(s.scheduled_date, '9999-12-31') END ASC,
                         CASE WHEN s.app_status = 'PROGRAMADO' THEN COALESCE(s.scheduled_date, '9999-12-31') END ASC,
                         s.updated_at DESC"""
    # Una guía es una unidad operativa: nunca se trunca, para que el lote
    # incluya todas sus BL activas y el servidor conserve su validación de
    # completitud. La cola general mantiene su límite de protección.
    if not (truck_guide and truck_guide != "ALL"):
        query += " LIMIT ?"
        try:
            safe_limit = max(1, min(int(limit), 1000))
        except (TypeError, ValueError):
            safe_limit = 10
        params.append(safe_limit)
    shipment_rows = [_as_dict(row) for row in connection.execute(query, params).fetchall()]
    rows = []
    for shipment_row in shipment_rows:
        shipment_id = int(shipment_row["id"])
        attention_rows = connection.execute(
            """SELECT id, sequence_no, app_status, condition_status,
                      current_assistant, current_auxiliary, receipt_id
                 FROM reception_attentions
                WHERE shipment_id = ?
                ORDER BY sequence_no""",
            (shipment_id,),
        ).fetchall()
        attention_count = len(attention_rows)
        active_id = None
        active_attention = _active_reception_attention(connection, shipment_id)
        if active_attention:
            active_id = int(active_attention["id"])

        # Una BL puede recibirse en varias llegadas. Cada llegada es una
        # atención independiente en la cola para que el equipo pueda ver,
        # por ejemplo, Atención 1/2 y Atención 2/2. El límite SQL se aplica
        # primero a BLs, por lo que una BL con dos atenciones no desplaza a
        # otras BLs del corte inicial.
        queue_items = attention_rows or [None]
        for attention in queue_items:
            item = dict(shipment_row)
            item["accounting_warning"] = _accounting_warning(item.get("accounting_status"))
            if attention is None:
                item["attention_id"] = None
                item["attention_sequence"] = None
                item["attention_total"] = 0
                item["attention_label"] = ""
                item["attention_is_active"] = False
            else:
                attention_id = int(attention["id"])
                item["attention_id"] = attention_id
                item["attention_sequence"] = int(attention["sequence_no"])
                item["attention_total"] = attention_count
                item["attention_label"] = (
                    f"Atención {int(attention['sequence_no'])}/{attention_count}"
                )
                item["attention_is_active"] = attention_id == active_id
                receipt = connection.execute(
                    "SELECT received_packages FROM reception_receipts WHERE id = ?",
                    (attention["receipt_id"],),
                ).fetchone() if attention["receipt_id"] else None
                item["attention_received_packages"] = (
                    float(receipt["received_packages"] or 0) if receipt else 0
                )
                # La cola representa el trabajo de esta llegada, no el
                # resumen histórico de la BL completa.
                item["app_status"] = attention["app_status"]
                item["condition_status"] = attention["condition_status"]
                item["current_assistant"] = attention["current_assistant"] or item.get("current_assistant")
                item["current_auxiliary"] = attention["current_auxiliary"] or item.get("current_auxiliary")
            if not state or state == "ALL" or item.get("app_status") == state:
                rows.append(item)
    return rows


def list_truck_guides(connection, search="", role="ADMINISTRADOR", username="", include_completed=False):
    """Return the operational queue as truck guides, never as a truncated BL list."""
    require_reception_access(role)
    pending_bl_state = """(
        (s.app_status = 'PROGRAMADO'
         OR ((COALESCE(g.is_confirmed,0) = 1 OR COALESCE(g.source_type,'') = 'ESTIMACION_PRUEBA')
             AND s.app_status = 'ARRIBADO')
         OR ((COALESCE(g.is_confirmed,0) = 1 OR COALESCE(g.source_type,'') = 'ESTIMACION_PRUEBA')
             AND s.app_status = 'REVISION SISTEMA'
             AND a.id IS NOT NULL))
        AND (COALESCE(g.is_confirmed,0) = 1
             OR COALESCE(g.source_type,'') = 'ESTIMACION_PRUEBA'
             OR (
            TRIM(COALESCE(s.em_number,'')) = ''
            AND NOT EXISTS (
                SELECT 1 FROM reception_accounting_refs er
                 WHERE er.shipment_id=s.id AND TRIM(COALESCE(er.em_number,''))<>''
            )
            AND NOT EXISTS (
                SELECT 1 FROM reception_accounting_ems ee
                JOIN reception_accounting_refs er ON er.id=ee.accounting_ref_id
                 WHERE er.shipment_id=s.id AND TRIM(COALESCE(ee.em_number,''))<>''
            )
        ))
    )"""
    pending_active_bl_state = """(
        (active.app_status = 'PROGRAMADO'
         OR ((COALESCE(g.is_confirmed,0) = 1 OR COALESCE(g.source_type,'') = 'ESTIMACION_PRUEBA')
             AND active.app_status = 'ARRIBADO')
         OR ((COALESCE(g.is_confirmed,0) = 1 OR COALESCE(g.source_type,'') = 'ESTIMACION_PRUEBA')
             AND active.app_status = 'REVISION SISTEMA'
             AND open_a.id IS NOT NULL))
        AND (COALESCE(g.is_confirmed,0) = 1
             OR COALESCE(g.source_type,'') = 'ESTIMACION_PRUEBA'
             OR (
            TRIM(COALESCE(active.em_number,'')) = ''
            AND NOT EXISTS (
                SELECT 1 FROM reception_accounting_refs er
                 WHERE er.shipment_id=active.id AND TRIM(COALESCE(er.em_number,''))<>''
            )
            AND NOT EXISTS (
                SELECT 1 FROM reception_accounting_ems ee
                JOIN reception_accounting_refs er ON er.id=ee.accounting_ref_id
                 WHERE er.shipment_id=active.id AND TRIM(COALESCE(ee.em_number,''))<>''
            )
        ))
    )"""
    conditions = ["1=1"] if include_completed else [
        f"""EXISTS (
            SELECT 1
              FROM reception_truck_bl_manifest open_m
              JOIN reception_shipments active ON active.id = open_m.shipment_id
              LEFT JOIN reception_truck_bl_arrivals open_a
                ON open_a.shipment_id = active.id
               AND lower(open_a.truck_guide) = lower(open_m.truck_guide)
             WHERE lower(open_m.truck_guide) = lower(m.truck_guide)
               AND COALESCE(open_m.operational_active,1)=1
               AND {pending_active_bl_state}
               AND (COALESCE(g.scanner_enabled,0)=1 OR COALESCE(open_m.planned_packages, 0) > 0
                    OR COALESCE(active.expected_packages, 0) <= 0)
               AND (UPPER(TRIM(COALESCE(active.transport_type,''))) IN ('AEREO','COURIER')
                    OR COALESCE(g.is_confirmed,0) = 1
                    OR COALESCE(g.source_type,'') = 'ESTIMACION_PRUEBA')
               AND (open_a.id IS NOT NULL
                    OR COALESCE(g.scanner_enabled,0)=1
                    OR COALESCE(active.expected_packages, 0) <= 0
                    OR COALESCE(active.received_packages, 0) < COALESCE(active.expected_packages, 0))
        )""",
    ]
    params = []
    if role != "ADMINISTRADOR":
        # El camión es una unidad operativa común. Una guía confirmada puede
        # ser trabajada por recepción aunque sus BL tengan responsables distintos.
        # Las guías de simulación también están habilitadas sin confirmación,
        # igual que en _require_confirmed_truck_guide.
        conditions.append("(COALESCE(g.is_confirmed,0) = 1 OR COALESCE(g.source_type,'') = 'ESTIMACION_PRUEBA')")
    token = str(search or "").strip()
    if token:
        normalized = _normalized_identifier(token)
        match = f"%{normalized}%"
        conditions.append("""(
            REPLACE(REPLACE(UPPER(COALESCE(m.truck_guide, '')), '-', ''), ' ', '') LIKE ?
            OR EXISTS (
                SELECT 1 FROM reception_truck_bl_manifest candidate_m
                JOIN reception_shipments candidate ON candidate.id = candidate_m.shipment_id
                 WHERE lower(candidate_m.truck_guide) = lower(m.truck_guide)
                   AND COALESCE(candidate_m.operational_active,1)=1
                   AND (REPLACE(REPLACE(REPLACE(REPLACE(UPPER(COALESCE(candidate.bl_awb, '')), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ?
                     OR EXISTS (SELECT 1 FROM reception_lines l WHERE l.shipment_id=candidate.id AND REPLACE(REPLACE(UPPER(COALESCE(l.np_code,'')),'-',''),' ','') LIKE ?))
            )
        )""")
        params.extend([match, match, match])
    query = f"""SELECT m.truck_guide,
                      COALESCE(g.guide_status, 'PENDIENTE') AS guide_status,
                      COALESCE(g.planned_packages, 0) AS planned_packages,
                      COALESCE(g.source_type, 'PROPUESTA_FECHA') AS source_type,
                      COALESCE(g.is_confirmed, 0) AS is_confirmed,
                      g.carrier_reference,
                      g.confirmed_by,
                      g.confirmed_at,
                      g.count_enabled_at,
                      g.count_enabled_by,
                      COUNT(DISTINCT s.id) AS bl_count,
                      COALESCE(SUM(CASE
                        WHEN {pending_bl_state}
                         AND (COALESCE(g.scanner_enabled,0)=1 OR COALESCE(m.planned_packages, 0) > 0)
                         AND (a.id IS NOT NULL OR COALESCE(g.scanner_enabled,0)=1
                              OR COALESCE(s.expected_packages, 0) <= 0
                              OR COALESCE(s.received_packages, 0) < COALESCE(s.expected_packages, 0))
                        THEN MIN(
                          COALESCE(m.planned_packages, 0),
                          CASE WHEN COALESCE(s.expected_packages, 0) > 0
                               THEN MAX(0, COALESCE(s.expected_packages, 0)
                                           - MAX(0, COALESCE(s.received_packages, 0)
                                                    - COALESCE(a.received_packages, 0)))
                               ELSE COALESCE(m.planned_packages, 0) END
                        ) ELSE 0 END), 0) AS open_expected_packages,
                      COALESCE(SUM(CASE
                        WHEN {pending_bl_state}
                         AND (COALESCE(g.scanner_enabled,0)=1 OR COALESCE(m.planned_packages, 0) > 0)
                         AND (a.id IS NOT NULL OR COALESCE(g.scanner_enabled,0)=1
                              OR COALESCE(s.expected_packages, 0) <= 0
                              OR COALESCE(s.received_packages, 0) < COALESCE(s.expected_packages, 0))
                        THEN COALESCE(a.received_packages, 0) ELSE 0 END), 0) AS received_packages,
                      MAX(a.arrived_at) AS received_at,
                      SUM(CASE WHEN {pending_bl_state}
                         AND (COALESCE(g.scanner_enabled,0)=1 OR COALESCE(m.planned_packages, 0) > 0
                              OR COALESCE(s.expected_packages, 0) <= 0)
                         AND (a.id IS NOT NULL OR COALESCE(g.scanner_enabled,0)=1
                              OR COALESCE(s.expected_packages, 0) <= 0
                              OR COALESCE(s.received_packages, 0) < COALESCE(s.expected_packages, 0))
                        THEN 1 ELSE 0 END) AS active_bl_count,
                      SUM(CASE WHEN s.app_status = 'CERRADO' THEN 1 ELSE 0 END) AS closed_bl_count,
                      SUM(CASE WHEN s.app_status IN ('PROGRAMADO', 'ARRIBADO')
                                AND COALESCE(s.expected_packages, 0) > 0
                               THEN 1 ELSE 0 END) AS count_startable_bl_count
                 FROM reception_truck_bl_manifest m
                 JOIN reception_shipments s ON s.id = m.shipment_id
                 LEFT JOIN reception_truck_bl_arrivals a
                   ON lower(a.truck_guide) = lower(m.truck_guide) AND a.shipment_id = m.shipment_id
                 LEFT JOIN reception_truck_guides g
                   ON lower(g.guide_code) = lower(m.truck_guide)
                WHERE COALESCE(m.operational_active,1)=1
                  AND COALESCE(g.archived_at,'')=''
                  AND """ + " AND ".join(conditions) + """
                GROUP BY lower(m.truck_guide), m.truck_guide, g.guide_status, g.planned_packages,
                         g.source_type, g.is_confirmed, g.carrier_reference, g.confirmed_by, g.confirmed_at,
                         g.count_enabled_at, g.count_enabled_by
                ORDER BY MIN(COALESCE(s.scheduled_date, '9999-12-31')), m.truck_guide"""
    guides = []
    for row in connection.execute(query, params).fetchall():
        guide = _as_dict(row)
        guide["guide_status"] = _truck_guide_status(guide)
        if (include_completed and int(guide.get("active_bl_count") or 0) == 0
                and int(guide.get("closed_bl_count") or 0) > 0):
            guide["guide_status"] = "FINALIZADA"
        has_bl_arrivals = connection.execute(
            "SELECT 1 FROM reception_truck_bl_arrivals WHERE lower(truck_guide)=lower(?) LIMIT 1",
            (guide["truck_guide"],),
        ).fetchone()
        legacy = connection.execute(
            "SELECT received_packages FROM reception_truck_arrivals WHERE lower(truck_guide)=lower(?)",
            (guide["truck_guide"],),
        ).fetchone()
        if legacy and not has_bl_arrivals:
            guide["legacy_unallocated"] = True
            guide["legacy_received_packages"] = float(legacy["received_packages"] or 0)
            guide["received_packages"] = 0
            guide["guide_status"] = "PENDIENTE"
        elif guide["guide_status"] == "LISTA_PARA_CONTEO" and float(guide["received_packages"] or 0) <= 0:
            guide["guide_status"] = "CERRADA_SIN_BULTOS"
        guide["counting_enabled"] = guide["guide_status"] == "LISTA_PARA_CONTEO"
        # En la cola mostramos lo que falta según las BL aún abiertas. El plan
        # total original queda disponible en planned_packages para trazabilidad.
        guide["expected_packages"] = float(guide.get("open_expected_packages") or 0)
        # La asociación en este piloto procede de la fecha DHL programada;
        # se expone para que la UI no sugiera una captura manual de guías.
        guide["source"] = guide.get("source_type") or "PROPUESTA_FECHA"
        guide["data_pending_count"] = int(connection.execute(
            """SELECT COUNT(*) FROM reception_truck_bl_manifest m
                 JOIN reception_shipments s ON s.id=m.shipment_id
                WHERE lower(m.truck_guide)=lower(?) AND s.app_status<>'CERRADO'
                  AND COALESCE(m.operational_active,1)=1
                  AND COALESCE(s.expected_packages,0)<=0""",
            (guide["truck_guide"],),
        ).fetchone()[0])
        guides.append(guide)
    # New empty trucks must remain selectable after refresh so an admin can
    # continue adding BLs to their manifest.
    if role in {"ADMINISTRADOR", "ASISTENTE_RECEPCION"}:
        empty_conditions = [
            "NOT EXISTS (SELECT 1 FROM reception_truck_bl_manifest m WHERE lower(m.truck_guide)=lower(g.guide_code) AND COALESCE(m.operational_active,1)=1)",
            "COALESCE(g.archived_at,'')=''",
            "(COALESCE(g.source_type,'') IN ('ADMINISTRADOR','ADMIN_CONFIRMADA','TRANSPORTISTA') OR COALESCE(g.scanner_enabled,0)=1 OR (?=1 AND COALESCE(g.source_type,'')='ESCANEO' AND g.guide_status='CANCELADA'))",
        ]
        empty_params = [1 if include_completed else 0]
        if token:
            empty_conditions.append("REPLACE(REPLACE(UPPER(g.guide_code), '-', ''), ' ', '') LIKE ?")
            empty_params.append(match)
        for row in connection.execute(
            "SELECT g.guide_code, g.guide_status, g.planned_packages, g.source_type, g.is_confirmed, "
            "g.carrier_reference, g.confirmed_by, g.confirmed_at, g.count_enabled_at, g.count_enabled_by, g.scanner_enabled "
            "FROM reception_truck_guides g WHERE " + " AND ".join(empty_conditions) + " ORDER BY g.created_at DESC",
            empty_params,
        ).fetchall():
            item = _as_dict(row)
            item["truck_guide"] = item.pop("guide_code")
            item.update({"bl_count": 0, "active_bl_count": 0, "closed_bl_count": 0,
                         "count_startable_bl_count": 0, "open_expected_packages": 0,
                         "received_packages": 0, "expected_packages": 0,
                         "guide_status": _truck_guide_status(item), "counting_enabled": False,
                         "source": item.get("source_type") or "ADMINISTRADOR", "data_pending_count": 0,
                         "scanner_enabled": bool(item.get("scanner_enabled"))})
            guides.append(item)
    return guides


def reception_links(connection, shipment_id, role="ADMINISTRADOR", username=""):
    """Carga bajo demanda la relación única OV/OC de una BL."""
    shipment = _get_reception_shipment(connection, shipment_id, username, role)
    rows = connection.execute(
        """SELECT DISTINCT ov_number, oc_number
             FROM reception_lines
            WHERE shipment_id = ?
              AND (TRIM(COALESCE(ov_number, '')) <> ''
                   OR TRIM(COALESCE(oc_number, '')) <> '')
            ORDER BY ov_number, oc_number""",
        (shipment_id,),
    ).fetchall()
    return {
        "shipment_id": shipment_id,
        "bl_awb": shipment["bl_awb"],
        "rows": [_as_dict(row) for row in rows],
    }


def _truck_package_count(value, label, allow_zero=False):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} debe ser un número entero")
    minimum = 0 if allow_zero else 1
    if not math.isfinite(amount) or amount < minimum or not amount.is_integer():
        raise ValueError(f"{label} debe ser un número entero de al menos {minimum}")
    return int(amount)


def create_truck_guide(connection, scheduled_date="", username="", role="ADMINISTRADOR"):
    """Create the next synthetic truck identifier for an operating date."""
    require_reception_access(role)
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede crear una guía de camión")
    day = str(scheduled_date or reception_now()[:10]).strip()[:10]
    try:
        day = date.fromisoformat(day).strftime("%Y%m%d")
    except ValueError:
        raise ValueError("Selecciona una fecha válida para el camión")
    prefix = f"CAMION-{day}-"
    existing = connection.execute(
        "SELECT guide_code FROM reception_truck_guides WHERE guide_code LIKE ?",
        (prefix + "%",),
    ).fetchall()
    sequence = 1
    for row in existing:
        match = re.search(r"-(\d+)$", str(row["guide_code"] or ""))
        if match:
            sequence = max(sequence, int(match.group(1)) + 1)
    guide = f"{prefix}{sequence:02d}"
    timestamp = reception_now()
    connection.execute(
        """INSERT INTO reception_truck_guides
           (guide_code, guide_status, planned_packages, source_type, is_confirmed,
            created_by, created_at, updated_at)
           VALUES (?, 'PENDIENTE', 0, 'ADMINISTRADOR', 1, ?, ?, ?)""",
        (guide, username or "sistema", timestamp, timestamp),
    )
    return {"truck_guide": guide}


def create_scanner_truck_guide(connection, username="", role="ASISTENTE_RECEPCION"):
    """Create an empty operational guide for physical BL/package scanning."""
    require_reception_access(role)
    if role not in {"ADMINISTRADOR", "ASISTENTE_RECEPCION"}:
        raise PermissionError("Tu rol no puede iniciar una recepción por escaneo")
    timestamp = reception_now()
    day = date.fromisoformat(timestamp[:10]).strftime("%Y%m%d")
    prefix = f"SCAN-{day}-"
    rows = connection.execute(
        "SELECT guide_code FROM reception_truck_guides WHERE guide_code LIKE ?", (prefix + "%",)
    ).fetchall()
    sequence = max(
        [int(match.group(1)) for row in rows
         if (match := re.search(r"-(\d+)$", str(row["guide_code"] or "")))] or [0]
    ) + 1
    guide = f"{prefix}{sequence:02d}"
    connection.execute(
        """INSERT INTO reception_truck_guides
           (guide_code, guide_status, planned_packages, source_type, is_confirmed,
            scanner_enabled, created_by, created_at, updated_at)
           VALUES (?, 'PENDIENTE', 0, 'ESCANEO', 1, 1, ?, ?, ?)""",
        (guide, username or "sistema", timestamp, timestamp),
    )
    return {"truck_guide": guide, "guide_status": "PENDIENTE", "scanner_enabled": True}


def _normalize_scan_code(value, label):
    code = str(value or "").strip()
    if not code or len(code) > 120 or any(ord(char) < 32 for char in code):
        raise ValueError(f"Escanea o ingresa un {label} válido")
    # Preserve leading zeros and punctuation; normalize only scanner whitespace/case.
    return code, re.sub(r"\s+", "", code).upper()


def add_scanned_truck_bl(connection, truck_guide, bl_code, username, role):
    """Resolve a scanned BL and attach it to an empty scanner guide, idempotently."""
    require_reception_access(role)
    guide = str(truck_guide or "").strip()
    header = _truck_guide_header(connection, guide, create_if_missing=False)
    if not header or not int(header["scanner_enabled"] or 0):
        raise ValueError("Esta guía no usa el flujo de escaneo")
    if _truck_guide_status(header) not in {"PENDIENTE", "EN_CURSO"}:
        raise ValueError("La llegada ya se cerró; no se pueden agregar BL")
    raw, normalized = _normalize_scan_code(bl_code, "BL/AWB")
    shipment = connection.execute(
        """SELECT * FROM reception_shipments
            WHERE upper(replace(replace(trim(bl_awb),' ',''),'-','')) = ?
            ORDER BY id DESC LIMIT 1""",
        (normalized.replace("-", ""),),
    ).fetchone()
    if not shipment:
        raise ValueError("No se encontró una BL/AWB con ese código")
    if str(shipment["app_status"] or "").upper() == "CERRADO":
        raise ValueError("La BL ya está cerrada y no puede recibirse nuevamente")
    previous_guide = str(shipment["truck_guide"] or "").strip()
    existing = connection.execute(
        "SELECT * FROM reception_truck_bl_manifest WHERE lower(truck_guide)=lower(?) AND shipment_id=?",
        (guide, int(shipment["id"])),
    ).fetchone()
    if existing and int(existing["operational_active"] or 1):
        return {"added": False, "duplicate": True, "shipment_id": int(shipment["id"]),
                "bl_awb": shipment["bl_awb"]}
    if existing:
        connection.execute(
            "UPDATE reception_truck_bl_manifest SET operational_active=1, updated_at=? WHERE truck_guide=? AND shipment_id=?",
            (reception_now(), guide, int(shipment["id"])),
        )
    else:
        connection.execute(
            """INSERT INTO reception_truck_bl_manifest
               (truck_guide, shipment_id, planned_packages, operational_active,
                created_by, created_at, updated_at)
               VALUES (?, ?, 0, 1, ?, ?, ?)""",
            (guide, int(shipment["id"]), username, reception_now(), reception_now()),
        )
    connection.execute(
        "UPDATE reception_shipments SET truck_guide=?, updated_at=? WHERE id=?",
        (guide, reception_now(), int(shipment["id"])),
    )
    connection.execute(
        "UPDATE reception_truck_guides SET guide_status='EN_CURSO', updated_at=? WHERE lower(guide_code)=lower(?) AND guide_status='PENDIENTE'",
        (reception_now(), guide),
    )
    _write_history(connection, int(shipment["id"]), "ESCANEO BL", f"guia:{guide}:bl",
                   previous_guide, raw, username, "BL agregada por lectura de código")
    return {"added": True, "duplicate": False, "shipment_id": int(shipment["id"]),
            "bl_awb": shipment["bl_awb"]}


def scan_truck_package(connection, truck_guide, shipment_id, package_code, username, role):
    """Persist one unique package scan; duplicate retries never change counts."""
    require_reception_access(role)
    guide = str(truck_guide or "").strip()
    header = _truck_guide_header(connection, guide, create_if_missing=False)
    if not header or not int(header["scanner_enabled"] or 0):
        raise ValueError("Esta guía no usa el flujo de escaneo")
    if role not in {"ADMINISTRADOR", "ASISTENTE_RECEPCION", "AUXILIAR_RECEPCION"}:
        raise PermissionError("Tu rol no puede registrar bultos recibidos")
    if _truck_guide_status(header) not in {"PENDIENTE", "EN_CURSO"}:
        raise ValueError("La llegada de esta guía ya está cerrada")
    raw, normalized = _normalize_scan_code(package_code, "código de paquete")
    try:
        shipment_id = int(shipment_id)
    except (TypeError, ValueError):
        raise ValueError("Escanea primero una BL válida")
    manifest = connection.execute(
        """SELECT 1 FROM reception_truck_bl_manifest
            WHERE lower(truck_guide)=lower(?) AND shipment_id=? AND COALESCE(operational_active,1)=1""",
        (guide, shipment_id),
    ).fetchone()
    if not manifest:
        raise ValueError("Escanea primero la BL que corresponde a este paquete")
    if connection.execute(
        "SELECT 1 FROM reception_truck_bl_arrivals WHERE lower(truck_guide)=lower(?) AND shipment_id=?",
        (guide, shipment_id),
    ).fetchone():
        raise ValueError("La llegada de esta BL ya se guardó; revísala desde Zona de recepción")
    duplicate = connection.execute(
        """SELECT ps.truck_guide, ps.shipment_id, s.bl_awb
             FROM reception_truck_package_scans ps
             JOIN reception_shipments s ON s.id=ps.shipment_id
            WHERE ps.normalized_code=? AND ps.scan_status='ACTIVO'""",
        (normalized,),
    ).fetchone()
    if duplicate:
        if str(duplicate["truck_guide"]).casefold() == guide.casefold() and int(duplicate["shipment_id"]) == shipment_id:
            return {"duplicate": True, "accepted": False,
                    "count": int(connection.execute(
                        "SELECT COUNT(*) FROM reception_truck_package_scans WHERE lower(truck_guide)=lower(?) AND shipment_id=? AND scan_status='ACTIVO'",
                        (guide, shipment_id),
                    ).fetchone()[0])}
        raise ValueError(
            "Ese código de paquete ya fue registrado en otra BL o guía "
            f"(BL/AWB: {duplicate['bl_awb']}; guía: {duplicate['truck_guide']})"
        )
    connection.execute(
        """INSERT INTO reception_truck_package_scans
           (truck_guide, shipment_id, package_code, normalized_code, scanned_by, scanned_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (guide, shipment_id, raw, normalized, username, reception_now()),
    )
    count = int(connection.execute(
        "SELECT COUNT(*) FROM reception_truck_package_scans WHERE lower(truck_guide)=lower(?) AND shipment_id=? AND scan_status='ACTIVO'",
        (guide, shipment_id),
    ).fetchone()[0])
    connection.execute(
        "UPDATE reception_truck_bl_manifest SET planned_packages=?, updated_at=? WHERE lower(truck_guide)=lower(?) AND shipment_id=?",
        (count, reception_now(), guide, shipment_id),
    )
    connection.execute(
        "UPDATE reception_truck_guides SET planned_packages=(SELECT COALESCE(SUM(planned_packages),0) FROM reception_truck_bl_manifest WHERE lower(truck_guide)=lower(?) AND COALESCE(operational_active,1)=1), updated_at=? WHERE lower(guide_code)=lower(?)",
        (guide, reception_now(), guide),
    )
    _write_history(connection, shipment_id, "ESCANEO BULTO", f"guia:{guide}:paquete:{normalized}",
                   "", raw, username, "Paquete único registrado por escáner")
    return {"duplicate": False, "accepted": True, "count": count}


def finalize_scanned_truck_arrival(connection, truck_guide, notes, username, role):
    """Convert durable package scans into the normal per-BL arrival records."""
    require_reception_access(role)
    guide = str(truck_guide or "").strip()
    header = _truck_guide_header(connection, guide, create_if_missing=False)
    if not header or not int(header["scanner_enabled"] or 0):
        raise ValueError("Esta guía no usa el flujo de escaneo")
    counts = connection.execute(
        """SELECT ps.shipment_id, COUNT(*) AS received,
                  s.expected_packages, s.received_packages
             FROM reception_truck_package_scans ps
             JOIN reception_shipments s ON s.id=ps.shipment_id
            WHERE lower(ps.truck_guide)=lower(?) AND ps.scan_status='ACTIVO'
            GROUP BY ps.shipment_id, s.expected_packages, s.received_packages
            ORDER BY ps.shipment_id""", (guide,)
    ).fetchall()
    if not counts:
        raise ValueError("Escanea al menos un bulto antes de guardar la llegada")
    bls = []
    for row in counts:
        total_received = float(row["received_packages"] or 0)
        expected = float(row["expected_packages"] or 0)
        reason = (
            "Diferencia registrada por escaneo físico"
            if expected > 0 and total_received > expected else ""
        )
        bls.append({"shipment_id": int(row["shipment_id"]),
                    "received_packages": int(row["received"]),
                    "excess_reason": reason})
    return process_truck_guide_arrivals(
        connection, guide, bls, f"scan-arrival:{guide}:{uuid.uuid4().hex}",
        notes or "Llegada registrada por escaneo de paquetes", username, role,
    )


def cancel_scanned_truck_arrival(connection, truck_guide, username, role):
    """Cancel an unfinished scanner arrival, voiding scans and restoring BL links."""
    require_reception_access(role)
    if role not in {"ADMINISTRADOR", "ASISTENTE_RECEPCION"}:
        raise PermissionError("Tu rol no puede cancelar una recepción nueva")
    guide = str(truck_guide or "").strip()
    header = _truck_guide_header(connection, guide, create_if_missing=False)
    if not header or not int(header["scanner_enabled"] or 0):
        raise ValueError("Esta guía no usa el flujo de escaneo")
    if _truck_guide_status(header) not in {"PENDIENTE", "EN_CURSO"}:
        raise ValueError("La llegada ya terminó; usa el retroceso del camión para corregirla")
    if connection.execute(
        "SELECT 1 FROM reception_truck_bl_arrivals WHERE lower(truck_guide)=lower(?) LIMIT 1",
        (guide,),
    ).fetchone():
        raise ValueError("La llegada ya se guardó; no se puede cancelar desde el escáner")

    timestamp = reception_now()
    manifests = connection.execute(
        """SELECT m.shipment_id, s.bl_awb
             FROM reception_truck_bl_manifest m
             JOIN reception_shipments s ON s.id=m.shipment_id
            WHERE lower(m.truck_guide)=lower(?) AND COALESCE(m.operational_active,1)=1""",
        (guide,),
    ).fetchall()
    total_voided = 0
    for manifest in manifests:
        shipment_id = int(manifest["shipment_id"])
        bl_voided = int(connection.execute(
            """SELECT COUNT(*) FROM reception_truck_package_scans
                WHERE lower(truck_guide)=lower(?) AND shipment_id=? AND scan_status='ACTIVO'""",
            (guide, shipment_id),
        ).fetchone()[0] or 0)
        total_voided += bl_voided
        connection.execute(
            """UPDATE reception_truck_package_scans
                  SET scan_status='ANULADO', voided_by=?, voided_at=?, void_reason=?
                WHERE lower(truck_guide)=lower(?) AND shipment_id=? AND scan_status='ACTIVO'""",
            (username, timestamp, "Recepción cancelada antes de confirmar la llegada", guide, shipment_id),
        )
        previous = connection.execute(
            """SELECT old_value FROM reception_history
                WHERE shipment_id=? AND event_type='ESCANEO BL' AND field_name=?
                ORDER BY id DESC LIMIT 1""",
            (shipment_id, f"guia:{guide}:bl"),
        ).fetchone()
        previous_guide = str(previous["old_value"] or "").strip() if previous else ""
        connection.execute(
            """UPDATE reception_shipments
                  SET truck_guide=?, updated_at=?
                WHERE id=? AND lower(COALESCE(truck_guide,''))=lower(?)""",
            (previous_guide or None, timestamp, shipment_id, guide),
        )
        connection.execute(
            """UPDATE reception_truck_bl_manifest
                  SET operational_active=0, updated_at=?
                WHERE lower(truck_guide)=lower(?) AND shipment_id=?""",
            (timestamp, guide, shipment_id),
        )
        _write_history(
            connection, shipment_id, "CANCELACION ESCANEO", f"guia:{guide}:bl",
            guide, previous_guide, username,
            f"Recepción cancelada antes de la llegada; {bl_voided} lectura(s) de paquete anuladas",
        )
    connection.execute(
        """UPDATE reception_truck_guides
              SET guide_status='CANCELADA', scanner_enabled=0, planned_packages=0, updated_at=?
            WHERE lower(guide_code)=lower(?)""",
        (timestamp, guide),
    )
    return {"truck_guide": guide, "cancelled": True,
            "cancelled_bls": len(manifests), "voided_package_scans": total_voided,
            "guide_status": "CANCELADA"}


def archive_cancelled_scanned_truck_guide(connection, truck_guide, reason, username, role):
    """Hide a cancelled, empty scanner guide without deleting its audit trail."""
    require_reception_access(role)
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede retirar una guía cancelada del historial")
    guide = str(truck_guide or "").strip()
    header = _truck_guide_header(connection, guide, create_if_missing=False)
    if not header or not (
        str(header["source_type"] or "").upper() == "ESCANEO"
        or guide.upper().startswith("SCAN-")
    ):
        raise ValueError("Solo se puede retirar una guía creada por escaneo")
    if _truck_guide_status(header) != "CANCELADA":
        raise ValueError("Primero cancela la recepción del escáner antes de retirar la guía")
    if connection.execute(
        "SELECT 1 FROM reception_truck_bl_arrivals WHERE lower(truck_guide)=lower(?) LIMIT 1",
        (guide,),
    ).fetchone() or connection.execute(
        "SELECT 1 FROM reception_truck_arrivals WHERE lower(truck_guide)=lower(?) LIMIT 1",
        (guide,),
    ).fetchone():
        raise ValueError("La guía tiene una llegada guardada; usa el retroceso administrativo")
    if connection.execute(
        """SELECT 1 FROM reception_truck_bl_manifest
             WHERE lower(truck_guide)=lower(?) AND COALESCE(operational_active,1)=1 LIMIT 1""",
        (guide,),
    ).fetchone():
        raise ValueError("La guía aún tiene BL activas; cancela primero la recepción")
    note = str(reason or "").strip()
    if len(note) < 5:
        raise ValueError("Indica un motivo de al menos 5 caracteres")
    timestamp = reception_now()
    # Soft-delete intencional: se mantiene el código y sus escaneos anulados
    # para trazabilidad, pero deja de salir en las colas y el historial visible.
    connection.execute(
        """UPDATE reception_truck_guides
              SET archived_at=?, archived_by=?, archive_reason=?, scanner_enabled=0,
                  planned_packages=0, updated_at=?
            WHERE lower(guide_code)=lower(?)""",
        (timestamp, username, note, timestamp, guide),
    )
    return {"truck_guide": guide, "archived": True, "archived_at": timestamp}


def confirm_truck_guide(connection, truck_guide, carrier_reference, username, role):
    """Habilita una guía para iniciar el flujo de llegada del piloto."""
    require_reception_access(role)
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede confirmar una guía propuesta")
    guide = str(truck_guide or "").strip()
    if not guide:
        raise ValueError("Selecciona una guía de camión")
    header = _truck_guide_header(connection, guide, create_if_missing=False)
    if not header:
        raise ValueError("No existe la guía de camión seleccionada")
    if _truck_guide_status(header) != "PENDIENTE":
        raise PermissionError("La referencia del transportista debe confirmarse antes de registrar la llegada")
    reference = str(carrier_reference or "").strip()
    if len(reference) > 80:
        raise ValueError("La referencia del transportista es demasiado larga")
    if reference and connection.execute(
        """SELECT 1 FROM reception_truck_guides
            WHERE lower(TRIM(COALESCE(carrier_reference,'')))=lower(?)
              AND lower(guide_code)<>lower(?) LIMIT 1""",
        (reference, guide),
    ).fetchone():
        raise ValueError("La referencia real del transportista ya está vinculada a otra guía")
    timestamp = reception_now()
    source_type = "TRANSPORTISTA" if reference else "ADMIN_CONFIRMADA"
    connection.execute(
        """UPDATE reception_truck_guides
              SET is_confirmed=1, source_type=?, carrier_reference=?,
                  confirmed_by=?, confirmed_at=?, updated_at=?
            WHERE lower(guide_code)=lower(?)""",
        (source_type, reference, username, timestamp, timestamp, guide),
    )
    for row in connection.execute(
        "SELECT shipment_id FROM reception_truck_bl_manifest WHERE lower(truck_guide)=lower(?) AND COALESCE(operational_active,1)=1",
        (guide,),
    ).fetchall():
        _write_history(
            connection, int(row["shipment_id"]), "CONFIRMACION CAMION",
            f"guia:{guide}:referencia_transportista", "PROPUESTA",
            reference or guide, username,
            "Guía habilitada para recepción por administrador",
        )
    return truck_guide_summary(connection, guide, username, role)


def update_truck_bl_expected_packages(connection, truck_guide, shipment_id,
                                      expected_packages, reason, username, role):
    """Corrige un esperado faltante sin inventarlo y deja auditoría por BL."""
    require_reception_access(role)
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede confirmar los bultos esperados")
    guide = str(truck_guide or "").strip()
    amount = _truck_package_count(expected_packages, "Bultos esperados")
    reason = str(reason or "").strip()
    if len(reason) < 5:
        raise ValueError("Indica el motivo o la fuente de la cantidad esperada")
    try:
        shipment_id = int(shipment_id)
    except (TypeError, ValueError):
        raise ValueError("Selecciona una BL válida")
    shipment = connection.execute(
        "SELECT * FROM reception_shipments WHERE id=?", (shipment_id,)
    ).fetchone()
    if not shipment:
        raise ValueError("No existe la BL seleccionada")
    manifest = connection.execute(
        "SELECT planned_packages FROM reception_truck_bl_manifest WHERE shipment_id=? AND lower(truck_guide)=lower(?) AND COALESCE(operational_active,1)=1",
        (shipment_id, guide),
    ).fetchone()
    if not manifest:
        raise ValueError("La BL no pertenece a esta guía")
    received = float(connection.execute(
        "SELECT COALESCE(SUM(received_packages),0) FROM reception_truck_bl_arrivals WHERE shipment_id=?",
        (shipment_id,),
    ).fetchone()[0] or 0)
    if amount < received:
        raise ValueError(f"El esperado no puede ser menor que los {received:g} bultos ya recibidos")
    other_planned = float(connection.execute(
        """SELECT COALESCE(SUM(planned_packages),0) FROM reception_truck_bl_manifest
            WHERE shipment_id=? AND lower(truck_guide)<>lower(?) AND COALESCE(operational_active,1)=1""",
        (shipment_id, guide),
    ).fetchone()[0] or 0)
    if other_planned > amount:
        raise ValueError("El nuevo esperado es menor que lo programado en otros camiones")
    old_expected = float(shipment["expected_packages"] or 0)
    current_plan = float(manifest["planned_packages"] or 0)
    if current_plan + other_planned > amount:
        raise ValueError(
            "El nuevo esperado es menor que el total ya programado; corrige primero la distribución entre camiones"
        )
    new_plan = current_plan or max(0, amount - other_planned)
    timestamp = reception_now()
    connection.execute(
        "UPDATE reception_shipments SET expected_packages=?, updated_at=? WHERE id=?",
        (amount, timestamp, shipment_id),
    )
    connection.execute(
        """UPDATE reception_truck_bl_manifest
              SET planned_packages=?, updated_at=?
            WHERE shipment_id=? AND lower(truck_guide)=lower(?)""",
        (new_plan, timestamp, shipment_id, guide),
    )
    sync_truck_guide_totals(connection, [guide])
    _write_history(
        connection, shipment_id, "CORRECCION CAMION", "expected_packages",
        old_expected, amount, username, reason,
    )
    if new_plan != current_plan:
        _write_history(
            connection, shipment_id, "PROGRAMACION CAMION",
            f"guia:{guide}:bultos_programados", current_plan, new_plan,
            username, f"Programación habilitada por esperado confirmado: {reason}",
        )
    return truck_guide_summary(connection, guide, username, role)


def remove_truck_bl_from_proposal(connection, truck_guide, shipment_id, reason, username, role):
    """Retira una BL de una propuesta errónea sin borrar la guía ni su auditoría."""
    require_reception_access(role)
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede corregir una propuesta")
    guide = str(truck_guide or "").strip()
    reason = str(reason or "").strip()
    if len(reason) < 5:
        raise ValueError("Indica el motivo de la corrección del grupo")
    try:
        shipment_id = int(shipment_id)
    except (TypeError, ValueError):
        raise ValueError("Selecciona una BL válida")
    header = _truck_guide_header(connection, guide, create_if_missing=False)
    if not header:
        raise ValueError("No existe la guía seleccionada")
    if int(header["is_confirmed"] or 0):
        raise PermissionError("La guía ya fue confirmada; primero debe revertirse mediante control administrativo")
    manifest = connection.execute(
        "SELECT planned_packages FROM reception_truck_bl_manifest WHERE shipment_id=? AND lower(truck_guide)=lower(?) AND COALESCE(operational_active,1)=1",
        (shipment_id, guide),
    ).fetchone()
    if not manifest:
        raise ValueError("La BL no pertenece a esta propuesta")
    if connection.execute(
        "SELECT 1 FROM reception_truck_bl_arrivals WHERE shipment_id=? AND lower(truck_guide)=lower(?)",
        (shipment_id, guide),
    ).fetchone():
        raise PermissionError("La BL ya tiene una llegada registrada en esta guía")
    connection.execute(
        """UPDATE reception_truck_bl_manifest SET operational_active=0, updated_at=?
             WHERE shipment_id=? AND lower(truck_guide)=lower(?)""",
        (reception_now(), shipment_id, guide),
    )
    fallback = connection.execute(
        """SELECT truck_guide FROM reception_truck_bl_manifest
            WHERE shipment_id=? AND COALESCE(operational_active,1)=1
            ORDER BY created_at LIMIT 1""",
        (shipment_id,),
    ).fetchone()
    connection.execute(
        "UPDATE reception_shipments SET truck_guide=?, updated_at=? WHERE id=?",
        (fallback["truck_guide"] if fallback else None, reception_now(), shipment_id),
    )
    sync_truck_guide_totals(connection, [guide])
    _write_history(
        connection, shipment_id, "CORRECCION CAMION", "truck_auto_excluded",
        guide, "1", username, reason,
    )
    return truck_guide_summary(connection, guide, username, role)


def plan_truck_bl_packages(connection, truck_guide, shipment_id, planned_packages, username, role):
    """Assign part of one BL's expected package total to a truck."""
    require_reception_access(role)
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede programar BL en camiones")
    guide = str(truck_guide or "").strip()
    if not guide:
        raise ValueError("Selecciona una guía de camión")
    amount = _truck_package_count(planned_packages, "Bultos programados")
    try:
        shipment_id = int(shipment_id)
    except (TypeError, ValueError):
        raise ValueError("Selecciona una BL válida")
    shipment = connection.execute(
        "SELECT * FROM reception_shipments WHERE id = ?", (shipment_id,)
    ).fetchone()
    if not shipment:
        raise ValueError("No existe la BL seleccionada")
    if shipment["app_status"] == "CERRADO":
        raise PermissionError("No se puede programar una BL cerrada en otro camión")
    expected = float(shipment["expected_packages"] or 0)
    if expected <= 0:
        raise ValueError("La BL no tiene bultos esperados en la fuente; no programes una cantidad estimada")
    header = _truck_guide_header(connection, guide)
    if _truck_guide_status(header) == "LISTA_PARA_CONTEO":
        raise PermissionError("La guía ya pasó a conteo; regrésala a etapa pendiente antes de modificar el manifiesto")
    existing_arrival = connection.execute(
        "SELECT 1 FROM reception_truck_bl_arrivals WHERE shipment_id = ? AND lower(truck_guide) = lower(?)",
        (shipment_id, guide),
    ).fetchone()
    if existing_arrival:
        raise PermissionError("La BL ya tiene una llegada confirmada en este camión")
    current_plan = connection.execute(
        "SELECT planned_packages FROM reception_truck_bl_manifest WHERE shipment_id = ? AND lower(truck_guide) = lower(?) AND COALESCE(operational_active,1)=1",
        (shipment_id, guide),
    ).fetchone()
    current_amount = float(current_plan["planned_packages"] or 0) if current_plan else 0.0
    balance = truck_bl_package_balance(connection, shipment_id)
    max_for_this_guide = current_amount + float(balance["pending_to_plan_packages"] or 0)
    if amount > max_for_this_guide:
        raise ValueError(
            f"La programación supera el saldo pendiente de la BL ({max_for_this_guide:g} bultos disponibles para esta guía)"
        )
    timestamp = reception_now()
    connection.execute(
        """INSERT INTO reception_truck_bl_manifest
           (truck_guide, shipment_id, planned_packages, created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(truck_guide, shipment_id) DO UPDATE SET
             planned_packages=excluded.planned_packages, operational_active=1,
             updated_at=excluded.updated_at""",
        (guide, shipment_id, amount, username, timestamp, timestamp),
    )
    connection.execute(
        """INSERT OR IGNORE INTO reception_truck_guides
           (guide_code, guide_status, planned_packages, created_by, created_at, updated_at)
           VALUES (?, 'PENDIENTE', 0, ?, ?, ?)""",
        (guide, username, timestamp, timestamp),
    )
    connection.execute(
        "UPDATE reception_truck_guides SET planned_packages = ?, updated_at = ? WHERE lower(guide_code) = lower(?)",
        (float(connection.execute(
            "SELECT COALESCE(SUM(planned_packages),0) FROM reception_truck_bl_manifest WHERE lower(truck_guide)=lower(?) AND COALESCE(operational_active,1)=1",
            (guide,),
        ).fetchone()[0] or 0), timestamp, guide),
    )
    if not str(shipment["truck_guide"] or "").strip():
        connection.execute("UPDATE reception_shipments SET truck_guide = ? WHERE id = ?", (guide, shipment_id))
    _write_history(
        connection, shipment_id, "PROGRAMACION CAMION", f"guia:{guide}:bultos_programados",
        current_plan["planned_packages"] if current_plan else "", amount, username,
    )
    return next(row for row in list_truck_bl_plans(connection, shipment_id) if row["truck_guide"].casefold() == guide.casefold())


def truck_bl_package_balance(connection, shipment_id):
    shipment = connection.execute(
        "SELECT expected_packages, received_packages FROM reception_shipments WHERE id = ?", (int(shipment_id),)
    ).fetchone()
    if not shipment:
        raise ValueError("No existe la BL seleccionada")
    expected = max(0.0, float(shipment["expected_packages"] or 0))
    tracked_received = float(connection.execute(
        "SELECT COALESCE(SUM(received_packages),0) FROM reception_truck_bl_arrivals WHERE shipment_id = ?",
        (int(shipment_id),),
    ).fetchone()[0] or 0)
    # El total de la BL también contiene recepciones anteriores al desglose por
    # camión. Se usa el mayor acumulado para reconocerlas sin duplicarlas.
    received = max(tracked_received, float(shipment["received_packages"] or 0))
    unarrived = float(connection.execute(
        """SELECT COALESCE(SUM(m.planned_packages),0)
             FROM reception_truck_bl_manifest m
            WHERE m.shipment_id = ?
              AND COALESCE(m.operational_active,1)=1
              AND NOT EXISTS (SELECT 1 FROM reception_truck_bl_arrivals a
                               WHERE a.shipment_id=m.shipment_id AND lower(a.truck_guide)=lower(m.truck_guide))""",
        (int(shipment_id),),
    ).fetchone()[0] or 0)
    pending = max(0.0, expected - received)
    return {
        "expected_packages": expected,
        "received_packages": received,
        "pending_packages": pending,
        "planned_unarrived_packages": unarrived,
        "pending_to_plan_packages": max(0.0, pending - unarrived),
    }


def list_truck_bl_plans(connection, shipment_id):
    return [
        _as_dict(row)
        for row in connection.execute(
            """SELECT m.truck_guide, m.shipment_id, m.planned_packages,
                      a.id AS arrival_id, COALESCE(a.received_packages,0) AS received_packages,
                      a.arrival_key, a.excess_reason, a.username, a.arrived_at
                 FROM reception_truck_bl_manifest m
                 LEFT JOIN reception_truck_bl_arrivals a
                   ON a.shipment_id=m.shipment_id AND lower(a.truck_guide)=lower(m.truck_guide)
                WHERE m.shipment_id = ? AND COALESCE(m.operational_active,1)=1
                ORDER BY m.created_at, m.truck_guide""",
            (int(shipment_id),),
        ).fetchall()
    ]


def confirm_truck_bl_arrival(connection, truck_guide, shipment_id, received_packages,
                             arrival_key, username, role, excess_reason="", notes=""):
    require_reception_access(role)
    guide = str(truck_guide or "").strip()
    key = str(arrival_key or "").strip()
    if not guide or not key:
        raise ValueError("La guía y la clave de llegada son obligatorias")
    _require_confirmed_truck_guide(connection, guide)
    amount = _truck_package_count(received_packages, "Bultos recibidos", allow_zero=True)
    shipment = connection.execute(
        "SELECT * FROM reception_shipments WHERE id = ?", (int(shipment_id),)
    ).fetchone()
    if not shipment:
        raise ValueError("No existe la BL seleccionada")
    if role not in {"ADMINISTRADOR", "ASISTENTE_RECEPCION"}:
        raise PermissionError("Solo un administrador o asistente de recepción puede confirmar la llegada del camión")
    plan = connection.execute(
        "SELECT planned_packages FROM reception_truck_bl_manifest WHERE shipment_id = ? AND lower(truck_guide) = lower(?) AND COALESCE(operational_active,1)=1",
        (int(shipment_id), guide),
    ).fetchone()
    if not plan:
        raise ValueError("La BL no está programada en esta guía de camión")
    guide_header = _truck_guide_header(connection, guide, create_if_missing=False)
    guide_state = _truck_guide_status(guide_header)
    existing = connection.execute(
        "SELECT * FROM reception_truck_bl_arrivals WHERE shipment_id = ? AND lower(truck_guide) = lower(?)",
        (int(shipment_id), guide),
    ).fetchone()
    previous_key = connection.execute(
        "SELECT * FROM reception_truck_bl_arrivals WHERE arrival_key = ?", (key,)
    ).fetchone()
    if previous_key:
        if (existing and int(previous_key["id"]) == int(existing["id"])
                and guide_state == "PENDIENTE"):
            # An administrator explicitly rolled the guide back to transit.
            # Reuse its BL arrival row as a correction instead of creating a
            # duplicate physical receipt or rejecting the new quantities.
            pass
        elif (int(previous_key["shipment_id"]) == int(shipment_id)
                and str(previous_key["truck_guide"]).casefold() == guide.casefold()
                and float(previous_key["received_packages"]) == amount
                and str(previous_key["excess_reason"] or "") == str(excess_reason or "").strip()
                and str(previous_key["notes"] or "") == str(notes or "").strip()):
            payload = _as_dict(previous_key)
            payload["arrival_id"] = int(previous_key["id"])
            return payload
        else:
            raise ValueError("La clave de reintento ya se usó para otra llegada o cantidad")
    revising_existing = existing is not None
    if revising_existing:
        if guide_state != "PENDIENTE":
            raise ValueError("La llegada ya está registrada. El administrador debe regresar el camión a Tránsito antes de corregirla")
        if str(shipment["app_status"] or "").upper() not in {"PROGRAMADO", "ARRIBADO"}:
            raise ValueError("La BL ya avanzó al conteo. Reabre primero la etapa de la BL y déjala en Zona de recepción para corregir el camión")
    expected = max(0.0, float(shipment["expected_packages"] or 0))
    previous_received = float(connection.execute(
        """SELECT COALESCE(SUM(received_packages),0) FROM reception_truck_bl_arrivals
            WHERE shipment_id = ? AND (? = 0 OR id <> ?)""",
        (int(shipment_id), int(revising_existing), int(existing["id"]) if existing else -1),
    ).fetchone()[0] or 0)
    mapped_received_before = float(connection.execute(
        "SELECT COALESCE(SUM(received_packages),0) FROM reception_truck_bl_arrivals WHERE shipment_id = ?",
        (int(shipment_id),),
    ).fetchone()[0] or 0)
    legacy_receipt_total = float(connection.execute(
        """SELECT COALESCE(SUM(r.received_packages),0)
             FROM reception_receipts r
             LEFT JOIN reception_truck_bl_arrivals a
               ON a.shipment_id=r.shipment_id
              AND lower(a.truck_guide)=lower(COALESCE(r.truck_guide,''))
            WHERE r.shipment_id=? AND a.id IS NULL""",
        (int(shipment_id),),
    ).fetchone()[0] or 0)
    ledger_gap = max(0.0, float(shipment["received_packages"] or 0) - mapped_received_before)
    if abs(ledger_gap - legacy_receipt_total) > 1e-9:
        raise ValueError(
            "La BL conserva bultos anteriores sin respaldo en el historial de recepciones; revisa el expediente antes de registrar otra llegada"
        )
    # Receipts entered before truck tracking are valid historical arrivals.
    # Keep their quantity in the BL total and subtract it from the remaining
    # balance instead of treating their existence as a duplicate truck entry.
    legacy_unallocated = legacy_receipt_total
    effective_previous_received = previous_received + legacy_unallocated
    reason = str(excess_reason or "").strip()
    if amount > float(plan["planned_packages"] or 0) and not reason:
        raise ValueError("La cantidad recibida supera lo programado para este camión; ingresa una justificación")
    if expected > 0 and effective_previous_received + amount > expected and not reason:
        raise ValueError("La cantidad recibida supera el saldo esperado de la BL; ingresa una justificación")
    timestamp = reception_now()
    if revising_existing:
        arrival_id = int(existing["id"])
        connection.execute(
            """UPDATE reception_truck_bl_arrivals
                  SET received_packages = ?, arrival_key = ?, excess_reason = ?, notes = ?, username = ?
                WHERE id = ?""",
            (amount, key, reason, str(notes or "").strip(), username, arrival_id),
        )
        previous_locations = connection.execute(
            "SELECT location_text, package_count FROM reception_truck_bl_locations WHERE arrival_id = ? ORDER BY id",
            (arrival_id,),
        ).fetchall()
        connection.execute("DELETE FROM reception_truck_bl_locations WHERE arrival_id = ?", (arrival_id,))
        if previous_locations:
            _write_history(
                connection, int(shipment_id), "RETROCESO CAMION", f"guia:{guide}:ubicaciones_temporales",
                json.dumps([dict(row) for row in previous_locations], ensure_ascii=False), "[]", username,
                "Se limpiaron las ubicaciones temporales para repetir el paso 2",
            )
        _write_history(
            connection, int(shipment_id), "CORRECCION ARRIBO CAMION",
            f"guia:{guide}:bultos_recibidos", existing["received_packages"], amount, username,
            reason or str(notes or "Corrección tras reapertura administrativa"),
        )
    else:
        cursor = connection.execute(
            """INSERT INTO reception_truck_bl_arrivals
               (truck_guide, shipment_id, received_packages, arrival_key, excess_reason, notes, username, arrived_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (guide, int(shipment_id), amount, key, reason, str(notes or "").strip(), username, timestamp),
        )
        arrival_id = cursor.lastrowid
    receipt = connection.execute(
        "SELECT * FROM reception_receipts WHERE shipment_id = ? AND lower(COALESCE(truck_guide, '')) = lower(?) ORDER BY sequence_no DESC LIMIT 1",
        (int(shipment_id), guide),
    ).fetchone()
    attention = connection.execute(
        "SELECT * FROM reception_attentions WHERE receipt_id = ? LIMIT 1",
        (int(receipt["id"]),),
    ).fetchone() if receipt else None
    active_attention = _active_reception_attention(connection, int(shipment_id))
    revising_attention = bool(
        revising_existing and attention
        and int(active_attention["id"]) == int(attention["id"])
    ) if active_attention else False
    has_previous_open_attention = bool(
        active_attention and active_attention["app_status"] != "CERRADO"
        and not revising_attention
    )
    if amount > 0 and receipt:
        receipt_id = int(receipt["id"])
        connection.execute(
            "UPDATE reception_receipts SET received_packages = ?, notes = ?, username = ? WHERE id = ?",
            (amount, f"{guide}: {str(notes or '').strip()}".strip(), username, receipt_id),
        )
        connection.execute(
            "UPDATE reception_receipts SET location_text = '' WHERE id = ?", (receipt_id,)
        )
        if attention:
            connection.execute(
                """UPDATE reception_attentions
                      SET app_status = 'ARRIBADO', condition_status = 'EN PROCESO',
                          location_text = NULL, system_quantities_initialized = 0,
                          transfer_assistant_checked = 0, completed_at = NULL,
                          updated_at = ? WHERE id = ?""",
                (timestamp, attention["id"]),
            )
            for line in connection.execute(
                "SELECT id, expected_qty FROM reception_lines WHERE shipment_id = ?",
                (int(shipment_id),),
            ).fetchall():
                verified_elsewhere = connection.execute(
                    """SELECT COALESCE(SUM(al.verified_qty), 0)
                         FROM reception_attention_lines al
                         JOIN reception_attentions a ON a.id = al.attention_id
                        WHERE al.reception_line_id = ? AND a.id <> ?""",
                    (line["id"], attention["id"]),
                ).fetchone()[0]
                connection.execute(
                    """INSERT INTO reception_attention_lines
                       (attention_id, reception_line_id, planned_qty, verified_qty)
                       VALUES (?, ?, ?, 0)
                       ON CONFLICT(attention_id, reception_line_id) DO UPDATE SET
                         planned_qty=excluded.planned_qty, verified_qty=0""",
                    (attention["id"], line["id"], max(0.0, float(line["expected_qty"] or 0) - float(verified_elsewhere or 0))),
                )
    elif amount > 0:
        seq = int(connection.execute(
            "SELECT COALESCE(MAX(sequence_no),0)+1 FROM reception_receipts WHERE shipment_id = ?",
            (int(shipment_id),),
        ).fetchone()[0])
        receipt_cursor = connection.execute(
            """INSERT INTO reception_receipts
               (shipment_id, sequence_no, received_packages, notes, location_text, username, received_at, truck_guide)
               VALUES (?, ?, ?, ?, '', ?, ?, ?)""",
            (int(shipment_id), seq, amount, f"{guide}: {str(notes or '').strip()}".strip(), username, timestamp, guide),
        )
        _create_reception_attention(connection, shipment, receipt_cursor.lastrowid, username, "ARRIBADO")
        # Each receipt gets its own attention immediately, so arrivals can be
        # worked independently and in any order.
    elif amount > 0 and not attention:
        # Repair receipts queued by an older version without a matching task.
        _create_reception_attention(connection, shipment, receipt["id"], username, "ARRIBADO")
    elif receipt:
        connection.execute(
            "UPDATE reception_receipts SET received_packages = 0, location_text = '', username = ? WHERE id = ?",
            (username, receipt["id"]),
        )
        if attention:
            connection.execute(
                """UPDATE reception_attentions
                      SET app_status = 'CERRADO', condition_status = 'ANULADA POR CORRECCION DE ARRIBO',
                          location_text = NULL, system_quantities_initialized = 0,
                          transfer_assistant_checked = 0, completed_at = ?, updated_at = ?
                    WHERE id = ?""",
                (timestamp, timestamp, attention["id"]),
            )
            connection.execute(
                "UPDATE reception_attention_lines SET planned_qty = 0, verified_qty = 0 WHERE attention_id = ?",
                (attention["id"],),
            )
    _sync_reception_line_totals(connection, int(shipment_id))
    new_received = effective_previous_received + amount
    condition = "ARRIBO REGISTRADO" if expected <= 0 else (
        "EXCEDENTE POR VALIDAR" if new_received > expected else
        "ARRIBO COMPLETO" if new_received == expected else "SALDO POR ARRIBAR"
    )
    queued_behind_open_attention = amount > 0 and has_previous_open_attention
    connection.execute(
        """UPDATE reception_shipments
              SET received_packages = ?,
                  app_status = CASE WHEN ? > 0 THEN 'ARRIBADO' ELSE 'PROGRAMADO' END,
                  condition_status = CASE WHEN ? = 1 OR (? = 0 AND ? = 1) THEN condition_status ELSE ? END,
                  first_arrival_at = CASE WHEN ? > 0 THEN COALESCE(first_arrival_at, ?) ELSE first_arrival_at END,
                  updated_at = ?
            WHERE id = ?""",
        (new_received, amount,
         int(queued_behind_open_attention), amount, int(has_previous_open_attention), condition,
         amount, timestamp, timestamp, int(shipment_id)),
    )
    _write_history(
        connection, int(shipment_id), "ARRIBO CAMION", f"guia:{guide}:bultos_recibidos",
        previous_received, new_received, username, reason or str(notes or ""),
    )
    result = connection.execute(
        "SELECT * FROM reception_truck_bl_arrivals WHERE id = ?", (arrival_id,)
    ).fetchone()
    payload = _as_dict(result)
    payload["arrival_id"] = int(arrival_id)
    return payload


def process_truck_guide_arrivals(connection, truck_guide, bls, arrival_key, notes, username, role):
    """Close truck package arrival and move the guide to reception-zone work.

    Locations may still be supplied by older clients, but they are no longer
    required here: package confirmation (step 1) and physical placement (step
    2) are separate operational decisions.
    """
    require_reception_access(role)
    guide = str(truck_guide or "").strip()
    key = str(arrival_key or "").strip()
    if not guide or not key or not isinstance(bls, list) or not bls:
        raise ValueError("La guía, clave y detalle de las BL son obligatorios")
    if role not in {"ADMINISTRADOR", "ASISTENTE_RECEPCION"}:
        raise PermissionError("Solo un administrador o asistente de recepción puede cerrar la llegada del camión")
    _require_confirmed_truck_guide(connection, guide)
    guide_header = _truck_guide_header(connection, guide, create_if_missing=False)
    scanner_enabled = bool(guide_header and int(guide_header["scanner_enabled"] or 0))
    manifest = connection.execute(
        """SELECT m.shipment_id, m.planned_packages, s.expected_packages,
                      s.received_packages, s.app_status,
                      s.current_assistant, s.current_auxiliary,
                      a.id AS arrival_id,
                      (SELECT COUNT(*) FROM reception_truck_package_scans ps
                        WHERE lower(ps.truck_guide)=lower(m.truck_guide)
                          AND ps.shipment_id=m.shipment_id AND ps.scan_status='ACTIVO') AS scanned_packages
             FROM reception_truck_bl_manifest m JOIN reception_shipments s ON s.id=m.shipment_id
             LEFT JOIN reception_truck_bl_arrivals a
               ON a.shipment_id=s.id AND lower(a.truck_guide)=lower(m.truck_guide)
            WHERE lower(m.truck_guide)=lower(?) AND COALESCE(m.operational_active,1)=1""", (guide,)
    ).fetchall()
    if not scanner_enabled and any(
        row["app_status"] != "CERRADO" and float(row["expected_packages"] or 0) <= 0
        for row in manifest
    ):
        raise ValueError(
            "Hay BL con bultos esperados pendientes de confirmar; el administrador debe corregir ese dato antes de registrar la llegada"
        )
    active_ids = {
        int(row["shipment_id"])
        for row in manifest
        if row["app_status"] != "CERRADO"
        and (float(row["planned_packages"] or 0) > 0
             or (scanner_enabled and int(row["scanned_packages"] or 0) > 0))
        and (scanner_enabled or (
            row["arrival_id"] is not None
            or float(row["expected_packages"] or 0) <= 0
            or float(row["received_packages"] or 0) < float(row["expected_packages"] or 0)
        ))
    }
    submitted = {}
    for item in bls:
        try:
            shipment_id = int(item.get("shipment_id"))
        except (AttributeError, TypeError, ValueError):
            raise ValueError("Una BL del manifiesto no es válida")
        if shipment_id in submitted:
            raise ValueError("El manifiesto contiene una BL duplicada")
        submitted[shipment_id] = item
    if set(submitted) != active_ids:
        raise ValueError("Confirma cada BL activa exactamente una vez, incluso las que recibieron 0")
    # Valida el manifiesto completo antes de insertar para que la operación sea atómica.
    for shipment_id in sorted(active_ids):
        item = submitted[shipment_id]
        amount = _truck_package_count(item.get("received_packages"), "Bultos recibidos", allow_zero=True)
        locations = item.get("locations") or []
        if amount == 0 and locations:
            raise ValueError("Una BL con 0 bultos recibidos no debe tener ubicaciones")
        if amount > 0 and locations:
            if not isinstance(locations, list):
                raise ValueError("Las ubicaciones de la BL no son válidas")
            located = 0
            for location in locations:
                if not str(location.get("location") or "").strip():
                    raise ValueError("Indica la ubicación física de cada distribución")
                located += _truck_package_count(location.get("package_count"), "Bultos ubicados")
            if located != amount:
                raise ValueError("Las ubicaciones deben sumar exactamente los bultos recibidos por BL")
        plan = connection.execute(
            "SELECT planned_packages FROM reception_truck_bl_manifest WHERE shipment_id=? AND lower(truck_guide)=lower(?)",
            (shipment_id, guide),
        ).fetchone()
        if amount > float(plan["planned_packages"] or 0) and not str(item.get("excess_reason") or "").strip():
            raise ValueError("Justifica la cantidad que supera lo programado para esta BL")
    for shipment_id in sorted(active_ids):
        item = submitted[shipment_id]
        amount = _truck_package_count(item.get("received_packages"), "Bultos recibidos", allow_zero=True)
        reason = item.get("excess_reason", "")
        if scanner_enabled and amount > 0 and not reason:
            reason = "Diferencia verificada por escaneo físico"
        arrival = confirm_truck_bl_arrival(
            connection, guide, shipment_id, item.get("received_packages"), f"{key}:{shipment_id}",
            username, role, excess_reason=reason, notes=notes,
        )
        for location in item.get("locations") or []:
            assign_truck_bl_arrival_location(
                connection, arrival["arrival_id"], location.get("location"),
                location.get("package_count"), username, role,
            )
    header = _truck_guide_header(connection, guide)
    if TRUCK_GUIDE_STATE_INDEX.get(_truck_guide_status(header), 0) > TRUCK_GUIDE_STATE_INDEX["ZONA_RECEPCION"]:
        # Old aggregate truck steps are not proof that any individual BL was
        # received. New per-BL confirmation restarts only the truck header;
        # its legacy rows remain intact for audit/reconciliation.
        connection.execute(
            "UPDATE reception_truck_guides SET guide_status='ZONA_RECEPCION', count_enabled_at=NULL, count_enabled_by=NULL, updated_at=? WHERE lower(guide_code)=lower(?)",
            (reception_now(), guide),
        )
    else:
        _set_truck_guide_status(connection, guide, "ZONA_RECEPCION", username)
    return truck_guide_summary(connection, guide, username, role)


def process_truck_guide_locations(connection, truck_guide, bls, username, role):
    """Save step-2 locations and close the truck-guide workflow.

    Every BL with received packages must distribute exactly that quantity.
    Zero-received BLs need no location and remain pending for another truck.
    """
    if role not in {"ADMINISTRADOR", "ASISTENTE_RECEPCION", "AUXILIAR_RECEPCION"}:
        raise PermissionError("Tu rol no puede registrar la zona de recepción del camión")
    _require_confirmed_truck_guide(connection, str(truck_guide or "").strip())
    summary = truck_guide_summary(connection, truck_guide, username, role)
    if summary["guide_status"] not in {"ZONA_RECEPCION", "EN_CURSO"}:
        raise ValueError("Confirma primero que no llegarán más bultos en esta guía")
    if not isinstance(bls, list):
        raise ValueError("La distribución por BL es obligatoria")
    submitted = {}
    for item in bls:
        try:
            shipment_id = int(item.get("shipment_id"))
        except (AttributeError, TypeError, ValueError):
            raise ValueError("Una BL de la distribución no es válida")
        if shipment_id in submitted:
            raise ValueError("La distribución contiene una BL duplicada")
        submitted[shipment_id] = item
    received_rows = {
        int(row["id"]): row for row in summary["bls"]
        if str(row.get("app_status") or "").upper() != "CERRADO"
        and float(row.get("received_this_truck") or 0) > 0
    }
    if set(submitted) != set(received_rows):
        raise ValueError("Registra la ubicación de cada BL que recibió bultos")
    validated = {}
    for shipment_id, row in received_rows.items():
        locations = submitted[shipment_id].get("locations") or []
        if not isinstance(locations, list) or not locations:
            raise ValueError(f"Registra al menos una ubicación para {row['bl_awb']}")
        normalized = []
        located = 0
        for location in locations:
            zone = str(location.get("location") or "").strip()
            if not zone:
                raise ValueError(f"Indica la ubicación física de {row['bl_awb']}")
            count = _truck_package_count(location.get("package_count"), "Bultos ubicados")
            located += count
            normalized.append((zone, count))
        received = float(row.get("received_this_truck") or 0)
        if located != received:
            raise ValueError(
                f"Las ubicaciones de {row['bl_awb']} suman {located:g}; deben sumar {received:g}"
            )
        validated[shipment_id] = (int(row["arrival_id"]), normalized)
    for arrival_id, locations in validated.values():
        connection.execute(
            "DELETE FROM reception_truck_bl_locations WHERE arrival_id = ?", (arrival_id,)
        )
        for zone, count in locations:
            assign_truck_bl_arrival_location(
                connection, arrival_id, zone, count, username, role
            )
    # Zona de recepción is the last truck-level task. Completing it closes the
    # guide and exposes each received BL to its own count workflow.
    return enable_truck_guide_counting(
        connection, summary["truck_guide"], username, role
    )


def assign_truck_bl_arrival_location(connection, arrival_id, location, package_count, username, role):
    require_reception_access(role)
    arrival = connection.execute(
        """SELECT a.*, s.current_assistant, s.current_auxiliary
             FROM reception_truck_bl_arrivals a
             JOIN reception_shipments s ON s.id=a.shipment_id WHERE a.id=?""",
        (int(arrival_id),),
    ).fetchone()
    if not arrival:
        raise ValueError("No existe la llegada de BL seleccionada")
    if role not in {"ADMINISTRADOR", "ASISTENTE_RECEPCION", "AUXILIAR_RECEPCION"}:
        raise PermissionError("Tu rol no puede registrar ubicaciones del camión")
    zone = str(location or "").strip()
    count = _truck_package_count(package_count, "Bultos ubicados")
    if not zone:
        raise ValueError("Indica la ubicación física")
    current = connection.execute(
        "SELECT package_count FROM reception_truck_bl_locations WHERE arrival_id=? AND lower(location_text)=lower(?)",
        (int(arrival_id), zone),
    ).fetchone()
    previous_for_zone = float(current["package_count"] or 0) if current else 0.0
    if current and previous_for_zone == float(package_count):
        return {"arrival_id": int(arrival_id), "location": zone, "package_count": previous_for_zone}
    other_locations = float(connection.execute(
        "SELECT COALESCE(SUM(package_count),0) FROM reception_truck_bl_locations WHERE arrival_id=? AND lower(location_text)<>lower(?)",
        (int(arrival_id), zone),
    ).fetchone()[0] or 0)
    if other_locations + count > float(arrival["received_packages"] or 0):
        raise ValueError("Las ubicaciones no pueden sumar más que los bultos recibidos de esta BL en este camión")
    timestamp = reception_now()
    connection.execute(
        """INSERT INTO reception_truck_bl_locations
           (arrival_id, location_text, package_count, username, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(arrival_id, location_text) DO UPDATE SET
             package_count=excluded.package_count, username=excluded.username, updated_at=excluded.updated_at""",
        (int(arrival_id), zone, count, username, timestamp, timestamp),
    )
    connection.execute(
        "UPDATE reception_receipts SET location_text = ? WHERE shipment_id=? AND lower(truck_guide)=lower(?)",
        (zone if other_locations == 0 and count == float(arrival["received_packages"] or 0) else "VARIAS UBICACIONES",
         arrival["shipment_id"], arrival["truck_guide"]),
    )
    _write_history(
        connection, int(arrival["shipment_id"]), "ZONA RECEPCION CAMION",
        f"guia:{arrival['truck_guide']}:llegada:{arrival_id}:ubicacion:{zone}",
        previous_for_zone, count, username,
    )
    return {"arrival_id": int(arrival_id), "location": zone, "package_count": count}


def list_truck_bl_arrival_locations(connection, shipment_id):
    return [
        {"arrival_id": int(row["arrival_id"]), "truck_guide": row["truck_guide"],
         "location": row["location_text"], "location_text": row["location_text"],
         "package_count": float(row["package_count"] or 0)}
        for row in connection.execute(
            """SELECT l.arrival_id, a.truck_guide, l.location_text, l.package_count
                 FROM reception_truck_bl_locations l
                 JOIN reception_truck_bl_arrivals a ON a.id=l.arrival_id
                WHERE a.shipment_id=? ORDER BY a.arrived_at, l.id""",
            (int(shipment_id),),
        ).fetchall()
    ]


def _validation_sample_ids(connection, shipment_id):
    """Return a stable 30% sample of the shipment's NPs.

    The sample is persisted on the shipment so refreshing the page never changes
    what the assistant must validate.
    """
    lines = connection.execute(
        "SELECT id FROM reception_lines WHERE shipment_id = ? ORDER BY id", (shipment_id,)
    ).fetchall()
    line_ids = [int(row["id"]) for row in lines]
    shipment = connection.execute(
        "SELECT validation_sample_json FROM reception_shipments WHERE id = ?", (shipment_id,)
    ).fetchone()
    try:
        stored = [int(value) for value in json.loads(shipment["validation_sample_json"] or "[]")]
    except (TypeError, ValueError, json.JSONDecodeError):
        stored = []
    if stored and set(stored).issubset(set(line_ids)):
        sample = stored
    elif not line_ids:
        return []
    else:
        sample_size = max(1, math.ceil(len(line_ids) * 0.30))
        ranked = sorted(
            line_ids,
            key=lambda line_id: hashlib.sha256(f"{shipment_id}:{line_id}".encode()).hexdigest(),
        )
        sample = ranked[:sample_size]
        connection.execute(
            "UPDATE reception_shipments SET validation_sample_json = ? WHERE id = ?",
            (json.dumps(sample), shipment_id),
        )
    # La validación operativa solo requiere confirmar la ubicación. En una
    # muestra nueva el check parte marcado para que el usuario solo lo quite
    # si detecta una ubicación incorrecta; una decisión ya guardada no se
    # sobreescribe al refrescar la pantalla.
    for line_id in sample:
        saved = connection.execute(
            "SELECT 1 FROM reception_history WHERE shipment_id = ? "
            "AND field_name = ? LIMIT 1",
            (shipment_id, f"linea:{line_id}:muestra"),
        ).fetchone()
        if not saved:
            connection.execute(
                "UPDATE reception_lines SET validation_location_checked = 1 WHERE id = ?",
                (line_id,),
            )
    return sample


def reception_detail(connection, shipment_id, role="ADMINISTRADOR", username="", attention_id=None):
    require_reception_access(role)
    shipment = connection.execute(
        "SELECT * FROM reception_shipments WHERE id = ?", (shipment_id,)
    ).fetchone()
    if not shipment:
        return None
    if role != "ADMINISTRADOR" and username and not _is_assigned_to(shipment, username):
        raise PermissionError("Esta BL/AWB no está asignada a tu usuario")
    payload = _as_dict(shipment)
    payload["truck_plans"] = list_truck_bl_plans(connection, shipment_id)
    payload["truck_arrivals"] = list_truck_bl_arrival_locations(connection, shipment_id)
    guide_header = _truck_guide_header(connection, shipment["truck_guide"], create_if_missing=False) if shipment["truck_guide"] else None
    payload["guide_status"] = _truck_guide_status(guide_header) if guide_header else "PENDIENTE"
    payload["accounting_warning"] = _accounting_warning(payload.get("accounting_status"))
    linked = connection.execute(
        """SELECT GROUP_CONCAT(DISTINCT sap_ov) AS linked_ovs,
                         GROUP_CONCAT(DISTINCT transport_type) AS linked_transport
              FROM order_importation_refs
             WHERE lower(COALESCE(bl_awb, '')) = lower(COALESCE(?, ''))""",
        (shipment["bl_awb"],),
    ).fetchone()
    payload["linked_ovs"] = linked["linked_ovs"] if linked else ""
    payload["linked_transport"] = linked["linked_transport"] if linked else ""
    if payload["linked_transport"] and str(payload.get("transport_type") or "SIN DEFINIR") == "SIN DEFINIR":
        payload["transport_type"] = payload["linked_transport"]
    payload["lines"] = [
        _as_dict(row)
        for row in connection.execute(
            "SELECT * FROM reception_lines WHERE shipment_id = ? ORDER BY id", (shipment_id,)
        ).fetchall()
    ]
    # El packing list muestra una lectura operativa del mismo corte de stock
    # que Despacho: requerido de la BL, compromiso de OVs y saldo disponible.
    # No altera inventario ni asume que una importación sea un ingreso SAP.
    for line in payload["lines"]:
        stock_summary = global_stock_summary(connection, line.get("np_code"), "1")
        line.update(stock_summary)
        if not line.get("default_location"):
            line["default_location"] = stock_summary.get("stock_default_location", "")
    attention_rows = _attention_rows(connection, shipment_id)
    active_attention = _active_reception_attention(connection, shipment_id, attention_id)
    if active_attention:
        # A BL can have concurrent arrival tasks. Render the selected task's
        # stage, without changing the shipment's shared identity/details.
        payload["app_status"] = active_attention["app_status"]
        payload["condition_status"] = active_attention["condition_status"]
        payload["attention_id"] = int(active_attention["id"])
    payload["active_attention_id"] = int(active_attention["id"]) if active_attention else None
    payload["active_attention_sequence"] = (
        int(active_attention["sequence_no"]) if active_attention else None
    )
    receipt_count = connection.execute(
        "SELECT COUNT(*) FROM reception_receipts WHERE shipment_id = ? AND received_packages > 0",
        (shipment_id,),
    ).fetchone()[0]
    payload["attention_count"] = max(len(attention_rows), int(receipt_count or 0))
    payload["attentions"] = []
    for attention in attention_rows:
        attention_payload = _as_dict(attention)
        attention_payload["label"] = f"Atención {attention['sequence_no']}/{payload['attention_count']}"
        attention_payload["lines"] = [
            _as_dict(row)
            for row in connection.execute(
                """SELECT al.*, l.np_code, l.description
                     FROM reception_attention_lines al
                     JOIN reception_lines l ON l.id = al.reception_line_id
                    WHERE al.attention_id = ? ORDER BY l.id""",
                (attention["id"],),
            ).fetchall()
        ]
        payload["attentions"].append(attention_payload)
    if active_attention:
        active_lines = {
            int(row["reception_line_id"]): row
            for row in connection.execute(
                "SELECT * FROM reception_attention_lines WHERE attention_id = ?",
                (active_attention["id"],),
            ).fetchall()
        }
        for line in payload["lines"]:
            attention_line = active_lines.get(int(line["id"]))
            if attention_line:
                line["attention_id"] = int(active_attention["id"])
                line["attention_sequence"] = int(active_attention["sequence_no"])
                line["attention_system_initialized"] = int(
                    active_attention["system_quantities_initialized"] or 0
                )
                line["attention_planned_qty"] = float(attention_line["planned_qty"] or 0)
                line["attention_verified_qty"] = float(attention_line["verified_qty"] or 0)
                line["attention_remaining_qty"] = max(
                    0.0,
                    line["attention_planned_qty"] - line["attention_verified_qty"],
                )
                line["location_attention_required"] = int(
                    float(attention_line["planned_qty"] or 0) > 0
                    or float(attention_line["verified_qty"] or 0) > 0
                )
            else:
                line["attention_system_initialized"] = 1
                line["attention_planned_qty"] = float(line["expected_qty"] or 0)
                line["attention_verified_qty"] = float(line["received_qty"] or 0)
                line["location_attention_required"] = int(
                    float(line["received_qty"] or 0) > 0
                )
    else:
        for line in payload["lines"]:
            line["location_attention_required"] = int(
                float(line["received_qty"] or 0) > 0
            )
    if role == "ADMINISTRADOR" or RECEPTION_STATE_INDEX.get(payload["app_status"], -1) >= RECEPTION_STATE_INDEX["REVISION SISTEMA"]:
        accounting_rows = connection.execute(
            "SELECT * FROM reception_accounting_refs WHERE shipment_id = ? ORDER BY reception_date, source_row, id",
            (shipment_id,),
        ).fetchall()
        accounting_by_ip = _accounting_rows_by_ip(accounting_rows)
        for line in payload["lines"]:
            line_ips = set(_ip_tokens(line.get("ip_reference")))
            matching_refs = [
                row for row in accounting_rows
                if line_ips.intersection(_ip_tokens(row["ip_reference"]))
            ]
            line["fr_number"] = _joined_accounting_values(matching_refs, "fr_number") if matching_refs else ""
            line["em_number"] = ", ".join(
                value for ref in matching_refs for value in [_accounting_em_summary(connection, ref)] if value
            ) if matching_refs else ""
            line["accounting_locked"] = int(
                _line_has_complete_accounting(line, accounting_by_ip, connection, shipment_id)
            )
            line["accounting_lock_reason"] = (
                "FR y EM registrados para el IP; línea no requiere atención"
                if line["accounting_locked"] else ""
            )
    payload["receipts"] = [
        _as_dict(row)
        for row in connection.execute(
            """SELECT r.*, a.sequence_no AS attention_sequence
                 FROM reception_receipts r
                 LEFT JOIN reception_attentions a ON a.receipt_id = r.id
                WHERE r.shipment_id = ? ORDER BY r.sequence_no""", (shipment_id,)
        ).fetchall()
    ]
    payload["validation_sample_ids"] = _validation_sample_ids(connection, shipment_id)
    payload["lots"] = lots_for_shipment(connection, shipment_id)
    if role == "ADMINISTRADOR" or RECEPTION_STATE_INDEX.get(payload["app_status"], -1) >= RECEPTION_STATE_INDEX["REVISION SISTEMA"]:
        raw_accounting_refs = [
            _as_dict(row)
            for row in connection.execute(
                """SELECT * FROM reception_accounting_refs
                   WHERE shipment_id = ? ORDER BY reception_date, source_row, id""",
                (shipment_id,),
            ).fetchall()
        ]
        accounting_refs = []
        for raw_reference in raw_accounting_refs:
            reference_ips = _ip_display_tokens(raw_reference.get("ip_reference")) or [("", "")]
            for ip_key, ip_display in reference_ips:
                reference = dict(raw_reference)
                reference["ip_reference_key"] = ip_key
                reference["ip_reference"] = ip_display or raw_reference.get("ip_reference") or ""
                reference["source_em_number"] = raw_reference.get("em_number") or ""
                ref_ips = {ip_key} if ip_key else set()
                linked_lines = []
                for line in payload["lines"]:
                    if ref_ips and not ref_ips.intersection(_ip_tokens(line.get("ip_reference"))):
                        continue
                    entered_qty = float(line.get("attention_verified_qty", line.get("received_qty") or 0) or 0)
                    expected_qty = float(line.get("attention_planned_qty", line.get("expected_qty") or 0) or 0)
                    linked_lines.append({
                        "np_code": line.get("np_code") or "",
                        "description": line.get("description") or "",
                        "ov_number": line.get("ov_number") or "",
                        "expected_qty": expected_qty,
                        "received_qty": entered_qty,
                        "pending_qty": max(0.0, expected_qty - entered_qty),
                    })
                reference["linked_lines"] = linked_lines
                reference["em_numbers"] = _accounting_em_values(connection, reference["id"], ip_key)
                reference["em_entries"] = _accounting_em_entries(connection, reference["id"], ip_key)
                reference["em_eligible"] = int(
                    any(item["received_qty"] > 0 for item in linked_lines)
                    or bool(reference["em_numbers"] and linked_lines)
                )
                required_ems = _accounting_required_attention_count(connection, shipment_id, reference, ip_key)
                reference["required_em_count"] = required_ems
                reference["pending_em_count"] = max(0, required_ems - len(reference["em_numbers"]))
                if not reference["em_eligible"]:
                    reference["em_status"] = "PENDIENTE DE ESTA LLEGADA"
                elif not str(reference.get("fr_number") or "").strip():
                    reference["em_status"] = "PENDIENTE FR"
                elif reference["pending_em_count"]:
                    reference["em_status"] = f"EM {len(reference['em_numbers'])}/{required_ems}"
                else:
                    reference["em_status"] = "EM COMPLETAS"
                accounting_refs.append(reference)
        payload["accounting_refs"] = accounting_refs
    return payload


def _elapsed_hours_excluding_sundays(start_value, end_value=None):
    """Cuenta horas transcurridas sin incluir ningún tramo del domingo."""
    start = _history_datetime(start_value)
    end = _history_datetime(end_value) if end_value else _history_datetime(reception_now())
    if start is None or end is None or end <= start:
        return None if start is None or end is None else 0.0

    elapsed_seconds = 0.0
    cursor = start
    while cursor < end:
        next_midnight = cursor.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        segment_end = min(end, next_midnight)
        if cursor.weekday() != 6:
            elapsed_seconds += (segment_end - cursor).total_seconds()
        cursor = segment_end
    return elapsed_seconds / 3600


def reception_report(connection, role="ADMINISTRADOR"):
    require_reception_access(role)
    if role != "ADMINISTRADOR":
        raise PermissionError("La reportería de Recepción es solo para el administrador")
    rows = connection.execute(
        """SELECT s.*,
                  (SELECT COUNT(DISTINCT NULLIF(TRIM(l.np_code), ''))
                     FROM reception_lines l WHERE l.shipment_id = s.id) AS sku_count,
                  (SELECT COALESCE(SUM(l.expected_qty), 0)
                     FROM reception_lines l WHERE l.shipment_id = s.id) AS total_units,
                  (SELECT COUNT(*) FROM reception_receipts r WHERE r.shipment_id = s.id) AS receipt_count,
                  (SELECT GROUP_CONCAT(NULLIF(TRIM(r.notes), ''), ' · ')
                     FROM reception_receipts r WHERE r.shipment_id = s.id) AS guide_remission,
                  (SELECT GROUP_CONCAT(DISTINCT m.truck_guide)
                     FROM reception_truck_bl_manifest m WHERE m.shipment_id = s.id) AS truck_guides,
                  (SELECT MIN(a.arrived_at) FROM reception_truck_bl_arrivals a
                    WHERE a.shipment_id = s.id) AS truck_started_at,
                  (SELECT MAX(h.created_at) FROM reception_history h
                    WHERE h.shipment_id = s.id AND h.field_name = 'app_status'
                      AND h.new_value = 'CERRADO') AS closed_at,
                  (SELECT MAX(a.completed_at) FROM reception_attentions a
                    WHERE a.shipment_id = s.id AND a.app_status = 'CERRADO') AS attention_completed_at
           FROM reception_shipments s
           ORDER BY CASE WHEN COALESCE(s.scheduled_date, '') = '' THEN 1 ELSE 0 END,
                    s.scheduled_date ASC, s.updated_at DESC"""
    ).fetchall()
    items = []
    by_status = {}
    by_transport = {}
    semaphore_counts = {"VERDE": 0, "AMARILLO": 0, "ROJO": 0}
    for row in rows:
        item = _as_dict(row)
        transport = str(item.get("transport_type") or "SIN DEFINIR")
        sla_hours = 96 if transport == "MARITIMO" else 72
        started_at = item.get("truck_started_at") or item.get("first_arrival_at")
        closed_at = item.get("closed_at") or item.get("attention_completed_at")
        if item.get("app_status") == "CERRADO" and not closed_at:
            closed_at = item.get("updated_at")
        elapsed = _elapsed_hours_excluding_sundays(started_at, closed_at)
        if elapsed is None:
            sla_status = "AMARILLO"
            remaining = None
        else:
            remaining = round(sla_hours - elapsed, 1)
            if remaining < 0:
                sla_status = "ROJO"
            elif remaining <= 12:
                sla_status = "AMARILLO"
            else:
                sla_status = "VERDE"
        semaphore_counts[sla_status] += 1
        item["sla_hours"] = sla_hours
        item["elapsed_hours"] = round(elapsed, 2) if elapsed is not None else None
        item["remaining_hours"] = round(remaining, 2) if remaining is not None else None
        item["sla_status"] = sla_status
        item["report_started_at"] = started_at
        item["report_closed_at"] = closed_at if item.get("app_status") == "CERRADO" else None
        item["truck_guides"] = item.get("truck_guides") or item.get("truck_guide") or ""
        item["work_bucket"] = (
            "CONTROL ADMINISTRATIVO"
            if item.get("accounting_status") in {"PENDIENTE CONTABILIDAD", "PENDIENTE FR", "CONFLICTO IP"}
            else "TRABAJO RECEPCIÓN"
        )
        receipt_count = int(item.get("receipt_count") or 0)
        item["attention_progress"] = f"{receipt_count}/{receipt_count}" if receipt_count else "—"
        items.append(item)
        by_status[item["app_status"]] = by_status.get(item["app_status"], 0) + 1
        by_transport[transport] = by_transport.get(transport, 0) + 1
    return {
        "generated_at": reception_now(),
        "summary": {
            "total_pendientes": sum(item.get("app_status") != "CERRADO" for item in items),
            "total_bl": len(items),
            "semaforizacion": semaphore_counts,
        },
        "by_status": by_status,
        "by_transport": by_transport,
        "items": items,
    }


def reception_operational_report_bytes(connection, shipment_id, role="ADMINISTRADOR", username=""):
    """Export the system review and final controls for one BL/AWB."""
    shipment = _get_reception_shipment(connection, shipment_id, username, role)
    lines = connection.execute(
        "SELECT * FROM reception_lines WHERE shipment_id = ? ORDER BY id", (shipment_id,)
    ).fetchall()
    refs = connection.execute(
        "SELECT * FROM reception_accounting_refs WHERE shipment_id = ? ORDER BY id", (shipment_id,)
    ).fetchall()
    refs_by_ip = {}
    for ref in refs:
        for ip in _ip_tokens(ref["ip_reference"]):
            refs_by_ip.setdefault(ip, []).append(ref)
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Resumen"
    summary.append(["TRITON WMS · Reporte operativo de recepción"])
    summary.append(["BL / AWB", shipment["bl_awb"]])
    summary.append(["Estado", shipment["app_status"]])
    summary.append(["Bultos", f"{shipment['received_packages']} / {shipment['expected_packages']}"])
    summary.append(["Ubicación", shipment["location_text"] or ""])
    summary.append(["Generado", reception_now()])
    summary.append([])
    summary.append(["El reporte consolida el control de sistema, diferencias, observaciones y referencias contables."])
    lines_sheet = workbook.create_sheet("Packing List SAP")
    lines_sheet.append([
        "IP", "NP", "Descripción", "OC", "OV", "Esperado", "Verificado",
        "Diferencia", "Resultado", "Observación", "Comentario validación", "FR", "EM",
    ])
    for line in lines:
        expected = float(line["expected_qty"] or 0)
        verified = float(line["received_qty"] or 0)
        line_refs = []
        for ip in _ip_tokens(line["ip_reference"]):
            line_refs.extend(refs_by_ip.get(ip, []))
        unique_refs = {int(ref["id"]): ref for ref in line_refs}
        fr_values = ", ".join(sorted({str(ref["fr_number"] or "") for ref in unique_refs.values() if ref["fr_number"]}))
        em_values = ", ".join(sorted({str(ref["em_number"] or "") for ref in unique_refs.values() if ref["em_number"]}))
        difference = verified - expected
        result_label = "EXCEDENTE" if difference > 0 else "FALTANTE" if difference < 0 else "CONFORME"
        lines_sheet.append([
            line["ip_reference"] or "", line["np_code"] or "", line["description"] or "",
            line["oc_number"] or "", line["ov_number"] or "", expected, verified,
            difference, result_label, line["blocked_reason"] or "",
            line["validation_comment"] or "", fr_values, em_values,
        ])
    refs_sheet = workbook.create_sheet("FR EM")
    refs_sheet.append(["IP", "AWB", "Factura reserva", "EM", "Fecha recepción", "Fecha EM", "Estado"])
    for ref in refs:
        refs_sheet.append([
            ref["ip_reference"] or "", ref["awb_reference"] or "", ref["fr_number"] or "",
            ref["em_number"] or "", ref["reception_date"] or "", ref["em_date"] or "",
            ref["import_status"] or "",
        ])
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.sheet_view.showGridLines = False
        for cell in sheet[1]:
            cell.fill = PatternFill("solid", fgColor="3E4A52")
            cell.font = Font(name="Arial", bold=True, color="FFFFFF")
        for column in sheet.columns:
            values = list(column)
            width = min(48, max(12, max(len(str(cell.value or "")) for cell in values[:100]) + 2))
            sheet.column_dimensions[values[0].column_letter].width = width
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _history_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError):
        return None


def _format_elapsed_hm(hours):
    """Convierte horas decimales a una duración acumulada HH:MM."""
    if hours is None:
        return ""
    total_minutes = max(0, int(round(float(hours) * 60)))
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def reception_history_report(connection, role="ADMINISTRADOR", preview_limit=200):
    """Builds operational timing data only when the administrator requests it."""
    require_reception_access(role)
    if role != "ADMINISTRADOR":
        raise PermissionError("El historial de Recepción es solo para el administrador")
    shipments = connection.execute(
        "SELECT * FROM reception_shipments ORDER BY created_at DESC, id DESC"
    ).fetchall()
    history_rows = connection.execute(
        """SELECT h.*, s.bl_awb, s.transport_type, s.current_assistant,
                         s.current_auxiliary, s.app_status AS current_app_status,
                         s.first_arrival_at
             FROM reception_history h
             JOIN reception_shipments s ON s.id = h.shipment_id
            ORDER BY h.shipment_id, h.id"""
    ).fetchall()
    by_shipment = {}
    for row in history_rows:
        by_shipment.setdefault(row["shipment_id"], []).append(row)

    timing_rows = []
    event_rows = []
    stage_names = list(RECEPTION_STATES)
    total_work_hours = 0.0
    by_user = {}
    by_event = {}
    now_value = reception_now()
    now_dt = _history_datetime(now_value) or datetime.now()

    for shipment in shipments:
        events = by_shipment.get(shipment["id"], [])
        stage_started = _history_datetime(shipment["created_at"])
        if stage_started is None:
            stage_started = now_dt
        current_stage = "PROGRAMADO"
        durations = {stage: 0.0 for stage in stage_names}
        previous_event_dt = None
        arrival_dt = _history_datetime(shipment["first_arrival_at"])

        for event in events:
            event_dt = _history_datetime(event["created_at"])
            if event_dt is None:
                continue
            stage_before = current_stage
            stage_closed_hours = None
            if event["field_name"] == "app_status" and event["new_value"]:
                stage_closed_hours = max(0.0, (event_dt - stage_started).total_seconds() / 3600)
                durations[current_stage] = durations.get(current_stage, 0.0) + stage_closed_hours
                current_stage = str(event["new_value"])
                stage_started = event_dt
            since_previous_minutes = (
                max(0.0, (event_dt - previous_event_dt).total_seconds() / 60)
                if previous_event_dt else None
            )
            since_arrival_hours = (
                max(0.0, (event_dt - arrival_dt).total_seconds() / 3600)
                if arrival_dt else None
            )
            event_rows.append({
                "shipment_id": shipment["id"],
                "bl_awb": event["bl_awb"],
                "transport_type": event["transport_type"],
                "event_type": event["event_type"],
                "field_name": event["field_name"],
                "old_value": event["old_value"] or "",
                "new_value": event["new_value"] or "",
                "stage_before": stage_before,
                "stage_after": current_stage,
                "stage_duration_hours": round(stage_closed_hours, 2) if stage_closed_hours is not None else "",
                "minutes_since_previous_event": round(since_previous_minutes, 2) if since_previous_minutes is not None else "",
                "hours_since_first_arrival": round(since_arrival_hours, 2) if since_arrival_hours is not None else "",
                "username": event["username"],
                "reason": event["reason"] or "",
                "created_at": event["created_at"],
            })
            previous_event_dt = event_dt
            by_user[event["username"] or "Sin usuario"] = by_user.get(event["username"] or "Sin usuario", 0) + 1
            by_event[event["event_type"] or "SIN EVENTO"] = by_event.get(event["event_type"] or "SIN EVENTO", 0) + 1

        current_stage = shipment["app_status"] or current_stage
        current_duration = max(0.0, (now_dt - stage_started).total_seconds() / 3600)
        durations[current_stage] = durations.get(current_stage, 0.0) + current_duration
        total_elapsed = sum(durations.values())
        total_work_hours += total_elapsed
        timing = {
            "shipment_id": shipment["id"],
            "bl_awb": shipment["bl_awb"],
            "transport_type": shipment["transport_type"],
            "current_status": shipment["app_status"],
            "assistant": shipment["current_assistant"] or "",
            "auxiliary": shipment["current_auxiliary"] or "",
            "created_at": shipment["created_at"],
            "first_arrival_at": shipment["first_arrival_at"] or "",
            "total_elapsed_hours": round(total_elapsed, 2),
            "total_elapsed_hm": _format_elapsed_hm(total_elapsed),
            "events_count": len(events),
        }
        for stage in stage_names:
            stage_key = stage.lower().replace(" ", "_")
            timing[f"hours_{stage_key}"] = round(durations.get(stage, 0.0), 2)
            timing[f"duration_{stage_key}_hm"] = _format_elapsed_hm(durations.get(stage, 0.0))
        timing_rows.append(timing)

    event_rows.sort(key=lambda row: (row["created_at"], row["shipment_id"]), reverse=True)
    timing_rows.sort(key=lambda row: (row["created_at"], row["shipment_id"]), reverse=True)
    if preview_limit is None:
        preview_events = event_rows
    else:
        preview_events = event_rows[:max(1, min(int(preview_limit), 500))]
    return {
        "generated_at": now_value,
        "summary": {
            "shipments": len(timing_rows),
            "events": len(event_rows),
            "total_elapsed_hours": round(total_work_hours, 2),
            "users": len(by_user),
        },
        "by_user": dict(sorted(by_user.items(), key=lambda item: (-item[1], item[0]))),
        "by_event": dict(sorted(by_event.items(), key=lambda item: (-item[1], item[0]))),
        "timings": timing_rows,
        "events": preview_events,
    }


def reception_history_export_bytes(connection, role="ADMINISTRADOR"):
    """Exports the complete audit and timing history in a readable workbook."""
    report = reception_history_report(connection, role, preview_limit=500)
    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = "Resumen"
    timings_sheet = workbook.create_sheet("Tiempos por BL")
    events_sheet = workbook.create_sheet("Eventos auditoria")
    sheets = [summary_sheet, timings_sheet, events_sheet]
    header_fill = PatternFill("solid", fgColor="3E4A52")
    header_font = Font(name="Arial", bold=True, color="FFFFFF")
    body_font = Font(name="Arial", size=10, color="343A40")

    summary_sheet.append(["TRITON WMS · Historial de Recepción"])
    summary_sheet.append(["Generado", report["generated_at"]])
    summary_sheet.append(["Expedientes BL/AWB", report["summary"]["shipments"]])
    summary_sheet.append(["Eventos de auditoría", report["summary"]["events"]])
    summary_sheet.append(["Horas acumuladas de seguimiento", report["summary"]["total_elapsed_hours"]])
    summary_sheet.append([])
    summary_sheet.append(["Eventos por usuario"])
    summary_sheet.append(["Usuario", "Eventos"])
    for username, count in report["by_user"].items():
        summary_sheet.append([username, count])
    summary_sheet.append([])
    summary_sheet.append(["Eventos por tipo"])
    summary_sheet.append(["Tipo", "Eventos"])
    for event_type, count in report["by_event"].items():
        summary_sheet.append([event_type, count])

    stage_headers = [
        "shipment_id", "bl_awb", "transport_type", "current_status", "assistant", "auxiliary",
        "created_at", "first_arrival_at", "total_elapsed_hours", "total_elapsed_hm", "events_count",
    ] + [
        header
        for stage in RECEPTION_STATES
        for header in (
            f"hours_{stage.lower().replace(' ', '_')}",
            f"duration_{stage.lower().replace(' ', '_')}_hm",
        )
    ]
    timings_sheet.append(stage_headers)
    for row in report["timings"]:
        timings_sheet.append([row.get(header, "") for header in stage_headers])

    event_headers = [
        "shipment_id", "bl_awb", "transport_type", "event_type", "field_name", "old_value",
        "new_value", "stage_before", "stage_after", "stage_duration_hours",
        "minutes_since_previous_event", "hours_since_first_arrival", "username", "reason", "created_at",
    ]
    events_sheet.append(event_headers)
    # The UI preview is capped, but the export always reads the complete event set.
    full_report = reception_history_report(connection, role, preview_limit=None)
    for row in full_report["events"]:
        events_sheet.append([row.get(header, "") for header in event_headers])

    for sheet in sheets:
        sheet.sheet_view.showGridLines = False
        sheet.freeze_panes = "A2"
        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.font = body_font
                cell.alignment = Alignment(vertical="top", wrap_text=False)
        sheet.auto_filter.ref = sheet.dimensions
        for column_cells in sheet.columns:
            column_letter = column_cells[0].column_letter
            max_length = min(42, max(len(str(cell.value or "")) for cell in column_cells) + 2)
            sheet.column_dimensions[column_letter].width = max(12, max_length)
    summary_sheet.freeze_panes = "A8"
    for sheet in (timings_sheet, events_sheet):
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value, (int, float)) and "hours" in str(sheet.cell(1, cell.column).value):
                    cell.number_format = "0.00"
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def create_reception(connection, data, username, role):
    require_reception_access(role)
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede crear o importar una BL")
    bl_awb = str(data.get("bl_awb") or "").strip()
    if not bl_awb:
        raise ValueError("La BL/AWB es obligatoria")
    transport_type = str(data.get("transport_type") or "AEREO").strip().upper()
    if transport_type not in {"AEREO", "MARITIMO", "COURIER"}:
        raise ValueError("El transporte debe ser AEREO, MARITIMO o COURIER")
    expected_packages = 0
    current_assistant = str(data.get("current_assistant") or "").strip()
    current_auxiliary = str(data.get("current_auxiliary") or "").strip()
    timestamp = reception_now()
    cursor = connection.execute(
        """INSERT INTO reception_shipments
           (bl_awb, transport_type, supplier, ip_reference, primary_oc, primary_ov,
            expected_packages, current_assistant, current_auxiliary, scheduled_date,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            bl_awb,
            transport_type,
            str(data.get("supplier") or "").strip(),
            str(data.get("ip_reference") or "").strip(),
            str(data.get("primary_oc") or "").strip(),
            str(data.get("primary_ov") or "").strip(),
            expected_packages,
            current_assistant,
            current_auxiliary,
            str(data.get("scheduled_date") or "").strip(),
            timestamp,
            timestamp,
        ),
    )
    shipment_id = cursor.lastrowid
    _write_history(connection, shipment_id, "CREACION", "bl_awb", "", bl_awb, username)
    _ensure_default_reception_assignees(
        connection,
        shipment_id,
        username,
        "Creación de expediente: responsables predeterminados",
    )
    return reception_detail(connection, shipment_id, role, username)


def _normalize_header(value):
    value = unicodedata.normalize("NFKD", str(value or "").strip().upper())
    value = "".join(character for character in value if not unicodedata.combining(character))
    return " ".join(value.replace("\n", " ").split())


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _number(value):
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    normalized = str(value).strip().replace(" ", "").replace(",", "")
    try:
        return float(normalized)
    except ValueError:
        return 0.0


def _find_column(headers, *aliases):
    for alias in aliases:
        normalized = _normalize_header(alias)
        if normalized in headers:
            return headers.index(normalized)
    return None


def _row_value(row, index):
    return row[index] if index is not None and index < len(row) else None


def _transport_type(value):
    normalized = _normalize_header(value)
    if "MARIT" in normalized:
        return "MARITIMO"
    if "AERE" in normalized:
        return "AEREO"
    if "COURIER" in normalized:
        return "COURIER"
    return normalized or "SIN DEFINIR"


def _unique_summary(records, field, limit=12):
    values = []
    seen = set()
    for record in records:
        value = str(record.get(field) or "").strip()
        if not value or value.upper() in {"S/N", "SIN NUMERO", "NONE"} or value in seen:
            continue
        seen.add(value)
        values.append(value)
    if len(values) > limit:
        return ", ".join(values[:limit]) + f" (+{len(values) - limit})"
    return ", ".join(values)


def _read_reception_workbook(workbook):
    grouped = {}
    valid_sheets = []
    skipped_rows = 0
    for worksheet in workbook.worksheets:
        header_row = None
        indexes = None
        for row_number, row in enumerate(
            worksheet.iter_rows(min_row=1, max_row=min(worksheet.max_row, 20), values_only=True), 1
        ):
            headers = [_normalize_header(value) for value in row]
            guide_index = _find_column(headers, "GUIA DE IMPORTACION")
            code_index = _find_column(headers, "CODIGO")
            if guide_index is None or code_index is None:
                continue
            header_row = row_number
            indexes = {
                "guide": guide_index,
                "code": code_index,
                "description": _find_column(headers, "DESCRIPCION"),
                "ov": _find_column(headers, "OV", "ORDEN DE VENTA"),
                "oc": _find_column(headers, "ORDEN DE COMPRA"),
                "requested": _find_column(headers, "CANTIDAD SOLICITADA"),
                "invoiced": _find_column(headers, "CANTIDAD FACTURADA"),
                "pending": _find_column(headers, "CANTIDAD PENDIENTE"),
                "purchase_type": _find_column(headers, "TIPO DE COMPRA"),
                "brand": _find_column(headers, "MARCA"),
                "applicant": _find_column(headers, "SOLICITANTE"),
                "ip": _find_column(headers, "PEDIDO TRITON"),
                "status": _find_column(headers, "STATUS"),
                "status_by_np": _find_column(headers, "ESTADO POR NP"),
                "invoice": _find_column(headers, "N° FACTURA", "Nº FACTURA", "N FACTURA"),
                "transport": _find_column(headers, "MODO DE TRANSPORTE"),
                "country": _find_column(headers, "PAIS DE ORIGEN"),
                "default_location": _find_column(
                    headers, "UBICACION", "UBICACIÓN", "UBICACION POR DEFECTO",
                    "UBICACIÓN POR DEFECTO", "UBICACION SUGERIDA", "UBICACIÓN SUGERIDA",
                ),
                "confirmed_date": _find_column(headers, "FECHA CONFIRMADA TRITON"),
                "estimated_date": _find_column(headers, "FECHA TRITON ESTIMADA"),
            }
            break
        if header_row is None:
            continue
        valid_sheets.append(worksheet.title)
        duplicate_counter = {}
        for row_number, row in enumerate(
            worksheet.iter_rows(min_row=header_row + 1, values_only=True), header_row + 1
        ):
            guide = _cell_text(_row_value(row, indexes["guide"]))
            np_code = _cell_text(_row_value(row, indexes["code"]))
            if not guide or not np_code:
                skipped_rows += 1
                continue
            requested = _number(_row_value(row, indexes["requested"]))
            invoiced = _number(_row_value(row, indexes["invoiced"]))
            pending = _number(_row_value(row, indexes["pending"]))
            record = {
                "guide": guide,
                "source_sheet": worksheet.title,
                "source_row": row_number,
                "np_code": np_code,
                "description": _cell_text(_row_value(row, indexes["description"])),
                "ov": _cell_text(_row_value(row, indexes["ov"])),
                "oc": _cell_text(_row_value(row, indexes["oc"])),
                "requested_qty": requested,
                "invoiced_qty": invoiced,
                "pending_qty": pending,
                "expected_qty": invoiced if invoiced > 0 else requested,
                "purchase_type": _cell_text(_row_value(row, indexes["purchase_type"])),
                "brand": _cell_text(_row_value(row, indexes["brand"])),
                "applicant": _cell_text(_row_value(row, indexes["applicant"])),
                "ip": _cell_text(_row_value(row, indexes["ip"])),
                "source_status": _cell_text(_row_value(row, indexes["status"])),
                "status_by_np": _cell_text(_row_value(row, indexes["status_by_np"])),
                "source_invoice": _cell_text(_row_value(row, indexes["invoice"])),
                "transport_type": _transport_type(_row_value(row, indexes["transport"])),
                "country": _cell_text(_row_value(row, indexes["country"])),
                "default_location": _cell_text(_row_value(row, indexes["default_location"])),
                "confirmed_date": _cell_text(_row_value(row, indexes["confirmed_date"])),
                "estimated_date": _cell_text(_row_value(row, indexes["estimated_date"])),
            }
            record["scheduled_date"] = record["confirmed_date"] or record["estimated_date"]
            identity = "|".join(
                (
                    worksheet.title,
                    guide,
                    record["ip"],
                    record["oc"],
                    record["ov"],
                    np_code,
                )
            )
            duplicate_counter[identity] = duplicate_counter.get(identity, 0) + 1
            record["source_key"] = hashlib.sha256(
                f"{identity}|{duplicate_counter[identity]}".encode("utf-8")
            ).hexdigest()
            grouped.setdefault(guide, []).append(record)
    if not valid_sheets:
        raise ValueError(
            "No encontré hojas con las columnas GUIA DE IMPORTACION y CODIGO en las primeras 20 filas"
        )
    return grouped, valid_sheets, skipped_rows


def _source_confirms_arrival(records):
    """Return whether the import source confirms physical arrival.

    A confirmed date is deliberately required; an estimated date must not move
    a BL from PROGRAMADO. The source used by Importaciones marks each line as
    DISPONIBLE and COMPLETE when the received import is ready for operation.
    A BL is considered arrived only when every imported line has no pending
    quantity and carries one of those source completion states.
    """
    if not records or not all(record.get("confirmed_date") for record in records):
        return False
    valid_statuses = {"DISPONIBLE", "COMPLETO", "COMPLETADO"}
    for record in records:
        source_status = _normalized_identifier(record.get("source_status"))
        line_status = _normalized_identifier(record.get("status_by_np"))
        if float(record.get("pending_qty") or 0) > 0:
            return False
        if source_status not in valid_statuses and line_status not in valid_statuses:
            return False
    return True


def import_reception_workbook(connection, workbook, filename, username, role):
    require_reception_access(role)
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede cargar el Excel de Recepción")
    grouped, valid_sheets, skipped_rows = _read_reception_workbook(workbook)
    timestamp = reception_now()
    shipments_created = 0
    shipments_updated = 0
    lines_created = 0
    lines_updated = 0
    for guide, records in grouped.items():
        transport = _unique_summary(records, "transport_type", 2) or "SIN DEFINIR"
        brands = _unique_summary(records, "brand", 5)
        country = _unique_summary(records, "country", 3)
        source_sheets = _unique_summary(records, "source_sheet", 12)
        ip_reference = _unique_summary(records, "ip", 12)
        primary_oc = _unique_summary(records, "oc", 12)
        primary_ov = _unique_summary(records, "ov", 12)
        scheduled_date = next((record["scheduled_date"] for record in records if record["scheduled_date"]), "")
        shipment = connection.execute(
            "SELECT * FROM reception_shipments WHERE bl_awb = ?", (guide,)
        ).fetchone()
        if shipment:
            shipment_id = shipment["id"]
            connection.execute(
                """UPDATE reception_shipments
                   SET transport_type = ?, brand_summary = ?, country_origin = ?, source_sheets = ?,
                       ip_reference = ?, primary_oc = ?, primary_ov = ?,
                       scheduled_date = CASE WHEN ? <> '' THEN ? ELSE scheduled_date END,
                       updated_at = ?
                   WHERE id = ?""",
                (
                    transport,
                    brands,
                    country,
                    source_sheets,
                    ip_reference,
                    primary_oc,
                    primary_ov,
                    scheduled_date,
                    scheduled_date,
                    timestamp,
                    shipment_id,
                ),
            )
            shipments_updated += 1
        else:
            cursor = connection.execute(
                """INSERT INTO reception_shipments
                   (bl_awb, transport_type, brand_summary, country_origin, source_sheets,
                    ip_reference, primary_oc, primary_ov, scheduled_date,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    guide,
                    transport,
                    brands,
                    country,
                    source_sheets,
                    ip_reference,
                    primary_oc,
                    primary_ov,
                    scheduled_date,
                    timestamp,
                    timestamp,
                ),
            )
            shipment_id = cursor.lastrowid
            shipments_created += 1
        _ensure_default_reception_assignees(
            connection,
            shipment_id,
            username,
            f"{filename}: responsable predeterminado para evitar pendientes de asignación",
        )
        if _source_confirms_arrival(records):
            current = connection.execute(
                "SELECT app_status, condition_status, first_arrival_at FROM reception_shipments WHERE id = ?",
                (shipment_id,),
            ).fetchone()
            current_status = str(current["app_status"] or "PROGRAMADO")
            if RECEPTION_STATE_INDEX.get(current_status, 0) < RECEPTION_STATE_INDEX["ARRIBADO"]:
                arrival_date = next(
                    (record["confirmed_date"] for record in records if record.get("confirmed_date")),
                    "",
                )
                connection.execute(
                    """UPDATE reception_shipments
                       SET app_status = 'ARRIBADO', condition_status = 'ARRIBO REGISTRADO',
                           first_arrival_at = COALESCE(first_arrival_at, ?), updated_at = ?
                       WHERE id = ?""",
                    (arrival_date, timestamp, shipment_id),
                )
                _write_history(
                    connection,
                    shipment_id,
                    "IMPORTACION EXCEL",
                    "app_status",
                    current_status,
                    "ARRIBADO",
                    username,
                    "STATUS=DISPONIBLE, fecha confirmada y todas las líneas completas sin pendiente",
                )
        shipment_lines_created = 0
        shipment_lines_updated = 0
        for record in records:
            existing_line = connection.execute(
                "SELECT id FROM reception_lines WHERE source_key = ?", (record["source_key"],)
            ).fetchone()
            values = (
                shipment_id,
                record["source_row"],
                record["source_sheet"],
                record["source_key"],
                record["np_code"],
                record["description"],
                record["oc"],
                record["ov"],
                record["expected_qty"],
                record["requested_qty"],
                record["invoiced_qty"],
                record["pending_qty"],
                record["purchase_type"],
                record["brand"],
                record["applicant"],
                record["source_status"],
                record["source_invoice"],
                record["ip"],
                record["default_location"],
            )
            if existing_line:
                connection.execute(
                    """UPDATE reception_lines
                       SET shipment_id = ?, source_row = ?, source_sheet = ?, source_key = ?,
                           np_code = ?, description = ?, oc_number = ?, ov_number = ?,
                           expected_qty = ?, requested_qty = ?, invoiced_qty = ?, pending_qty = ?,
                           purchase_type = ?, brand = ?, applicant = ?, source_status = ?,
                           source_invoice = ?, ip_reference = ?, default_location = ?
                       WHERE id = ?""",
                    values + (existing_line["id"],),
                )
                lines_updated += 1
                shipment_lines_updated += 1
            else:
                connection.execute(
                    """INSERT INTO reception_lines
                       (shipment_id, source_row, source_sheet, source_key, np_code, description,
                        oc_number, ov_number, expected_qty, requested_qty, invoiced_qty, pending_qty,
                        purchase_type, brand, applicant, source_status, source_invoice, ip_reference,
                        default_location)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    values,
                )
                lines_created += 1
                shipment_lines_created += 1
        _write_history(
            connection,
            shipment_id,
            "IMPORTACION EXCEL",
            "lineas",
            shipment_lines_updated,
            shipment_lines_created + shipment_lines_updated,
            username,
            f"{filename}: {shipment_lines_created} nuevas y {shipment_lines_updated} actualizadas",
        )
        # Si ya existía una carga contable, vuelve a evaluar la BL después de
        # refrescar sus líneas. Así una BL completa puede cerrarse y sus
        # cantidades quedar alineadas sin esperar al siguiente reinicio.
        _refresh_accounting_summary(connection, shipment_id, username, filename)
    # Cada corte puede aportar BL nuevas: así entran al manifiesto sin
    # reescribir las guías ni los conteos ya guardados.
    assign_demo_truck_guides(connection)
    return {
        "filename": filename,
        "sheets": valid_sheets,
        "shipments": len(grouped),
        "shipments_created": shipments_created,
        "shipments_updated": shipments_updated,
        "lines_created": lines_created,
        "lines_updated": lines_updated,
        "skipped_rows": skipped_rows,
    }


def import_reception_excel_bytes(connection, content, filename, username, role):
    if not str(filename or "").lower().endswith(".xlsx"):
        raise ValueError("El archivo de Recepción debe ser .xlsx")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Conditional Formatting extension is not supported")
        workbook = load_workbook(BytesIO(content), data_only=True, read_only=True)
        try:
            return import_reception_workbook(connection, workbook, filename, username, role)
        finally:
            workbook.close()


def import_reception_excel_path(connection, path, username="sistema.local", role="ADMINISTRADOR"):
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Conditional Formatting extension is not supported")
        workbook = load_workbook(path, data_only=True, read_only=True)
        try:
            return import_reception_workbook(connection, workbook, str(path), username, role)
        finally:
            workbook.close()


def _normalized_identifier(value):
    normalized = unicodedata.normalize("NFKD", str(value or "").strip().upper())
    normalized = "".join(character for character in normalized if not unicodedata.combining(character))
    return "".join(character for character in normalized if character.isalnum())


def _accounting_header_indexes(headers):
    required = {
        "fr_number": _find_column(headers, "FACTURA RESERVA"),
        "em_number": _find_column(headers, "ENTRADA DE MERCANCIA"),
        "reception_date": _find_column(headers, "FECHA DE RECEPCION"),
        "em_date": _find_column(headers, "FECHA DE EM"),
        "ip_reference": _find_column(headers, "IP"),
        "awb_reference": _find_column(headers, "AWB"),
    }
    if any(index is None for index in required.values()):
        return None
    return {
        **required,
        "email_date": _find_column(headers, "FECHA DE CORREO"),
        "costing_date": _find_column(headers, "FECHA DE COSTEO"),
        "import_status": _find_column(headers, "ESTADO IMPORTACION", "ESTADO"),
    }


def _accounting_source_key(sheet, awb_key, ip_key, occurrence):
    return hashlib.sha256(f"{sheet}|{awb_key}|{ip_key}|{occurrence}".encode("utf-8")).hexdigest()


def _read_accounting_workbook(workbook):
    canonical = [
        worksheet for worksheet in workbook.worksheets
        if _normalize_header(worksheet.title) == _normalize_header(ACCOUNTING_SHEET_NAME)
    ]
    if not canonical:
        canonical = [
            worksheet for worksheet in workbook.worksheets
            if _normalize_header(worksheet.title) == LEGACY_ACCOUNTING_SHEET_NAME
        ]
    if not canonical:
        raise ValueError(
            f"No encontré la hoja {ACCOUNTING_SHEET_NAME} "
            f"(ni la anterior {LEGACY_ACCOUNTING_SHEET_NAME}) en el archivo contable"
        )

    records = []
    blocks = []
    skipped_rows = 0
    duplicate_counter = {}
    for worksheet in canonical:
        indexes = None
        for row_number, row in enumerate(worksheet.iter_rows(values_only=True), 1):
            headers = [_normalize_header(value) for value in row]
            detected = _accounting_header_indexes(headers)
            if detected:
                indexes = detected
                blocks.append({"sheet": worksheet.title, "header_row": row_number})
                continue
            if indexes is None:
                continue

            awb = _cell_text(_row_value(row, indexes["awb_reference"]))
            ip_reference = _cell_text(_row_value(row, indexes["ip_reference"]))
            fr_number = _cell_text(_row_value(row, indexes["fr_number"]))
            em_number = _cell_text(_row_value(row, indexes["em_number"]))
            if not awb and not ip_reference and not fr_number and not em_number:
                continue
            if not (awb or ip_reference) or not (fr_number or em_number):
                skipped_rows += 1
                continue

            pair = (_normalized_identifier(awb), _normalized_identifier(ip_reference))
            duplicate_counter[pair] = duplicate_counter.get(pair, 0) + 1
            # Keep the original namespace so a sheet rename does not create new references.
            source_key = _accounting_source_key(
                LEGACY_ACCOUNTING_SHEET_NAME, pair[0], pair[1], duplicate_counter[pair]
            )
            records.append(
                {
                    "source_key": source_key,
                    "source_occurrence": duplicate_counter[pair],
                    "source_sheet": worksheet.title,
                    "source_row": row_number,
                    "awb_reference": awb,
                    "ip_reference": ip_reference,
                    "fr_number": fr_number,
                    "em_number": em_number,
                    "email_date": _cell_text(_row_value(row, indexes["email_date"])),
                    "reception_date": _cell_text(_row_value(row, indexes["reception_date"])),
                    "em_date": _cell_text(_row_value(row, indexes["em_date"])),
                    "costing_date": _cell_text(_row_value(row, indexes["costing_date"])),
                    "import_status": _cell_text(_row_value(row, indexes["import_status"])),
                }
            )
    if not blocks:
        raise ValueError(
            "No encontré un bloque con AWB, IP, FACTURA RESERVA, ENTRADA DE MERCANCIA, "
            "FECHA DE RECEPCION y FECHA DE EM"
        )
    if not records:
        raise ValueError("El archivo contable no contiene filas FR/EM utilizables")
    return records, blocks, skipped_rows


def _identifier_candidates(value):
    raw = str(value or "").strip()
    candidates = []
    whole = _normalized_identifier(raw)
    if whole:
        candidates.append(whole)
    if "(" in raw and ")" in raw:
        outside = raw.split("(", 1)[0]
        inside = raw.split("(", 1)[1].split(")", 1)[0]
        for part in (outside, inside):
            normalized = _normalized_identifier(part)
            if normalized and normalized not in candidates:
                candidates.append(normalized)
    return candidates


def _shipment_identifier_maps(connection):
    awb_map = {}
    ip_map = {}
    shipments = connection.execute(
        "SELECT id, bl_awb, ip_reference FROM reception_shipments"
    ).fetchall()
    for shipment in shipments:
        awb = _normalized_identifier(shipment["bl_awb"])
        if awb:
            awb_map.setdefault(awb, set()).add(shipment["id"])
        for ip_reference in str(shipment["ip_reference"] or "").replace(";", ",").split(","):
            ip_key = _normalized_identifier(ip_reference)
            if ip_key:
                ip_map.setdefault(ip_key, set()).add(shipment["id"])
    for line in connection.execute(
        "SELECT shipment_id, ip_reference FROM reception_lines WHERE ip_reference IS NOT NULL"
    ).fetchall():
        ip_key = _normalized_identifier(line["ip_reference"])
        if ip_key:
            ip_map.setdefault(ip_key, set()).add(line["shipment_id"])
    return awb_map, ip_map


def _match_accounting_record(record, awb_map, ip_map):
    candidates = set()
    for awb_key in _identifier_candidates(record["awb_reference"]):
        candidates.update(awb_map.get(awb_key, set()))
    method = "AWB"
    if not candidates:
        raw_ip = str(record["ip_reference"] or "").replace(";", ",").replace(" - ", ",")
        for ip_reference in raw_ip.split(","):
            ip_key = _normalized_identifier(ip_reference)
            candidates.update(ip_map.get(ip_key, set()))
        method = "IP"
    if len(candidates) == 1:
        return next(iter(candidates)), method
    if len(candidates) > 1:
        return None, "AMBIGUO"
    return None, "SIN COINCIDENCIA"


def _joined_accounting_values(rows, field, limit=60):
    values = []
    seen = set()
    for row in rows:
        value = str(row[field] or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    if len(values) > limit:
        return ", ".join(values[:limit]) + f" (+{len(values) - limit})"
    return ", ".join(values)


def _refresh_accounting_summary(connection, shipment_id, username, filename):
    shipment = connection.execute(
        "SELECT * FROM reception_shipments WHERE id = ?", (shipment_id,)
    ).fetchone()
    rows = connection.execute(
        """SELECT * FROM reception_accounting_refs
           WHERE shipment_id = ? ORDER BY reception_date, source_row, id""",
        (shipment_id,),
    ).fetchall()
    # Una línea con FR y EM completos ya fue atendida por el circuito contable.
    # Algunas fuentes de importación traen received_qty=0; para evitar que una
    # BL cerrada aparezca con cantidades pendientes, inicializamos únicamente
    # esas líneas en la cantidad esperada. No sobrescribimos diferencias
    # registradas manualmente durante la revisión de sistema.
    accounting_by_ip = _accounting_rows_by_ip(rows)
    for line in connection.execute(
        "SELECT * FROM reception_lines WHERE shipment_id = ? ORDER BY id",
        (shipment_id,),
    ).fetchall():
        expected_qty = float(line["expected_qty"] or 0)
        received_qty = float(line["received_qty"] or 0)
        if (
            expected_qty > 0
            and received_qty == 0
            and _line_has_complete_accounting(line, accounting_by_ip, connection, shipment_id)
        ):
            connection.execute(
                "UPDATE reception_lines SET received_qty = ? WHERE id = ?",
                (expected_qty, line["id"]),
            )
            _write_history(
                connection,
                shipment_id,
                "IMPORTACION FR/EM",
                f"linea:{line['id']}:received_qty",
                received_qty,
                expected_qty,
                username,
                "FR y EM completas para la IP; se toma la cantidad esperada como atendida",
            )
    new_accounting_status = _accounting_status_for_shipment(
        connection, shipment_id, shipment, rows
    )
    old_accounting_status = str(shipment["accounting_status"] or "")
    state_changes = 0
    if new_accounting_status != old_accounting_status:
        connection.execute(
            "UPDATE reception_shipments SET accounting_status = ?, updated_at = ? WHERE id = ?",
            (new_accounting_status, reception_now(), shipment_id),
        )
        _write_history(
            connection,
            shipment_id,
            "IMPORTACION FR/EM",
            "accounting_status",
            old_accounting_status,
            new_accounting_status,
            username,
            filename,
        )
    old_app_status = str(shipment["app_status"] or "")
    if (
        new_accounting_status == "EM REGISTRADA"
        and old_app_status != "CERRADO"
        and _all_expected_ips_received(connection, shipment_id, shipment)
    ):
        connection.execute(
            """UPDATE reception_shipments
               SET app_status = 'CERRADO', condition_status = 'COMPLETADO', updated_at = ?
               WHERE id = ?""",
            (reception_now(), shipment_id),
        )
        _write_history(
            connection,
            shipment_id,
            "IMPORTACION FR/EM",
            "app_status",
            old_app_status,
            "CERRADO",
            username,
            "FR y EM completas para las referencias contables de la BL",
        )
        state_changes += 1
    elif new_accounting_status != "EM REGISTRADA" and old_app_status == "CERRADO":
        reopened_status = "ARRIBADO" if float(shipment["received_packages"] or 0) > 0 else "PROGRAMADO"
        reopened_condition = "ARRIBO REGISTRADO" if reopened_status == "ARRIBADO" else "POR ARRIBAR"
        connection.execute(
            """UPDATE reception_shipments
               SET app_status = ?, condition_status = ?, updated_at = ?
               WHERE id = ?""",
            (reopened_status, reopened_condition, reception_now(), shipment_id),
        )
        _write_history(
            connection,
            shipment_id,
            "IMPORTACION FR/EM",
            "app_status",
            old_app_status,
            reopened_status,
            username,
            "La referencia contable dejó de estar completa; se reabre para control",
        )
        state_changes += 1
    mappings = {
        "fr_number": "fr_number",
        "em_number": "em_number",
        "accounting_email_date": "email_date",
        "source_reception_date": "reception_date",
        "em_date": "em_date",
        "costing_date": "costing_date",
    }
    changed_fields = 0
    for shipment_field, reference_field in mappings.items():
        if reference_field == "em_number":
            new_value = ", ".join(
                value for row in rows for value in [_accounting_em_summary(connection, row)] if value
            )
        else:
            new_value = _joined_accounting_values(rows, reference_field)
        old_value = str(shipment[shipment_field] or "")
        if new_value == old_value:
            continue
        connection.execute(
            f"UPDATE reception_shipments SET {shipment_field} = ?, updated_at = ? WHERE id = ?",
            (new_value, reception_now(), shipment_id),
        )
        _write_history(
            connection,
            shipment_id,
            "IMPORTACION FR/EM",
            shipment_field,
            old_value,
            new_value,
            username,
            filename,
        )
        changed_fields += 1
    sync_shipment_lot_references(connection, shipment_id)
    return changed_fields + int(new_accounting_status != old_accounting_status) + state_changes


def _refresh_manual_accounting_status(connection, shipment_id, username, close_when_complete=False):
    shipment = connection.execute(
        "SELECT * FROM reception_shipments WHERE id = ?", (shipment_id,)
    ).fetchone()
    if not shipment:
        return
    new_status = _accounting_status_for_shipment(connection, shipment_id, shipment)
    old_status = str(shipment["accounting_status"] or "")
    if new_status != old_status:
        connection.execute(
            "UPDATE reception_shipments SET accounting_status = ?, updated_at = ? WHERE id = ?",
            (new_status, reception_now(), shipment_id),
        )
        _write_history(
            connection, shipment_id, "MODIFICACION", "accounting_status",
            old_status, new_status, username,
        )
    if (
        close_when_complete
        and new_status == "EM REGISTRADA"
        and str(shipment["app_status"] or "") != "CERRADO"
        and _all_expected_ips_received(connection, shipment_id, shipment)
    ):
        timestamp = reception_now()
        connection.execute(
            """UPDATE reception_shipments
                  SET app_status = 'CERRADO', condition_status = 'COMPLETADO', updated_at = ?
                WHERE id = ?""",
            (timestamp, shipment_id),
        )
        attention = _active_reception_attention(connection, shipment_id)
        if attention:
            connection.execute(
                """UPDATE reception_attentions
                      SET app_status = 'CERRADO', condition_status = 'COMPLETADO',
                          updated_at = ?, completed_at = ?
                    WHERE id = ?""",
                (timestamp, timestamp, attention["id"]),
            )
        _write_history(
            connection, shipment_id, "MODIFICACION", "app_status",
            shipment["app_status"], "CERRADO", username,
            "Todas las parejas FR + IP + EM están completas",
        )


def import_reception_accounting_workbook(connection, workbook, filename, username, role):
    require_reception_access(role)
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede cargar el Excel de FR/EM")
    records, blocks, skipped_rows = _read_accounting_workbook(workbook)
    historical_sheets = [
        row["source_sheet"]
        for row in connection.execute("SELECT DISTINCT source_sheet FROM reception_accounting_refs")
        if _normalize_header(row["source_sheet"]) in {
            LEGACY_ACCOUNTING_SHEET_NAME, _normalize_header(ACCOUNTING_SHEET_NAME)
        }
    ]
    awb_map, ip_map = _shipment_identifier_maps(connection)
    timestamp = reception_now()
    created = 0
    updated = 0
    unchanged = 0
    matched_by_awb = 0
    matched_by_ip = 0
    ambiguous = []
    unmatched = []
    affected_shipments = set()
    matched_records = []
    reference_fields = (
        "source_sheet", "source_row", "awb_reference", "ip_reference", "fr_number",
        "em_number", "email_date", "reception_date", "em_date", "costing_date",
        "import_status", "source_file",
    )
    for record in records:
        shipment_id, method = _match_accounting_record(record, awb_map, ip_map)
        if shipment_id is None:
            item = {
                "row": record["source_row"],
                "awb": record["awb_reference"],
                "ip": record["ip_reference"],
            }
            (ambiguous if method == "AMBIGUO" else unmatched).append(item)
            continue
        affected_shipments.add(shipment_id)
        matched_records.append((record, shipment_id, method))

    # Una IP no implica una relación 1:1. Es válido que cuatro IP compartan
    # una FR, que dos FR cubran una misma BL o que una EM cubra varias FR.
    # La correspondencia se valida por referencia y por BL; no se marca como
    # conflicto solo porque una IP tenga más de una combinación FR/EM.
    conflicting_ip_keys = set()
    conflicts = []
    conflict_by_shipment = {}
    valid_records = []
    for record, shipment_id, method in matched_records:
        record_ip_keys = [
            (shipment_id, ip_key) for ip_key in _ip_tokens(record["ip_reference"])
        ]
        conflict_keys = [key for key in record_ip_keys if key in conflicting_ip_keys]
        if conflict_keys:
            conflict_ips = [key[1] for key in conflict_keys]
            for _shipment, ip_key in conflict_keys:
                conflict_by_shipment.setdefault(shipment_id, set()).add(ip_key)
            conflicts.append(
                {
                    "row": record["source_row"],
                    "awb": record["awb_reference"],
                    "ip": record["ip_reference"],
                    "fr": record["fr_number"],
                    "em": record["em_number"],
                    "conflicting_ips": conflict_ips,
                }
            )
            continue
        valid_records.append((record, shipment_id, method))

    for record, shipment_id, method in valid_records:
        matched_by_awb += int(method == "AWB")
        matched_by_ip += int(method == "IP")
        values = {
            **{field: record.get(field, "") for field in reference_fields if field != "source_file"},
            "source_file": filename,
        }
        existing = connection.execute(
            "SELECT * FROM reception_accounting_refs WHERE source_key = ?",
            (record["source_key"],),
        ).fetchone()
        if not existing:
            for historical_sheet in historical_sheets:
                historical_key = _accounting_source_key(
                    historical_sheet, _normalized_identifier(record["awb_reference"]),
                    _normalized_identifier(record["ip_reference"]), record["source_occurrence"]
                )
                existing = connection.execute(
                    "SELECT * FROM reception_accounting_refs WHERE source_key = ?", (historical_key,)
                ).fetchone()
                if existing:
                    connection.execute(
                        "UPDATE reception_accounting_refs SET source_key = ? WHERE id = ?",
                        (record["source_key"], existing["id"]),
                    )
                    break
        if existing:
            changed = existing["shipment_id"] != shipment_id or any(
                str(existing[field] or "") != str(values[field] or "") for field in reference_fields
            )
            if changed:
                assignments = ", ".join(f"{field} = ?" for field in reference_fields)
                connection.execute(
                    f"""UPDATE reception_accounting_refs
                        SET shipment_id = ?, {assignments}, updated_at = ? WHERE id = ?""",
                    (shipment_id, *(values[field] for field in reference_fields), timestamp, existing["id"]),
                )
                updated += 1
            else:
                unchanged += 1
            reference_id = existing["id"]
        else:
            columns = ", ".join(reference_fields)
            placeholders = ", ".join("?" for _ in reference_fields)
            connection.execute(
                f"""INSERT INTO reception_accounting_refs
                    (shipment_id, source_key, {columns}, created_at, updated_at)
                    VALUES (?, ?, {placeholders}, ?, ?)""",
                (
                    shipment_id,
                    record["source_key"],
                    *(values[field] for field in reference_fields),
                    timestamp,
                    timestamp,
                ),
            )
            created += 1
            reference_id = connection.execute(
                "SELECT id FROM reception_accounting_refs WHERE source_key = ?",
                (record["source_key"],),
            ).fetchone()["id"]
        # Mantiene sincronizado el detalle de EM si el corte contable trae una
        # o varias EM en la misma celda. No elimina el resumen legacy.
        for em_value in _accounting_em_tokens(values.get("em_number")):
            imported_ip_keys = _ip_tokens(values.get("ip_reference"))
            imported_ip_key = imported_ip_keys[0] if len(imported_ip_keys) == 1 else None
            connection.execute(
                """INSERT OR IGNORE INTO reception_accounting_ems
                   (accounting_ref_id, ip_reference_key, em_number, em_date, username, created_at)
                   VALUES (?, ?, ?, ?, 'importacion', ?)""",
                (reference_id, imported_ip_key, em_value, values.get("em_date") or timestamp[:10], timestamp),
            )

    changed_summary_fields = 0
    conflict_shipments = set(affected_shipments)
    for shipment_id in conflict_shipments:
        conflict_ips = sorted(conflict_by_shipment.get(shipment_id, set()))
        new_count = len(conflict_ips)
        new_detail = ", ".join(conflict_ips[:20])
        if len(conflict_ips) > 20:
            new_detail += f" (+{len(conflict_ips) - 20})"
        current = connection.execute(
            "SELECT accounting_conflict_count, accounting_conflict_detail FROM reception_shipments WHERE id = ?",
            (shipment_id,),
        ).fetchone()
        old_count = int(current["accounting_conflict_count"] or 0)
        old_detail = str(current["accounting_conflict_detail"] or "")
        if old_count == new_count and old_detail == new_detail:
            continue
        connection.execute(
            """UPDATE reception_shipments
               SET accounting_conflict_count = ?, accounting_conflict_detail = ?, updated_at = ?
               WHERE id = ?""",
            (new_count, new_detail, reception_now(), shipment_id),
        )
        _write_history(
            connection,
            shipment_id,
            "IMPORTACION FR/EM",
            "accounting_conflict_detail",
            old_detail,
            new_detail,
            username,
            "IP con más de una combinación FR/EM; filas conflictivas no aplicadas",
        )
        changed_summary_fields += 1
    for shipment_id in affected_shipments:
        changed_summary_fields += _refresh_accounting_summary(
            connection, shipment_id, username, filename
        )
    return {
        "filename": filename,
        "sheet": blocks[0]["sheet"],
        "blocks": blocks,
        "records_read": len(records),
        "matched_records": matched_by_awb + matched_by_ip,
        "matched_by_awb": matched_by_awb,
        "matched_by_ip": matched_by_ip,
        "shipments_updated": len(affected_shipments),
        "references_created": created,
        "references_updated": updated,
        "references_unchanged": unchanged,
        "summary_fields_changed": changed_summary_fields,
        "unmatched_count": len(unmatched),
        "unmatched_examples": unmatched[:20],
        "ambiguous_count": len(ambiguous),
        "ambiguous_examples": ambiguous[:20],
        "skipped_rows": skipped_rows,
        "conflict_count": len(conflicts),
        "conflict_ip_count": len(conflicting_ip_keys),
        "conflict_examples": conflicts[:20],
    }


def import_reception_accounting_excel_bytes(connection, content, filename, username, role):
    if not str(filename or "").lower().endswith(".xlsx"):
        raise ValueError("El archivo de FR/EM debe ser .xlsx")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Conditional Formatting extension is not supported")
        warnings.filterwarnings("ignore", message="Data Validation extension is not supported")
        workbook = load_workbook(BytesIO(content), data_only=True, read_only=True)
        try:
            return import_reception_accounting_workbook(
                connection, workbook, filename, username, role
            )
        finally:
            workbook.close()


def import_reception_accounting_excel_path(
    connection, path, username="sistema.local", role="ADMINISTRADOR"
):
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Conditional Formatting extension is not supported")
        warnings.filterwarnings("ignore", message="Data Validation extension is not supported")
        workbook = load_workbook(path, data_only=True, read_only=True)
        try:
            return import_reception_accounting_workbook(
                connection, workbook, str(path), username, role
            )
        finally:
            workbook.close()


def add_physical_receipt(connection, shipment_id, data, username, role):
    shipment = _get_reception_shipment(connection, shipment_id, username, role)
    if str(shipment["truck_guide"] or "").strip():
        raise PermissionError("Esta BL pertenece a una guía de camión; registra la llegada y ubicación desde la guía")
    if int(shipment["bultos_closed"] or 0):
        raise PermissionError("Los bultos ya fueron cerrados; si llegó algo adicional, el administrador debe reabrir el expediente")
    quantity = float(data.get("received_packages") or 0)
    if quantity <= 0:
        raise ValueError("La cantidad recibida debe ser mayor que cero")
    sequence_no = connection.execute(
        "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM reception_receipts WHERE shipment_id = ?",
        (shipment_id,),
    ).fetchone()[0]
    timestamp = reception_now()
    receipt_cursor = connection.execute(
        """INSERT INTO reception_receipts
           (shipment_id, sequence_no, received_packages, notes, location_text, username, received_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            shipment_id,
            sequence_no,
            quantity,
            str(data.get("notes") or "").strip(),
            str(data.get("location") or "").strip(),
            username,
            timestamp,
        ),
    )
    receipt_id = receipt_cursor.lastrowid
    # Cada llegada es una atención propia. Se pueden trabajar en cualquier
    # orden; sus cantidades y estado quedan aislados por attention_id.
    _create_reception_attention(connection, shipment, receipt_id, username, "ARRIBADO")
    old_total = float(shipment["received_packages"] or 0)
    new_total = old_total + quantity
    expected = float(shipment["expected_packages"] or 0)
    if expected and new_total < expected:
        condition = "SALDO POR ARRIBAR"
    elif expected and new_total > expected:
        condition = "EXCEDENTE POR VALIDAR"
    elif expected:
        condition = "ARRIBO COMPLETO"
    else:
        condition = "ARRIBO REGISTRADO"
    resulting_status = (
        "ARRIBADO"
        if shipment["app_status"] == "CERRADO"
        else shipment["app_status"]
        if RECEPTION_STATE_INDEX.get(shipment["app_status"], 0) >= RECEPTION_STATE_INDEX["ARRIBADO"]
        else "ARRIBADO"
    )
    connection.execute(
        """UPDATE reception_shipments
               SET received_packages = ?, app_status = ?, condition_status = ?,
                   first_arrival_at = COALESCE(first_arrival_at, ?),
                   completed_arrival_at = CASE WHEN expected_packages > 0 AND ? >= expected_packages THEN ? ELSE completed_arrival_at END,
                   system_quantities_initialized = CASE WHEN ? = 'CERRADO' THEN 0 ELSE system_quantities_initialized END,
                   transfer_assistant_checked = CASE WHEN ? = 'CERRADO' THEN 0 ELSE transfer_assistant_checked END,
                   location_text = CASE WHEN ? = 'CERRADO' THEN '' ELSE location_text END,
                   updated_at = ?
               WHERE id = ?""",
        (
            new_total,
            resulting_status,
            condition,
            timestamp,
            new_total,
            timestamp,
            shipment["app_status"],
            shipment["app_status"],
            shipment["app_status"],
            timestamp,
            shipment_id,
        ),
    )
    _write_history(
        connection,
        shipment_id,
        "ARRIBO",
        "received_packages",
        old_total,
        new_total,
        username,
        f"Recepción física {sequence_no}",
    )
    return reception_detail(connection, shipment_id, role)


def close_physical_receipts(connection, shipment_id, data, username, role):
    """Close the physical-arrival window without changing expected packages."""
    shipment = _get_reception_shipment(connection, shipment_id, username, role)
    if shipment["app_status"] == "CERRADO":
        raise PermissionError("La recepción ya está cerrada")
    if int(shipment["bultos_closed"] or 0):
        return reception_detail(connection, shipment_id, role)
    reason = str(data.get("reason") or "No quedan bultos pendientes por recibir").strip()
    timestamp = reception_now()
    connection.execute(
        "UPDATE reception_shipments SET bultos_closed = 1, updated_at = ? WHERE id = ?",
        (timestamp, shipment_id),
    )
    _write_history(
        connection, shipment_id, "ARRIBO", "bultos_closed", 0, 1, username, reason
    )
    return reception_detail(connection, shipment_id, role)


def update_reception_location(connection, shipment_id, data, username, role):
    shipment = _get_reception_shipment(connection, shipment_id, username, role)
    is_admin = role == "ADMINISTRADOR"
    if str(shipment["truck_guide"] or "").strip() and not is_admin:
        raise PermissionError("Esta BL pertenece a una guía de camión; la ubicación se registra desde la guía")
    # El asistente/auxiliar solo puede registrar la ubicación en el paso 2.
    # El administrador puede corregir una ubicación histórica después de que
    # el expediente avanzó o se cerró, sin reabrir ni borrar la trazabilidad.
    if not is_admin and shipment["app_status"] != "ARRIBADO":
        raise PermissionError("La ubicación de recepción se registra únicamente en ZONA RECEPCIÓN")
    location = str(data.get("location") or "").strip()
    if not location:
        raise ValueError("Indica la ubicación física en texto")
    receipt_id = data.get("receipt_id")
    if receipt_id:
        receipt = connection.execute(
            "SELECT * FROM reception_receipts WHERE id = ? AND shipment_id = ?",
            (int(receipt_id), shipment_id),
        ).fetchone()
    else:
        receipt = connection.execute(
            "SELECT * FROM reception_receipts WHERE shipment_id = ? ORDER BY sequence_no DESC LIMIT 1",
            (shipment_id,),
        ).fetchone()
    if not receipt:
        raise ValueError("Registra primero la llegada de al menos un bulto")
    old_value = str(receipt["location_text"] or "")
    if location == old_value:
        return reception_detail(connection, shipment_id, role)
    timestamp = reception_now()
    latest_receipt = connection.execute(
        "SELECT id FROM reception_receipts WHERE shipment_id = ? ORDER BY sequence_no DESC LIMIT 1",
        (shipment_id,),
    ).fetchone()
    # Correct the physical arrival represented by this receipt only. Historic
    # receipts without a guide must never inherit the BL's current truck.
    arrival = connection.execute(
        "SELECT id, received_packages FROM reception_truck_bl_arrivals WHERE shipment_id=? AND lower(truck_guide)=lower(?)",
        (shipment_id, str(receipt["truck_guide"] or "")),
    ).fetchone()
    if arrival and float(arrival["received_packages"] or 0) > 0:
        prior_locations = [dict(row) for row in connection.execute(
            "SELECT location_text, package_count FROM reception_truck_bl_locations WHERE arrival_id=? ORDER BY id",
            (arrival["id"],),
        )]
        connection.execute("DELETE FROM reception_truck_bl_locations WHERE arrival_id=?", (arrival["id"],))
        connection.execute(
            """INSERT INTO reception_truck_bl_locations
               (arrival_id, location_text, package_count, username, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (arrival["id"], location, arrival["received_packages"], username, timestamp, timestamp),
        )
        _write_history(
            connection, shipment_id, "ZONA RECEPCION", f"arribo:{arrival['id']}:ubicaciones",
            json.dumps(prior_locations, ensure_ascii=False),
            json.dumps([{"location_text": location, "package_count": arrival["received_packages"]}], ensure_ascii=False),
            username, "Corrección administrativa de ubicación temporal de la llegada",
        )
    # location_text en reception_shipments es solo un resumen de la última
    # llegada. Al corregir un bulto histórico no debe reemplazar el resumen
    # de una llegada posterior.
    shipment_location = (
        location if latest_receipt and int(latest_receipt["id"]) == int(receipt["id"])
        else str(shipment["location_text"] or "")
    )
    connection.execute(
        "UPDATE reception_receipts SET location_text = ? WHERE id = ?",
        (location, receipt["id"]),
    )
    connection.execute(
        "UPDATE reception_shipments SET location_text = ?, updated_at = ? WHERE id = ?",
        (shipment_location, timestamp, shipment_id),
    )
    attention = connection.execute(
        "SELECT * FROM reception_attentions WHERE receipt_id = ? LIMIT 1",
        (receipt["id"],),
    ).fetchone()
    if attention:
        connection.execute(
            "UPDATE reception_attentions SET location_text = ?, updated_at = ? WHERE id = ?",
            (location, timestamp, attention["id"]),
        )
    _write_history(
        connection, shipment_id, "ZONA RECEPCION", f"bulto:{receipt['sequence_no']}:location_text",
        old_value, location, username,
    )
    return reception_detail(connection, shipment_id, role)


def update_reception_validation(connection, shipment_id, data, username, role):
    shipment = _get_reception_shipment(connection, shipment_id, username, role)
    if shipment["app_status"] != "VALIDACION":
        raise PermissionError("La muestra solo se registra durante VALIDACIÓN / TRANSFERENCIA")
    sample_ids = set(_validation_sample_ids(connection, shipment_id))
    checks = data.get("checks") or []
    if not isinstance(checks, list):
        raise ValueError("Formato de muestra no válido")
    known = {int(row["id"]): row for row in connection.execute(
        "SELECT * FROM reception_lines WHERE shipment_id = ?", (shipment_id,)
    ).fetchall()}
    timestamp = reception_now()
    for item in checks:
        try:
            line_id = int(item.get("line_id"))
        except (AttributeError, TypeError, ValueError):
            raise ValueError("La muestra contiene una línea no válida")
        if line_id not in sample_ids or line_id not in known:
            raise ValueError("Solo se puede validar la muestra seleccionada por el sistema")
        values = {
            "validation_sap_checked": 0,
            "validation_location_checked": int(bool(item.get("location_checked"))),
            "validation_comment_checked": 0,
        }
        validation_comment = str(item.get("comment") or "").strip()
        connection.execute(
            """UPDATE reception_lines SET validation_sap_checked = ?,
               validation_location_checked = ?, validation_comment_checked = ?,
               validation_comment = ? WHERE id = ?""",
            (values["validation_sap_checked"], values["validation_location_checked"],
             values["validation_comment_checked"], validation_comment, line_id),
        )
        values["comment"] = validation_comment
        _write_history(
            connection, shipment_id, "VALIDACION", f"linea:{line_id}:muestra",
            "", json.dumps(values), username, "Control de ubicación y comentario de muestra",
        )
    return reception_detail(connection, shipment_id, role)


def confirm_reception_transfer(connection, shipment_id, data, username, role):
    shipment = _get_reception_shipment(connection, shipment_id, username, role)
    if shipment["app_status"] != "SOLICITUD TRANSFERENCIA":
        raise PermissionError("La confirmación administrativa solo aplica a una transferencia solicitada")
    if role not in RECEPTION_ROLES:
        raise PermissionError("No tienes permiso para confirmar la solicitud")
    if not bool(data.get("checked")):
        raise ValueError("Marca la solicitud como revisada")
    if int(shipment["transfer_assistant_checked"] or 0):
        return reception_detail(connection, shipment_id, role)
    timestamp = reception_now()
    connection.execute(
        "UPDATE reception_shipments SET transfer_assistant_checked = 1, updated_at = ? WHERE id = ?",
        (timestamp, shipment_id),
    )
    _write_history(connection, shipment_id, "TRANSFERENCIA", "transfer_assistant_checked", 0, 1, username)
    return reception_detail(connection, shipment_id, role)


def update_reception_references(connection, shipment_id, data, username, role):
    shipment = _get_reception_shipment(connection, shipment_id, username, role)
    selected_attention_id = data.get("attention_id")
    selected_attention = _active_reception_attention(
        connection, shipment_id, selected_attention_id
    ) if selected_attention_id else _active_reception_attention(connection, shipment_id)
    reference_shipment = dict(shipment)
    if selected_attention:
        reference_shipment["app_status"] = selected_attention["app_status"]
    changed = False
    if "expected_packages" in data:
        raise ValueError("Los bultos esperados provienen de la fuente de recepción y no se editan manualmente")
    if (
        "em_number" in data
        and role == "ADMINISTRADOR"
        and reference_shipment["app_status"] == "REVISION SISTEMA"
        and not str(shipment["em_number"] or "").strip()
    ):
        raise PermissionError("Completa la revisión de sistema y pasa a la etapa EM antes de registrar la EM")
    if (
        "em_number" in data
        and role != "ADMINISTRADOR"
        and _is_assigned_to(shipment, username)
        and reference_shipment["app_status"] != "EM"
    ):
        raise PermissionError("La EM solo se registra dentro de la etapa EM")
    allowed = set()
    if role == "ADMINISTRADOR":
        allowed |= {"fr_number", "em_number", "current_assistant", "current_auxiliary"}
    elif _is_assigned_to(shipment, username) and reference_shipment["app_status"] == "EM":
        # La revisión de sistema solo valida cantidades y observaciones.
        # El trabajador registra el número de EM únicamente después de entrar
        # a la etapa EM. La creación automática en SAP se conectará aquí
        # cuando TI entregue las credenciales del Service Layer.
        if "em_number" in data:
            missing_fr = connection.execute(
                """SELECT 1 FROM reception_accounting_refs
                   WHERE shipment_id = ? AND trim(COALESCE(fr_number, '')) = ''
                   LIMIT 1""",
                (shipment_id,),
            ).fetchone()
            if missing_fr:
                raise PermissionError("No se puede registrar una EM: falta factura de reserva")
            accounting_status = _accounting_status_for_shipment(connection, shipment_id, shipment)
            if accounting_status != "PENDIENTE EM":
                raise PermissionError(
                    "La EM solo puede registrarse cuando todas las IP ya tienen factura de reserva"
                )
            allowed.add("em_number")
    # En EM se registra una entrada por cada referencia contable. Una BL puede
    # contener varias IP y una FR puede acumular una EM por atención parcial.
    reference_updates = data.get("reference_updates") or []
    if reference_updates:
        if role != "ADMINISTRADOR" and not _is_assigned_to(shipment, username):
            raise PermissionError("Solo el personal asignado puede registrar las EM")
        if reference_shipment["app_status"] != "EM" and role != "ADMINISTRADOR":
            raise PermissionError("Las EM solo se registran dentro de la etapa EM")
        refs = {
            int(row["id"]): row
            for row in connection.execute(
                "SELECT * FROM reception_accounting_refs WHERE shipment_id = ?",
                (shipment_id,),
            ).fetchall()
        }
        for item in reference_updates:
            try:
                reference_id = int(item.get("id"))
            except (TypeError, ValueError):
                raise ValueError("La referencia FR/EM no es válida")
            reference = refs.get(reference_id)
            if not reference:
                raise ValueError("La referencia FR/EM no pertenece a esta BL")
            ip_key = str(item.get("ip_key") or "").strip() or None
            reference_ip_keys = _ip_tokens(reference["ip_reference"])
            if len(reference_ip_keys) > 1 and not ip_key:
                raise ValueError("Selecciona la IP específica antes de registrar la EM")
            if ip_key and ip_key not in reference_ip_keys:
                raise ValueError("La IP no pertenece a la referencia FR seleccionada")
            ip_key = ip_key or (reference_ip_keys[0] if reference_ip_keys else None)
            if not str(reference["fr_number"] or "").strip():
                raise ValueError("No se puede registrar una EM sin factura de reserva")
            if not _accounting_ref_has_received_sku(
                connection, shipment_id, reference, ip_key,
                selected_attention["id"] if selected_attention else None,
            ):
                raise ValueError(
                    f"La IP {ip_key or reference['ip_reference'] or 'sin IP'} no tiene SKU ingresado en esta llegada; queda pendiente"
                )
            value = str(item.get("em_number") or "").strip()
            if not value:
                raise ValueError(
                    f"Registra la EM correspondiente a la FR {reference['fr_number'] or 'sin número'}"
                )
            old_value = ", ".join(_accounting_em_values(connection, reference_id, ip_key))
            updated_at = reception_now()
            attention = selected_attention or _active_reception_attention(connection, shipment_id)
            em_id = item.get("em_id")
            if em_id not in (None, ""):
                try:
                    em_id = int(em_id)
                except (TypeError, ValueError):
                    raise ValueError("El registro de EM que intentas corregir no es válido")
                existing_em = connection.execute(
                    """SELECT * FROM reception_accounting_ems
                        WHERE id = ? AND accounting_ref_id = ?""",
                    (em_id, reference_id),
                ).fetchone()
                if not existing_em:
                    raise ValueError("La EM que intentas corregir no pertenece a esta FR")
                if role != "ADMINISTRADOR" and (
                    not attention or int(existing_em["attention_id"] or 0) != int(attention["id"])
                ):
                    raise PermissionError("Solo puedes corregir la EM de la atención que estás trabajando")
                duplicate = connection.execute(
                    """SELECT 1 FROM reception_accounting_ems
                        WHERE accounting_ref_id = ? AND em_number = ? AND id <> ? LIMIT 1""",
                    (reference_id, value, em_id),
                ).fetchone()
                if duplicate:
                    raise ValueError("Ese número de EM ya está registrado para esta FR")
                previous_em = str(existing_em["em_number"] or "").strip()
                if previous_em == value:
                    continue
                connection.execute(
                    """UPDATE reception_accounting_ems
                          SET em_number = ?, em_date = ?, username = ? WHERE id = ?""",
                    (value, updated_at[:10], username, em_id),
                )
                change_note = f"EM corregida para IP {ip_key or '—'} y FR {reference['fr_number'] or '—'}"
            else:
                existing_values = set(_accounting_em_values(connection, reference_id, ip_key))
                if value in existing_values:
                    continue
                connection.execute(
                    """INSERT INTO reception_accounting_ems
                       (accounting_ref_id, ip_reference_key, attention_id, em_number, em_date, username, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (reference_id, ip_key, attention["id"] if attention else None, value,
                     updated_at[:10], username, updated_at),
                )
                change_note = f"EM registrada para IP {ip_key or '—'} y FR {reference['fr_number'] or '—'}"
            ordered_values = [*(_accounting_em_values(connection, reference_id))]
            connection.execute(
                "UPDATE reception_accounting_refs SET em_number = ?, em_date = ?, updated_at = ? WHERE id = ?",
                (", ".join(ordered_values), updated_at[:10], updated_at, reference_id),
            )
            _write_history(
                connection, shipment_id, "MODIFICACION", f"referencia:{reference_id}:em_number",
                old_value, ", ".join(ordered_values), username,
                change_note,
            )
            changed = True
        refreshed_refs = connection.execute(
            "SELECT * FROM reception_accounting_refs WHERE shipment_id = ? ORDER BY id",
            (shipment_id,),
        ).fetchall()
        for shipment_field, reference_field in {
            "fr_number": "fr_number", "em_number": "em_number", "em_date": "em_date",
        }.items():
            value = _joined_accounting_values(refreshed_refs, reference_field)
            old_value = str(shipment[shipment_field] or "")
            if value == old_value:
                continue
            connection.execute(
                f"UPDATE reception_shipments SET {shipment_field} = ?, updated_at = ? WHERE id = ?",
                (value, reception_now(), shipment_id),
            )
            _write_history(connection, shipment_id, "MODIFICACION", shipment_field, old_value, value, username)
        _refresh_manual_accounting_status(
            connection, shipment_id, username, close_when_complete=True
        )
    for field in allowed:
        if field not in data:
            continue
        value = str(data.get(field) or "").strip()
        old_value = str(shipment[field] or "")
        if value == old_value:
            continue
        connection.execute(
            f"UPDATE reception_shipments SET {field} = ?, updated_at = ? WHERE id = ?",
            (value, reception_now(), shipment_id),
        )
        _write_history(connection, shipment_id, "MODIFICACION", field, old_value, value, username)
        changed = True
    if not changed and not reference_updates:
        raise ValueError("No se recibió ningún cambio")
    if not reference_updates:
        _refresh_manual_accounting_status(connection, shipment_id, username)
    return reception_detail(
        connection, shipment_id, role, username,
        selected_attention["id"] if selected_attention else None,
    )


def update_reception_line_locations(connection, shipment_id, data, username, role):
    """Save final SAP/bin locations per NP, independently of truck staging."""
    shipment = _get_reception_shipment(connection, shipment_id, username, role)
    if role != "ADMINISTRADOR" and shipment["app_status"] != "UBICACION":
        raise PermissionError("La ubicación final se registra únicamente en el paso UBICACIÓN")
    items = data.get("locations") or []
    if not isinstance(items, list) or not items:
        raise ValueError("No hay ubicaciones de NP para guardar")

    known = {
        int(row["id"]): row
        for row in connection.execute(
            "SELECT id, final_location, final_location_confirmed FROM reception_lines WHERE shipment_id = ?",
            (shipment_id,),
        ).fetchall()
    }
    submitted = set()
    timestamp = reception_now()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Formato de ubicación por NP no válido")
        try:
            line_id = int(item.get("line_id"))
        except (TypeError, ValueError):
            raise ValueError("Selecciona un NP válido")
        if line_id not in known or line_id in submitted:
            raise ValueError("Hay un NP duplicado o que no pertenece a esta BL")
        submitted.add(line_id)
        location = str(item.get("final_location") or "").strip()
        confirmed = bool(item.get("confirmed"))
        if confirmed and not location:
            raise ValueError("Indica la ubicación final antes de confirmarla")
        old = known[line_id]
        old_location = str(old["final_location"] or "")
        old_confirmed = int(old["final_location_confirmed"] or 0)
        if old_location == location and old_confirmed == int(confirmed):
            continue
        connection.execute(
            "UPDATE reception_lines SET final_location = ?, final_location_confirmed = ? WHERE id = ?",
            (location, int(confirmed), line_id),
        )
        if old_location != location:
            _write_history(
                connection, shipment_id, "UBICACION", f"linea:{line_id}:final_location",
                old_location, location, username, "Ubicación final del NP; distinta de la zona temporal del camión",
            )
        if old_confirmed != int(confirmed):
            _write_history(
                connection, shipment_id, "UBICACION", f"linea:{line_id}:final_location_confirmed",
                old_confirmed, int(confirmed), username,
            )
    return reception_detail(connection, shipment_id, role)


def truck_guide_summary(connection, truck_guide, username="", role="ADMINISTRADOR"):
    """Return the plan, receipts and locations for every BL on one truck."""
    require_reception_access(role)
    guide = str(truck_guide or '').strip()
    if not guide:
        raise ValueError("Selecciona una guía de camión")
    rows = connection.execute(
        """SELECT s.id, s.bl_awb, s.expected_packages,
                      s.received_packages AS shipment_received_packages, s.app_status,
                      CASE WHEN TRIM(COALESCE(s.em_number,'')) <> ''
                                 OR EXISTS (SELECT 1 FROM reception_accounting_refs er
                                             WHERE er.shipment_id=s.id
                                               AND TRIM(COALESCE(er.em_number,''))<>'')
                                 OR EXISTS (SELECT 1 FROM reception_accounting_ems ee
                                             JOIN reception_accounting_refs er
                                               ON er.id=ee.accounting_ref_id
                                             WHERE er.shipment_id=s.id
                                               AND TRIM(COALESCE(ee.em_number,''))<>'')
                            THEN 1 ELSE 0 END AS has_registered_em,
                      s.current_assistant, s.current_auxiliary,
                      m.planned_packages,
                      a.id AS arrival_id, a.received_packages AS received_this_truck,
                      a.arrival_key, a.excess_reason, a.notes AS arrival_notes,
                      a.username AS arrival_username, a.arrived_at,
                      COALESCE((SELECT SUM(prev.received_packages)
                                  FROM reception_truck_bl_arrivals prev
                                 WHERE prev.shipment_id = s.id
                                   AND lower(prev.truck_guide) <> lower(m.truck_guide)), 0) AS previously_received
             FROM reception_truck_bl_manifest m
             JOIN reception_shipments s ON s.id = m.shipment_id
             LEFT JOIN reception_truck_bl_arrivals a
               ON a.shipment_id = s.id AND lower(a.truck_guide) = lower(m.truck_guide)
            WHERE lower(m.truck_guide) = lower(?)
              AND COALESCE(m.operational_active,1)=1
            ORDER BY s.bl_awb""",
        (guide,),
    ).fetchall()
    header = _truck_guide_header(connection, guide)
    scanner_enabled = bool(header and int(header["scanner_enabled"] or 0))
    if not rows:
        if not header:
            raise ValueError("No existe la guía de camión seleccionada")
        if role != "ADMINISTRADOR" and not scanner_enabled:
            raise PermissionError("La guía todavía no tiene BL asignadas")
        return {"truck_guide": guide, "guide_status": _truck_guide_status(header),
                "counting_enabled": False, "count_enabled_at": header["count_enabled_at"],
                "count_enabled_by": header["count_enabled_by"],
                "source": header["source_type"], "source_type": header["source_type"],
                "scanner_enabled": scanner_enabled,
                "is_confirmed": int(header["is_confirmed"] or 0),
                "carrier_reference": header["carrier_reference"] or "",
                "bl_count": 0, "closed_bl_count": 0, "count_startable_bl_count": 0,
                "expected_packages": 0, "planned_packages": 0, "total_manifest_packages": 0,
                "open_expected_packages": 0, "closed_expected_packages": 0,
                "remaining_packages": 0, "received_packages": 0, "unlocated_packages": 0,
                "steps_complete": False, "locations": [], "notes": "", "received_at": None,
                "updated_at": None, "bls": []}
    is_demo_guide = str(header["source_type"] or "").strip().upper() == "ESTIMACION_PRUEBA"
    if role != "ADMINISTRADOR" and not int(header["is_confirmed"] or 0) and not is_demo_guide:
        raise PermissionError("La guía aún es una propuesta pendiente de confirmación administrativa")
    is_unconfirmed_date_proposal = bool(
        not int(header["is_confirmed"] or 0)
        and str(header["source_type"] or "") == "PROPUESTA_FECHA"
    )
    def is_open_truck_work(row):
        """True only while this guide still has physical work for the BL."""
        status = str(row["app_status"] or "").upper()
        if status in {"EM", "UBICACION", "VALIDACION", "SOLICITUD TRANSFERENCIA", "CERRADO"}:
            return False
        if is_unconfirmed_date_proposal and int(row["has_registered_em"] or 0):
            return False
        if is_unconfirmed_date_proposal and status != "PROGRAMADO":
            return False
        if status == "REVISION SISTEMA" and row["arrival_id"] is None:
            return False
        if scanner_enabled and row["arrival_id"] is None:
            return True
        if float(row["expected_packages"] or 0) <= 0:
            return True
        if float(row["planned_packages"] or 0) <= 0:
            return False
        if row["arrival_id"] is not None:
            return True
        expected = float(row["expected_packages"] or 0)
        received = float(row["shipment_received_packages"] or 0)
        return expected <= 0 or received < expected

    closed_expected = sum(float(row["planned_packages"] or 0) for row in rows if row["app_status"] == "CERRADO")
    locations = []
    enriched = []
    for row in rows:
        data = _as_dict(row)
        data["expected_packages"] = float(row["expected_packages"] or 0)
        data["expected_data_pending"] = data["expected_packages"] <= 0
        explicit_previous = float(row["previously_received"] or 0)
        received_this_truck = float(row["received_this_truck"] or 0)
        shipment_received = float(row["shipment_received_packages"] or 0)
        data["previously_received_packages"] = max(
            explicit_previous, max(0.0, shipment_received - received_this_truck)
        )
        data["planned_packages"] = float(row["planned_packages"] or 0)
        data["package_scan_count"] = int(connection.execute(
            """SELECT COUNT(*) FROM reception_truck_package_scans
                WHERE lower(truck_guide)=lower(?) AND shipment_id=? AND scan_status='ACTIVO'""",
            (guide, int(row["id"])),
        ).fetchone()[0] or 0)
        data["received_this_truck"] = received_this_truck
        pending_before_truck = (
            max(0.0, data["expected_packages"] - data["previously_received_packages"])
            if data["expected_packages"] > 0 else data["planned_packages"]
        )
        data["guide_required_packages"] = min(data["planned_packages"], pending_before_truck)
        data["pending_packages"] = max(
            0.0, data["expected_packages"] - data["previously_received_packages"] - data["received_this_truck"]
        )
        data["truck_work_pending"] = is_open_truck_work(row)
        data["pending_to_plan_packages"] = truck_bl_package_balance(connection, int(row["id"]))["pending_to_plan_packages"]
        data["locations"] = list_truck_bl_arrival_locations(connection, int(row["id"]))
        arrival_id = data.get("arrival_id")
        data["locations"] = [location for location in data["locations"] if location["arrival_id"] == arrival_id]
        locations.extend(data["locations"])
        enriched.append(data)
    open_rows = [row for row in enriched if row["truck_work_pending"]]
    open_expected = sum(float(row["guide_required_packages"] or 0) for row in open_rows)
    covered = sum(float(row["received_this_truck"] or 0) for row in open_rows)
    total_planned = open_expected
    all_recorded = all(row["arrival_id"] is not None for row in open_rows)
    all_located = all(
        row["received_this_truck"] == 0
        or sum(float(location["package_count"] or 0) for location in row["locations"]) == row["received_this_truck"]
        for row in open_rows if row["arrival_id"] is not None
    )
    stored_guide_status = _truck_guide_status(header)
    has_bl_arrivals = connection.execute(
        "SELECT 1 FROM reception_truck_bl_arrivals WHERE lower(truck_guide)=lower(?) LIMIT 1", (guide,)
    ).fetchone()
    legacy_summary = connection.execute(
        "SELECT expected_packages, received_packages FROM reception_truck_arrivals WHERE lower(truck_guide)=lower(?)",
        (guide,),
    ).fetchone()
    legacy_locations = []
    if legacy_summary:
        legacy_locations = [
            {"location_text": row["location_text"], "package_count": float(row["package_count"] or 0)}
            for row in connection.execute(
                "SELECT location_text, package_count FROM reception_truck_locations WHERE lower(truck_guide)=lower(?) ORDER BY location_text",
                (guide,),
            ).fetchall()
        ]
    guide_status = stored_guide_status
    if not open_rows:
        guide_status = "FINALIZADA"
    elif legacy_summary and not has_bl_arrivals:
        # Old totals have no reliable BL allocation. Preserve them for review,
        # but do not count them as received, located, or eligible for counting.
        guide_status = "PENDIENTE"
    elif stored_guide_status == "LISTA_PARA_CONTEO" and not (all_recorded and all_located):
        guide_status = "ZONA_RECEPCION" if has_bl_arrivals else "PENDIENTE"
    elif stored_guide_status == "EN_CURSO" and all_recorded:
        # Compatibility for guides saved before arrival and location became
        # separate steps: their recorded package quantities belong to step 2.
        guide_status = "ZONA_RECEPCION"
    if (stored_guide_status == "LISTA_PARA_CONTEO" and all_recorded and all_located
            and covered <= 0 and open_rows):
        guide_status = "CERRADA_SIN_BULTOS"
    summary_arrival = connection.execute(
        "SELECT MAX(arrived_at) AS arrived_at, GROUP_CONCAT(DISTINCT notes) AS notes "
        "FROM reception_truck_bl_arrivals WHERE lower(truck_guide) = lower(?)", (guide,)
    ).fetchone()
    return {
        "truck_guide": guide,
        "guide_status": guide_status,
        "counting_enabled": (
            guide_status == "LISTA_PARA_CONTEO" and all_recorded and all_located and covered > 0
        ),
        "stored_guide_status": stored_guide_status,
        "count_enabled_at": header["count_enabled_at"] if header else None,
        "count_enabled_by": header["count_enabled_by"] if header else None,
        "source": header["source_type"] if header else "PROPUESTA_FECHA",
        "source_type": header["source_type"] if header else "PROPUESTA_FECHA",
        "scanner_enabled": scanner_enabled,
        "is_confirmed": int(header["is_confirmed"] or 0) if header else 0,
        "carrier_reference": str(header["carrier_reference"] or "") if header else "",
        "confirmed_by": header["confirmed_by"] if header else None,
        "confirmed_at": header["confirmed_at"] if header else None,
        "data_pending_count": sum(1 for row in open_rows if row["expected_data_pending"]),
        "bl_count": len(rows),
        "closed_bl_count": sum(1 for row in rows if row["app_status"] == "CERRADO"),
        "count_startable_bl_count": sum(1 for row in open_rows if row["app_status"] in {"PROGRAMADO", "ARRIBADO"}),
        "expected_packages": total_planned,
        "planned_packages": total_planned,
        "total_manifest_packages": total_planned,
        "open_expected_packages": open_expected,
        "closed_expected_packages": closed_expected,
        "remaining_packages": sum(
            max(0.0, float(row["guide_required_packages"] or 0) - float(row["received_this_truck"] or 0))
            for row in open_rows
        ),
        "received_packages": covered,
        "unlocated_packages": sum(
            max(0.0, row["received_this_truck"] - sum(float(location["package_count"] or 0) for location in row["locations"]))
            for row in open_rows
        ),
        "steps_complete": all_recorded and all_located,
        "legacy_unallocated": bool(legacy_summary),
        "legacy_tracking": ({
            "received_packages": float(legacy_summary["received_packages"] or 0),
            "expected_packages": float(legacy_summary["expected_packages"] or 0),
            "locations": legacy_locations,
        } if legacy_summary else None),
        "locations": locations,
        "notes": str(summary_arrival["notes"] or "") if summary_arrival else "",
        "received_at": summary_arrival["arrived_at"] if summary_arrival else None,
        "updated_at": summary_arrival["arrived_at"] if summary_arrival else None,
        # Las BL son detalle informativo del camión.  La UI sólo debe abrir
        # una para conteo después de que la cabecera esté LISTA_PARA_CONTEO.
        "bls": enriched,
    }


def process_truck_arrival(connection, truck_guide, received_packages, locations, notes, username, role, additional_packages=False):
    """Save truck-level arrival and locations without recording BL quantities."""
    summary = truck_guide_summary(connection, truck_guide, username, role)
    guide = summary["truck_guide"]
    try:
        incoming = float(received_packages)
    except (TypeError, ValueError):
        raise ValueError("Indica la cantidad de bultos recibidos del camión")
    if incoming <= 0:
        raise ValueError("La cantidad de bultos recibidos debe ser mayor que cero")
    planned = float(summary.get("planned_packages") or 0)
    previous = float(summary.get("received_packages") or 0)
    remaining = max(0, min(planned - previous, float(summary.get("open_expected_packages") or planned)))
    has_manifest_balance = float(summary.get("open_expected_packages") or 0) > 0
    if has_manifest_balance and incoming < remaining and not bool(additional_packages):
        raise ValueError(
            f"Debes ingresar los {remaining:g} bultos pendientes para completar el plan del camión."
        )
    if incoming > remaining and not bool(additional_packages):
        raise ValueError(
            f"Solo quedan {remaining:g} bultos pendientes para las BL abiertas. Marca el adicional para registrar excedentes."
        )
    received = previous + incoming
    if not isinstance(locations, list) or not locations:
        raise ValueError("Registra al menos una ubicación para la guía de camión")
    distribution = {}
    for item in locations:
        try:
            location = str(item.get("location") or "").strip()
            packages = float(item.get("package_count") or 0)
        except (AttributeError, TypeError, ValueError):
            raise ValueError("Una ubicación de la guía no es válida")
        if not location:
            raise ValueError("Indica la zona o ubicación de cada distribución")
        if packages <= 0:
            raise ValueError(f"Indica los bultos ubicados en {location}")
        distribution[location] = distribution.get(location, 0) + packages
    located = sum(distribution.values())
    if located > received:
        raise ValueError("Los bultos distribuidos no pueden superar los bultos recibidos del camión")
    timestamp = reception_now()
    connection.execute(
        """INSERT INTO reception_truck_arrivals
           (truck_guide, expected_packages, received_packages, notes, username, received_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(truck_guide) DO UPDATE SET
             expected_packages = excluded.expected_packages,
             received_packages = excluded.received_packages,
             notes = excluded.notes,
             username = excluded.username,
             received_at = excluded.received_at,
             updated_at = excluded.updated_at""",
        (guide, summary["expected_packages"], received, str(notes or "").strip(), username, timestamp, timestamp),
    )
    connection.executemany(
        """INSERT INTO reception_truck_locations (truck_guide, location_text, package_count)
           VALUES (?, ?, ?)
           ON CONFLICT(truck_guide, location_text) DO UPDATE SET
             package_count = reception_truck_locations.package_count + excluded.package_count""",
        [(guide, location, packages) for location, packages in distribution.items()],
    )
    # Registrar la llegada mueve exclusivamente la cabecera del camión.  No
    # crea receipts ni cambia bultos/estados de ninguna BL hija.
    _set_truck_guide_status(connection, guide, "EN_CURSO", username)
    return truck_guide_summary(connection, guide, username, role)


def enable_truck_guide_counting(connection, truck_guide, username, role):
    """Mark a tracked truck as ready; this never opens or counts a BL.

    The operation is deliberately separate from ``process_truck_arrival``:
    Operations can finish validating its physical distribution before exposing
    the individual BLs to the count screen.
    """
    summary = truck_guide_summary(connection, truck_guide, username, role)
    state = summary["guide_status"]
    if state in {"LISTA_PARA_CONTEO", "CERRADA_SIN_BULTOS"} and summary.get("steps_complete"):
        return summary
    if state not in {"EN_CURSO", "ZONA_RECEPCION"}:
        raise ValueError(
            "Registra primero la llegada y ubicación del camión antes de habilitar el conteo"
        )
    if not summary.get("steps_complete"):
        raise ValueError("Confirma la cantidad y ubicación de cada BL del manifiesto antes de habilitar el conteo")
    if any(
        (float(bl.get("received_this_truck") or 0) > 0)
        and (not str(bl.get("current_assistant") or "").strip()
             or not str(bl.get("current_auxiliary") or "").strip())
        for bl in summary["bls"] if str(bl.get("app_status") or "").upper() != "CERRADO"
    ):
        raise PermissionError(
            "Asigna un asistente y un auxiliar a cada BL recibida antes de habilitar el conteo"
        )
    _set_truck_guide_status(connection, summary["truck_guide"], "LISTA_PARA_CONTEO", username)
    return truck_guide_summary(connection, summary["truck_guide"], username, role)


def revert_truck_guide(connection, truck_guide, username, role, target_status="PENDIENTE"):
    """Undo truck stages; returning to transit unreceives only this guide's BL amounts."""
    require_reception_access(role)
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede revertir una guía de camión")
    summary = truck_guide_summary(connection, truck_guide, username, role)
    guide = summary["truck_guide"]
    target = str(target_status or "PENDIENTE").strip().upper()
    if target not in TRUCK_GUIDE_STATE_INDEX:
        raise ValueError("Etapa de guía de camión no válida")
    current = _truck_guide_status(summary)
    if TRUCK_GUIDE_STATE_INDEX[target] > TRUCK_GUIDE_STATE_INDEX[current]:
        raise ValueError("La guía solo puede regresar a una etapa anterior")
    # Moving back to either post-arrival stage preserves the physical receipt.
    # Returning all the way to transit annuls only this guide's arrivals so
    # those planned packages become available for a later truck again.
    if target == "PENDIENTE":
        arrivals = connection.execute(
            """SELECT a.*, s.bl_awb, s.expected_packages, s.received_packages,
                      s.app_status AS shipment_status
                 FROM reception_truck_bl_arrivals a
                 JOIN reception_shipments s ON s.id=a.shipment_id
                WHERE lower(a.truck_guide)=lower(?) ORDER BY a.id""",
            (guide,),
        ).fetchall()
        for arrival in arrivals:
            receipt = connection.execute(
                """SELECT * FROM reception_receipts
                    WHERE shipment_id=? AND lower(COALESCE(truck_guide,''))=lower(?)
                    ORDER BY sequence_no DESC, id DESC LIMIT 1""",
                (arrival["shipment_id"], guide),
            ).fetchone()
            attention = connection.execute(
                "SELECT * FROM reception_attentions WHERE receipt_id=? LIMIT 1",
                (receipt["id"],),
            ).fetchone() if receipt else None
            if str(arrival["shipment_status"] or "").upper() not in {"PROGRAMADO", "ARRIBADO"}:
                raise PermissionError(
                    f"La BL {arrival['bl_awb']} ya inició su conteo; reábrela a Zona de recepción antes de devolver el camión a Tránsito"
                )
            if attention and str(attention["app_status"] or "").upper() != "ARRIBADO":
                raise PermissionError(
                    f"La BL {arrival['bl_awb']} ya avanzó de Zona de recepción; reábrela a ese paso antes de anular la llegada"
                )
            if attention and connection.execute(
                "SELECT 1 FROM reception_attention_lines WHERE attention_id=? AND COALESCE(verified_qty,0)>0 LIMIT 1",
                (attention["id"],),
            ).fetchone():
                raise PermissionError(
                    f"La BL {arrival['bl_awb']} ya tiene cantidades contadas; reábrela y corrige el conteo antes de anular la llegada"
                )

            package_scan_count = int(connection.execute(
                """SELECT COUNT(*) FROM reception_truck_package_scans
                    WHERE lower(truck_guide)=lower(?) AND shipment_id=? AND scan_status='ACTIVO'""",
                (guide, int(arrival["shipment_id"])),
            ).fetchone()[0] or 0)
            if package_scan_count:
                connection.execute(
                    """UPDATE reception_truck_package_scans
                          SET scan_status='ANULADO', voided_by=?, voided_at=?,
                              void_reason='Reversión administrativa de la llegada del camión'
                        WHERE lower(truck_guide)=lower(?) AND shipment_id=? AND scan_status='ACTIVO'""",
                    (username, reception_now(), guide, int(arrival["shipment_id"])),
                )
                _write_history(
                    connection, int(arrival["shipment_id"]), "RETROCESO CAMION",
                    f"guia:{guide}:paquetes_anulados", package_scan_count, 0, username,
                    "Se anularon lecturas activas para repetir la llegada; el detalle queda en la tabla de escaneos",
                )

        for arrival in arrivals:
            shipment_id = int(arrival["shipment_id"])
            receipt = connection.execute(
                """SELECT * FROM reception_receipts
                    WHERE shipment_id=? AND lower(COALESCE(truck_guide,''))=lower(?)
                    ORDER BY sequence_no DESC, id DESC LIMIT 1""",
                (shipment_id, guide),
            ).fetchone()
            attention = connection.execute(
                "SELECT * FROM reception_attentions WHERE receipt_id=? LIMIT 1",
                (receipt["id"],),
            ).fetchone() if receipt else None
            locations = [dict(row) for row in connection.execute(
                "SELECT location_text, package_count, username, created_at FROM reception_truck_bl_locations WHERE arrival_id=? ORDER BY id",
                (arrival["id"],),
            ).fetchall()]
            snapshot = {
                "guide": guide,
                "arrival": dict(arrival),
                "locations": locations,
                "receipt": dict(receipt) if receipt else None,
                "attention_id": int(attention["id"]) if attention else None,
            }
            if receipt:
                connection.execute(
                    "UPDATE reception_receipts SET received_packages=0, location_text='', username=? WHERE id=?",
                    (username, receipt["id"]),
                )
            if attention:
                timestamp = reception_now()
                connection.execute(
                    """UPDATE reception_attentions
                          SET app_status='CERRADO', condition_status='ANULADA POR REVERSIÓN DE CAMIÓN',
                              completed_at=?, updated_at=? WHERE id=?""",
                    (timestamp, timestamp, attention["id"]),
                )
                connection.execute(
                    "UPDATE reception_attention_lines SET planned_qty=0, verified_qty=0 WHERE attention_id=?",
                    (attention["id"],),
                )
            connection.execute(
                "DELETE FROM reception_truck_bl_locations WHERE arrival_id=?", (arrival["id"],)
            )
            connection.execute(
                "DELETE FROM reception_truck_bl_arrivals WHERE id=?", (arrival["id"],)
            )

            remaining_truck_received = float(connection.execute(
                "SELECT COALESCE(SUM(received_packages),0) FROM reception_truck_bl_arrivals WHERE shipment_id=?",
                (shipment_id,),
            ).fetchone()[0] or 0)
            legacy_received = float(connection.execute(
                """SELECT COALESCE(SUM(r.received_packages),0)
                     FROM reception_receipts r
                     LEFT JOIN reception_truck_bl_arrivals a
                       ON a.shipment_id=r.shipment_id
                      AND lower(a.truck_guide)=lower(COALESCE(r.truck_guide,''))
                    WHERE r.shipment_id=? AND a.id IS NULL""",
                (shipment_id,),
            ).fetchone()[0] or 0)
            restored_received = remaining_truck_received + legacy_received
            open_attention = connection.execute(
                """SELECT app_status, condition_status FROM reception_attentions
                    WHERE shipment_id=? AND app_status<>'CERRADO'
                    ORDER BY sequence_no LIMIT 1""",
                (shipment_id,),
            ).fetchone()
            expected = max(0.0, float(arrival["expected_packages"] or 0))
            shipment_status = (
                open_attention["app_status"] if open_attention
                else "PROGRAMADO" if expected > restored_received
                else "ARRIBADO" if restored_received > 0 else "PROGRAMADO"
            )
            shipment_condition = (
                open_attention["condition_status"] if open_attention
                else "SALDO POR ARRIBAR" if expected > restored_received
                else "ARRIBO COMPLETO" if restored_received > 0 else "PENDIENTE DE ARRIBO"
            )
            connection.execute(
                """UPDATE reception_shipments
                      SET received_packages=?, app_status=?, condition_status=?, updated_at=?
                    WHERE id=?""",
                (restored_received, shipment_status, shipment_condition, reception_now(), shipment_id),
            )
            _sync_reception_line_totals(connection, shipment_id)
            _write_history(
                connection, shipment_id, "RETROCESO CAMION", f"guia:{guide}:llegada_anulada",
                json.dumps(snapshot, ensure_ascii=False, default=str),
                f"Saldo devuelto a pendiente: {float(arrival['received_packages'] or 0):g} bultos",
                username,
                "Reversión a Tránsito: se anuló solo la llegada de esta guía; las demás llegadas de la BL se conservaron",
            )
        connection.execute("DELETE FROM reception_truck_locations WHERE lower(truck_guide) = lower(?)", (guide,))
        connection.execute("DELETE FROM reception_truck_arrivals WHERE lower(truck_guide) = lower(?)", (guide,))
    timestamp = reception_now()
    connection.execute(
        """UPDATE reception_truck_guides
              SET guide_status = ?,
                  count_enabled_at = NULL,
                  count_enabled_by = NULL,
                  updated_at = ?
            WHERE lower(guide_code) = lower(?)""",
        (target, timestamp, guide),
    )
    return {"truck_guide": guide, "reverted": True, "reverted_to": target, "guide_status": target,
            "assigned_bls": summary["bl_count"]}


def start_truck_guide_bl_counting(connection, truck_guide, shipment_id, username, role):
    """Open one BL child for count after its truck guide has been enabled.

    The physical arrival already created its receipt and attention. Reuse that
    exact attention; do not create a second receipt or rewrite package counts.
    Only the BL stage and the attention for this truck arrival advance to count.
    Closed BLs are immutable and are never re-opened by a truck action.
    """
    summary = truck_guide_summary(connection, truck_guide, username, role)
    if not summary.get("counting_enabled"):
        raise ValueError("La guía de camión aún no está lista para iniciar conteo")
    try:
        selected_id = int(shipment_id)
    except (TypeError, ValueError):
        raise ValueError("Selecciona una BL/AWB válida para iniciar el conteo")
    shipment = _get_reception_shipment(connection, selected_id, username, role)
    in_manifest = connection.execute(
        "SELECT 1 FROM reception_truck_bl_manifest WHERE shipment_id=? AND lower(truck_guide)=lower(?)",
        (selected_id, summary["truck_guide"]),
    ).fetchone()
    if not in_manifest:
        raise ValueError("La BL/AWB seleccionada no pertenece a esta guía de camión")
    selected_bl = next(
        (item for item in summary["bls"] if int(item["id"]) == selected_id), None
    )
    if not selected_bl or not selected_bl.get("arrival_id"):
        raise ValueError("Confirma primero la llegada de esta BL en el camión")
    if float(selected_bl.get("received_this_truck") or 0) <= 0:
        raise ValueError("Esta BL recibió 0 bultos en este camión y no tiene conteo que iniciar")
    located = sum(float(item["package_count"] or 0) for item in selected_bl.get("locations", []))
    if located != float(selected_bl.get("received_this_truck") or 0):
        raise ValueError("Completa la ubicación de todos los bultos de esta BL antes del conteo")
    current = str(shipment["app_status"] or "").strip().upper()
    truck_receipt = connection.execute(
        """SELECT r.id AS receipt_id, a.id AS attention_id, a.app_status AS attention_status
             FROM reception_receipts r
             LEFT JOIN reception_attentions a ON a.receipt_id = r.id
            WHERE r.shipment_id = ? AND lower(COALESCE(r.truck_guide, '')) = lower(?)
            ORDER BY r.sequence_no DESC LIMIT 1""",
        (selected_id, summary["truck_guide"]),
    ).fetchone()
    task_status = (
        str(truck_receipt["attention_status"] or "ARRIBADO").strip().upper()
        if truck_receipt and truck_receipt["attention_id"] else current
    )
    if task_status == "CERRADO":
        raise ValueError("La atención de esta llegada ya está cerrada")
    if task_status in {"PROGRAMADO", "ARRIBADO"}:
        if truck_receipt:
            # Every physical arrival owns its own attention; other arrivals
            # for this BL may stay open and progress independently.
            if truck_receipt["attention_id"] and truck_receipt["attention_status"] == "CERRADO":
                raise ValueError("La atención de esta llegada ya está cerrada")
            attention_id = int(truck_receipt["attention_id"]) if truck_receipt["attention_id"] else None
        else:
            # Compatibility path for a clean BL where an older UI enabled the
            # guide without creating a per-BL receipt. Never absorb legacy
            # receipts or package totals into the truck arrival.
            has_receipt = connection.execute(
                "SELECT 1 FROM reception_receipts WHERE shipment_id = ? LIMIT 1",
                (selected_id,),
            ).fetchone()
            if has_receipt or float(shipment["received_packages"] or 0) != 0:
                raise ValueError(
                    "La BL/AWB ya tiene recepción histórica sin desglose para esta guía; conserva su flujo histórico"
                )
            attention_id = None
        timestamp = reception_now()
        connection.execute(
            """UPDATE reception_shipments
                  SET app_status = 'REVISION SISTEMA',
                      condition_status = 'CONTEO HABILITADO POR GUIA DE CAMION',
                      updated_at = ?
                WHERE id = ?""",
            (timestamp, selected_id),
        )
        if attention_id is not None:
            connection.execute(
                """UPDATE reception_attentions
                      SET app_status = 'REVISION SISTEMA', condition_status = 'EN PROCESO', updated_at = ?
                    WHERE id = ?""",
                (timestamp, attention_id),
            )
            primary_attention = _active_reception_attention(connection, selected_id)
            if primary_attention:
                connection.execute(
                    "UPDATE reception_shipments SET app_status = ?, condition_status = ?, updated_at = ? WHERE id = ?",
                    (primary_attention["app_status"], primary_attention["condition_status"], timestamp, selected_id),
                )
        _write_history(
            connection,
            selected_id,
            "GUIA CAMION",
            "app_status",
            current,
            "REVISION SISTEMA",
            username,
            f"Conteo habilitado por guía de camión {summary['truck_guide']}; sin registrar recepción ni cantidades",
        )
        if attention_id is None:
            refreshed = connection.execute(
                "SELECT * FROM reception_shipments WHERE id = ?", (selected_id,)
            ).fetchone()
            if truck_receipt:
                _create_reception_attention(
                    connection, refreshed, int(truck_receipt["receipt_id"]), username, "REVISION SISTEMA"
                )
            else:
                _ensure_reception_attention(connection, refreshed, username)
        started = True
    elif task_status == "REVISION SISTEMA":
        if truck_receipt and truck_receipt["attention_id"]:
            if truck_receipt["attention_status"] == "CERRADO":
                raise ValueError("La atención de esta llegada ya está cerrada")
            connection.execute(
                """UPDATE reception_attentions
                      SET app_status = 'REVISION SISTEMA', condition_status = 'EN PROCESO', updated_at = ?
                    WHERE id = ? AND app_status <> 'CERRADO'""",
                (reception_now(), int(truck_receipt["attention_id"])),
            )
            started = False
        elif truck_receipt:
            refreshed = connection.execute(
                "SELECT * FROM reception_shipments WHERE id = ?", (selected_id,)
            ).fetchone()
            _create_reception_attention(
                connection, refreshed, int(truck_receipt["receipt_id"]), username, "REVISION SISTEMA"
            )
            started = True
        else:
            # Idempotencia: no crea recepciones ni vuelve a escribir cantidades.
            started = False
    else:
        raise ValueError(
            "La BL/AWB ya avanzó después del conteo; consulta su detalle para continuar"
        )
    return {
        "truck_guide": summary["truck_guide"],
        "shipment_id": selected_id,
        "bl_awb": shipment["bl_awb"],
        "counting_started": started,
        "guide_status": summary["guide_status"],
        "shipment": reception_detail(connection, selected_id, role, username),
    }


def update_reception_line_quantity(connection, shipment_id, line_id, data, username, role):
    shipment = _get_reception_shipment(connection, shipment_id, username, role)
    attention = _ensure_reception_attention(connection, shipment, username)
    attention = _active_reception_attention(connection, shipment_id, data.get("attention_id")) or attention
    task_status = attention["app_status"] if data.get("attention_id") and attention else shipment["app_status"]
    if task_status != "REVISION SISTEMA":
        raise PermissionError("Las cantidades verificadas solo se modifican durante REVISIÓN DE SISTEMA")
    line = connection.execute(
        "SELECT * FROM reception_lines WHERE id = ? AND shipment_id = ?",
        (line_id, shipment_id),
    ).fetchone()
    if not line:
        raise ValueError("Línea NP no encontrada")
    received_qty = float(data.get("received_qty") or 0)
    if received_qty < 0:
        raise ValueError("La cantidad recibida no puede ser negativa")
    reason = str(data.get("reason") or "").strip()
    attention_line = None
    if attention:
        attention_line = connection.execute(
            "SELECT * FROM reception_attention_lines WHERE attention_id = ? AND reception_line_id = ?",
            (attention["id"], line_id),
        ).fetchone()
    # El esperado es el valor inicial de conteo, no un tope. El físico puede
    # traer faltantes o excedentes y ambos deben registrarse para que el
    # reporte muestre la diferencia y se notifique a Importaciones.
    old_qty = float(attention_line["verified_qty"] or 0) if attention_line else float(line["received_qty"] or 0)
    if attention_line:
        connection.execute(
            "UPDATE reception_attention_lines SET verified_qty = ? WHERE id = ?",
            (received_qty, attention_line["id"]),
        )
        # Una edición explícita confirma que esta atención ya fue inicializada
        # y evita volver a mostrar el esperado como valor predeterminado en
        # una siguiente consulta.
        connection.execute(
            "UPDATE reception_attentions SET system_quantities_initialized = 1 WHERE id = ?",
            (attention["id"],),
        )
    connection.execute(
        "UPDATE reception_lines SET blocked_reason = ? WHERE id = ?",
        (reason, line_id),
    )
    _sync_reception_line_totals(connection, shipment_id)
    _write_history(
        connection,
        shipment_id,
        "REVISION SISTEMA",
        f"linea:{line_id}:received_qty",
        old_qty,
        received_qty,
        username,
        reason,
    )
    if reason or received_qty != float(line["expected_qty"] or 0):
        _enqueue_notification(
            connection,
            shipment_id,
            "OBSERVACION_IMPORTACIONES",
            f"Observación en revisión de sistema · BL/AWB {shipment['bl_awb']}",
            (
                f"BL/AWB: {shipment['bl_awb']}\n"
                f"NP: {line['np_code'] or '—'}\n"
                f"Descripción: {line['description'] or '—'}\n"
                f"OC: {line['oc_number'] or '—'} · OV: {line['ov_number'] or '—'}\n"
                f"Esperado: {line['expected_qty']} · Verificado: {received_qty}\n"
                f"Observación: {reason or 'Diferencia detectada'}\n"
                f"Registrado por: {username}"
            ),
            "TRITON_IMPORTACIONES_EMAILS",
            "sgallo@triton.com.pe;claudia.acedo@triton.com.pe;jorge.cucho@triton.com.pe;pfigueroa@triton.com.pe",
        )
    return reception_detail(connection, shipment_id, role, username, data.get("attention_id"))


def change_reception_status(connection, shipment_id, data, username, role):
    shipment = _get_reception_shipment(connection, shipment_id, username, role)
    attention = _ensure_reception_attention(connection, shipment, username)
    attention = _active_reception_attention(connection, shipment_id, data.get("attention_id")) or attention
    old_status = (
        attention["app_status"]
        if data.get("attention_id") and attention
        else shipment["app_status"]
    )
    new_status = str(data.get("status") or "").strip().upper()
    if new_status not in RECEPTION_STATE_INDEX:
        raise ValueError("Estado de recepción no válido")

    validation_result = str(data.get("validation_result") or "").strip().upper()
    if old_status == "VALIDACION" and validation_result == "NO CONFORME":
        new_status = "UBICACION"
        condition = "REUBICACION REQUERIDA"
        connection.execute(
            "UPDATE reception_shipments SET app_status = ?, condition_status = ?, updated_at = ? WHERE id = ?",
            (new_status, condition, reception_now(), shipment_id),
        )
        if attention:
            connection.execute(
                "UPDATE reception_attentions SET app_status = ?, condition_status = ?, updated_at = ? WHERE id = ?",
                (new_status, condition, reception_now(), attention["id"]),
            )
        _write_history(
            connection, shipment_id, "VALIDACION", "app_status", old_status, new_status,
            username, "Muestra de ubicación no conforme; se exige nueva ubicación y nueva muestra",
        )
        return reception_detail(connection, shipment_id, role)

    expected_next = RECEPTION_STATE_INDEX[old_status] + 1
    if RECEPTION_STATE_INDEX[new_status] != expected_next:
        raise PermissionError("El flujo de recepción debe avanzar una etapa a la vez")
    if old_status == "UBICACION" and new_status == "VALIDACION":
        if attention:
            missing_final_locations = connection.execute(
                """SELECT COUNT(*)
                     FROM reception_attention_lines al
                     JOIN reception_lines l ON l.id = al.reception_line_id
                    WHERE al.attention_id = ?
                      AND (COALESCE(al.planned_qty, 0) > 0 OR COALESCE(al.verified_qty, 0) > 0)
                      AND (COALESCE(l.final_location_confirmed, 0) = 0
                           OR TRIM(COALESCE(l.final_location, '')) = '')""",
                (attention["id"],),
            ).fetchone()[0]
        else:
            missing_final_locations = connection.execute(
                """SELECT COUNT(*) FROM reception_lines
                    WHERE shipment_id = ? AND COALESCE(received_qty, 0) > 0
                      AND (COALESCE(final_location_confirmed, 0) = 0
                           OR TRIM(COALESCE(final_location, '')) = '')""",
                (shipment_id,),
            ).fetchone()[0]
        if missing_final_locations:
            raise PermissionError(
                "Confirma la ubicación final de cada NP de esta llegada antes de pasar a validación"
            )
    expected_packages = float(shipment["expected_packages"] or 0)
    received_packages = float(shipment["received_packages"] or 0)
    # El saldo de bultos no bloquea el trabajo previo: pueden existir arribos
    # acumulados y el trabajador puede revisar lo disponible. La ventana de
    # bultos permanece abierta hasta que el usuario la cierre explícitamente.
    # Consultar las referencias actuales evita aceptar una FR parcial por IP
    # o depender de un resumen contable desactualizado. No modifica la BD.
    accounting_status = _accounting_status_for_shipment(connection, shipment_id, shipment)
    if new_status == "EM" and accounting_status == "PENDIENTE CONTABILIDAD":
        raise PermissionError(
            "Registra la factura de reserva de las IP con SKU ingresado antes de pasar a EM"
        )
    if new_status == "EM" and accounting_status == "PENDIENTE FR":
        eligible_fr = connection.execute(
            """SELECT * FROM reception_accounting_refs
               WHERE shipment_id = ? AND trim(COALESCE(fr_number, '')) <> ''""",
            (shipment_id,),
        ).fetchall()
        fr_ip_keys = {
            ip_key
            for reference in eligible_fr
            for ip_key in _ip_tokens(reference["ip_reference"])
        }
        received_lines = connection.execute(
            "SELECT ip_reference FROM reception_lines WHERE shipment_id = ? AND received_qty > 0",
            (shipment_id,),
        ).fetchall()
        ambiguous_line = any(
            bool(set(_ip_tokens(line["ip_reference"])) & fr_ip_keys)
            and bool(set(_ip_tokens(line["ip_reference"])) - fr_ip_keys)
            for line in received_lines
        )
        if ambiguous_line or not any(
            _accounting_ref_has_received_sku(connection, shipment_id, reference)
            for reference in eligible_fr
        ):
            raise PermissionError(
                "Registra la factura de reserva de las IP con SKU ingresado antes de pasar a EM"
            )
    if new_status == "EM":
        received_sku = connection.execute(
            "SELECT 1 FROM reception_lines WHERE shipment_id = ? AND received_qty > 0 LIMIT 1",
            (shipment_id,),
        ).fetchone()
        if not received_sku:
            raise PermissionError(
                "Registra primero al menos un SKU encontrado para habilitar la EM de su IP"
            )
    if new_status == "REVISION SISTEMA":
        if not str(shipment["current_assistant"] or "").strip() or not str(shipment["current_auxiliary"] or "").strip():
            raise PermissionError(
                "Asigna un asistente y un auxiliar de recepción antes de iniciar la revisión de sistema"
            )
        if data.get("require_location"):
            guide = str(shipment["truck_guide"] or "").strip()
            current_receipt = connection.execute(
                """SELECT * FROM reception_receipts
                    WHERE shipment_id=? AND received_packages > 0
                      AND (?='' OR lower(COALESCE(truck_guide,''))=lower(?))
                    ORDER BY sequence_no DESC, id DESC LIMIT 1""",
                (shipment_id, guide, guide),
            ).fetchone()
            # La ubicación es informativa. Se mantiene únicamente la regla
            # que evita saltar una atención previa aún abierta.
            if (current_receipt and attention and attention["app_status"] != "CERRADO"
                    and attention["receipt_id"] != current_receipt["id"]):
                raise PermissionError(
                    "Hay una atención anterior abierta; complétala antes de iniciar la siguiente"
                )
    if new_status == "EM" and accounting_status == "CONFLICTO IP":
        raise PermissionError(
            "La BL tiene una IP relacionada con más de una FR/EM; corrige el Excel contable antes de pasar a EM"
        )
    if new_status == "REVISION SISTEMA" and accounting_status == "EM REGISTRADA" and not (
        attention and old_status == "ARRIBADO"
    ):
        raise PermissionError("La BL ya tiene EM registrada; no requiere trabajo de recepción")
    if new_status == "UBICACION" and not str(shipment["em_number"] or "").strip():
        allow_pending_em = bool(data.get("allow_pending_em"))
        pending_em_status = _accounting_status_for_shipment(connection, shipment_id, shipment)
        received_in_attention = 0
        if attention:
            received_in_attention = connection.execute(
                """SELECT COALESCE(SUM(verified_qty), 0)
                     FROM reception_attention_lines WHERE attention_id = ?""",
                (attention["id"],),
            ).fetchone()[0]
        if not (
            allow_pending_em
            and old_status == "EM"
            and pending_em_status == "PENDIENTE EM"
            and float(received_in_attention or 0) > 0
        ):
            raise PermissionError("Registra la EM o elige continuar con los NP disponibles")
    if old_status == "VALIDACION" and validation_result != "CONFORME":
        raise PermissionError("Indica si la muestra de ubicación fue CONFORME o NO CONFORME")
    if old_status == "VALIDACION" and validation_result == "CONFORME":
        sample_ids = _validation_sample_ids(connection, shipment_id)
        if sample_ids:
            placeholders = ",".join("?" for _ in sample_ids)
            sample_rows = connection.execute(
                f"SELECT validation_sap_checked, validation_location_checked, validation_comment_checked, blocked_reason "
                f"FROM reception_lines WHERE shipment_id = ? AND id IN ({placeholders})",
                [shipment_id, *sample_ids],
            ).fetchall()
            if any(not row["validation_location_checked"] for row in sample_rows):
                raise PermissionError("Completa el check de ubicación de toda la muestra")
    if new_status == "CERRADO" and not int(shipment["transfer_assistant_checked"] or 0):
        raise PermissionError("La solicitud de transferencia debe ser revisada y marcada antes de cerrar")

    condition = "EN PROCESO" if new_status != "CERRADO" else "COMPLETADO"
    shipment_status = new_status
    shipment_condition = condition
    if new_status == "CERRADO" and connection.execute(
        "SELECT 1 FROM reception_truck_bl_arrivals WHERE shipment_id = ? LIMIT 1",
        (shipment_id,),
    ).fetchone():
        package_balance = truck_bl_package_balance(connection, shipment_id)
        queued_receipt = connection.execute(
            """SELECT 1 FROM reception_receipts r
                 WHERE r.shipment_id = ? AND COALESCE(r.received_packages, 0) > 0
                   AND COALESCE(TRIM(r.truck_guide), '') <> ''
                   AND NOT EXISTS (SELECT 1 FROM reception_attentions a WHERE a.receipt_id = r.id)
                 LIMIT 1""",
            (shipment_id,),
        ).fetchone()
        if float(package_balance["pending_packages"] or 0) > 0 or queued_receipt:
            # Se cierra esta atención, no el expediente BL: aún quedan bultos
            # esperados por llegar o una llegada física que aún espera su turno.
            shipment_status = "ARRIBADO"
            shipment_condition = (
                "SALDO POR ARRIBAR" if float(package_balance["pending_packages"] or 0) > 0
                else "OTRA ATENCION PENDIENTE"
            )
    # La inicialización pertenece a cada atención, no a la BL completa. Una
    # BL puede tener Atención 1 cerrada y una nueva llegada (Atención 2); la
    # segunda también debe arrancar con su esperado al 100% aunque la BL ya
    # haya pasado antes por revisión de sistema.
    attention_initialized = (
        int(attention["system_quantities_initialized"] or 0)
        if attention else int(shipment["system_quantities_initialized"] or 0)
    )
    initialize_system = new_status == "REVISION SISTEMA" and not attention_initialized
    if initialize_system:
        if attention:
            connection.execute(
                "UPDATE reception_attention_lines SET verified_qty = planned_qty WHERE attention_id = ?",
                (attention["id"],),
            )
            connection.execute(
                "UPDATE reception_attentions SET system_quantities_initialized = 1 WHERE id = ?",
                (attention["id"],),
            )
            _sync_reception_line_totals(connection, shipment_id)
        else:
            connection.execute(
                "UPDATE reception_lines SET received_qty = expected_qty WHERE shipment_id = ?",
                (shipment_id,),
            )
        connection.execute(
            """UPDATE reception_shipments
               SET app_status = ?, condition_status = ?, system_quantities_initialized = 1, updated_at = ?
               WHERE id = ?""",
            (shipment_status, shipment_condition, reception_now(), shipment_id),
        )
        line_count = connection.execute(
            "SELECT COUNT(*) FROM reception_lines WHERE shipment_id = ?", (shipment_id,)
        ).fetchone()[0]
        _write_history(
            connection,
            shipment_id,
            "INICIALIZACION",
            "cantidades_revision_sistema",
            0,
            "100%",
            username,
            f"{line_count} líneas inicializadas al 100% al iniciar revisión de sistema",
        )
    else:
        connection.execute(
            "UPDATE reception_shipments SET app_status = ?, condition_status = ?, updated_at = ? WHERE id = ?",
            (shipment_status, shipment_condition, reception_now(), shipment_id),
        )
    if attention:
        timestamp = reception_now()
        connection.execute(
            """UPDATE reception_attentions
                  SET app_status = ?, condition_status = ?,
                      updated_at = ?, completed_at = CASE WHEN ? = 'CERRADO' THEN ? ELSE completed_at END
                WHERE id = ?""",
            (new_status, condition, timestamp, new_status, timestamp, attention["id"]),
        )
        primary_attention = _active_reception_attention(connection, shipment_id)
        primary_status = primary_attention["app_status"] if primary_attention else new_status
        primary_condition = primary_attention["condition_status"] if primary_attention else condition
        connection.execute(
            "UPDATE reception_shipments SET app_status = ?, condition_status = ?, updated_at = ? WHERE id = ?",
            (primary_status, primary_condition, timestamp, shipment_id),
        )
    _write_history(
        connection, shipment_id, "ESTADO", "app_status", old_status, shipment_status, username,
        (
            "Continuó con los NP disponibles; la referencia sin EM queda pendiente"
            if new_status == "UBICACION" and data.get("allow_pending_em")
            else "Atención cerrada; queda saldo físico de bultos por arribar"
            if shipment_status != new_status else ""
        ),
    )
    if old_status == "REVISION SISTEMA" and new_status == "EM" and advanced_lots_enabled():
        created_lots = generate_lots_for_shipment(connection, shipment_id, username)
        _write_history(
            connection,
            shipment_id,
            "LOTES",
            "lotes_generados",
            0,
            len(created_lots),
            username,
            "Lotes internos generados con las cantidades verificadas",
        )
    if old_status == "VALIDACION" and new_status == "SOLICITUD TRANSFERENCIA":
        already_requested = connection.execute(
            """SELECT 1 FROM reception_notifications
               WHERE shipment_id = ? AND notification_type = 'SOLICITUD_TRANSFERENCIA'
               LIMIT 1""",
            (shipment_id,),
        ).fetchone()
        if not already_requested:
            _enqueue_notification(
                connection,
                shipment_id,
                "SOLICITUD_TRANSFERENCIA",
                f"Solicitud de transferencia IMP a 01 · BL/AWB {shipment['bl_awb']}",
                (
                    f"BL/AWB: {shipment['bl_awb']}\n"
                    f"EM: {shipment['em_number'] or '—'}\n"
                    "La validación de ubicación fue CONFORME. Solicitud de transferencia de IMP a 01.\n"
                    f"Registrado por: {username}"
                ),
                "TRITON_CONTABILIDAD_EMAILS",
                "mpucurimay@triton.com.pe",
            )
    return reception_detail(connection, shipment_id, role, username, data.get("attention_id"))


def mark_reception_arrived(connection, shipment_id, username, role):
    """Register an administrative arrival without creating a receipt yet.

    A shipment with no physical arrival date remains visible in ``En curso``
    as pending arrival.  Only the administrator may confirm that it arrived;
    the worker still records packages in the normal Llegada step afterwards.
    This deliberately does not create a receipt or initialize quantities.
    """
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede confirmar el arribo")
    shipment = _get_reception_shipment(connection, shipment_id, username, role)
    if str(shipment["truck_guide"] or "").strip():
        raise PermissionError("Esta BL pertenece a una guía de camión; confirma la llegada en la guía")
    current_status = str(shipment["app_status"] or "PROGRAMADO").strip().upper()
    if current_status == "CERRADO":
        raise ValueError("La BL ya está cerrada")
    if RECEPTION_STATE_INDEX.get(current_status, 0) > RECEPTION_STATE_INDEX["ARRIBADO"]:
        raise PermissionError("La BL ya avanzó después de la llegada")
    timestamp = reception_now()
    if current_status == "ARRIBADO" and str(shipment["first_arrival_at"] or "").strip():
        return reception_detail(connection, shipment_id, role)
    connection.execute(
        """UPDATE reception_shipments
              SET app_status = 'ARRIBADO', condition_status = 'ARRIBO REGISTRADO',
                  first_arrival_at = COALESCE(NULLIF(first_arrival_at, ''), ?),
                  updated_at = ?
            WHERE id = ?""",
        (timestamp, timestamp, shipment_id),
    )
    _write_history(
        connection,
        shipment_id,
        "ARRIBO ADMINISTRATIVO",
        "app_status",
        current_status,
        "ARRIBADO",
        username,
        "Confirmación administrativa de llegada; pendiente de registrar bultos",
    )
    return reception_detail(connection, shipment_id, role)


def rewind_reception_stage(connection, shipment_id, data, username, role):
    """Reopen a completed reception stage for an administrator.

    Workers can navigate to prior stages only as read-only. This separate
    operation keeps the normal forward-only workflow intact and records the
    administrative reason without deleting the existing audit trail.
    """
    shipment = _get_reception_shipment(connection, shipment_id, username, role)
    if role != "ADMINISTRADOR":
        raise PermissionError("Solo el administrador puede reabrir una etapa")

    attention = _active_reception_attention(
        connection, shipment_id, data.get("attention_id")
    )
    current_status = str(
        attention["app_status"] if attention else shipment["app_status"] or "PROGRAMADO"
    )
    target_status = str(data.get("status") or "").strip().upper()
    if target_status not in RECEPTION_STATE_INDEX:
        raise ValueError("Etapa de reapertura no válida")
    if RECEPTION_STATE_INDEX[target_status] >= RECEPTION_STATE_INDEX[current_status]:
        raise PermissionError("La reapertura debe devolver la BL a una etapa anterior")

    reason = str(data.get("reason") or "").strip()
    if len(reason) < 5:
        raise ValueError("Indica el motivo de la reapertura")
    if target_status == "PROGRAMADO" and (
        float(shipment["received_packages"] or 0) > 0
        or connection.execute(
            "SELECT 1 FROM reception_receipts WHERE shipment_id = ? LIMIT 1",
            (shipment_id,),
        ).fetchone()
    ):
        raise PermissionError(
            "No se puede devolver a PROGRAMADO porque la BL ya tiene bultos registrados"
        )

    timestamp = reception_now()
    target_condition = {
        "PROGRAMADO": "POR ARRIBAR",
        "ARRIBADO": "ARRIBO REGISTRADO",
    }.get(target_status, "EN PROCESO")
    connection.execute(
        """UPDATE reception_shipments
           SET app_status = ?, condition_status = ?,
               validation_sample_json = CASE WHEN ? < ? THEN NULL ELSE validation_sample_json END,
               transfer_assistant_checked = CASE WHEN ? < ? THEN 0 ELSE transfer_assistant_checked END,
               system_quantities_initialized = CASE WHEN ? < ? THEN 0 ELSE system_quantities_initialized END,
               updated_at = ?
         WHERE id = ?""",
        (
            target_status,
            target_condition,
            RECEPTION_STATE_INDEX[target_status],
            RECEPTION_STATE_INDEX["VALIDACION"],
            RECEPTION_STATE_INDEX[target_status],
            RECEPTION_STATE_INDEX["SOLICITUD TRANSFERENCIA"],
            RECEPTION_STATE_INDEX[target_status],
            RECEPTION_STATE_INDEX["REVISION SISTEMA"],
            timestamp,
            shipment_id,
        ),
    )

    # Reset only controls that belong to stages after the selected reopening
    # point. The physical receipt and its manual location remain evidence.
    if RECEPTION_STATE_INDEX[target_status] < RECEPTION_STATE_INDEX["VALIDACION"]:
        connection.execute(
            """UPDATE reception_lines
               SET validation_sap_checked = 0,
                   validation_location_checked = 1,
                   validation_comment_checked = 0
             WHERE shipment_id = ?""",
            (shipment_id,),
        )
    if attention:
        target_index = RECEPTION_STATE_INDEX[target_status]
        if target_status == "REVISION SISTEMA":
            attention_system_init = 1
        elif target_index < RECEPTION_STATE_INDEX["REVISION SISTEMA"]:
            attention_system_init = 0
        else:
            attention_system_init = int(attention["system_quantities_initialized"] or 0)
        attention_transfer_check = (
            0
            if RECEPTION_STATE_INDEX[target_status] < RECEPTION_STATE_INDEX["SOLICITUD TRANSFERENCIA"]
            else int(attention["transfer_assistant_checked"] or 0)
        )
        connection.execute(
            """UPDATE reception_attentions
               SET app_status = ?, condition_status = ?,
                   system_quantities_initialized = ?,
                   transfer_assistant_checked = ?,
                   completed_at = NULL, updated_at = ?
             WHERE id = ?""",
            (
                target_status,
                target_condition,
                attention_system_init,
                attention_transfer_check,
                timestamp,
                attention["id"],
            ),
        )
        if RECEPTION_STATE_INDEX[target_status] < RECEPTION_STATE_INDEX["REVISION SISTEMA"]:
            connection.execute(
                "UPDATE reception_attention_lines SET verified_qty = 0 WHERE attention_id = ?",
                (attention["id"],),
            )
        elif target_status == "REVISION SISTEMA":
            connection.execute(
                "UPDATE reception_attention_lines SET verified_qty = planned_qty WHERE attention_id = ?",
                (attention["id"],),
            )

    _write_history(
        connection,
        shipment_id,
        "RETROCESO_ADMIN",
        "app_status",
        current_status,
        target_status,
        username,
        reason,
    )
    return reception_detail(
        connection,
        shipment_id,
        role,
        username,
        int(attention["id"]) if attention else None,
    )
