// Disposable loopback fixture: real label engine, no WMS database or private assets.
const assert = require('node:assert/strict'), fs = require('node:fs');
const http = require('node:http'), path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'qa', 'label-order-text');
const assets = {
  '/assets/reception-labels.js': ['reception-labels.js', 'text/javascript'],
  '/assets/reception-labels.css': ['reception-labels.css', 'text/css'],
  '/assets/bwip-js-min.js': ['bwip-js-min.js', 'text/javascript'],
};
let savedDetail, detailRequests = 0, detailUnavailable = false;
const server = http.createServer((request, response) => {
  const asset = assets[new URL(request.url, 'http://127.0.0.1').pathname];
  if (asset) {
    response.writeHead(200, {'Content-Type': asset[1]});
    response.end(fs.readFileSync(path.join(root, 'frontend/static', asset[0])));
  } else if (request.url === '/api/receptions/1?attention_id=7') {
    detailRequests++;
    response.writeHead(detailUnavailable ? 503 : 200, {'Content-Type':'application/json', 'Cache-Control':'no-store'});
    response.end(JSON.stringify(detailUnavailable ? {error:'No se pudo verificar la etiqueta.'} : savedDetail));
  } else if (request.url === '/') {
    response.writeHead(200, {'Content-Type': 'text/html; charset=utf-8'});
    response.end('<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/assets/reception-labels.css"></head><body><script>function countLocationValue(line){return line.final_location||"";}</script><script src="/assets/bwip-js-min.js"></script><script src="/assets/reception-labels.js"></script></body></html>');
  } else {response.writeHead(404); response.end();}
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  fs.mkdirSync(output, {recursive:true});
  let browser;
  try {
    browser = await chromium.launch({headless:true, channel:'msedge'});
    for (const viewport of [{width:320,height:640}, {width:393,height:873},
                            {width:1366,height:768}, {width:873,height:393}]) {
      const context = await browser.newContext({viewport});
      try {
        const errors = [], page = await context.newPage();
        context.on('page', target => target.on('pageerror', error => errors.push(error.message)));
        await page.goto('http://127.0.0.1:' + server.address().port);
        const opening = page.waitForEvent('popup');
        await page.evaluate(() => {
          const source = {bl_awb:'QA-BL-ORDER', attention_id:1,
            lines:['123456','S/N','COT 123457','POR REG','COTI 123458'].map((ov, index) => ({
              id:index+1,np_code:'QA-NP-01',description:'Repuesto de prueba',
              ov_number:ov,customer_name:'Cliente QA',brand:'BOBCAT',
              attention_id:1,attention_verified_qty:index+1,final_location:'QA-A-01',
            }))};
          const before = JSON.stringify(source);
          const popup = window.open('', '_blank');
          popup.document.write(WmsReceptionLabels.documentHtml(source, WmsReceptionLabels.items(source)));
          popup.document.close();
          if (JSON.stringify(source) !== before) throw Error('Print changed receipt data');
        });
        const popup = await opening;
        await popup.setViewportSize(viewport);
        await popup.waitForFunction(() => document.querySelector('#printLabels')?.disabled === false);
        assert.deepEqual(await popup.locator('.ov-value').allTextContents(),
          ['123456','Stock','COT 123457','','COTI 123458']);
        assert.deepEqual(await popup.locator('.quantity-value').allTextContents(), ['1','2','3','4','5']);
        assert.deepEqual(await popup.locator('.customer > strong').allTextContents(),
          ['Cliente QA','Para stock','Cliente QA','Cliente QA','Cliente QA']);
        assert.equal(await popup.locator('.sticker').count(), 5);
        assert.equal(await popup.getByText('POR REG', {exact:true}).count(), 0);
        assert.equal(await popup.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
        assert(await popup.locator('.sticker').evaluateAll(sheets => sheets.every(sheet =>
          sheet.dataset.fits === 'true' &&
          [...sheet.querySelectorAll('.np,.ov-value,.description,.quantity-value,.customer > strong,.location-box')]
            .every(field => field.scrollWidth <= field.clientWidth + 1 && field.scrollHeight <= field.clientHeight + 1)
        )));
        await popup.screenshot({path:path.join(output, 'order-' + viewport.width + '.png'), fullPage:true});
        await popup.evaluate(() => {window.print = () => {window.qaPrints = (window.qaPrints || 0) + 1;};});
        await popup.locator('#printLabels').click();
        assert.equal(await popup.evaluate(() => window.qaPrints), 1);
        await popup.locator('#labelWidth').fill('50');
        assert.equal(await popup.locator('#printLabels').isDisabled(), true);
        await popup.locator('#labelPaper').selectOption('te200-4x3');
        await popup.waitForFunction(() => !document.querySelector('#printLabels').disabled);
        if (viewport.width === 1366) {
          await popup.pdf({path:path.join(output, 'orders.pdf'), preferCSSPageSize:true, printBackground:true});
          await popup.evaluate(() => {
            document.querySelector('.description').textContent = 'QA '.repeat(1000);
            window.dispatchEvent(new Event('resize'));
          });
          assert.equal(await popup.locator('#printLabels').isDisabled(), true);
        }
        assert.deepEqual(errors, []);
        const stale = {id:1,bl_awb:'QA-BL-LIVE',attention_id:7,lines:[{
          id:1,np_code:'QA-NP-01',description:'Repuesto de prueba',ov_number:'COT 000111',
          customer_name:'Cliente QA',brand:'BOBCAT',attention_id:7,attention_verified_qty:2,
          final_location:'QA-A-01',in_selected_attention:true,
        }]};
        await page.evaluate(source => {
          window.selected = source;
          window.selectedAttentionId = 7;
          window.api = url => fetch(url);
          window.receptionHasUnsavedFields = () => false;
          window.notify = message => {window.qaNotice = message;};
        }, stale);
        for (const ov of ['COT 000222 / 000333', '159001']) {
          savedDetail = {...stale,lines:[{...stale.lines[0],ov_number:ov}]};
          const requestsBefore = detailRequests;
          const nextPopup = page.waitForEvent('popup');
          await page.evaluate(() => WmsReceptionLabels.print());
          const live = await nextPopup;
          await live.setViewportSize(viewport);
          await live.waitForFunction(() => document.querySelector('#printLabels')?.disabled === false);
          assert.equal(detailRequests, requestsBefore + 1);
          assert.deepEqual(await live.locator('.ov-value').allTextContents(), [ov]);
          assert.deepEqual(await live.locator('.quantity-value').allTextContents(), ['2']);
          assert.deepEqual(await live.locator('.location-box').allTextContents(), ['QA-A-01']);
          assert(await live.locator('.sticker').evaluateAll(sheets => sheets.every(sheet => sheet.dataset.fits === 'true')));
          await live.screenshot({path:path.join(output,'live-' + (ov.startsWith('COT')?'cot':'ov') + '-' + viewport.width + '.png'),fullPage:true});
          await live.close();
        }
        detailUnavailable = true;
        await page.evaluate(() => WmsReceptionLabels.print());
        assert.equal(await page.evaluate(() => window.qaNotice), 'No se pudo verificar la etiqueta.');
        detailUnavailable = false;
        const retryPopup = page.waitForEvent('popup');
        await page.evaluate(() => WmsReceptionLabels.print());
        const retry = await retryPopup;
        await retry.waitForFunction(() => document.querySelector('#printLabels')?.disabled === false);
        assert.deepEqual(await retry.locator('.ov-value').allTextContents(), ['159001']);
        await retry.close();
        assert.deepEqual(errors, []);
      } finally {await context.close();}
    }
    console.log('OK: complete COT/OV/Stock/blank pending, fresh server reference before printing, failure/retry and preserved quantities, four viewports');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
