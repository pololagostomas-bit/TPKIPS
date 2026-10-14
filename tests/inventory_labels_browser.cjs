// Synthetic inventory fixture only; output and private logos are never staged.
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],output=path.join(__dirname,'../qa/inventory-labels');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable loopback fixture required');
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'}),results=[];
 try{
  for(const viewport of [{width:1366,height:900},{width:393,height:873},{width:320,height:640},{width:873,height:393}]){
   const context=await browser.newContext({viewport,serviceWorkers:'block',extraHTTPHeaders:{'X-User':'qa.picker','X-Role':'PICKER'}});
   await context.addInitScript(()=>{window.print=()=>{window.qaPrints=(window.qaPrints||0)+1};});
   const page=await context.newPage(),errors=[],requests=[];
   context.on('request',request=>requests.push(request.url()));
   page.on('pageerror',error=>errors.push(error.message));
   await page.goto(base+'/inventory');
   await page.waitForFunction(()=>window.WmsReceptionLabels && document.querySelector('#role').value==='PICKER');
   assert(!requests.some(url=>url.includes('html5-qrcode')||url.includes('bwip-js')),'Heavy engines must load on demand');
   const codes=viewport.width===1366?['ICM/2022-273.a','31EE-02110','NP-NOSTOCK','NP-LONG']:['ICM/2022-273.a','NP-NOSTOCK'];
   for(const code of codes){
    await page.locator('#inventorySearch').fill(code);await page.locator('#inventorySearch').press('Enter');
    await page.waitForFunction(code=>document.querySelector('#inventoryRows .sku')?.textContent===code,code);
    assert.equal(await page.locator('[data-action="generate-barcode"]').count(),0);
    assert.match(await page.locator('#inventoryRows').innerText(),/Data Matrix/);
    const button=page.locator('[data-action="print-label"]');await button.scrollIntoViewIfNeeded();
    const bounds=await button.boundingBox();assert(bounds.height>=44 && bounds.width>=44);
    const opening=page.waitForEvent('popup');await button.click();const popup=await opening;
    popup.on('pageerror',error=>errors.push(error.message));await popup.setViewportSize(viewport);
    await popup.waitForLoadState();await popup.waitForFunction(()=>document.querySelector('#printLabels')?.disabled===false,{},{timeout:5000}).catch(async error=>{
     await popup.screenshot({path:path.join(output,'failed-fit.png'),fullPage:true});
     console.log(await popup.evaluate(()=>({text:document.body.innerText,fields:[...document.querySelectorAll('.sticker,.sticker>*')].map(node=>({name:node.className,height:node.clientHeight,scroll:node.scrollHeight,bounds:node.getBoundingClientRect().toJSON()}))})));
     throw error;
    });
    assert.equal(await popup.locator('.np').innerText(),code);
    assert.equal(await popup.locator('.ov,.customer,.bl').count(),0);
    assert.equal(await popup.locator('.datamatrix').getAttribute('aria-label'),'Data Matrix '+code);
    assert.equal(await popup.locator('#labelWidth').inputValue(),'101.6');
    assert.equal(await popup.locator('#labelHeight').inputValue(),'76.2');
    assert.equal(await popup.locator('.sticker').getAttribute('data-fits'),'true');
    assert.equal(await popup.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    assert.equal(await popup.evaluate(()=>window.qaPrints||0),0,'No automatic print');
    assert(await popup.locator('.brand-logo').evaluate(image=>image.naturalWidth>0));
    if(code==='NP-NOSTOCK')assert.equal(await popup.locator('.location-box').innerText(),'');
    if(code==='ICM/2022-273.a')assert.equal(await popup.locator('.location-box').innerText(),'01-22-B-11-01');
    await popup.screenshot({path:path.join(output,code.replace(/[^A-Z0-9-]/gi,'_')+'-'+viewport.width+'.png'),fullPage:true});
    if(code==='ICM/2022-273.a'){
     await popup.locator('#printLabels').click();assert.equal(await popup.evaluate(()=>window.qaPrints),1);
    }
    await popup.close();
   }
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   await page.evaluate(()=>{
    window.Html5Qrcode=class {
     async start(camera,config,decoded){this.isScanning=true;window.qaCamera={config,decoded}}
     async stop(){this.isScanning=false}clear(){}
    };
   });
   await page.evaluate(()=>startInventoryCamera());
   assert.equal(await page.locator('#inventoryCamera').isVisible(),true);
   assert.deepEqual(await page.evaluate(()=>window.qaCamera.config.qrbox(250,400)),{width:200,height:200});
   const before=requests.filter(url=>url.includes('/api/inventory/catalog')).length;
   await page.evaluate(async()=>{await window.qaCamera.decoded(']d1ICM/2022-273.a');await window.qaCamera.decoded(']d1ICM/2022-273.a')});
   assert.equal(requests.filter(url=>url.includes('/api/inventory/catalog')).length,before+1);
   assert.equal(await page.locator('#inventoryRows .sku').innerText(),'ICM/2022-273.a');
   assert.equal(await page.locator('#inventoryCamera').isVisible(),false);
   await page.evaluate(()=>startInventoryCamera());await page.keyboard.press('Escape');
   assert.equal(await page.locator('#inventoryCamera').isVisible(),false);
   if(viewport.width===1366){
    const items=[];
    for(const code of codes){
     const response=await context.request.get(base+'/api/inventory/label?item_code='+encodeURIComponent(code));
     assert.equal(response.status(),200);items.push((await response.json()).item);
    }
    const opening=page.waitForEvent('popup');await page.evaluate(items=>{
     const target=window.open('','_blank');
     target.document.write(WmsReceptionLabels.documentHtml({},items.map(WmsReceptionLabels.inventoryItem),true));target.document.close();
    },items);
    const batch=await opening;await batch.waitForLoadState();
    for(const orientation of ['landscape','portrait']){
     await batch.locator('[name=labelOrientation][value='+orientation+']').check();
     await batch.waitForFunction(()=>!document.querySelector('#printLabels').disabled);
     await batch.pdf({path:path.join(output,orientation+'.pdf'),preferCSSPageSize:true,printBackground:true});
    }
    await batch.locator('#labelWidth').fill('60');await batch.locator('#labelHeight').fill('60');
    await batch.waitForFunction(()=>document.querySelector('#printLabels').disabled);
    assert.match(await batch.locator('#labelPrintMessage').innerText(),/no cabe/);
    await batch.close();
    const route='**/api/inventory/label?*';
    await page.route(route,route=>route.fulfill({status:403,contentType:'application/json',body:'{"error":"QA sin permiso"}'}));
    const failed=page.waitForEvent('popup');await page.locator('[data-action="print-label"]').click();
    const failedPopup=await failed;await page.waitForFunction(()=>document.querySelector('#inventoryToast').textContent.includes('QA sin permiso'));
    assert(failedPopup.isClosed());await page.unroute(route);
    assert.equal(await page.locator('[data-action="print-label"]').isEnabled(),true);
    await page.evaluate(()=>{window.qaOpen=window.open;window.open=()=>null});
    await page.locator('[data-action="print-label"]').click();
    await page.waitForFunction(()=>document.querySelector('#inventoryToast').textContent.includes('ventanas emergentes'));
    await page.evaluate(()=>{window.open=window.qaOpen});
   }
   assert.deepEqual(errors,[]);results.push({viewport,labels:codes.length,errors});await context.close();
  }
  fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(results,null,2));
  console.log('OK: generic Data Matrix labels, exact SKU, private logos, no stock blank, no OV/client/BL, four viewports, popup errors, physical print layouts');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
