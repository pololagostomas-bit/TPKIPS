/* Bulk printing is read-only; only one short catalog request runs at a time. */
(() => {
  const byId = id => document.getElementById(id);
  const form = byId('stockLabelForm');
  if (!form) return;
  const file = byId('stockLabelFile'), text = byId('stockLabelText');
  const status = byId('stockLabelStatus'), progress = byId('stockLabelProgress');
  const printButton = byId('stockLabelPrint'), batch = byId('stockLabelBatch');
  const cancel = byId('stockLabelCancel'), prepare = byId('stockLabelPrepare');
  let active = null, items = [], missing = [], duplicates = 0, printSize = 500;
  const key = value => String(value).replace(/[a-z]/g, c => c.toUpperCase());
  const message = (value, error = false) => {status.textContent = value;status.dataset.error = String(error);};
  function busy(controller) {
    active = controller;
    for (const control of [file, text, prepare, batch]) control.disabled = !!controller;
    cancel.disabled = !controller;
    cancel.classList.toggle('hidden', !controller);
    printButton.disabled = !!controller || !items.length;
  }
  function selection() {return items.slice(Number(batch.value || 0) * printSize, (Number(batch.value || 0) + 1) * printSize);}
  function printCaption() {printButton.textContent = `Imprimir ${selection().length} etiquetas`;}
  function render() {
    byId('stockLabelResult').classList.toggle('hidden', !items.length && !missing.length);
    batch.replaceChildren();
    for (let start = 0; start < items.length; start += printSize) batch.add(new Option(`${start + 1}–${Math.min(start + printSize, items.length)} de ${items.length}`, String(start / printSize)));
    byId('stockLabelBatchField').classList.toggle('hidden', items.length <= printSize);
    byId('stockLabelSummary').textContent = `${items.length} etiquetas listas · ${missing.length} NP sin coincidencia · ${duplicates} filas repetidas omitidas`;
    byId('stockLabelRows').innerHTML = items.slice(0, 50).map(item => `<tr><td data-label="NP">${esc(item.item_code)}</td><td data-label="Descripción">${esc(item.description)}</td><td data-label="Marca">${esc(item.label_brand)}</td><td data-label="Ubicación por defecto">${esc(Number(item.stock_qty) > 0 ? item.default_location : '')}</td></tr>`).join('');
    byId('stockLabelPreviewNote').textContent = items.length > 50 ? `Se muestran los primeros 50 NP. La impresión incluye todos los NP del lote elegido.` : '';
    const details = byId('stockLabelMissing');
    details.classList.toggle('hidden', !missing.length);
    details.querySelector('summary').textContent = `Revisar ${missing.length} NP sin coincidencia`;
    details.querySelector('textarea').value = missing.join('\n');
    printCaption();printButton.disabled = !!active || !items.length;
  }
  function invalidate() {items = [];missing = [];duplicates = 0;render();message('El listado cambió. Prepara las etiquetas para continuar.');}
  async function post(path, payload, signal) {
    const response = await api(path, {method:'POST',body:payload,signal});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'No se pudo preparar el listado.');
    return data;
  }
  async function resolve(codes, signal) {
    const data = await post('/api/inventory/labels', {codes}, signal);
    if (!Array.isArray(data.items) || !Array.isArray(data.missing)) throw new Error('El catálogo devolvió una respuesta incompleta.');
    const expected = new Set(codes.map(key)), returned = new Set();
    for (const code of [...data.items.map(item => item.item_code), ...data.missing]) {
      if (typeof code !== 'string' || !expected.has(key(code)) || returned.has(key(code))) throw new Error('La respuesta no corresponde al listado. Vuelve a prepararlo.');
      returned.add(key(code));
    }
    if (returned.size !== expected.size) throw new Error('El catálogo no verificó todos los NP. Reintenta la preparación.');
    return data;
  }
  function encodedFile(selected) {
    return new Promise((accept, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error('No se pudo leer el archivo.'));
      reader.onload = () => accept(String(reader.result).split(',')[1]);
      reader.readAsDataURL(selected);
    });
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();if (active) return;
    const controller = new AbortController();busy(controller);
    items = [];missing = [];duplicates = 0;render();
    progress.classList.remove('hidden');progress.max = 1;progress.value = 0;
    message('Leyendo el listado…');
    try {
      const selected = file.files[0];
      if (selected && text.value.trim()) throw new Error('Carga un archivo o pega el listado, no ambos.');
      if (selected && selected.size > 4 * 1024 * 1024) throw new Error('El archivo supera 4 MB.');
      const payload = selected ? {filename:selected.name,file_base64:await encodedFile(selected)} : {text:text.value};
      const parsed = await post('/api/inventory/labels/parse', payload, controller.signal);
      if (!Array.isArray(parsed.codes) || !parsed.codes.length || parsed.batch_size !== 100 || parsed.print_size !== 500) throw new Error('No se pudo interpretar el listado.');
      duplicates = parsed.duplicates;printSize = parsed.print_size;progress.max = parsed.codes.length;
      const prepared = new Map(), absent = [];
      for (let start = 0; start < parsed.codes.length; start += parsed.batch_size) {
        const codes = parsed.codes.slice(start, start + parsed.batch_size);
        message(`Verificando ${Math.min(start + codes.length, parsed.codes.length)} de ${parsed.codes.length} NP…`);
        const data = await resolve(codes, controller.signal);
        for (const item of data.items) prepared.set(key(item.item_code), item);
        absent.push(...data.missing);progress.value = start + codes.length;
      }
      items = [...prepared.values()];missing = absent;render();
      message(items.length ? `${items.length} etiquetas listas. Se genera una etiqueta por NP, sin multiplicar cantidades.` : 'No hay NP disponibles para imprimir. Revisa los códigos del listado.');
      status.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
    } catch (error) {
      items = [];missing = [];render();
      message(error.name === 'AbortError' ? 'Preparación cancelada. El listado se conserva.' : error.message, error.name !== 'AbortError');
    } finally {progress.classList.add('hidden');busy(null);}
  });
  printButton.addEventListener('click', async () => {
    if (active || !items.length) return;
    const selected = selection();
    const popup = window.open('', '_blank', 'width=640,height=800');
    if (!popup) {message('Permite ventanas emergentes para abrir las etiquetas.', true);return;}
    const controller = new AbortController();busy(controller);message('Verificando los datos actuales antes de imprimir…');
    try {
      const engine = window.WmsReceptionLabels;
      if (!engine?.inventoryDocumentsHtml) throw new Error('Actualiza la página para cargar las etiquetas.');
      await engine.loadEngine();
      const fresh = [];
      for (let start = 0; start < selected.length; start += 100) {
        const data = await resolve(selected.slice(start, start + 100).map(item => item.item_code), controller.signal);
        if (data.missing.length) throw new Error('El catálogo cambió. Prepara nuevamente el listado antes de imprimir.');
        fresh.push(...data.items);
      }
      if (popup.closed) throw new Error('Se cerró la vista de impresión.');
      popup.document.write(engine.inventoryDocumentsHtml(fresh));popup.document.close();
      message(`Vista abierta con ${fresh.length} etiquetas. Confirma la impresora y el formato para imprimir.`);
    } catch (error) {popup.close();message(error.name === 'AbortError' ? 'Preparación de impresión cancelada.' : error.message, error.name !== 'AbortError');}
    finally {busy(null);}
  });
  cancel.addEventListener('click', () => active?.abort());
  file.addEventListener('change', invalidate);text.addEventListener('input', invalidate);
  batch.addEventListener('change', printCaption);
  if (new URLSearchParams(location.search).get('tab') === 'labels') switchInventoryTab('labels');
})();
