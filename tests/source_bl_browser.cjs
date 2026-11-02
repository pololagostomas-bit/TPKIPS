const {chromium}=require('playwright'),assert=require('node:assert/strict');
const base=process.argv[2];if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Synthetic loopback fixture required');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 for(const width of [320,393,1366]){
  const context=await browser.newContext({viewport:{width,height:873},serviceWorkers:'block'}),page=await context.newPage();let data,target,posts=0;
  await page.route('**/api/receptions/2**',async route=>{
   const request=route.request(),url=new URL(request.url());
   if(request.method()==='GET'&&url.pathname==='/api/receptions/2'){
    data=await (await route.fetch()).json();data.app_status='REVISION SISTEMA';
    target=data.lines.find(l=>l.in_selected_attention!==false&&Number(l.attention_verified_qty??l.received_qty)>0);assert(target);
    target.source_bl_eligible=false;target.source_bl_state='NO_BL';target.source_bl_message='Pedido sin guía en el corte actual';
    data.source_bl_issues=[{id:target.id,np_code:target.np_code,state:'NO_BL'}];return route.fulfill({json:data});
   }
   if(request.method()==='POST'&&url.pathname==='/api/receptions/2/lines/'+target.id){
    const body=request.postDataJSON();assert.equal(body.source_bl_correction,true);assert.equal(body.confirmed,true);
    assert.equal(body.received_qty,0);assert.equal(body.previous_received_qty,Number(target.attention_verified_qty??target.received_qty));assert(body.reason.length>=8);
    posts++;target.attention_verified_qty=0;target.received_qty=0;return route.fulfill({json:data});
   }
   return route.continue();
  });
  await page.goto(base+'/reception');await page.waitForLoadState('networkidle');await page.evaluate(()=>loadDetail(2));
  try{await page.getByText('Hay NP sin asociación vigente a esta BL.',{exact:true}).waitFor({timeout:5000});}catch(e){console.log(await page.evaluate(()=>({html:document.querySelector('#content')?.innerText.slice(0,1200),role:document.querySelector('#role')?.value,fn:typeof sourceAssociationCard,issues:selected?.lines?.filter(l=>l.source_bl_eligible===false).map(l=>({id:l.id,att:l.in_selected_attention}))})));throw e;}
  assert.equal(await page.evaluate(id=>WmsNpScan.countLines(selected).some(l=>l.id===id),target.id),false);
  assert.equal(await page.evaluate(id=>WmsReceptionLabels.items({...selected,lines:selected.lines.filter(l=>l.id===id)}).length,target.id),0);
  page.on('dialog',dialog=>dialog.accept(dialog.type()==='prompt'?'QA confirmed wrong source BL association':undefined));
  await page.getByRole('button',{name:'Retirar cantidad de esta entrega',exact:true}).click();
  await page.waitForFunction(id=>selected.lines.find(l=>l.id===id).attention_verified_qty===0,target.id);
  assert.equal(posts,1);
  await page.evaluate(()=>{$('role').value='ASISTENTE_RECEPCION';renderDetail();});
  assert.equal(await page.getByRole('button',{name:'Retirar cantidad de esta entrega',exact:true}).count(),0);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
  await context.close();console.log('source BL UI '+width+'px OK');
 }
}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1});
