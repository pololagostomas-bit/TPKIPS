(() => {
  'use strict';
  const el = id => document.getElementById(id);
  let flow = null;
  let timer = null;
  let busy = false;
  async function request(path, data) {
    const response = await fetch(path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-WMS-Request':'1'}, body:JSON.stringify(data)});
    let payload;
    try { payload = await response.json(); } catch { throw new Error('El servidor no respondio correctamente. Revisa la conexion.'); }
    if (!response.ok) throw new Error(payload.error || 'No se pudo completar la solicitud.');
    return payload;
  }
  function message(text, error=false) {el('message').textContent=text;el('message').classList.toggle('error',error);}
  function stop() {clearTimeout(timer);timer=null;flow=null;el('authorization').hidden=true;el('deviceCode').value='';}
  async function refresh() {
    const status = await request('/api/cloud-connection/status');
    el('connectionStatus').textContent = status.authorized ? 'Autorizacion guardada en el servidor' : status.pending ? 'Autorizacion pendiente' : status.configured ? 'Pendiente de conectar la cuenta de empresa' : 'Pendiente del Client ID de TI';
    el('configureForm').hidden=status.configured;
    el('connect').disabled=busy||!status.configured||status.pending;
    el('disconnect').hidden=!status.authorized&&!status.pending;
    el('disconnect').disabled=busy;
    el('sync').disabled=busy||!status.authorized;
    el('interval').textContent=status.automatic_enabled ? `Consulta automatica: cada ${Math.round(status.interval_seconds/60)} minutos` : 'Consulta automatica desactivada';
    const list=el('sources');list.replaceChildren();
    status.sources.forEach(source=>{
      const row=document.createElement('li'),title=document.createElement('strong'),detail=document.createElement('small');
      title.textContent=source.label;
      const states={updated:'Actualizado',unchanged:'Sin cambios',error:'Requiere revision'};
      detail.textContent=source.pending||[(states[source.state]||'Pendiente de primera validacion'),source.checked_at?`Consulta: ${source.checked_at.replace('T',' ')}`:'',source.success_at?`Ultima consulta correcta: ${source.success_at.replace('T',' ')}`:'',source.detail||''].filter(Boolean).join(' | ');
      row.append(title,detail);list.append(row);
    });
  }
  async function operation(fn) {
    if(busy)return;busy=true;document.querySelectorAll('button').forEach(button=>button.disabled=true);
    try{await fn();}catch(error){message(error.message,true);}finally{busy=false;el('refresh').disabled=false;el('cancel').disabled=false;el('configureForm').querySelector('button').disabled=false;await refresh().catch(error=>message(error.message,true));}
  }
  async function poll() {
    if(!flow)return;
    if(Date.now()/1000>=flow.expires_at){stop();message('El codigo vencio. Vuelve a conectar.',true);await refresh();return;}
    try{
      const outcome=await request('/api/cloud-connection/poll',{flow_id:flow.flow_id});
      if(outcome.state==='authorized'){stop();message('Cuenta autorizada. La primera consulta validara los archivos.');await refresh();return;}
    }catch(error){stop();message(error.message,true);await refresh().catch(()=>{});return;}
    timer=setTimeout(poll,Math.max(5,flow.interval)*1000);
  }
  el('configureForm').onsubmit=event=>{event.preventDefault();operation(async()=>{await request('/api/cloud-connection/configure',{client_id:el('clientId').value.trim()});message('Aplicacion guardada.');});};
  el('connect').onclick=()=>operation(async()=>{flow=await request('/api/cloud-connection/start',{});el('deviceCode').value=flow.user_code;el('authorization').hidden=false;el('expiry').textContent='Valido hasta '+new Date(flow.expires_at*1000).toLocaleTimeString();message('');timer=setTimeout(poll,flow.interval*1000);});
  el('cancel').onclick=()=>operation(async()=>{if(flow)await request('/api/cloud-connection/cancel',{flow_id:flow.flow_id});stop();message('Autorizacion cancelada.');});
  el('disconnect').onclick=()=>{if(confirm('Desconectar Microsoft para ambas versiones del servidor?'))operation(async()=>{await request('/api/cloud-connection/disconnect',{});stop();message('Acceso del servidor eliminado.');});};
  el('sync').onclick=()=>operation(async()=>{message('Validando archivos...');const result=await request('/api/daily-cloud-sync',{});message(result.sources.map(source=>`${source.source_type}: ${source.state==='unchanged'?'sin cambios':'actualizado'}`).join(' | '));});
  el('refresh').onclick=()=>operation(refresh);
  window.addEventListener('pagehide',()=>clearTimeout(timer));
  refresh().catch(error=>message(error.message,true));
})();
