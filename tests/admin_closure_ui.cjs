// Synthetic browser contract. Every request is intercepted; no server or database.
// Run with cached Playwright on NODE_PATH. ADMIN_CLOSURE_SCREENSHOTS is optional.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const read = file => fs.existsSync(path.join(root, file)) ? fs.readFileSync(path.join(root, file), 'utf8') : '';
const script = read('frontend/static/reception-admin-closure.js');
const css = read('frontend/static/reception-admin-closure.css');
const readerCss = read('frontend/static/reader-ui.css');
const preview = overrides => ({id:71, bl_awb:'QA-BL-000071', attention_id:19,
  app_status:'EM', condition_status:'PENDIENTE', token:'qa-state-token',
  can_reconcile:false, reconcile_blocker:'La referencia IP no coincide.',
  can_retire_test:false, retire_blocker:'Hay evidencia fisica registrada.',
  can_close_bl:true, close_bl_blocker:'', can_close_attention:true, attention_blocker:'',
  open_attention_count:2, unread_np_count:3, pending_np_count:1,
  accounting_status:'CONFLICTO IP', ...overrides});
const result = (action = 'close_attention', overrides = {}) => ({id:71, attention_id:19,
  app_status:'CERRADO',
  condition_status:action === 'reconcile' ? 'COMPLETADO' : action === 'retire_test' ?
    'REGISTRO DE PRUEBA RETIRADO' : 'CIERRE ADMINISTRATIVO', action, unchanged:false, ...overrides});
