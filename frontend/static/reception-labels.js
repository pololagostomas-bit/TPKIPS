/* Label presentation never changes source brands, source rows or received quantities. */
window.WmsReceptionLabels = (() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, character =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
  let engineLoading;
  function loadEngine() {
    if (window.bwipjs?.toSVG) return Promise.resolve();
    if (!engineLoading) engineLoading = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = '/assets/bwip-js-min.js?v=4.11.4';
      script.onload = () => window.bwipjs?.toSVG ? resolve() : reject(new Error('No se cargó Data Matrix.'));
      script.onerror = () => {script.remove();reject(new Error('No se cargó Data Matrix. Reintenta la impresión.'));};
      document.head.append(script);
    }).catch(error => {engineLoading = null;throw error;});
    return engineLoading;
  }
  const names = ['KALMAR','TRITON','CROWN','HYUNDAI','BOBCAT','KUBOTA','HOWO','TVH','HUSQVARNA','LIEBHERR'];
  function brandName(value) {
    const raw = String(value || '').trim();
    const tokens = raw.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toUpperCase().match(/[A-Z0-9]+/g) || [];
    const matches = names.filter(name => tokens.includes(name));
    return matches.length === 1 ? matches[0] : raw;
  }
  function referenceLines(reference) {
    const seen = new Set();
    return (reference.linked_lines || []).filter(line => {
      const id = Number(line.id);
      if (!Number.isSafeInteger(id) || id <= 0) return true;
      if (seen.has(id)) return false;
      seen.add(id); return true;
    });
  }
  if (typeof emEntryCard === 'function') {
    const emBase = emEntryCard;
    emEntryCard = shipment => emBase({...shipment, accounting_refs:(shipment.accounting_refs || []).map(reference =>
      ({...reference, linked_lines:referenceLines(reference)}))});
  }

  function logoUrl(value) {
    const url = String(value || '');
    return /^\/api\/(?:reception-brand-logo|inventory\/brand-logo)\?brand=[A-Z]+&v=[a-f0-9]{64}$/.test(url) ? url : '';
  }
  function inventoryItem(item) {
    const np = String(item.item_code || '').trim();
    if (!np) throw new Error('El material no tiene un NP válido.');
    return {np, description:String(item.description || '').trim(),
      location:Number(item.stock_qty) > 0 ? String(item.default_location || '').trim() : '',
      brand:brandName(item.label_brand), logo:logoUrl(item.brand_logo_url), companyLogo:logoUrl(item.company_logo_url)};
  }
  function items(shipment) {
    const seen = new Set(), result = [];
    for (const line of shipment?.lines || []) {
      const np = String(line.np_code || '').trim();
      if (!np || Number(line.attention_verified_qty ?? line.received_qty ?? 0) <= 0) continue;
      const item = {np, ov:String(line.ov_number || '').trim(), customer:String(line.customer_name || '').trim(),
        location:countLocationValue(line), description:String(line.description || '').trim(),
        brand:brandName(line.brand || line.label_brand), logo:logoUrl(line.brand_logo_url), companyLogo:logoUrl(line.company_logo_url)};
      // Same NP in another OV, brand, customer or destination is a different label.
      const key = JSON.stringify([item.np,item.ov,item.customer,item.location,item.brand]);
      if (seen.has(key)) continue;
      seen.add(key); result.push(item);
    }
    return result;
  }

  function popupApp() {
    const storageKey = 'triton-wms-label-paper-v2';
    const width = document.getElementById('labelWidth'), height = document.getElementById('labelHeight');
    const paper = document.getElementById('labelPaper');
    const message = document.getElementById('labelPrintMessage'), print = document.getElementById('printLabels');
    const sheets = [...document.querySelectorAll('.sticker')];
    let ready = false, logoError = false;
    let previous = null;
    const valid = saved => saved && Number.isFinite(saved.width) && Number.isFinite(saved.height)
      && saved.width >= 60 && saved.width <= 210 && saved.height >= 60 && saved.height <= 297;
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
      if (valid(saved)) {
        width.value = saved.width; height.value = saved.height;
        paper.value = saved.preset === 'te200-4x3' ? 'te200-4x3' : 'custom';
      }
      // The old unconfirmed default must never select the wrong printer stock.
      previous = JSON.parse(localStorage.getItem('triton-wms-label-paper-v1') || 'null');
      if (valid(previous)) {
        const option = document.createElement('option');
        option.value = 'previous'; option.textContent = 'Anterior: ' + previous.width + ' x ' + previous.height + ' mm';
        paper.append(option);
      }
    } catch {}
    function apply() {
      const w = Number(width.value), h = Number(height.value);
      if (!Number.isFinite(w) || !Number.isFinite(h) || w < 60 || w > 210 || h < 60 || h > 297) {
        message.textContent = 'Ancho: 60 a 210 mm. Alto: 60 a 297 mm.'; print.disabled = true; return;
      }
      document.getElementById('labelPageStyle').textContent = '@page{size:' + w + 'mm ' + h + 'mm;margin:2mm}';
      const pixels = (w - 4) * 96 / 25.4, vertical = (h - 4) * 96 / 25.4;
      const scale = Math.min(1, (document.documentElement.clientWidth - 24) / pixels);
      document.documentElement.style.setProperty('--label-width', (w - 4) + 'mm');
      document.documentElement.style.setProperty('--label-height', (h - 4) + 'mm');
      document.documentElement.style.setProperty('--preview-scale', scale);
      document.documentElement.style.setProperty('--preview-width', pixels * scale + 'px');
      document.documentElement.style.setProperty('--preview-height', vertical * scale + 'px');
      document.querySelectorAll('[name=labelOrientation]').forEach(radio => radio.checked = radio.value === (w > h ? 'landscape' : 'portrait'));
      let fits = true;
      for (const sheet of sheets) {
        let fit = false;
        for (const [keySize, detailSize] of [[24,10.5],[23,10],[22,10],[21,9.5],[20,9.5],[19,9],[18,8.5],[17,8.5],[16,8.5]]) {
          sheet.style.setProperty('--key-size', keySize + 'pt');
          sheet.style.setProperty('--detail-size', detailSize + 'pt');
          const bounds = sheet.getBoundingClientRect(), css = getComputedStyle(sheet);
          const bottom = bounds.bottom - (parseFloat(css.paddingBottom) + parseFloat(css.borderBottomWidth)) * scale;
          fit = sheet.scrollHeight <= sheet.clientHeight && sheet.scrollWidth <= sheet.clientWidth
            && [...sheet.children].every(child => child.getBoundingClientRect().bottom <= bottom + .1)
            && [...sheet.querySelectorAll('.np,.description,.ov-value,.bl strong,.customer strong,.location-box,.brand-name')]
              .every(field => field.scrollWidth <= field.clientWidth + 1 && field.scrollHeight <= field.clientHeight + 1
                && field.getBoundingClientRect().bottom <= bottom + .1);
          if (fit) break;
        }
        sheet.dataset.fits = String(fit); fits &&= fit;
        sheet.parentElement.style.setProperty('--page-preview-height', Math.max(vertical, sheet.scrollHeight) * scale + 'px');
      }
      message.textContent = logoError ? 'No se cargó un logotipo. Cierra y vuelve a abrir las etiquetas.' : !ready ? 'Cargando logotipos...' : fits ? sheets.length + ' etiquetas · ' + w + ' × ' + h + ' mm'
        : 'El contenido no cabe. Aumenta el formato; no se recortará la etiqueta.';
      print.disabled = !ready || !fits;
      try {localStorage.setItem(storageKey, JSON.stringify({width:w,height:h,preset:paper.value}));} catch {}
    }
    const custom = () => {paper.value = 'custom'; apply();};
    width.addEventListener('input', custom); height.addEventListener('input', custom);
    paper.addEventListener('change', () => {
      if (paper.value === 'te200-4x3') {width.value = '101.6'; height.value = '76.2';}
      else if (paper.value === 'previous' && valid(previous)) {width.value = previous.width; height.value = previous.height;}
      apply();
    });
    document.querySelectorAll('[name=labelOrientation]').forEach(radio => radio.addEventListener('change', () => {
      if ((radio.value === 'landscape') !== (Number(width.value) > Number(height.value))) {
        [width.value,height.value] = [height.value,width.value];
      }
      apply();
    }));
    print.addEventListener('click', () => {apply(); if (!print.disabled) window.print();});
    window.addEventListener('resize', apply);
    apply();
    const images = [...document.querySelectorAll('.brand-logo, .company-logo')];
    const loaded = images.map(image => image.decode().then(() => {
      if (!image.naturalWidth || !image.naturalHeight) throw new Error('Logo vacio');
    }));
    Promise.all([document.fonts.ready, ...loaded]).then(() => {ready = true; apply();})
      .catch(() => {logoError = true; apply();});
  }

  function documentHtml(shipment, labels, inventory = false) {
    const style = document.querySelector('link[href*="/assets/reception-labels.css"]')?.href || '/assets/reception-labels.css';
    const location = item => `<div class="location"><span class="field-caption">${inventory ? 'Ubicación por defecto' : 'Ubicación'}</span><div class="location-box">${esc(item.location)}</div></div>`;
    return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><base href="${esc(window.location.origin)}/"><title>${inventory ? 'Etiqueta de inventario' : 'Etiquetas por NP · ' + esc(shipment.bl_awb || '')}</title><link rel="stylesheet" href="${esc(style)}"><style id="labelPageStyle"></style></head><body class="label-print">
      <header class="label-toolbar"><label class="label-paper">Formato<select id="labelPaper"><option value="te200-4x3">TSC TE200 · 4 × 3 pulgadas</option><option value="custom">Personalizado</option></select></label><fieldset class="label-orientation"><legend>Orientación</legend><label><input type="radio" name="labelOrientation" value="portrait">Vertical</label><label><input type="radio" name="labelOrientation" value="landscape" checked>Horizontal</label></fieldset><label>Ancho (mm)<input id="labelWidth" type="number" min="60" max="210" step="0.1" value="101.6"></label><label>Alto (mm)<input id="labelHeight" type="number" min="60" max="297" step="0.1" value="76.2"></label><button type="button" id="printLabels" disabled>Imprimir</button><p id="labelPrintMessage" role="status" aria-live="polite"></p></header>
      <main class="label-preview">${labels.map(item => `<article class="label-page"><section class="sticker${inventory ? ' inventory-sticker' : ''}"><header class="brand-block">${item.logo ? `<img class="brand-logo" src="${esc(item.logo)}" alt="${esc(item.brand)}">` : `<strong class="brand-name">${esc(item.brand)}</strong>`}${item.companyLogo && item.brand !== 'TRITON' ? `<img class="company-logo" src="${esc(item.companyLogo)}" alt="Triton Trading">` : ''}</header><div class="facts"><section class="article-code"><span class="label-caption">Código de artículo / NP</span><div class="np">${esc(item.np)}</div></section>${inventory ? '' : `<section class="ov"><span class="label-caption"># OV</span><strong class="ov-value">${esc(item.ov)}</strong></section>`}</div><section class="article-description"><span class="label-caption">Descripción del artículo</span><div class="description">${esc(item.description)}</div></section><div class="label-footer">${inventory ? location(item) : `<div class="customer"><div class="bl"><span class="field-caption">BL / AWB</span><strong>${esc(shipment.bl_awb || '')}</strong></div><span class="field-caption">Cliente</span><strong>${esc(item.customer)}</strong></div>`}${dataMatrix(item.np)}</div>${inventory ? '' : location(item)}</section></article>`).join('')}</main>
      <script>(${popupApp.toString()})();<\/script></body></html>`;
  }
  function dataMatrix(np) {
    if (!window.bwipjs?.toSVG) throw new Error('No se cargó Data Matrix. Actualiza la página.');
    // Plain ECC200: exact NP only, not GS1, a URL, or a shipment identifier.
    const svg = window.bwipjs.toSVG({bcid:'datamatrix',text:np,format:'square',scale:1,padding:2,backgroundcolor:'FFFFFF'});
    const box = svg.match(/viewBox="0 0 (\d+) (\d+)"/);
    if (!box || box[1] !== box[2] || Number(box[1]) > 96) throw new Error('El NP excede el tamaño legible de la etiqueta.');
    return svg.replace('<svg ', `<svg class="barcode datamatrix" role="img" aria-label="Data Matrix ${esc(np)}" `);
  }
  async function print() {
    if (typeof receptionHasUnsavedFields === 'function' && receptionHasUnsavedFields()) {
      notify('Guarda los cambios antes de imprimir las etiquetas.', 'error'); return;
    }
    const shipment = selected, attention = selectedAttentionId;
    const popup = window.open('', '_blank', 'width=640,height=800');
    if (!popup) {notify('El navegador bloqueo la ventana de impresion', 'error'); return;}
    try {
      // Fetch saved quantities, including individual NP saves that preserve other local drafts.
      await loadEngine();
      const response = await api('/api/receptions/' + shipment.id + (attention ? '?attention_id=' + attention : ''));
      const saved = await response.json();
      if (!response.ok) throw new Error(saved.error || 'No se pudo verificar la etiqueta.');
      if (Number(saved.id) !== Number(shipment.id) || (attention && Number(saved.attention_id) !== Number(attention))) throw new Error('La respuesta no corresponde a esta atención. Reabre la BL.');
      if (selected !== shipment || selectedAttentionId !== attention) throw new Error('La selección cambió. Vuelve a imprimir desde la BL.');
      if (receptionHasUnsavedFields()) throw new Error('Guarda los cambios antes de imprimir las etiquetas.');
      const inputs = [...document.querySelectorAll('input[id^="qty-"]')];
      if (inputs.some(input => {
        const line = saved.lines.find(row => String(row.id) === input.id.slice(4));
        return line && Number(input.value) !== Number(line.attention_verified_qty ?? line.received_qty ?? 0);
      })) throw new Error('Guarda la revisión antes de imprimir las cantidades verificadas.');
      const labels = items(saved);
      if (!labels.length) throw new Error('No hay NPs con cantidad guardada en esta atención.');
      popup.document.write(documentHtml(saved, labels)); popup.document.close();
    } catch(error) {popup.close();notify(error.message, 'error');}
  }
  if (typeof printOvStickers === 'function') printOvStickers = print;
  const inventoryDocumentHtml = item => documentHtml({}, [inventoryItem(item)], true);
  return {items, documentHtml, referenceLines, brandName, dataMatrix, print, loadEngine, inventoryItem, inventoryDocumentHtml};
})();
