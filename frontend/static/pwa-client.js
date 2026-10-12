/* No automatic reload, replay or storage reset: keep unsaved work intact. */
(() => {
  'use strict';
  let disconnected = false, checking = false;
  function keepFocusVisible() {
    const node = document.getElementById('wmsConnectionStatus'), focus = document.activeElement;
    if (!node || node.hidden || !focus || focus === document.body || node.contains(focus)) return;
    const box = focus.getBoundingClientRect(), warning = node.getBoundingClientRect();
    if (box.bottom > warning.top && box.top < warning.bottom) focus.scrollIntoView({block:'center',behavior:'instant'});
  }
  function reserveSpace() {
    const node = document.getElementById('wmsConnectionStatus');
    const space = document.getElementById('wmsConnectionSpace');
    if (!space || !node) return;
    space.style.height = node.hidden ? '0px' : node.offsetHeight + 12 + 'px';
    requestAnimationFrame(keepFocusVisible);
  }
  function banner() {
    if (!document.body) return;
    let node = document.getElementById('wmsConnectionStatus');
    if (!node && disconnected) {
      node = document.createElement('aside'); node.id = 'wmsConnectionStatus';
      node.setAttribute('role','status'); node.setAttribute('aria-live','polite');
      node.innerHTML = '<span>Servidor no disponible. Comprueba la conexion antes de registrar cambios.</span><button type="button">Reintentar conexion</button>';
      node.querySelector('button').onclick = checkConnection;
      document.body.append(node);
      const space = document.createElement('div'); space.id = 'wmsConnectionSpace'; space.setAttribute('aria-hidden','true');
      document.body.append(space);
      if ('ResizeObserver' in window) new ResizeObserver(reserveSpace).observe(node);
    }
    if (node) node.hidden = !disconnected;
    reserveSpace();
  }
  function unavailable() { disconnected = true; banner(); }
  function available() { disconnected = false; banner(); }
  async function checkConnection() {
    if (checking) return;
    checking = true;
    const button = document.querySelector('#wmsConnectionStatus button');
    if (button) button.disabled = true;
    try {
      const response = await fetch('/health', {cache:'no-store',credentials:'same-origin'});
      const data = response.ok ? await response.json() : null;
      if (data?.status === 'ok') available(); else unavailable();
    } catch (_) { unavailable(); }
    finally { checking = false; if (button) button.disabled = false; }
  }
  window.WmsConnection = {unavailable, available};
  window.addEventListener('offline', unavailable);
  window.addEventListener('online', () => { if (disconnected) checkConnection(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && disconnected) checkConnection(); });
  document.addEventListener('focusin', () => { if (disconnected) requestAnimationFrame(keepFocusVisible); });
  function ready() {
    banner();
    const root = document.documentElement;
    if (root.dataset.wmsUi !== 'loading') return;
    const workspace = ['/', '/reception'].includes(location.pathname);
    if (!document.body.classList.contains('reader-ui') || (workspace && !document.body.classList.contains('unified-workspace'))) {
      window.wmsBootFailure(); return;
    }
    root.dataset.wmsUi = 'ready';
    clearTimeout(window.wmsBootTimeout);
    document.getElementById('wmsBootStatus')?.remove();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready, {once:true});
  else ready();
  try {
    if (window === window.top && 'serviceWorker' in navigator) {
      navigator.serviceWorker.register('/service-worker.js', {updateViaCache:'none'}).catch(() => {});
    }
  } catch (_) { /* Unsupported/embedded browsers can still use the online client. */ }
})();
