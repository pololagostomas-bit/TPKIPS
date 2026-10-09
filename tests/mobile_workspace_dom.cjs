// Pure DOM integration tests against support_mobile_server.py, never a real browser.
const {JSDOM,ResourceLoader,VirtualConsole}=require('jsdom');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const base=process.argv[2];
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable loopback fixture only');
const tick=()=>new Promise(resolve=>setTimeout(resolve,25));
async function until(check){for(let i=0;i<160;i++){if(check())return;await tick()}throw Error('DOM condition timed out')}
function freeze(name,w){
 const copy=w.document.documentElement.cloneNode(true);
 const source=[...w.document.querySelectorAll('input,select,textarea')];
 copy.querySelectorAll('input,select,textarea').forEach((control,index)=>{
  const original=source[index];
  if(control.tagName==='SELECT')[...control.options].forEach((option,i)=>option.toggleAttribute('selected',original.options[i].selected));
  else if(control.tagName==='TEXTAREA')control.textContent=original.value;
  else{control.setAttribute('value',original.value);control.toggleAttribute('checked',original.checked)}
 });
 copy.querySelectorAll('script,.workspace-loading,#toast').forEach(node=>node.remove());
 copy.querySelectorAll('*').forEach(node=>{for(const attribute of [...node.attributes])if(attribute.name.startsWith('on'))node.removeAttribute(attribute.name)});
 copy.querySelectorAll('[href^="/assets/"],[src^="/assets/"]').forEach(node=>{for(const attribute of ['href','src'])if(node.getAttribute(attribute)?.startsWith('/assets/'))node.setAttribute(attribute,base+node.getAttribute(attribute))});
 copy.querySelector('body').classList.add('qa-mobile-snapshot');
 const sizing=w.document.createElement('script');
 sizing.textContent="function fit(){document.documentElement.style.setProperty('--wms-visible-height',innerHeight+'px');const m=document.querySelector('main.layout');if(m)m.style.height=Math.max(160,innerHeight-m.getBoundingClientRect().top-(document.getElementById('bottomNav')?.getBoundingClientRect().height||0))+'px'}addEventListener('load',fit);addEventListener('resize',fit);fit();";
 copy.querySelector('body').append(sizing);
 const directory=path.join(__dirname,'..','qa','runtime','mobile-views');fs.mkdirSync(directory,{recursive:true});
 fs.writeFileSync(path.join(directory,name+'.html'),'<!doctype html>'+copy.outerHTML);
}
async function page(route){
 const errors=[],posts=[];let pending=0;
 const log=new VirtualConsole();log.on('jsdomError',error=>{if(!error.message.includes('Could not parse CSS'))errors.push(error.message)});
 const resources=new class extends ResourceLoader{fetch(url){return url.startsWith(base)?fetch(url).then(r=>r.arrayBuffer()).then(b=>Buffer.from(b)):Promise.resolve(Buffer.from(''))}};
 const html=await (await fetch(base+route)).text();
 const dom=new JSDOM(html,{url:base+route,runScripts:'dangerously',resources,pretendToBeVisual:true,virtualConsole:log,beforeParse(w){
  w.ResizeObserver=class{observe(){}disconnect(){}};w.AbortController=AbortController;w.Headers=Headers;w.Request=Request;w.Response=Response;
  w.requestAnimationFrame=callback=>w.setTimeout(()=>callback(Date.now()),0);w.cancelAnimationFrame=id=>w.clearTimeout(id);
  w.HTMLElement.prototype.scrollIntoView=function(){};w.scrollTo=()=>{};
  Object.defineProperty(w.HTMLElement.prototype,'innerText',{get(){return this.textContent},set(value){this.textContent=value}});
  w.HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','')};w.HTMLDialogElement.prototype.close=function(){this.removeAttribute('open')};
  w.CSS={escape:value=>String(value).replace(/[^a-zA-Z0-9_-]/g,'\\$&')};
  w.confirm=()=>true;w.prompt=()=>'Correccion de prueba movil';w.alert=message=>errors.push('Alert: '+message);
  w.fetch=(url,options={})=>{const absolute=new URL(url,base).href;if(options.method==='POST')posts.push({url:absolute,body:options.body});pending++;return fetch(absolute,options).finally(()=>pending--)};
 }});
 await until(()=>dom.window.document.body.classList.contains('mobile-workspace'));
 await until(()=>pending===0);await tick();await until(()=>pending===0);return {dom,w:dom.window,d:dom.window.document,errors,posts};
}
module.exports={page,until,tick,freeze};
if(require.main===module)(async()=>{
 let q=await page('/reception');
 try{
  await until(()=>q.d.querySelector('#content .home-stat,.home-stats,.dashboard-stats,.home-tile')||q.d.querySelector('#content').textContent.includes('BL visibles'));
  await q.w.showPendingDeliveries();await tick();
  freeze('reception-transfers',q.w);
  assert.match(q.d.querySelector('#content').textContent,/QA-MOBILE-6/,'Transfers must contain actual BL');
  assert.ok(q.d.querySelector('.mobile-sort'),'Mobile sorting is retained');
  await q.w.showMyWork();await tick();
  freeze('reception-work',q.w);
  assert.ok(q.d.querySelector('.work-global-summary h3'),'Async work summary survives rendering');
  const workTable=q.d.querySelector('table.mobile-records');
  const names=()=>[...workTable.tBodies[0].rows].filter(row=>row.cells.length>1).map(row=>row.cells[0].textContent.trim());
  const expected=names().sort((a,b)=>b.localeCompare(a,'es',{numeric:true,sensitivity:'base'}));
  const sorting=workTable.parentElement.querySelector('.mobile-sort select');
  sorting.value='0:desc';sorting.dispatchEvent(new q.w.Event('change',{bubbles:true}));await tick();
  assert.deepEqual(names(),expected,'Mobile sorting invokes the original BL column action');
  for(let id=1;id<=8;id++){
   await q.w.loadDetail(id);await tick();
   const nav=q.d.querySelector('.mobile-stage-select select');assert.ok(nav,'Every BL has a mobile stage selector');
   freeze('reception-stage-'+id,q.w);
   const buttons=[...q.d.querySelectorAll('.detail-tabs button')];
   for(let index=0;index<buttons.length;index++){
    nav.value=String(index);nav.dispatchEvent(new q.w.Event('change',{bubbles:true}));await tick();
    const active=buttons.findIndex(button=>button.getAttribute('aria-current')==='step');
    assert.equal(Number(nav.value),active,'Selector follows the actual tab');
   }
   assert.equal(nav.dataset.wmsNavigation,'true');
   if(q.d.querySelector('.admin-rewind'))assert.equal(q.d.querySelectorAll('.wms-admin-panel').length,1);
   assert.equal(q.d.querySelectorAll('.scan-stage-picker').length,0,'No redundant collapsed stages');
  }
  await q.w.loadDetail(4);await tick();
  assert.equal(q.w.receptionHasUnsavedFields(),false,'Navigation does not create unsaved business fields');
  const stage=q.d.querySelector('.mobile-stage-select select'),oldStage=stage.value;
  const field=q.d.querySelector('#content input:not([disabled]):not([readonly]):not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=number])');
  if(field){const saved=field.value;field.value='QA unsaved';assert.equal(q.w.receptionHasUnsavedFields(),true,'Changed field is a real edit');q.w.confirm=()=>false;stage.value=oldStage==='0'?'1':'0';stage.dispatchEvent(new q.w.Event('change',{bubbles:true}));await tick();assert.equal(stage.value,oldStage,'Rejected stage change stays on the current stage');field.value=saved;q.w.confirm=()=>true;}
  const beforeState=await (await fetch(base+'/api/receptions/4',{headers:{'X-User':'demo.admin','X-Role':'ADMINISTRADOR'}})).json();
  assert.equal(beforeState.app_status,'EM','Run this test with a fresh fixture');
  q.d.querySelector('#rewindStatus').value='REVISION SISTEMA';
  await q.w.rewindStage();await tick();
  const latest=await (await fetch(base+'/api/receptions/4',{headers:{'X-User':'demo.admin','X-Role':'ADMINISTRADOR'}})).json();
  assert.equal(latest.app_status,'REVISION SISTEMA','Admin state correction remains functional');
  const forbidden=await fetch(base+'/api/receptions/4/rewind',{method:'POST',headers:{'Content-Type':'application/json','X-User':'qa.receiver','X-Role':'ASISTENTE_RECEPCION'},body:JSON.stringify({status:'ARRIBADO',reason:'Intento sin permiso'})});
  assert.equal(forbidden.status,403,'Workers cannot perform admin state corrections');
  for(const action of ['showUsers','showWorkload','showNotifications','showNotices']){await q.w[action]();await tick();assert.ok(q.d.querySelector('#content').textContent.trim());freeze('reception-'+action.toLowerCase(),q.w)}
  await q.w.showAccount();assert.ok(q.d.querySelector('.profile-fields'));q.w.showMore();assert.ok(q.d.querySelector('#adminTools'));
  freeze('reception-tools',q.w);
  await q.w.openNewModal();assert.equal(q.d.querySelector('#newModal').hidden,false);q.w.closeNewModal();
  q.d.querySelector('#dailyDataButton').click();await until(()=>q.d.querySelector('#dailyDialog')?.open);
  freeze('reception-cuts',q.w);
  assert.deepEqual(q.errors,[]);console.log('OK Reception: all BL stages, admin rewind, worker guard, transfers, work, users/workload/notices/profile/dialogs');
 }finally{q.w.close()}
 q=await page('/');
 try{
  await until(()=>q.d.querySelector('#detail').textContent.includes('OV')&&q.w.loadDetail);
  await q.w.loadDetail('QA-OV-1');await tick();
  assert.ok(q.d.querySelector('.wms-admin-panel .admin-correction'),'Dispatch corrections stay prominent');
  freeze('dispatch-order',q.w);
  const tabs=q.d.querySelector('.mobile-stage-select select');assert.ok(tabs);
  for(let index=0;index<tabs.options.length;index++){tabs.value=String(index);tabs.dispatchEvent(new q.w.Event('change',{bubbles:true}));await tick();assert.ok(q.d.querySelector('.detail-tab.active'));freeze('dispatch-tab-'+index,q.w)}
  await q.w.showMyWork();await q.w.showPendingDeliveries();await q.w.showReport();await q.w.showUsers();await q.w.showAccount();
  assert.deepEqual(q.errors,[]);console.log('OK Dispatch: detail tabs, administrative actions, work, deliveries, reports, users, profile');
 }finally{q.w.close()}
 q=await page('/inventory');
 try{
  await until(()=>q.d.querySelector('#user').value);await q.w.loadInventory('QA-NP-0');await tick();
  assert.ok(q.d.querySelector('#inventoryRows tr.mobile-record'));assert.equal(q.d.querySelectorAll('.progress-card').length,0);
  freeze('inventory-stock',q.w);
  q.w.showRequestForm();const form=q.d.querySelector('#materialRequestForm');form.elements.item_code.value='QA-DIRTY';
  await tick();freeze('inventory-request-form',q.w);
  q.w.confirm=()=>false;q.w.switchInventoryTab('stock');assert.ok(q.d.querySelector('#requestsPanel').classList.contains('active'));assert.equal(form.elements.item_code.value,'QA-DIRTY');
  q.w.confirm=()=>true;q.w.switchInventoryTab('stock');assert.equal(form.elements.item_code.value,'');assert.ok(q.d.querySelector('#requestFormCard').classList.contains('hidden'));
  q.w.showRequestForm();Object.assign(form.elements.item_code,{value:'QA-NEW-'+Date.now()});form.elements.description.value='Nueva pieza de prueba';form.elements.justification.value='Necesidad de QA';
  const before=q.posts.length;await Promise.all([q.w.submitMaterialRequest({preventDefault(){},currentTarget:form}),q.w.submitMaterialRequest({preventDefault(){},currentTarget:form})]);
  assert.equal(q.posts.slice(before).filter(p=>p.url.endsWith('/api/inventory/requests')).length,1,'No duplicate submission');
  assert.equal(form.querySelector('[type=submit]').disabled,false);
  const note=q.d.querySelector('[id^=decision-note-]');note.value='Revisado en prueba';const id=Number(note.id.replace('decision-note-',''));
  await q.w.decideMaterialRequest(id,'APROBAR');assert.match(q.d.querySelector('#requestList').textContent,/APROBADA/);
  freeze('inventory-requests',q.w);
  assert.deepEqual(q.errors,[]);console.log('OK Inventory: catalog, request tabs/discard guard, single submission, administrator approval');
 }finally{q.w.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
