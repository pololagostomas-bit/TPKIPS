// Disposable support_partial_count_server.py PORT --no-fr only.
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],output=path.join(__dirname,'../qa/no-fr');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Loopback fixture required');
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  for(const [index,viewport] of [{width:320,height:640},{width:393,height:873},{width:1366,height:768},{width:873,height:393}].entries()){
   for(const partial of [false,true]){
    const context=await browser.newContext({viewport,serviceWorkers:'block'}),page=await context.newPage(),errors=[];
    page.on('pageerror',error=>errors.push(error.message));page.on('dialog',dialog=>dialog.accept());
    const sid=partial?index+7:index+1;
    await page.goto(base+'/reception');await page.waitForSelector('html[data-wms-ui=ready]');
    await page.evaluate(id=>loadDetail(id),sid);await page.locator('#scanReceptionNp').waitFor();
    assert.equal(await page.getByRole('button',{name:/Pasar a EM/}).count(),1,'Missing FR must not hide the physical EM action');
    assert.equal(await page.evaluate(()=>selected.fr_number||''),'');
    for(let n=0;n<(partial?9:10);n++){
     await page.locator('#scanReceptionNp').fill('NP-'+String(n).padStart(2,'0'));
     await page.locator('#scanReceptionNp').press('Enter');await page.waitForFunction(()=>!WmsNpScan.hasPending());
    }
    if(partial)await page.locator('#receptionNpPartial').click();
    else await page.getByRole('button',{name:/Pasar a EM/}).click();
    await page.waitForFunction(()=>selected?.app_status==='EM');
    await page.locator('[data-reception-panel="em"]').waitFor({state:'visible'});
    assert.equal(await page.evaluate(()=>selected.fr_number||''),'');
    assert.equal(await page.evaluate(()=>selected.em_number||''),'');
    assert.equal(await page.evaluate(()=>selected.fr_wait?.pending),true);
    await page.locator('#frPendingNotice').waitFor();
    assert.equal(await page.getByRole('button',{name:'Imprimir etiquetas por NP',exact:true}).isVisible(),true);
    assert.equal(await page.locator('.em-reference-input').count(),0,'No fictitious documentary EM input without FR');
    if(partial){
     assert.equal(await page.evaluate(()=>selected.lines.find(line=>line.np_code==='NP-09').attention_verified_qty),0);
     assert.match(await page.evaluate(()=>selected.lines.find(line=>line.np_code==='NP-09').np_unreceived_reason),/pendiente para otra llegada/);
    }
    await page.locator('[data-reception-panel="em"]').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,`em-${partial?'partial':'full'}-${viewport.width}.png`),fullPage:true});
    await page.getByRole('button',{name:'Continuar con los NP disponibles',exact:true}).click();
    await page.waitForFunction(()=>selected?.app_status==='UBICACION');
    assert.equal(await page.evaluate(()=>selected.em_number||''),'');
    await page.reload();await page.waitForSelector('html[data-wms-ui=ready]');
    await page.evaluate(id=>loadDetail(id),sid);await page.waitForFunction(()=>selected?.app_status==='UBICACION');
    assert.equal(await page.evaluate(()=>selected.fr_wait?.pending),true);
    if(viewport.width===393&&!partial){
     await page.evaluate(async()=>{
      await mutate(shipmentUrl('/location-lines'),{locations:selected.lines.filter(line=>line.attention_verified_qty>0).map(line=>({line_id:line.id,confirmed:true}))});
      await advance('VALIDACION');
     });
     await page.waitForFunction(()=>selected?.app_status==='VALIDACION');
     assert.equal(await page.locator('#frPendingNotice').evaluate(node=>node.classList.contains('error')),true);
     await page.locator('#frPendingNotice').scrollIntoViewIfNeeded();
     await page.screenshot({path:path.join(output,'validation-fr-red-393.png'),fullPage:true});
     await page.evaluate(async()=>{
      await mutate(shipmentUrl('/validation'),{checks:selected.validation_sample_ids.map(id=>({line_id:id,location_checked:true}))});
      await advance('SOLICITUD TRANSFERENCIA','CONFORME');
     });
     await page.waitForFunction(()=>selected?.app_status==='SOLICITUD TRANSFERENCIA');
     assert.equal(await page.evaluate(()=>selected.transfer_assistant_checked),0,'Documentary debt never confirms SAP automatically');
    }
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    assert.deepEqual(errors,[]);await context.close();
   }
  }
  console.log('OK: full/partial no-FR counts -> EM, labels, explicit location, timer, missing NP/reload; four sizes; red validation and existing transfer request without auto SAP, no JS errors');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
