// Offline DOM/bridge contract tests. All data is synthetic; no server is started.
const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const template = fs.readFileSync(path.join(root, 'frontend/templates/reception.html'), 'utf8');
const source = fs.readFileSync(path.join(root, 'frontend/static/reception-np-scan.js'), 'utf8');
const integration = template.split('\n').find(line => line.includes('WmsNpScan.init({'));
const styles = template.match(/<style>([\s\S]*?)<\/style>/)[1] + '\n' +
  ['wms-ui.css', 'reception-work.css', 'reader-ui.css'].map(name =>
    fs.readFileSync(path.join(root, 'frontend/static', name), 'utf8')).join('\n');
let browser;
before(async () => { browser = await chromium.launch({headless: true, channel: 'msedge'}); });
after(async () => { await browser?.close(); });

async function fixture(t, options = {}, viewport = {width: 393, height: 873}) {
  const context = await browser.newContext({viewport, serviceWorkers: 'block'});
  t.after(() => context.close());
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await context.route('**/*', route => route.abort());
  const lines = Array.from({length: 10}, (_, i) => ({id: i + 1, attention_id: 7,
    np_code: 'QA-NP-' + (i + 1), description: 'Repuesto sintetico', ov_number: 'QA-OV-' + (i + 1),
    ip_reference: 'QA-IP', attention_planned_qty: 5, expected_qty: 5, received_qty: 5,
    attention_verified_qty: 5, np_scanned_at: '2026-10-20 10:00:00',
    np_unreceived_reason: '', blocked_reason: '', final_location: 'QA-A',
    count_location_saved: true, ...options.lines?.[i]}));
  await page.setContent('<!doctype html><html lang="es"><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width,initial-scale=1"><style>' + styles +
    '</style><body class="reader-ui"><main class="content" id="content"></main>' +
    '<div id="notices" role="status"></div></body></html>');
  await page.addScriptTag({content: source});
  await page.addScriptTag({content: `
    let selected = ${JSON.stringify({id: 5, attention_id: 7, app_status: options.status || 'REVISION SISTEMA', lines})};
    let selectedId = 5, selectedAttentionId = 7, admin = ${options.admin !== false};
    let server = structuredClone(selected), calls = [], confirmations = [], notices = [];
    let accept = true, responseMode = 'ok', responseOverride = null, release;
    let sounds = [], arms = 0;
    window.WmsScanFeedback = {arm() { arms++; }, success() { sounds.push('success'); }, error() { sounds.push('error'); }};
    function isAdmin() { return admin; }
    function panelEditable() { return true; }
    function shipmentUrl(suffix) { return '/api/receptions/' + selectedId + suffix; }
    function defaultLocationLabel() { return 'QA-A'; }
    function countLocationValue(line) { return line.final_location; }
    function notify(text, level) { notices.push({text, level}); document.querySelector('#notices').textContent = text; }
    window.confirm = text => { confirmations.push(text); return accept; };
    async function api(url, options) {
      // Match the real template helper's attention injection for object bodies.
      const bodyType = typeof options.body;
      const body = bodyType === 'string' ? JSON.parse(options.body) : {...options.body, attention_id: selectedAttentionId};
      calls.push({url, body, bodyType});
      if (responseMode === 'hold') await new Promise(resolve => { release = resolve; });
      if (responseMode === 'invalid-json') return {ok: false, json: async () => { throw Error('QA unavailable'); }};
      if (responseMode === 'rejected') return {ok: false, json: async () => ({error: 'QA stale quantity'})};
      if (url.endsWith('/count/partial')) server.app_status = 'EM';
      else {
        const line = server.lines.find(item => String(item.id) === url.split('/').at(-1));
        line.attention_verified_qty = line.received_qty = body.received_qty;
        line.blocked_reason = body.reason;
        if (body.scan_np) line.np_scanned_at ||= '2026-10-20 11:00:00';
        line.np_unreceived_reason = body.defer_np ? 'CORRECCION ADMIN NP: ' + body.reason : '';
        if ('count_location' in body) line.final_location = body.count_location;
      }
      const data = responseOverride || structuredClone(server);
      return {ok: true, json: async () => data};
    }
    function applyPartialNpCount(data, context) { if (context.isCurrent()) { selected = data; mount(); } }
    ${integration}
    function mount() {
      const legacy = selected.lines.map(line => '<div><input id="qty-' + line.id + '" type="number"' + (line.readonly ? ' readonly' : '') + ' value="' +
        (line.attention_verified_qty ?? line.expected_qty) + '"><input id="reason-' + line.id + '" value="' +
        line.blocked_reason + '"><input id="count-location-' + line.id + '" value="' + line.final_location +
        '"><span id="diff-' + line.id + '"></span></div>').join('');
      document.querySelector('#content').innerHTML = WmsNpScan.render(selected, legacy);
    }
    function handleReceptionNpScan(event) { return WmsNpScan.handle(event); }
    mount();
  `});
  t.after(() => assert.deepEqual(errors, [], 'No browser script errors'));
  return page;
}

