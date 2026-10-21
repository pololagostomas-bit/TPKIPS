const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2];
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable loopback fixture required');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  for(const width of [320,393,1366]){
   const page=await browser.newPage({viewport:{width,height:873},serviceWorkers:'block'}),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   await page.goto(base+'/reception');await page.waitForFunction(()=>typeof loadDetail==='function');
   await page.evaluate(()=>loadDetail(13));await page.locator('#scanReceptionNp').waitFor();
   const progress=await page.locator('#receptionNpProgress').innerText();
   assert.match(progress,width===320?/9\/10/:/10\/10/);
   assert.doesNotMatch(progress,/No recibidos|por BL/i);
   if(width===320){
    await page.locator('#scanReceptionNp').fill('NP-00');await page.locator('#scanReceptionNp').press('Enter');
    await page.getByRole('button',{name:'Descartar lectura',exact:true}).waitFor();
    assert.match(await page.locator('#receptionNpProgress').innerText(),/9\/10/);
    await page.evaluate(()=>WmsNpScan.discard());
    await page.locator('#scanReceptionNp').fill('NP-09');await page.locator('#scanReceptionNp').press('Enter');
    await page.waitForFunction(()=>!WmsNpScan.hasPending());
    assert.equal(await page.locator('#receptionNpProgress').innerText(),'NP leidos: 10/10');
    await page.reload();await page.waitForFunction(()=>typeof loadDetail==='function');await page.evaluate(()=>loadDetail(13));
    await page.locator('#scanReceptionNp').waitFor();
    assert.equal(await page.locator('#receptionNpProgress').innerText(),'NP leidos: 10/10');
   }
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
   await page.locator('#receptionNpProgress').evaluate(node=>node.scrollIntoView({block:'center'}));
   fs.mkdirSync(path.join(__dirname,'../qa/np-cumulative'),{recursive:true});
   await page.screenshot({path:path.join(__dirname,`../qa/np-cumulative/after-${width}.png`),fullPage:false});
   assert.deepEqual(errors,[]);await page.close();
  }
  console.log('OK cumulative NP: previous 9 retained, only missing NP accepted, 10/10 persisted, 3 widths.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
