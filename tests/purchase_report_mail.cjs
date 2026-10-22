// Render synthetic mail only; no configured database, account or mail transport.
const {chromium} = require('playwright');
const {execFileSync} = require('node:child_process');
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const root = path.resolve(__dirname, '..');
const python = process.env.WMS_QA_PYTHON || 'python';
const code = `
import json
from backend.services import purchase_alerts as a
from tests.test_purchase_report_dates import workbook
config = {**a.DEFAULTS, 'sender_name':'QA', 'sender':'qa@example.test'}
snapshot = a.read_cases(workbook([
 ['PRE1', 'IP-REGULAR-NEW', 'OV1', '17/09/2026'],
 ['PRE2', 'IP-REGULAR-OLD', 'OV2', None],
 ['12345', 'IP-GRAVE-NEW', 'COT1', '18/09/2026'],
 ['54321', 'IP-GRAVE-OLD', 'COT2', '19/09/2026']]), [])
snapshot['checked_at'] = '2026-10-22T13:00:00+00:00'
new_keys = {case['key'] for case in snapshot['cases'] if case['ip'].endswith('NEW')}
print(json.dumps(a.render(config,snapshot,new_keys,'incremental')))
`;
const payload = JSON.parse(execFileSync(python, ['-c', code], {cwd:root,encoding:'utf8'}));
(async () => {
  const browser = await chromium.launch({headless:true,channel:'msedge'});
  try {
    for (const width of [320,393,1366]) {
      const page = await browser.newPage({viewport:{width,height:873}});
      await page.route('**/*', route => route.abort());
      await page.setContent(payload.html);
      assert.equal(await page.locator('h2').count(), 2);
      assert.match(await page.locator('h2').first().innerText(), /^Graves:/);
      assert.equal(await page.locator('table').count(), 4);
      const expected = ['IP-GRAVE-NEW','IP-GRAVE-OLD','IP-REGULAR-NEW','IP-REGULAR-OLD'];
      for (let index=0; index<expected.length; index++) {
        const table = page.locator('table').nth(index);
        assert.match(await table.innerText(), new RegExp(expected[index]));
        for (const other of expected.filter(value=>value!==expected[index])) {
          assert.equal((await table.innerText()).includes(other), false);
        }
        assert.equal(await table.evaluate(element=>element.previousElementSibling.textContent),
          index%2===0 ? 'Casos adicionados' : 'Demas pendientes');
      }
      assert.match(await page.locator('body').innerText(), /18\/09\/2026/);
      assert.match(await page.locator('body').innerText(), /Sin fecha/);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth+1),true);
      assert.equal(await page.locator('.cell-label').first().isVisible(), width<=600);
      fs.mkdirSync(path.join(root,'qa/purchase-report-dates'), {recursive:true});
      await page.screenshot({path:path.join(root,`qa/purchase-report-dates/mail-${width}.png`),fullPage:true});
      await page.close();
    }
    console.log('OK synthetic purchase mail: severity sections, dates/missing dates, mobile reflow, no real mail.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1)});
