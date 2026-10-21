// Only support_admin_closure_server.py on loopback; never an operating WMS.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.argv[2];
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '')) throw Error('Disposable loopback fixture required');
const out = path.join(__dirname, '../qa/runtime/admin-closure');

(async () => {
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true, channel: 'msedge'});
  try {
    for (const [index, [width, height]] of [[320, 740], [393, 873], [1366, 900], [873, 393]].entries()) {
      const context = await browser.newContext({viewport: {width, height}, serviceWorkers: 'block'});
      const page = await context.newPage(), errors = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('dialog', dialog => dialog.accept());
      await page.goto(base + '/reception');
      await page.waitForFunction(() => typeof loadDetail === 'function' && Boolean(window.WmsAdminClosure));
      for (const [kind, action, expectedState] of [['PHANTOM', 'retire_test', 'CERRADO'],
        ['DOC', 'close_bl', 'CERRADO'], ['PARTIAL', 'close_attention', 'CERRADO']]) {
        const bl = 'QA-ADMIN-' + kind + '-' + (index + 1);
        const before = await page.evaluate(async bl => {
          const rows = await (await api('/api/receptions?all=1&search=' + encodeURIComponent(bl))).json();
          const id = rows.find(row => row.bl_awb === bl).id;
          await loadDetail(id);
          return {id, aid: selectedAttentionId, lines: selected.lines.map(l => [l.id, l.received_qty]),
            packages: selected.received_packages};
        }, bl);
        const button = page.getByRole('button', {name: 'Regularizar o cerrar BL', exact: true});
        await button.scrollIntoViewIfNeeded();
        assert.equal(await button.isEnabled(), true);
        await button.click();
        await page.locator('#adminClosureAction').waitFor();
        await page.waitForFunction(() => !document.querySelector('#adminClosureAction').disabled);
        await page.locator('#adminClosureAction').selectOption(action);
        assert.equal(await page.locator('#adminClosureDialog').isVisible(), true);
        await page.locator('#adminClosureReason').fill('Regularizacion administrativa QA confirmada por propietario');
        await page.locator('#adminClosureBlConfirmation').fill(bl);
        if (await page.locator('#adminClosureAcknowledge').isVisible()) await page.locator('#adminClosureAcknowledge').check();
        const submit = page.locator('#adminClosureSubmit');
        await submit.scrollIntoViewIfNeeded();
        const bounds = await submit.boundingBox();
        assert(bounds.height >= 44 && bounds.x >= 0 && bounds.x + bounds.width <= width + 1);
        if (width === 320 && kind === 'DOC') {
          await page.addStyleTag({content: '#adminClosureDialog :is(input,textarea,select,button,label,p){font-size:28px!important;line-height:1.4!important}'});
          await submit.scrollIntoViewIfNeeded();
          assert.equal(await page.locator('#adminClosureDialog').evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
        }
        await page.screenshot({path: path.join(out, kind + '-' + width + '.png'), fullPage: true});
        let posts = 0;
        const count = request => { if (request.method() === 'POST' && request.url().endsWith('/admin-closure')) posts++; };
        page.on('request', count);
        if (kind === 'DOC') {
          let first = true;
          await page.route('**/api/receptions/' + before.id + '/admin-closure', async route => {
            if (route.request().method() === 'POST' && first) {
              first = false;
              await route.fulfill({status: 503, body: 'Unavailable'});
            } else await route.continue();
          });
          await submit.click();
          await page.locator('#adminClosureError').waitFor({state: 'visible'});
          assert.equal(await page.locator('#adminClosureReason').inputValue(), 'Regularizacion administrativa QA confirmada por propietario');
          assert.equal(await page.locator('#adminClosureBlConfirmation').inputValue(), bl);
          await page.locator('#adminClosureRefresh').click();
          await page.waitForFunction(() => !document.querySelector('#adminClosureSubmit').disabled);
        }
        await submit.evaluate(button => { button.click(); button.click(); });
        await page.locator('#adminClosureDialog').waitFor({state: 'hidden'});
        await page.waitForFunction(state => selected.app_status === state, expectedState);
        assert.equal(posts, kind === 'DOC' ? 2 : 1, 'One mutation per explicit attempt');
        page.off('request', count);
        assert.equal(await page.evaluate(() => selected.received_packages), before.packages);
        assert.deepEqual(await page.evaluate(() => selected.lines.map(l => [l.id, l.received_qty])), before.lines);
        if (kind === 'DOC') assert.equal(await page.evaluate(() => selected.condition_status), 'CIERRE ADMINISTRATIVO');
        if (kind === 'PARTIAL') {
          const master = await page.evaluate(async id =>
            (await api('/api/receptions/' + id + '/admin-closure')).json(), before.id);
          assert.notEqual(master.app_status, 'CERRADO', 'Only selected attention closes; master stays open');
        }
        console.log('OK real admin closure ' + kind + ' ' + width);
      }
      await page.evaluate(() => showMyWork());
      await page.locator('[data-work-view="history"]').click();
      await page.waitForFunction(() => document.querySelector('#content [data-work-view="history"]')?.getAttribute('aria-pressed') === 'true');
      await page.getByText('Cierre administrativo', {exact: true}).first().waitFor();
      await page.getByText('Registro de prueba retirado', {exact: true}).first().waitFor();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      assert.deepEqual(errors, []);
      await context.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
