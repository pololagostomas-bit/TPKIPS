// Local synthetic BL fixture, optionally using the user's private manufacturer assets.
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],output=path.join(__dirname,'../qa/em-labels');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable loopback fixture required');
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'}),results=[];
 try{
  for(const viewport of [{width:1440,height:900},{width:393,height:873},{width:360,height:780},{width:320,height:640},{width:873,height:393}]){
   const context=await browser.newContext({viewport}),page=await context.newPage(),errors=[];
   await context.addInitScript(()=>{window.print=()=>{window.qaPrints=(window.qaPrints||0)+1;};if('serviceWorker'in navigator)navigator.serviceWorker.register=async()=>undefined;});
   page.on('pageerror',e=>errors.push(e.message));
   await page.goto(base+'/reception');await page.evaluate(()=>loadDetail(2));
   await page.waitForFunction(()=>window.WmsReceptionLabels && selected?.id===2);
   const duplicate=await page.evaluate(()=>{
    const copy=structuredClone(selected),ref=copy.accounting_refs[0],initial=ref.linked_lines.length;
    ref.linked_lines.push({...ref.linked_lines[0]});
    const html=emEntryCard(copy),dom=new DOMParser().parseFromString(html,'text/html');
    return {count:dom.querySelector('.em-reference-card tbody').children.length,initial,raw:ref.linked_lines.length};
   });
   assert.equal(duplicate.count,duplicate.initial);assert.equal(duplicate.raw,duplicate.initial+1);
   const opening=page.waitForEvent('popup');await page.evaluate(()=>printOvStickers());const popup=await opening;
   popup.on('pageerror',e=>errors.push(e.message));await popup.setViewportSize(viewport);
   await popup.waitForLoadState();await popup.waitForFunction(()=>!document.querySelector('#printLabels').disabled);
   assert.equal(await popup.locator('.sticker').count(),3);
   assert.equal(await popup.locator('.brand-logo').count(),3);
   assert.equal(await popup.locator('.brand-logo').first().getAttribute('alt'),'BOBCAT');
   assert.equal(await popup.locator('.brand-logo').nth(1).getAttribute('alt'),'BOBCAT');
   assert.equal(await popup.locator('.brand-logo').nth(2).getAttribute('alt'),'CROWN');
   assert.equal(await popup.locator('.location-box').nth(2).innerText(),'');
   assert.equal(await popup.locator('#labelWidth').inputValue(),'101.6');
   assert.equal(await popup.locator('#labelHeight').inputValue(),'76.2');
   assert.equal(await popup.locator('#labelPaper').inputValue(),'te200-4x3');
   for(const orientation of ['landscape','portrait']){
    await popup.locator('[name=labelOrientation][value='+orientation+']').check();
    await popup.waitForFunction(()=>!document.querySelector('#printLabels').disabled);
    const geometry=await popup.evaluate(()=>({
     overflow:document.documentElement.scrollWidth>innerWidth+1,
     sizes:[...document.querySelectorAll('.sticker')].map(sheet=>({
      np:getComputedStyle(sheet.querySelector('.np')).fontSize,ov:getComputedStyle(sheet.querySelector('.ov-value')).fontSize,
      fits:sheet.dataset.fits,logo:sheet.querySelector('.brand-logo').naturalWidth>0,
      top:sheet.querySelector('.brand-block').getBoundingClientRect().bottom<=sheet.querySelector('.np').getBoundingClientRect().top+1
     })),width:document.querySelector('#labelWidth').value,height:document.querySelector('#labelHeight').value
    }));
    assert.equal(geometry.overflow,false);assert.ok(geometry.sizes.every(item=>item.np===item.ov&&item.fits==='true'&&item.logo&&item.top));
    assert.equal(geometry.width,orientation==='landscape'?'101.6':'76.2');
    assert.equal(geometry.height,orientation==='landscape'?'76.2':'101.6');
    assert.ok(await popup.locator('.barcode').evaluateAll(codes=>codes.every(code=>{
     const bars=[...code.querySelectorAll('rect')],first=bars[0],last=bars.at(-1);
     const narrow=Math.min(...bars.map(bar=>Number(bar.getAttribute('width'))));
     return Number(first.getAttribute('x'))>=10*narrow && code.viewBox.baseVal.width-Number(last.getAttribute('x'))-Number(last.getAttribute('width'))>=10*narrow;
    })));
    await popup.screenshot({path:path.join(output,orientation+'-'+viewport.width+'.png'),fullPage:true});
    if(viewport.width===1440)await popup.pdf({path:path.join(output,orientation+'.pdf'),preferCSSPageSize:true,printBackground:true});
    results.push({viewport,orientation,width:geometry.width,height:geometry.height,labels:3});
   }
   await popup.locator('#labelWidth').fill('60');await popup.locator('#labelHeight').fill('60');
   await popup.waitForFunction(()=>document.querySelector('#printLabels').disabled);
   assert.match(await popup.locator('#labelPrintMessage').innerText(),/no cabe/);
   assert.equal(await popup.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   assert.ok(await popup.evaluate(()=>{const pages=[...document.querySelectorAll('.label-page')];return pages.every((item,i)=>!i||item.getBoundingClientRect().top>=pages[i-1].getBoundingClientRect().bottom)}));
   if(viewport.width===1440){
    await popup.close();
    const logos=[];
    for(const brand of ['KALMAR','TRITON','CROWN','HYUNDAI','BOBCAT','KUBOTA','HOWO','TVH','HUSQVARNA','LIEBHERR']){
     const response=await context.request.get(base+'/api/reception-brand-logo?brand='+brand);
     assert.equal(response.status(),200);assert.match(response.headers()['content-type'],/^image\/(png|jpeg)$/);
     logos.push([brand,response.headers().etag.replaceAll('"','')]);
    }
    const allOpening=page.waitForEvent('popup');await page.evaluate(values=>{
     const items=values.map(([brand,digest])=>({np:'QA-'+brand,ov:'QA-OV-1',customer:'Cliente de prueba',location:'',description:'Repuesto ficticio',brand,logo:'/api/reception-brand-logo?brand='+brand+'&v='+digest}));
     const target=window.open('','_blank');target.document.write(WmsReceptionLabels.documentHtml({bl_awb:'QA-BRANDS'},items));target.document.close();
    },logos);
    const all=await allOpening;await all.waitForLoadState();
    await all.locator('#labelPaper').selectOption('te200-4x3');
    await all.waitForFunction(()=>!document.querySelector('#printLabels').disabled);
    assert.equal(await all.locator('.brand-logo').count(),10);
    assert.ok(await all.locator('.brand-logo').evaluateAll(images=>images.every(image=>image.complete&&image.naturalWidth>0)));
    await all.screenshot({path:path.join(output,'all-brands.png'),fullPage:true});
    await all.pdf({path:path.join(output,'all-brands.pdf'),preferCSSPageSize:true,printBackground:true});
    await all.evaluate(()=>{
     const images=[...document.querySelectorAll('.brand-logo')],main=document.createElement('main');
     main.style.cssText='display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px';
     for(const image of images){const figure=document.createElement('figure'),caption=document.createElement('figcaption');
      figure.style.cssText='margin:0;padding:12px;border:1px solid #bbb;text-align:center';caption.textContent=image.alt;
      image.style.cssText='width:100%;height:90px;object-fit:contain;max-width:none;max-height:none';
      figure.append(image,caption);main.append(figure);}
     document.body.replaceChildren(main);
    });
    await all.setViewportSize({width:1000,height:850});await all.screenshot({path:path.join(output,'logo-catalog.png'),fullPage:true});
    await all.close();
    const failedOpening=page.waitForEvent('popup');await page.evaluate(()=>{
     const original=selected;selected=structuredClone(original);
     selected.lines[0].brand_logo_url=selected.lines[0].brand_logo_url.replace(/v=[a-f0-9]+/,'v='+'0'.repeat(64));
     printOvStickers();selected=original;
    });const failed=await failedOpening;
    await failed.waitForFunction(()=>document.querySelector('#labelPrintMessage')?.textContent.includes('No se cargó'));
    await failed.setViewportSize({width:500,height:700});
    assert.equal(await failed.locator('#printLabels').isDisabled(),true);
    assert.match(await failed.locator('#labelPrintMessage').innerText(),/No se cargó/);
    await failed.close();
    await page.evaluate(()=>{
     localStorage.removeItem('triton-wms-label-paper-v2');
     localStorage.setItem('triton-wms-label-paper-v1',JSON.stringify({width:150,height:100}));
    });
    const migrationOpening=page.waitForEvent('popup');await page.evaluate(()=>printOvStickers());const migration=await migrationOpening;
    await migration.waitForLoadState();await migration.waitForFunction(()=>!document.querySelector('#printLabels').disabled);
    assert.equal(await migration.locator('#labelWidth').inputValue(),'101.6');
    assert.equal(await migration.locator('#labelHeight').inputValue(),'76.2');
    await migration.locator('#labelPaper').selectOption('previous');
    assert.equal(await migration.locator('#labelWidth').inputValue(),'150');
    assert.equal(await migration.locator('#labelHeight').inputValue(),'100');
    await migration.locator('#labelWidth').fill('120.5');
    assert.equal(await migration.locator('#labelPaper').inputValue(),'custom');
    await migration.close();
    const customOpening=page.waitForEvent('popup');await page.evaluate(()=>printOvStickers());const custom=await customOpening;
    await custom.waitForLoadState();await custom.waitForFunction(()=>!document.querySelector('#printLabels').disabled);
    assert.equal(await custom.locator('#labelWidth').inputValue(),'120.5');
    assert.equal(await custom.locator('#labelHeight').inputValue(),'100');
    await custom.locator('#labelPaper').selectOption('te200-4x3');
    await custom.close();
   }
   assert.deepEqual(errors,[]);await context.close();
  }
  fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(results,null,2));
  console.log('OK: private logos, normalized brands, equal OV/NP type, landscape/portrait, overflow guard, duplicate-row guard, five viewports');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
