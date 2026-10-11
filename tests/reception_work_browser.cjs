// Disposable data from tests.test_reception_work --serve only.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const base=process.argv[2];
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||'')) throw Error('Pass the isolated fixture URL');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.WMS_QA_BROWSER_CHANNEL||undefined});
 const output=path.join(__dirname,'..','qa','reception-work');fs.mkdirSync(output,{recursive:true});
 const errors=[];
 try{
  for(const width of [1280,393,375,360]){
   const page=await browser.newPage({viewport:{width,height:851}});
   page.on('pageerror',error=>errors.push(error.message));
   await page.goto(base+'/reception');
   await page.locator('#bottomNav [data-nav=work]').click();
   await page.locator('.work-metric').first().waitFor();
   assert.equal(await page.locator('.work-metric').count(),4);
   assert.ok((await page.locator('.work-metric').first().innerText()).includes('106'));
   assert.equal(await page.locator('.work-global-summary').count(),0,'No second, contradictory summary');
   assert.equal(await page.locator('[data-work-row]').count(),100);
   await page.locator('#workNext').click();
   await page.waitForFunction(()=>document.querySelectorAll('[data-work-row]').length===6);
   await page.locator('#workPrevious').click();
   await page.waitForFunction(()=>document.querySelectorAll('[data-work-row]').length===100);
   await page.locator('#workSearch').fill('TEST-DOCUMENTED');
   await page.waitForFunction(()=>document.querySelectorAll('[data-work-row]').length===0);
   await page.locator('[data-work-view=history]').click();
   await page.waitForFunction(()=>document.querySelectorAll('[data-work-row]').length===1);
   const documented=page.locator('[data-work-row]');
   assert.ok((await documented.innerText()).includes('FR/EM completas'));
   assert.ok((await documented.innerText()).includes('No aplica'));
   assert.equal(await documented.locator('[data-work-arrival]').count(),0);
   await page.locator('#workSearch').fill('');
   await page.locator('[data-work-view=pending]').click();
   await page.locator('#workStage').selectOption('UBICACION');
   await page.waitForFunction(()=>document.querySelectorAll('[data-work-row]').length===53);
   assert.ok((await page.locator('[data-work-row]').first().innerText()).includes('Vencido hace'));
   assert.ok((await page.locator('[data-work-row]').first().innerText()).includes('Límite:'));
   if(width<720){
    const owners=await page.locator('[data-work-row]').first().locator('td').nth(1).boundingBox();
    assert.ok(owners.height<85,'Compact mobile ownership row');
   }
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'No page overflow');
   for(const selector of ['.work-heading','.work-metrics','.work-filters']){
    const box=await page.locator(selector).boundingBox();assert.ok(box.x>=-1&&box.x+box.width<=width+1,'Fits '+selector);
   }
   await page.screenshot({path:path.join(output,'work-'+width+'.png'),fullPage:false});
   await page.locator('#workStage').selectOption('PROGRAMADO');
   const arrivalBl='TEST-WORK-'+String(101-[1280,393,375,360].indexOf(width)*2).padStart(3,'0');
   await page.locator('#workSearch').fill(arrivalBl);
   await page.waitForFunction(()=>document.querySelectorAll('[data-work-row]').length===1);
   if(width===1280){
    page.once('dialog',dialog=>dialog.accept());
    await page.locator('[data-work-arrival]').click();
    await page.waitForFunction(()=>document.querySelectorAll('[data-work-row]').length===0);
    await page.locator('#workStage').selectOption('');
    await page.waitForFunction(()=>document.querySelectorAll('[data-work-row]').length===1);
    assert.ok((await page.locator('[data-work-row]').innerText()).includes('Quedan'));
   }
   await page.evaluate(()=>{$('user').value='worker.test';$('role').value='ASISTENTE_RECEPCION';return showMyWork();});
   await page.locator('.work-metric').first().waitFor();
   assert.equal(await page.locator('[data-work-arrival]').count(),0,'Workers cannot mark arrivals');
   const denied=await page.request.get(base+'/api/receptions/work',{headers:{'X-User':'other','X-Role':'PICKER'}});
   assert.equal(denied.status(),403);
   await page.locator('#workSearch').fill('TEST-WORK');
   await page.locator('#bottomNav [data-nav=profile]').click();
   await page.waitForTimeout(400);
   assert.equal(await page.locator('[data-reception-work]').count(),0,'Debounced search cannot replace the profile');
   await page.close();
   console.log('Reception work '+width+'px: history, SLA, filters, pagination, roles OK');
  }
  assert.deepEqual(errors,[],'No browser exceptions');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
