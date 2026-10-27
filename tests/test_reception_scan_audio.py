"""Real NP flow contracts; success follows acceptance, never a decoded draft."""
from tests import test_reception_np_scan_ui as scan_ui


class ReceptionScanAudioTests(scan_ui.unittest.TestCase):
    run_js = scan_ui.ReceptionNpScanUiTests.run_js

    def test_np_success_waits_for_acceptance_then_duplicates_and_unknown_warn(self):
        self.run_js(r"""
let sounds=[],arms=0;window.WmsScanFeedback={arm(){arms++},success(){sounds.push('success')},error(){sounds.push('error')}};
mount();let finish;request=()=>new Promise(resolve=>{finish=resolve});
const saving=automatic();assert.equal(arms,1);assert.deepEqual(sounds,[]);
finish({ok:true,json:async()=>({id:5,attention_id:7,lines:[{...first,np_scanned_at:'now',attention_verified_qty:9}]})});
await saving;assert.deepEqual(sounds,['success']);
await automatic();assert.deepEqual(sounds,['success','error']);assert.equal(calls.length,1);
await automatic('UNKNOWN');assert.deepEqual(sounds,['success','error','error']);assert.equal(calls.length,1);
""")

    def test_failed_and_late_np_results_never_sound_success(self):
        self.run_js(r"""
let sounds=[];window.WmsScanFeedback={arm(){},success(){sounds.push('success')},error(){sounds.push('error')}};
mount();request=async()=>({ok:false,json:async()=>({error:'QA rejected'})});
await automatic();assert.deepEqual(sounds,['error']);
await w.discard();let finish;request=()=>new Promise(resolve=>{finish=resolve});
const saving=automatic();selectedId=6;
finish({ok:true,json:async()=>({id:5,attention_id:7,lines:[{...first,np_scanned_at:'now',attention_verified_qty:9}]})});
await saving;assert.deepEqual(sounds,['error']);
""")
