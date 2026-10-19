// Real local sessions and disposable data; never run against the production WMS.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const base = process.argv[2], output = path.join(__dirname, '../qa/package-access');
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '')) throw Error('Loopback fixture required');
const headers = {'Content-Type':'application/json', 'X-WMS-Request':'1'};
async function login(context, username) {
  const response = await context.request.post(base + '/api/login', {
    headers, data:{username, password:'QA-password-only-123!'}});
  assert.equal(response.status(), 200);
}
(async () => {
  fs.mkdirSync(output, {recursive:true});
  const browser = await chromium.launch({headless:true, channel:'msedge'}), results = [];
  try {
    const admin = await browser.newContext(); await login(admin, 'qa.reader');
    for (const username of ['qa.assistant', 'qa.auxiliary']) {
      for (const viewport of [{width:320,height:640}, {width:393,height:873},
          {width:1366,height:768}, {width:873,height:393}]) {
        const created = await admin.request.post(base + '/api/receptions/truck-guide/scan-create', {headers, data:{}});
        assert.equal(created.status(), 201);
        const guide = (await created.json()).truck_guide;
        assert.equal((await admin.request.post(base + '/api/receptions/truck-guide/scan-bl', {
          headers, data:{truck_guide:guide, bl_code:'1234567890'}})).status(), 200);
        const context = await browser.newContext({viewport}); await login(context, username);
        const page = await context.newPage(), errors = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('dialog', dialog => dialog.accept());
        await context.addInitScript(() => {
          if ('serviceWorker' in navigator) navigator.serviceWorker.register = async () => undefined;
        });
        for (const method of ['get', 'post']) {
          const response = await context.request[method](base + '/api/dhl-tracking/shipment?shipment_id=1&role=ADMINISTRADOR',
            method === 'post' ? {headers, data:{shipment_id:1, role:'ADMINISTRADOR'}} : {});
          assert.equal(response.status(), 200);
          const data = await response.json();
          assert.equal(data.can_view_piece_codes, false);
          assert.equal(data.pending_pieces, 61);
          assert.equal(data.pending_piece_ids, undefined);
          assert.ok(!JSON.stringify(data).includes('JD00000001'));
        }
        const list = await context.request.get(base + '/api/receptions/truck-guide/manual-pieces?truck_guide='
          + encodeURIComponent(guide) + '&shipment_id=1', {headers:{'X-Role':'ADMINISTRADOR'}});
        assert.equal(list.status(), 403, 'Forged role header cannot replace a worker session');
        assert.equal((await context.request.post(base + '/api/receptions/truck-guide/manual-package', {headers,
          data:{truck_guide:guide, shipment_id:1, package_code:'JD00000001', source:'cache',
            reason:'Synthetic physical evidence', confirmed:true, role:'ADMINISTRADOR'}})).status(), 403);
        await page.goto(base + '/reception');
        await page.getByRole('button', {name:'Tránsito', exact:true}).click();
        await page.locator('#truckGuideFilter option[value="' + guide + '"]').waitFor({state:'attached'});
        await page.locator('#truckGuideFilter').selectOption(guide);
        await page.locator('#scanTruckPackageCode').waitFor();
        await page.locator('#scanBlListTitle').click();
        await page.locator('[data-scan-context="1"]').click();
        await page.locator('#scanDhlProgress').waitFor({state:'visible'});
        assert.ok((await page.locator('#scanDhlProgress').textContent()).includes('Por escanear'));
        assert.equal(await page.locator('#scanDhlProgress details').count(), 0);
        assert.equal(await page.locator('#scanManualSearch').count(), 0);
        assert.equal(await page.locator('#scanManualPieces').count(), 0);
        assert.ok(!(await page.locator('body').textContent()).includes('JD00000002'));
        await page.locator('#scanTruckPackageCode').fill('JD-INVALID-BOX');
        await page.locator('#scanTruckPackageCode').press('Enter');
        await page.locator('#scanFeedback[role=alert]').waitFor();
        assert.equal(await page.locator('#scanTotal').textContent(), '0');
        assert.equal(await page.locator('[data-identify-reading]').count(), 0);
        await page.locator('[data-discard-reading]').click();
        await page.locator('#scanTruckPackageCode').fill('JJD00000001');
        await page.locator('#scanTruckPackageCode').press('Enter');
        await page.waitForFunction(() => document.querySelector('#scanTotal')?.textContent === '1');
        await page.waitForFunction(() => document.querySelector('#scanPackageSubmit')?.disabled === false);
        await page.locator('#scanTruckPackageCode').fill('JD00000001');
        await page.locator('#scanTruckPackageCode').press('Enter');
        await page.waitForFunction(() => document.querySelector('#scanFeedback')?.textContent.includes('ya registrado'));
        assert.equal(await page.locator('#scanTotal').textContent(), '1');
        const forged = await context.request.post(base + '/api/receptions/truck-arrival', {headers, data:{
          truck_guide:guide, arrival_key:'QA-FORGED', bls:[{shipment_id:1, received_packages:61, excess_reason:'QA fake count'}]}});
        assert.ok([400,403].includes(forged.status()));
        await page.screenshot({path:path.join(output, username + '-' + viewport.width + '.png'), fullPage:true});
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
        if (viewport.width === 320) {
          await page.addStyleTag({content:'#scanTruckWorkspace{font-size:200%} #scanTruckWorkspace input,#scanTruckWorkspace button,#scanTruckWorkspace label,#scanTruckWorkspace p,#scanTruckWorkspace summary,#scanTruckWorkspace small,#scanTruckWorkspace strong{font-size:inherit}'});
          await page.screenshot({path:path.join(output, username + '-320-text200.png'), fullPage:true});
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
        }
        assert.deepEqual(errors, []);
        const adminStatus = await (await admin.request.get(base + '/api/dhl-tracking/shipment?shipment_id=1')).json();
        assert.equal(adminStatus.can_view_piece_codes, true);
        assert.ok(adminStatus.pending_piece_ids.includes('JD00000002'));
        assert.equal((await admin.request.post(base + '/api/receptions/truck-guide/cancel', {
          headers, data:{truck_guide:guide}})).status(), 200);
        results.push({username, viewport, physical_count:1, expected_codes_hidden:true});
        await context.close();
      }
    }
    await admin.close();
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(results, null, 2));
    console.log('OK: two real worker roles, server privacy, forged role/selection/count rejected, exact scan, duplicate, four viewports and 200% text');
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
