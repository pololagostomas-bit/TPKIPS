// Truck workflow against the same disposable fixture, with simulated typed codes.
const assert=require('node:assert/strict');
const {page,until,tick,freeze}=require('./mobile_workspace_dom.cjs');
(async()=>{
 const q=await page('/reception'),scanner=Boolean(q.w.WmsTruckScan);
 try{
  if(scanner){
   await q.w.createScannerTruckGuide();await tick();
   freeze('truck-choose-bl',q.w);
   q.d.querySelector('#scanTruckBlCode').value='QA-TRUCK-MOBILE';await q.w.scanTruckBl();
   q.d.querySelector('#scanTruckPackageCode').value='QA-PACKAGE-'+Date.now();await q.w.scanTruckPackage();
   await until(()=>q.d.querySelector('#scanTotal')?.textContent==='1'&&!q.w.WmsTruckScan.hasPending());
   freeze('truck-arrival',q.w);
   await q.w.WmsTruckControls.back();assert.ok(q.d.querySelector('#scanTruckBlCode'));
   assert.equal(q.d.querySelector('#scanTotal').textContent,'1','Returning to BL selection preserves scans');
   q.d.querySelector('#scanTruckBlCode').value='QA-TRUCK-MOBILE';await q.w.scanTruckBl();
   await q.w.finalizeScannedTruckArrival();
   assert.ok(q.d.querySelector('#saveTruckLocationsButton'),q.d.querySelector('#content').textContent);
  }else{
   const response=await q.w.api('/api/truck-guides',{method:'POST',body:{}}),guide=(await response.json()).truck_guide;
   assert.ok(guide);await q.w.openTruckGuideFromBl(guide);await tick();
   freeze('truck-choose-bl',q.w);
   q.d.querySelector('#truckDirectBlCode').value='QA-TRUCK-MOBILE';q.d.querySelector('#truckDirectSearch').click();
   await until(()=>q.d.querySelector('[data-select-bl]'));q.d.querySelector('[data-select-bl]').click();
   await until(()=>!q.d.querySelector('#truckDirectPackages').disabled);
   q.d.querySelector('#truckDirectPackages').value='1';q.d.querySelector('#truckDirectAdd').click();
   await until(()=>q.d.querySelector('#truckDirectFeedback')?.textContent.includes('BL agregada'));
   q.w.startTruckArrival();await tick();q.d.querySelector('.truck-bl-received').value='1';
   freeze('truck-arrival',q.w);await q.w.saveTruckArrival();
  }
  await until(()=>q.d.querySelector('#saveTruckLocationsButton'));await tick();
  freeze('truck-location',q.w);q.d.querySelector('.truck-bl-location').value='TEMP-QA';
  await q.w.saveTruckLocations();await tick();freeze('truck-completed',q.w);
  await q.w.WmsTruckControls.back();assert.ok(q.d.querySelector('#saveTruckLocationsButton'));
  assert.equal(q.d.querySelector('.truck-bl-location').value,'TEMP-QA','Reopened location is preserved');
  await q.w.WmsTruckControls.cancel();assert.equal(q.d.querySelector('#truckGuideFilter').value,'ALL');
  assert.deepEqual(q.errors,[]);console.log('OK '+(scanner?'scanner':'manual')+' truck: BL selection, arrival, location, complete, back, cancel');
 }finally{await tick();q.w.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
