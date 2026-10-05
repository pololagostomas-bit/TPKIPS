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
global.window = {};
const nodes = {};
function node(id) { return nodes[id] ||= {value:'',dataset:{},innerHTML:'',textContent:'',disabled:false,focus(){},select(){this.selected=true}}; }
global.$ = node;
global.document = {querySelectorAll:()=>[]};
global.guideBlRows = s=>s.bls||[];
global.guideStatus = s=>s;
global.esc = s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
global.truckRowId = row=>row.id;
global.renderTruckLocationInputs = ()=>'<input class="truck-bl-location">';
global.notify = ()=>{};
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
assert.ok(node('content').innerHTML.includes('Escanea una BL'));
assert.ok(!node('content').innerHTML.includes('id="scanTruckPackageCode"'));
scan.changeBl(1);
assert.equal(scannerSelectedShipmentId,1);
assert.ok(node('content').innerHTML.includes('Cambiar BL'));
scan.changeBl();
assert.equal(scannerSelectedShipmentId,null);
scan.changeBl(1);
scan.render({...activeTruckGuideSummary,truck_guide:'SCAN-B'});
assert.equal(scannerSelectedShipmentId,null);
''')

    def test_fast_reads_are_serialized_and_cannot_change_bl_mid_save(self):
        self.run_js('''
scan.changeBl(1);
let release;
const gate=new Promise(resolve=>release=resolve), calls=[];
global.api=async (url,options)=>{calls.push(options.body);if(calls.length===1)await gate;return {ok:true,json:async()=>({count:calls.length})}};
node('scanTruckPackageCode').value='PACKAGE-1';
const first=scan.scanPackage();
node('scanTruckPackageCode').value='PACKAGE-2';
await scan.scanPackage();
scan.changeBl(2);
assert.equal(scannerSelectedShipmentId,1);
assert.equal(calls.length,1);
release(); await first;
assert.deepEqual(calls.map(c=>[c.shipment_id,c.package_code]),[[1,'PACKAGE-1'],[1,'PACKAGE-2']]);
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
global.api=async()=>({ok:true,json:async()=>({duplicate:true,count:1})});
node('scanTruckPackageCode').value='SAME';
await scan.scanPackage();
assert.equal(node('scanTotal').textContent,'1');
assert.equal(node('scanFeedback').dataset.kind,'warning');
assert.ok(node('content').innerHTML.includes('<details class="scan-details">'));
assert.ok(!node('content').innerHTML.includes('<table'));
''')
