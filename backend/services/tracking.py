"""Internal document tracking: allowlisted snapshots and read-only warehouse evidence."""
from collections import Counter, defaultdict
import hashlib
import json
import math
from datetime import datetime, timezone

from backend.services.purchase_alerts import oc_format
from backend.services.reception import _cell_text, _find_column, _normalize_header, _row_value
from backend.services.reception_projection import SHIPMENT_CTE, project_shipment
from backend.services.reception_work import _timing
from backend.services.reception_source_bl import ov_key

MAX_DOCUMENT_LINES = 2000
DOCUMENT_FIELDS = {
    'OV': ('ov', 'l.ov_number'), 'OC': ('oc', 'l.oc_number'),
    'IP': ("json_extract(payload, '$.triton_order') COLLATE NOCASE", 'l.ip_reference COLLATE NOCASE'),
    'BL': ("json_extract(payload, '$.bl') COLLATE NOCASE", 's.bl_awb COLLATE NOCASE'),
}
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
    for kind, (field, _) in DOCUMENT_FIELDS.items():
        db.execute(f'CREATE INDEX IF NOT EXISTS tracking_{kind.lower()} ON tracking_lines({field})')
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reception_lines'").fetchone():
        for field in ('ov_number', 'oc_number'):
            db.execute(f'CREATE INDEX IF NOT EXISTS tracking_reception_{field} ON reception_lines({field})')
        db.execute('CREATE INDEX IF NOT EXISTS tracking_reception_ip ON reception_lines(ip_reference COLLATE NOCASE)')
        db.execute('CREATE INDEX IF NOT EXISTS tracking_reception_bl ON reception_shipments(bl_awb COLLATE NOCASE)')
    db.execute('INSERT OR IGNORE INTO tracking_source(id,warning) VALUES(1,?)',
               ('Pendiente del primer corte de Importaciones',))


