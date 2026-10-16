/* Two independent location labels per existing 4x3 stock. No SKU/shipment fields. */
window.WmsLocationLabels = (() => {
  const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function popupApp() {
    const button = document.getElementById('printLocationLabels'), status = document.getElementById('locationPrintStatus');
    let ready = false, failed = false;
    function fit() {
      const width = 97.6 * 96 / 25.4, height = 72.2 * 96 / 25.4;
      const scale = Math.min(1, (document.documentElement.clientWidth - 24) / width);
      document.documentElement.style.setProperty('--preview-scale', scale);
      document.documentElement.style.setProperty('--preview-width', width * scale + 'px');
      document.documentElement.style.setProperty('--preview-height', height * scale + 'px');
      let fits = true;
      for (const label of document.querySelectorAll('.location-label')) {
        let valid = false;
        for (const size of [22,21,20,19,18,17,16,15,14]) {
          label.style.setProperty('--code-size', size + 'pt');
          const box = label.getBoundingClientRect();
          valid = label.scrollWidth <= label.clientWidth && label.scrollHeight <= label.clientHeight
            && [...label.querySelectorAll('strong,.triton-mark,.datamatrix')].every(node => {
              const field = node.getBoundingClientRect();
              return node.scrollWidth <= node.clientWidth + 1 && node.scrollHeight <= node.clientHeight + 1
                && field.left >= box.left && field.right <= box.right && field.top >= box.top && field.bottom <= box.bottom;
            });
          if (valid) break;
        }
        label.dataset.fits = String(valid); fits &&= valid;
      }
      button.disabled = !ready || !fits;
      status.textContent = failed ? 'No se cargó el logo de Triton. Cierra y vuelve a preparar las etiquetas.'
        : !ready ? 'Preparando logo...' : !fits ? 'Una ubicación no cabe en media etiqueta. No se imprimirá recortada.'
        : document.querySelectorAll('.location-label').length + ' etiquetas · Dos por sticker de 4 × 3 pulgadas';
    }
    button.addEventListener('click', () => {fit();if (!button.disabled) window.print();});
    window.addEventListener('resize', fit);fit();
    Promise.all([document.fonts.ready, ...[...document.querySelectorAll('.triton-mark')].map(image => image.decode())])
      .then(() => {ready = true;fit();}).catch(() => {failed = true;fit();});
  }
  async function documentHtml(codes, logo, progress = () => {}) {
    if (!Array.isArray(codes) || !codes.length || codes.length > 200) throw Error('De 1 a 200 etiquetas por lote.');
    if (!/^\/api\/inventory\/brand-logo\?brand=TRITON&v=[a-f0-9]{64}$/.test(logo)) throw Error('Logo de Triton no válido.');
    const labels = [];
    for (let index = 0; index < codes.length; index++) {
      const code = codes[index];
      if (typeof code !== 'string' || !/^[A-Z0-9][A-Z0-9._ /-]{0,59}$/.test(code)) throw Error('Ubicación no válida.');
      labels.push(`<section class="location-label"><div class="label-text"><img class="triton-mark" alt="Triton" src="${esc(logo)}"><strong>${esc(code)}</strong></div>${WmsReceptionLabels.dataMatrix(code)}</section>`);
      if (index % 10 === 9) {progress(index + 1);await new Promise(resolve => setTimeout(resolve, 0));}
    }
    const sheets = [];
    for (let index = 0; index < labels.length; index += 2) sheets.push(`<article class="sheet-preview"><div class="location-sheet">${labels[index]}${labels[index + 1] || '<div class="empty-half" aria-hidden="true"></div>'}</div></article>`);
    return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><base href="${esc(location.origin)}/"><title>Etiquetas de ubicaciones</title><link rel="stylesheet" href="/assets/location-labels.css?v=20261014-1"></head><body><header class="print-toolbar"><p>TSC TE200 · 101,6 × 76,2 mm<br>Corte central: dos etiquetas de 101,6 × 38,1 mm</p><button id="printLocationLabels" type="button" disabled>Imprimir</button><p id="locationPrintStatus" class="print-status" role="status" aria-live="polite"></p></header><main class="location-preview">${sheets.join('')}</main><script>(${popupApp.toString()})();<\/script></body></html>`;
  }
  return {documentHtml};
})();
