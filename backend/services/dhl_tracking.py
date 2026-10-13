"""Bounded, server-only DHL Express tracking; never a physical receipt or ASN."""
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from backend.services.daily_operations import local_now

ENDPOINT = 'https://api-eu.dhl.com/track/shipments'
MESSAGES = {
    'disabled': 'Conexion DHL desactivada.',
    'configuration': 'Falta la clave DHL protegida en el servidor.',
    'authorization': 'DHL rechazo la credencial. Revisa su aprobacion o reemplaza la clave.',
    'quota': 'DHL limito las consultas. Se reintentara mas tarde.',
    'not_found': 'DHL no encontro esta guia Express.',
    'network': 'DHL no responde. La recepcion fisica sigue disponible.',
    'response': 'DHL devolvio datos no validos para esta guia.',
    'conflict': 'DHL asigno un bulto a mas de una guia. Requiere revision.',
}
LABELS = {'delivered': 'Entregado por DHL', 'transit': 'En transito DHL',
          'pre-transit': 'Previo al transporte', 'failure': 'Incidencia DHL',
          'unknown': 'Estado DHL no informado'}
_guard = threading.Lock()
_started = False


def enabled():
    return os.getenv('WMS_DHL_ENABLED', '0') == '1'


def daily_budget():
    # Leave headroom in the initial 250/day plan for support and manual tests.
    try:
        return max(1, min(200, int(os.getenv('WMS_DHL_DAILY_BUDGET', '200'))))
    except ValueError:
        return 200


def refresh_seconds():
    try:
        return max(24 * 3600, int(os.getenv('WMS_DHL_REFRESH_HOURS', '24')) * 3600)
    except ValueError:
        return 24 * 3600


def prefetch_limit():
    try:
        return max(1, min(100, int(os.getenv('WMS_DHL_PREFETCH_LIMIT', '100'))))
    except ValueError:
        return 100


def _key():
    try:
        with Path(os.getenv('DHL_API_KEY_FILE', '/run/secrets/dhl_api_key')).open('rb') as stream:
            value = stream.read(513).decode('ascii').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,512}', value):
            raise ValueError
        return value
    except (OSError, UnicodeError, ValueError):
        raise TrackingError('configuration') from None


def init_schema(connection):
    statements = (
        """CREATE TABLE IF NOT EXISTS dhl_tracking_cache (
            awb TEXT PRIMARY KEY, status_code TEXT NOT NULL, total_pieces INTEGER,
            checked_at REAL NOT NULL, event_at REAL, delivered_at REAL, expires_at REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS dhl_tracking_pieces (
            piece_id TEXT PRIMARY KEY, awb TEXT NOT NULL REFERENCES dhl_tracking_cache(awb) ON DELETE CASCADE)""",
        "CREATE INDEX IF NOT EXISTS idx_dhl_pieces_awb ON dhl_tracking_pieces(awb)",
        "CREATE INDEX IF NOT EXISTS idx_dhl_cache_expiry ON dhl_tracking_cache(expires_at)",
        """CREATE TABLE IF NOT EXISTS dhl_tracking_jobs (
            awb TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT 'queued', next_at REAL NOT NULL,
            lease_until REAL NOT NULL DEFAULT 0, priority INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0, day TEXT NOT NULL DEFAULT '',
            calls INTEGER NOT NULL DEFAULT 0, error_code TEXT NOT NULL DEFAULT '')""",
        "CREATE INDEX IF NOT EXISTS idx_dhl_jobs_due ON dhl_tracking_jobs(state, next_at)",
        """CREATE TABLE IF NOT EXISTS dhl_tracking_runtime (
            id INTEGER PRIMARY KEY CHECK(id=1), day TEXT NOT NULL DEFAULT '',
            calls INTEGER NOT NULL DEFAULT 0, last_call REAL NOT NULL DEFAULT 0,
            inflight_until REAL NOT NULL DEFAULT 0,
            blocked_until REAL NOT NULL DEFAULT 0, auth_blocked INTEGER NOT NULL DEFAULT 0,
            key_digest TEXT NOT NULL DEFAULT '', heartbeat REAL NOT NULL DEFAULT 0,
            maintained_at REAL NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '')""",
        'INSERT OR IGNORE INTO dhl_tracking_runtime(id) VALUES (1)',
    )
    for statement in statements:
        connection.execute(statement)


def awb_code(value):
    value = re.sub(r'[\s-]+', '', str(value or ''))
    return value if re.fullmatch(r'[0-9]{10}', value) else None


