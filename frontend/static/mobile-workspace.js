/* Adapt existing controls without cloning business actions or changing permissions. */
(() => {
  const body = document.body;
  const reception = Boolean(document.getElementById('content'));
  body.classList.add('mobile-workspace');
  let scheduled = false;
  const labelOf = button => button.textContent.trim().replace(/\s+/g, ' ');
  function tables() {
    document.querySelectorAll('.tablewrap table,.table-wrap table,.daily-table table').forEach(table => {
      const headers = [...table.querySelectorAll('thead tr:last-child th')];
      if (headers.length < 2 || headers.some(th => th.colSpan !== 1 || th.rowSpan !== 1)) return;
      if (!table.classList.contains('mobile-records')) table.classList.add('mobile-records');
      table.querySelectorAll('tbody tr').forEach(row => {
        if (row.cells.length !== headers.length) return;
        [...row.cells].forEach((cell, index) => {
          const label = headers[index].textContent.trim().replace(/ [\u2191\u2193]$/, '');
          if (cell.dataset.label !== label) cell.dataset.label = label;
        });
        if (!row.classList.contains('mobile-record')) row.classList.add('mobile-record');
      });
      const sortable = headers.map(th => th.querySelector('.sort-button'));
      if (!sortable.some(Boolean)) return;
      let sort = table.parentElement.querySelector(':scope > .mobile-sort');
      if (!sort) {
        sort = document.createElement('label'); sort.className = 'mobile-sort';
        sort.append(document.createTextNode('Ordenar por'));
        const select = document.createElement('select'); select.dataset.wmsNavigation = 'true'; select.setAttribute('aria-label', 'Ordenar registros');
        select.addEventListener('change', () => {
          const [index, direction] = select.value.split(':');
          const button = sortable[Number(index)];
          if (button && button.dataset.direction !== direction) button.click();
          if (button && button.dataset.direction !== direction) button.click();
        });
        sort.append(select); table.before(sort);
      }
      const select = sort.querySelector('select');
      const options = sortable.flatMap((button, index) => button ? ['asc', 'desc'].map(direction => ({
        value: index + ':' + direction, label: labelOf(button).replace(/ [\u2191\u2193]$/, '') + (direction === 'asc' ? ' (ascendente)' : ' (descendente)')
      })) : []);
      const signature = JSON.stringify(options);
      if (select.dataset.options !== signature) {
        select.replaceChildren(new Option('Seleccionar', ''), ...options.map(option => new Option(option.label, option.value)));
        select.dataset.options = signature;
      }
      const active = sortable.findIndex(button => button && button.dataset.direction !== 'none');
      select.value = active < 0 ? '' : active + ':' + sortable[active].dataset.direction;
    });
  }
  function tabs() {
    document.querySelectorAll('.detail-tabs,#inventoryApp > .tabs').forEach(nav => {
      const buttons = [...nav.querySelectorAll('button')].filter(button => !button.hidden);
      if (!buttons.length) return;
      // The scanner used to hide stage navigation in a collapsed details element.
      if (nav.parentElement.matches('details.scan-stage-picker')) {
        const picker = nav.parentElement; picker.before(nav); picker.remove();
      }
      let label = nav.previousElementSibling;
      if (!label?.matches('.mobile-stage-select')) {
        label = document.createElement('label'); label.className = 'mobile-stage-select';
        label.append(document.createTextNode(nav.classList.contains('reception-tabs') ? 'Etapa de la BL' : 'Secci\u00f3n'));
        const select = document.createElement('select'); select.dataset.wmsNavigation = 'true'; select.setAttribute('aria-label', nav.classList.contains('reception-tabs') ? 'Etapa de la BL' : 'Secci\u00f3n');
        select.addEventListener('change', () => {
          buttons[Number(select.value)]?.click();
          // A rejected unsaved-fields confirmation must leave the selector on the real tab.
          refresh();
        });
        label.append(select); nav.before(label);
      }
      const select = label.querySelector('select');
      const signature = buttons.map(button => labelOf(button) + ':' + button.disabled).join('|');
      if (select.dataset.options !== signature) {
        select.replaceChildren(...buttons.map((button, index) => {
          const option = new Option(labelOf(button), String(index)); option.disabled = button.disabled; return option;
        }));
        select.dataset.options = signature;
      }
      const index = buttons.findIndex(button => button.classList.contains('active') || button.getAttribute('aria-selected') === 'true' || button.getAttribute('aria-current') === 'step');
      select.value = String(Math.max(0, index));
      if (!nav.classList.contains('mobile-stage-tabs')) nav.classList.add('mobile-stage-tabs');
    });
  }
  function administrativeControls() {
    const root = document.getElementById('content') || document.getElementById('detail');
    if (!root) return;
    const controls = root.querySelector('.admin-rewind,.admin-correction');
    if (!controls || controls.closest('.wms-admin-panel')) return;
    const panel = document.createElement('section'); panel.className = 'wms-admin-panel';
    panel.setAttribute('aria-label', 'Modificar estados (administrador)');
    const title = document.createElement('h2'); title.textContent = 'Modificar estados'; panel.append(title, controls);
    if (controls.matches('details')) controls.open = true;
    const hero = root.querySelector('.hero,.order-summary');
    if (hero) hero.after(panel); else root.prepend(panel);
  }
  function refresh() {
    scheduled = false; administrativeControls(); tabs(); tables();
    if (reception && document.querySelector('#content [data-reception-panel]')) {
      document.querySelectorAll('#bottomNav [data-nav]').forEach(button => {
        const active = button.dataset.nav === 'work';
        if (button.classList.contains('active') !== active) button.classList.toggle('active', active);
        if (active && button.getAttribute('aria-current') !== 'page') button.setAttribute('aria-current', 'page');
        if (!active && button.hasAttribute('aria-current')) button.removeAttribute('aria-current');
      });
      const caption = document.querySelector('.workspace-rail-label');
      if (caption && caption.textContent !== 'BL / AWB') caption.textContent = 'BL / AWB';
    }
    const transfers = document.querySelector('#bottomNav [data-nav=deliveries]');
    if (transfers && reception) {
      transfers.setAttribute('aria-label', 'Transferencias');
      const caption = transfers.querySelector('span');
      const text = innerWidth <= 720 ? 'Transf.' : 'Transferencias';
      if (caption && caption.textContent !== text) caption.textContent = text;
    }
  }
  new MutationObserver(() => {
    if (!scheduled) { scheduled = true; requestAnimationFrame(refresh); }
  }).observe(body, {childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'hidden', 'disabled', 'aria-selected', 'aria-current']});
  function viewport() {
    const view = window.visualViewport;
    const height = view?.height || innerHeight;
    document.documentElement.style.setProperty('--wms-visible-height', height + 'px');
    const editing = document.activeElement?.matches('input:not([type=checkbox]):not([type=radio]),textarea,select');
    body.classList.toggle('wms-keyboard-open', Boolean(editing && innerHeight - height > 140));
    window.dispatchEvent(new Event('wms-viewport'));
  }
  window.visualViewport?.addEventListener('resize', viewport);
  window.visualViewport?.addEventListener('scroll', viewport);
  window.addEventListener('resize', () => { viewport(); refresh(); });
  body.addEventListener('focusin', viewport); body.addEventListener('focusout', () => setTimeout(viewport, 0));
  viewport(); refresh();
})();
