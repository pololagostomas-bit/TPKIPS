/* Administrative views shared by Reception and Dispatch. No operational writes on navigation. */
/* Shared workspace navigation: visual state only, never changes operational data. */
(() => {
  const layout = document.querySelector('main.layout');
  const queue = document.getElementById('list') || document.getElementById('queuePanel');
  const detail = document.getElementById('detail') || document.getElementById('content');
  if (!layout || !queue || !detail) return;
  const label = queue.id === 'list' ? 'OVs' : 'BL/AWB';
  document.body.classList.add('workspace-app');
  const rail = document.createElement('nav');
  rail.className = 'workspace-rail';
  rail.setAttribute('aria-label', 'Navegación de ' + label);
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'workspace-toggle';
  toggle.setAttribute('aria-controls', queue.id);
  const caption = document.createElement('span');
  caption.className = 'workspace-rail-label';
  caption.textContent = label;
  rail.append(toggle, caption);
  layout.prepend(rail);
  detail.tabIndex = -1;
  detail.setAttribute('role', 'region');
  detail.setAttribute('aria-label', 'Contenido de ' + label);
  let expanded = true;
  let lastRecord = null;
  let lastLoadedRecord = null;
  function setOpen(open, focus = false) {
    expanded = open;
    layout.classList.toggle('workspace-list-open', open);
    queue.hidden = !open;
    queue.inert = !open;
    toggle.textContent = open ? '‹' : '›';
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', (open ? 'Contraer lista de ' : 'Mostrar lista de ') + label);
    toggle.title = toggle.getAttribute('aria-label');
    document.querySelectorAll('.list-overlay,.queue-overlay').forEach(el => el.classList.remove('open'));
    if (focus) {
      if (open) (lastRecord?.isConnected ? lastRecord : queue.querySelector('.record-open,select,button') || toggle).focus();
      else detail.focus({preventScroll:true});
    }
  }
  toggle.onclick = () => setOpen(!expanded, true);
  window.openList = window.openQueue = () => setOpen(true, true);
  window.closeList = window.closeQueue = () => setOpen(false);
  window.toggleList = window.toggleQueue = () => setOpen(!expanded, true);
  const originalLoad = window.loadDetail;
  if (originalLoad) window.loadDetail = async function(...args) {
    const fromQueue = queue.contains(document.activeElement);
    const changedRecord = String(args[0]) !== lastLoadedRecord;
    if (fromQueue) lastRecord = document.activeElement;
    const result = await originalLoad.apply(this, args);
    if (!detail.querySelector(':scope > .empty')) {
      setOpen(false, fromQueue);
      if (fromQueue || changedRecord) detail.scrollTop = 0;
      lastLoadedRecord = String(args[0]);
    }
    return result;
  };
  for (const name of ['blankDetail', 'clearSelection']) {
    const original = window[name];
    if (original) window[name] = function(...args) {const result = original.apply(this,args); setOpen(true); return result;};
  }
  // Real buttons make record selection accessible without nesting button roles.
  function prepareRecords() {
    queue.querySelectorAll('.row h3,.queue-row h3').forEach(heading => {
      if (heading.querySelector('button')) return;
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'record-open';
      button.textContent = heading.textContent;
      button.setAttribute('aria-label', 'Abrir ' + button.textContent);
      heading.replaceChildren(button);
    });
  }
  new MutationObserver(prepareRecords).observe(queue,{childList:true,subtree:true});
  prepareRecords(); setOpen(true);
  document.getElementById('stateFilter')?.setAttribute('aria-label','Filtrar etapa de recepción');
  // Toolbar wrapping, zoom and cut-status updates all change the usable height.
  function fitWorkspace() {
    const navigationHeight = document.getElementById('bottomNav')?.getBoundingClientRect().height || 0;
    const available = window.innerHeight - layout.getBoundingClientRect().top - navigationHeight;
    document.body.classList.toggle('workspace-short', available < 160);
    const height = Math.max(160, available);
    layout.style.height = height + 'px';
  }
  const observer = new ResizeObserver(fitWorkspace);
  document.querySelectorAll('body > header,body > .data-strip,#bottomNav').forEach(el => observer.observe(el));
  window.addEventListener('resize', fitWorkspace);
  fitWorkspace();
})();