async function review(page, code = 'QA-NP-10') { await page.evaluate(code => WmsNpScan.review(code), code); }
async function deferButton(page) {
  const button = page.getByRole('button', {name: 'No recibido en esta entrega', exact: true});
  assert.equal(await button.count(), 1, 'Admin correction must expose the explicit defer action');
  return button;
}
async function defer(page, reason = 'No llego en esta entrega') {
  await page.locator('#receptionNpReason').fill(reason);
  const button = await deferButton(page);
  await button.click();
  await page.waitForFunction(() => !WmsNpScan.hasPending());
}

test('admin defers the chosen scanned row using SERVER quantity and fixed numeric attention', async t => {
  const page = await fixture(t);
  await page.evaluate(() => {
    document.querySelector('#qty-10').value = '99';
    document.querySelector('#qty-2').value = '23';
    document.querySelector('#reason-2').value = 'Borrador ajeno';
    document.querySelector('#count-location-2').value = 'QA-draft';
  });
  await review(page);
  await page.locator('#receptionNpQuantity').fill('88');
  await defer(page);
  const state = await page.evaluate(() => ({calls, confirmations, line: selected.lines[9]}));
  assert.equal(state.calls.length, 1);
  assert.equal(state.calls[0].url, '/api/receptions/5/lines/10');
  assert.equal(state.calls[0].bodyType, 'string');
  assert.deepEqual(state.calls[0].body, {received_qty: 0, reason: 'No llego en esta entrega',
    defer_np: true, confirmed: true, previous_received_qty: 5, attention_id: 7});
  assert.equal(state.confirmations.length, 1);
  assert.match(state.confirmations[0], /QA-NP-10/);
  assert.equal(state.line.attention_verified_qty, 0);
  assert.equal(state.line.received_qty, 0);
  assert.match(state.line.np_unreceived_reason, /^CORRECCION ADMIN NP:/);
  assert.equal(state.line.np_scanned_at, '2026-10-20 10:00:00');
  assert.equal(await page.locator('#qty-2').inputValue(), '23');
  assert.equal(await page.locator('#reason-2').inputValue(), 'Borrador ajeno');
  assert.equal(await page.locator('#count-location-2').inputValue(), 'QA-draft');
  assert.equal(await page.locator('#receptionNpProgress').innerText(), 'NP leidos: 9/10');
  assert.equal(await page.getByRole('button', {name: 'Finalizar conteo de esta entrega', exact: true}).isVisible(), true);
});

test('reason validation, cancellation and duplicate clicks never cause an extra POST', async t => {
  const page = await fixture(t); await review(page);
  await page.locator('#receptionNpReason').fill('corto');
  await (await deferButton(page)).click();
  assert.equal(await page.evaluate(() => calls.length), 0);
  assert.equal(await page.evaluate(() => document.activeElement.id), 'receptionNpReason');
  await page.locator('#receptionNpReason').fill('Motivo confirmado');
  await page.evaluate(() => { accept = false; });
  await (await deferButton(page)).click();
  assert.equal(await page.evaluate(() => calls.length), 0);
  await page.evaluate(() => { accept = true; responseMode = 'hold'; });
  await (await deferButton(page)).click();
  await page.evaluate(() => WmsNpScan.defer());
  assert.equal(await page.evaluate(() => calls.length), 1);
  await page.evaluate(() => { responseMode = 'ok'; release(); });
  await page.waitForFunction(() => !WmsNpScan.hasPending());
});

