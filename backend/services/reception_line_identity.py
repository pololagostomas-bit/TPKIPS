"""Stable local line numbers and documentary aliases; physical rows never merge."""
import re
import sqlite3


class ImportLineConflict(ValueError):
    """Private detailed conflict; cloud status must use a redacted diagnostic."""


class MatchPlan(dict):
    def __init__(self):
        super().__init__()
        self.legacy = {}


def init_schema(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS reception_import_keys(
        source_key TEXT PRIMARY KEY,line_id INTEGER NOT NULL REFERENCES reception_lines(id),
        first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL)''')
    connection.execute('CREATE INDEX IF NOT EXISTS idx_reception_import_key_line ON reception_import_keys(line_id)')
    connection.execute('''CREATE TABLE IF NOT EXISTS reception_import_legacy(
        legacy_line_id INTEGER PRIMARY KEY REFERENCES reception_lines(id),
        canonical_line_id INTEGER NOT NULL REFERENCES reception_lines(id),
        detected_at TEXT NOT NULL,CHECK(legacy_line_id<>canonical_line_id))''')


def stored(connection, table):
    # Read-only preflight may run against an installation preceding this schema.
    if table not in {'reception_import_keys','reception_import_legacy'}:
        raise ValueError('Unsupported identity table')
    try:return [dict(row) for row in connection.execute('SELECT * FROM '+table)]
    except sqlite3.OperationalError as error:
        if 'no such table' not in str(error):raise
        return []


def legacy_ids(connection):
    return {row['legacy_line_id'] for row in stored(connection,'reception_import_legacy')}


def allow_legacy_overlap(candidate, competing, inverse, record, grouped):
    """Narrow PRE revision with an incomplete older documentary representation.

    Same historical position is supporting evidence, never the sole identity.
    Concurrent current orders or two complete IP anchors still need review.
    """
    family=lambda row:tuple(str(row.get(k) or '').strip() for k in ('source_sheet','guide','ov','np_code'))
    current=[r for records in grouped.values() for r in records if family(r)==family(record)]
    candidate=dict(candidate)
    if (inverse or len(competing)!=1 or len(current)!=1 or not record['ip']
            or str(candidate['ip_reference'] or '').strip()!=record['ip']
            or not re.search(r'\bPRE(?:LIMINAR)?\b',str(candidate['oc_number'] or '').upper())
            or not re.fullmatch(r'\d{5}',record['oc'])):
        return False
    for row in competing:
        if (str(row['ip_reference'] or '').strip() or not row['source_row']
                or row['source_row']!=candidate['source_row']
                or abs(float(row['expected_qty'] or 0)-float(candidate['expected_qty'] or 0))>1e-9
                or str(row['description'] or '').strip()!=str(candidate['description'] or '').strip()):
            return False
    return True


def remember(connection, plan, record, line_id, stamp, username):
    from backend.services.reception import _write_history
    def bind(key):
        if key:
            connection.execute('''INSERT INTO reception_import_keys VALUES(?,?,?,?)
                ON CONFLICT(source_key) DO UPDATE SET line_id=excluded.line_id,last_seen_at=excluded.last_seen_at''',
                (key,line_id,stamp,stamp))
    old=plan.get(record['source_key'])
    if old:bind(old['source_key'])
    bind(record['source_key'])
    for legacy in plan.legacy.get(line_id,[]):
        # Archive only the documentary key; keep both IDs, quantities and work.
        connection.execute('INSERT INTO reception_import_legacy VALUES(?,?,?)',
                           (legacy['id'],line_id,stamp))
        bind(legacy['source_key'])
        connection.execute('UPDATE reception_lines SET source_key=NULL WHERE id=?',(legacy['id'],))
        _write_history(connection,legacy['shipment_id'],'IDENTIDAD DOCUMENTAL',
            f"linea:{legacy['id']}:referencia_vigente",legacy['id'],line_id,username,
            'Antecedente documental incompleto de una PRE regularizada; cantidades y lecturas conservadas')
