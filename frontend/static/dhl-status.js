(() => {
  'use strict';
  const host = document.getElementById('dhlConnection');
  if (!host) return;
  const text = document.getElementById('dhlConnectionStatus'), facts = document.getElementById('dhlConnectionFacts');
  const retry = document.getElementById('dhlRetry');
  const labels = {disabled:'DHL desactivado',configuration:'DHL pendiente de configuracion',connected:'DHL conectado',
    stale:'DHL sin actividad reciente',authorization:'DHL requiere revisar el acceso',quota:'Presupuesto diario DHL alcanzado',waiting:'DHL en pausa temporal'};
  let timer, disposed = false, busy = false;
  async function refresh(reconnect = false) {
    if (busy || disposed) return;
    busy = true; retry.disabled = true;
    try {
      const response = await fetch('/api/dhl-tracking/' + (reconnect ? 'retry' : 'status'), reconnect ? {
        method:'POST',headers:{'Content-Type':'application/json','X-WMS-Request':'1'},body:'{}'
      } : {cache:'no-store'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'No se pudo consultar DHL.');
      text.textContent = [labels[data.state] || 'Estado DHL pendiente', data.error].filter(Boolean).join(' · ');
      text.className = ['connected','disabled'].includes(data.state) ? '' : 'warning';
      facts.textContent = data.calls_today + ' / ' + data.daily_budget + ' consultas hoy (UTC) · '
        + data.cached_guides + ' guias guardadas · ' + data.queued_guides + ' en cola · Revision cada ' + data.refresh_hours + ' h'
        + ' · Precarga: mes actual y proximas llegadas, hasta ' + data.prefetch_limit + ' guias';
      if (data.resume_at) facts.textContent += ' · Reintento desde ' + new Date(data.resume_at * 1000).toLocaleString('es-PE');
      retry.hidden = data.state !== 'authorization';
    } catch (error) { text.textContent = error.message; text.className = 'warning'; }
    finally { busy = false; retry.disabled = false; }
  }
  retry.onclick = () => refresh(true);
  document.getElementById('refresh')?.addEventListener('click', () => refresh());
  function tick() { if (disposed) return; if (!document.hidden) refresh(); timer = setTimeout(tick,30000); }
  window.addEventListener('pagehide', () => { disposed = true; clearTimeout(timer); });
  window.addEventListener('pageshow', event => { if (event.persisted) { disposed = false; refresh(); timer = setTimeout(tick,30000); } });
  refresh(); timer = setTimeout(tick,30000);
})();
