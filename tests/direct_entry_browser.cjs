// Only fresh support_direct_entry_server.py fixtures, never operational servers.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.argv[2], scanner = process.argv[3] === 'scanner';
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '')) throw Error('Loopback fixture URL required');
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH});
  try {
    for (const width of [1366, 375]) {
      const page = await browser.newPage({viewport: {width, height: 900}});
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      page.on('dialog', d => d.accept());
      const code = '000-NEW-' + width + '-' + Date.now();
      await page.goto(base + '/reception');
      await page.getByRole('button', {name: 'Tránsito', exact: true}).click();
      await page.locator(scanner ? '#createScanTruckButton' : '#createManualTruckButton').click();
      await page.locator(scanner ? '#scanTruckBlCode' : '#truckDirectBlCode').waitFor();
      const guide = await page.locator('#truckGuideFilter').inputValue();
      if (scanner) {
        await page.locator('#scanTruckBlCode').fill(code);
        await page.locator('#scanTruckBlCode').press('Enter');
        await page.locator('#scanTruckPackageCode').waitFor();
        assert.match(await page.locator('#scanFeedback').innerText(), /Datos documentales pendientes/);
        for (const suffix of ['A', 'B']) {
          await page.locator('#scanTruckPackageCode').fill(code + '-PACKAGE-' + suffix);
          await page.locator('#scanTruckPackageCode').press('Enter');
        }
        await page.waitForFunction(() => document.querySelector('#scanTotal')?.textContent === '2');
        await page.reload();
        await page.locator('#scanTruckBlCode').fill(code);
        await page.locator('#scanTruckBlCode').press('Enter');
        await page.locator('#scanTruckPackageCode').waitFor();
        await page.locator('#finalizeScanTruckButton').click();
      } else {
        await page.locator('#truckDirectBlCode').fill(code);
        await page.locator('#truckDirectPackages').fill('2');
        await page.locator('#truckDirectAdd').click();
        await page.getByText('BL nueva registrada. Datos documentales pendientes.', {exact: true}).waitFor();
        await page.locator('#truckDirectBlCode').fill(code);
        await page.locator('#truckDirectPackages').fill('9');
        await page.locator('#truckDirectAdd').click();
        await page.getByText('Esta BL ya esta ingresada en este camion; no se duplico.', {exact: true}).waitFor();
        await page.getByRole('button', {name: 'Iniciar llegada', exact: true}).click();
        assert.equal(await page.locator('.truck-bl-received').count(), 1);
        await page.reload();
        await page.getByRole('button', {name: 'Iniciar llegada', exact: true}).click();
        await page.locator('.truck-bl-received').fill('2');
        await page.locator('#saveTruckArrivalButton').click();
      }
      await page.locator('#saveTruckLocationsButton').waitFor();
      await page.locator('.truck-bl-location').fill('QA-TEMP-' + width);
      await page.locator('#saveTruckLocationsButton').click();
      await page.getByRole('button', {name: scanner ? 'Continuar recepción' : 'Abrir BL para conteo', exact: true}).click();
      await page.getByRole('heading', {name: code, exact: true}).waitFor();
      await page.getByRole('button', {name: 'Volver al camion ' + guide, exact: false}).click();
      await page.locator('#content [data-truck-guide]').waitFor();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
      assert.deepEqual(errors, []);
      const output = path.join(__dirname, '..', 'qa', 'runtime', 'direct-entry');
      fs.mkdirSync(output, {recursive: true});
      await page.screenshot({path: path.join(output, (scanner ? 'scanner' : 'manual') + '-' + width + '.png')});
      await page.close();
      console.log('OK: ' + (scanner ? 'scanner' : 'manual') + ', new unprogrammed BL, reload, arrival, location and return at ' + width + 'px');
    }
  } finally { await browser.close(); }
})().catch(e => {console.error(e); process.exitCode = 1;});
