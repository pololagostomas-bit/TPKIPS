/* Network-only operational client. Never serve a cached authenticated screen. */
const OFFLINE_PAGE = `<!doctype html><html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Servidor no disponible | TRITON WMS</title><style>
*{box-sizing:border-box}body{margin:0;background:#f4f5f5;color:#29343b;font:16px/1.5 "Segoe UI",Arial,sans-serif}
main{max-width:460px;margin:80px auto;padding:24px}header{font-weight:700;border-top:3px solid #f58200;padding-top:16px}
h1{font-size:24px;margin:28px 0 12px;overflow-wrap:anywhere}p{margin:0 0 24px;color:#526169}
button{font:inherit;min-height:44px;padding:10px 20px;border:1px solid #9a5100;border-radius:6px;background:#f58200;color:#17232b;cursor:pointer}
button:focus-visible{outline:3px solid #176b87;outline-offset:3px}@media(max-height:500px){main{margin-top:12px}}
</style></head><body><main id="wmsOffline"><header>TRITON WMS</header>
<h1>Servidor no disponible</h1><p>No hay conexion con el servidor. Comprueba la conexion e intenta nuevamente.</p>
<button type="button" onclick="location.reload()">Reintentar</button></main></body></html>`;

self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil((async () => {
  const keys = await caches.keys();
  await Promise.all(keys.filter(key => key.startsWith('triton-picking-') || key.startsWith('triton-wms-')).map(key => caches.delete(key)));
  await self.clients.claim();
})()));

function unavailable(request) {
  const headers = {'Cache-Control':'no-store', 'X-WMS-Offline':'1', 'X-Content-Type-Options':'nosniff'};
  if (request.mode === 'navigate') {
    headers['Content-Type'] = 'text/html; charset=utf-8';
    headers['Content-Security-Policy'] = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";
    return new Response(OFFLINE_PAGE, {status:503, headers});
  }
  if (new URL(request.url).pathname.startsWith('/api/')) {
    headers['Content-Type'] = 'application/json; charset=utf-8';
    return new Response(JSON.stringify({error:'Servidor no disponible. Comprueba la conexion e intenta nuevamente.'}), {status:503, headers});
  }
  headers['Content-Type'] = 'text/plain; charset=utf-8';
  return new Response('Servidor no disponible', {status:503, headers});
}

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET' || new URL(request.url).origin !== self.location.origin) return;
  event.respondWith((async () => {
    try {
      const response = await fetch(request, {cache:'no-store'});
      return request.mode === 'navigate' && response.status >= 500 ? unavailable(request) : response;
    } catch (_) { return unavailable(request); }
  })());
});
