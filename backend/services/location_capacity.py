"""Physical position master; stock defaults are evidence, not bin-level balances."""
import base64
import csv
import hashlib
import json
import re
import unicodedata
from io import BytesIO, StringIO
from itertools import islice
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree.ElementTree import ParseError

from backend.services.safe_excel import load_workbook

from backend.services.daily_operations import local_now
from backend.services.inventory_governance import INVENTORY_ROLES
from backend.services.reception_brands import label_brand

STATES = {'HABILITADA', 'BLOQUEADA', 'BAJA'}
MAX_ROWS = 100000
HEADER_ROWS = 20
MAX_LABELS = 200
MAX_FILE_BYTES = 4 * 1024 * 1024
DIMENSIONS = ('warehouse', 'aisle', 'level', 'bin')
HEADINGS = {'ubicacion': 'code', 'posiciondeubicacion': 'code', 'codigo': 'code',
            'location': 'code', 'zona': 'zone', 'zone': 'zone', 'rack': 'rack',
            'estado': 'state', 'almacen': 'warehouse', 'pasillo': 'aisle',
            'nivel': 'level', 'caja': 'bin'}


def init_schema(connection):
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS warehouse_locations (
            code TEXT PRIMARY KEY, zone TEXT NOT NULL DEFAULT '', rack TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL CHECK(state IN ('HABILITADA','BLOQUEADA','BAJA')),
            updated_at TEXT NOT NULL, updated_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS warehouse_location_revision (
            id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL DEFAULT 0
        );
        INSERT OR IGNORE INTO warehouse_location_revision(id,revision) VALUES(1,0);
        CREATE TABLE IF NOT EXISTS warehouse_location_history (
            id INTEGER PRIMARY KEY, code TEXT NOT NULL, before_json TEXT NOT NULL,
            after_json TEXT NOT NULL, reason TEXT NOT NULL, username TEXT NOT NULL,
            created_at TEXT NOT NULL, source TEXT NOT NULL, revision INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_location_history_code ON warehouse_location_history(code,id);
    """)
    existing = {row[1] for row in connection.execute('PRAGMA table_info(warehouse_locations)')}
    for name in DIMENSIONS:
        if name not in existing:
            default = '01' if name == 'warehouse' else ''
            connection.execute(f"ALTER TABLE warehouse_locations ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")


def require_access(role, admin=False):
    if str(role).upper() not in INVENTORY_ROLES or (admin and role != 'ADMINISTRADOR'):
        raise PermissionError('Solo el administrador modifica ubicaciones' if admin else 'Sin acceso a ubicaciones')


def code_key(value):
    code = str(value or '').strip().upper()
    # Preserve separators and zero padding; no inferred rack expansion.
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9._ /-]{0,59}', code):
        raise ValueError('Ubicación inválida: usa hasta 60 letras, números, espacios, puntos, / o guiones')
    return code


def revision(connection):
    return connection.execute('SELECT revision FROM warehouse_location_revision WHERE id=1').fetchone()[0]


def _heading(value):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode().lower())


def _header(rows):
    for index, row in enumerate(rows):
        if any(HEADINGS.get(_heading(value)) == 'code' for value in row):
            return index
    return None


def _dimension(value):
    if value is None or str(value).strip() == '':
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip().upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9._ /-]{0,39}', text):
        raise ValueError('Dimensión de ubicación inválida')
    return text.zfill(2) if text.isdigit() else text


def parse_master(payload):
    """Bounded XLSX/CSV or explicit one-code-per-line input; no operational import."""
    if payload.get('text') and payload.get('file_base64'):
        raise ValueError('Carga un archivo o pega ubicaciones, no ambos')
    if payload.get('file_base64'):
        encoded = payload['file_base64']
        if not isinstance(encoded, str) or len(encoded) > (MAX_FILE_BYTES * 4 // 3 + 8):
            raise ValueError('Archivo demasiado grande; máximo 4 MB')
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError('Archivo no válido') from error
        if len(content) > MAX_FILE_BYTES:
            raise ValueError('Archivo demasiado grande; máximo 4 MB')
        filename = Path(str(payload.get('filename') or '')).name
        if filename.lower().endswith('.xlsx'):
            try:
                with ZipFile(BytesIO(content)) as archive:
                    if len(archive.infolist()) > 1000 or sum(row.file_size for row in archive.infolist()) > 24 * 1024 * 1024:
                        raise ValueError('Excel demasiado grande al descomprimir')
                workbook = load_workbook(BytesIO(content), read_only=True, data_only=False, keep_links=False)
                try:
                    sheet_name = str(payload.get('sheet') or '')
                    if sheet_name and sheet_name not in workbook.sheetnames:
                        raise ValueError('No existe la hoja indicada')
                    candidates = []
                    for sheet in ([workbook[sheet_name]] if sheet_name else workbook.worksheets):
                        if (sheet.max_column or 0) > 30:
                            continue
                        head = list(sheet.iter_rows(max_row=HEADER_ROWS, values_only=True))
                        if _header(head) is not None:
                            candidates.append(sheet)
                    if len(candidates) != 1:
                        raise ValueError('Indica una hoja con encabezado Ubicacion o Posición de ubicación' if not candidates
                                         else 'Hay varias hojas de ubicaciones; indica cuál cargar')
                    sheet = candidates[0]
                    if (sheet.max_column or 0) > 30:
                        raise ValueError('Usa un maestro de ubicaciones con un máximo de 30 columnas')
                    if (sheet.max_row or 0) > MAX_ROWS + HEADER_ROWS:
                        raise ValueError('Máximo 100000 ubicaciones por carga')
                    sheet.reset_dimensions()
                    rows = list(islice(sheet.iter_rows(max_col=30, values_only=True), MAX_ROWS + HEADER_ROWS + 1))
                    source_sheet = sheet.title
                finally:
                    workbook.close()
            except (BadZipFile, KeyError, OSError, ParseError) as error:
                raise ValueError('No se pudo leer el Excel de ubicaciones') from error
        elif filename.lower().endswith('.csv'):
            try:
                text = content.decode('utf-8-sig')
                try:
                    dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t')
                except csv.Error:
                    dialect = csv.excel
                rows = list(islice(csv.reader(StringIO(text), dialect), MAX_ROWS + HEADER_ROWS + 1))
            except (UnicodeError, csv.Error) as error:
                raise ValueError('Usa CSV UTF-8 con encabezado Ubicacion, o un Excel .xlsx') from error
        else:
            raise ValueError('Usa un archivo .xlsx o .csv')
        source = filename + (' / ' + source_sheet if filename.lower().endswith('.xlsx') else '')
    else:
        text = payload.get('text')
        if not isinstance(text, str) or len(text) > MAX_FILE_BYTES:
            raise ValueError('Pega una ubicación por línea, máximo 100000')
        rows = [['Ubicacion']] + [[line] for line in text.splitlines() if line.strip()]
        source = 'Ingreso de ubicaciones'
    if len(rows) > MAX_ROWS + HEADER_ROWS:
        raise ValueError('Máximo 100000 ubicaciones por carga')
    header = _header(rows[:HEADER_ROWS]) if rows else None
    if header is None:
        raise ValueError('El maestro necesita un encabezado Ubicacion o Posición de ubicación')
    headings = [_heading(cell) for cell in rows[header]]
    columns = {}
    for index, name in enumerate(headings):
        if name in HEADINGS:
            target = HEADINGS[name]
            if target in columns:
                raise ValueError('Hay columnas duplicadas en el maestro')
            columns[target] = index
    if 'code' not in columns:
        raise ValueError('El maestro necesita un encabezado Ubicacion')
    cleaned, seen = [], set()
    for number, row in enumerate(rows[header + 1:], header + 2):
        if not any(str(value or '').strip() for value in row):
            continue
        record = {key: (row[index] if index < len(row) else '') for key, index in columns.items()}
        if any(isinstance(value, str) and value.startswith('=') for value in record.values()):
            raise ValueError(f'Fila {number}: usa valores, no fórmulas, en el maestro')
        try:
            code = code_key(record.get('code'))
        except ValueError as error:
            raise ValueError(f'Fila {number}: {error}') from error
        if code in seen:
            raise ValueError(f'Ubicación duplicada en el archivo: {code}')
        seen.add(code)
        item = {'code': code}
        for key in ('zone', 'rack', 'state', *DIMENSIONS):
            if key in record:
                value = _dimension(record[key]) if key in DIMENSIONS else str(record[key] or '').strip().upper()
                if len(value) > 80:
                    raise ValueError(f'Fila {number}: {key} demasiado largo')
                if key == 'state' and value not in STATES:
                    raise ValueError(f'Fila {number}: estado debe ser HABILITADA, BLOQUEADA o BAJA')
                if key == 'warehouse' and value != '01':
                    raise ValueError(f'Fila {number}: este maestro corresponde al almacén 01')
                item[key] = value
        cleaned.append(item)
        if len(cleaned) > MAX_ROWS:
            raise ValueError('Máximo 100000 ubicaciones por carga')
    if not cleaned:
        raise ValueError('El maestro no tiene ubicaciones')
    digest = hashlib.sha256(json.dumps(cleaned, sort_keys=True).encode()).hexdigest()
    return cleaned, source[:200], digest


def _preview_rows(connection, rows, source, digest):
    current = {row['code']: dict(row) for row in connection.execute('SELECT * FROM warehouse_locations')}
    additions = sum(row['code'] not in current for row in rows)
    changes = sum(row['code'] in current and any(current[row['code']][key] != value
                  for key, value in row.items()) for row in rows)
    return {'count': len(rows), 'added': additions, 'changed': changes, 'unchanged': len(rows) - additions - changes,
            'sample': rows[:10], 'digest': digest, 'source': source, 'revision': revision(connection)}


def preview(connection, payload, role, prepared=None):
    require_access(role, admin=True)
    return _preview_rows(connection, *(prepared if prepared is not None else parse_master(payload)))


def save_master(connection, payload, username, role, prepared=None):
    require_access(role, admin=True)
    reason = str(payload.get('reason') or '').strip()
    if len(reason) < 5 or len(reason) > 500:
        raise ValueError('Indica el motivo de la actualización (5 a 500 caracteres)')
    rows, source, digest = prepared if prepared is not None else parse_master(payload)
    check = _preview_rows(connection, rows, source, digest)
    if type(payload.get('revision')) is not int or payload['revision'] != check['revision']:
        raise ValueError('El maestro cambió. Revisa nuevamente la vista previa')
    if payload.get('digest') != check['digest']:
        raise ValueError('El archivo cambió. Revisa nuevamente la vista previa')
    new_revision, stamp = check['revision'] + 1, local_now()
    for item in rows:
        existing = connection.execute('SELECT * FROM warehouse_locations WHERE code=?', (item['code'],)).fetchone()
        before = {key: existing[key] for key in ('code', 'zone', 'rack', 'state', *DIMENSIONS)} if existing else {}
        after = {'zone': '', 'rack': '', 'state': 'HABILITADA', 'warehouse': '01',
                 'aisle': '', 'level': '', 'bin': '', **before, **item}
        if before == after:
            continue
        connection.execute('''INSERT INTO warehouse_locations
            (code,zone,rack,state,updated_at,updated_by,warehouse,aisle,level,bin)
            VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET zone=excluded.zone,rack=excluded.rack,
            state=excluded.state,updated_at=excluded.updated_at,updated_by=excluded.updated_by,
            warehouse=excluded.warehouse,aisle=excluded.aisle,level=excluded.level,bin=excluded.bin''',
            (after['code'], after['zone'], after['rack'], after['state'], stamp, username,
             *(after[key] for key in DIMENSIONS)))
        connection.execute('''INSERT INTO warehouse_location_history
            (code,before_json,after_json,reason,username,created_at,source,revision) VALUES (?,?,?,?,?,?,?,?)''',
            (item['code'], json.dumps(before), json.dumps(after), reason, username, stamp, source, new_revision))
    if check['added'] or check['changed']:
        connection.execute('UPDATE warehouse_location_revision SET revision=? WHERE id=1', (new_revision,))
    return {**check, 'revision': revision(connection)}


STOCK_CTE = '''WITH stock AS (
    SELECT upper(trim(default_location)) AS code, count(DISTINCT item_key) AS sku_count
    FROM inventory_stock WHERE is_current=1 AND warehouse_key='1' AND snapshot_qty>0
      AND trim(COALESCE(default_location,''))<>'' GROUP BY upper(trim(default_location))
), positions AS (
    SELECT l.*, COALESCE(s.sku_count,0) AS sku_count
    FROM warehouse_locations l LEFT JOIN stock s ON s.code=l.code
) '''


def catalog(connection, role, search='', state='', evidence='', offset=0):
    require_access(role)
    search = str(search or '').strip()
    if len(search) > 100 or state not in STATES | {''} or evidence not in {'', 'WITH_STOCK', 'NO_STOCK', 'UNMAPPED'}:
        raise ValueError('Filtros de ubicaciones no válidos')
    try:
        offset = int(offset)
    except (ValueError, TypeError) as error:
        raise ValueError('Página inválida') from error
    if offset < 0 or offset > 1000000:
        raise ValueError('Página inválida')
    if search[:3].lower() == ']d1':
        search = search[3:]
    # Literal matching: % and _ in rack identifiers are not SQL wildcards.
    match = '%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    stock = dict(connection.execute('''SELECT count(*) AS rows, max(snapshot_at) AS cutoff,
        sum(CASE WHEN snapshot_qty>0 AND trim(COALESCE(default_location,''))='' THEN 1 ELSE 0 END) AS missing_location
        FROM inventory_stock WHERE is_current=1 AND warehouse_key='1' ''').fetchone())
    summary = dict(connection.execute(STOCK_CTE + '''SELECT count(*) AS registered,
        sum(state<>'BAJA') AS installed, sum(state='HABILITADA') AS enabled,
        sum(state='BLOQUEADA') AS blocked, sum(state='HABILITADA' AND sku_count>0) AS with_stock,
        sum(state='BLOQUEADA' AND sku_count>0) AS blocked_with_stock FROM positions''').fetchone())
    summary = {key: int(value or 0) for key, value in summary.items()}
    unmapped = connection.execute(STOCK_CTE + '''SELECT count(*) FROM stock s
        WHERE NOT EXISTS(SELECT 1 FROM warehouse_locations l WHERE l.code=s.code AND l.state<>'BAJA')''').fetchone()[0]
    summary.update({'without_stock': summary['enabled'] - summary['with_stock'], 'unmapped': unmapped,
                    'ratio': round(summary['with_stock'] * 100 / summary['enabled'], 1)
                    if summary['enabled'] and stock['rows'] else None})
    if evidence == 'UNMAPPED':
        base = '''FROM stock s WHERE NOT EXISTS(SELECT 1 FROM warehouse_locations l WHERE l.code=s.code AND l.state<>'BAJA')
                  AND s.code LIKE ? ESCAPE '\\' '''
        parameters = (match,)
        count = connection.execute(STOCK_CTE + 'SELECT count(*) ' + base, parameters).fetchone()[0]
        rows = connection.execute(STOCK_CTE + "SELECT s.code,'' AS zone,'' AS rack,'SIN_REGISTRO' AS state,s.sku_count,"
                                  "'01' AS warehouse,'' AS aisle,'' AS level,'' AS bin " +
                                  base + ' ORDER BY s.code LIMIT 50 OFFSET ?', (*parameters, offset)).fetchall()
    else:
        base = """FROM positions WHERE (code LIKE ? ESCAPE '\\' OR zone LIKE ? ESCAPE '\\' OR rack LIKE ? ESCAPE '\\')
            AND (?='' OR state=?) AND (?='' OR (?='WITH_STOCK' AND sku_count>0) OR (?='NO_STOCK' AND sku_count=0)) """
        parameters = (match, match, match, state, state, evidence, evidence, evidence)
        count = connection.execute(STOCK_CTE + 'SELECT count(*) ' + base, parameters).fetchone()[0]
        rows = connection.execute(STOCK_CTE + 'SELECT code,zone,rack,state,sku_count,warehouse,aisle,level,bin ' +
                                  base + ' ORDER BY code LIMIT 50 OFFSET ?', (*parameters, offset)).fetchall()
    return {'items': [dict(row) for row in rows], 'total': count, 'offset': offset, 'limit': 50,
            'has_more': offset + len(rows) < count, 'summary': summary, 'stock': stock, 'revision': revision(connection)}


def labels(connection, payload, role, db_path):
    require_access(role)
    values = payload.get('codes')
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_LABELS:
        raise ValueError('Selecciona entre 1 y 200 ubicaciones por lote')
    codes = [code_key(value) for value in values]
    if len(set(codes)) != len(codes):
        raise ValueError('La selección contiene ubicaciones repetidas')
    copies = payload.get('copies', 1)
    if type(copies) is not int or not 1 <= copies <= 10 or copies * len(codes) > MAX_LABELS:
        raise ValueError('De 1 a 10 copias por ubicación, máximo 200 etiquetas por lote')
    placeholders = ','.join('?' for _ in codes)
    found = {row[0] for row in connection.execute(
        f"SELECT code FROM warehouse_locations WHERE code IN ({placeholders}) AND state<>'BAJA'", codes)}
    if set(codes) != found:
        raise ValueError('Una ubicación no está registrada o fue dada de baja; actualiza la selección')
    logo = label_brand('TRITON', db_path)['brand_logo_url'].replace('/api/reception-brand-logo?', '/api/inventory/brand-logo?')
    if not logo:
        raise ValueError('Falta el logo privado de Triton en el servidor')
    return {'codes': [code for code in codes for _ in range(copies)], 'logo': logo, 'revision': revision(connection)}


def history(connection, code, role):
    require_access(role, admin=True)
    return [dict(row) for row in connection.execute('''SELECT code,before_json,after_json,reason,username,created_at,source,revision
        FROM warehouse_location_history WHERE code=? ORDER BY id DESC LIMIT 30''', (code_key(code),))]
