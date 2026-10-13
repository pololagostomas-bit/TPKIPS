// Disposable support_dhl_server fixture only; no operational data or external calls.
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],output=path.join(__dirname,'../qa/maritime-intake');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Loopback fixture required');
const headers={'Content-Type':'application/json','X-WMS-Request':'1'};
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'}),results=[];
 try{
  for(const viewport of [{width:1440,height:900},{width:393,height:873},{width:360,height:780},{width:320,height:640},{width:873,height:393}]){
   const context=await browser.newContext({viewport}),page=await context.newPage(),errors=[];
   page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
   await context.addInitScript(()=>{if('serviceWorker'in navigator)navigator.serviceWorker.register=async()=>undefined;});
   assert.equal((await context.request.post(base+'/api/login',{headers,data:{username:'qa.reader',password:'QA-password-only-123!'}})).status(),200);
   const before=await(await context.request.get(base+'/api/dhl-tracking/status')).json();
   await page.goto(base+'/reception');await page.getByRole('button',{name:'Tránsito',exact:true}).click();
   await page.locator('#createScanTruckButton').click();await page.locator('#scanTruckPackageCode').waitFor();
   const guide=await page.locator('#truckGuideFilter').inputValue(),field=page.locator('#scanTruckPackageCode');
   const pieceMode=page.getByRole('button',{name:'Bulto DHL',exact:true}),blMode=page.getByRole('button',{name:'Por BL',exact:true});
   await field.fill('JD000000000000000001');await field.press('Enter');
   await page.waitForFunction(()=>document.querySelector('#scanTotal')?.textContent==='1');
   await blMode.click();
   assert.equal(await field.isDisabled(),true);
   assert.equal(await page.evaluate(()=>document.activeElement.id),'scanTruckBlCode');
   const bl=page.locator('#scanTruckBlCode');
   await bl.fill('UNKNOWN-SEA');await bl.press('Enter');
   await page.waitForFunction(()=>document.querySelector('#scanFeedback')?.textContent.includes('no encontrada'));
   assert.equal(await bl.inputValue(),'UNKNOWN-SEA');assert.equal(await field.isDisabled(),true);
   await bl.fill('qa sea 0001');await bl.press('Enter');
   await page.waitForFunction(()=>document.querySelector('#scanReceivingBl')?.textContent==='QA-SEA-0001'&&!document.querySelector('#scanTruckPackageCode').disabled);
   assert.equal(await page.locator('#scanReceivingTransport').textContent(),'MARITIMO');
   assert.equal(await page.evaluate(()=>document.activeElement.id),'scanTruckPackageCode');
   assert.equal(await page.locator('#scanDhlStatus').isVisible(),false);
   for(const [code,total]of [['SEA-BOX-1','2'],['SEA-BOX-1','2'],['SEA-BOX-2','3']]){
    await field.fill(code);await field.press('Enter');
    await page.waitForFunction(()=>document.querySelector('#scanPending')?.textContent==='Lecturas guardadas');
    assert.equal(await page.locator('#scanTotal').textContent(),total);
   }
   await page.locator('#scanBlListTitle').click();
   await page.getByRole('button',{name:'Revisar BL 1234567890',exact:true}).click();
   assert.equal(await page.locator('#scanReceivingBl').textContent(),'QA-SEA-0001');
   await field.fill('SEA-BOX-3');await field.press('Enter');
   await page.waitForFunction(()=>document.querySelector('#scanTotal')?.textContent==='4');
   await field.fill('SEA-DRAFT');await page.locator('#scanBlEntryTitle').click();await bl.fill('QA-SEA-0002');await page.locator('#scanBlSubmit').click();
   await page.waitForFunction(()=>document.querySelector('#scanReceivingBl')?.textContent==='QA-SEA-0002');
   assert.equal(await field.inputValue(),'','A new receiving BL does not inherit a package draft');
   await page.locator('#scanBlEntryTitle').click();await bl.fill('QA-SEA-0001');await bl.press('Enter');
   await page.waitForFunction(()=>document.querySelector('#scanReceivingBl')?.textContent==='QA-SEA-0001');
   assert.equal(await field.inputValue(),'SEA-DRAFT');
   await pieceMode.click();assert.equal(await field.inputValue(),'');
   await field.fill('JD000000000000000003');await field.press('Enter');
   await page.waitForFunction(()=>document.querySelector('#scanTotal')?.textContent==='5');
   await blMode.click();assert.equal(await field.inputValue(),'SEA-DRAFT');
   await page.screenshot({path:path.join(output,'arrival-'+viewport.width+'.png'),fullPage:true});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'Overflow');
   for(const button of [pieceMode,blMode,page.locator('#scanBlEntryTitle'),page.locator('#scanPackageSubmit')]){
    const box=await button.boundingBox();assert.ok(box.height>=47.5);
   }
   assert.equal(await page.locator('[data-camera-for="scanTruckBlCode"]').count(),1);
   assert.equal(await page.locator('[data-camera-for="scanTruckPackageCode"]').count(),1);
   const summary=await(await context.request.get(base+'/api/receptions/truck-guide?truck_guide='+encodeURIComponent(guide))).json();
   assert.equal(summary.bls.find(row=>row.bl_awb==='QA-SEA-0001').package_scan_count,3);
   assert.equal(summary.bls.find(row=>row.bl_awb==='QA-SEA-0002').package_scan_count,0);
   assert.equal(summary.bls.find(row=>row.bl_awb==='QA-SEA-0001').arrival_id,null,'BL lookup is not a receipt');
   assert.equal((await(await context.request.get(base+'/api/dhl-tracking/status')).json()).calls_today,before.calls_today);
   await field.fill('');await page.locator('#finalizeScanTruckButton').click();
   await page.locator('#saveTruckLocationsButton').waitFor();await page.locator('#scanGeneralLocation').fill('QA-TEMP');
   assert.equal(await page.locator('.scan-location-card[data-truck-bl-row]').count(),3,'Untouched BL does not block location');
   await page.locator('#saveTruckLocationsButton').click();await page.getByRole('heading',{name:'Camión terminado',exact:true}).waitFor();
   const done=await(await context.request.get(base+'/api/receptions/truck-guide?truck_guide='+encodeURIComponent(guide))).json();
   const sea=done.bls.find(row=>row.bl_awb==='QA-SEA-0001');
   assert.equal(sea.received_this_truck,3);assert.equal(sea.locations[0].package_count,3);
   assert.deepEqual(errors,[]);results.push({viewport,packages:5,maritime_packages:3,calls:before.calls_today});
   assert.equal((await context.request.post(base+'/api/receptions/truck-guide/cancel',{headers,data:{truck_guide:guide,reason:'QA cleanup'}})).status(),200);
   await context.close();
  }
  fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(results,null,2));
  console.log('OK: maritime BL lookup, HID/typing, mixed DHL, drafts per BL/mode, real arrival/location, five viewports');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
