'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const state = {data: null, query: null, controller: null, serial: 0};
  const numberFormat = new Intl.NumberFormat('es-PE', {maximumFractionDigits: 3});
  const quantity = value => value === null || value === undefined ? 'Sin dato' : numberFormat.format(value);
  function node(tag, className, text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined) item.textContent = String(text);
    return item;
  }
  function notice(text = '', error = false) {
    $('notice').hidden = !text;
    $('notice').textContent = text;
    $('notice').classList.toggle('error', error);
  }
  function date(value) {
    if (!value) return 'Sin fecha';
    const text = String(value), simple = text.match(/^(\d{4})-(\d{2})-(\d{2})(?:$|[T ])/);
    if (simple) return `${simple[3]}/${simple[2]}/${simple[1]}`;
    return text;
  }
  function stamp(value) {
    if (!value || String(value).length <= 10) return date(value);
    let text = String(value).replace(' ', 'T');
    if (!/(Z|[+-]\d{2}:\d{2})$/.test(text)) text += '-05:00';
    const parsed = new Date(text);
    return Number.isNaN(parsed.getTime()) ? date(value) : new Intl.DateTimeFormat('es-PE', {timeZone: 'America/Lima', dateStyle: 'short', timeStyle: 'short'}).format(parsed);
  }
  function reference(value, kind) {
    if (!value) return kind === 'OV' ? 'Sin OV asociada' : 'Pendiente';
    if (/^(COTIZACI[ÓO]N|COTI|COT)(?:$|[\s./:#-]|\d)/i.test(value)) return 'Cotización ' + value;
    if (/^PRE(?:LIMINAR)?(?:$|[\s./:#-]|\d)/i.test(value)) return 'Preliminar ' + value;
    return value;
  }
  async function api(path, options = {}) {
    const response = await fetch('/tracking/api/' + path, {
      credentials: 'same-origin', cache: 'no-store', ...options,
      headers: {'Content-Type': 'application/json', 'X-WMS-Request': '1', ...options.headers}
    });
    const text = await response.text();
    const data = text ? JSON.parse(text) : {};
    if (!response.ok) {
      const error = new Error(data.error || 'No se pudo completar la consulta.');
      error.status = response.status; error.code = data.code;
      throw error;
    }
    return data;
  }
  function clear() {
    state.controller?.abort(); state.serial++; state.data = null;
    $('searchButton').disabled = false; $('result').hidden = true; $('lines').replaceChildren(); $('timeline').replaceChildren();
  }
  function access() {
    clear(); $('workspace').hidden = true; $('passwordChange').hidden = true; $('access').hidden = false;
    $('accountName').textContent = ''; $('logout').hidden = true;
  }
  async function session() {
    try {
      const me = await api('me');
      const types = $('searchForm').elements.type;
      types.querySelectorAll('[data-analyst]').forEach(option => option.remove());
      if (me.details) {
        for (const [value, label] of [['IP', 'Pedido Triton · IP'], ['BL', 'Guía de importación · BL']]) {
          const option = new Option(label, value);
          option.dataset.analyst = '';
          types.add(option);
        }
      }
      $('access').hidden = true; $('logout').hidden = false;
      $('accountName').textContent = me.display_name || me.username;
      $('passwordChange').hidden = !me.must_change_password;
      $('workspace').hidden = me.must_change_password;
      notice(me.must_change_password ? 'Actualiza tu contraseña para continuar.' : '');
    } catch (error) {
      access();
      if (error.status !== 401) {
        $('logout').hidden = error.status !== 403;
        notice(error.message || 'No pudimos comprobar tu acceso. Intenta de nuevo.', true);
      } else notice('');
    }
  }
  function references(line) {
    const items = [
      ['OV / cotización', reference(line.ov, 'OV')], ['OC / preliminar', reference(line.oc, 'OC')],
      ['Aprobación de OC', line.approval || 'Sin verificación'], ['Pedido Triton', line.triton_order || 'Sin dato'],
      ['Pedido de fábrica', line.factory_order || 'Sin dato'], ['Factura', line.invoice || 'Sin dato'],
      ['BL / guía', line.bl || 'Todavía sin BL'], ['Ubicación confirmada', line.location || 'Sin ubicación'],
      ['Triton estimada', date(line.dates?.estimated)], ['Triton confirmada', date(line.dates?.confirmed)]
    ];
    $('references').replaceChildren(...items.map(([label, value]) => {
      const wrapper = node('div'); wrapper.append(node('dt', '', label), node('dd', '', value)); return wrapper;
    }));
  }
  function journey(index) {
    const line = state.data.lines[index], dates = line.dates || {};
    $('journey').hidden = false;
    $('journeyItem').textContent = (line.item || 'Referencia documental') + (line.description ? ' · ' + line.description : '');
    const received = (line.received_qty || 0) > 0;
    const complete = received && line.requested_qty != null && line.requested_qty > 0 && line.received_qty >= line.requested_qty;
    const steps = [
      ['Solicitud', date(dates.request), !!dates.request, false],
      ['Compra', line.oc ? `${reference(line.oc, 'OC')} · ${line.approval}` : 'OC pendiente', !!line.oc, false],
      ['Fábrica', `${line.factory_order || 'Pedido sin confirmar'} · ${date(dates.order)}`, !!(line.factory_order || dates.order), false],
      ['Importación', [line.bl ? `BL ${line.bl}` : 'BL pendiente', dates.invoice && `Factura: ${date(dates.invoice)}`, dates.pickup && `Recojo: ${date(dates.pickup)}`, dates.callao && `Callao informado: ${date(dates.callao)}`].filter(Boolean).join(' · '), !!(line.bl || dates.invoice || dates.pickup || dates.callao), false],
      ['Recibido', received ? `${quantity(line.received_qty)} de ${quantity(line.requested_qty)} · ${complete ? 'recepción completa' : 'parcial / por completar'}` : 'Sin recepción confirmada', received, complete],
      ['Ubicado', line.location || 'Pendiente de ubicación', !!line.location, !!line.location && complete],
      ['Costeo / transferencia', (dates.costing ? `Costeo informado: ${date(dates.costing)}. ` : 'Costeo sin fecha. ') + (line.transferred && complete ? 'Transferencia confirmada en WMS' : 'Transferencia por confirmar'), !!dates.costing || line.transferred, line.transferred && complete]
    ];
    $('timeline').replaceChildren(...steps.map(([label, detail, informed, confirmed]) => {
      const item = node('li', confirmed ? 'confirmed' : label === 'Recibido' && received ? 'partial' : informed ? 'informed' : '');
      item.append(node('strong', '', label), node('span', '', detail)); return item;
    }));
    $('eta').textContent = dates.confirmed ? `${date(dates.confirmed)} · confirmada en origen` : dates.estimated ? `${date(dates.estimated)} · estimada` : 'Sin previsión informada';
    const sla = line.sla;
    $('sla').textContent = sla ? `SLA almacén: ${sla.sla_status}. Límite: ${stamp(sla.sla_due_at)}. ${sla.remaining_hours != null ? quantity(sla.remaining_hours) + ' h restantes.' : ''}` : 'El SLA de almacén comienza con una llegada real registrada.';
    $('lineWarning').hidden = !line.warning; $('lineWarning').textContent = line.warning || '';
    references(line);
    [...$('lines').children].forEach((row, i) => {
      row.classList.toggle('selected', i === index);
      row.querySelector('button')?.setAttribute('aria-pressed', String(i === index));
    });
  }
  function render(data) {
    state.data = data;
    const summary = data.summary, source = data.source;
    const details = Array.isArray(data.lines);
    $('documentTitle').textContent = `${data.document.type} ${reference(data.document.number, data.document.type)}`;
    $('documentStatus').textContent = summary.status;
    $('sourceDate').textContent = `Corte de Importaciones: ${source.cutoff_at ? stamp(source.cutoff_at) : 'sin fecha de origen'}. Importado al WMS: ${stamp(source.loaded_at)}.` + (source.orders_updated_at ? ` OV actualizada: ${stamp(source.orders_updated_at)}.` : '');
    const warnings = [source.warning, source.orders_warning, source.coverage_warning].filter(Boolean);
    $('sourceWarning').hidden = !warnings.length; $('sourceWarning').textContent = warnings.join(' · ');
    const metrics = [['Líneas del documento', summary.total], ['Recepción completa', summary.received]];
    if (details) metrics.push(['Ubicación completa', summary.located], ['Atención completada', summary.transferred]);
    else metrics.push(['Recepción parcial', summary.partially_received]);
    $('summary').replaceChildren(...metrics.map(([label, value]) => {
      const div = node('div'); div.append(node('strong', '', quantity(value)), node('span', '', label)); return div;
    }));
    $('detailLines').hidden = !details || !summary.total;
    $('noResults').hidden = !!summary.total;
    $('journey').hidden = !details || !data.lines.length;
    if (details) renderLines(data);
    $('result').hidden = false; $('documentTitle').focus({preventScroll: true});
  }
  function renderLines(data) {
    $('lines').replaceChildren();
    for (const [index, line] of data.lines.entries()) {
      const row = node('tr');
      function cell(label, primary, secondary) {
        const td = node('td'); td.dataset.label = label; td.append(node('strong', '', primary));
        if (secondary) td.append(node('p', '', secondary)); row.append(td); return td;
      }
      cell('Repuesto', line.item || 'Referencia documental', line.description || line.brand || 'Sin detalle de repuesto');
      cell('OC / BL', reference(line.oc, 'OC'), line.bl ? `BL ${line.bl}` : 'Sin BL asociada');
      cell('Cantidades', `Solicitado: ${quantity(line.requested_qty)}`, `Recibido: ${quantity(line.received_qty)} · Pendiente de origen: ${quantity(line.pending_qty)}`);
      cell('Situación', line.stage, line.warning || '');
      const td = cell('Recorrido', ''); const button = node('button', 'quiet', 'Ver recorrido');
      button.type = 'button'; button.setAttribute('aria-label', 'Ver recorrido de ' + (line.item || 'referencia documental'));
      button.addEventListener('click', () => journey(index)); td.replaceChildren(button); $('lines').append(row);
    }
    if (data.lines.length) journey(0);
    const page = data.pagination;
    $('pageInfo').textContent = page.total ? `${page.offset + 1}–${Math.min(page.offset + page.limit, page.total)} de ${page.total} líneas` : 'Sin líneas disponibles';
    $('previous').disabled = page.offset <= 0; $('next').disabled = page.offset + page.limit >= page.total;
  }
  async function search(offset = 0) {
    const serial = ++state.serial; state.controller?.abort(); state.controller = new AbortController();
    $('searchButton').disabled = true; $('result').hidden = true; notice('Buscando en el último corte disponible…');
    try {
      const params = new URLSearchParams({...state.query, offset: String(offset)});
      const data = await api('search?' + params, {signal: state.controller.signal});
      if (serial !== state.serial) return;
      render(data); notice('');
    } catch (error) {
      if (serial !== state.serial || error.name === 'AbortError') return;
      if (error.status === 401) access();
      if (error.code === 'PASSWORD_CHANGE_REQUIRED') { clear(); $('workspace').hidden = true; $('passwordChange').hidden = false; }
      notice(error.message || 'No se pudo consultar. Intenta de nuevo.', true);
    } finally {
      if (serial === state.serial) $('searchButton').disabled = false;
    }
  }
  $('searchForm').addEventListener('submit', event => {
    event.preventDefault(); const fields = new FormData(event.currentTarget);
    state.query = {type: fields.get('type'), number: fields.get('number').trim()}; search();
  });
  $('previous').addEventListener('click', () => search(Math.max(0, state.data.pagination.offset - state.data.pagination.limit)));
  $('next').addEventListener('click', () => search(state.data.pagination.offset + state.data.pagination.limit));
  $('loginForm').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget, button = form.querySelector('button'); button.disabled = true;
    try { await api('login', {method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(form)))}); await session(); }
    catch (error) { notice(error.message || 'No se pudo iniciar sesión.', true); }
    finally { form.elements.password.value = ''; button.disabled = false; }
  });
  $('passwordForm').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget, button = form.querySelector('button'); button.disabled = true;
    try { await api('change-password', {method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(form)))}); form.reset(); await session(); }
    catch (error) { notice(error.message || 'No se pudo cambiar la contraseña.', true); }
    finally { button.disabled = false; }
  });
  $('logout').addEventListener('click', async () => {
    try { await api('logout', {method: 'POST', body: '{}'}); access(); notice('Sesión cerrada.'); }
    catch (error) { notice(error.message || 'No se pudo cerrar sesión. Intenta de nuevo.', true); }
  });
  session();
})();
