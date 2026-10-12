const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../frontend/static/auth-client.js'),'utf8');
async function auth(status, type, body, url='/api/work-summary') {
  const redirects=[], requests=[];
  const scope = {window:{fetch:async(input,options)=>{requests.push(options);return new Response(body,{status,headers:{'Content-Type':type}})}},
    location:{href:'http://127.0.0.1:9000/reception',origin:'http://127.0.0.1:9000',assign:url=>redirects.push(url)},
    Headers,Request,Response,URL};
  vm.runInNewContext(source,scope);
  return {response:await scope.window.fetch(url),redirects,requests};
}
(async()=>{
  const unauthorized=await auth(401,'text/plain','Unauthorized');
  assert.deepEqual(unauthorized.redirects,['/login']);
  assert.equal(unauthorized.response.status,401);
  assert.match((await unauthorized.response.json()).error,/sesión venció/);
  assert.equal(unauthorized.requests[0].headers.get('X-WMS-Request'),'1');
  assert.equal(unauthorized.requests[0].cache,'no-store');
  const forbidden=await auth(403,'text/html','<h1>Forbidden</h1>');
  assert.equal(forbidden.response.status,403);
  assert.match((await forbidden.response.json()).error,/permiso/);
  const login=await auth(401,'text/plain','Unauthorized','/api/login');
  assert.deepEqual(login.redirects,[]);
  assert.match((await login.response.json()).error,/usuario y la contraseña/);
  const gateway=await auth(200,'text/html','<h1>Login portal</h1>');
  assert.equal(gateway.response.status,502);
  assert.match((await gateway.response.json()).error,/conexión/);
  const excel=await auth(200,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','binary');
  assert.equal(await excel.response.text(),'binary','Do not rewrite valid Excel exports');
  const csv=await auth(200,'text/csv','a;b');
  assert.equal(await csv.response.text(),'a;b');
  const normal=await auth(200,'application/json','{"total":4}');
  assert.equal((await normal.response.json()).total,4);
  const events=[], requests=[];
  let failure=new TypeError('Failed to fetch');
  const scope={window:{WmsConnection:{unavailable:()=>events.push('offline'),available:()=>events.push('online')},
    fetch:async(input,options)=>{requests.push({input,options});if(failure)throw failure;return new Response('{}',{headers:{'Content-Type':'application/json'}})}},
    location:{href:'http://127.0.0.1:9000/reception',origin:'http://127.0.0.1:9000',assign:()=>{throw Error('Network errors must not redirect')}},
    Headers,Request,Response,URL};
  vm.runInNewContext(source,scope);
  const offline=await scope.window.fetch('/api/receptions',{method:'POST',body:'{}'});
  assert.equal(offline.status,503);
  assert.equal(offline.headers.get('X-WMS-Offline'),'1');
  assert.match((await offline.json()).error,/Servidor no disponible/);
  assert.deepEqual(events,['offline']);
  assert.equal(requests.length,1,'No mutation replay');
  failure=new DOMException('Cancelled','AbortError');
  await assert.rejects(scope.window.fetch('/api/receptions'),{name:'AbortError'});
  assert.deepEqual(events,['offline'],'Cancellation is not a connectivity failure');
  failure=null;
  await scope.window.fetch('/api/receptions');
  assert.deepEqual(events,['offline','online']);
  console.log('OK: response boundaries, exports, offline mutations, cancellation and reconnection');
})().catch(error=>{console.error(error);process.exitCode=1});
