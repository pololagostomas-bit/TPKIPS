(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const form = $('settingsForm');
  const names = ['Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab', 'Dom'];
  let flow = null, timer = null, saved = null, dirty = false, busy = false;
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
  }
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
    display(await request('/api/purchase-alerts/status')); message('Estado actualizado.');
  });
  $('preview').onclick = () => execute(async () => {
    message('Revisando todas las hojas de compradores...');
    const result = await request('/api/purchase-alerts/preview', {});
    $('previewSubject').textContent = result.preview.subject;
    $('previewCounts').textContent = `${result.snapshot.cases.length} pendientes · ${result.new_count} nuevos · Hojas: ${result.snapshot.sheets.join(', ')}`;
    $('previewFrame').srcdoc = '<!doctype html><html lang="es"><meta charset="utf-8"><style>body{font:14px Arial;line-height:1.5;margin:16px;color:#263238}table{font-size:12px}td,th{overflow-wrap:anywhere}h2{font-size:17px}</style><body>' + result.preview.html + '</body></html>';
    $('previewSection').hidden = false;
    display(await request('/api/purchase-alerts/status')); message('Vista previa actualizada. No se envio correo.');
  });
  $('closePreview').onclick = () => { $('previewSection').hidden = true; };
  $('send').onclick = () => execute(async () => {
    if (!confirm(`¿Enviar el reporte actualizado a ${saved.to.length} destinatarios y ${saved.cc.length} en copia?`)) return;
    const result = await request('/api/purchase-alerts/send', {confirm: true});
    display(await request('/api/purchase-alerts/status'));
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
  execute(async () => { display(await request('/api/purchase-alerts/status')); message('Configuracion cargada.'); });
})();
