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
      assert.deepEqual(errors,[]);await context.close();
    }
    console.log('OK location progress: 3 widths, per-NP saves, drafts, in-flight edits, errors, single flight, pending advance and stale replies.');
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
