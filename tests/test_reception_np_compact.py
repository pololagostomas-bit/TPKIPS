"""Compact count surface keeps the existing guarded registration path."""
import unittest
from tests import test_reception_np_scan_ui as scan_ui


class CompactNpTests(unittest.TestCase):
    run_js = scan_ui.ReceptionNpScanUiTests.run_js

    def test_stock_order_names_are_consistent_without_changing_source(self):
        self.run_js(r"""
for(const value of ['',null,'S/N','sn',' S / N ','Sin OV','Stock'])assert.equal(w.ovLabel(value),'Stock');
assert.equal(w.ovLabel(' OV-SN-1 '),'OV-SN-1');
first.ov_number='S/N';mount();
assert(w.listControl(first).includes('OV Stock'));
assert.equal(first.ov_number,'S/N');
shipment.lines.push({...first,id:12,ov_number:'OV-2'});mount();
await automatic();const choices=nodes.get('receptionNpScanResult').innerHTML;
assert(choices.includes('<strong>Stock</strong>'));assert(choices.includes('OV-2'));
assert(!choices.includes('S/N'));assert(!choices.includes('Sin OV'));
""")

    def test_list_does_not_repeat_the_visible_order_beside_the_np(self):
        self.run_js(r"""
const html=w.listControl(first,true);
assert(!html.includes('class="np-order-reference"'));
assert(html.includes('aria-label="Registrar NP AB 01, OV OV-1"'));
""")

    def test_one_list_and_camera_inside_input_with_separate_finish_area(self):
        self.run_js(r"""
const html=mount();
assert(!html.includes('Elegir NP de la lista'));
assert(!html.includes('receptionNpFallbackSearch'));
assert(html.includes('class="np-input-camera"'));
assert(html.includes('data-camera-for="scanReceptionNp"'));
assert(html.includes('aria-label="Escanear NP con camara"'));
assert(html.includes('id="receptionNpList"'));
assert(html.includes('class="np-count-finish"'));
assert(/id="receptionNpFinish" hidden/.test(html));
first.np_scanned_at='saved';first.attention_verified_qty=9;
shipment.lines.push({...first,id:12,np_code:'NP-LATER',np_scanned_at:null});
assert(!/id="receptionNpFinish" hidden/.test(mount()));
""")

    def test_exact_row_selection_uses_same_queue_and_does_not_confirm_quantity(self):
        self.run_js(r"""
shipment.lines.push({...first,id:12,ov_number:'OV-2'}, {...first,id:13,in_selected_attention:false});
mount();confirmReads();const serial=w.status().context.viewId;
assert.equal(await w.selectFromList(13,serial),false);
await w.selectFromList(12,serial);
assert.equal(calls.length,1);assert(calls[0].url.endsWith('/lines/12'));
assert.equal(JSON.parse(calls[0].options.body).received_qty,9);
assert(!nodes.has('receptionNpQuantity'));
await w.selectFromList(12,serial);assert.equal(calls.length,1);
""")

    def test_unresolved_scan_or_stale_view_cannot_be_bypassed_with_list(self):
        self.run_js(r"""
mount();const serial=w.status().context.viewId;
await automatic('UNKNOWN');
assert.equal(await w.selectFromList(11,serial),false);assert.equal(calls.length,0);
await w.discard();confirmReads();
assert.equal(await w.selectFromList(11,serial+1),false);
editable=false;assert.equal(await w.selectFromList(11,serial),false);
assert.equal(calls.length,0);
""")
