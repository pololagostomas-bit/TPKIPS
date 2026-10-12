/* A bounded report page with cancellable reads; totals still cover the full base. */
(() => {
  'use strict';
  const modal = document.getElementById('reportModal');
  const content = document.getElementById('reportContent');
  if (!modal || !content) return;
  const filters = {from:'',to:'',arrival:'ALL',sla:'ALL'};
  let offset=0, controller, requestId=0;
  const ids = {from:'reportFrom',to:'reportTo',arrival:'reportArrival',sla:'reportSla'};
  const history = `<section class="card"><div class="section-title"><h2>Historial administrativo y tiempos</h2></div><div class="actions"><button class="dark" onclick="loadHistoryReport()">Ver historial</button><button class="primary" onclick="downloadHistoryExcel()">Exportar Excel</button></div><div id="historyReportContent"></div></section>`;
  async function load() {
    const id=++requestId;
    controller?.abort();controller=new AbortController();
    content.setAttribute('aria-busy','true');
    for(const name of ['reportPrevious','reportNext']){const button=document.getElementById(name);if(button)button.disabled=true}
    try {
      const query=new URLSearchParams({...filters,limit:'50',offset:String(offset)});
      const response=await api('/api/receptions/report?'+query,{signal:controller.signal});
      const data=await response.json();
      if(!response.ok)throw Error(data.error||'No se pudo cargar la reporteria');
      if(id!==requestId || modal.hidden)return;
      if(data.offset && !data.items.length && data.total){offset=0;return await load()}
      const focus=document.activeElement?.id;
      content.innerHTML=reportHtml(data)+`<footer class="report-pagination"><span>${data.total?data.offset+1:0}-${Math.min(data.total,data.offset+data.items.length)} de ${data.total}</span><div><button class="ghost" type="button" id="reportPrevious" title="Pagina anterior" aria-label="Pagina anterior" ${data.offset===0?'disabled':''}>&larr;</button><button class="ghost" type="button" id="reportNext" title="Pagina siguiente" aria-label="Pagina siguiente" ${!data.has_more?'disabled':''}>&rarr;</button></div></footer>`+history;
      for(const [key,field] of Object.entries(ids))document.getElementById(field).value=filters[key];
      document.getElementById('reportFilteredCount').textContent=`${data.total} resultado(s)`;
      const count=content.querySelector('[data-report-kpi="BL consultadas"] strong');if(count)count.textContent=data.total;
      document.getElementById('reportPrevious').onclick=()=>{offset=Math.max(0,offset-data.limit);load()};
      document.getElementById('reportNext').onclick=()=>{offset+=data.limit;load()};
      if(focus && content.querySelector('#'+focus))document.getElementById(focus).focus({preventScroll:true});
    } catch(error) {
      if(error.name==='AbortError' || id!==requestId || modal.hidden)return;
      let notice=document.getElementById('reportLoadError');
      if(!notice){notice=document.createElement('p');notice.id='reportLoadError';notice.className='notice error';notice.setAttribute('role','alert');content.prepend(notice)}
      notice.textContent=error.message;
      if(!document.getElementById('reportRetry')){const button=document.createElement('button');button.id='reportRetry';button.className='ghost';button.type='button';button.textContent='Reintentar';button.onclick=load;notice.append(button)}
    } finally {
      if(id===requestId)content.setAttribute('aria-busy','false');
    }
  }
  window.WmsReceptionReport={
    open:async()=>{
      if(role()!=='ADMINISTRADOR')return;
      offset=0;Object.assign(filters,{from:'',to:'',arrival:'ALL',sla:'ALL'});
      modal.hidden=false;content.innerHTML='<div class="empty" role="status">Cargando reporteria...</div>';
      await load();
    },
    close:()=>{++requestId;controller?.abort();modal.hidden=true;content.setAttribute('aria-busy','false')},
    filter:()=>{
      for(const [key,field] of Object.entries(ids))filters[key]=document.getElementById(field)?.value|| (key==='from'||key==='to'?'':'ALL');
      offset=0;return load();
    }
  };
})();
