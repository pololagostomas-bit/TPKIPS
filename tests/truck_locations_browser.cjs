// Disposable support_dhl_server fixture only; all guides/locations are fictitious.
const {chromium} = require('playwright');
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const base = process.argv[2], output = path.join(__dirname, '../qa/truck-locations');
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '')) throw Error('Loopback fixture required');
const headers = {'Content-Type':'application/json', 'X-WMS-Request':'1'};
(async () => {
  fs.mkdirSync(output, {recursive:true});
  const browser = await chromium.launch({headless:true, channel:'msedge'}), results = [];
  try {
    for (const viewport of [{width:1440,height:900},{width:393,height:873},{width:360,height:780},{width:320,height:640},{width:873,height:393}]) {
      const context = await browser.newContext({viewport}), page = await context.newPage(), errors = [];
      let rejectNextDialog = false;
      page.on('pageerror', error => errors.push(error.message));
      page.on('dialog', dialog => { if (rejectNextDialog) {rejectNextDialog = false; dialog.dismiss();} else dialog.accept(); });
      await context.addInitScript(() => { if ('serviceWorker' in navigator) navigator.serviceWorker.register = async () => undefined; });
      assert.equal((await context.request.post(base + '/api/login', {headers,data:{username:'qa.reader',password:'QA-password-only-123!'}})).status(), 200);
      await page.goto(base + '/reception');
      await page.getByRole('button', {name:'Tránsito',exact:true}).click();
      await page.locator('#createScanTruckButton').click();
      await page.locator('#scanTruckPackageCode').waitFor();
      const guide = await page.locator('#truckGuideFilter').inputValue();
      for (const [code,total] of [['JD000000000000000001','1'],['JD000000000000000003','2'],['JD000000000000000004','3']]) {
        await page.locator('#scanTruckPackageCode').fill(code); await page.locator('#scanTruckPackageCode').press('Enter');
        await page.waitForFunction(value => document.querySelector('#scanTotal')?.textContent === value && !window.WmsTruckScan.hasPending(), total);
      }
      await page.locator('#finalizeScanTruckButton').click(); await page.locator('#scanGeneralLocation').waitFor();
      const cards = page.locator('.scan-location-card[data-truck-bl-row]');
      const first = cards.nth(0), second = cards.nth(1), general = page.locator('#scanGeneralLocation');
      assert.equal(await cards.count(), 2);
      await general.fill('QA-GENERAL');
      assert.deepEqual(await cards.locator('.truck-bl-location').evaluateAll(nodes => nodes.map(node => node.value)), ['QA-GENERAL','QA-GENERAL']);
      assert.deepEqual(await cards.locator('.truck-bl-location-qty').evaluateAll(nodes => nodes.map(node => node.value)), ['1','2']);
      assert.equal(await cards.locator('.truck-bl-location').evaluateAll(nodes => nodes.every(node => node.readOnly)), true);
      await second.locator('[data-own-location]').check();
      await second.locator('.truck-bl-location').fill('QA-EXCEPTION');
      await second.locator('.truck-bl-location-qty').fill('1');
      await second.locator('[data-add-location]').click();
      await second.locator('.truck-bl-location').nth(1).fill('QA-SECOND');
      await second.locator('.truck-bl-location-qty').nth(1).fill('1');
      await general.fill('QA-CHANGED');
      assert.equal(await first.locator('.truck-bl-location').inputValue(), 'QA-CHANGED');
      assert.deepEqual(await second.locator('.truck-bl-location').evaluateAll(nodes => nodes.map(node => node.value)), ['QA-EXCEPTION','QA-SECOND']);
      await general.fill(''); assert.equal(await first.locator('.truck-bl-location').inputValue(), '');
      assert.equal(await second.locator('.truck-bl-location').first().inputValue(), 'QA-EXCEPTION');
      await general.fill('QA-CHANGED');
      await second.locator('.truck-bl-location').nth(1).fill('qa-exception');
      await page.locator('#saveTruckLocationsButton').click();
      assert.equal(await general.isVisible(), true); assert.equal(await second.locator('[aria-invalid="true"]').count(), 1);
      await second.locator('.truck-bl-location').nth(1).fill('QA-SECOND');
      await second.locator('.truck-bl-location-qty').nth(1).fill('2');
      await page.locator('#saveTruckLocationsButton').click();
      assert.match(await second.locator('.truck-bl-location-status').textContent(), /Sobran 1/);
      await second.locator('.truck-bl-location-qty').nth(1).fill('1');
      rejectNextDialog = true; await second.locator('[data-own-location]').click();
      assert.equal(await second.locator('[data-own-location]').isChecked(), true);
      assert.equal(await second.locator('.truck-location-row').count(), 2);
      await second.locator('[data-own-location]').uncheck();
      assert.equal(await second.locator('.truck-location-row').count(), 1);
      assert.equal(await second.locator('.truck-bl-location').inputValue(), 'QA-CHANGED');
      assert.equal(await second.locator('.truck-bl-location-qty').inputValue(), '2');
      await page.locator('[data-truck-action="discard"]').click(); await general.waitFor();
      assert.equal(await general.inputValue(), '');
      assert.deepEqual(await cards.locator('.truck-bl-location').evaluateAll(nodes => nodes.map(node => node.value)), ['','']);
      await general.fill('QA-CHANGED'); await second.locator('[data-own-location]').check();
      await second.locator('.truck-bl-location').fill('QA-EXCEPTION'); await second.locator('.truck-bl-location-qty').fill('1');
      await second.locator('[data-add-location]').click();
      await second.locator('.truck-bl-location').nth(1).fill('QA-SECOND'); await second.locator('.truck-bl-location-qty').nth(1).fill('1');
      assert.equal(await cards.locator('.truck-bl-location-qty').evaluateAll(nodes => nodes.every(node => node.getBoundingClientRect().width >= 72)), true, 'Readable quantity inputs');
      await page.screenshot({path:path.join(output,'draft-' + viewport.width + '.png'),fullPage:true});
      await page.locator('.scan-task').evaluate(node => node.scrollTop = 0);
      await page.screenshot({path:path.join(output,'general-' + viewport.width + '.png'),fullPage:true});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
      await page.route('**/api/receptions/truck-guide/locations', route => route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'QA: guardado no disponible'})}), {times:1});
      await page.locator('#saveTruckLocationsButton').click();
      await page.waitForFunction(() => document.querySelector('#scanFeedback')?.textContent.includes('QA: guardado no disponible') && !window.WmsTruckControls.hasPending());
      assert.equal(await general.isEnabled(), true);
      assert.equal(await second.locator('.truck-location-row').count(), 2, 'Failed save retains the draft');
      const submitted = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/truck-guide/locations'));
      await page.locator('#saveTruckLocationsButton').click();
      const payload = (await submitted).postDataJSON();
      assert.deepEqual(payload.bls.map(row => row.locations), [
        [{location:'QA-CHANGED',package_count:1}], [{location:'QA-EXCEPTION',package_count:1},{location:'QA-SECOND',package_count:1}]
      ]);
      await page.getByRole('heading', {name:'Camión terminado',exact:true}).waitFor();
      assert.equal(await page.locator('.scan-location-summary li').count(), 3);
      await page.getByRole('button',{name:'Revisar BL 1234567890',exact:true}).click();
      await page.waitForFunction(() => document.querySelector('#scanDhlProgress')?.textContent.includes('Por escanear: 1'));
      assert.equal(await page.locator('#scanBlCount').textContent(), '1');
      assert.equal(await page.locator('.scan-location-summary li').count(), 3, 'Review preserves saved locations');
      const summary = await (await context.request.get(base + '/api/receptions/truck-guide?truck_guide=' + encodeURIComponent(guide))).json();
      assert.equal(summary.guide_status, 'LISTA_PARA_CONTEO');
      assert.deepEqual(summary.bls.map(row => row.received_this_truck), [1,2]);
      assert.deepEqual(summary.bls.map(row => row.locations.map(item => [item.location_text,item.package_count])), [
        [['QA-CHANGED',1]], [['QA-EXCEPTION',1],['QA-SECOND',1]]
      ]);
      await page.screenshot({path:path.join(output,'saved-' + viewport.width + '.png'),fullPage:true});
      await page.locator('[data-truck-action="back"]').click(); await general.waitFor();
      assert.deepEqual(await cards.locator('.truck-bl-location').evaluateAll(nodes => nodes.map(node => node.value)), ['QA-CHANGED','QA-EXCEPTION','QA-SECOND']);
      assert.equal(await second.locator('[data-own-location]').isChecked(), true);
      await general.fill('QA-REOPENED');
      assert.equal(await first.locator('.truck-bl-location').inputValue(), 'QA-CHANGED', 'Saved exceptions are not overwritten');
      await first.locator('[data-own-location]').uncheck(); await second.locator('[data-own-location]').uncheck();
      await page.locator('#saveTruckLocationsButton').click();
      await page.getByRole('heading', {name:'Camión terminado',exact:true}).waitFor();
      await page.locator('[data-truck-action="back"]').click(); await general.waitFor();
      assert.equal(await general.inputValue(), 'QA-REOPENED');
      assert.equal(await cards.locator('[data-own-location]:checked').count(), 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
      assert.deepEqual(errors, []);
      assert.equal((await context.request.post(base + '/api/receptions/truck-guide/cancel', {headers,data:{truck_guide:guide,reason:'QA cleanup'}})).status(), 200);
      results.push({viewport,received:[1,2],split_preserved:true,general_recovered:true});
      await context.close();
    }
    fs.writeFileSync(path.join(output,'results.json'), JSON.stringify(results,null,2));
    console.log('OK: general location, per-BL split, validation, reset confirmation, discard, saved summary, reopen, five viewports');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
