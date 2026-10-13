// Only the disposable support_dhl_server fixture; no real mailbox or DHL API.
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],output=path.join(__dirname,'../qa/package-intake');
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
   await page.locator('#createScanTruckButton').click();
   await page.locator('#scanTruckPackageCode').waitFor();
   assert.equal(await page.locator('#scanTruckBlCode').isVisible(),false);
   assert.equal(await page.evaluate(()=>document.activeElement.id),'scanTruckPackageCode');
   const guide=await page.locator('#truckGuideFilter').inputValue();
   const field=page.locator('#scanTruckPackageCode');
   for(const [code,total]of [['JJD000000000000000001','1'],['JD000000000000000003','2'],['JD000000000000000001','2'],['(J)JD000000000000000001','2'],['JJD000000000000000003','2']]){
    await field.fill(code);await field.press('Enter');
    await page.waitForFunction(()=>document.querySelector('#scanPending')?.textContent==='Lecturas guardadas');
    assert.equal(await page.locator('#scanTotal').textContent(),total);
    assert.equal(await page.evaluate(()=>document.activeElement.id),'scanTruckPackageCode');
   }
   await field.fill('UNKNOWN-BOX');await field.press('Enter');
   await page.locator('[data-identify-reading]').waitFor();
   assert.equal(await page.locator('#finalizeScanTruckButton').isDisabled(),true);
   await page.locator('[data-identify-reading]').click();
   await page.locator('#scanIdentifyBl').fill('NO-SUCH-BL');await page.locator('#scanIdentifyConfirm').click();
   await page.waitForFunction(()=>document.querySelector('#scanFeedback')?.textContent.includes('no encontrada'));
   await page.locator('#scanIdentifyBl').fill('1234567890');await page.locator('#scanIdentifyConfirm').click();
   await page.waitForFunction(()=>document.querySelector('#scanFeedback')?.textContent.includes('Sin verificar por DHL'));
   assert.equal(await page.locator('#scanTotal').textContent(),'3');
   assert.equal(await page.locator('#scanIdentifyPanel').isVisible(),false);
   await field.fill('JD000000000000000004');await field.press('Enter');
   await page.waitForFunction(()=>document.querySelector('#scanTotal')?.textContent==='4');
   assert.equal(await page.locator('#scanLastBl').textContent(),'1234567891');
   await page.locator('#scanBlListTitle').click();
   await field.fill('JJD000000000000000004');
   await page.getByRole('button',{name:'Revisar BL 1234567890',exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('#scanDhlProgress')?.textContent.includes('JD000000000000000002'));
   assert.equal(await field.inputValue(),'JJD000000000000000004','Selecting BL retains unsubmitted code');
   assert.equal(await page.locator('#scanLastBl').textContent(),'1234567890');
   assert.equal(await page.locator('#scanBlCount').textContent(),'2');
   assert.ok(await page.locator('.scan-details').evaluate(node=>node.open),'Selection preserves list expansion');
   const blButton=await page.getByRole('button',{name:'Revisar BL 1234567890',exact:true}).boundingBox();
   assert.ok(blButton.height>=47.5);
   await field.press('Enter');
   await page.waitForFunction(()=>document.querySelector('#scanPending')?.textContent==='Lecturas guardadas'&&document.querySelector('#scanLastBl')?.textContent==='1234567891');
   assert.equal(await page.locator('#scanTotal').textContent(),'4','Selection never assigns a duplicate to another BL');
   await page.waitForFunction(()=>document.querySelector('#scanDhlProgress')?.textContent.includes('Por escanear: 0'));
   await page.screenshot({path:path.join(output,'mixed-'+viewport.width+'.png'),fullPage:true});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'Overflow');
   const summary=await(await context.request.get(base+'/api/receptions/truck-guide?truck_guide='+encodeURIComponent(guide))).json();
   assert.deepEqual(summary.bls.map(r=>r.package_scan_count).sort(),[2,2]);
   assert.equal((await(await context.request.get(base+'/api/dhl-tracking/status')).json()).calls_today,before.calls_today);
   await page.locator('#finalizeScanTruckButton').click();
   await page.locator('#saveTruckLocationsButton').waitFor();
   await page.locator('#scanGeneralLocation').fill('QA-DRAFT');
   await page.getByRole('button',{name:'Revisar BL 1234567890',exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('#scanDhlProgress')?.textContent.includes('JD000000000000000002'));
   assert.equal(await page.locator('#scanGeneralLocation').inputValue(),'QA-DRAFT','BL review does not rerender location draft');
   assert.equal(await page.locator('#scanBlCount').textContent(),'2');
   await page.screenshot({path:path.join(output,'location-'+viewport.width+'.png'),fullPage:true});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'Location overflow');
   assert.deepEqual(errors,[]);results.push({viewport,recognized_bls:2,packages:4,calls:before.calls_today});
   // Explicit QA-only cleanup; production app/data are not reachable from this fixture.
   assert.equal((await context.request.post(base+'/api/receptions/truck-guide/cancel',{headers,data:{truck_guide:guide,reason:'QA cleanup'}})).status(),200);
   await context.close();
  }
  fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(results,null,2));
  console.log('OK: mixed BL intake, JJD/JD/(J)JD aliases count once, explicit unknown confirmation, arrival, five viewports, no extra DHL calls');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
