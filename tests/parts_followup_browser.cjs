const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
const root=process.cwd();
const output=process.env.WMS_QA_OUTPUT||path.join(root,'qa/parts-followup');
const labels={RECEPCION:'Zona de recepción',ALMACEN:'Trabajo en almacén',COSTEO:'Costeo',DISPONIBLE:'Disponible'};
const dates={arrival_date:'2026-10-01',work_date:'2026-10-02',em_date:'2026-10-03',costing_date:'2026-10-04',available_date:'2026-10-04'};
const rows=Object.entries(labels).map(([state,state_label],i)=>({id:i+1,bl_awb:'QA-BL-'+(i+1),state,state_label,truck_guides:['QA-TRUCK'],...dates,costing_date:i===3?dates.costing_date:'',available_date:i===3?dates.available_date:'',delivery_count:1,costed_deliveries:i===3?1:0,deliveries:[{sequence:1,truck:'QA-TRUCK',arrival_date:dates.arrival_date,costing_date:i===3?dates.costing_date:'',stage:i===3?'CERRADO':'ARRIBADO',packages:2}],em_dates:[dates.em_date]}));
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{for(const width of [320,393,1366]){
  const page=await browser.newPage({viewport:{width,height:850}});const errors=[];page.on('pageerror',e=>errors.push(e.message));let fail=false;
  await page.route('**/*',async route=>{
   const url=new URL(route.request().url());
   if(url.pathname==='/parts-followup')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'frontend/templates/parts-followup.html'))});
   if(url.pathname==='/api/me')return route.fulfill({json:{username:'qa.reader',role:'CONSULTA_REPUESTOS',mode:'local'}});
   if(url.pathname==='/api/parts-followup'){
    if(fail)return route.fulfill({status:503,json:{error:'QA sin conexión'}});
    let items=rows.filter(row=>(url.searchParams.get('state')==='ALL'||!url.searchParams.get('state')||row.state===url.searchParams.get('state'))&&row.bl_awb.toLowerCase().includes((url.searchParams.get('search')||'').toLowerCase()));
    return route.fulfill({json:{items,total:items.length,limit:50,offset:0,has_more:false,generated_at:'2026-10-05T10:00:00',summary:Object.fromEntries(Object.keys(labels).map(k=>[k,items.filter(r=>r.state===k).length]))}});
   }
   if(url.pathname==='/assets/auth-client.js')return route.fulfill({contentType:'application/javascript',body:'window.installSessionControls=()=>{};'});
   if(url.pathname.startsWith('/assets/')){
    const file=path.join(root,'frontend/static',path.basename(url.pathname));
    if(fs.existsSync(file))return route.fulfill({contentType:file.endsWith('.css')?'text/css':'application/javascript',body:fs.readFileSync(file)});
   }
   return route.abort();
  });
  await page.goto('http://wms.example.test/parts-followup');
  await page.locator('#followupResults tbody tr').first().waitFor({timeout:4000});
  assert.equal(await page.locator('#followupResults tbody tr').count(),4);
  assert.equal(await page.locator('#backWms').isVisible(),false);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
  await page.locator('#followupState').selectOption('DISPONIBLE');
  await page.waitForFunction(()=>document.querySelectorAll('#followupResults tbody tr').length===1);
  assert.match(await page.locator('#followupResults').innerText(),/04\/10\/2026/);
  await page.locator('#followupSearch').fill('not-found');
  await page.locator('#followupResults').getByText('No hay BL con estos filtros.').waitFor();
  await page.locator('#followupSearch').fill('');await page.locator('#followupState').selectOption('ALL');
  await page.waitForFunction(()=>document.querySelectorAll('#followupResults tbody tr').length===4);
  await page.screenshot({path:path.join(output,'parts-'+width+'.png'),fullPage:true});
  fail=true;await page.locator('#refreshFollowup').click();await page.locator('#followupError').waitFor({state:'visible'});
  assert.equal(await page.locator('#followupResults tbody tr').count(),0);
  fail=false;await page.locator('#refreshFollowup').click();await page.locator('#followupResults tbody tr').first().waitFor();
  assert.deepEqual(errors,[]);await page.close();console.log('parts-followup '+width+'px OK');
 }}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
