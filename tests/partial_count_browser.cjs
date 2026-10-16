const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],output=path.join(__dirname,'../qa/partial-count');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable loopback fixture required');
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 try{
  for(const [index,viewport] of [{width:320,height:640},{width:393,height:873},{width:1366,height:768},{width:873,height:393}].entries()){
   const context=await browser.newContext({viewport,serviceWorkers:'block'}),page=await context.newPage();
   let accept=false,writes=0;
   page.on('pageerror',error=>errors.push(error.message));page.on('dialog',dialog=>accept?dialog.accept():dialog.dismiss());
   page.on('request',request=>{if(request.method()==='POST'&&request.url().endsWith('/count/partial'))writes++;});
   const id=index+1;
   await page.goto(base+'/reception');await page.waitForFunction(()=>typeof loadDetail==='function');
   await page.evaluate(id=>loadDetail(id),id);await page.locator('#scanReceptionNp').waitFor();
   assert.equal(await page.locator('#receptionNpPartial').isVisible(),false,'No shortcut for zero scanned');
   for(let number=0;number<9;number++){
    await page.locator('#scanReceptionNp').fill('NP-'+String(number).padStart(2,'0'));
    await page.locator('#scanReceptionNp').press('Enter');await page.waitForFunction(()=>!WmsNpScan.hasPending());
   }
   assert.match(await page.locator('#receptionNpProgress').innerText(),/9\/10/);
   await page.locator('#receptionNpPartial').click();assert.equal(writes,0,'Cancel leaves count unchanged');
   assert.equal(await page.evaluate(()=>selected.app_status),'REVISION SISTEMA');
   if(viewport.width===320){
    await page.addStyleTag({content:'#receptionNpScanPanel :is(button,p,span){font-size:24px!important;line-height:1.5!important}'});
   }
   await page.locator('#receptionNpPartial').scrollIntoViewIfNeeded();
   const button=await page.locator('#receptionNpPartial').boundingBox();assert(button.height>=44);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
   await page.screenshot({path:path.join(output,`before-${viewport.width}.png`),fullPage:false});
   accept=true;await page.locator('#receptionNpPartial').click();
   await page.waitForFunction(()=>selected?.app_status==='EM');assert.equal(writes,1);
   const deferred=await page.evaluate(()=>selected.lines.find(line=>line.np_code==='NP-09'));
   assert.equal(deferred.attention_verified_qty,0);assert.equal(deferred.expected_qty,1);
   assert(!deferred.np_scanned_at);assert.match(deferred.np_unreceived_reason,/pendiente para otra llegada/);
   assert.equal(await page.evaluate(()=>selected.lines.filter(line=>line.np_scanned_at).length),9);
   await page.reload();await page.waitForFunction(()=>typeof loadDetail==='function');await page.evaluate(id=>loadDetail(id),id);
   await page.waitForFunction(()=>selected?.app_status==='EM');
   assert.equal(await page.evaluate(()=>selected.lines.find(line=>line.np_code==='NP-09').attention_verified_qty),0);
   await page.screenshot({path:path.join(output,`after-${viewport.width}.png`),fullPage:false});
   await context.close();
  }
  const page=await browser.newPage({viewport:{width:393,height:873}});
  page.on('pageerror',error=>errors.push(error.message));page.on('dialog',dialog=>dialog.accept());
  await page.goto(base+'/reception');await page.waitForFunction(()=>typeof loadDetail==='function');await page.evaluate(()=>loadDetail(5));
  await page.locator('#scanReceptionNp').fill('NP-00');await page.locator('#scanReceptionNp').press('Enter');
  await page.waitForFunction(()=>!WmsNpScan.hasPending());
  await page.route('**/count/partial',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'QA partial unavailable'})}),{times:1});
  await page.locator('#receptionNpPartial').click();
  await page.waitForFunction(()=>!WmsNpScan.hasPending());
  assert.equal(await page.evaluate(()=>selected.app_status),'REVISION SISTEMA');
  assert.equal(await page.locator('#receptionNpPartial').isEnabled(),true);
  await page.locator('#receptionNpPartial').click();await page.waitForFunction(()=>selected.app_status==='EM');
  assert.equal(await page.evaluate(()=>selected.lines.filter(line=>line.attention_verified_qty===0).length),9);
  await page.evaluate(()=>showMyWork());await page.locator('[data-work-view=truck]').click();
  await page.waitForFunction(()=>document.querySelectorAll('[data-work-row]').length===1);
  const waiting=await page.locator('[data-work-row]').innerText();
  assert.match(waiting,/QA-PARTIAL-6/);assert.match(waiting,/1 SKU pendientes para otra llegada/);
  assert.match(waiting,/Aún no inicia/);assert.match(waiting,/Sin fecha prevista/);
  assert.match(waiting,/Ver última atención/);assert.doesNotMatch(waiting,/Vencido hace|Inicio por revisar/);
  await page.screenshot({path:path.join(output,'next-arrival-393.png'),fullPage:true});
  await page.close();assert.deepEqual(errors,[]);
  console.log('OK: 9/10 continue, explicit cancel, zero deferred, no fake reads, reload, error/retry, 4 viewports and large text.');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
