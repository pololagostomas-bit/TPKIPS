// Run against a fresh support_tracking_server.py --synthetic fixture.
const assert = require('node:assert/strict');
const {chromium} = require('playwright');

const base = process.argv[2];
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '')) throw Error('Synthetic loopback fixture required');
const role = 'CONSULTA_TRACKING';
const analystRole = 'CONSULTA_TRACKING_REPUESTOS';
const trackingCredential = 'synthetic-account-password';

async function login(page, route, username, credential) {
  await page.goto(base + route);
  await page.locator('#loginForm [name=username]').fill(username);
  await page.locator('#loginForm [name=password]').fill(credential);
  await page.locator('#loginForm [type=submit]').click();
}

async function createUser(page, username, accessRole) {
  await page.locator('#accountUsername').fill(username);
  await page.locator('#accountDisplay').fill('Consulta de prueba');
  await page.locator('#accountRole').selectOption(accessRole, {timeout: 5000});
  await page.locator('#accountPassword').fill(trackingCredential);
  await page.locator('#userForm button[type=submit]').click();
  await page.getByText('Usuario guardado correctamente.').waitFor();
}

async function verifyTracking(context, username, route, analyst) {
  const page = await context.newPage();
  await login(page, route, username, trackingCredential);
  await page.waitForURL(base + '/tracking');
  await page.locator('#searchForm').waitFor();
  const me = await (await context.request.get(base + '/tracking/api/me')).json();
  assert.equal(me.username, username);
  assert.equal(me.details, analyst);
  const filters = page.locator('#searchForm [name=type]');
  assert.deepEqual(await filters.locator('option').evaluateAll(options => options.map(o => o.value)),
    analyst ? ['OV', 'OC', 'IP', 'BL'] : ['OV', 'OC']);
  const cases = [
    ['OV', 'OV-DEMO-0421', 'REP-001'],
    ['OC', '54321', 'REP-STOCK-03']
  ];
  if (analyst) cases.push(['IP', 'IP-DEMO-01', 'REP-001'], ['BL', 'BL-DEMO-02', 'REP-002']);
  for (const [type, number, part] of cases) {
    await filters.selectOption(type);
    await page.locator('#searchForm [name=number]').fill(number);
    await page.getByRole('button', {name: 'Consultar', exact: true}).click();
    await page.locator('#result').getByRole('heading', {name: type + ' ' + number, exact: true}).waitFor();
    if (analyst) await page.locator('#lines').getByText(part, {exact: true}).waitFor();
    else {
      assert.equal(await page.locator('#detailLines').isVisible(), false);
      assert.equal(await page.locator('#journey').isVisible(), false);
      assert.ok(!(await page.locator('#result').innerText()).includes(part));
    }
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  }
  assert.equal((await context.request.get(base + '/api/users')).status(), 403);
}

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.WMS_QA_BROWSER_CHANNEL || 'msedge'});
  try {
    for (const [width, adminRoute] of [[1366, '/'], [393, '/reception']]) {
      const options = {viewport: {width, height: 900}, serviceWorkers: 'block'};
      const adminContext = await browser.newContext(options);
      const admin = await adminContext.newPage();
      const created = 'tracking.created.' + width;
      const edited = 'tracking.edited.' + width;
      await login(admin, '/login', 'admin.qa', 'synthetic-admin-password');
      await admin.waitForURL(base + '/');
      if (adminRoute !== '/') await admin.goto(base + adminRoute);
      await admin.waitForFunction(() => document.getElementById('role')?.value === 'ADMINISTRADOR');
      await admin.evaluate(() => window.showUsers());
      await admin.locator('#userForm').waitFor();
      await createUser(admin, created, role);
      await createUser(admin, edited, 'PICKER');
      const profile = admin.locator('#profileForm');
      const openProfile = () => admin.locator('[data-profile="' + edited + '"]').click();
      await openProfile();
      await profile.locator('[name=role]').selectOption(analystRole, {timeout: 5000});
      await profile.getByRole('button', {name: 'Guardar cambios'}).click();
      await profile.waitFor({state: 'hidden'});
      await openProfile();
      assert.equal(await profile.locator('[name=role]').inputValue(), analystRole);
      await profile.locator('[name=first_name]').fill('Prueba');
      await profile.getByRole('button', {name: 'Guardar cambios'}).click();
      await profile.waitFor({state: 'hidden'});
      for (const [username, route, analyst] of [[created, '/tracking', false], [edited, '/login', true]]) {
        const trackingContext = await browser.newContext(options);
        await verifyTracking(trackingContext, username, route, analyst);
        await trackingContext.close();
      }
      await adminContext.close();
      console.log('Tracking admin and lookup passed at ' + width + 'px');
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
