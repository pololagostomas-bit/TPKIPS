// Disposable fixture only. These checks do not submit business mutations.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const base=process.argv[2];
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Loopback QA fixture required');
const output=path.join(__dirname,'../qa/reader-performance');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  const errors=[],measurements=[];
  try{
    for(const viewport of [{width:1440,height:900},{width:375,height:812},{width:873,height:393}]){
      const context=await browser.newContext({viewport,reducedMotion:'reduce'});
      await context.addInitScript(()=>{navigator.serviceWorker.register=async()=>undefined});
      const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
      const requests=[];page.on('request',request=>requests.push(request.url()));
      await page.route('https://unpkg.com/**',route=>route.abort());
      await page.goto(base+'/reception');
      await page.waitForSelector('html[data-wms-ui=ready]');
      await page.waitForSelector('.home-stats,.dashboard-stats,.home-tile');
      await page.waitForTimeout(150);
      assert.equal(requests.filter(url=>url.includes('/api/account')).length,1,'One account load');
      assert.equal(requests.filter(url=>url.includes('/api/me')).length,1,'One identity load');
      assert.equal(requests.filter(url=>url.includes('unpkg.com')).length,0,'Camera library is not on startup path');
      let delay=0;
      const rows=Array.from({length:105},(_,index)=>({id:index+1000,bl_awb:'QA-REPORT-'+index,
        app_status:'PROGRAMADO',transport_type:'AEREO',supplier:'QA',sla_status:'AMARILLO',
        elapsed_hours:null,remaining_hours:null,total_units:3,sku_count:2,scheduled_date:'2026-10-11'}));
      await page.route(base+'/api/receptions/report?**',async route=>{
        const params=new URL(route.request().url()).searchParams;
        const offset=Number(params.get('offset')),limit=Number(params.get('limit'));
        assert.equal(limit,50);if(delay)await sleep(delay);
        await route.fulfill({json:{items:rows.slice(offset,offset+limit),offset,limit,total:105,
          has_more:offset+limit<105,generated_at:'2026-10-11 10:00:00',
          summary:{total_bl:105,total_pendientes:105},by_status:{PROGRAMADO:105},by_transport:{AEREO:105}}}).catch(()=>{});
      });
      const started=Date.now();await page.evaluate(()=>openReport());
      await page.waitForSelector('#reportNext');
      assert.equal(await page.locator('.report-item-row').count(),50);
      await page.locator('#reportNext').click();await page.waitForFunction(()=>document.querySelector('.report-item-row').textContent.includes('QA-REPORT-50'));
      assert.equal(await page.locator('.report-item-row').count(),50);
      await page.locator('#reportNext').click();await page.waitForFunction(()=>document.querySelector('.report-item-row').textContent.includes('QA-REPORT-100'));
      assert.equal(await page.locator('.report-item-row').count(),5);
      assert.equal(await page.locator('#reportNext').isDisabled(),true);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
      assert.equal(await page.locator('#reportPrevious').evaluate(button=>button.getBoundingClientRect().height>=44),true);
      await page.screenshot({path:path.join(output,`report-${viewport.width}x${viewport.height}.png`)});
      await page.keyboard.press('Escape');
      delay=1600;
      await page.evaluate(()=>{openReport()});await page.waitForTimeout(1100);
      assert.equal(await page.locator('.workspace-loading').evaluate(node=>getComputedStyle(node).pointerEvents),'none','Read waits do not block closing or navigation');
      await page.keyboard.press('Escape');await page.waitForTimeout(650);
      assert.equal(await page.locator('#reportModal').evaluate(node=>node.hidden),true,'Late report cannot reopen modal');
      delay=0;
      await page.route(base+'/api/receptions/work?**',async route=>{await sleep(1500);await route.continue().catch(()=>{})});
      await page.evaluate(()=>{showMyWork()});await page.waitForTimeout(1100);
      await page.locator('[data-nav=profile]').click();await page.waitForSelector('.profile-fields');
      await page.waitForTimeout(550);
      assert.equal(await page.locator('[data-reception-work]').count(),0,'Late work does not replace profile');
      const old=requests.filter(url=>url.includes('/api/assignees')).length;
      await page.evaluate(()=>openNewModal());
      assert.equal(requests.filter(url=>url.includes('/api/assignees')).length-old,2,'Two roles load once each');
      await page.keyboard.press('Escape');
      // Request objects must retain mutation protection as well as normal fetch options.
      let release;
      await page.route(base+'/api/qa-performance-only',async route=>{await new Promise(resolve=>release=resolve);await route.fulfill({json:{ok:true}})});
      await page.evaluate(base=>{window.qaPending=fetch(new Request(base+'/api/qa-performance-only',{method:'POST'}))},base);
      await page.waitForTimeout(1100);
      assert.equal(await page.locator('.workspace-loading').evaluate(node=>node.classList.contains('blocking')),true);
      release();await page.evaluate(()=>window.qaPending);await page.waitForFunction(()=>document.querySelector('.workspace-loading').hidden);
      measurements.push({viewport,scenario_ms:Date.now()-started,maximum_report_rows:50,
        identity_requests:1,account_requests:1,camera_startup_requests:0});
      await context.close();
    }
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'checks.json'),JSON.stringify({measurements,errors},null,2));
    console.log('OK: bounded report pages, cancellable reads, responsive navigation, shared identity and deferred camera');
  }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
