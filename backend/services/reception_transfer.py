"""Per-attention transfer requests. A guest confirms SAP work, never executes it."""
import hashlib
import html
import json
import logging
import re
import secrets
import threading
import time
from urllib.parse import urlsplit

import requests

STAGE = 'SOLICITUD TRANSFERENCIA'
TTL = 24 * 60 * 60
PUBLIC_PATHS = {'/transfer-confirmation', '/api/transfer-confirmation/inspect',
                '/api/transfer-confirmation/confirm'}
_worker_started = False


def init_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS reception_transfer_settings (
        id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 0,
        sender TEXT NOT NULL DEFAULT '', recipient TEXT NOT NULL DEFAULT '',
        public_origin TEXT NOT NULL DEFAULT '')''')
    db.execute('INSERT OR IGNORE INTO reception_transfer_settings(id) VALUES(1)')
    db.execute('''CREATE TABLE IF NOT EXISTS reception_transfer_requests (
        id INTEGER PRIMARY KEY, shipment_id INTEGER NOT NULL,
        attention_id INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL,
        token_hash TEXT UNIQUE, expires_at REAL NOT NULL DEFAULT 0,
        created_at REAL NOT NULL, attempted_at REAL NOT NULL DEFAULT 0,
        next_attempt REAL NOT NULL DEFAULT 0, confirmed_at REAL NOT NULL DEFAULT 0,
        recipient TEXT NOT NULL DEFAULT '', error_code TEXT NOT NULL DEFAULT '')''')
    db.execute('''CREATE INDEX IF NOT EXISTS reception_transfer_scope
        ON reception_transfer_requests(shipment_id,attention_id,id)''')
    db.execute('''CREATE TABLE IF NOT EXISTS reception_transfer_limits (
        remote_hash TEXT PRIMARY KEY, window_at REAL NOT NULL, attempts INTEGER NOT NULL)''')


def settings(db):
    return dict(db.execute('SELECT * FROM reception_transfer_settings WHERE id=1').fetchone())


def save_settings(db, data):
    if not isinstance(data, dict):
        raise ValueError('Configuración no válida')
    if type(data.get('enabled')) is not bool:
        raise ValueError('Indica si el aviso está activo')
    values = {key: str(data.get(key) or '').strip() for key in ('sender', 'recipient', 'public_origin')}
    for key in ('sender', 'recipient'):
        if values[key] and not re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+', values[key]):
            raise ValueError('Usa una sola dirección de correo en cada campo')
        if len(values[key]) > 254:
            raise ValueError('Correo demasiado largo')
    origin = values['public_origin'].rstrip('/')
    parsed = urlsplit(origin)
    if origin and (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                   or parsed.password or parsed.port not in (None, 443) or parsed.path
                   or parsed.query or parsed.fragment or len(origin) > 253
                   or not re.fullmatch(r'[A-Za-z0-9.-]+', parsed.hostname)):
        raise ValueError('Usa el origen HTTPS público, sin ruta, credenciales ni parámetros')
    if data['enabled'] and not all([values['sender'], values['recipient'], origin]):
        raise ValueError('Completa remitente, destinatario y origen público antes de activar')
    db.execute('''UPDATE reception_transfer_settings SET enabled=?,sender=?,recipient=?,public_origin=? WHERE id=1''',
               (int(data['enabled']), values['sender'], values['recipient'], origin))
    return settings(db)


def revoke(db, shipment_id, attention_id):
    db.execute('''UPDATE reception_transfer_requests SET status='REVOKED', token_hash=NULL
        WHERE shipment_id=? AND attention_id=? AND status NOT IN ('REVOKED','CONFIRMED')''',
               (shipment_id, attention_id or 0))


def enqueue(db, shipment_id, attention_id):
    revoke(db, shipment_id, attention_id)
    db.execute('''INSERT INTO reception_transfer_requests(shipment_id,attention_id,status,created_at)
        VALUES(?,?,'PENDING',?)''', (shipment_id, attention_id or 0, time.time()))


def request_state(db, shipment_id, attention_id):
    row = db.execute('''SELECT id,status,expires_at,confirmed_at,error_code FROM reception_transfer_requests
        WHERE shipment_id=? AND attention_id=? ORDER BY id DESC LIMIT 1''',
                     (shipment_id, attention_id or 0)).fetchone()
    if not row:
        return None
    state = dict(row)
    if state['status'] == 'ACCEPTED' and state['expires_at'] <= time.time():
        state['status'] = 'EXPIRED'
    if state['status'] in ('PENDING', 'BLOCKED') and not settings(db)['enabled']:
        state['status'] = 'DISABLED'
    return state


def _scope(db, row):
    shipment = db.execute('SELECT * FROM reception_shipments WHERE id=?', (row['shipment_id'],)).fetchone()
    attention = db.execute('SELECT * FROM reception_attentions WHERE id=? AND shipment_id=?',
                           (row['attention_id'], row['shipment_id'])).fetchone() if row['attention_id'] else None
    if not shipment or (row['attention_id'] and not attention):
        raise ValueError('Enlace no disponible o vencido. Solicita uno nuevo.')
    current = attention or shipment
    if current['app_status'] != STAGE or str(current['condition_status'] or '').startswith('ANULADA'):
        raise ValueError('Enlace no disponible o vencido. Solicita uno nuevo.')
    return shipment, attention, current


def _token_row(db, token, now):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise ValueError('Enlace no disponible o vencido. Solicita uno nuevo.')
    digest = hashlib.sha256(token.encode('ascii')).hexdigest()
    row = db.execute('SELECT * FROM reception_transfer_requests WHERE token_hash=?', (digest,)).fetchone()
    if not row or row['status'] not in ('SENDING', 'ACCEPTED', 'REVIEW', 'CONFIRMED') or row['expires_at'] <= now:
        raise ValueError('Enlace no disponible o vencido. Solicita uno nuevo.')
    return row


def inspect_token(db, token, now=None):
    row = _token_row(db, token, time.time() if now is None else now)
    # An already consumed token reveals no shipment details and cannot mutate.
    if row['status'] == 'CONFIRMED':
        return {'confirmed': True}
    shipment, attention, current = _scope(db, row)
    if current['transfer_assistant_checked']:
        return {'confirmed': True}
    return {'confirmed': False, 'bl_awb': shipment['bl_awb'],
            'em_number': shipment['em_number'] or '',
            'attention': attention['sequence_no'] if attention else 1,
            'expires_at': row['expires_at']}


def _mark_done(db, shipment_id, attention, actor, reason):
    from backend.services.reception import _write_history, reception_now, _active_reception_attention
    if attention:
        db.execute('UPDATE reception_attentions SET transfer_assistant_checked=1,updated_at=? WHERE id=?',
                   (reception_now(), attention['id']))
    primary = _active_reception_attention(db, shipment_id)
    if not attention or (primary and primary['id'] == attention['id']):
        db.execute('UPDATE reception_shipments SET transfer_assistant_checked=1,updated_at=? WHERE id=?',
                   (reception_now(), shipment_id))
    _write_history(db, shipment_id, 'TRANSFERENCIA', 'transferencia_sap_realizada', 0, 1, actor, reason)


def confirm_token(db, token, checked, now=None):
    if checked is not True:
        raise ValueError('Confirma que ya realizaste la transferencia IMP a 01 en SAP')
    row = _token_row(db, token, time.time() if now is None else now)
    if row['status'] == 'CONFIRMED':
        return {'confirmed': True}
    _, attention, current = _scope(db, row)
    if not current['transfer_assistant_checked']:
        # The bearer link is not proof of Microsoft identity; audit its authority honestly.
        _mark_done(db, row['shipment_id'], attention, 'enlace.transferencia',
                   f"Confirmación SAP mediante enlace enviado al destinatario configurado; solicitud {row['id']}; atención {row['attention_id']}")
    db.execute("UPDATE reception_transfer_requests SET status='CONFIRMED',confirmed_at=? WHERE id=?",
               (time.time() if now is None else now, row['id']))
    return {'confirmed': True}


def rate_allow(db, remote, now=None):
    now = time.time() if now is None else now
    key = hashlib.sha256(str(remote).encode()).hexdigest()
    db.execute('DELETE FROM reception_transfer_limits WHERE window_at<?', (now - 900,))
    db.execute('''INSERT INTO reception_transfer_limits VALUES(?,?,1)
        ON CONFLICT(remote_hash) DO UPDATE SET attempts=attempts+1''', (key, now))
    return db.execute('SELECT attempts FROM reception_transfer_limits WHERE remote_hash=?', (key,)).fetchone()[0] <= 60


def mail_payload(config, shipment, attention, token):
    link = config['public_origin'] + '/transfer-confirmation#token=' + token
    bl = str(shipment['bl_awb'])
    sequence = attention['sequence_no'] if attention else 1
    text = (f"Estimado: los repuestos de la BL/AWB {html.escape(bl)} (atención {sequence}) "
            f"ya están ubicados. EM: {html.escape(str(shipment['em_number'] or 'pendiente'))}. "
            "Por favor realiza la transferencia IMP → 01 en SAP y confírmala aquí. "
            f'<p><a href="{html.escape(link, quote=True)}">Confirmar transferencia realizada</a></p>'
            '<p>Enlace individual, válido por 24 horas. No lo reenvíes.</p>')
    return {'message': {'subject': ('Transferencia IMP a 01 | BL/AWB ' + bl.replace('\r', '').replace('\n', ''))[:200],
            'body': {'contentType': 'HTML', 'content': text},
            'toRecipients': [{'emailAddress': {'address': config['recipient']}}]}, 'saveToSentItems': True}


def worker_cycle(app, now=None):
    now = time.time() if now is None else now
    with app.db() as db:
        db.execute('BEGIN IMMEDIATE')
        # A crash/network ambiguity is never retried automatically: it could duplicate an accepted mail.
        db.execute("UPDATE reception_transfer_requests SET status='REVIEW',error_code='ENVIO_INCIERTO' WHERE status='SENDING' AND attempted_at<?", (now - 300,))
        config = settings(db)
        if not config['enabled']:
            return
        row = db.execute("SELECT * FROM reception_transfer_requests WHERE status IN ('PENDING','BLOCKED') AND next_attempt<=? ORDER BY id LIMIT 1", (now,)).fetchone()
        if not row:
            return
        try:
            shipment, attention, current = _scope(db, row)
        except ValueError:
            revoke(db, row['shipment_id'], row['attention_id'])
            return
        if current['transfer_assistant_checked']:
            revoke(db, row['shipment_id'], row['attention_id'])
            return
    try:
        from backend.services import cloud_auth
        token = cloud_auth.access_token(cloud_auth.MAIL_SCOPES, expected_username=config['sender'])
    except Exception:
        with app.db() as db:
            db.execute("UPDATE reception_transfer_requests SET status='BLOCKED',error_code='AUTORIZAR_MAIL_SEND',next_attempt=? WHERE id=? AND status IN ('PENDING','BLOCKED')", (now + 300, row['id']))
        return
    raw = secrets.token_urlsafe(32)
    with app.db() as db:
        db.execute('BEGIN IMMEDIATE')
        # Settings or stage may have changed during the silent Microsoft authorization.
        if settings(db) != config:
            return
        fresh = db.execute('SELECT * FROM reception_transfer_requests WHERE id=?', (row['id'],)).fetchone()
        if fresh['status'] not in ('PENDING', 'BLOCKED'):
            return
        try:
            shipment, attention, current = _scope(db, fresh)
        except ValueError:
            revoke(db, row['shipment_id'], row['attention_id'])
            return
        if current['transfer_assistant_checked']:
            revoke(db, row['shipment_id'], row['attention_id'])
            return
        db.execute("UPDATE reception_transfer_requests SET status='SENDING',attempted_at=?,token_hash=?,expires_at=?,recipient=?,error_code='' WHERE id=?",
                   (now, hashlib.sha256(raw.encode()).hexdigest(), now + TTL, config['recipient'], row['id']))
        payload = mail_payload(config, shipment, attention, raw)
    status, error = 'REVIEW', 'ENVIO_INCIERTO'
    try:
        response = requests.post('https://graph.microsoft.com/v1.0/me/sendMail',
            headers={'Authorization': 'Bearer ' + token}, json=payload, timeout=30, allow_redirects=False)
        if response.status_code == 202:
            status, error = 'ACCEPTED', ''
        else:
            status, error = 'ERROR', 'MICROSOFT_' + str(response.status_code)
    except requests.RequestException:
        pass
    with app.db() as db:
        db.execute("UPDATE reception_transfer_requests SET status=?,error_code=? WHERE id=? AND status='SENDING'",
                   (status, error, row['id']))


def start_worker(app):
    global _worker_started
    if _worker_started:
        return
    _worker_started = True
    def run():
        while True:
            try:
                worker_cycle(app)
            except Exception:
                logging.warning('No se pudo procesar el aviso de transferencia')
            time.sleep(60)
    threading.Thread(target=run, daemon=True, name='wms-transfer-mail').start()


def handle_public(app, request, path):
    """Exact guest routes, before the normal login gate; no WMS session is created."""
    if path not in PUBLIC_PATHS:
        return False
    request.send_header('Referrer-Policy', 'no-referrer')
    request.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'none'")
    if path == '/transfer-confirmation' and request.command in ('GET', 'HEAD'):
        request.send_response(200)
        request.send_header('Content-Type', 'text/html; charset=utf-8')
        request.end_headers()
        request.wfile.write((app.ROOT / 'frontend/templates/transfer-confirmation.html').read_bytes())
        return True
    if path == '/transfer-confirmation' or request.command != 'POST':
        request.send_json({'error': 'Método no permitido'}, 405)
        return True
    if request.headers.get('X-WMS-Request') != '1' or request.headers.get('Sec-Fetch-Site') == 'cross-site':
        request.send_json({'error': 'Solicitud no permitida'}, 403)
        return True
    try:
        size = int(request.headers.get('Content-Length') or 0)
        if size <= 0 or size > 4096 or request.headers.get_content_type() != 'application/json':
            request.send_json({'error': 'Solicitud no válida'}, 400)
            return True
        data = request.body()
        if not isinstance(data, dict):
            raise ValueError('Solicitud no válida')
        with app.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not rate_allow(db, request.client_address[0]):
                payload, status = {'error': 'Demasiados intentos. Espera 15 minutos.'}, 429
            else:
                try:
                    payload = (inspect_token(db, data.get('token')) if path.endswith('/inspect')
                               else confirm_token(db, data.get('token'), data.get('checked')))
                    status = 200
                except ValueError as error:
                    payload, status = {'error': str(error)}, 410
        request.send_json(payload, status)
    except (ValueError, TypeError, json.JSONDecodeError):
        request.send_json({'error': 'Solicitud no válida'}, 400)
    return True
