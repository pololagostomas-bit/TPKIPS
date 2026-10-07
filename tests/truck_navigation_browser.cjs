// Run only against tests/support_navigation_server.py (disposable data).
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.argv[2];
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '')) throw Error('Pass a loopback QA URL');

(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || chromium.executablePath()});
  const context = await browser.newContext({viewport: {width: 1366, height: 900}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  const output = path.join(__dirname, '..', 'qa', 'runtime', 'truck-navigation');
  fs.mkdirSync(output, {recursive: true});
  try {
    await page.goto(base + '/reception');
    await page.waitForFunction(() => typeof window.WmsTruckNavigation === 'object');
    await page.evaluate(() => openTruckGuideFromBl('QA-ORIGIN'));
    const manual = await page.locator('#manualTruckWorkspace').count() > 0;
    await page.getByRole('button', {name: /Continuar recepci.n|Abrir BL para conteo/}).first().click();
    await page.getByRole('heading', {name: 'QA-RETURN-001', exact: true}).waitFor();
    await page.getByRole('button', {name: /Volver al camion QA-ORIGIN/}).waitFor();
    await page.screenshot({path: path.join(output, 'bl-desktop.png')});
    for (const role of ['ASISTENTE_RECEPCION', 'AUXILIAR_RECEPCION', 'ADMINISTRADOR']) {
      await page.evaluate(role => {document.getElementById('role').value = role; renderDetail();}, role);
      assert.equal(await page.getByRole('button', {name: /Volver al camion QA-ORIGIN/}).count(), 1);
    }
    await page.setViewportSize({width: 375, height: 812});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
    await page.screenshot({path: path.join(output, 'bl-mobile.png')});
    await page.getByRole('button', {name: /Volver al camion QA-ORIGIN/}).click();
    await page.locator('#content [data-truck-guide="QA-ORIGIN"]').waitFor();
    assert.deepEqual(await page.evaluate(() => [selected, selectedId, selectedAttentionId]), [null, null, null]);
    assert.equal(await page.evaluate(() => activeTruckGuideSummary.truck_guide), 'QA-ORIGIN');

    if (manual) {
      await page.evaluate(() => openTruckGuideFromBl('QA-OTHER'));
      await page.locator('#truckPlanBlSearch').fill('QA-RETURN-001');
      await page.locator('#truckPlanBlSearch').press('Enter');
      await page.locator('#truckPlanMatches').getByText('BL ya registrada en:').waitFor();
      assert.equal(await page.locator('#truckPlanMatches [data-open-truck]').count(), 2);
      await page.locator('#truckPlanMatches button', {hasText: 'QA-RETURN-001'}).click();
      await page.locator('#truckPlanSelection').getByText(/ya fue ingresada/).waitFor();
      assert.equal(await page.locator('#truckPlanSelection').getByRole('button', {name: 'Agregar BL al transito'}).count(), 0);
      await page.screenshot({path: path.join(output, 'existing-bl-mobile.png')});
      await page.setViewportSize({width: 1366, height: 900});
      await page.screenshot({path: path.join(output, 'existing-bl-desktop.png')});
      await page.locator('#truckPlanSelection').getByRole('button', {name: 'Camion QA-ORIGIN', exact: true}).click();
      await page.getByRole('heading', {name: 'QA-ORIGIN', exact: true}).waitFor();
      const guide = await page.evaluate(async () => {
        const response = await api('/api/truck-guides', {method: 'POST', body: {scheduled_date: '2026-10-07'}});
        const data = await response.json();
        if (!response.ok) throw Error(data.error);
        return data.truck_guide;
      });
      await page.evaluate(guide => openTruckGuideFromBl(guide), guide);
      await page.locator('#truckPlanBlSearch').fill('QA-RETURN-001');
      await page.locator('#truckPlanBlSearch').press('Enter');
      await page.locator('#truckPlanMatches button', {hasText: 'QA-RETURN-001'}).click();
      await page.locator('#truckPlanSelection').getByRole('button', {name: 'Agregar BL al transito'}).waitFor();
      await page.locator('#truckPlanQuantity').fill('1');
      await page.locator('#truckPlanSelection').getByRole('button', {name: 'Agregar BL al transito'}).click();
      await page.waitForFunction(() => activeTruckGuideSummary.bls.some(item => item.bl_awb === 'QA-RETURN-001'));
      assert.equal(await page.evaluate(() => activeTruckGuideSummary.bls.find(item => item.bl_awb === 'QA-RETURN-001').planned_packages), 1);
    }
    assert.deepEqual(errors, []);
    console.log('OK: camion -> BL -> camion, todos los roles, desktop/mobile' + (manual ? ', BL existente localizada y saldo adicional programado.' : '.'));
  } catch (error) {
    await page.screenshot({path: path.join(output, 'failure.png')});
    console.error((await page.locator('#content').innerText()).slice(0, 1800));
    throw error;
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
