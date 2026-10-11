/* Session boundary shared by both server pilots. */
(() => {
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    if (url.origin === location.origin && url.pathname.startsWith('/api/')) {
      const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
      headers.set('X-WMS-Request','1');
      const response = await originalFetch(input, {...options, headers});
      if (response.headers.get('X-WMS-Password-Change') === 'required') location.assign('/change-password');
      if (response.status === 401 && url.pathname !== '/api/login') location.assign('/login');
      const contentType = response.headers.get('Content-Type') || '';
      if (!contentType.includes('application/json') && (!response.ok || /text\/(html|plain)/i.test(contentType))) {
        const error = response.status === 401 ? (url.pathname === '/api/login'
          ? 'No se pudo iniciar sesión. Revisa el usuario y la contraseña.'
          : 'Tu sesión venció. Vuelve a ingresar.') :
          response.status === 403 ? 'No tienes permiso para esta operación.' :
          'El servidor no respondió correctamente. Revisa la conexión e intenta nuevamente.';
        return new Response(JSON.stringify({error}),
          {status:response.ok ? 502 : response.status,headers:{'Content-Type':'application/json; charset=utf-8'}});
      }
      return response;
    }
    return originalFetch(input, options);
  };
  window.installSessionControls = me => {
    window.wmsIdentity = me;
    if (me.must_change_password) {location.assign('/change-password');return;}
    if (me.mode === 'demo') return;
    const actions = document.querySelector('.toolbar-actions');
    if (!actions || document.getElementById('sessionLogout')) return;
    const button = document.createElement('button');
    button.id = 'sessionLogout'; button.className = 'ghost'; button.textContent = 'Salir';
    button.onclick = async () => {await fetch('/api/logout',{method:'POST'}); location.assign('/login');};
    actions.append(button);
  };
})();
