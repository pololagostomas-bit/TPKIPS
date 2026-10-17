const {chromium}=require('playwright');
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const base=process.argv[2];
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable loopback fixture required');
const output=path.join(__dirname,'../qa/camera-fallback');fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),results=[];
 try{
  for(const viewport of [{width:320,height:640},{width:393,height:873},{width:1366,height:768},{width:873,height:393}]){
   const page=await browser.newPage({viewport}),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   await page.goto(base+'/login');
   await page.setContent('<style>body{font-family:Arial;margin:0}.wms-camera-overlay[hidden]{display:none}.wms-camera-overlay{position:fixed;inset:0;background:#0009;display:grid;place-items:center;padding:12px;box-sizing:border-box}.wms-camera-dialog{background:white;padding:12px;width:min(100%,500px);box-sizing:border-box}button{min-height:48px;padding:10px}header{display:flex;justify-content:space-between;gap:8px}h2{margin:0;font-size:20px}</style><input id="qaCameraCode" aria-label="Codigo"><div id="qaScanner"></div>');
   await page.addStyleTag({url:base+'/assets/wms-camera.css'});
   await page.addScriptTag({url:base+'/assets/wms-camera.js'});
   await page.evaluate(()=>{
    window.qaCamera={context:'BL-1/attention-1',codes:[],next:'saved',failStart:false,stops:0,clears:0};
    window.Html5Qrcode=class{
     constructor(){window.qaScanner=this;this.isScanning=false;}
     async start(_camera,config,onRead){this.config=config;this.read=onRead;
      if(qaCamera.failStart)throw new Error('NotAllowedError: Permission denied');
      if(qaCamera.waitPermission)await new Promise(resolve=>qaCamera.grant=resolve);
      this.isScanning=true;
     }
     async stop(){qaCamera.stops++;this.isScanning=false;}
     clear(){qaCamera.clears++;}
    };
    WmsCamera.init({context:()=>qaCamera.context?{key:qaCamera.context}:null,
     accept:async(_target,code)=>{qaCamera.codes.push(code);
      if(qaCamera.waitSave)await new Promise(resolve=>qaCamera.saved=resolve);
      return {state:qaCamera.next,message:qaCamera.next==='error'?'No se pudo confirmar. Revisa el registro.':'Registrado '+code};},
     manual:()=>document.getElementById('qaCameraCode').focus()});
   });
   await page.evaluate(()=>WmsCamera.open('qaCameraCode','reception-np'));
   assert.equal(await page.locator('#wmsCameraContinuous').isChecked(),true);
   assert.deepEqual(await page.evaluate(()=>qaScanner.config.qrbox(200,150)),{width:120,height:120});
   await page.evaluate(async()=>{await qaScanner.read('NP-A');await qaScanner.read('NP-A');await qaScanner.read('NP-B');});
   assert.deepEqual(await page.evaluate(()=>qaCamera.codes),['NP-A','NP-B']);
   assert.equal(await page.locator('#wmsBarcodeCamera').isVisible(),true);
   await page.evaluate(async()=>{qaCamera.next='error';await qaScanner.read('UNKNOWN');await qaScanner.read('NP-C');});
   assert.equal(await page.locator('#wmsCameraError').isVisible(),true);
   assert.equal((await page.evaluate(()=>qaCamera.codes)).length,3);
   await page.screenshot({path:path.join(output,'error-'+viewport.width+'.png')});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   const actions=await page.locator('#wmsCameraManual,#wmsCameraResume').evaluateAll(buttons=>buttons.map(b=>({w:b.getBoundingClientRect().width,h:b.getBoundingClientRect().height})));
   assert.ok(actions.every(b=>b.w>=44&&b.h>=44));
   if(viewport.width===320){
    await page.evaluate(()=>document.querySelectorAll('#wmsBarcodeCamera *').forEach(el=>el.style.fontSize=parseFloat(getComputedStyle(el).fontSize)*2+'px'));
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    await page.locator('#wmsCameraManual').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,'text-200-320.png')});
   }
   await page.getByRole('button',{name:'Reintentar lectura'}).click();
   await page.evaluate(async()=>{qaCamera.next='saved';await qaScanner.read('NP-C');});
   assert.equal((await page.evaluate(()=>qaCamera.codes)).length,4);
   await page.getByRole('button',{name:'Ingresar sin camara'}).click();
   assert.equal(await page.locator('#wmsBarcodeCamera').isVisible(),false);
   assert.equal(await page.evaluate(()=>document.activeElement.id),'qaCameraCode');

   await page.evaluate(async()=>{qaCamera.failStart=true;await WmsCamera.open('qaCameraCode','truck-package');});
   assert.match(await page.locator('#wmsCameraError').innerText(),/denegado/);
   await page.keyboard.press('Escape');
   assert.equal(await page.locator('#wmsBarcodeCamera').isVisible(),false);
   await page.evaluate(async()=>{qaCamera.failStart=false;qaCamera.waitSave=true;await WmsCamera.open('qaCameraCode','truck-package');qaScanner.read('OLD-CONTEXT');});
   await page.waitForFunction(()=>qaCamera.saved);
   await page.evaluate(async()=>{qaCamera.context='BL-2/attention-2';WmsCamera.changed();qaCamera.saved();});
   assert.equal(await page.locator('#wmsBarcodeCamera').isVisible(),false);
   await page.evaluate(()=>{qaCamera.waitSave=false;qaCamera.waitPermission=true;WmsCamera.open('qaCameraCode','truck-package');});
   await page.waitForFunction(()=>qaCamera.grant);
   await page.evaluate(()=>WmsCamera.close());
   await page.evaluate(()=>qaCamera.grant());
   await page.waitForFunction(()=>qaScanner.isScanning===false);
   assert.equal(await page.locator('#wmsBarcodeCamera').isVisible(),false);
   assert.deepEqual(errors,[]);
   results.push({viewport,checks:'continuous/dedup/error/retry/manual/permission/context/late-start'});
   await page.close();
  }
  // Exercise the real local decoder with synthetic labels, not a camera mock.
  const page=await browser.newPage();await page.goto(base+'/login');
  await page.setContent('<div id="decode"></div><canvas id="sample"></canvas>');
  await page.addScriptTag({url:base+'/assets/html5-qrcode.min.js?v=2.3.8'});
  await page.addScriptTag({url:base+'/assets/bwip-js-min.js'});
  const decoded=await page.evaluate(async()=>{
   const values=[];
   for(const [format,text] of [['datamatrix','QA-NP-001'],['qrcode','QA-NP-002'],['code128','JD001234567890']]){
    bwipjs.toCanvas('sample',{bcid:format,text,scale:4,padding:16,backgroundcolor:'FFFFFF'});
    const blob=await new Promise(resolve=>document.getElementById('sample').toBlob(resolve,'image/png'));
    const reader=new Html5Qrcode('decode');
    const actual=await reader.scanFile(new File([blob],format+'.png',{type:'image/png'}),false);
    reader.clear();values.push({format,text,actual});
   }
   return values;
  });
  assert.ok(decoded.every(item=>item.actual===item.text));
  await page.close();
  console.log(JSON.stringify({results,real_local_decoder:decoded},null,2));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
