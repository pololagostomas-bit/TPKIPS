// Synthetic server only. Proves row-level saving, drafts and guarded progression.
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),base='http://127.0.0.1:51992';
const sample=()=>({id:501,bl_awb:'QA-LOCATION',attention_id:71,active_attention_id:71,
  app_status:'UBICACION',condition_status:'EN PROCESO',current_assistant:'qa.worker',current_auxiliary:'qa.worker',
  received_packages:1,accounting_status:'PENDIENTE FR',attentions:[],accounting_refs:[],receipts:[],
  lines:[{id:11,np_code:'NP-A',description:'Pieza A',attention_id:71,in_selected_attention:true,
    attention_verified_qty:2,received_qty:2,expected_qty:2,location_attention_required:1,
    final_location:'COUNT-A',count_location_saved:1,final_location_confirmed:0},
    {id:12,np_code:'NP-B',description:'Pieza B sin stock',attention_id:71,in_selected_attention:true,
    attention_verified_qty:1,received_qty:1,expected_qty:1,location_attention_required:1,
    final_location:'',count_location_saved:1,count_location_manual:1,stock_cut_qty:0,final_location_confirmed:0},
    {id:13,np_code:'NP-LATER',description:'Aun no recibido',attention_id:71,in_selected_attention:true,
      attention_verified_qty:0,received_qty:0,expected_qty:3,location_attention_required:1,
      final_location:'',count_location_saved:1,final_location_confirmed:0}]});
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    for(const width of [320,393,1366]){
      const context=await browser.newContext({viewport:{width,height:873}}),page=await context.newPage();
      await context.addInitScript(()=>{
        window.Html5Qrcode=class{
          async start(_device,_options,onRead){if(window.qaCameraDenied)throw Error('NotAllowedError');this.isScanning=true;window.qaLocationRead=onRead;}
          async stop(){this.isScanning=false;}
          clear(){}
        };
      });
      let current=sample(),hold=false,release,fail=false;const posts=[],errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      await page.route('**/*',async route=>{
        const req=route.request(),url=new URL(req.url());assert.equal(url.origin,base);
        if(url.pathname==='/reception')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'frontend/templates/reception.html'))});
        if(url.pathname.startsWith('/assets/')){
          const file=path.join(root,'frontend/static',path.basename(url.pathname));
          return fs.existsSync(file)?route.fulfill({path:file}):route.fulfill({status:204,body:''});
        }
        if(req.method()==='POST'){
          const body=req.postDataJSON();posts.push({path:url.pathname,body});
          if(hold)await new Promise(resolve=>{release=resolve});
          if(fail)return route.fulfill({status:400,json:{error:'QA no se pudo guardar'}});
          if(url.pathname.endsWith('/location-lines')){
            assert.equal(url.pathname,'/api/receptions/501/location-lines');assert.equal(body.attention_id,71);
            assert.equal(body.locations.length,1);
            const item=body.locations[0],line=current.lines.find(l=>l.id===item.line_id);
            assert(line);Object.assign(line,{final_location:item.final_location,final_location_confirmed:1,count_location_saved:1,count_location_manual:0});
          }else{assert.equal(url.pathname,'/api/receptions/501/status');current.app_status=body.status;}
          return route.fulfill({json:current});
        }
        let data={};
        if(['/api/me','/api/account'].includes(url.pathname))data={username:'qa.worker',role:'ASISTENTE_RECEPCION',mode:'demo',show_guidance:false};
        else if(['/api/receptions','/api/truck-guides'].includes(url.pathname))data=[];
        else if(url.pathname==='/api/assignees')data={users:[]};
        else if(url.pathname==='/api/receptions/501')data=current;
        return route.fulfill({json:data});
      });
      await page.goto(base+'/reception');await page.waitForFunction(()=>document.querySelector('.home-welcome')&&window.WmsNpScan);
      await page.evaluate(s=>{document.querySelector('#role').value='ASISTENTE_RECEPCION';document.querySelector('#user').value='qa.worker';
        selectedId=s.id;selectedAttentionId=s.attention_id;selected=s;renderDetail();activateReceptionTab('ubicacion')},current);
      assert.equal(await page.locator('#final-location-11').isEditable(),true);
      assert.equal(await page.locator('#final-location-12').inputValue(),'');
      assert.equal(await page.locator('#locationProgress').textContent(),'0/2 guardados');
      assert.equal(await page.locator('#final-location-13').count(),0,'Unreceived NP does not require putaway');
      await page.locator('#final-location-12').fill('BIN-B');
      await page.locator('#final-location-11').fill('BIN-A');
      await page.locator('#location-save-11').click();
      await page.waitForFunction(()=>document.querySelector('#locationProgress').textContent==='1/2 guardados');
      assert.equal(await page.locator('#final-location-12').inputValue(),'BIN-B','Other NP draft survives server response');
      assert.equal(posts.length,1);assert.equal(posts[0].body.locations[0].previous_location,'COUNT-A');
      await page.evaluate(()=>advance('VALIDACION'));assert.equal(posts.length,1);
      hold=true;await page.locator('#location-save-12').click();
      await page.waitForFunction(()=>document.querySelector('#location-state-12').textContent==='Guardando...');
      await page.evaluate(()=>{saveFinalLocations(12);advance('VALIDACION')});assert.equal(posts.length,2);
      await page.locator('#final-location-12').fill('BIN-B-EDITED');release();hold=false;
      await page.waitForFunction(()=>document.querySelector('#location-state-12').textContent==='Cambios sin guardar');
      assert.equal(await page.locator('#final-location-12').inputValue(),'BIN-B-EDITED','Editing during request survives');
      fail=true;await page.locator('#location-save-12').click();
      await page.getByText('QA no se pudo guardar',{exact:true}).first().waitFor();
      assert.equal(await page.locator('#final-location-12').inputValue(),'BIN-B-EDITED');
      fail=false;await page.locator('#location-save-12').click();
      await page.waitForFunction(()=>document.querySelector('#locationProgress').textContent==='2/2 guardados');
      assert.equal(await page.evaluate(()=>receptionHasUnsavedFields()),false);
      await page.locator('#locationNpFilter').fill('NP-B');await page.evaluate(()=>filterReceptionNpRows('location'));
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
      assert.ok((await page.locator('#location-save-12').boundingBox()).height>=44);
      fs.mkdirSync(path.join(root,'qa/location-progress'),{recursive:true});
      await page.screenshot({path:path.join(root,`qa/location-progress/saved-${width}.png`)});
      await page.evaluate(()=>advance('VALIDACION'));await page.waitForFunction(()=>selected.app_status==='VALIDACION');
      assert.equal(posts.filter(p=>p.path.endsWith('/status')).length,1);
      // A late reply must never replace another BL/arrival now on screen.
      current=sample();await page.evaluate(s=>{selected=s;selectedId=501;selectedAttentionId=71;renderDetail();activateReceptionTab('ubicacion')},current);
      await page.locator('#locationNpFilter').fill('');await page.evaluate(()=>filterReceptionNpRows('location'));
      await page.locator('#final-location-11').fill('OLD-CONTEXT-SAVE');hold=true;
      await page.locator('#location-save-11').click();await page.waitForFunction(()=>receptionLocationSaves.size===1);
      await page.evaluate(s=>{s.id=777;s.attention_id=88;s.active_attention_id=88;selected=s;selectedId=777;selectedAttentionId=88;renderDetail();activateReceptionTab('ubicacion')},sample());
      release();hold=false;await page.waitForFunction(()=>receptionLocationSaves.size===0);
      assert.equal(await page.evaluate(()=>selected.id),777);
      assert.equal(await page.locator('#final-location-11').inputValue(),'COUNT-A');
      // Physical reader replaces the suggested bin; Enter saves only this NP.
      current=sample();await page.evaluate(s=>{selected=s;selectedId=s.id;selectedAttentionId=s.attention_id;renderDetail();activateReceptionTab('ubicacion')},current);
      await page.locator('#locationNpFilter').fill('');await page.evaluate(()=>filterReceptionNpRows('location'));
      const location=page.locator('#final-location-11'),other=page.locator('#final-location-12');
      assert.equal(await page.locator('[data-location-camera="11"]').count(),1,'Location offers a camera reader beside its field');
      await other.fill('KEEP-OTHER-DRAFT');await location.focus();
      assert.deepEqual(await location.evaluate(input=>[input.selectionStart,input.selectionEnd]),[0,'COUNT-A'.length]);
      await page.keyboard.type(']d101-02-A-03-01');const beforeReader=posts.length;
      await location.press('Enter');
      await page.waitForFunction(()=>selected.lines[0].final_location==='01-02-A-03-01'&&selected.lines[0].final_location_confirmed);
      assert.equal(posts.length,beforeReader+1);assert.equal(await other.inputValue(),'KEEP-OTHER-DRAFT');
      // Camera fills a draft for the chosen NP, never registers the bin as a package/NP.
      await page.locator('[data-location-camera="11"]').click();
      await page.waitForFunction(()=>document.querySelector('#wmsCameraStatus')?.textContent==='Listo para leer');
      assert.equal(await page.locator('#wmsCameraTitle').textContent(),'Escanear ubicación');
      assert.equal(await page.locator('.wms-camera-continuous').isVisible(),false);
      const beforeCamera=posts.length;
      await page.evaluate(()=>qaLocationRead(']d101-02-B-04-01'));
      await page.locator('#wmsBarcodeCamera').waitFor({state:'hidden'});
      assert.equal(posts.length,beforeCamera,'Camera only fills the location draft');
      assert.equal(await location.inputValue(),'01-02-B-04-01');
      assert.equal(await other.inputValue(),'KEEP-OTHER-DRAFT');
      assert.equal(await page.evaluate(()=>document.activeElement.id),'location-save-11');
      await page.locator('#location-save-11').click();
      await page.waitForFunction(()=>selected.lines[0].final_location==='01-02-B-04-01');
      // Invalid scans preserve the saved bin and can be retried without posting.
      await page.locator('[data-location-camera="11"]').click();
      await page.waitForFunction(()=>document.querySelector('#wmsCameraStatus')?.textContent==='Listo para leer');
      const beforeInvalid=posts.length;
      await page.evaluate(()=>qaLocationRead('X'.repeat(121)));
      await page.locator('#wmsCameraError').waitFor({state:'visible'});
      assert.equal(await location.inputValue(),'01-02-B-04-01');assert.equal(posts.length,beforeInvalid);
      await page.locator('#wmsCameraResume').click();
      await page.evaluate(()=>qaLocationRead('01-02-C-05-01'));
      await page.locator('#wmsBarcodeCamera').waitFor({state:'hidden'});
      assert.equal(await location.inputValue(),'01-02-C-05-01');
      // Denied camera access keeps the physical-reader/manual path and its draft.
      await page.evaluate(()=>{qaCameraDenied=true});
      await page.locator('[data-location-camera="12"]').click();
      await page.locator('#wmsCameraError').waitFor({state:'visible'});
      await page.locator('#wmsCameraManual').click();
      assert.equal(await other.inputValue(),'KEEP-OTHER-DRAFT');
      assert.equal(await page.evaluate(()=>document.activeElement.id),'final-location-12');
      await page.keyboard.type('01-02-D-06-01');await other.press('Enter');
      await page.waitForFunction(()=>selected.lines[1].final_location==='01-02-D-06-01');
      // Same-BL rerenders and other arrivals invalidate old callbacks too.
      await page.evaluate(()=>{qaCameraDenied=false});
      await page.locator('[data-location-camera="11"]').click();
      await page.waitForFunction(()=>document.querySelector('#wmsCameraStatus')?.textContent==='Listo para leer');
      await page.evaluate(()=>{window.qaStaleLocationRead=qaLocationRead;renderDetail();activateReceptionTab('ubicacion')});
      await page.locator('#wmsBarcodeCamera').waitFor({state:'hidden'});
      await page.evaluate(()=>qaStaleLocationRead('OLD-BIN'));
      assert.equal(await location.inputValue(),'01-02-B-04-01','A removed draft is not restored by an old camera callback');
      await page.locator('[data-location-camera="11"]').click();
      await page.waitForFunction(()=>document.querySelector('#wmsCameraStatus')?.textContent==='Listo para leer');
      await page.evaluate(s=>{window.qaStaleLocationRead=qaLocationRead;s.attention_id=99;selected=s;selectedAttentionId=99;renderDetail();activateReceptionTab('ubicacion')},sample());
      await page.locator('#wmsBarcodeCamera').waitFor({state:'hidden'});
      const beforeStale=posts.length;await page.evaluate(()=>qaStaleLocationRead('WRONG-ARRIVAL'));
      assert.equal(await location.inputValue(),'COUNT-A');assert.equal(posts.length,beforeStale);
      const buttonBox=await page.locator('[data-location-camera="11"]').boundingBox();
      assert.ok(buttonBox.width>=44&&buttonBox.height>=44);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
      await page.screenshot({path:path.join(root,`qa/location-progress/scanner-${width}.png`)});
      await page.evaluate(()=>{selected.app_status='VALIDACION';renderDetail();activateReceptionTab('ubicacion')});
      assert.equal(await page.locator('[data-location-camera]').count(),0,'Later stages cannot scan/change final destinations');
      assert.deepEqual(errors,[]);await context.close();
    }
    console.log('OK location progress/scan: 3 widths, row saves/drafts, physical Enter/AIM, camera draft/retry/denial, stale arrival/DOM and read-only stages.');
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
