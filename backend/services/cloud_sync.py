"""Admin cloud controls and per-database periodic imports using existing rules."""
import hashlib
import json
import os
import threading
from urllib.parse import parse_qs, urlparse

from backend.services import cloud_auth, cloud_excel
from backend.services.cloud_import_policy import documentary_only
from backend.services.daily_operations import local_now, normalize_cutoff

_sync_lock = threading.Lock()
_worker_started = False
_worker_guard = threading.Lock()


def init_schema(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS cloud_sync_status (
        source_type TEXT PRIMARY KEY, checked_at TEXT NOT NULL,
        success_at TEXT, state TEXT NOT NULL, detail TEXT NOT NULL)''')


def interval():
    try:
        return max(300, min(86400, int(os.getenv('WMS_CLOUD_INTERVAL_SECONDS', '300'))))
    except ValueError:
        return 300


def enabled():
    return os.getenv('WMS_CLOUD_AUTO_SYNC', '0') == '1'


def _record(app, source_type, state, detail):
    with app.db() as connection:
        connection.execute('''INSERT INTO cloud_sync_status
            (source_type,checked_at,success_at,state,detail) VALUES(?,?,?,?,?)
            ON CONFLICT(source_type) DO UPDATE SET checked_at=excluded.checked_at,
            success_at=COALESCE(excluded.success_at,cloud_sync_status.success_at),
            state=excluded.state,detail=excluded.detail''',
            (source_type, local_now(), local_now() if state in {'updated', 'unchanged'} else None,
             state, detail))


def status(app):
    auth = cloud_auth.status()
    configured = {source['source_type'] for source in cloud_excel.configured_sources()}
    with app.db() as connection:
        rows = {row['source_type']: dict(row) for row in connection.execute('SELECT * FROM cloud_sync_status')}
    sources = []
    for key, label in [('dispatch', 'OV'), ('stock', 'Stock / almacen 01'),
                       ('importation', 'Importaciones'), ('accounting', 'Facturas')]:
        manual = key == 'dispatch' and os.getenv('WMS_CLOUD_DISPATCH_MODE', 'cloud') == 'manual'
        sources.append({'source_type': key, 'label': label, 'configured': key in configured,
            **rows.get(key, {}), 'mode': 'manual' if manual else 'cloud',
            'pending': ('Carga manual' if manual else 'Modelo y permisos de Power BI' if key == 'stock'
            and os.getenv('POWERBI_STOCK_REPORT_ID') and key not in configured else
            'Falta enlace Excel' if key not in configured else '')})
    return {**auth, 'automatic_enabled': enabled(), 'interval_seconds': interval(), 'sources': sources}


def sync(app, username, force=False, cutoff_at=None, reconcile=False):
    if not _sync_lock.acquire(blocking=False):
        return {'error': 'Ya hay una sincronizacion en curso.'}, 409
    try:
        sources = cloud_excel.configured_sources()
        if not sources:
            return {'error': 'No hay fuentes Excel configuradas.'}, 503
        results, failures = [], []
        for configured in sources:
            key = configured['source_type']
            try:
                source = cloud_excel.download_cloud_excels(force=force, sources=[configured])[0]
                digest = hashlib.sha256(source['content']).hexdigest()
                with app.db() as connection:
                    latest = connection.execute('''SELECT file_hash,cutoff_at FROM data_imports
                        WHERE source_type=? ORDER BY cutoff_at DESC,id DESC LIMIT 1''', (key,)).fetchone()
                if not force and latest and latest['file_hash'] == digest:
                    _record(app, key, 'unchanged', 'Sin cambios en el archivo.')
                    results.append({'source_type': key, 'state': 'unchanged'})
                    continue
                # A polling clock is not an Excel cutoff. Use the source modification time.
                cutoff = cutoff_at or source.get('modified_at')
                if not cutoff:
                    raise ValueError('Microsoft no informo la fecha del archivo; carga un corte manual.')
                cutoff = normalize_cutoff(str(cutoff).replace('Z', '+00:00'))
                context = documentary_only.set(True)
                try:
                    result = app.import_daily_excel(source['content'], source['filename'], key,
                        cutoff, username, 'ADMINISTRADOR', reconcile_delivered=reconcile, force=force)
                finally:
                    documentary_only.reset(context)
                _record(app, key, 'updated', 'Archivo validado e importado.')
                results.append({'source_type': key, 'state': 'updated', 'result': result,
                    'filename': source['filename']})
            except (cloud_excel.CloudExcelError, cloud_auth.CloudAuthError) as error:
                detail = str(error)
                _record(app, key, 'error', detail)
                failures.append({'source_type': key, 'error': detail})
            except Exception:
                # Parser errors may contain private cells: keep those out of status/logs.
                detail = 'No se importo: revisa formato y fecha del corte. Los avances se conservaron.'
                _record(app, key, 'error', detail)
                failures.append({'source_type': key, 'error': detail})
        payload = {'sources': results, 'failures': failures, 'forced': force, 'configured': len(sources)}
        if failures:
            payload['error'] = 'No se completaron todas las fuentes. Revisa el estado de cada archivo.'
        return payload, 502 if failures else 200
    finally:
        _sync_lock.release()


def start_worker(app):
    global _worker_started
    if not enabled():
        return
    with _worker_guard:
        if _worker_started:
            return
        _worker_started = True
    def loop():
        while True:
            try:
                if cloud_auth.status()['authorized']:
                    sync(app, 'system.cloud-sync')
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
