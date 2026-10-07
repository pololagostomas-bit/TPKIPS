// Disposable fixture only: support_navigation_server.py.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const base=process.argv[2];
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Loopback QA URL required');

(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH||chromium.executablePath()});
  let probePage;
  try{
    for(const viewport of [{width:1366,height:900},{width:375,height:812}]){
      const context=await browser.newContext({viewport});
      const page=await context.newPage();
      probePage=page;
      const errors=[],dialogs=[],writes=[];
      let allowDiscard=false;
      page.on('pageerror',e=>errors.push(e.message));
      page.on('request',r=>{if(r.method()==='POST')writes.push(r.url())});
      page.on('dialog',async d=>{dialogs.push(d.message());if(allowDiscard)await d.accept();else await d.dismiss()});
      await page.route('**/api/truck-guides?*',async route=>{
        await new Promise(resolve=>setTimeout(resolve,500));
        await route.continue();
      });
      await page.goto(base+'/reception');
      await page.evaluate(()=>openTruckGuideFromBl('QA-ORIGIN'));
      await page.getByRole('button',{name:/Continuar recepci.n|Abrir BL para conteo/}).first().click();
      await page.getByRole('heading',{name:'QA-RETURN-001',exact:true}).waitFor();
      await page.waitForFunction(()=>!receptionHasUnsavedFields());
      await page.waitForTimeout(100);
      await page.reload();
      await page.getByRole('heading',{name:'QA-RETURN-001',exact:true}).waitFor();
      await page.waitForFunction(()=>!receptionHasUnsavedFields());
      await page.getByRole('button',{name:/Volver al camion QA-ORIGIN/}).click();
      await page.locator('#content [data-truck-guide="QA-ORIGIN"]').waitFor();
      assert.equal(dialogs.length,0,'Untouched BL must not request discarding edits');
      assert.equal(await page.evaluate(()=>selectedId),null);
      await page.getByRole('button',{name:/Continuar recepci.n|Abrir BL para conteo/}).first().click();
      await page.getByRole('heading',{name:'QA-RETURN-001',exact:true}).waitFor();
      await page.waitForFunction(()=>!receptionHasUnsavedFields());
      const field=page.locator('#content input:not([type="hidden"]):enabled:not([readonly]):visible').first();
      const original=await field.inputValue();
      await field.fill(await field.getAttribute('type')==='number'?String(Number(original||0)+1):original+'-QA');
      assert.equal(await page.evaluate(()=>receptionHasUnsavedFields()),true);
      await page.getByRole('button',{name:/Volver al camion QA-ORIGIN/}).click();
      assert.equal(dialogs.length,1);
      assert.equal(await page.evaluate(()=>selectedId),1,'Cancel keeps the BL and unsaved fields');
      assert.equal(await field.inputValue()===original,false);
      allowDiscard=true;
      await page.getByRole('button',{name:/Volver al camion QA-ORIGIN/}).click();
      await page.locator('#content [data-truck-guide="QA-ORIGIN"]').waitFor();
      assert.equal(dialogs.length,2);
      assert.equal(await page.evaluate(()=>selectedId),null);
      assert.deepEqual(writes,[],'Return navigation must never reverse arrivals or write data');
      assert.deepEqual(errors,[]);
      await context.close();
      console.log('OK: real return click after reload, no false dirty warning, cancel/confirm edits, GET only, '+viewport.width+'px');
    }
  }catch(error){
    if(probePage&&!probePage.isClosed()){
      console.error(await probePage.locator('#content').innerText());
      console.error(await probePage.evaluate(()=>({selectedId,continuity:window.getReceptionContinuityState?.(),storage:{...sessionStorage}})));
    }
    throw error;
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
