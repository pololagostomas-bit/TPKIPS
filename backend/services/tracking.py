"""Internal document tracking: allowlisted snapshots and read-only warehouse evidence."""
from collections import Counter, defaultdict
import hashlib
import json
import math
from datetime import datetime, timezone

from backend.services.reception import _cell_text, _find_column, _normalize_header, _row_value
from backend.services.reception_projection import SHIPMENT_CTE, project_shipment
from backend.services.reception_work import _timing
from backend.services.reception_source_bl import ov_key

ROLE = 'CONSULTA_TRACKING'
MAX_DOCUMENT_LINES = 2000
DATES = {'request': 'FECHA DE SOLICITUD DE IMP OV', 'order': 'FECHA DE PEDIDO',
         'invoice': 'FECHA DE FACTURA', 'pickup': 'FECHA RECOJO', 'callao': 'FECHA CALLAO',
         'estimated': 'FECHA TRITON ESTIMADA', 'confirmed': 'FECHA CONFIRMADA TRITON',
         'costing': 'FECHA COSTEO'}
FIELDS = {'ov': ('OV', 'ORDEN DE VENTA', 'OV/ORDEN DE VENTA'), 'oc': ('ORDEN DE COMPRA',),
          'item': ('CODIGO',), 'bl': ('GUIA DE IMPORTACION',), 'description': ('DESCRIPCION',),
          'brand': ('MARCA',), 'requested_qty': ('CANTIDAD SOLICITADA',),
          'invoiced_qty': ('CANTIDAD FACTURADA',), 'pending_qty': ('CANTIDAD PENDIENTE',),
          'triton_order': ('PEDIDO TRITON',), 'factory_order': ('PEDIDO FABRICA',),
          'invoice': ('N° FACTURA', 'Nº FACTURA', 'N FACTURA'),
          'transport': ('MODO DE TRANSPORTE',), 'source_status': ('STATUS',),
          'item_status': ('ESTADO POR NP',)}


