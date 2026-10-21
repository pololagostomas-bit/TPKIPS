// Synthetic DOM/API fixture only. Does not load a database or contact any server.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'qa/np-fallback');
const template = fs.readFileSync(path.join(root, 'frontend/templates/reception.html'), 'utf8');
const baseStyle = template.match(/<style>([\s\S]*?)<\/style>/)[1];
const moduleCode = fs.readFileSync(path.join(root, 'frontend/static/reception-np-scan.js'), 'utf8');

async function boot(page, count = 10, extras = false) {
  await page.setContent('<!doctype html><html lang="es"><meta name="viewport" content="width=device-width,initial-scale=1"><body class="reader-ui workspace-app unified-workspace"><main id="detail"></main><p id="notice" role="status"></p></body></html>');
  await page.addStyleTag({content: baseStyle});
  for (const file of ['reception-scan.css', 'reader-ui.css'])
    await page.addStyleTag({path: path.join(root, 'frontend/static', file)});
  await page.addScriptTag({content: moduleCode});
  await page.addScriptTag({content: `var receptionNpFilters=new Map(); var $=id=>document.getElementById(id); var esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));\n` + template.slice(template.indexOf('function receptionNpFilter('),template.indexOf('function countLocationCell('))});
  await page.evaluate(({count, extras}) => {
    const lines = Array.from({length: count}, (_, index) => ({id: index + 1,
      attention_id: 7, in_selected_attention: true, np_code: 'NP-' + index,
      description: 'Repuesto sintetico de prueba con descripcion extensa',
      ov_number: 'QA-OV-' + index, ip_reference: 'QA-IP-' + index,
      attention_planned_qty: 9, attention_verified_qty: 9, stock_available_qty: 0}));
    if (extras) lines.push(...[
      {id: 501, ov_number: 'QA-OV-A'}, {id: 502, ov_number: 'QA-OV-B'},
      {id: 503, attention_id: 8, in_selected_attention: false}
    ].map(line => ({...lines[0], np_code: 'NP-SAME', ...line})));
    const f = window.fixture = {shipment: {id: 5, attention_id: 7,
      app_status: 'REVISION SISTEMA', lines}, calls: [], failure: null, hold: false, release: null};
    f.mount = () => {
      const fields = f.shipment.lines.filter(line => line.in_selected_attention).map(line =>
        `<tr data-np-code="${line.np_code}"><td>${WmsNpScan.listControl(line,true)}</td><td><input id="qty-${line.id}" type="number" value="${line.attention_verified_qty}"><input id="reason-${line.id}" value=""><input id="count-location-${line.id}" value="QA-BIN"><span id="diff-${line.id}"></span></td></tr>`).join('');
      document.getElementById('detail').innerHTML = WmsNpScan.render(f.shipment, receptionNpFilter(f.shipment,'count')+'<div class="tablewrap"><table id="countNpTable"><tbody>'+fields+'</tbody></table></div>');
      filterReceptionNpRows('count');
    };
    window.handleReceptionNpScan = event => WmsNpScan.handle(event);
    WmsNpScan.init({getContext: () => ({shipment: f.shipment, shipmentId: f.shipment.id, attentionId: 7}),
      panelEditable: () => f.shipment.app_status === 'REVISION SISTEMA',
      shipmentUrl: suffix => '/api/receptions/5' + suffix,
      notify: text => {document.getElementById('notice').textContent = text;},
      onPartialSaved: data => {f.shipment = data; f.mount();},
      onSaved: data => {f.shipment.lines = data.lines;},
      api: async (url, options) => {
        const body = JSON.parse(options.body);
        f.calls.push({url, body});
        const failure = f.failure; f.failure = null;
        if (f.hold) {f.hold = false; await new Promise(resolve => {f.release = resolve;});}
        if (failure === 'offline') throw Error('Conexion de prueba interrumpida');
        if (failure === 'html') return {ok: false, json: async () => {throw Error('Respuesta no JSON de prueba');}};
        if (failure === 'forbidden') return {ok: false, json: async () => ({error: 'Sin permiso de prueba'})};
        assertContext(body.attention_id);
        if (url.endsWith('/count/partial')) {
          for (const id of body.line_ids) {
            const line = f.shipment.lines.find(item => item.id === id);
            if (line.np_scanned_at) throw Error('El faltante ya se registro');
            line.attention_verified_qty = 0; line.np_unreceived_reason = 'No recibido en esta llegada';
          }
          return {ok: true, json: async () => ({...f.shipment, app_status: 'EM'})};
        }
        const line = f.shipment.lines.find(item => String(item.id) === url.split('/').at(-1));
        if (!line?.in_selected_attention || line.attention_id !== 7) throw Error('Linea fuera de atencion');
        if (!line.np_scanned_at) {
          line.attention_verified_qty = body.received_qty;
          line.np_scanned_at = '2026-10-16T12:00:00Z'; line.blocked_reason = body.reason;
          line.final_location = body.count_location;
        }
        return {ok: true, json: async () => ({...f.shipment, lines: f.shipment.lines.map(item => ({...item}))})};
      }});
    function assertContext(value) {if (String(value) !== '7') throw Error('Atencion incorrecta');}
    f.mount();
  }, {count, extras});
}

