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
  const requiresCount = line => Number(expected(line)) > 0 || Number(line.attention_verified_qty ?? line.received_qty) > 0;
  const reference = line => `OV ${escapeHtml(line.ov_number || '—')} · IP ${escapeHtml(line.ip_reference || '—')}`;
  function countLines(shipment) {
    const seen = new Set();
    const attentionId = idOf(shipment.attention_id ?? shipment.active_attention_id);
    return (shipment.lines || []).filter(line => {
      const id = idOf(line.id);
      if (!id || seen.has(id) || line.in_selected_attention === false || line.in_selected_attention === 0 ||
          (attentionId && idOf(line.attention_id) && idOf(line.attention_id) !== attentionId)) return false;
      seen.add(id);
      return true;
    });
  }
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
    return target.lines.includes(line) && target.editableIds.has(String(line.id)) && !!input &&
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
    const lines = countLines(shipment);
    const previous = view;
    const sameContext = previous && previous.shipmentId === now.shipmentId &&
      previous.attentionId === now.attentionId && previous.status === shipment.app_status;
    if (previous) previous.resultHtml = byId('receptionNpScanResult')?.innerHTML || previous.resultHtml || '';
    // Keep the queue object used by an in-flight save across a same-attention render.
    if (previous && !sameContext && (previous.queue.length || previous.issue)) {
      return '<section class="notice" role="alert">Hay lecturas NP pendientes en otra atencion. Vuelve a esa atencion para resolverlas.</section>';
    }
    if (sameContext && previous.queue.length && !pending && !previous.issue) {
      previous.issue = 'Hay una lectura pendiente de verificar. Reintenta o descarta explicitamente.';
      previous.issueKind = 'error'; previous.issueRetryable = true;
    }
    const resultHtml = sameContext ? previous.resultHtml : '';
    const issueHtml = sameContext && previous.issue ? issueMarkup(previous) : '';
    const state = {...now, shipment, lines, status: shipment.app_status, editableIds,
      serial: sameContext ? previous.serial : ++serial};
    if (sameContext) {
      Object.assign(previous, state);
      previous.matches = previous.matches.map(line => lines.find(item => String(item.id) === String(line.id))).filter(Boolean);
      previous.line = lines.find(line => String(line.id) === String(previous.line?.id)) || null;
      for (const line of lines) if (line.np_scanned_at) previous.scanned.add(String(line.id));
      view = previous;
    } else view = {...state,
      matches: [], line: null, queue: [], issue: null, lastCode: '', automatic: false,
      issueKind: null, lastResult: null,
      fallback: false, fallbackQuery: '', fallbackPage: 0, fallbackLines: [],
      unreceived: new Map(lines.filter(line => line.np_unreceived_reason).map(line => [String(line.id), line.np_unreceived_reason])),
      scanned: new Set(lines.filter(line => line.np_scanned_at).map(line => String(line.id)))};
    const enabled = !pending && now.valid && now.shipment === shipment &&
      editableIds.size > 0 && bridge.panelEditable('sistema');
    return `<section class="card reception-panel" data-reception-panel="sistema" id="receptionNpScanPanel" data-np-view="${view.serial}">
      <div class="section-title"><div><span class="eyebrow">Inicio de conteo</span><h2>Conteo por NP</h2></div></div>
      <div class="np-scan-progress" id="receptionNpProgress" aria-live="polite">${progressText(view)}</div>
      <div class="form-grid np-scan-control"><div class="field"><label for="scanReceptionNp">Escanear NP</label>
      <input class="control" id="scanReceptionNp" autocomplete="off" placeholder="NP" aria-describedby="receptionNpIssue receptionNpMissing" onkeydown="handleReceptionNpScan(event)" ${enabled ? '' : 'disabled'}></div></div>
      <div id="receptionNpIssue" role="status">${issueHtml}</div><div id="receptionNpMissing" role="status"></div>
      <div id="receptionNpUnreceived" role="status">${escapeHtml(unreceivedText(view))}</div>
      <div id="receptionNpScanResult" aria-live="polite">${resultHtml || (enabled ? '' : 'No hay NP editables en este paso.')}</div>
      <button class="ghost" id="receptionNpFallbackToggle" type="button" aria-controls="receptionNpFallback" aria-expanded="false" onclick="WmsNpScan.openFallback()" ${enabled ? '' : 'disabled'}>Elegir NP de la lista</button>
      <div id="receptionNpFallback" style="max-width:620px" hidden></div>
      <button class="ghost" id="receptionNpReview" type="button" onclick="WmsNpScan.review()" ${enabled ? '' : 'disabled'}>Corregir NP</button>
      <button class="ghost" id="receptionNpPartial" type="button" onclick="WmsNpScan.continuePartial()" ${enabled && partialAvailable(view) ? '' : 'hidden style="display:none"'}>Continuar con recibidos</button>
      ${filterHtml}<details><summary>Ver listado completo</summary>${template.innerHTML}</details>${actionsHtml}
    </section>`;
  }

  function message(text, level = 'warning') { bridge.notify(text, level); }

  function closeFallback(target) {
    target.fallback = false;
    if (byId('receptionNpFallback')) byId('receptionNpFallback').hidden = true;
    byId('receptionNpFallbackToggle')?.setAttribute?.('aria-expanded', 'false');
  }

  function openFallback() {
    const target = view;
    if (!isCurrent(target) || !bridge.panelEditable('sistema') || pending) return false;
    if (target.queue.length || target.issue || target.line) {
      message('Resuelve o descarta la lectura pendiente y guarda la correccion antes de elegir otro NP.');
      return false;
    }
    if (target.fallback && !byId('receptionNpFallback')?.hidden) {
      closeFallback(target); byId('receptionNpFallbackToggle')?.focus(); return;
    }
    target.fallback = true; target.fallbackQuery = ''; target.fallbackPage = 0;
    const panel = byId('receptionNpFallback');
    panel.hidden = false;
    panel.innerHTML = '<div class="field"><label for="receptionNpFallbackSearch">Buscar en esta atencion</label><input class="control" id="receptionNpFallbackSearch" type="search" autocomplete="off" oninput="WmsNpScan.filterFallback(this.value)"></div><div id="receptionNpFallbackList"></div>';
    byId('receptionNpFallbackToggle')?.setAttribute?.('aria-expanded', 'true');
    filterFallback(''); byId('receptionNpFallbackSearch')?.focus();
  }

  function filterFallback(query, page = 0) {
    const target = view;
    if (!isCurrent(target) || !target.fallback || pending || !Number.isInteger(page)) return;
    target.fallbackQuery = String(query); target.fallbackPage = Math.max(0, page);
    const term = normalize(query);
    const candidates = target.lines.filter(line => requiresCount(line) && allowed(target, line) &&
      !target.scanned.has(String(line.id)) && !target.unreceived.has(String(line.id)) &&
      [line.np_code, line.ov_number, line.ip_reference].some(value => normalize(value).includes(term)));
    const pages = Math.max(1, Math.ceil(candidates.length / 50));
    target.fallbackPage = Math.min(target.fallbackPage, pages - 1);
    target.fallbackLines = candidates.slice(target.fallbackPage * 50, (target.fallbackPage + 1) * 50);
    byId('receptionNpFallbackList').innerHTML = `<p role="status">Pedidos pendientes: ${candidates.length} · Pagina ${target.fallbackPage + 1}/${pages}</p><div class="np-matches">${target.fallbackLines.map(line =>
      `<button class="ghost np-match" style="justify-content:stretch" type="button" onclick="WmsNpScan.selectFallback(${Number(line.id)},${target.serial})"><strong>Registrar NP ${escapeHtml(line.np_code)}</strong><span>${escapeHtml(line.description)}</span><span>${line.ov_number ? `OV ${escapeHtml(line.ov_number)}` : 'Sin OV'}</span><span class="help-guidance">IP ${escapeHtml(line.ip_reference || '')} · Linea ${escapeHtml(line.id)}</span><span>Cantidad: ${escapeHtml(initialQuantity(line))} · Requerido: ${escapeHtml(expected(line))}</span>${stockStatus(line)}</button>`
    ).join('')}</div>${pages > 1 ? `<div class="actions"><button class="ghost" type="button" onclick="WmsNpScan.fallbackPage(-1)" ${target.fallbackPage ? '' : 'disabled'}>Anterior</button><button class="ghost" type="button" onclick="WmsNpScan.fallbackPage(1)" ${target.fallbackPage < pages - 1 ? '' : 'disabled'}>Siguiente</button></div>` : ''}`;
  }

  function fallbackPage(delta) {
    if (view && Number.isInteger(delta)) filterFallback(view.fallbackQuery, view.fallbackPage + delta);
  }

  function selectFallback(lineId, viewSerial) {
    const target = view;
    if (!isCurrent(target) || !target.fallback || target.serial !== viewSerial || pending ||
        target.queue.length || target.issue || target.line || !Number.isSafeInteger(lineId)) return false;
    const line = target.fallbackLines.find(item => Number(item.id) === lineId);
    if (!line || !allowed(target, line) || target.scanned.has(String(line.id)) || target.unreceived.has(String(line.id))) return false;
    target.queue.push({code: line.np_code, lineId: String(line.id), source: 'list'});
    target.lastResult = null;
    closeFallback(target); updateProgress(target);
    return drain();
  }

  function handle(event) {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    const target = view;
    const input = event.currentTarget;
    if (!isCurrent(target) || input !== byId('scanReceptionNp') || input.disabled) return;
    const code = String(input.value).trim();
    if (!code) return;
    const result = enqueue(target, code);
    // Keep an unaccepted read visible when a correction or a full queue blocks it.
    if (result !== false) input.value = '';
    return result;
  }

  function enqueue(target, code) {
    if (target.line && !target.automatic) { message('Guarda la correccion del NP antes de continuar.'); return false; }
    // A repeated HID/camera callback must not choose the next order while this code is unresolved.
    if (target.queue.some(item => resolveCode(target, item.code) === resolveCode(target, code))) {
      message('Este NP ya tiene una lectura pendiente. Resuelvela antes de repetirlo.');
      return;
    }
    if (target.queue.length >= 100) { message('La cola esta llena; espera a que terminen las lecturas.', 'error'); return false; }
    closeFallback(target);
    target.lastResult = null;
    target.queue.push({code});
    updateProgress(target);
    return drain();
  }

  function status() {
    const target = view;
    const active = !!bridge && isCurrent(target) && bridge.panelEditable('sistema') &&
      target.editableIds.size > 0 && (pending === target || target.lines.some(line => allowed(target, line)));
    const phase = !active ? 'inactive' : pending ? 'saving' : target.issue ? target.issueKind || 'error'
      : target.queue.length ? 'queued' : target.line ? 'editing' : 'ready';
    return Object.freeze({phase, canReceive: phase === 'ready', queueLength: target?.queue.length || 0,
      context: active ? Object.freeze({shipmentId: target.shipmentId, attentionId: target.attentionId,
        viewId: target.serial}) : null,
      code: target?.queue[0]?.code || null, lineId: target?.queue[0]?.lineId || null,
      error: target?.issue || null, lastResult: target?.lastResult || null});
  }

  async function receiveCamera(code, capturedContext) {
    const before = status();
    if (!before.context || !capturedContext ||
        idOf(capturedContext.shipmentId) !== before.context.shipmentId ||
        idOf(capturedContext.attentionId) !== before.context.attentionId ||
        capturedContext.viewId !== before.context.viewId)
      return {...before, accepted: false, reason: 'stale-context'};
    if (!before.canReceive) return {...before, accepted: false, reason: 'busy'};
    const value = String(code ?? '').trim();
    if (!value) return {...before, accepted: false, reason: 'empty-code'};
    await enqueue(view, value);
    return {...status(), accepted: true};
  }

  function groups(target) {
    const result = new Map();
    for (const line of target.lines) {
      if (!target.editableIds.has(String(line.id)) || !requiresCount(line)) continue;
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
    const partial = byId('receptionNpPartial');
    if (partial) {
      const visible = bridge.panelEditable('sistema') && partialAvailable(target);
      partial.hidden = !visible;
      partial.style?.setProperty('display', visible ? '' : 'none');
    }
  }

  function partialAvailable(target) {
    return target.status === 'REVISION SISTEMA' && !!target.attentionId && missing(target).length>0 &&
      target.lines.some(line=>target.scanned.has(String(line.id)) &&
        Number(byId(`qty-${line.id}`)?.value ?? line.attention_verified_qty ?? line.received_qty)>0);
  }

  async function continuePartial() {
    const target=view;
    if (!isCurrent(target) || !bridge.panelEditable('sistema')) return false;
    if (hasPending() || target.line) { message('Guarda la correccion y resuelve las lecturas pendientes antes de continuar.'); return false; }
    if (!partialAvailable(target)) { message('Escanea los NP recibidos antes de confirmar un conteo parcial.'); return false; }
    const drafts=target.lines.filter(line=>target.scanned.has(String(line.id))).some(line=>
      ['qty-','reason-','count-location-'].some(prefix=>{
        const field=byId(prefix+line.id);return field && field.value!==field.defaultValue;
      }));
    if (drafts) { message('Guarda las correcciones de los NP leidos antes de continuar.'); return false; }
    const lines=missing(target).flatMap(group=>group.lines.filter(line=>
      !target.scanned.has(String(line.id)) && !target.unreceived.has(String(line.id))));
    const names=[...new Set(lines.map(line=>line.np_code))];
    if (!global.confirm(`No recibidos en esta llegada: ${names.slice(0,10).join(', ')}${names.length>10?'...':''}.\n\nQuedaran ${lines.length} pedidos pendientes para otra llegada, con cantidad recibida cero. Los NP recibidos continuaran a EM. La BL no se marcara completa.\n\n¿Confirmas que esos repuestos no llegaron?`)) return false;
    const controls=Array.from(byId('receptionNpScanPanel').querySelectorAll('input,button,select,textarea'))
      .map(element=>({element,disabled:element.disabled}));
    pending=target;controls.forEach(({element})=>{element.disabled=true;});
    const button=byId('receptionNpPartial');if(button)button.textContent='Guardando...';
    let saved=false;
    try {
      const response=await bridge.api(bridge.shipmentUrl('/count/partial'),{method:'POST',
        headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmed:true,
          attention_id:Number(target.attentionId),line_ids:lines.map(line=>Number(line.id))})});
      const data=await response.json();
      if (!response.ok) throw Error(data.error || 'No se pudo confirmar el conteo parcial.');
      if (!isCurrent(target)) return false;
      if (idOf(data.id)!==target.shipmentId || idOf(data.attention_id)!==target.attentionId || data.app_status!=='EM')
        throw Error('Reabre la atencion para comprobar el resultado del conteo parcial.');
      saved=true;
      pending=null;
      if (typeof bridge.onPartialSaved==='function') await bridge.onPartialSaved(data,{isCurrent:()=>isCurrent(target)});
      message('Conteo parcial guardado. Faltantes pendientes.','success');
      return true;
    } catch(error) {
      if(isCurrent(target)) message((saved?'El servidor guardo el conteo. Reabre la atencion para verificar. ': '')+error.message,'error');
      return false;
    } finally {
      pending=null;
      if(isCurrent(target)) {
        controls.forEach(({element,disabled})=>{element.disabled=disabled;});
        if(button)button.textContent='Continuar con recibidos';
      }
    }
  }

  function issue(target, text, retryable = true, kind = 'error') {
    target.issue = text;
    target.issueKind = kind;
    target.issueRetryable = retryable;
    const node = byId('receptionNpIssue');
    if (node) node.innerHTML = issueMarkup(target);
    const state = byId('receptionNpScanResult')?.querySelector?.('[data-np-save-state]');
    if (kind === 'error' && state) state.textContent = 'Lectura pendiente de resolver.';
  }

  function issueMarkup(target) {
    return `<p class="notice">${escapeHtml(target.issue)}</p><div class="actions">${target.issueRetryable ? '<button class="ghost" type="button" onclick="WmsNpScan.retry()">Reintentar lectura</button>' : ''}<button class="ghost" type="button" onclick="WmsNpScan.discard()">Descartar lectura</button></div>`;
  }

  function clearIssue(target) {
    target.issue = null;
    target.issueKind = null;
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
    view.queue.shift(); view.line = null; view.matches = [];
    clearIssue(view);
    if (byId('receptionNpScanResult')) byId('receptionNpScanResult').textContent = '';
    return drain();
  }

  function review(value) {
    const target = view;
    if (pending || !isCurrent(target) || target.queue.length || target.issue) return;
    const code = value ?? (byId('scanReceptionNp')?.value.trim() || target.lastCode);
    if (!code) { message('Indica el NP que necesitas corregir.'); return; }
    closeFallback(target);
    return lookup(code, false);
  }

  function resolveCode(target, value) {
    const literal = normalize(value);
    return (target.shipment.lines || []).some(line => normalize(line.np_code) === literal)
      ? literal : normalize(String(value).trim().replace(/^\]d1/i, ''));
  }

  function lookup(value, automatic) {
    const target = view;
    if (!isCurrent(target)) return false;
    target.automatic = automatic;
    const code = resolveCode(target, value);
    // Keep distinct source IDs, even when OV/IP/quantities look identical.
    const matches = target.lines.filter(line => normalize(line.np_code) === code && (!automatic || requiresCount(line)));
    target.matches = matches;
    target.line = null;
    const result = byId('receptionNpScanResult');
    if (!target.matches.length) {
      const inOtherAttention = (target.shipment.lines || []).some(line => normalize(line.np_code) === code);
      const inThisAttention = target.lines.some(line => normalize(line.np_code) === code);
      result.textContent = inThisAttention ? 'Este NP no tiene cantidad pendiente en esta llegada.' : inOtherAttention
        ? 'Este NP pertenece a otra llegada de la BL. Revisa la atencion seleccionada.'
        : 'El NP no pertenece a esta BL / atención.';
      if (automatic) issue(target, `NP ${value}: ${result.textContent}`, false);
      else { message(result.textContent, 'error'); byId('scanReceptionNp')?.select(); }
      return false;
    }
    const chosenId = automatic ? target.queue[0]?.lineId : null;
    if (chosenId) {
      const index = matches.findIndex(line => String(line.id) === chosenId);
      if (index < 0) { issue(target, 'El pedido seleccionado ya no esta en esta atencion. Descarta la lectura y revisa la BL.', false); return false; }
      return choose(index);
    }
    if (automatic) {
      target.matches = matches.filter(line => !target.scanned.has(String(line.id)) && !target.unreceived.has(String(line.id)));
      if (!target.matches.length) {
        target.queue.shift(); target.line = null;
        target.lastResult = Object.freeze({code: value, outcome: 'duplicate'});
        result.textContent = `NP ${value}: ya revisado; la cantidad no cambia.`;
        updateProgress(target); return true;
      }
    }
    // A repeated camera/HID callback cannot implicitly consume the remaining OV.
    if (target.matches.length === 1 && (!automatic || matches.length === 1)) return choose(0);
    if (automatic) issue(target, `NP ${value}: selecciona el pedido correspondiente.`, false, 'choice');
    result.innerHTML = `<h3>NP ${escapeHtml(target.matches[0].np_code)}</h3><p>${escapeHtml(target.matches[0].description || '—')}</p><p>Pedidos ${automatic ? 'pendientes' : 'de esta atencion'}: ${target.matches.length}</p><div class="np-matches">${target.matches.map((line, index) =>
      `<button type="button" class="ghost np-match" onclick="WmsNpScan.choose(${index},${target.serial})"><strong>${line.ov_number ? `OV ${escapeHtml(line.ov_number)}` : 'Sin OV'}</strong><span>Requerido: ${escapeHtml(expected(line))} · Pedido ${index + 1}</span><span class="help-guidance">${line.ip_reference ? `IP ${escapeHtml(line.ip_reference)} · ` : ''}Linea ${escapeHtml(line.id)}</span>${stockStatus(line)}</button>`
    ).join('')}</div>`;
    return false;
  }

  function choose(index, viewSerial = view?.serial) {
    const target = view;
    if (pending || !isCurrent(target) || target.serial !== viewSerial || !Number.isInteger(index) ||
        (target.automatic && !target.queue.length)) return;
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
      result.innerHTML = `<h3>NP ${escapeHtml(line.np_code)}</h3><p>${escapeHtml(line.description || '—')}</p><p>Requerido: ${escapeHtml(expected(line))} ${stockStatus(line)}</p><p data-np-save-state>Guardando lectura...</p>`;
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
    const queued = automatic ? target.queue[0] : null;
    if (automatic && !queued) return false;
    const quantity = quantityValue(automatic ? queued.body?.received_qty ?? initialQuantity(line) : input?.value);
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
    const payload = automatic ? (queued.body ??= body) : body;
    const controls = Array.from(byId('receptionNpScanPanel').querySelectorAll('input,button,select,textarea'))
      .map(element => ({element, disabled: element.disabled}));
    pending = target;
    controls.forEach(({element}) => { if (!automatic || element.id !== 'scanReceptionNp') element.disabled = true; });
    let saved = false;
    try {
      // String body prevents template api() from overwriting the captured attention_id.
      const url = automatic ? (queued.url ??= bridge.shipmentUrl('/lines/' + encodeURIComponent(line.id)))
        : bridge.shipmentUrl('/lines/' + encodeURIComponent(line.id));
      const response = await bridge.api(url, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'No se pudo guardar el NP.');
      if (!isCurrent(target)) return;
      const responseAttention = idOf(data.attention_id ?? data.active_attention_id);
      if (idOf(data.id) !== target.shipmentId || responseAttention !== target.attentionId) {
        message('No se pudo verificar el guardado: la respuesta corresponde a otra atención. Reabre la atención para verificar.', 'warning');
        if (automatic) issue(target, 'No se pudo verificar esta lectura. Reintenta para consultar su registro.');
        return false;
      }
      const savedLine = (data.lines || []).find(item => String(item.id) === String(line.id));
      if (savedLine && (savedLine.in_selected_attention === false || savedLine.in_selected_attention === 0 ||
          (idOf(savedLine.attention_id) && idOf(savedLine.attention_id) !== target.attentionId)))
        throw new Error('El servidor devolvio una linea de otra atencion.');
      if (automatic && !savedLine?.np_scanned_at) throw new Error('El servidor no confirmo la lectura NP.');
      const recordedQty = automatic ? quantityValue(savedLine.attention_verified_qty ?? savedLine.received_qty) : quantity;
      if (recordedQty === null) throw new Error('La cantidad guardada no es valida.');
      saved = true;
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
        target.lastResult = Object.freeze({code: queued.code, lineId: String(line.id), outcome: 'saved',
          source: queued.source || 'scan', quantity: recordedQty});
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
        if (automatic) byId('receptionNpScanResult').innerHTML = `<h3>NP ${escapeHtml(line.np_code)}</h3><p>${escapeHtml(line.description || '—')}</p><p>Requerido: ${escapeHtml(expected(line))} ${stockStatus(line)}</p><p>${queued.source === 'list' ? 'Seleccion de lista guardada' : 'Lectura guardada'} · Cantidad ${escapeHtml(recordedQty)}</p>`;
        else { byId('receptionNpScanResult').textContent = 'NP guardado.'; byId('scanReceptionNp').value = ''; }
      }
      return true;
    } catch (error) {
      if (isCurrent(target)) message(saved
        ? 'El NP se guardó, pero falló la actualización visual. Reabre la atención para verificar.'
        : String(error.message || 'No se pudo guardar el NP.'), 'error');
      if (automatic && isCurrent(target) && target.queue[0] === queued) issue(target, `Lectura ${line.np_code} pendiente: ${error.message || 'revisa la conexion'}`);
      if (automatic && isCurrent(target) && target.queue[0] !== queued) {
        target.line = null;
        const state = byId('receptionNpScanResult')?.querySelector?.('[data-np-save-state]');
        if (state) state.textContent = 'Guardado confirmado; actualizacion visual pendiente.';
        return true;
      }
      return false;
      // Keep manually entered quantity and reason on request/JSON/network failure.
    } finally {
      pending = null;
      if (isCurrent(target) && bridge.panelEditable('sistema')) {
        controls.forEach(({element, disabled}) => { element.disabled = disabled; });
        const canScan = target.lines.some(item => allowed(target, item));
        for (const id of ['scanReceptionNp', 'receptionNpFallbackToggle', 'receptionNpReview']) {
          if (byId(id)) byId(id).disabled = !canScan;
        }
        if (!target.line) byId('scanReceptionNp')?.focus();
      } else if (view && isCurrent(view) && bridge.panelEditable('sistema')) {
        // A new render during the request started with its scanner disabled.
        const canScan = (view.shipment.lines || []).some(item => allowed(view, item));
        for (const id of ['scanReceptionNp', 'receptionNpFallbackToggle', 'receptionNpReview']) {
          if (byId(id)) byId(id).disabled = !canScan;
        }
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
  global.WmsNpScan = Object.freeze({init, render, countLines, handle, review, choose, save, retry, discard, hasPending, canComplete, continuePartial,
    openFallback, filterFallback, fallbackPage, selectFallback, status, receiveCamera});
})(window);
