// Real loopback WMS routes + synthetic databases; only the camera device is mocked.
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const [trucks,items]=process.argv.slice(2);
if(![trucks,items].every(url=>/^http:\/\/127\.0\.0\.1:\d+$/.test(url||'')))throw Error('Two disposable loopback fixtures required');
const output=path.join(__dirname,'../qa/camera-integration');fs.mkdirSync(output,{recursive:true});
const headers={'Content-Type':'application/json','X-WMS-Request':'1'};
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  for(const viewport of [{width:393,height:873},{width:1366,height:768}]){
   const context=await browser.newContext({viewport}),page=await context.newPage(),errors=[];
   page.on('pageerror',error=>errors.push(error.message));
   await context.addInitScript(()=>{
    if('serviceWorker'in navigator)navigator.serviceWorker.register=async()=>undefined;
    window.Html5Qrcode=class{
     async start(_device,_options,onRead){this.isScanning=true;window.qaRead=onRead;}
     async stop(){this.isScanning=false;}
     clear(){}
    };
   });
   assert.equal((await context.request.post(trucks+'/api/login',{headers,data:{username:'qa.reader',password:'QA-password-only-123!'}})).status(),200);
   await page.goto(trucks+'/reception');await page.getByRole('button',{name:'Tránsito',exact:true}).click();
   await page.locator('#createScanTruckButton').click();await page.locator('#scanTruckPackageCode').waitFor();
   assert.equal(await page.locator('#scanTruckPackageCode').getAttribute('inputmode'),'none');
   const guide=await page.locator('#truckGuideFilter').inputValue();
   await page.locator('[data-camera-for="scanTruckPackageCode"]').click();
   await page.waitForFunction(()=>document.querySelector('#wmsCameraStatus')?.textContent==='Listo para leer');
   await page.evaluate(()=>qaRead('JJD00000002'));
   await page.waitForFunction(()=>document.querySelector('#scanTotal')?.textContent==='1');
   assert.equal(await page.locator('#wmsBarcodeCamera').isVisible(),true);
   await page.evaluate(()=>qaRead('JD00000003'));
   await page.waitForFunction(()=>document.querySelector('#scanTotal')?.textContent==='2');
   await page.evaluate(()=>qaRead('JD00000002'));
   assert.equal(await page.locator('#scanTotal').textContent(),'2');
   await page.keyboard.press('Escape');
   assert.equal(await page.locator('#scanTruckPackageCode').getAttribute('inputmode'),'none');
   assert.equal((await context.request.post(trucks+'/api/receptions/truck-guide/cancel',{headers,data:{truck_guide:guide}})).status(),200);

   await page.goto(items+'/reception');await page.evaluate(id=>loadDetail(id),viewport.width===393?1:4);
   await page.locator('#scanReceptionNp').waitFor();
   await page.locator('[data-camera-for="scanReceptionNp"]').click();
   await page.waitForFunction(()=>document.querySelector('#wmsCameraStatus')?.textContent==='Listo para leer');
   await page.evaluate(()=>qaRead('NP-001'));
   assert.equal(await page.locator('#wmsBarcodeCamera').isVisible(),false,'Ambiguous OV leaves camera for explicit choice');
   await page.locator('#receptionNpScanResult .np-match').first().click();
   await page.waitForFunction(()=>WmsNpScan.status().phase==='ready');
   assert.equal(await page.locator('#receptionNpQuantity').count(),0);
   await page.locator('[data-camera-for="scanReceptionNp"]').click();
   await page.waitForFunction(()=>document.querySelector('#wmsCameraStatus')?.textContent==='Listo para leer');
   await page.evaluate(()=>qaRead('NP-NOSTOCK'));
   await page.waitForFunction(()=>WmsNpScan.status().lastResult?.code==='NP-NOSTOCK');
   assert.equal(await page.locator('#scanReceptionNp').getAttribute('inputmode'),'none');
   assert.equal(await page.locator('#wmsBarcodeCamera').isVisible(),true,'Saved NP allows next camera scan');
   assert.equal(await page.evaluate(()=>WmsNpScan.status().lastResult.quantity),5);
   await page.evaluate(()=>qaRead('UNKNOWN-NP'));
   await page.locator('#wmsCameraError').waitFor();
   assert.equal(await page.evaluate(()=>WmsNpScan.status().phase),'error');
   await page.screenshot({path:path.join(output,'np-error-'+viewport.width+'.png')});
   await page.locator('#wmsCameraManual').click();
   assert.equal(await page.evaluate(()=>document.activeElement.id),'scanReceptionNp');
   await page.getByRole('button',{name:'Descartar lectura',exact:true}).click();
   await page.locator('#scanReceptionNp').fill('UNSENT-DRAFT');
   await page.locator('[data-camera-for="scanReceptionNp"]').click();
   await page.waitForFunction(()=>document.querySelector('#wmsCameraStatus')?.textContent==='Listo para leer');
   await page.evaluate(()=>qaRead('NP-001'));
   assert.match(await page.locator('#wmsCameraError').innerText(),/escrito sin registrar/);
   await page.keyboard.press('Escape');
   assert.equal(await page.locator('#scanReceptionNp').inputValue(),'UNSENT-DRAFT');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   assert.deepEqual(errors,[]);
   await context.close();
   console.log('Camera bridge + real fixture saves, duplicates, OV choice, quantity, error and draft OK '+viewport.width);
  }
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
