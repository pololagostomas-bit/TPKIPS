// Synthetic loopback fixture only. No production reports or carrier requests.
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const path=require('node:path'),fs=require('node:fs');
const base=process.argv[2],output=path.join(__dirname,'../qa/report-export');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Loopback fixture required');
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  for(const viewport of [{width:320,height:640},{width:393,height:873},{width:1366,height:768},{width:873,height:393}]){
   const context=await browser.newContext({viewport,acceptDownloads:true,serviceWorkers:'block'}),page=await context.newPage(),errors=[];
   page.on('pageerror',error=>errors.push(error.message));
   await context.addInitScript(()=>{navigator.serviceWorker.register=async()=>undefined});
   await page.goto(base+'/reception');await page.waitForSelector('html[data-wms-ui=ready]');
   await page.evaluate(()=>openReport());await page.locator('#reportSearch').waitFor();
   await page.locator('#reportExport').waitFor();
   await page.locator('#reportSearch').fill('QA-MOBILE-7');
   await page.waitForFunction(()=>document.querySelectorAll('.report-item-row').length===1&&document.querySelector('.report-open')?.textContent==='QA-MOBILE-7');
   let requests=0,query='';
   await page.route('**/api/receptions/report/export?**',async route=>{
    requests++;query=new URL(route.request().url()).searchParams.get('search');
    await new Promise(resolve=>setTimeout(resolve,600));await route.continue();
   });
   const downloading=page.waitForEvent('download');
   await page.evaluate(()=>{WmsReceptionReport.download('indicators');WmsReceptionReport.download('indicators')});
   assert.equal(await page.locator('#reportExport').isDisabled(),true);
   await page.locator('#reportSearch').fill('QA-MOBILE-2');
   await page.waitForFunction(()=>document.querySelector('.report-open')?.textContent==='QA-MOBILE-2');
   const file=await downloading;
   assert.equal(requests,1);assert.equal(query,'QA-MOBILE-7');
   assert.equal(file.suggestedFilename(),'triton_recepcion_indicadores.xlsx');
   await file.saveAs(path.join(output,'indicators-'+viewport.width+'.xlsx'));
   await page.waitForFunction(()=>!document.querySelector('#reportExport').disabled);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   await page.screenshot({path:path.join(output,'filtered-'+viewport.width+'.png'),fullPage:true});
   await page.unroute('**/api/receptions/report/export?**');
   await page.route('**/api/receptions/report/export?**',route=>route.fulfill({status:503,json:{error:'QA export unavailable'}}));
   await page.locator('#reportExport').click();
   await page.waitForFunction(()=>document.querySelector('#reportExportStatus')?.textContent.includes('QA export unavailable'));
   assert.equal(await page.locator('#reportExport').isDisabled(),false);
   assert.deepEqual(errors,[]);
   await context.close();
  }
  console.log('OK: BL live search, filtered XLSX, double click, stable scope on redraw, failure/retry, four viewports');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
