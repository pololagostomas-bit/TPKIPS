/* Carga única de los cortes para ambos módulos; no requiere diálogos prompt. */
(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const role = () => el('role')?.value || '';
  const headers = () => ({'X-User': el('user')?.value.trim() || 'demo.admin', 'X-Role': role()});
  let status = null;
  let importBusy = false;
  window.wmsFeatures = {advanced_lots: false};
  document.body.classList.add('stage-one');
  const style = document.createElement('link'); style.rel = 'stylesheet'; style.href = '/assets/daily-work.css'; document.head.append(style);
  const strip = document.createElement('div'); strip.className = 'data-strip'; strip.id = 'dailyStatus'; strip.setAttribute('role','status');
  document.querySelector('body>header')?.after(strip);
  const toolbar = document.querySelector('.toolbar-actions') || document.querySelector('header .actions');
  const dataButton = document.createElement('button'); dataButton.type = 'button'; dataButton.dataset.daily = '1'; dataButton.textContent = 'Cortes Excel'; dataButton.id = 'dailyDataButton'; dataButton.hidden = true;
  dataButton.addEventListener('click', () => openData());
  const stockButton = document.createElement('button'); stockButton.type = 'button'; stockButton.textContent = 'Stock y compromisos'; stockButton.id = 'dailyStockButton'; stockButton.hidden = true; stockButton.addEventListener('click', openInventory);
  toolbar?.append(stockButton, dataButton);
  const dialog = document.createElement('dialog'); dialog.className = 'daily-dialog'; dialog.id = 'dailyDialog'; dialog.setAttribute('aria-labelledby','dailyTitle'); document.body.append(dialog);
  dialog.addEventListener('cancel', event => {if (importBusy) event.preventDefault();});
  async function request(url, options={}) {
    const response = await fetch(url,{...options, headers:{...headers(),...options.headers}});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'No se pudo completar la operación');
    return data;
  }
  function date(value) {return value ? String(value).replace('T',' ').slice(0,16) : 'Sin cargar';}
  async function refreshStatus() {
    try {
      status = await request('/api/data-status'); window.wmsFeatures = status;
      document.body.classList.toggle('stage-one', !status.advanced_lots);
      strip.innerHTML = '<strong>Operación diaria · corte 16:00 · Lima</strong>' + status.sources.map(source => `<span class="data-pill ${source.status==='VIGENTE'?'':'stale'}" title="${escape(source.label)}">${escape(source.label)}: ${escape(date(source.cutoff_at))}${source.status==='ACTUALIZAR'?' · actualizar':''}</span>`).join('');
      const admin = role() === 'ADMINISTRADOR'; dataButton.hidden = !admin; stockButton.hidden = !admin;
    } catch(error) {strip.textContent = 'No se pudo consultar el corte. Verifica la conexión y pulsa Actualizar.';}
  }
  function layout(title, content) {
    dialog.innerHTML = `<header><div><span class="daily-eyebrow">TRITON WMS · Operación con Excel</span><h2 id="dailyTitle">${escape(title)}</h2></div><button type="button" id="dailyClose" aria-label="Cerrar ventana">Cerrar ×</button></header><div class="daily-body">${content}</div>`;
    el('dailyClose').onclick = () => {if (!importBusy) dialog.close();};
    if (!dialog.open) dialog.showModal();
  }
  async function openData() {
    if(role()!=='ADMINISTRADOR')return;
    await refreshStatus();
    layout('Cargar corte diario', `<p class="daily-intro">Carga cada documento una sola vez. Importaciones actualiza las BL/AWB de Recepción y los compromisos de Despacho en la misma operación.</p>
      <form id="dailyForm" class="daily-form">
       <div class="daily-field"><label for="dailySource">Documento</label><select id="dailySource"><option value="dispatch">1 · OV y stock SAP</option><option value="importation">2 · IMPORTACIÓN DE REPUESTOS</option><option value="accounting">3 · Facturas de reserva / EM</option></select></div>
       <div class="daily-field"><label for="dailyCutoff">Fecha y hora del corte (Lima)</label><input id="dailyCutoff" type="datetime-local" required value="${escape((status?.expected_cutoff||'').slice(0,16))}"></div>
       <div class="daily-help daily-wide" id="dailyHelp"></div>
       <div class="daily-field daily-wide"><label for="dailyFile">Archivo Excel .xlsx</label><input id="dailyFile" type="file" accept=".xlsx" required></div>
       <label class="daily-confirm daily-wide" id="dailyConfirmRow"><input type="checkbox" id="dailyReconcile"><span>Confirmo que el stock SAP de este corte ya incluye las entregas finalizadas hasta esa hora. Las reservas y el picking sin entregar seguirán descontándose.</span></label>
       <div class="daily-wide"><button type="submit" class="primary" id="dailySubmit">Validar y cargar</button></div>
      </form><div id="dailyResult" role="status" hidden></div><details style="margin-top:20px"><summary>Últimas cargas y responsables</summary><div class="daily-table"><table><thead><tr><th>Documento</th><th>Corte</th><th>Cargado</th><th>Responsable</th></tr></thead><tbody>${(status?.history||[]).map(row=>`<tr><td>${escape(row.filename)}</td><td>${escape(date(row.cutoff_at))}</td><td>${escape(date(row.loaded_at))}</td><td>${escape(row.username)}</td></tr>`).join('')||'<tr><td colspan="4">Aún no hay cortes registrados en esta versión.</td></tr>'}</tbody></table></div></details>`);
    function sourceHelp() {
      const source = el('dailySource').value;
      el('dailyHelp').textContent = {dispatch:'Actualiza las OVs y el saldo por NP del almacén 1. El stock repetido en varias OVs se cuenta una sola vez. Usa la fecha real de exportación.',importation:'Identifica qué NP están destinados a cada OV y sus BL/AWB. No suma existencias. Los SKU aéreos esperan que Recepción termine su validación.',accounting:'Cruza IP y BL/AWB con los códigos y fechas de FR/EM. Conserva los responsables, arribos, cantidades trabajadas e historial.'}[source];
      el('dailyConfirmRow').hidden = source !== 'dispatch';
      el('dailyReconcile').checked = false;
    }
    el('dailySource').onchange = sourceHelp; sourceHelp();
    el('dailyForm').onsubmit = upload;
  }
  async function upload(event) {
    event.preventDefault(); if(importBusy)return;
    const file=el('dailyFile').files[0]; if(!file)return;
    if(!file.name.toLowerCase().endsWith('.xlsx')) {showResult('Selecciona un archivo .xlsx.',true);return;}
    importBusy=true; el('dailySubmit').disabled=true; el('dailyClose').disabled=true;
    showResult('Validando el archivo… Conserva esta ventana abierta.');
    try {
      const result = await request('/api/daily-import',{method:'POST', headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','X-File-Name':encodeURIComponent(file.name),'X-Source-Type':el('dailySource').value,'X-Cutoff-At':el('dailyCutoff').value,'X-Reconcile-Delivered':el('dailyReconcile').checked?'1':'0'},body:file});
      let message=result.duplicate?'Este mismo corte ya estaba cargado. Se conservaron los avances.':`Corte ${date(result.cutoff_at)} cargado correctamente.`;
      if(result.orders!==undefined)message+=`\n${result.orders} OVs · ${result.lines} líneas pendientes · ${result.closed_orders_updated||0} cerradas por SAP.`;
      if(result.shipments!==undefined)message+=`\n${result.shipments} BL/AWB · ${result.ovs||0} OVs vinculadas a Importaciones.`;
      if(result.matched_records!==undefined)message+=`\n${result.matched_records} referencias FR/EM vinculadas · ${result.unmatched_count||0} sin coincidencia.`;
      if(result.stock_updated===false)message+='\nEl saldo de stock no fue modificado.';
      if(result.inventory_conflicts)message+=`\n${result.inventory_conflicts} NP tienen saldos distintos en el Excel; se usó el menor. Revisa Stock y compromisos.`;
      if(el('dailySource').value==='dispatch' && !el('dailyReconcile').checked)message+='\nSe conservaron los descuentos locales pendientes de conciliación.';
      showResult(message); await refreshStatus();
      if(location.pathname==='/reception' && typeof loadReceptions==='function') await loadReceptions();
      else if(typeof loadOrders==='function')await loadOrders();
    } catch(error){showResult(error.message || 'No hubo respuesta del servidor. Puedes repetir el mismo archivo sin duplicar registros.',true);}
    finally{importBusy=false;el('dailySubmit').disabled=false;el('dailyClose').disabled=false;}
  }
  function showResult(message,error=false){const result=el('dailyResult');result.hidden=false;result.className='daily-result'+(error?' error':'');result.textContent=message;}
  async function openInventory(){
    if(role()!=='ADMINISTRADOR')return;
    layout('Stock y compromisos',`<p class="daily-intro">Saldo del último Excel, menos reservas, consumos locales y compromisos arribados para otras OVs. Importaciones y FR/EM no generan ingresos.</p><form class="daily-search" id="inventorySearchForm"><div class="daily-field"><label for="inventorySearch">Buscar NP / SKU</label><input id="inventorySearch" placeholder="Ej. 363506-001"></div><button class="primary" type="submit">Buscar</button></form><div id="inventoryResult" role="status" aria-live="polite"></div>`);
    el('inventorySearchForm').onsubmit=event=>{event.preventDefault();loadInventory();}; await loadInventory();
  }
  async function loadInventory(){
    const target=el('inventoryResult');target.textContent='Consultando saldos…';
    try{const data=await request('/api/inventory?search='+encodeURIComponent(el('inventorySearch').value.trim()));
      target.innerHTML=`<p class="daily-muted">${data.items.length} NP visibles${data.has_more?' · Usa el buscador para ver otros NP':''}. Los compromisos por llegar se informan; los arribados se retienen para su OV.</p><div class="daily-table"><table><thead><tr><th>NP</th><th>Corte</th><th>Stock Excel</th><th>Reservado</th><th>Consumo local</th><th>Comprometido sin reservar</th><th>Libre general</th><th>Detalle por OV</th></tr></thead><tbody>${data.items.map(item=>`<tr><td><strong>${escape(item.item_code)}</strong>${item.stock_deficit?'<br><span style="color:#b13c2d">Revisar saldo / reservas</span>':''}${!item.is_current?'<br>Sin dato en último corte':''}</td><td>${escape(date(item.snapshot_at))}</td><td class="number">${item.source_total}</td><td class="number">${item.reserved_total}</td><td class="number">${item.consumed_total}</td><td class="number">${item.committed_other_qty}</td><td class="number"><strong>${item.free_qty}</strong></td><td>${Object.keys(item.commitments).length?`<details><summary>Ver ${Object.keys(item.commitments).length} OV(s)</summary>${Object.entries(item.commitments).map(([ov,c])=>`<p><b>OV ${escape(ov)}</b> · ${c.quantity} comprometidas<br>${escape(c.bls.join(', '))}<br>${c.pending_bls.length?'Pendiente Recepción':'Recepción completada'}${c.unknown_qty?'<br>Cantidad estimada según pendiente de OV':''}</p>`).join('')}</details>`:'Sin compromiso de Importaciones'}</td></tr>`).join('')||'<tr><td colspan="8">No se encontraron artículos. Carga primero OV y stock SAP.</td></tr>'}</tbody></table></div>`;
    }catch(error){target.textContent=error.message;}
  }
  window.refreshDailyStatus=refreshStatus;
  el('role')?.addEventListener('change',()=>{dialog.close();refreshStatus();});
  refreshStatus();
})();
