// Disposable support_reception_items_server.py only. Never use an operational database.
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],output=path.join(__dirname,'../qa/np-stability');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable loopback fixture required');
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 try{
  for(const [index,[width,height]] of [[1366,768],[393,873],[375,812],[320,640],[873,393]].entries()){
   const firstId=14+index*4;
   const context=await browser.newContext({viewport:{width,height},reducedMotion:'reduce'}),page=await context.newPage();
   await context.addInitScript(()=>{if('serviceWorker'in navigator)navigator.serviceWorker.register=async()=>undefined;});
   page.on('pageerror',error=>errors.push(error.message));page.on('dialog',dialog=>dialog.accept());
   const writes=[];
   page.on('request',request=>{if(request.method()==='POST'&&/\/api\/receptions\/\d+\/lines\//.test(request.url()))writes.push({url:request.url(),body:request.postDataJSON()});});
   await page.route(new RegExp('/api/receptions/'+firstId+'(?:\\?|$)'),async route=>{
    const response=await route.fetch(),data=await response.json();
    data.lines.push({...data.lines[0],id:String(data.lines[0].id)});
    await route.fulfill({response,json:data});
   });
   await page.goto(base+'/reception');await page.waitForFunction(()=>typeof loadDetail==='function');
   const load=async id=>{await page.evaluate(id=>loadDetail(id),id);await page.locator('#scanReceptionNp').waitFor();};
   const scan=async code=>{await page.locator('#scanReceptionNp').fill(code);await page.locator('#scanReceptionNp').press('Enter');};
   const settled=()=>page.waitForFunction(()=>!WmsNpScan.hasPending());
   await load(firstId);
   assert.equal(await page.locator('#countNpTable tbody tr').count(),4,'Repeated source ID cannot duplicate a rendered row');
   assert.equal(await page.evaluate(()=>new Set([...document.querySelectorAll('#countNpTable input[id^="qty-"]')].map(node=>node.id)).size),4);
   await scan('NP-001');await page.locator('.np-match').first().waitFor();
   const choices=page.locator('.np-match');assert.equal(await choices.count(),2);
   assert.match(await choices.nth(0).innerText(),/OV QA-OV-1/);assert.match(await choices.nth(1).innerText(),/OV QA-OV-2/);
   assert.equal(await page.locator('#receptionNpQuantity').count(),0);
   for(const choice of await choices.all()){
    await choice.scrollIntoViewIfNeeded();const box=await choice.boundingBox();
    assert(box.height>=48&&box.x>=0&&box.x+box.width<=width+1,'Choice is a reachable touch target');
   }
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   await page.screenshot({path:path.join(output,`choices-${width}.png`),fullPage:true});
   await scan(']D1NP-001');await scan('NP-NOSTOCK');
   assert.equal(writes.length,0,'Pending duplicate callbacks must not create extra writes');
   await choices.filter({hasText:'QA-OV-2'}).focus();await page.keyboard.press('Enter');await settled();
   assert.equal(writes.length,2,'Chosen order and a different queued NP save once each');
   assert.match(await page.locator('#receptionNpProgress').innerText(),/1\/3/);
   await scan(']D1NP-001');await choices.waitFor();assert.equal(writes.length,2);
   await choices.click();await settled();assert.equal(writes.length,3);
   assert.equal(await page.locator('.np-match').count(),0,'Remaining OV saved after explicit selection');
   await scan('NP-001');await settled();assert.equal(writes.length,3);
   await page.reload();await page.waitForFunction(()=>typeof loadDetail==='function');await load(firstId);
   assert.match(await page.locator('#receptionNpProgress').innerText(),/2\/3/);

   await load(firstId+1);const before=writes.length;
   assert.equal(await page.locator('#countNpTable tbody tr').count(),3);
   await scan('NP-001');await settled();assert.equal(writes.length,before+1);
   assert.equal(await page.locator('.np-match').count(),0,'Another arrival is not an ambiguous order');
   await scan('NP-HIST');await page.getByRole('button',{name:'Descartar lectura'}).waitFor();
   assert.match(await page.locator('#receptionNpIssue').innerText(),/otra llegada/);
   assert.equal(writes.length,before+1,'Foreign arrival is rejected locally, not posted');
   await page.getByRole('button',{name:'Descartar lectura'}).click();await settled();

   await load(firstId+2);await scan('NP-001');await choices.first().waitFor();
   assert.equal(await choices.count(),2);assert.match(await choices.filter({hasText:'Sin OV'}).innerText(),/Requerido: 5/);
   if(width===393){
    await page.addStyleTag({content:'#receptionNpScanPanel :is(input,button,p,span,strong){font-size:32px!important;line-height:1.5!important}'});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    await choices.filter({hasText:'Sin OV'}).scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,'choices-200-percent.png')});
   }
   const blankOvId=await page.evaluate(()=>selected.lines.find(line=>line.np_code==='NP-001'&&!line.ov_number).id);
   const beforeBlank=writes.length;await choices.filter({hasText:'Sin OV'}).click();await settled();
   assert(writes.at(-1).url.endsWith('/'+blankOvId));assert.equal(await page.locator('#receptionNpQuantity').count(),0);
   await scan('NP-001');await choices.waitFor();assert.equal(writes.length,beforeBlank+1);
   await choices.click();await settled();assert.equal(writes.length,beforeBlank+2);

   await load(firstId+3);await scan('NP-001');await choices.first().waitFor();
   assert.equal(await choices.count(),2,'Different source IDs remain separate even with identical business references');
   assert.match(await choices.nth(0).innerText(),/Pedido 1/);assert.match(await choices.nth(1).innerText(),/Pedido 2/);
   await page.getByRole('button',{name:'Descartar lectura'}).click();await settled();
   assert.equal(await choices.count(),0,'Discarded choices cannot remain actionable');
   await load(34+index);const beforeZero=writes.length;
   await scan('NP-001');await settled();assert.equal(writes.length,beforeZero+1);
   assert.equal(await choices.count(),0,'Zero balance from a previous arrival cannot create a false order choice');
   await context.close();console.log(`NP stability, duplicate IDs, arrival scope, OV/without OV and keyboard OK ${width}x${height}`);
  }
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
