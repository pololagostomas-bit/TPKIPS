/* One comparative grid on phone and desktop; edits still belong to the BL workflow. */
(() => {
  'use strict';
  const columns=[['BL','bl_awb'],['Camion',''],['SKUs','sku_count'],['Unidades','total_units'],
    ['Etapa','app_status'],['Transporte',''],['Inicio','report_started_at'],['Responsables',''],
    ['Fin','report_closed_at'],['Tiempo / SLA',''],['Restante','remaining_hours'],['SLA','']];
  const widths=[190,180,88,100,200,120,190,210,190,150,130,120];
  const layout=widths.map(width=>({width,visible:true}));
  function render(report){
    const option=(value,label)=>`<option value="${esc(value)}">${esc(label)}</option>`;
    const stages=['PROGRAMADO','ARRIBADO','REVISION SISTEMA','EM','UBICACION','VALIDACION','SOLICITUD TRANSFERENCIA','CERRADO'];
    const select=(label,id,options)=>`<label>${label}<select id="${id}" onchange="applyReportFilters()">${options.map(([value,text])=>option(value,text)).join('')}</select></label>`;
    const form=`<div class="report-filters">
      <label>Buscar BL o camion<input id="reportSearch" type="search" maxlength="100" autocomplete="off" oninput="WmsReceptionReport.search()" onkeydown="if(event.key==='Enter'){event.preventDefault();applyReportFilters()}"></label>
      ${select('Estado','reportState',[['ALL','Todos'],['OPEN','Solo abiertas'],...stages.map(value=>[value,stateLabel(value)])])}
      </div><details class="report-more-filters"><summary>Mas filtros</summary><div class="report-filters">
      <label>Desde<input id="reportFrom" type="date" onchange="applyReportFilters()"></label>
      <label>Hasta<input id="reportTo" type="date" onchange="applyReportFilters()"></label>
      ${select('Llegada','reportArrival',[['ALL','Todas'],['ARRIBADO','Con llegada'],['PROGRAMADO','Sin llegada']])}
      ${select('SLA','reportSla',['ALL','VERDE','AMARILLO','ROJO','SIN INICIO'].map(value=>[value,value==='ALL'?'Todos':value]))}
      ${select('Transporte','reportTransport',['ALL','AEREO','MARITIMO','COURIER','TERRESTRE','SIN DEFINIR'].map(value=>[value,value==='ALL'?'Todos':value]))}
      ${select('Ordenar por','reportSort',[['default','Fecha programada'],...columns.filter(([,key])=>key).map(([label,key])=>[key,label])])}
      ${select('Orden','reportDirection',[['asc','Ascendente'],['desc','Descendente']])}</div></details>`;
    const summary=report.summary||{};
    const partials=report.filtered_summary?.partial_bl;
    const semaphore=report.filtered_summary?.semaforizacion||{};
    const slaKpi=(label,status)=>`<button type="button" id="reportSla${status}" class="report-kpi report-sla-kpi" data-report-kpi="${label}" data-report-sla="${status}" aria-pressed="false" onclick="WmsReceptionReport.toggleSla('${status}')" title="Filtrar ${label.toLowerCase()}; vuelve a pulsar para quitar el filtro"><span class="label">${label}</span><strong class="${slaClass(status)}">${Number.isInteger(semaphore[status])?semaphore[status].toLocaleString('es-PE'):'—'}</strong><small class="report-sla-note">Ver lista · Según filtros</small></button>`;
    const partialKpi=`<div class="report-kpi report-partial-kpi" data-report-kpi="BL parciales"><span class="label">BL parciales</span><strong>${Number.isInteger(partials)?partials.toLocaleString('es-PE'):'—'}</strong><small class="report-partial-note">2 o más camiones · Según filtros</small></div>`;
    const rows=report.items.map(item=>{
      const elapsed=item.elapsed_hours===null?'—':`${formatDuration(item.elapsed_hours)} / ${formatDuration(item.sla_hours)}`;
      const remaining=item.remaining_hours===null?'—':`${item.remaining_hours<0?'−':''}${formatDuration(Math.abs(item.remaining_hours))}`;
      const cells=[`<button type="button" class="report-open" onclick="openReportedShipment(${Number(item.id)})">${esc(item.bl_awb)}</button>`,
        esc(item.truck_guides||'—'),Number(item.sku_count||0).toLocaleString('es-PE'),Number(item.total_units||0).toLocaleString('es-PE'),
        esc(stateLabel(item.app_status)),esc(item.transport_type||'—'),esc(item.report_started_at||'—'),
        esc([item.current_assistant,item.current_auxiliary].filter(Boolean).join(' / ')||'Sin asignar'),
        esc(item.report_closed_at||'—'),elapsed,remaining,esc(item.sla_status)];
      return `<tr class="report-item-row" data-state="${esc(item.app_status)}">${cells.map((value,index)=>`<td data-column="${index}" class="${index===11?slaClass(item.sla_status):''}">${value}</td>`).join('')}</tr>`;
    }).join('')||'<tr><td colspan="12">No hay BL con estos filtros.</td></tr>';
    const cut=report.snapshot_at?new Date(report.snapshot_at*1000).toLocaleString('es-PE',{timeZone:'America/Lima'}):report.generated_at;
    return `<p class="report-cut">Corte: ${esc(cut)}</p>
      <div class="report-summary report-main-summary">${slaKpi('BL rojas','ROJO')}${slaKpi('BL amarillas','AMARILLO')}${slaKpi('BL verdes','VERDE')}${partialKpi}${reportKpi('En trabajo',summary.total_pendientes||0)}${reportKpi('Por llegar',summary.awaiting_arrival||0)}</div>
      ${form}<div class="report-grid-toolbar"><span id="reportFilteredCount" role="status"></span>
      <button type="button" class="primary" id="reportExport" onclick="WmsReceptionReport.download('indicators')" title="Descargar Excel de indicadores"><span aria-hidden="true">&#8595;</span> Descargar indicadores</button>
      <details class="report-columns"><summary>Columnas</summary><div>
        <label>Columna<select id="reportColumn">${columns.map(([label],index)=>option(index,label)).join('')}</select></label>
        <label>Ancho (px)<input type="number" id="reportColumnWidth" min="88" max="600" step="10"></label>
        <label class="report-column-visible"><input id="reportColumnVisible" type="checkbox">Visible</label>
        <button type="button" class="ghost" id="reportColumnReset">Restablecer columnas</button></div></details></div>
      <p id="reportExportStatus" role="status" aria-live="polite"></p>
      <div class="report-grid" role="region" aria-label="Reporte de BL" tabindex="0"><table class="report-table"><colgroup>${columns.map((_,index)=>`<col data-column="${index}">`).join('')}</colgroup>
      <thead><tr>${columns.map(([label],index)=>`<th scope="col" data-column="${index}">${label}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>
      <details class="report-general-totals"><summary>Totales generales</summary><div class="report-summary">${reportKpi('BL en la base',summary.total_bl||0)}${reportKpi('Cerradas',report.by_status?.CERRADO||0)}</div></details>`;
  }
  function configure(content){
    content.querySelectorAll('[data-report-sla]').forEach(button=>button.setAttribute('aria-pressed',
      String(button.dataset.reportSla===document.getElementById('reportSla').value)));
    const field=document.getElementById('reportColumn'),width=document.getElementById('reportColumnWidth'),visible=document.getElementById('reportColumnVisible');
    const apply=()=>{
      layout.forEach((value,index)=>content.querySelectorAll(`[data-column="${index}"]`).forEach(node=>{
        node.hidden=!value.visible;if(node.tagName==='COL')node.style.width=value.width+'px';
      }));
      content.querySelector('.report-grid table').style.width=layout.reduce((sum,value)=>sum+(value.visible?value.width:0),0)+'px';
    };
    const display=()=>{width.value=layout[field.value].width;visible.checked=layout[field.value].visible;visible.disabled=field.value==='0'};
    field.onchange=display;
    width.onchange=()=>{if(!width.checkValidity()){width.reportValidity();return}layout[field.value].width=Number(width.value);apply()};
    visible.onchange=()=>{layout[field.value].visible=visible.checked;apply()};
    document.getElementById('reportColumnReset').onclick=()=>{widths.forEach((value,index)=>Object.assign(layout[index],{width:value,visible:true}));display();apply()};
    display();apply();
  }
  window.WmsReceptionReportView={render,configure};
})();
