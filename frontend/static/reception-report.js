/* A bounded report page with cancellable reads; totals still cover the full base. */
(() => {
  'use strict';
  const modal = document.getElementById('reportModal');
  const content = document.getElementById('reportContent');
  if (!modal || !content) return;
  const defaults = {from:'',to:'',arrival:'ALL',sla:'ALL',state:'ALL',transport:'ALL',search:'',sort:'default',direction:'asc'};
  const filters = {...defaults};
  let offset=0, controller, requestId=0, searchTimer, downloadController, downloadKind, downloadProgress='',currentTotal=0;
  const ids = {from:'reportFrom',to:'reportTo',arrival:'reportArrival',sla:'reportSla',state:'reportState',transport:'reportTransport',search:'reportSearch',sort:'reportSort',direction:'reportDirection'};
  const history = `<section><div class="section-title"><h2>Historial administrativo y tiempos</h2></div><div class="actions"><button class="ghost report-history-preview" onclick="loadHistoryReport()">Ver historial completo</button><button id="historyExport" class="ghost" onclick="downloadHistoryExcel()">Exportar historial completo</button></div><p id="historyExportStatus" role="status" aria-live="polite"></p><div id="historyReportContent"></div></section>`;
  let downloading = false;
  function exportControls(){
    for(const id of ['reportExport','historyExport']){
      const button=document.getElementById(id);
      if(button)button.disabled=downloading||content.dataset.stale==='true'||(id==='reportExport'&&currentTotal===0);
    }
    const status=document.getElementById(downloadKind==='indicators'?'reportExportStatus':'historyExportStatus');
    if(status&&downloadProgress)status.textContent=downloadProgress;
  }
  function readFilters(){
    for(const [key,field] of Object.entries(ids))filters[key]=document.getElementById(field)?.value??defaults[key];
    offset=0;
  }
  async function json(response){
    if(response.status===401)throw Error('La sesion vencio. Inicia sesion nuevamente.');
    if(response.status===403)throw Error('No tienes permiso para consultar este reporte.');
    if(!response.headers.get('content-type')?.includes('application/json'))throw Error('El servidor no devolvio un reporte valido. Intenta nuevamente.');
    try{return await response.json()}catch{throw Error('El servidor no devolvio un reporte valido. Intenta nuevamente.')}
  }
  const wait = signal => new Promise((resolve,reject) => {
    if(signal?.aborted){reject(new DOMException('Cancelado','AbortError'));return}
    const abort=()=>{clearTimeout(timer);reject(new DOMException('Cancelado','AbortError'))};
    const timer=setTimeout(()=>{signal?.removeEventListener('abort',abort);resolve()},1500);
    signal?.addEventListener('abort',abort,{once:true});
  });
  async function request(url, {signal,onProgress}={}) {
    let response=await api(url,{signal});
    if(response.status!==202)return response;
    const job=await json(response);
    if(!/^[a-f0-9]{32}$/.test(job.id))throw Error('No se pudo iniciar el reporte');
    const statusUrl='/api/report-jobs/'+job.id;
    const resultUrl=statusUrl+'/result'+(url.includes('?')?'?'+url.split('?')[1]:'');
    let status=job;
    const deadline=Date.now()+12*60*1000;
    while(status.status!=='READY'){
      if(Date.now()>deadline)throw Error('El reporte sigue pendiente. Puedes volver a consultar su estado.');
      onProgress?.(status.phase||'Preparando reporte');
      await wait(signal);
      response=await api(statusUrl,{signal});
      status=await json(response);
      if(!response.ok||status.status==='FAILED')throw Error(status.error||'No se pudo preparar el reporte');
    }
    return api(resultUrl,{signal});
  }
  async function load() {
    const id=++requestId;
    controller?.abort();controller=new AbortController();
    content.setAttribute('aria-busy','true');
    content.dataset.stale='true';
    exportControls();
    content.querySelector('.report-grid')?.setAttribute('inert','');
    let progress=document.getElementById('reportProgress');
    if(!progress){progress=document.createElement('p');progress.id='reportProgress';progress.setAttribute('role','status');content.prepend(progress)}
    progress.textContent='Consultando reporte...';
    for(const name of ['reportPrevious','reportNext']){const button=document.getElementById(name);if(button)button.disabled=true}
    try {
      const query=new URLSearchParams({...filters,limit:'50',offset:String(offset)});
      const response=await request('/api/receptions/report?'+query,{signal:controller.signal,
        onProgress:phase=>{if(id===requestId)progress.textContent=phase+'...'}});
      const data=await json(response);
      if(!response.ok)throw Error(data.error||'No se pudo cargar la reporteria');
      if(id!==requestId || modal.hidden)return;
      if(data.offset && !data.items.length && data.total){offset=0;return await load()}
      const focus=document.activeElement?.id;
      const selection=focus==='reportSearch'?[document.activeElement.selectionStart,document.activeElement.selectionEnd]:null;
      content.innerHTML=WmsReceptionReportView.render(data)+`<footer class="report-pagination"><span>${data.total?data.offset+1:0}-${Math.min(data.total,data.offset+data.items.length)} de ${data.total}</span><div><button class="ghost" type="button" id="reportPrevious" title="Pagina anterior" aria-label="Pagina anterior" ${data.offset===0?'disabled':''}>&larr;</button><button class="ghost" type="button" id="reportNext" title="Pagina siguiente" aria-label="Pagina siguiente" ${!data.has_more?'disabled':''}>&rarr;</button></div></footer>`+history;
      delete content.dataset.stale;
      currentTotal=data.total;
      for(const [key,field] of Object.entries(ids))document.getElementById(field).value=filters[key];
      document.getElementById('reportFilteredCount').textContent=`${data.total} resultado(s)`;
      WmsReceptionReportView.configure(content);
      exportControls();
      const count=content.querySelector('[data-report-kpi="BL consultadas"] strong');if(count)count.textContent=data.total;
      document.getElementById('reportPrevious').onclick=()=>{offset=Math.max(0,offset-data.limit);load()};
      document.getElementById('reportNext').onclick=()=>{offset+=data.limit;load()};
      if(focus && content.querySelector('#'+focus))document.getElementById(focus).focus({preventScroll:true});
      if(selection)document.getElementById('reportSearch').setSelectionRange(...selection);
    } catch(error) {
      if(error.name==='AbortError' || id!==requestId || modal.hidden)return;
      content.innerHTML='';
      const notice=document.createElement('p');notice.id='reportLoadError';notice.className='notice error';notice.setAttribute('role','alert');content.append(notice);
      notice.textContent=error.message;
      const button=document.createElement('button');button.id='reportRetry';button.className='ghost';button.type='button';button.textContent='Reintentar';button.onclick=load;notice.append(button);
    } finally {
      if(id===requestId)content.setAttribute('aria-busy','false');
    }
  }
  window.WmsReceptionReport={
    open:async()=>{
      if(role()!=='ADMINISTRADOR')return;
      clearTimeout(searchTimer);
      if(!downloading){downloadProgress='';downloadKind=null}
      offset=0;Object.assign(filters,defaults);
      modal.hidden=false;content.innerHTML='<div class="empty" role="status">Cargando reporteria...</div>';
      await load();
    },
    close:()=>{++requestId;clearTimeout(searchTimer);controller?.abort();downloadController?.abort();modal.hidden=true;content.setAttribute('aria-busy','false')},
    filter:()=>{
      clearTimeout(searchTimer);readFilters();return load();
    },
    search:()=>{
      readFilters();++requestId;controller?.abort();clearTimeout(searchTimer);
      content.dataset.stale='true';content.querySelector('.report-grid')?.setAttribute('inert','');exportControls();
      searchTimer=setTimeout(load,350);
    },
    request,
    download:async(kind='history')=>{
      if(downloading)return;
      if(kind==='indicators'&&(content.dataset.stale==='true'||!currentTotal))return;
      downloading=true;
      downloadKind=kind;downloadController=new AbortController();
      const signal=downloadController.signal;
      const update=text=>{downloadProgress=text;exportControls()};
      const query=new URLSearchParams({...filters});
      update('Preparando Excel en segundo plano...');
      try{
        const response=await request(kind==='indicators'?'/api/receptions/report/export?'+query:'/api/receptions/history/export',{signal,onProgress:update});
        if(!response.ok){const data=await json(response);throw Error(data.error||'No se pudo preparar el Excel')}
        if(!response.headers.get('content-type')?.includes('spreadsheetml.sheet'))throw Error('El archivo no esta disponible');
        const blob=await response.blob();if(!blob.size)throw Error('El archivo esta vacio. Solicitalo nuevamente.');
        if(signal.aborted)throw new DOMException('Cancelado','AbortError');
        const url=URL.createObjectURL(blob);
        const link=document.createElement('a');link.href=url;link.download=kind==='indicators'?'triton_recepcion_indicadores.xlsx':'triton_recepcion_historial.xlsx';
        document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
        update('Excel listo. Descarga iniciada.');notify('Descarga del reporte iniciada','success');
      }catch(error){if(error.name!=='AbortError'){update(error.message);notify(error.message,'error')}}
      finally{downloading=false;downloadController=null;exportControls()}
    }
  };
})();
