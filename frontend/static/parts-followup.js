/* Consultation only: operational commands remain in their existing workflow. */
(() => {
 'use strict';
 const $=id=>document.getElementById(id),form=$('followupFilters');
 const states={RECEPCION:'Zona de recepción',ALMACEN:'Trabajo en almacén',COSTEO:'Costeo',DISPONIBLE:'Disponible'};
 const stageNames={PROGRAMADO:'Por llegar',ARRIBADO:'Zona de recepción','REVISION SISTEMA':'Trabajo en almacén',EM:'Trabajo en almacén',UBICACION:'Trabajo en almacén',VALIDACION:'Trabajo en almacén','SOLICITUD TRANSFERENCIA':'Costeo',CERRADO:'Finalizada'};
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const day=value=>/^\d{4}-\d{2}-\d{2}$/.test(value||'')?value.split('-').reverse().join('/'):'—';
 let offset=0,sequence=0,controller,timer,last=null;
 function kpis(summary=null){
  $('followupKpis').innerHTML=Object.entries(states).map(([key,label])=>`<button type="button" class="kpi ${key}" data-state="${key}" aria-pressed="${$('followupState').value===key}" ${summary?'':'disabled'}><span>${label}</span><strong>${Number.isInteger(summary?.[key])?summary[key].toLocaleString('es-PE'):'—'}</strong></button>`).join('');
 }
 function render(data){
  if(!data||!Array.isArray(data.items)||!Number.isInteger(data.total)||!data.summary)throw new Error('No se pudo interpretar el seguimiento');
  kpis(data.summary);last=data;
  $('followupStatus').textContent=`${data.total.toLocaleString('es-PE')} BL con llegada registrada`;
  $('followupCut').textContent=data.generated_at?`Consulta: ${data.generated_at.replace('T',' ')}`:'';
  if(!data.items.length){$('followupResults').innerHTML='<p class="empty">No hay BL con estos filtros.</p>';return;}
  const fields=[['Llegada','arrival_date'],['Inicio trabajo','work_date'],['EM','em_date'],['Costeo','costing_date'],['Disponible','available_date']];
  const rows=data.items.map(item=>{
   if(!states[item.state]||!Array.isArray(item.deliveries)||!Array.isArray(item.truck_guides))throw new Error('Respuesta de seguimiento no válida');
   const deliveries=item.deliveries.map(d=>`<div class="delivery"><strong>Entrega ${esc(d.sequence||'—')}</strong><p>${esc(d.truck||'Sin camión registrado')}</p><p>Llegada: ${day(d.arrival_date)} · ${Number(d.packages||0)} bultos</p><p>${esc(stageNames[d.stage]||'Por revisar')}${d.costing_date?' · Costeo: '+day(d.costing_date):''}</p></div>`).join('');
   return `<tr><td class="bl-cell" data-label="BL"><details><summary>${esc(item.bl_awb)}</summary>${deliveries}${item.em_dates?.length>1?'<p class="secondary">Fechas EM: '+item.em_dates.map(day).join(', ')+'</p>':''}</details>${item.delivery_count>1?`<span class="secondary">${Number(item.delivery_count)} entregas · ${Number(item.costed_deliveries)} costeadas</span>`:''}${item.pending_delivery?'<span class="secondary">Saldo de la BL pendiente</span>':''}</td>
    <td data-label="Estado"><span class="state-tag ${item.state}">${esc(states[item.state])}</span></td>
    <td data-label="Camión">${item.truck_guides.length?item.truck_guides.map(esc).join('<br>'):'Sin camión registrado'}</td>
    ${fields.map(([label,key])=>`<td data-label="${label}">${day(item[key])}</td>`).join('')}</tr>`;
  }).join('');
  $('followupResults').innerHTML=`<div class="tracking-grid"><table><thead><tr><th>BL</th><th>Estado</th><th>Camión</th>${fields.map(([label])=>'<th>'+label+'</th>').join('')}</tr></thead><tbody>${rows}</tbody></table></div>`;
 }
 async function load(reset=false){
  if(reset)offset=0;
  controller?.abort();controller=new AbortController();const signal=controller.signal,revision=++sequence;
  const params=new URLSearchParams(new FormData(form));params.set('limit','50');params.set('offset',String(offset));
  $('followupResults').setAttribute('aria-busy','true');$('followupResults').replaceChildren();$('followupError').hidden=true;
  $('followupStatus').textContent='Consultando seguimiento…';$('followupCut').textContent='';kpis();
  $('refreshFollowup').disabled=true;$('followupPrevious').disabled=true;$('followupNext').disabled=true;$('followupPage').textContent='';
  try{
   const response=await fetch('/api/parts-followup?'+params,{signal,cache:'no-store'});
   if(revision!==sequence)return;
   if(!(response.headers.get('Content-Type')||'').includes('application/json'))throw new Error('El servidor no respondió correctamente');
   const data=await response.json();if(revision!==sequence)return;
   if(!response.ok)throw new Error(data.error||'No se pudo consultar el seguimiento');
   render(data);$('followupPrevious').disabled=offset===0;$('followupNext').disabled=!data.has_more;
   $('followupPage').textContent=data.total?`${offset+1}–${Math.min(offset+data.items.length,data.total)} de ${data.total}`:'0 BL';
  }catch(error){
   if(revision!==sequence||error.name==='AbortError')return;
   last=null;$('followupResults').replaceChildren();kpis();$('followupStatus').textContent='Consulta no disponible';
   $('followupError').textContent=error.message;$('followupError').hidden=false;
  }finally{if(revision===sequence){$('followupResults').setAttribute('aria-busy','false');$('refreshFollowup').disabled=false;}}
 }
 form.addEventListener('submit',event=>{event.preventDefault();clearTimeout(timer);if(form.reportValidity())load(true);});
 form.addEventListener('change',()=>{clearTimeout(timer);if(form.reportValidity())load(true);});
 $('followupSearch').addEventListener('input',()=>{sequence++;controller?.abort();clearTimeout(timer);timer=setTimeout(()=>load(true),350);});
 form.addEventListener('reset',()=>{clearTimeout(timer);setTimeout(()=>load(true),0);});
 $('refreshFollowup').onclick=()=>{clearTimeout(timer);if(form.reportValidity())load();};
 $('followupPrevious').onclick=()=>{offset=Math.max(0,offset-50);load();};
 $('followupNext').onclick=()=>{if(last?.has_more){offset+=50;load();}};
 $('followupKpis').onclick=event=>{const button=event.target.closest('button[data-state]');if(!button||button.disabled)return;
  $('followupState').value=$('followupState').value===button.dataset.state?'ALL':button.dataset.state;load(true);};
 async function start(){
  try{
   const response=await fetch('/api/me',{cache:'no-store'});const me=await response.json();
   if(!response.ok)throw new Error(me.error||'Inicia sesión para consultar');
   window.installSessionControls?.(me);if(me.must_change_password)return;
   if(!['ADMINISTRADOR','CONSULTA_REPUESTOS'].includes(me.role))throw new Error('No tienes acceso al seguimiento de Repuestos');
   $('backWms').hidden=me.role!=='ADMINISTRADOR';await load();
  }catch(error){$('followupStatus').textContent='Consulta no disponible';$('followupError').textContent=error.message;$('followupError').hidden=false;}
 }
 start();
})();
