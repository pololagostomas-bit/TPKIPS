// Synthetic loopback: support_mobile_server.py PORT --partial-deliveries --sla-kpis.
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],output=path.join(__dirname,'../qa/sla-report-kpis');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Loopback fixture required');
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  for(const viewport of [{width:320,height:640},{width:393,height:873},{width:1366,height:768},{width:873,height:393}]){
   const context=await browser.newContext({viewport,acceptDownloads:true,serviceWorkers:'block'}),page=await context.newPage(),errors=[];
   let reportRequests=0;
   page.on('request',request=>{if(new URL(request.url()).pathname==='/api/receptions/report')reportRequests++});
   page.on('pageerror',error=>errors.push(error.message));
   await context.addInitScript(()=>{navigator.serviceWorker.register=async()=>undefined});
   await page.goto(base+'/reception');await page.waitForSelector('html[data-wms-ui=ready]');await page.evaluate(()=>openReport());
   const count=async label=>Number(await page.locator(`[data-report-kpi="${label}"] strong`).textContent());
   const waitCounts=async(red,yellow)=>page.waitForFunction(([r,y])=>
     document.querySelector('[data-report-kpi="BL rojas"] strong')?.textContent===String(r)&&
     document.querySelector('[data-report-kpi="BL amarillas"] strong')?.textContent===String(y),[red,yellow]);
   await page.waitForFunction(()=>document.querySelector('[data-report-kpi="BL amarillas"] strong')?.textContent==='1');
   assert.equal(await page.locator('[data-report-kpi="BL verdes"]').count(),1,'Green BLs must have a visible KPI');
   assert.equal(await count('BL rojas'),await page.locator('.report-item-row td.sla-bad').count());
   assert.equal(await count('BL amarillas'),await page.locator('.report-item-row td.sla-warn').count());
   assert.equal(await count('BL verdes'),await page.locator('.report-item-row td.sla-ok').count());
   assert.ok(await count('BL rojas')>0);
   assert.equal(await page.locator('.report-general-totals').evaluate(node=>node.open),false);
   assert.equal(await page.locator('[data-report-kpi="BL en la base"]').isVisible(),false);
   assert.equal(await page.locator('[data-report-kpi="Cerradas"]').isVisible(),false);
   await page.screenshot({path:path.join(output,`all-${viewport.width}.png`),fullPage:true});
   const before=reportRequests;
   await page.locator('.report-general-totals summary').focus();
   await page.locator('.report-general-totals summary').press('Enter');
   assert.equal(await page.locator('[data-report-kpi="BL en la base"]').isVisible(),true);
   assert.equal(await page.locator('[data-report-kpi="Cerradas"]').isVisible(),true);
   assert.equal(reportRequests,before,'Opening totals reuses the current report');
   await page.locator('.report-general-totals summary').click();
   const green=page.locator('[data-report-sla="VERDE"]');
   await green.click();await waitCounts(0,0);
   assert.equal(await page.locator('#reportSla').inputValue(),'VERDE');
   assert.equal(await green.getAttribute('aria-pressed'),'true');
   assert.equal(await page.locator('.report-item-row').count(),await count('BL verdes'));
   assert.equal(await page.locator('.report-item-row td.sla-ok').count(),await count('BL verdes'));
   await page.locator('#reportSearch').fill('QA-MOBILE-4');
   await page.waitForFunction(()=>document.querySelector('.report-open')?.textContent==='QA-MOBILE-4');
   assert.equal(await count('BL verdes'),1);
   assert.equal(await page.locator('#reportSla').inputValue(),'VERDE','Color shortcut preserves search and other filters');
   const greenDownload=page.waitForEvent('download');await page.locator('#reportExport').click();
   await (await greenDownload).saveAs(path.join(output,`green-${viewport.width}.xlsx`));
   await page.screenshot({path:path.join(output,`green-${viewport.width}.png`),fullPage:true});
   await page.locator('#reportSearch').fill('QA-MOBILE-0');
   await page.waitForFunction(()=>document.querySelector('#reportFilteredCount')?.textContent==='0 resultado(s)');
   assert.equal(await count('BL verdes'),0,'BL without a physical start is not green');
   await page.locator('#reportSearch').fill('');
   await page.waitForFunction(()=>document.querySelector('[data-report-kpi="BL verdes"] strong')?.textContent==='1');
   await green.click();
   await page.waitForFunction(()=>document.querySelector('#reportSla')?.value==='ALL'&&document.querySelector('[data-report-kpi="BL rojas"] strong')?.textContent!=='0');
   assert.equal(await green.getAttribute('aria-pressed'),'false');
   await page.locator('#reportSearch').fill('QA-MOBILE-3');await waitCounts(0,1);
   await page.locator('#reportSearch').fill('QA-MOBILE-2');await waitCounts(1,0);
   await page.locator('#reportSearch').fill('QA-MOBILE-0');await waitCounts(0,0);
   await page.locator('#reportSearch').fill('');
   await page.waitForFunction(()=>document.querySelector('[data-report-kpi="BL amarillas"] strong')?.textContent==='1');
   await page.locator('.report-more-filters summary').click();await page.locator('#reportSla').selectOption('AMARILLO');await waitCounts(0,1);
   assert.equal(await page.locator('.report-item-row').count(),1);
   const download=page.waitForEvent('download');await page.locator('#reportExport').click();
   await (await download).saveAs(path.join(output,`sla-${viewport.width}.xlsx`));
   await page.screenshot({path:path.join(output,`yellow-${viewport.width}.png`),fullPage:true});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   await page.evaluate(()=>document.querySelectorAll('.report-kpi :is(span,strong,small)').forEach(node=>node.style.fontSize=(parseFloat(getComputedStyle(node).fontSize)*2)+'px'));
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'SLA cards reflow at200% text');
   assert.deepEqual(errors,[]);await context.close();
  }
  console.log('OK: red/yellow/green KPIs and direct filter, collapsed totals, search/no-start, eight XLSX, four sizes/text200%, no JS errors');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
