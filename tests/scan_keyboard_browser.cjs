// Keyboard policy only: no real camera, server, credentials or operational writes.
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),root=path.resolve(__dirname,'..');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  for(const width of [320,393,1366]){
   const context=await browser.newContext({viewport:{width,height:873},hasTouch:true,isMobile:width<820});
   const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
   await page.route('**/*',route=>route.fulfill({contentType:'text/html',body:'<input id="code" data-wms-scan-input inputmode="none" value="00123"><input id="quantity" type="number" data-wms-scan-input data-manual-inputmode="numeric" inputmode="none"><textarea id="comment"></textarea>'}));
   await page.goto('http://127.0.0.1:52639');
   await page.addStyleTag({content:fs.readFileSync(path.join(root,'frontend/static/wms-camera.css'),'utf8')});
   await page.addScriptTag({content:fs.readFileSync(path.join(root,'frontend/static/wms-camera.js'),'utf8')});
   await page.evaluate(()=>{
    window.Html5Qrcode=class{async start(_camera,_options,read){this.isScanning=true;window.qaRead=read}async stop(){this.isScanning=false}clear(){}};
    WmsCamera.init({context:()=>({key:'qa-arrival'}),accept:async()=>({state:'saved'}),manual:(_target,id)=>WmsCamera.manualInput(document.getElementById(id))});
   });
   const code=page.locator('#code');
   await page.evaluate(()=>WmsCamera.focusInput(document.getElementById('code')));
   assert.equal(await code.getAttribute('inputmode'),'none');
   assert.equal(await code.inputValue(),'00123','Focus preserves leading zeroes and draft');
   await code.press('End');await page.keyboard.type('-HID');
   assert.equal(await code.inputValue(),'00123-HID','Physical input still works');
   await code.tap();assert.equal(await code.getAttribute('inputmode'),'text','Explicit tap enables manual typing');
   await page.evaluate(()=>WmsCamera.focusInput(document.getElementById('code')));
   assert.equal(await code.getAttribute('inputmode'),'none','Automatic refocus restores scanner mode');
   await page.evaluate(()=>WmsCamera.open('code','truck-bl'));
   await page.waitForFunction(()=>document.querySelector('#wmsCameraStatus').textContent==='Listo para leer');
   await page.evaluate(()=>qaRead('QA-CAMERA'));
   await page.waitForFunction(()=>document.querySelector('#wmsBarcodeCamera').hidden);
   assert.equal(await code.getAttribute('inputmode'),'none','Camera return never requests keyboard');
   assert.equal(await page.evaluate(()=>document.activeElement.id),'code');
   await page.evaluate(()=>WmsCamera.open('code','truck-bl'));
   await page.locator('#wmsCameraManual').click();
   assert.equal(await code.getAttribute('inputmode'),'text','Camera manual fallback explicitly enables keyboard');
   await page.locator('#comment').focus();
   assert.equal(await code.getAttribute('inputmode'),'none','Leaving manual entry resets scanner mode');
   assert.notEqual(await page.locator('#comment').getAttribute('inputmode'),'none','Ordinary fields are unaffected');
   await page.evaluate(()=>WmsCamera.focusInput(document.getElementById('quantity')));
   assert.equal(await page.locator('#quantity').getAttribute('inputmode'),'none');
   await page.locator('#quantity').tap();
   assert.equal(await page.locator('#quantity').getAttribute('inputmode'),'numeric','Manual maritime quantity keeps its numeric keyboard');
   await page.evaluate(()=>document.getElementById('code').replaceWith(document.getElementById('code').cloneNode(true)));
   await code.tap();assert.equal(await code.getAttribute('inputmode'),'text','Dynamic scanner fields support manual entry');
   assert.deepEqual(errors,[]);await context.close();
  }
  console.log('OK scanner keyboard: 3 sizes, auto/HID/camera returns suppress keyboard, explicit tap/manual works, drafts and ordinary fields preserved.');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
