// Synthetic loopback only: support_dhl_server.py PORT picker.
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],output=path.join(__dirname,'../qa/runtime/truck-picker');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Loopback fixture required');
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'}),results=[];
 try{
  for(const viewport of [{width:1366,height:768},{width:393,height:873},{width:320,height:640},{width:873,height:393},{width:683,height:384}]){
   const context=await browser.newContext({viewport,serviceWorkers:'block'}),page=await context.newPage(),errors=[];
   page.on('pageerror',error=>errors.push(error.message));
   page.on('dialog',dialog=>dialog.accept());
   const login=await context.request.post(base+'/api/login',{headers:{'X-WMS-Request':'1'},data:{username:'qa.reader',password:'QA-password-only-123!'}});
   assert.equal(login.status(),200);await page.goto(base+'/reception');
   await page.getByRole('button',{name:'Camiones',exact:true}).click();
   await page.waitForFunction(()=>document.querySelectorAll('#queueRows .queue-row').length===5);
   const input=page.getByRole('combobox',{name:'Buscar o elegir camión'}),toggle=page.getByRole('button',{name:'Mostrar camiones',exact:true});
   assert.equal(await page.locator('#search').isVisible(),false);
   assert.equal(await page.locator('#truckGuideFilter').isVisible(),false);
   assert.equal(await page.locator('#queuePanel input:visible').count(),1);
   const geometry=()=>page.evaluate(()=>{
    const rows=document.getElementById('queueRows'),q=document.getElementById('queuePanel');
    return {controls:['truckPickerInput','createScanTruckButton','toggleTruckHistory','truckQueuePager'].map(id=>{
     const r=document.getElementById(id).getBoundingClientRect();return {id,x:r.x,y:r.y,width:r.width,height:r.height};
    }),display:getComputedStyle(q).display,queueScroll:q.scrollTop,rowsTop:rows.scrollTop,
    rowHeight:rows.clientHeight,rowBottom:rows.getBoundingClientRect().bottom,queueBottom:q.getBoundingClientRect().bottom};
   });
   const before=await geometry();assert.equal(before.display,'flex');assert(before.rowHeight>=70,JSON.stringify(before));
   await page.locator('#queueRows').evaluate(e=>e.scrollTop=e.scrollHeight);
   const after=await geometry();assert(after.rowsTop>0,'Rows must scroll independently');
   assert.deepEqual(after.controls,before.controls);assert.equal(after.queueScroll,0);
   assert(after.rowBottom<=after.queueBottom+1,'Rows fit the drawer');
   await page.getByRole('button',{name:'Siguiente →',exact:true}).click();
   assert.match(await page.locator('#truckQueuePager').innerText(),/Página 2 de/);
   assert.equal((await geometry()).rowsTop,0);
   await toggle.click();await page.getByRole('option',{name:'SCAN-QA-001',exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('#truckGuideFilter').value==='SCAN-QA-001');
   assert.equal(await input.inputValue(),'SCAN-QA-001');
   await page.waitForFunction(()=>document.querySelector('#scanTruckWorkspace')?.dataset.guide==='SCAN-QA-001'&&document.querySelector('#queuePanel').hidden);
   await page.getByRole('button',{name:'Camiones',exact:true}).click();
   await input.fill('QA-054');await page.getByRole('option',{name:'SCAN-QA-054',exact:true}).waitFor();
   assert.equal(await page.locator('#truckGuideFilter').inputValue(),'SCAN-QA-001','Typing preserves the working truck');
   assert.equal(await page.locator('#truckPickerOptions [role=option]').count(),1);
   await input.press('ArrowDown');assert(await input.getAttribute('aria-activedescendant'));
   await input.press('Enter');assert.equal(await page.locator('#truckGuideFilter').inputValue(),'SCAN-QA-054');
   assert.equal(await input.getAttribute('aria-expanded'),'false');
   await page.waitForFunction(()=>document.querySelector('#scanTruckWorkspace')?.dataset.guide==='SCAN-QA-054'&&document.querySelector('#queuePanel').hidden);
   await page.getByRole('button',{name:'Camiones',exact:true}).click();
   await input.fill('NO-SUCH-GUIDE');await page.getByRole('status').filter({hasText:'No hay camiones para esta búsqueda.'}).waitFor();
   await input.press('Enter');assert.equal(await page.locator('#truckGuideFilter').inputValue(),'SCAN-QA-054');
   await input.press('Escape');assert.equal(await input.getAttribute('aria-expanded'),'false');
   await page.route('**/api/truck-guides?*',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"QA unavailable"}'}));
   await input.fill('QA-003');await page.locator('#truckPickerStatus').filter({hasText:'No se pudo buscar'}).waitFor();
   await input.press('Enter');assert.equal(await page.locator('#truckGuideFilter').inputValue(),'SCAN-QA-054');
   await page.unroute('**/api/truck-guides?*');
   // A refused existing leave-work guard must also restore the visible label.
   await page.evaluate(()=>{window.qaConfirm=window.confirmLeaveActiveReceptionWork;window.confirmLeaveActiveReceptionWork=()=>false;});
   await input.fill('QA-003');await page.getByRole('option',{name:'SCAN-QA-003',exact:true}).click();
   assert.equal(await page.locator('#truckGuideFilter').inputValue(),'SCAN-QA-054');
   assert.equal(await input.inputValue(),'SCAN-QA-054');
   await page.evaluate(()=>{window.confirmLeaveActiveReceptionWork=window.qaConfirm;delete window.qaConfirm;});
   await input.fill('');await page.getByRole('option',{name:'Todos los camiones',exact:true}).waitFor();
   await input.press('Tab');assert.equal(await input.getAttribute('aria-expanded'),'false');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   await page.locator('#toast.show').waitFor({state:'hidden'});
   await page.screenshot({path:path.join(output,`fixed-${viewport.width}.png`),fullPage:true});
   await toggle.click();await page.screenshot({path:path.join(output,`picker-${viewport.width}.png`),fullPage:true});
   await input.press('Escape');assert.deepEqual(errors,[]);results.push({viewport,geometry:await geometry()});
   await context.close();
  }
  fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(results,null,2));
  console.log('OK truck picker: fixed controls, list-only scroll, pagination, one search/select, retained truck, keyboard, empty/error/retry, five sizes');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
