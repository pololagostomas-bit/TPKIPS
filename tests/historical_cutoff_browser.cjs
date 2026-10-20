// Disposable support_independent_arrivals_server.py only.
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const base=process.argv[2];if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Loopback fixture required');
(async()=>{const browser=await chromium.launch({headless:true,channel:'msedge'});try{
 for(const viewport of [{width:320,height:740},{width:393,height:873},{width:1366,height:900}]){
  const page=await browser.newPage({viewport}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/reception');await page.waitForFunction(()=>window.showHistoricalCutoff);
  const id=await page.evaluate(async width=>{const r=await api('/api/receptions',{method:'POST',body:{bl_awb:'QA-CUTOFF-'+width,transport_type:'MARITIMO',scheduled_date:'2026-07-31'}});const d=await r.json();if(!r.ok)throw Error(d.error);return d.id;},viewport.width);
  await page.evaluate(()=>showMore());await page.getByRole('button',{name:/Cierre historico/}).click();
  let posts=0;page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/historical-cutoff'))posts++;});
  await page.locator('#historicalCutoffPreview').click();await page.locator('#historicalCutoffForm').waitFor();
  assert.equal(posts,0,'Preview cannot close a BL');
  assert(await page.getByText('QA-CUTOFF-'+viewport.width,{exact:true}).isVisible());
  await page.locator('#historicalCutoffReason').fill('Owner directed historical assumption verified QA');await page.locator('#historicalCutoffConfirm').check();
  await page.locator('#historicalCutoffApply').click();await page.waitForFunction(()=>document.querySelector('#historicalCutoffStatus')?.textContent.includes('BL cerradas como historicas'));
  assert.equal(posts,1);
  const result=await page.evaluate(async id=>{const d=await(await api('/api/receptions/'+id)).json();return {status:d.app_status,condition:d.condition_status,qty:d.received_packages};},id);
  assert.deepEqual(result,{status:'CERRADO',condition:'HISTORICO POR CORTE',qty:0});
  const denied=await page.evaluate(async()=>{const r=await fetch('/api/receptions/historical-cutoff',{headers:{'X-User':'demo.recepcion','X-Role':'ASISTENTE_RECEPCION'}});return r.status;});assert.equal(denied,403);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);assert.deepEqual(errors,[]);
  console.log('OK cutoff preview/confirmed assumption/no fake receipt/admin-only '+viewport.width);await page.close();
 }
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
