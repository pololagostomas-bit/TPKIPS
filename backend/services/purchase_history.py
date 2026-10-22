"""Observed purchase-rule episodes; no operational database or mail access."""
import csv
import io
import json
from datetime import date, datetime, timezone


def request_dates_text(case):
    dates, missing = set(), not case.get('sources')
    for source in case.get('sources', []):
        try:
            dates.add(date.fromisoformat(source.get('request_date') or ''))
        except (ValueError, TypeError):
            missing = True
    labels = [day.strftime('%d/%m/%Y') for day in sorted(dates)]
    if missing:
        labels.append('Sin fecha')
    return '; '.join(labels)


def initialize(connection):
    connection.executescript('''
        CREATE TABLE IF NOT EXISTS purchase_episodes(
            id INTEGER PRIMARY KEY, issue_key TEXT NOT NULL, issue_type TEXT NOT NULL,
            severity TEXT NOT NULL, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
            resolved_at TEXT, resolution TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS purchase_episode_open
            ON purchase_episodes(issue_key) WHERE resolved_at IS NULL;
        CREATE INDEX IF NOT EXISTS purchase_episode_status
            ON purchase_episodes(resolved_at,severity,id);
    ''')


def observe(connection, snapshot, stamp):
    active = {row['issue_key']: row for row in connection.execute(
        'SELECT * FROM purchase_episodes WHERE resolved_at IS NULL')}
    checked = {str(sheet).strip().casefold() for sheet in snapshot['sheets']}
    ov_sheets = {str(sheet).strip().casefold() for sheet in snapshot.get('ov_sheets', [])}
    for episode in active.values():
        old = json.loads(episode['payload'])
        evidence_sheets = {source['sheet'] for source in old['sources']} | set(old.get('unverified_sheets', []))
        if episode['issue_type'] == 'COT' and any(
                sheet.strip().casefold() in checked - ov_sheets for sheet in evidence_sheets):
            raise ValueError('Falta la columna OV en una hoja con alertas COT pendientes.')
    current = {}
    for case in snapshot['cases']:
        key = case['history_key']
        if key not in current:
            current[key] = {**case, 'sources': list(case['sources'])}
        else:
            item = current[key]
            item['sources'].extend(case['sources'])
            item['preliminary'] = ' / '.join(sorted(set(item['preliminary'].split(' / ') + [case['preliminary']])))
    for key, case in current.items():
        previous = json.loads(active[key]['payload']) if key in active else {}
        evidence_sheets = {source['sheet'] for source in previous.get('sources', [])} | set(previous.get('unverified_sheets', []))
        case['unverified_sheets'] = sorted(sheet for sheet in evidence_sheets if sheet.strip().casefold() not in checked)
        payload = json.dumps(case, ensure_ascii=False)
        if key in active:
            connection.execute('UPDATE purchase_episodes SET last_seen_at=?,payload=? WHERE id=?',
                               (stamp, payload, active[key]['id']))
        else:
            connection.execute('''INSERT INTO purchase_episodes
                (issue_key,issue_type,severity,first_seen_at,last_seen_at,payload)
                VALUES(?,?,?,?,?,?)''', (key, case['issue_type'], case['severity'], stamp, stamp, payload))
    for key, episode in active.items():
        old = json.loads(episode['payload'])
        evidence_sheets = {source['sheet'] for source in old['sources']} | set(old.get('unverified_sheets', []))
        # A deliberately excluded sheet is out of scope, not proof of a correction.
        if key not in current and all(sheet.strip().casefold() in checked for sheet in evidence_sheets):
            connection.execute('UPDATE purchase_episodes SET resolved_at=?,resolution=? WHERE id=?',
                (stamp, 'Dejo de cumplir la regla o de aparecer en una revision completa', episode['id']))
    for case in snapshot['cases']:
        episode = connection.execute('SELECT id,first_seen_at FROM purchase_episodes '
            'WHERE issue_key=? AND resolved_at IS NULL', (case['history_key'],)).fetchone()
        case.update(episode_id=episode['id'], first_seen_at=episode['first_seen_at'])


def query(connection, state='pending', severity='ALL', limit=50, offset=0, now=None, export=False):
    if state not in {'pending', 'resolved', 'all'} or severity not in {'ALL', 'GRAVE', 'REGULARIZAR'}:
        raise ValueError('Filtro de historial no valido.')
    limit, offset = int(limit), int(offset)
    if not export and (not 1 <= limit <= 100 or offset < 0):
        raise ValueError('Pagina de historial no valida.')
    conditions, params = [], []
    if state != 'all':
        conditions.append('resolved_at IS ' + ('NULL' if state == 'pending' else 'NOT NULL'))
    if severity != 'ALL':
        conditions.append('severity=?')
        params.append(severity)
    where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    total = connection.execute('SELECT COUNT(*) FROM purchase_episodes' + where, params).fetchone()[0]
    if export and total > 50000:
        raise ValueError('Filtra el historial antes de descargar: maximo 50000 episodios.')
    rows = connection.execute('SELECT * FROM purchase_episodes' + where +
        " ORDER BY severity='GRAVE' DESC,resolved_at IS NOT NULL,first_seen_at,id LIMIT ? OFFSET ?",
        [*params, 50000 if export else limit, 0 if export else offset]).fetchall()
    moment = datetime.fromtimestamp(now, timezone.utc) if now is not None else datetime.now(timezone.utc)
    items = []
    for row in rows:
        item = {**json.loads(row['payload']), **dict(row)}
        item.pop('payload')
        end = datetime.fromisoformat(row['resolved_at']) if row['resolved_at'] else moment
        item['elapsed_hours'] = round(max(0, (end - datetime.fromisoformat(row['first_seen_at'])).total_seconds()) / 3600, 2)
        item['status'] = 'RESUELTO' if row['resolved_at'] else 'PENDIENTE'
        item['request_date_display'] = request_dates_text(item)
        items.append(item)
    return {'items': items, 'total': total, 'offset': offset, 'limit': limit,
            'has_more': offset + len(items) < total}


def csv_bytes(result):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['Episodio', 'Nivel', 'Regla', 'Estado', 'Comprador / hoja', 'OC / Preliminar',
        'IP / Pedido Triton', 'OV', 'Fecha de solicitud IMP/OV', 'Primera deteccion UTC', 'Ultima observacion UTC',
        'Fin observado UTC', 'Horas calendario', 'Resultado', 'Hojas sin revisar'])

    def safe(value):
        text = '' if value is None else str(value)
        return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')) else text

    for item in result['items']:
        writer.writerow([safe(value) for value in [item['id'], item['severity'], item['issue_type'],
            item['status'], ', '.join(sorted({s['sheet'] for s in item['sources']})),
            item['preliminary'], item['ip'], item.get('ov', ''), request_dates_text(item), item['first_seen_at'],
            item['last_seen_at'], item['resolved_at'], item['elapsed_hours'], item['resolution'],
            ', '.join(item.get('unverified_sheets', []))]])
    return output.getvalue().encode('utf-8-sig')
