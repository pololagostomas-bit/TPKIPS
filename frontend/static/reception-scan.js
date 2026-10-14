/* DHL resolves each piece; BL intake captures an explicitly chosen receiving context. */
window.WmsTruckScan = (() => {
  let currentGuide = '', busy = false, draining = false;
  let entryMode = 'piece', receivingShipmentId = null;
  const packageDrafts = {piece:'', bl:''};
  const blPackageDrafts = new Map();
  const pending = [];
  const failed = [];
  let failureId = 0;
  let dhlTimer = null, dhlSequence = 0;
  const guideValue = () => $('truckGuideFilter')?.value || '';
  const rows = () => guideBlRows(activeTruckGuideSummary || {});
  const activeRows = () => rows().filter(row => row.truck_work_pending !== false);
  const inView = guide => guideValue() === guide && $('scanTruckWorkspace')?.dataset.guide === guide;
  const locked = () => busy || draining || pending.length > 0 || Boolean(window.WmsTruckControls?.hasPending());

  function setMode(mode) {
    if (!['piece','bl'].includes(mode) || locked()) return;
    if (mode !== entryMode) {
      packageDrafts[entryMode] = $('scanTruckPackageCode')?.value || '';
      entryMode = mode;
      if ($('scanTruckPackageCode')) $('scanTruckPackageCode').value = packageDrafts[mode];
      closeIdentification();
    }
    update();
    if (mode === 'bl' && !receivingShipmentId && $('scanBlEntry')) $('scanBlEntry').open = true;
    (mode === 'bl' && !receivingShipmentId ? $('scanTruckBlCode') : $('scanTruckPackageCode'))?.focus();
  }
  function discardDrafts() {
    packageDrafts.piece = ''; packageDrafts.bl = ''; blPackageDrafts.clear();
    if ($('scanTruckPackageCode')) $('scanTruckPackageCode').value = '';
    if ($('scanTruckBlCode')) $('scanTruckBlCode').value = '';
  }
  const hasDrafts = () => Boolean($('scanTruckPackageCode')) &&
    [$('scanTruckPackageCode').value, packageDrafts[entryMode === 'piece' ? 'bl' : 'piece'], ...blPackageDrafts.values()].some(Boolean);

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
      const progress = $('scanDhlProgress');
      progress.hidden = !data.enabled || data.pending_pieces == null;
      if (!progress.hidden) {
        const coverage = data.piece_list_complete ? '' : ' · Lista DHL parcial';
        progress.innerHTML = `<p>Leidos DHL: <strong>${Number(data.matched_pieces || 0)}</strong> · Por escanear: <strong>${Number(data.pending_pieces)}</strong>${coverage}</p>`
          + (data.pending_piece_ids?.length ? `<details><summary>Codigos por escanear (${Number(data.pending_pieces)})</summary><ul>${data.pending_piece_ids.map(code => `<li>${esc(code)}</li>`).join('')}</ul>${data.pending_pieces > data.pending_piece_ids.length ? '<p>Se muestran los primeros 20.</p>' : ''}</details>` : '');
      }
      host.dataset.state = data.error ? 'warning' : data.state;
      $('scanDhlRefresh').disabled = data.pending === true;
      // This polls only our database; it never calls DHL or moves keyboard focus.
      if (!host.hidden && data.pending && !document.hidden) dhlTimer = setTimeout(() => loadDhl(shipmentId, false), 6000);
    } catch {
      if (current()) { $('scanDhlProgress').hidden = true; $('scanDhlStatus').hidden = false; $('scanDhlText').textContent = 'Estado DHL no disponible. Puedes continuar la recepcion.'; }
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
    const mode = item.mode || 'piece';
    const currentContext = mode === entryMode && (mode !== 'bl' || item.shipmentId === receivingShipmentId);
    if (currentContext && $('scanTruckPackageCode')?.value.trim() === item.code) $('scanTruckPackageCode').value = '';
    if ((mode !== 'bl' || item.shipmentId === receivingShipmentId) && packageDrafts[mode] === item.code) packageDrafts[mode] = '';
    if (blPackageDrafts.get(item.shipmentId) === item.code) blPackageDrafts.delete(item.shipmentId);
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
    const receiving = activeRows().find(row => Number(row.id) === Number(receivingShipmentId));
    if ($('scanBlEntry')) $('scanBlEntry').hidden = entryMode !== 'bl';
    if ($('scanBlEntryTitle')) $('scanBlEntryTitle').textContent = receiving ? 'Cambiar BL' : 'Buscar BL';
    if ($('scanReceivingContext')) $('scanReceivingContext').hidden = entryMode !== 'bl';
    if ($('scanReceivingBl')) $('scanReceivingBl').textContent = receiving?.bl_awb || 'Sin BL elegida';
    if ($('scanReceivingTransport')) $('scanReceivingTransport').textContent = receiving?.transport_type || '';
    if ($('scanUseReviewedBl')) {
      $('scanUseReviewedBl').hidden = entryMode !== 'bl' || !bl || Number(bl.id) === Number(receivingShipmentId);
      $('scanUseReviewedBl').disabled = locked();
    }
    document.querySelectorAll('[data-scan-mode]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.scanMode === entryMode));
      button.disabled = locked();
    });
    if ($('scanBlSubmit')) $('scanBlSubmit').disabled = locked();
    const cannotScan = busy || Boolean(window.WmsTruckControls?.hasPending()) || (entryMode === 'bl' && !receiving);
    if ($('scanTruckPackageCode')) $('scanTruckPackageCode').disabled = cannotScan;
    if ($('scanPackageSubmit')) $('scanPackageSubmit').disabled = cannotScan;
    if ($('scanBlCount')) $('scanBlCount').textContent = String(bl?.package_scan_count || 0);
    if ($('scanLastBl')) $('scanLastBl').textContent = bl?.bl_awb || 'Sin lectura';
    if ($('scanBlReview')) $('scanBlReview').hidden = !bl;
    if ($('scanBlList')) {
      $('scanBlList').innerHTML = activeRows().map(row => `<button type="button" class="ghost scan-list-row" data-scan-context="${Number(row.id)}" aria-pressed="${Number(row.id) === Number(scannerSelectedShipmentId)}" aria-label="Revisar BL ${esc(row.bl_awb)}"><strong>${esc(row.bl_awb)}</strong><span><strong id="scan-count-${Number(row.id)}">${Number(row.package_scan_count || 0)}</strong> bultos</span></button>`).join('');
      $('scanBlListTitle').textContent = 'BL del camion (' + activeRows().length + ')';
    }
    rows().forEach(row => {
      const node = $('scan-count-' + Number(row.id));
      if (node) node.textContent = String(row.package_scan_count || 0);
    });
    document.querySelectorAll('[data-scan-context]').forEach(button => {
      button.disabled = locked();
      button.setAttribute('aria-pressed', String(Number(button.dataset.scanContext) === Number(scannerSelectedShipmentId)));
      button.onclick = () => changeBl(Number(button.dataset.scanContext));
    });
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
    const match = rows().find(row => Number(row.id) === Number(id));
    scannerSelectedShipmentId = match ? Number(match.id) : null;
    clearTimeout(dhlTimer); dhlSequence++;
    if ($('scanDhlStatus')) $('scanDhlStatus').hidden = true;
    if ($('scanDhlProgress')) $('scanDhlProgress').hidden = true;
    update();
    if (match) loadDhl(Number(match.id), false);
    $('scanTruckPackageCode')?.focus();
  }
  async function scanBl(reviewedCode = '') {
    if (locked() || entryMode !== 'bl') return;
    const input = $('scanTruckBlCode'), code = reviewedCode || input?.value.trim(), guide = guideValue();
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
      if (receivingShipmentId && receivingShipmentId !== Number(data.shipment_id)) {
        blPackageDrafts.set(receivingShipmentId, $('scanTruckPackageCode')?.value || '');
        packageDrafts.bl = blPackageDrafts.get(Number(data.shipment_id)) || '';
        blPackageDrafts.delete(Number(data.shipment_id));
        if ($('scanTruckPackageCode')) $('scanTruckPackageCode').value = packageDrafts.bl;
      }
      receivingShipmentId = Number(data.shipment_id);
      if (input && !reviewedCode) input.value = '';
      if ($('scanBlEntry') && !input?.value) $('scanBlEntry').open = false;
      update();
      if ($('scanDhlStatus')) $('scanDhlStatus').hidden = true;
      if ($('scanDhlProgress')) $('scanDhlProgress').hidden = true;
      loadDhl(receivingShipmentId, false);
      message('BL ' + data.bl_awb + ' elegida para registrar sus bultos.');
    } catch (error) {
      if (inView(guide)) { message(error.message, 'error'); input?.select(); }
    } finally {
      busy = false;
      if (inView(guide)) { update(); if (receivingShipmentId && !input?.value) $('scanTruckPackageCode')?.focus(); }
    }
  }
  async function useReviewedBl() {
    const row = activeRows().find(row => Number(row.id) === Number(scannerSelectedShipmentId));
    if (row) await scanBl(row.bl_awb);
  }
  async function scanPackage() {
    const input = $('scanTruckPackageCode'), code = input?.value.trim();
    const guide = guideValue();
    if (!code || busy || window.WmsTruckControls?.hasPending()) return;
    const receiving = activeRows().find(row => Number(row.id) === Number(receivingShipmentId));
    if (entryMode === 'bl' && !receiving) { message('Escanea o ingresa primero la BL.', 'error'); $('scanTruckBlCode')?.focus(); return; }
    // Consume the field before awaiting so fast HID readers do not concatenate codes.
    input.value = '';
    packageDrafts[entryMode] = '';
    if (entryMode === 'bl') blPackageDrafts.delete(Number(receiving.id));
    pending.push({guide, code, mode:entryMode, ...(entryMode === 'bl' ? {shipmentId:Number(receiving.id), blAwb:receiving.bl_awb} : {})});
    update();
    if (draining) return;
    await drain();
  }
  async function drain() {
    draining = true; update();
    while (pending.length) {
      const item = pending.shift();
      try {
        const manual = item.mode === 'bl';
        const response = await api('/api/receptions/truck-guide/' + (manual ? 'scan-package' : 'scan-piece'), {method:'POST', body:{truck_guide:item.guide, package_code:item.code,
          ...(manual ? {shipment_id:item.shipmentId} : item.blCode ? {bl_code:item.blCode, confirm_unverified:true} : {})}});
        const payload = await response.json();
        const data = manual ? {...payload, shipment_id:item.shipmentId, bl_awb:item.blAwb} : payload;
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
          if ($('scanDhlProgress')) $('scanDhlProgress').hidden = true;
          const unverified = !manual && (data.identification === 'manual' || data.dhl_verification === 'unverified');
          message(data.duplicate ? item.code + ': ya registrado; no suma otra vez.' : item.code + ' · BL ' + data.bl_awb + ' · ' + data.count + ' bultos.'
            + (manual ? ' BL elegida explicitamente.' : unverified ? ' Sin verificar por DHL.' : data.dhl_verification === 'verified' ? ' Verificado por DHL.' : ''), data.duplicate || unverified ? 'warning' : 'success');
          if (shipmentId) loadDhl(shipmentId, false);
        }
      } catch (error) {
        const previous = failed.find(other => sameReading(other, item));
        if (previous) { Object.assign(previous, item, {error:error.message, canIdentify:error.canIdentify === true}); }
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
    if (hasDrafts()) { message('Hay codigos sin registrar. Registralos o cancela los cambios antes de terminar la llegada.', 'error'); return; }
    busy = true; update(); message('Guardando llegada…');
    try {
      const response = await api('/api/receptions/truck-guide/scan-finalize', {method:'POST', body:{truck_guide:guide}});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'No se pudo guardar la llegada.');
      if (inView(guide)) { discardDrafts(); await refreshTruckGuideWorkspace(data); }
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
  const locationCards = () => [...($('scanTruckWorkspace')?.querySelectorAll('.scan-location-card[data-truck-bl-row]') || [])];
  const savedLocations = row => Array.isArray(row.locations) ? row.locations : [];
  const packageLabel = count => Number(count) + (Number(count) === 1 ? ' bulto' : ' bultos');
  function commonLocation(list) {
    const saved = list.filter(row => savedLocations(row).length);
    if (!saved.length) return '';
    const first = savedLocations(saved[0])[0].location_text || '';
    return saved.every(row => savedLocations(row).length === 1
      && savedLocations(row)[0].location_text === first
      && Number(savedLocations(row)[0].package_count) === Number(row.received_this_truck)) ? first : '';
  }
  function locationRowHtml(id, location = '', count = '') {
    return `<div class="truck-location-row"><label>Ubicación<input class="control truck-bl-location" data-shipment-id="${id}" value="${esc(location)}" autocomplete="off"></label><label>Bultos<input class="control truck-bl-location-qty" data-shipment-id="${id}" type="number" min="1" step="1" value="${count === '' ? '' : Number(count)}"></label><button class="ghost" type="button" data-remove-location aria-label="Quitar ubicación" title="Quitar ubicación">×</button></div>`;
  }
  function locationCardHtml(row, general) {
    const id = truckRowId(row), saved = savedLocations(row), received = Number(row.received_this_truck);
    const own = saved.length && !(saved.length === 1 && saved[0].location_text === general
      && Number(saved[0].package_count) === received);
    const values = saved.length ? saved : [{location_text:general, package_count:received}];
    return `<article class="scan-location-card" data-truck-bl-row="${id}" data-received="${received}"><header><strong>BL ${esc(row.bl_awb)}</strong><span>${packageLabel(received)}</span></header><label class="scan-location-own"><input type="checkbox" data-own-location ${own ? 'checked' : ''}>Ubicación propia</label><div class="truck-location-list" id="truck-locations-${id}">${values.map(item => locationRowHtml(id, item.location_text || '', item.package_count)).join('')}</div><button class="ghost" type="button" data-add-location title="Agregar otra ubicación para esta BL">+ Ubicación</button><small class="truck-bl-location-status" role="status" aria-live="polite"></small></article>`;
  }
  function locationBalance(card, report = false) {
    const entries = [...card.querySelectorAll('.truck-location-row')], names = new Set();
    let total = 0, valid = entries.length > 0, invalid = null;
    for (const entry of entries) {
      const zone = entry.querySelector('.truck-bl-location'), qty = entry.querySelector('.truck-bl-location-qty');
      const name = zone.value.trim().toLocaleUpperCase(), count = Number(qty.value);
      const goodName = Boolean(name) && !names.has(name), goodCount = Number.isInteger(count) && count > 0;
      zone.setAttribute('aria-invalid', String(!goodName)); qty.setAttribute('aria-invalid', String(!goodCount));
      if (!goodName || !goodCount) { valid = false; invalid ||= !goodName ? zone : qty; }
      names.add(name); total += Number.isFinite(count) ? count : 0;
    }
    const expected = Number(card.dataset.received), delta = expected - total;
    valid &&= delta === 0;
    const text = !entries.length ? 'Agrega una ubicación.' : !valid && delta === 0 ? 'Revisa ubicaciones y cantidades.'
      : delta > 0 ? `Faltan ubicar ${delta} bultos.` : delta < 0 ? `Sobran ${-delta} bultos en la distribución.` : 'Distribución completa.';
    const status = card.querySelector('.truck-bl-location-status');
    status.textContent = text; status.dataset.kind = valid ? 'success' : 'error';
    if (report && !valid) {
      const field = invalid || entries[0]?.querySelector('.truck-bl-location-qty') || card.querySelector('[data-add-location]');
      if (field?.matches('input')) field.setAttribute('aria-invalid', 'true');
      field?.focus();
      notify('BL ' + card.querySelector('header strong').textContent.replace(/^BL /, '') + ': ' + text, 'error');
    }
    return valid;
  }
  function setOwnLocation(card, own) {
    card.querySelector('[data-own-location]').checked = own;
    card.querySelectorAll('.truck-location-row input').forEach(input => { input.readOnly = !own; });
    // Editing by adding/removing a row explicitly creates an exception too.
    locationBalance(card);
  }
  function useGeneralLocation(card) {
    const id = Number(card.dataset.truckBlRow), general = $('scanGeneralLocation').value.trim();
    card.querySelector('.truck-location-list').innerHTML = locationRowHtml(id, general, Number(card.dataset.received));
    setOwnLocation(card, false);
  }
  function mountLocations() {
    const general = $('scanGeneralLocation');
    general.addEventListener('input', () => {
      if (locked()) return;
      locationCards().filter(card => !card.querySelector('[data-own-location]').checked).forEach(useGeneralLocation);
    });
    general.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); general.blur(); } });
    for (const card of locationCards()) {
      setOwnLocation(card, card.querySelector('[data-own-location]').checked);
      card.addEventListener('change', event => {
        if (!event.target.matches('[data-own-location]')) return;
        if (!event.target.checked) {
          if (!confirm('Usar la ubicación general para esta BL? Se reemplazará su distribución sin guardar.')) {
            event.target.checked = true; return;
          }
          useGeneralLocation(card);
        } else { setOwnLocation(card, true); card.querySelector('.truck-bl-location')?.focus(); }
      });
      card.addEventListener('input', event => {
        if (event.target.matches('.truck-bl-location,.truck-bl-location-qty')) locationBalance(card);
      });
      card.addEventListener('click', event => {
        if (locked()) return;
        const add = event.target.closest('[data-add-location]'), remove = event.target.closest('[data-remove-location]');
        if (!add && !remove) return;
        setOwnLocation(card, true);
        if (add) {
          card.querySelector('.truck-location-list').insertAdjacentHTML('beforeend', locationRowHtml(Number(card.dataset.truckBlRow)));
          card.querySelector('.truck-location-row:last-child .truck-bl-location').focus();
        } else remove.closest('.truck-location-row').remove();
        locationBalance(card);
      });
    }
  }
  async function saveLocations() {
    if (locked()) return;
    for (const card of locationCards()) if (!locationBalance(card, true)) return;
    const controls = [...$('scanTruckWorkspace').querySelectorAll('input,button')], disabled = controls.map(control => control.disabled);
    controls.forEach(control => { control.disabled = true; });
    try { await window.saveTruckLocations(); }
    finally { controls.forEach((control, index) => { if (control.isConnected) control.disabled = disabled[index]; }); }
  }
  function render(summary) {
    clearTimeout(dhlTimer); dhlSequence++;
    const guide = summary.truck_guide || '', status = guideStatus(summary.guide_status);
    if (currentGuide !== guide) {
      currentGuide = guide; scannerSelectedShipmentId = null; receivingShipmentId = null; entryMode = 'piece';
      packageDrafts.piece = ''; packageDrafts.bl = ''; blPackageDrafts.clear();
    } else if (inView(guide) && $('scanTruckPackageCode')) {
      packageDrafts[entryMode] = $('scanTruckPackageCode').value;
    }
    const list = guideBlRows(summary), active = list.filter(row => row.truck_work_pending !== false);
    const selectedBl = list.find(row => Number(row.id) === Number(scannerSelectedShipmentId));
    const arrival = ['PENDIENTE','EN_CURSO'].includes(status);
    let task;
    if (arrival) {
      const chooser = `<div class="scan-entry-modes" role="group" aria-label="Modo de ingreso"><button class="ghost" type="button" data-scan-mode="piece" onclick="WmsTruckScan.setMode('piece')">Bulto DHL</button><button class="ghost" type="button" data-scan-mode="bl" onclick="WmsTruckScan.setMode('bl')">Por BL</button></div>
        <details id="scanBlEntry" class="scan-bl-entry" hidden ${receivingShipmentId ? '' : 'open'}><summary id="scanBlEntryTitle">Buscar BL</summary><label class="field" for="scanTruckBlCode">BL / AWB<input class="control" id="scanTruckBlCode" maxlength="120" autocomplete="off" autocapitalize="off" spellcheck="false" onkeydown="if(event.key==='Enter'){event.preventDefault();scanTruckBl()}"></label><button class="ghost scan-submit" type="button" id="scanBlSubmit" onclick="scanTruckBl()">Buscar BL</button></details>
        <div id="scanReceivingContext" class="scan-receiving-context" hidden><small>Recibir bultos de</small><strong id="scanReceivingBl"></strong><span id="scanReceivingTransport"></span></div>
        <label class="field" for="scanTruckPackageCode">Codigo unico del bulto<input class="control" id="scanTruckPackageCode" value="${esc(packageDrafts[entryMode])}" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Codigo del bulto" onkeydown="if(event.key==='Enter'){event.preventDefault();scanTruckPackage()}"></label><button class="primary scan-submit" type="button" id="scanPackageSubmit" onclick="scanTruckPackage()">Registrar bulto</button><div class="scan-active-bl"><div><small>BL seleccionada</small><strong id="scanLastBl">${esc(selectedBl?.bl_awb || 'Sin lectura')}</strong></div><div class="scan-counter"><strong id="scanBlCount">${Number(selectedBl?.package_scan_count || 0)}</strong><span>en camion</span></div></div><button class="ghost scan-submit" type="button" id="scanUseReviewedBl" hidden onclick="WmsTruckScan.useReviewedBl()">Usar esta BL para recibir</button>`;
      task = `<section class="scan-task">${chooser}<div id="scanFeedback" class="scan-feedback" role="status" aria-live="polite">Esperando lectura.</div><small id="scanPending"></small><details class="scan-details"><summary id="scanBlListTitle">BL del camion (${active.length})</summary><div id="scanBlList"></div></details><div class="scan-finish"><button class="ghost scan-cancel" id="cancelScanTruckButton" onclick="cancelScannedTruckArrival()">Cancelar recepción</button><button class="ghost" id="finalizeScanTruckButton" onclick="finalizeScannedTruckArrival()">Terminar llegada →</button></div></section>`;
    } else if (status === 'ZONA_RECEPCION') {
      const received = active.filter(row => String(row.app_status || '').toUpperCase() !== 'CERRADO' && Number(row.received_this_truck || 0) > 0);
      const general = commonLocation(received);
      task = `<section class="scan-task"><h2>Ubicación temporal</h2><div class="scan-location-general"><label class="field" for="scanGeneralLocation">Ubicación general del camión<input class="control" id="scanGeneralLocation" value="${esc(general)}" autocomplete="off"></label></div>${received.map(row => locationCardHtml(row, general)).join('')}<button class="primary scan-submit" id="saveTruckLocationsButton" onclick="WmsTruckScan.saveLocations()">Guardar y finalizar camión</button></section>`;
    } else {
      task = `<section class="scan-task"><h2>Camión terminado</h2>${list.filter(row => Number(row.received_this_truck || 0) > 0).map(row => `<article class="scan-location-card" data-review-bl="${truckRowId(row)}"><header><strong>BL ${esc(row.bl_awb)}</strong><span>${packageLabel(row.received_this_truck)}</span></header><ul class="scan-location-summary">${savedLocations(row).map(item => `<li><strong>${esc(item.location_text || '')}</strong><span>${packageLabel(item.package_count)}</span></li>`).join('')}</ul><button class="primary" onclick="loadDetail(${truckRowId(row)},false,${Number(row.attention_id || 0) || 'null'})">Continuar recepción</button></article>`).join('') || '<p>Sin bultos recibidos.</p>'}</section>`;
    }
    $('content').innerHTML = `<section class="card scan-workspace" id="scanTruckWorkspace" data-guide="${esc(guide)}"><header class="scan-heading"><div><small>Guía de camión</small><h1>${esc(guide)}</h1></div><div class="scan-total"><strong id="scanTotal">${list.reduce((n,r)=>n+Number(r.package_scan_count||0),0)}</strong><small>bultos</small></div></header><p class="scan-stage">${arrival?'1. Llegada':status==='ZONA_RECEPCION'?'2. Zona de recepción':'Completado'}</p>${task}</section>`;
    if (!arrival) {
      const review = document.createElement('div'); review.id = 'scanBlReview'; review.hidden = !selectedBl;
      review.innerHTML = `<div class="scan-active-bl"><div><small>BL seleccionada</small><strong id="scanLastBl"></strong></div><div class="scan-counter"><strong id="scanBlCount"></strong><span>en camion</span></div></div>`;
      document.querySelector('#scanTruckWorkspace .scan-stage')?.after(review);
      document.querySelectorAll('#scanTruckWorkspace .scan-location-card > header').forEach(header => {
        const card = header.parentElement;
        const id = Number(card.dataset.truckBlRow || card.dataset.reviewBl);
        const row = list.find(item => Number(item.id) === id);
        if (!row) return;
        const button = document.createElement('button'); button.type = 'button'; button.className = 'ghost';
        button.dataset.scanContext = String(row.id);
        button.setAttribute('aria-label', 'Revisar BL ' + row.bl_awb);
        const label = header.querySelector('strong');
        label.replaceWith(button); button.append(label);
      });
    }
    window.WmsTruckControls?.mount(summary);
    if (status === 'ZONA_RECEPCION') mountLocations();
    if (arrival) {
      const errors = document.createElement('section'); errors.id = 'scanFailures'; errors.className = 'scan-errors'; errors.hidden = true;
      errors.setAttribute('aria-label','Lecturas sin guardar'); errors.setAttribute('aria-live','polite');
      $('scanPending')?.after(errors);
      const identification = document.createElement('section'); identification.id = 'scanIdentifyPanel'; identification.className = 'scan-identify'; identification.hidden = true;
      identification.setAttribute('aria-label','Identificar bulto');
      identification.innerHTML = `<h3>Identificar bulto</h3><p id="scanIdentifyCode"></p><label class="field" for="scanIdentifyBl">BL / AWB<input class="control" id="scanIdentifyBl" autocomplete="off" onkeydown="if(event.key==='Enter'){event.preventDefault();WmsTruckScan.confirmIdentification()}"></label><div class="actions"><button class="primary" id="scanIdentifyConfirm" onclick="WmsTruckScan.confirmIdentification()">Confirmar BL y registrar</button><button class="ghost" onclick="WmsTruckScan.closeIdentification()">Cancelar</button></div>`;
      errors.after(identification);
    }
    {
        const dhl = document.createElement('div'); dhl.id = 'scanDhlStatus'; dhl.className = 'scan-dhl-status'; dhl.hidden = true;
        const text = document.createElement('span'); text.id = 'scanDhlText'; text.setAttribute('role','status'); text.setAttribute('aria-live','polite');
        const refresh = document.createElement('button'); refresh.id = 'scanDhlRefresh'; refresh.type = 'button'; refresh.className = 'ghost';
        refresh.textContent = '\u21bb'; refresh.title = 'Consultar estado DHL'; refresh.setAttribute('aria-label','Consultar estado DHL');
        refresh.onclick = () => { if (scannerSelectedShipmentId) loadDhl(Number(scannerSelectedShipmentId)); };
        const progress = document.createElement('div'); progress.id = 'scanDhlProgress'; progress.className = 'scan-dhl-progress'; progress.hidden = true;
        progress.setAttribute('aria-live','polite');
        dhl.append(text, refresh); $('scanBlCount')?.parentElement.parentElement?.after(dhl);
        dhl.after(progress);
        if (selectedBl) loadDhl(Number(selectedBl.id), false);
    }
    update();
    (arrival && entryMode === 'bl' && !receivingShipmentId ? $('scanTruckBlCode') : $('scanTruckPackageCode'))?.focus();
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
  return {render, changeBl, setMode, useReviewedBl, scanBl, scanPackage, finalize, cancel, simplifyDetail, update, discardDrafts,
    hasDrafts,
    identify, confirmIdentification, closeIdentification, saveLocations, hasPending:() => locked() || failed.length > 0};
})();