async function scan(page, code) {
  await page.locator('#scanReceptionNp').fill(code);
  await page.locator('#scanReceptionNp').press('Enter');
}
const settled = page => page.waitForFunction(() => WmsNpScan.status().phase === 'ready');

async function geometry(page) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
  const invalid = await page.locator('#receptionNpScanPanel button:visible').evaluateAll(buttons => buttons
    .filter(button => button.getBoundingClientRect().height < 44 || button.scrollWidth > button.clientWidth + 2)
    .map(button => button.textContent));
  assert.deepEqual(invalid, []);
}

(async () => {
  fs.mkdirSync(output, {recursive: true});
  const browser = await chromium.launch({headless: true, channel: 'msedge'});
  const errors = [];
  try {
    for (const [width, height] of [[320, 640], [393, 873], [1366, 768], [873, 393]]) {
      const context = await browser.newContext({viewport: {width, height}, reducedMotion: 'reduce'});
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      // Block any accidental external load from this entirely local fixture.
      await page.route('**/*', route => route.abort());
      await boot(page, 10, true);
      assert.equal(await page.getByRole('button', {name: 'Finalizar conteo de esta entrega'}).isVisible(), false);
      assert.equal(await page.locator('#receptionNpFallbackToggle').count(),0);
      await page.locator('#countNpFilter').fill('NP-SAME');
      assert.equal(await page.locator('#countNpTable tr:visible [data-np-select]').count(), 2);
      await geometry(page);
      await page.screenshot({path: path.join(output, `list-${width}.png`), fullPage: true});
      await page.getByRole('button',{name:'Registrar NP NP-SAME, OV QA-OV-B',exact:true}).click();
      await settled(page);
      assert.equal(await page.evaluate(() => fixture.calls[0].url), '/api/receptions/5/lines/502');
      assert.equal(await page.locator('#receptionNpQuantity').count(), 0);
      assert.match(await page.locator('#receptionNpScanResult').innerText(), /Seleccion de lista guardada.*Cantidad 9/);
      const choice = await page.evaluate(() => WmsNpScan.receiveCamera('NP-SAME', WmsNpScan.status().context));
      assert.equal(choice.phase, 'choice');
      assert.equal(await page.evaluate(() => fixture.calls.length), 1);
      await page.locator('#receptionNpScanResult .np-match').click(); await settled(page);
      assert.equal(await page.evaluate(() => fixture.calls.length), 2);
      const duplicate = await page.evaluate(() => WmsNpScan.receiveCamera('NP-SAME', WmsNpScan.status().context));
      assert.equal(duplicate.lastResult.outcome, 'duplicate');
      assert.equal(await page.evaluate(() => fixture.calls.length), 2);

      await page.evaluate(() => {fixture.failure = 'offline'; fixture.hold = true;});
      await scan(page, 'NP-0'); await scan(page, 'NP-1');
      assert.equal(await page.evaluate(() => WmsNpScan.status().phase), 'saving');
      assert.equal(await page.evaluate(() => WmsNpScan.status().queueLength), 2);
      await page.evaluate(() => fixture.release());
      await page.getByRole('button', {name: 'Reintentar lectura'}).waitFor();
      assert.match(await page.locator('[data-np-save-state]').innerText(), /pendiente de resolver/);
      await page.evaluate(() => fixture.mount());
      assert.equal(await page.evaluate(() => WmsNpScan.status().queueLength), 2);
      assert.equal(await page.locator('#countNpTable [data-np-select]:enabled').count(),0);
      await geometry(page);
      await page.screenshot({path: path.join(output, `retry-${width}.png`), fullPage: true});
      await page.getByRole('button', {name: 'Reintentar lectura'}).click(); await settled(page);
      assert.deepEqual(await page.evaluate(() => fixture.calls[2]), await page.evaluate(() => fixture.calls[3]));
      assert.equal(await page.evaluate(() => fixture.calls.length), 5);
      await scan(page, 'NP-O');
      assert.equal(await page.evaluate(() => WmsNpScan.status().phase), 'error');
      assert.equal(await page.locator('#countNpTable [data-np-select]:enabled').count(),0);
      await page.getByRole('button', {name: 'Descartar lectura'}).click(); await settled(page);
      await page.locator('#countNpFilter').fill('NP-O');
      assert.equal(await page.locator('#countNpTable tr:visible').count(), 0);
      await page.locator('#countNpFilter').fill('NP-2');
      await page.evaluate(() => {fixture.failure = 'forbidden';});
      await page.locator('#countNpTable tr:visible [data-np-select]').click();
      await page.getByRole('button', {name: 'Reintentar lectura'}).waitFor();
      assert.match(await page.locator('#receptionNpIssue').innerText(), /Sin permiso/);
      await page.getByRole('button', {name: 'Reintentar lectura'}).click(); await settled(page);

      await boot(page);
      await page.getByText('Ver listado completo',{exact:true}).click();
      for (let index = 0; index < 9; index++) {
        await page.locator('#countNpTable [data-np-select]:enabled').first().click(); await settled(page);
      }
      assert.match(await page.locator('#receptionNpProgress').innerText(), /9\/10/);
      assert.equal(await page.evaluate(() => WmsNpScan.canComplete()), false);
      page.once('dialog', dialog => dialog.dismiss());
      await page.getByRole('button', {name: 'Finalizar conteo de esta entrega'}).click();
      assert.equal(await page.evaluate(() => fixture.calls.length), 9);
      await geometry(page);
      await page.screenshot({path: path.join(output, `partial-${width}.png`), fullPage: true});
      page.once('dialog', dialog => dialog.accept());
      await page.getByRole('button', {name: 'Finalizar conteo de esta entrega'}).click();
      await page.waitForFunction(() => fixture.shipment.app_status === 'EM');
      assert.deepEqual(await page.evaluate(() => fixture.calls.at(-1).body.line_ids), [10]);
      assert.equal(await page.evaluate(() => fixture.shipment.lines.filter(line => line.np_scanned_at).length), 9);
      assert.equal(await page.evaluate(() => !!fixture.shipment.lines[9].np_scanned_at), false);
      assert.equal(await page.evaluate(() => fixture.shipment.lines[9].attention_planned_qty), 9);
      assert.equal(await page.evaluate(() => fixture.shipment.lines[9].attention_verified_qty), 0);

      await boot(page, 120);
      assert.equal(await page.locator('#countNpTable [data-np-select]').count(), 120);
      await page.locator('#countNpFilter').fill('NP-119');
      assert.equal(await page.locator('#countNpTable tr:visible [data-np-select]').count(), 1);
      if (width === 320) await page.addStyleTag({content: '#receptionNpScanPanel :is(button,p,span,label,input){font-size:32px!important;line-height:1.5!important}'});
      await geometry(page);
      await page.screenshot({path: path.join(output, `search-${width}.png`), fullPage: true});
      await context.close();
      console.log(`NP list/camera choice, serial queue/error/retry, exact ID, 9/10 partial and reflow OK ${width}x${height}`);
    }
    assert.deepEqual(errors, []);
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
