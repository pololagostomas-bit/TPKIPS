// Exercise the real navigation control without a server or operational data.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync(require('node:path').join(__dirname, '../frontend/static/truck-controls.js'), 'utf8');
function fixture(options = {}) {
  const calls = [], events = [], filter = {value:'QA-DRAFT'};
  const context = {
    activeTruckGuideSummary:{truck_guide:'QA-DRAFT',scanner_enabled:true,guide_status:'PENDIENTE',bls:options.bls || []},
    guideStatus:value=>value, guideBlRows:s=>s.bls || [], role:()=>options.role || 'ASISTENTE_RECEPCION',
    isAdmin:()=>false, receptionHasUnsavedFields:()=>false,
    document:{querySelectorAll:()=>[]}, $:id=>id==='truckGuideFilter' ? filter : null,
    confirm:()=>options.confirm !== false, notify:message=>events.push(message),
    renderTruckGuideWorkspace:()=>{}, openQueue:()=>{},
    showTruckGuideWorkspace:async()=>events.push('navigate'), loadTruckGuides:async()=>{},
    api:async(path, request)=>{
      calls.push({path,body:request.body});
      return {ok:!options.fail,json:async()=>options.fail ? {error:'QA unavailable'} : {cancelled:options.cancelled !== false}};
    },
    WmsTruckScan:{hasPending:()=>Boolean(options.rejected || options.inFlight),
      hasInFlight:()=>Boolean(options.inFlight), hasDrafts:()=>false,
      clearCancelledGuide:guide=>events.push('cleared:'+guide)}
  };
  context.window=context; vm.runInNewContext(source, context);
  return {context,calls,events,filter};
}
(async()=>{
  for (const options of [{},{rejected:true}]) {
    const f=fixture(options); await f.context.WmsTruckControls.leave();
    assert.equal(f.calls.length,1,'Leaving an empty preparation must request a guarded discard');
    assert.equal(f.calls[0].body.empty_only,true);
    assert.equal(f.filter.value,'ALL'); assert.ok(f.events.includes('cleared:QA-DRAFT'));
  }
  for (const options of [{confirm:false},{inFlight:true},{fail:true}]) {
    const f=fixture(options); await f.context.WmsTruckControls.leave();
    assert.equal(f.events.includes('navigate'),false,'Decline/in-flight/error keeps the preparation');
    assert.equal(f.events.includes('cleared:QA-DRAFT'),false);
    assert.equal(f.context.activeTruckGuideSummary.truck_guide,'QA-DRAFT');
  }
  for (const options of [{bls:[{id:1}]},{role:'AUXILIAR_RECEPCION'}]) {
    const f=fixture(options); await f.context.WmsTruckControls.leave();
    assert.equal(f.calls.length,0,'Saved BL work and auxiliary navigation never request cancellation');
    assert.ok(f.events.includes('navigate'));
  }
  const raced=fixture({cancelled:false}); await raced.context.WmsTruckControls.leave();
  assert.ok(raced.events.includes('navigate')); assert.equal(raced.events.includes('cleared:QA-DRAFT'),false);
  console.log('8 empty-preparation navigation scenarios OK');
})().catch(error=>{console.error(error);process.exitCode=1});
