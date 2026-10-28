"""Scheduled BI stock orchestration and passive administrator diagnostics."""
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from backend.services import powerbi_stock_store as store
from backend.services import powerbi_stock_api as api
from backend.services.daily_operations import normalize_cutoff
from backend.services.powerbi_stock_api import Client, StockError, enabled, load_configuration
from backend.services.powerbi_stock_rows import normalize_rows

POLL_SECONDS=300
_sync_lock=threading.Lock()
_worker_guard=threading.Lock()
_worker_started=False
ERRORS={
 'configuration':('Falta configurar el origen Power BI.','Revisa el archivo privado de mapeo del servidor.'),
 'authorization_required':('El acceso a Power BI necesita autorizacion.','Revisa la cuenta conectada y sus permisos BI con TI; no desconectes Excel o correo.'),
 'busy':('La conexion Microsoft esta ocupada.','Espera a la siguiente revision.'),
 'forbidden':('Power BI denego el acceso al modelo.','TI debe revisar Leer y Compilar y la opcion Execute Queries.'),
 'model_missing':('No se pudo acceder al modelo configurado.','TI debe revisar el modelo y sus permisos.'),
 'network':('No se pudo contactar con Power BI.','Se conserva el ultimo corte; se reintentara automaticamente.'),
 'throttled':('Power BI limito temporalmente las consultas.','Se respeta el plazo de reintento y se conserva el corte anterior.'),
 'partial':('Power BI no devolvio un corte completo y valido.','Revisa los datos y limites; se conserva el corte anterior.'),
 'protocol':('Power BI no devolvio la respuesta esperada.','Se conserva el corte anterior.'),
 'model_changed':('El modelo cambio durante la descarga.','Se reintentara con un corte estable en la siguiente revision.'),
 'refresh_pending':('La ultima actualizacion del modelo no esta completada.','Se conserva el corte anterior hasta una actualizacion correcta.'),
 'invalid_refresh':('No se pudo verificar la fecha de actualizacion del modelo.','Revisa el historial de actualizacion en Power BI.'),
 'newer_cut':('Ya existe un corte de stock mas reciente.','Se conserva ese corte hasta que Power BI publique uno posterior.'),
 'replaced_cut':('Este corte fue sustituido por otro.','Se conserva el corte vigente.'),
 'api_error':('Power BI no pudo atender la consulta.','Se conserva el corte anterior; se reintentara automaticamente.'),
 'service_error':('No se completo la carga de stock Power BI.','Se conserva el corte anterior; revisa el servidor.'),
}


def _stamp():return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _configuration_states():
    try:data=api.private_mapping()
    except StockError:data={}
    return {key:api.identifier_state(data.get(key+'_id') or os.getenv('POWERBI_STOCK_'+key.upper()+'_ID',''))
            for key in ('report','workspace','dataset')}


def status(app=None):
    value={};current={};config=None
    if app is not None:
        with app.db() as connection:
            value=store.state(connection)
            if enabled():current=store.latest(connection)
    state='disabled'
    if enabled():
        try:config=load_configuration();state=value.get('state','pending')
        except StockError:state='configuration_error'
    if state in {'updated','unchanged'} and time.time()-api.utc_time(value['checked_at']).timestamp()>POLL_SECONDS*3:state='stale'
    summary=current.get('summary',{})
    connected=bool(config and summary.get('source_kind')=='powerbi' and summary.get('source_fingerprint')==config['fingerprint'])
    if state in {'updated','unchanged'} and not connected:state='superseded'
    code=value.get('error_code','')
    if state=='configuration_error':code='configuration'
    detail,action=ERRORS.get(code,('',''))
    return {'state':state,'connector_implemented':True,'stock_connected':connected,
        'automatic_enabled':enabled(),'interval_seconds':POLL_SECONDS,
        'configuration':_configuration_states(),'required_warehouse':'01',
        'warehouse_filter_verified':connected,'model_mapping':'verified' if connected else 'unverified',
        'api_access':'verified' if value.get('api_success_at') else 'unverified',
        'refresh_schedule':{'state':'unknown'},'last_refresh_at':value.get('completed_at'),
        'checked_at':value.get('checked_at'),'success_at':value.get('success_at'),
        'updated_at':value.get('updated_at'),'cutoff_at':current.get('cutoff_at') if connected else None,
        'next_check_at':value.get('next_check_at'),'error_code':code,'detail':detail,'action':action,
        'inventory_skus':summary.get('inventory_skus') if connected else None,
        'positive_bins':summary.get('positive_bins') if connected else None}


