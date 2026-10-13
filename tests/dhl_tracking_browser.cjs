// Run only against support_dhl_server.py; no real tracking/mail/warehouse data.
const {chromium} = require('playwright');
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const base = process.argv[2], output = path.join(__dirname,'../qa/dhl-tracking');
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '')) throw Error('Disposable loopback fixture required');
const headers = {'Content-Type':'application/json','X-WMS-Request':'1'};
(async () => {
  fs.mkdirSync(output,{recursive:true});
  const browser = await chromium.launch({headless:true,channel:'msedge'}), results=[];
  try {
    for (const viewport of [{width:1440,height:900},{width:393,height:873},{width:360,height:780},{width:320,height:640},{width:873,height:393}]) {
      const context = await browser.newContext({viewport}), page=await context.newPage(), errors=[];
      page.on('pageerror', error=>errors.push(error.message));
      page.on('dialog', dialog=>dialog.accept());
      await context.addInitScript(()=>{if('serviceWorker' in navigator)navigator.serviceWorker.register=async()=>undefined;});
      const login=await context.request.post(base+'/api/login',{headers,data:{username:'qa.reader',password:'QA-password-only-123!'}});
      assert.equal(login.status(),200);
      const before=await (await context.request.get(base+'/api/dhl-tracking/status')).json();
      await page.goto(base+'/reception');
      await page.getByRole('button',{name:'Tránsito',exact:true}).click();
      await page.locator('#createScanTruckButton').click();
      await page.locator('#scanTruckBlCode').fill('1234567890');
      await page.locator('#scanTruckBlCode').press('Enter');
      await page.locator('#scanDhlStatus:not([hidden])').waitFor();
      await page.waitForFunction(()=>document.querySelector('#scanDhlText')?.textContent.includes('2 bultos'));
      assert.equal(await page.evaluate(()=>document.activeElement.id),'scanTruckPackageCode');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'Scanner horizontal overflow');
      await page.screenshot({path:path.join(output,'scan-'+viewport.width+'.png'),fullPage:true});
      const valid = 'JD0000000000000000' + '01';
      await page.locator('#scanTruckPackageCode').fill(valid);
      await page.locator('#scanTruckPackageCode').press('Enter');
      await page.waitForFunction(()=>document.querySelector('#scanFeedback')?.textContent.includes('Verificado por DHL'));
      await page.locator('#scanTruckPackageCode').fill('JD000000000000000003');
      await page.locator('#scanTruckPackageCode').press('Enter');
      await page.waitForFunction(()=>document.querySelector('#scanFeedback')?.textContent.includes('1234567891'));
      assert.equal(await page.locator('#scanTotal').textContent(),'1');
      assert.equal(await page.locator('#finalizeScanTruckButton').isDisabled(),true);
      await page.locator('[data-discard-reading]').click();
      await page.locator('[data-truck-action="cancel"]').click();
      await page.waitForFunction(()=>document.querySelector('#truckGuideFilter')?.value==='ALL' && !window.WmsTruckControls?.hasPending());
      await page.goto(base+'/cloud-connection');
      await page.waitForFunction(()=>document.querySelector('#dhlConnectionFacts')?.textContent.includes('2 guias guardadas'));
      const after=await (await context.request.get(base+'/api/dhl-tracking/status')).json();
      assert.equal(after.calls_today,before.calls_today,'UI/scan must not spend extra DHL requests');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
      await page.screenshot({path:path.join(output,'admin-'+viewport.width+'.png'),fullPage:true});
      assert.deepEqual(errors,[]);
      results.push({viewport,calls:after.calls_today});
      await context.close();
    }
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(results,null,2));
    console.log('OK: DHL local scan, wrong BL rejection, preserved failures, admin status, unchanged API budget, five viewports');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
