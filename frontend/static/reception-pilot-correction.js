/* Administrative correction stays separate from operational stage navigation. */
(() => {
  let context = null, busy = false;
  const originalCard = adminRewindCard;
  adminRewindCard = function(shipment) {
    const existing = originalCard(shipment);
    if (!isAdmin() || !shipment.pilot_correction?.eligible) return existing;
    return existing + '<section class="admin-rewind pilot-control"><strong>Recepciones de prueba retiradas</strong>' +
      '<button type="button" class="ghost" onclick="WmsPilotCorrection.open()">Corregir pruebas de esta BL</button></section>';
  };
  const dialog = document.createElement('dialog');
  dialog.id = 'pilotCorrectionDialog';
  dialog.setAttribute('aria-labelledby', 'pilotCorrectionTitle');
  dialog.innerHTML = `<form id="pilotCorrectionForm">
    <h2 id="pilotCorrectionTitle">Corregir recepciones de prueba</h2>
    <strong id="pilotCorrectionBl"></strong>
    <p>Se anularan los bultos y conteos de prueba. Los documentos FR/EM y el historial se conservaran.</p>
    <label for="pilotCorrectionAction">Resultado</label>
    <select id="pilotCorrectionAction" class="control">
      <option value="pending_arrival">Pendiente de llegada</option>
      <option value="historical_closed">Historica atendida: cerrar BL</option>
    </select>
    <label for="pilotCorrectionReason">Motivo</label>
    <textarea id="pilotCorrectionReason" class="control" required minlength="8" rows="3"></textarea>
    <label for="pilotCorrectionConfirmation">Escribe la BL completa para confirmar</label>
    <input id="pilotCorrectionConfirmation" class="control" required autocomplete="off">
    <p id="pilotCorrectionError" role="alert" hidden></p>
    <div class="pilot-actions"><button type="button" class="ghost" id="pilotCorrectionCancel">Cancelar</button>
      <button type="submit" class="primary" id="pilotCorrectionSubmit">Confirmar correccion</button></div>
  </form>`;
  document.body.append(dialog);
  function close() { if (!busy) dialog.close(); }
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  $('pilotCorrectionCancel').addEventListener('click', close);
  $('pilotCorrectionForm').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !context) return;
    const error = $('pilotCorrectionError');
    error.hidden = true;
    const body = {action:$('pilotCorrectionAction').value, reason:$('pilotCorrectionReason').value.trim(),
      bl_confirmation:$('pilotCorrectionConfirmation').value.trim(), confirmed:true, token:context.token};
    if (body.bl_confirmation !== context.bl) {
      error.textContent = 'La BL escrita no coincide.'; error.hidden = false;
      $('pilotCorrectionConfirmation').focus(); return;
    }
    const controls = [...dialog.querySelectorAll('input,textarea,select,button')];
    const previous = controls.map(control => control.disabled);
    busy = true; controls.forEach(control => { control.disabled = true; });
    $('pilotCorrectionSubmit').textContent = 'Guardando...';
    try {
      const response = await api(`/api/receptions/${context.id}/pilot-correction`, {method:'POST',body});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'No se pudo corregir la BL');
      selected = data; selectedId = data.id; selectedAttentionId = null;
      dialog.close();
      renderDetail();
      notify(body.action === 'historical_closed' ? 'BL historica cerrada.' : 'BL devuelta a Pendiente de llegada.');
      await loadReceptions({keepQueue:true});
    } catch (failure) { error.textContent = failure.message; error.hidden = false; }
    finally {
      busy = false; controls.forEach((control, index) => { control.disabled = previous[index]; });
      $('pilotCorrectionSubmit').textContent = 'Confirmar correccion';
    }
  });
  window.WmsPilotCorrection = {open() {
    if (busy || !isAdmin() || !selected?.pilot_correction?.eligible) return;
    if (receptionHasUnsavedFields() && !confirm('Descartar los cambios sin guardar de esta BL?')) return;
    context = {id:selected.id,bl:selected.bl_awb,token:selected.pilot_correction.token};
    $('pilotCorrectionForm').reset();
    $('pilotCorrectionBl').textContent = context.bl;
    $('pilotCorrectionError').hidden = true;
    $('pilotCorrectionAction').querySelector('[value="historical_closed"]').disabled = !selected.pilot_correction.can_close_history;
    dialog.showModal();
    $('pilotCorrectionAction').focus();
  }};
})();
