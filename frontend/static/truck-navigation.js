(function () {
  let originTruckGuide = '';
  const truckScreen = () => document.querySelector('#content [data-truck-guide]') || $('manualTruckWorkspace') || $('scanTruckWorkspace');
  const guideKey = value => String(value || '').trim().toLowerCase();

  function attentionTruckContext(shipment) {
    const attentionId = Number(shipment.attention_id || shipment.active_attention_id);
    if (!attentionId) return null;
    if (Object.prototype.hasOwnProperty.call(shipment, 'selected_attention_truck_guide')) {
      return {
        truck_guide: String(shipment.selected_attention_truck_guide || '').trim(),
        guide_status: shipment.selected_attention_guide_status || 'PENDIENTE'
      };
    }
    const attention = (shipment.attentions || []).find(item => Number(item.id) === attentionId);
    const receipt = (shipment.receipts || []).find(item => Number(item.id) === Number(attention?.receipt_id));
    const guide = String(receipt?.truck_guide || '').trim();
    const arrivals = (shipment.truck_arrivals || []).filter(item => guideKey(item.truck_guide) === guideKey(guide));
    return {
      truck_guide: arrivals.length && arrivals.every(item => item.truck_archived) ? '' : guide,
      guide_status: guideKey(guide) === guideKey(shipment.truck_guide)
        ? shipment.guide_status || 'PENDIENTE' : selectedGuideRecord(guide).guide_status || 'PENDIENTE'
    };
  }

  function shipmentTruckGuides(shipment) {
    const names = [
      ...(shipment.truck_plans || []).map(plan => plan.truck_guide),
      ...(shipment.truck_arrivals || []).filter(arrival=>!arrival.truck_archived).map(arrival => arrival.truck_guide),
      ...String(shipment.linked_truck_guides || '').split(','),
      shipment.truck_guide
    ];
    const seen = new Set();
    return names.filter(name => {
      const key = guideKey(name);
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    }).map(name => String(name).trim());
  }

  function truckLinksHtml(shipment) {
    return shipmentTruckGuides(shipment).map(guide =>
      `<button class="ghost" type="button" data-open-truck="${esc(guide)}">Camion ${esc(guide)}</button>`
    ).join(' ');
  }

  function bindTruckLinks(target) {
    target.querySelectorAll('[data-open-truck]').forEach(button => {
      button.addEventListener('click', () => openTruckGuideFromBl(button.dataset.openTruck));
    });
  }

  window.WmsTruckNavigation = {shipmentTruckGuides, truckLinksHtml, bindTruckLinks};

  const renderTruckGuideBase = renderTruckGuideWorkspace;
  renderTruckGuideWorkspace = function (summary) {
    renderTruckGuideBase(summary);
    const workspace = $('scanTruckWorkspace') || $('manualTruckWorkspace') || document.querySelector('#content .hero');
    if (workspace) workspace.dataset.truckGuide = String(summary.truck_guide || '');
  };

  const adminRewindCardBase = adminRewindCard;
  adminRewindCard = function (shipment) {
    const context = attentionTruckContext(shipment);
    return adminRewindCardBase(context ? {...shipment, ...context} : shipment);
  };

  const renderDetailBase = renderDetail;
  renderDetail = function () {
    const context = attentionTruckContext(selected || {});
    if (context) originTruckGuide = context.truck_guide;
    renderDetailBase();
    const content = $('content');
    content.querySelector('.back-btn')?.remove();
    const guides = shipmentTruckGuides(selected || {});
    const destination = context ? context.truck_guide : originTruckGuide || (guides.length === 1 ? guides[0] : '');
    const back = destination
      ? `<button class="back-btn" type="button" data-open-truck="${esc(destination)}">&larr; Volver al camion ${esc(destination)}</button>`
      : '<button class="back-btn" type="button" onclick="openQueue()">&larr; Volver a la lista</button>';
    content.insertAdjacentHTML('afterbegin',
      `<nav class="actions" aria-label="Camiones de la BL">${back}${guides.filter(guide => guideKey(guide) !== guideKey(destination)).map(guide => truckLinksHtml({truck_guide: guide})).join('')}</nav>`);
    const zoneNotice = content.querySelector('[data-reception-panel="zona"] .notice');
    if (context?.truck_guide && !isAdmin() && zoneNotice) {
      zoneNotice.textContent = `La cantidad y ubicaci\u00f3n de esta BL quedaron registradas desde la gu\u00eda ${context.truck_guide}. Aqu\u00ed puedes consultarlas; el conteo contin\u00faa en el siguiente paso.`;
    }
    bindTruckLinks(content);
  };

  const loadDetailBase = loadDetail;
  loadDetail = async function (id, ...args) {
    // The last shipment pointer may refer to a different partial-arrival truck.
    if (truckScreen()) originTruckGuide = String(activeTruckGuideSummary?.truck_guide || '');
    else if (Number(id) !== Number(selectedId)) originTruckGuide = '';
    return loadDetailBase(id, ...args);
  };

  const clearSelectionBase = clearSelection;
  clearSelection = function () {
    originTruckGuide = '';
    return clearSelectionBase();
  };

  const showTruckGuideBase = showTruckGuideWorkspace;
  showTruckGuideWorkspace = async function () {
    await showTruckGuideBase();
    if (!truckScreen()) return;
    selected = null;
    selectedId = null;
    selectedAttentionId = null;
    originTruckGuide = '';
    truckPlanCandidate = null;
    setReceptionWorkFocus(false);
    setActiveNav('operation');
    closeQueue();
  };

  openTruckGuideFromBl = async function (guide) {
    const code = String(guide || '').trim();
    if (!code) return;
    if ((receptionHasUnsavedFields() || window.WmsTruckScan?.hasPending?.()) &&
        !window.confirmLeaveActiveReceptionWork('el camion ' + code)) return;
    const select = $('truckGuideFilter');
    if (!select) return;
    let option = [...select.options].find(item => guideKey(item.value) === guideKey(code));
    // Completed trucks are absent from the pending-only selector.
    if (!option) {
      option = new Option(code, code);
      select.add(option);
    }
    select.value = option.value;
    await showTruckGuideWorkspace();
  };

  const continuityBase = window.getReceptionContinuityState;
  if (continuityBase) window.getReceptionContinuityState = () => ({
    ...continuityBase(),
    truckGuide: truckScreen() ? String(activeTruckGuideSummary?.truck_guide || '') : '',
    originTruckGuide
  });
  const restoreBase = window.restoreReceptionContinuity;
  if (restoreBase) window.restoreReceptionContinuity = async state => {
    const result = await restoreBase(state);
    originTruckGuide = String(state.originTruckGuide || '');
    if (selected && !truckScreen()) renderDetail();
    return result;
  };
})();