const shell = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
  <style>body{margin:0;font:16px 'Segoe UI',Arial,sans-serif;color:#29343b}#content{padding:16px}
  button,input,select,textarea{font:inherit}button{padding:10px 14px}.control{padding:8px}
  .primary{background:#f58200;color:#202d35;border:1px solid #b96200}.ghost{background:white;border:1px solid #bcc8ce}
  [hidden]{display:none!important}</style><style>${readerCss}</style><style>${css}</style></head>
  <body class="reader-ui"><nav><button class="nav-item active" data-nav="pending">Recepcion</button></nav>
  <div class="queue"></div><main id="content"></main><p id="toast" role="status"></p>
  <script>
  let selectedId=71, selectedAttentionId=19;
  let selected={id:71,attention_id:19,bl_awb:'QA-BL-000071',app_status:'EM'};
  let qaAdmin=true, qaNpPending=false, qaTruckPending=false;
  const $=id=>document.getElementById(id);
  const isAdmin=()=>qaAdmin;
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function adminRewindCard(){return isAdmin()?'<div class="admin-rewind"><p class="help-guidance">Ayuda opcional</p><button>Reabrir BL</button></div>':''}
  function receptionHasUnsavedFields(){return [...document.querySelectorAll('#content input')].some(input=>input.value!==input.defaultValue)}
  function notify(message,type){qaNotices.push({message,type});$('toast').textContent=message}
  window.qaNotices=[];window.qaLoads=[];
  window.WmsNpScan={hasPending:()=>qaNpPending};window.WmsTruckScan={hasPending:()=>qaTruckPending};
  function api(url,options={}){
    options.headers={...options.headers,'X-Role':isAdmin()?'ADMINISTRADOR':'AUXILIAR'};
    if(options.body&&typeof options.body!=='string'){
      options.body={...options.body,attention_id:selectedAttentionId};
      options.headers['Content-Type']='application/json';options.body=JSON.stringify(options.body);
    }
    return fetch(url,options);
  }
  async function loadDetail(id,keepQueue,aid){qaLoads.push([id,keepQueue,aid]);
    selected={...selected,id,attention_id:aid,app_status:'CERRADO'};selectedId=id;selectedAttentionId=aid;qaRender()}
  function qaRender(){ $('content').innerHTML='<section><h1>'+esc(selected.bl_awb)+'</h1><input id="qaDraft" aria-label="Nota de conteo" value="guardado"><div id="qaAdminControls">'+adminRewindCard(selected)+'</div></section>' }
  function qaNavigate(id=72,aid=20){selected={id,attention_id:aid,bl_awb:'QA-OTHER',app_status:'EM'};selectedId=id;selectedAttentionId=aid;qaRender()}
  </script><script>${script.replace(/<\/script/gi, '<\\/script')}</script><script>qaRender()</script></body></html>`;

function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return {promise, resolve}; }
const reason = 'Revision administrativa solicitada por el responsable.';
let browser, passed = 0;
async function fixture(options = {}) {
  const page = await browser.newPage({viewport:options.viewport || {width:393,height:873}});
  page.setDefaultTimeout(4000);
  const errors = [], requests = [], confirmations = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', async dialog => { confirmations.push(dialog.message()); await (options.decline ? dialog.dismiss() : dialog.accept()); });
  const state = {preview:preview(options.preview), post:result(), getGate:null, postGate:null,
    getStatus:200, postStatus:200, postRaw:null, postType:'application/json'};
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== 'http://wms-admin-closure.test') throw Error('Unexpected external request: ' + url);
    if (url.pathname === '/') return route.fulfill({contentType:'text/html', body:shell});
    assert.equal(url.pathname, '/api/receptions/71/admin-closure');
    requests.push({method:request.method(), url:url.pathname+url.search,
      body:request.postData(), headers:request.headers()});
    const post = request.method() === 'POST';
    const gate = post ? state.postGate : state.getGate;
    if (gate) await gate.promise;
    await route.fulfill({status:post ? state.postStatus : state.getStatus,
      contentType:post ? state.postType : 'application/json',
      body:post && state.postRaw !== null ? state.postRaw : JSON.stringify(post ? state.post : state.preview)}).catch(error => {
        if (!page.isClosed() && !/closed|aborted|Invalid InterceptionId/i.test(error.message)) throw error;
      });
  });
  await page.goto('http://wms-admin-closure.test/');
  return {page, state, requests, errors, confirmations, async close() {
    assert.deepEqual(errors, [], 'No browser errors'); await page.close();
  }};
}
async function open(f) {
  await f.page.getByRole('button', {name:'Regularizar o cerrar BL',exact:true}).click();
  await f.page.waitForFunction(() => document.getElementById('adminClosureAction')?.options.length === 4 &&
    !document.getElementById('adminClosureDialog').getAttribute('aria-busy'));
}
async function fill(f, action = 'close_attention') {
  await f.page.locator('#adminClosureAction').selectOption(action);
  await f.page.locator('#adminClosureReason').fill(reason);
  await f.page.locator('#adminClosureBlConfirmation').fill('QA-BL-000071');
  if (action !== 'reconcile') await f.page.locator('#adminClosureAcknowledge').check();
}
async function idle(f) { await f.page.waitForFunction(() => !document.getElementById('adminClosureDialog').getAttribute('aria-busy')); }
async function test(name, fn) { await fn(); passed++; console.log('OK ' + name); }

(async () => {
  browser = await chromium.launch({headless:true,channel:'msedge'});
  try {
    await test('admin entry survives hidden guidance, closed records, and rerender; workers cannot open', async () => {
      const f = await fixture();
      assert.equal(await f.page.getByRole('button',{name:'Regularizar o cerrar BL',exact:true}).count(), 1);
      assert.equal(await f.page.locator('.help-guidance').isVisible(), false);
      await f.page.evaluate(() => {selected.app_status='CERRADO';qaRender();qaRender()});
      await open(f);
      await f.page.getByRole('button',{name:'Cancelar',exact:true}).click();
      await f.page.evaluate(() => {qaAdmin=false;qaRender();WmsAdminClosure.open()});
      assert.equal(await f.page.getByRole('button',{name:'Regularizar o cerrar BL',exact:true}).count(), 0);
      assert.equal(await f.page.getByRole('dialog').count(), 0);
      assert.equal(f.requests.length, 1);
      await f.close();
    });
    await test('readonly preview shows every action and blocker; cancellation restores focus', async () => {
      const f = await fixture(); await open(f);
      assert.equal(f.requests[0].url, '/api/receptions/71/admin-closure?attention_id=19');
      assert.equal(f.requests[0].method, 'GET');
      assert.equal(await f.page.locator('#adminClosureAction option').count(),4);
      assert.equal(await f.page.locator('#adminClosureAction option[value=reconcile]').isDisabled(),true);
      assert.equal(await f.page.locator('#adminClosureAction option[value=retire_test]').isDisabled(),true);
      assert.match(await f.page.getByRole('dialog').innerText(),/La referencia IP no coincide/);
      assert.match(await f.page.getByRole('dialog').innerText(),/Hay evidencia fisica/);
      assert.equal(await f.page.locator('#qaDraft').inputValue(),'guardado');
      assert.deepEqual(await f.page.evaluate(() => qaLoads),[]);
      await f.page.keyboard.press('Escape');
      assert.equal(await f.page.getByRole('dialog').count(),0);
      assert.equal(await f.page.getByRole('button',{name:'Regularizar o cerrar BL',exact:true}).evaluate(el=>el===document.activeElement),true);
      await f.close();
    });
    await test('all blocked actions stay visible with a disabled review and explicit empty state', async () => {
      const f=await fixture({preview:{app_status:'CERRADO',can_close_bl:false,close_bl_blocker:'BL cerrada.',
        can_close_attention:false,attention_blocker:'Entrega cerrada.'}}); await open(f);
      assert.equal(await f.page.locator('#adminClosureAction option:disabled').count(),4);
      assert.equal(await f.page.locator('#adminClosureSubmit').isDisabled(),true);
      assert.match(await f.page.getByRole('dialog').innerText(),/No hay acciones habilitadas/);
      assert.match(await f.page.getByRole('dialog').innerText(),/Entrega cerrada/);
      await f.close();
    });
    await test('pending NP/truck scans and unsaved warehouse fields block opening without resetting them', async () => {
      const f=await fixture();
      for(const flag of ['qaNpPending','qaTruckPending']) {
        await f.page.evaluate(flag=>window.eval(flag+'=true'),flag);
        await f.page.evaluate(()=>WmsAdminClosure.open());
        assert.equal(await f.page.getByRole('dialog').count(),0);
        await f.page.evaluate(flag=>window.eval(flag+'=false'),flag);
      }
      await f.page.locator('#qaDraft').fill('borrador conservado');
      await f.page.evaluate(()=>WmsAdminClosure.open());
      assert.equal(await f.page.getByRole('dialog').count(),0);
      assert.equal(await f.page.locator('#qaDraft').inputValue(),'borrador conservado');
      assert.equal(f.requests.length,0);await f.close();
    });
    await test('exact typed BL, reason bounds, and exceptional acknowledgment are mandatory', async () => {
      const f=await fixture();await open(f);await fill(f);
      for(const [id,value] of [['adminClosureReason','short'],['adminClosureBlConfirmation','QA-BL-71']]) {
        await f.page.locator('#'+id).fill(value);
        await f.page.locator('#adminClosureSubmit').click();
        assert.equal(f.requests.filter(r=>r.method==='POST').length,0);
        assert.equal(await f.page.locator('#adminClosureError').isVisible(),true);
        assert.equal(await f.page.locator('#'+id).evaluate(el=>el===document.activeElement),true);
        await fill(f);
      }
      await f.page.evaluate(()=>document.getElementById('adminClosureReason').value='x'.repeat(501));
      await f.page.locator('#adminClosureSubmit').click();
      assert.equal(f.requests.filter(r=>r.method==='POST').length,0);
      await fill(f);await f.page.locator('#adminClosureAcknowledge').uncheck();
      await f.page.locator('#adminClosureSubmit').click();
      assert.equal(f.requests.filter(r=>r.method==='POST').length,0);await f.close();
    });
    for(const [action,scope] of [['reconcile',/validado/i],['retire_test',/no acredita.*recepcion fisica/i],
      ['close_bl',/todas las entregas/i],['close_attention',/BL.*permanece abierta/i]]) {
      await test(action+' confirms its scope and reloads only its exact delivery',async()=>{
        const f=await fixture({preview:{can_reconcile:true,reconcile_blocker:'',can_retire_test:true,retire_blocker:''}});
        f.state.post=result(action);await open(f);await fill(f,action);
        assert.match(await f.page.locator('#adminClosureStatus').innerText(),scope);
        await f.page.locator('#adminClosureSubmit').click();
        await f.page.waitForFunction(()=>!document.getElementById('adminClosureDialog').open);
        const request=f.requests.find(r=>r.method==='POST');assert(request);
        assert.deepEqual(JSON.parse(request.body),{action,token:'qa-state-token',confirmed:true,
          bl_confirmation:'QA-BL-000071',reason,attention_id:19,acknowledge_unverified:action!=='reconcile'});
        assert.match(request.headers['content-type'],/application\/json/);
        assert.match(f.confirmations.at(-1),scope);
        assert.deepEqual(await f.page.evaluate(()=>qaLoads),[[71,false,19]]);
        assert.match(await f.page.locator('#toast').innerText(),/QA-BL-000071/);
        if(action==='close_attention') assert.match(await f.page.locator('#toast').innerText(),/19.*BL.*abierta/);
        await f.close();
      });
    }
    await test('declining final scope confirmation sends no POST',async()=>{
      const f=await fixture({decline:true});await open(f);await fill(f);await f.page.locator('#adminClosureSubmit').click();
      assert.equal(f.requests.filter(r=>r.method==='POST').length,0);
      assert.equal(await f.page.locator('#adminClosureReason').inputValue(),reason);await f.close();
    });
    await test('double submission sends one POST; busy state prevents Escape and cancel',async()=>{
      const f=await fixture();await open(f);await fill(f);const gate=deferred();f.state.postGate=gate;
      await f.page.evaluate(()=>{document.getElementById('adminClosureForm').requestSubmit();document.getElementById('adminClosureForm').requestSubmit()});
      await f.page.waitForFunction(()=>document.getElementById('adminClosureDialog').getAttribute('aria-busy')==='true');
      assert.equal(await f.page.getByRole('button',{name:'Cancelar',exact:true}).isDisabled(),true);
      await f.page.keyboard.press('Escape');assert.equal(await f.page.getByRole('dialog').count(),1);
      gate.resolve();await f.page.waitForFunction(()=>!document.getElementById('adminClosureDialog').open);
      assert.equal(f.requests.filter(r=>r.method==='POST').length,1);await f.close();
    });
    for(const failure of ['503','invalid JSON','stale token','mismatched result']) {
      await test(failure+' preserves fields and permits explicit review',async()=>{
        const f=await fixture();await open(f);await fill(f);
        if(failure==='503'){f.state.postStatus=503;f.state.post={error:'Servicio temporalmente no disponible.'}}
        if(failure==='invalid JSON'){f.state.postRaw='<html>offline</html>';f.state.postType='text/html'}
        if(failure==='stale token'){f.state.postStatus=409;f.state.post={error:'La revision perdio vigencia.'}}
        if(failure==='mismatched result') f.state.post=result('close_attention',{attention_id:20});
        await f.page.locator('#adminClosureSubmit').click();await idle(f);
        assert.equal(await f.page.locator('#adminClosureError').isVisible(),true);
        assert.equal(await f.page.locator('#adminClosureReason').inputValue(),reason);
        assert.equal(await f.page.locator('#adminClosureBlConfirmation').inputValue(),'QA-BL-000071');
        assert.equal(await f.page.locator('#adminClosureAcknowledge').isChecked(),true);
        assert.deepEqual(await f.page.evaluate(()=>qaLoads),[]);
        assert.equal(await f.page.locator('#adminClosureSubmit').isDisabled(),true);
        assert.deepEqual(await f.page.evaluate(()=>qaNotices.filter(notice=>notice.type==='success')),[]);
        await f.page.getByRole('button',{name:'Actualizar revision',exact:true}).click();await idle(f);
        assert.equal(await f.page.locator('#adminClosureReason').inputValue(),reason);
        assert.equal(await f.page.locator('#adminClosureSubmit').isEnabled(),true);
        await f.close();
      });
    }
    await test('preview HTTP errors retain cancellation and retry controls',async()=>{
      const f=await fixture();f.state.getStatus=403;f.state.preview={error:'Solo administradores.'};
      await f.page.getByRole('button',{name:'Regularizar o cerrar BL',exact:true}).click();await idle(f);
      assert.match(await f.page.locator('#adminClosureError').innerText(),/Solo administradores/);
      assert.equal(await f.page.locator('#adminClosureSubmit').isDisabled(),true);
      f.state.getStatus=200;f.state.preview=preview();
      await f.page.getByRole('button',{name:'Actualizar revision',exact:true}).click();await idle(f);
      assert.equal(await f.page.locator('#adminClosureSubmit').isEnabled(),true);await f.close();
    });
    for(const change of ['shipment','attention','same-id-new-detail','queue','draft','scan']) {
      await test('late POST cannot reload after '+change+' changes',async()=>{
        const f=await fixture();await open(f);await fill(f);const gate=deferred();f.state.postGate=gate;
        await f.page.locator('#adminClosureSubmit').click();
        await f.page.waitForFunction(()=>document.getElementById('adminClosureDialog').getAttribute('aria-busy')==='true');
        await f.page.evaluate(change=>{
          if(change==='shipment')qaNavigate();
          if(change==='attention')selectedAttentionId=20;
          if(change==='same-id-new-detail')qaNavigate(71,19);
          if(change==='queue')document.querySelector('.queue').classList.add('open');
          if(change==='draft')document.getElementById('qaDraft').value='edicion en curso';
          if(change==='scan')qaNpPending=true;
        },change);
        gate.resolve();await idle(f);
        assert.deepEqual(await f.page.evaluate(()=>qaLoads),[]);
        assert.equal(await f.page.locator('#adminClosureReason').inputValue(),reason);
        assert.equal(await f.page.locator('#adminClosureError').isVisible(),true);
        assert.equal(f.requests.filter(r=>r.method==='POST').length,1);await f.close();
      });
    }
    await test('late preview cannot enable an action in a different delivery',async()=>{
      const f=await fixture();const gate=deferred();f.state.getGate=gate;
      await f.page.getByRole('button',{name:'Regularizar o cerrar BL',exact:true}).click();
      await f.page.evaluate(()=>qaNavigate());gate.resolve();await idle(f);
      assert.equal(await f.page.locator('#adminClosureSubmit').isDisabled(),true);
      assert.equal(await f.page.locator('#adminClosureError').isVisible(),true);await f.close();
    });
    await test('no selected delivery uses a null POST scope and no attention query',async()=>{
      const f=await fixture({preview:{attention_id:null,can_close_attention:false,attention_blocker:'Selecciona una entrega.'}});
      await f.page.evaluate(()=>{selectedAttentionId=null;selected.attention_id=null;qaRender()});
      f.state.post=result('close_bl',{attention_id:null});await open(f);await fill(f,'close_bl');
      assert.equal(f.requests[0].url,'/api/receptions/71/admin-closure');
      await f.page.locator('#adminClosureSubmit').click();await f.page.waitForFunction(()=>!document.getElementById('adminClosureDialog').open);
      assert.equal(JSON.parse(f.requests.find(r=>r.method==='POST').body).attention_id,null);
      assert.deepEqual(await f.page.evaluate(()=>qaLoads),[[71,false,null]]);await f.close();
    });
    for(const failure of ['empty object','ok flag only','missing id','missing attention_id','missing action',
      'wrong action','missing app_status','open state','missing condition_status','wrong condition','invalid JSON 200']) {
      await test(failure+' cannot announce closure or reload; review is mandatory',async()=>{
        const f=await fixture();await open(f);await fill(f);
        if(failure==='empty object')f.state.post={};
        if(failure==='ok flag only')f.state.post={ok:true};
        if(failure.startsWith('missing '))delete f.state.post[failure.slice(8)];
        if(failure==='wrong action')f.state.post=result('close_bl');
        if(failure==='open state')f.state.post=result('close_attention',{app_status:'EM'});
        if(failure==='wrong condition')f.state.post=result('close_attention',{condition_status:'COMPLETADO'});
        if(failure==='invalid JSON 200')f.state.postRaw='{"id":71,not-json';
        await f.page.locator('#adminClosureSubmit').click();await idle(f);
        assert.equal(await f.page.getByRole('dialog').count(),1,'Uncertain response keeps the review open');
        assert.equal(await f.page.locator('#adminClosureError').isVisible(),true);
        assert.equal(await f.page.locator('#adminClosureReason').inputValue(),reason);
        assert.equal(await f.page.locator('#adminClosureBlConfirmation').inputValue(),'QA-BL-000071');
        assert.equal(await f.page.locator('#adminClosureAcknowledge').isChecked(),true);
        assert.equal(await f.page.locator('#adminClosureSubmit').isDisabled(),true);
        assert.deepEqual(await f.page.evaluate(()=>qaLoads),[]);
        assert.deepEqual(await f.page.evaluate(()=>qaNotices.filter(notice=>notice.type==='success')),[]);
        await f.page.evaluate(()=>document.getElementById('adminClosureForm').requestSubmit());
        assert.equal(f.requests.filter(request=>request.method==='POST').length,1,'No automatic or unreviewed retry');
        await f.page.getByRole('button',{name:'Actualizar revision',exact:true}).click();await idle(f);
        assert.equal(await f.page.locator('#adminClosureSubmit').isEnabled(),true);
        assert.equal(await f.page.locator('#adminClosureReason').inputValue(),reason);
        await f.close();
      });
    }
    for(const action of ['reconcile','retire_test','close_bl']) {
      await test(action+' rejects a closed response with the wrong condition',async()=>{
        const f=await fixture({preview:{can_reconcile:true,reconcile_blocker:'',can_retire_test:true,retire_blocker:''}});
        await open(f);await fill(f,action);
        f.state.post=result(action,{condition_status:action==='reconcile'?'CIERRE ADMINISTRATIVO':'COMPLETADO'});
        await f.page.locator('#adminClosureSubmit').click();await idle(f);
        assert.equal(await f.page.getByRole('dialog').count(),1);
        assert.equal(await f.page.locator('#adminClosureError').isVisible(),true);
        assert.equal(await f.page.locator('#adminClosureSubmit').isDisabled(),true);
        assert.equal(await f.page.locator('#adminClosureReason').inputValue(),reason);
        assert.deepEqual(await f.page.evaluate(()=>qaLoads),[]);
        assert.deepEqual(await f.page.evaluate(()=>qaNotices.filter(notice=>notice.type==='success')),[]);
        await f.close();
      });
    }
    for(const viewport of [{width:320,height:640},{width:393,height:873},{width:1366,height:768},{width:873,height:393}]) {
      for(const scale of [1,2]) {
        await test('reflow, keyboard, and reachable controls '+viewport.width+'x'+viewport.height+' text '+scale*100+'%',async()=>{
          const f=await fixture({viewport});
          if(scale===2) await f.page.addStyleTag({content:'html{font-size:32px}body{font-size:32px}'});
          await open(f);await fill(f);
          assert.equal(await f.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
          assert.equal(await f.page.locator('#adminClosureDialog').evaluate(el=>el.scrollWidth<=el.clientWidth+1),true);
          for(const selector of ['#adminClosureAction','#adminClosureReason','#adminClosureBlConfirmation','#adminClosureSubmit']) {
            const el=f.page.locator(selector);await el.scrollIntoViewIfNeeded();const box=await el.boundingBox();
            assert(box.x>=0&&box.x+box.width<=viewport.width+1,selector+' fits horizontally');
            assert(box.height>=44,selector+' touch target');
          }
          const el=f.page.locator('#adminClosureSubmit');await el.focus();await f.page.keyboard.press('Tab');
          assert.equal(await f.page.getByRole('dialog').evaluate(el=>el.contains(document.activeElement)),true,'Focus stays in dialog');
          if(process.env.ADMIN_CLOSURE_SCREENSHOTS){fs.mkdirSync(process.env.ADMIN_CLOSURE_SCREENSHOTS,{recursive:true});
            await f.page.screenshot({path:path.join(process.env.ADMIN_CLOSURE_SCREENSHOTS,`closure-${viewport.width}-${scale}.png`)});}
          await f.page.keyboard.press('Escape');assert.equal(await f.page.getByRole('dialog').count(),0);await f.close();
        });
      }
    }
    console.log('PASS '+passed+' admin closure browser contracts (synthetic API only).');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1});
