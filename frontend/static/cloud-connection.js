(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const labels = {importation:'Importaciones',accounting:'Facturas',stock:'Stock Excel',dispatch:'OV',powerbi_stock:'Stock Power BI'};
  const states = {updated:'Actualizado',unchanged:'Sin cambios',error:'Error',blocked:'Sin autorizacion',interrupted:'Interrumpido'};
  let flow = null, authTimer = null, refreshTimer = null, busy = false, disposed = false;
  let currentStatus = null, cursor = 0, nextCursor = null, cursors = [], historySequence = 0, historyBusy = false;
  let statusSequence = 0, statusAvailable = false;
  const dateFormat = new Intl.DateTimeFormat('es-PE',{timeZone:'America/Lima',dateStyle:'short',timeStyle:'medium',hour12:false});

  async function request(path, data) {
    const response = await fetch(path, data === undefined ? {cache:'no-store'} : {
      method:'POST',headers:{'Content-Type':'application/json','X-WMS-Request':'1'},body:JSON.stringify(data)});
    if(response.status===401)throw new Error('Tu sesion vencio. Vuelve a ingresar.');
    if(response.status===403)throw new Error('No tienes permiso para esta operacion.');
    if(!(response.headers.get('Content-Type')||'').includes('application/json'))
      throw new Error('El servidor no respondio correctamente. Revisa la conexion.');
    let payload;
    try { payload = await response.json(); } catch { throw new Error('El servidor no respondio correctamente. Revisa la conexion.'); }
    if(!payload||typeof payload!=='object'||Array.isArray(payload))throw new Error('Respuesta de conexion no valida.');
    if (!response.ok) throw new Error(payload.error || 'No se pudo completar la solicitud.');
    return payload;
  }
  function node(tag, text, className='') {
    const value=document.createElement(tag); value.textContent=text; value.className=className; return value;
  }
  function date(value) {
    if (!value) return 'Sin registro';
    const raw=typeof value==='number' ? value*1000 : /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : value+'-05:00';
    const parsed=new Date(raw); return Number.isNaN(parsed.getTime()) ? 'Sin registro' : dateFormat.format(parsed);
  }
  function fields(values) {
    const list=document.createElement('dl');
    values.forEach(([label,value])=>{list.append(node('dt',label),node('dd',value));});
    return list;
  }
  function badge(state, label) { return node('span',label||states[state]||'Pendiente','badge '+state); }
  function message(text, error=false) {el('message').textContent=text;el('message').classList.toggle('error',error);}
  function stop() {clearTimeout(authTimer);authTimer=null;flow=null;el('authorization').hidden=true;el('deviceCode').value='';}
  function controls() {
    const status=currentStatus;
    el('connect').disabled=busy||!statusAvailable||!status?.configured||status.pending;
    el('disconnect').hidden=!status?.authorized&&!status?.pending;
    el('disconnect').disabled=busy||!statusAvailable;
    el('sync').disabled=busy||!statusAvailable||!status?.authorized||status?.connection?.state==='authorization_required'||status?.monitor?.running;
    el('refresh').disabled=busy;
    el('cancel').disabled=busy;
    el('configureForm').querySelector('button').disabled=busy||!statusAvailable;
    el('newer').disabled=busy||historyBusy||!cursors.length;
    el('older').disabled=busy||historyBusy||!nextCursor;
    el('historySource').disabled=busy;el('historyState').disabled=busy;
  }
  function render(status) {
    currentStatus=status;statusAvailable=true;
    const connection=status.connection||{};
    const text={verified:'Acceso a Excel en Microsoft Graph comprobado',unverified:'Cuenta guardada; falta una comprobacion reciente de Excel',
      authorization_required:'Microsoft solicita una nueva autorizacion',disconnected:'Cuenta Microsoft desconectada',
      not_configured:'Pendiente del Client ID de TI',pending:'Autorizacion pendiente',unavailable:'No se pudo comprobar el acceso a Microsoft'};
    el('connectionStatus').textContent=text[connection.state]||'Consultando conexion';
    el('connectionStatus').className=['authorization_required','unavailable','disconnected'].includes(connection.state)?'warning':'';
    el('connectionVerified').textContent=[connection.verified_at?'Ultimo acceso comprobado: '+date(connection.verified_at)+' (Lima)':'',connection.action||''].filter(Boolean).join(' | ');
    el('configureForm').hidden=status.configured!==false;
    el('interval').textContent=status.automatic_enabled?'Consulta de archivos Excel: cada '+Math.round(status.interval_seconds/60)+' minutos':'Consulta automatica de Excel desactivada';
    const monitor=status.monitor||{};
    const workerText={disabled:'Revision automatica desactivada',starting:'Esperando actividad del proceso automatico',
      running:'Comprobando '+(labels[monitor.active_source]||'archivos'),waiting:'Proceso automatico al dia',
      blocked:'Revision automatica detenida por autorizacion',error:'La revision automatica requiere atencion',stale:'Sin actividad reciente del proceso automatico'};
    el('workerStatus').textContent=[workerText[monitor.state]||'',monitor.worker_error||'',monitor.worker_action||''].filter(Boolean).join(' | ');
    el('workerStatus').className=['stale','blocked','error'].includes(monitor.state)?'warning':'';
    el('nextCheck').textContent=status.automatic_enabled?[monitor.heartbeat_at?'Ultima actividad: '+date(monitor.heartbeat_at):'',
      monitor.next_check_at&&!['stale','running'].includes(monitor.state)?'Proxima revision prevista: '+date(monitor.next_check_at):''].filter(Boolean).join(' | '):'';
    const list=el('sources');list.replaceChildren();
    status.sources.forEach(source=>{
      const row=document.createElement('li'),heading=node('div','','item-heading');heading.append(node('strong',source.label));
      const health={manual:'Manual',not_configured:'Sin configurar',configuration_error:'Fuente incorrecta',checking:'Comprobando',authorization_required:'Falta autorizacion',stale:'Sin comprobacion reciente',pending:'Pendiente'};
      heading.append(badge(health[source.health]?source.health:source.health==='error'?'error':source.state,health[source.health]));row.append(heading);
      if(source.pending){row.append(node('p',source.pending,'secondary'));}
      else {
        if(source.filename)row.append(node('p',source.filename,'filename'));
        row.append(fields([['Comprobacion',date(source.checked_at)],['Consulta correcta',date(source.success_at)],
          ['Actualizacion efectiva',date(source.updated_at)],['Fecha del corte',date(source.cutoff_at)],
          ['Cambio en Microsoft',date(source.source_modified_at)]]));
        if(source.detail)row.append(node('p',source.detail,'secondary'));
        if(source.action)row.append(node('p',source.action,'warning'));
      }
      list.append(row);
    });
    const bi=status.powerbi_stock;
    const biStates={disabled:'Stock Power BI desactivado',pending:'Esperando el primer corte Power BI',
      configuration_error:'Falta configurar Stock Power BI',updated:'Stock Power BI conectado',unchanged:'Stock Power BI conectado',
      error:'Error en Stock Power BI',blocked:'Stock Power BI requiere atencion',stale:'Stock Power BI sin comprobacion reciente',
      superseded:'El stock vigente proviene de otro corte'};
    el('powerbiStatus').textContent=bi?(biStates[bi.state]||'Stock Power BI sin conectar'):'Estado Power BI no disponible';
    el('powerbiStatus').className=['error','blocked','stale','configuration_error','superseded'].includes(bi?.state)?'warning':'';
    el('powerbiAction').textContent=[bi?.detail,bi?.action].filter(Boolean).join(' ');
    const config=bi?.configuration||{}, declared={missing:'Sin configurar',invalid:'Identificador no valido',declared:bi?.api_access==='verified'?'Comprobado':'Declarado; sin validar'};
    el('powerbiFacts').replaceChildren(fields([
      ['Almacen solicitado',bi?.required_warehouse||'01'],
      ['Modelo semantico',declared[config.dataset]||'Sin comprobar'],
      ['Consulta del servidor',bi?.automatic_enabled?'Cada '+Math.round((bi.interval_seconds||300)/60)+' minutos':'Desactivada'],
      ['Acceso API / filtro 01',bi?.warehouse_filter_verified?'Comprobado':'Sin validar'],
      ['Ultima comprobacion',date(bi?.checked_at)],['Ultima consulta correcta',date(bi?.success_at)],
      ['Ultimo refresh del modelo',bi?.last_refresh_at?date(bi.last_refresh_at):'Sin comprobar'],
      ['Corte Power BI cargado',date(bi?.cutoff_at)],['Proxima comprobacion',date(bi?.next_check_at)],
      ['Corte de stock registrado ('+(status.registered_stock_import?.source_kind==='powerbi'?'Power BI':'Excel')+')',date(status.registered_stock_import?.cutoff_at)]
    ]));
    controls();
  }
  async function refresh() {
    const sequence=++statusSequence;
    try {
      const status=await request('/api/cloud-connection/status');
      if(disposed||sequence!==statusSequence)return;
      if(!Array.isArray(status.sources))throw new Error('Respuesta de estado no valida.');
      render(status);
    } catch(error) {
      if(disposed||sequence!==statusSequence)return;
      statusAvailable=false;
      el('connectionStatus').textContent='Estado sin actualizar. '+error.message;
      el('connectionStatus').className='warning';
      el('connectionVerified').textContent='';
      el('workerStatus').textContent='Estado del proceso sin comprobar.';
      el('nextCheck').textContent='';controls();
      throw error;
    }
  }
  async function loadHistory(reset=false) {
    if(reset){cursor=0;cursors=[];nextCursor=null;}
    const sequence=++historySequence;
    historyBusy=true;controls();
    const params=new URLSearchParams({limit:'10',source_type:el('historySource').value,state:el('historyState').value});
    if(cursor)params.set('before',String(cursor));
    try {
      const result=await request('/api/cloud-connection/history?'+params);
      if(disposed||sequence!==historySequence)return;
      nextCursor=result.next_before;
      const list=el('history');list.replaceChildren();
      result.items.forEach(item=>{
        const row=document.createElement('li'),heading=node('div','','item-heading');
        heading.append(node('strong',labels[item.source_type]||item.source_type),badge(item.state));row.append(heading);
        row.append(node('p',date(item.checked_at)+' | '+(item.origin==='automatic'?'Automatica':'Solicitada por admin')+(item.forced?' | Forzada':''),'secondary'));
        if(item.filename)row.append(node('p',item.filename,'filename'));
        row.append(node('p',item.detail));
        if(item.action)row.append(node('p',item.action,'warning'));
        const detail=document.createElement('details');detail.append(node('summary','Detalle de la carga'));
        const values=[['Inicio',date(item.started_at)],['Fecha del corte',date(item.cutoff_at)],
          ['Cambio en Microsoft',date(item.source_modified_at)],['Duracion',(item.duration_ms/1000).toFixed(1)+' s']];
        if(item.import_id)values.push(['Carga registrada','#'+item.import_id]);
        if(item.rows_count!==null)values.push(['Filas informadas',String(item.rows_count)]);
        if(item.file_hash)values.push(['Huella del archivo',item.file_hash.slice(0,12)]);
        if(item.error_code)values.push(['Motivo',item.error_code]);
        detail.append(fields(values));row.append(detail);list.append(row);
      });
      el('historyMessage').textContent=result.items.length?result.items.length+(result.items.length===1?' comprobacion':' comprobaciones')+' | Hora de Lima':'Sin comprobaciones para estos filtros.';
      el('historyMessage').classList.remove('warning');
      el('historyPage').textContent='Pagina '+(cursors.length+1);controls();
    } catch(error) { if(sequence===historySequence){el('history').replaceChildren();nextCursor=null;
      el('historyMessage').textContent=error.message;el('historyMessage').classList.add('warning');} }
    finally {if(sequence===historySequence){historyBusy=false;controls();}}
  }
  function tab(history) {
    ['status','history'].forEach(key=>{const selected=(key==='history')===history;
      el(key+'Tab').setAttribute('aria-selected',String(selected));el(key+'Tab').tabIndex=selected?0:-1;el(key+'Panel').hidden=!selected;});
    if(history)loadHistory();
  }
  async function operation(fn) {
    if(busy)return;busy=true;controls();
    try{await fn();}catch(error){message(error.message,true);}finally{busy=false;await refresh().catch(error=>message(error.message,true));controls();}
  }
  async function poll() {
    if(!flow||disposed)return;
    const pending=flow;
    if(Date.now()/1000>=flow.expires_at){stop();message('El codigo vencio. Vuelve a conectar.',true);await refresh();return;}
    try{
      const outcome=await request('/api/cloud-connection/poll',{flow_id:pending.flow_id});
      if(!flow||flow.flow_id!==pending.flow_id||disposed)return;
      if(outcome.state==='authorized'){stop();message('Cuenta autorizada. Pendiente de comprobar los archivos.');await refresh();return;}
    }catch(error){stop();message(error.message,true);await refresh().catch(()=>{});return;}
    authTimer=setTimeout(poll,Math.max(5,flow.interval)*1000);
  }
  el('configureForm').onsubmit=event=>{event.preventDefault();operation(async()=>{await request('/api/cloud-connection/configure',{client_id:el('clientId').value.trim()});message('Aplicacion guardada.');});};
  el('connect').onclick=()=>operation(async()=>{flow=await request('/api/cloud-connection/start',{});el('deviceCode').value=flow.user_code;el('authorization').hidden=false;el('expiry').textContent='Valido hasta '+date(flow.expires_at);message('');authTimer=setTimeout(poll,flow.interval*1000);});
  el('cancel').onclick=()=>operation(async()=>{if(flow)await request('/api/cloud-connection/cancel',{flow_id:flow.flow_id});stop();message('Autorizacion cancelada.');});
  el('disconnect').onclick=()=>{if(confirm('Desconectar Microsoft para ambas versiones del servidor?'))operation(async()=>{await request('/api/cloud-connection/disconnect',{});stop();message('Acceso del servidor eliminado.');});};
  el('sync').onclick=()=>operation(async()=>{message('Validando archivos...');try{
    const result=await request('/api/daily-cloud-sync',{});message(result.sources.map(source=>(labels[source.source_type]||source.source_type)+': '+(states[source.state]||source.state)).join(' | '));
  }finally{await loadHistory(true);}});
  el('refresh').onclick=()=>operation(async()=>{await refresh();await loadHistory();message('Estado actualizado.');});
  ['historySource','historyState'].forEach(id=>el(id).onchange=()=>loadHistory(true));
  el('older').onclick=()=>{if(nextCursor){cursors.push(cursor);cursor=nextCursor;loadHistory();}};
  el('newer').onclick=()=>{if(cursors.length){cursor=cursors.pop();loadHistory();}};
  el('statusTab').onclick=()=>tab(false);el('historyTab').onclick=()=>tab(true);
  [el('statusTab'),el('historyTab')].forEach(button=>button.onkeydown=event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){
    event.preventDefault();const history=event.key==='End'||event.key!=='Home'&&button===el('statusTab');tab(history);el(history?'historyTab':'statusTab').focus();}});
  async function tick() {
    if(disposed)return;
    if(!busy&&!document.hidden){await refresh().catch(error=>message(error.message,true));if(!el('historyPanel').hidden&&!cursor)await loadHistory();}
    refreshTimer=setTimeout(tick,15000);
  }
  window.addEventListener('pagehide',()=>{disposed=true;clearTimeout(authTimer);clearTimeout(refreshTimer);});
  window.addEventListener('pageshow',event=>{if(event.persisted){disposed=false;
    refresh().catch(error=>message(error.message,true));loadHistory();
    if(flow)authTimer=setTimeout(poll,5000);refreshTimer=setTimeout(tick,15000);}});
  Promise.all([refresh(),loadHistory()]).catch(error=>message(error.message,true));
  refreshTimer=setTimeout(tick,15000);
})();
