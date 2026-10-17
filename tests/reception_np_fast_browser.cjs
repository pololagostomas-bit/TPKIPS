// Disposable support_reception_items_server.py only; never production.
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],output=path.join(__dirname,'../qa/np-fast');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable loopback fixture required');
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 try{
  const sizes=[[1440,900],[393,873],[375,812],[320,640],[820,1000],[821,900],[873,393]];
  for(const [index,[width,height]] of sizes.entries()){
   const context=await browser.newContext({viewport:{width,height},reducedMotion:'reduce'}),page=await context.newPage();
   await context.addInitScript(()=>{if('serviceWorker'in navigator)navigator.serviceWorker.register=async()=>undefined;});
   page.on('pageerror',error=>errors.push(error.message));page.on('dialog',d=>d.accept());
   const id=5+index;let writes=0;
   page.on('request',r=>{if(r.method()==='POST'&&r.url().includes(`/api/receptions/${id}/lines/`))writes++;});
   await page.goto(base+'/reception');await page.waitForFunction(()=>typeof loadDetail==='function');
   await page.evaluate(id=>loadDetail(id),id);await page.locator('#scanReceptionNp').waitFor();
   const scan=async code=>{await page.locator('#scanReceptionNp').fill(code);await page.locator('#scanReceptionNp').press('Enter');};
   const settled=()=>page.waitForFunction(()=>!WmsNpScan.hasPending());
   assert.match(await page.locator('#receptionNpProgress').innerText(),/0\/3/);
   await page.locator('[data-save-physical-review]').click();
   assert.match(await page.locator('#receptionNpMissing').innerText(),/Faltan 3 NP/);assert.equal(writes,0);
   await scan(']d1NP-NOSTOCK');await settled();assert.equal(writes,1);
   assert.equal(await page.evaluate(()=>document.activeElement?.id),'scanReceptionNp');
   assert.equal(await page.locator('#receptionNpQuantity').count(),0);
   assert.match(await page.locator('#receptionNpScanResult').innerText(),/Cantidad 5/);
   assert.match(await page.locator('#receptionNpScanResult').innerText(),/Sin stock/);
   assert.doesNotMatch(await page.locator('#receptionNpScanResult').innerText(),/QA-OV|QA-IP|Linea|Línea/);
   assert.match(await page.locator('#receptionNpProgress').innerText(),/1\/3/);
   await scan('NP-NOSTOCK');await settled();assert.equal(writes,1);
   await scan('NP-ZERO');await settled();assert.equal(writes,2);
   assert.match(await page.locator('#receptionNpScanResult').innerText(),/Cantidad 0/);
   await scan('NP-001');await page.locator('.np-match').first().waitFor();
   assert.equal(await page.locator('#receptionNpQuantity').count(),0);
   await page.locator('.np-match').filter({hasText:'QA-OV-1'}).click();await settled();
   await scan('NP-001');await page.locator('.np-match').waitFor();
   assert.equal(writes,3,'Repeated NP must not consume another OV implicitly');
   await page.locator('.np-match').click();await settled();
   assert.equal(await page.locator('.np-match').count(),0,'Remaining order saved after explicit selection');
   assert.equal(writes,4);assert.match(await page.locator('#receptionNpProgress').innerText(),/3\/3/);
   assert.equal(await page.evaluate(()=>WmsNpScan.canComplete()),true);
   await page.reload();await page.waitForFunction(()=>typeof loadDetail==='function');
   await page.evaluate(id=>loadDetail(id),id);await page.locator('#scanReceptionNp').waitFor();
   assert.match(await page.locator('#receptionNpProgress').innerText(),/3\/3/);
   await page.locator('#scanReceptionNp').fill('NP-NOSTOCK');
   await page.getByRole('button',{name:'Corregir NP',exact:true}).click();
   await page.locator('#receptionNpQuantity').fill('3');await page.locator('#receptionNpSave').click();
   await page.waitForFunction(()=>document.querySelector('#receptionNpScanResult')?.textContent==='NP guardado.');
   await scan('NP-NOSTOCK');await settled();assert.equal(writes,5);
   const line=await page.evaluate(()=>selected.lines.find(l=>l.np_code==='NP-NOSTOCK'));
   assert.equal(await page.locator('#qty-'+line.id).inputValue(),'3');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   await page.locator('#scanReceptionNp').scrollIntoViewIfNeeded();
   const field=await page.locator('#scanReceptionNp').boundingBox();assert(field.height>=44);
   await page.screenshot({path:path.join(output,`scan-${width}.png`),fullPage:true});
   await context.close();console.log(`Automatic NP, missing/duplicate/order choice, zero, reload and correction OK ${width}x${height}`);
  }
  const context=await browser.newContext({viewport:{width:393,height:873}}),page=await context.newPage();
  page.on('pageerror',error=>errors.push(error.message));page.on('dialog',d=>d.accept());
  await page.goto(base+'/reception');await page.waitForFunction(()=>typeof loadDetail==='function');
  await page.evaluate(()=>loadDetail(12));await page.locator('#scanReceptionNp').waitFor();
  let first=true,writes=0;
  await page.route('**/api/receptions/12/lines/*',async route=>{
   writes++;if(first){first=false;await new Promise(resolve=>setTimeout(resolve,250));await route.fulfill({status:503,contentType:'text/plain',body:'Unavailable'});}else await route.continue();
  });
  await page.locator('#scanReceptionNp').fill('NP-NOSTOCK');await page.locator('#scanReceptionNp').press('Enter');
  await page.locator('#scanReceptionNp').fill('NP-ZERO');await page.locator('#scanReceptionNp').press('Enter');
  await page.getByRole('button',{name:'Reintentar lectura'}).waitFor();
  assert.equal(writes,1);assert.equal(await page.evaluate(()=>WmsNpScan.hasPending()),true);
  await page.evaluate(()=>loadDetail(5));assert.equal(await page.evaluate(()=>selected.id),12);
  assert.equal(await page.evaluate(()=>confirmLeaveActiveReceptionWork('otra BL')),false);
  await page.getByRole('button',{name:'Reintentar lectura'}).click();
  await page.waitForFunction(()=>!WmsNpScan.hasPending());assert.equal(writes,3);
  assert.match(await page.locator('#receptionNpProgress').innerText(),/2\/3/);
  await page.addStyleTag({content:'#receptionNpScanPanel :is(label,input,button,p,span){font-size:24px!important;line-height:1.5!important}'});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
  await page.screenshot({path:path.join(output,'retry-large-text.png'),fullPage:true});
  await page.evaluate(()=>loadDetail(13));await page.locator('#scanReceptionNp').waitFor();
  await page.locator('#scanReceptionNp').fill('NP-NOSTOCK');await page.locator('#scanReceptionNp').press('Enter');
  await page.waitForFunction(()=>!WmsNpScan.hasPending());
  await page.reload();await page.waitForFunction(()=>typeof loadDetail==='function');
  await page.evaluate(()=>loadDetail(13));await page.locator('#scanReceptionNp').waitFor();
  const unscanned=await page.evaluate(()=>selected.lines.find(l=>l.np_code==='NP-001').id);
  assert.equal(await page.locator('#qty-'+unscanned).inputValue(),'5','An unreviewed NP retains its full default after another NP initializes the attention');
  assert.match(await page.locator('#receptionNpProgress').innerText(),/1\/3/);
  for(const [code,order] of [['NP-001',0],['NP-001',1],['NP-ZERO',null]]){
   await page.locator('#scanReceptionNp').fill(code);await page.getByRole('button',{name:'Corregir NP',exact:true}).click();
   if(order!==null)await page.locator('.np-match').nth(order).click();
   await page.locator('#receptionNpQuantity').fill('0');await page.locator('#receptionNpReason').fill('No llego este repuesto');
   await page.locator('#receptionNpSave').click();await page.waitForFunction(()=>document.querySelector('#receptionNpScanResult')?.textContent==='NP guardado.');
  }
  assert.equal(await page.evaluate(()=>WmsNpScan.canComplete()),true);
  assert.match(await page.locator('#receptionNpProgress').innerText(),/NP leidos: 1\/3.*No recibidos: 2/);
  assert.match(await page.locator('#receptionNpUnreceived').innerText(),/No llego este repuesto/);
  await context.close();assert.deepEqual(errors,[]);
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
