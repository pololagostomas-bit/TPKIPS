// Only support_independent_arrivals_server.py, never production.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2];if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable loopback fixture required');
(async()=>{const browser=await chromium.launch({headless:true,channel:'msedge'});try{
 for(const viewport of [{width:320,height:740},{width:393,height:873},{width:1366,height:900},{width:873,height:393}]){
  const page=await browser.newPage({viewport}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept(d.type()==='prompt'?'Administrative reopening verified QA':undefined));
  await page.goto(base+'/reception');await page.waitForFunction(()=>window.WmsPackageReview);
  const ids=await page.evaluate(async width=>{const rows=await(await api('/api/receptions?search=QA-ARRIVALS-'+width)).json();const row=rows.find(r=>r.bl_awb==='QA-ARRIVALS-'+width);await loadDetail(row.id);return {sid:row.id,first:selected.attentions[0].id,second:selected.attentions[1].id};},viewport.width);
  await page.locator(`[data-attention-open="${ids.second}"]`).click();await page.waitForFunction(id=>selected?.attention_id===id,ids.second);
  assert.equal(await page.locator('.back-btn').innerText(),`← Volver al camion QA-${viewport.width}-B`);
  await page.evaluate(()=>advance('REVISION SISTEMA'));await page.locator('#scanReceptionNp').waitFor();
  await page.locator('#packageReviewOpen').click();await page.locator('#packageReviewDialog[open]').waitFor();
  await page.locator('[data-package-remove]').first().click();await page.locator('#packageCorrectionReason').fill('Invalid physical read checked by admin QA');
  await page.locator('#packageCorrectionSubmit').click();await page.locator('#packageReviewError').filter({hasText:'Reabre'}).waitFor();
  await page.locator('#packageReviewClose').click();
  await page.locator('#rewindStatus').selectOption('ARRIBADO');await page.evaluate(()=>rewindStage());
  await page.waitForFunction(()=>selected?.app_status==='ARRIBADO');
  await page.locator('#packageReviewOpen').click();await page.locator('[data-package-replace]').first().click();
  await page.locator('#packageCorrectionCode').fill(`QA-${viewport.width}-B-CORRECTED`);
  await page.locator('#packageCorrectionReason').fill('Correct unique package code verified QA');
  await page.locator('#packageCorrectionSubmit').click();
  await page.waitForFunction(()=>!document.querySelector('#packageCorrectionForm')?.hidden===false);
  await page.getByText(`QA-${viewport.width}-B-CORRECTED`,{exact:true}).waitFor();
  assert.match(await page.locator('#packageReviewBalance').innerText(),/Esta llegada: 1 bultos/);
  await page.locator('[data-package-remove]').first().click();await page.locator('#packageCorrectionReason').fill('False receipt verified by administrator QA');
  let posts=0,oldBody;
  await page.route('**/package-correction',async route=>{posts++;oldBody=route.request().postDataJSON();await route.fulfill({status:503,contentType:'application/json',body:'{"error":"QA temporary failure"}'});});
  await page.evaluate(()=>{document.querySelector('#packageCorrectionForm').requestSubmit();document.querySelector('#packageCorrectionForm').requestSubmit();});
  await page.locator('#packageReviewError').filter({hasText:'QA temporary failure'}).waitFor();assert.equal(posts,1);
  assert.equal(await page.locator('#packageCorrectionReason').inputValue(),'False receipt verified by administrator QA');
  await page.unroute('**/package-correction');await page.locator('#packageCorrectionSubmit').click();
  await page.waitForFunction(()=>document.querySelector('#packageCorrectionForm')?.hidden===true);
  assert.match(await page.locator('#packageReviewBalance').innerText(),/Esta llegada: 0 bultos/);
  await page.locator('#packageReviewClose').click();
  await page.waitForFunction(id=>selected?.attention_id===id,ids.first);
  assert.equal(await page.locator('.back-btn').innerText(),`← Volver al camion QA-${viewport.width}-A`);
  assert.equal(await page.evaluate(()=>selected.received_packages),1,'Only the corrected arrival changes');
  const denied=await page.evaluate(async ({sid,body})=>{const worker=await fetch('/api/receptions/'+sid+'/package-review?attention_id='+body.attention_id,{headers:{'X-User':'demo.recepcion','X-Role':'ASISTENTE_RECEPCION'}});const stale=await api('/api/receptions/'+sid+'/package-correction',{method:'POST',body:JSON.stringify(body),headers:{'Content-Type':'application/json'}});return [worker.status,stale.status];},{sid:ids.sid,body:oldBody});
  assert.deepEqual(denied,[403,400]);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);assert.deepEqual(errors,[]);
  const folder=path.join(__dirname,'../qa/runtime/package-corrections');fs.mkdirSync(folder,{recursive:true});await page.screenshot({path:path.join(folder,'package-'+viewport.width+'.png')});
  console.log('OK independent arrivals, package correction/reopen/error and navigation '+viewport.width);await page.close();
 }
}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1});
