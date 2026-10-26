// Synthetic loopback fixture only: support_mobile_server.py PORT.
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],output=path.join(__dirname,'../qa/truck-cancel');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Loopback fixture required');
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  for(const viewport of [{width:320,height:640},{width:393,height:873},{width:1366,height:768},{width:873,height:393}]){
   const context=await browser.newContext({viewport,serviceWorkers:'block'}),page=await context.newPage(),errors=[],posts=[];
   await context.addInitScript(()=>{navigator.serviceWorker.register=async()=>undefined});
   page.on('pageerror',error=>errors.push(error.message));
   let accept=false,deny=false;
   page.on('dialog',dialog=>accept?dialog.accept():dialog.dismiss());
   page.on('request',request=>{if(request.method()==='POST'&&request.url().endsWith('/cancel'))posts.push(request.url())});
   await page.route('**/api/receptions/truck-guide/scan-piece',route=>route.fulfill({
    status:400,contentType:'application/json',body:JSON.stringify({error:'Paquete de prueba no reconocido'})}));
   await page.route('**/api/receptions/truck-guide/cancel',route=>deny?route.fulfill({
    status:403,contentType:'application/json',body:JSON.stringify({error:'Cancelación de prueba denegada'})}):route.continue());
   await page.goto(base+'/reception');await page.waitForSelector('html[data-wms-ui=ready]');
   await page.getByRole('button',{name:'Tránsito',exact:true}).click();
   await page.locator('#createScanTruckButton').click();
   await page.locator('[data-truck-action="cancel"]').waitFor();
   const guide=await page.locator('#truckGuideFilter').inputValue();
   await page.locator('#scanTruckPackageCode').fill('QA-REJECTED-PIECE');
   await page.locator('#scanTruckPackageCode').press('Enter');
   await page.waitForFunction(()=>!WmsTruckScan.hasInFlight()&&WmsTruckScan.hasPending());
   assert.equal(await page.locator('#scanTotal').innerText(),'0');
   await page.locator('[data-truck-action="cancel"]').click();
   assert.equal(posts.length,0,'Dismissed confirmation does not mutate');
   assert.equal(await page.locator('#truckGuideFilter').inputValue(),guide);
   accept=true;deny=true;
   await page.locator('[data-truck-action="cancel"]').click();
   await page.waitForFunction(()=>$('scanFeedback').textContent.includes('denegada'));
   assert.equal(await page.evaluate(()=>WmsTruckScan.hasPending()),true);
   assert.equal(await page.locator('#scanTruckPackageCode').inputValue(),'QA-REJECTED-PIECE');
   await page.screenshot({path:path.join(output,`rejected-${viewport.width}.png`),fullPage:true});
   deny=false;
   await page.locator('[data-truck-action="cancel"]').click();
   await page.waitForFunction(()=>$('truckGuideFilter').value==='ALL'&&!WmsTruckControls.hasPending());
   assert.equal(posts.length,2);
   assert.equal(await page.evaluate(()=>WmsTruckScan.hasPending()),false);
   const state=await page.evaluate(async guide=>(await (await api('/api/receptions/truck-guide?truck_guide='+encodeURIComponent(guide))).json()),guide);
   assert.equal(state.guide_status,'CANCELADA');assert.equal(state.bl_count,0);
   const active=await page.evaluate(async()=>(await (await api('/api/truck-guides')).json()));
   assert.ok(!(active.items||active.guides||active).some(item=>item.truck_guide===guide),'Cancelled empty truck leaves active transit');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   assert.deepEqual(errors,[]);await context.close();
   console.log(`OK ${viewport.width}px: rejected reading, dismissed/denied/accepted cancel, no active empty truck`);
  }
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
