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

    def test_inventory_labels_still_omit_order_customer_and_bl(self):
        self.run_js(r"""
const html=labels.inventoryDocumentHtml({item_code:'QA-NP',stock_qty:0});
assert(!html.includes('class="ov-value"'));assert(!html.includes('field-caption">Cliente'));
assert(!html.includes('Para stock'));assert(!html.includes('BL / AWB'));
""")