def piece_code(value):
    """Normalize only the DHL Express (J)JD numeric label family."""
    code = re.sub(r'\s+', '', str(value or '')).upper()
    match = re.fullmatch(r'(?:J|\(J\))?JD([0-9]+)', code)
    return 'JD' + match[1] if match else code


def piece_aliases(value):
    code = piece_code(value)
    if re.fullmatch(r'JD[0-9]+', code):
        return (code, 'J' + code, '(J)' + code)
    return (code,)


def _eligible(shipment):
    return (str(shipment['app_status']).upper() != 'CERRADO'
            and str(shipment['transport_type']).upper() in {'COURIER', 'AEREO'}
            and awb_code(shipment['bl_awb']) is not None)


def _shipment(connection, shipment_id):
    try:
        shipment_id = int(shipment_id)
    except (TypeError, ValueError):
        raise ValueError('Selecciona una BL valida.') from None
    row = connection.execute('SELECT * FROM reception_shipments WHERE id=?', (shipment_id,)).fetchone()
    if row is None:
        raise ValueError('La BL no existe en Importaciones.')
    return row


def enqueue(connection, shipment_id, now=None):
    shipment = _shipment(connection, shipment_id)
    if not enabled() or not _eligible(shipment):
        return False
    return _queue(connection, awb_code(shipment['bl_awb']), now or time.time(), priority=1)


def _queue(connection, awb, now, priority=0):
    # INSERT OR IGNORE deduplicates scans/polls, preserving TTL, backoff and quotas.
    connection.execute('INSERT OR IGNORE INTO dhl_tracking_jobs(awb,next_at,priority) VALUES (?,?,?)',
                       (awb, now, priority))
    if priority:
        connection.execute('UPDATE dhl_tracking_jobs SET priority=1 WHERE awb=? AND priority=0', (awb,))
    return True


def purge(connection, now):
    expired = [row[0] for row in connection.execute(
        'SELECT awb FROM dhl_tracking_cache WHERE expires_at<=?', (now,))]
    for awb in expired:
        connection.execute('PRAGMA secure_delete=ON')
        connection.execute('DELETE FROM dhl_tracking_pieces WHERE awb=?', (awb,))
        connection.execute('DELETE FROM dhl_tracking_cache WHERE awb=?', (awb,))
        connection.execute("UPDATE dhl_tracking_jobs SET state='expired', error_code='', lease_until=0 WHERE awb=?", (awb,))


def maintain(connection, now, today=None):
    purge(connection, now)
    today = today or datetime.fromisoformat(local_now()).date()
    month_start = today.replace(day=1)
    month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    nearby_start, nearby_end = today - timedelta(days=7), today + timedelta(days=14)
    # Never use import/update timestamps: reloading Excel would select all history.
    candidates = connection.execute("""SELECT id, bl_awb, transport_type, app_status FROM reception_shipments
        WHERE app_status<>'CERRADO' AND UPPER(transport_type)='COURIER'
          AND length(replace(replace(bl_awb,' ',''),'-',''))=10
          AND replace(replace(bl_awb,' ',''),'-','') NOT GLOB '*[^0-9]*'
          AND (substr(scheduled_date,1,10) BETWEEN ? AND ?
            OR substr(scheduled_date,1,10) BETWEEN ? AND ?
            OR substr(first_arrival_at,1,10) BETWEEN ? AND ?)
        GROUP BY replace(replace(bl_awb,' ',''),'-','')
        ORDER BY CASE WHEN COALESCE(first_arrival_at,'')<>'' THEN 2
                 WHEN substr(scheduled_date,1,10)>=? THEN 0 ELSE 1 END,
                 abs(julianday(substr(scheduled_date,1,10))-julianday(?)), id
        LIMIT ?""", (str(month_start), str(month_end), str(nearby_start), str(nearby_end),
                      str(month_start), str(month_end), str(today), str(today), prefetch_limit()))
    for row in candidates:
        if _eligible(row):
            _queue(connection, awb_code(row['bl_awb']), now)
    # Previously tracked, still-open guides carry across a week boundary.
    connection.execute("""UPDATE dhl_tracking_jobs SET state='queued', lease_until=0
        WHERE state='running' AND lease_until<=?""", (now,))