for (const mode of ['invalid-json', 'rejected', 'wrong-attention', 'missing-line']) {
  test(mode + ' preserves correction quantity/reason and unrelated drafts for explicit retry', async t => {
    const page = await fixture(t); await review(page);
    await page.locator('#receptionNpQuantity').fill('17');
    await page.evaluate(mode => {
      document.querySelector('#qty-2').value = '42';
      responseMode = mode;
      if (mode === 'wrong-attention') responseOverride = {...server, attention_id: 8};
      if (mode === 'missing-line') responseOverride = {...server, lines: []};
    }, mode);
    await defer(page, 'Motivo que debo conservar');
    assert.equal(await page.locator('#receptionNpQuantity').inputValue(), '17');
    assert.equal(await page.locator('#receptionNpReason').inputValue(), 'Motivo que debo conservar');
    assert.equal(await page.locator('#qty-2').inputValue(), '42');
    assert.equal(await page.evaluate(() => selected.lines[9].attention_verified_qty), 5);
    assert.equal(await (await deferButton(page)).isEnabled(), true);
    await page.evaluate(() => { responseMode = 'ok'; responseOverride = null; });
    await (await deferButton(page)).click();
    await page.waitForFunction(() => !WmsNpScan.hasPending());
    assert.equal(await page.evaluate(() => calls.length), 2);
  });
}

test('only admin at system review with a saved scan can defer; workers cannot restore admin deferrals', async t => {
  for (const options of [{admin: false}, {status: 'EM'}, {lines: {9: {np_scanned_at: null}}}]) {
    const page = await fixture(t, options); await review(page);
    assert.equal(await page.getByRole('button', {name: 'No recibido en esta entrega', exact: true}).count(), 0);
  }
  const page = await fixture(t, {admin: false, lines: {9: {attention_verified_qty: 0,
    received_qty: 0, np_unreceived_reason: 'CORRECCION ADMIN NP: No llego'}}});
  await review(page);
  assert.equal(await page.locator('#receptionNpQuantity').count(), 0);
  await page.evaluate(() => WmsNpScan.save());
  assert.equal(await page.evaluate(() => calls.length), 0);
});

test('restoring normally uses server fields and updates the next correction quantity', async t => {
  const page = await fixture(t); await review(page); await defer(page);
  await review(page);
  assert.equal(await page.locator('#receptionNpQuantity').inputValue(), '0');
  await page.locator('#receptionNpQuantity').fill('3');
  await page.locator('#receptionNpSave').click();
  await page.waitForFunction(() => !WmsNpScan.hasPending());
  assert.equal(await page.evaluate(() => selected.lines[9].attention_verified_qty), 3);
  assert.equal(await page.evaluate(() => selected.lines[9].np_unreceived_reason), '');
  assert.match(await page.locator('#receptionNpProgress').innerText(), /10\/10/);
  await review(page); await defer(page);
  assert.equal(await page.evaluate(() => calls.at(-1).body.previous_received_qty), 3);
});

test('reload of a historical scan corrected to zero offers partial finalization with empty IDs', async t => {
  const page = await fixture(t, {lines: {9: {attention_verified_qty: 0, received_qty: 0,
    np_unreceived_reason: 'CORRECCION ADMIN NP: No llego'}}});
  assert.equal(await page.locator('#receptionNpProgress').innerText(), 'NP leidos: 9/10');
  await page.getByRole('button', {name: 'Finalizar conteo de esta entrega', exact: true}).click({timeout: 1500});
  await page.waitForFunction(() => !WmsNpScan.hasPending());
  assert.deepEqual(await page.evaluate(() => calls.map(call => ({url: call.url, body: call.body}))),
    [{url: '/api/receptions/5/count/partial', body: {confirmed: true, attention_id: 7, line_ids: []}}]);
  assert.equal(await page.evaluate(() => selected.app_status), 'EM');
  assert.match(await page.evaluate(() => confirmations[0]), /EM/);
});

