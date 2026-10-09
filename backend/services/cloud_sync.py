"""Admin cloud controls and per-database periodic imports using existing rules."""
import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from backend.services import cloud_auth, cloud_excel
from backend.services.cloud_import_policy import documentary_only
from backend.services.daily_operations import LIMA, normalize_cutoff

_sync_lock = threading.Lock()
_worker_started = False
_worker_guard = threading.Lock()
SOURCE_LABELS = {'dispatch': 'OV', 'stock': 'Stock / almacen 01',
                 'importation': 'Importaciones', 'accounting': 'Facturas'}
DIAGNOSTICS = {
    'busy': ('Otra operacion esta usando la conexion Microsoft.', 'Espera y vuelve a comprobar; no necesitas desconectar la cuenta.'),
    'configuration': ('Falta configurar la aplicacion o el enlace Excel.', 'Revisa la configuracion con TI.'),
    'authorization_required': ('Microsoft requiere autorizar de nuevo la cuenta.', 'Usa Conectar Microsoft con la cuenta de empresa.'),
    'network': ('No se pudo contactar con Microsoft.', 'Revisa Internet en el servidor y vuelve a comprobar.'),
    'forbidden': ('Microsoft denego el acceso al archivo.', 'TI debe revisar permisos y politicas de acceso al archivo.'),
    'file_missing': ('Microsoft no encontro el Excel configurado.', 'Revisa si se movio, elimino o cambio el enlace compartido.'),
    'throttled': ('Microsoft limito temporalmente las consultas.', 'Espera la siguiente revision; evita forzar varias cargas.'),
    'microsoft_unavailable': ('Microsoft no pudo atender la consulta.', 'Espera la siguiente revision o comprueba mas tarde.'),
    'cloud_error': ('Microsoft no devolvio el archivo esperado.', 'Revisa el enlace y vuelve a comprobar; consulta a TI si persiste.'),
    'file_format': ('El archivo no es un Excel valido, esta vacio o supera 50 MB.', 'Revisa el archivo de origen antes de volver a cargar.'),
    'import_error': ('No se importo el Excel; los avances se conservaron.', 'Revisa columnas, formato y fecha del corte.'),
    'interrupted': ('La revision anterior no termino antes del reinicio.', 'Comprueba de nuevo; no se da esa carga por completada.'),
    'service_error': ('El proceso automatico no completo la revision.', 'Revisa el servidor y vuelve a comprobar.'),
}
HISTORY_LIMIT = 10000
HISTORY_DAYS = 30


def _stamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _timestamp(value):
    if isinstance(value, (int, float)):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=LIMA)).timestamp()
    except (ValueError, TypeError):
        return 0


