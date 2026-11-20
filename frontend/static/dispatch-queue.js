/* This queue orders work only; existing attention actions own all state changes. */
window.WmsDispatchQueue = (() => {
  const byId=id=>document.getElementById(id),filter=byId('customerTypeFilter');
  if(!filter)return {active:()=>false,render:()=>false};
  let data=null,busy=false,error='',scope='current',page=1,sequence=0,lastQuery='';
  const active=()=>window.WmsDispatchKind==='OV'&&['internal','regular'].includes(filter.value);
  const stamp=value=>String(value||'').replace(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}:\d{2}).*$/,'$3/$2/$1 $4')||'Sin fecha/hora';
  const label=document.createElement('label');label.className='dispatch-client-choice';label.textContent='Cliente';
  const advanced=filter.closest('.operation-filters')?.querySelector('.operation-more-filters');
  if(advanced)advanced.before(label);else filter.before(label);
  label.append(filter);filter.value='internal';
  function layout(){
    const sts=window.WmsDispatchKind==='STS';label.hidden=sts;
    const all=filter.querySelector('[value=""]');if(all)all.hidden=byId('role').value!=='ADMINISTRADOR';
    if(!sts&&all?.hidden&&!filter.value)filter.value='internal';
    const advanced=document.querySelector('.operation-more-filters'),origin=document.querySelector('.workspace-origin-filter');
    if(advanced)advanced.hidden=active();if(origin)origin.hidden=active();
  }
  function render(){
    layout();if(!active())return false;
    const internal=filter.value==='internal',root=byId('list');
    const period=!data?'':scope==='carryover'?'<p>Pendientes de cortes anteriores.</p>':scope==='review'?'<p>Revisa la fecha y hora originales de creación en el Excel.</p>':`<p>Corte: <strong>${esc(stamp(data.cutoff_at))}</strong> · Lima</p><p>Entrega: ${esc(stamp(data.delivery_start))} a ${esc(data.delivery_end.slice(11,16))}${data.overdue?' · <strong>Fuera del horario objetivo</strong>':''}</p>`;
    root.innerHTML=`<section id="internalDispatchQueue" class="dispatch-work-queue"><h2>${internal?'Picking · cliente interno':'Picking · cliente regular'}</h2>${internal&&data?`${period}<div class="dispatch-cutoff-choices" role="group" aria-label="Pendientes internos">${[['current','Del corte'],['carryover','Rezagadas'],...(data.counts.review?[['review','Revisar fecha/hora']]:[])].map(([key,name])=>`<button type="button" data-cutoff-scope="${key}" aria-pressed="${scope===key}" ${busy?'disabled':''}>${name} · ${data.counts[key]}</button>`).join('')}</div>`:''}${busy?'<p role="status">Cargando pendientes…</p>':error?`<p role="alert">${esc(error)}</p><button type="button" data-queue-retry>Reintentar</button>`:!internal&&!byId('search').value.trim()?'<p>Busca la OV para abrir su atención.</p>':`<p role="status">${data?.total||0} OV${data?.total===1?'':'s'} ${internal?(scope==='carryover'?'rezagadas':scope==='review'?'sin fecha/hora válida':'pendientes del corte'):'encontradas'}</p>${(data?.items||[]).map(item=>`<button type="button" class="dispatch-queue-order" data-open-queue-order="${esc(item.sap_ov)}"><strong>${esc(item.sap_ov)}</strong>${internal?'':`<span>${esc(item.customer_name)}</span>`}${!item.source_present?'<span>Ausente del último corte SAP</span>':''}<span>${esc(stamp(item.source_order_date))}</span><span class="badge ${cls(item.active_status)}">${esc(item.active_status)}</span></button>`).join('')}${data?.total?`<nav class="queue-pagination" aria-label="Páginas de pendientes"><button type="button" data-queue-previous ${data.page<=1?'disabled':''}>← Anterior</button><span>Página ${data.page} de ${Math.ceil(data.total/data.page_size)}</span><button type="button" data-queue-next ${data.page*data.page_size>=data.total?'disabled':''}>Siguiente →</button></nav>`:'<p>No hay pendientes para esta selección.</p>'}`}</section>`;
    root.querySelectorAll('[data-cutoff-scope]').forEach(button=>button.onclick=()=>{scope=button.dataset.cutoffScope;page=1;window.loadOrders();});
    root.querySelectorAll('[data-open-queue-order]').forEach(button=>button.onclick=()=>window.loadDetail(button.dataset.openQueueOrder));
    root.querySelector('[data-queue-previous]')?.addEventListener('click',()=>{page--;window.loadOrders();});
    root.querySelector('[data-queue-next]')?.addEventListener('click',()=>{page++;window.loadOrders();});
    root.querySelector('[data-queue-retry]')?.addEventListener('click',()=>window.loadOrders());
    return true;
  }
  const previousLoad=window.loadOrders;
  window.loadOrders=async function(...args){
    layout();const request=++sequence;
    if(!active()){data=null;busy=false;return previousLoad.apply(this,args);}
    orderRequest++;
    const search=byId('search').value.trim(),type=filter.value,key=type+'|'+scope+'|'+search;
    if(key!==lastQuery)page=1;lastQuery=key;busy=true;error='';window.renderList();
    try{
      const query=new URLSearchParams({customer_type:type,scope,search,page:String(page)});
      const response=await apiFetch('/api/dispatch/queue?'+query),result=await response.json();
      if(request!==sequence||!active())return [];
      if(!response.ok)throw Error(result.error||'No se pudo consultar la cola.');
      data=result;page=data.page;orders=data.items;busy=false;window.renderList();
      if(selected)await window.loadDetail(selected);
      window.refreshDailyStatus?.();return orders;
    }catch(failure){if(request===sequence){data=null;orders=[];busy=false;error=failure.message||'Sin conexión. Intenta nuevamente.';window.renderList();}return [];}
  };
  filter.addEventListener('change',()=>{page=1;scope='current';window.loadOrders();});
  setInterval(()=>{
    if(document.visibilityState==='visible'&&active()&&!selected&&!document.querySelector('.operation-filters')?.hidden&&!busy)window.loadOrders();
  },60000);
  queueMicrotask(()=>window.loadOrders());
  return {active,render};
})();
