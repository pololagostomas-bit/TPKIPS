// Synthetic loopback fixture only. No production DB, mail, or tracking network.
const {chromium} = require('playwright');
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const base = process.argv[2], output = path.join(__dirname, '../qa/package-manual');
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '')) throw Error('Loopback fixture required');
const headers = {'Content-Type':'application/json','X-WMS-Request':'1'};
(async () => {
  fs.mkdirSync(output, {recursive:true});
  const browser = await chromium.launch({headless:true,channel:'msedge'}), results = [];
  try {
    for (const viewport of [{width:320,height:640},{width:393,height:873},{width:1366,height:768},{width:873,height:393}]) {
      const context = await browser.newContext({viewport}), page = await context.newPage(), errors = [];
      page.on('pageerror', error => errors.push(error.message)); page.on('dialog', dialog => dialog.accept());
      await context.addInitScript(() => {if ('serviceWorker' in navigator) navigator.serviceWorker.register = async () => undefined;});
      assert.equal((await context.request.post(base+'/api/login', {headers,data:{username:'qa.reader',password:'QA-password-only-123!'}})).status(), 200);
      await context.request.post(base+'/api/account/preferences', {headers,data:{show_guidance:false}});
      const calls = (await (await context.request.get(base+'/api/dhl-tracking/status')).json()).calls_today;
      await page.goto(base+'/reception'); await page.getByRole('button',{name:'Tránsito',exact:true}).click();
      await page.locator('#createScanTruckButton').click(); await page.locator('#scanTruckPackageCode').waitFor();
      const guide = await page.locator('#truckGuideFilter').inputValue();
      const anonymous = await browser.newContext();
      assert.equal((await anonymous.request.get(base+'/api/receptions/truck-guide/manual-pieces?truck_guide='+encodeURIComponent(guide)+'&shipment_id=1')).status(),401);
      await anonymous.close();
      assert.equal((await context.request.post(base+'/api/receptions/truck-guide/manual-package',{
        headers:{'Content-Type':'application/json'},data:{truck_guide:guide,shipment_id:1,
          package_code:'JD00000001',source:'cache',reason:'QA identity checked',confirmed:true}})).status(),403);
      await page.getByRole('button',{name:'Por BL',exact:true}).click();
      await page.locator('#scanTruckBlCode').fill('1234567890'); await page.locator('#scanBlSubmit').click();
      await page.waitForFunction(() => document.querySelector('#scanReceivingBl')?.textContent === '1234567890' && !document.querySelector('#scanTruckPackageCode').disabled);
      await page.locator('#scanManualEntry>summary').click();
      await page.locator('[data-manual-piece]').first().waitFor();
      assert.equal(await page.locator('#scanManualPieces li').count(), 50);
      await page.locator('#scanManualNext').click();
      await page.waitForFunction(() => document.querySelector('#scanManualPieces')?.children.length === 11);
      await page.locator('#scanManualSearch').fill('JJD00000001'); await page.locator('#scanManualReload').click();
      await page.waitForFunction(() => document.querySelector('#scanManualPieces')?.children.length === 1);
      await page.locator('[data-manual-piece]').click();
      assert.equal(await page.locator('#scanManualSelected').textContent(),'JD00000001');
      assert.equal(await page.locator('#scanManualRequirement').isVisible(), true, 'Minimum identity remains visible without guidance');
      assert.equal(await page.locator('#scanManualEntry .help-guidance').isVisible(), false);
      await page.locator('#scanManualSave').click();
      await page.locator('#scanManualStatus[role=alert]').waitFor();
      await page.locator('#scanManualReason').fill('Etiqueta borrosa; documento sintetico verificado');
      await page.locator('#scanManualConfirmed').check();
      let fail = true;
      await page.route('**/api/receptions/truck-guide/manual-package', async route => {
        if (fail) {fail = false; await route.fulfill({status:503,json:{error:'QA retry needed'}});}
        else await route.continue();
      });
      await page.locator('#scanManualSave').click(); await page.locator('[data-retry-reading]').waitFor();
      assert.equal(await page.locator('#scanManualSelected').textContent(),'JD00000001');
      assert.equal(await page.locator('#scanTotal').textContent(),'0');
      await page.locator('[data-retry-reading]').click();
      await page.waitForFunction(() => document.querySelector('#scanTotal')?.textContent === '1');
      await page.locator('#scanManualEntry>summary').click();
      await page.locator('#scanManualReload').click();
      await page.waitForFunction(() => document.querySelector('#scanManualPieces')?.textContent.includes('Recibida'));
      assert.equal(await page.locator('[data-manual-piece]').count(),0, 'Received piece cannot be selected again');
      const alias = await page.evaluate(async () => WmsTruckScan.scanPackage('JJD00000001'));
      assert.equal(alias.status,'duplicate'); assert.equal(await page.locator('#scanTotal').textContent(),'1');
      await page.locator('#scanBlEntryTitle').click();
      await page.locator('#scanTruckBlCode').fill('QA-SEA-0001'); await page.locator('#scanBlSubmit').click();
      await page.waitForFunction(() => document.querySelector('#scanReceivingBl')?.textContent === 'QA-SEA-0001');
      await page.locator('#scanManualEntry>summary').click();
      await page.locator('#scanManualKnownCode').fill('QA-SEA-BOX-01'); await page.locator('#scanManualUseCode').click();
      await page.locator('#scanManualReason').fill('Identidad cotejada con documento sintetico');
      await page.locator('#scanManualConfirmed').check();
      // A failed read-only cache request must not prevent an explicit known-code receipt.
      await page.route('**/api/receptions/truck-guide/manual-pieces?*', route => route.fulfill({status:503,json:{error:'QA unavailable'}}));
      await page.locator('#scanManualReload').click();
      await page.waitForFunction(() => document.querySelector('#scanManualStatus')?.textContent.includes('Lista no disponible'));
      await page.screenshot({path:path.join(output,'manual-'+viewport.width+'.png'),fullPage:true});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1),false,'Page overflow');
      const bounds = await page.locator('#scanManualSave').boundingBox(); assert.ok(bounds.height >= 48);
      await page.locator('#scanManualSave').click();
      await page.waitForFunction(() => document.querySelector('#scanTotal')?.textContent === '2');
      if (viewport.width === 320) {
        await page.addStyleTag({content:'#scanTruckWorkspace{font-size:200%} #scanTruckWorkspace input,#scanTruckWorkspace button,#scanTruckWorkspace label,#scanTruckWorkspace p,#scanTruckWorkspace summary,#scanTruckWorkspace small,#scanTruckWorkspace strong{font-size:inherit}'});
        await page.screenshot({path:path.join(output,'manual-320-text200.png'),fullPage:true});
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1),false,'200% text overflow');
      }
      assert.equal((await (await context.request.get(base+'/api/dhl-tracking/status')).json()).calls_today,calls,'No tracking calls per piece');
      assert.deepEqual(errors,[]); results.push({viewport,packages:2,tracking_calls:calls});
      assert.equal((await context.request.post(base+'/api/receptions/truck-guide/cancel',{headers,data:{truck_guide:guide}})).status(),200);
      await context.close();
    }
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(results,null,2));
    console.log('OK: manual cached piece, pagination, JJD alias, uncertain retry, maritime typing, identity, guidance, four viewports and 200% text');
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
