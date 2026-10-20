// Only support_partial_count_server.py, never production.
const {chromium} = require('playwright');
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const base = process.argv[2];
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '')) throw Error('Disposable loopback fixture required');
(async () => {
  const browser = await chromium.launch({headless: true, channel: 'msedge'});
  try {
    for (const [index, viewport] of [{width:320,height:740},{width:393,height:873},
      {width:1366,height:900},{width:873,height:393}].entries()) {
      const page = await browser.newPage({viewport}), errors = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('dialog', dialog => dialog.accept());
      await page.goto(base + '/reception');
      await page.waitForFunction(() => typeof loadDetail === 'function');
      const state = await page.evaluate(async number => {
        const rows = await (await api('/api/receptions?search=QA-PARTIAL-' + number)).json();
        await loadDetail(rows.find(row => row.bl_awb === 'QA-PARTIAL-' + number).id);
        return {id:selected.id, attention:selected.attention_id, packages:selected.received_packages};
      }, index + 9);
      for (let number = 0; number < 10; number++) {
        await page.locator('#scanReceptionNp').fill('NP-' + String(number).padStart(2, '0'));
        await page.locator('#scanReceptionNp').press('Enter');
        await page.waitForFunction(() => !WmsNpScan.hasPending());
      }
      assert.match(await page.locator('#receptionNpProgress').innerText(), /10\/10/);
      await page.evaluate(() => WmsNpScan.review('NP-09'));
      await page.locator('#receptionNpReason').fill('QA physical inspection: not received in this arrival');
      const correctionUrl = '**/api/receptions/' + state.id + '/lines/*';
      await page.route(correctionUrl, route => route.fulfill({status:503, contentType:'application/json',
        body:JSON.stringify({error:'QA transient failure'})}), {times:1});
      await page.locator('#receptionNpDefer').click();
      await page.waitForFunction(() => !WmsNpScan.hasPending());
      assert.match(await page.locator('#receptionNpProgress').innerText(), /10\/10/);
      assert.match(await page.locator('#receptionNpReason').inputValue(), /physical inspection/);
      let corrections = 0;
      page.on('request', request => { if (request.method() === 'POST' &&
        request.url().includes('/api/receptions/' + state.id + '/lines/')) corrections++; });
      await page.evaluate(() => { WmsNpScan.defer(); WmsNpScan.defer(); });
      await page.waitForFunction(() => !WmsNpScan.hasPending());
      assert.equal(corrections, 1);
      assert.match(await page.locator('#receptionNpProgress').innerText(), /9\/10.*No recibidos: 1/);
      const deferred = await page.evaluate(() => selected.lines.find(line => line.np_code === 'NP-09'));
      assert.equal(deferred.attention_verified_qty, 0);
      assert(deferred.np_scanned_at, 'Original scan must remain evidence');
      assert.match(deferred.np_unreceived_reason, /^CORRECCION ADMIN NP:/);
      const output = path.join(__dirname, '../qa/runtime/np-partial-corrections'); fs.mkdirSync(output, {recursive:true});
      await page.locator('#receptionNpPartial').scrollIntoViewIfNeeded();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      await page.screenshot({path:path.join(output, 'count-' + viewport.width + '.png'), fullPage:true});
      await page.locator('#receptionNpPartial').click();
      await page.waitForFunction(() => selected?.app_status === 'EM');
      assert.equal(await page.evaluate(() => selected.received_packages), state.packages);
      await page.evaluate(async () => {
        const response = await api(shipmentUrl('/rewind'), {method:'POST', body:{
          status:'REVISION SISTEMA', reason:'QA reopen without restoring the planned quantity'}});
        const data = await response.json(); if (!response.ok) throw Error(data.error);
        selected = data; selectedAttentionId = data.attention_id; renderDetail();
      });
      assert.match(await page.locator('#receptionNpProgress').innerText(), /9\/10/);
      assert.equal(await page.evaluate(() => selected.lines.find(line => line.np_code === 'NP-09').attention_verified_qty), 0);
      assert.equal(await page.evaluate(() => selected.received_packages), state.packages);
      assert.deepEqual(errors, []);
      await page.close();
      console.log('OK real backend: admin correction,503,double click,9/10,partial EM,reopen,unchanged packages ' + viewport.width);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
