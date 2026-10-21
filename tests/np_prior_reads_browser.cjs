// Real disposable API + screen: completing the last source order of an older arrival.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.argv[2];
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '')) throw Error('Disposable loopback fixture required');
(async () => {
  const browser = await chromium.launch({headless:true,channel:'msedge'});
  try {
    for (const [index,width] of [320,393,1366,873,320].entries()) {
      const page = await browser.newPage({viewport:{width,height:873},serviceWorkers:'block'});
      const errors = [], posts = [];
      page.on('pageerror',error=>errors.push(error.message));
      page.on('request',req=>{if(req.method()==='POST' && /\/lines\/\d+$/.test(req.url()))posts.push(req);});
      await page.goto(base+'/reception');
      await page.waitForFunction(()=>typeof loadDetail==='function');
      await page.evaluate(sid=>loadDetail(sid),index+1);
      await page.locator('#scanReceptionNp').waitFor();
      if(index===4)await page.addStyleTag({content:'html{font-size:200%}'});
      assert.equal(await page.locator('#receptionNpProgress').innerText(),'NP leidos: 38/39');
      assert.equal(await page.locator('input[id^="qty-"]').count(),1,'Only current missing source order editable');
      assert.equal(await page.locator('.np-list-status').filter({hasText:'Leido en otra llegada'}).count(),39);
      await page.evaluate(()=>document.querySelector('#receptionNpList').open=true);
      const prior = page.locator('[data-count-line]').first();
      assert.equal(await prior.locator('input').count(),0,'Prior quantities and location read-only');
      const stateBefore = await page.evaluate(()=>structuredClone(selected.attentions[1].lines));
      if(index===0){
        await page.route('**/api/receptions/*/lines/*',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"QA unavailable"}'}),{times:1});
      }
      await page.locator('#scanReceptionNp').fill('QA-NP-38');
      await page.locator('#scanReceptionNp').press('Enter');
      if(index===0){
        await page.getByRole('button',{name:'Reintentar lectura',exact:true}).waitFor();
        assert.match(await page.locator('#receptionNpProgress').innerText(),/^NP leidos: 38\/39/);
        await page.getByRole('button',{name:'Reintentar lectura',exact:true}).click();
      }
      await page.waitForFunction(()=>!WmsNpScan.hasPending());
      assert.equal(await page.locator('#receptionNpProgress').innerText(),'NP leidos: 39/39');
      assert.equal(await page.evaluate(()=>WmsNpScan.canComplete()),true);
      await page.getByRole('button',{name:'Guardar revisi\u00f3n completa',exact:true}).click();
      await page.waitForFunction(()=>document.querySelector('[data-save-physical-review]')?.textContent==='Guardar revisión completa');
      assert.equal(posts.length,index===0?3:2,'One scan, one save; no 39-row bulk rewrite');
      await page.locator('#receptionNpProgress').scrollIntoViewIfNeeded();
      fs.mkdirSync(path.join(__dirname,'../qa/np-prior-reads'),{recursive:true});
      await page.screenshot({path:path.join(__dirname,`../qa/np-prior-reads/count-${width}-${index}.png`)});
      await page.evaluate(()=>advance('EM'));
      await page.waitForFunction(()=>selected.app_status==='EM');
      const detail = await page.evaluate(async()=>{
        const response=await api(shipmentUrl(''));if(!response.ok)throw Error('QA detail failed');return response.json();
      });
      assert.equal(detail.np_progress.read,39);
      assert.equal(detail.np_progress.total,39);
      assert.deepEqual(detail.attentions[1].lines,stateBefore,'Other arrival retains its actual readings');
      assert.equal(detail.attentions[0].lines.filter(line=>line.verified_qty>0).length,1);
      assert.equal(detail.lines.filter(line=>line.location_attention_required).length,1);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
      await page.locator('#receptionNpProgress').evaluate(node=>node.scrollIntoView({block:'center'}));
      fs.mkdirSync(path.join(__dirname,'../qa/np-prior-reads'),{recursive:true});
      await page.screenshot({path:path.join(__dirname,`../qa/np-prior-reads/after-${width}-${index}.png`)});
      assert.deepEqual(errors,[]);await page.close();
    }
    const page=await browser.newPage({viewport:{width:393,height:873},serviceWorkers:'block'});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto(base+'/reception');await page.waitForFunction(()=>typeof loadDetail==='function');
    await page.evaluate(()=>loadDetail(6));await page.locator('#scanReceptionNp').waitFor();
    const button=page.getByRole('button',{name:'Regularizar lecturas de otras llegadas',exact:true});
    assert.equal(await button.isVisible(),true);
    const review=await page.evaluate(()=>({attention_id:selected.attention_id,bl_awb:selected.bl_awb,
      confirmed:true,...selected.np_prior_read_review}));
    const denied=await page.request.post(base+'/api/receptions/6/count/prior-reads',{
      headers:{'X-User':'demo.admin','X-Role':'ASISTENTE_RECEPCION','X-WMS-Request':'1'},data:review});
    assert.equal(denied.status(),403);
    page.once('dialog',dialog=>dialog.dismiss());await button.click();
    assert.equal((await page.evaluate(()=>selected.np_prior_read_review.line_ids.length)),39);
    await page.locator('#scanReceptionNp').fill('QA-NP-38');await page.locator('#scanReceptionNp').press('Enter');
    await page.waitForFunction(()=>!WmsNpScan.hasPending());
    assert.equal(await page.evaluate(()=>WmsNpScan.canComplete()),false);
    await page.evaluate(()=>document.querySelector('#receptionNpList').open=true);
    page.once('dialog',dialog=>dialog.accept());
    await page.getByRole('button',{name:'Confirmar cantidad antigua de QA-NP-00, OV QA-OV-0',exact:true}).click();
    await page.waitForFunction(()=>!WmsNpScan.hasPending() && selected.lines[0].np_count_confirmed_manually);
    assert.equal(await page.locator('#scanReceptionNp').isEnabled(),true);
    await page.evaluate(()=>WmsNpScan.review('QA-NP-00'));
    await page.locator('#receptionNpQuantity').fill('2');
    await page.locator('#receptionNpReason').fill('Cantidad real verificada por administrador');
    await page.locator('#receptionNpSave').click();await page.waitForFunction(()=>!WmsNpScan.hasPending());
    let release,held=false;
    await page.route('**/count/prior-reads',async route=>{held=true;await new Promise(resolve=>release=resolve);await route.continue();},{times:1});
    page.once('dialog',dialog=>dialog.accept());await button.click();
    for(let tries=0;!held && tries<100;tries++)await new Promise(resolve=>setTimeout(resolve,10));
    assert.equal(held,true);
    assert.equal(await page.locator('input[id^="qty-"]').first().isDisabled(),true,'No editable drafts can be lost during regularization');
    await page.evaluate(()=>renderDetail());
    assert.equal(await page.locator('input[id^="qty-"]').first().isDisabled(),true,'A repaint retains the administrative request lock');
    release();
    await page.waitForFunction(()=>!WmsNpScan.hasPending() && selected.np_prior_read_review.line_ids.length===0);
    assert.equal(await page.evaluate(()=>WmsNpScan.canComplete()),true);
    assert.equal(await page.locator('#scanReceptionNp').isEnabled(),true);
    await page.evaluate(()=>savePhysicalReview());await page.evaluate(()=>advance('EM'));
    assert.equal(await page.evaluate(()=>selected.app_status),'EM');
    assert.equal(await page.evaluate(()=>selected.lines[0].attention_verified_qty),2,'Real manual quantities retained, not erased with defaults');
    assert.deepEqual(errors,[]);await page.close();
    console.log('OK: 38/39 -> 39/39, save + EM, no duplicate quantities, prior attention unchanged, 503/retry, 4 widths and 200% text.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