def init_schema(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS cloud_sync_status (
        source_type TEXT PRIMARY KEY, checked_at TEXT NOT NULL,
        success_at TEXT, state TEXT NOT NULL, detail TEXT NOT NULL)''')
    columns = {row[1] for row in connection.execute('PRAGMA table_info(cloud_sync_status)')}
    for column in ['updated_at', 'filename', 'source_modified_at', 'cutoff_at', 'file_hash',
                   'error_code', 'action', 'remote_access_at']:
        if column not in columns:
            connection.execute(f'ALTER TABLE cloud_sync_status ADD COLUMN {column} TEXT')
    connection.execute('''CREATE TABLE IF NOT EXISTS cloud_sync_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT NOT NULL,
        checked_at TEXT NOT NULL, started_at TEXT NOT NULL, state TEXT NOT NULL,
        detail TEXT NOT NULL, error_code TEXT NOT NULL, action TEXT NOT NULL,
        origin TEXT NOT NULL, actor TEXT NOT NULL, forced INTEGER NOT NULL,
        filename TEXT, source_modified_at TEXT, cutoff_at TEXT, file_hash TEXT,
        import_id INTEGER, rows_count INTEGER, duration_ms INTEGER NOT NULL,
        remote_accessed INTEGER NOT NULL)''')
    connection.execute('CREATE INDEX IF NOT EXISTS idx_cloud_history_source ON cloud_sync_history(source_type,id)')
    connection.execute('CREATE INDEX IF NOT EXISTS idx_cloud_history_state ON cloud_sync_history(state,id)')
    connection.execute('CREATE INDEX IF NOT EXISTS idx_cloud_history_time ON cloud_sync_history(checked_at)')
    connection.execute('''CREATE TABLE IF NOT EXISTS cloud_sync_runtime (
        id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)''')


def _runtime(app, **updates):
    with app.db() as connection:
        row = connection.execute('SELECT value FROM cloud_sync_runtime WHERE id=1').fetchone()
        value = json.loads(row['value']) if row else {}
        if updates:
            value.update(updates)
            connection.execute('INSERT INTO cloud_sync_runtime VALUES(1,?) '
                'ON CONFLICT(id) DO UPDATE SET value=excluded.value', (json.dumps(value),))
    return value


def interval():
    try:
        return max(300, min(86400, int(os.getenv('WMS_CLOUD_INTERVAL_SECONDS', '300'))))
    except ValueError:
        return 300


def enabled():
    return os.getenv('WMS_CLOUD_AUTO_SYNC', '0') == '1'


def _record(app, source_type, state, detail, *, metadata=None, error_code='', origin='manual',
            actor='', forced=False, started_at=None, duration_ms=0):
    metadata = metadata or {}
    checked = _stamp()
    filename = Path(str(metadata.get('filename') or '').replace('\\', '/')).name[:255] or None
    action = DIAGNOSTICS.get(error_code, ('', ''))[1]
    success = checked if state in {'updated', 'unchanged'} else None
    with app.db() as connection:
        if not filename:
            previous = connection.execute('SELECT filename FROM cloud_sync_status WHERE source_type=?', (source_type,)).fetchone()
            filename = previous['filename'] if previous else None
        connection.execute('''INSERT INTO cloud_sync_status
            (source_type,checked_at,success_at,state,detail,updated_at,filename,
             source_modified_at,cutoff_at,file_hash,error_code,action,remote_access_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_type) DO UPDATE SET checked_at=excluded.checked_at,
            success_at=COALESCE(excluded.success_at,cloud_sync_status.success_at),
            state=excluded.state,detail=excluded.detail,
            updated_at=COALESCE(excluded.updated_at,cloud_sync_status.updated_at),
            filename=COALESCE(excluded.filename,cloud_sync_status.filename),
            source_modified_at=COALESCE(excluded.source_modified_at,cloud_sync_status.source_modified_at),
            cutoff_at=COALESCE(excluded.cutoff_at,cloud_sync_status.cutoff_at),
            file_hash=COALESCE(excluded.file_hash,cloud_sync_status.file_hash),
            error_code=excluded.error_code,action=excluded.action,
            remote_access_at=COALESCE(excluded.remote_access_at,cloud_sync_status.remote_access_at)''',
            (source_type, checked, success, state, detail, checked if state == 'updated' else None,
             filename, metadata.get('source_modified_at'), metadata.get('cutoff_at') if success else None,
             metadata.get('file_hash') if success else None, error_code, action, checked if metadata.get('remote_accessed') else None))
        connection.execute('''INSERT INTO cloud_sync_history
            (source_type,checked_at,started_at,state,detail,error_code,action,origin,actor,
             forced,filename,source_modified_at,cutoff_at,file_hash,import_id,rows_count,
             duration_ms,remote_accessed) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (source_type, checked, started_at or checked, state, detail, error_code, action,
             origin, actor, int(forced), filename, metadata.get('source_modified_at'),
             metadata.get('cutoff_at'), metadata.get('file_hash'), metadata.get('import_id'),
             metadata.get('rows_count'), max(0, duration_ms), int(bool(metadata.get('remote_accessed')))))
        oldest = (datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)).isoformat(timespec='seconds')
        connection.execute('DELETE FROM cloud_sync_history WHERE checked_at<?', (oldest,))
        connection.execute('DELETE FROM cloud_sync_history WHERE id <= '
            '(SELECT id FROM cloud_sync_history ORDER BY id DESC LIMIT 1 OFFSET ?)', (HISTORY_LIMIT,))