def init_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS tracking_source (
        id INTEGER PRIMARY KEY CHECK(id=1), loaded_at TEXT, cutoff_at TEXT,
        filename TEXT, warning TEXT, sheets TEXT NOT NULL DEFAULT '[]')''')
    db.execute('''CREATE TABLE IF NOT EXISTS tracking_lines (
        identity TEXT PRIMARY KEY, ov TEXT NOT NULL, oc TEXT NOT NULL,
        sheet TEXT NOT NULL, source_row INTEGER NOT NULL, payload TEXT NOT NULL,
        present INTEGER NOT NULL DEFAULT 1)''')
    for field in ('ov', 'oc'):
        db.execute(f'CREATE INDEX IF NOT EXISTS tracking_{field} ON tracking_lines({field})')
    db.execute('INSERT OR IGNORE INTO tracking_source(id,warning) VALUES(1,?)',
               ('Pendiente del primer corte de Importaciones',))


def _quantity(value):
    if value in (None, ''):
        return None
    number = float(str(value).replace(',', '').replace(' ', ''))
    if not math.isfinite(number) or number < 0:
        raise ValueError('Cantidad no válida')
    return number


def _read(workbook):
    records, sheets, occurrences = [], {}, {}
    for sheet in workbook.worksheets:
        indexes = None
        for row_number, row in enumerate(sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 20), values_only=True), 1):
            headers = [_normalize_header(value) for value in row]
            candidate = {name: _find_column(headers, *aliases) for name, aliases in FIELDS.items()}
            if all(candidate[name] is not None for name in ('ov', 'oc', 'item', 'bl')):
                indexes = candidate
                date_indexes = {name: _find_column(headers, alias) for name, alias in DATES.items()}
                break
        if indexes is None:
            continue
        sheets[sheet.title] = [key for key, index in {**indexes, **date_indexes}.items() if index is not None]
        for source_row, row in enumerate(sheet.iter_rows(min_row=row_number + 1, values_only=True), row_number + 1):
            record = {name: (_quantity(_row_value(row, index)) if name.endswith('_qty') else
                             _cell_text(_row_value(row, index))) for name, index in indexes.items()}
            record['ov'] = ov_key(record['ov'])
            if not (record['ov'] or record['oc']):
                continue
            record['dates'] = {name: _cell_text(_row_value(row, index)) or None for name, index in date_indexes.items()}
            key = json.dumps([sheet.title] + [record[name] for name in ('ov', 'oc', 'bl', 'item', 'triton_order')], ensure_ascii=False)
            occurrences[key] = occurrences.get(key, 0) + 1
            identity = hashlib.sha256(f'{key}|{occurrences[key]}'.encode()).hexdigest()
            records.append((identity, record['ov'], record['oc'], sheet.title, source_row, json.dumps(record, ensure_ascii=False)))
    return records, sheets


def store_workbook(db, workbook, filename, cutoff=None):
    init_schema(db)
    previous = db.execute('SELECT sheets FROM tracking_source WHERE id=1').fetchone()
    try:
        records, sheets = _read(workbook)
        previous_sheets = json.loads(previous[0])
        if (not records or not set(previous_sheets).issubset(sheets)
                or (isinstance(previous_sheets, dict) and any(
                    not set(columns).issubset(sheets.get(name, [])) for name, columns in previous_sheets.items()))):
            raise ValueError('Corte vacío o faltan hojas del corte anterior')
    except (ValueError, TypeError, OverflowError):
        db.execute('UPDATE tracking_source SET warning=? WHERE id=1',
                   ('Se conserva el último corte válido: fuente incompleta o no válida',))
        return False
    # A savepoint keeps the caller's transaction intact, including reception writes.
    db.execute('SAVEPOINT tracking_snapshot')
    try:
        db.execute('UPDATE tracking_lines SET present=0')
        db.executemany('''INSERT INTO tracking_lines(identity,ov,oc,sheet,source_row,payload,present)
            VALUES(?,?,?,?,?,?,1) ON CONFLICT(identity) DO UPDATE SET
            source_row=excluded.source_row,payload=excluded.payload,present=1''', records)
        db.execute('UPDATE tracking_source SET loaded_at=?,cutoff_at=?,filename=?,warning=NULL,sheets=? WHERE id=1',
                   (datetime.now(timezone.utc).isoformat(), _cell_text(cutoff) or None,
                    str(filename), json.dumps(sheets)))
        db.execute('RELEASE tracking_snapshot')
    except Exception:
        db.execute('ROLLBACK TO tracking_snapshot')
        db.execute('RELEASE tracking_snapshot')
        raise
    return True


def _stage(line):
    received = line['received_qty']
    expected = line['requested_qty']
    if received is not None and received > 0:
        if expected is None or received + 1e-9 < expected:
            return 'Recepción parcial'
        if line['transferred']:
            return 'Atención de almacén completada'
        if line['location']:
            return 'Ubicado'
        return 'Recibido'
    for field, label in [('callao', 'Callao informado'), ('pickup', 'Recojo informado'),
                         ('invoice', 'Factura informada'), ('order', 'Pedido informado')]:
        if line['dates'][field]:
            return label
    return 'Datos por confirmar'


def search(db, kind, number, offset=0, limit=50):
    kind, number = str(kind).strip().upper(), _cell_text(number)
    if kind == 'OV':
        number = ov_key(number)
    if kind not in {'OV', 'OC'} or not number or len(number) > 100:
        raise ValueError('Documento de Tracking no válido')
    offset, limit = max(0, int(offset)), max(1, min(100, int(limit)))
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    source = dict(db.execute('SELECT loaded_at,cutoff_at,warning,filename FROM tracking_source WHERE id=1').fetchone()) if 'tracking_source' in tables else {
        'loaded_at': None, 'cutoff_at': None, 'filename': None, 'warning': 'Pendiente del primer corte de Importaciones'}
    if 'cloud_sync_status' in tables:
        sync = db.execute("SELECT state,checked_at FROM cloud_sync_status WHERE source_type='importation'").fetchone()
        if sync:
            source.update(sync_state=sync['state'], sync_checked_at=sync['checked_at'])
            if str(sync['state']).upper() in {'ERROR', 'BLOCKED'}:
                source['warning'] = source['warning'] or 'La última sincronización de Importaciones falló; se conserva el último corte válido'
    rows = []
    if 'tracking_lines' in tables:
        counts = db.execute(f'SELECT COUNT(*),SUM(present) FROM tracking_lines WHERE {kind.lower()}=?', (number,)).fetchone()
        current = bool(counts[1])
        if (counts[1] if current else counts[0]) > MAX_DOCUMENT_LINES:
            raise ValueError('El documento excede el límite de líneas de Tracking; requiere revisión de Importaciones')
        rows = db.execute(f'SELECT * FROM tracking_lines WHERE {kind.lower()}=? AND (?=0 OR present=1) ORDER BY sheet,source_row,identity', (number, int(current))).fetchall()
    evidence = {}
    if rows and 'reception_lines' in tables:
        # Only an exact, unique documentary line can supply warehouse facts.
        evidence = {(r['source_sheet'], r['bl_awb'], ov_key(r['ov_number']), r['oc_number'], r['np_code'], r['ip_reference']): dict(r)
                    for r in db.execute(SHIPMENT_CTE + f''', tracking_closed AS (
                    SELECT shipment_id,MAX(created_at) AS closed_at FROM reception_history
                    WHERE field_name='app_status' AND new_value='CERRADO' GROUP BY shipment_id)
                    SELECT l.source_sheet,s.bl_awb,l.ov_number,l.oc_number,l.np_code,l.ip_reference,
                    COUNT(*) AS matches,MAX(l.received_qty) AS received_qty,
                    MAX(CASE WHEN l.final_location_confirmed=1 THEN l.final_location END) AS location,
                    MIN(CASE WHEN s.app_status='CERRADO' AND s.transfer_assistant_checked=1 THEN 1 ELSE 0 END) AS transferred,
                    MAX(s.has_received_packages) AS has_received_packages,MIN(s.receipt_started_at) AS receipt_started_at,
                    MIN(s.truck_started_at) AS truck_started_at,MIN(s.legacy_physical_at) AS legacy_physical_at,
                    MAX(s.app_status) AS app_status,MAX(s.transport_type) AS transport_type,MAX(c.closed_at) AS closed_at
                    FROM reception_lines l JOIN operational_shipments s ON s.id=l.shipment_id
                    LEFT JOIN tracking_closed c ON c.shipment_id=s.id
                    WHERE l.{ 'ov_number' if kind == 'OV' else 'oc_number' }=?
                    GROUP BY l.source_sheet,s.bl_awb,l.ov_number,l.oc_number,l.np_code,l.ip_reference''', (number,))}
    identities = Counter((row['sheet'], *(json.loads(row['payload'])[name] for name in
                         ('bl', 'ov', 'oc', 'item', 'triton_order'))) for row in rows if row['present'])
    lines = []
    now = datetime.now(timezone.utc).isoformat()
    attention_timing = defaultdict(list)
    attention_transferred = defaultdict(float)
    if rows and 'reception_attention_lines' in tables:
        for fact in db.execute(f'''SELECT l.source_sheet,s.bl_awb,l.ov_number,l.oc_number,l.np_code,l.ip_reference,
                a.id,a.app_status,a.completed_at,a.transfer_assistant_checked,al.verified_qty,r.received_at,s.transport_type
                FROM reception_attention_lines al JOIN reception_attentions a ON a.id=al.attention_id
                JOIN reception_lines l ON l.id=al.reception_line_id
                JOIN reception_shipments s ON s.id=l.shipment_id AND s.id=a.shipment_id
                JOIN reception_receipts r ON r.id=a.receipt_id AND r.shipment_id=s.id
                WHERE l.{'ov_number' if kind == 'OV' else 'oc_number'}=? AND al.verified_qty>0
                AND r.received_packages>0 AND COALESCE(a.condition_status,'') NOT LIKE 'ANULADA%'
                ORDER BY a.id''', (number,)):
            key = (fact['source_sheet'], fact['bl_awb'], ov_key(fact['ov_number']), fact['oc_number'], fact['np_code'], fact['ip_reference'])
            item = dict(transport_type=fact['transport_type'], work_pending=fact['app_status'] != 'CERRADO',
                        pending_arrival=False, work_status=fact['app_status'])
            timing = _timing(item, fact['received_at'], fact['completed_at'] if not item['work_pending'] else None, now)
            timing['attention_id'] = fact['id']
            attention_timing[key].append(timing)
            if fact['app_status'] == 'CERRADO' and fact['transfer_assistant_checked']:
                attention_transferred[key] += fact['verified_qty']
    for row in rows:
        line = json.loads(row['payload'])
        key = (row['sheet'], line['bl'], line['ov'], line['oc'], line['item'], line['triton_order'])
        fact = evidence.get(key)
        line.update(received_qty=None, location=None, transferred=False, transferred_qty=None,
                    warning=None if row['present'] else 'Ya no aparece en el corte actual', sla=None)
        if fact and fact['matches'] == 1 and identities[key] == 1 and row['present']:
            physical = project_shipment(fact)
            if physical['physically_received']:
                complete = (line['requested_qty'] is not None and fact['received_qty'] > 0
                            and fact['received_qty'] + 1e-9 >= line['requested_qty'])
                line.update(received_qty=fact['received_qty'], location=fact['location'], transferred=bool(fact['transferred'] and complete))
                line['transferred_qty'] = fact['received_qty'] if line['transferred'] else None
                timing = dict(transport_type=fact['transport_type'], work_pending=not line['transferred'],
                              pending_arrival=False, work_status=fact['app_status'])
                line['sla'] = _timing(timing, physical['physical_started_at'],
                                      fact['closed_at'] if line['transferred'] else None, now)
                if attention_timing[key]:
                    quantity = attention_transferred[key]
                    if quantity <= fact['received_qty'] + 1e-9:
                        line['transferred_qty'] = quantity
                        line['transferred'] = bool(complete and quantity + 1e-9 >= line['requested_qty'])
                    else:
                        line['transferred'], line['transferred_qty'] = False, None
                        line['warning'] = 'Datos por confirmar: cantidades de transferencia contradictorias'
                    line['slas'] = attention_timing[key]
                    pending = [timing for timing in line['slas'] if timing['sla_status'] != 'FINALIZADO']
                    line['sla'] = min(pending, key=lambda timing: timing['remaining_hours'] if timing['remaining_hours'] is not None else float('inf')) if pending else line['slas'][-1]
        elif fact and (fact['matches'] > 1 or identities[key] > 1):
            line['warning'] = 'Datos por confirmar: vínculo de recepción ambiguo'
        line['approval'] = 'Aprobación no verificada'
        line['stage'] = _stage(line)
        lines.append(line)
    if kind == 'OV' and 'orders' in tables and 'order_lines' in tables:
        order = db.execute('SELECT updated_at FROM orders WHERE sap_ov=?', (number,)).fetchone()
        if order:
            source['orders_updated_at'] = order[0]
            if str(order[0] or '')[:10] != str(source['cutoff_at'] or source['loaded_at'] or '')[:10]:
                source['orders_warning'] = 'Pedidos e Importaciones tienen marcas de actualización diferentes'
            count = db.execute('SELECT COUNT(*) FROM order_lines WHERE sap_ov=?', (number,)).fetchone()[0]
            if count > MAX_DOCUMENT_LINES:
                raise ValueError('El documento excede el límite de líneas de Tracking; requiere revisión de Importaciones')
            known = {line['item'] for line in lines}
            for row in db.execute('SELECT item_code,description,required_qty,pending_qty FROM order_lines WHERE sap_ov=? ORDER BY source_row', (number,)):
                if row['item_code'] in known:
                    continue
                lines.append(dict(item=row['item_code'], description=row['description'], ov=number, oc='', bl='', brand='',
                    requested_qty=row['required_qty'], invoiced_qty=None, pending_qty=row['pending_qty'], received_qty=None,
                    location=None, transferred=False, transferred_qty=None, sla=None, dates=dict.fromkeys(DATES), stage='Datos por confirmar',
                    warning='Sin referencia de Importaciones; compra y recepción sin verificar', approval='Aprobación no verificada'))
    if len(lines) > MAX_DOCUMENT_LINES:
        raise ValueError('El documento excede el límite de líneas de Tracking; requiere revisión de Importaciones')
    total = len(lines)
    full = [line for line in lines if line['received_qty'] and line['received_qty'] > 0
            and line['requested_qty'] is not None and line['received_qty'] + 1e-9 >= line['requested_qty']]
    received = len(full)
    partial = sum(line['stage'] == 'Recepción parcial' for line in lines)
    located = sum(bool(line['location']) for line in full)
    transferred = sum(line['transferred'] and line['stage'] == 'Atención de almacén completada' for line in lines)
    status = ('Sin resultados' if not total else 'Atención de almacén completada' if transferred == total else
              'Parcial' if partial or (received and received < total) else
              'Recibido' if received == total else 'Datos por confirmar')
    return {'document': {'type': kind, 'number': number}, 'source': source,
            'summary': {'total': total, 'received': received, 'partially_received': partial, 'located': located, 'transferred': transferred, 'status': status},
            'lines': lines[offset:offset + limit], 'pagination': {'offset': offset, 'limit': limit, 'total': total}}
