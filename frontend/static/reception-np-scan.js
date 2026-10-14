/* Integration (classic script loaded AFTER reception.html's inline script):
 * WmsNpScan.init({
 *   getContext: () => ({shipment: selected, shipmentId: selectedId,
 *                      attentionId: selectedAttentionId}),
 *   api, shipmentUrl, panelEditable, notify,
 *   onSaved: (data, context) => { ... } // optional, see below
 * });
 * systemLinesCard(s): retain its pre-system branch, otherwise return
 * WmsNpScan.render(s, legacyTableAndActionsHtml). Pass trusted template HTML
 * (escaped row values), NOT the old card/header/scan control. This module
 * returns the entire sistema section, including closed legacy details.
 * handleReceptionNpScan(event): return WmsNpScan.handle(event).
 * init must precede the first integrated render; re-render if already mounted.
 * onSaved runs only for a matching response AND still-current view. By default
 * only the saved row's DOM is updated; selected/other lines are never mutated.
 * Optional callback receives {shipmentId, attentionId, lineId, quantity, reason,
 * isCurrent}. Check isCurrent() immediately before any state/DOM write, also
 * after await. Do not assign the whole response or unconditionally loadDetail:
 * that can discard other unsaved rows. No callback is required for scanning.
 */
(function (global) {
  'use strict';
  let bridge = null;
  let view = null;
  let pending = null;
  let draining = false;
  const byId = id => document.getElementById(id);
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g,
    char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
  const normalize = value => String(value ?? '').replace(/\s+/g, '').toUpperCase();
  const idOf = value => value == null || value === '' ? null : String(value);
  const expected = line => line.attention_planned_qty ?? line.expected_qty ?? 0;
  const reference = line => `OV ${escapeHtml(line.ov_number || '—')} · IP ${escapeHtml(line.ip_reference || '—')}`;
  function initialQuantity(line) {
    const draft = String(byId(`qty-${line.id}`)?.value ?? '').trim();
    if (draft) return draft;
    return quantityValue(expected(line)) ?? '';
  }
  function stockStatus(line) {
    const stock = line.stock_cut_qty ?? line.stock_available_qty;
    return stock != null && Number(stock) === 0 ? '<span class="np-stock-status">Sin stock</span>' : '';
  }

  function init(callbacks) {
    if (pending) throw new Error('No reinicializar durante un guardado NP.');
    for (const name of ['getContext', 'api', 'shipmentUrl', 'panelEditable', 'notify']) {
      if (typeof callbacks?.[name] !== 'function') throw new Error(`Falta WmsNpScan.init.${name}`);
    }
    bridge = {...callbacks};
    view = null;
  }

  function context() {
    const raw = bridge.getContext() || {};
    const shipment = raw.shipment;
    const shipmentId = idOf(raw.shipmentId ?? shipment?.id);
    const attentionId = idOf(raw.attentionId ?? shipment?.attention_id ?? shipment?.active_attention_id);
    // Refuse a transition where the selector and loaded detail disagree.
    const detailAttention = idOf(shipment?.attention_id ?? shipment?.active_attention_id);
    const valid = !!shipmentId && idOf(shipment?.id) === shipmentId &&
      (!detailAttention || detailAttention === attentionId);
    return {shipment, shipmentId, attentionId, valid};
  }

  function isCurrent(target) {
    if (!target || view !== target) return false;
    const now = context();
    return now.valid && now.shipment === target.shipment &&
      now.shipmentId === target.shipmentId && now.attentionId === target.attentionId &&
      now.shipment.app_status === target.status &&
      byId('receptionNpScanPanel')?.dataset.npView === String(target.serial);
  }

  function allowed(target, line) {
    if (!isCurrent(target) || !bridge.panelEditable('sistema')) return false;
    const input = byId(`qty-${line.id}`);
    const lineAttention = idOf(line.attention_id);
    return target.editableIds.has(String(line.id)) && !!input &&
      !input.disabled && !input.readOnly && input.type === 'number' &&
      (!lineAttention || lineAttention === target.attentionId);
  }

  let serial = 0;
  function render(shipment, legacyHtml) {
    if (!bridge) throw new Error('Llama WmsNpScan.init antes de render.');
    const template = document.createElement('template');
    template.innerHTML = String(legacyHtml ?? '');
    const filter = template.content.querySelector?.('.np-filter');
    const filterHtml = filter?.outerHTML || '';
    filter?.remove();
    // Defensive cleanup for old callers; the integration should omit this block.
    template.content.querySelectorAll('.np-scan-control, #scanReceptionNp, [data-camera-for="scanReceptionNp"]')
      .forEach(element => element.remove());
    const actions = template.content.querySelector('[data-count-actions]');
    const actionsHtml = actions?.outerHTML || '';
    actions?.remove();
    const editableIds = new Set(Array.from(template.content.querySelectorAll('input[id^="qty-"]'))
      .filter(input => !input.disabled && !input.readOnly && input.type === 'number')
      .map(input => input.id.slice(4)));
    const now = context();
    view = {...now, shipment, status: shipment.app_status, editableIds, serial: ++serial,
      matches: [], line: null, queue: [], issue: null, lastCode: '', automatic: false,
      unreceived: new Map((shipment.lines || []).filter(line => line.np_unreceived_reason).map(line => [String(line.id), line.np_unreceived_reason])),
      scanned: new Set((shipment.lines || []).filter(line => line.np_scanned_at).map(line => String(line.id)))};
    const enabled = !pending && now.valid && now.shipment === shipment &&
      editableIds.size > 0 && bridge.panelEditable('sistema');
    return `<section class="card reception-panel" data-reception-panel="sistema" id="receptionNpScanPanel" data-np-view="${view.serial}">
      <div class="section-title"><div><span class="eyebrow">Inicio de conteo</span><h2>Conteo por NP</h2></div></div>
      <div class="np-scan-progress" id="receptionNpProgress" aria-live="polite">${progressText(view)}</div>
      <div class="form-grid np-scan-control"><div class="field"><label for="scanReceptionNp">Escanear NP</label>
      <input class="control" id="scanReceptionNp" autocomplete="off" placeholder="NP" onkeydown="handleReceptionNpScan(event)" ${enabled ? '' : 'disabled'}></div></div>
      <div id="receptionNpIssue" role="status"></div><div id="receptionNpMissing" role="status"></div>
      <div id="receptionNpUnreceived" role="status">${escapeHtml(unreceivedText(view))}</div>
      <div id="receptionNpScanResult" aria-live="polite">${enabled ? '' : 'No hay NP editables en este paso.'}</div>
      <button class="ghost" type="button" onclick="WmsNpScan.review()" ${enabled ? '' : 'disabled'}>Corregir NP</button>
      ${filterHtml}<details><summary>Ver listado completo</summary>${template.innerHTML}</details>${actionsHtml}
    </section>`;
  }

  function message(text, level = 'warning') { bridge.notify(text, level); }

  function handle(event) {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    const target = view;
    const input = event.currentTarget;
    if (!isCurrent(target) || input !== byId('scanReceptionNp') || input.disabled) return;
    const code = String(input.value).trim();
    if (!code) return;
    if (target.line && !target.automatic) { message('Guarda la correccion del NP antes de continuar.'); return; }
    if (target.queue.length >= 100) { message('La cola esta llena; espera a que terminen las lecturas.', 'error'); return; }
    target.queue.push({code});
    input.value = '';
    updateProgress(target);
    return drain();
  }

  function groups(target) {
    const result = new Map();
    for (const line of target.shipment.lines || []) {
      if (!target.editableIds.has(String(line.id)) ||
          !(Number(expected(line)) > 0 || Number(line.attention_verified_qty ?? line.received_qty) > 0)) continue;
      const key = normalize(line.np_code);
      if (!result.has(key)) result.set(key, {code: line.np_code || 'Sin NP', lines: []});
      result.get(key).lines.push(line);
    }
    return [...result.values()];
  }

  function missing(target) {
    return groups(target).filter(group => group.lines.some(line => !target.scanned.has(String(line.id)) && !target.unreceived.has(String(line.id))));
  }

  function unreceivedText(target) {
    return [...target.unreceived].map(([id, reason]) => {
      const line = (target.shipment.lines || []).find(item => String(item.id) === id);
      return `No recibido: ${line?.np_code || 'NP'} · ${reason}`;
    }).join('; ');
  }

  function progressText(target) {
    const all = groups(target);
    const read = all.filter(group => group.lines.some(line => target.scanned.has(String(line.id))) &&
      group.lines.every(line => target.scanned.has(String(line.id)) || target.unreceived.has(String(line.id))));
    const absent = all.filter(group => group.lines.every(line => target.unreceived.has(String(line.id)) && !target.scanned.has(String(line.id))));
    return `NP leidos: ${read.length}/${all.length}` +
      (absent.length ? ` · No recibidos: ${absent.length}` : '') +
      (target.queue.length ? ` · Lecturas en cola: ${target.queue.length}` : '');
  }

  function updateProgress(target) {
    if (!isCurrent(target)) return;
    if (byId('receptionNpProgress')) byId('receptionNpProgress').textContent = progressText(target);
    if (byId('receptionNpUnreceived')) byId('receptionNpUnreceived').textContent = unreceivedText(target);
    if (!missing(target).length && byId('receptionNpMissing')) byId('receptionNpMissing').textContent = '';
  }

  function issue(target, text, retryable = true) {
    target.issue = text;
    const node = byId('receptionNpIssue');
    if (node) node.innerHTML = `<p class="notice">${escapeHtml(text)}</p><div class="actions">${retryable ? '<button class="ghost" type="button" onclick="WmsNpScan.retry()">Reintentar lectura</button>' : ''}<button class="ghost" type="button" onclick="WmsNpScan.discard()">Descartar lectura</button></div>`;
  }

  function clearIssue(target) {
    target.issue = null;
    if (byId('receptionNpIssue')) byId('receptionNpIssue').textContent = '';
  }

  async function drain() {
    const target = view;
    if (draining || pending || !isCurrent(target) || target.issue) return;
    draining = true;
    try {
      while (isCurrent(target) && target.queue.length && !target.issue) {
        if (!await lookup(target.queue[0].code, true)) break;
      }
    } finally { draining = false; updateProgress(target); }
  }

  function retry() {
    if (pending || !isCurrent(view)) return;
    clearIssue(view);
    return drain();
  }

  function discard() {
    if (pending || !isCurrent(view)) return;
    view.queue.shift(); view.line = null;
    clearIssue(view);
    return drain();
  }

  function review(value) {
    const target = view;
    if (pending || !isCurrent(target) || target.queue.length || target.issue) return;
    const code = value ?? (byId('scanReceptionNp')?.value.trim() || target.lastCode);
    if (!code) { message('Indica el NP que necesitas corregir.'); return; }
    return lookup(code, false);
  }

  function lookup(value, automatic) {
    const target = view;
    if (!isCurrent(target)) return false;
    target.automatic = automatic;
    const literal = normalize(value);
    const lines = target.shipment.lines || [];
    const code = lines.some(line => normalize(line.np_code) === literal)
      ? literal : normalize(String(value).trim().replace(/^\]d1/, ''));
    // Do not filter duplicates by editability: the operator must see ambiguity.
    target.matches = (target.shipment.lines || []).filter(line => normalize(line.np_code) === code);
    target.line = null;
    const result = byId('receptionNpScanResult');
    if (!target.matches.length) {
      result.textContent = 'El NP no pertenece a esta BL / atención.';
      message(result.textContent, 'error');
      if (automatic) issue(target, `NP ${value}: no pertenece a esta BL / atencion.`, false);
      else byId('scanReceptionNp')?.select();
      return false;
    }
    const chosenId = automatic ? target.queue[0]?.lineId : null;
    if (chosenId) return choose(target.matches.findIndex(line => String(line.id) === chosenId));
    if (target.matches.length === 1) return choose(0);
    if (automatic && target.matches.every(line => target.scanned.has(String(line.id)))) {
      target.queue.shift(); target.line = null;
      result.textContent = `NP ${value}: ya registrado; la cantidad no cambia.`;
      updateProgress(target); return true;
    }
    if (automatic) issue(target, `NP ${value}: selecciona el pedido correspondiente.`, false);
    result.innerHTML = `<p>Este NP pertenece a varios pedidos. Elige el que vas a contar.</p><div class="np-matches">${target.matches.map((line, index) =>
      `<details class="np-match"><summary><strong>${escapeHtml(line.np_code)}</strong><span>${escapeHtml(line.description || '—')}</span><span>Requerido: ${escapeHtml(expected(line))}</span>${stockStatus(line)}</summary><p>${reference(line)}</p><p class="help-guidance">Línea ${escapeHtml(line.id)}</p><button type="button" class="ghost" onclick="WmsNpScan.choose(${index})">Contar este pedido</button></details>`
    ).join('')}</div>`;
    return false;
  }

  function choose(index) {
    const target = view;
    if (pending || !isCurrent(target) || !Number.isInteger(index)) return;
    const line = target.matches[index];
    if (!line) return;
    target.line = null;
    const result = byId('receptionNpScanResult');
    if (!allowed(target, line)) {
      message('Este NP no tiene una cantidad editable en el paso actual.');
      if (target.matches.length === 1) result.textContent = 'Este NP no es editable.';
      if (target.automatic) issue(target, 'Este NP no es editable en esta atencion.', false);
      return false;
    }
    target.line = line;
    target.lastCode = line.np_code;
    if (target.automatic) {
      if (target.scanned.has(String(line.id))) {
        result.textContent = `NP ${line.np_code}: ya registrado; la cantidad no cambia.`;
        target.queue.shift(); target.line = null; clearIssue(target); updateProgress(target);
        if (!draining) return drain();
        return true;
      }
      if (target.queue[0]) target.queue[0].lineId = String(line.id);
      clearIssue(target);
      result.innerHTML = `<h3>NP ${escapeHtml(line.np_code)}</h3><p>${escapeHtml(line.description || '—')}</p><p>Requerido: ${escapeHtml(expected(line))} ${stockStatus(line)}</p><p>Guardando lectura...</p>`;
      return save(true).then(success => { if (success && !draining) drain(); return success; });
    }
    result.innerHTML = `<h3>NP ${escapeHtml(line.np_code)}</h3>
      <p>${escapeHtml(line.description || '—')}</p>
      <p class="np-reference-info help-guidance">${reference(line)} · Línea ${escapeHtml(line.id)}</p>
      <p class="np-required">Requerido: ${escapeHtml(expected(line))} ${stockStatus(line)}</p>
      <div class="form-grid"><div class="field"><label for="receptionNpQuantity">Cantidad contada (entero)</label>
      <input class="control" id="receptionNpQuantity" type="number" min="0" step="1" inputmode="numeric" value="${escapeHtml(initialQuantity(line))}" autocomplete="off" onkeydown="if(event.key==='Enter'){event.preventDefault();WmsNpScan.save()}"></div>
      <div class="field"><label for="receptionNpLocation">Ubicación por defecto</label><input class="control" id="receptionNpLocation" maxlength="120" value="${escapeHtml(byId(`count-location-${line.id}`)?.value ?? (bridge.countLocation ? bridge.countLocation(line) : line.final_location ?? line.default_location ?? ''))}"></div>
      <div class="field"><label for="receptionNpReason">Observación</label><input class="control" id="receptionNpReason" value="${escapeHtml(byId(`reason-${line.id}`)?.value ?? line.blocked_reason ?? '')}" placeholder="Solo si existe diferencia"></div></div>
      <div class="actions"><button class="primary" type="button" id="receptionNpSave" onclick="WmsNpScan.save()">Guardar NP</button></div>`;
    byId('receptionNpQuantity')?.focus();
    byId('receptionNpQuantity')?.select();
  }

  function quantityValue(value) {
    const text = String(value ?? '').trim();
    const number = Number(text);
    return /^\d+$/.test(text) && Number.isSafeInteger(number) ? number : null;
  }

  async function save(automatic = false) {
    const target = view;
    const line = target?.line;
    if (pending || !line || !allowed(target, line)) return;
    const input = byId('receptionNpQuantity');
    const quantity = quantityValue(automatic ? initialQuantity(line) : input?.value);
    if (quantity === null) {
      message('Ingresa una cantidad entera, igual o mayor que cero.', 'error');
      input?.focus();
      if (automatic) issue(target, 'La cantidad predefinida no es un entero valido. Corrigela en el listado.');
      return false;
    }
    const reason = automatic ? byId(`reason-${line.id}`)?.value || '' : byId('receptionNpReason')?.value || '';
    const body = {received_qty: quantity, reason};
    if (automatic) body.scan_np = true;
    if (byId(`count-location-${line.id}`)) body.count_location = automatic
      ? byId(`count-location-${line.id}`).value.trim() : byId('receptionNpLocation')?.value.trim() ?? '';
    if (target.attentionId !== null) body.attention_id = target.attentionId;
    const payload = automatic ? (target.queue[0].body ??= body) : body;
    const controls = Array.from(byId('receptionNpScanPanel').querySelectorAll('input,button,select,textarea'))
      .map(element => ({element, disabled: element.disabled}));
    pending = target;
    controls.forEach(({element}) => { if (!automatic || element.id !== 'scanReceptionNp') element.disabled = true; });
    let saved = false;
    try {
      // String body prevents template api() from overwriting the captured attention_id.
      const response = await bridge.api(bridge.shipmentUrl('/lines/' + encodeURIComponent(line.id)), {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'No se pudo guardar el NP.');
      saved = true;
      if (!isCurrent(target)) return;
      const responseAttention = idOf(data.attention_id ?? data.active_attention_id);
      if (idOf(data.id) !== target.shipmentId || responseAttention !== target.attentionId) {
        message('El NP se guardó, pero la respuesta corresponde a otra atención. Reabre la atención para verificar.', 'warning');
        if (automatic) issue(target, 'No se pudo verificar esta lectura. Reintenta para consultar su registro.');
        return false;
      }
      const savedLine = (data.lines || []).find(item => String(item.id) === String(line.id));
      if (automatic && !savedLine?.np_scanned_at) throw new Error('El servidor no confirmo la lectura NP.');
      const recordedQty = automatic ? quantityValue(savedLine.attention_verified_qty ?? savedLine.received_qty) : quantity;
      if (recordedQty === null) throw new Error('La cantidad guardada no es valida.');
      const recordedReason = automatic ? String(savedLine.blocked_reason ?? payload.reason ?? '') : reason;
      const recordedLocation = automatic && 'final_location' in savedLine
        ? String(savedLine.final_location ?? '') : body.count_location;
      if (savedLine && 'np_unreceived_reason' in savedLine) {
        if (savedLine.np_unreceived_reason) target.unreceived.set(String(line.id), savedLine.np_unreceived_reason);
        else target.unreceived.delete(String(line.id));
        updateProgress(target);
      }
      // Preserve unrelated draft rows. No assignment to selected or bulk refresh.
      byId(`qty-${line.id}`).value = String(recordedQty);
      byId(`qty-${line.id}`).defaultValue = String(recordedQty);
      const locationInput = byId(`count-location-${line.id}`);
      if (locationInput && 'count_location' in body) {
        locationInput.value = recordedLocation;
        locationInput.defaultValue = recordedLocation;
      }
      const reasonInput = byId(`reason-${line.id}`);
      if (reasonInput) { reasonInput.value = recordedReason; reasonInput.defaultValue = recordedReason; }
      const difference = byId(`diff-${line.id}`);
      if (difference) difference.textContent = String(recordedQty - Number(expected(line)));
      if (automatic) {
        target.scanned.add(String(line.id)); target.queue.shift(); clearIssue(target); updateProgress(target);
      }
      message(`NP ${line.np_code} guardado.`, 'success');
      if (typeof bridge.onSaved === 'function') {
        await bridge.onSaved(data, {
          shipmentId: target.shipmentId, attentionId: target.attentionId,
          lineId: line.id, quantity: recordedQty, reason: recordedReason, isCurrent: () => isCurrent(target)
        });
      }
      if (isCurrent(target)) {
        target.line = null;
        if (automatic) byId('receptionNpScanResult').innerHTML = `<h3>NP ${escapeHtml(line.np_code)}</h3><p>${escapeHtml(line.description || '—')}</p><p>Requerido: ${escapeHtml(expected(line))} ${stockStatus(line)}</p><p>Lectura guardada · Cantidad ${escapeHtml(recordedQty)}</p>`;
        else { byId('receptionNpScanResult').textContent = 'NP guardado.'; byId('scanReceptionNp').value = ''; }
      }
      return true;
    } catch (error) {
      if (isCurrent(target)) message(saved
        ? 'El NP se guardó, pero falló la actualización visual. Reabre la atención para verificar.'
        : String(error.message || 'No se pudo guardar el NP.'), 'error');
      if (automatic && isCurrent(target) && target.queue.length) issue(target, `Lectura ${line.np_code} pendiente: ${error.message || 'revisa la conexion'}`);
      return false;
      // Keep manually entered quantity and reason on request/JSON/network failure.
    } finally {
      pending = null;
      if (isCurrent(target) && bridge.panelEditable('sistema')) {
        controls.forEach(({element, disabled}) => { element.disabled = disabled; });
        if (!target.line) byId('scanReceptionNp')?.focus();
      } else if (view && isCurrent(view) && bridge.panelEditable('sistema')) {
        // A new render during the request started with its scanner disabled.
        const canScan = (view.shipment.lines || []).some(item => allowed(view, item));
        if (byId('scanReceptionNp')) byId('scanReceptionNp').disabled = !canScan;
      }
    }
  }

  function hasPending() { return !!pending || !!view?.queue.length || !!view?.issue; }
  function canComplete() {
    if (!isCurrent(view)) { message('Reabre el conteo para comprobar las lecturas.', 'error'); return false; }
    if (hasPending()) { message('Resuelve las lecturas pendientes antes de terminar.', 'warning'); return false; }
    const left = missing(view);
    if (!left.length) return true;
    const text = `Faltan ${left.length} NP por escanear: ${left.slice(0, 10).map(group => group.code).join(', ')}${left.length > 10 ? '...' : ''}`;
    if (byId('receptionNpMissing')) byId('receptionNpMissing').textContent = text;
    message(text, 'warning'); byId('scanReceptionNp')?.focus(); return false;
  }
  if (typeof global.addEventListener === 'function') global.addEventListener('beforeunload', event => {
    if (hasPending()) { event.preventDefault(); event.returnValue = ''; }
  });
  global.WmsNpScan = Object.freeze({init, render, handle, review, choose, save, retry, discard, hasPending, canComplete});
})(window);