def status(app):
    auth_error = ''
    try:
        auth = cloud_auth.status()
    except cloud_auth.CloudAuthError as error:
        auth_error = error.code
        auth = {'configured': None, 'authorized': False, 'pending': False}
    configured = {source['source_type'] for source in cloud_excel.configured_sources()}
    with app.db() as connection:
        rows = {row['source_type']: dict(row) for row in connection.execute('SELECT * FROM cloud_sync_status')}
    sources = []
    now = time.time()
    runtime = _runtime(app)
    stale = enabled() and bool(runtime.get('heartbeat_at')) and now - _timestamp(runtime['heartbeat_at']) > max(600, interval() * 2)
    monitor_state = ('disabled' if not enabled() else 'stale' if stale else
        'starting' if not runtime.get('heartbeat_at') else 'running' if runtime.get('running') else
        runtime.get('worker_state', 'waiting'))
    for key, label in SOURCE_LABELS.items():
        manual = key == 'dispatch' and os.getenv('WMS_CLOUD_DISPATCH_MODE', 'cloud') == 'manual'
        row = rows.get(key, {})
        age = now - _timestamp(row.get('checked_at')) if row.get('checked_at') else None
        health = ('manual' if manual else 'not_configured' if key not in configured else
            'checking' if runtime.get('running') and runtime.get('active_source') == key and not stale else
            'authorization_required' if not auth['authorized'] else 'error' if row.get('state') in {'error', 'blocked', 'interrupted'} else
            'stale' if enabled() and age is not None and age > max(1800, interval() * 3) else
            'pending' if not row else 'healthy')
        sources.append({'source_type': key, 'label': label, 'configured': key in configured,
            **rows.get(key, {}), 'mode': 'manual' if manual else 'cloud',
            'health': health,
            'pending': ('Carga manual' if manual else 'Modelo y permisos de Power BI' if key == 'stock'
            and os.getenv('POWERBI_STOCK_REPORT_ID') and key not in configured else
            'Falta enlace Excel' if key not in configured else '')})
    relevant = [row for key, row in rows.items() if key in configured]
    verified_at = max((row.get('remote_access_at') or row.get('success_at') for row in relevant), key=_timestamp, default=None)
    failure = max((row for row in relevant if row.get('state') in {'error', 'blocked'}),
                  key=lambda row: _timestamp(row['checked_at']), default={})
    auth_failure_at = max((_timestamp(row.get('checked_at')) for row in relevant
        if row.get('error_code') == 'authorization_required' and row.get('state') in {'error', 'blocked'}), default=0)
    auth_failed = bool(auth_failure_at and auth_failure_at >= max(_timestamp(verified_at), _timestamp(auth.get('authorization_at'))))
    connection_state = ('unavailable' if auth_error else 'not_configured' if not auth['configured'] else
        'pending' if auth['pending'] and not auth['authorized'] else 'disconnected' if not auth['authorized'] else
        'authorization_required' if auth_failed else
        'unavailable' if failure.get('error_code') in {'network', 'microsoft_unavailable'} and _timestamp(failure.get('checked_at')) > _timestamp(verified_at) else
        'verified' if verified_at and _timestamp(verified_at) >= _timestamp(auth.get('authorization_at'))
        and now - _timestamp(verified_at) <= max(1800, interval() * 3) else 'unverified')
    return {**auth, 'automatic_enabled': enabled(), 'interval_seconds': interval(), 'sources': sources,
        'connection': {'state': connection_state, 'verified_at': verified_at,
            'action': DIAGNOSTICS.get(auth_error or ('authorization_required' if auth_failed else ''), ('', ''))[1]},
        'monitor': {**runtime, 'state': monitor_state},
        'history_retention': {'days': HISTORY_DAYS, 'max_records': HISTORY_LIMIT}}


