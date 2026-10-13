// Disposable support_pilot_server fixture; never point at an operational host.
const {chromium} = require('playwright');
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const base = process.argv[2], output = path.join(__dirname, '../qa/pilot-correction');
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '')) throw Error('Loopback QA fixture required');
const headers = {'Content-Type':'application/json','X-WMS-Request':'1'};
(async () => {
  fs.mkdirSync(output, {recursive:true});
  const browser = await chromium.launch({headless:true,channel:'msedge'}), results = [];
  try {
    let index = 0;
    for (const viewport of [{width:1440,height:900},{width:393,height:873},{width:360,height:780},{width:320,height:640},{width:873,height:393}]) {
      const context = await browser.newContext({viewport}), page = await context.newPage(), errors = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('dialog', dialog => dialog.accept());
      await context.addInitScript(() => {if ('serviceWorker' in navigator) navigator.serviceWorker.register = async () => undefined;});
      assert.equal((await context.request.post(base + '/api/login',{headers,data:{username:'qa.reader',password:'QA-password-only-123!'}})).status(),200);
      await page.goto(base + '/reception');
      await page.waitForFunction(() => typeof WmsPilotCorrection !== 'undefined' && role() === 'ADMINISTRADOR');
      const id = ++index;
      await page.evaluate(id => loadDetail(id), id);
      const button = page.getByRole('button',{name:'Corregir pruebas de esta BL',exact:true});
      await page.locator('.scan-bl-extra').evaluate(node => node.open = true);
      await button.click();
      const dialog = page.locator('#pilotCorrectionDialog');
      await dialog.waitFor({state:'visible'});
      assert.equal(await page.locator('#pilotCorrectionAction').evaluate(node => node === document.activeElement),true);
      await page.locator('#pilotCorrectionCancel').click();
      assert.equal(await dialog.isVisible(),false);
      assert.equal((await (await context.request.get(`${base}/api/receptions/${id}`)).json()).app_status,'REVISION SISTEMA');
      await button.click();
      await page.locator('#pilotCorrectionReason').fill('QA: correccion de prueba aprobada');
      await page.locator('#pilotCorrectionConfirmation').fill('OTRA-BL');
      await page.locator('#pilotCorrectionSubmit').click();
      await page.getByText('La BL escrita no coincide.',{exact:true}).waitFor();
      await page.locator('#pilotCorrectionConfirmation').fill('QA-PILOT-' + id);
      await page.screenshot({path:path.join(output,'dialog-' + viewport.width + '.png'),fullPage:true});
      const box = await dialog.boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= viewport.width + 1);
      assert.ok(box.y >= 0 && box.y + box.height <= viewport.height + 1);
      assert.equal(await dialog.evaluate(node => node.scrollWidth > node.clientWidth + 1),false);
      await page.route(`**/api/receptions/${id}/pilot-correction`, route => route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'QA: guardar no disponible'})}),{times:1});
      await page.locator('#pilotCorrectionSubmit').click();
      await page.getByText('QA: guardar no disponible',{exact:true}).waitFor();
      assert.equal(await page.locator('#pilotCorrectionConfirmation').inputValue(),'QA-PILOT-' + id);
      await page.locator('#pilotCorrectionAction').selectOption(index % 2 ? 'pending_arrival' : 'historical_closed');
      const saved = page.waitForResponse(response => response.url().endsWith('/pilot-correction') && response.request().method() === 'POST');
      await page.locator('#pilotCorrectionSubmit').click();
      assert.equal((await saved).status(),200);
      await page.waitForFunction(() => !document.querySelector('#pilotCorrectionDialog').open);
      const detail = await (await context.request.get(`${base}/api/receptions/${id}`)).json();
      assert.equal(detail.app_status,index % 2 ? 'PROGRAMADO' : 'CERRADO');
      assert.equal(detail.active_attention_id,null);
      assert.equal(detail.lines[0].received_qty,0);
      assert.equal(detail.accounting_refs[0].fr_number,'QA-FR');
      assert.deepEqual(detail.accounting_refs[0].em_numbers,['QA-EM']);
      assert.equal(await button.count(),0);
      assert.deepEqual(errors,[]);
      results.push({viewport,status:detail.app_status,passed:true});
      await context.close();
    }
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(results,null,2));
    process.stdout.write(JSON.stringify(results) + '\n');
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exit(1);});
