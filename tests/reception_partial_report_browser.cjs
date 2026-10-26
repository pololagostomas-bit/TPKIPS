// Synthetic loopback fixture: support_mobile_server.py PORT --partial-deliveries.
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],output=path.join(__dirname,'../qa/partial-report');
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
   await page.evaluate(()=>openReport());
   const kpi=page.locator('[data-report-kpi="BL parciales"]');
   await page.waitForFunction(()=>document.querySelector('[data-report-kpi="BL parciales"] strong')?.textContent==='2');
   assert.match(await kpi.innerText(),/Según filtros/);
   await page.screenshot({path:path.join(output,`all-${viewport.width}.png`),fullPage:true});
   await page.locator('#reportState').selectOption('CERRADO');
   await page.waitForFunction(()=>document.querySelector('[data-report-kpi="BL parciales"] strong')?.textContent==='1');
   await page.locator('.report-more-filters summary').click();
   await page.locator('#reportTransport').selectOption('MARITIMO');
   await page.waitForFunction(()=>document.querySelector('[data-report-kpi="BL parciales"] strong')?.textContent==='0');
   await page.locator('.report-more-filters summary').click();
   await page.locator('#reportTransport').selectOption('ALL');
   await page.waitForFunction(()=>document.querySelector('[data-report-kpi="BL parciales"] strong')?.textContent==='1');
   await page.locator('#reportSearch').fill('QA-MOBILE-0');
   await page.waitForFunction(()=>document.querySelector('[data-report-kpi="BL parciales"] strong')?.textContent==='0');
   await page.locator('#reportSearch').fill('QA-MOBILE-7');
   await page.waitForFunction(()=>document.querySelector('[data-report-kpi="BL parciales"] strong')?.textContent==='1');
   const download=page.waitForEvent('download');await page.locator('#reportExport').click();
   await (await download).saveAs(path.join(output,`partials-${viewport.width}.xlsx`));
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   await page.screenshot({path:path.join(output,`partial-${viewport.width}.png`),fullPage:true});
   await page.evaluate(()=>document.querySelectorAll('[data-report-kpi="BL parciales"] :is(span,strong,small)').forEach(node=>node.style.fontSize=(parseFloat(getComputedStyle(node).fontSize)*2)+'px'));
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'KPI reflows at200% text');
   assert.deepEqual(errors,[]);await context.close();
  }
  console.log('OK: partial BL KPI, state/transport/search/empty filters, real XLSX, four sizes/text200%, no JS errors');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
