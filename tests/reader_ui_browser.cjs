// Run against a fresh support_mobile_server.py only. Microsoft and mail are mocked.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const base = process.argv[2];
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '')) throw Error('Disposable loopback fixture required');
const output = path.join(__dirname,'../qa/reader-ui');
const asset = name => fs.readFileSync(path.join(__dirname,'../frontend/templates/'+name+'.html'),'utf8');
const stamp = '2026-10-11T10:00:00-05:00';
const cloud = {configured:true,authorized:true,pending:false,automatic_enabled:true,interval_seconds:300,
  connection:{state:'verified',verified_at:stamp},monitor:{state:'waiting',heartbeat_at:stamp,next_check_at:stamp},
  sources:[{label:'Importaciones',source_type:'importation',health:'updated',state:'updated',filename:'QA-Importaciones.xlsx',checked_at:stamp,success_at:stamp,updated_at:stamp},
    {label:'Facturas',source_type:'accounting',health:'authorization_required',pending:'Microsoft solicita una nueva autorizacion.'}]};
const settings={sender:'qa@example.invalid',sender_name:'QA',to:['qa@example.invalid'],cc:[],excluded_sheets:['HISTORICO'],interval_minutes:60,daily_time:'10:00',weekdays:[0,1,2,3,4],enabled:false,subject:'Reporte QA',new_subject:'Nuevos QA',body:'Texto de prueba',new_intro:'Nuevos casos'};
const alerts={settings,state:{snapshot:{cases:[]},checked_at:stamp},history:[],mail_authorized:true,worker_enabled:false};
(async()=>{
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:process.env.WMS_QA_BROWSER_CHANNEL || 'msedge'});
  const errors=[], results=[];
  async function testContext(viewport) {
    const context=await browser.newContext({viewport,reducedMotion:'reduce'});
    // Playwright's serviceWorkers:block init script throws inside a sandboxed
    // iframe. Disable registration only in the top-level disposable fixture.
    await context.addInitScript(()=>{
      if(window===window.top && 'serviceWorker' in navigator)
        navigator.serviceWorker.register=async()=>undefined;
    });
    return context;
  }
  try {
    for (const viewport of (process.env.WMS_QA_SCAN_ONLY ? [] : [{width:1440,height:900},{width:393,height:873},{width:375,height:812},{width:360,height:780},{width:873,height:393}])) {
      const context=await testContext(viewport), page=await context.newPage();
      page.on('pageerror',error=>errors.push(error.message));
      page.on('dialog',dialog=>dialog.accept('Correccion de prueba de interfaz'));
      await page.route(base+'/cloud-connection',route=>route.fulfill({contentType:'text/html',body:asset('cloud-connection')}));
      await page.route(base+'/purchase-alerts',route=>route.fulfill({contentType:'text/html',body:asset('purchase-alerts')}));
      for(const name of ['cloud-connection.js','cloud-connection.css','purchase-alerts.js','purchase-alerts.css']) {
        await page.route(base+'/assets/'+name,route=>route.fulfill({contentType:name.endsWith('.js')?'application/javascript':'text/css',body:fs.readFileSync(path.join(__dirname,'../frontend/static',name),'utf8')}));
      }
      await page.route(base+'/api/cloud-connection/**',route=>route.fulfill({json:route.request().url().includes('/history')?{items:[],has_more:false,next_cursor:null}:cloud}));
      await page.route(base+'/api/purchase-alerts/**',route=>route.fulfill({json:alerts}));
      async function capture(name) {
        await page.waitForTimeout(90);
        const geometry=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,
          tiny:[...document.querySelectorAll('button')].filter(button=>button.checkVisibility()&&!button.closest('[inert]')&&button.getBoundingClientRect().height<43.5).map(button=>button.textContent.trim())}));
        assert.ok(geometry.scroll<=geometry.width+1,name+': horizontal overflow');
        assert.deepEqual(geometry.tiny,[],name+': small touch controls');
        results.push({view:name,width:viewport.width,height:viewport.height});
        await page.screenshot({path:path.join(output,`${name}-${viewport.width}x${viewport.height}.png`)});
      }
      await page.goto(base+'/reception');await page.waitForSelector('body.reader-ui');await page.waitForSelector('.home-stats,.home-tile,.dashboard-stats');
      await capture('reception-home');
      await page.evaluate(()=>showMyWork());await page.waitForSelector('#workSearch');await capture('reception-work');
      await page.locator('#workSearch').fill('QA-MOBILE-3');await page.waitForFunction(()=>document.querySelectorAll('[data-work-row]').length===1);
      await page.locator('[data-work-open]').click();await page.waitForSelector('.wms-admin-panel');
      assert.ok(await page.locator('#rewindStatus').isVisible(),'Admin state controls remain visible');
      await capture('bl-admin');
      for (let id=1;id<=8;id++) {
        await page.evaluate(id=>loadDetail(id),id);await page.waitForSelector('.mobile-stage-select',{state:'attached'});
        await capture('bl-stage-'+id);
        const tabs=await page.locator('[data-reception-tab]').count();
        for(let index=0;index<tabs;index++) {
          await page.evaluate(index=>document.querySelectorAll('[data-reception-tab]')[index].click(),index);
          assert.equal(await page.locator('[data-reception-panel]:not([hidden])').count(),1);
        }
      }
      for(const [name,action,ready] of [['profile','showAccount','.profile-fields'],['tools','showMore','#adminTools'],['users','showUsers','#userForm'],['workload','showWorkload','#workloadFilters'],['mail','showNotifications','.management-head'],['transfers','showPendingDeliveries','.tablewrap']]) {
        await page.evaluate(action=>window[action](),action);await page.waitForSelector(ready);await capture('reception-'+name);
      }
      await page.evaluate(()=>showMore());
      await page.getByRole('button',{name:/Nueva BL \/ AWB/}).click();await page.waitForSelector('#newModal:not([hidden])');
      await page.waitForFunction(()=>document.activeElement?.id==='newBl');
      assert.equal(await page.locator('#newModal').getAttribute('role'),'dialog');
      assert.equal(await page.locator('header.top').evaluate(node=>node.inert),true,'Background inert');
      assert.equal(await page.locator('#newBl').evaluate(node=>{const b=node.getBoundingClientRect();return node.contains(document.elementFromPoint(b.left+3,b.top+b.height/2));}),true,'Rail must not cover modal fields');
      await capture('new-bl-modal');
      await page.locator('#newModal button[type=submit]').focus();await page.keyboard.press('Tab');
      assert.equal(await page.locator('#newModal').evaluate(node=>node.contains(document.activeElement)),true,'Tab stays in modal');
      await page.keyboard.press('Escape');await page.waitForSelector('#newModal',{state:'hidden'});
      await page.waitForFunction(()=>!document.querySelector('header.top').inert);
      assert.equal(await page.locator('header.top').evaluate(node=>node.inert),false);
      assert.match(await page.evaluate(()=>document.activeElement.textContent),/Nueva BL/,'Return focus to opener');
      await page.evaluate(()=>openReport());await page.waitForSelector('#reportModal:not([hidden])');await page.waitForSelector('#reportContent .card');await capture('reception-report');
      await page.keyboard.press('Escape');
      await page.evaluate(()=>document.getElementById('dailyDataButton').click());await page.waitForSelector('#dailyDialog[open]');await capture('daily-cuts');await page.locator('#dailyClose').click();
      await page.goto(base+'/');await page.waitForSelector('body.reader-ui');await page.waitForTimeout(250);
      await capture('dispatch-home');await page.evaluate(()=>loadDetail('QA-OV-1'));await page.waitForSelector('.wms-admin-panel');await capture('dispatch-order');
      const dispatchTabs=await page.locator('.detail-tabs button').count();
      for(let index=0;index<dispatchTabs;index++){await page.evaluate(index=>document.querySelectorAll('.detail-tabs button')[index].click(),index);await capture('dispatch-tab-'+index);}
      await page.evaluate(()=>showMyWork());await page.waitForSelector('.work-global-summary');await capture('dispatch-work');
      await page.goto(base+'/inventory');await page.waitForSelector('body.reader-ui');await page.waitForFunction(()=>document.querySelector('#user')?.value);
      await page.evaluate(()=>loadInventory('QA-NP-0'));await page.waitForSelector('#inventoryRows tr');await capture('inventory-stock');
      await page.evaluate(()=>showRequestForm());await page.waitForSelector('#requestFormCard:not(.hidden)');await capture('inventory-request');
      await page.goto(base+'/cloud-connection');
      await page.waitForSelector('body.reader-ui').catch(async error=>{console.error('Cloud fixture',page.url(),await page.locator('body').innerText(),errors);throw error;});
      await page.waitForFunction(()=>document.querySelector('#connectionStatus').textContent.includes('comprobado'));await capture('cloud-status');
      await page.locator('#historyTab').click();await page.waitForSelector('#historyPanel:not([hidden])');await capture('cloud-history');
      await page.goto(base+'/purchase-alerts');await page.waitForFunction(()=>!document.querySelector('#save').disabled);await capture('purchase-alerts');
      await page.locator('[name=subject]').fill('QA modificado');assert.equal(await page.locator('#send').isDisabled(),true,'Dirty form cannot send');
      await page.goto(base+'/login');await page.waitForSelector('body.reader-ui');await capture('login');
      await page.route(base+'/api/login',route=>route.fulfill({status:401,contentType:'text/plain',body:'Unauthorized'}));
      await page.locator('#username').fill('qa.invalid');await page.locator('#password').fill('qa-invalid-password');await page.locator('[type=submit]').click();
      await page.waitForFunction(()=>document.activeElement?.id==='error');assert.match(await page.locator('#error').innerText(),/usuario y la contraseña/);await capture('login-error');
      await context.close();
      console.log(`Views OK at ${viewport.width}x${viewport.height}`);
    }
    // A delayed administration response must never replace a newer profile screen.
    const recoveryContext=await testContext({width:393,height:873});
    const page=await recoveryContext.newPage();page.on('pageerror',error=>errors.push(error.message));
    await page.goto(base+'/reception');await page.waitForSelector('body.reader-ui');
    await page.route(base+'/api/users',async route=>{await new Promise(resolve=>setTimeout(resolve,450));await route.continue();});
    await page.evaluate(()=>{showUsers();return showAccount();});await page.waitForSelector('.profile-fields');await page.waitForTimeout(600);
    assert.equal(await page.locator('.profile-fields').count(),1,'Late users response cannot replace profile');
    await page.unroute(base+'/api/users');
    await page.evaluate(()=>showUsers());await page.waitForSelector('#userForm');await page.locator('[data-profile]').first().click();
    await page.waitForSelector('.user-modal.open');await page.keyboard.press('Escape');await page.waitForSelector('.user-modal.open',{state:'hidden'});
    // Scanner: later successful readings must not hide earlier failures or change their BL.
    await page.getByRole('button',{name:'Tránsito',exact:true}).click();await page.locator('#createScanTruckButton').click();await page.getByRole('button',{name:'Por BL',exact:true}).click();await page.locator('#scanTruckBlCode').fill('QA-TRUCK-MOBILE');await page.locator('#scanTruckBlCode').press('Enter');await page.locator('#scanTruckPackageCode').waitFor();
    await page.waitForFunction(()=>document.querySelector('#scanReceivingBl')?.textContent==='QA-TRUCK-MOBILE'&&!WmsTruckScan.hasPending());
    let fail=true; const readings=[];
    const originalShipment=await page.evaluate(()=>scannerSelectedShipmentId);
    await page.route(base+'/api/receptions/truck-guide/scan-package',async route=>{
      const data=route.request().postDataJSON();
      readings.push(data);
      if(data.package_code==='QA-FAILED'&&fail){await new Promise(resolve=>setTimeout(resolve,150));await route.fulfill({status:503,json:{error:'Conexion de prueba interrumpida'}});}else await route.continue();
    });
    await page.locator('#scanTruckPackageCode').fill('QA-FAILED');await page.locator('#scanTruckPackageCode').press('Enter');
    await page.locator('#scanTruckPackageCode').fill('QA-SUCCESS');await page.locator('#scanTruckPackageCode').press('Enter');
    await page.waitForFunction(()=>!WmsTruckControls.hasPending()&&document.querySelector('#scanTotal')?.textContent==='1');
    await page.locator('[data-retry-reading]:not([disabled])').waitFor();
    assert.match(await page.locator('#scanFailures').innerText(),/QA-FAILED/);
    assert.equal(await page.locator('#finalizeScanTruckButton').isDisabled(),true);
    assert.equal(await page.evaluate(()=>WmsTruckScan.hasPending()),true);
    await page.screenshot({path:path.join(output,'scanner-failure-393.png')});
    await page.evaluate(()=>WmsTruckScan.changeBl());await page.locator('#scanBlEntryTitle').click();await page.locator('#scanTruckBlCode').fill('QA-MOBILE-0');await page.locator('#scanTruckBlCode').press('Enter');await page.locator('#scanTruckPackageCode').waitFor();
    await page.waitForFunction(()=>document.querySelector('#scanReceivingBl')?.textContent==='QA-MOBILE-0');
    assert.notEqual(await page.evaluate(()=>scannerSelectedShipmentId),originalShipment);
    fail=false;await page.locator('[data-retry-reading]').click();await page.waitForFunction(()=>document.querySelector('#scanTotal').textContent==='2'&&!WmsTruckScan.hasPending());
    assert.equal(readings.at(-1).shipment_id,originalShipment,'Retry belongs to original BL, not current selection');
    assert.equal(await page.locator('#scanFailures').isVisible(),false);
    await page.evaluate(async id=>{WmsTruckScan.changeBl(id);await WmsTruckScan.useReviewedBl();},originalShipment);
    await page.locator('#scanTruckPackageCode').fill('QA-SUCCESS');await page.locator('#scanTruckPackageCode').press('Enter');await page.waitForFunction(()=>!WmsTruckScan.hasPending());
    assert.equal(await page.locator('#scanTotal').innerText(),'2','Duplicate retry cannot inflate packages');
    await page.locator('#finalizeScanTruckButton').click();await page.locator('#saveTruckLocationsButton').waitFor();
    await page.screenshot({path:path.join(output,'scanner-location-393.png')});
    await page.locator('#scanGeneralLocation').fill('QA-TEMP');await page.locator('#saveTruckLocationsButton').click();
    await page.getByRole('button',{name:'Continuar recepción'}).waitFor({timeout:5000}).catch(async error=>{console.error('Location QA',await page.locator('#content').innerText());throw error;});
    await page.getByRole('button',{name:'Continuar recepción'}).click();
    await page.getByRole('button',{name:/Volver al cami[oó]n/}).click();await page.locator('#scanTruckWorkspace').waitFor();
    assert.match(await page.locator('#scanTruckWorkspace').innerText(),/QA-TRUCK-MOBILE/);
    await page.evaluate(async()=>{$('user').value='qa.receiver';$('role').value='ASISTENTE_RECEPCION';await loadDetail(2);});
    assert.equal(await page.locator('.wms-admin-panel').count(),0,'Assistant does not get administrative corrections');
    const forbidden=await page.evaluate(async()=>{const response=await api('/api/receptions/2/rewind',{method:'POST',body:JSON.stringify({status:'PROGRAMADO',reason:'Intento sin permiso de QA'})});return response.status;});
    assert.equal(forbidden,403);
    assert.deepEqual(errors,[],'Browser runtime errors');
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({views:results.length,results,errors,scanner:'retry, duplicate, finalize, locate, return',navigation:'late users response discarded'},null,2));
    console.log(`OK: ${results.length} responsive views, modal keyboard/focus, role controls, navigation races, login errors and scanner recovery`);
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