def shipment_status(connection, shipment_id, now=None):
    now = now or time.time()
    row = _shipment(connection, shipment_id)
    awb = awb_code(row['bl_awb'])
    base = {'applicable': bool(awb and str(row['transport_type']).upper() in {'COURIER', 'AEREO'}),
            'enabled': enabled(), 'state': 'disabled' if not enabled() else 'pending',
            'total_pieces': None, 'known_pieces': 0, 'checked_at': None, 'status_label': '', 'error': ''}
    if not enabled() or not base['applicable']:
        return base
    cache = connection.execute('SELECT * FROM dhl_tracking_cache WHERE awb=? AND expires_at>?', (awb, now)).fetchone()
    job = connection.execute('SELECT * FROM dhl_tracking_jobs WHERE awb=?', (awb,)).fetchone()
    if cache:
        base.update(state='ready', total_pieces=cache['total_pieces'], checked_at=cache['checked_at'],
                    status_label=LABELS.get(cache['status_code'], LABELS['unknown']),
                    known_pieces=connection.execute('SELECT COUNT(*) FROM dhl_tracking_pieces WHERE awb=?', (awb,)).fetchone()[0])
    if job:
        base.update(pending=job['state'] in {'queued', 'running'}, next_check_at=job['next_at'])
        if job['error_code']:
            base.update(state='stale' if cache else 'error', error=MESSAGES.get(job['error_code'], MESSAGES['response']))
        if job['state'] == 'expired':
            base.update(state='expired', pending=False)
    runtime = connection.execute('SELECT * FROM dhl_tracking_runtime WHERE id=1').fetchone()
    if runtime and runtime['auth_blocked']:
        base.update(error=MESSAGES['authorization'], state='stale' if cache else 'error', pending=False)
    elif runtime and runtime['last_error'] == 'configuration':
        base.update(error=MESSAGES['configuration'], state='stale' if cache else 'error', pending=False)
    elif runtime and (runtime['blocked_until'] > now or
            (runtime['day'] == datetime.fromtimestamp(now, timezone.utc).date().isoformat() and runtime['calls'] >= daily_budget())):
        base.update(error=MESSAGES.get(runtime['last_error'], 'Presupuesto diario DHL alcanzado. Consulta pendiente.'), pending=False)
    return base


def verify_piece(connection, shipment_id, normalized_code, now=None):
    """Local-only verification; unknown labels remain valid physical observations."""
    if not enabled():
        return 'unavailable'
    row = _shipment(connection, shipment_id)
    awb = awb_code(row['bl_awb'])
    owner = piece_owner(connection, normalized_code, now)
    if owner and owner != awb:
        raise ValueError('DHL identifica ese bulto en la BL/AWB ' + owner + '. Selecciona su BL antes de escanear.')
    if owner:
        return 'verified'
    return 'unverified' if awb else 'not_applicable'


def piece_owner(connection, normalized_code, now=None):
    """Resolve a unique piece from retained cache only; never contact DHL here."""
    if not enabled():
        return None
    aliases = piece_aliases(normalized_code)
    placeholders = ','.join('?' for _ in aliases)
    rows = connection.execute(f"""SELECT DISTINCT p.awb FROM dhl_tracking_pieces p
        JOIN dhl_tracking_cache c ON c.awb=p.awb
        WHERE p.piece_id IN ({placeholders}) AND c.expires_at>? LIMIT 2""",
        (*aliases, now or time.time())).fetchall()
    if len(rows) > 1:
        raise ValueError(MESSAGES['conflict'])
    return rows[0]['awb'] if rows else None


class TrackingError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(MESSAGES[code])


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc).timestamp() if parsed.tzinfo is None else parsed.timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def parse_response(payload, awb, now):
    try:
        matches = [item for item in payload['shipments'] if item['id'] == awb and item['service'] == 'express']
        if len(matches) != 1:
            raise ValueError
        item = matches[0]
        details = item.get('details') or {}
        raw_pieces = details.get('pieceIds') or []
        if not isinstance(raw_pieces, list) or len(raw_pieces) > 2000:
            raise ValueError
        pieces = set()
        for piece in raw_pieces:
            if not isinstance(piece, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,120}', piece):
                raise ValueError
            pieces.add(piece_code(piece))
        total = details.get('totalNumberOfPieces')
        if total is not None and (type(total) is not int or not 1 <= total <= 2000 or total < len(pieces)):
            raise ValueError
        status = item.get('status') or {}
        code = status.get('statusCode', 'unknown')
        code = code if code in LABELS else 'unknown'
        event = _timestamp(status.get('timestamp'))
        if event and event > now + 86400:
            raise ValueError
        delivered = event if code == 'delivered' else None
        if code == 'delivered' and not delivered:
            dates = [_timestamp(entry.get('timestamp')) for entry in item.get('events', [])
                     if entry.get('statusCode') == 'delivered']
            delivered = min((stamp for stamp in dates if stamp and stamp <= now), default=None)
        return {'status_code': code, 'total_pieces': total, 'pieces': sorted(pieces),
                'event_at': event, 'delivered_at': delivered,
                'expires_at': now if code == 'delivered' and delivered is None else (delivered or now) + 30 * 86400}
    except (KeyError, TypeError, ValueError, AttributeError):
        raise TrackingError('response') from None


