import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node required')
class ReceptionScanUiTests(unittest.TestCase):
    def run_js(self, scenario):
        setup = r'''
const assert = require('assert/strict');
global.window = {addEventListener(){}};
const nodes = {};
function node(id) { return nodes[id] ||= {value:'',dataset:{},innerHTML:'',textContent:'',disabled:false,parentElement:{after(){},append(){},querySelector(){return null}},append(){},focus(){},select(){this.selected=true},setAttribute(){},addEventListener(){},after(){},querySelectorAll(){return []}}; }
global.$ = node;
global.document = {querySelector:()=>null,querySelectorAll:()=>[],createElement:()=>node('created-section')};
global.guideBlRows = s=>s.bls||[];
global.guideStatus = s=>s;
global.esc = s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
global.truckRowId = row=>row.id;
global.renderTruckLocationInputs = ()=>'<input class="truck-bl-location">';
global.notify = ()=>{};
global.api = async()=>({ok:true,json:async()=>({applicable:false,enabled:false})});
global.scannerSelectedShipmentId = null;
global.activeTruckGuideSummary = {truck_guide:'SCAN-A',guide_status:'PENDIENTE',bls:[{id:1,bl_awb:'BL-A',package_scan_count:0},{id:2,bl_awb:'BL-B',package_scan_count:0}]};
node('truckGuideFilter').value='SCAN-A';
node('scanTruckWorkspace').dataset.guide='SCAN-A';
require('./frontend/static/reception-scan.js');
const scan=window.WmsTruckScan;
scan.render(activeTruckGuideSummary);
'''
        result = subprocess.run(['node', '-e', setup + '\n(async()=>{' + scenario + '\n})().catch(e=>{console.error(e);process.exit(1)})'], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_context_is_explicit_and_reset_when_changing_guide(self):
        self.run_js('''
assert.ok(node('content').innerHTML.includes('id="scanTruckPackageCode"'));
assert.ok(node('content').innerHTML.includes('id="scanTruckBlCode"'));
assert.equal(node('scanBlEntry').hidden,true);
scan.changeBl(1);
assert.equal(scannerSelectedShipmentId,1);
assert.ok(node('content').innerHTML.includes('BL seleccionada'));
scan.changeBl();
assert.equal(scannerSelectedShipmentId,null);
scan.changeBl(1);
scan.render({...activeTruckGuideSummary,truck_guide:'SCAN-B'});
assert.equal(scannerSelectedShipmentId,null);
''')

    def test_progress_uses_expected_totals_prior_receipts_and_multiple_brands(self):
        self.run_js('''
Object.assign(activeTruckGuideSummary.bls[0],{package_scan_count:8,brands:['BOBCAT','LIEBHERR'],package_progress:{expected:10,source:'DHL',previously_received:0}});
scan.changeBl(1);
assert.equal(node('scanBlCount').textContent,'8/10');
assert.equal(node('scanBlBrands').textContent,'BOBCAT / LIEBHERR');
assert.equal(node('scanBlProgressLabel').textContent,'Faltan 2 · DHL');
assert.equal(node('scanTotalExpected').textContent,'/—','Unknown BL total must not masquerade as complete');
Object.assign(activeTruckGuideSummary.bls[1],{package_scan_count:0,package_progress:{expected:3,source:'WMS',previously_received:0}});
scan.update();assert.equal(node('scanTotalExpected').textContent,'/13');
activeTruckGuideSummary.bls[0].package_progress.previously_received=2;
scan.update();assert.equal(node('scanBlCount').textContent,'10/10');
assert.equal(node('scanBlPrevious').textContent,'2 previos · 8 en este camión');
assert.equal(node('scanBlProgressLabel').textContent,'Completa · DHL');
assert.equal(node('scanTotalExpected').textContent,'/11');
activeTruckGuideSummary.bls[0].package_scan_count=9;
scan.update();assert.equal(node('scanBlCount').textContent,'11/10');
assert.equal(node('scanBlProgressLabel').textContent,'Exceso: 1 · DHL');
assert.ok(node('scanBlList').innerHTML.includes('BOBCAT / LIEBHERR'));
''')

    def test_bl_mode_requires_explicit_lookup_and_preserves_both_mode_drafts(self):
        self.run_js('''
node('scanTruckPackageCode').value='DHL-DRAFT';
scan.setMode('bl');
assert.equal(node('scanBlEntry').hidden,false);
assert.equal(node('scanTruckPackageCode').disabled,true);
const calls=[];
global.api=async(url,options)=>{
 calls.push([url,options?.body]);
 if(url.endsWith('/scan-bl'))return {ok:true,json:async()=>({shipment_id:1,bl_awb:'BL-A'})};
 if(url.includes('/truck-guide?'))return {ok:true,json:async()=>activeTruckGuideSummary};
 if(url.endsWith('/scan-package'))return {ok:true,json:async()=>({count:1,dhl_verification:'unverified'})};
 return {ok:true,json:async()=>({applicable:false,enabled:false})};
};
node('scanTruckPackageCode').value='SEA-DRAFT';await scan.scanPackage();
assert.equal(calls.length,0,'A visual review is not a receiving selection');
scan.changeBl(2);await scan.scanPackage();assert.equal(calls.filter(([,body])=>body).length,0);
node('scanTruckBlCode').value='BL-A';await scan.scanBl();
assert.equal(node('scanReceivingBl').textContent,'BL-A');
assert.equal(node('scanTruckPackageCode').value,'SEA-DRAFT');
assert.equal(node('scanTruckPackageCode').disabled,false);
scan.changeBl(2);
await scan.scanPackage();
const saved=calls.find(([url])=>url.endsWith('/scan-package'))[1];
assert.equal(saved.shipment_id,1,'Reviewing another BL never changes the receiving context');
assert.equal(saved.package_code,'SEA-DRAFT');
assert.ok(!node('scanFeedback').textContent.includes('Sin verificar por DHL'));
node('scanTruckPackageCode').value='SEA-NEXT';scan.setMode('piece');
assert.equal(node('scanTruckPackageCode').value,'DHL-DRAFT');
scan.setMode('bl');assert.equal(node('scanTruckPackageCode').value,'SEA-NEXT');
scan.render({...activeTruckGuideSummary,truck_guide:'SCAN-B'});
assert.equal(node('scanBlEntry').hidden,true);
scan.setMode('bl');assert.equal(node('scanReceivingBl').textContent,'Sin BL elegida');
''')

    def test_bl_mode_queue_and_retry_keep_original_target_and_mode(self):
        self.run_js('''
scan.setMode('bl');
let release, fail=true;
const retryButton={dataset:{retryReading:'1'}};
node('scanFailures').querySelectorAll=selector=>selector==='[data-retry-reading]'?[retryButton]:[];
const gate=new Promise(resolve=>release=resolve),calls=[];
global.api=async(url,options)=>{
 if(url.endsWith('/scan-bl'))return {ok:true,json:async()=>({shipment_id:1,bl_awb:'BL-A'})};
 if(url.includes('/truck-guide?'))return {ok:true,json:async()=>activeTruckGuideSummary};
 if(!url.endsWith('/scan-package'))return {ok:true,json:async()=>({applicable:false,enabled:false})};
 calls.push(options.body);if(calls.length===1)await gate;
 return fail?{ok:false,json:async()=>({error:'QA temporary failure'})}:{ok:true,json:async()=>({count:calls.length})};
};
node('scanTruckBlCode').value='BL-A';await scan.scanBl();
node('scanTruckPackageCode').value='SEA-1';const first=scan.scanPackage();
node('scanTruckPackageCode').value='SEA-2';await scan.scanPackage();
scan.setMode('piece');assert.equal(node('scanBlEntry').hidden,false);
scan.changeBl(2);assert.equal(scannerSelectedShipmentId,1);
release();await first;assert.equal(node('scanTotal').textContent,'0');
scan.setMode('piece');fail=false;await retryButton.onclick();
assert.equal(calls[2].shipment_id,1);
assert.equal(calls[2].package_code,'SEA-1');
''')

    def test_unsent_hidden_mode_code_blocks_finalize_until_explicit_discard(self):
        self.run_js('''
node('scanTruckPackageCode').value='DHL-DRAFT';scan.setMode('bl');
assert.equal(scan.hasDrafts(),true);
let sent=0;global.api=async()=>{sent++;return {ok:true,json:async()=>({})}};
await scan.finalize();assert.equal(sent,0);
assert.ok(node('scanFeedback').textContent.includes('codigos sin registrar'));
scan.discardDrafts();assert.equal(scan.hasDrafts(),false);
scan.setMode('piece');assert.equal(node('scanTruckPackageCode').value,'');
''')

    def test_reviewing_bl_keeps_unsaved_code_and_does_not_assign_next_scan(self):
        self.run_js('''
node('scanTruckPackageCode').value='PENDING-READING';
const original=node('content').innerHTML;
scan.changeBl(1);
assert.equal(node('scanTruckPackageCode').value,'PENDING-READING');
assert.equal(node('content').innerHTML,original);
assert.ok(node('scanBlList').innerHTML.includes('data-scan-context="1"'));
assert.ok(node('scanBlList').innerHTML.includes('aria-pressed="true"'));
let body;
global.api=async(url,options)=>{if(!url.endsWith('/scan-piece'))return {ok:true,json:async()=>({applicable:false,enabled:false})};body=options.body;return {ok:true,json:async()=>({count:1,shipment_id:2,bl_awb:'BL-B'})}};
await scan.scanPackage();
assert.equal(body.shipment_id,undefined);
assert.equal(body.bl_code,undefined);
assert.equal(scannerSelectedShipmentId,2);
assert.equal(activeTruckGuideSummary.bls[0].package_scan_count,0);
assert.equal(activeTruckGuideSummary.bls[1].package_scan_count,1);
''')

    def test_fast_reads_are_serialized_and_cannot_change_bl_mid_save(self):
        self.run_js('''
scan.changeBl(1);
let release;
const gate=new Promise(resolve=>release=resolve), calls=[];
global.api=async (url,options)=>{if(!url.endsWith('/scan-piece'))return {ok:true,json:async()=>({applicable:false,enabled:false})};calls.push(options.body);if(calls.length===1)await gate;return {ok:true,json:async()=>({count:calls.length,shipment_id:1,bl_awb:'BL-A'})}};
node('scanTruckPackageCode').value='PACKAGE-1';
const first=scan.scanPackage();
node('scanTruckPackageCode').value='PACKAGE-2';
await scan.scanPackage();
scan.changeBl(2);
assert.equal(scannerSelectedShipmentId,1);
assert.equal(calls.length,1);
release(); await first;
assert.deepEqual(calls.map(c=>[c.shipment_id,c.package_code]),[[undefined,'PACKAGE-1'],[undefined,'PACKAGE-2']]);
assert.equal(activeTruckGuideSummary.bls[0].package_scan_count,2);
assert.equal(node('scanTotal').textContent,'2');
assert.equal(node('finalizeScanTruckButton').disabled,false);
scan.changeBl(2);assert.equal(scannerSelectedShipmentId,2);
''')

    def test_error_keeps_code_and_does_not_increment_count(self):
        self.run_js('''
scan.changeBl(2);
global.api=async()=>({ok:false,json:async()=>({error:'Ya pertenece a BL-A / SCAN-A'})});
node('scanTruckPackageCode').value='DUPLICATE';
await scan.scanPackage();
assert.equal(node('scanTruckPackageCode').value,'DUPLICATE');
assert.equal(node('scanFeedback').dataset.kind,'error');
assert.ok(node('scanFeedback').textContent.includes('BL-A'));
assert.equal(activeTruckGuideSummary.bls[1].package_scan_count,0);
''')

    def test_duplicate_is_not_added_and_details_are_collapsed(self):
        self.run_js('''
scan.changeBl(1);
global.api=async()=>({ok:true,json:async()=>({duplicate:true,count:1,shipment_id:1,bl_awb:'BL-A'})});
node('scanTruckPackageCode').value='SAME';
await scan.scanPackage();
assert.equal(node('scanTotal').textContent,'1');
assert.equal(node('scanFeedback').dataset.kind,'warning');
assert.ok(node('content').innerHTML.includes('<details class="scan-details">'));
assert.ok(!node('content').innerHTML.includes('<table'));
''')

    def test_unknown_dhl_label_is_saved_with_visible_warning(self):
        self.run_js('''
scan.changeBl(1);
global.api=async()=>({ok:true,json:async()=>({count:1,dhl_verification:'unverified',shipment_id:1,bl_awb:'BL-A',identification:'manual'})});
node('scanTruckPackageCode').value='UNKNOWN';
await scan.scanPackage();
assert.equal(node('scanTotal').textContent,'1');
assert.equal(node('scanFeedback').dataset.kind,'warning');
assert.ok(node('scanFeedback').textContent.includes('Sin verificar por DHL'));
assert.equal(node('finalizeScanTruckButton').disabled,false);
''')

    def test_mixed_bls_do_not_inherit_selected_context(self):
        self.run_js('''
let index=0;
global.api=async(url,options)=>{if(!url.endsWith('/scan-piece'))return {ok:true,json:async()=>({applicable:false,enabled:false})};index++;assert.equal(options.body.shipment_id,undefined);return {ok:true,json:async()=>({count:1,shipment_id:index,bl_awb:index===1?'BL-A':'BL-B'})}};
for(const code of ['BOX-A','BOX-B']){node('scanTruckPackageCode').value=code;await scan.scanPackage();}
assert.equal(node('scanTotal').textContent,'2');
assert.equal(node('scanLastBl').textContent,'BL-B');
''')

    def test_unknown_confirmation_is_explicit_and_applies_only_to_one_reading(self):
        self.run_js('''
const calls=[];
global.api=async(url,options)=>{if(!url.endsWith('/scan-piece'))return {ok:true,json:async()=>({applicable:false,enabled:false})};calls.push(options.body);return options.body.bl_code?{ok:true,json:async()=>({count:1,shipment_id:2,bl_awb:'BL-B',identification:'manual'})}:{ok:false,json:async()=>({error:'Identifica BL',can_identify:true})}};
node('scanTruckPackageCode').value='UNKNOWN';await scan.scanPackage();
assert.equal(node('scanTotal').textContent,'0');
assert.equal(node('finalizeScanTruckButton').disabled,true);
scan.identify(1);node('scanIdentifyBl').value='BL-B';await scan.confirmIdentification();
assert.equal(calls[1].confirm_unverified,true);
assert.equal(calls[1].package_code,'UNKNOWN');
assert.equal(node('scanTotal').textContent,'1');
assert.equal(node('scanIdentifyPanel').hidden,true);
assert.equal(node('finalizeScanTruckButton').disabled,false);
node('scanTruckPackageCode').value='NEXT-BOX';await scan.scanPackage();
assert.equal(calls[2].bl_code,undefined);
assert.equal(calls[2].shipment_id,undefined);
''')

    def test_location_step_recovers_common_location_and_ignores_unreceived_or_closed(self):
        self.run_js('''
activeTruckGuideSummary={truck_guide:'SCAN-A',guide_status:'ZONA_RECEPCION',bls:[
 {id:1,bl_awb:'BL-A',received_this_truck:2,locations:[{location_text:'GENERAL',package_count:2}]},
 {id:2,bl_awb:'BL-B',received_this_truck:3,locations:[{location_text:'GENERAL',package_count:3}]},
 {id:3,bl_awb:'BL-ZERO',received_this_truck:0},
 {id:4,bl_awb:'BL-CLOSED',received_this_truck:1,app_status:'CERRADO'}]};
scan.render(activeTruckGuideSummary);
const html=node('content').innerHTML;
assert.ok(html.includes('id="scanGeneralLocation" value="GENERAL"'));
assert.equal((html.match(/data-own-location /g)||[]).length,2);
assert.equal((html.match(/data-own-location checked/g)||[]).length,0);
assert.ok(!html.includes('BL-ZERO'));
assert.ok(!html.includes('BL-CLOSED'));
assert.ok(html.includes('WmsTruckScan.saveLocations()'));
''')

    def test_location_step_preserves_saved_split_as_exception_and_shows_completed_summary(self):
        self.run_js('''
activeTruckGuideSummary={truck_guide:'SCAN-A',guide_status:'ZONA_RECEPCION',bls:[
 {id:1,bl_awb:'BL-A',received_this_truck:2,locations:[{location_text:'GENERAL',package_count:2}]},
 {id:2,bl_awb:'BL-B',received_this_truck:3,locations:[{location_text:'OTHER',package_count:1},{location_text:'SECOND',package_count:2}]}]};
scan.render(activeTruckGuideSummary);
assert.ok(node('content').innerHTML.includes('id="scanGeneralLocation" value=""'));
assert.equal((node('content').innerHTML.match(/data-own-location checked/g)||[]).length,2);
activeTruckGuideSummary.guide_status='LISTA_PARA_CONTEO';scan.render(activeTruckGuideSummary);
assert.ok(node('content').innerHTML.includes('scan-location-summary'));
assert.ok(node('content').innerHTML.includes('SECOND'));
assert.ok(!node('content').innerHTML.includes('scanGeneralLocation'));
''')
