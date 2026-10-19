/* DHL resolves each piece; BL intake captures an explicitly chosen receiving context. */
window.WmsTruckScan = (() => {
  let currentGuide = '', busy = false, draining = false;
  let entryMode = 'piece', receivingShipmentId = null;
  let contextRevision = 0, activeReading = null, manualSequence = 0;
  let manualPage = null;
  const manualDrafts = new Map();
  const packageDrafts = {piece:'', bl:''};
  const blPackageDrafts = new Map();
  const pending = [];
  const failed = [];
  let failureId = 0;
  let dhlTimer = null, dhlSequence = 0;
  const canReviewPieceCodes = () => typeof isAdmin === 'function' && isAdmin();
  const guideValue = () => $('truckGuideFilter')?.value || '';
  const rows = () => guideBlRows(activeTruckGuideSummary || {});
  const activeRows = () => rows().filter(row => row.truck_work_pending !== false);
  const inView = guide => guideValue() === guide && $('scanTruckWorkspace')?.dataset.guide === guide;
  const locked = () => busy || draining || pending.length > 0 || Boolean(window.WmsTruckControls?.hasPending());
  function getCameraState() {
    return {guide:guideValue(), shipmentId:entryMode === 'bl' ? receivingShipmentId : null, mode:entryMode,
      pending:pending.length + (activeReading ? 1 : 0) + (busy ? 1 : 0),
      failed:failed.filter(item => item.guide === guideValue()).length,
      choice:$('scanManualEntry')?.open ? 'manual' : $('scanIdentifyPanel')?.hidden === false ? 'identify-bl' : null,
      revision:contextRevision};
  }
  const cameraMatches = context => !context || (context.guide === guideValue() && context.mode === entryMode &&
    context.shipmentId === getCameraState().shipmentId && context.revision === contextRevision);
  const readingCurrent = item => inView(item.guide) && item.revision === contextRevision;
  const resultFor = (status, item = {}, extra = {}) => ({status, guide:item.guide || guideValue(),
    shipmentId:item.shipmentId ?? (entryMode === 'bl' ? receivingShipmentId : null),
    mode:item.mode || entryMode, code:item.code || '', revision:contextRevision, ...extra});
  const brands = row => (row?.brands || []).join(' / ') || 'Marca sin indicar';
  const truckReceived = row => Math.max(Number(row?.package_scan_count || 0), Number(row?.received_this_truck || 0));
  function progress(row) {
    const expected = Number(row?.package_progress?.expected || row?.expected_packages || 0);
    const previous = Number(row?.package_progress?.previously_received ?? row?.previously_received_packages ?? 0);
    const received = previous + truckReceived(row);
    const source = row?.package_progress?.source || (expected > 0 ? 'WMS' : '');
    return {expected, previous, received, source,
      text: expected > 0 ? `${received}/${expected}` : `${received}/—`,
      status: expected <= 0 ? 'Total sin informar' : received > expected ? `Exceso: ${received - expected}` :
        received === expected ? 'Completa' : `Faltan ${expected - received}`};
  }
  function progressHtml(row) {
    const value = progress(row);
    return `<span class="scan-row-progress"><strong>${esc(value.text)}</strong><small>${esc(value.status)}${value.source ? ' · ' + esc(value.source) : ''}</small></span>`;
  }

  function setMode(mode) {
    if (!['piece','bl'].includes(mode) || locked()) return;
    if (mode !== entryMode) {
      packageDrafts[entryMode] = $('scanTruckPackageCode')?.value || '';
      entryMode = mode;
      contextRevision++; manualSequence++;
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
    manualDrafts.clear(); restoreManualDraft();
  }
  const hasDrafts = () => Boolean($('scanTruckPackageCode')) &&
    ([$('scanTruckPackageCode').value, packageDrafts[entryMode === 'piece' ? 'bl' : 'piece'], ...blPackageDrafts.values()].some(Boolean) ||
      [...manualDrafts.values()].some(draft => draft.code || draft.knownCode || draft.reason));

  function rememberManualDraft() {
    if (!receivingShipmentId || !$('scanManualKnownCode')) return;
    const draft = manualDrafts.get(receivingShipmentId) || {};
    Object.assign(draft, {knownCode:$('scanManualKnownCode').value, reason:$('scanManualReason').value,
      confirmed:$('scanManualConfirmed').checked === true, open:$('scanManualEntry').open === true});
    manualDrafts.set(receivingShipmentId, draft);
  }
  function restoreManualDraft() {
    const draft = manualDrafts.get(receivingShipmentId) || {};
    if (!$('scanManualKnownCode')) return;
    $('scanManualKnownCode').value = draft.knownCode || '';
    $('scanManualReason').value = draft.reason || '';
    $('scanManualConfirmed').checked = draft.confirmed === true;
    $('scanManualEntry').open = draft.open === true;
    $('scanManualSelected').textContent = draft.code || 'Sin pieza elegida';
    if ($('scanManualSelectedBl')) $('scanManualSelectedBl').textContent =
      'BL ' + (activeRows().find(row => Number(row.id) === Number(receivingShipmentId))?.bl_awb || 'Sin elegir');
    $('scanManualSelection').hidden = !draft.code;
  }
  function manualMessage(text, error = false) {
    const node = $('scanManualStatus');
    if (node) { node.textContent = text; node.setAttribute('role', error ? 'alert' : 'status'); }
  }
  function renderManualPieces() {
    const host = $('scanManualPieces');
    if (!canReviewPieceCodes() || !host || !manualPage) return;
    const data = manualPage;
    $('scanManualCoverage').textContent = data.checked_at == null ? '' :
      `Recibidas: ${data.received} · Faltantes en cache: ${data.missing ?? 'Sin informar'} · ${data.list_complete ? 'Lista completa' : 'Lista parcial'} · ${new Date(data.checked_at * 1000).toLocaleString('es-PE')}`;
    host.innerHTML = (data.items || []).map((item, index) => `<li><span><strong>${esc(item.code)}</strong><small>${item.state === 'received' ? 'Recibida' : item.state === 'blocked' ? 'Requiere revision' : 'Faltante'}${item.detail ? ' · ' + esc(item.detail) : ''}</small></span>${item.can_select ? `<button type="button" class="ghost" data-manual-piece="${index}" aria-label="Elegir pieza ${esc(item.code)}">Elegir</button>` : ''}</li>`).join('');
    host.querySelectorAll('[data-manual-piece]').forEach(button => {
      button.disabled = locked();
      button.onclick = () => selectManualPiece(data.items[Number(button.dataset.manualPiece)]?.code, 'cache');
    });
    $('scanManualPage').textContent = `${data.page} / ${data.pages} · ${data.total} piezas`;
    $('scanManualPrev').disabled = locked() || data.page <= 1;
    $('scanManualNext').disabled = locked() || data.page >= data.pages;
  }
  async function loadManualPieces(page = 1) {
    if (!canReviewPieceCodes()) return;
    const guide = guideValue(), sid = receivingShipmentId, revision = contextRevision, sequence = ++manualSequence;
    const current = () => sequence === manualSequence && revision === contextRevision && inView(guide) &&
      entryMode === 'bl' && receivingShipmentId === sid;
    if (!sid || entryMode !== 'bl') return;
    manualPage = null; $('scanManualPieces').innerHTML = ''; $('scanManualCoverage').textContent = '';
    $('scanManualPage').textContent = '';
    $('scanManualPrev').disabled = true; $('scanManualNext').disabled = true;
    manualMessage('Cargando piezas guardadas…');
    try {
      const query = new URLSearchParams({truck_guide:guide, shipment_id:String(sid), page:String(page), query:$('scanManualSearch').value.trim()});
      const response = await api('/api/receptions/truck-guide/manual-pieces?' + query);
      const data = await response.json();
      if (!current()) return;
      if (!response.ok) throw new Error(data.error || 'No se pudo cargar la lista.');
      if (data.truck_guide !== guide || Number(data.shipment_id) !== sid || !Array.isArray(data.items))
        throw new Error('La respuesta no corresponde a esta BL y camion.');
      manualPage = data; renderManualPieces();
      manualMessage(data.error || (!data.applicable ? 'Esta BL no utiliza piezas DHL. Puedes ingresar su codigo unico conocido.' :
        !data.enabled ? 'DHL deshabilitado. Esta BL requiere verificacion antes de registrar nuevos bultos.' :
        data.checked_at == null ? 'Sin cache DHL vigente. Actualiza la consulta o revisa la conexion DHL.' :
        !data.items.length ? 'Sin piezas para esta busqueda.' : ''));
    } catch (error) {
      if (current()) manualMessage('Lista no disponible. ' + error.message + ' Reintenta la consulta; el borrador se conserva.', true);
    }
  }
  function selectManualPiece(code, source) {
    if (locked() || entryMode !== 'bl' || !receivingShipmentId) return;
    if (source === 'cache' && !canReviewPieceCodes()) return;
    code = String(code || '').trim();
    if (!code) { manualMessage('Ingresa el codigo unico conocido del bulto.', true); $('scanManualKnownCode')?.focus(); return; }
    if (source === 'cache' && !manualPage?.items.some(item => item.code === code && item.can_select)) return;
    rememberManualDraft();
    const draft = manualDrafts.get(receivingShipmentId) || {};
    Object.assign(draft, {code, source, confirmed:false, open:true});
    manualDrafts.set(receivingShipmentId, draft); restoreManualDraft();
    $('scanManualReason')?.focus();
  }
  async function confirmManualPiece() {
    if (locked() || entryMode !== 'bl') return resultFor('blocked');
    rememberManualDraft();
    const draft = manualDrafts.get(receivingShipmentId), row = activeRows().find(item => Number(item.id) === receivingShipmentId);
    if (!row || !draft?.code) return resultFor('blocked');
    if (draft.source === 'cache' && !canReviewPieceCodes()) return resultFor('blocked');
    if (!draft.reason || draft.reason.trim().length < 8 || draft.reason.trim().length > 500) {
      manualMessage('Indica la evidencia de identificacion (8 a 500 caracteres).', true); $('scanManualReason').focus();
      return resultFor('blocked');
    }
    if (!draft.confirmed) {
      manualMessage('Confirma la identidad y presencia fisica de esta pieza exacta.', true); $('scanManualConfirmed').focus();
      return resultFor('choice');
    }
    return enqueueReading({guide:guideValue(), shipmentId:receivingShipmentId, blAwb:row.bl_awb, code:draft.code,
      mode:'bl', manual:true, source:draft.source, reason:draft.reason.trim(), confirmed:true, revision:contextRevision});
  }
  async function useManualBl() {
    const row = activeRows().find(item => Number(item.id) === Number($('scanManualBl').value));
    if (row) return scanBl(row.bl_awb);
  }
  function mountManualEntry() {
    const admin = canReviewPieceCodes();
    const host = document.createElement('details'); host.id = 'scanManualEntry'; host.className = 'scan-manual-entry'; host.hidden = true;
    host.innerHTML = `<summary>${admin ? 'Ingreso manual / etiqueta borrosa' : 'Etiqueta borrosa: codigo conocido'}</summary>
      <p id="scanManualRequirement">${admin ? 'Confirma la identidad y presencia fisica del bulto. Un codigo DHL sin coincidencia vigente no se registra.' : 'Ingresa solo el codigo que puedas leer en el bulto o su copia. Si no es legible, solicita revision del administrador.'}</p>
      ${admin ? `<p class="help-guidance">Elige solo la pieza cuya identidad puedas verificar.</p><label class="field" for="scanManualSearch">Buscar pieza DHL guardada<input class="control" id="scanManualSearch" maxlength="120" autocomplete="off"></label>
      <button type="button" class="ghost scan-submit" id="scanManualReload">Consultar piezas guardadas</button>
      <p id="scanManualCoverage"></p><ul id="scanManualPieces"></ul>
      <nav class="scan-manual-pages" aria-label="Paginas de piezas"><button type="button" class="ghost" id="scanManualPrev" aria-label="Pagina anterior" title="Pagina anterior">←</button><span id="scanManualPage"></span><button type="button" class="ghost" id="scanManualNext" aria-label="Pagina siguiente" title="Pagina siguiente">→</button></nav>
      ` : ''}<p id="scanManualStatus" role="status" aria-live="polite"></p>
      <label class="field" for="scanManualKnownCode">Codigo unico conocido<input class="control" id="scanManualKnownCode" maxlength="120" autocomplete="off" autocapitalize="off" spellcheck="false"></label>
      <button type="button" class="ghost scan-submit" id="scanManualUseCode">Usar codigo conocido</button>
      <section id="scanManualSelection" hidden><h3>Bulto elegido</h3><p id="scanManualSelectedBl"></p><strong id="scanManualSelected"></strong>
      <label class="field" for="scanManualReason">Evidencia de identificacion<input class="control" id="scanManualReason" minlength="8" maxlength="500" autocomplete="off"></label>
      <label class="scan-manual-confirm" for="scanManualConfirmed"><input type="checkbox" id="scanManualConfirmed">Confirmo la identidad y presencia fisica de esta pieza exacta en esta BL y camion.</label>
      <button type="button" class="primary scan-submit" id="scanManualSave">Confirmar bulto manual</button>
      <button type="button" class="ghost scan-submit" id="scanManualClear">Descartar borrador manual</button></section>`;
    $('scanPackageSubmit').after(host);
    if (admin) {
      $('scanManualReload').onclick = () => loadManualPieces();
      $('scanManualPrev').onclick = () => loadManualPieces((manualPage?.page || 1) - 1);
      $('scanManualNext').onclick = () => loadManualPieces((manualPage?.page || 1) + 1);
      $('scanManualSearch').onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); loadManualPieces(); } };
    }
    $('scanManualUseCode').onclick = () => selectManualPiece($('scanManualKnownCode').value, 'known_code');
    $('scanManualSave').onclick = confirmManualPiece;
    $('scanManualClear').onclick = () => { if (!locked()) { manualDrafts.delete(receivingShipmentId); restoreManualDraft(); } };
    $('scanManualKnownCode').onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); selectManualPiece(event.target.value, 'known_code'); } };
    host.addEventListener('input', rememberManualDraft);
    host.addEventListener('toggle', () => { rememberManualDraft(); if (canReviewPieceCodes() && host.open && !manualPage) loadManualPieces(); });
    restoreManualDraft();
  }

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
      const row = rows().find(item => Number(item.id) === shipmentId);
      if (row) {
        row.package_progress = {...row.package_progress, expected:data.total_pieces || row.expected_packages || null,
          source:data.total_pieces ? 'DHL' : row.expected_packages ? 'WMS' : ''};
        update();
      }
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
          + (canReviewPieceCodes() && data.can_view_piece_codes === true && data.pending_piece_ids?.length ? `<details><summary>Codigos por escanear (${Number(data.pending_pieces)})</summary><ul>${data.pending_piece_ids.map(code => `<li>${esc(code)}</li>`).join('')}</ul>${data.pending_pieces > data.pending_piece_ids.length ? '<p>Se muestran los primeros 20.</p>' : ''}</details>` : '');
      }
      host.dataset.state = data.error ? 'warning' : data.state;
      $('scanDhlRefresh').disabled = data.pending === true;
      // This polls only our database; it never calls DHL or moves keyboard focus.
      if (!host.hidden && data.pending && !document.hidden) dhlTimer = setTimeout(() => loadDhl(shipmentId, false), 6000);
    } catch {
      if (current()) { $('scanDhlProgress').hidden = true; $('scanDhlStatus').hidden = false; $('scanDhlText').textContent = 'Estado DHL no disponible. Reintenta la consulta o solicita revision del administrador.'; }
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
    if (!canReviewPieceCodes() || locked()) return;
    const item = failed.find(entry => entry.key === key);
    if (!item || !item.canIdentify || !inView(item.guide)) return;
    const panel = $('scanIdentifyPanel');
    panel.dataset.key = String(key); panel.hidden = false;
    $('scanIdentifyCode').textContent = item.code;
    $('scanIdentifyBl').value = item.blCode || '';
    $('scanIdentifyBl').focus();
  }
  async function confirmIdentification() {
    if (!canReviewPieceCodes() || locked()) return;
    const item = failed.find(entry => entry.key === Number($('scanIdentifyPanel')?.dataset.key));
    const blCode = $('scanIdentifyBl')?.value.trim();
    if (!item || !item.canIdentify || !blCode || !inView(item.guide)) return;
    return enqueueReading({...item, blCode, revision:contextRevision});
  }
  function showFailures() {
    const host = $('scanFailures');
    if (!host) return;
    const items = failed.filter(item => item.guide === guideValue());
    host.hidden = items.length === 0;
    const signature = JSON.stringify(items);
    if (host.dataset.readings !== signature) {
      host.dataset.readings = signature;
      host.innerHTML = `<h3>Lecturas sin guardar (${items.length})</h3><ul>${items.map(item => `<li><strong>${esc(item.code)}</strong><small>${esc(item.error)}</small><div class="actions">${canReviewPieceCodes() && item.canIdentify ? `<button type="button" class="ghost" data-identify-reading="${item.key}">Identificar BL</button>` : ''}<button type="button" class="ghost" data-retry-reading="${item.key}">Reintentar</button><button type="button" class="ghost" data-discard-reading="${item.key}">Descartar lectura</button></div></li>`).join('')}</ul>`;
      host.querySelectorAll('[data-identify-reading]').forEach(button => button.onclick = () => identify(Number(button.dataset.identifyReading)));
      host.querySelectorAll('[data-retry-reading]').forEach(button => button.onclick = () => retry(Number(button.dataset.retryReading)));
      host.querySelectorAll('[data-discard-reading]').forEach(button => button.onclick = () => discardFailure(Number(button.dataset.discardReading)));
    }
    host.querySelectorAll('button').forEach(button => { button.disabled = locked(); });
  }
  function update() {
    const count = rows().reduce((total, row) => total + truckReceived(row), 0);
    const total = $('scanTotal');
    if (total) total.textContent = String(count);
    const knownTotal = rows().length && rows().every(row => progress(row).expected > 0);
    if ($('scanTotalExpected')) $('scanTotalExpected').textContent = knownTotal
      ? '/' + rows().reduce((sum,row) => sum + Math.max(0, progress(row).expected - progress(row).previous), 0) : '/—';
    if ($('scanTotalLabel')) $('scanTotalLabel').textContent = knownTotal ? 'en este camión' : 'total por confirmar';
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
    if ($('scanManualBl')) {
      const chosen = $('scanManualBl').value;
      const options = activeRows().map(row => `<option value="${Number(row.id)}">${esc(row.bl_awb)}</option>`).join('');
      const signature = JSON.stringify(activeRows().map(row => [row.id, row.bl_awb]));
      if ($('scanManualBl').dataset.options !== signature) {
        $('scanManualBl').innerHTML = '<option value="">Elegir BL del camion</option>' + options;
        $('scanManualBl').value = chosen; $('scanManualBl').dataset.options = signature;
      }
      $('scanManualBl').disabled = locked();
      $('scanManualUseBl').disabled = locked();
    }
    if ($('scanManualEntry')) {
      $('scanManualEntry').hidden = entryMode !== 'bl' || !receiving;
      $('scanManualEntry').querySelectorAll('input,button').forEach(control => { control.disabled = locked(); });
      renderManualPieces();
    }
    const cannotScan = busy || Boolean(window.WmsTruckControls?.hasPending()) || (entryMode === 'bl' && !receiving);
    if ($('scanTruckPackageCode')) $('scanTruckPackageCode').disabled = cannotScan;
    if ($('scanPackageSubmit')) $('scanPackageSubmit').disabled = cannotScan;
    const value = progress(bl);
    if ($('scanBlCount')) $('scanBlCount').textContent = bl ? value.text : '—';
    if ($('scanBlProgressLabel')) $('scanBlProgressLabel').textContent = bl ? value.status + (value.source ? ' · ' + value.source : '') : '';
    if ($('scanBlPrevious')) $('scanBlPrevious').textContent = value.previous > 0
      ? `${value.previous} previos · ${truckReceived(bl)} en este camión` : '';
    if ($('scanBlBrands')) $('scanBlBrands').textContent = bl ? brands(bl) : '';
    if ($('scanLastBl')) $('scanLastBl').textContent = bl?.bl_awb || 'Sin lectura';
    if ($('scanBlReview')) $('scanBlReview').hidden = !bl;
    if ($('scanBlList')) {
      $('scanBlList').innerHTML = activeRows().map(row => `<button type="button" class="ghost scan-list-row" data-scan-context="${Number(row.id)}" aria-pressed="${Number(row.id) === Number(scannerSelectedShipmentId)}" aria-label="Revisar BL ${esc(row.bl_awb)}"><span class="scan-row-identity"><strong>${esc(row.bl_awb)}</strong><small>${esc(brands(row))}</small></span>${progressHtml(row)}</button>`).join('');
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
  async function scanBl(reviewedCode = '', cameraContext = null) {
    if (!cameraMatches(cameraContext)) return resultFor('stale');
    if (locked() || entryMode !== 'bl') return resultFor('blocked');
    const input = $('scanTruckBlCode'), code = reviewedCode || input?.value.trim(), guide = guideValue();
    if (!code) return resultFor('blocked');
    const revision = contextRevision;
    let finalRevision = revision;
    const item = {guide, code, mode:'bl', shipmentId:receivingShipmentId};
    busy = true; update();
    try {
      const response = await api('/api/receptions/truck-guide/scan-bl', {method:'POST', body:{truck_guide:guide, bl_code:code}});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'No se encontró la BL.');
      const lookup = await api('/api/receptions/truck-guide?truck_guide=' + encodeURIComponent(guide));
      const summary = await lookup.json();
      if (!lookup.ok) throw new Error(summary.error || 'No se pudo actualizar la guía. Vuelve a leer la BL.');
      if (!inView(guide) || revision !== contextRevision) return resultFor('stale', item);
      activeTruckGuideSummary = summary;
      scannerSelectedShipmentId = Number(data.shipment_id);
      rememberManualDraft(); manualSequence++; manualPage = null;
      if (receivingShipmentId && receivingShipmentId !== Number(data.shipment_id)) {
        blPackageDrafts.set(receivingShipmentId, $('scanTruckPackageCode')?.value || '');
        packageDrafts.bl = blPackageDrafts.get(Number(data.shipment_id)) || '';
        blPackageDrafts.delete(Number(data.shipment_id));
        if ($('scanTruckPackageCode')) $('scanTruckPackageCode').value = packageDrafts.bl;
      }
      receivingShipmentId = Number(data.shipment_id);
      contextRevision++; finalRevision = contextRevision; restoreManualDraft();
      if ($('scanManualSearch')) $('scanManualSearch').value = '';
      if ($('scanManualPieces')) $('scanManualPieces').innerHTML = '';
      if ($('scanManualCoverage')) $('scanManualCoverage').textContent = '';
      if ($('scanManualEntry')?.open) loadManualPieces();
      if (input && !reviewedCode) input.value = '';
      if ($('scanBlEntry') && !input?.value) $('scanBlEntry').open = false;
      update();
      if ($('scanDhlStatus')) $('scanDhlStatus').hidden = true;
      if ($('scanDhlProgress')) $('scanDhlProgress').hidden = true;
      loadDhl(receivingShipmentId, false);
      message('BL ' + data.bl_awb + ' elegida para registrar sus bultos.');
      return resultFor(data.duplicate ? 'duplicate' : 'saved', {...item, shipmentId:receivingShipmentId}, {blAwb:data.bl_awb});
    } catch (error) {
      const current = inView(guide) && revision === contextRevision;
      if (current) { message(error.message, 'error'); input?.select(); }
      return resultFor(current ? 'failed' : 'stale', item, {error:error.message});
    } finally {
      busy = false;
      if (inView(guide) && finalRevision === contextRevision) { update(); if (receivingShipmentId && !input?.value) $('scanTruckPackageCode')?.focus(); }
    }
  }
  async function useReviewedBl() {
    const row = activeRows().find(row => Number(row.id) === Number(scannerSelectedShipmentId));
    if (row) await scanBl(row.bl_awb);
  }
  function enqueueReading(item) {
    const completion = new Promise(resolve => { item.resolve = resolve; });
    pending.push(item); update();
    if (!draining) void drain();
    return completion;
  }
  async function scanPackage(cameraCode = null, cameraContext = null) {
    if (!cameraMatches(cameraContext)) return resultFor('stale');
    if (cameraContext && getCameraState().choice) return resultFor('choice');
    const input = $('scanTruckPackageCode'), code = String(cameraCode ?? input?.value ?? '').trim();
    const guide = guideValue();
    if (!code || busy || window.WmsTruckControls?.hasPending()) return resultFor('blocked');
    if (cameraCode !== null && input?.value && input.value.trim() !== code) return resultFor('blocked', {guide, code}, {error:'Hay un codigo sin registrar.'});
    const receiving = activeRows().find(row => Number(row.id) === Number(receivingShipmentId));
    if (entryMode === 'bl' && !receiving) { message('Elige o ingresa primero la BL.', 'error'); $('scanTruckBlCode')?.focus(); return resultFor('choice', {guide, code}); }
    // Consume the field before awaiting so fast HID readers do not concatenate codes.
    input.value = '';
    packageDrafts[entryMode] = '';
    if (entryMode === 'bl') blPackageDrafts.delete(Number(receiving.id));
    return enqueueReading({guide, code, mode:entryMode, revision:contextRevision,
      ...(entryMode === 'bl' ? {shipmentId:Number(receiving.id), blAwb:receiving.bl_awb} : {})});
  }
  async function drain() {
    draining = true; update();
    let lastReading;
    while (pending.length) {
      const item = pending.shift();
      lastReading = item;
      activeReading = item;
      let outcome;
      try {
        const manual = item.mode === 'bl';
        const response = await api('/api/receptions/truck-guide/' + (item.manual ? 'manual-package' : manual ? 'scan-package' : 'scan-piece'), {method:'POST', body:{truck_guide:item.guide, package_code:item.code,
          ...(item.manual ? {source:item.source, reason:item.reason, confirmed:item.confirmed} : {}),
          ...(manual ? {shipment_id:item.shipmentId} : item.blCode ? {bl_code:item.blCode, confirm_unverified:true} : {})}});
        const payload = await response.json();
        const data = manual ? {...payload, shipment_id:item.shipmentId, bl_awb:item.blAwb} : payload;
        if (!response.ok) { const error = new Error(data.error || 'No se guardó el paquete.'); error.canIdentify = canReviewPieceCodes() && data.can_identify === true; throw error; }
        removeFailure(item);
        outcome = resultFor(readingCurrent(item) ? data.duplicate ? 'duplicate' : 'saved' : 'stale', item,
          {shipmentId:Number(data.shipment_id), blAwb:data.bl_awb, duplicate:data.duplicate === true,
            outcome:data.duplicate ? 'duplicate' : 'saved'});
        if (readingCurrent(item)) {
          if (item.manual) {
            const draft = manualDrafts.get(item.shipmentId);
            if (draft?.code === item.code) manualDrafts.delete(item.shipmentId);
            restoreManualDraft();
            if (manualPage?.shipment_id === item.shipmentId) {
              const piece = manualPage.items.find(piece => piece.code === item.code);
              if (piece && piece.state === 'missing') {
                piece.state = 'received'; piece.can_select = false; piece.detail = 'Este camion';
                manualPage.received++; manualPage.missing = Math.max(0, Number(manualPage.missing) - 1);
              }
            }
          }
          const shipmentId = Number(data.shipment_id);
          let row = rows().find(row => Number(row.id) === shipmentId);
          if (!row && shipmentId) {
            row = {id:shipmentId, bl_awb:data.bl_awb, package_scan_count:0, truck_work_pending:true};
            activeTruckGuideSummary.bls = [...rows(), row];
          }
          if (row) {
            row.package_scan_count = Number(data.count || 0);
            if (data.bl_context) Object.assign(row, data.bl_context);
          }
          if (shipmentId) scannerSelectedShipmentId = shipmentId;
          if ($('scanDhlProgress')) $('scanDhlProgress').hidden = true;
          const unverified = (!manual || item.manual) && (data.identification === 'manual' || data.dhl_verification === 'unverified');
          message(data.duplicate ? item.code + ': ya registrado; no suma otra vez.' : item.code + ' · BL ' + data.bl_awb + ' · ' + progress(row).text + ' bultos.'
            + (item.manual ? ' Registro manual auditado.' + (unverified ? ' Sin verificar por DHL.' : '') : manual ? ' BL elegida explicitamente.' : unverified ? ' Sin verificar por DHL.' : data.dhl_verification === 'verified' ? ' Verificado por DHL.' : ''), data.duplicate || unverified ? 'warning' : 'success');
          if (shipmentId) loadDhl(shipmentId, false);
        }
      } catch (error) {
        outcome = resultFor(readingCurrent(item) ? error.canIdentify ? 'choice' : 'failed' : 'stale', item,
          {error:error.message, canIdentify:error.canIdentify === true});
        const {resolve, ...reading} = item;
        const previous = failed.find(other => sameReading(other, item));
        if (previous) { Object.assign(previous, reading, {error:error.message, canIdentify:error.canIdentify === true}); }
        else failed.push({...reading, key:++failureId, error:error.message, canIdentify:error.canIdentify === true});
        if (readingCurrent(item)) {
          message(item.code + ': ' + error.message, 'error');
          notify(error.message, 'error');
          const field = $('scanTruckPackageCode');
          if (!item.manual && field && !field.value && pending.length === 0) { field.value = item.code; field.select(); }
        }
      }
      item.resolve?.(outcome);
      activeReading = null;
      if (inView(item.guide)) update();
    }
    draining = false;
    update();
    if (lastReading && readingCurrent(lastReading)) $('scanTruckPackageCode')?.focus();
  }
  async function retry(key) {
    if (locked()) return;
    const item = failed.find(entry => entry.key === key);
    if (!item || !inView(item.guide)) return;
    pending.push({...item, blCode:undefined, revision:contextRevision});
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
    if (hasDrafts()) { message('Hay codigos sin registrar. Registralos o vacía el campo antes de terminar la llegada.', 'error'); return; }
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
    rememberManualDraft(); contextRevision++; manualSequence++; manualPage = null;
    const guide = summary.truck_guide || '', status = guideStatus(summary.guide_status);
    if (currentGuide !== guide) {
      currentGuide = guide; scannerSelectedShipmentId = null; receivingShipmentId = null; entryMode = 'piece';
      packageDrafts.piece = ''; packageDrafts.bl = ''; blPackageDrafts.clear();
      manualDrafts.clear();
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
    const totalNode = $('scanTotal');
    if (totalNode) {
      const expected = document.createElement('span'); expected.id = 'scanTotalExpected';
      totalNode.after(expected);
      const label = totalNode.parentElement.querySelector('small');
      if (label) label.id = 'scanTotalLabel';
    }
    const blCounter = $('scanBlCount');
    if (blCounter) {
      const label = blCounter.parentElement.querySelector('span');
      if (label) label.id = 'scanBlProgressLabel';
      const identity = $('scanLastBl')?.parentElement;
      if (identity) {
        const brand = document.createElement('span'); brand.id = 'scanBlBrands'; brand.className = 'scan-brand-name';
        const previous = document.createElement('small'); previous.id = 'scanBlPrevious';
        identity.append(brand, previous);
      }
    }
    document.querySelectorAll('.scan-location-card').forEach(card => {
      const row = list.find(item => Number(item.id) === Number(card.dataset.truckBlRow || card.dataset.reviewBl));
      if (!row) return;
      const info = document.createElement('p'); info.className = 'scan-card-progress';
      info.innerHTML = `<span>${esc(brands(row))}</span>${progressHtml(row)}`;
      card.querySelector('header')?.after(info);
    });
    if (status === 'ZONA_RECEPCION') mountLocations();
    if (arrival) {
      const chooser = document.createElement('div'); chooser.className = 'scan-manual-bl';
      chooser.innerHTML = '<label class="field" for="scanManualBl">BL del camion<select class="control" id="scanManualBl"></select></label><button type="button" class="ghost scan-submit" id="scanManualUseBl">Elegir BL</button>';
      $('scanBlEntry').append(chooser);
      $('scanManualUseBl').onclick = useManualBl;
      mountManualEntry();
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
    const maker = document.createElement('p'); maker.className = 'scan-brand-name scan-bl-brands';
    maker.textContent = brands(selected);
    hero.querySelector('h1')?.after(maker);
    const extra = document.createElement('details');
    extra.className = 'scan-bl-extra';
    const label = document.createElement('summary');
    label.textContent = 'Más información y controles de la BL';
    extra.append(label);
    [hero.querySelector('.title p:not(.scan-bl-brands)'),hero.querySelector('.grid'),hero.querySelector('.flow'),
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
    hasDrafts, getCameraState, loadManualPieces, selectManualPiece, confirmManualPiece, useManualBl,
    identify, confirmIdentification, closeIdentification, saveLocations, hasPending:() => locked() || failed.length > 0};
})();