test('a historical zero quantity never counts as a received NP even without a saved reason', async t => {
  const page = await fixture(t, {lines: {9: {attention_verified_qty: 0, received_qty: 0}}});
  assert.equal(await page.locator('#receptionNpProgress').innerText(), 'NP leidos: 9/10');
  await review(page);
  assert.equal(await (await deferButton(page)).isVisible(), true);
});

test('cumulative counter retains prior reads and current readonly confirmed rows', async t => {
  const page = await fixture(t);
  await page.evaluate(() => {
    selected.np_progress = {read: 10, total: 10};
    selected.lines.forEach((line, index) => {
      line.np_total_expected_qty = 5;
      line.np_previous_scanned = index < 9;
      if (index < 9) line.attention_planned_qty = 0;
    });
    selected.lines[9].readonly = true;
    mount();
  });
  assert.equal(await page.locator('#receptionNpProgress').innerText(), 'NP leidos: 10/10');
  await page.evaluate(() => { selected.lines[9].attention_verified_qty=0; selected.lines[9].np_unreceived_reason='CORRECCION ADMIN NP: No llego'; mount(); });
  assert.equal(await page.locator('#receptionNpProgress').innerText(), 'NP leidos: 9/10');
});

test('38 completed NP from another arrival never block saving the last of 39', async t => {
  const page = await fixture(t);
  await page.evaluate(() => {
    selected.np_progress = {read: 38, total: 39};
    selected.lines = Array.from({length: 39}, (_, i) => ({...selected.lines[0], id: i + 1,
      np_code: 'QA-NP-' + (i + 1), np_scanned_at: null, np_total_expected_qty: 5,
      np_previous_scanned: i < 38, np_count_covered_elsewhere: i < 38}));
    server = structuredClone(selected); mount();
  });
  assert.equal(await page.locator('#receptionNpProgress').innerText(), 'NP leidos: 38/39');
  assert.equal(await page.evaluate(() => WmsNpScan.canComplete()), false);
  await scan(page, 'QA-NP-39');
  await page.waitForFunction(() => !WmsNpScan.hasPending());
  assert.equal(await page.locator('#receptionNpProgress').innerText(), 'NP leidos: 39/39');
  assert.equal(await page.evaluate(() => WmsNpScan.canComplete()), true);
  assert.equal(await page.getByRole('button', {name:'Finalizar conteo de esta entrega',exact:true}).isVisible(), false);
  assert.equal(await page.evaluate(() => calls.length), 1);
  await page.evaluate(() => { selected = structuredClone(server); mount(); });
  assert.equal(await page.evaluate(() => WmsNpScan.canComplete()), true);
  await scan(page, 'QA-NP-1');
  assert.equal(await page.evaluate(() => calls.length), 1, 'A completed source order cannot register again');
});

test('reopening authoritative detail clears a prior-coverage warning without losing valid reads', async t => {
  const page = await fixture(t,{lines:{9:{np_scanned_at:null}}});
  await page.evaluate(() => {
    selected.np_progress={read:9,total:10};
    selected.lines.forEach((line,i)=>{line.np_count_covered_elsewhere=i<9;line.np_previous_scanned=i<9;line.np_total_expected_qty=5;});
    server=structuredClone(selected);server.lines[0].np_count_covered_elsewhere=false;
    mount();
  });
  await scan(page,'QA-NP-10');await page.waitForFunction(()=>!WmsNpScan.hasPending());
  assert.equal(await page.evaluate(()=>WmsNpScan.canComplete()),false);
  await page.evaluate(()=>{selected=structuredClone(server);mount();});
  assert.equal(await page.evaluate(()=>WmsNpScan.canComplete()),true);
});

