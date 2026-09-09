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
  const captions = {home:'Inicio', profile:'Perfil', work:'Trabajo', more:'Más'};
  let active = 'home';
  let navigationRequest = 0;
  const icons = {
    home:'M3 10 12 3l9 7M5 9v12h5v-7h4v7h5V9',
    profile:'M20 21v-2a7 7 0 0 0-14 0v2M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8',
    work:'M8 6V3h8v3M3 7h18v14H3zM3 12h18M10 11v3h4v-3',
    more:'M5 5h3v3H5zM16 5h3v3h-3zM5 16h3v3H5zM16 16h3v3h-3z'
  };
  const nav = $('bottomNav');
  nav.innerHTML = Object.entries(captions).map(([key,label]) => `<button type="button" class="nav-item" data-nav="${key}"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="${icons[key]}"/></svg><span>${label}</span></button>`).join('');

  function activate(key) {
    active = key;
    navigationRequest++;
    document.querySelectorAll('#bottomNav [data-nav]').forEach(button => {
      const current = button.dataset.nav === key;
      button.classList.toggle('active', current);
      if(current) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');
    });
    // A subsequent refresh must not replace Perfil/Más with a previously opened record.
    if(typeof selected !== 'undefined') selected = null;
    if(typeof selectedId !== 'undefined') selectedId = null;
    if(reception) window.closeQueue?.(); else window.closeList?.();
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
  const identityStore = document.createElement('div');
  identityStore.hidden = true;
  identityStore.id = 'workspaceIdentityControls';
  document.body.append(identityStore);
  for(const id of ['user','role']) if($(id)) identityStore.append($(id));
  const brand = header.querySelector('.brand');
  brand.querySelector('strong').textContent = 'TRITON WMS';
  brand.querySelector('span').remove();
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

  window.showMore = () => {
    activate('more');
    root.innerHTML='<section class="card workspace-tools"><h1>Más opciones</h1><p>Herramientas de '+(reception?'Recepción':'Despacho')+'.</p><div id="commonTools" class="tools-grid"></div></section>';
    function action(target,label,description,callback){
      const button=document.createElement('button');button.type='button';button.className='tool-link';
      button.innerHTML=`<strong>${esc(label)}</strong><span>${esc(description)}</span>`;
      button.onclick=callback;target.append(button);
    }
    const common=$('commonTools');
    action(common,'Actualizar','Consultar la cola con los filtros actuales',async()=>{
      await (reception?window.loadReceptions():window.loadOrders());window.goHome();
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
      root.innerHTML=`<section class="card"><h1>Perfil</h1><p>Datos de tu cuenta y asignación operativa.</p><dl class="profile-fields">${fields.map(([label,value])=>`<div><dt>${esc(label)}</dt><dd>${esc(value||'No registrado')}</dd></div>`).join('')}</dl></section>`;
    }catch(error){if(requestId===navigationRequest)root.innerHTML=`<section class="card"><h1>Perfil</h1><p role="alert">${esc(error.message)}</p></section>`;}
  };
  const originalHome = window.renderHomeDashboard;
  window.renderHomeDashboard = () => {
    activate('home');originalHome();
    const note=document.createElement('p');note.className='section-note';
    note.textContent=`Vista de ${reception?'hasta 10 BL':'hasta 20 OV'} según tus filtros. Los indicadores generales se consultan en Más → Reportes.`;
    root.firstElementChild?.append(note);
    const button=document.createElement('button');button.type='button';button.className='primary';button.textContent='Ver lista de '+(reception?'BL':'OV');
    button.onclick=()=>reception?window.openQueue():window.openList();root.firstElementChild?.append(button);
  };
  window.goHome=()=>window.renderHomeDashboard();
  async function loadGlobalWorkSummary(){
    const host=root.querySelector('.work-global-summary');if(!host)return;
    try{
      const response=await fetch('/api/work-summary?module='+(reception?'reception':'dispatch'));
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
  window.showMyWork=()=>{activate('work');originalWork();const card=root.querySelector('section.card');if(card){const host=document.createElement('section');host.className='work-global-summary';host.innerHTML='<p class="empty">Consultando todos los estados…</p>';const table=card.querySelector('.tablewrap');card.insertBefore(host,table||null);}enhanceSortableWorkTable();loadGlobalWorkSummary();};
  const originalDetail=window.loadDetail;
  window.loadDetail=async function(...args){window.setActiveNav('work');navigationRequest++;return originalDetail.apply(this,args);};
  nav.addEventListener('click', event=>{
    const key=event.target.closest('[data-nav]')?.dataset.nav;
    if(key==='home')window.goHome();if(key==='profile')window.showAccount();if(key==='work')window.showMyWork();if(key==='more')window.showMore();
  });
  // Refresh the currently visible dashboard, never overwrite another module.
  for(const name of [reception?'loadReceptions':'loadOrders']){
    const original=window[name];
    window[name]=async function(...args){const result=await original.apply(this,args);refreshRole();if(active==='home')window.renderHomeDashboard();return result;};
  }
  window.dispatchEvent(new Event('resize'));
})();
