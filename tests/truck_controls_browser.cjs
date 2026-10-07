// Fresh support_truck_controls_server.py only. All writes are disposable.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],scanner=process.argv[3]==='scanner';
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Loopback QA only');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH});
 try{
  for(const viewport of [{width:1366,height:900},{width:375,height:812},{width:320,height:640}]){
   const page=await browser.newPage({viewport}), errors=[],posts=[];
   let accept=true;
   page.on('pageerror',e=>errors.push(e.message));
   page.on('dialog',d=>accept?d.accept():d.dismiss());
   page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});
   await page.goto(base+'/reception');
   await page.getByRole('button',{name:'Tránsito',exact:true}).click();
   await page.locator(scanner?'#createScanTruckButton':'#createManualTruckButton').click();
   await page.locator('#truckStageControls').waitFor();
   const guide=await page.locator('#truckGuideFilter').inputValue(), code='QA-CONTROLS-'+viewport.width;
   accept=false;
   await page.locator('[data-truck-action="cancel"]').click();
   assert.equal(await page.locator('#truckGuideFilter').inputValue(),guide);
   assert.equal(posts.some(url=>url.endsWith('/cancel')),false,'Rejected cancellation must not write');
   accept=true;
   if(scanner){
    await page.locator('#scanTruckBlCode').fill(code);await page.locator('#scanTruckBlCode').press('Enter');
    await page.locator('#scanTruckPackageCode').waitFor();
    for(const suffix of ['A','B']){
     await page.locator('#scanTruckPackageCode').fill(code+'-'+suffix);
     await page.locator('#scanTruckPackageCode').press('Enter');
    }
    await page.waitForFunction(()=>$('scanTotal')?.textContent==='2'&&!WmsTruckScan.hasPending());
    await page.locator('[data-truck-action="back"]').click();
    await page.locator('#scanTruckBlCode').waitFor();
    assert.equal(await page.locator('#scanTotal').innerText(),'2','Changing BL preserves package scans');
    await page.locator('#scanTruckBlCode').fill(code);await page.locator('#scanTruckBlCode').press('Enter');
    await page.locator('#scanTruckPackageCode').waitFor();
    // A long history must scroll internally while the field and footer stay usable.
    await page.evaluate(()=>{const details=document.querySelector('.scan-details');details.open=true;
      details.insertAdjacentHTML('beforeend',Array.from({length:30},(_,i)=>'<p>QA history '+i+'</p>').join(''));});
    const directory=path.join(__dirname,'..','qa','runtime','truck-controls');fs.mkdirSync(directory,{recursive:true});
    await page.screenshot({path:path.join(directory,'scanner-arrival-'+viewport.width+'.png')});
    const bounds=await page.locator('#scanTruckWorkspace').boundingBox();
    const input=await page.locator('#scanTruckPackageCode').boundingBox();
    const finish=await page.locator('#finalizeScanTruckButton').boundingBox();
    assert.ok(bounds.y>=0&&bounds.y+bounds.height<=viewport.height,'Scanner fits viewport');
    assert.ok(input.y>=bounds.y&&input.y+input.height<=bounds.y+bounds.height,'Package field visible');
    assert.ok(finish.y>=bounds.y&&finish.y+finish.height<=bounds.y+bounds.height,'Stage action pinned');
    const height=bounds.height;
    await page.locator('.scan-task').evaluate(node=>node.scrollTop=node.scrollHeight);
    assert.equal(Math.round((await page.locator('#scanTruckWorkspace').boundingBox()).height),Math.round(height),'History cannot resize scanner');
    await page.locator('#finalizeScanTruckButton').click();
   }else{
    await page.locator('#truckDirectBlCode').fill(code);await page.locator('#truckDirectSearch').click();
    await page.locator('[data-select-bl]').click();await page.locator('#truckDirectPackages').fill('2');
    await page.locator('#truckDirectAdd').click();
    await page.getByRole('button',{name:'Iniciar llegada',exact:true}).click();
    await page.locator('[data-truck-action="back"]').click();
    await page.getByRole('button',{name:'Iniciar llegada',exact:true}).click();
    await page.locator('.truck-bl-received').fill('2');
    accept=false;await page.locator('[data-truck-action="discard"]').click();
    assert.equal(await page.locator('.truck-bl-received').inputValue(),'2');
    accept=true;await page.locator('[data-truck-action="discard"]').click();
    assert.equal(await page.locator('.truck-bl-received').inputValue(),'');
    await page.locator('.truck-bl-received').fill('2');await page.locator('#saveTruckArrivalButton').click();
   }
   await page.locator('#saveTruckLocationsButton').waitFor();
   await page.locator('.truck-bl-location').fill('TEMP-QA');
   await page.locator('#saveTruckLocationsButton').click();
   await page.waitForFunction(()=>activeTruckGuideSummary?.guide_status==='LISTA_PARA_CONTEO'&&!WmsTruckControls.hasPending());
   await page.locator('[data-truck-action="back"]').click();
   await page.locator('#saveTruckLocationsButton').waitFor();
   assert.equal(await page.locator('.truck-bl-location').inputValue(),'TEMP-QA','Reopening location keeps saved location');
   assert.equal(await page.evaluate(()=>activeTruckGuideSummary.bls[0].received_this_truck),2);
   await page.locator('[data-truck-action="back"]').click();
   if(scanner){
    await page.locator('#scanTruckBlCode').waitFor();
    assert.equal(await page.locator('#scanTotal').innerText(),'0','Reopening arrival annuls prior scans');
    await page.locator('#scanTruckBlCode').fill(code);await page.locator('#scanTruckBlCode').press('Enter');
    await page.locator('#scanTruckPackageCode').waitFor();
    await page.locator('#scanTruckPackageCode').fill(code+'-A');await page.locator('#scanTruckPackageCode').press('Enter');
    await page.waitForFunction(()=>$('scanTotal')?.textContent==='1'&&!WmsTruckScan.hasPending());
   }else await page.getByRole('button',{name:'Iniciar llegada',exact:true}).waitFor();
   const before=posts.length;
   await page.locator('[data-truck-action="leave"]').click();
   assert.equal(posts.length,before,'List navigation does not reverse receipts');
   await page.evaluate(guide=>openTruckGuideFromBl(guide),guide);
   await page.locator('[data-truck-action="cancel"]').click();
   await page.waitForFunction(()=>$('truckGuideFilter').value==='ALL'&&!WmsTruckControls.hasPending());
   const result=await page.evaluate(async guide=>{const r=await api('/api/receptions/truck-guide?truck_guide='+encodeURIComponent(guide));return r.json();},guide);
   assert.equal(result.guide_status,'CANCELADA');
   assert.equal(result.bls.filter(row=>row.operational_active!==false&&row.truck_work_pending).length,0);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'No horizontal page overflow');
   assert.deepEqual(errors,[]);
   console.log('OK '+(scanner?'scanner':'manual')+' '+viewport.width+'px: cancel/back/discard, history and viewport');
   await page.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
