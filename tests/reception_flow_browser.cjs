// support_reception_flow_server.py only; synthetic data and local users.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],out=path.join(__dirname,'../qa/runtime/reception-flow');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Loopback required');
const headers={'Content-Type':'application/json','X-WMS-Request':'1'};
(async()=>{
 fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  for(const width of [320,393,1366,873,683]){
   for(const username of ['qa.reader','qa.assistant','qa.auxiliary']){
    const context=await browser.newContext({viewport:{width,height:width===873?393:width===683?384:873}}),page=await context.newPage(),errors=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
    await context.addInitScript(()=>{if('serviceWorker'in navigator)navigator.serviceWorker.register=async()=>undefined;});
    assert.equal((await context.request.post(base+'/api/login',{headers,data:{username,password:'QA-password-only-123!'}})).status(),200);
    await page.goto(base+'/reception');await page.waitForFunction(()=>Boolean(window.WmsReceptionFlow));
    for(let id=1;id<=8;id++){
     await page.evaluate(id=>loadDetail(id),id);
     await page.locator('.reception-record-header').waitFor();
     assert.equal(await page.locator('.reception-record-status').count(),1);
     assert.match(await page.locator('.reception-record-status').innerText(),/Trabajo[\s\S]*Documentos/);
     assert.equal(await page.locator('#receptionAdministration').count(),username==='qa.reader'?1:0);
     await page.locator('.reception-record-links').getByRole('button',{name:'Documentos',exact:true}).click();
     assert.notEqual(await page.locator('#receptionDocuments').getAttribute('open'),null,`Documentos width=${width} user=${username} id=${id}`);
     assert.equal(await page.locator('#receptionDocuments').isVisible(),true);
     if(id!==1){
      await page.locator('.reception-record-links').getByRole('button',{name:'Entregas',exact:true}).click();
      assert.notEqual(await page.locator('#receptionDeliveries').getAttribute('open'),null);
      await page.locator('.reception-record-links').getByRole('button',{name:'Historial',exact:true}).click();
      assert.equal(await page.locator('#receptionTimeline li').count(),1);
     }else assert.match(await page.locator('.reception-record-status').innerText(),/Llegada pendiente/);
     const selector=page.locator('.mobile-stage-select select');
     assert.ok(await selector.isVisible()||await page.locator('.reception-tabs').isVisible());
     if(username!=='qa.reader'&&id>=4){
      const previous=page.locator('[data-reception-tab="sistema"]');
      if(await selector.isVisible()){
       const index=await page.locator('[data-reception-tab]').evaluateAll(nodes=>nodes.findIndex(n=>n.dataset.receptionTab==='sistema'));
       await selector.selectOption(String(index));
      }else await previous.click();
      assert.match(await page.locator('#receptionTaskTitle').innerText(),/Consulta/);
      assert.equal(await page.locator('[data-reception-panel=sistema] input[id^="qty-"]:enabled').count(),0);
     }
     assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Page reflows');
     if([3,5,7].includes(id)&&username==='qa.assistant'){
      await page.evaluate(()=>document.getElementById('content').scrollTop=0);
      await page.screenshot({path:path.join(out,`state-${id}-${width}.png`),fullPage:true});
     }
    }
    assert.deepEqual(errors,[]);await context.close();
   }
  }
  // A failed write retains the live fields and does not advance the stage.
  const context=await browser.newContext(),page=await context.newPage();
  page.on('dialog',d=>d.accept());
  await context.request.post(base+'/api/login',{headers,data:{username:'qa.reader',password:'QA-password-only-123!'}});
  await page.goto(base+'/reception');await page.waitForFunction(()=>Boolean(window.WmsReceptionFlow));
  await page.evaluate(()=>loadDetail(3));
  await page.locator('#receptionNpList summary').click();
  const field=page.locator('input[id^="qty-"]').first();await field.fill('7');
  await page.route('**/api/receptions/3/status',r=>r.fulfill({status:409,contentType:'application/json',body:JSON.stringify({error:'QA conflicto guardado'})}),{times:1});
  await page.evaluate(async()=>{try{await mutate(shipmentUrl('/status'),{status:'EM'})}catch{}});
  assert.equal(await field.inputValue(),'7');assert.match(await page.locator('#receptionSaveState').innerText(),/QA conflicto/);
  assert.equal(await field.isEnabled(),true);
  let release,posts=0;const hold=new Promise(resolve=>release=resolve);
  await page.route('**/api/receptions/3/status',async r=>{posts++;await hold;await r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({id:3,attention_id:3,app_status:'EM'})});});
  await page.evaluate(()=>{window.saveOne=mutate(shipmentUrl('/status'),{status:'EM'});window.saveTwo=mutate(shipmentUrl('/status'),{status:'EM'}).catch(()=>{});});
  await page.waitForFunction(()=>receptionMutationPending);assert.equal(await field.isDisabled(),true);
  await page.evaluate(()=>loadDetail(4));release();await page.evaluate(()=>Promise.all([window.saveOne,window.saveTwo]));
  assert.equal(posts,1);assert.equal(await page.evaluate(()=>selected.id),4);
  await context.close();console.log('OK: eight states, three roles, five viewports, documents/history, readonly stages, failed save and late single-flight write');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