def history(app, query):
    values = parse_qs(query, keep_blank_values=True)
    if set(values) - {'source_type', 'state', 'before', 'limit'} or any(len(value) != 1 for value in values.values()):
        raise ValueError('Filtros de historial no validos.')
    source = values.get('source_type', [''])[0]
    state = values.get('state', [''])[0]
    if source and source not in SOURCE_LABELS or state and state not in {'updated', 'unchanged', 'error', 'blocked', 'interrupted'}:
        raise ValueError('Fuente o resultado no valido.')
    try:
        limit = int(values.get('limit', ['25'])[0])
        before = int(values.get('before', ['0'])[0])
        if not 1 <= limit <= 100 or not 0 <= before < 2**63:
            raise ValueError()
    except ValueError as error:
        raise ValueError('Pagina del historial no valida.') from error
    conditions, parameters = [], []
    for name, value in [('source_type', source), ('state', state)]:
        if value:
            conditions.append(name + '=?'); parameters.append(value)
    if before:
        conditions.append('id<?'); parameters.append(before)
    where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    with app.db() as connection:
        rows = [dict(row) for row in connection.execute('SELECT * FROM cloud_sync_history' + where +
            ' ORDER BY id DESC LIMIT ?', (*parameters, limit + 1))]
    return {'items': rows[:limit], 'next_before': rows[limit - 1]['id'] if len(rows) > limit else None,
            'retention_days': HISTORY_DAYS, 'max_records': HISTORY_LIMIT}


