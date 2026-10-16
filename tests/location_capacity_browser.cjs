const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],privateMaster=process.argv[3],output=path.join(__dirname,'../qa/location-capacity');
const runTag=Date.now().toString(36).toUpperCase();
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable loopback fixture required');
(async()=>{
 fs.mkdirSync(output,{recursive:true});const browser=await chromium.launch({headless:true,channel:'msedge'}),results=[];
 const viewports=[{width:1366,height:900},{width:393,height:873},{width:375,height:812},{width:320,height:640},
  {width:768,height:1024},{width:820,height:900},{width:821,height:900},{width:1440,height:900},{width:873,height:393}];
 try{
  for(const viewport of viewports){
   const context=await browser.newContext({viewport,serviceWorkers:'block',extraHTTPHeaders:{'X-User':'qa.admin','X-Role':'ADMINISTRADOR'}});
   const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
   await context.addInitScript(()=>{window.print=()=>window.qaPrinted=(window.qaPrinted||0)+1});
   await page.goto(base+'/locations');await page.locator('.capacity-select').first().waitFor();
   assert.equal(await page.locator('.capacity-select').count(),50);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   assert.match(await page.locator('#capacityWarnings').innerText(),/sin registro activo/);
   assert.equal(await page.locator('#capacityWarnings').isVisible(),true);
   for(const label of (await page.locator('.capacity-select').all()).slice(0,3))await label.check();
   const opening=page.waitForEvent('popup');await page.locator('#capacityPrint').click();const popup=await opening;
   popup.on('pageerror',error=>errors.push(error.message));await popup.setViewportSize(viewport);
   await popup.waitForFunction(()=>document.querySelector('#printLocationLabels')?.disabled===false);
   assert.equal(await popup.locator('.location-sheet').count(),2);
   assert.equal(await popup.locator('.location-label').count(),3);
   assert.equal(await popup.locator('.empty-half').count(),1);
   assert.deepEqual(await popup.locator('.location-label strong').allTextContents(),['01-01-A-01-01','01-02-A-01-01','01-03-A-01-01']);
   assert(await popup.locator('.triton-mark').evaluateAll(nodes=>nodes.every(node=>node.naturalWidth>0)));
   assert(await popup.locator('.location-label').evaluateAll(nodes=>nodes.every(node=>node.dataset.fits==='true')));
   assert.equal(await popup.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   assert.equal(await popup.evaluate(()=>window.qaPrinted||0),0);
   await popup.screenshot({path:path.join(output,'labels-'+viewport.width+'.png'),fullPage:true});
   if(viewport.width===1366){
    await popup.pdf({path:path.join(output,'odd-three.pdf'),preferCSSPageSize:true,printBackground:true});
    await popup.locator('#printLocationLabels').click();assert.equal(await popup.evaluate(()=>window.qaPrinted),1);
   }
   await popup.close();await page.locator('#capacityClear').click();
   await page.locator('.capacity-select').first().check();await page.locator('#capacityCopies').fill('2');
   const copiesOpening=page.waitForEvent('popup');await page.locator('#capacityPrint').click();const copies=await copiesOpening;
   await copies.waitForFunction(()=>document.querySelector('#printLocationLabels')?.disabled===false);
   assert.equal(await copies.locator('.location-sheet').count(),1);assert.equal(await copies.locator('.location-label').count(),2);
   if(viewport.width===1366)await copies.pdf({path:path.join(output,'two-copies.pdf'),preferCSSPageSize:true,printBackground:true});
   await copies.close();await page.locator('#capacityClear').click();await page.locator('#capacityCopies').fill('1');
   await page.locator('#capacityImport summary').first().click();
   const code='QA-UPLOAD-'+viewport.width+'-'+runTag,buffer=Buffer.from('Ubicacion,Zona,Rack,Estado\n'+code+',ZONA QA,R1,HABILITADA');
   await page.locator('#capacityFile').setInputFiles({name:'maestro-qa.csv',mimeType:'text/csv',buffer});
   await page.locator('#capacityReason').fill('Carga inicial de posiciones de prueba');
   await page.locator('#capacityPreviewButton').click();await page.locator('#capacitySaveButton').waitFor({state:'visible'});
   await page.waitForFunction(()=>!document.querySelector('#capacitySaveButton').disabled);
   const before=await(await context.request.get(base+'/api/locations?search='+code)).json();assert.equal(before.total,0);
   await page.locator('#capacitySaveButton').click();await page.waitForFunction(()=>document.querySelector('#capacityPreview').textContent.includes('Guardado en servidor'));
   const saved=await(await context.request.get(base+'/api/locations?search='+code)).json();assert.equal(saved.items[0].code,code);
   await page.locator('#capacitySearch').fill(code);await page.locator('#capacitySearch').press('Enter');
   await page.waitForFunction(code=>document.querySelector('#capacityRows .code')?.textContent===code,code);
   await page.locator('[data-edit]').click();await page.locator('#capacityEditState').selectOption('BLOQUEADA');
   await page.locator('#capacityEditReason').fill('Bloqueo preventivo de prueba');
   await page.locator('#capacityEditForm [type=submit]').click();await page.waitForFunction(()=>!document.querySelector('#capacityEditDialog').open);
   await page.waitForFunction(()=>document.querySelector('#capacityRows .state')?.textContent==='BLOQUEADA');
   await page.locator('[data-history]').click();await page.locator('#capacityHistory').getByText('Bloqueo preventivo de prueba',{exact:true}).waitFor();
   await page.keyboard.press('Escape');
   await page.locator('#capacitySearch').fill(']d101-01-A-01-01');await page.locator('#capacitySearch').press('Enter');
   await page.waitForFunction(()=>document.querySelector('#capacityRows .code')?.textContent==='01-01-A-01-01');
   const target=await page.locator('.check-control').last().boundingBox();assert(target.width>=44&&target.height>=44);
   if(viewport.width===1366){
    await page.locator('#capacitySearch').fill('01-');await page.locator('#capacitySearch').press('Enter');
    await page.waitForFunction(()=>document.querySelectorAll('.capacity-select').length===50);
    await page.locator('#capacitySelectPage').check();await page.locator('#capacityNext').click();
    await page.waitForFunction(()=>document.querySelector('#capacityPage').textContent.startsWith('51-'));
    await page.locator('#capacitySelectPage').check();await page.locator('#capacityCopies').fill('3');assert(await page.locator('#capacityPrint').isDisabled());
    await page.locator('#capacityCopies').fill('2');
    const largeOpening=page.waitForEvent('popup');await page.locator('#capacityPrint').click();const large=await largeOpening;
    await large.waitForFunction(()=>document.querySelector('#printLocationLabels')?.disabled===false);
    assert.equal(await large.locator('.location-label').count(),200);assert.equal(await large.locator('.location-sheet').count(),100);
    await large.close();await page.locator('#capacityClear').click();
    await page.locator('#capacityCopies').fill('1');await page.locator('.capacity-select').first().check();
    assert.equal(await page.locator('#capacityPrint').isDisabled(),false);
    await page.route('**/api/locations?*',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"QA sin conexion"}'}));
    await page.locator('#capacitySearchForm button').click();await page.locator('#capacityStatus').getByText('QA sin conexion',{exact:true}).waitFor();
    assert.equal(await page.locator('#capacityMetrics dd').allTextContents().then(values=>values.every(value=>value==='-')),true);
    assert.equal(await page.locator('#capacityPrint').isDisabled(),true,'No printing from a stale failed query');
    await page.unroute('**/api/locations?*');await page.locator('#capacitySearchForm button').click();await page.locator('.capacity-select').first().waitFor();
    await page.goto(base+'/inventory');await page.getByRole('link',{name:'Ubicaciones y capacidad',exact:true}).click();
    await page.waitForURL(base+'/locations');await page.locator('.capacity-select').first().waitFor();
    await page.goto(base+'/reception');await page.locator('#module,#moduleSelector').selectOption('ubicaciones');
    await page.waitForURL(base+'/locations');await page.locator('.capacity-select').first().waitFor();
   }
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   await page.screenshot({path:path.join(output,'module-'+viewport.width+'.png'),fullPage:true});
   if([320,393].includes(viewport.width)){
    await page.evaluate(()=>{const sizes=[...document.querySelectorAll('body *')].map(node=>[node,parseFloat(getComputedStyle(node).fontSize)]);for(const[node,size]of sizes)node.style.fontSize=(size*2)+'px'});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'No page overflow at 200% text');
    const clipped=await page.locator('h1,h2,p,dt,dd,label,button').evaluateAll(nodes=>nodes.filter(n=>n.checkVisibility()&&n.scrollWidth>n.clientWidth+2).map(n=>n.tagName));
    assert.deepEqual(clipped,[],'Essential text not clipped at 200%');
    await page.screenshot({path:path.join(output,'text-200-'+viewport.width+'.png'),fullPage:true});
   }
   assert.deepEqual(errors,[]);results.push({viewport,errors});await context.close();
  }
  const picker=await browser.newContext({serviceWorkers:'block',extraHTTPHeaders:{'X-User':'qa.picker','X-Role':'PICKER'}});
  const page=await picker.newPage();await page.goto(base+'/locations');await page.locator('.capacity-select').first().waitFor();
  assert.equal(await page.locator('#capacityImport').isVisible(),false);assert.equal(await page.locator('[data-edit]').count(),0);
  assert.equal(await page.locator('#capacityModule option[value="/reception"]').count(),0);
  assert.equal((await picker.request.post(base+'/api/locations/preview',{data:{text:'QA-DENIED'}})).status(),403);
  await picker.close();
  if(privateMaster){
   const context=await browser.newContext({viewport:{width:393,height:873},serviceWorkers:'block',extraHTTPHeaders:{'X-User':'qa.admin','X-Role':'ADMINISTRADOR'}});
   const page=await context.newPage();await page.goto(base+'/locations');await page.locator('.capacity-select').first().waitFor();
   await page.locator('#capacityImport summary').first().click();await page.locator('#capacityFile').setInputFiles(privateMaster);
   await page.locator('#capacityReason').fill('Validacion de maestro privado en base QA desechable');
   let response=page.waitForResponse(r=>r.url().endsWith('/api/locations/preview')&&r.request().method()==='POST');
   await page.locator('#capacityPreviewButton').click();const preview=await(await response).json();
   assert(preview.count>5000,'Private large workbook must not be truncated');
   await page.waitForFunction(()=>!document.querySelector('#capacitySaveButton').disabled);
   response=page.waitForResponse(r=>r.url().endsWith('/api/locations/import')&&r.request().method()==='POST');
   await page.locator('#capacitySaveButton').click();assert.equal((await response).status(),200);
   await page.waitForFunction(()=>document.querySelector('#capacityPreview').textContent.includes('Guardado en servidor'));
   const first=preview.sample[0],url=base+'/api/locations?search='+encodeURIComponent(first.code);
   let data=await(await context.request.get(url)).json();assert(data.summary.registered>=preview.count);
   for(const key of ['warehouse','aisle','rack','level','bin'])assert.equal(data.items[0][key],first[key]??'');
   await page.locator('#capacitySearch').fill(first.code);await page.locator('#capacitySearch').press('Enter');
   await page.waitForFunction(code=>document.querySelector('#capacityRows .code')?.textContent===code,first.code);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   await page.locator('[data-edit]').first().click();assert.equal(await page.locator('#capacityEditAisle').inputValue(),first.aisle);
   await page.locator('#capacityEditState').selectOption('BLOQUEADA');await page.locator('#capacityEditReason').fill('Prueba privada de conservacion de dimensiones');
   await page.locator('#capacityEditForm [type=submit]').click();await page.waitForFunction(()=>!document.querySelector('#capacityEditDialog').open);
   data=await(await context.request.get(url)).json();for(const key of ['warehouse','aisle','rack','level','bin'])assert.equal(data.items[0][key],first[key]??'');
   await page.locator('#capacityFile').setInputFiles(privateMaster);response=page.waitForResponse(r=>r.url().endsWith('/api/locations/preview'));
   await page.locator('#capacityPreviewButton').click();const again=await(await response).json();
   assert.equal(again.unchanged,preview.count);assert.equal(again.added,0);assert.equal(again.changed,0);
   await page.screenshot({path:path.join(output,'private-master-mobile.png'),fullPage:true});
   console.log('OK: private workbook full upload, dimensions retained, state correction and idempotent reupload ('+preview.count+' positions)');
   await context.close();
  }
  fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(results,null,2));
  console.log('OK: nine viewports, persisted master, audit, roles, AIM, 2-up labels, odd batch, copies, 200-label job and read-error recovery');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
