// Only support_dhl_server.py PORT progress, with synthetic users/tracking.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],out=path.join(__dirname,'../qa/runtime/truck-operator-flow');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Loopback QA fixture required');
const headers={'Content-Type':'application/json','X-WMS-Request':'1'};
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try {
  // 683x384 is the CSS viewport of 1366x768 at 200% browser zoom.
  for(const viewport of [{width:393,height:873},{width:320,height:640},{width:1366,height:768},{width:873,height:393},{width:683,height:384}]){
   const context=await browser.newContext({viewport}),page=await context.newPage(),errors=[];
   page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
   await context.addInitScript(()=>{if('serviceWorker'in navigator)navigator.serviceWorker.register=async()=>undefined;});
   assert.equal((await context.request.post(base+'/api/login',{headers,data:{username:'qa.assistant',password:'QA-password-only-123!'}})).status(),200);
   await page.goto(base+'/reception');
   await page.locator('[data-nav="operation"]').waitFor();
   await page.screenshot({path:path.join(out,'entry-'+viewport.width+'.png'),fullPage:true});
   assert.equal(await page.locator('[data-nav="operation"]').innerText(),'Camiones');
   await page.getByRole('button',{name:'Camiones',exact:true}).click();
   await page.locator('#createScanTruckButton').click();await page.locator('#scanTruckPackageCode').waitFor();
   await page.screenshot({path:path.join(out,'draft-'+viewport.width+'.png'),fullPage:true});
   assert.equal(await page.locator('#scanTruckWorkspace h1').innerText(),'Camión en preparación');
   const guide=await page.locator('#truckGuideFilter').inputValue();
   // Different physical packages on each viewport, never reuse an already received piece.
   const number=101+[393,320,1366,873,683].indexOf(viewport.width);
   await page.locator('#scanTruckPackageCode').fill('JD'+String(number).padStart(18,'0'));
   await page.locator('#scanTruckPackageCode').press('Enter');
   await page.waitForFunction(()=>document.getElementById('scanTotal')?.textContent==='1'&&!WmsTruckScan.hasPending());
   assert.equal(await page.locator('#scanBlCount').innerText(),'1');
   assert.equal(await page.locator('#scanShipmentDetails').getAttribute('open'),null);
   assert.equal(await page.locator('#scanBlList [data-scan-context]').count(),1);
   assert.ok(await page.evaluate(()=>document.querySelector('.scan-task').clientHeight>=120));
   await page.screenshot({path:path.join(out,'scanned-'+viewport.width+'.png'),fullPage:true});
   await page.locator('#finalizeScanTruckButton').click();
   await page.locator('#scanGeneralLocation').waitFor();
   assert.match(await page.locator('#scanTruckWorkspace h1').innerText(),/^CAMION-\d{6}-\d+$/);
   await page.locator('#scanGeneralLocation').fill(']d201-01-A-01-01');
   await page.locator('#scanGeneralLocation').press('Enter');
   assert.equal(await page.locator('#scanGeneralLocation').inputValue(),'01-01-A-01-01');
   assert.equal(await page.locator('.truck-bl-location').first().inputValue(),'01-01-A-01-01');
   const camera=await page.evaluate(()=>{
    const target='truck-location:scanGeneralLocation',context=cameraContext(target);
    return acceptCameraCode(target,']d201-02-A-01-01',context.key);
   });
   assert.equal(camera.state,'choice');
   assert.equal(await page.locator('.truck-bl-location').first().inputValue(),'01-02-A-01-01');
   const staleKey=await page.evaluate(()=>cameraContext('truck-location:scanGeneralLocation').key);
   const finalLocation=viewport.width===393?'01-03-A-01-01':'01-02-A-01-01';
   // Some autofill paths change value without dispatching input; save must reconcile inheritance.
   if(viewport.width===393)await page.locator('#scanGeneralLocation').evaluate((input,value)=>input.value=value,finalLocation);
   await page.screenshot({path:path.join(out,'location-'+viewport.width+'.png'),fullPage:true});
   await page.locator('#saveTruckLocationsButton').click();
   await page.getByRole('heading',{name:'Camión terminado',exact:true}).waitFor();
   const summary=await(await context.request.get(base+'/api/receptions/truck-guide?truck_guide='+encodeURIComponent(guide))).json();
   assert.equal(summary.received_packages,1);
   assert.equal(summary.bls[0].locations[0].location_text,finalLocation);
   const late=await page.evaluate(key=>acceptCameraCode('truck-location:scanGeneralLocation','WRONG-LATE',key),staleKey);
   assert.equal(late.state,'error','Late camera result cannot replace a saved location');
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   assert.deepEqual(errors,[]);
   await page.screenshot({path:path.join(out,'saved-'+viewport.width+'.png'),fullPage:true});
   await context.close();
  }
  for(const [username,operator] of [['qa.auxiliary',true],['qa.reader',false]]){
   const context=await browser.newContext({viewport:{width:393,height:873}}),page=await context.newPage();
   assert.equal((await context.request.post(base+'/api/login',{headers,data:{username,password:'QA-password-only-123!'}})).status(),200);
   await page.goto(base+'/reception');await page.locator('[data-nav=operation]').waitFor();
   assert.equal(await page.locator('.operator-home').count(),operator?1:0);
   if(operator)assert.equal(await page.locator('.home-grid').count(),0);
   await context.close();
  }
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
