// In-memory, synthetic HTTP responses only: no application server or database.
const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '..');
const base = 'http://127.0.0.1:51987';
const trucks = ['QA-FIRST', 'QA-SECOND', 'QA-LATEST'];
const attentions = [801, 802].map((id, index) => ({
  id, receipt_id: 901 + index, sequence_no: index + 1,
  label: `Atencion QA ${index + 1}`, app_status: 'ARRIBADO', lines: []
}));
function detail(attentionId) {
  const guide = {801: 'QA-FIRST', 802: 'QA-SECOND'}[attentionId] || '';
  return {
    id: 701, bl_awb: 'QA-NAV-PARTIAL', app_status: 'ARRIBADO',
    condition_status: 'PARCIAL', expected_packages: 5, received_packages: 2,
    current_assistant: 'qa.navigation', current_auxiliary: 'qa.navigation',
    truck_guide: 'QA-LATEST', guide_status: 'PENDIENTE',
    selected_attention_truck_guide: guide,
    selected_attention_guide_status: guide ? 'LISTA_PARA_CONTEO' : '',
    attention_id: attentionId, active_attention_id: attentionId,
    active_attention_sequence: attentionId === 802 ? 2 : 1, attention_count: 2,
    attentions, lines: [], accounting_refs: [], lots: [],
    truck_plans: trucks.map(truck_guide => ({truck_guide})),
    truck_arrivals: [], linked_truck_guides: trucks.join(','),
    receipts: attentions.map((attention, index) => ({
      id: attention.receipt_id, sequence_no: index + 1,
      attention_sequence: index + 1, truck_guide: trucks[index],
      received_packages: 1, location_text: 'QA-ZONE', received_at: '2026-10-19',
      username: 'qa.navigation', notes: ''
    }))
  };
}

let browser;
before(async () => {
  browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
    ? {executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH} : {channel: 'msedge'})});
});
after(async () => {await browser?.close();});

async function fixture(t, {width = 1366, height = 768, orphan = false, legacy = false} = {}) {
  const context = await browser.newContext({viewport: {width, height}, serviceWorkers: 'block'});
  t.after(() => context.close());
  const page = await context.newPage();
  const errors = [], writes = [], reads = [];
  page.on('pageerror', error => errors.push(error.message));
  t.after(() => {
    assert.deepEqual(errors, [], 'No browser exceptions');
    assert.deepEqual(writes, [], 'Navigation must not send mutations');
  });
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    assert.equal(url.origin, base, 'All requests stay inside the disposable fixture');
    const json = body => route.fulfill({json: body});
    if (request.method() !== 'GET') {
      writes.push(request.method() + ' ' + url.pathname);
      return route.fulfill({status: 405, json: {error: 'Navigation cannot write'}});
    }
    if (url.pathname === '/reception') return route.fulfill({
      contentType: 'text/html', body: fs.readFileSync(path.join(root, 'frontend/templates/reception.html'))
    });
    if (url.pathname.startsWith('/assets/')) {
      const filename = path.basename(url.pathname);
      const file = path.join(root, 'frontend/static', filename);
      if (fs.existsSync(file)) return route.fulfill({path: file});
      return route.fulfill({status: 204, body: ''});
    }
    if (url.pathname === '/api/me' || url.pathname === '/api/account') {
      return json({username: 'qa.navigation', display_name: 'QA Navigation',
        mode: 'demo', role: 'ADMINISTRADOR', show_guidance: true});
    }
    if (url.pathname === '/api/truck-guides') return json([]);
    if (url.pathname === '/api/receptions') return json([]);
    if (url.pathname === '/api/assignees') return json({users: []});
    if (url.pathname === '/api/receptions/701') {
      const payload = detail(Number(url.searchParams.get('attention_id')) || 801);
      if (orphan) Object.assign(payload, {selected_attention_truck_guide: '',
        selected_attention_guide_status: '', truck_plans: [], truck_arrivals: [],
        linked_truck_guides: '', receipts: []});
      if (legacy) {
        delete payload.selected_attention_truck_guide;
        delete payload.selected_attention_guide_status;
      }
      return json(payload);
    }
    if (url.pathname === '/api/receptions/truck-guide') {
      const guide = url.searchParams.get('truck_guide');
      reads.push(guide);
      return json({truck_guide: guide, guide_status: 'LISTA_PARA_CONTEO',
        scanner_enabled: true, is_confirmed: 1, bls: []});
    }
    if (url.pathname.startsWith('/api/')) return json({});
    return route.fulfill({status: 204, body: ''});
  });
  await page.goto(base + '/reception');
  await page.waitForFunction(() => Boolean(window.WmsTruckNavigation) &&
    document.querySelector('.home-welcome'));
  return {page, reads};
}

test('BL queue returns to the selected attention truck, not the shared latest pointer', async t => {
  const {page, reads} = await fixture(t);
  await page.evaluate(() => loadDetail(701, true, 801));
  assert.equal(await page.locator('#content .back-btn').getAttribute('data-open-truck'), 'QA-FIRST');
  await page.locator('#content .back-btn').click();
  await page.locator('#content [data-truck-guide="QA-FIRST"]').waitFor();
  assert.deepEqual(reads, ['QA-FIRST']);
  assert.deepEqual(await page.evaluate(() => [selectedId, selectedAttentionId]), [null, null]);
});

