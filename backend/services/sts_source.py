"""SAP STS snapshots: document/line identity, independent of physical fulfilment."""
from io import BytesIO
from decimal import Decimal, InvalidOperation
import re
import math
import unicodedata
from zipfile import BadZipFile

from openpyxl import load_workbook


def source_order_timestamp(get):
    """Creation time wins over accounting date; never use an import arrival."""
    from backend.services.workload import _timestamp
    creation = get('source_creation_date')
    raw = creation or get('source_order_date')
    parsed = _timestamp(raw)
    if parsed is None:
        return "" if raw is None else str(raw).strip()
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


def normalized(value):
    return re.sub(r'[^A-Z0-9]', '', unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode().upper())


def literal(value, label, limit=120):
    if isinstance(value, bool) or value is None:
        raise ValueError(f'{label}: valor vacío o no válido.')
    if isinstance(value, (float, int)):
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError(f'{label}: número no válido.')
        value = format(number, 'f').rstrip('0').rstrip('.') if number % 1 else str(int(number))
    value = str(value).strip()
    if not value or len(value) > limit or value.startswith('=') or any(ord(c) < 32 for c in value):
        raise ValueError(f'{label}: texto vacío, demasiado largo o no válido.')
    return value


def warehouse(value):
    code = literal(value, 'Almacén', 30).upper()
    return str(int(code)).zfill(2) if code.isdigit() else code


def parse_workbook(content):
    aliases = {
        'type': ['Tipo_Doc'], 'number': ['Número de documento'],
        'status': ['Status de Documento'], 'line': ['Nº de Línea', 'N° de Línea'],
        'item_code': ['Número de artículo'], 'description': ['Descripción artículo/serv.'],
        'group': ['Grupo de Articulo'], 'origin': ['Alm Origen'], 'destination': ['Alm Destino'],
        'quantity': ['Cantidad'], 'source_creation_date': ['FechaCrea_ST'],
        'source_order_time': ['HoraCrea_ST'], 'source_order_date': ['Fecha de contabilización'],
        'customer_code': ['Código de cliente/proveedor'], 'customer_name': ['Nombre de cliente/proveedor'],
    }
    required = {'type', 'number', 'status', 'line', 'item_code', 'group', 'origin', 'destination', 'quantity'}
    try:
        book = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except (BadZipFile, KeyError) as error:
        raise ValueError('El archivo no es un Excel .xlsx válido. Descarga nuevamente el reporte STS.') from error
    try:
        matches = []
        for sheet in book:
            for index, row in enumerate(sheet.iter_rows(max_row=20, max_col=64, values_only=True), 1):
                headers = {normalized(cell): i for i, cell in enumerate(row) if cell is not None}
                columns = {key: next((headers[normalized(a)] for a in values if normalized(a) in headers), None) for key, values in aliases.items()}
                if all(columns[key] is not None for key in required):
                    matches.append((sheet, index, columns)); break
        if len(matches) != 1:
            raise ValueError('Selecciona un reporte SAP de STS con una sola hoja de detalle y sus encabezados completos.')
        sheet, header, columns = matches[0]
        result = {'open': {}, 'closed': {}, 'repeated_rows': 0}
        documents = {}
        recognized = 0
        for index, raw in enumerate(sheet.iter_rows(min_row=header+1, max_col=64, values_only=True), 1):
            if index > 200000:
                raise ValueError('El reporte STS supera las 200000 filas.')
            if not any(value is not None for value in raw):
                continue
            get = lambda key: raw[columns[key]] if columns.get(key) is not None else None
            if normalized(get('type')) != 'SOLTRANSF':
                raise ValueError('El archivo debe contener únicamente solicitudes SOL TRANSF.')
            recognized += 1
            if warehouse(get('origin')) != '01' or normalized(get('group')) not in {'REPUESTOS', 'ACCESORIOS'}:
                continue
            destination = warehouse(get('destination'))
            if destination == '01':
                continue
            number = literal(get('number'), 'Número de STS', 60)
            line = literal(get('line'), 'Línea SAP', 12)
            if not line.isdigit():
                raise ValueError('La línea SAP debe ser un número entero no negativo.')
            status = normalized(get('status'))
            if status not in {'ABIERTO', 'CERRADO'}:
                raise ValueError('El estado SAP debe ser Abierto o Cerrado.')
            try:
                quantity = Decimal(str(get('quantity')))
                if not quantity.is_finite() or quantity < 0 or (quantity == 0 and status == 'ABIERTO'):
                    raise ValueError('Cantidad STS no válida.')
                amount = float(quantity)
                if not math.isfinite(amount):
                    raise ValueError('Cantidad STS fuera de rango.')
            except (InvalidOperation, TypeError) as error:
                raise ValueError('Cantidad STS no válida.') from error
            meta = {'destination': destination, 'status': status, 'source_order_date': source_order_timestamp(get),
                    'customer_code': str(get('customer_code') or '').strip(),
                    'customer_name': str(get('customer_name') or '').strip()}
            document = documents.setdefault(number, {**meta, 'lines': {}})
            if document['status'] != status or (status == 'ABIERTO' and any(document[key] != value for key, value in meta.items())):
                raise ValueError(f'La STS {number} tiene estados, destinos o datos de cabecera diferentes.')
            item = {'item_code': literal(get('item_code'), 'NP', 100),
                    'description': str(get('description') or '').strip(), 'quantity': amount}
            line_no = int(line)
            if line_no in document['lines']:
                if document['lines'][line_no] != item:
                    raise ValueError(f'La STS {number}, línea {line}, tiene datos contradictorios.')
                if status == 'ABIERTO':
                    result['repeated_rows'] += 1
            document['lines'][line_no] = item
        if not recognized or not documents:
            raise ValueError('El reporte STS no contiene documentos. Se conservó el corte anterior.')
        for number, document in documents.items():
            result['open' if document['status'] == 'ABIERTO' else 'closed'][number] = document
        return result
    finally:
        book.close()


