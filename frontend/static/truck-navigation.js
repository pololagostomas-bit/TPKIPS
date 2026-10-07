(function () {
  let originTruckGuide = '';
  const truckScreen = () => document.querySelector('#content [data-truck-guide]') || $('manualTruckWorkspace') || $('scanTruckWorkspace');
  const guideKey = value => String(value || '').trim().toLowerCase();

  function shipmentTruckGuides(shipment) {
    const names = [
      ...(shipment.truck_plans || []).map(plan => plan.truck_guide),
      ...(shipment.truck_arrivals || []).map(arrival => arrival.truck_guide),
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

  const renderDetailBase = renderDetail;
  renderDetail = function () {
    renderDetailBase();
    const content = $('content');
    content.querySelector('.back-btn')?.remove();
    const guides = shipmentTruckGuides(selected || {});
    const destination = originTruckGuide || (guides.length === 1 ? guides[0] : '');
    const back = destination
      ? `<button class="back-btn" type="button" data-open-truck="${esc(destination)}">&larr; Volver al camion ${esc(destination)}</button>`
      : '<button class="back-btn" type="button" onclick="openQueue()">&larr; Volver a la lista</button>';
    content.insertAdjacentHTML('afterbegin',
      `<nav class="actions" aria-label="Camiones de la BL">${back}${guides.filter(guide => guideKey(guide) !== guideKey(destination)).map(guide => truckLinksHtml({truck_guide: guide})).join('')}</nav>`);
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
