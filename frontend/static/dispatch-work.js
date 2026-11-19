/* OV and STS share the existing attention, reservation and signed-guide flow. */
(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  if (!byId('detail') || !byId('list')) return;
  window.WmsDispatchKind = new URLSearchParams(location.search).get('kind') === 'STS' ? 'STS' : 'OV';
  let current = null, busy = false, pendingChoice = null;
  const admin = () => byId('role').value === 'ADMINISTRADOR';
  const headers = () => ({'Content-Type':'application/json','X-WMS-Request':'1','X-User':currentUserName(),'X-Role':byId('role').value});
  async function post(path, payload) {
    const response = await fetch(path, {method:'POST',headers:headers(),body:JSON.stringify(payload)});
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'No se pudo guardar.');
    return data;
  }
  async function get(path) {
    const response = await apiFetch(path), data = await response.json();
    if (!response.ok) throw Error(data.error || 'No se pudo consultar.');
    return data;
  }
  function dialog(title, content, action, save) {
    const element = document.createElement('dialog'); element.className = 'dispatch-dialog';
    element.innerHTML = `<form><h2>${esc(title)}</h2>${content}<p role="alert" class="dispatch-error"></p><footer><button type="button" data-cancel>Cancelar</button><button class="primary" type="submit">${esc(action)}</button></footer></form>`;
    document.body.append(element); element.showModal();
    element.querySelector('[data-cancel]').onclick = () => element.close();
    element.addEventListener('close', () => element.remove(), {once:true});
    element.querySelector('form').onsubmit = async event => {
      event.preventDefault(); const button = element.querySelector('[type=submit]');
      button.disabled = true;
      try {await save(element); element.close();}
      catch (error) {element.querySelector('[role=alert]').textContent = error.message;}
      finally {button.disabled = false;}
    };
    return element;
  }
  function photoFields() {
    return `<label>Foto de la guía firmada<input name="photo" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" required></label><label class="delivery-signature"><input name="recipient" type="checkbox" required> Confirmo la firma del cliente o receptor</label><label class="delivery-signature"><input name="warehouse" type="checkbox" required> Confirmo la firma del almacén</label>`;
  }
  async function photo(element) {
    const file = element.querySelector('[name=photo]').files[0];
    if (!file || file.size > 8*1024*1024) throw Error('Adjunta una foto de hasta 8 MB.');
    const image = await new Promise((resolve,reject) => {
      const reader = new FileReader(); reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(Error('No se pudo leer la foto.')); reader.readAsDataURL(file);
    });
    return {file_name:file.name,mime_type:file.type,image_base64:image,
      recipient_signed:element.querySelector('[name=recipient]').checked,warehouse_signed:element.querySelector('[name=warehouse]').checked};
  }
  function mountTabs() {
    byId('dispatchDocumentTabs')?.remove();
    const tabs = document.createElement('div'); tabs.id = 'dispatchDocumentTabs'; tabs.className = 'dispatch-tabs';
    tabs.innerHTML = `<div role="group" aria-label="Tipo de documento"><button type="button" data-kind="OV" aria-pressed="${WmsDispatchKind === 'OV'}">Despacho · OV</button><button type="button" data-kind="STS" aria-pressed="${WmsDispatchKind === 'STS'}">STS · sucursales</button></div>${admin() && WmsDispatchKind === 'STS' ? '<button type="button" class="primary" data-new>Nueva STS</button>' : ''}`;
    byId('list').prepend(tabs);
    for (const button of tabs.querySelectorAll('[data-kind]')) button.onclick = async () => {
      window.WmsDispatchKind = button.dataset.kind; selected = null; current = null; blankDetail();
      const url = new URL(location.href); url.searchParams.set('kind', WmsDispatchKind); history.replaceState(null,'',url);
      await loadOrders();
    };
    tabs.querySelector('[data-new]')?.addEventListener('click', () => newSTS().catch(error => notify(error.message,'error')));
  }
  async function newSTS() {
    const data = await get('/api/dispatch/branches'), key = crypto.randomUUID();
    const element = dialog('Nueva solicitud de traslado a sucursal', `<label>Sucursal destino<select name="destination"><option value="">Seleccionar sucursal</option>${data.items.map(item => `<option value="${esc(item.code)}">${esc(item.name)} · ${esc(item.code)}</option>`).join('')}</select></label><details><summary>Registrar una sucursal nueva</summary><label>Código de almacén destino<input name="branchCode" maxlength="30"></label><label>Nombre de sucursal<input name="branchName" maxlength="100"></label></details><label>Fecha requerida<input name="due" type="date" required></label><label>Referencia SAP (opcional)<input name="reference" maxlength="120"></label><div data-lines></div><button type="button" data-add>Agregar NP</button>`, 'Crear STS', async form => {
      let destination = form.querySelector('[name=destination]').value;
      if (!destination) {
        const branch = await post('/api/dispatch/branches',{code:form.querySelector('[name=branchCode]').value,name:form.querySelector('[name=branchName]').value});
        destination = branch.code;
      }
      const lines = [...form.querySelectorAll('[data-np-row]')].map(row => ({item_code:row.querySelector('[name=np]').value,quantity:row.querySelector('[name=quantity]').value}));
      const result = await post('/api/dispatch/requests',{request_key:key,kind:'STS',destination,due_date:form.querySelector('[name=due]').value,source_reference:form.querySelector('[name=reference]').value,lines});
      await loadOrders(); await loadDetail(result.sap_ov);
    });
    const addLine = () => {
      const row = document.createElement('div'); row.dataset.npRow = ''; row.className = 'dispatch-request-line';
      row.innerHTML = '<label>NP<input name="np" maxlength="120" required></label><label>Cantidad<input name="quantity" type="number" min="0.000001" step="any" value="1" required></label><button type="button" aria-label="Quitar repuesto">Quitar</button>';
      row.querySelector('button').onclick = () => row.remove(); element.querySelector('[data-lines]').append(row);
    };
    element.querySelector('[data-add]').onclick = addLine; addLine();
  }
  async function refresh(code) {if (selected === code) await loadDetail(code);}
  async function accept(code, lineId) {
    const context = current;
    if (!context || busy) return {state:'error',message:'Espera a que termine la lectura actual.'};
    busy = true;
    try {
      const result = await post(`/api/dispatch/attentions/${context.id}/scan`,{code,line_id:lineId});
      if (result.choices) {
        await WmsCamera.close(false);
        pendingChoice = () => dialog('Elige la línea del NP', `<label>Línea del pedido<select name="line">${result.choices.map(item => `<option value="${item.id}">${esc(item.name)} · ${esc(item.description)} · requerida ${qty(item.required)}</option>`).join('')}</select></label>`, 'Validar línea', async element => {const checked=await accept(code, Number(element.querySelector('[name=line]').value));if(checked.state==='error')throw Error(checked.message);});
        pendingChoice(); return {state:'choice'};
      }
      WmsScanFeedback.success(); notify('NP validado: '+code,'success'); await refresh(context.code);
      WmsCamera.focusInput(byId('dispatchNPScan'));
      return {state:'saved',message:'NP validado: '+code};
    } catch (error) {WmsScanFeedback.error(); notify(error.message,'error'); return {state:'error',message:error.message};}
    finally {busy = false;}
  }
  async function renderDispatch(code) {
    const data = await get('/api/orders/'+encodeURIComponent(code));
    if (selected !== code) return;
    const attention = (data.attentions || []).find(item => !isTerminalStatus(item.app_status));
    current = attention ? {id:attention.id,code,state:attention.app_status} : null; WmsCamera.changed();
    if(!admin()) document.querySelectorAll('#detail button').forEach(button => {
      if(button.disabled && button.textContent.trim()==='Confirmar asignación') button.remove();
    });
    if(data.dispatch_context?.kind === 'STS') {
      document.querySelectorAll('#detail .label').forEach(label => {if(label.textContent==='ORDEN DE VENTA')label.textContent='SOLICITUD DE TRASLADO';});
      document.querySelectorAll('#detail .badge').forEach(badge => {if(badge.textContent==='ENTREGADO'){badge.textContent='DESPACHADO';badge.title='Salida del almacén de origen. La recepción en sucursal se muestra por separado.';}});
      if(data.dispatch_context.pending_qty<=0) document.querySelectorAll('#detail button').forEach(button => {if(button.textContent.trim()==='Crear nueva atención')button.remove();});
    }
    byId('dispatchPicking')?.remove(); byId('dispatchShipments')?.remove();
    if (attention?.app_status === 'EN PICKING' && ['PICKER','PICKER_GUIADOR'].includes(byId('role').value) && sameUser(currentUserName(),attention.current_picker)) {
      const reads = data.dispatch_reads || [], lines = attention.lines.filter(item => item.picked_qty > 0);
      const verified = lines.filter(line => reads.some(read => read.attention_line_id === line.id && Math.abs(read.quantity-line.picked_qty)<0.000001));
      const section = document.createElement('section'); section.id = 'dispatchPicking'; section.className = 'card dispatch-picking';
      section.innerHTML = `<h2>Validar picking</h2><p role="status">NP verificados: <strong>${verified.length}/${lines.length}</strong></p><label for="dispatchNPScan">Escanear Data Matrix del NP</label><div class="dispatch-scan"><input id="dispatchNPScan" data-wms-scan-input inputmode="none" autocomplete="off"><button type="button" data-camera aria-label="Escanear NP con cámara">${WmsCamera.icon}</button></div><details><summary>Buscar o registrar NP manualmente</summary>${attention.lines.map(line => `<button type="button" data-manual="${line.id}">${esc(line.item_code)} · ${esc(line.description)} · preparada ${qty(line.picked_qty)}</button>`).join('')}</details>`;
      const stage = document.querySelector('.stage-advance');
      if(stage) stage.insertAdjacentElement('beforebegin',section);
      else byId('detail').firstElementChild.insertAdjacentElement('afterend',section);
      byId('dispatchNPScan').addEventListener('keydown', async event => {if(event.key==='Enter'){event.preventDefault();WmsScanFeedback.arm();await accept(event.target.value);}});
      section.querySelector('[data-camera]').onclick = () => {WmsScanFeedback.arm();WmsCamera.open('dispatch','dispatchNPScan');};
      section.querySelectorAll('[data-manual]').forEach(button => button.onclick = () => {
        const line = attention.lines.find(item => item.id === Number(button.dataset.manual));
        dialog('Confirmación manual de NP', `<p>${esc(line.item_code)} · ${esc(line.description)}</p><label>Cantidad preparada<input name="quantity" type="number" min="0" max="${line.planned_qty}" step="any" value="${line.picked_qty}" required></label><label>Motivo<input name="reason" maxlength="200" required></label>`, 'Guardar validación', async element => {
          await post(`/api/dispatch/attentions/${attention.id}/manual`,{line_id:line.id,quantity:element.querySelector('[name=quantity]').value,reason:element.querySelector('[name=reason]').value});await refresh(code);
        });
      });
      WmsCamera.focusInput(byId('dispatchNPScan'));
    }
    if (attention?.app_status === 'GUIADO FINALIZADO') {
      const stage = document.querySelector('.stage-advance strong'); if(stage) stage.textContent = 'Pendiente de validar entrega';
    }
    if (data.dispatch_context?.kind === 'STS' && attention && ['EN GUIADO','GUIADO FINALIZADO'].includes(attention.app_status)) {
      const stage = document.querySelector('.stage-advance-button');
      if(stage && attention.app_status === 'GUIADO FINALIZADO') {
        stage.textContent = 'Confirmar salida a sucursal';
        stage.onclick = () => dialog('Confirmar salida a sucursal', '<label>Guía de envío<input name="guide" maxlength="120" required></label>', 'Confirmar salida', async element => {
          await post(`/api/dispatch/attentions/${attention.id}/shipping`,{guide_reference:element.querySelector('[name=guide]').value});await refresh(code);
        });
      }
    }
    if (data.dispatch_context?.kind === 'STS' && !data.dispatch_context.local_created && !data.source_present) {
      const notice = document.createElement('p'); notice.setAttribute('role','status');
      notice.textContent = 'SAP: ' + (data.document_status === 'Cerrado' ? 'solicitud cerrada.' : 'solicitud ausente del último reporte completo.') + ' Las entregas y guías conservan su estado en el WMS.';
      byId('detail').prepend(notice);
    }
    if (data.shipments?.length) {
      const section = document.createElement('section'); section.id = 'dispatchShipments'; section.className = 'card';
      section.innerHTML = `<h2>Entregas a sucursal</h2>${data.shipments.map((shipment,index) => `<div class="dispatch-shipment"><strong>${esc(shipment.guide_reference)} · ${esc(shipment.destination)}</strong><span>${esc(shipment.state)}</span><span>${esc(shipment.shipped_at)}</span>${admin() && shipment.state !== 'RECIBIDO' ? `<button type="button" data-receive="${index}">Registrar recepción en sucursal</button>` : ''}</div>`).join('')}`;
      byId('detail').append(section);
      if(admin()) section.querySelectorAll('.dispatch-shipment').forEach((element,index) => {
        for(const receipt of data.shipments[index].receipts || []) {
          const link=document.createElement('a');link.href='/api/dispatch/receipts/'+encodeURIComponent(receipt.request_key)+'/evidence';link.target='_blank';link.rel='noopener';link.textContent='Guía firmada · '+receipt.receiver+' · '+receipt.created_at;element.append(link);
        }
      });
      section.querySelectorAll('[data-receive]').forEach(button => button.onclick = () => {
        const shipment = data.shipments[Number(button.dataset.receive)], key = crypto.randomUUID();
        dialog('Recepción de STS en sucursal', `<label>Recibido por<input name="receiver" maxlength="120" required></label>${shipment.lines.filter(line => line.pending_qty>0).map(line => `<label>${esc(line.item_code)} · pendiente ${qty(line.pending_qty)}<input data-receipt-line="${line.id}" type="number" min="0" max="${line.pending_qty}" step="any" value="${line.pending_qty}"></label>`).join('')}${photoFields()}`, 'Validar recepción', async element => {
          await post(`/api/dispatch/shipments/${shipment.attention_id}/receive`,{request_key:key,receiver:element.querySelector('[name=receiver]').value,evidence:await photo(element),lines:[...element.querySelectorAll('[data-receipt-line]')].filter(input=>Number(input.value)>0).map(input=>({id:Number(input.dataset.receiptLine),quantity:input.value}))});await refresh(code);
        });
      });
    }
  }
  WmsCamera.init({context:() => current?.state === 'EN PICKING' ? {key:current.code+':'+current.id} : null,
    accept:(_,code) => accept(code), manual:() => WmsCamera.manualInput(byId('dispatchNPScan'))});
  const originalList = window.renderList;
  window.renderList = function(...args) {const result = originalList.apply(this,args);mountTabs();return result;};
  const originalDetail = window.loadDetail;
  window.loadDetail = async function(code,...args) {const result = await originalDetail.call(this,code,...args);try{await renderDispatch(code);}catch(error){notify(error.message,'error');}return result;};
  const originalAdvance = window.advanceActive;
  window.advanceActive = async function(status) {
    if(status !== 'PICKING FINALIZADO') return originalAdvance(status);
    if(!current) return;
    try{await post(`/api/dispatch/attentions/${current.id}/finish-picking`,{});await loadOrders();}catch(error){notify(error.message,'error');}
  };
  mountTabs(); loadOrders();
})();