def apply_snapshot(app, db, parsed, identity, complete):
    stamp, username = app.now(), identity['username']
    tracked = {r['source_reference']: r['sap_ov'] for r in db.execute(
        "SELECT sap_ov,source_reference FROM dispatch_context WHERE kind='STS' AND local_created=0 AND sap_ov LIKE 'STS-SAP-%'")}
    changed = 0
    for number, document in parsed['open'].items():
        code = 'STS-SAP-' + number
        destination = document['destination']
        old = db.execute('SELECT * FROM orders WHERE sap_ov=?', (code,)).fetchone()
        previous_context = db.execute('SELECT * FROM dispatch_context WHERE sap_ov=?', (code,)).fetchone()
        if old and (not previous_context or previous_context['kind'] != 'STS' or previous_context['local_created']):
            raise ValueError('La referencia STS ya existe con otro origen. No se modificaron datos.')
        if old and old['destination'] != destination and db.execute('SELECT 1 FROM attentions WHERE sap_ov=?', (code,)).fetchone():
            raise ValueError('La STS tiene atenciones; revisa el cambio de destino antes de cargarla.')
        db.execute('INSERT OR IGNORE INTO dispatch_branches(code,name) VALUES(?,?)', (destination, 'Almacén '+destination))
        db.execute('''INSERT INTO orders(sap_ov,customer_code,customer_name,source_order_date,destination,
            document_status,source_present,created_at,updated_at)
            VALUES(?,?,?,?,?,'Abierto',1,?,?) ON CONFLICT(sap_ov) DO UPDATE SET
            customer_code=excluded.customer_code,customer_name=excluded.customer_name,
            source_order_date=excluded.source_order_date,destination=excluded.destination,
            document_status='Abierto',source_present=1,updated_at=excluded.updated_at''',
            (code, document['customer_code'], document['customer_name'] or 'Almacén '+destination,
             document['source_order_date'], destination, stamp, stamp))
        db.execute('''INSERT INTO dispatch_context(sap_ov,kind,destination,source_reference,local_created,created_by,updated_at)
            VALUES(?,'STS',?,?,0,?,?) ON CONFLICT(sap_ov) DO UPDATE SET destination=excluded.destination,updated_at=excluded.updated_at''',
            (code, destination, number, username, stamp))
        seen = []
        for line_no, line in document['lines'].items():
            key = f'SAP_STS_LINE:{line_no}'
            existing = db.execute('SELECT * FROM order_lines WHERE sap_ov=? AND source_key=?', (code, key)).fetchone()
            if existing and existing['item_code'] != line['item_code'] and db.execute('''SELECT 1 FROM attention_lines l
                JOIN attentions a ON a.id=l.attention_id WHERE l.order_line_id=? AND
                (l.picked_qty>0 OR l.delivered_qty>0 OR a.app_status NOT IN ('PENDIENTE','ASIGNADO'))''', (existing['id'],)).fetchone():
                raise ValueError('Una línea STS trabajada cambió de NP. Revisa el documento antes de cargarlo.')
            if not existing or any(existing[k] != line[v] for k,v in (('item_code','item_code'),('description','description'),('required_qty','quantity'))) or not existing['is_pending_sap']:
                app.write_history(db, code, 'ACTUALIZACION_STS_SAP', key,
                    str(dict(existing)) if existing else None, str(line), username)
            db.execute('''INSERT INTO order_lines(sap_ov,source_row,source_key,item_code,description,
                required_qty,pending_qty,available_qty,warehouse,is_pending_sap)
                VALUES(?,?,?,?,?,?,?,0,'1',1) ON CONFLICT(sap_ov,source_key) WHERE source_key IS NOT NULL
                DO UPDATE SET item_code=excluded.item_code,description=excluded.description,
                required_qty=excluded.required_qty,pending_qty=excluded.pending_qty,is_pending_sap=1''',
                (code, line_no, key, line['item_code'], line['description'], line['quantity'], line['quantity']))
            seen.append(key)
        if complete:
            placeholders = ','.join('?' for _ in seen)
            missing = db.execute(f'SELECT source_key FROM order_lines WHERE sap_ov=? AND is_pending_sap=1 AND source_key NOT IN ({placeholders})', (code, *seen)).fetchall()
            if missing:
                app.write_history(db, code, 'ACTUALIZACION_STS_SAP', 'lineas_ausentes',
                    ', '.join(line['source_key'] for line in missing), 'Fuera del reporte completo', username)
            db.execute(f'UPDATE order_lines SET is_pending_sap=0 WHERE sap_ov=? AND source_key NOT IN ({placeholders})', (code, *seen))
        app.sync_unstarted_attention_lines(db, code)
    to_close = {number: 'Cerrado' for number in parsed['closed'] if number in tracked}
    if complete:
        to_close.update({number: 'NO REPORTADA' for number in tracked if number not in parsed['open'] and number not in parsed['closed']})
    for number, status in to_close.items():
        code = tracked[number]
        old = db.execute('SELECT document_status,source_present FROM orders WHERE sap_ov=?', (code,)).fetchone()
        if old['source_present'] or old['document_status'] != status:
            app.write_history(db, code, 'ESTADO_STS_SAP', 'document_status', old['document_status'], status, username)
            changed += 1
        db.execute('UPDATE orders SET source_present=0,document_status=?,updated_at=? WHERE sap_ov=?', (status, stamp, code))
        db.execute('UPDATE order_lines SET is_pending_sap=0 WHERE sap_ov=?', (code,))
        app.sync_unstarted_attention_lines(db, code)
    return {'sts': len(parsed['open']), 'lines': sum(len(d['lines']) for d in parsed['open'].values()),
            'repeated_rows': parsed['repeated_rows'], 'source_closed': changed,
            'complete_snapshot': bool(complete), 'stock_updated': False}
