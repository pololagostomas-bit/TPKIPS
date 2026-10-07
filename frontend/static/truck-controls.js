/* Shared truck controls. Navigation never reverses saved receipts. */
window.WmsTruckControls = (() => {
  let busy = false, saving = false;
  const statusOf = summary => guideStatus(summary?.guide_status || summary?.status);
  const pending = () => busy || saving || Boolean(window.WmsTruckScan?.hasPending?.());
  const savedArrival = summary => guideBlRows(summary).some(row => row.arrival_id);
  const localArrival = summary => !summary.scanner_enabled && statusOf(summary) === 'PENDIENTE' &&
    arrivalStartedGuide === summary.truck_guide;
  function canDiscard() {
    return !receptionHasUnsavedFields() || confirm('Descartar los cambios sin guardar de esta pantalla? Los registros guardados se conservaran.');
  }
  function ready() {
    if (!pending()) return true;
    notify('Espera a que termine el guardado.', 'warning'); return false;
  }
  async function leave() {
    if (!ready() || !canDiscard()) return;
    arrivalStartedGuide = '';
    selected = null; selectedId = null; selectedAttentionId = null;
    activeTruckGuideSummary = null; truckPlanCandidate = null;
    $('truckGuideFilter').value = 'ALL';
    await showTruckGuideWorkspace();
    openQueue();
  }
  async function discard() {
    if (!ready() || !canDiscard()) return;
    await showTruckGuideWorkspace();
  }
  async function request(path, body, after) {
    busy = true;
    const controls = [...document.querySelectorAll('#content button, #content input, #content select')];
    const disabled = controls.map(control => control.disabled);
    controls.forEach(control => { control.disabled = true; });
    try {
      const response = await api(path, {method:'POST', body});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'No se pudo actualizar el camion.');
      await after(data);
    } catch (error) { notify(error.message, 'error'); }
    finally {
      busy = false;
      controls.forEach((control, index) => { if (control.isConnected) control.disabled = disabled[index]; });
      window.WmsTruckScan?.update?.();
    }
  }
  async function back() {
    if (!ready()) return;
    const summary = activeTruckGuideSummary || {}, guide = summary.truck_guide;
    if (summary.scanner_enabled && !savedArrival(summary) && ['PENDIENTE','EN_CURSO'].includes(statusOf(summary))) {
      if (!canDiscard()) return;
      if (scannerSelectedShipmentId) window.WmsTruckScan.changeBl();
      else await leave();
      return;
    }
    if (localArrival(summary)) {
      if (!canDiscard()) return;
      arrivalStartedGuide = '';
      renderTruckGuideWorkspace(summary); return;
    }
    if (!isAdmin()) { notify('Solicita al administrador la correccion de la llegada guardada.', 'warning'); return; }
    const target = ['LISTA_PARA_CONTEO','FINALIZADA'].includes(statusOf(summary)) ? 'ZONA_RECEPCION' : 'PENDIENTE';
    const detail = target === 'PENDIENTE'
      ? 'Se anulara la llegada de este camion y sus lecturas para registrar los bultos de nuevo. El historial y las otras llegadas se conservaran.'
      : 'Se reabrira la ubicacion. Los bultos recibidos y las lecturas se conservaran.';
    if (!guide || !confirm('Retroceder el camion ' + guide + '? ' + detail + ' Los cambios sin guardar se descartaran.')) return;
    await request('/api/receptions/truck-guide/revert', {truck_guide:guide,target_status:target}, async () => {
      arrivalStartedGuide = '';
      if (target === 'PENDIENTE' && window.WmsTruckScan) scannerSelectedShipmentId = null;
      localStorage.removeItem('triton-wms-jose-arrival:' + guide);
      await showTruckGuideWorkspace();
      notify(target === 'PENDIENTE' ? 'Llegada reabierta para registrar de nuevo.' : 'Ubicacion reabierta.', 'success');
    });
  }
  async function cancel() {
    if (!ready()) return;
    const summary = activeTruckGuideSummary || {}, guide = summary.truck_guide;
    if (!guide) return;
    const detail = savedArrival(summary)
      ? 'Se anularan la llegada y las ubicaciones de este camion.'
      : 'Se anularan las lecturas y se retiraran las BL de este camion.';
    if (!confirm('Cancelar la recepcion del camion ' + guide + '? ' + detail +
      ' Los documentos, el historial y las otras llegadas se conservaran.')) return;
    await request('/api/receptions/truck-guide/cancel', {truck_guide:guide}, async () => {
      arrivalStartedGuide = '';
      localStorage.removeItem('triton-wms-jose-arrival:' + guide);
      activeTruckGuideSummary = null;
      $('truckGuideFilter').value = 'ALL';
      await loadTruckGuides(); await showTruckGuideWorkspace();
      notify('Recepcion del camion cancelada. El historial se conserva.', 'success');
    });
  }
  function mount(summary) {
    const root = $('content'), scanner = $('scanTruckWorkspace');
    root.querySelector('#truckStageControls')?.remove();
    root.querySelector('#truckRevertStage')?.closest('section.card')?.remove();
    const status = statusOf(summary);
    const active = status !== 'CANCELADA';
    const scanArrival = summary.scanner_enabled && ['PENDIENTE','EN_CURSO'].includes(status) && !savedArrival(summary);
    const rewind = active && (scanArrival || localArrival(summary) || status !== 'PENDIENTE' || savedArrival(summary));
    const canRewind = isAdmin() || localArrival(summary) || scanArrival;
    const canCancel = active && (isAdmin() || (role() === 'ASISTENTE_RECEPCION' &&
      ['PENDIENTE','EN_CURSO'].includes(status) && !savedArrival(summary)));
    const toolbar = document.createElement('nav');
    toolbar.id = 'truckStageControls'; toolbar.className = 'truck-stage-controls';
    toolbar.setAttribute('aria-label', 'Controles del camion');
    toolbar.innerHTML = '<button type="button" class="ghost" data-truck-action="leave" title="Volver a la lista sin anular registros">&larr; Lista</button>' +
      (rewind ? '<button type="button" class="ghost" data-truck-action="back" ' + (canRewind ? '' : 'disabled ') +
        'title="' + (canRewind ? 'Volver al paso anterior' : 'El administrador debe corregir la llegada guardada') + '">Retroceder</button>' : '') +
      (active ? '<button type="button" class="ghost" data-truck-action="discard" title="Descartar solo los cambios sin guardar">Cancelar cambios</button>' : '') +
      (active ? '<button type="button" class="ghost truck-cancel" data-truck-action="cancel" ' + (canCancel ? '' : 'disabled ') +
        'title="' + (canCancel ? 'Anular esta recepcion con confirmacion' : 'Solo el administrador puede anular esta llegada') + '">Cancelar recepcion</button>' : '');
    toolbar.querySelectorAll('[data-truck-action]').forEach(button =>
      button.addEventListener('click', {leave,back,discard,cancel}[button.dataset.truckAction]));
    if (scanner) {
      scanner.querySelector('.scan-heading').after(toolbar);
      // Keep the stage action outside the scrolling form, with its original listener/ID.
      const finish = scanner.querySelector('.scan-finish');
      if (finish) {
        finish.querySelector('#cancelScanTruckButton')?.remove();
        scanner.append(finish);
      } else {
        const save = scanner.querySelector('#saveTruckLocationsButton');
        if (save) {const footer = document.createElement('div'); footer.className='scan-finish'; footer.append(save); scanner.append(footer);}
      }
    } else root.prepend(toolbar);
  }
  const renderBase = renderTruckGuideWorkspace;
  const notifyBase = notify;
  notify = function(message, variant = '') {
    const scanner = $('scanTruckWorkspace');
    if (!scanner) return notifyBase(message, variant);
    let feedback = $('scanFeedback');
    if (!feedback) {
      feedback = document.createElement('div');
      feedback.id = 'scanFeedback'; feedback.className = 'scan-feedback';
      feedback.setAttribute('role', 'status'); feedback.setAttribute('aria-live', 'polite');
      scanner.querySelector('.scan-task').prepend(feedback);
    }
    feedback.textContent = message; feedback.dataset.kind = variant;
    $('toast')?.classList.remove('show');
  };
  renderTruckGuideWorkspace = function(summary) {
    if (statusOf(summary) === 'CANCELADA') {
      $('content').innerHTML = '<section id="manualTruckWorkspace" data-truck-guide="' + esc(summary.truck_guide) +
        '"><h1>' + esc(summary.truck_guide) + '</h1><p>Recepcion cancelada. El historial se conserva.</p></section>';
    } else renderBase(summary);
    mount(summary);
  };
  for (const name of ['saveTruckArrival', 'saveTruckLocations']) {
    const original = window[name];
    window[name] = async function(...args) {
      if (pending()) return;
      saving = true;
      try { return await original(...args); }
      finally { saving = false; window.WmsTruckScan?.update?.(); }
    };
  }
  return {mount, leave, back, discard, cancel, hasPending:() => busy || saving};
})();
