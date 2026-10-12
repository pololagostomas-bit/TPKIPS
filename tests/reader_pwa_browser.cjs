// Real service worker and a disposable proxy: never use a production origin.
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),http=require('node:http');
const fs=require('node:fs'),path=require('node:path');
const upstream=process.argv[2];
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(upstream||''))throw Error('Disposable loopback fixture required');
const output=path.join(__dirname,'../qa/reader-pwa');
const worker=fs.readFileSync(path.join(__dirname,'../frontend/static/service-worker.js'),'utf8');
const oldWorker=`const CACHE='triton-wms-pilot-v2-20260911';
self.addEventListener('install',e=>e.waitUntil((async()=>{const c=await caches.open(CACHE);await c.put('/reception',new Response('<h1>LEGACY FIXTURE UI</h1>',{headers:{'Content-Type':'text/html'}}));await self.skipWaiting()})()));
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>{if(e.request.method==='GET')e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)))});`;
let legacy=true,failedAsset='',httpFailure=false,delayAsset='',mutations=0;
const proxy=http.createServer(async(req,res)=>{
  const url=new URL(req.url,upstream);
  if(req.method!=='GET')mutations++;
  if(url.pathname==='/service-worker.js'){
    res.writeHead(200,{'Content-Type':'application/javascript','Cache-Control':'no-store'});res.end(legacy?oldWorker:worker);return;
  }
  if(httpFailure){res.writeHead(503,{'Content-Type':'text/html'});res.end('<h1>Gateway unavailable</h1>');return;}
  if(url.pathname===failedAsset){res.writeHead(404,{'Content-Type':'text/plain'});res.end('QA missing asset');return;}
  if(url.pathname===delayAsset)await new Promise(resolve=>setTimeout(resolve,650));
  try{
    const chunks=[];for await(const chunk of req)chunks.push(chunk);
    const headers={...req.headers};delete headers.host;
    const response=await fetch(url,{method:req.method,headers,body:chunks.length?Buffer.concat(chunks):undefined,redirect:'manual'});
    const data=Buffer.from(await response.arrayBuffer()),outHeaders=Object.fromEntries(response.headers);
    delete outHeaders['content-encoding'];delete outHeaders['transfer-encoding'];outHeaders['content-length']=data.length;
    res.writeHead(response.status,outHeaders);res.end(data);
  }catch(_){res.destroy();}
});
const listen=port=>new Promise(resolve=>proxy.listen(port,'127.0.0.1',resolve));
const stop=()=>new Promise(resolve=>{proxy.close(resolve);proxy.closeAllConnections();});
(async()=>{
  fs.mkdirSync(output,{recursive:true});await listen(0);
  const port=proxy.address().port,base='http://127.0.0.1:'+port;
  const browser=await chromium.launch({headless:true,channel:process.env.WMS_QA_BROWSER_CHANNEL||'msedge'});
  const context=await browser.newContext({viewport:{width:393,height:873},reducedMotion:'reduce'});
  const page=await context.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  // Camera CDN is irrelevant here; do not let it delay this network test.
  await context.route('https://unpkg.com/**',route=>route.abort());
  async function ready(route){await page.goto(base+route);await page.waitForFunction(()=>document.documentElement.dataset.wmsUi==='ready');}
  async function capture(name){
    const box=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,
      small:[...document.querySelectorAll('button')].filter(b=>b.checkVisibility()&&b.getBoundingClientRect().height<44).map(b=>b.textContent)}));
    assert.ok(box.scroll<=box.width+1,name+': horizontal overflow');assert.deepEqual(box.small,[],name+': touch targets');
    await page.screenshot({path:path.join(output,name+'.png')});
  }
  try{
    await ready('/reception');
    await page.waitForFunction(()=>!!navigator.serviceWorker.controller);
    await page.evaluate(async()=>{
      await (await caches.open('triton-picking-obsolete')).put('/old',new Response('old'));
      await (await caches.open('unrelated-qa')).put('/other',new Response('keep'));
      localStorage.setItem('wms-qa-unsaved','preserve');sessionStorage.setItem('wms-qa-view','preserve');
    });
    await stop();await page.goto(base+'/reception');
    assert.equal(await page.locator('h1').innerText(),'LEGACY FIXTURE UI','Reproduce the old cached app first');
    await listen(port);legacy=false;
    await page.evaluate(async()=>{await (await navigator.serviceWorker.getRegistration()).update();});
    await page.waitForFunction(async()=>!(await caches.keys()).some(k=>k.startsWith('triton-wms-')||k.startsWith('triton-picking-')));
    assert.equal(await page.evaluate(async()=>!!(await caches.match('/other'))),true,'Preserve unrelated caches');
    assert.equal(await page.evaluate(()=>localStorage.getItem('wms-qa-unsaved')),'preserve');
    assert.equal(await page.evaluate(()=>sessionStorage.getItem('wms-qa-view')),'preserve');
    for(const route of ['/','/reception','/inventory'])await ready(route);
    await page.evaluate(()=>showRequestForm());
    await page.locator('[name=justification]').fill('Unsaved work must survive reconnection');
    const initialMutations=mutations;
    await stop();
    const failed=await page.evaluate(async()=>{const r=await fetch('/api/inventory/requests',{method:'POST',body:'{}'});return {status:r.status,data:await r.json()};});
    assert.equal(failed.status,503);assert.match(failed.data.error,/Servidor no disponible/);
    await page.locator('#wmsConnectionStatus').waitFor();await capture('connection-lost-393');
    assert.equal(await page.locator('[name=justification]').inputValue(),'Unsaved work must survive reconnection');
    await page.locator('#materialRequestForm [type=submit]').focus();await page.waitForTimeout(100);
    assert.equal(await page.locator('#materialRequestForm [type=submit]').evaluate(n=>{const b=n.getBoundingClientRect();return n.contains(document.elementFromPoint(b.left+b.width/2,b.top+b.height/2));}),true,'Warning must not obscure focused submit');
    await capture('connection-lost-submit-393');
    await listen(port);await page.locator('#wmsConnectionStatus button').click();
    await page.waitForSelector('#wmsConnectionStatus',{state:'hidden'});
    assert.equal(await page.locator('[name=justification]').inputValue(),'Unsaved work must survive reconnection');
    assert.equal(mutations,initialMutations,'No automatic replay on recovery');
    httpFailure=true;await page.goto(base+'/reception');
    assert.equal(await page.locator('#wmsOffline h1').innerText(),'Servidor no disponible');
    httpFailure=false;await page.locator('#wmsOffline button').click();await page.waitForFunction(()=>document.documentElement.dataset.wmsUi==='ready');
    await stop();
    for(const route of ['/','/reception','/inventory','/login','/change-password','/cloud-connection','/purchase-alerts']){
      const response=await page.goto(base+route);assert.equal(response.status(),503);
      assert.equal(response.headers()['x-wms-offline'],'1');
      assert.equal(await page.locator('#wmsOffline h1').innerText(),'Servidor no disponible');
      assert.equal(await page.locator('form,header.top,.workspace-rail,.profile-chip').count(),0,'No stale operational screen');
    }
    for(const viewport of [{width:1440,height:900},{width:393,height:873},{width:375,height:812},{width:360,height:780},{width:873,height:393}]){
      await page.setViewportSize(viewport);await capture('offline-'+viewport.width);
    }
    await page.evaluate(()=>document.querySelector('main').style.fontSize='24px');await capture('offline-large-text');
    await listen(port);await ready('/reception');
    await page.setViewportSize({width:393,height:873});
    for(const asset of ['/assets/reader-ui.css','/assets/reader-ui.js','/assets/workspace-shell.js','/assets/pwa-client.js']){
      failedAsset=asset;await page.goto(base+'/reception');
      await page.waitForFunction(()=>document.documentElement.dataset.wmsUi==='failed');
      assert.equal(await page.locator('#wmsBootStatus h1').innerText(),'No se pudo cargar la interfaz');
      assert.equal(await page.locator('header.top').evaluate(n=>getComputedStyle(n).visibility),'hidden');
      assert.equal(await page.locator('#wmsBootStatus button').isVisible(),true);
      await capture('missing-'+path.basename(asset));
    }
    failedAsset='';delayAsset='/assets/workspace-shell.js';
    await page.goto(base+'/reception',{waitUntil:'commit'});await page.locator('#wmsBootStatus').waitFor();
    assert.equal(await page.locator('#wmsBootStatus h1').innerText(),'Cargando interfaz');
    await capture('loading');await page.waitForFunction(()=>document.documentElement.dataset.wmsUi==='ready');
    assert.deepEqual(errors,[],'No runtime errors on tested routes');
    console.log('OK: reproduced legacy cache; migrated without losing storage; seven offline routes; five viewport sizes; safe reconnection; four asset failures; loading gate');
  }finally{await browser.close();if(proxy.listening)await stop();}
})().catch(error=>{console.error(error);process.exitCode=1;proxy.closeAllConnections();proxy.close();});
