(() => {
  window.addEventListener('hashchange', () => {if (location.hash) location.reload();});
  const token = new URLSearchParams(location.hash.slice(1)).get('token') || '';
  history.replaceState(null, '', location.pathname);
  const get = id => document.getElementById(id);
  let pending = false, valid = false;
  const checked = get('checked'), button = get('confirmButton');
  async function call(action, extra = {}) {
    const response = await fetch('/api/transfer-confirmation/' + action, {
      method:'POST',credentials:'omit',cache:'no-store',referrerPolicy:'no-referrer',
      headers:{'Content-Type':'application/json','X-WMS-Request':'1'}, body:JSON.stringify({token,...extra})});
    if (!response.headers.get('Content-Type')?.includes('application/json')) throw new Error('No se pudo conectar. Vuelve a abrir el enlace.');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'No se pudo completar la solicitud.');
    return data;
  }
  function done() {
    valid = false;get('request').hidden = true;
    get('status').textContent = 'Transferencia en SAP confirmada. Gracias.';
  }
  checked.addEventListener('change', () => {button.disabled = pending || !valid || !checked.checked;});
  get('confirmForm').addEventListener('submit', async event => {
    event.preventDefault();if (!valid || pending || !checked.checked) return;
    pending = true;button.disabled = true;checked.disabled = true;get('error').textContent = '';
    button.textContent = 'Confirmando…';
    try {await call('confirm', {checked:true});done();}
    catch (error) {get('error').textContent = error.message;}
    finally {pending = false;checked.disabled = false;button.disabled = !valid || !checked.checked;button.textContent = 'Confirmar transferencia realizada';}
  });
  (async () => {
    try {
      if (!token) throw new Error('Enlace no disponible. Solicita uno nuevo.');
      const data = await call('inspect');
      if (data.confirmed) {done();return;}
      get('bl').textContent = data.bl_awb;get('attention').textContent = data.attention;
      get('em').textContent = data.em_number || 'Sin EM registrada';
      get('status').textContent = 'Pendiente de transferencia en SAP';
      valid = true;get('request').hidden = false;
    } catch (error) {get('status').textContent = 'No se pudo validar el enlace';get('error').textContent = error.message;}
  })();
})();
