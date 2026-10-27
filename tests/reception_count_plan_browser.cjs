// Synthetic HTTP; no corporate data, real database writes or email.
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),base='http://127.0.0.1:51991';
const sample=()=>({id:501,bl_awb:'QA-BL',app_status:'UBICACION',condition_status:'EN PROCESO',
  attention_id:71,active_attention_id:71,attention_count:1,received_packages:2,
  attentions:[{id:71,label:'Entrega 1',app_status:'UBICACION'}],lines:[],accounting_refs:[],
  count_plan:{lines:[{id:12,np_code:'NP-LATE',description:'Pieza pendiente',expected_qty:4}],
    can_include:true,reopens_count:true,state_token:'synthetic-state'}});
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    for(const width of [320,393,1366]){
      const context=await browser.newContext({viewport:{width,height:873}}),page=await context.newPage();
      await page.addInitScript(()=>{window.qaEvents=[];for(const kind of ['pointerdown','pointerup','click'])document.addEventListener(kind,e=>qaEvents.push({kind,id:e.target.id,tag:e.target.tagName}),true)});
      const errors=[],writes=[];let current=sample(),hold=false,release,fail=false;
      page.on('pageerror',e=>errors.push(e.message));
      await page.route('**/*',async route=>{
        const req=route.request(),url=new URL(req.url());assert.equal(url.origin,base);
        if(url.pathname==='/reception')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'frontend/templates/reception.html'))});
        if(url.pathname.startsWith('/assets/')){
          const file=path.join(root,'frontend/static',path.basename(url.pathname));
          return fs.existsSync(file)?route.fulfill({path:file}):route.fulfill({status:204,body:''});
        }
        if(req.method()==='POST'){
          assert.equal(url.pathname,'/api/receptions/501/count/include-lines');writes.push(req.postDataJSON());
          if(hold)await new Promise(resolve=>{release=resolve});
          if(fail)return route.fulfill({status:400,json:{error:'El corte cambio; actualiza la BL'}});
          current={...current,app_status:'REVISION SISTEMA',count_plan:{lines:[],can_include:true}};
          return route.fulfill({json:current});
        }
        let data={};
        if(['/api/me','/api/account'].includes(url.pathname))data={username:'qa.admin',role:'ADMINISTRADOR',mode:'demo',show_guidance:false};
        else if(['/api/receptions','/api/truck-guides'].includes(url.pathname))data=[];
        else if(url.pathname==='/api/assignees')data={users:[]};
        else if(url.pathname==='/api/receptions/501')data=current;
        return route.fulfill({json:data});
      });
      await page.goto(base+'/reception');
      await page.waitForFunction(()=>document.querySelector('.home-welcome'));
      await page.evaluate(s=>{selectedId=501;selectedAttentionId=71;selected=s;renderDetail()},current);
      await page.locator('#countPlanOpen').waitFor();
      assert.match(await page.locator('.late-count-lines').innerText(),/NP-LATE/);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
      // Replacing detail markup must not leave a visible action without its handler.
      await page.evaluate(()=>{const button=document.querySelector('#countPlanOpen');button.replaceWith(button.cloneNode(true));});
      await page.locator('#countPlanOpen').click();
      assert.equal(await page.locator('#countPlanDialog').evaluate(e=>e.open),true,
        JSON.stringify(await page.evaluate(()=>({dirty:receptionHasUnsavedFields(),message:document.querySelector('.toast')?.textContent,
          admin:isAdmin(),role:role(),npPending:WmsNpScan?.hasPending?.(),packagePending:WmsPackageReview?.hasPending?.(),
          selectedId,selectedAttentionId,countPlan:selected?.count_plan,dialogCount:document.querySelectorAll('#countPlanDialog').length,
          events:qaEvents,
          controls:[...document.querySelectorAll('#content input,#content textarea,#content select')].map(e=>({id:e.id,value:e.value,initial:e.defaultValue}))}))));
      assert.equal(await page.locator('#countPlanSubmit').isDisabled(),true);
      await page.locator('[data-count-plan-line]').check();
      await page.locator('#countPlanReason').fill('Pertenece a esta entrega fisica');
      for(const selector of ['.count-plan-choice','#countPlanClose','#countPlanSubmit']){
        const box=await page.locator(selector).boundingBox();assert.ok(box.height>=44&&box.width>=44,selector);
      }
      fs.mkdirSync(path.join(root,'qa/count-plan'),{recursive:true});
      await page.screenshot({path:path.join(root,`qa/count-plan/confirm-${width}.png`)});
      assert.match(await page.locator('#countPlanEffect').innerText(),/Inicio de conteo/);
      hold=true;await page.locator('#countPlanSubmit').click();
      await page.evaluate(()=>document.querySelector('#countPlanSubmit').click());
      assert.equal(writes.length,1);assert.equal(writes[0].attention_id,71);
      assert.deepEqual(writes[0].line_ids,[12]);assert.equal(writes[0].confirmed,true);
      assert.equal(writes[0].state_token,'synthetic-state');
      release();await page.waitForFunction(()=>!document.querySelector('#countPlanDialog').open);
      await page.locator('#countPlanOpen').waitFor({state:'detached'});
      // A worker sees the missing NP but cannot alter a frozen plan.
      current=sample();current.count_plan.can_include=false;delete current.count_plan.state_token;
      await page.evaluate(s=>{document.querySelector('#role').value='ASISTENTE_RECEPCION';selected=s;renderDetail()},current);
      assert.match(await page.locator('.late-count-lines').innerText(),/NP-LATE/);
      assert.equal(await page.locator('#countPlanOpen').count(),0);
      assert.equal(writes.length,1);
      // Rejected/stale save keeps the dialog and permits an explicit retry later.
      await page.evaluate(s=>{document.querySelector('#role').value='ADMINISTRADOR';selected=s;renderDetail()},sample());
      hold=false;fail=true;await page.locator('#countPlanOpen').click();
      await page.locator('[data-count-plan-line]').check();
      await page.locator('#countPlanReason').fill('Revisar la nueva fuente importada');
      await page.locator('#countPlanSubmit').click();
      await page.getByText('El corte cambio; actualiza la BL',{exact:true}).waitFor();
      assert.equal(await page.locator('#countPlanDialog').evaluate(e=>e.open),true);
      assert.equal(await page.locator('#countPlanSubmit').isDisabled(),false);
      assert.equal(await page.locator('#countPlanDialog').evaluate(e=>e.scrollWidth<=e.clientWidth+1),true);
      assert.deepEqual(errors,[]);await context.close();
    }
    console.log('OK late-count NP: 3 widths, visibility, roles, selection/reason, one POST, reopen and stale error.');
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
