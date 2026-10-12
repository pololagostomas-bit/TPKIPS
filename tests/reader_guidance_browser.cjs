// Disposable support_mobile_server.py only; saves preferences, never production data.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const base = process.argv[2];
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '')) throw Error('Disposable loopback fixture required');
const output = path.join(__dirname, '../qa/reader-guidance');
(async () => {
  fs.mkdirSync(output, {recursive:true});
  const browser = await chromium.launch({headless:true, channel:'msedge'});
  const errors = [], results = [];
  const headers = {'Content-Type':'application/json','X-WMS-Request':'1','X-User':'demo.admin','X-Role':'ADMINISTRADOR'};
  try {
    for (const viewport of [{width:1440,height:900},{width:393,height:873},{width:375,height:812},{width:360,height:780},{width:873,height:393}]) {
      const context = await browser.newContext({viewport,reducedMotion:'reduce',colorScheme:'dark'});
      await context.addInitScript(() => {if (window === window.top && 'serviceWorker' in navigator) navigator.serviceWorker.register = async () => undefined;});
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      page.on('dialog', dialog => dialog.accept());
      await context.request.post(base+'/api/account/preferences',{headers,data:{show_guidance:false}});
      async function capture(name) {
        await page.waitForTimeout(90);
        const data = await page.evaluate(() => ({
          width:innerWidth,scroll:document.documentElement.scrollWidth,
          visibleHelp:[...document.querySelectorAll('.help-guidance:not(.error):not(.warning):not(.success):not([role=alert])')].filter(node => node.checkVisibility()).map(node => node.textContent),
          text:document.querySelector('#content,#detail,#inventoryApp')?.innerText || ''
        }));
        assert.deepEqual(data.visibleHelp, [], name+': tutorial leaked');
        assert.ok(data.scroll <= data.width+1, name+': horizontal overflow');
        assert.doesNotMatch(data.text, /Revisión José|Carga manual del MVP|app\.py|Selecciona una BL\/AWB|Busca o elige un registro/);
        results.push({name,viewport});
        await page.screenshot({path:path.join(output, name+'-'+viewport.width+'.png')});
      }
      await page.goto(base+'/reception');
      await page.waitForSelector('.home-welcome');
      await page.waitForFunction(() => document.body.classList.contains('hide-guidance'));
      await capture('home');
      await page.getByRole('button',{name:'Tránsito',exact:true}).click();
      await page.waitForSelector('[data-transit-overview]');
      assert.equal(await page.locator('.workspace-credits').count(),0);
      assert.equal(await page.locator('#createScanTruckButton').count(),1);
      await page.evaluate(() => closeQueue());
      await capture('transit');
      await page.evaluate(() => showMyWork()); await page.waitForSelector('#workSearch'); await capture('work');
      await page.evaluate(() => loadDetail(3)); await page.waitForSelector('#rewindStatus');
      assert.equal(await page.locator('#rewindStatus').isVisible(),true);
      for (const tab of await page.locator('[data-reception-tab]').all()) {
        await tab.evaluate(node => node.click());
        await capture('bl-'+await tab.getAttribute('data-reception-tab'));
      }
      for (const [action,ready] of [['showMore','#adminTools'],['showUsers','#userForm'],['showWorkload','#workloadFilters'],['showNotifications','.management-head'],['showPendingDeliveries','.tablewrap']]) {
        await page.evaluate(action => window[action](),action); await page.waitForSelector(ready); await capture(action);
      }
      await page.evaluate(() => showMore());
      await page.getByRole('button',{name:'Cortes Excel',exact:true}).click();
      await page.waitForSelector('#dailyDialog[open]'); await capture('cuts'); await page.locator('#dailyClose').click();
      await page.evaluate(() => openReport()); await page.waitForSelector('#reportContent .card'); await capture('report'); await page.keyboard.press('Escape');
      await page.evaluate(() => showAccount()); await page.waitForSelector('#showGuidancePreference');
      assert.equal(await page.locator('.workspace-credits').count(),1);
      await page.locator('#showGuidancePreference').check(); await page.locator('#saveGuidancePreference').click();
      await page.waitForFunction(() => document.querySelector('#guidancePreferenceStatus')?.textContent === 'Preferencia guardada.');
      assert.equal(await page.locator('#guidancePreferenceStatus').isVisible(),true,'Saved feedback remains visible');
      await page.evaluate(() => showMore());
      assert.equal(await page.locator('#adminTools .help-guidance').first().isVisible(),true,'Opt-in restores descriptions');
      await page.reload(); await page.waitForFunction(() => document.body.classList.contains('guidance-enabled'));
      await page.goto(base+'/inventory'); await page.waitForSelector('body.reader-ui.guidance-enabled');
      assert.equal(await page.locator('#stockTitle + p').isVisible(),true,'Preference follows the user across modules');
      await context.request.post(base+'/api/account/preferences',{headers,data:{show_guidance:false}});
      await page.reload(); await page.waitForSelector('body.reader-ui.hide-guidance'); await capture('inventory');
      await page.locator('#inventorySearch').fill('QA-NP-0'); await page.locator('button.search').click();
      await page.waitForSelector('#inventoryRows .sku'); await capture('inventory-result');
      await page.locator('#inventorySearch').fill('a'); await page.locator('button.search').click();
      assert.equal(await page.locator('#searchNotice.error').isVisible(),true,'Validation never hidden');
      // Defensive CSS: status, validation and errors cannot be hidden by an old help class.
      await page.evaluate(() => {
        const probe=document.createElement('div');probe.id='guidanceProbe';
        probe.innerHTML='<p class="section-note" role="status">Estado operativo</p><p class="help-guidance error">Error</p><p class="help-guidance warning">Alerta</p><p class="help-guidance success">Guardado</p><p class="help-guidance" role="alert">Bloqueo</p>';
        document.body.append(probe);
      });
      for (const node of await page.locator('#guidanceProbe p').all()) assert.equal(await node.isVisible(),true);
      await page.evaluate(() => document.getElementById('guidanceProbe').remove());
      await page.goto(base+'/'); await page.waitForSelector('.home-welcome'); await capture('dispatch');
      await page.evaluate(() => loadDetail('QA-OV-1')); await page.waitForSelector('.wms-admin-panel'); await capture('dispatch-detail');
      if(viewport.width===375){
        await page.addStyleTag({content:'body :is(p,span,strong,label,button,input,select,summary,dt,dd){font-size:24px!important}'});
        await capture('dispatch-large-text');
        const labels=await page.locator('#bottomNav .nav-item>span').evaluateAll(nodes=>nodes.map(node=>{
          const label=node.getBoundingClientRect(),button=node.parentElement.getBoundingClientRect();
          return label.left>=button.left-1&&label.right<=button.right+1&&label.bottom<=button.bottom+1;
        }));
        assert.ok(labels.every(Boolean),'Scaled navigation labels fit their own buttons');
        const clearance=await page.evaluate(()=>({layout:document.querySelector('main.layout').getBoundingClientRect().bottom,nav:document.getElementById('bottomNav').getBoundingClientRect().top}));
        assert.ok(clearance.layout<=clearance.nav+1,'Scaled navigation does not obscure the workspace');
        const header=await page.evaluate(()=>({brand:document.querySelector('header.top .brand').getBoundingClientRect().right,module:document.querySelector('header.top .toolbar').getBoundingClientRect().left}));
        assert.ok(header.brand<=header.module+1,'Scaled brand and module selector do not overlap');
      }
      await context.close();
      console.log('Guidance and essential controls OK at '+viewport.width+'x'+viewport.height);
    }
    const context=await browser.newContext({viewport:{width:375,height:812},reducedMotion:'reduce'});
    await context.addInitScript(() => {if(window===window.top && 'serviceWorker' in navigator)navigator.serviceWorker.register=async()=>undefined;});
    const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
    for(const name of ['cloud-connection','purchase-alerts']){
      await page.route(base+'/'+name,handler=>handler.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(__dirname,'../frontend/templates/'+name+'.html'),'utf8')}));
      for(const extension of ['js','css'])await page.route(base+'/assets/'+name+'.'+extension,handler=>handler.fulfill({contentType:extension==='js'?'application/javascript':'text/css',body:fs.readFileSync(path.join(__dirname,'../frontend/static/'+name+'.'+extension),'utf8')}));
      await page.route(base+'/api/'+name+'/**',handler=>handler.fulfill({status:503,json:{error:'Servicio externo no disponible en QA'}}));
    }
    for(const route of ['/cloud-connection','/purchase-alerts']){
      const accountRequests=[];
      await page.route(base+'/api/account',async handler=>{
        accountRequests.push(handler.request().url());
        await new Promise(resolve=>setTimeout(resolve,200));
        await handler.fulfill({json:{show_guidance:false}});
      });
      await page.goto(base+route);await page.waitForSelector('body.reader-ui');
      await page.waitForTimeout(300);
      assert.equal(accountRequests.length,1,'Standalone preference is loaded once');
      assert.equal(await page.locator('body.hide-guidance').count(),1);
      // The mock only concerns optional preferences. Real unavailable services stay visible.
      assert.equal(await page.locator('#message').isVisible(),true);
      await page.unroute(base+'/api/account');
    }
    await page.route(base+'/api/account',handler=>handler.fulfill({status:503,json:{error:'Preferencia no disponible'}}));
    await page.goto(base+'/inventory');await page.waitForSelector('body.reader-ui');
    assert.equal(await page.locator('#stockTitle + p').isVisible(),false,'No optional-content flash on preference failure');
    await context.close();
    assert.deepEqual(errors,[],'Runtime errors');
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({views:results.length,results,errors},null,2));
    console.log('OK: '+results.length+' views, preference persistence, cross-module behavior and visible operational feedback');
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