test('fresh server flags can revoke a prior attention read without replacing quantity drafts', async t => {
  const page = await fixture(t, {lines:{9:{np_scanned_at:null}}});
  await page.evaluate(() => {
    selected.np_progress = {read:9,total:10};
    selected.lines.forEach((line,index) => {
      line.np_total_expected_qty=5;
      line.np_previous_scanned=index<9;
      if(index<9) {
        line.attention_planned_qty=0; line.attention_verified_qty=0;
        line.received_qty=0; line.np_scanned_at=null;
      }
    });
    server=structuredClone(selected);
    server.lines[0].np_previous_scanned=false;
    server.lines[0].np_scanned_at=null;
    mount();
    document.querySelector('#qty-2').value='23';
  });
  assert.equal(await page.locator('#receptionNpProgress').innerText(),'NP leidos: 9/10');
  await page.locator('#scanReceptionNp').fill('QA-NP-10');
  await page.locator('#scanReceptionNp').press('Enter');
  await page.waitForFunction(()=>!WmsNpScan.hasPending());
  assert.equal(await page.locator('#receptionNpProgress').innerText(),'NP leidos: 9/10');
  assert.equal(await page.locator('#qty-2').inputValue(),'23');
});

test('partial count still sends every unread order, including distinct OV sharing an NP', async t => {
  const page = await fixture(t, {lines: {8: {np_code: 'QA-NP-10', np_scanned_at: null, attention_verified_qty: 0},
    9: {np_scanned_at: null, attention_verified_qty: 0}}});
  await page.evaluate(() => WmsNpScan.continuePartial());
  assert.deepEqual(await page.evaluate(() => calls[0].body.line_ids), [9, 10]);
});

test('failed automatic scan queue cannot be consumed by an admin correction', async t => {
  const page = await fixture(t, {lines: {0: {np_scanned_at: null, attention_verified_qty: 0}}});
  await page.evaluate(async () => {
    responseMode = 'rejected';
    const input = document.querySelector('#scanReceptionNp'); input.value = 'QA-NP-1';
    await WmsNpScan.handle({key: 'Enter', currentTarget: input, preventDefault() {}});
    WmsNpScan.review('QA-NP-10');
  });
  assert.equal(await page.evaluate(() => WmsNpScan.status().queueLength), 1);
  assert.equal(await page.evaluate(() => calls.length), 1);
  await page.evaluate(async () => { responseMode = 'ok'; await WmsNpScan.retry(); });
  assert.equal(await page.evaluate(() => WmsNpScan.status().queueLength), 0);
});

test('a late correction response cannot apply to another attention', async t => {
  const page = await fixture(t); await review(page);
  await page.evaluate(() => { responseMode = 'hold'; });
  await page.locator('#receptionNpReason').fill('No llego el repuesto');
  await (await deferButton(page)).click();
  await page.evaluate(() => { selectedAttentionId = 8; responseMode = 'ok'; release(); });
  await page.waitForFunction(() => !WmsNpScan.hasPending());
  assert.equal(await page.evaluate(() => selected.lines[9].attention_verified_qty), 5);
  assert.equal(await page.locator('#receptionNpReason').inputValue(), 'No llego el repuesto');
});

async function scan(page, code) {
  await page.locator('#scanReceptionNp').fill(code);
  await page.locator('#scanReceptionNp').press('Enter');
}

test('NP sound waits for the confirmed save, then flags a repeated read without another POST', async t => {
  const page = await fixture(t, {lines: {0: {np_scanned_at: null}}});
  await page.evaluate(() => {
    responseMode = 'hold';
    const input = document.querySelector('#scanReceptionNp'); input.value = 'QA-NP-1';
    window.pendingScan = WmsNpScan.handle({key: 'Enter', currentTarget: input, preventDefault() {}});
  });
  await page.waitForFunction(() => calls.length === 1);
  assert.deepEqual(await page.evaluate(() => sounds), []);
  assert.equal(await page.evaluate(() => arms), 1);
  await page.evaluate(() => { responseMode = 'ok'; release(); });
  await page.waitForFunction(() => !WmsNpScan.hasPending());
  assert.deepEqual(await page.evaluate(() => sounds), ['success']);
  await scan(page, 'QA-NP-1');
  await page.waitForFunction(() => !WmsNpScan.hasPending());
  assert.deepEqual(await page.evaluate(() => sounds), ['success', 'error']);
  assert.equal(await page.evaluate(() => calls.length), 1);
});

