(() => {
  const labels = {PENDING:'Aviso en cola',DISABLED:'Aviso desactivado',BLOCKED:'Pendiente de autorizar Mail.Send',
    SENDING:'Enviando aviso',ACCEPTED:'Aviso aceptado por Microsoft',EXPIRED:'Enlace vencido',
    ERROR:'Aviso no enviado',REVIEW:'Revisar envío antes de reenviar',REVOKED:'Enlace revocado',CONFIRMED:'Transferencia confirmada'};
  transferCard = s => {
    const reached = states.indexOf(s.app_status) >= states.indexOf('SOLICITUD TRANSFERENCIA');
    if (!reached && !isAdmin()) return '';
    const editable = s.app_status === 'SOLICITUD TRANSFERENCIA' && !s.transfer_assistant_checked;
    const state = s.transfer_request;
    return `<section class="card reception-panel" data-reception-panel="transferencia"><div class="section-title"><h2>Transferencia IMP → 01</h2><span class="badge ${s.transfer_assistant_checked?'green':'orange'}">${s.transfer_assistant_checked?'REALIZADA EN SAP':'PENDIENTE SAP'}</span></div>
      <div class="compact-ref"><strong>EM:</strong> ${esc(s.em_number||'—')}</div>
      <p role="status">${esc(labels[state?.status] || (editable?'Pendiente de solicitud':'Sin solicitud'))}</p>
      ${editable&&isAdmin()?`<div class="actions"><button class="dark" onclick="reissueTransfer()">Reenviar aviso</button><button class="ghost" onclick="saveTransferCheck()">Confirmación administrativa</button></div>`:''}
      ${isAdmin()?`<details><summary onclick="loadTransferSettings()">Configuración del aviso</summary><div id="transferSettings"></div></details>`:''}</section>`;
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
      container.innerHTML = `<div class="form-grid"><div class="field"><label for="transferSender">Remitente Microsoft</label><input class="control" id="transferSender" type="email" value="${esc(data.sender)}"></div><div class="field"><label for="transferRecipient">Destinatario</label><input class="control" id="transferRecipient" type="email" value="${esc(data.recipient)}"></div><div class="field"><label for="transferOrigin">Origen público HTTPS</label><input class="control" id="transferOrigin" type="url" value="${esc(data.public_origin)}"></div></div><label class="check-row"><input type="checkbox" id="transferEnabled" ${data.enabled?'checked':''}>Aviso automático activo</label><div class="actions"><button class="primary" onclick="saveTransferSettings()">Guardar configuración</button><a class="btn" href="/purchase-alerts">Permiso de correo Microsoft</a></div>`;
    } catch(error) {container.textContent = error.message;delete container.dataset.loaded;}
  };
  window.saveTransferSettings = async () => {
    try {
      const response = await api('/api/reception-transfer/settings',{method:'POST',body:{
        sender:$('transferSender').value,recipient:$('transferRecipient').value,
        public_origin:$('transferOrigin').value,enabled:$('transferEnabled').checked}});
      const data = await response.json();if (!response.ok) throw new Error(data.error);
      notify('Configuración guardada');
    } catch(error) {notify(error.message,'error');}
  };
})();