def _quantity(value, *, allow_negative=False):
    if value in (None, ''):
        return None
    number = float(str(value).replace(',', '').replace(' ', ''))
    if not math.isfinite(number) or (number < 0 and not allow_negative):
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
            # Importaciones reports pending as a signed balance; other quantities stay nonnegative.
            record = {name: (_quantity(_row_value(row, index), allow_negative=name == 'pending_qty')
                             if name.endswith('_qty') else
                             _cell_text(_row_value(row, index))) for name, index in indexes.items()}
            record['ov'] = ov_key(record['ov'])
            record['oc'] = record['oc'].upper()
            if not (record['ov'] or record['oc'] or record['bl'] or record['triton_order'].upper() not in {'', 'X'}):
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
        populated = {row[0] for row in db.execute('SELECT DISTINCT sheet FROM tracking_lines WHERE present=1')}
        incoming = {record[3] for record in records}
        if (not records or not set(previous_sheets).issubset(sheets)
                or not populated.issubset(incoming)
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


def search(db, kind, number, offset=0, limit=50, *, details=True):
    kind, number = str(kind).strip().upper(), _cell_text(number)
    number = ov_key(number) if kind == 'OV' else number.upper()
    if kind not in DOCUMENT_FIELDS or not number or len(number) > 100:
        raise ValueError('Documento de Tracking no válido')
    if not details and kind not in {'OV', 'OC'}:
        raise PermissionError('El perfil Comercial consulta por OV u OC.')
    document_field, reception_field = DOCUMENT_FIELDS[kind]
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
        counts = db.execute(f'SELECT COUNT(*),SUM(present) FROM tracking_lines WHERE {document_field}=?', (number,)).fetchone()
        current = bool(counts[1])
        if current and counts[0] > counts[1]:
            source['coverage_warning'] = 'Hay líneas de cortes anteriores ausentes del corte actual; la cobertura completa del documento no está verificada'
        if (counts[1] if current else counts[0]) > MAX_DOCUMENT_LINES:
            raise ValueError('El documento excede el límite de líneas de Tracking; requiere revisión de Importaciones')
        rows = db.execute(f'SELECT * FROM tracking_lines WHERE {document_field}=? AND (?=0 OR present=1) ORDER BY sheet,source_row,identity', (number, int(current))).fetchall()
    evidence = {}
    if rows and 'reception_lines' in tables:
        # Scope the shared evidence projection before its grouped history reads.
        scoped = f'''WITH tracking_shipments AS (
            SELECT DISTINCT l.shipment_id FROM main.reception_lines l
            JOIN main.reception_shipments s ON s.id=l.shipment_id WHERE {reception_field}=?), '''
        for table, field in (('reception_shipments', 'id'), ('reception_receipts', 'shipment_id'),
                             ('reception_truck_bl_arrivals', 'shipment_id'), ('reception_history', 'shipment_id')):
            scoped += f'{table} AS (SELECT * FROM main.{table} WHERE {field} IN (SELECT shipment_id FROM tracking_shipments)), '
        scoped += SHIPMENT_CTE.removeprefix('WITH ')
        # Only an exact, unique documentary line can supply warehouse facts.
        evidence = {(r['source_sheet'], r['bl_awb'], ov_key(r['ov_number']), r['oc_number'], r['np_code'], r['ip_reference']): dict(r)
                    for r in db.execute(scoped + f''', tracking_closed AS (
                    SELECT shipment_id,MAX(created_at) AS closed_at FROM reception_history
                    WHERE field_name='app_status' AND new_value='CERRADO' GROUP BY shipment_id)
                    SELECT l.source_sheet,s.bl_awb,l.ov_number,l.oc_number,l.np_code,l.ip_reference,
                    COUNT(*) AS matches,MAX(l.received_qty) AS received_qty,
                    MAX(CASE WHEN l.final_location_confirmed=1 THEN l.final_location END) AS location,
                    MIN(CASE WHEN s.app_status='CERRADO' AND s.transfer_assistant_checked=1
                        AND COALESCE(s.condition_status,'') NOT LIKE 'ANULADA%'
                        AND COALESCE(s.condition_status,'')<>'CIERRE ADMINISTRATIVO'
                        AND NOT EXISTS (SELECT 1 FROM reception_attentions excluded
                            WHERE excluded.shipment_id=s.id AND (excluded.condition_status='CIERRE ADMINISTRATIVO'
                                OR excluded.condition_status LIKE 'ANULADA%'))
                        THEN 1 ELSE 0 END) AS transferred,
                    MAX(s.has_received_packages) AS has_received_packages,MIN(s.receipt_started_at) AS receipt_started_at,
                    MIN(s.truck_started_at) AS truck_started_at,MIN(s.legacy_physical_at) AS legacy_physical_at,
                    MAX(s.app_status) AS app_status,MAX(s.transport_type) AS transport_type,MAX(c.closed_at) AS closed_at
                    FROM reception_lines l JOIN operational_shipments s ON s.id=l.shipment_id
                    LEFT JOIN tracking_closed c ON c.shipment_id=s.id
                    WHERE {reception_field}=?
                    GROUP BY l.source_sheet,s.bl_awb,l.ov_number,l.oc_number,l.np_code,l.ip_reference''', (number, number))}
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
                WHERE {reception_field}=? AND al.verified_qty>0
                AND r.received_packages>0 AND COALESCE(a.condition_status,'') NOT LIKE 'ANULADA%'
                AND COALESCE(a.condition_status,'')<>'CIERRE ADMINISTRATIVO'
                AND COALESCE(s.condition_status,'') NOT LIKE 'ANULADA%'
                AND COALESCE(s.condition_status,'')<>'CIERRE ADMINISTRATIVO'
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
        line['approval'] = {'preliminary': 'Preliminar por regularizar',
                            'approved_by_format': 'Aprobada según formato'}.get(oc_format(line['oc']), 'Aprobación no verificada')
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
            order_rows = db.execute('SELECT item_code,description,required_qty,pending_qty FROM order_lines WHERE sap_ov=? ORDER BY source_row', (number,)).fetchall()
            wanted, imported = defaultdict(float), defaultdict(float)
            for item in order_rows:
                wanted[item['item_code']] += item['required_qty'] or 0
            for line in lines:
                imported[line['item']] += line['requested_qty'] or 0
            if set(wanted) != set(imported) or any(abs(wanted[key] - imported[key]) > 1e-9 for key in wanted):
                source['coverage_warning'] = 'Las cantidades de la OV y de Importaciones no coinciden; no se certifica la atención completa de la OV'
            for row in order_rows:
                if row['item_code'] in known:
                    continue
                lines.append(dict(item=row['item_code'], description=row['description'], ov=number, oc='', bl='', brand='',
                    requested_qty=row['required_qty'], invoiced_qty=None, pending_qty=row['pending_qty'], received_qty=None,
                    location=None, transferred=False, transferred_qty=None, sla=None, dates=dict.fromkeys(DATES), stage='Datos por confirmar',
                    warning='Sin referencia de Importaciones; compra y recepción sin verificar', approval='Aprobación no verificada'))
        elif lines:
            source['coverage_warning'] = 'OV sin detalle en el corte de pedidos; su cobertura completa no está verificada'
    if len(lines) > MAX_DOCUMENT_LINES:
        raise ValueError('El documento excede el límite de líneas de Tracking; requiere revisión de Importaciones')
    total = len(lines)
    full = [line for line in lines if line['received_qty'] and line['received_qty'] > 0
            and line['requested_qty'] is not None and line['received_qty'] + 1e-9 >= line['requested_qty']]
    received = len(full)
    partial = sum(line['stage'] == 'Recepción parcial' for line in lines)
    located = sum(bool(line['location']) for line in full)
    transferred = sum(line['transferred'] and line['stage'] == 'Atención de almacén completada' for line in lines)
    status = ('Sin resultados' if not total else 'Atención de almacén completada' if transferred == total and not source.get('coverage_warning') else
              'Parcial' if partial or (received and received < total) else
              'Recibido' if received == total else 'Datos por confirmar')
    document = {'type': kind, 'number': number}
    if not details:
        if status == 'Datos por confirmar' and all(l['stage'] in {'Factura informada', 'Recojo informado', 'Callao informado'} for l in lines):
            status = 'Importación informada'
        return {'document': document,
                'source': {key: source.get(key) for key in ('loaded_at', 'cutoff_at', 'warning', 'coverage_warning',
                                                          'orders_updated_at', 'orders_warning')},
                'summary': {'total': total, 'received': received, 'partially_received': partial, 'status': status}}
    return {'document': document, 'source': source,
            'summary': {'total': total, 'received': received, 'partially_received': partial, 'located': located, 'transferred': transferred, 'status': status},
            'lines': lines[offset:offset + limit], 'pagination': {'offset': offset, 'limit': limit, 'total': total}}
