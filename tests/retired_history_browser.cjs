const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const base=process.argv[2];
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable loopback fixture required');
const output=path.join(__dirname,'../qa/retired-history');
(async()=>{
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  const errors=[];
  try{
    for(const viewport of [{width:320,height:640},{width:393,height:873},{width:1366,height:768},{width:873,height:393}]){
      const context=await browser.newContext({viewport,serviceWorkers:'block'});
      const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
      await page.goto(base+'/reception');await page.waitForSelector('html[data-wms-ui=ready]');
      await page.evaluate(()=>loadDetail(1));await page.waitForSelector('.hero h1');
      assert.match(await page.locator('.hero h1').textContent(),/QA-HISTORY-RETIRED/);
      assert.equal(await page.locator('.attention-summary').count(),0,'Retired tests are not active arrival summaries');
      assert.match(await page.locator('.hero .badges').textContent(),/CERRADO/);
      await page.screenshot({path:path.join(output,`closed-${viewport.width}.png`)});
      await page.evaluate(()=>showMyWork());await page.waitForSelector('[data-work-view=history]');
      await page.locator('[data-work-view=history]').click();
      await page.waitForFunction(()=>document.querySelectorAll('[data-work-row]').length===1);
      assert.match(await page.locator('[data-work-row]').textContent(),/QA-HISTORY-RETIRED/);
      await page.evaluate(()=>loadDetail(2));await page.waitForSelector('.attention-summary',{state:'attached'});
      await page.locator('.attention-summary').evaluate(node=>{
        for(let parent=node.parentElement;parent;parent=parent.parentElement){if(parent.tagName==='DETAILS')parent.open=true;}
      });
      assert.equal(await page.locator('.attention-summary .attention-row').count(),2);
      const labels=await page.locator('.attention-row > strong').allTextContents();
      assert.deepEqual(labels,['Atención 1/2','Atención 2/2']);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
      await page.screenshot({path:path.join(output,`partial-${viewport.width}.png`)});
      await context.close();
    }
    assert.deepEqual(errors,[]);
    console.log('OK: retired tests hidden, one closed BL, real partial numbering, desktop/mobile/landscape.');
  }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
