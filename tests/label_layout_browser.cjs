// Synthetic label samples; manufacturer assets stay in the private loopback fixture.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],output=path.join(__dirname,'../qa/em-labels-layout');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable loopback fixture required');
(async()=>{
 fs.mkdirSync(output,{recursive:true});const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  for(const viewport of [{width:1440,height:900},{width:393,height:873},{width:360,height:780},{width:320,height:640},{width:873,height:393}]){
   const context=await browser.newContext({viewport,deviceScaleFactor:2}),page=await context.newPage(),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   await context.addInitScript(()=>{if('serviceWorker'in navigator)navigator.serviceWorker.register=async()=>undefined;});
   await page.goto(base+'/reception');await page.evaluate(()=>loadDetail(2));
   // Load the same local engine as a real print, without changing receipt data.
   const firstOpening=page.waitForEvent('popup');await page.evaluate(()=>printOvStickers());
   const first=await firstOpening;await first.waitForFunction(()=>document.querySelector('#printLabels')&&!document.querySelector('#printLabels').disabled);await first.close();
   const opening=page.waitForEvent('popup');await page.evaluate(async()=>{
    const brandUrl=async brand=>{
     const response=await api('/api/reception-brand-logo?brand='+brand);
     if(!response.ok)throw Error('Private QA brand missing');
     return '/api/reception-brand-logo?brand='+brand+'&v='+response.headers.get('ETag').replaceAll('"','');
    };
    const logo=await brandUrl('HYUNDAI'),companyLogo=await brandUrl('TRITON');
    const items=[{np:'QA31-02110',ov:'804321',description:'ELEMENT-BREATHER',customer:'Cliente de ejemplo',
     location:'QA-A-01',brand:'HYUNDAI',logo,companyLogo},
     {np:'QA31-02110',ov:'804322',description:'ELEMENT-BREATHER',customer:'Cliente de ejemplo',
      location:'',brand:'HYUNDAI',logo,companyLogo},
     {np:'QA-125070-401',ov:'QAOV00002',description:'Repuesto industrial con descripcion extensa para validar texto completo sin abreviaturas',
      customer:'Cliente de operaciones industriales y servicios de mantenimiento de prueba con razon social extensa',
      location:'',brand:'HYUNDAI',logo,companyLogo}];
    const popup=window.open('','_blank');popup.document.write(WmsReceptionLabels.documentHtml({bl_awb:'QA-BL-001'},items));popup.document.close();
   });
   const popup=await opening;popup.on('pageerror',e=>errors.push(e.message));await popup.setViewportSize(viewport);
   await popup.waitForFunction(()=>document.querySelector('#printLabels')&&!document.querySelector('#printLabels').disabled);
   assert.equal(await popup.locator('.sticker').count(),3);
   for(const sticker of await popup.locator('.sticker').all()){
    const geometry=await sticker.evaluate(sheet=>{
     const rect=sheet.getBoundingClientRect(),bottom=sheet.querySelector('.location-box').getBoundingClientRect();
     const keys=[...sheet.querySelectorAll('.np,.ov-value')].map(node=>getComputedStyle(node).fontSize);
     const fields=[...sheet.querySelectorAll('.np,.ov-value,.description,.customer>strong,.bl strong,.location-box')];
     return {keys,fit:sheet.dataset.fits,locationWidth:bottom.width/rect.width,
      locationBottom:rect.bottom-bottom.bottom,
      clipped:fields.some(node=>node.scrollWidth>node.clientWidth+1||node.scrollHeight>node.clientHeight+1),
      backgrounds:[sheet,...sheet.querySelectorAll('.label-caption,.location-box')].map(node=>getComputedStyle(node).backgroundColor),
      order:[...sheet.children].map(node=>node.className)};
    });
    assert.equal(geometry.keys[0],geometry.keys[1]);assert.equal(geometry.fit,'true');assert.equal(geometry.clipped,false);
    assert(geometry.locationWidth>.93);assert(geometry.locationBottom>=0&&geometry.locationBottom<5);
    assert.deepEqual(geometry.order,['brand-block','facts','article-description','label-footer','location']);
    assert(geometry.backgrounds.every(color=>['rgb(255, 255, 255)','rgba(0, 0, 0, 0)'].includes(color)));
   }
   assert.equal(await popup.locator('.location-box').nth(1).innerText(),'');
   assert.equal(await popup.locator('.brand-logo').first().getAttribute('alt'),'HYUNDAI');
   assert.equal(await popup.locator('.company-logo').count(),3);
   assert(await popup.locator('.sticker').first().evaluate(node=>node.querySelector('.brand-logo').getBoundingClientRect().height>node.querySelector('.company-logo').getBoundingClientRect().height),'Manufacturer remains the primary branding');
   assert.equal(await popup.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   await popup.screenshot({path:path.join(output,'layout-'+viewport.width+'.png'),fullPage:true});
   if(viewport.width===1440){
    await popup.locator('.sticker').first().screenshot({path:path.join(output,'reference-example.png')});
    await popup.locator('.sticker').nth(1).screenshot({path:path.join(output,'reference-no-stock.png')});
    await popup.pdf({path:path.join(output,'reference.pdf'),preferCSSPageSize:true,printBackground:true});
    await popup.evaluate(()=>{
     const label=document.querySelector('.sticker');label.querySelector('.description').textContent='TEXTO '.repeat(300);
     window.dispatchEvent(new Event('resize'));
    });
    assert.equal(await popup.locator('#printLabels').isDisabled(),true,'Never silently clip excessive source content');
   }
   assert.deepEqual(errors,[]);await context.close();
  }
  console.log('OK: reference-style label, all fields, equal NP/OV, full-width blank location, white background, long text, five viewports');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