def _record(connection,app,state,*,marker=None,result=None,code='',started=None,retry=300):
    from backend.services import cloud_sync
    now=_stamp();result=result or {};old=store.state(connection)
    updates={'state':state,'checked_at':now,'error_code':code,
        'next_check_at':(datetime.now(timezone.utc)+timedelta(seconds=retry)).isoformat(timespec='seconds')}
    if marker:updates.update(completed_at=marker['completed_at'],api_success_at=now)
    if state in {'updated','unchanged'}:updates['success_at']=now
    if state=='updated':updates['updated_at']=now
    if 'inventory_skus' in result:updates['inventory_skus']=result['inventory_skus']
    store.update_state(connection,**updates)
    detail=ERRORS.get(code,('Corte Power BI cargado.' if state=='updated' else 'Sin cambios en el modelo Power BI.',''))[0]
    cloud_sync._record(app,'powerbi_stock',state,detail,connection=connection,
        metadata={'filename':store.SOURCE_FILE,'remote_accessed':bool(marker),
            'source_modified_at':marker.get('completed_at') if marker else None,
            'cutoff_at':result.get('cutoff_at'),'import_id':result.get('import_id'),
            'rows_count':result.get('inventory_skus',old.get('inventory_skus'))},
        error_code='bi_'+code if code else '',origin='automatic',actor='system.powerbi-stock',started_at=started)


def sync(app):
    if not enabled():return {'state':'disabled'}
    if not _sync_lock.acquire(blocking=False):return {'state':'busy'}
    marker=None;started=_stamp()
    try:
        with app.db() as connection:previous=store.state(connection)
        if previous.get('error_code')=='throttled' and api.utc_time(previous['next_check_at']).timestamp()>time.time():return {'state':'throttled'}
        config=load_configuration();client=Client(config);marker=client.refresh()
        with app.db() as connection:current=store.latest(connection)
        same=store.same_cut(current,config,marker)
        if current and current['cutoff_at']>normalize_cutoff(marker['started_at']):raise StockError('newer_cut')
        items=None
        if not same:
            rows=client.read_rows(marker)
            try:items=normalize_rows(rows)
            except ValueError:raise StockError('partial') from None
            descriptions={}
            for row in rows:
                key=row['item_code'].strip().upper();description=str(row.get('description') or '').strip()
                if description:
                    descriptions[key]=min(description,descriptions.get(key,description))
            for item in items:item['description']=descriptions.get(item['item_code'].upper(),'')
        with app.db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            if items is None:
                current=store.latest(connection)
                if not store.same_cut(current,config,marker):raise StockError('newer_cut')
                result={'state':'unchanged','import_id':current['id'],'cutoff_at':current['cutoff_at']}
            else:result=store.activate(connection,items,config,marker,'system.powerbi-stock')
            _record(connection,app,result['state'],marker=marker,result=result,started=started)
        return result
    except Exception as failure:
        code=failure.code if isinstance(failure,StockError) and failure.code in ERRORS else 'service_error'
        state='blocked' if code in {'configuration','authorization_required','forbidden','model_missing','newer_cut','replaced_cut'} else 'error'
        retry=failure.retry_after if isinstance(failure,StockError) and code=='throttled' else POLL_SECONDS
        with app.db() as connection:_record(connection,app,state,marker=marker,code=code,started=started,retry=retry)
        return {'state':state,'error_code':code}
    finally:_sync_lock.release()


def _worker_tick(app,schedule,now=None):
    clock=time.monotonic() if now is None else now
    if clock>=schedule.get('next',0):
        schedule['next']=clock+POLL_SECONDS
        sync(app)
    return max(1,schedule['next']-(time.monotonic() if now is None else now))


def start_worker(app):
    global _worker_started
    if not enabled():return
    with _worker_guard:
        if _worker_started:return
        _worker_started=True
    def loop():
        schedule={}
        while True:
            try:delay=_worker_tick(app,schedule)
            except Exception:delay=POLL_SECONDS
            threading.Event().wait(delay)
    threading.Thread(target=loop,name='wms-powerbi-stock',daemon=True).start()
