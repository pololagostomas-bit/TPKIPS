// Entirely intercepted synthetic page: no server, session or external request.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const base = 'http://127.0.0.1:50688';
const output = path.join(root, 'qa/cloud-powerbi');
const stamp = '2026-10-15T10:00:00-05:00';
const cloud = {
  configured:true, authorized:true, pending:false, automatic_enabled:true, interval_seconds:300,
  connection:{state:'verified',resource:'microsoft_graph_excel',verified_at:stamp},
  monitor:{state:'waiting',heartbeat_at:stamp,next_check_at:stamp},
  powerbi_stock:{state:'not_implemented',connector_implemented:false,stock_connected:false,
    configuration:{report:'declared',workspace:'missing',dataset:'missing'},required_warehouse:'01',
    warehouse_filter_verified:false,refresh_schedule:{state:'unknown'},last_refresh_at:null,
    action:'Falta validar espacio de trabajo, modelo, permisos y filtro del almacen 01.'},
  registered_stock_import:{import_id:1,cutoff_at:stamp,source_kind:'excel',powerbi_verified:false},
  sources:[{label:'Importaciones',source_type:'importation',health:'healthy',state:'unchanged',
    filename:'QA-Importaciones-archivo-sintetico-con-nombre-largo.xlsx',checked_at:stamp,
    success_at:stamp,updated_at:stamp,cutoff_at:stamp,source_modified_at:stamp},
    {label:'Stock Excel',source_type:'stock',health:'not_configured',pending:'Falta enlace Excel'}]
};
const item = {id:1,source_type:'importation',state:'unchanged',checked_at:stamp,started_at:stamp,
  origin:'automatic',duration_ms:100,filename:'QA-Importaciones.xlsx',cutoff_at:stamp,
  detail:'Sin cambios en el archivo.',rows_count:null};

