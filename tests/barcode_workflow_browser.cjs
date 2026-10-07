const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const base = process.argv[2];
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '')) throw Error('Isolated QA URL required');
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH});
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.accept());
  try {
    await page.goto(base + '/reception');
    await page.getByRole('button', {name: 'Tránsito', exact: true}).click();
    await page.locator('#createScanTruckButton').click();
    await page.locator('#scanTruckBlCode').fill('QA-BL-001');
    await page.locator('#scanTruckBlCode').press('Enter');
    await page.locator('#scanTruckPackageCode').waitFor();
    for (const code of ['QA-PACKAGE-001', 'QA-PACKAGE-002']) {
      await page.locator('#scanTruckPackageCode').fill(code);
      await page.locator('#scanTruckPackageCode').press('Enter');
    }
    await page.waitForFunction(() => document.querySelector('#scanTotal')?.textContent === '2');
    await page.reload();
    await page.locator('#scanTruckBlCode').fill('QA-BL-001');
    await page.locator('#scanTruckBlCode').press('Enter');
    await page.locator('#scanTruckPackageCode').waitFor();
    await page.locator('#scanTruckPackageCode').fill('QA-PACKAGE-003');
    await page.locator('#scanTruckPackageCode').press('Enter');
    await page.waitForFunction(() => document.querySelector('#scanTotal')?.textContent === '3');
    await page.locator('#finalizeScanTruckButton').click();
    await page.locator('#saveTruckLocationsButton').waitFor();
    await page.locator('.truck-bl-location').fill('QA-TEMP');
    await page.locator('#saveTruckLocationsButton').click();
    await page.getByRole('button', {name: 'Continuar recepción'}).click();
    await page.getByRole('heading', {name: 'QA-BL-001', exact: true}).waitFor();
    await page.getByRole('button', {name: /Pasar a.*INICIO CONTEO/i}).click();
    await page.locator('#scanReceptionNp').waitFor();
    await page.locator('#scanReceptionNp').fill('NP-001');
    await page.locator('#scanReceptionNp').press('Enter');
    await page.locator('#receptionNpQuantity').waitFor();
    await page.locator('#receptionNpQuantity').fill('8');
    await page.locator('#receptionNpSave').click();
    await page.waitForFunction(() => document.querySelector('#receptionNpScanResult')?.textContent.includes('Línea guardada'));
    assert.equal(await page.evaluate(() => typeof Html5Qrcode), 'function');
    assert.deepEqual(errors, []);
    console.log('OK: BL, fast packages, truck restoration, arrival, locations, NP selection and quantity save');
  } catch (e) {
    console.error('PAGE ERRORS', errors);
    console.error(await page.locator('#content').innerText());
    console.error(await page.evaluate(() => ({guide: document.getElementById('truckGuideFilter').value, selected: scannerSelectedShipmentId, summary: activeTruckGuideSummary})));
    throw e;
  } finally { await browser.close(); }
})().catch(e => {console.error(e); process.exitCode = 1;});
// Run once against a fresh support_scan_server.py fixture (never operational data).
