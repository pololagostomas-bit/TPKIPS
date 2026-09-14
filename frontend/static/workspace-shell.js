/* One navigation and one tools menu for Reception and Dispatch. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const reception = location.pathname === '/reception';
  const root = $('content') || $('detail');
  const header = document.querySelector('header.top');
  if (!root || !header) return;
  document.body.classList.add('unified-workspace');
  const loading=document.createElement('div');loading.className='workspace-loading';loading.hidden=true;loading.setAttribute('role','status');loading.setAttribute('aria-live','polite');loading.innerHTML='<div class="workspace-loading-card"><span class="workspace-spinner" aria-hidden="true"></span><span>Procesando, espera un momento…</span></div>';document.body.append(loading);
  let pendingRequests=0;let loadingTimer;
  const nativeFetch=window.fetch.bind(window);
  window.fetch=(...args)=>{pendingRequests++;if(pendingRequests===1)loadingTimer=setTimeout(()=>{if(pendingRequests)loading.hidden=false},1000);return nativeFetch(...args).finally(()=>{pendingRequests=Math.max(0,pendingRequests-1);if(!pendingRequests){clearTimeout(loadingTimer);loading.hidden=true}})};
  // Keep one discreet credit at the end of every screen, outside the fixed navigation.
  const credits = document.createElement('footer');
  credits.className = 'workspace-credits';
  credits.setAttribute('aria-label', 'Créditos del aplicativo');
  credits.innerHTML = '<small><span>© 2026 Triton WMS.</span><span>Desarrollado por Tomás Polo para Triton Trading S.A.</span><span>Todos los derechos reservados.</span></small>';
  function placeCredits() {
    if (root.lastElementChild !== credits) root.append(credits);
  }
  new MutationObserver(placeCredits).observe(root, {childList: true});
  placeCredits();
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const admin = () => $('role')?.value === 'ADMINISTRADOR';
  const roleText = () => ($('role')?.value || '').replaceAll('_', ' ').toLocaleLowerCase('es-PE');
<<<<<<< HEAD
  const captions = reception
    ? {home:'Inicio', operation:'Operación', work:'En curso', deliveries:'Transferencias', profile:'Mi perfil'}
    : {home:'Inicio', operation:'Operación', work:'En curso', deliveries:'Entregas', profile:'Mi perfil'};
=======
  const captions = {home:'Inicio', profile:'Perfil', work:'Trabajo', more:'Más'};
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312
  let active = 'home';
  let navigationRequest = 0;
  const icons = {
    home:'M3 10 12 3l9 7M5 9v12h5v-7h4v7h5V9',
<<<<<<< HEAD
    operation:'M4 5h16M4 12h16M4 19h16M7 3v4M13 10v4M17 17v4',
    profile:'M20 21v-2a7 7 0 0 0-14 0v2M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8',
    work:'M8 6V3h8v3M3 7h18v14H3zM3 12h18M10 11v3h4v-3',
    deliveries:'M5 4h14v16H5zM8 8h8M8 12h8M8 16h5M4 7l2 2 3-3'
=======
    profile:'M20 21v-2a7 7 0 0 0-14 0v2M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8',
    work:'M8 6V3h8v3M3 7h18v14H3zM3 12h18M10 11v3h4v-3',
    more:'M5 5h3v3H5zM16 5h3v3h-3zM5 16h3v3H5zM16 16h3v3h-3z'
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312
  };
  const nav = $('bottomNav');
  nav.innerHTML = Object.entries(captions).map(([key,label]) => `<button type="button" class="nav-item" data-nav="${key}"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="${icons[key]}"/></svg><span>${label}</span></button>`).join('');

  function activate(key) {
    active = key;
    navigationRequest++;
<<<<<<< HEAD
    // La cola existe exclusivamente dentro de Operación. Los demás módulos
    // no retienen un expediente para que no sustituyan su contenido al actualizar.
    // Al cambiar de módulo se recupera el layout normal; la selección vuelve a
    // activar el foco solamente después de que el detalle se haya cargado.
    document.querySelector('main.layout')?.classList.remove('work-focus');
=======
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312
    document.querySelectorAll('#bottomNav [data-nav]').forEach(button => {
      const current = button.dataset.nav === key;
      button.classList.toggle('active', current);
      if(current) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');
    });
    // A subsequent refresh must not replace Perfil/Más with a previously opened record.
<<<<<<< HEAD
    if(key !== 'operation') {
      if(typeof selected !== 'undefined') selected = null;
      if(typeof selectedId !== 'undefined') selectedId = null;
      if(reception) window.closeQueue?.(); else window.closeList?.();
    }
=======
    if(typeof selected !== 'undefined') selected = null;
    if(typeof selectedId !== 'undefined') selectedId = null;
    if(reception) window.closeQueue?.(); else window.closeList?.();
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312
    root.scrollTop = 0;
  }
  window.setActiveNav = key => {
    const normalized = ({account:'profile', pending:'work', performance:'work'})[key] || key;
    active = normalized;
    nav.querySelectorAll('[data-nav]').forEach(button => {
      const current=button.dataset.nav===normalized;
      button.classList.toggle('active',current);
      if(current)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
    });
  };

  const context = header.querySelector('.toolbar-context');
  let dateFilterTimer;
  const scheduleDateFilter=()=>{clearTimeout(dateFilterTimer);dateFilterTimer=setTimeout(()=>reception?window.loadReceptions({keepQueue:true}):window.loadOrders(),180)};
<<<<<<< HEAD
  const identityStore = $('workspaceIdentityControls') || document.createElement('div');
  identityStore.hidden = true;
  identityStore.id = 'workspaceIdentityControls';
  if (!identityStore.isConnected) document.body.append(identityStore);
=======
  const identityStore = document.createElement('div');
  identityStore.hidden = true;
  identityStore.id = 'workspaceIdentityControls';
  document.body.append(identityStore);
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312
  for(const id of ['user','role']) if($(id)) identityStore.append($(id));
  const brand = header.querySelector('.brand');
  brand.querySelector('strong').textContent = 'TRITON WMS';
  brand.querySelector('span').remove();
<<<<<<< HEAD
  // La cabecera usa la marca mínima del modelo operativo: una T reconocible,
  // no el logo horizontal completo que ocupaba espacio útil en celular.
  const fullLogo = brand.querySelector('img');
  if (fullLogo) {
    // `span` is hidden by the legacy subtitle rule in the inline template.
    // Use a dedicated element so the compact mark remains visible on mobile.
    const mark = document.createElement('div');
    mark.className = 'workspace-brand-mark';
    mark.setAttribute('aria-label', 'Triton');
    mark.textContent = 'T';
    fullLogo.replaceWith(mark);
  }
  // Variante 1: identidad de la sesión visible en el encabezado. El perfil
  // sigue siendo una pantalla propia, pero el usuario siempre sabe quién opera.
  const profileChip=document.querySelector('.workspace-profile-chip') || document.createElement('button');
  profileChip.type='button';profileChip.className='workspace-profile-chip';
  profileChip.setAttribute('aria-label','Abrir mi perfil');profileChip.title='Abrir mi perfil';
  if (!profileChip.isConnected) header.append(profileChip);
  function initials(value){return String(value||'U').split(/[.\s_-]+/).filter(Boolean).slice(0,2).map(part=>part[0]).join('').toUpperCase()||'U'}
  function refreshProfile(account={}){
    const username=account.username||$('user')?.value||'usuario';
    const display=account.display_name||username;
    const currentRole=account.role||$('role')?.value||'';
    profileChip.innerHTML=`<span class="workspace-profile-avatar" aria-hidden="true">${esc(initials(display))}</span><span class="workspace-profile-copy"><strong>${esc(display)}</strong><small>${esc(String(currentRole).replaceAll('_',' ')||'Perfil')}</small></span>`;
  }
  async function loadProfileChip(){
    refreshProfile();
    try{const response=await fetch('/api/account',{headers:{'X-User':$('user')?.value||'','X-Role':$('role')?.value||''}});if(response.ok)refreshProfile(await response.json())}catch(error){}
  }
  profileChip.onclick=()=>window.showAccount?.();
  refreshProfile();$('role')?.addEventListener('change',()=>refreshProfile());
  const originalInstall = window.installSessionControls;
  window.installSessionControls = me => {
    originalInstall?.(me);
    // Initialization fills the hidden fields after this callback.
    queueMicrotask(loadProfileChip);
  };
  loadProfileChip();
=======
  const roleLabel = document.createElement('span');
  roleLabel.id='workspaceRole';roleLabel.className='workspace-role';
  brand.append(roleLabel);
  function refreshRole(){roleLabel.textContent=roleText();roleLabel.title='Rol de la sesión';}
  refreshRole();$('role')?.addEventListener('change',refreshRole);
  const originalInstall = window.installSessionControls;
  window.installSessionControls = me => {
    originalInstall?.(me);
    // Initialization fills the hidden role field immediately after this callback.
    queueMicrotask(refreshRole);
  };
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312
  function dateField(id, label, description){
    const field=document.createElement('label');field.className='workspace-date workspace-date-'+id;
    field.innerHTML=`<span>${label}</span><input id="${id}" type="date" aria-label="${description}">`;
    context.append(field);$(id).onchange=scheduleDateFilter;
  }
  if(reception){
    dateField('arrivalDate','Desde','Filtrar BL desde esta fecha');
    dateField('arrivalDateEnd','Hasta','Filtrar BL hasta esta fecha');
  } else {
    const legacy=$('creationDate')?.closest('label');
    legacy?.remove();
    dateField('creationDate','Desde','Filtrar OV desde esta fecha');
    dateField('creationDateEnd','Hasta','Filtrar OV hasta esta fecha');
  }
  const search=$('search');
  const searchLabel=document.createElement('label');searchLabel.className='workspace-search';
  search.before(searchLabel);searchLabel.innerHTML=`<span>${reception?'Buscar BL / AWB':'Buscar OV'}</span>`;searchLabel.append(search);
  search.placeholder=reception?'BL o últimos 4 dígitos':'OV, cliente o artículo';
  const moduleControl=$('module')||$('moduleSelector');
  const moduleLabel=document.createElement('label');moduleLabel.className='workspace-module';
  moduleControl.before(moduleLabel);moduleLabel.innerHTML='<span>Módulo</span>';moduleLabel.append(moduleControl);
<<<<<<< HEAD
  const dailyStatus=$('dailyStatus');
  if(dailyStatus){dailyStatus.classList.add('workspace-cutoff-status');header.append(dailyStatus);}

  // Buscar y filtrar pertenece a la cola de Operación, no a todas las pantallas.
  // Así Inicio, Perfil y las vistas de seguimiento quedan libres de controles.
  const operationFilters=document.createElement('section');
  operationFilters.className='operation-filters';
  operationFilters.setAttribute('aria-label','Buscar y filtrar cola operativa');
  const clientFilter=document.createElement('select');
  clientFilter.id='customerTypeFilter';
  clientFilter.setAttribute('aria-label','Tipo de cliente');
  clientFilter.innerHTML='<option value="">Todos los clientes</option><option value="internal">Cliente interno</option><option value="regular">Cliente regular</option>';
  const originFilter=document.createElement('select');
  originFilter.id='stockOriginFilter';
  originFilter.setAttribute('aria-label','Origen del stock de la OV');
  originFilter.innerHTML='<option value="">Todos los orígenes</option><option value="STOCK">Solo stock</option><option value="AEREO">Solo aéreo</option><option value="MARITIMO">Solo marítimo</option><option value="MIXTO">Mixto</option>';
  const advanced=document.createElement('details');advanced.className='operation-more-filters';
  advanced.innerHTML='<summary>Más filtros</summary><div class="operation-filter-advanced"></div>';
  operationFilters.append(searchLabel, advanced);
  const advancedBody=advanced.querySelector('.operation-filter-advanced');
  for(const field of [...context.querySelectorAll('.workspace-date')]) advancedBody.append(field);
  const statusFilter=$('statusFilter') || $('stageFilter');
  if(statusFilter){
    [...statusFilter.options].filter(option=>option.value==='STOCK_PARCIAL').forEach(option=>option.remove());
    advancedBody.append(statusFilter.closest('label')||statusFilter);
  }
  advancedBody.append(clientFilter);
  // El origen se consulta desde la barra lateral para mantener la parte alta
  // de la cola reservada únicamente a búsqueda y filtros generales.
  if(!reception){
    const rail=document.querySelector('.workspace-rail');
    if(rail){
      const originControl=document.createElement('details');
      originControl.className='workspace-origin-filter';
      originControl.innerHTML='<summary>Origen</summary>';
      originControl.append(originFilter);
      rail.append(originControl);
    }
  }
  function queueHost(){return document.querySelector(reception?'.queue':'.list')}
  function relocateOperationControls(){
    const host=queueHost();
    if(active==='operation' && host && operationFilters.parentElement!==host)host.prepend(operationFilters);
    const visibleCount=host?.querySelector('.queue-visible-count');
    const searchLabel=operationFilters.querySelector('.workspace-search');
    if(visibleCount&&searchLabel&&!operationFilters.querySelector('.workspace-visible-count')){
      visibleCount.classList.add('workspace-visible-count');
      searchLabel.append(visibleCount);
    }
    // renderList de versiones anteriores vuelve a crear #statusFilter dentro
    // del encabezado. Preferimos siempre ese selector recién creado y quitamos
    // el anterior para que Etapa nunca se duplique ni desaparezca al filtrar.
    const sourceStage=host?.querySelector('.queue-controls #statusFilter');
    const stage=sourceStage||advancedBody.querySelector('#statusFilter')||$('stateFilter');
    if(sourceStage){
      const oldStage=advancedBody.querySelector('#statusFilter');
      if(oldStage&&oldStage!==sourceStage)oldStage.closest('.operation-stage-filter')?.remove();
    }
    if(stage && !advancedBody.contains(stage)){
      const oldContainer=stage.closest('.queue-filter');
      const label=document.createElement('label');label.className='operation-stage-filter';
      label.textContent='Etapa';label.append(stage);
      advancedBody.prepend(label);
      oldContainer?.remove();
    }
    // Stock parcial es un indicador de disponibilidad, no una etapa de trabajo.
    [...(stage?.options||[])].filter(option=>option.value==='STOCK_PARCIAL').forEach(option=>option.remove());
    document.querySelector('.queue-controls .queue-label')?.remove();
  }
  function applyCustomerFilter(){
    const type=clientFilter.value;
    const origin=originFilter.value;
    const rows=[...document.querySelectorAll(reception?'.queue .queue-row':'.list .row')];
    rows.forEach(row=>{
      const internal=/cliente interno/i.test(row.textContent||'');
      const typeMismatch=type==='internal'?!internal:type==='regular'?internal:false;
      const originFromRow=()=>{
        if(row.dataset.origin)return row.dataset.origin;
        const match=(row.textContent||'').match(/Origen:\s*(MIXTO|A[ÉE]REO|MAR[IÍ]TIMO|STOCK)/i);
        const value=String(match?.[1]||'STOCK').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toUpperCase();
        return value==='AEREO'||value==='MARITIMO'||value==='MIXTO'?value:'STOCK';
      };
      const originMismatch=!reception&&origin!==''&&originFromRow()!==origin;
      row.hidden=typeMismatch||originMismatch;
    });
  }
  clientFilter.addEventListener('change',applyCustomerFilter);
  originFilter.addEventListener('change',()=>{
    // Las versiones actuales recalculan paginación desde el origen; las que
    // aún están ejecutándose sin reinicio se filtran en pantalla sin fallar.
    if(!reception&&document.querySelector('.list .row[data-origin]')&&typeof window.renderList==='function'){window.renderList();return;}
    applyCustomerFilter();
  });
  const baseRenderList=window.renderList;
  if(baseRenderList)window.renderList=function(...args){const out=baseRenderList.apply(this,args);relocateOperationControls();applyCustomerFilter();return out};
  const baseRenderQueue=window.renderQueue;
  if(baseRenderQueue)window.renderQueue=function(...args){const out=baseRenderQueue.apply(this,args);relocateOperationControls();applyCustomerFilter();return out};
  function showOperation(){
    activate('operation');
    const host=queueHost();
    operationFilters.hidden=false;
    // Volver a Operación siempre cancela la selección temporal. Así una carga
    // posterior no vuelve a abrir el expediente ni esconde la cola.
    if(typeof selected!=='undefined')selected=null;
    if(typeof selectedId!=='undefined')selectedId=null;
    if(reception)window.openQueue?.();else window.openList?.();
    relocateOperationControls();
    root.innerHTML='<section class="card operation-empty"><h1>Selecciona una '+(reception?'BL/AWB':'OV')+'</h1><p>Busca o elige un registro de la lista para iniciar el trabajo.</p></section>';
    applyCustomerFilter();
  }
  // Debe permanecer conectado al DOM aunque esté oculto: loadOrders y
  // loadReceptions leen #search incluso cuando el usuario está en Inicio.
  operationFilters.hidden=true;
  header.append(operationFilters);

  window.showMore = () => {
    activate('profile');
=======

  window.showMore = () => {
    activate('more');
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312
    root.innerHTML='<section class="card workspace-tools"><h1>Más opciones</h1><p>Herramientas de '+(reception?'Recepción':'Despacho')+'.</p><div id="commonTools" class="tools-grid"></div></section>';
    function action(target,label,description,callback){
      const button=document.createElement('button');button.type='button';button.className='tool-link';
      button.innerHTML=`<strong>${esc(label)}</strong><span>${esc(description)}</span>`;
      button.onclick=callback;target.append(button);
    }
    const common=$('commonTools');
    action(common,'Actualizar','Consultar la cola con los filtros actuales',async()=>{
<<<<<<< HEAD
      await (reception?window.loadReceptions():window.loadOrders());showOperation();
=======
      await (reception?window.loadReceptions():window.loadOrders());window.goHome();
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312
    });
    action(common,'Avisos','Revisar bloqueos y tareas que necesitan atención',()=>{activate('more');window.showNotices();});
    if(admin()){
      const heading=document.createElement('h2');heading.textContent='Administración';root.firstElementChild.append(heading);
      const tools=document.createElement('div');tools.className='tools-grid';tools.id='adminTools';root.firstElementChild.append(tools);
      action(tools,'Cortes Excel','Cargar OV/stock, importaciones y FR/EM',()=>$('dailyDataButton').click());
      action(tools,'Usuarios','Administrar accesos y responsables',()=>window.showUsers());
      action(tools,'Carga picker','Consultar metas, turnos y desempeño',()=>window.showWorkload());
      action(tools,'Reportes',reception?'Seguimiento de recepción e historial':'Seguimiento de atenciones',()=>reception?window.openReport():window.showReport());
      action(tools,'Correos','Consultar solicitudes y estado de envío',()=>window.showNotifications());
      if(reception)action(tools,'Nueva BL / AWB','Registrar una llegada manual',()=>window.openNewModal());
      else action(tools,'Stock y compromisos','Consultar saldos y reservas',()=>$('dailyStockButton').click());
      if(!reception&&window.wmsFeatures?.advanced_lots)action(tools,'Trazabilidad','Consultar lotes y movimientos',()=>window.showTraceability());
      const cuts=document.createElement('details');cuts.className='optional-data';
      const summary=document.createElement('summary');summary.textContent='Estado de los cortes';cuts.append(summary);
      const text=document.createElement('p');text.textContent=$('dailyStatus')?.textContent||'Sin información de cortes';cuts.append(text);root.firstElementChild.append(cuts);
    }
    if($('sessionLogout'))action(common,'Salir','Cerrar esta sesión',()=>$('sessionLogout').click());
  };

  // Keep the existing authenticated profile API, show a single profile screen.
  window.showAccount = async () => {
    activate('profile');const requestId=navigationRequest;
    root.innerHTML='<section class="card"><h1>Perfil</h1><p role="status">Cargando perfil…</p></section>';
    try{
      const response=await fetch('/api/account',{headers:{'X-User':$('user').value,'X-Role':$('role').value}});
      const account=await response.json();if(!response.ok)throw Error(account.error||'No se pudo consultar el perfil');
      if(requestId!==navigationRequest)return;
      const fields=[['Nombre visible',account.display_name],['Nombres',account.first_name],['Apellidos',account.last_name],['Usuario',account.username],['Rol',(account.role||'').replaceAll('_',' ')],['Turno',account.shift]];
<<<<<<< HEAD
      root.innerHTML=`<section class="card"><h1>Mi perfil</h1><p>Datos de tu cuenta y asignación operativa.</p><dl class="profile-fields">${fields.map(([label,value])=>`<div><dt>${esc(label)}</dt><dd>${esc(value||'No registrado')}</dd></div>`).join('')}</dl><button class="ghost profile-tools-button" type="button">Herramientas y opciones</button></section>`;
      root.querySelector('.profile-tools-button')?.addEventListener('click',window.showMore);
=======
      root.innerHTML=`<section class="card"><h1>Perfil</h1><p>Datos de tu cuenta y asignación operativa.</p><dl class="profile-fields">${fields.map(([label,value])=>`<div><dt>${esc(label)}</dt><dd>${esc(value||'No registrado')}</dd></div>`).join('')}</dl></section>`;
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312
    }catch(error){if(requestId===navigationRequest)root.innerHTML=`<section class="card"><h1>Perfil</h1><p role="alert">${esc(error.message)}</p></section>`;}
  };
  const originalHome = window.renderHomeDashboard;
  window.renderHomeDashboard = () => {
    activate('home');originalHome();
    const note=document.createElement('p');note.className='section-note';
<<<<<<< HEAD
    note.textContent=`Vista de ${reception?'hasta 10 BL':'hasta 20 OV'} según tus filtros. Los indicadores generales se consultan desde Mi perfil.`;
    root.firstElementChild?.append(note);
    const button=document.createElement('button');button.type='button';button.className='primary';button.textContent='Ver lista de '+(reception?'BL':'OV');
    button.textContent='Ir a Operación';button.onclick=showOperation;root.firstElementChild?.append(button);
=======
    note.textContent=`Vista de ${reception?'hasta 10 BL':'hasta 20 OV'} según tus filtros. Los indicadores generales se consultan en Más → Reportes.`;
    root.firstElementChild?.append(note);
    const button=document.createElement('button');button.type='button';button.className='primary';button.textContent='Ver lista de '+(reception?'BL':'OV');
    button.onclick=()=>reception?window.openQueue():window.openList();root.firstElementChild?.append(button);
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312
  };
  window.goHome=()=>window.renderHomeDashboard();
  async function loadGlobalWorkSummary(){
    const host=root.querySelector('.work-global-summary');if(!host)return;
    try{
<<<<<<< HEAD
      const response=await fetch('/api/work-summary?module='+(reception?'reception':'dispatch'),{headers:{'X-User':$('user').value,'X-Role':$('role').value}});
=======
      const response=await fetch('/api/work-summary?module='+(reception?'reception':'dispatch'));
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312
      const data=await response.json();if(!response.ok)throw Error(data.error||'No se pudo cargar el resumen');
      host.innerHTML='<div class="section-title"><div><span class="eyebrow">Base acumulada</span><h3>Trabajos por estado</h3></div><span class="badge orange">'+esc(data.total)+' total</span></div><div class="global-status-grid">'+Object.entries(data.by_status||{}).map(([state,total])=>'<div class="global-status"><strong>'+esc(total)+'</strong><span>'+esc(state.replaceAll('_',' '))+'</span></div>').join('')+'</div><p class="section-note">Este recuento considera toda la base acumulada y respeta tus asignaciones.</p>';
    }catch(error){host.innerHTML='<p class="notice error">'+esc(error.message)+'</p>';}
  }
  function enhanceSortableWorkTable(){
    const table=root.querySelector('.tablewrap table');if(!table)return;
    const headers=[...table.querySelectorAll('thead th')];
    headers.forEach((th,index)=>{
      if(th.querySelector('.sort-button'))return;
      const label=th.textContent.trim();const button=document.createElement('button');button.type='button';button.className='sort-button';button.textContent=label;button.dataset.direction='none';button.setAttribute('aria-label','Ordenar por '+label);
      th.textContent='';th.append(button);
      button.onclick=()=>{
        const direction=button.dataset.direction==='asc'?'desc':'asc';headers.forEach(other=>{const old=other.querySelector('.sort-button');if(old&&old!==button){old.dataset.direction='none';old.textContent=old.textContent.replace(/ ↑| ↓$/,'');}});button.dataset.direction=direction;button.textContent=label+' '+(direction==='asc'?'↑':'↓');
        const body=table.querySelector('tbody');[...body.rows].sort((a,b)=>{const av=a.cells[index]?.innerText.trim()||'';const bv=b.cells[index]?.innerText.trim()||'';const an=Number(av.replace(/[^0-9.-]/g,''));const bn=Number(bv.replace(/[^0-9.-]/g,''));const numeric=av!==''&&bv!==''&&!Number.isNaN(an)&&!Number.isNaN(bn);const compare=numeric?an-bn:av.localeCompare(bv,'es',{numeric:true,sensitivity:'base'});return direction==='asc'?compare:-compare;}).forEach(row=>body.append(row));
      };
    });
  }
  const originalWork=window.showMyWork;
<<<<<<< HEAD
  window.showMyWork=()=>{activate('work');originalWork();const card=root.querySelector('section.card');if(card){const title=card.querySelector('h2');if(title)title.textContent='Trabajo en curso';const host=document.createElement('section');host.className='work-global-summary';host.innerHTML='<p class="empty">Consultando todos los estados…</p>';const table=card.querySelector('.tablewrap');card.insertBefore(host,table||null);}enhanceSortableWorkTable();loadGlobalWorkSummary();};
  window.showPendingDeliveries=async()=>{
    activate('deliveries');
    if(reception){
      root.innerHTML='<section class="card"><h1>Transferencias pendientes</h1><p>Este módulo se habilitará con las solicitudes de transferencia de Recepción. Revisa tu Trabajo en curso para completar las etapas asignadas.</p></section>';
      return;
    }
    root.innerHTML='<section class="card"><h1>Entregas pendientes</h1><p role="status">Consultando OVs listas para entregar…</p></section>';
    try{
      const response=await fetch('/api/deliveries/pending',{headers:{'X-User':$('user').value,'X-Role':$('role').value}});
      const data=await response.json();if(!response.ok)throw Error(data.error||'No se pudieron consultar las entregas');
      const rows=(data.deliveries||[]).map(row=>`<tr><td><button class="ghost" type="button" onclick="loadDetail('${esc(row.sap_ov)}')">${esc(row.sap_ov)}</button></td><td>${esc(row.customer_name||'Cliente')}</td><td>${esc(row.cost_centers||'Sin CECO')}</td><td>${esc(row.current_picker||'Sin picker')}</td><td>${esc(row.current_guide||'Sin guiador')}</td><td>${row.has_signed_guide?'Adjunta':'Pendiente'}</td></tr>`).join('')||'<tr><td colspan="6">No hay entregas pendientes.</td></tr>';
      root.innerHTML=`<section class="card"><div class="section-title"><div><span class="eyebrow">Despacho</span><h1>Entregas pendientes</h1><p>OVs con guiado finalizado. La entrega requiere foto de la guía firmada.</p></div><a class="primary export-deliveries" href="/api/deliveries/pending/export">Descargar Excel</a></div><div class="tablewrap"><table><thead><tr><th>OV</th><th>Cliente</th><th>CECO</th><th>Picker</th><th>Guiador</th><th>Guía firmada</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
      enhanceSortableWorkTable();
    }catch(error){root.innerHTML=`<section class="card"><h1>Entregas pendientes</h1><p role="alert">${esc(error.message)}</p></section>`;}
  };
  const originalDetail=window.loadDetail;
  window.loadDetail=async function(...args){
    window.setActiveNav('operation');navigationRequest++;
    const result=await originalDetail.apply(this,args);
    const layout=document.querySelector('main.layout');
    const detail=$('content')||$('detail');
    if(detail&&!detail.querySelector(':scope > .empty')){
      layout?.classList.add('work-focus');
      // Cierra mediante management.js para sincronizar el ancho del grid,
      // la visibilidad y aria-expanded de la barra de la izquierda.
      if(reception)window.closeQueue?.();else window.closeList?.();
    }
    if(!reception)await renderDeliveryEvidence(args[0]);
    return result;
  };
  async function renderDeliveryEvidence(ov){
    try{
      const response=await fetch('/api/orders/'+encodeURIComponent(ov),{headers:{'X-User':$('user').value,'X-Role':$('role').value}});
      const order=await response.json();if(!response.ok)return;
      const attention=(order.attentions||[]).find(item=>!['ENTREGADO','CERRADO SAP'].includes(item.app_status));
      if(!attention||!['EN GUIADO','GUIADO FINALIZADO'].includes(attention.app_status))return;
      const role=$('role').value;const canUpload=role==='ADMINISTRADOR'||(['GUIADOR','PICKER_GUIADOR'].includes(role)&&String(attention.current_guide||'').toLowerCase()===String($('user').value||'').toLowerCase());
      const existing=attention.delivery_evidence;
      const card=document.createElement('section');card.className='card delivery-evidence';
      card.innerHTML=`<h2>Guía firmada</h2><p class="section-note">Antes de registrar la entrega, toma o adjunta una foto legible de la guía firmada.</p>${existing?`<p class="notice success">Adjunta por ${esc(existing.uploaded_by)} el ${esc(existing.uploaded_at)}. <a href="/api/attentions/${attention.id}/delivery-evidence" target="_blank" rel="noopener">Ver evidencia</a></p>`:''}${canUpload?`<label class="delivery-photo-field">Foto de guía firmada<input id="deliveryEvidenceFile" type="file" accept="image/jpeg,image/png,image/webp" capture="environment"></label><button class="primary" id="uploadDeliveryEvidence" type="button">${existing?'Reemplazar foto':'Guardar foto de guía'}</button>`:'<p class="notice">Solo el guiador/entregador asignado puede adjuntar la evidencia.</p>'}`;
      root.append(card);
      card.querySelector('#uploadDeliveryEvidence')?.addEventListener('click',async()=>{
        const file=card.querySelector('#deliveryEvidenceFile')?.files?.[0];if(!file){alert('Selecciona o toma una foto de la guía firmada.');return;}if(file.size>8*1024*1024){alert('La foto debe pesar como máximo 8 MB.');return;}
        const reader=new FileReader();reader.onload=async()=>{try{const r=await fetch('/api/attentions/'+attention.id+'/delivery-evidence',{method:'POST',headers:{'Content-Type':'application/json','X-User':$('user').value,'X-Role':$('role').value,'X-WMS-Request':'1'},body:JSON.stringify({file_name:file.name,mime_type:file.type,image_base64:reader.result})});const data=await r.json();if(!r.ok)throw Error(data.error||'No se pudo guardar la foto');await window.loadDetail(ov);notify('Guía firmada guardada','success')}catch(error){notify(error.message,'error')}};reader.readAsDataURL(file);
      });
    }catch(error){console.warn('No se pudo cargar la evidencia de entrega',error);}
  }
  nav.addEventListener('click', event=>{
    const key=event.target.closest('[data-nav]')?.dataset.nav;
    if(key==='home')window.goHome();if(key==='operation')showOperation();if(key==='profile')window.showAccount();if(key==='work')window.showMyWork();if(key==='deliveries')window.showPendingDeliveries();
=======
  window.showMyWork=()=>{activate('work');originalWork();const card=root.querySelector('section.card');if(card){const host=document.createElement('section');host.className='work-global-summary';host.innerHTML='<p class="empty">Consultando todos los estados…</p>';const table=card.querySelector('.tablewrap');card.insertBefore(host,table||null);}enhanceSortableWorkTable();loadGlobalWorkSummary();};
  const originalDetail=window.loadDetail;
  window.loadDetail=async function(...args){window.setActiveNav('work');navigationRequest++;return originalDetail.apply(this,args);};
  nav.addEventListener('click', event=>{
    const key=event.target.closest('[data-nav]')?.dataset.nav;
    if(key==='home')window.goHome();if(key==='profile')window.showAccount();if(key==='work')window.showMyWork();if(key==='more')window.showMore();
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312
  });
  // Refresh the currently visible dashboard, never overwrite another module.
  for(const name of [reception?'loadReceptions':'loadOrders']){
    const original=window[name];
<<<<<<< HEAD
    window[name]=async function(...args){const result=await original.apply(this,args);if(active==='home')window.renderHomeDashboard();return result;};
=======
    window[name]=async function(...args){const result=await original.apply(this,args);refreshRole();if(active==='home')window.renderHomeDashboard();return result;};
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312
  }
  window.dispatchEvent(new Event('resize'));
})();