test('changing attention on the same BL replaces the previous truck origin', async t => {
  const {page} = await fixture(t);
  await page.evaluate(async () => {
    await openTruckGuideFromBl('QA-SECOND');
    await loadDetail(701, true, 802);
    await loadDetail(701, true, 801);
  });
  assert.equal(await page.locator('#content .back-btn').getAttribute('data-open-truck'), 'QA-FIRST');
});

test('an unrelated visible truck cannot override the selected attention origin', async t => {
  const {page} = await fixture(t);
  await page.evaluate(async () => {
    await openTruckGuideFromBl('QA-LATEST');
    await loadDetail(701, true, 801);
  });
  assert.equal(await page.locator('#content .back-btn').getAttribute('data-open-truck'), 'QA-FIRST');
});

test('administrative truck controls use the selected truck and its own stage', async t => {
  const {page} = await fixture(t);
  await page.evaluate(() => loadDetail(701, true, 801));
  const open = page.getByRole('button', {name: /Abrir gu.a de cami.n/, exact: true});
  assert.match(await open.getAttribute('onclick'), /QA-FIRST/);
  assert.ok((await page.locator('#truckRevertStage option').allTextContents()).length > 0,
    'A completed selected truck exposes its correction stages');
  assert.equal(await page.locator('#truckRevertStage option[value="ZONA_RECEPCION"]').count(), 1);
  assert.equal(await page.evaluate(() => selected.truck_guide), 'QA-LATEST', 'Shared pointer stays intact');
});

test('legacy detail resolves an attention through its receipt instead of the shared pointer', async t => {
  const {page} = await fixture(t, {legacy: true});
  await page.evaluate(() => loadDetail(701, true, 801));
  assert.equal(await page.locator('#content .back-btn').getAttribute('data-open-truck'), 'QA-FIRST');
});

test('worker arrival guidance names the selected attention truck', async t => {
  const {page} = await fixture(t);
  await page.evaluate(async () => {
    $('role').value = 'AUXILIAR_RECEPCION';
    await loadDetail(701, true, 801);
  });
  assert.match(await page.locator('[data-reception-panel="zona"] .notice').textContent(), /QA-FIRST/);
  assert.doesNotMatch(await page.locator('[data-reception-panel="zona"] .notice').textContent(), /QA-LATEST/);
});

test('canceling unsaved navigation preserves the attention, draft and truck selector', async t => {
  const {page, reads} = await fixture(t);
  await page.evaluate(async () => {
    await openTruckGuideFromBl('QA-FIRST');
    await loadDetail(701, true, 801);
  });
  await page.locator('#receipt-location-901').fill('QA-UNSAVED');
  const before = await page.evaluate(() => ({id: selectedId, attention: selectedAttentionId,
    guide: $('truckGuideFilter').value, continuity: window.getReceptionContinuityState()}));
  page.once('dialog', dialog => dialog.dismiss());
  await page.locator('#content nav[aria-label="Camiones de la BL"] [data-open-truck="QA-SECOND"]').click();
  assert.deepEqual(await page.evaluate(() => ({id: selectedId, attention: selectedAttentionId,
    guide: $('truckGuideFilter').value, continuity: window.getReceptionContinuityState()})), before);
  assert.equal(await page.locator('#receipt-location-901').inputValue(), 'QA-UNSAVED');
  assert.deepEqual(reads, ['QA-FIRST']);
  page.once('dialog', dialog => dialog.accept());
  await page.locator('#content .back-btn').click();
  await page.locator('#content [data-truck-guide="QA-FIRST"]').waitFor();
  assert.deepEqual(reads, ['QA-FIRST', 'QA-FIRST']);
});

test('an orphan attention returns to the BL list despite a stale shared truck pointer', async t => {
  const {page, reads} = await fixture(t, {orphan: true});
  await page.evaluate(async () => {
    await openTruckGuideFromBl('QA-FIRST');
    await loadDetail(701, true, 803);
  });
  assert.equal(await page.locator('#content .back-btn').getAttribute('data-open-truck'), null);
  await page.locator('#content .back-btn').click();
  assert.equal(await page.locator('.queue').evaluate(node => node.classList.contains('open')), true);
  assert.deepEqual(reads, ['QA-FIRST']);
});

test('continuity restoration cannot replace the selected attention origin with a stale truck', async t => {
  const {page} = await fixture(t);
  await page.evaluate(() => window.restoreReceptionContinuity({shipmentId: 701,
    attentionId: 801, originTruckGuide: 'QA-SECOND'}));
  assert.equal(await page.locator('#content .back-btn').getAttribute('data-open-truck'), 'QA-FIRST');
});

for (const viewport of [
  {width: 320, height: 640}, {width: 375, height: 812}, {width: 393, height: 873},
  {width: 768, height: 1024}, {width: 820, height: 900}, {width: 821, height: 900},
  {width: 1366, height: 768}, {width: 1440, height: 900}, {width: 873, height: 393}
]) {
  test(`selected attention return is reachable at ${viewport.width}x${viewport.height}`, async t => {
    const {page} = await fixture(t, viewport);
    await page.evaluate(() => loadDetail(701, false, 802));
    assert.equal(await page.locator('#content .back-btn').getAttribute('data-open-truck'), 'QA-SECOND');
    assert.equal(await page.locator('#content .back-btn').isVisible(), true);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    await page.locator('#content .back-btn').click();
    await page.locator('#content [data-truck-guide="QA-SECOND"]').waitFor();
  });
}
