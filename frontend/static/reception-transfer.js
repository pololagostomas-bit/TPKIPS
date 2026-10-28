(() => {
  const labels = {PENDING:'Aviso en cola',DISABLED:'Aviso desactivado',BLOCKED:'Pendiente de autorizar Mail.Send',
    SENDING:'Enviando aviso',ACCEPTED:'Aviso aceptado por Microsoft',EXPIRED:'Enlace vencido',
    ERROR:'Aviso no enviado',REVIEW:'Revisar envío antes de reenviar',REVOKED:'Enlace revocado',CONFIRMED:'Transferencia confirmada'};
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
      ${editable&&isAdmin()?`<div class="actions"><button class="dark" onclick="reissueTransfer()">Reenviar aviso</button><button class="ghost" onclick="saveTransferCheck()">Confirmación administrativa</button></div>`:''}
      ${isAdmin()?'<button class="ghost" type="button" onclick="showNotifications()">Ver aviso en Correos</button>':''}</section>`;
  };
  saveTransferCheck = async () => {
    if (!isAdmin() || !confirm('¿Confirmas que la transferencia IMP → 01 ya fue realizada en SAP?')) return;
    const reason = prompt('Motivo de la confirmación administrativa:');
    if (reason === null) return;
    try {await mutate(shipmentUrl('/transfer-check'),{checked:true,reason});}
    catch (error) {notify(error.message,'error');}
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
