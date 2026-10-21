// Disposable loopback fixture only. Presentation changes do not write reception data.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2];
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable loopback fixture required');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const output=path.join(__dirname,'../qa/reception-display');fs.mkdirSync(output,{recursive:true});
 const headers={'X-User':'demo.admin','X-Role':'ADMINISTRADOR','X-WMS-Request':'1'};
 try{
  for(const width of [320,393,1366,873]){
   const context=await browser.newContext({viewport:{width,height:873}}),page=await context.newPage(),errors=[],writes=[];
   page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
   page.on('request',r=>{if(r.method()==='POST'&&/\/api\/receptions\//.test(r.url()))writes.push(r.url());});
   await context.request.post(base+'/api/account/preferences',{headers,data:{show_guidance:false}});
   await page.goto(base+'/reception');await page.waitForFunction(()=>document.body.classList.contains('hide-guidance'));
   await page.evaluate(()=>loadDetail(5));await page.locator('#scanReceptionNp').waitFor();
   await page.locator('#countNpFilter').fill('NP-001');
   const spacing=await page.locator('#countNpFilter').evaluate(e=>({
    textStart:e.getBoundingClientRect().left+parseFloat(getComputedStyle(e).paddingLeft),
    iconRight:e.parentElement.querySelector('svg').getBoundingClientRect().right
   }));
   assert(spacing.textStart>=spacing.iconRight+8,'Search text must clear the magnifier');
   const rows=page.locator('#countNpTable tbody tr:visible');
   assert.equal(await rows.count(),2);
   assert.deepEqual(await rows.locator('[data-count-ov]').allTextContents(),['QA-OV-1','QA-OV-2']);
   assert.equal(await rows.locator('[data-count-ov]:visible').count(),2);
   assert.equal(await page.locator('.np-order-reference').count(),0);
   assert.doesNotMatch(await page.locator('#countNpTable').innerText(),/QA-IP|L[ií]nea/);
   assert.equal(await page.locator('#receptionNpScanPanel .eyebrow').count(),0);
   assert.equal(await page.locator('#receptionNpFallbackToggle').count(),0);
   assert.equal(await page.locator('[data-camera-for="scanReceptionNp"]').count(),1);
   assert.equal(await page.locator('[data-save-physical-review]').count(),1);
   await rows.first().scrollIntoViewIfNeeded();
   await page.screenshot({path:path.join(output,'list-'+width+'.png'),fullPage:false});
   await page.evaluate(()=>{
    selected=structuredClone(selected);
    const line=selected.lines.find(l=>l.np_code==='NP-001');
    line.ov_number='S/N';line.customer_name='';renderDetail();
   });
   await page.locator('#countNpFilter').fill('NP-001');
   assert.deepEqual(await rows.locator('[data-count-ov]').allTextContents(),['Stock','QA-OV-2']);
   assert.equal(await page.evaluate(()=>selected.lines.find(l=>l.np_code==='NP-001').ov_number),'S/N');
   await page.evaluate(()=>WmsNpScan.review('NP-001'));
   assert.deepEqual(await page.locator('.np-match strong').allTextContents(),['Stock','OV QA-OV-2']);
   assert.doesNotMatch(await page.locator('#receptionNpScanResult').innerText(),/S\/N|Sin OV|QA-IP|L[ií]nea/);
   await page.screenshot({path:path.join(output,'orders-'+width+'.png'),fullPage:false});
   const opening=page.waitForEvent('popup');
   await page.evaluate(async()=>{
    await WmsReceptionLabels.loadEngine();
    const items=WmsReceptionLabels.items(selected);
    const popup=window.open('','_blank');popup.document.write(WmsReceptionLabels.documentHtml(selected,items));popup.document.close();
   });
   const popup=await opening;await popup.setViewportSize({width,height:873});
   await popup.waitForFunction(()=>!document.querySelector('#printLabels').disabled);
   assert.equal(await popup.locator('.ov-value').first().innerText(),'Stock');
   assert.equal(await popup.locator('.customer>strong').first().innerText(),'Para stock');
   assert.equal(await popup.locator('.ov-value').nth(1).innerText(),'QA-OV-2');
   assert.match(await popup.locator('.customer>strong').nth(1).innerText(),/Cliente dos/);
   assert.equal(await popup.locator('.quantity-value').first().innerText(),'5');
   assert.equal(await popup.locator('.datamatrix').count(),3);
   await popup.screenshot({path:path.join(output,'labels-'+width+'.png'),fullPage:true});await popup.close();
   await context.request.post(base+'/api/account/preferences',{headers,data:{show_guidance:true}});
   await page.reload();await page.waitForFunction(()=>document.body.classList.contains('guidance-enabled'));
   await page.evaluate(()=>loadDetail(5));await page.locator('#countNpFilter').fill('NP-001');
   assert.equal(await rows.locator('[data-count-ov]:visible').count(),2);
   assert.match(await page.locator('#countNpTable').innerText(),/QA-IP/);
   await page.evaluate(()=>WmsNpScan.review('NP-001'));
   assert.match(await page.locator('#receptionNpScanResult').innerText(),/QA-IP/);
   if(width===320)await page.addStyleTag({content:'#receptionNpScanPanel :is(button,label,input,summary,p,span,td){font-size:32px!important}'});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
   assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
   await context.close();console.log('OK OV always visible, guidance, Stock/Para stock, exact labels, no operational writes at '+width);
  }
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