def sync(app, username, force=False, cutoff_at=None, reconcile=False, origin='manual'):
    if not _sync_lock.acquire(blocking=False):
        return {'error': 'Ya hay una sincronizacion en curso.'}, 409
    try:
        _runtime(app, running=True, cycle_started_at=_stamp(), active_source=None, origin=origin)
        sources = cloud_excel.configured_sources()
        if not sources:
            return {'error': 'No hay fuentes Excel configuradas.'}, 503
        results, failures = [], []
        for configured in sources:
            key = configured['source_type']
            started_at, started = _stamp(), time.monotonic()
            metadata = {}
            progress = {'active_source': key}
            if origin == 'automatic':
                progress['heartbeat_at'] = _stamp()
            _runtime(app, **progress)
            try:
                source = cloud_excel.download_cloud_excels(force=force, sources=[configured])[0]
                digest = hashlib.sha256(source['content']).hexdigest()
                metadata.update(filename=source['filename'], source_modified_at=source.get('modified_at'),
                    file_hash=digest, remote_accessed=True)
                with app.db() as connection:
                    latest = connection.execute('''SELECT id,file_hash,cutoff_at FROM data_imports
                        WHERE source_type=? ORDER BY cutoff_at DESC,id DESC LIMIT 1''', (key,)).fetchone()
                if not force and latest and latest['file_hash'] == digest:
                    metadata.update(cutoff_at=latest['cutoff_at'], import_id=latest['id'])
                    _record(app, key, 'unchanged', 'Sin cambios en el archivo.', metadata=metadata,
                        origin=origin, actor=username, forced=force, started_at=started_at,
                        duration_ms=int((time.monotonic() - started) * 1000))
                    results.append({'source_type': key, 'state': 'unchanged', 'filename': source['filename']})
                    continue
                # A polling clock is not an Excel cutoff. Use the source modification time.
                cutoff = cutoff_at or source.get('modified_at')
                if not cutoff:
                    raise ValueError('Microsoft no informo la fecha del archivo; carga un corte manual.')
                cutoff = normalize_cutoff(str(cutoff).replace('Z', '+00:00'))
                metadata['cutoff_at'] = cutoff
                context = documentary_only.set(True)
                try:
                    result = app.import_daily_excel(source['content'], source['filename'], key,
                        cutoff, username, 'ADMINISTRADOR', reconcile_delivered=reconcile, force=force)
                finally:
                    documentary_only.reset(context)
                with app.db() as connection:
                    stored = connection.execute('SELECT id FROM data_imports WHERE source_type=? '
                        'AND file_hash=? AND cutoff_at=? ORDER BY id DESC LIMIT 1', (key, digest, cutoff)).fetchone()
                metadata['import_id'] = stored['id'] if stored else None
                count = result.get('rows')
                metadata['rows_count'] = count if type(count) is int and count >= 0 else None
                state = 'unchanged' if result.get('duplicate') else 'updated'
                _record(app, key, state, 'El corte ya estaba cargado.' if state == 'unchanged' else
                    'Archivo validado e importado.', metadata=metadata, origin=origin, actor=username,
                    forced=force, started_at=started_at, duration_ms=int((time.monotonic() - started) * 1000))
                results.append({'source_type': key, 'state': state, 'result': result,
                    'filename': source['filename']})
            except (cloud_excel.CloudExcelError, cloud_auth.CloudAuthError) as error:
                code = error.code if error.code in DIAGNOSTICS else 'cloud_error'
                detail, action = DIAGNOSTICS[code]
                _record(app, key, 'error', detail, metadata=metadata, error_code=code, origin=origin,
                    actor=username, forced=force, started_at=started_at,
                    duration_ms=int((time.monotonic() - started) * 1000))
                failures.append({'source_type': key, 'error': detail, 'error_code': code, 'action': action})
            except Exception:
                # Parser errors may contain private cells: keep those out of status/logs.
                code = 'import_error' if metadata.get('remote_accessed') else 'cloud_error'
                detail, action = DIAGNOSTICS[code]
                _record(app, key, 'error', detail, metadata=metadata, error_code=code, origin=origin,
                    actor=username, forced=force, started_at=started_at,
                    duration_ms=int((time.monotonic() - started) * 1000))
                failures.append({'source_type': key, 'error': detail, 'error_code': code, 'action': action})
        payload = {'sources': results, 'failures': failures, 'forced': force, 'configured': len(sources)}
        if failures:
            payload['error'] = 'No se completaron todas las fuentes. Revisa el estado de cada archivo.'
        return payload, 502 if failures else 200
    finally:
        try:
            _runtime(app, running=False, active_source=None, cycle_finished_at=_stamp())
        finally:
            _sync_lock.release()


def _worker_cycle(app):
    _runtime(app, heartbeat_at=_stamp(), worker_state='running', next_check_at=None,
        worker_error='', worker_action='')
    try:
        auth = cloud_auth.status()
        if auth['authorized']:
            payload, code = sync(app, 'system.cloud-sync', origin='automatic')
            _runtime(app, worker_state='waiting' if code == 200 else 'error',
                worker_error=payload.get('error', ''), worker_action='Revisa el estado de cada fuente.' if code != 200 else '')
        else:
            error_code = 'authorization_required' if auth.get('configured') else 'configuration'
            detail, action = DIAGNOSTICS[error_code]
            for source in cloud_excel.configured_sources():
                _record(app, source['source_type'], 'blocked', detail, error_code=error_code,
                    origin='automatic', actor='system.cloud-sync')
            _runtime(app, worker_state='blocked', worker_error=detail, worker_action=action)
    except cloud_auth.CloudAuthError as error:
        code = error.code if error.code in DIAGNOSTICS else 'authorization_required'
        detail, action = DIAGNOSTICS[code]
        state = 'blocked' if code in {'authorization_required', 'configuration'} else 'error'
        for source in cloud_excel.configured_sources():
            _record(app, source['source_type'], state, detail, error_code=code,
                origin='automatic', actor='system.cloud-sync')
        _runtime(app, worker_state=state, worker_error=detail, worker_action=action)
    except Exception:
        detail, action = DIAGNOSTICS['service_error']
        _runtime(app, worker_state='error', worker_error=detail, worker_action=action)
    finally:
        _runtime(app, heartbeat_at=_stamp(), next_check_at=(datetime.now(timezone.utc) +
            timedelta(seconds=interval())).isoformat(timespec='seconds'))


