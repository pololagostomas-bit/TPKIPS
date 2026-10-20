/* Administrative decisions use a captured BL/attention, never the live selection. */
(() => {
  if (window.WmsAdminClosure) return;
  const actions = [
    {value:'reconcile', label:'Conciliar cierre validado', allowed:'can_reconcile', blocker:'reconcile_blocker'},
    {value:'retire_test', label:'Retirar registro de prueba', allowed:'can_retire_test', blocker:'retire_blocker'},
    {value:'close_bl', label:'Cerrar BL administrativamente', allowed:'can_close_bl', blocker:'close_bl_blocker'},
    {value:'close_attention', label:'Cerrar solo esta entrega', allowed:'can_close_attention', blocker:'attention_blocker'}
  ];
  const originalCard = adminRewindCard;
  adminRewindCard = function(shipment) {
    const existing = originalCard(shipment);
    if (!isAdmin()) return existing;
    return existing + '<section class="admin-closure-entry" aria-label="Regularizacion administrativa">' +
      '<strong>Regularizacion administrativa</strong><button class="ghost" type="button" ' +
      'onclick="WmsAdminClosure.open()">Regularizar o cerrar BL</button></section>';
  };

  const dialog = document.createElement('dialog');
  dialog.id = 'adminClosureDialog';
  dialog.setAttribute('aria-labelledby', 'adminClosureTitle');
  dialog.innerHTML = `<form id="adminClosureForm" novalidate>
    <h2 id="adminClosureTitle">Regularizar o cerrar BL</h2>
    <p id="adminClosureIdentity"></p>
    <p id="adminClosureStatus" role="status" aria-live="polite" tabindex="-1"></p>
    <div id="adminClosureReview" hidden>
      <dl id="adminClosureFacts"></dl>
      <ul id="adminClosureBlockers" aria-label="Disponibilidad de acciones"></ul>
    </div>
    <p id="adminClosureError" role="alert" tabindex="-1" hidden></p>
    <button class="ghost" type="button" id="adminClosureRefresh">Actualizar revision</button>
    <div class="admin-closure-field"><label for="adminClosureAction">Accion</label>
      <select class="control" id="adminClosureAction">${actions.map(action =>
        `<option value="${action.value}" disabled>${action.label}</option>`).join('')}</select></div>
    <div class="admin-closure-field"><label for="adminClosureReason">Motivo (8 a 500 caracteres)</label>
      <textarea class="control" id="adminClosureReason" rows="3" minlength="8" maxlength="500" required></textarea></div>
    <div class="admin-closure-field"><label for="adminClosureBlConfirmation">Escribe la BL completa para confirmar</label>
      <input class="control" id="adminClosureBlConfirmation" autocomplete="off" spellcheck="false" required></div>
    <label class="admin-closure-ack" id="adminClosureAcknowledgeLabel" hidden>
      <input type="checkbox" id="adminClosureAcknowledge">
      <span>Reconozco que esta accion no acredita recepcion fisica, cumplimiento, FR/EM ni transferencia en SAP. Se conservan las cantidades y la evidencia registrada.</span>
    </label>
    <div class="admin-closure-actions"><button class="ghost" type="button" id="adminClosureCancel">Cancelar</button>
      <button class="primary" type="submit" id="adminClosureSubmit">Confirmar accion</button></div>
  </form>`;
  document.body.append(dialog);
  const field = suffix => document.getElementById('adminClosure' + suffix);
  let session = null, phase = '';
  const positiveId = value => Number.isSafeInteger(Number(value)) && Number(value) > 0 ? Number(value) : null;
  const pending = () => Boolean(window.WmsNpScan?.hasPending?.() || window.WmsTruckScan?.hasPending?.());
  const drafts = () => receptionHasUnsavedFields();
  const queueOpen = () => Boolean(document.querySelector('.queue.open'));
  const activeTab = () => document.querySelector('[data-reception-tab][aria-current="step"]')?.dataset.receptionTab || '';
  const activeNav = () => document.querySelector('.nav-item.active')?.dataset.nav || '';
  function current(context) {
    return session === context && !context.stale && isAdmin() && selected === context.shipment &&
      positiveId(selectedId) === context.id && positiveId(selected?.id) === context.id &&
      positiveId(selectedAttentionId) === context.aid &&
      document.getElementById('content')?.firstElementChild === context.view &&
      activeTab() === context.tab && activeNav() === context.nav && queueOpen() === context.queue;
  }
  function safe(context) { return current(context) && !pending() && !drafts() && !queueOpen(); }
  function error(message, target) {
    field('Error').textContent = message;
    field('Error').hidden = false;
    if (target) { target.setAttribute('aria-invalid', 'true'); target.focus(); }
  }
  function invalidate(context, message) {
    context.stale = true;
    error(message || 'Cambio la BL o la entrega seleccionada. Cancela esta revision y abre de nuevo el registro correcto.');
  }
  function eligible(action, context = session) {
    return Boolean(context?.preview?.[action.allowed] === true && (action.value !== 'close_attention' || context.aid));
  }
  function scope(action, context) {
    const bl = context.bl;
    if (action === 'reconcile') return `Conciliar cierre validado de la BL ${bl}. Se aplica el cierre ordinario validado.`;
    if (action === 'retire_test') return `Retirar el registro de prueba ${bl}. No acredita una recepcion fisica ni cumplimiento. No registra FR/EM ni transferencia en SAP.`;
    if (action === 'close_bl') return `Cerrar administrativamente la BL ${bl} y todas las entregas abiertas. No acredita FR/EM ni transferencia en SAP.`;
    return `Cerrar solo la entrega ${context.aid} de la BL ${bl}. La BL permanece abierta; las otras entregas conservan su trabajo. No acredita FR/EM ni transferencia en SAP.`;
  }
  function status() {
    if (!session?.preview) return;
    const action = actions.find(item => item.value === field('Action').value);
    field('Status').textContent = action && eligible(action) ? scope(action.value, session) : 'No hay acciones habilitadas para este registro.';
    field('AcknowledgeLabel').hidden = !action || action.value === 'reconcile' || !eligible(action);
    field('Acknowledge').required = !field('AcknowledgeLabel').hidden;
    field('Action').title = action?.label || 'Sin acciones habilitadas';
  }
  function controls() {
    const busy = Boolean(phase), invalid = !session?.preview || session.stale;
    if (busy) dialog.setAttribute('aria-busy', 'true'); else dialog.removeAttribute('aria-busy');
    for (const name of ['Action', 'Reason', 'BlConfirmation', 'Acknowledge']) field(name).disabled = busy || invalid;
    field('Submit').disabled = busy || invalid || session.needsReview || !actions.some(action => eligible(action));
    field('Cancel').disabled = phase === 'saving';
    field('Refresh').disabled = busy || !session || session.stale;
    field('Submit').textContent = phase === 'saving' ? 'Guardando...' : 'Confirmar accion';
  }
  function close() {
    if (phase === 'saving') return;
    const previous = session;
    session = null; phase = '';
    previous?.controller?.abort(); previous?.observer?.disconnect();
    dialog.removeAttribute('aria-busy'); dialog.close();
  }
  async function json(response) {
    const type = response.headers.get('content-type') || '';
    const fallback = response.status === 401 ? 'La sesion vencio. Inicia sesion de nuevo.' :
      response.status === 403 ? 'No tienes permiso para regularizar esta BL.' :
      'No se pudo confirmar la respuesta. Actualiza la revision antes de repetir la accion.';
    if (!/\bapplication\/(?:[\w.-]+\+)?json\b/i.test(type)) throw Error(fallback);
    let data;
    try { data = await response.json(); } catch { throw Error(fallback); }
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw Error(fallback);
    if (!response.ok || data.error) throw Error(typeof data.error === 'string' ? data.error : fallback);
    return data;
  }
  function matches(data, context) {
    return positiveId(data.id) === context.id &&
      (data.attention_id === null || positiveId(data.attention_id) !== null) &&
      positiveId(data.attention_id) === context.aid;
  }
  function showPreview(context, data) {
    const previousAction = field('Action').value;
    context.preview = data; context.needsReview = false;
    field('Review').hidden = false;
    const facts = field('Facts'); facts.replaceChildren();
    const count = value => Number.isInteger(value) && value >= 0 ? String(value) : 'Sin informar';
    for (const [label, value] of [['Estado de esta vista', data.app_status], ['Condicion', data.condition_status],
      ['Contabilidad', data.accounting_status], ['Entregas abiertas', count(data.open_attention_count)],
      ['NP sin lectura', count(data.unread_np_count)], ['NP pendientes', count(data.pending_np_count)]]) {
      const term = document.createElement('dt'), detail = document.createElement('dd');
      term.textContent = label; detail.textContent = value || 'Sin informar'; facts.append(term, detail);
    }
    const blockers = field('Blockers'); blockers.replaceChildren();
    for (const action of actions) {
      const allowed = eligible(action, context);
      field('Action').querySelector(`[value="${action.value}"]`).disabled = !allowed;
      const item = document.createElement('li'), title = document.createElement('strong'), explanation = document.createElement('span');
      title.textContent = action.label;
      explanation.textContent = allowed ? 'Disponible.' : String(data[action.blocker] ||
        (action.value === 'close_attention' && !context.aid ? 'Selecciona una entrega para cerrar solo esa entrega.' : 'Accion no habilitada para el estado actual.'));
      item.append(title, explanation); blockers.append(item);
    }
    const previous = actions.find(action => action.value === previousAction && eligible(action));
    const preferred = actions.find(action => action.value === 'close_attention' && eligible(action));
    field('Action').value = (previous || preferred || actions.find(action => eligible(action)))?.value || '';
    status();
  }
  async function review(context) {
    if (phase || !current(context)) return;
    phase = 'loading'; field('Error').hidden = true;
    field('Status').textContent = 'Revisando estado y bloqueos...'; controls();
    context.controller = new AbortController();
    try {
      const suffix = context.aid ? '?attention_id=' + context.aid : '';
      const response = await api(`/api/receptions/${context.id}/admin-closure${suffix}`,
        {cache:'no-store', signal:context.controller.signal});
      const data = await json(response);
      if (session !== context || !dialog.open) return;
      if (!safe(context)) { invalidate(context); return; }
      if (!matches(data, context) || data.bl_awb !== context.bl || typeof data.token !== 'string' || !data.token ||
        actions.some(action => typeof data[action.allowed] !== 'boolean')) {
        context.needsReview = true;
        throw Error('La revision no coincide con esta BL o entrega, o esta incompleta. Actualiza la revision.');
      }
      showPreview(context, data);
    } catch (failure) {
      if (session === context && dialog.open && failure.name !== 'AbortError') {
        context.needsReview = true; error(failure.message);
        field('Status').textContent = 'Revision no confirmada. Se conservan los campos.';
      }
    } finally {
      if (session === context) { phase = ''; controls(); }
    }
  }
  field('Cancel').addEventListener('click', close);
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  dialog.addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;
    const targets = [...dialog.querySelectorAll('button,input,select,textarea')]
      .filter(control => !control.disabled && control.getClientRects().length);
    const first = targets[0], last = targets.at(-1), active = document.activeElement;
    if (!first) { event.preventDefault(); field('Status').focus(); return; }
    if ((event.shiftKey && (active === first || !targets.includes(active))) ||
      (!event.shiftKey && (active === last || !targets.includes(active)))) {
      event.preventDefault(); (event.shiftKey ? last : first).focus();
    }
  });
  field('Refresh').addEventListener('click', () => { if (session) review(session); });
  field('Action').addEventListener('change', () => { field('Acknowledge').checked = false; status(); });
  dialog.addEventListener('input', event => event.target.removeAttribute('aria-invalid'));
  field('Form').addEventListener('submit', async event => {
    event.preventDefault();
    const context = session;
    if (phase || !context?.preview || context.needsReview || context.stale) return;
    if (!safe(context)) { invalidate(context, 'Cambio el contexto o hay lecturas/cambios sin guardar. Cancela y revisa la BL antes de confirmar.'); controls(); return; }
    field('Error').hidden = true;
    const action = actions.find(item => item.value === field('Action').value);
    if (!action || !eligible(action)) { error('La accion elegida no esta habilitada.', field('Action')); return; }
    const reason = field('Reason').value.trim(), bl = field('BlConfirmation').value;
    if (reason.length < 8 || reason.length > 500) { error('El motivo debe tener entre 8 y 500 caracteres.', field('Reason')); return; }
    if (bl !== context.bl) { error('La BL escrita no coincide. Escribe la BL completa.', field('BlConfirmation')); return; }
    if (action.value !== 'reconcile' && !field('Acknowledge').checked) {
      error('Confirma que esta accion no acredita verificacion fisica ni contable.', field('Acknowledge')); return;
    }
    if (!window.confirm(scope(action.value, context) + '\n\nMotivo: ' + reason + '\n\nConfirmar esta accion?')) return;
    if (!safe(context)) { invalidate(context); controls(); return; }
    const body = {action:action.value, token:context.preview.token, confirmed:true,
      bl_confirmation:bl, reason, attention_id:context.aid,
      acknowledge_unverified:action.value !== 'reconcile' && field('Acknowledge').checked};
    phase = 'saving'; controls();
    try {
      // A string body prevents the shared api helper from substituting a new attention_id.
      const response = await api(`/api/receptions/${context.id}/admin-closure`,
        {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
      const data = await json(response);
      if (session !== context) return;
      const condition = action.value === 'reconcile' ? 'COMPLETADO' : action.value === 'retire_test'
        ? 'REGISTRO DE PRUEBA RETIRADO' : 'CIERRE ADMINISTRATIVO';
      if (!matches(data, context) || data.action !== action.value ||
          data.app_status !== 'CERRADO' || data.condition_status !== condition) {
        throw Error('La respuesta no coincide con la BL, entrega o accion confirmada. Se conservan los campos; actualiza la revision.');
      }
      const message = action.value === 'close_attention' ?
        `Solo la entrega ${context.aid} de la BL ${context.bl} fue cerrada administrativamente. La BL permanece abierta.` :
        action.value === 'close_bl' ? `BL ${context.bl} y todas sus entregas abiertas cerradas administrativamente. No acredita FR/EM ni SAP.` :
        action.value === 'retire_test' ? `Registro de prueba ${context.bl} retirado. No acredita recepcion fisica ni cumplimiento.` :
        `Cierre validado conciliado para la BL ${context.bl}.`;
      if (!safe(context)) {
        invalidate(context, message + ' Cambio el contexto o hay trabajo pendiente. La vista actual no se recargo; revisa el registro antes de otra accion.');
        notify(message, 'success'); return;
      }
      context.observer.disconnect();
      try { await loadDetail(context.id, false, context.aid); }
      catch { notify(message + ' No se pudo recargar el detalle; actualizalo cuando termines el trabajo pendiente.', 'warning'); phase = ''; close(); return; }
      phase = ''; close();
      notify((data.unchanged ? 'Sin cambios adicionales. ' : '') + message, 'success');
    } catch (failure) {
      if (session === context) { context.needsReview = true; error(failure.message); }
    } finally {
      if (session === context) { phase = ''; controls(); }
    }
  });
  window.WmsAdminClosure = {open() {
    if (dialog.open || phase || !isAdmin() || !positiveId(selectedId) || !selected || positiveId(selected.id) !== positiveId(selectedId)) return;
    if (pending()) { notify('Resuelve las lecturas pendientes antes de regularizar la BL.', 'warning'); return; }
    if (drafts()) { notify('Guarda los cambios pendientes antes de regularizar la BL. Los campos se conservan.', 'warning'); return; }
    if (queueOpen()) { notify('Vuelve al detalle de la BL antes de regularizarla.', 'warning'); return; }
    const context = {id:positiveId(selectedId), aid:positiveId(selectedAttentionId), bl:String(selected.bl_awb || ''),
      shipment:selected, view:document.getElementById('content')?.firstElementChild, tab:activeTab(), nav:activeNav(),
      queue:queueOpen(), preview:null, stale:false, needsReview:false};
    session = context;
    field('Form').reset(); field('Error').hidden = true; field('Review').hidden = true;
    field('AcknowledgeLabel').hidden = true;
    dialog.querySelectorAll('[aria-invalid]').forEach(control => control.removeAttribute('aria-invalid'));
    field('Identity').textContent = `BL ${context.bl} · ${context.aid ? 'Entrega ' + context.aid : 'Sin entrega seleccionada'}`;
    context.observer = new MutationObserver(() => {
      if (session === context && dialog.open && !context.stale && !current(context)) { invalidate(context); controls(); }
    });
    context.observer.observe(document.body, {childList:true, subtree:true, attributes:true, attributeFilter:['class','aria-current','hidden']});
    dialog.showModal(); field('Status').focus(); review(context);
  }};
})();
