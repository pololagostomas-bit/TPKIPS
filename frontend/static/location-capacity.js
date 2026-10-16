(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let me, snapshot, offset = 0, requestVersion = 0, previewVersion = 0, candidate = null, editRevision = null;
  let printing = false, loading = false, toastTimer, queryAbort;
  const selected = new Set();
  const admin = () => me?.role === 'ADMINISTRADOR';
  function toast(message) {
    $('capacityToast').textContent = message;clearTimeout(toastTimer);
    toastTimer = setTimeout(() => $('capacityToast').textContent = '', 6000);
  }
  async function api(path, options = {}) {
    const response = await fetch(path, {...options, headers:{'X-User':me?.username || '', 'X-Role':me?.role || '',
      ...(options.body ? {'Content-Type':'application/json'} : {}), ...options.headers},
      ...(options.body ? {body:JSON.stringify(options.body)} : {})});
    let value;
    try {value = await response.json();}
    catch {throw Error('El servidor no respondió correctamente. Reintenta la consulta.');}
    if (!response.ok) throw Error(value?.error || 'No se pudo completar la operación.');
    if (!value || typeof value !== 'object') throw Error('El servidor no devolvió los datos esperados.');
    return value;
  }
  function selectionState() {
    const copies = Number($('capacityCopies').value), total = selected.size * copies;
    $('capacitySelectionError').textContent = !Number.isInteger(copies) || copies < 1 || copies > 10 ? 'Copias: de 1 a 10.' : total > 200 ? 'Máximo 200 etiquetas por lote.' : '';
    $('capacitySelectionCount').textContent = selected.size + ' seleccionadas' + (selected.size ? ' · ' + total + ' etiquetas' : '');
    $('capacityPrint').disabled = printing || loading || !snapshot || !selected.size || !Number.isInteger(copies) || copies < 1 || copies > 10 || total > 200;
    const boxes = [...document.querySelectorAll('.capacity-select:not(:disabled)')];
    $('capacitySelectPage').disabled = !boxes.length;
    $('capacitySelectPage').checked = boxes.length > 0 && boxes.every(box => box.checked);
    $('capacitySelectPage').indeterminate = boxes.some(box => box.checked) && !boxes.every(box => box.checked);
  }
  function render(data) {
    const s = data.summary, stock = data.stock;
    $('capacityMetrics').innerHTML = [['Ubicaciones instaladas',s.installed],['Habilitadas',s.enabled],
      ['Con stock informado',stock.rows ? s.with_stock : '-'],['Bloqueadas',s.blocked]].map(([label,value]) => `<div><dt>${label}</dt><dd>${value}</dd></div>`).join('');
    $('capacityRatio').textContent = s.ratio === null ? '-' : s.ratio + '%';
    $('capacityMeter').hidden = s.ratio === null;
    if (s.ratio !== null) $('capacityMeter').value = s.ratio;
    $('capacitySource').textContent = stock.rows ? 'Ubicación por defecto · Corte SAP: ' + (stock.cutoff || 'sin fecha informada') + '. No mide volumen ni peso.' : 'Sin corte de stock del almacén 01. Ocupación no disponible.';
    const warnings = [];
    if (!s.registered) warnings.push('Sin maestro cargado: la capacidad total aún no está registrada.');
    if (s.unmapped) warnings.push(s.unmapped + ' ubicaciones con stock sin registro activo en el maestro.');
    if (stock.missing_location) warnings.push(stock.missing_location + ' registros con stock sin ubicación informada.');
    if (s.blocked_with_stock) warnings.push(s.blocked_with_stock + ' ubicaciones bloqueadas con stock informado.');
    if (stock.rows) warnings.push('La ausencia de stock informado no confirma espacio físico libre.');
    $('capacityWarnings').textContent = warnings.join(' ');$('capacityWarnings').hidden = !warnings.length;
    $('capacityRows').innerHTML = data.items.map(item => {
      const printable = !['BAJA','SIN_REGISTRO'].includes(item.state);
      const address = [['Zona',item.zone],['Pasillo',item.aisle],['Rack',item.rack],['Nivel',item.level],['Caja',item.bin]]
        .filter(([,value]) => value).map(([label,value]) => label + ' ' + value).join(' · ');
      return `<tr><td><label class="check-control"><input class="capacity-select" type="checkbox" data-code="${esc(item.code)}" aria-label="Seleccionar ${esc(item.code)}" ${selected.has(item.code) ? 'checked' : ''} ${printable ? '' : 'disabled'}></label></td><td class="code">${esc(item.code)}</td><td data-label="Posición">${esc(address || '-')}</td><td data-label="Estado"><span class="state ${esc(item.state)}">${esc(item.state.replaceAll('_',' '))}</span></td><td data-label="SKU con stock">${stock.rows ? item.sku_count : '-'}</td>${admin() ? `<td><div class="row-actions">${item.state !== 'SIN_REGISTRO' ? `<button type="button" data-edit="${esc(item.code)}">Editar</button><button type="button" data-history="${esc(item.code)}">Historial</button>` : ''}</div></td>` : ''}</tr>`;
    }).join('') || '<tr><td colspan="6">No hay ubicaciones para esta consulta.</td></tr>';
    $('capacityPage').textContent = data.total ? (data.offset + 1) + '-' + (data.offset + data.items.length) + ' de ' + data.total : '0 ubicaciones';
    $('capacityPrev').disabled = !data.offset;$('capacityNext').disabled = !data.has_more;
    selectionState();
  }
  async function load() {
    const version = ++requestVersion;queryAbort?.abort();queryAbort = new AbortController();
    loading = true;selectionState();
    $('capacityStatus').className = '';$('capacityStatus').textContent = 'Consultando ubicaciones...';
    $('capacityRows').innerHTML = '<tr><td colspan="6">Cargando...</td></tr>';
    $('capacitySelectPage').disabled = true;$('capacityPrev').disabled = true;$('capacityNext').disabled = true;
    const params = new URLSearchParams({search:$('capacitySearch').value,state:$('capacityState').value,
      evidence:$('capacityEvidence').value,offset:String(offset)});
    try {
      const data = await api('/api/locations?' + params, {signal:queryAbort.signal});
      if (version !== requestVersion) return;
      if (data.offset && !data.items.length && data.total) {offset = Math.floor((data.total - 1) / 50) * 50;return load();}
      snapshot = data;loading = false;render(data);$('capacityStatus').textContent = data.summary.registered ? 'Maestro registrado en el servidor' : 'Maestro pendiente de carga';
    } catch (error) {
      if (error.name === 'AbortError' || version !== requestVersion) return;
      snapshot = null;$('capacityStatus').className = 'error';$('capacityStatus').textContent = error.message;
      $('capacityRows').innerHTML = '<tr><td colspan="6">Consulta no disponible.</td></tr>';
      $('capacityMetrics').querySelectorAll('dd').forEach(node => node.textContent = '-');
      $('capacityRatio').textContent = '-';$('capacityMeter').hidden = true;
      $('capacitySource').textContent = 'Sin datos actuales. Reintenta la consulta.';
      $('capacityWarnings').hidden = true;$('capacityPage').textContent = '';
    } finally {
      if (version === requestVersion) {loading = false;selectionState();}
    }
  }
  function invalidatePreview() {
    ++previewVersion;candidate = null;$('capacitySaveButton').disabled = true;$('capacityPreview').textContent = '';
  }
  const encodeFile = file => new Promise((resolve,reject) => {
    const reader = new FileReader();reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.onerror = () => reject(Error('No se pudo leer el archivo.'));reader.readAsDataURL(file);
  });
  async function sourcePayload() {
    const file = $('capacityFile').files[0], text = $('capacityText').value.trim();
    if (file && text) throw Error('Carga un archivo o pega ubicaciones, no ambos.');
    if (file) {
      if (file.size > 4 * 1024 * 1024) throw Error('Máximo 4 MB por archivo.');
      return {filename:file.name,file_base64:await encodeFile(file),sheet:$('capacitySheet').value.trim()};
    }
    if (!text) throw Error('Selecciona el maestro o ingresa las ubicaciones.');
    return {text};
  }
  $('capacityPreviewButton').addEventListener('click', async () => {
    const version = ++previewVersion;candidate = null;$('capacitySaveButton').disabled = true;
    $('capacityPreviewButton').disabled = true;$('capacityPreview').textContent = 'Revisando archivo...';
    try {
      const payload = await sourcePayload(), checked = await api('/api/locations/preview', {method:'POST',body:payload});
      if (version !== previewVersion) return;
      candidate = {...payload,revision:checked.revision,digest:checked.digest};
      $('capacityPreview').innerHTML = `<p>${esc(checked.source)}</p><p>${checked.count} ubicaciones · ${checked.added} nuevas · ${checked.changed} cambios · ${checked.unchanged} sin cambios</p><ul>${checked.sample.map(item => `<li>${esc(item.code)}${item.state ? ' · ' + esc(item.state) : ''}</li>`).join('')}</ul>`;
      $('capacitySaveButton').disabled = false;
    } catch (error) {if (version === previewVersion) $('capacityPreview').textContent = error.message;}
    finally {$('capacityPreviewButton').disabled = false;}
  });
  $('capacityImportForm').addEventListener('submit', async event => {
    event.preventDefault();if (!candidate) return;
    const payload = {...candidate,reason:$('capacityReason').value.trim()};
    const controls = [...$('capacityImportForm').querySelectorAll('button,input,textarea')];controls.forEach(node => node.disabled = true);
    $('capacityPreview').textContent = 'Guardando maestro en el servidor...';
    try {
      const saved = await api('/api/locations/import', {method:'POST',body:payload});
      invalidatePreview();$('capacityFile').value = '';$('capacityText').value = '';$('capacityReason').value = '';
      $('capacityPreview').textContent = 'Guardado en servidor: ' + saved.added + ' nuevas y ' + saved.changed + ' actualizadas.';
      selected.clear();offset = 0;await load();
    } catch (error) {invalidatePreview();$('capacityPreview').textContent = error.message;}
    finally {controls.forEach(node => node.disabled = false);$('capacitySaveButton').disabled = true;}
  });
  for (const id of ['capacityFile','capacityText','capacitySheet']) $(id).addEventListener('input', invalidatePreview);
  $('capacitySearchForm').addEventListener('submit', event => {event.preventDefault();offset = 0;load();});
  for (const id of ['capacityState','capacityEvidence']) $(id).addEventListener('change', () => {offset = 0;load();});
  $('capacityPrev').addEventListener('click', () => {offset = Math.max(0, offset - 50);load();});
  $('capacityNext').addEventListener('click', () => {offset += 50;load();});
  $('capacityRows').addEventListener('change', event => {
    const input = event.target.closest('.capacity-select');if (!input) return;
    if (input.checked && selected.size >= 200) {input.checked = false;toast('Máximo 200 ubicaciones por lote.');}
    else if (input.checked) selected.add(input.dataset.code);else selected.delete(input.dataset.code);
    selectionState();
  });
  $('capacitySelectPage').addEventListener('change', event => {
    for (const input of document.querySelectorAll('.capacity-select:not(:disabled)')) {
      if (event.target.checked && selected.size < 200) {selected.add(input.dataset.code);input.checked = true;}
      else if (!event.target.checked) {selected.delete(input.dataset.code);input.checked = false;}
    }
    selectionState();
  });
  $('capacityClear').addEventListener('click', () => {selected.clear();document.querySelectorAll('.capacity-select').forEach(node => node.checked = false);selectionState();});
  $('capacityCopies').addEventListener('input', selectionState);
  $('capacityPrint').addEventListener('click', async () => {
    if (printing || $('capacityPrint').disabled) return;
    const codes = [...selected], copies = Number($('capacityCopies').value), view = window.open('', '_blank', 'width=700,height=800');
    if (!view) {toast('Permite ventanas emergentes para imprimir.');return;}
    view.document.body.textContent = 'Preparando etiquetas...';printing = true;selectionState();
    try {
      const result = await api('/api/locations/labels', {method:'POST',body:{codes,copies}});
      await WmsReceptionLabels.loadEngine();
      const html = await WmsLocationLabels.documentHtml(result.codes, result.logo, count => {
        if (view.closed) throw Error('Se cerró la vista de etiquetas.');
        view.document.body.textContent = 'Preparando ' + count + ' de ' + result.codes.length + ' etiquetas...';
      });
      if (view.closed) throw Error('Se cerró la vista de etiquetas.');
      view.document.write(html);view.document.close();
    } catch (error) {view.close();toast(error.message);}
    finally {printing = false;selectionState();}
  });
  $('capacityRows').addEventListener('click', async event => {
    const edit = event.target.closest('[data-edit]'), history = event.target.closest('[data-history]');
    if (edit && snapshot) {
      const row = snapshot.items.find(item => item.code === edit.dataset.edit);if (!row) return;
      editRevision = snapshot.revision;
      for (const [id,value] of [['Code',row.code],['Zone',row.zone],['Rack',row.rack],['State',row.state],['Warehouse',row.warehouse || '01'],['Aisle',row.aisle || ''],['Level',row.level || ''],['Bin',row.bin || ''],['Reason','']]) $('capacityEdit' + id).value = value;
      $('capacityEditError').textContent = '';$('capacityEditDialog').showModal();
    }
    if (history) {
      const code = history.dataset.history, dialog = $('capacityHistoryDialog');
      $('capacityHistoryTitle').textContent = 'Historial: ' + code;$('capacityHistory').textContent = 'Consultando...';dialog.showModal();
      try {
        const data = await api('/api/locations/history?' + new URLSearchParams({code}));
        if (!dialog.open || $('capacityHistoryTitle').textContent !== 'Historial: ' + code) return;
        $('capacityHistory').innerHTML = data.items.map(item => {
          const before = JSON.parse(item.before_json), after = JSON.parse(item.after_json);
          const names = {zone:'Zona',rack:'Rack',state:'Estado',warehouse:'Almacén',aisle:'Pasillo',level:'Nivel',bin:'Caja'};
          const changes = Object.entries(names).filter(([key]) => before[key] !== after[key])
            .map(([key,label]) => `${esc(label)}: ${esc(before[key] || '-')} → ${esc(after[key] || '-')}`).join('<br>');
          return `<article><strong>${esc(item.created_at)} · ${esc(item.username)}</strong><p>${esc(item.reason)}</p><p>${changes || 'Sin cambios de datos'}</p></article>`;
        }).join('') || 'Sin cambios registrados.';
      } catch (error) {$('capacityHistory').textContent = error.message;}
    }
  });
  $('capacityEditForm').addEventListener('submit', async event => {
    event.preventDefault();const button = event.submitter;button.disabled = true;button.textContent = 'Guardando...';
    try {
      const csvCell = value => '"' + String(value).replaceAll('"','""') + '"';
      const csv = 'Ubicacion,Zona,Rack,Estado,Almacen,Pasillo,Nivel,Caja\n' + ['Code','Zone','Rack','State','Warehouse','Aisle','Level','Bin'].map(key => csvCell($('capacityEdit' + key).value)).join(',');
      const payload = {filename:'actualizacion-ubicacion.csv',file_base64:await encodeFile(new Blob([csv], {type:'text/csv'}))};
      const checked = await api('/api/locations/preview', {method:'POST',body:payload});
      if (checked.revision !== editRevision) throw Error('El maestro cambió. Cierra y consulta nuevamente antes de editar.');
      await api('/api/locations/import', {method:'POST',body:{...payload,reason:$('capacityEditReason').value.trim(),revision:checked.revision,digest:checked.digest}});
      selected.delete($('capacityEditCode').value);$('capacityEditDialog').close();toast('Ubicación actualizada en el servidor.');await load();
    } catch (error) {$('capacityEditError').textContent = error.message;}
    finally {button.disabled = false;button.textContent = 'Guardar cambio';}
  });
  document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
  const dirty = () => $('capacityFile').files.length || $('capacityText').value.trim() || $('capacityReason').value.trim();
  window.addEventListener('beforeunload', event => {if (dirty()) {event.preventDefault();event.returnValue = '';}});
  $('capacityModule').addEventListener('change', event => {
    if (dirty() && !confirm('¿Salir sin guardar el maestro de ubicaciones?')) {event.target.value = '/locations';return;}
    location.assign(event.target.value);
  });
  async function initialize() {
    try {
      me = await api('/api/me');$('capacityIdentity').textContent = me.display_name || me.username;
      const modules = new Set(me.modules || []), names = {'/':'despacho','/reception':'recepcion','/inventory':'inventario'};
      for (const option of [...$('capacityModule').options]) if (names[option.value] && !modules.has(names[option.value])) option.remove();
      $('capacityImport').hidden = !admin();document.querySelectorAll('.admin-column').forEach(node => node.hidden = !admin());
      await load();
    } catch (error) {$('capacityStatus').className = 'error';$('capacityStatus').textContent = error.message;}
  }
  initialize();
})();
