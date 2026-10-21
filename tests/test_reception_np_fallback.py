"""Synthetic NP fallback and camera contract; no runtime or external services."""
from tests import test_reception_np_scan_ui as scan_ui
import unittest


class NpFallbackTests(unittest.TestCase):
    run_js = scan_ui.ReceptionNpScanUiTests.run_js

    def test_list_selects_exact_source_id_without_enter_or_quantity_confirmation(self):
        self.run_js(r"""
shipment.lines.push({...first,id:12,ov_number:'OV-2'},
 {...first,id:13,in_selected_attention:false},
 {...first,id:14,attention_id:8});
mount();confirmReads();
const html=w.listControl(first,true)+w.listControl(shipment.lines[1],true);
assert(html.includes('OV-1'));assert(html.includes('OV-2'));
assert(!html.includes('np-select-13'));assert(!html.includes('np-select-14'));
assert.equal(await w.selectFromList(13,w.status().context.viewId),false);
await w.selectFromList(12,w.status().context.viewId);
assert.equal(calls.length,1);assert(calls[0].url.endsWith('/lines/12'));
assert.equal(JSON.parse(calls[0].options.body).received_qty,9);
assert(!nodes.has('receptionNpQuantity'));
assert(nodes.get('receptionNpScanResult').innerHTML.includes('Seleccion de lista guardada'));
await w.selectFromList(12,w.status().context.viewId);assert.equal(calls.length,1);
""")

    def test_unknown_code_never_becomes_a_similar_list_item(self):
        self.run_js(r"""
mount();confirmReads();await automatic('ABO1');assert.equal(w.status().phase,'error');
assert.equal(await w.selectFromList(11,w.status().context.viewId),false);assert.equal(calls.length,0);
await w.discard();nodes.set('countNpFilter',{value:'ABO1'});
assert.equal(await w.selectFromList(11,w.status().context.viewId),false);
assert.equal(calls.length,0);nodes.get('countNpFilter').value='AB01';
await w.selectFromList(11,w.status().context.viewId);assert.equal(calls.length,1);
""")

    def test_same_np_always_requires_an_explicit_remaining_order(self):
        self.run_js(r"""
shipment.lines.push({...first,id:12,ov_number:'OV-2'});mount();confirmReads();
const ctx=w.status().context;
assert.equal((await w.receiveCamera('AB01',ctx)).phase,'choice');assert.equal(calls.length,0);
await w.choose(0);assert.equal(calls.length,1);
assert.equal((await w.receiveCamera('AB01',ctx)).phase,'choice');
assert.equal(calls.length,1);assert(nodes.get('receptionNpScanResult').innerHTML.includes('OV-2'));
assert.equal((await w.receiveCamera('AB01',ctx)).reason,'busy');
await w.choose(0);assert.equal(calls.length,2);
assert(w.canComplete());await w.receiveCamera('AB01',ctx);assert.equal(calls.length,2);
""")

    def test_camera_promise_status_and_captured_context(self):
        self.run_js(r"""
mount();let finish;request=()=>new Promise(resolve=>{finish=resolve});
const ctx=w.status().context;const saving=w.receiveCamera('AB01',ctx);
assert.equal(w.status().phase,'saving');assert.equal(w.status().canReceive,false);
assert.equal((await w.receiveCamera('AB01',ctx)).reason,'busy');assert.equal(calls.length,1);
finish({ok:true,json:async()=>({id:5,attention_id:7,lines:[{...first,np_scanned_at:'QA',attention_verified_qty:9}]})});
const result=await saving;assert.equal(result.accepted,true);assert.equal(result.phase,'ready');
assert.equal(result.lastResult.outcome,'saved');assert.equal(result.lastResult.lineId,'11');
shipment={...shipment,id:6};selectedId=6;mount();
assert.equal((await w.receiveCamera('AB01',ctx)).reason,'stale-context');assert.equal(calls.length,1);
""")

    def test_late_camera_response_retains_original_attention_for_explicit_retry(self):
        self.run_js(r"""
mount();let finish;request=()=>new Promise(resolve=>{finish=resolve});
const original=shipment;const ctx=w.status().context;
const saving=w.receiveCamera('AB01',ctx);
shipment={...shipment,id:6};selectedId=6;mount();
assert.equal(w.status().phase,'inactive');assert(w.hasPending());
finish({ok:true,json:async()=>({id:5,attention_id:7,lines:[{...first,np_scanned_at:'QA',attention_verified_qty:9}]})});
assert.equal((await saving).phase,'inactive');assert.equal(callbacks.length,0);
shipment=original;selectedId=5;const restored=mount();assert.equal(w.status().phase,'error');
assert(restored.includes('Reintentar lectura'));
confirmReads();await w.retry();assert.equal(w.status().phase,'ready');
assert.equal(calls.length,2);assert.equal(calls[0].url,calls[1].url);
assert.equal(calls[0].options.body,calls[1].options.body);
""")

    def test_camera_error_busy_empty_and_inactive_are_explicit(self):
        self.run_js(r"""
mount();const ctx=w.status().context;
assert.equal((await w.receiveCamera('',ctx)).reason,'empty-code');
request=async()=>({ok:false,json:async()=>{throw Error('QA not JSON')}});
const result=await w.receiveCamera('AB01',ctx);
assert.equal(result.accepted,true);assert.equal(result.phase,'error');assert.equal(result.lastResult,null);
assert.equal((await w.receiveCamera('AB01',ctx)).reason,'busy');assert.equal(calls.length,1);
editable=false;assert.equal(w.status().phase,'inactive');
assert.equal((await w.receiveCamera('AB01',ctx)).reason,'stale-context');assert.equal(calls.length,1);
""")

    def test_rerender_during_pending_save_keeps_queue_and_restores_controls(self):
        self.run_js(r"""
shipment.lines.push({...first,id:12,np_code:'OTHER'});mount();let finish;
request=()=>new Promise(resolve=>{finish=resolve});const saving=automatic();automatic('OTHER');
shipment={...shipment,lines:shipment.lines.map(line=>({...line}))};mount();
assert(w.hasPending());assert.equal(w.status().queueLength,2);confirmReads();
finish({ok:false,json:async()=>({error:'QA offline'})});await saving;
assert.equal(w.status().phase,'error');assert.equal(w.status().queueLength,2);
mount();assert.equal(w.status().queueLength,2);await w.retry();
assert.equal(calls.length,3);assert.equal(w.status().phase,'ready');
assert(!nodes.get('scanReceptionNp').disabled);assert(!nodes.get('receptionNpCamera').disabled);
assert.deepEqual(JSON.parse(calls[0].options.body),JSON.parse(calls[1].options.body));
""")

    def test_failed_list_retry_uses_original_line_url_and_body(self):
        self.run_js(r"""
mount();request=async()=>{throw Error('QA offline')};
await w.selectFromList(11,w.status().context.viewId);assert.equal(w.status().phase,'error');
nodes.get('qty-11').value='';nodes.get('reason-11').value='changed';
confirmReads();await w.retry();assert.equal(w.status().phase,'ready');
assert.equal(calls.length,2);assert.equal(calls[0].url,calls[1].url);
assert.equal(calls[0].options.body,calls[1].options.body);
""")

    def test_stale_choices_permissions_and_invalid_response_never_count(self):
        self.run_js(r"""
mount();const old=w.status().context;editable=false;
assert.equal(await w.selectFromList(11,old.viewId),false);assert.equal(calls.length,0);
editable=true;await automatic('UNKNOWN');await w.discard();await w.choose(0);
assert.equal(calls.length,0);confirmReads();
request=async()=>({ok:true,json:async()=>({id:5,attention_id:7,lines:[{...first,attention_id:8,np_scanned_at:'QA',attention_verified_qty:9}]})});
await automatic();assert.equal(w.status().phase,'error');assert(!w.canComplete());
assert.equal(nodes.get('receptionNpProgress').textContent,'NP leidos: 0/1 · Lecturas en cola: 1');
""")

    def test_post_save_callback_failure_does_not_attach_an_error_to_next_read(self):
        self.run_js(r"""
shipment.lines.push({...first,id:12,np_code:'OTHER'});mount();let finish;
request=()=>new Promise(resolve=>{finish=resolve});onSaved=()=>{throw Error('QA render failure')};
const saving=automatic();automatic('OTHER');confirmReads();
finish({ok:true,json:async()=>({id:5,attention_id:7,lines:[{...first,np_scanned_at:'QA',attention_verified_qty:9}]})});
await saving;assert.equal(calls.length,2);assert.equal(w.status().phase,'ready');assert(w.canComplete());
""")

    def test_shared_search_preserves_line_identity_without_dropping_draft_inputs(self):
        self.run_js(r"""
shipment.lines=Array.from({length:120},(_,i)=>({...first,id:100+i,np_code:'NP-'+i}));
mount();nodes.set('countNpFilter',{value:'NP-119'});
assert(nodes.has('qty-100'));assert(nodes.has('qty-219'));
assert.equal(await w.selectFromList(100,w.status().context.viewId),false);assert.equal(calls.length,0);
confirmReads();await w.selectFromList(219,w.status().context.viewId);
assert.equal(calls.length,1);assert(calls[0].url.endsWith('/219'));
""")


if __name__ == '__main__':
    unittest.main()
