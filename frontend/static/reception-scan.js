/* Scanner-first receiving. Each queued package keeps its original guide and BL. */
window.WmsTruckScan = (() => {
  let currentGuide = '', busy = false, draining = false;
  const pending = [];
  const guideValue = () => $('truckGuideFilter')?.value || '';
  const rows = () => guideBlRows(activeTruckGuideSummary || {});
  const activeRows = () => rows().filter(row => row.truck_work_pending !== false);
  const inView = guide => guideValue() === guide && $('scanTruckWorkspace')?.dataset.guide === guide;
  const locked = () => busy || draining || pending.length > 0;

  function message(text, kind = 'success') {
    const target = $('scanFeedback');
    if (target) { target.textContent = text; target.dataset.kind = kind; }
  }
  function update() {
    const count = rows().reduce((total, row) => total + Number(row.package_scan_count || 0), 0);
    const total = $('scanTotal');
    if (total) total.textContent = String(count);
    const bl = rows().find(row => Number(row.id) === Number(scannerSelectedShipmentId));
    if ($('scanBlCount')) $('scanBlCount').textContent = String(bl?.package_scan_count || 0);
    rows().forEach(row => {
      const node = $('scan-count-' + Number(row.id));
      if (node) node.textContent = String(row.package_scan_count || 0);
    });
    document.querySelectorAll('[data-scan-context]').forEach(button => { button.disabled = locked(); });
    const end = $('finalizeScanTruckButton');
    if (end) end.disabled = locked() || count === 0;
    const cancel = $('cancelScanTruckButton');
    if (cancel) cancel.disabled = locked();
    const queue = $('scanPending');
    if (queue) queue.textContent = pending.length || draining ? 'Guardando lecturas…' : 'Lecturas guardadas';
  }
  function changeBl(id = null) {
    if (locked()) { message('Espera a que se guarden las lecturas.', 'warning'); return; }
    const match = activeRows().find(row => Number(row.id) === Number(id));
    scannerSelectedShipmentId = match ? Number(match.id) : null;
    render(activeTruckGuideSummary || {});
  }
  async function scanBl() {
    if (locked()) return;
    const input = $('scanTruckBlCode'), code = input?.value.trim(), guide = guideValue();
    if (!code) return;
    busy = true; update();
    try {
      const response = await api('/api/receptions/truck-guide/scan-bl', {method:'POST', body:{truck_guide:guide, bl_code:code}});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'No se encontró la BL.');
      const lookup = await api('/api/receptions/truck-guide?truck_guide=' + encodeURIComponent(guide));
      const summary = await lookup.json();
      if (!lookup.ok) throw new Error(summary.error || 'No se pudo actualizar la guía. Vuelve a leer la BL.');
      if (!inView(guide)) return;
      activeTruckGuideSummary = summary;
      scannerSelectedShipmentId = Number(data.shipment_id);
      render(summary);
      message('BL ' + data.bl_awb + (data.created ? ' registrada. Datos documentales pendientes. ' : ' activa. ') + 'Escanea sus paquetes.');
    } catch (error) {
      if (inView(guide)) { message(error.message, 'error'); input?.select(); }
    } finally { busy = false; if (inView(guide)) update(); }
  }
  async function scanPackage() {
    const input = $('scanTruckPackageCode'), code = input?.value.trim();
    const guide = guideValue(), shipmentId = Number(scannerSelectedShipmentId);
    if (!code || busy) return;
    if (!shipmentId) { message('Primero selecciona una BL.', 'error'); return; }
    // Consume the field before awaiting so fast HID readers do not concatenate codes.
    input.value = '';
    pending.push({guide, shipmentId, code});
    update();
    if (draining) return;
    draining = true; update();
    while (pending.length) {
      const item = pending.shift();
      try {
        const response = await api('/api/receptions/truck-guide/scan-package', {method:'POST', body:{truck_guide:item.guide, shipment_id:item.shipmentId, package_code:item.code}});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'No se guardó el paquete.');
        if (inView(item.guide)) {
          const row = rows().find(row => Number(row.id) === item.shipmentId);
          if (row) row.package_scan_count = Number(data.count || 0);
          message(data.duplicate ? item.code + ': ya registrado; no suma otra vez.' : item.code + ' guardado · ' + data.count + ' bultos en esta BL.', data.duplicate ? 'warning' : 'success');
        }
      } catch (error) {
        if (inView(item.guide)) {
          message(item.code + ': ' + error.message, 'error');
          notify(error.message, 'error');
          const field = $('scanTruckPackageCode');
          if (field && !field.value && pending.length === 0) { field.value = item.code; field.select(); }
        }
      }
      if (inView(item.guide)) update();
    }
    draining = false;
    if (inView(guide)) { update(); $('scanTruckPackageCode')?.focus(); }
  }
  async function finalize() {
    if (locked()) return;
    const guide = guideValue();
    busy = true; update(); message('Guardando llegada…');
    try {
      const response = await api('/api/receptions/truck-guide/scan-finalize', {method:'POST', body:{truck_guide:guide}});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'No se pudo guardar la llegada.');
      if (inView(guide)) await refreshTruckGuideWorkspace(data);
    } catch (error) { if (inView(guide)) message(error.message, 'error'); }
    finally { busy = false; if (inView(guide)) update(); }
  }
  async function cancel() {
    if (locked()) return;
    const guide = guideValue();
    const count = rows().reduce((total, row) => total + Number(row.package_scan_count || 0), 0);
    const detail = count
      ? ` Se anularán ${count} lecturas y las BL volverán a su asignación anterior.`
      : ' Las BL vinculadas volverán a su asignación anterior.';
    if (!confirm(`¿Cancelar esta recepción nueva (${guide})?${detail} Esta acción no registra la llegada.`)) return;
    busy = true; update(); message('Cancelando recepción…');
    try {
      const response = await api('/api/receptions/truck-guide/scan-cancel', {method:'POST', body:{truck_guide:guide}});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'No se pudo cancelar la recepción.');
      if (inView(guide)) {
        scannerSelectedShipmentId = null;
        activeTruckGuideSummary = null;
        const select = $('truckGuideFilter');
        if (select) select.value = 'ALL';
        await loadTruckGuides();
        await showTruckGuideWorkspace();
        notify(`Recepción ${guide} cancelada. Las lecturas quedaron anuladas.`, 'success');
      }
    } catch (error) { if (inView(guide)) message(error.message, 'error'); }
    finally { busy = false; if (inView(guide)) update(); }
  }
  function render(summary) {
    const guide = summary.truck_guide || '', status = guideStatus(summary.guide_status);
    if (currentGuide !== guide) { currentGuide = guide; scannerSelectedShipmentId = null; }
    const list = guideBlRows(summary), active = list.filter(row => row.truck_work_pending !== false);
    const selectedBl = active.find(row => Number(row.id) === Number(scannerSelectedShipmentId));
    const arrival = ['PENDIENTE','EN_CURSO'].includes(status);
    let task;
    if (arrival) {
      const chooser = selectedBl
        ? `<div class="scan-active-bl"><div><small>BL activa</small><strong>${esc(selectedBl.bl_awb)}</strong></div><button class="ghost" data-scan-context onclick="WmsTruckScan.changeBl()">Cambiar BL</button></div><div class="scan-counter"><strong id="scanBlCount">${Number(selectedBl.package_scan_count || 0)}</strong><span>bultos de esta BL</span></div><label class="field" for="scanTruckPackageCode">Escanea el código único del paquete<input class="control" id="scanTruckPackageCode" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Código del paquete" onkeydown="if(event.key==='Enter'){event.preventDefault();scanTruckPackage()}"></label><button class="primary scan-submit" onclick="scanTruckPackage()">Registrar paquete</button>`
        : `<h2>Escanea una BL</h2><label class="field" for="scanTruckBlCode">BL / AWB<input class="control" id="scanTruckBlCode" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Código de BL" onkeydown="if(event.key==='Enter'){event.preventDefault();scanTruckBl()}"></label><button class="primary scan-submit" data-scan-context onclick="scanTruckBl()">Usar esta BL</button>`;
      task = `<section class="scan-task">${chooser}<div id="scanFeedback" class="scan-feedback" role="status" aria-live="polite">${selectedBl?'Lista para recibir paquetes.':'Lee la BL o escribe su código.'}</div><small id="scanPending"></small><details class="scan-details"><summary>Ver BLs del camión (${active.length})</summary>${active.map(row => `<div class="scan-list-row"><button class="ghost" data-scan-context onclick="selectScanTruckBl(${Number(row.id)})">${esc(row.bl_awb)}</button><span><strong id="scan-count-${Number(row.id)}">${Number(row.package_scan_count || 0)}</strong> bultos</span></div>`).join('') || '<p>Aún no hay BLs agregadas.</p>'}</details><div class="scan-finish"><button class="ghost scan-cancel" id="cancelScanTruckButton" onclick="cancelScannedTruckArrival()">Cancelar recepción</button><button class="ghost" id="finalizeScanTruckButton" onclick="finalizeScannedTruckArrival()">Terminar llegada →</button></div></section>`;
    } else if (status === 'ZONA_RECEPCION') {
      task = `<section class="scan-task"><h2>Ubicación temporal</h2>${active.filter(row => Number(row.received_this_truck || 0) > 0).map(row => `<article class="scan-location-card" data-truck-bl-row="${truckRowId(row)}"><header><strong>BL ${esc(row.bl_awb)}</strong><span>${Number(row.received_this_truck || 0)} bultos</span></header>${renderTruckLocationInputs(row)}</article>`).join('')}<button class="primary scan-submit" id="saveTruckLocationsButton" onclick="saveTruckLocations()">Guardar y finalizar camión</button></section>`;
    } else {
      task = `<section class="scan-task"><h2>Camión terminado</h2>${list.filter(row => Number(row.received_this_truck || 0) > 0).map(row => `<article class="scan-location-card"><header><strong>BL ${esc(row.bl_awb)}</strong><span>${Number(row.received_this_truck || 0)} bultos</span></header><button class="primary" onclick="loadDetail(${truckRowId(row)},false,${Number(row.attention_id || 0) || 'null'})">Continuar recepción</button></article>`).join('') || '<p>Sin bultos recibidos.</p>'}</section>`;
    }
    $('content').innerHTML = `<section class="card scan-workspace" id="scanTruckWorkspace" data-guide="${esc(guide)}"><header class="scan-heading"><div><small>Guía de camión</small><h1>${esc(guide)}</h1></div><div class="scan-total"><strong id="scanTotal">${list.reduce((n,r)=>n+Number(r.package_scan_count||0),0)}</strong><small>bultos</small></div></header><p class="scan-stage">${arrival?'1. Llegada':status==='ZONA_RECEPCION'?'2. Zona de recepción':'Completado'}</p>${task}</section>`;
    update();
    (selectedBl ? $('scanTruckPackageCode') : $('scanTruckBlCode'))?.focus();
  }
  function simplifyDetail() {
    const content = $('content'), hero = content?.querySelector('.hero');
    if (!hero) return;
    hero.classList.add('scan-bl-heading');
    const extra = document.createElement('details');
    extra.className = 'scan-bl-extra';
    const label = document.createElement('summary');
    label.textContent = 'Más información y controles de la BL';
    extra.append(label);
    [hero.querySelector('.title p'),hero.querySelector('.grid'),hero.querySelector('.flow'),
      hero.querySelector('.admin-rewind'),content.querySelector('.attention-summary'),
      content.querySelector('.reception-relations')].filter(Boolean).forEach(node => extra.append(node));
    const badges = hero.querySelectorAll('.badges .badge');
    if (badges.length > 1) {
      const secondary = document.createElement('div'); secondary.className = 'badges';
      Array.from(badges).slice(1).forEach(node => secondary.append(node));
      extra.append(secondary);
    }
    const nav = content.querySelector('.reception-tabs');
    if (nav) {
      const stages = document.createElement('details');
      stages.className = 'scan-stage-picker';
      const title = document.createElement('summary');
      title.textContent = 'Ver etapas y consultas';
      stages.append(title);
      nav.before(stages); stages.append(nav);
    }
    const advance = hero.querySelector(':scope > .actions');
    if (advance) { advance.classList.add('scan-bl-next'); content.append(advance); }
    content.append(extra);
  }
  return {render, changeBl, scanBl, scanPackage, finalize, cancel, simplifyDetail, hasPending:locked};
})();
