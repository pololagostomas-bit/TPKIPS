"""Current explicit shared-EM coverage, separate from editable manual entries."""
import json
import sqlite3

REVISION = 1


def init_schema(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS reception_accounting_source_em(
        accounting_ref_id INTEGER PRIMARY KEY REFERENCES reception_accounting_refs(id) ON DELETE CASCADE,
        source_key TEXT NOT NULL,ip_keys TEXT NOT NULL,em_number TEXT NOT NULL,fr_number TEXT NOT NULL,
        source_file TEXT NOT NULL,observed_at TEXT NOT NULL)''')
    connection.execute('''CREATE TABLE IF NOT EXISTS reception_accounting_source_state(
        id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL)''')


def refresh_required(connection):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reception_accounting_refs'").fetchone():
        return False
    try:row=connection.execute('SELECT revision FROM reception_accounting_source_state WHERE id=1').fetchone()
    except sqlite3.OperationalError as error:
        if 'no such table' not in str(error):raise
        return True
    return not row or row['revision']<REVISION


def begin_snapshot(connection):
    connection.execute('DELETE FROM reception_accounting_source_em')


def store(connection, reference_id, record, filename, timestamp):
    from backend.services.reception import _ip_tokens, _accounting_em_tokens
    ips=sorted(set(_ip_tokens(record['ip_reference'])))
    ems=sorted(set(_accounting_em_tokens(record['em_number'])))
    if len(ips)>1 and str(record['fr_number'] or '').strip():
        connection.execute('INSERT INTO reception_accounting_source_em VALUES(?,?,?,?,?,?,?)',
            (reference_id,record['source_key'],json.dumps(ips),', '.join(ems),str(record['fr_number']).strip(),filename,timestamp))


def finish_snapshot(connection):
    connection.execute('''INSERT INTO reception_accounting_source_state VALUES(1,?)
        ON CONFLICT(id) DO UPDATE SET revision=excluded.revision''',(REVISION,))


def declared(connection, reference_id, ip_key):
    """None means no completed snapshot yet; an empty list is current absence."""
    from backend.services.reception import _ip_tokens, _accounting_em_tokens
    if not ip_key:return []
    try:
        proof=connection.execute('''SELECT p.*,r.ip_reference,r.source_key AS current_key,r.fr_number AS current_fr
            FROM reception_accounting_source_em p JOIN reception_accounting_refs r ON r.id=p.accounting_ref_id
            WHERE p.accounting_ref_id=?''',(reference_id,)).fetchone()
    except sqlite3.OperationalError as error:
        if 'no such table' not in str(error):raise
        return None
    if not proof:return None if refresh_required(connection) else []
    ips=set(json.loads(proof['ip_keys']))
    if (proof['source_key']!=proof['current_key'] or proof['fr_number']!=str(proof['current_fr'] or '').strip()
            or ips!=set(_ip_tokens(proof['ip_reference'])) or ip_key not in ips or not proof['source_file']):
        return []
    return list(dict.fromkeys(_accounting_em_tokens(proof['em_number'])))


def values(connection, reference_id, ip_key):
    ems=declared(connection,reference_id,ip_key) or []
    return ems if len(ems)==1 else []
