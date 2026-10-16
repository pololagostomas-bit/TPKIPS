// Fresh support_reception_items_server.py only. All accounts and BLs are fictitious.
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],output=path.join(__dirname,'../qa/reception-np-concise');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable loopback fixture required');
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 const headers={'X-User':'demo.admin','X-Role':'ADMINISTRADOR','X-WMS-Request':'1'};
 try{
  for(const viewport of [{width:1440,height:900},{width:393,height:873},{width:360,height:780},{width:320,height:640},{width:873,height:393}]){
   const context=await browser.newContext({viewport,reducedMotion:'reduce'}),page=await context.newPage();
   await context.addInitScript(()=>{if('serviceWorker'in navigator)navigator.serviceWorker.register=async()=>undefined;});
   page.on('pageerror',e=>errors.push(e.message));
   page.on('dialog',dialog=>dialog.accept());
   await context.request.post(base+'/api/account/preferences',{headers,data:{show_guidance:false}});
   await page.goto(base+'/reception');await page.waitForFunction(()=>document.body.classList.contains('hide-guidance'));
   async function scan(code){await page.evaluate(code=>WmsNpScan.review(code),code);}
   async function detail(){await page.evaluate(()=>loadDetail(4));await page.locator('#scanReceptionNp').waitFor();}
   await detail();let writes=0;
   page.on('request',request=>{if(request.method()==='POST'&&/\/receptions\/4\/lines\//.test(request.url()))writes++;});
   await scan('NP-NOSTOCK');
   const result=page.locator('#receptionNpScanResult');
   assert.match(await result.innerText(),/NP-NOSTOCK/);assert.match(await result.innerText(),/Requerido: 5/);
   assert.match(await result.innerText(),/Sin stock/);assert.doesNotMatch(await result.innerText(),/OV |IP |Línea|Ubicación de conteo/);
   assert.equal(await page.locator('#receptionNpQuantity').inputValue(),'5');
   assert.equal(await page.locator('#receptionNpLocation').inputValue(),'');
   assert.equal(await page.locator('label[for=receptionNpLocation]').textContent(),'Ubicación por defecto');
   assert.equal(writes,0,'Explicit correction opens a draft; Enter scanning is tested separately');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   await page.evaluate(()=>document.querySelector('details:has(#countNpTable)').open=true);
   assert.doesNotMatch(await page.locator('#countNpTable').innerText(),/Línea|IP |QA-IP|QA-OV/);
   assert.equal(await page.locator('#countNpTable thead th.help-guidance').first().isVisible(),false);
   await page.screenshot({path:path.join(output,'scan-'+viewport.width+'.png'),fullPage:true});
   // Preserve corrected/saved zeroes; prefill must not reset them to the requirement.
   await page.evaluate(()=>{const line=selected.lines.find(l=>l.np_code==='NP-NOSTOCK');document.getElementById('qty-'+line.id).value='0';});
   await scan('NP-NOSTOCK');assert.equal(await page.locator('#receptionNpQuantity').inputValue(),'0');
   // Repeated NP needs an explicit order choice, never an automatic first match.
   await scan('NP-001');assert.equal(await page.locator('#receptionNpQuantity').count(),0);
   assert.equal(await page.locator('.np-match').count(),2);
   assert.doesNotMatch(await result.innerText(),/Línea/);
   const choice=page.locator('.np-match').nth(1);
   assert.match(await choice.innerText(),/QA-OV-2/);assert.match(await choice.innerText(),/QA-IP-2/);
   assert.doesNotMatch(await choice.innerText(),/Línea/);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   const second=await page.evaluate(()=>selected.lines.find(l=>l.np_code==='NP-001'&&l.ov_number==='QA-OV-2').id);
   const previous=await page.locator('#qty-'+second).inputValue();
   await choice.click();
   assert.equal(await page.locator('#receptionNpQuantity').inputValue(),previous);
   assert.doesNotMatch(await result.innerText(),/QA-OV|QA-IP|Línea/);
   await page.locator('#receptionNpQuantity').fill('4');await page.locator('#receptionNpSave').click();
   await page.waitForFunction(()=>document.querySelector('#receptionNpScanResult')?.textContent==='NP guardado.');
   assert.equal(writes,1);assert.equal(await page.locator('#qty-'+second).inputValue(),'4');
   assert.doesNotMatch(await page.locator('#toast').innerText(),/línea|Línea/);
   await page.evaluate(id=>document.getElementById('qty-'+id).value='1.5',second);
   await page.locator('[data-save-physical-review]').click();
   assert.match(await page.locator('#toast').innerText(),/enteros/);assert.equal(writes,1);
   await page.evaluate(id=>document.getElementById('qty-'+id).value='',second);
   await page.locator('[data-save-physical-review]').click();
   assert.match(await page.locator('#toast').innerText(),/enteros/);assert.equal(writes,1);
   await page.evaluate(id=>document.getElementById('qty-'+id).value='4',second);
   // The existing user preference persists and restores the same optional data.
   await page.evaluate(()=>showAccount());await page.locator('#showGuidancePreference').check();
   await page.locator('#saveGuidancePreference').click();
   await page.waitForFunction(()=>document.querySelector('#guidancePreferenceStatus')?.textContent==='Preferencia guardada.');
   await page.reload();await page.waitForFunction(()=>document.body.classList.contains('guidance-enabled'));
   await detail();await scan('NP-NOSTOCK');
   assert.equal(await page.locator('.np-reference-info').isVisible(),true);
   assert.match(await result.innerText(),/Línea/);
   await page.evaluate(()=>document.querySelector('details:has(#countNpTable)').open=true);
   assert.equal(await page.locator('#countNpTable thead th.help-guidance').first().isVisible(),true);
   await page.evaluate(()=>showAccount());await page.locator('#showGuidancePreference').uncheck();
   await page.locator('#saveGuidancePreference').click();
   await page.waitForFunction(()=>document.querySelector('#guidancePreferenceStatus')?.textContent==='Preferencia guardada.');
   for(const id of [2,3]){
    await page.evaluate(id=>loadDetail(id),id);
    const table=page.locator(id===2?'.em-reference-card table':'#locationNpTable');
    assert.equal(await table.first().locator('th.help-guidance').first().isVisible(),false);
    if(id===3)assert.match(await table.locator('thead').innerText(),/Ubicación por defecto/i);
   }
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   if(viewport.width===393){
    await detail();await scan('NP-NOSTOCK');
    await page.addStyleTag({content:'#receptionNpScanPanel :is(label,input,button,summary,p,span){font-size:24px!important;line-height:1.5!important}'});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    await page.locator('#receptionNpSave').scrollIntoViewIfNeeded();
    const button=await page.locator('#receptionNpSave').boundingBox();
    const nav=await page.locator('#bottomNav').boundingBox();
    assert.ok(button.x>=0&&button.x+button.width<=viewport.width+1);
    assert.ok(button.y+button.height<=nav.y+1,'Save is not hidden behind mobile navigation');
    await page.screenshot({path:path.join(output,'large-text-393.png')});
   }
   await context.close();console.log('Concise NP, defaults, explicit duplicate choice and saved preference OK at '+viewport.width);
  }
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
