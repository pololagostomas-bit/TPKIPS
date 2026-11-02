const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=process.cwd(),base=process.argv[2],output=process.env.WMS_QA_OUTPUT||path.join(root,'qa/label-text-fit');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable loopback fixture required');
(async()=>{
 fs.mkdirSync(output,{recursive:true});const browser=await chromium.launch({channel:'msedge',headless:true});
 try{for(const width of [320,393,1366]){
  const context=await browser.newContext({viewport:{width,height:873}});const page=await context.newPage();
  await page.goto(base+'/reception');await page.evaluate(()=>WmsReceptionLabels.loadEngine());
  const opened=page.waitForEvent('popup');
  await page.evaluate(()=>{const p=window.open('','_blank');p.document.write(WmsReceptionLabels.documentHtml({bl_awb:'QA-BL'},[{np:'QA / ARTICLE-987654321-REF',quantity:2,ov:'810001',customer:'CLIENTE INTERNACIONAL DE OPERACIONES LOGISTICAS Y SERVICIOS INDUSTRIALES S.A.C.',description:'REPUESTO DE PRUEBA',location:'QA-A-01',brand:'QA'}]));p.document.close();});
  const popup=await opened;popup.on('pageerror',e=>console.error('popup-error',e.message));popup.on('requestfailed',r=>console.error('popup-request',r.url(),r.failure()));await popup.setViewportSize({width,height:873});
  try{await popup.waitForFunction(()=>document.querySelector('#labelPrintMessage')?.textContent.trim()&&!document.querySelector('#labelPrintMessage').textContent.includes('Cargando'),null,{timeout:5000});}catch(e){console.log(await popup.evaluate(()=>({url:location.href,ready:document.readyState,msg:document.getElementById('labelPrintMessage')?.textContent,scripts:[...document.scripts].map(s=>s.textContent.slice(-150)),resources:performance.getEntriesByType('resource').map(r=>r.name)})));throw e;}
  const metrics=await popup.locator('.sticker').evaluate(sheet=>{
   const lines=node=>{const r=document.createRange();r.selectNodeContents(node);return r.getClientRects().length;};
   return {npLines:lines(sheet.querySelector('.np')),customerLines:lines(sheet.querySelector('.customer>strong')),
    customerFont:getComputedStyle(sheet.querySelector('.customer>strong')).fontSize,customerWidth:sheet.querySelector('.customer>strong').clientWidth,customerHeight:sheet.querySelector('.customer>strong').clientHeight,customerScroll:sheet.querySelector('.customer>strong').scrollHeight,fit:sheet.dataset.fits,code:sheet.querySelector('.np').textContent,customer:sheet.querySelector('.customer>strong').textContent,
    npSize:parseFloat(getComputedStyle(sheet.querySelector('.np')).fontSize),ovSize:parseFloat(getComputedStyle(sheet.querySelector('.ov-value')).fontSize),
    clipped:[...sheet.querySelectorAll('.np,.customer>strong')].some(n=>n.scrollWidth>n.clientWidth+1||n.scrollHeight>n.clientHeight+1)};
  });
  if(process.env.WMS_DEBUG_FIT)console.log(JSON.stringify(metrics));assert.equal(metrics.npLines,1);assert(metrics.customerLines<=2);assert.equal(metrics.fit,'true');assert.equal(metrics.clipped,false);
  assert.equal(metrics.code,'QA / ARTICLE-987654321-REF');assert(metrics.customer.includes('INDUSTRIALES S.A.C.'));assert(metrics.npSize<=metrics.ovSize);
  await popup.screenshot({path:path.join(output,'fit-'+width+'.png'),fullPage:true});
  await context.close();console.log('label text fit '+width+'px OK');
 }}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
