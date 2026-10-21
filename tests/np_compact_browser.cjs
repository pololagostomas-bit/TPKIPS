// Disposable loopback fixtures only. Camera hardware is stubbed, server writes are synthetic.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const [mobile,items]=process.argv.slice(2);
if(![mobile,items].every(url=>/^http:\/\/127\.0\.0\.1:\d+$/.test(url||'')))throw Error('Two loopback fixtures required');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const output=path.join(__dirname,'../qa/np-compact');fs.mkdirSync(output,{recursive:true});
 try{
  const navigation=await browser.newPage({viewport:{width:393,height:873}});
  navigation.on('dialog',d=>d.accept());
  await navigation.goto(items+'/reception');await navigation.waitForFunction(()=>typeof loadDetail==='function');
  await navigation.evaluate(()=>loadDetail(1));
  await navigation.locator('[aria-label="Camiones de la BL"] .back-btn').click();
  await navigation.locator('[data-reception-work]').waitFor({timeout:3000});
  assert.equal(await navigation.locator('.workspace-queue-scrim').isVisible(),false);
  await navigation.close();
  for(const [index,width] of [320,393,1366,873].entries()){
   const page=await browser.newPage({viewport:{width,height:873}}),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   await page.goto(mobile+'/reception');await page.waitForFunction(()=>document.body.classList.contains('mobile-workspace'));
   await page.getByRole('button',{name:'Recepción (BLs)',exact:true}).click();
   await page.locator('[data-reception-work]').waitFor();
   assert.equal(await page.locator('.workspace-rail').isVisible(),false,'No truck rail in reception BLs');
   assert.equal(await page.locator('#content').evaluate(e=>Math.round(e.getBoundingClientRect().left)),0);
   await page.getByRole('button',{name:'Tránsito',exact:true}).click();
   assert.equal(await page.locator('.workspace-rail').isVisible(),true);
   assert.equal(await page.locator('.workspace-rail-label').textContent(),'Camión');
   await page.goto(items+'/reception');await page.waitForFunction(()=>typeof loadDetail==='function');
   await page.evaluate(id=>loadDetail(id),5+index);
   await page.locator('#scanReceptionNp').waitFor();
   assert.equal(await page.locator('.workspace-rail').isVisible(),false,'No truck rail in BL detail');
   assert.equal(await page.locator('#receptionNpFallbackToggle').count(),0);
   assert.equal(await page.locator('[data-camera-for="scanReceptionNp"]').count(),1);
   const camera=await page.locator('#receptionNpCamera').boundingBox(),scan=await page.locator('#scanReceptionNp').boundingBox();
   assert(camera.width>=44&&camera.height>=44&&camera.x>=scan.x&&camera.x+camera.width<=scan.x+scan.width+1);
   assert(camera.y>=scan.y&&camera.y+camera.height<=scan.y+scan.height+1);
   const search=page.locator('#countNpFilter');await search.scrollIntoViewIfNeeded();
   assert.equal(await page.locator('#receptionNpList').getAttribute('open'),null);
   assert((await search.boundingBox()).height<=52);
   await search.fill('NP-001');
   assert.notEqual(await page.locator('#receptionNpList').getAttribute('open'),null);
   assert.equal(await page.locator('#countNpTable tbody tr:visible').count(),2);
   await page.locator('#countNpTable tbody tr:visible').last().locator('[data-np-select]').click();
   await page.waitForFunction(()=>!WmsNpScan.hasPending());
   assert.equal(await page.evaluate(()=>WmsNpScan.status().lastResult?.source),'list');
   assert.equal(await page.locator('#receptionNpQuantity').count(),0);
   assert.equal(await page.locator('#countNpTable tbody tr:visible').last().locator('[data-np-select]').isDisabled(),true);
   const draft=page.locator('#countNpTable tbody tr:visible').first().locator('input[id^="qty-"]');
   await draft.fill('3');await search.fill('');
   assert.equal(await page.locator('#receptionNpList').getAttribute('open'),null);
   await search.fill('NP-001');assert.equal(await draft.inputValue(),'3');
   await search.fill('UNKNOWN');assert.match(await page.locator('#countNpFilterStatus').innerText(),/0 de 4/);
   await search.fill('');
   if(width===320)await page.addStyleTag({content:'#receptionNpScanPanel :is(button,label,input,p,span){font-size:32px!important}'});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
   await page.locator('#scanReceptionNp').evaluate(e=>e.scrollIntoView({block:'center'}));
   await page.screenshot({path:path.join(output,`count-${width}.png`),fullPage:false});
   assert.deepEqual(errors,[]);await page.close();
  }
  console.log('OK compact NP and rail: 4 widths, embedded camera, one search/table, exact choice, no quantity confirmation, draft retention,200% text.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
