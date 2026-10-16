const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const base=process.argv[2];
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable loopback fixture required');
const output=path.join(__dirname,'../qa/arrival-queues');
(async()=>{
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  const errors=[];
  try{
    for(const viewport of [{width:320,height:640},{width:393,height:873},{width:1366,height:768},{width:873,height:393}]){
      const context=await browser.newContext({viewport,serviceWorkers:'block'});
      const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
      await page.goto(base+'/reception');await page.waitForSelector('html[data-wms-ui=ready]');
      await page.evaluate(()=>showMyWork());await page.waitForSelector('[data-work-view=truck]');
      const metric=async key=>Number(await page.locator(`[data-work-metric="${key}"] strong`).innerText());
      assert.equal(await metric(''),1);assert.equal(await metric('truck'),3);assert.equal(await metric('upcoming'),3);
      await page.locator('[data-work-metric=truck]').click();
      await page.waitForFunction(()=>document.querySelectorAll('[data-work-row]').length===3);
      const truckText=await page.locator('.work-table').innerText();
      assert.match(truckText,/QA-PAST/);assert.match(truckText,/QA-FR-FUTURE/);assert.match(truckText,/QA-REF-FR/);
      assert.match(truckText,/FR registrada/);assert.match(truckText,/Fecha Triton vencida/);
      assert.match(truckText,/\d{2}\/\d{2}\/\d{4}/,'Date-only Excel values are visible');
      assert.doesNotMatch(truckText,/Sin fecha registrada/);
      assert.match(truckText,/Aún no inicia/);assert.doesNotMatch(truckText,/Límite:|Vencido hace/);
      assert.equal(await page.locator('[data-work-truck]').count(),2);
      assert.equal(await page.locator('[data-work-existing-truck]').count(),1);
      await page.screenshot({path:path.join(output,`truck-${viewport.width}.png`),fullPage:false});
      await page.evaluate(()=>{window.qaOpenedTruck='';window.openTruckGuideFromBl=async guide=>{window.qaOpenedTruck=guide}});
      await page.locator('[data-work-existing-truck]').click();
      assert.equal(await page.evaluate(()=>window.qaOpenedTruck),'QA-TRUCK-EXISTING');
      await page.locator('[data-work-view=upcoming]').click();
      await page.waitForFunction(()=>document.querySelectorAll('[data-work-row]').length===3&&document.querySelector('.work-table')?.innerText.includes('QA-TODAY'));
      const upcoming=await page.locator('.work-table').innerText();
      assert.match(upcoming,/QA-TODAY/);assert.match(upcoming,/QA-FUTURE/);assert.match(upcoming,/QA-NO-DATE/);
      assert.doesNotMatch(upcoming,/QA-PAST|FR registrada/);
      await page.locator('#workSearch').fill('QA-NO-DATE');
      await page.waitForFunction(()=>document.querySelectorAll('[data-work-row]').length===1);
      assert.match(await page.locator('[data-work-row]').innerText(),/Sin fecha prevista/);
      assert.equal(await metric('truck'),3,'Filters do not rewrite global KPIs');
      await page.locator('#workSearch').fill('');
      await page.waitForFunction(()=>document.querySelectorAll('[data-work-row]').length===3);
      await page.route('**/api/receptions/work?**',async route=>{
        await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'QA temporary failure'})});
      },{times:1});
      await page.locator('#workRefresh').click();
      await page.locator('#workError').waitFor({state:'visible'});
      assert.match(await page.locator('#workError').innerText(),/QA temporary failure/);
      await page.locator('#workRefresh').click();
      await page.locator('#workError').waitFor({state:'hidden'});
      await page.locator('[data-work-view=history]').click();
      await page.waitForFunction(()=>document.querySelectorAll('[data-work-row]').length===1&&document.querySelector('.work-table')?.innerText.includes('QA-CLOSED'));
      await page.locator('[data-work-view=truck]').click();
      await page.waitForFunction(()=>document.querySelectorAll('[data-work-row]').length===3);
      if(viewport.width===320){
        await page.evaluate(()=>{
          const sizes=[...document.querySelectorAll('.reception-work,.reception-work *')].map(node=>[node,getComputedStyle(node).fontSize]);
          for(const [node,size] of sizes)node.style.fontSize=(parseFloat(size)*2)+'px';
        });
        await page.screenshot({path:path.join(output,'truck-text200-320.png'),fullPage:false});
      }
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,'Page reflows');
      const buttons=await page.locator('.work-view-tabs button').evaluateAll(nodes=>nodes.map(node=>{
        const box=node.getBoundingClientRect();return {height:box.height,width:box.width,x:box.x};
      }));
      assert.ok(buttons.every(box=>box.height>=44&&box.x>=0&&box.x+box.width<=viewport.width+1),'Visible reachable tabs');
      await context.close();
    }
    assert.deepEqual(errors,[]);
    console.log('OK: arrival priorities, no false SLA, existing truck, filters, history, error/retry, 4 viewports and 200% text.');
  }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
