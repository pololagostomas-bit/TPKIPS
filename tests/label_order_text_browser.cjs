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
const server = http.createServer((request, response) => {
  const asset = assets[new URL(request.url, 'http://127.0.0.1').pathname];
  if (asset) {
    response.writeHead(200, {'Content-Type': asset[1]});
    response.end(fs.readFileSync(path.join(root, 'frontend/static', asset[0])));
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
            lines:['123456','S/N','COT 123457','POR REG','COT 123458'].map((ov, index) => ({
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
          ['123456','Stock','Cotizaci\u00f3n','','Cotizaci\u00f3n']);
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
      } finally {await context.close();}
    }
    console.log('OK: OV/Stock/Quotation/blank pending, separate orders and quantities, print/retry/overflow guard, four viewports');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
