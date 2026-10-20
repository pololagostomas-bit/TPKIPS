// Synthetic HTTP only; no production requests, tracking calls or database writes.
const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..'), base = 'http://127.0.0.1:51987';
let browser;
before(async () => { browser = await chromium.launch({headless: true, channel: 'msedge'}); });
after(async () => { await browser?.close(); });

async function fixture(t) {
  const context = await browser.newContext({viewport: {width: 393, height: 873}, serviceWorkers: 'block'});
  t.after(() => context.close());
  const page = await context.newPage(), errors = [], writes = [];
  let mode = 'ok', release;
  const summary = {truck_guide: 'QA-TRUCK', guide_status: 'PENDIENTE', scanner_enabled: true,
    is_confirmed: 1, bls: [{id: 701, bl_awb: 'QA-BL', truck_work_pending: true, package_scan_count: 0}]};
  page.on('pageerror', error => errors.push(error.message));
  t.after(() => assert.deepEqual(errors, []));
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url());
    assert.equal(url.origin, base);
    if (url.pathname === '/reception') return route.fulfill({contentType: 'text/html',
      body: fs.readFileSync(path.join(root, 'frontend/templates/reception.html'))});
    if (url.pathname.startsWith('/assets/')) {
      const file = path.join(root, 'frontend/static', path.basename(url.pathname));
      return fs.existsSync(file) ? route.fulfill({path: file}) : route.fulfill({status: 204, body: ''});
    }
    if (req.method() === 'POST') {
      writes.push({path: url.pathname, body: req.postDataJSON()});
      if (mode === 'hold') await new Promise(resolve => { release = resolve; });
      if (mode === 'reject') return route.fulfill({status: 400, json: {error: 'QA codigo ajeno'}});
      if (mode === 'invalid-json') return route.fulfill({status: 503, body: 'Unavailable'});
      return route.fulfill({json: {shipment_id: 701, bl_awb: 'QA-BL', count: 1,
        duplicate: mode === 'duplicate', dhl_verification: 'verified'}});
    }
    let data = {};
    if (['/api/me', '/api/account'].includes(url.pathname)) data = {username: 'qa.reader',
      display_name: 'QA', role: 'ADMINISTRADOR', mode: 'demo', show_guidance: false};
    if (['/api/truck-guides', '/api/receptions'].includes(url.pathname)) data = [];
    if (url.pathname === '/api/assignees') data = {users: []};
    if (url.pathname === '/api/receptions/truck-guide') data = summary;
    return route.fulfill({json: data});
  });
  await page.goto(base + '/reception');
  await page.waitForFunction(() => Boolean(window.WmsTruckScan) && document.querySelector('.home-welcome'));
  await page.evaluate(async () => {
    window.sounds = []; window.arms = 0;
    window.WmsScanFeedback = {arm() { arms++; }, success() { sounds.push('success'); }, error() { sounds.push('error'); }};
    await openTruckGuideFromBl('QA-TRUCK');
  });
  await page.locator('#scanTruckPackageCode').waitFor();
  return {page, writes, setMode: value => { mode = value; }, resolve: () => { mode = 'ok'; release(); }};
}

async function scan(page, code = 'QA-PIECE') {
  await page.locator('#scanTruckPackageCode').fill(code);
  await page.locator('#scanTruckPackageCode').press('Enter');
}

test('truck scan sound waits for HTTP confirmation, duplicate sounds error', async t => {
  const f = await fixture(t); f.setMode('hold');
  await scan(f.page);
  await f.page.waitForFunction(() => WmsTruckScan.hasPending());
  assert.deepEqual(await f.page.evaluate(() => sounds), []);
  assert.equal(await f.page.evaluate(() => arms), 1);
  f.resolve();
  await f.page.waitForFunction(() => !WmsTruckScan.hasPending());
  assert.deepEqual(await f.page.evaluate(() => sounds), ['success']);
  f.setMode('duplicate'); await scan(f.page);
  await f.page.waitForFunction(() => !WmsTruckScan.hasPending());
  assert.deepEqual(await f.page.evaluate(() => sounds), ['success', 'error']);
  assert.equal(f.writes.length, 2);
});

for (const mode of ['reject', 'invalid-json']) test('truck ' + mode + ' sounds error only', async t => {
  const f = await fixture(t); f.setMode(mode); await scan(f.page);
  await f.page.waitForFunction(() => WmsTruckScan.getCameraState().pending === 0);
  assert.deepEqual(await f.page.evaluate(() => sounds), ['error']);
});

test('truck late result cannot beep in a different context', async t => {
  const f = await fixture(t); f.setMode('hold'); await scan(f.page);
  await f.page.waitForFunction(() => WmsTruckScan.hasPending());
  await f.page.evaluate(() => { document.querySelector('#scanTruckWorkspace').dataset.guide = 'QA-OTHER'; });
  f.resolve(); await f.page.waitForFunction(() => !WmsTruckScan.hasPending());
  assert.deepEqual(await f.page.evaluate(() => sounds), []);
});

test('BL scan sound confirms chosen BL and warns on rejection', async t => {
  const f = await fixture(t);
  await f.page.evaluate(() => WmsTruckScan.setMode('bl'));
  await f.page.locator('#scanTruckBlCode').fill('QA-BL');
  await f.page.locator('#scanTruckBlCode').press('Enter');
  await f.page.waitForFunction(() => !WmsTruckScan.hasPending());
  assert.deepEqual(await f.page.evaluate(() => sounds), ['success']);
  f.setMode('reject');
  await f.page.evaluate(async () => { document.querySelector('#scanTruckBlCode').value = 'QA-FOREIGN'; await WmsTruckScan.scanBl(); });
  assert.deepEqual(await f.page.evaluate(() => sounds), ['success', 'error']);
});
