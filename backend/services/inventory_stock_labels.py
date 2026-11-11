"""Read-only bulk SKU labels, using the existing inventory label authority."""
import base64
import csv
import math
import re
import unicodedata
from io import BytesIO, StringIO
from itertools import islice
from zipfile import ZipFile, BadZipFile
from xml.etree.ElementTree import ParseError

from backend.services.safe_excel import load_workbook
from backend.services.inventory_governance import INVENTORY_ROLES, inventory_label

MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_ROWS = 50000
MAX_CODES = 20000
BATCH_SIZE = 100
PRINT_SIZE = 500
HEADERS = {'np', 'sku', 'npsku', 'itemcode', 'codarticulo', 'codigoarticulo',
           'codigodearticulo', 'codigodearticulonp', 'numerodeparte', 'nrodeparte', 'partnumber'}
ASCII_UPPER = str.maketrans('abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ')


def require_access(role):
    if str(role or '').upper() not in INVENTORY_ROLES:
        raise PermissionError('Tu usuario no tiene acceso a etiquetas de stock')


def _heading(value):
    text = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode()
    return re.sub('[^a-z0-9]', '', text.lower())


def _code(value):
    if isinstance(value, bool) or (isinstance(value, float) and not math.isfinite(value)):
        raise ValueError('El NP debe ser un código de artículo')
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    code = '' if value is None else str(value).strip()
    if not code or len(code) > 100 or code.startswith('=') or re.search(r'[\x00-\x1f\x7f]', code):
        raise ValueError('Usa un NP de hasta 100 caracteres, sin fórmulas ni caracteres de control')
    return code


def _csv_rows(text):
    try:
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t')
        except csv.Error:
            dialect = csv.excel_tab if '\t' in text else csv.excel
        return list(islice(csv.reader(StringIO(text), dialect), MAX_ROWS + 21))
    except csv.Error as error:
        raise ValueError('No se pudo leer el listado CSV') from error


def parse_list(payload):
    if not isinstance(payload, dict):
        raise ValueError('Carga un archivo o pega un listado de NP')
    if payload.get('text') and payload.get('file_base64'):
        raise ValueError('Carga un archivo o pega el listado, no ambos')
    file_input = bool(payload.get('file_base64'))
    if file_input:
        encoded = payload['file_base64']
        if not isinstance(encoded, str) or len(encoded) > MAX_FILE_BYTES * 4 // 3 + 8:
            raise ValueError('El archivo supera 4 MB')
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError('Archivo no válido') from error
        if len(content) > MAX_FILE_BYTES:
            raise ValueError('El archivo supera 4 MB')
        filename = str(payload.get('filename') or '')
        if filename.lower().endswith('.xlsx'):
            try:
                with ZipFile(BytesIO(content)) as archive:
                    if len(archive.infolist()) > 1000 or sum(e.file_size for e in archive.infolist()) > 24 * 1024 * 1024:
                        raise ValueError('El Excel es demasiado grande al descomprimir')
                workbook = load_workbook(BytesIO(content), read_only=True, data_only=False, keep_links=False)
                try:
                    sheet = workbook.active
                    if not hasattr(sheet, 'iter_rows') or (sheet.max_column or 0) > 30:
                        raise ValueError('Usa una hoja de hasta 30 columnas')
                    sheet.reset_dimensions()
                    rows = list(islice(sheet.iter_rows(max_col=30, values_only=True), MAX_ROWS + 21))
                finally:
                    workbook.close()
            except (BadZipFile, KeyError, OSError, ParseError) as error:
                raise ValueError('No se pudo leer el Excel') from error
        elif filename.lower().endswith('.csv'):
            try:
                rows = _csv_rows(content.decode('utf-8-sig'))
            except UnicodeError as error:
                raise ValueError('Guarda el CSV como UTF-8') from error
        else:
            raise ValueError('Usa un archivo Excel .xlsx o CSV')
    else:
        text = payload.get('text')
        if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_FILE_BYTES:
            raise ValueError('Pega un NP por línea; máximo 4 MB')
        rows = _csv_rows(text) if '\t' in text else [[line] for line in text.splitlines()]
    header, column = -1, 0
    for index, row in enumerate(rows[:20]):
        if len(row) > 30:
            raise ValueError('Usa un listado de hasta 30 columnas')
        candidates = [i for i, cell in enumerate(row) if _heading(cell) in HEADERS]
        if len(candidates) > 1:
            raise ValueError('Hay varias columnas de NP; conserva una sola')
        if candidates:
            header, column = index, candidates[0]
            break
    if file_input and header < 0:
        raise ValueError('El archivo necesita un encabezado NP, SKU o Código de artículo')
    if len(rows) - header - 1 > MAX_ROWS:
        raise ValueError('Máximo 50000 filas por carga')
    codes, seen, duplicates = [], set(), 0
    for number, row in enumerate(rows[header + 1:], header + 2):
        if len(row) > 30:
            raise ValueError(f'Fila {number}: máximo 30 columnas')
        value = row[column] if column < len(row) else None
        if value is None or not str(value).strip():
            continue
        try:
            code = _code(value)
        except ValueError as error:
            raise ValueError(f'Fila {number}: {error}') from error
        key = code.translate(ASCII_UPPER)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key); codes.append(code)
        if len(codes) > MAX_CODES:
            raise ValueError('Máximo 20000 NP distintos por carga')
    if not codes:
        raise ValueError('El listado no contiene NP')
    return {'codes': codes, 'duplicates': duplicates, 'batch_size': BATCH_SIZE, 'print_size': PRINT_SIZE}


def labels_batch(connection, payload, username, role, *, db_path):
    require_access(role)
    codes = payload.get('codes') if isinstance(payload, dict) else None
    if not isinstance(codes, list) or not 1 <= len(codes) <= BATCH_SIZE:
        raise ValueError('Verifica entre 1 y 100 NP por solicitud')
    codes = [_code(code) if isinstance(code, str) else _code(None) for code in codes]
    items, missing, seen = [], [], set()
    for code in codes:
        if code.translate(ASCII_UPPER) in seen:
            continue
        seen.add(code.translate(ASCII_UPPER))
        try:
            items.append(inventory_label(connection, code, username, role, db_path=db_path))
        except ValueError:
            missing.append(code)
    return {'items': items, 'missing': missing}
