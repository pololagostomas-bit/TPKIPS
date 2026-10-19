"""Queue/camera contract and manual draft isolation using synthetic JS nodes."""
import unittest

import test_reception_scan_ui as scan_harness


class ManualPackageUiTests(unittest.TestCase):
    run_js = scan_harness.ReceptionScanUiTests.run_js

    def test_worker_sees_counts_but_not_expected_codes_or_cache_selection(self):
        self.run_js('''
global.isAdmin=()=>false;
const created=[];
document.createElement=()=>{const item=node('created-'+created.length);created.push(item);return item};
scan.render(activeTruckGuideSummary);
const form=created.find(item=>item.id==='scanManualEntry');
assert.ok(form.innerHTML.includes('scanManualKnownCode'));
assert.ok(!form.innerHTML.includes('scanManualSearch'));
assert.ok(!form.innerHTML.includes('scanManualPieces'));
const calls=[];
global.api=async(url)=>{calls.push(url);return {ok:true,json:async()=>({enabled:true,applicable:true,checked_at:1,
 total_pieces:3,matched_pieces:0,pending_pieces:3,can_view_piece_codes:true,pending_piece_ids:['SECRET-EXPECTED-CODE']})}};
scan.changeBl(1);await new Promise(resolve=>setImmediate(resolve));
assert.ok(node('scanDhlProgress').innerHTML.includes('Por escanear'));
assert.ok(!node('scanDhlProgress').innerHTML.includes('SECRET-EXPECTED-CODE'));
assert.ok(!node('scanDhlProgress').innerHTML.includes('Codigos por escanear'));
const before=calls.length;
await scan.loadManualPieces();
assert.equal(calls.length,before,'Worker cannot request expected-code list');
scan.setMode('bl');
global.api=async(url)=>({ok:true,json:async()=>url.endsWith('/scan-bl')?{shipment_id:1,bl_awb:'BL-A'}:activeTruckGuideSummary});
await scan.scanBl('BL-A');
scan.selectManualPiece('SECRET-EXPECTED-CODE','cache');
assert.notEqual(node('scanManualSelected').textContent,'SECRET-EXPECTED-CODE');
global.api=async()=>({ok:false,json:async()=>({error:'No coincide',can_identify:true})});
const failed=await scan.scanPackage('WRONG-CODE');
assert.equal(failed.status,'failed');
assert.equal(failed.canIdentify,false);
assert.ok(!node('scanFailures').innerHTML.includes('data-identify-reading'));
''')

    def test_admin_can_see_expected_codes_when_server_authorizes_them(self):
        self.run_js('''
global.api=async()=>({ok:true,json:async()=>({enabled:true,applicable:true,checked_at:1,total_pieces:3,
 matched_pieces:0,pending_pieces:3,can_view_piece_codes:true,pending_piece_ids:['JD-ADMIN-ONLY']})});
scan.changeBl(1);await new Promise(resolve=>setImmediate(resolve));
assert.ok(node('scanDhlProgress').innerHTML.includes('JD-ADMIN-ONLY'));
''')

    def test_camera_result_resolves_its_own_queued_save(self):
        self.run_js('''
let release;const gate=new Promise(resolve=>release=resolve),calls=[];
global.api=async(url,options)=>{
 if(!url.endsWith('/scan-piece'))return {ok:true,json:async()=>({applicable:false,enabled:false})};
 calls.push(options.body);const count=calls.length;if(count===1)await gate;
 return {ok:true,json:async()=>({count,shipment_id:count,bl_awb:'BL-'+count})};
};
const context=scan.getCameraState();
const first=scan.scanPackage('BOX-A',context),second=scan.scanPackage('BOX-B',context);
assert.equal(scan.getCameraState().pending,2);
release();const results=await Promise.all([first,second]);
assert.deepEqual(results.map(r=>[r.status,r.code,r.shipmentId]),[['saved','BOX-A',1],['saved','BOX-B',2]]);
assert.equal(scan.getCameraState().pending,0);
''')

    def test_camera_choices_duplicates_errors_and_stale_context(self):
        self.run_js('''
global.api=async()=>({ok:false,json:async()=>({error:'Identificar BL',can_identify:true})});
const context=scan.getCameraState();
const result=await scan.scanPackage('UNKNOWN',context);
assert.equal(result.status,'choice');assert.equal(result.canIdentify,true);
assert.equal(scan.getCameraState().failed,1);
scan.identify(1);assert.equal(scan.getCameraState().choice,'identify-bl');
scan.setMode('bl');
assert.equal((await scan.scanPackage('OTHER',context)).status,'stale');
assert.equal(scan.getCameraState().shipmentId,null);
''')

    def test_late_package_response_never_changes_new_truck_or_focus(self):
        self.run_js('''
let release;const gate=new Promise(resolve=>release=resolve);
global.api=async()=>{await gate;return {ok:true,json:async()=>({count:1,shipment_id:1,bl_awb:'BL-A'})}};
const reading=scan.scanPackage('BOX-A',scan.getCameraState());
node('truckGuideFilter').value='SCAN-B';node('scanTruckWorkspace').dataset.guide='SCAN-B';
activeTruckGuideSummary={truck_guide:'SCAN-B',guide_status:'PENDIENTE',bls:[{id:2,bl_awb:'BL-B',package_scan_count:0}]};
scan.render(activeTruckGuideSummary);
node('scanTruckPackageCode').focus=()=>{throw Error('Late focus')};
release();const result=await reading;
assert.equal(result.status,'stale');assert.equal(result.outcome,'saved');
assert.equal(scannerSelectedShipmentId,null);assert.equal(node('scanTotal').textContent,'0');
''')

    def test_manual_confirmation_and_drafts_keep_original_bl(self):
        self.run_js('''
let selected=1,fail=true;const calls=[];
global.api=async(url,options)=>{
 if(url.endsWith('/scan-bl'))return {ok:true,json:async()=>({shipment_id:selected,bl_awb:selected===1?'BL-A':'BL-B'})};
 if(url.includes('/truck-guide?'))return {ok:true,json:async()=>activeTruckGuideSummary};
 if(url.endsWith('/manual-package')){calls.push(options.body);return fail?{ok:false,json:async()=>({error:'QA uncertain result'})}:{ok:true,json:async()=>({count:1})};}
 return {ok:true,json:async()=>({applicable:false,enabled:false})};
};
scan.setMode('bl');await scan.scanBl('BL-A');
node('scanManualKnownCode').value='SEA-KNOWN-A';scan.selectManualPiece('SEA-KNOWN-A','known_code');
assert.equal((await scan.confirmManualPiece()).status,'blocked');assert.equal(calls.length,0);
node('scanManualReason').value='Documento de prueba verificado';
assert.equal((await scan.confirmManualPiece()).status,'choice');
node('scanManualConfirmed').checked=true;
assert.equal((await scan.confirmManualPiece()).status,'failed');
assert.equal(scan.hasDrafts(),true);assert.equal(node('scanManualKnownCode').value,'SEA-KNOWN-A');
selected=2;await scan.scanBl('BL-B');
assert.equal(node('scanManualKnownCode').value,'');
node('scanManualKnownCode').value='SEA-KNOWN-B';scan.selectManualPiece('SEA-KNOWN-B','known_code');
selected=1;await scan.scanBl('BL-A');
assert.equal(node('scanManualSelected').textContent,'SEA-KNOWN-A');
assert.equal(node('scanManualReason').value,'Documento de prueba verificado');
fail=false;await scan.confirmManualPiece();
assert.deepEqual(calls.map(c=>[c.truck_guide,c.shipment_id,c.package_code,c.source,c.confirmed]),
 [['SCAN-A',1,'SEA-KNOWN-A','known_code',true],['SCAN-A',1,'SEA-KNOWN-A','known_code',true]]);
assert.equal(node('scanManualSelection').hidden,true);
assert.equal(scan.hasDrafts(),true,'Other BL manual draft survives successful save');
''')

    def test_old_manual_list_cannot_replace_current_bl(self):
        self.run_js('''
let sid=1,release;const gate=new Promise(resolve=>release=resolve);
global.api=async(url)=>{
 if(url.endsWith('/scan-bl'))return {ok:true,json:async()=>({shipment_id:sid,bl_awb:'BL-'+sid})};
 if(url.includes('/truck-guide?'))return {ok:true,json:async()=>activeTruckGuideSummary};
 if(url.includes('/manual-pieces?')){await gate;return {ok:true,json:async()=>({truck_guide:'SCAN-A',shipment_id:1,items:[{code:'OLD'}]})};}
 return {ok:true,json:async()=>({applicable:false,enabled:false})};
};
scan.setMode('bl');await scan.scanBl('BL-A');
const listing=scan.loadManualPieces();sid=2;await scan.scanBl('BL-B');
release();await listing;
assert.equal(node('scanManualPieces').innerHTML,'');
assert.equal(scan.getCameraState().shipmentId,2);
''')


if __name__ == '__main__':
    unittest.main()
