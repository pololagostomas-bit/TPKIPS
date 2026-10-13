/* Label presentation never changes source brands, source rows or received quantities. */
window.WmsReceptionLabels = (() => {
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
  const emBase = emEntryCard;
  emEntryCard = shipment => emBase({...shipment, accounting_refs:(shipment.accounting_refs || []).map(reference =>
    ({...reference, linked_lines:referenceLines(reference)}))});

  function logoUrl(value) {
    const url = String(value || '');
    return /^\/api\/reception-brand-logo\?brand=[A-Z]+&v=[a-f0-9]{64}$/.test(url) ? url : '';
  }
  function items(shipment) {
    const seen = new Set(), result = [];
    for (const line of shipment?.lines || []) {
      const np = String(line.np_code || '').trim();
      if (!np || Number(line.attention_verified_qty ?? line.received_qty ?? 0) <= 0) continue;
      const item = {np, ov:String(line.ov_number || '').trim(), customer:String(line.customer_name || '').trim(),
        location:countLocationValue(line), description:String(line.description || '').trim(),
        brand:brandName(line.brand || line.label_brand), logo:logoUrl(line.brand_logo_url)};
      // Same NP in another OV, brand, customer or destination is a different label.
      const key = JSON.stringify([item.np,item.ov,item.customer,item.location,item.brand]);
      if (seen.has(key)) continue;
      seen.add(key); result.push(item);
    }
    return result;
  }

  function popupApp() {
    const storageKey = 'triton-wms-label-paper-v1';
    const width = document.getElementById('labelWidth'), height = document.getElementById('labelHeight');
    const message = document.getElementById('labelPrintMessage'), print = document.getElementById('printLabels');
    const sheets = [...document.querySelectorAll('.sticker')];
    let ready = false, logoError = false;
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
      if (saved && Number.isFinite(saved.width) && Number.isFinite(saved.height)) {
        width.value = saved.width; height.value = saved.height;
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
        for (const [keySize, detailSize, gap] of [[20,10,1.5],[19,9.5,1.25],[18,9.5,1],[17,9,1],[16,9,.75]]) {
          sheet.style.setProperty('--key-size', keySize + 'pt');
          sheet.style.setProperty('--detail-size', detailSize + 'pt');
          sheet.style.setProperty('--label-gap', gap + 'mm');
          fit = sheet.scrollHeight <= sheet.clientHeight + 1 && sheet.scrollWidth <= sheet.clientWidth + 1;
          if (fit) break;
        }
        sheet.dataset.fits = String(fit); fits &&= fit;
        sheet.parentElement.style.height = Math.max(vertical, sheet.scrollHeight) * scale + 'px';
      }
      message.textContent = logoError ? 'No se cargó un logotipo. Cierra y vuelve a abrir las etiquetas.' : !ready ? 'Cargando logotipos...' : fits ? sheets.length + ' etiquetas · ' + w + ' × ' + h + ' mm'
        : 'El contenido no cabe. Aumenta el formato; no se recortará la etiqueta.';
      print.disabled = !ready || !fits;
      try {localStorage.setItem(storageKey, JSON.stringify({width:w,height:h}));} catch {}
    }
    width.addEventListener('input', apply); height.addEventListener('input', apply);
    document.querySelectorAll('[name=labelOrientation]').forEach(radio => radio.addEventListener('change', () => {
      if ((radio.value === 'landscape') !== (Number(width.value) > Number(height.value))) {
        [width.value,height.value] = [height.value,width.value];
      }
      apply();
    }));
    print.addEventListener('click', () => {apply(); if (!print.disabled) window.print();});
    window.addEventListener('resize', apply);
    apply();
    const images = [...document.querySelectorAll('.brand-logo')];
    const loaded = images.map(image => image.decode().then(() => {
      if (!image.naturalWidth || !image.naturalHeight) throw new Error('Logo vacio');
    }));
    Promise.all([document.fonts.ready, ...loaded]).then(() => {ready = true; apply();})
      .catch(() => {logoError = true; apply();});
  }

  function documentHtml(shipment, labels) {
    const style = document.querySelector('link[href*="/assets/reception-labels.css"]')?.href || '/assets/reception-labels.css';
    return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><base href="${esc(window.location.origin)}/"><title>Etiquetas por NP · ${esc(shipment.bl_awb || '')}</title><link rel="stylesheet" href="${esc(style)}"><style id="labelPageStyle"></style></head><body class="label-print">
      <header class="label-toolbar"><fieldset class="label-orientation"><legend>Orientación</legend><label><input type="radio" name="labelOrientation" value="portrait">Vertical</label><label><input type="radio" name="labelOrientation" value="landscape" checked>Horizontal</label></fieldset><label>Ancho (mm)<input id="labelWidth" type="number" min="60" max="210" step="1" value="150"></label><label>Alto (mm)<input id="labelHeight" type="number" min="60" max="297" step="1" value="100"></label><button type="button" id="printLabels" disabled>Imprimir</button><p id="labelPrintMessage" role="status" aria-live="polite"></p></header>
      <main class="label-preview">${labels.map(item => `<article class="label-page"><section class="sticker"><header class="brand-block">${item.logo ? `<img class="brand-logo" src="${esc(item.logo)}" alt="${esc(item.brand)}">` : `<strong class="brand-name">${esc(item.brand)}</strong>`}</header><div class="np">${esc(item.np)}</div><div class="description">${esc(item.description)}</div>${code39Svg(item.np)}<div class="facts"><span class="ov"># OV<strong class="ov-value">${esc(item.ov)}</strong></span><span class="bl">BL<strong>${esc(shipment.bl_awb || '')}</strong></span></div><div class="customer">Cliente<strong>${esc(item.customer)}</strong></div><div class="location">Ubicación<div class="location-box">${esc(item.location)}</div></div></section></article>`).join('')}</main>
      <script>(${popupApp.toString()})();<\/script></body></html>`;
  }
  function print() {
    const labels = items(selected);
    if (!labels.length) {notify('No hay NPs con cantidad ingresada en esta atencion', 'error'); return;}
    const popup = window.open('', '_blank', 'width=640,height=800');
    if (!popup) {notify('El navegador bloqueo la ventana de impresion', 'error'); return;}
    popup.document.write(documentHtml(selected, labels)); popup.document.close();
  }
  printOvStickers = print;
  return {items, documentHtml, referenceLines, brandName, print};
})();
