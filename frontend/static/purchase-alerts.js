(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const form = $('settingsForm');
  const names = ['Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab', 'Dom'];
  let flow = null, timer = null, saved = null, dirty = false, busy = false;
  let caseBusy = false, exportBusy = false, caseOffset = 0, caseResult = null;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[character]));
  const date = value => value ? new Date(value).toLocaleString('es-PE', {timeZone: 'America/Lima'}) : 'Sin revision';
  names.forEach((name, index) => {
    const label = document.createElement('label');
    const input = document.createElement('input'); input.type = 'checkbox'; input.name = 'weekday'; input.value = index;
    label.append(input, name); $('weekdays').append(label);
  });

  function message(text, error = false) {
    $('message').textContent = text; $('message').className = error ? 'error' : 'success';
  }
  function controls() {
    form.querySelectorAll('input,textarea').forEach(element => { element.disabled = busy || !saved; });
    ['save','preview','send','authorize','refresh'].forEach(id => { $(id).disabled = busy || (id !== 'refresh' && !saved); });
    $('preview').disabled ||= dirty;
    $('send').disabled ||= dirty || !saved?.enabled || flow !== null;
    $('authorize').disabled ||= dirty || !saved?.sender || flow !== null;
    caseControls();
  }
  function caseControls() {
    for (const id of ['caseState','caseSeverity']) $(id).disabled = caseBusy || exportBusy;
    $('casePrevious').disabled = caseBusy || exportBusy || !caseResult || caseOffset === 0;
    $('caseNext').disabled = caseBusy || exportBusy || !caseResult?.has_more;
    $('caseExport').disabled = caseBusy || exportBusy || !caseResult?.total;
  }
  function caseQuery() {
    return new URLSearchParams({state:$('caseState').value, severity:$('caseSeverity').value});
  }
  async function loadCases(offset = 0) {
    if (caseBusy || exportBusy) return;
    caseBusy = true; caseControls();
    $('caseMessage').textContent = 'Consultando historial...';
    const query = caseQuery(); query.set('offset', offset); query.set('limit', 50);
    try {
      const data = await request('/api/purchase-alerts/cases?' + query);
      if (!Array.isArray(data.items) || !Number.isInteger(data.total)) throw Error('Historial no valido.');
      caseOffset = offset; caseResult = data;
      $('caseRows').innerHTML = data.items.map(item => {
        const cells = [
          `<strong class="${item.severity === 'GRAVE' ? 'case-grave' : ''}">${esc(item.severity)}</strong><span>${esc(item.status)}</span>`,
          `<strong>${esc(item.ip || 'Sin IP')}</strong><span>${esc(item.preliminary || 'Sin OC')}</span><span>${esc(item.ov || '')}</span>`,
          esc([...new Set(item.sources.map(source => source.sheet))].join(', ')) +
            (item.unverified_sheets?.length ? `<span>Sin revisar: ${esc(item.unverified_sheets.join(', '))}</span>` : ''),
          esc(item.request_date_display || 'Sin fecha'),
          esc(date(item.first_seen_at)),
          `${esc(date(item.last_seen_at))}${item.resolved_at ? `<span>Fin: ${esc(date(item.resolved_at))}</span>` : ''}`,
          `<strong>${esc(item.elapsed_hours)} h</strong>`
        ];
        const labels = ['Nivel / estado','Pedido','Comprador','Fecha de solicitud IMP/OV','Primera deteccion','Ultima observacion / fin','Tiempo'];
        return '<tr>' + cells.map((value,index) => `<td data-label="${labels[index]}">${value}</td>`).join('') + '</tr>';
      }).join('');
      $('casePage').textContent = data.total ? `${offset+1}-${offset+data.items.length} de ${data.total}` : '0 registros';
      $('caseMessage').textContent = data.total ? '' : 'Sin casos para estos filtros.';
    } catch (error) {
      caseResult = null; $('caseRows').replaceChildren(); $('casePage').textContent = '';
      $('caseMessage').textContent = error.message;
    } finally { caseBusy = false; caseControls(); }
  }
  for (const id of ['caseState','caseSeverity']) $(id).onchange = () => loadCases();
  $('casePrevious').onclick = () => loadCases(Math.max(0,caseOffset-50));
  $('caseNext').onclick = () => loadCases(caseOffset+50);
  $('caseExport').onclick = async () => {
    if (exportBusy || caseBusy || !caseResult?.total) return;
    exportBusy = true; caseControls(); $('caseMessage').textContent = 'Preparando descarga...';
    try {
      const response = await fetch('/api/purchase-alerts/export?' + caseQuery(), {credentials:'same-origin'});
      if (!response.ok || !response.headers.get('Content-Type')?.toLowerCase().includes('text/csv')) {
        let detail; try { detail = (await response.json()).error; } catch {}
        throw Error(detail || 'No se pudo descargar el historial.');
      }
      const url = URL.createObjectURL(await response.blob()), link = document.createElement('a');
      link.href = url; link.download = 'historial_alertas_compras.csv'; document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      $('caseMessage').textContent = 'Descarga preparada.';
    } catch (error) { $('caseMessage').textContent = error.message; }
    finally { exportBusy = false; caseControls(); }
  };
  async function request(path, data) {
    const response = await fetch(path, {method: data === undefined ? 'GET' : 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-WMS-Request': '1'}, body: data === undefined ? undefined : JSON.stringify(data)});
    const raw = await response.text(); let result;
    try { result = JSON.parse(raw); } catch { throw Error('El servidor no devolvio una respuesta valida. Actualiza la pagina.'); }
    if (!response.ok) throw Error(result.error || 'No se completo la solicitud.');
    return result;
  }
  function fill(config) {
    saved = config;
    for (const name of ['sender','sender_name','interval_minutes','daily_time','subject','new_subject','body','new_intro']) form.elements[name].value = config[name];
    for (const name of ['to','cc','excluded_sheets']) form.elements[name].value = config[name].join('\n');
    form.elements.enabled.checked = config.enabled;
    form.querySelectorAll('[name=weekday]').forEach(input => { input.checked = config.weekdays.includes(Number(input.value)); });
    dirty = false;
  }
  function values() {
    const config = {...saved};
    for (const name of ['sender','sender_name','daily_time','subject','new_subject','body','new_intro']) config[name] = form.elements[name].value;
    for (const name of ['to','cc','excluded_sheets']) config[name] = form.elements[name].value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    config.interval_minutes = Number(form.elements.interval_minutes.value);
    config.enabled = form.elements.enabled.checked;
    config.weekdays = [...form.querySelectorAll('[name=weekday]:checked')].map(input => Number(input.value));
    return config;
  }
  function display(data, replaceForm = true) {
    if (replaceForm) fill(data.settings);
    const state = data.state, snapshot = state.snapshot;
    const summary = [['Pendientes', snapshot?.cases?.length ?? 'Sin revision'], ['Ultima revision (Lima)', date(state.checked_at)], ['Automatizacion', !data.settings.enabled ? 'Pausada' : data.worker_enabled ? 'Activa' : 'Worker no habilitado']];
    $('summary').innerHTML = summary.map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join('');
    $('mailStatus').textContent = data.mail_authorized ? 'Autorizacion de correo registrada.' : 'Pendiente de autorizar Mail.Send con la cuenta remitente.';
    $('history').replaceChildren();
    for (const item of data.history) {
      const article = document.createElement('article');
      article.innerHTML = `<strong>${esc(item.status)} · ${esc(item.kind)}</strong><p>${esc(date(item.sent_at || item.created_at))}</p><p>${esc(item.detail)}</p>`;
      if (item.status === 'REVISAR ENVIO') {
        const actions = document.createElement('div'); actions.className = 'actions';
        for (const [label, delivered] of [['Confirmar enviado', true], ['Confirmar no enviado', false]]) {
          const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
          button.onclick = () => execute(async () => {
            if (!confirm(`¿Revisaste el buzon de enviados y confirmas que este reporte ${delivered ? 'si' : 'no'} fue enviado?`)) return;
            display(await request('/api/purchase-alerts/delivery-review', {id: item.id, delivered, confirm: true}));
            message('Resultado del envio registrado.');
          });
          actions.append(button);
        }
        article.append(actions);
      }
      $('history').append(article);
    }
    if (!data.history.length) $('history').textContent = 'Sin envios registrados.';
    if (state.error) message(state.error, true);
    controls();
  }
  async function execute(action) {
    if (busy) return;
    busy = true; controls();
    try { await action(); } catch (error) { message(error.message, true); }
    finally { busy = false; controls(); }
  }
  form.oninput = () => { dirty = true; controls(); };
  form.addEventListener('keydown', event => {
    if (event.key === 'Enter' && event.target.matches('[name=subject],[name=new_subject]')) event.preventDefault();
  });
  form.onsubmit = event => {
    event.preventDefault();
    execute(async () => {
      const config = values();
      if (config.enabled && !saved.enabled && !confirm('¿Activar revisiones y correos automaticos a los destinatarios configurados?')) return;
      display(await request('/api/purchase-alerts/settings', config)); message('Configuracion guardada.');
    });
  };
  $('refresh').onclick = () => execute(async () => {
    if (dirty && !confirm('¿Descartar los cambios sin guardar?')) return;
    display(await request('/api/purchase-alerts/status')); await loadCases(); message('Estado actualizado.');
  });
  $('preview').onclick = () => execute(async () => {
    message('Revisando todas las hojas de compradores...');
    const result = await request('/api/purchase-alerts/preview', {});
    $('previewSubject').textContent = result.preview.subject;
    $('previewCounts').textContent = `${result.snapshot.cases.length} pendientes · ${result.new_count} nuevos · Hojas: ${result.snapshot.sheets.join(', ')}`;
    $('previewFrame').srcdoc = '<!doctype html><html lang="es"><meta charset="utf-8"><style>body{font:14px Arial;line-height:1.5;margin:16px;color:#263238}table{font-size:12px}td,th{overflow-wrap:anywhere}h2{font-size:17px}</style><body>' + result.preview.html + '</body></html>';
    $('previewSection').hidden = false;
    display(await request('/api/purchase-alerts/status')); message('Vista previa actualizada. No se envio correo.');
    await loadCases();
  });
  $('closePreview').onclick = () => { $('previewSection').hidden = true; };
  $('send').onclick = () => execute(async () => {
    if (!confirm(`¿Enviar el reporte actualizado a ${saved.to.length} destinatarios y ${saved.cc.length} en copia?`)) return;
    const result = await request('/api/purchase-alerts/send', {confirm: true});
    display(await request('/api/purchase-alerts/status'));
    await loadCases();
    message(result.sent ? 'Reporte aceptado por Microsoft 365.' : result.mail_status || 'No hay pendientes para enviar.', !!result.mail_status && !result.sent);
  });
  function stopFlow() { clearTimeout(timer); flow = null; $('authorization').hidden = true; controls(); }
  async function poll() {
    const current = flow;
    if (!current) return;
    if (Date.now() / 1000 >= current.expires_at) { stopFlow(); message('El codigo vencio. Vuelve a autorizar el correo.', true); return; }
    try {
      const result = await request('/api/cloud-connection/poll', {flow_id: current.flow_id});
      if (flow !== current) return;
      if (result.state === 'authorized') { stopFlow(); display(await request('/api/purchase-alerts/status')); message('Correo autorizado.'); return; }
      timer = setTimeout(poll, current.interval * 1000);
    } catch (error) { if (flow === current) { stopFlow(); message(error.message, true); } }
  }
  $('authorize').onclick = () => execute(async () => {
    flow = await request('/api/purchase-alerts/authorize', {});
    $('deviceCode').value = flow.user_code; $('authorization').hidden = false;
    $('expiry').textContent = `Vence: ${date(new Date(flow.expires_at * 1000).toISOString())} (Lima).`;
    timer = setTimeout(poll, flow.interval * 1000); message('Autoriza con la cuenta remitente en Microsoft.');
  });
  $('cancel').onclick = () => execute(async () => {
    if (!flow) return;
    await request('/api/cloud-connection/cancel', {flow_id: flow.flow_id}); stopFlow(); message('Autorizacion cancelada.');
  });
  window.addEventListener('pagehide', () => clearTimeout(timer));
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  execute(async () => { display(await request('/api/purchase-alerts/status')); await loadCases(); message('Configuracion cargada.'); });
})();
