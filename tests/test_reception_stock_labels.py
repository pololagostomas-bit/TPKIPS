"""Stock wording is presentation only, not an order or quantity migration."""
import pathlib
import shutil
import subprocess
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "frontend/static/reception-labels.js"
HARNESS = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const window={location:{origin:'http://127.0.0.1:51988'},bwipjs:{toSVG:()=>'<svg viewBox="0 0 20 20"></svg>'}};
const document={querySelector:()=>null};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{window,document,countLocationValue:()=>''});
const labels=window.WmsReceptionLabels;
const first={id:1,np_code:'QA-NP',ov_number:'S/N',customer_name:'',received_qty:2};
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is required")
class StockLabelTests(unittest.TestCase):
    def run_js(self, script):
        result = subprocess.run([shutil.which("node"), "-e", HARNESS + script, str(MODULE)],
                                text=True, encoding="utf-8", capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_stock_wording_is_used_without_mutating_or_merging_source_orders(self):
        self.run_js(r"""
const shipment={lines:[first,{...first,id:2,ov_number:''}]};
const before=JSON.stringify(shipment),items=labels.items(shipment);
assert.equal(items.length,2);assert.equal(JSON.stringify(shipment),before);
for(const item of items){
 const raw=JSON.stringify(item),html=labels.documentHtml({bl_awb:'QA-BL'},[item]);
 assert(html.includes('<strong class="ov-value">Stock</strong>'));
 assert(html.includes('<span class="field-caption">Cliente</span><strong>Para stock</strong>'));
 assert.equal(JSON.stringify(item),raw);
}
""")

    def test_real_order_and_customer_remain_exact_and_escaped(self):
        self.run_js(r"""
const line={...first,ov_number:'OV-SN-7',customer_name:'Cliente <QA> & asociado'};
const html=labels.documentHtml({},labels.items({lines:[line]}));
assert(html.includes('<strong class="ov-value">OV-SN-7</strong>'));
assert(html.includes('Cliente &lt;QA&gt; &amp; asociado'));assert(!html.includes('Para stock'));
""")

    def test_quote_references_print_complete_source_value_without_changing_customer(self):
        self.run_js(r"""
for(const ov of ['COT 001234','cot-001234','COT001234','COTI 001234','COTIZACION','Cotizaci\u00f3n 001234','COT 001234 / 005678']){
 const line={...first,ov_number:ov,customer_name:'Cliente de cotizacion'};
 const before=JSON.stringify(line),html=labels.documentHtml({},labels.items({lines:[line]}));
 assert(html.includes('<strong class="ov-value">'+ov+'</strong>'),ov);
 assert(html.includes('<span class="field-caption">Cliente</span><strong>Cliente de cotizacion</strong>'));
 assert.equal(JSON.stringify(line),before);assert(!html.includes('Para stock'));
}
""")

    def test_pending_order_placeholder_is_not_printed_or_invented_as_stock_or_quote(self):
        self.run_js(r"""
for(const ov of ['POR REG','por reg.','POR REGULARIZAR','POR REGULARIZACION','POR REGULARIZACI\u00d3N']){
 const html=labels.documentHtml({},labels.items({lines:[{...first,ov_number:ov,customer_name:'Cliente QA'}]}));
 assert(html.includes('<strong class="ov-value"></strong>'),ov);
 assert(html.includes('<span class="field-caption">Cliente</span><strong>Cliente QA</strong>'));
 assert(!html.includes('>Stock</strong>'));assert(!html.includes('>Cotizaci\u00f3n</strong>'));
 assert(!html.includes('Para stock'));assert(!html.includes('>'+ov+'</strong>'));
}
""")

    def test_real_orders_with_similar_substrings_are_not_hidden_or_reclassified(self):
        self.run_js(r"""
for(const ov of ['001234','123456 / 123457','OV-POR-REG-7','SCOT-123456']){
 const html=labels.documentHtml({},labels.items({lines:[{...first,ov_number:ov}]}));
 assert(html.includes('<strong class="ov-value">'+ov+'</strong>'),ov);
}
""")

    def test_print_wording_does_not_merge_distinct_quote_or_pending_orders(self):
        self.run_js(r"""
const shipment={lines:[{...first,ov_number:'COT 123456'},
 {...first,id:2,ov_number:'COT 123457'}, {...first,id:3,ov_number:'POR REG'},
 {...first,id:4,ov_number:'POR REGULARIZAR'}]};
const before=JSON.stringify(shipment),items=labels.items(shipment);
assert.equal(items.length,4);assert.deepEqual(Array.from(items,item=>item.quantity),[2,2,2,2]);
const html=labels.documentHtml({},items);
assert.equal((html.match(/class="sticker"/g)||[]).length,4);
assert(html.includes('<strong class="ov-value">COT 123456</strong>'));
assert(html.includes('<strong class="ov-value">COT 123457</strong>'));
assert.equal((html.match(/class="ov-value"><\/strong>/g)||[]).length,2);
assert.equal(JSON.stringify(shipment),before);
""")

    def test_inventory_labels_still_omit_order_customer_and_bl(self):
        self.run_js(r"""
const html=labels.inventoryDocumentHtml({item_code:'QA-NP',stock_qty:0});
assert(!html.includes('class="ov-value"'));assert(!html.includes('field-caption">Cliente'));
assert(!html.includes('Para stock'));assert(!html.includes('BL / AWB'));
""")

    def test_prior_arrival_orders_cannot_generate_duplicate_current_labels(self):
        self.run_js(r"""
const shipment={lines:[first,{...first,id:2,np_count_covered_elsewhere:true},
 {...first,id:3,np_count_prior_review:true}]};
const before=JSON.stringify(shipment),items=labels.items(shipment);
assert.equal(items.length,1);assert.equal(items[0].quantity,2);
assert.equal(JSON.stringify(shipment),before);
""")
