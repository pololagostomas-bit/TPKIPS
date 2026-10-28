/* Camera transport only. The existing receipt/count flows own validation and saving. */
window.WmsCamera = (() => {
  let bridge, active = null, sequence = 0, library, opening = null;
  const byId = id => document.getElementById(id);
  const connected = session => active === session && session.key === bridge.context(session.target)?.key;

  function focusInput(input, options) {
    if (!input) return;
    if (input.matches('[data-wms-scan-input]')) {
      if (document.activeElement === input) input.blur();
      input.inputMode = 'none';
    }
    input.focus(options);
  }

  function manualInput(input) {
    if (!input || input.disabled || input.readOnly) return;
    if (input.matches('[data-wms-scan-input]')) {
      if (document.activeElement === input) input.blur();
      input.inputMode = input.dataset.manualInputmode || 'text';
    }
    input.focus(); input.select?.();
  }

  function overlay() {
    let root = byId('wmsBarcodeCamera');
    if (root) return root;
    document.body.insertAdjacentHTML('beforeend', `<div id="wmsBarcodeCamera" class="wms-camera-overlay" hidden>
      <section class="wms-camera-dialog" role="dialog" aria-modal="true" aria-labelledby="wmsCameraTitle">
        <header><h2 id="wmsCameraTitle">Escanear codigo</h2><button type="button" class="ghost" id="wmsCameraClose">Cerrar</button></header>
        <div id="wmsCameraStatus" role="status" aria-live="polite"></div>
        <div id="wmsCameraError" role="alert" hidden></div>
        <div id="wmsBarcodeReader" class="wms-camera-reader"></div>
        <label class="wms-camera-continuous"><input id="wmsCameraContinuous" type="checkbox">Continuar escaneando</label>
        <div class="actions"><button id="wmsCameraResume" class="primary" type="button" hidden>Reintentar lectura</button>
          <button id="wmsCameraManual" class="ghost" type="button">Ingresar sin camara</button></div>
      </section></div>`);
    root = byId('wmsBarcodeCamera');
    byId('wmsCameraClose').addEventListener('click', () => close());
    byId('wmsCameraManual').addEventListener('click', async () => {
      const session = active;
      await close();
      if (session) bridge.manual?.(session.target, session.inputId);
    });
    byId('wmsCameraResume').addEventListener('click', () => {
      if (!active || !connected(active) || !active.scanner) return;
      active.paused = false; active.last = ''; active.lastAt = 0;
      byId('wmsCameraError').hidden = true; byId('wmsCameraResume').hidden = true;
      byId('wmsCameraStatus').textContent = 'Listo para leer';
    });
    root.addEventListener('click', event => { if (event.target === root) close(); });
    root.addEventListener('keydown', event => {
      if (event.key === 'Escape') {event.preventDefault(); close();}
      if (event.key !== 'Tab') return;
      const fields = [...root.querySelectorAll('button,input')].filter(item => !item.hidden && !item.disabled && item.getClientRects().length);
      const first = fields[0], last = fields.at(-1);
      if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last?.focus();}
      else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus();}
    });
    return root;
  }

  function loadLibrary() {
    if (window.Html5Qrcode) return Promise.resolve();
    if (!library) library = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = '/assets/html5-qrcode.min.js?v=2.3.8';
      const fail = () => {
        clearTimeout(timer); script.remove(); library = null;
        reject(new Error('No se pudo cargar la camara. Usa Ingresar sin camara.'));
      };
      const timer = setTimeout(fail, 10000);
      script.onerror = fail;
      script.onload = () => {if (!window.Html5Qrcode) return fail(); clearTimeout(timer); resolve();};
      document.head.append(script);
    });
    return library;
  }

  async function release(session) {
    if (!session?.scanner || session.starting) return;
    try { if (session.scanner.isScanning) await session.scanner.stop(); } catch {}
    try { session.scanner.clear(); } catch {}
    session.scanner = null;
  }

  async function close(restore = true) {
    const session = active;
    active = null; sequence++;
    if (byId('wmsBarcodeCamera')) byId('wmsBarcodeCamera').hidden = true;
    await release(session);
    if (restore && !active) {
      const field = byId(session?.inputId);
      focusInput(field && !field.disabled ? field : session?.opener);
    }
  }

  function error(session, message, retry = false) {
    if (!connected(session)) return;
    session.paused = true;
    byId('wmsCameraError').textContent = message;
    byId('wmsCameraError').hidden = false;
    byId('wmsCameraResume').hidden = !retry;
    byId('wmsCameraStatus').textContent = 'Lectura detenida';
  }

  async function receive(session, raw) {
    if (!connected(session) || session.busy || session.paused) return;
    const code = String(raw || '').trim(), now = Date.now();
    if (!code) return;
    if (code === session.last && now - session.lastAt < 1200) {session.lastAt = now; return;}
    session.last = code; session.lastAt = now;
    if (code.length > 512 || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(code)) {
      error(session, 'El codigo no es valido. Ingresa el codigo impreso o elige el registro.', true); return;
    }
    session.busy = true;
    byId('wmsCameraStatus').textContent = 'Validando ' + code;
    try {
      const result = await bridge.accept(session.target, code, session.key);
      if (!connected(session)) {if (active === session) await close(false); return;}
      if (result?.state === 'choice') {await close(false); bridge.choice?.(session.target); return;}
      if (!result || result.state === 'error') {
        error(session, result?.message || 'No se pudo confirmar la lectura. Revisa el registro antes de reintentar.', true); return;
      }
      byId('wmsCameraStatus').textContent = result.message || 'Codigo registrado: ' + code;
      if (!byId('wmsCameraContinuous').checked) await close();
    } catch (failure) {
      error(session, failure.message || 'No se pudo confirmar la lectura. Usa Ingresar sin camara.', true);
    } finally {session.busy = false;}
  }

  async function open(inputId, target) {
    const context = bridge.context(target), input = byId(inputId);
    if (!context?.key || !input || input.disabled || input.readOnly) return;
    // An earlier permission/start promise must finish before sharing the same video host.
    if (opening) return;
    window.WmsScanFeedback?.arm();
    const openingToken = {}; opening = openingToken;
    await close(false);
    const session = {key:context.key, inputId, target, opener:document.activeElement,
      scanner:null, starting:true, busy:false, paused:false, last:'', lastAt:0, serial:++sequence};
    active = session;
    const root = overlay(); root.hidden = false;
    byId('wmsCameraError').hidden = true; byId('wmsCameraResume').hidden = true;
    const location = /^reception-location(?::\d+|-np)$/.test(target);
    byId('wmsCameraContinuous').checked = !location && target !== 'truck-bl';
    byId('wmsCameraContinuous').closest('label').hidden = location;
    byId('wmsCameraTitle').textContent = target === 'reception-location-np' ? 'Escanear NP para ubicar' : location ? 'Escanear ubicación' : target === 'reception-np' ? 'Escanear NP' : target === 'truck-package' ? 'Escanear bulto' : 'Escanear BL';
    byId('wmsCameraStatus').textContent = 'Abriendo camara...';
    byId('wmsCameraClose').focus();
    try {
      if (!window.isSecureContext) throw new Error('La camara requiere HTTPS. Puedes ingresar el codigo sin camara.');
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Este navegador no ofrece camara. Puedes usar el lector o ingresar el codigo.');
      await loadLibrary();
      if (!connected(session)) return;
      session.scanner = new Html5Qrcode('wmsBarcodeReader');
      await session.scanner.start({facingMode:'environment'}, {
        fps:10,
        qrbox:(width, height) => {
          const side = Math.min(260, Math.floor(Math.min(width, height) * .8));
          return {width:Math.max(50, side), height:Math.max(50, side)};
        }
      }, value => receive(session, value), () => {});
      if (!connected(session)) {await release(session); return;}
      byId('wmsCameraStatus').textContent = 'Listo para leer';
    } catch (failure) {
      session.startFailed = true;
      if (connected(session)) {
        const message = /NotAllowed|Permission|denied/i.test(String(failure)) ?
          'Permiso de camara denegado. Puedes usar el lector o Ingresar sin camara.' :
          'No se pudo abrir la camara. Puedes usar el lector o Ingresar sin camara.';
        error(session, failure instanceof Error && !session.scanner ? failure.message : message);
      }
      await release(session);
    } finally {
      session.starting = false;
      if (active !== session || session.startFailed) await release(session);
      if (opening === openingToken) opening = null;
    }
  }

  function changed() {
    if (active && !connected(active)) close(false);
  }

  function init(callbacks) {
    bridge = callbacks;
    document.addEventListener('pointerdown', event => {
      if (event.target.matches?.('[data-wms-scan-input]')) manualInput(event.target);
    }, true);
    document.addEventListener('focusout', event => {
      if (event.target.matches?.('[data-wms-scan-input]')) event.target.inputMode = 'none';
    });
    document.addEventListener('visibilitychange', () => {if (document.hidden) close(false);});
    window.addEventListener('pagehide', () => close(false));
  }
  return {init, open, close, changed, focusInput, manualInput};
})();