def fetch_tracking(awb, key, now):
    request = Request(ENDPOINT + '?' + urlencode({'trackingNumber': awb, 'service': 'express', 'language': 'en'}),
                      headers={'DHL-API-Key': key, 'Accept': 'application/json'})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=20) as response:
            if response.headers.get_content_type() != 'application/json':
                raise TrackingError('response')
            body = response.read(1_048_577)
        if len(body) > 1_048_576:
            raise TrackingError('response')
        return parse_response(json.loads(body), awb, now)
    except HTTPError as error:
        code = ('authorization' if error.code in {401, 403} else 'quota' if error.code == 429
                else 'not_found' if error.code in {400, 404} else 'network')
        error.close()
        raise TrackingError(code) from None
    except (URLError, TimeoutError, OSError):
        raise TrackingError('network') from None
    except (ValueError, UnicodeError):
        raise TrackingError('response') from None


def worker_cycle(app, now=None, today=None):
    now = now or time.time()
    with app.db() as connection:
        connection.execute('BEGIN IMMEDIATE')
        purge(connection, now)
        runtime = connection.execute('SELECT * FROM dhl_tracking_runtime WHERE id=1').fetchone()
        if enabled() and runtime['maintained_at'] + 300 <= now:
            maintain(connection, now, today)
            connection.execute('UPDATE dhl_tracking_runtime SET maintained_at=? WHERE id=1', (now,))
    if not enabled():
        return False
    try:
        key = _key()
    except TrackingError as error:
        with app.db() as connection:
            connection.execute('UPDATE dhl_tracking_runtime SET heartbeat=?, last_error=? WHERE id=1', (now, error.code))
        return False
    digest = hashlib.sha256(key.encode('ascii')).hexdigest()
    day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    with app.db() as connection:
        connection.execute('BEGIN IMMEDIATE')
        runtime = connection.execute('SELECT * FROM dhl_tracking_runtime WHERE id=1').fetchone()
        connection.execute('UPDATE dhl_tracking_runtime SET heartbeat=? WHERE id=1', (now,))
        if runtime['inflight_until'] > now:
            return False
        if digest != runtime['key_digest']:
            connection.execute("UPDATE dhl_tracking_runtime SET key_digest=?, auth_blocked=0, last_error='' WHERE id=1", (digest,))
            connection.execute("UPDATE dhl_tracking_jobs SET next_at=? WHERE error_code='authorization'", (now,))
        elif runtime['auth_blocked']:
            return False
        elif runtime['last_error'] == 'configuration':
            connection.execute("UPDATE dhl_tracking_runtime SET last_error='' WHERE id=1")
        calls = runtime['calls'] if runtime['day'] == day else 0
        if calls >= daily_budget() or runtime['blocked_until'] > now or runtime['last_call'] + 5.2 > now:
            return False
        job = connection.execute("""SELECT j.* FROM dhl_tracking_jobs j
            WHERE j.state IN ('queued','error','ready') AND j.next_at<=?
              AND (j.day<>? OR j.calls<10)
              AND EXISTS (SELECT 1 FROM reception_shipments s WHERE
                replace(replace(s.bl_awb,' ',''),'-','')=j.awb AND s.app_status<>'CERRADO')
            ORDER BY j.priority DESC, CASE WHEN j.state='queued' THEN 0 ELSE 1 END, j.next_at LIMIT 1""", (now, day)).fetchone()
        if not job:
            return False
        connection.execute('UPDATE dhl_tracking_runtime SET day=?, calls=?, last_call=?, inflight_until=? WHERE id=1', (day, calls + 1, now, now + 120))
        connection.execute("UPDATE dhl_tracking_jobs SET state='running', lease_until=?, day=?, calls=?, attempts=attempts+1 WHERE awb=?",
                           (now + 120, day, (job['calls'] if job['day'] == day else 0) + 1, job['awb']))
    # No network under an app DB transaction, or in a scanner HTTP request.
    try:
        result = fetch_tracking(job['awb'], key, now)
        with app.db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            for piece in result['pieces']:
                aliases = piece_aliases(piece)
                placeholders = ','.join('?' for _ in aliases)
                if connection.execute(f'SELECT 1 FROM dhl_tracking_pieces WHERE piece_id IN ({placeholders}) AND awb<>?',
                                      (*aliases, job['awb'])).fetchone():
                    raise TrackingError('conflict')
            connection.execute("""INSERT INTO dhl_tracking_cache
                (awb,status_code,total_pieces,checked_at,event_at,delivered_at,expires_at) VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(awb) DO UPDATE SET status_code=excluded.status_code, total_pieces=excluded.total_pieces,
                checked_at=excluded.checked_at,event_at=excluded.event_at,delivered_at=excluded.delivered_at,expires_at=excluded.expires_at""",
                (job['awb'], result['status_code'], result['total_pieces'], now,
                 result['event_at'], result['delivered_at'], result['expires_at']))
            connection.execute('DELETE FROM dhl_tracking_pieces WHERE awb=?', (job['awb'],))
            connection.executemany('INSERT INTO dhl_tracking_pieces(piece_id,awb) VALUES (?,?)',
                                   [(piece, job['awb']) for piece in result['pieces']])
            connection.execute("UPDATE dhl_tracking_jobs SET state='ready', error_code='', attempts=0, priority=0, lease_until=0, next_at=? WHERE awb=?",
                               (result['expires_at'] if result['status_code'] == 'delivered' else now + refresh_seconds(), job['awb']))
            connection.execute("UPDATE dhl_tracking_runtime SET last_error='',inflight_until=0 WHERE id=1")
    except TrackingError as error:
        delay = 86400 if error.code in {'quota', 'authorization', 'not_found'} else min(8 * 3600, 300 * 2 ** min(job['attempts'], 6))
        with app.db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute("UPDATE dhl_tracking_jobs SET state='error', lease_until=0, error_code=?, next_at=? WHERE awb=?",
                               (error.code, now + delay, job['awb']))
            connection.execute('UPDATE dhl_tracking_runtime SET last_error=?, auth_blocked=?, blocked_until=?,inflight_until=0 WHERE id=1',
                               (error.code, int(error.code == 'authorization'), now + delay if error.code in {'quota', 'network'} else 0))
    return True


