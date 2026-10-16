// Disposable support_mobile_server.py only; no operational mutations or real mail.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const base=process.argv[2];
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Loopback QA fixture required');
const output=path.join(__dirname,'../qa/report-jobs');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  const errors=[],results=[];
  try{
    for(const viewport of [{width:320,height:640},{width:375,height:812},{width:393,height:873},
      {width:768,height:1024},{width:820,height:900},{width:821,height:900},
      {width:1366,height:768},{width:1440,height:900},{width:873,height:393}]){
      const context=await browser.newContext({viewport,acceptDownloads:true,reducedMotion:'reduce'});
      await context.addInitScript(()=>{navigator.serviceWorker.register=async()=>undefined});
      const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
      await page.goto(base+'/reception');
      await page.waitForSelector('html[data-wms-ui=ready]');
      await page.evaluate(()=>openReport());
      await page.waitForSelector('#reportState');
      assert.equal(await page.locator('.report-item-row').count(),9);
      assert.equal(await page.locator('.report-open').first().evaluate(node=>getComputedStyle(node).whiteSpace),'nowrap');
      assert.equal(await page.locator('.report-open').first().evaluate(node=>node.getBoundingClientRect().height>=44),true);
      assert.equal(await page.locator('.report-grid').evaluate(node=>node.scrollWidth>node.clientWidth),true);
      assert.equal(await page.locator('.report-grid thead tr').evaluate(node=>{
        const cells=[...node.children].map(cell=>cell.getBoundingClientRect());
        return cells.every(cell=>cell.height>=44&&Math.abs(cell.y-cells[0].y)<1);
      }),true,'Headers stay on one horizontal table row on mobile');
      assert.equal(await page.locator('.report-grid .mobile-records').count(),0);
      await page.locator('#reportState').selectOption('CERRADO');
      await page.waitForFunction(()=>document.querySelectorAll('.report-item-row').length===1);
      assert.equal(await page.locator('.report-item-row').getAttribute('data-state'),'CERRADO');
      await page.locator('.report-columns summary').click();
      await page.locator('#reportColumn').selectOption('1');
      await page.locator('#reportColumnWidth').fill('240');await page.locator('#reportColumnWidth').press('Tab');
      await page.locator('#reportColumnVisible').uncheck();
      assert.equal(await page.locator('.report-grid th[data-column="1"]').isVisible(),false);
      await page.locator('#reportColumnReset').click();
      assert.equal(await page.locator('.report-grid th[data-column="1"]').isVisible(),true);
      await page.locator('.report-columns summary').click();
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
      await page.screenshot({path:path.join(output,`closed-${viewport.width}.png`)});
      if([320,393].includes(viewport.width)){
        await page.evaluate(()=>{
          const sizes=[...document.querySelectorAll('#reportContent :is(input,select,label,summary,button,strong,.report-cut)')]
            .map(node=>[node,parseFloat(getComputedStyle(node).fontSize)*2]);
          sizes.forEach(([node,size])=>node.style.fontSize=size+'px');
        });
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,'200% text reflow');
        await page.screenshot({path:path.join(output,`text200-${viewport.width}.png`)});
      }
      results.push({viewport,closed_filter:true,columns:true});
      await context.close();
    }
    // One click is one request, even if the handler is called twice or filters redraw the button.
    const contexts=await Promise.all([browser.newContext({acceptDownloads:true,serviceWorkers:'block'}),browser.newContext({acceptDownloads:true,serviceWorkers:'block'})]);
    const pages=await Promise.all(contexts.map(c=>c.newPage()));
    const ids=[];let requests=0;
    for(const page of pages){
      page.on('pageerror',error=>errors.push(error.message));
      page.on('response',async response=>{
        if(response.url().endsWith('/api/receptions/history/export')){
          if(response.status()===202)ids.push((await response.json()).id);
          else if(response.status()===200)ids.push(response.headers()['x-wms-report-job']);
        }
      });
      await page.route('**/api/receptions/history/export',async route=>{requests++;await sleep(600);await route.continue()});
      await page.goto(base+'/reception');await page.waitForSelector('html[data-wms-ui=ready]');
      await page.evaluate(()=>openReport());await page.waitForSelector('#historyExport');
    }
    const downloads=pages.map(page=>page.waitForEvent('download'));
    await Promise.all(pages.map(page=>page.evaluate(()=>{downloadHistoryExcel();downloadHistoryExcel()})));
    assert.equal(await pages[0].locator('#historyExport').isDisabled(),true);
    await pages[0].locator('#reportState').selectOption('CERRADO');
    await pages[0].waitForFunction(()=>document.querySelectorAll('.report-item-row').length===1);
    assert.equal(await pages[0].locator('#historyExport').isDisabled(),true,'Redraw retains download lock');
    const files=await Promise.all(downloads);
    assert.equal(requests,2,'Only one initial request per person');
    assert.equal(ids.length,2);
    assert.ok(ids[0]);assert.equal(new Set(ids).size,1,'Both users reuse one queued export');
    for(let i=0;i<files.length;i++){
      assert.equal(files[i].suggestedFilename(),'triton_recepcion_historial.xlsx');
      await files[i].saveAs(path.join(output,`qa-history-${i}.xlsx`));
      await pages[i].waitForFunction(()=>!document.querySelector('#historyExport').disabled);
    }
    // Failed reads remove stale actions, and a late result cannot reopen the modal.
    await pages[0].route('**/api/receptions/report?**',route=>route.fulfill({status:503,json:{error:'QA report unavailable'}}));
    await pages[0].locator('#reportState').selectOption('ALL');
    await pages[0].waitForSelector('#reportLoadError');
    assert.equal(await pages[0].locator('.report-item-row,#historyExport').count(),0);
    await pages[0].unroute('**/api/receptions/report?**');
    await pages[0].locator('#reportRetry').click();await pages[0].waitForSelector('#reportState');
    await pages[0].route('**/api/receptions/report?**',async route=>{await sleep(1000);await route.continue().catch(()=>{})});
    await pages[0].evaluate(()=>{openReport()});await pages[0].keyboard.press('Escape');await sleep(1300);
    assert.equal(await pages[0].locator('#reportModal').evaluate(node=>node.hidden),true);
    await Promise.all(contexts.map(c=>c.close()));
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(results,null,2));
    console.log('OK: 9 viewports, closed filter, column controls, text200%, two people/one export, duplicate-click guard, stale/error/cancel.');
  }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