(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = value => Number(value||0).toLocaleString('es-PE',{maximumFractionDigits:2});
  const stamp = value => esc(String(value||'—').replace('T',' ').slice(0,19));
  const isAdmin = () => $('role')?.value === 'ADMINISTRADOR';
  const headers = () => ({'Content-Type':'application/json','X-User':$('user')?.value||'','X-Role':$('role')?.value||''});
  async function request(url, options={}) {
    const response = await fetch(url,{...options,headers:{...headers(),...options.headers}});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error||'No se pudo completar la solicitud');
    return result;
  }
  function target(){return $('detail')||$('content');}
  function begin(title) {
    if (!isAdmin()) return null;
    if (typeof clearSelection==='function') clearSelection();
    else if (typeof selected!=='undefined') selected=null;
    if (typeof closeList==='function') closeList();
    if (typeof closeQueue==='function') closeQueue();
    const root=target();root.innerHTML=`<section class="card"><h1>${esc(title)}</h1><p role="status">Cargando…</p></section>`;
    return root;
  }
  function fail(root,error){root.innerHTML=`<section class="card"><h2>No se pudo cargar</h2><p class="management-error" role="alert">${esc(error.message)}</p></section>`;}
  let userRows=[];
  window.showUsers = async () => {
    const root=begin('Usuarios y accesos');if(!root)return;
    try {
      const data=await request('/api/users');userRows=data.users||[];
      root.innerHTML=`<section class="card"><div class="management-head"><div><h1>Usuarios y accesos</h1><p>Crea usuarios, asigna su rol y controla el acceso a cada módulo.</p></div></div>
      <form id="userForm" class="management-form"><label>Usuario / correo<input id="accountUsername" required maxlength="120" autocomplete="off"></label><label>Nombre visible<input id="accountDisplay" required maxlength="160"></label><label>Nombres<input id="accountFirstName" maxlength="80"></label><label>Apellidos<input id="accountLastName" maxlength="120"></label><label>Documento de identidad<input id="accountDocumentId" maxlength="40" placeholder="DNI / CE"></label><label>Rol<select id="accountRole"><option>PICKER</option><option>GUIADOR</option><option>PICKER_GUIADOR</option><option>ASISTENTE_RECEPCION</option><option>AUXILIAR_RECEPCION</option><option>ADMINISTRADOR</option></select></label><label>Turno<select id="accountShift"><option>DÍA</option><option>NOCHE</option></select></label><label>Contraseña · mínimo 12 caracteres<input id="accountPassword" type="password" minlength="12" maxlength="256" autocomplete="new-password" placeholder="Obligatoria para nuevos accesos"></label><div class="actions"><button type="submit">Guardar usuario</button><button type="reset" class="ghost">Limpiar</button></div><p id="userMessage" role="status"></p></form>
      <p class="section-note">La ficha permite corregir nombres, apellidos e identificación sin cambiar el usuario que conserva las asignaciones y el historial. Las contraseñas nunca se muestran.</p>
      <div class="tablewrap"><table><thead><tr><th>Nombre / usuario</th><th>Rol</th><th>Turno</th><th>Acceso</th><th>Acciones</th></tr></thead><tbody>${userRows.map(u=>`<tr><td><strong>${esc(u.display_name)}</strong><br>${esc([u.first_name,u.last_name].filter(Boolean).join(' ')||'Ficha pendiente')}<br><small>${esc(u.username)}</small></td><td>${esc(u.role)}</td><td>${esc(u.shift)}</td><td><span class="traffic-light ${u.active?'green':'gray'}">${u.active?'Activo':'Inactivo'}</span></td><td><div class="management-table-actions"><button data-profile="${esc(u.username)}">Ver ficha</button><button data-edit="${esc(u.username)}">${u.active?'Editar':'Reactivar'}</button>${u.active?`<button class="danger" data-deactivate="${esc(u.username)}">Desactivar</button>`:''}</div></td></tr>`).join('')||'<tr><td colspan="5">Sin usuarios</td></tr>'}</tbody></table></div><div id="userModal" class="user-modal" role="dialog" aria-modal="true" aria-labelledby="userModalTitle" aria-hidden="true"></div></section>`;
      $('userForm').onsubmit=async event=>{
        event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;
        try{await request('/api/users',{method:'POST',body:JSON.stringify({username:$('accountUsername').value,display_name:$('accountDisplay').value,first_name:$('accountFirstName').value,last_name:$('accountLastName').value,document_id:$('accountDocumentId').value,role:$('accountRole').value,shift:$('accountShift').value,password:$('accountPassword').value})});await window.showUsers();$('userMessage').textContent='Usuario guardado correctamente.';}
        catch(error){$('userMessage').textContent=error.message;$('userMessage').className='management-error';}finally{button.disabled=false}
      };
      $('userForm').onreset=()=>{$('accountUsername').readOnly=false;for(const id of ['accountFirstName','accountLastName','accountDocumentId'])$(id).value='';};
      const fillForm=u=>{$('accountUsername').value=u.username;$('accountUsername').readOnly=true;$('accountDisplay').value=u.display_name||'';$('accountFirstName').value=u.first_name||'';$('accountLastName').value=u.last_name||'';$('accountDocumentId').value=u.document_id||'';$('accountRole').value=u.role;$('accountShift').value=u.shift;$('accountPassword').value='';$('accountDisplay').focus();};
      root.querySelectorAll('[data-edit]').forEach(button=>button.onclick=()=>{const u=userRows.find(u=>u.username===button.dataset.edit);if(u)fillForm(u);});
      const modal=$('userModal');
      const closeProfile=()=>{modal.classList.remove('open');modal.setAttribute('aria-hidden','true');};
      const openProfile=username=>{const u=userRows.find(row=>row.username===username);if(!u)return;modal.innerHTML=`<div class="user-modal-card"><div class="user-modal-head"><div><h2 id="userModalTitle">Ficha del usuario</h2><p class="section-note">Datos personales y perfil operativo.</p></div><button class="user-modal-close" type="button" aria-label="Cerrar ficha">×</button></div><p class="user-modal-note"><strong>${esc(u.username)}</strong> · ${u.active?'Cuenta activa':'Cuenta inactiva'}. La contraseña no se visualiza.</p><form id="profileForm" class="user-form-grid"><label>Nombre visible<input name="display_name" required maxlength="160" value="${esc(u.display_name||'')}"></label><label>Nombres<input name="first_name" maxlength="80" value="${esc(u.first_name||'')}"></label><label>Apellidos<input name="last_name" maxlength="120" value="${esc(u.last_name||'')}"></label><label>Documento de identidad<input name="document_id" maxlength="40" placeholder="DNI / CE" value="${esc(u.document_id||'')}"></label><label>Rol<select name="role"><option ${u.role==='PICKER'?'selected':''}>PICKER</option><option ${u.role==='GUIADOR'?'selected':''}>GUIADOR</option><option ${u.role==='PICKER_GUIADOR'?'selected':''}>PICKER_GUIADOR</option><option ${u.role==='ASISTENTE_RECEPCION'?'selected':''}>ASISTENTE_RECEPCION</option><option ${u.role==='AUXILIAR_RECEPCION'?'selected':''}>AUXILIAR_RECEPCION</option><option ${u.role==='ADMINISTRADOR'?'selected':''}>ADMINISTRADOR</option></select></label><label>Turno<select name="shift"><option ${u.shift==='DÍA'?'selected':''}>DÍA</option><option ${u.shift==='NOCHE'?'selected':''}>NOCHE</option></select></label><div class="user-modal-actions"><button class="ghost" type="button" data-close-profile>Cancelar</button><button class="primary" type="submit">Guardar cambios</button></div><p id="profileMessage" role="status"></p></form></div>`;modal.classList.add('open');modal.setAttribute('aria-hidden','false');modal.querySelector('.user-modal-close').onclick=closeProfile;modal.querySelector('[data-close-profile]').onclick=closeProfile;modal.onclick=e=>{if(e.target===modal)closeProfile()};modal.querySelector('input').focus();modal.querySelector('#profileForm').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('[type=submit]');button.disabled=true;const values=Object.fromEntries(new FormData(e.target));try{await request('/api/users',{method:'POST',body:JSON.stringify({username:u.username,...values})});closeProfile();await window.showUsers();}catch(error){$('profileMessage').textContent=error.message;$('profileMessage').className='management-error';button.disabled=false;}};};
      root.querySelectorAll('[data-profile]').forEach(button=>button.onclick=()=>openProfile(button.dataset.profile));
      root.querySelectorAll('[data-deactivate]').forEach(button=>button.onclick=async()=>{if(!confirm('¿Desactivar el acceso de '+button.dataset.deactivate+'? Su historial se conserva.'))return;button.disabled=true;try{await request('/api/users/'+encodeURIComponent(button.dataset.deactivate)+'/deactivate',{method:'POST',body:'{}'});await window.showUsers()}catch(error){$('userMessage').textContent=error.message;button.disabled=false}});
    } catch(error){fail(root,error)}
  };
  let reportFilters={period:'week',start:'',end:''};
  window.showWorkload = async () => {
    const root=begin('Seguimiento de picking');if(!root)return;
    try {
      const query=new URLSearchParams({period:reportFilters.period});
      if(reportFilters.start)query.set('start',reportFilters.start);if(reportFilters.end)query.set('end',reportFilters.end);
      const data=await request('/api/reports/workload?'+query);
      const last=data.cutoffs[data.cutoffs.length-1]||{};
      const metrics=data.picker_metrics||[];
      root.innerHTML=`<section class="card"><div class="management-head"><div><h1>Seguimiento de picking</h1><p>Trabajo nocturno de clientes internos y desempeño individual de ambos turnos.</p></div></div>
      <form class="management-form" id="workloadFilters"><label>Periodo<select id="reportPeriod"><option value="day">Hoy</option><option value="week">Semana actual</option><option value="all">Histórico disponible</option></select></label><label>Desde<input type="date" id="reportStart" value="${esc(reportFilters.start)}"></label><label>Hasta<input type="date" id="reportEnd" value="${esc(reportFilters.end)}"></label><div class="actions"><button type="submit">Aplicar filtros</button><button type="button" id="reportReset">Limpiar fechas</button><button type="button" id="reportExport">Exportar CSV</button></div></form>
      <p class="section-note">${esc(data.start)} al ${esc(data.end)} · ${data.workdays} días de lunes a viernes · Meta del periodo: ${num(data.targets.period_ovs)} OVs y ${num(data.targets.period_units)} unidades por picker.</p>
      <div class="metric-cards"><div class="metric-card"><strong>${num(last.picking_pending_ovs)}</strong><span>Pendientes de picking · última ventana</span></div><div class="metric-card"><strong>${num(last.carryover_pending_ovs)}</strong><span>Pendientes de fechas anteriores</span></div><div class="metric-card"><strong>${num(last.date_missing_ovs)}</strong><span>OVs sin fecha válida · revisar fuente</span></div></div>
      <h2>Desempeño por picker</h2><p class="section-note">Se cuentan OVs distintas con picking finalizado y unidades recogidas. Un cierre importado desde SAP no se atribuye al trabajador. Los reinicios quedan excluidos.</p>
      <div class="tablewrap"><table><thead><tr><th>Picker</th><th>Turno</th><th>OVs / meta</th><th>Unidades / meta</th><th>Cumplimiento</th></tr></thead><tbody>${metrics.map(row=>`<tr><td><strong>${esc(row.display_name)}</strong><br>${esc(row.username)}</td><td>${esc(row.shift)}</td><td class="number">${num(row.completed_ovs)} / ${num(row.target_ovs)}</td><td class="number">${num(row.picked_units)} / ${num(row.target_units)}</td><td><span class="traffic-light ${row.traffic_light==='VERDE'?'green':row.traffic_light==='AMARILLO'?'yellow':row.traffic_light==='ROJO'?'red':'gray'}">${esc(row.traffic_light)} ${row.compliance_pct===null?'':num(row.compliance_pct)+'%'}</span></td></tr>`).join('')||'<tr><td colspan="5" class="management-empty">Crea usuarios Picker para visualizar sus metas, incluso sin actividad.</td></tr>'}</tbody></table></div>
      <h2 style="margin-top:24px">Pendientes de trabajo del picker nocturno</h2><p class="section-note">Solo TRITON TRADING S.A. · Cada ventana comprende desde las 16:00 del día anterior (excluido) hasta las 16:00 del día señalado (incluido). Las fechas sin hora se interpretan a las 00:00; carga fecha y hora SAP para un corte exacto. Los estados mostrados son los actuales.</p>
      <div class="tablewrap"><table><thead><tr><th>Trabajo nocturno</th><th>Listo para</th><th>OVs ventana</th><th>Picking pendiente</th><th>Picking terminado</th><th>Cerradas SAP</th><th>Arrastre pendiente</th></tr></thead><tbody>${data.cutoffs.map(row=>`<tr><td>${esc(row.work_day)}${row.weekday_included?'':' · fin de semana'}<br><small>${stamp(row.window_start)} → ${stamp(row.cutoff_at)}</small></td><td>${esc(row.ready_day)}</td><td>${num(row.total_ovs)}</td><td>${num(row.picking_pending_ovs)}</td><td>${num(row.local_completed_ovs)}</td><td>${num(row.closed_sap_ovs)}</td><td>${num(row.carryover_pending_ovs)}</td></tr>`).join('')}</tbody></table></div>
      <details class="optional-data"><summary>Ver OVs de las ventanas y criterios de cálculo</summary><p>${data.notes.map(esc).join('<br>')}</p><div class="tablewrap"><table><thead><tr><th>Trabajo</th><th>OV</th><th>Creada SAP</th><th>Estado actual</th></tr></thead><tbody>${data.cutoffs.flatMap(c=>(c.orders.window||[]).map(o=>`<tr><td>${esc(c.work_day)}</td><td>${esc(o.sap_ov)}</td><td>${stamp(o.source_order_date)}</td><td>${esc(o.app_status)}</td></tr>`)).join('')||'<tr><td colspan="4">Sin OVs en estas ventanas.</td></tr>'}</tbody></table></div></details></section>`;
      $('reportPeriod').value=reportFilters.period;
      $('workloadFilters').onsubmit=event=>{event.preventDefault();reportFilters={period:$('reportPeriod').value,start:$('reportStart').value,end:$('reportEnd').value};window.showWorkload()};
      $('reportReset').onclick=()=>{reportFilters={period:$('reportPeriod').value,start:'',end:''};window.showWorkload()};
      $('reportExport').onclick=()=>{
        const cell=value=>'"'+String(value??'').replace(/^[=+@-]/,"'$&").replaceAll('"','""')+'"';
        const rows=[['Desde','Hasta','Picker','Turno','OVs terminadas','Meta OVs','Unidades','Meta unidades','Cumplimiento'],...metrics.map(r=>[data.start,data.end,r.username,r.shift,r.completed_ovs,r.target_ovs,r.picked_units,r.target_units,r.compliance_pct])];
        const url=URL.createObjectURL(new Blob(['\uFEFF'+rows.map(r=>r.map(cell).join(';')).join('\r\n')],{type:'text/csv;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download='picking-'+data.start+'-'+data.end+'.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      };
    }catch(error){fail(root,error)}
  };
  window.showNotifications=async()=>{
    const root=begin('Correos de recepción');if(!root)return;
    try{const data=await request('/api/notifications');root.innerHTML=`<section class="card"><div class="management-head"><div><h1>Correos de recepción</h1><p>Remitente: ${esc(data.sender)} · ${data.configured?'Envío habilitado':'Pendiente de configuración corporativa'}</p></div></div><p class="section-note">ENVIADO indica aceptación por Microsoft 365, no lectura del destinatario. Antes de repetir un envío con resultado incierto, verifica el buzón de enviados.</p><div class="tablewrap"><table><thead><tr><th>BL/AWB</th><th>Asunto / destinatario</th><th>Estado</th><th>Fecha</th><th>Detalle</th></tr></thead><tbody>${data.rows.map(r=>`<tr><td>${esc(r.bl_awb)}</td><td><strong>${esc(r.subject)}</strong><br>${esc(r.recipient)}</td><td>${esc(r.status)}<br>${num(r.attempt_count)} intentos</td><td>${stamp(r.sent_at||r.created_at)}</td><td><details><summary>Ver mensaje</summary><p style="white-space:pre-wrap">${esc(r.body)}</p><p>${esc(r.error)}</p></details>${['ERROR','REVISAR ENVIO'].includes(r.status)?`<div class="management-table-actions"><button data-retry="${r.id}">Reintentar</button></div>`:''}</td></tr>`).join('')||'<tr><td colspan="5" class="management-empty">No hay notificaciones registradas.</td></tr>'}</tbody></table></div></section>`;root.querySelectorAll('[data-retry]').forEach(button=>button.onclick=async()=>{if(!confirm('¿Reintentar este correo? Si el resultado anterior fue incierto, verifica primero que no se haya enviado.'))return;button.disabled=true;try{await request('/api/notifications/'+button.dataset.retry+'/retry',{method:'POST',body:'{}'});window.showNotifications()}catch(error){button.disabled=false;alert(error.message)}})}catch(error){fail(root,error)}
  };
  function buttons(){
    const bar=document.querySelector('.toolbar-actions');if(!bar)return;
    // The shared bottom navigation owns the administrative menu.
    if (document.getElementById('bottomNav')) return;
    for(const [id,label,action] of [['workloadButton','Carga picker',()=>window.showWorkload()],['userAdminButton','Usuarios',()=>window.showUsers()],['mailButton','Correos',()=>window.showNotifications()]]){
      let button=$(id);if(!button){button=document.createElement('button');button.id=id;button.type='button';bar.append(button)}button.textContent=label;button.onclick=action;button.hidden=!isAdmin();
    }
    let more=$('moreActions');if(!more){more=document.createElement('button');more.id='moreActions';more.type='button';more.textContent='Más opciones';more.setAttribute('aria-expanded','false');more.onclick=()=>{const open=bar.classList.toggle('expanded-actions');more.setAttribute('aria-expanded',String(open));more.textContent=open?'Menos opciones':'Más opciones'};bar.append(more)}
    const priority=['Actualizar','Reportes','Nueva BL/AWB','Carga picker','Usuarios','Correos','Stock y compromisos','Cortes Excel','Salir','Más opciones'];
    for(const button of bar.querySelectorAll('button'))button.classList.toggle('secondary-mobile-action',!['Actualizar','Reportes','Nueva BL/AWB','Más opciones','Menos opciones'].includes(button.textContent.trim()));
    for(const button of bar.querySelectorAll('button')){const order=priority.indexOf(button.textContent.trim());if(order>=0)button.style.order=order;if(button.textContent.trim()==='Reportes')button.hidden=!isAdmin();}
    for(const id of ['user','role','search','module','moduleSelector']){const input=$(id);if(input)input.setAttribute('aria-label',id==='user'?'Usuario':id==='role'?'Rol':id==='search'?(location.pathname==='/reception'?'Buscar BL/AWB':'Buscar OV'):'Módulo');}
  }
  buttons();$('role')?.addEventListener('change',buttons);
  fetch('/api/me').then(r=>r.ok?r.json():null).then(()=>buttons()).catch(()=>{});
})();

// Compact header shared by both operational modules.
(() => {
  const header = document.querySelector('header.top');
  // Perfil vive en la navegación inferior; evita duplicarlo en el encabezado.
  if (!header || document.getElementById('workspaceAccount') || document.querySelector('.bottom-nav')) return;
  const actions = header.querySelector('.toolbar-actions');
  const profile = document.createElement('dialog');
  profile.id = 'workspaceAccount'; profile.className = 'workspace-account';
  profile.setAttribute('aria-labelledby', 'workspaceAccountTitle');
  profile.innerHTML = '<h2 id="workspaceAccountTitle">Mi cuenta</h2><p>Usuario y perfil de la sesión actual.</p><div class="workspace-account-fields"></div><form method="dialog"><button class="primary">Cerrar</button></form>';
  const fields = profile.querySelector('.workspace-account-fields');
  for (const [id, caption] of [['user','Usuario'],['role','Perfil operativo']]) {
    const control = document.getElementById(id);
    if (!control) continue;
    const label = document.createElement('label'); label.textContent = caption;
    label.append(control); fields.append(label);
  }
  document.body.append(profile);
  const account = document.createElement('button');
  account.type = 'button'; account.className = 'workspace-account-button';
  account.textContent = 'Mi cuenta'; account.setAttribute('aria-haspopup','dialog');
  account.onclick = () => profile.showModal(); header.append(account);
  profile.addEventListener('close', () => account.focus({preventScroll:true}));
  const date = header.querySelector('.creation-date-filter');
  if (date && actions) {
    const filters = document.createElement('details'); filters.className = 'workspace-filters';
    const summary = document.createElement('summary'); summary.textContent = 'Fecha OV';
    filters.append(summary,date); actions.prepend(filters);
    date.querySelector('input').addEventListener('change', event => {
      summary.textContent = event.target.value ? 'Fecha: ' + event.target.value : 'Fecha OV';
      filters.open = false;
    });
  }
  const strip = document.getElementById('dailyStatus');
  if (strip) {
    const sources = document.createElement('details'); sources.className = 'workspace-sources';
    const summary = document.createElement('summary'); summary.textContent = 'Cortes de información';
    strip.before(sources); sources.append(summary,strip);
    new MutationObserver(() => {
      const stale = strip.querySelectorAll('.stale').length;
      summary.textContent = 'Cortes de información' + (stale ? ' · ' + stale + ' por actualizar' : ' · ver fechas');
    }).observe(strip,{childList:true,subtree:true});
    new ResizeObserver(() => window.dispatchEvent(new Event('resize'))).observe(sources);
  }
  window.dispatchEvent(new Event('resize'));
})();

// Administrative views use the same detail panel on small screens.
(() => {
  for (const name of ['showReport','showWorkload','showUsers','showNotifications','showTraceability']) {
    const original = window[name];
    if (!original) continue;
    window[name] = async function(...args) {
      const panel = document.getElementById('detail') || document.getElementById('content');
      const before = panel?.innerHTML;
      const result = await original.apply(this,args);
      if (panel && before !== panel.innerHTML) {
        window.closeList?.(); panel.scrollTop = 0; panel.focus({preventScroll:true});
      }
      return result;
    };
  }
})();
