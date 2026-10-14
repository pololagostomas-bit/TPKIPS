// support_dhl_server.py PORT progress only. All rows and tracking data are fictitious.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],out=path.join(__dirname,'../qa/runtime/truck-progress');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Loopback QA fixture required');
const headers={'X-WMS-Request':'1','Content-Type':'application/json'};
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  for(const viewport of [{width:1440,height:900},{width:393,height:873},{width:375,height:812},{width:320,height:640},{width:873,height:393}]){
   const context=await browser.newContext({viewport,reducedMotion:'reduce'}),page=await context.newPage(),errors=[];
   page.on('pageerror',error=>errors.push(error.message));
   page.on('dialog',dialog=>dialog.accept(dialog.type()==='prompt'?'Corrección de recepción QA':undefined));
   await context.addInitScript(()=>{if('serviceWorker' in navigator)navigator.serviceWorker.register=async()=>undefined;});
   assert.equal((await context.request.post(base+'/api/login',{headers,data:{username:'qa.reader',password:'QA-password-only-123!'}})).status(),200);
   const before=await(await context.request.get(base+'/api/dhl-tracking/status')).json();
   await page.goto(base+'/reception');await page.getByRole('button',{name:'Tránsito',exact:true}).click();
   await page.locator('#createScanTruckButton').click();await page.locator('#scanTruckPackageCode').waitFor();
   const guide=await page.locator('#truckGuideFilter').inputValue();
   assert.equal(await page.locator('[data-truck-action="discard"]').count(),0);
   assert.equal(await page.locator('[data-truck-action="back"]').count(),0,'No destructive generic back during scanning');
   const scan=async code=>{
    await page.locator('#scanTruckPackageCode').fill(code);await page.locator('#scanTruckPackageCode').press('Enter');
    await page.waitForFunction(()=>!WmsTruckScan.hasPending());
   };
   for(let n=101;n<=108;n++)await scan('JD'+String(n).padStart(18,'0'));
   await page.waitForFunction(()=>$('scanBlCount')?.textContent==='8/10');
   assert.equal(await page.locator('#scanBlBrands').innerText(),'BOBCAT');
   assert.equal(await page.locator('#scanBlProgressLabel').innerText(),'Faltan 2 · DHL');
   assert.equal(await page.locator('#scanTotalExpected').innerText(),'/10');
   await scan('JD'+String(108).padStart(18,'0'));
   assert.equal(await page.locator('#scanBlCount').innerText(),'8/10','Duplicate cannot advance progress');
   await page.screenshot({path:path.join(out,'eight-of-ten-'+viewport.width+'.png'),fullPage:true});
   await scan('JD'+String(109).padStart(18,'0'));await scan('JD'+String(110).padStart(18,'0'));
   await page.waitForFunction(()=>$('scanBlCount')?.textContent==='10/10');
   await scan('JD000000000000000003');
   assert.equal(await page.locator('#scanBlBrands').innerText(),'CROWN / LIEBHERR');
   await page.getByRole('button',{name:'Por BL',exact:true}).click();
   for(const bl of ['QA-SEA-0001','QA-SEA-0002']){
    if(!await page.locator('#scanTruckBlCode').isVisible())await page.locator('#scanBlEntryTitle').click();
    await page.locator('#scanTruckBlCode').fill(bl);await page.locator('#scanTruckBlCode').press('Enter');
    await page.waitForFunction(bl=>$('scanReceivingBl')?.textContent===bl&&!WmsTruckScan.hasPending(),bl);
    await scan('BOX-'+bl+'-'+viewport.width);
   }
   await page.locator('#scanBlListTitle').click();
   assert.equal(await page.locator('#scanBlList [data-scan-context]').count(),4);
   assert.equal(await page.locator('#scanBlList').getByText('BOBCAT',{exact:true}).count(),1);
   assert.equal(await page.locator('#scanBlList').getByText('CROWN / LIEBHERR',{exact:true}).count(),1);
   await page.getByRole('button',{name:'Revisar BL 1234567890',exact:true}).click();
   assert.equal(await page.locator('#scanBlCount').innerText(),'10/10');
   const bounds=await page.locator('#scanTruckWorkspace').boundingBox(),finish=await page.locator('#finalizeScanTruckButton').boundingBox();
   assert.ok(bounds.y>=0&&bounds.y+bounds.height<=viewport.height+1,'Workspace within viewport');
   assert.ok(finish.y+finish.height<=viewport.height+1,'Stage action visible');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   await page.screenshot({path:path.join(out,'four-bls-'+viewport.width+'.png'),fullPage:true});
   await page.locator('#finalizeScanTruckButton').click();await page.locator('#scanGeneralLocation').waitFor();
   assert.equal(await page.getByRole('button',{name:'Reabrir llegada',exact:true}).count(),1);
   assert.equal(await page.locator('.scan-card-progress').count(),4);
   await page.locator('#scanGeneralLocation').fill('QA-TEMP');await page.locator('#saveTruckLocationsButton').click();
   await page.getByRole('heading',{name:'Camión terminado',exact:true}).waitFor();
   await page.getByRole('button',{name:'Reabrir ubicación',exact:true}).click();
   await page.locator('#scanGeneralLocation').waitFor();
   assert.equal(await page.locator('#scanTotal').innerText(),'13','Reopening location keeps scans');
   await page.locator('#saveTruckLocationsButton').click();
   await page.getByRole('heading',{name:'Camión terminado',exact:true}).waitFor();
   const sid=await page.evaluate(()=>activeTruckGuideSummary.bls.find(row=>row.bl_awb==='1234567891').id);
   await page.evaluate(id=>loadDetail(id),sid);
   await page.locator('.scan-bl-brands').waitFor();
   assert.equal(await page.locator('.scan-bl-brands').innerText(),'CROWN / LIEBHERR');
   assert.equal(await page.locator('.scan-bl-brands').isVisible(),true,'Brands are not hidden with optional guidance');
   assert.equal((await(await context.request.get(base+'/api/dhl-tracking/status')).json()).calls_today,before.calls_today);
   assert.deepEqual(errors,[]);
   assert.equal((await context.request.post(base+'/api/receptions/truck-guide/cancel',{headers,data:{truck_guide:guide}})).status(),200);
   console.log('OK progress/brands/admin corrections '+viewport.width+'px');await context.close();
  }
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
