"""Actual receipts, not cached future pieces, in the normal scanner view."""
import unittest

import test_reception_scan_ui as scan_harness


class ReceivedPieceUiTests(unittest.TestCase):
    run_js = scan_harness.ReceptionScanUiTests.run_js

    def test_admin_normal_view_lists_only_physical_reads(self):
        self.run_js('''
global.api=async()=>({ok:true,json:async()=>({enabled:true,applicable:true,checked_at:1,
 total_pieces:3,received_pieces:1,matched_pieces:1,pending_pieces:2,pending_arrival_pieces:2,
 piece_list_complete:true,can_view_piece_codes:true,received_piece_ids:['JD-RECEIVED'],
 pending_piece_ids:['JD-NOT-ARRIVED-A','JD-NOT-ARRIVED-B']})});
scan.changeBl(1);await new Promise(resolve=>setImmediate(resolve));
assert.ok(node('scanDhlProgress').innerHTML.includes('JD-RECEIVED'));
assert.ok(!node('scanDhlProgress').innerHTML.includes('JD-NOT-ARRIVED'));
assert.ok(node('scanDhlProgress').innerHTML.includes('Recibidos'));
assert.ok(node('scanDhlText').textContent.includes('total del envio'));
''')

    def test_worker_keeps_counts_without_any_expected_code_leak(self):
        self.run_js('''
global.isAdmin=()=>false;
global.api=async()=>({ok:true,json:async()=>({enabled:true,applicable:true,checked_at:1,
 total_pieces:3,received_pieces:1,matched_pieces:1,pending_pieces:2,pending_arrival_pieces:2,
 can_view_piece_codes:true,received_piece_ids:['JD-RECEIVED'],pending_piece_ids:['JD-SECRET']})});
scan.changeBl(1);await new Promise(resolve=>setImmediate(resolve));
assert.ok(node('scanDhlProgress').innerHTML.includes('Recibidos'));
assert.ok(node('scanDhlProgress').innerHTML.includes('Pendientes de arribo'));
assert.ok(!node('scanDhlProgress').innerHTML.includes('JD-'));
''')

    def test_partial_cache_does_not_turn_an_unknown_shipment_total_into_zero(self):
        self.run_js(r'''
global.api=async()=>({ok:true,json:async()=>({enabled:true,applicable:true,checked_at:1,
 total_pieces:null,received_pieces:1,pending_arrival_pieces:null,pending_pieces:0})});
scan.changeBl(1);await new Promise(resolve=>setImmediate(resolve));
assert.ok(/Pendientes de arribo: <strong>Sin informar<\/strong>/.test(node('scanDhlProgress').innerHTML));
''')

    def test_disabled_dhl_keeps_saved_physical_receipts_visible(self):
        self.run_js('''
global.api=async()=>({ok:true,json:async()=>({enabled:false,applicable:true,state:'disabled',
 total_pieces:null,received_pieces:1,pending_arrival_pieces:null,can_view_piece_codes:true,
 received_piece_ids:['JD-RECEIVED']})});
scan.changeBl(1);await new Promise(resolve=>setImmediate(resolve));
assert.equal(node('scanDhlStatus').hidden,false);
assert.equal(node('scanDhlProgress').hidden,false);
assert.ok(node('scanDhlProgress').innerHTML.includes('JD-RECEIVED'));
assert.ok(node('scanDhlText').textContent.includes('desactivado'));
''')


if __name__ == '__main__':
    unittest.main()
