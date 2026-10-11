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
  console.log('OK: 7 response boundaries, redirects, login errors and binary/CSV exports');
})().catch(error=>{console.error(error);process.exitCode=1});