(async () => {
  fs.mkdirSync(output,{recursive:true});
  const browser = await chromium.launch({headless:true,channel:process.env.WMS_QA_BROWSER_CHANNEL || 'msedge'});
  const errors = [], results = [], unexpected = [];
  try {
    for (const viewport of [{width:320,height:640},{width:393,height:873},
      {width:1366,height:768},{width:873,height:393}]) {
      const context = await browser.newContext({viewport,reducedMotion:'reduce'});
      const page = await context.newPage();
      await page.clock.install();
      let status = cloud, failure = null, historyForbidden = false, delayOnce = false, release;
      let notifyDelay;
      const delayed = new Promise(resolve => {notifyDelay = resolve;});
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/*', async route => {
        const request = route.request(), url = new URL(request.url());
        if (url.origin !== base || request.method() !== 'GET') {
          unexpected.push(request.method()+' '+url.pathname);return route.abort();
        }
        if (url.pathname === '/cloud-connection')
          return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'frontend/templates/cloud-connection.html'),'utf8')});
        if (url.pathname.startsWith('/assets/')) {
          const name = path.basename(url.pathname);
          if (!/^[a-z-]+\.(js|css)$/.test(name)) throw Error('Unexpected asset');
          return route.fulfill({contentType:name.endsWith('.js')?'application/javascript':'text/css',
            body:fs.readFileSync(path.join(root,'frontend/static',name),'utf8')});
        }
        if (url.pathname === '/api/cloud-connection/status') {
          if (delayOnce) {
            delayOnce = false;
            const prior = status;
            await new Promise(resolve => {release = resolve;notifyDelay();});
            return route.fulfill({json:prior});
          }
          return route.fulfill(failure || {json:status});
        }
        if (url.pathname === '/api/cloud-connection/history')
          return route.fulfill(historyForbidden ? {status:403,json:{error:'Private upstream text'}} : {json:{items:[item],next_before:null}});
        if (url.pathname === '/api/account') return route.fulfill({json:{show_guidance:false}});
        if (url.pathname === '/api/dhl-tracking/status') return route.fulfill({json:{state:'disabled',
          calls_today:0,daily_budget:0,cached_guides:0,queued_guides:0,refresh_hours:6,prefetch_limit:0}});
        unexpected.push(url.pathname);return route.abort();
      });
      await page.goto(base+'/cloud-connection');
      await page.waitForFunction(() => document.querySelector('#connectionStatus').textContent.includes('Graph comprobado'));
      assert.match(await page.locator('#powerbiStatus').innerText(), /sin conectar/);
      assert.match(await page.locator('#powerbiFacts').innerText(), /Sin comprobar/);
      assert.match(await page.locator('#interval').innerText(), /archivos Excel: cada 5 minutos/);
      assert.match(await page.locator('#sources').innerText(), /Fecha del corte/);
      assert.equal(await page.locator('#sync').isEnabled(),true);
      status={...cloud,powerbi_stock:{...cloud.powerbi_stock,state:'updated',connector_implemented:true,
        automatic_enabled:true,interval_seconds:300,stock_connected:true,warehouse_filter_verified:true,
        api_access:'verified',checked_at:stamp,success_at:stamp,last_refresh_at:stamp,cutoff_at:stamp,
        next_check_at:stamp,inventory_skus:2,positive_bins:3,action:''}};
      await page.locator('#refresh').click();
      await page.waitForFunction(()=>document.querySelector('#powerbiStatus').textContent.includes('conectado'));
      assert.match(await page.locator('#powerbiFacts').innerText(),/5 minutos/);
      assert.match(await page.locator('#powerbiFacts').innerText(),/Ultimo refresh del modelo/);
      status={...status,powerbi_stock:{...status.powerbi_stock,state:'error',detail:'Se conserva el corte anterior.',action:'Revisa la conexion.'}};
      await page.locator('#refresh').click();
      await page.waitForFunction(()=>document.querySelector('#powerbiStatus').textContent.includes('Error'));
      assert.match(await page.locator('#powerbiAction').innerText(),/conserva/);
      status=cloud;await page.locator('#refresh').click();
      await page.waitForFunction(()=>document.querySelector('#powerbiStatus').textContent.includes('sin conectar'));

      async function geometry(name) {
        const measured = await page.evaluate(() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
          small:[...document.querySelectorAll('button')].filter(button => button.checkVisibility() &&
            button.getBoundingClientRect().height < 43.5).map(button => button.id)}));
        assert.ok(measured.scroll <= measured.width+1, name+': horizontal overflow');
        assert.deepEqual(measured.small,[],name+': touch target');
        await page.screenshot({path:path.join(output,`${name}-${viewport.width}x${viewport.height}.png`)});
      }
      await geometry('status');
      await page.locator('#powerbiConnection').scrollIntoViewIfNeeded();
      await geometry('powerbi');

      failure = {status:503,json:{error:'Servidor de prueba no disponible.'}};
      await page.locator('#refresh').click();
      await page.waitForFunction(() => !document.querySelector('#refresh').disabled);
      assert.match(await page.locator('#connectionStatus').innerText(), /Estado sin actualizar/);
      assert.doesNotMatch(await page.locator('#connectionStatus').innerText(), /comprobado/);
      assert.equal(await page.locator('#sync').isDisabled(),true);
      failure = null;
      await page.locator('#refresh').click();
      await page.waitForFunction(() => !document.querySelector('#refresh').disabled);
      assert.match(await page.locator('#connectionStatus').innerText(), /Graph comprobado/);
      assert.equal(await page.locator('#sync').isEnabled(),true);

      await page.locator('#historyTab').click();
      await page.waitForSelector('#history details');
      await page.locator('#history summary').click();
      assert.equal(await page.locator('#history details').getAttribute('open'),'');
      historyForbidden = true;
      await page.locator('#historySource').selectOption('stock');
      await page.waitForFunction(() => document.querySelector('#historyMessage').textContent.includes('No tienes permiso'));
      assert.doesNotMatch(await page.locator('#historyMessage').innerText(), /Private/);
      historyForbidden = false;
      await page.locator('#historySource').selectOption('');
      await page.waitForSelector('#history li');
      await page.locator('#statusTab').click();

      delayOnce = true;
      await page.clock.runFor(15000);
      await delayed;
      status = {...cloud,connection:{state:'authorization_required'}};
      await page.locator('#refresh').click();
      await page.waitForFunction(() => !document.querySelector('#refresh').disabled);
      release();
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
      assert.match(await page.locator('#connectionStatus').innerText(), /nueva autorizacion/);
      assert.equal(await page.locator('#sync').isDisabled(),true);

      if (viewport.width === 320) {
        await page.evaluate(() => {
          const sizes = [...document.querySelectorAll('body,body *')].map(element =>
            [element,parseFloat(getComputedStyle(element).fontSize)*2]);
          sizes.forEach(([element,size]) => {element.style.fontSize=size+'px';});
        });
        await page.locator('#powerbiConnection').scrollIntoViewIfNeeded();
        await geometry('text200');
      }
      results.push({viewport,verified:true});
      await context.close();
    }
    assert.deepEqual(errors,[],'Browser exceptions');
    assert.deepEqual(unexpected,[],'Unexpected request or mutation');
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({results,errors,unexpected},null,2));
    console.log(JSON.stringify({viewports:results.length,errors,unexpected,output}));
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
