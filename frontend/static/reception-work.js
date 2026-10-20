/* The server owns classification, permissions and the SLA calendar. */
(() => {
  const root = document.getElementById('content');
  if (!root) return;
  const stages = ['PROGRAMADO','ARRIBADO','REVISION SISTEMA','EM','UBICACION','VALIDACION','SOLICITUD TRANSFERENCIA','CERRADO'];
  const state = {view:'pending', search:'', stage:'', sla:'', offset:0};
  let requestId = 0, searchTimer, controller, loading = false;
  const labels = {PROGRAMADO:'Llegada', ARRIBADO:'Zona de recepción',
    'REVISION SISTEMA':'En conteo', EM:'Registro de EM', UBICACION:'Ubicación',
    VALIDACION:'Validación', 'SOLICITUD TRANSFERENCIA':'Transferencia', CERRADO:'Cerrado',
    'FR/EM COMPLETAS':'FR/EM completas'};
  const label = value => labels[value] || value;
  const stamp = (value, dateOnly=false) => {
    if (!value) return 'Sin fecha registrada';
    const raw = String(value).trim();
    const iso = /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw+'T00:00:00' : raw.replace(' ','T');
    const date = new Date(/[Zz]|[+-]\d\d:\d\d$/.test(iso) ? iso : iso+'-05:00');
    if (Number.isNaN(date.getTime())) return 'Sin fecha registrada';
    return new Intl.DateTimeFormat('es-PE',{timeZone:'America/Lima',day:'2-digit',month:'2-digit',year:'numeric',...(dateOnly?{}:{hour:'2-digit',minute:'2-digit',hour12:false})}).format(date);
  };
  const duration = hours => {
    const minutes = Math.round(Math.abs(Number(hours))*60);
    return `${Math.floor(minutes/60)} h ${String(minutes%60).padStart(2,'0')} min`;
  };
  const slaText = item => item.sla_status==='NO APLICA' ? 'No aplica' :
    item.sla_status==='FINALIZADO' ? 'Finalizado' : item.remaining_hours===null ?
    (item.pending_arrival ? 'Aún no inicia' : 'Inicio por revisar') :
    `${item.remaining_hours<0?'Vencido hace':'Quedan'} ${duration(item.remaining_hours)}`;
  const slaClass = status => ({ROJO:'overdue',AMARILLO:'at-risk',VERDE:'on-time'}[status] || 'no-start');
  const metric = (name,value,filter='') => `<button class="work-metric" type="button" data-work-metric="${filter}" aria-label="${esc(name)}: ${Number(value||0)}"><strong>${Number(value||0)}</strong><span>${esc(name)}</span></button>`;
  function row(item) {
    const attention = Number(item.attention_total)>1 ? `<small>Atención ${Number(item.attention_position||item.attention_sequence)||'—'} / ${Number(item.attention_total)}</small>` : '';
    const owners = [item.current_assistant||'Sin asistente',item.current_auxiliary||'Sin auxiliar'];
    const packages = item.attention_id ? `${Number(item.attention_received_packages||0)} recibidos` :
      Number(item.expected_packages)>0 ? `${Number(item.received_packages||0)} / ${Number(item.expected_packages)}` :
      `${Number(item.received_packages||0)} recibidos · Total sin documentar`;
    const truckAction = ['ADMINISTRADOR','ASISTENTE_RECEPCION'].includes(role()) && item.pending_arrival ?
      (item.arrival_trucks?.length ? item.arrival_trucks.map(guide=>`<button class="ghost" type="button" data-work-existing-truck="${esc(guide)}">Abrir camión ${esc(guide)}</button>`).join('') :
      '<button class="ghost" type="button" data-work-truck>Registrar camión</button>') : '';
    const deadline = item.sla_due_at ? `<small>Límite: ${esc(stamp(item.sla_due_at))}</small>` : '';
    const timing = item.pending_arrival ? `<small>Fecha Triton</small><time>${esc(item.scheduled_date?stamp(item.scheduled_date,true):'Sin fecha prevista')}</time>` :
      `<time>${esc(stamp(item.work_started_at))}</time>${deadline}`;
    const stageLabel = item.work_status === 'CERRADO' && item.condition_status === 'CIERRE ADMINISTRATIVO'
      ? 'Cierre administrativo' : item.work_status === 'CERRADO' && item.condition_status === 'REGISTRO DE PRUEBA RETIRADO'
        ? 'Registro de prueba retirado' : item.pending_arrival ? (item.pending_truck?'Pendiente de camión':'Por llegar') : label(item.work_status);
    const reason = item.awaiting_next_arrival ? `${Number(item.pending_sku_count)} SKU pendientes para otra llegada` :
      item.pending_arrival ? item.arrival_reason : item.work_reason;
    const closure = role()==='ADMINISTRADOR' && item.closure_eligible ?
      `<button class="ghost" type="button" data-work-close="${Number(item.id)}">Conciliar cierre</button>` : '';
    return `<tr data-work-row="${Number(item.id)}"><td><strong>${esc(item.bl_awb)}</strong><small>${esc((item.brands||[]).join(' / ') || 'Marca sin indicar')}</small>${attention}<span class="work-stage">${esc(stageLabel)}</span>${reason?`<small>${esc(reason)}</small>`:''}</td>
      <td>${owners.map(owner=>`<span>${esc(owner)}</span>`).join('')}</td>
      <td>${timing}</td>
      <td><strong class="work-sla ${slaClass(item.sla_status)}">${esc(slaText(item))}</strong>${item.work_started_at?`<small>SLA ${Number(item.sla_hours)} h</small>`:''}</td>
      <td>${esc(packages)}</td><td><div class="work-row-actions"><button class="primary" type="button" data-work-open="${Number(item.id)}" data-attention="${Number(item.attention_id)||0}">${item.awaiting_next_arrival?'Ver última atención':'Abrir BL'}</button>${truckAction}${closure}</div></td></tr>`;
  }
  function render(data) {
    const summary = data.summary;
    const arrivalView = ['arrival','upcoming','truck'].includes(state.view);
    const stageOptions = stages.filter(value=>arrivalView ? value==='PROGRAMADO' : state.view==='history' ? value==='CERRADO' : !['PROGRAMADO','CERRADO'].includes(value));
    const entries = Object.entries(summary.by_status||{});
    root.innerHTML = `<section class="reception-work" data-reception-work>
      <header class="work-heading"><div><h2>Trabajo en curso</h2><small>Actualizado: ${esc(stamp(data.generated_at))}</small></div><button class="ghost" type="button" id="workRefresh">Actualizar</button></header>
      <div class="work-metrics">${metric('BL en proceso',summary.total)}${metric('Pendientes de camión',summary.pending_truck,'truck')}${metric('Por llegar',summary.upcoming_arrival,'upcoming')}${metric('Por vencer',summary.sla_at_risk,'AMARILLO')}${metric('Vencidas',summary.sla_overdue,'ROJO')}</div>
      <details class="work-stages"><summary>Por etapa · ${Number(summary.open_attentions||0)} atenciones abiertas</summary><dl>${entries.map(([key,total])=>`<div><dt>${esc(label(key))}</dt><dd>${Number(total)}</dd></div>`).join('')||'<div><dt>Sin pendientes</dt><dd>0</dd></div>'}</dl></details>
      <div class="work-view-tabs" role="group" aria-label="Vista de trabajo"><button type="button" data-work-view="pending" aria-pressed="${state.view==='pending'}">En proceso</button><button type="button" data-work-view="truck" aria-pressed="${state.view==='truck'}">Pendiente de camión</button><button type="button" data-work-view="upcoming" aria-pressed="${state.view==='upcoming'}">Por llegar</button><button type="button" id="toggleReceptionHistory" data-work-view="history" aria-pressed="${state.view==='history'}">Historial</button><span>${Number(summary.documentary_complete_count||0)} BL con FR/EM completas</span></div>
      <div class="work-filters"><label>BL / AWB<input type="search" id="workSearch" value="${esc(state.search)}" autocomplete="off"></label>
      <label>Etapa<select id="workStage"><option value="">Todas</option>${stageOptions.map(value=>`<option value="${esc(value)}" ${state.stage===value?'selected':''}>${esc(label(value))}</option>`).join('')}</select></label>
      <label>SLA<select id="workSla">${[['','Todos'],['VERDE','A tiempo'],['AMARILLO','Por vencer'],['ROJO','Vencido'],['SIN INICIO','Sin inicio']].map(([value,text])=>`<option value="${value}" ${state.sla===value?'selected':''}>${text}</option>`).join('')}</select></label></div>
      ${summary.sla_missing_start?`<p class="work-data-warning" role="status">${Number(summary.sla_missing_start)} BL en proceso sin fecha de inicio registrada.</p>`:''}
      <div class="tablewrap work-table"><table><thead><tr><th>BL / etapa</th><th>Responsables</th><th>${arrivalView?'Llegada prevista':'Inicio / límite'}</th><th>SLA restante</th><th>Bultos</th><th>Acción</th></tr></thead><tbody>${data.items.map(row).join('')||'<tr><td colspan="6">No hay BL para esta selección.</td></tr>'}</tbody></table></div>
      <footer class="work-pagination"><span>${data.total?data.offset+1:0}–${Math.min(data.total,data.offset+data.items.length)} de ${data.total} ${arrivalView?'registros':'tareas'} · ${data.total_bl} BL</span><div><button class="ghost" type="button" id="workPrevious" title="Página anterior" aria-label="Página anterior" ${data.offset===0?'disabled':''}>&larr;</button><button class="ghost" type="button" id="workNext" title="Página siguiente" aria-label="Página siguiente" ${!data.has_more?'disabled':''}>&rarr;</button></div></footer>
      <p id="workError" role="alert" hidden></p></section>`;
    bind(data);
  }
  async function load() {
    if (!root.querySelector('[data-reception-work]')) return;
    clearTimeout(searchTimer);
    const id = ++requestId;
    const navigation = window.getWorkViewRequest?.();
    controller?.abort(); controller = new AbortController(); loading = true;
    const query = new URLSearchParams({view:state.view,search:state.search,stage:state.stage,sla:state.sla,offset:String(state.offset)});
    try {
      const response = await api('/api/receptions/work?'+query,{signal:controller.signal});
      const data = await response.json();
      if (!response.ok) throw Error(data.error||'No se pudo consultar el trabajo');
      if (id!==requestId || !root.querySelector('[data-reception-work]') || (window.getWorkViewRequest && navigation!==window.getWorkViewRequest())) return;
      if (data.offset && !data.items.length && data.total) { state.offset=0; await load(); return; }
      const focus = document.activeElement?.id;
      const caret = focus==='workSearch' ? document.activeElement.selectionStart : null;
      render(data);
      if (focus==='workSearch') { const field=document.getElementById(focus);field.focus();field.setSelectionRange(caret,caret); }
    } catch (error) {
      if (error.name==='AbortError' || id!==requestId || !root.querySelector('[data-reception-work]') || (window.getWorkViewRequest && navigation!==window.getWorkViewRequest())) return;
      const errorBox=document.getElementById('workError');
      if (errorBox) { errorBox.hidden=false;errorBox.textContent=error.message; }
      else root.innerHTML=`<section class="reception-work" data-reception-work><h2>Trabajo en curso</h2><p role="alert">${esc(error.message)}</p><button class="ghost" type="button" id="workRetry">Reintentar</button></section>`;
      document.getElementById('workRetry')?.addEventListener('click',load);
    } finally { if(id===requestId) loading=false; }
  }
  function bind(data) {
    document.getElementById('workRefresh').onclick=load;
    root.querySelectorAll('[data-work-view]').forEach(button=>button.onclick=()=>{
      state.view=button.dataset.workView;state.offset=0;state.stage='';state.sla='';
      load();
    });
    root.querySelectorAll('[data-work-metric]').forEach(button=>button.onclick=()=>{
      state.view=['arrival','upcoming','truck'].includes(button.dataset.workMetric)?button.dataset.workMetric:'pending';state.offset=0;state.stage='';
      state.search='';
      state.sla=['AMARILLO','ROJO'].includes(button.dataset.workMetric)?button.dataset.workMetric:'';load();
    });
    document.getElementById('workSearch').oninput=event=>{state.search=event.target.value;state.offset=0;clearTimeout(searchTimer);searchTimer=setTimeout(load,250);};
    document.getElementById('workStage').onchange=event=>{state.stage=event.target.value;state.offset=0;load();};
    document.getElementById('workSla').onchange=event=>{state.sla=event.target.value;state.offset=0;load();};
    document.getElementById('workPrevious').onclick=()=>{state.offset=Math.max(0,state.offset-data.limit);load();};
    document.getElementById('workNext').onclick=()=>{state.offset+=data.limit;load();};
    root.querySelectorAll('[data-work-open]').forEach(button=>button.onclick=()=>loadDetail(Number(button.dataset.workOpen),true,Number(button.dataset.attention)||null));
    root.querySelectorAll('[data-work-close]').forEach(button=>button.onclick=async()=>{
      if(!confirm('¿Confirmas que esta BL es histórica o tiene todas sus atenciones terminadas? El estado principal quedará CERRADO. No se registrarán cantidades ni arribos.')) return;
      const reason=prompt('Motivo del cierre histórico (mínimo 8 caracteres):');
      if(reason===null) return;
      if(reason.trim().length<8) { notify('Indica un motivo de al menos 8 caracteres','error');return; }
      button.disabled=true;
      try {
        const response=await api(`/api/receptions/${button.dataset.workClose}/reconcile-closure`,
          {method:'POST',body:JSON.stringify({confirmed:true,historical:true,reason:reason.trim()})});
        const result=await response.json();if(!response.ok) throw Error(result.error||'No se pudo conciliar el cierre');
        notify('Estado principal cerrado; historial conservado','success');await load();
      } catch(error) { button.disabled=false;notify(error.message,'error'); }
    });
    root.querySelectorAll('[data-work-truck]').forEach(button=>button.onclick=async()=>{
      button.disabled=true;
      try {
        await createScannerTruckGuide();
      } finally { if(button.isConnected) button.disabled=false; }
    });
    root.querySelectorAll('[data-work-existing-truck]').forEach(button=>button.onclick=()=>openTruckGuideFromBl(button.dataset.workExistingTruck));
  }
  window.showMyWork=async()=>{
    setActiveNav('work');closeQueue();
    root.innerHTML='<section class="reception-work" data-reception-work><h2>Trabajo en curso</h2><p role="status">Consultando pendientes...</p></section>';
    await load();
  };
  setInterval(()=>{
    if(root.querySelector('[data-reception-work]') && !document.hidden && !loading &&
       !document.activeElement?.matches('input,select,button')) load();
  },60000);
})();
