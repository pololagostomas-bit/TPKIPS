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
  const byId = id => document.getElementById(id);
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g,
    char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
  const normalize = value => String(value ?? '').replace(/\s+/g, '').toUpperCase();
  const idOf = value => value == null || value === '' ? null : String(value);
  const expected = line => line.attention_planned_qty ?? line.expected_qty ?? 0;

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
    // Defensive cleanup for old callers; the integration should omit this block.
    template.content.querySelectorAll('.np-scan-control, #scanReceptionNp, [data-camera-for="scanReceptionNp"]')
      .forEach(element => element.remove());
    const editableIds = new Set(Array.from(template.content.querySelectorAll('input[id^="qty-"]'))
      .filter(input => !input.disabled && !input.readOnly && input.type === 'number')
      .map(input => input.id.slice(4)));
    const now = context();
    view = {...now, shipment, status: shipment.app_status, editableIds, serial: ++serial,
      matches: [], line: null};
    const enabled = !pending && now.valid && now.shipment === shipment &&
      editableIds.size > 0 && bridge.panelEditable('sistema');
    return `<section class="card reception-panel" data-reception-panel="sistema" id="receptionNpScanPanel" data-np-view="${view.serial}">
      <div class="section-title"><div><span class="eyebrow">Inicio de conteo</span><h2>Conteo por NP</h2></div></div>
      <p class="notice help-guidance">Escanea un NP, confirma la línea e ingresa la cantidad contada. Solo se guarda esa línea.</p>
      <div class="form-grid np-scan-control"><div class="field"><label for="scanReceptionNp">Escanear NP</label>
      <input class="control" id="scanReceptionNp" autocomplete="off" placeholder="Escanea o escribe el NP y pulsa Enter" onkeydown="handleReceptionNpScan(event)" ${enabled ? '' : 'disabled'}></div></div>
      <div id="receptionNpScanResult" aria-live="polite">${enabled ? 'Esperando un NP.' : 'No hay cantidades editables en el contexto actual.'}</div>
      <details><summary>Ver listado completo</summary>${template.innerHTML}</details>
    </section>`;
  }

  function message(text, level = 'warning') { bridge.notify(text, level); }

  function handle(event) {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    const target = view;
    const input = event.currentTarget;
    if (pending || !isCurrent(target) || input !== byId('scanReceptionNp') || input.disabled) return;
    const code = normalize(input.value);
    if (!code) return;
    // Do not filter duplicates by editability: the operator must see ambiguity.
    target.matches = (target.shipment.lines || []).filter(line => normalize(line.np_code) === code);
    target.line = null;
    const result = byId('receptionNpScanResult');
    if (!target.matches.length) {
      result.textContent = 'El NP no pertenece a esta BL / atención.';
      message(result.textContent, 'error');
      input.select();
      return;
    }
    if (target.matches.length === 1) { choose(0); return; }
    result.innerHTML = `<p>NP repetido: elige una línea antes de ingresar la cantidad.</p><div class="actions">${target.matches.map((line, index) =>
      `<button type="button" class="ghost" onclick="WmsNpScan.choose(${index})">${escapeHtml(line.np_code)} · OV ${escapeHtml(line.ov_number || '—')} · IP ${escapeHtml(line.ip_reference || '—')} · ${escapeHtml(line.description || '—')} · Línea ${escapeHtml(line.id)}</button>`
    ).join('')}</div>`;
  }

  function choose(index) {
    const target = view;
    if (pending || !isCurrent(target) || !Number.isInteger(index)) return;
    const line = target.matches[index];
    if (!line) return;
    target.line = null;
    const result = byId('receptionNpScanResult');
    if (!allowed(target, line)) {
      message('Esta línea no tiene una cantidad editable en el paso actual.');
      if (target.matches.length === 1) result.textContent = 'Esta línea no es editable.';
      return;
    }
    target.line = line;
    result.innerHTML = `<h3>NP ${escapeHtml(line.np_code)}</h3>
      <p>${escapeHtml(line.description || '—')}</p>
      <p>OV ${escapeHtml(line.ov_number || '—')} · IP ${escapeHtml(line.ip_reference || '—')} · Línea ${escapeHtml(line.id)}</p>
      <p>Requerido: ${escapeHtml(expected(line))} · Ubicación de referencia: ${escapeHtml(bridge.locationLabel ? bridge.locationLabel(line) : line.default_location || 'Sin ubicación')}</p>
      <div class="form-grid"><div class="field"><label for="receptionNpQuantity">Cantidad contada (entero)</label>
      <input class="control" id="receptionNpQuantity" type="number" min="0" step="1" inputmode="numeric" value="" autocomplete="off" onkeydown="if(event.key==='Enter'){event.preventDefault();WmsNpScan.save()}"></div>
      <div class="field"><label for="receptionNpReason">Observación</label><input class="control" id="receptionNpReason" value="${escapeHtml(byId(`reason-${line.id}`)?.value ?? line.blocked_reason ?? '')}" placeholder="Solo si existe diferencia"></div></div>
      <div class="actions"><button class="primary" type="button" id="receptionNpSave" onclick="WmsNpScan.save()">Guardar solo esta línea</button></div>`;
    byId('receptionNpQuantity')?.focus();
  }

  function quantityValue(value) {
    const text = String(value ?? '').trim();
    const number = Number(text);
    return /^\d+$/.test(text) && Number.isSafeInteger(number) ? number : null;
  }

  async function save() {
    const target = view;
    const line = target?.line;
    if (pending || !line || !allowed(target, line)) return;
    const input = byId('receptionNpQuantity');
    const quantity = quantityValue(input?.value);
    if (quantity === null) {
      message('Ingresa manualmente una cantidad entera, igual o mayor que cero.', 'error');
      input?.focus();
      return;
    }
    const reason = byId('receptionNpReason')?.value || '';
    const body = {received_qty: quantity, reason};
    if (target.attentionId !== null) body.attention_id = target.attentionId;
    const controls = Array.from(byId('receptionNpScanPanel').querySelectorAll('input,button,select,textarea'))
      .map(element => ({element, disabled: element.disabled}));
    pending = target;
    controls.forEach(({element}) => { element.disabled = true; });
    let saved = false;
    try {
      // String body prevents template api() from overwriting the captured attention_id.
      const response = await bridge.api(bridge.shipmentUrl('/lines/' + encodeURIComponent(line.id)), {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'No se pudo guardar la línea.');
      saved = true;
      if (!isCurrent(target)) return;
      const responseAttention = idOf(data.attention_id ?? data.active_attention_id);
      if (idOf(data.id) !== target.shipmentId || responseAttention !== target.attentionId) {
        message('La línea se guardó, pero la respuesta corresponde a otro contexto. Reabre la atención para verificar.', 'warning');
        return;
      }
      // Preserve unrelated draft rows. No assignment to selected or bulk refresh.
      byId(`qty-${line.id}`).value = String(quantity);
      const reasonInput = byId(`reason-${line.id}`);
      if (reasonInput) reasonInput.value = reason;
      const difference = byId(`diff-${line.id}`);
      if (difference) difference.textContent = String(quantity - Number(expected(line)));
      message(`NP ${line.np_code} · línea ${line.id} guardada.`, 'success');
      if (typeof bridge.onSaved === 'function') {
        await bridge.onSaved(data, {
          shipmentId: target.shipmentId, attentionId: target.attentionId,
          lineId: line.id, quantity, reason, isCurrent: () => isCurrent(target)
        });
      }
      if (isCurrent(target)) {
        target.line = null;
        byId('receptionNpScanResult').textContent = 'Línea guardada. Escanea el siguiente NP.';
        byId('scanReceptionNp').value = '';
      }
    } catch (error) {
      if (isCurrent(target)) message(saved
        ? 'La línea se guardó, pero falló la actualización visual. Reabre la atención para verificar.'
        : String(error.message || 'No se pudo guardar la línea.'), 'error');
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

  global.WmsNpScan = Object.freeze({init, render, handle, choose, save});
})(window);
