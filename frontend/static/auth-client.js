/* Shared session boundary. Existing role headers are ignored by local authentication. */
(() => {
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    if (url.origin === location.origin && url.pathname.startsWith('/api/')) {
      const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
      headers.set('X-WMS-Request','1');
      const response = await originalFetch(input, {...options, headers});
      if (response.status === 401 && url.pathname !== '/api/login') location.assign('/login');
      return response;
    }
    return originalFetch(input,options);
  };
  window.installSessionControls = me => {
    window.wmsIdentity = me;
    if (me.mode === 'demo') return;
    const actions = document.querySelector('.toolbar-actions');
    if (!actions || document.getElementById('sessionLogout')) return;
    const button = document.createElement('button');
    button.id = 'sessionLogout'; button.className='ghost'; button.textContent='Salir';
    button.onclick = async () => { await fetch('/api/logout',{method:'POST'}); location.assign('/login'); };
    actions.append(button);
  };
})();