def status(connection, now=None):
    now = now or time.time()
    runtime = dict(connection.execute('SELECT * FROM dhl_tracking_runtime WHERE id=1').fetchone())
    try:
        _key()
        configured = True
    except TrackingError:
        configured = False
    day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    calls = runtime['calls'] if runtime['day'] == day else 0
    state = ('disabled' if not enabled() else 'configuration' if not configured else
             'authorization' if runtime['auth_blocked'] else 'quota' if calls >= daily_budget() else
             'waiting' if runtime['blocked_until'] > now else
             'stale' if now - runtime['heartbeat'] > 120 else 'connected')
    return {'enabled': enabled(), 'configured': configured, 'state': state, 'calls_today': calls,
            'daily_budget': daily_budget(), 'heartbeat_at': runtime['heartbeat'] or None,
            'resume_at': runtime['blocked_until'] if runtime['blocked_until'] > now else None,
            'refresh_hours': refresh_seconds() // 3600, 'prefetch_limit': prefetch_limit(),
            'scope': 'Mes actual y llegadas cercanas; guias abiertas ya consultadas',
            'error': MESSAGES.get(state, MESSAGES.get(runtime['last_error'], '')),
            'cached_guides': connection.execute('SELECT COUNT(*) FROM dhl_tracking_cache WHERE expires_at>?', (now,)).fetchone()[0],
            'queued_guides': connection.execute("""SELECT COUNT(*) FROM dhl_tracking_jobs j
                WHERE j.state IN ('queued','running','error') AND EXISTS
                (SELECT 1 FROM reception_shipments s WHERE replace(replace(s.bl_awb,' ',''),'-','')=j.awb
                 AND s.app_status<>'CERRADO')""").fetchone()[0]}


def retry_authorization(connection):
    # Operator action after fixing access; daily/per-guide quotas are never reset.
    connection.execute("UPDATE dhl_tracking_runtime SET auth_blocked=0, blocked_until=0, last_error='' WHERE id=1")
    connection.execute("UPDATE dhl_tracking_jobs SET next_at=? WHERE error_code='authorization'", (time.time(),))


def start_worker(app):
    global _started
    with _guard:
        if _started:
            return
        if not enabled():
            with app.db() as connection:
                if connection.execute('SELECT 1 FROM dhl_tracking_cache LIMIT 1').fetchone() is None:
                    return
        _started = True
    def loop():
        while True:
            try:
                worker_cycle(app)
            except Exception:
                # Responses/transport exceptions may contain credentials. Never log them.
                try:
                    with app.db() as connection:
                        connection.execute("UPDATE dhl_tracking_runtime SET last_error='network' WHERE id=1")
                except Exception:
                    pass
            threading.Event().wait(6 if enabled() else 60)
    threading.Thread(target=loop, name='wms-dhl-tracking', daemon=True).start()
