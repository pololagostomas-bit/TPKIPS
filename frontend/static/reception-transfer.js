(() => {
  const labels = {PENDING:'Aviso en cola',DISABLED:'Aviso desactivado',BLOCKED:'Pendiente de autorizar Mail.Send',
    SENDING:'Enviando aviso',ACCEPTED:'Aviso aceptado por Microsoft',EXPIRED:'Enlace vencido',
    ERROR:'Aviso no enviado',REVIEW:'Revisar envío antes de reenviar',REVOKED:'Enlace revocado',CONFIRMED:'Transferencia confirmada'};
  let transferCheckBusy = false;
  let emScopeBusy = false;
  let sharedEmBusy = false;
  const canonicalEm = value => String(value || '').trim().replace(/^(\d+)\s*-\s*$/, '$1');
  function emScopeCandidates(s) {
    if (!isAdmin() || !Number(s?.attention_id) || String(s.condition_status || '').startsWith('ANULADA') ||
        !['EM','UBICACION','VALIDACION','SOLICITUD TRANSFERENCIA'].includes(s.app_status)) return [];
    const choices = new Map(), assigned = new Set();
    for (const ref of s.accounting_refs || []) {
      if (!ref.fr_number) continue;
      const ip = ref.ip_reference_key || ref.ip_reference || '';
      for (const entry of ref.em_entries || []) {
        if (entry.ip_reference_key && entry.ip_reference_key !== ip) continue;
        const value = canonicalEm(entry.em_number);if (!value) continue;
        const documentKey = `${ref.fr_number}|${ip}|${value}`;
        if (Number(entry.attention_id)) {assigned.add(documentKey);continue;}
        const key = `${ref.id}|${ip}|${value}`, prior = choices.get(key);
        if (!prior || String(entry.em_number).trim() === value) choices.set(key, {
          id:Number(ref.id),em_id:Number(entry.id),ip_key:ip,em_number:value,
          fr:ref.fr_number,documentKey});
      }
    }
    return [...choices.values()].filter(item => !assigned.has(item.documentKey));
  }
  function emScopeCard(s) {
    const choices = emScopeCandidates(s);if (!choices.length) return '';
    return `<details id="emScopePanel" class="optional-data"><summary>Relacionar una EM existente</summary>
      <p>Selecciona la EM que corresponde a esta entrega. Su fecha de costeo se evaluará solo para esta entrega.</p>
      <div class="form-grid"><label class="field" for="emScopeSelect"><span>EM / FR / IP</span><select class="control" id="emScopeSelect"><option value="">Seleccionar EM</option>${choices.map((entry,index)=>`<option value="${index}">EM ${esc(entry.em_number)} · FR ${esc(entry.fr)} · ${esc(entry.ip_key)}</option>`).join('')}</select></label></div>
      <div class="actions"><button class="dark" type="button" id="bindEmScopeButton" onclick="bindExistingEmToAttention()" ${emScopeBusy?'disabled':''}>Vincular EM a esta entrega</button></div></details>`;
  }
  window.bindExistingEmToAttention = async () => {
    if (emScopeBusy) return;
    const shipment = selected, choice = $('emScopeSelect')?.value;
    const entry = choice !== '' && /^\d+$/.test(choice || '') ? emScopeCandidates(shipment)[Number(choice)] : null;
    if (!entry) {notify('Selecciona una EM existente de esta entrega.','error');return;}
    if (!confirm(`¿La EM ${entry.em_number}, FR ${entry.fr}, corresponde a la entrega ${shipment.attention_sequence || shipment.active_attention_sequence || shipment.attention_id} de la BL ${shipment.bl_awb || shipment.id}? Si su costeo es válido, se completará esta entrega.`)) return;
    const reason = prompt('Motivo del vínculo de EM (8 a 500 caracteres):');if (reason === null) return;
    if (reason.trim().length < 8 || reason.trim().length > 500) {notify('Escribe un motivo de 8 a 500 caracteres.','error');return;}
    emScopeBusy = true;const button = $('bindEmScopeButton');if(button)button.disabled = true;
    try {await mutate(shipmentUrl('/references'),{attention_id:shipment.attention_id,
      reference_updates:[{id:entry.id,em_id:entry.em_id,ip_key:entry.ip_key,em_number:entry.em_number,
        bind_to_attention:true,confirmed:true,reason:reason.trim()}]});}
    catch(error) {notify(error.message,'error');}
    finally {emScopeBusy = false;const current = $('bindEmScopeButton');if(current?.isConnected)current.disabled = false;}
  };
  function sharedEmChoices(s) {
    if (!isAdmin() || !s || String(s.condition_status || '').startsWith('ANULADA')) return [];
    const choices = [];
    for (const ref of s.accounting_refs || []) {
      const eligible = ref.em_eligible_attention_ids || [];
      if (!ref.fr_number || eligible.length < 2) continue;
      for (const entry of ref.em_entries || []) {
        if (!eligible.includes(Number(entry.attention_id))) continue;
        choices.push({key:`${ref.id}:${entry.id}:${encodeURIComponent(ref.ip_reference_key)}`,id:ref.id,em_id:entry.id,ip_key:ref.ip_reference_key,
          em_number:canonicalEm(entry.em_number),fr:ref.fr_number,origin:Number(entry.attention_id),
          eligible,covered:entry.shared_attention_ids || []});
      }
    }
    return choices;
  }
  function sharedEmCard(s) {
    const choices = sharedEmChoices(s);if (!choices.length) return '';
    return `<details id="sharedEmPanel" class="optional-data"><summary>Una EM para varias entregas</summary>
      <p>Excepción contable. Selecciona únicamente las entregas que cubre esta EM.</p>
      <div class="form-grid"><label class="field" for="sharedEmSelect"><span>EM existente / FR / IP</span>
      <select class="control" id="sharedEmSelect" onchange="renderSharedEmAttentions()"><option value="">Seleccionar EM</option>${choices.map(item=>`<option value="${esc(item.key)}">EM ${esc(item.em_number)} · FR ${esc(item.fr)} · ${esc(item.ip_key)}</option>`).join('')}</select></label></div>
      <div id="sharedEmAttentions"></div><div class="actions">
      <button class="dark" type="button" id="saveSharedEmButton" onclick="saveSharedEmCoverage()">Guardar cobertura</button>
      <button class="ghost" type="button" id="revokeSharedEmButton" onclick="saveSharedEmCoverage(true)" hidden>Quitar excepción</button></div></details>`;
  }
  function selectedSharedEm() {
    const value = $('sharedEmSelect')?.value;
    return sharedEmChoices(selected).find(item=>item.key===value) || null;
  }
  window.renderSharedEmAttentions = () => {
    const entry = selectedSharedEm(), target = $('sharedEmAttentions');if (!target) return;
    target.innerHTML = entry ? (selected.attentions || []).filter(a=>entry.eligible.includes(Number(a.id))).map(a=>{
      const origin = Number(a.id) === entry.origin;
      return `<label class="check"><input type="checkbox" value="${Number(a.id)}" ${origin || entry.covered.includes(Number(a.id))?'checked':''} ${origin?'disabled':''}>
        <span>Entrega ${Number(a.sequence_no)} · ${esc(String(a.received_at || '').slice(0,10) || a.truck_guide || '')}${origin?' · Origen de la EM':''}</span></label>`;
    }).join('') : '';
    const revoke = $('revokeSharedEmButton');if (revoke) revoke.hidden = !entry?.covered.length;
  };
  window.saveSharedEmCoverage = async (revoke=false) => {
    if (sharedEmBusy) return;
    const shipment = selected, entry = selectedSharedEm();
    if (!entry) {notify('Selecciona una EM existente.','error');return;}
    const ids = revoke ? [] : [...document.querySelectorAll('#sharedEmAttentions input:checked')].map(input=>Number(input.value));
    if (!revoke && ids.length < 2) {notify('Selecciona al menos dos entregas cubiertas por esta EM.','error');return;}
    const deliveries = (shipment.attentions || []).filter(a=>ids.includes(Number(a.id))).map(a=>`${a.sequence_no} (${String(a.received_at || '').slice(0,10)})`).join(', ');
    if (!confirm(revoke ? '¿Quitar la cobertura excepcional? Se revisará el costeo; los cierres históricos no se reabren.' :
      `¿La EM ${entry.em_number}, FR ${entry.fr}, cubre las entregas ${deliveries} de la BL ${shipment.bl_awb || shipment.id}? Se evaluará el costeo de esas entregas.`)) return;
    const reason = prompt('Motivo de la cobertura excepcional (8 a 500 caracteres):');if (reason === null) return;
    if (reason.trim().length < 8 || reason.trim().length > 500) {notify('Escribe un motivo de 8 a 500 caracteres.','error');return;}
    sharedEmBusy = true;for(const id of ['saveSharedEmButton','revokeSharedEmButton'])if($(id))$(id).disabled=true;
    try {await mutate(shipmentUrl('/references'),{attention_id:shipment.attention_id,reference_updates:[{
      id:entry.id,em_id:entry.em_id,ip_key:entry.ip_key,em_number:entry.em_number,
      coverage_attention_ids:ids,confirmed:true,reason:reason.trim()}]});}
    catch(error) {notify(error.message,'error');}
    finally {sharedEmBusy=false;for(const id of ['saveSharedEmButton','revokeSharedEmButton'])if($(id)?.isConnected)$(id).disabled=false;}
  };
  const canConfirmTransfer = s => {
    if (!s || s.app_status !== 'SOLICITUD TRANSFERENCIA' || s.transfer_assistant_checked ||
        String(s.condition_status || '').startsWith('ANULADA')) return false;
    if (isAdmin()) return true;
    const user = String(userName() || '').trim().toLowerCase();
    return role() === 'ASISTENTE_RECEPCION' && Number(s.attention_id) > 0 && user &&
      String(s.current_assistant || '').trim().toLowerCase() === user;
  };
  transferCard = s => {
    const reached = states.indexOf(s.app_status) >= states.indexOf('SOLICITUD TRANSFERENCIA');
    if (!reached && !isAdmin()) return '';
    const editable = s.app_status === 'SOLICITUD TRANSFERENCIA' && !s.transfer_assistant_checked;
    const state = s.transfer_request;
    const costing = s.costing;
    return `<section class="card reception-panel" data-reception-panel="transferencia"><div class="section-title"><h2>Transferencia IMP → 01</h2><span class="badge ${s.transfer_assistant_checked?'green':'orange'}">${s.transfer_assistant_checked?'REALIZADA EN SAP':'PENDIENTE SAP'}</span></div>
      <div class="compact-ref"><strong>EM:</strong> ${esc(s.em_number||'—')}</div>
      <div class="compact-ref"><strong>Fecha EM:</strong> ${esc(s.em_date||'—')}</div>
      <div class="compact-ref"><strong>Fecha de costeo:</strong> ${esc(costing?.costing_date||'—')}</div>
      ${costing?.ready?'<p role="status">Costeo registrado en Facturas.</p>':`<p class="secondary">${esc(costing?.detail||'Pendiente de fecha de costeo en Facturas')}</p>`}
      <p role="status">${esc(labels[state?.status] || (editable?'Pendiente de solicitud':'Sin solicitud'))}</p>
      ${emScopeCard(s)}
      ${sharedEmCard(s)}
      ${canConfirmTransfer(s)?`<div class="actions">${isAdmin()?'<button class="dark" onclick="reissueTransfer()">Reenviar aviso</button>':''}<button type="button" id="confirmTransferButton" class="${isAdmin()?'ghost':'primary'}" onclick="saveTransferCheck()" ${transferCheckBusy?'disabled':''}>${isAdmin()?'Confirmación administrativa':'Confirmar transferencia en SAP'}</button></div>`:''}
      ${isAdmin()?'<button class="ghost" type="button" onclick="showNotifications()">Ver aviso en Correos</button>':''}</section>`;
  };
  saveTransferCheck = async () => {
    const shipment = selected;
    if (transferCheckBusy || !canConfirmTransfer(shipment) || !confirm('¿Confirmas que la transferencia IMP → 01 ya fue realizada en SAP?')) return;
    const reason = prompt(isAdmin() ? 'Motivo de la confirmación administrativa:' : 'Observación de la transferencia realizada en SAP (mínimo 5 caracteres):');
    if (reason === null) return;
    if (reason.trim().length < 5) {notify('Escribe una observación de al menos 5 caracteres.','error');return;}
    transferCheckBusy = true;
    const button = $('confirmTransferButton');
    if (button) button.disabled = true;
    try {await mutate(shipmentUrl('/transfer-check'),{checked:true,reason:reason.trim(),attention_id:shipment.attention_id});}
    catch (error) {notify(error.message,'error');}
    finally {transferCheckBusy = false;const current = $('confirmTransferButton');if(current?.isConnected)current.disabled = false;}
  };
  window.refreshTransfer = () => {
    if (receptionHasUnsavedFields() && !confirm('¿Descartar los cambios sin guardar y actualizar la confirmación?')) return;
    loadDetail(activeShipmentId(),true,selectedAttentionId).catch(error=>notify(error.message,'error'));
  };
  window.reissueTransfer = async () => {
    if (!confirm('Se invalidará el enlace anterior y se enviará un nuevo aviso. ¿Continuar?')) return;
    const reason = prompt('Motivo del reenvío:');if (reason === null) return;
    try {await mutate(shipmentUrl('/transfer-reissue'),{reason});}
    catch (error) {notify(error.message,'error');}
  };
  window.loadTransferSettings = async () => {
    const container = document.getElementById('transferSettings');
    if (!container || container.dataset.loaded) return;
    container.dataset.loaded = '1';container.textContent = 'Cargando…';
    try {
      const response = await api('/api/reception-transfer/settings'), data = await response.json();
      if (!response.ok) throw new Error(data.error);
      if (!container.isConnected) return;
      container.innerHTML = `<div class="form-grid"><div class="field"><label for="transferSender">Remitente Microsoft</label><input class="control" id="transferSender" type="email" value="${esc(data.sender)}"></div><div class="field"><label for="transferRecipient">Destinatario</label><input class="control" id="transferRecipient" type="email" value="${esc(data.recipient)}"></div><div class="field"><label for="transferOrigin">Origen público HTTPS</label><input class="control" id="transferOrigin" type="url" value="${esc(data.public_origin)}"></div></div><label class="check-row"><input type="checkbox" id="transferEnabled" ${data.enabled?'checked':''}>Aviso automático activo</label><div class="actions"><button class="primary" id="saveTransferSettingsButton" onclick="saveTransferSettings()">Guardar configuración</button></div><p id="transferSettingsStatus" role="status"></p>`;
    } catch(error) {container.textContent = error.message;delete container.dataset.loaded;}
  };
  window.saveTransferSettings = async () => {
    const button = $('saveTransferSettingsButton'), status = $('transferSettingsStatus');
    if (!button || button.disabled) return;
    button.disabled = true;
    try {
      const response = await api('/api/reception-transfer/settings',{method:'POST',body:{
        sender:$('transferSender').value,recipient:$('transferRecipient').value,
        public_origin:$('transferOrigin').value,enabled:$('transferEnabled').checked}});
      const data = await response.json();if (!response.ok) throw new Error(data.error);
      if (status?.isConnected) status.textContent = 'Configuración guardada.';
      await refreshMailCenter();
    } catch(error) {if (status?.isConnected) status.textContent = error.message;}
    finally {if (button.isConnected) button.disabled = false;}
  };
  const connectionLabels = {REGISTERED:'Sesión Microsoft registrada',REQUIRED:'Falta autorizar el remitente',UNAVAILABLE:'Conexión no disponible'};
  const mailTime = value => value ? new Date(value*1000).toLocaleString('es-PE',{timeZone:'America/Lima',hour12:false}) : '—';
  async function refreshMailCenter() {
    const center = $('transferMailCenter');
    if (!center) return;
    const result = $('transferMailResult');
    try {
      const response = await api('/api/reception-transfer/status'), data = await response.json();
      if (!response.ok) throw new Error(data.error || 'No se pudo consultar el aviso de transferencia.');
      if (!center.isConnected) return;
      result.innerHTML = `<p><strong>${esc(connectionLabels[data.connection_state] || connectionLabels.UNAVAILABLE)}</strong> · ${data.settings.enabled?'Aviso activo':'Aviso desactivado'}</p>
        <dl class="profile-fields"><div><dt>Remitente</dt><dd>${esc(data.settings.sender || 'Sin configurar')}</dd></div><div><dt>Destinatario</dt><dd>${esc(data.settings.recipient || 'Sin configurar')}</dd></div></dl>
        ${data.connection_state==='REQUIRED'?'<a class="btn" href="/purchase-alerts">Autorizar correo Microsoft</a>':''}
        <div class="tablewrap"><table><thead><tr><th>BL / atención</th><th>Destinatario</th><th>Estado</th><th>Fecha</th></tr></thead><tbody>${data.rows.map(row=>`<tr><td><strong>${esc(row.bl_awb)}</strong>${row.attention_sequence?`<br>Atención ${Number(row.attention_sequence)}`:''}</td><td>${esc(row.recipient || data.settings.recipient || '—')}</td><td>${esc(labels[row.status] || row.status)}${row.error_code?`<br>${esc(row.error_code)}`:''}</td><td>${esc(mailTime(row.confirmed_at || row.attempted_at || row.created_at))}</td></tr>`).join('') || '<tr><td colspan="4">Sin avisos de transferencia registrados.</td></tr>'}</tbody></table></div>`;
    } catch(error) {if (center.isConnected) result.textContent = error.message;}
  }
  const originalNotifications = window.showNotifications;
  window.showNotifications = async (...args) => {
    if (!isAdmin()) return;
    await originalNotifications?.(...args);
    const root = $('content');
    if (root?.querySelector('h1')?.textContent !== 'Correos de recepción') return;
    const center = document.createElement('section'); center.id = 'transferMailCenter'; center.className = 'card';
    center.innerHTML = '<div class="section-title"><h2>Transferencias IMP → 01</h2><button class="ghost" type="button" id="refreshTransferMail" title="Actualizar avisos" aria-label="Actualizar avisos">↻</button></div><div id="transferMailResult" role="status">Cargando…</div><details><summary>Configuración del aviso</summary><div id="transferSettings"></div></details>';
    root.append(center);
    center.querySelector('#refreshTransferMail').onclick = refreshMailCenter;
    center.querySelector('details').addEventListener('toggle',event=>{if(event.target.open) loadTransferSettings();});
    await refreshMailCenter();
  };
})();
