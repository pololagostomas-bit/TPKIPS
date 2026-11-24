// support_reception_flow_server.py only. Synthetic diagnoses, no source edits.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],out=process.argv[3]||path.join(__dirname,'../qa/runtime/costing-diagnosis');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Synthetic loopback fixture required');
(async()=>{
 fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  for(const width of [320,393,1366]){
   for(const user of ['qa.reader','qa.assistant','qa.auxiliary']){
    const context=await browser.newContext({viewport:{width,height:873},serviceWorkers:'block'}),page=await context.newPage(),errors=[];
    page.on('pageerror',e=>errors.push(e.message));let ready=false,fail=false,posts=0,attention;
    await page.route('**/api/receptions/7**',async route=>{
     if(route.request().method()!=='GET'){posts++;return route.abort();}
     if(fail){fail=false;return route.abort('failed');}
     const data=await(await route.fetch()).json();attention??=data.attention_id;
     assert.equal(data.attention_id,attention);
     if(user==='qa.reader')data.costing={ready,costing_date:ready?'2026-11-18':'',issues:ready?[]:[
      {field:'IP en Facturas',message:'La IP QA-IP falta en Facturas.',action:'Comprueba si la FR/EM cubre esta IP.',source_sheet:'QA-'+('HOJA'.repeat(35)),source_row:23,fr_number:'QA-FR',em_number:'QA-EM'},
      {field:'Fecha de costeo',message:'<img src=x onerror=alert(1)>',action:'Completa la fecha real en Facturas.'}]};
     return route.fulfill({json:data});
    });
    assert.equal((await context.request.post(base+'/api/login',{headers:{'X-WMS-Request':'1'},data:{username:user,password:'QA-password-only-123!'}})).status(),200);
    await page.goto(base+'/reception');await page.waitForFunction(()=>Boolean(window.WmsReceptionFlow));
    await page.evaluate(()=>loadDetail(7));
    if(user==='qa.reader'){
     await page.locator('.transfer-diagnosis').waitFor();
     assert.equal(await page.locator('.transfer-diagnosis img').count(),0);
     assert.match(await page.locator('.transfer-diagnosis').innerText(),/QA-IP/);
     await page.locator('.transfer-diagnosis').scrollIntoViewIfNeeded();
     const button=page.getByRole('button',{name:'Actualizar diagnóstico',exact:true});
     const size=await button.boundingBox();assert(size.width>=44&&size.height>=44);
     assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
     await page.screenshot({path:path.join(out,'admin-'+width+'.png'),fullPage:true});
     if(width===393){
      fail=true;await button.click();await page.waitForTimeout(200);
      assert.equal(await page.locator('.transfer-diagnosis').count(),1);
     }
     ready=true;await button.click();await page.waitForFunction(()=>!document.querySelector('.transfer-diagnosis'));
     assert.match(await page.locator('[data-reception-panel="transferencia"]').innerText(),/Costeo registrado en Facturas/);
    }else{
     assert.equal(await page.locator('.transfer-diagnosis').count(),0);
     assert.equal(await page.getByRole('button',{name:'Actualizar diagnóstico',exact:true}).count(),0);
    }
    assert.equal(posts,0);assert.deepEqual(errors,[]);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    await context.close();
   }
  }
  console.log('PASS: admin/assistant/auxiliary at 320/393/1366; source wrapping, escaping, refresh/recovery, no writes.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
