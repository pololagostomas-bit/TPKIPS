// support_received_piece_server.py PORT. Only synthetic guides/pieces and loopback.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],out=path.join(__dirname,'../qa/runtime/received-piece-ui');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable loopback fixture required');
const headers={'X-WMS-Request':'1','Content-Type':'application/json'};
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  for(const viewport of [{width:393,height:873},{width:320,height:740},{width:1366,height:768},{width:873,height:393}]){
   const context=await browser.newContext({viewport,reducedMotion:'reduce'}),page=await context.newPage(),errors=[];
   page.on('pageerror',error=>errors.push(error.message));
   page.on('dialog',dialog=>dialog.accept());
   await context.addInitScript(()=>{if('serviceWorker' in navigator)navigator.serviceWorker.register=async()=>undefined;});
   assert.equal((await context.request.post(base+'/api/login',{headers,data:{username:'qa.reader',password:'QA-password-only-123!'}})).status(),200);
   await page.goto(base+'/reception');await page.getByRole('button',{name:'Tránsito',exact:true}).click();
   await page.locator('#createScanTruckButton').click();await page.locator('#scanTruckPackageCode').waitFor();
   const guide=await page.locator('#truckGuideFilter').inputValue();
   const scan=async code=>{
    await page.locator('#scanTruckPackageCode').fill(code);await page.locator('#scanTruckPackageCode').press('Enter');
    await page.waitForFunction(()=>!WmsTruckScan.hasPending()||document.querySelector('[data-discard-reading]'));
   };
   await scan('(00) 123456789012345675');
   await page.waitForFunction(()=>$('scanBlCount')?.textContent==='1/3');
   await page.locator('#scanBlListTitle').click();
   await page.getByRole('button',{name:'Revisar BL 1234567890',exact:true}).click();
   await page.locator('#scanBlListTitle').click();
   await page.waitForFunction(()=>$('scanDhlProgress')?.textContent.includes('Recibidos en WMS: 1'));
   const status=await page.locator('#scanDhlProgress').innerText();
   assert.ok(status.includes('Total DHL: 3')&&status.includes('Pendientes de arribo: 2'));
   assert.ok(!status.includes('123456789012345682')&&!status.includes('JD000001'));
   await page.locator('#scanDhlProgress summary').click();
   assert.equal(await page.locator('#scanDhlProgress li').count(),1);
   assert.equal(await page.locator('#scanDhlProgress li').innerText(),'123456789012345675');
   await scan('00123456789012345675');await scan(']C100123456789012345675');
   assert.equal(await page.locator('#scanBlCount').innerText(),'1/3');
   await page.locator('#scanDhlProgress details').evaluate(element=>{element.open=true;});
   await page.locator('#scanDhlProgress').scrollIntoViewIfNeeded();
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   await page.screenshot({path:path.join(out,'one-of-three-'+viewport.width+'.png'),fullPage:true});
   if(viewport.width===393){
    const style=await page.addStyleTag({content:'#scanDhlProgress p,#scanDhlProgress li,#scanDhlProgress summary{font-size:28px!important;line-height:1.5}'});
    assert.equal(await page.locator('#scanDhlProgress p').evaluate(element=>getComputedStyle(element).fontSize),'28px');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    assert.equal(await page.locator('#scanDhlProgress li').evaluate(element=>element.scrollWidth<=element.clientWidth+1),true);
    await page.locator('#scanDhlProgress').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(out,'one-of-three-text200.png'),fullPage:true});
    await style.evaluate(element=>element.remove());
   }
   await scan('(00) 123456789012345699');
   await page.locator('[data-discard-reading]').waitFor();
   assert.equal(await page.locator('#scanBlCount').innerText(),'1/3');
   await page.locator('[data-discard-reading]').click();
   await scan('*JD000001*');await scan('JJD000001');
   assert.equal(await page.locator('#scanBlCount').innerText(),'2/3');
   await scan('123456789012345682');
   assert.equal(await page.locator('#scanBlCount').innerText(),'3/3','Different SSCC is a different physical piece');
   assert.deepEqual(errors,[]);
   assert.equal((await context.request.post(base+'/api/receptions/truck-guide/cancel',{headers,data:{truck_guide:guide}})).status(),200);
   console.log('OK received-only, SSCC/star aliases, wrong-code rejection '+viewport.width+'px');
   await context.close();
  }
  const context=await browser.newContext({viewport:{width:393,height:873}}),page=await context.newPage();
  page.on('dialog',dialog=>dialog.accept());
  await context.request.post(base+'/api/login',{headers,data:{username:'qa.reader',password:'QA-password-only-123!'}});
  await page.goto(base+'/reception');await page.getByRole('button',{name:'Tránsito',exact:true}).click();
  await page.locator('#createScanTruckButton').click();await page.locator('#scanTruckPackageCode').fill('(00)123456789012345675');
  await page.locator('#scanTruckPackageCode').press('Enter');await page.waitForFunction(()=>!WmsTruckScan.hasPending());
  await page.locator('#finalizeScanTruckButton').click();await page.locator('#scanGeneralLocation').waitFor();
  assert.equal(await page.locator('.scan-location-card').count(),1);
  assert.equal(await page.locator('.scan-location-card').getAttribute('data-received'),'1');
  assert.equal(await page.locator('.truck-bl-location-qty').inputValue(),'1');
  await page.screenshot({path:path.join(out,'partial-arrival-location.png'),fullPage:true});
  const id=await page.evaluate(()=>activeTruckGuideSummary.bls[0].id);
  const detail=await(await context.request.get(base+'/api/receptions/'+id)).json();
  assert.equal(detail.received_packages,1);
  assert.equal(detail.receipts.filter(row=>row.received_packages>0).length,1);
  assert.equal(detail.receipts.filter(row=>row.received_packages>0)[0].received_packages,1);
  console.log('OK partial arrival persists exactly1 receipt, not DHL total3');
  await context.close();
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
