const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../frontend/static/service-worker.js'),'utf8');
const listeners = {}, removed = [], network = [];
let fail = false, status = 200, claims = 0, skips = 0;
const scope = {URL,Response,Promise,self:{location:{origin:'http://127.0.0.1:9000'},
  addEventListener:(name,fn)=>listeners[name]=fn,skipWaiting:async()=>{skips++;},clients:{claim:async()=>{claims++;}}},
  caches:{keys:async()=>['triton-wms-pilot-v2-20260911','triton-picking-v1','unrelated-app'],delete:async key=>{removed.push(key);return true;}},
  fetch:async(request,options)=>{network.push({request,options});if(fail)throw Error('Network unavailable');return new Response('LIVE',{status});}};
vm.runInNewContext(source,scope);
async function event(name,request) {
  let promise;
  listeners[name]({request,waitUntil:value=>promise=value,respondWith:value=>promise=value});
  return promise;
}
const request=(url,mode='navigate',method='GET')=>({url:'http://127.0.0.1:9000'+url,mode,method});
(async()=>{
  await event('install');assert.equal(skips,1);
  await event('activate');assert.deepEqual(removed,['triton-wms-pilot-v2-20260911','triton-picking-v1']);assert.equal(claims,1);
  assert.equal(await (await event('fetch',request('/reception'))).text(),'LIVE');
  assert.equal(network.at(-1).options.cache,'no-store');
  status=401;assert.equal((await event('fetch',request('/api/me','same-origin'))).status,401);
  status=503;assert.match(await (await event('fetch',request('/'))).text(),/wmsOffline/);
  fail=true;
  for(const url of ['/','/reception','/inventory','/login','/change-password','/cloud-connection','/purchase-alerts']) {
    const response=await event('fetch',request(url));
    assert.equal(response.status,503);assert.equal(response.headers.get('X-WMS-Offline'),'1');
    assert.equal(response.headers.get('Cache-Control'),'no-store');
    const text=await response.text();assert.match(text,/Servidor no disponible/);assert.doesNotMatch(text,/workspace-variant|id="role"|id="user"/);
  }
  const api=await event('fetch',request('/api/me','same-origin'));assert.equal(api.status,503);assert.match((await api.json()).error,/Servidor no disponible/);
  assert.equal((await event('fetch',request('/assets/reader-ui.css','same-origin'))).status,503);
  const before=network.length;
  assert.equal(await event('fetch',request('/api/scan','same-origin','POST')),undefined);
  assert.equal(await event('fetch',{url:'https://example.invalid/a.js',mode:'cors',method:'GET'}),undefined);
  assert.equal(network.length,before,'No mutation replay or cross-origin interception');
  console.log('OK: cache migration, seven offline routes, network-only data/assets, auth and mutation boundaries');
})().catch(error=>{console.error(error);process.exitCode=1});
