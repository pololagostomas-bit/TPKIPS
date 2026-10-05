(() => {
  const input = document.getElementById('np-input');
  const result = document.getElementById('result');
  const status = document.getElementById('status');
  const reader = document.getElementById('reader');
  const searchButton = document.getElementById('search-button');
  const startButton = document.getElementById('start-scan');
  const stopButton = document.getElementById('stop-scan');
  let scanner = null;
  let lastScanned = '';

  function setStatus(message, kind = '') {
    status.textContent = message;
    status.className = `status ${kind}`.trim();
  }

  function quantity(value) {
    return new Intl.NumberFormat('es-PE', { maximumFractionDigits: 2 }).format(Number(value) || 0);
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  }

  function render(item) {
    const locations = item.locations.length
      ? item.locations.map(location => `<span class="location">${escapeHtml(location)}</span>`).join('')
      : '<span class="location">Sin ubicación con stock</span>';
    result.innerHTML = `<div class="result-heading"><div><p class="eyebrow">PRODUCTO ENCONTRADO</p><h2>${escapeHtml(item.description)}</h2></div><span class="np-tag">${escapeHtml(item.np)}</span></div>
      <p class="description">${item.unit ? `Unidad: ${escapeHtml(item.unit)}` : 'Unidad no especificada en el reporte'}</p>
      <div class="metrics"><div class="metric"><span>En stock</span><strong>${quantity(item.stock)}</strong></div><div class="metric"><span>Disponible</span><strong>${quantity(item.available)}</strong></div><div class="metric"><span>Comprometido</span><strong>${quantity(item.committed)}</strong></div><div class="metric"><span>Solicitado</span><strong>${quantity(item.requested)}</strong></div></div>
      <div class="locations"><h3>Ubicación${item.locations.length === 1 ? '' : 'es'} con existencia</h3><div class="location-list">${locations}</div></div>`;
    result.hidden = false;
  }

  async function lookup(value) {
    const np = String(value || '').trim();
    if (!np) {
      setStatus('Escribe o escanea el NP para consultar.', 'error');
      input.focus();
      return;
    }
    input.value = np;
    setStatus('Buscando en el stock cargado…');
    searchButton.disabled = true;
    try {
      const response = await fetch(`/api/product/${encodeURIComponent(np)}`, { cache: 'no-store' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'No se pudo consultar el producto.');
      render(payload);
      setStatus(`Consulta lista para ${payload.np}.`, 'success');
    } catch (error) {
      result.hidden = true;
      setStatus(error.message, 'error');
    } finally {
      searchButton.disabled = false;
    }
  }

  async function startScan() {
    if (!window.Html5Qrcode) {
      setStatus('No se cargó el lector de cámara. Revisa tu conexión a internet o busca el NP manualmente.', 'error');
      return;
    }
    try {
      scanner = scanner || new Html5Qrcode('reader');
      reader.style.display = 'block';
      startButton.disabled = true;
      await scanner.start(
        { facingMode: 'environment' },
        { fps: 10, qrbox: { width: 280, height: 140 }, aspectRatio: 1.777 },
        decodedText => {
          const scanned = String(decodedText || '').trim();
          if (scanned && scanned !== lastScanned) {
            lastScanned = scanned;
            lookup(scanned);
          }
        },
        () => {},
      );
      stopButton.disabled = false;
      setStatus('Cámara activa. Centra el código de barras dentro del recuadro.');
    } catch (error) {
      startButton.disabled = false;
      reader.style.display = 'none';
      setStatus(`No se pudo abrir la cámara: ${error.message || 'revisa el permiso del navegador.'}`, 'error');
    }
  }

  async function stopScan() {
    if (scanner?.isScanning) await scanner.stop();
    reader.style.display = 'none';
    startButton.disabled = false;
    stopButton.disabled = true;
    lastScanned = '';
  }

  searchButton.addEventListener('click', () => lookup(input.value));
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter') lookup(input.value);
  });
  startButton.addEventListener('click', startScan);
  stopButton.addEventListener('click', stopScan);

  fetch('/api/health', { cache: 'no-store' })
    .then(response => response.json())
    .then(info => { document.getElementById('source-note').textContent = `Fuente: ${info.source} · ${quantity(info.products)} productos del catálogo`; })
    .catch(() => {});
})();