def _recover_runtime(app):
    if not _sync_lock.acquire(blocking=False):
        return
    try:
        previous = _runtime(app)
        if previous.get('running'):
            source = previous.get('active_source')
            if source in SOURCE_LABELS:
                _record(app, source, 'interrupted', DIAGNOSTICS['interrupted'][0],
                    error_code='interrupted', origin=previous.get('origin', 'automatic'),
                    actor='system.restart', started_at=previous.get('cycle_started_at'))
            _runtime(app, running=False, active_source=None, worker_state='starting')
    finally:
        _sync_lock.release()


def start_worker(app):
    global _worker_started
    with _worker_guard:
        if _worker_started:
            return
        _recover_runtime(app)
        if not enabled():
            return
        _worker_started = True
    def loop():
        while True:
            try:
                _worker_cycle(app)
            except Exception:
                # No raw OAuth responses or workbook values in process logs.
                pass
            threading.Event().wait(interval())
    threading.Thread(target=loop, name='wms-cloud-sync', daemon=True).start()


def handle(request, app, user):
    if user['role'] != 'ADMINISTRADOR':
        return {'error': 'Solo el administrador puede gestionar Microsoft y los cortes.'}, 403
    path = urlparse(request.path).path
    if path == '/api/cloud-connection/status':
        if request.command not in {'GET', 'HEAD'}:
            return {'error': 'Usa GET para consultar el estado.'}, 405
        return status(app), 200
    if path == '/api/cloud-connection/history':
        if request.command not in {'GET', 'HEAD'}:
            return {'error': 'Usa GET para consultar el historial.'}, 405
        return history(app, urlparse(request.path).query), 200
    if request.command != 'POST':
        return {'error': 'Usa POST para esta solicitud.'}, 405
    if request.headers.get('X-WMS-Request') != '1' or request.headers.get('Sec-Fetch-Site') == 'cross-site':
        return {'error': 'Actualiza la pagina antes de enviar cambios.'}, 403
    if path == '/api/daily-cloud-sync':
        return sync(app, user['username'], force=parse_qs(urlparse(request.path).query).get('force', ['0'])[0] == '1',
            cutoff_at=request.headers.get('X-Cutoff-At'),
            reconcile=request.headers.get('X-Reconcile-Delivered') == '1')
    if int(request.headers.get('Content-Length', '0')) > 4096:
        raise ValueError('Solicitud demasiado grande.')
    data = request.body()
    owner = cloud_auth.owner_key(request.headers)
    if path == '/api/cloud-connection/configure':
        result = cloud_auth.configure(data.get('client_id'))
    elif path == '/api/cloud-connection/start':
        result = cloud_auth.begin(owner)
    elif path == '/api/cloud-connection/poll':
        result = cloud_auth.poll(owner, data.get('flow_id'))
    elif path == '/api/cloud-connection/cancel':
        result = cloud_auth.cancel(owner, data.get('flow_id'))
    elif path == '/api/cloud-connection/disconnect':
        result = cloud_auth.disconnect()
    else:
        return {'error': 'Ruta no encontrada.'}, 404
    with app.db() as connection:
        if not path.endswith('/poll'):
            app.identity.audit(connection, user['username'], user['username'],
                'MICROSOFT ' + path.rsplit('/', 1)[-1].upper(), 'Conexion de cortes; sin tokens en auditoria')
    return result, 200