test('NP rejected, foreign and ambiguous codes sound error, not success', async t => {
  for (const mode of ['rejected', 'invalid-json', 'wrong-attention', 'foreign', 'choice']) {
    const page = await fixture(t, {lines: {0: {np_scanned_at: null, attention_verified_qty: 0},
      ...(mode === 'choice' ? {1: {np_code: 'QA-NP-1', np_scanned_at: null, attention_verified_qty: 0}} : {})}});
    await page.evaluate(mode => {
      responseMode = mode;
      if (mode === 'wrong-attention') responseOverride = {...server, attention_id: 8};
    }, mode);
    await scan(page, mode === 'foreign' ? 'QA-FOREIGN' : 'QA-NP-1');
    await page.waitForFunction(() => ['error', 'choice'].includes(WmsNpScan.status().phase));
    assert.deepEqual(await page.evaluate(() => sounds), ['error'], mode);
  }
});

test('NP stale response and manual corrections never sound as new successful scans', async t => {
  const manual = await fixture(t);
  await review(manual); await defer(manual);
  assert.deepEqual(await manual.evaluate(() => sounds), []);
  const page = await fixture(t, {lines: {0: {np_scanned_at: null}}});
  await page.evaluate(() => {
    responseMode = 'hold';
    const input = document.querySelector('#scanReceptionNp'); input.value = 'QA-NP-1';
    window.pendingScan = WmsNpScan.handle({key: 'Enter', currentTarget: input, preventDefault() {}});
  });
  await page.waitForFunction(() => calls.length === 1);
  await page.evaluate(async () => { selectedAttentionId = 8; responseMode = 'ok'; release(); await window.pendingScan; });
  assert.deepEqual(await page.evaluate(() => sounds), []);
});

test('NP camera result has one confirmed sound and cannot sound for a stale callback', async t => {
  const page = await fixture(t, {lines: {0: {np_scanned_at: null}}});
  await page.evaluate(async () => {
    const context = WmsNpScan.status().context;
    await WmsNpScan.receiveCamera('QA-NP-1', {...context, viewId: context.viewId + 1});
    await WmsNpScan.receiveCamera('QA-NP-1', context);
  });
  assert.equal(await page.evaluate(() => calls.length), 1);
  assert.deepEqual(await page.evaluate(() => sounds), ['success']);
});

for (const [width, height] of [[320, 640], [393, 873], [1366, 768], [873, 393]]) {
  test('correction and finalization reflow with reachable controls at ' + width, async t => {
    const page = await fixture(t, {}, {width, height}); await review(page);
    const button = await deferButton(page);
    await button.scrollIntoViewIfNeeded();
    const box = await button.boundingBox();
    assert(box.height >= 44 && box.x >= 0 && box.x + box.width <= width + 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    await defer(page);
    const finish = page.getByRole('button', {name: 'Finalizar conteo de esta entrega', exact: true});
    await finish.scrollIntoViewIfNeeded();
    const finishBox = await finish.boundingBox(); assert(finishBox.height >= 44);
    if (process.env.NP_QA_SCREENSHOTS) await page.screenshot({path: path.join(process.env.NP_QA_SCREENSHOTS, 'partial-' + width + '.png'), fullPage: true});
    await finish.click(); await page.waitForFunction(() => selected.app_status === 'EM');
  });
}

test('admin correction and finish labels fit with 200 percent text at 320px', async t => {
  const page = await fixture(t, {}, {width: 320, height: 740}); await review(page);
  await page.addStyleTag({content: '#receptionNpScanPanel button{font-size:28px!important;line-height:1.3!important}'});
  const clipped = await page.locator('#receptionNpScanPanel button:visible').evaluateAll(nodes =>
    nodes.filter(node => node.scrollHeight > node.clientHeight + 1).map(node => node.textContent));
  assert.deepEqual(clipped, [], 'Button labels must reflow instead of clipping');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
});
