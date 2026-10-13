/* Package-first receiving. A queued reading never inherits the last visible BL. */
window.WmsTruckScan = (() => {
  let currentGuide = '', busy = false, draining = false;
  const pending = [];
  const failed = [];
  let failureId = 0;
  let dhlTimer = null, dhlSequence = 0;
  const guideValue = () => $('truckGuideFilter')?.value || '';
  const rows = () => guideBlRows(activeTruckGuideSummary || {});
  const activeRows = () => rows().filter(row => row.truck_work_pending !== false);
  const inView = guide => guideValue() === guide && $('scanTruckWorkspace')?.dataset.guide === guide;
  const locked = () => busy || draining || pending.length > 0 || Boolean(window.WmsTruckControls?.hasPending());

  async function loadDhl(shipmentId, enqueue = true) {
    clearTimeout(dhlTimer);
    const sequence = ++dhlSequence;
    const current = () => sequence === dhlSequence && Number(scannerSelectedShipmentId) === shipmentId && Boolean($('scanDhlStatus'));
    try {
      const response = await api('/api/dhl-tracking/shipment' + (enqueue ? '' : '?shipment_id=' + shipmentId),
        enqueue ? {method:'POST', body:{shipment_id:shipmentId}} : undefined);
      const data = await response.json();
      if (!current()) return;
      const host = $('scanDhlStatus'), text = $('scanDhlText');
      if (!response.ok) throw new Error('No se pudo consultar el estado DHL.');
      host.hidden = !data.applicable || !data.enabled;
      const count = data.total_pieces == null ? 'Bultos no informados' : data.total_pieces + ' bultos informados';
      const checked = data.checked_at ? ' · ' + new Date(data.checked_at * 1000).toLocaleTimeString('es-PE',{hour:'2-digit',minute:'2-digit'}) : '';
      text.textContent = data.error || (data.state === 'expired' ? 'Datos DHL vencidos' : data.checked_at
        ? 'DHL: ' + count + ' · ' + data.status_label + checked : 'DHL: consulta en segundo plano');
      host.dataset.state = data.error ? 'warning' : data.state;
      $('scanDhlRefresh').disabled = data.pending === true;
      // This polls only our database; it never calls DHL or moves keyboard focus.
      if (!host.hidden && data.pending && !document.hidden) dhlTimer = setTimeout(() => loadDhl(shipmentId, false), 6000);
    } catch {
      if (current()) { $('scanDhlStatus').hidden = false; $('scanDhlText').textContent = 'Estado DHL no disponible. Puedes continuar la recepcion.'; }
    }
  }
  window.addEventListener('pagehide', () => { clearTimeout(dhlTimer); dhlSequence++; });

  function message(text, kind = 'success') {
    const target = $('scanFeedback');
    if (target) { target.textContent = text; target.dataset.kind = kind; target.setAttribute('role',kind === 'error' ? 'alert' : 'status'); }
  }
  const sameReading = (a, b) => a.guide === b.guide && a.code === b.code;
  function closeIdentification() { if ($('scanIdentifyPanel')) $('scanIdentifyPanel').hidden = true; }
  function removeFailure(item) {
    const index = failed.findIndex(other => sameReading(item, other));
    if (index < 0) return;
    if ($('scanTruckPackageCode')?.value.trim() === item.code) $('scanTruckPackageCode').value = '';
    if (Number($('scanIdentifyPanel')?.dataset.key) === failed[index].key) closeIdentification();
    failed.splice(index, 1);
  }
  function identify(key) {
    if (locked()) return;
    const item = failed.find(entry => entry.key === key);
    if (!item || !item.canIdentify || !inView(item.guide)) return;
    const panel = $('scanIdentifyPanel');
    panel.dataset.key = String(key); panel.hidden = false;
    $('scanIdentifyCode').textContent = item.code;
    $('scanIdentifyBl').value = item.blCode || '';
    $('scanIdentifyBl').focus();
  }
  async function confirmIdentification() {
    if (locked()) return;
    const item = failed.find(entry => entry.key === Number($('scanIdentifyPanel')?.dataset.key));
    const blCode = $('scanIdentifyBl')?.value.trim();
    if (!item || !item.canIdentify || !blCode || !inView(item.guide)) return;
    pending.push({...item, blCode});
    await drain();
  }
  function showFailures() {
    const host = $('scanFailures');
    if (!host) return;
    const items = failed.filter(item => item.guide === guideValue());
    host.hidden = items.length === 0;
    const signature = JSON.stringify(items);
    if (host.dataset.readings !== signature) {
      host.dataset.readings = signature;
      host.innerHTML = `<h3>Lecturas sin guardar (${items.length})</h3><ul>${items.map(item => `<li><strong>${esc(item.code)}</strong><small>${esc(item.error)}</small><div class="actions">${item.canIdentify ? `<button type="button" class="ghost" data-identify-reading="${item.key}">Identificar BL</button>` : ''}<button type="button" class="ghost" data-retry-reading="${item.key}">Reintentar</button><button type="button" class="ghost" data-discard-reading="${item.key}">Descartar lectura</button></div></li>`).join('')}</ul>`;
      host.querySelectorAll('[data-identify-reading]').forEach(button => button.onclick = () => identify(Number(button.dataset.identifyReading)));
      host.querySelectorAll('[data-retry-reading]').forEach(button => button.onclick = () => retry(Number(button.dataset.retryReading)));
      host.querySelectorAll('[data-discard-reading]').forEach(button => button.onclick = () => discardFailure(Number(button.dataset.discardReading)));
    }
    host.querySelectorAll('button').forEach(button => { button.disabled = locked(); });
  }
  function update() {
    const count = rows().reduce((total, row) => total + Number(row.package_scan_count || 0), 0);
    const total = $('scanTotal');
    if (total) total.textContent = String(count);
    const bl = rows().find(row => Number(row.id) === Number(scannerSelectedShipmentId));
    if ($('scanBlCount')) $('scanBlCount').textContent = String(bl?.package_scan_count || 0);
    if ($('scanLastBl')) $('scanLastBl').textContent = bl?.bl_awb || 'Sin lectura';
    if ($('scanBlList')) {
      $('scanBlList').innerHTML = activeRows().map(row => `<div class="scan-list-row"><strong>${esc(row.bl_awb)}</strong><span><strong id="scan-count-${Number(row.id)}">${Number(row.package_scan_count || 0)}</strong> bultos</span></div>`).join('');
      $('scanBlListTitle').textContent = 'BL del camion (' + activeRows().length + ')';
    }
    rows().forEach(row => {
      const node = $('scan-count-' + Number(row.id));
      if (node) node.textContent = String(row.package_scan_count || 0);
    });
    document.querySelectorAll('[data-scan-context]').forEach(button => { button.disabled = locked(); });
    const end = $('finalizeScanTruckButton');
    if (end) end.disabled = locked() || count === 0 || failed.some(item => item.guide === guideValue());
    const cancel = $('cancelScanTruckButton');
    if (cancel) cancel.disabled = locked();
    if ($('scanIdentifyConfirm')) $('scanIdentifyConfirm').disabled = locked();
    const queue = $('scanPending');
    if (queue) queue.textContent = pending.length || draining ? 'Guardando lecturas…' : 'Lecturas guardadas';
    if (queue && failed.some(item => item.guide === guideValue())) queue.textContent += ' · Hay lecturas sin guardar';
    showFailures();
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
    const guide = guideValue();
    if (!code || busy || window.WmsTruckControls?.hasPending()) return;
    // Consume the field before awaiting so fast HID readers do not concatenate codes.
    input.value = '';
    pending.push({guide, code});
    update();
    if (draining) return;
    await drain();
  }
  async function drain() {
    draining = true; update();
    while (pending.length) {
      const item = pending.shift();
      try {
        const response = await api('/api/receptions/truck-guide/scan-piece', {method:'POST', body:{truck_guide:item.guide, package_code:item.code,
          ...(item.blCode ? {bl_code:item.blCode, confirm_unverified:true} : {})}});
        const data = await response.json();
        if (!response.ok) { const error = new Error(data.error || 'No se guardó el paquete.'); error.canIdentify = data.can_identify === true; throw error; }
        removeFailure(item);
        if (inView(item.guide)) {
          const shipmentId = Number(data.shipment_id);
          let row = rows().find(row => Number(row.id) === shipmentId);
          if (!row && shipmentId) {
            row = {id:shipmentId, bl_awb:data.bl_awb, package_scan_count:0, truck_work_pending:true};
            activeTruckGuideSummary.bls = [...rows(), row];
          }
          if (row) row.package_scan_count = Number(data.count || 0);
          if (shipmentId) scannerSelectedShipmentId = shipmentId;
          const unverified = data.identification === 'manual' || data.dhl_verification === 'unverified';
          message(data.duplicate ? item.code + ': ya registrado; no suma otra vez.' : item.code + ' · BL ' + data.bl_awb + ' · ' + data.count + ' bultos.'
            + (unverified ? ' Sin verificar por DHL.' : data.dhl_verification === 'verified' ? ' Verificado por DHL.' : ''), data.duplicate || unverified ? 'warning' : 'success');
          if (shipmentId) loadDhl(shipmentId, false);
        }
      } catch (error) {
        const previous = failed.find(other => sameReading(other, item));
        if (previous) { previous.error = error.message; previous.canIdentify = error.canIdentify === true; }
        else failed.push({...item, key:++failureId, error:error.message, canIdentify:error.canIdentify === true});
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
    update(); $('scanTruckPackageCode')?.focus();
  }
  async function retry(key) {
    if (locked()) return;
    const item = failed.find(entry => entry.key === key);
    if (!item || !inView(item.guide)) return;
    pending.push({...item, blCode:undefined});
    await drain();
  }
  function discardFailure(key) {
    if (locked()) return;
    const item = failed.find(entry => entry.key === key);
    if (!item || !confirm('¿Descartar la lectura sin guardar ' + item.code + '? No se eliminarán bultos registrados.')) return;
    removeFailure(item); update();
  }
  async function finalize() {
    if (locked()) return;
    const guide = guideValue();
    if (failed.some(item => item.guide === guide)) { message('Reintenta o descarta las lecturas sin guardar antes de terminar.', 'error'); return; }
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
      for (let index = failed.length - 1; index >= 0; index--) if (failed[index].guide === guide) failed.splice(index,1);
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
    clearTimeout(dhlTimer); dhlSequence++;
    const guide = summary.truck_guide || '', status = guideStatus(summary.guide_status);
    if (currentGuide !== guide) { currentGuide = guide; scannerSelectedShipmentId = null; }
    const list = guideBlRows(summary), active = list.filter(row => row.truck_work_pending !== false);
    const selectedBl = active.find(row => Number(row.id) === Number(scannerSelectedShipmentId));
    const arrival = ['PENDIENTE','EN_CURSO'].includes(status);
    let task;
    if (arrival) {
      const chooser = `<label class="field" for="scanTruckPackageCode">Codigo unico del bulto<input class="control" id="scanTruckPackageCode" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Codigo del bulto" onkeydown="if(event.key==='Enter'){event.preventDefault();scanTruckPackage()}"></label><button class="primary scan-submit" onclick="scanTruckPackage()">Registrar bulto</button><div class="scan-active-bl"><div><small>Ultima BL</small><strong id="scanLastBl">${esc(selectedBl?.bl_awb || 'Sin lectura')}</strong></div><div class="scan-counter"><strong id="scanBlCount">${Number(selectedBl?.package_scan_count || 0)}</strong><span>bultos</span></div></div>`;
      task = `<section class="scan-task">${chooser}<div id="scanFeedback" class="scan-feedback" role="status" aria-live="polite">Esperando lectura.</div><small id="scanPending"></small><details class="scan-details"><summary id="scanBlListTitle">BL del camion (${active.length})</summary><div id="scanBlList"></div></details><div class="scan-finish"><button class="ghost scan-cancel" id="cancelScanTruckButton" onclick="cancelScannedTruckArrival()">Cancelar recepción</button><button class="ghost" id="finalizeScanTruckButton" onclick="finalizeScannedTruckArrival()">Terminar llegada →</button></div></section>`;
    } else if (status === 'ZONA_RECEPCION') {
      task = `<section class="scan-task"><h2>Ubicación temporal</h2>${active.filter(row => Number(row.received_this_truck || 0) > 0).map(row => `<article class="scan-location-card" data-truck-bl-row="${truckRowId(row)}"><header><strong>BL ${esc(row.bl_awb)}</strong><span>${Number(row.received_this_truck || 0)} bultos</span></header>${renderTruckLocationInputs(row)}</article>`).join('')}<button class="primary scan-submit" id="saveTruckLocationsButton" onclick="saveTruckLocations()">Guardar y finalizar camión</button></section>`;
    } else {
      task = `<section class="scan-task"><h2>Camión terminado</h2>${list.filter(row => Number(row.received_this_truck || 0) > 0).map(row => `<article class="scan-location-card"><header><strong>BL ${esc(row.bl_awb)}</strong><span>${Number(row.received_this_truck || 0)} bultos</span></header><button class="primary" onclick="loadDetail(${truckRowId(row)},false,${Number(row.attention_id || 0) || 'null'})">Continuar recepción</button></article>`).join('') || '<p>Sin bultos recibidos.</p>'}</section>`;
    }
    $('content').innerHTML = `<section class="card scan-workspace" id="scanTruckWorkspace" data-guide="${esc(guide)}"><header class="scan-heading"><div><small>Guía de camión</small><h1>${esc(guide)}</h1></div><div class="scan-total"><strong id="scanTotal">${list.reduce((n,r)=>n+Number(r.package_scan_count||0),0)}</strong><small>bultos</small></div></header><p class="scan-stage">${arrival?'1. Llegada':status==='ZONA_RECEPCION'?'2. Zona de recepción':'Completado'}</p>${task}</section>`;
    window.WmsTruckControls?.mount(summary);
    if (arrival) {
      const errors = document.createElement('section'); errors.id = 'scanFailures'; errors.className = 'scan-errors'; errors.hidden = true;
      errors.setAttribute('aria-label','Lecturas sin guardar'); errors.setAttribute('aria-live','polite');
      $('scanPending')?.after(errors);
      const identification = document.createElement('section'); identification.id = 'scanIdentifyPanel'; identification.className = 'scan-identify'; identification.hidden = true;
      identification.setAttribute('aria-label','Identificar bulto');
      identification.innerHTML = `<h3>Identificar bulto</h3><p id="scanIdentifyCode"></p><label class="field" for="scanIdentifyBl">BL / AWB<input class="control" id="scanIdentifyBl" autocomplete="off" onkeydown="if(event.key==='Enter'){event.preventDefault();WmsTruckScan.confirmIdentification()}"></label><div class="actions"><button class="primary" id="scanIdentifyConfirm" onclick="WmsTruckScan.confirmIdentification()">Confirmar BL y registrar</button><button class="ghost" onclick="WmsTruckScan.closeIdentification()">Cancelar</button></div>`;
      errors.after(identification);
      {
        const dhl = document.createElement('div'); dhl.id = 'scanDhlStatus'; dhl.className = 'scan-dhl-status'; dhl.hidden = true;
        const text = document.createElement('span'); text.id = 'scanDhlText'; text.setAttribute('role','status'); text.setAttribute('aria-live','polite');
        const refresh = document.createElement('button'); refresh.id = 'scanDhlRefresh'; refresh.type = 'button'; refresh.className = 'ghost';
        refresh.textContent = '\u21bb'; refresh.title = 'Consultar estado DHL'; refresh.setAttribute('aria-label','Consultar estado DHL');
        refresh.onclick = () => { if (scannerSelectedShipmentId) loadDhl(Number(scannerSelectedShipmentId)); };
        dhl.append(text, refresh); $('scanBlCount')?.parentElement.parentElement?.after(dhl);
        if (selectedBl) loadDhl(Number(selectedBl.id), false);
      }
    }
    update();
    $('scanTruckPackageCode')?.focus();
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
  return {render, changeBl, scanBl, scanPackage, finalize, cancel, simplifyDetail, update,
    identify, confirmIdentification, closeIdentification, hasPending:() => locked() || failed.length > 0};
})();
