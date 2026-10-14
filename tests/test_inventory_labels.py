"""Generic SKU labels reuse the proven print engine without reception globals."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node required')
class InventoryLabelUiTests(unittest.TestCase):
    def run_js(self, scenario):
        setup = """
const assert=require('assert/strict');
global.window={location:{origin:'http://127.0.0.1'},bwipjs:require('./frontend/static/bwip-js-min.js')};
global.document={querySelector:()=>null};
require('./frontend/static/reception-labels.js');
const labels=window.WmsReceptionLabels;
"""
        result = subprocess.run(['node', '-e', setup + scenario], cwd=ROOT,
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_inventory_profile_omits_shipment_fields_and_uses_exact_np(self):
        self.run_js("""
const item={item_code:'ICM/2022-273.a',description:'Pieza <segura>',stock_qty:2,
 default_location:'BIN-01',label_brand:'BOBCAT EUROPA',ov_number:'SECRET-OV',
 customer_name:'SECRET-CUSTOMER',bl_awb:'SECRET-BL'};
const html=labels.inventoryDocumentHtml(item);
assert(html.includes('inventory-sticker'));assert(html.includes('Data Matrix ICM/2022-273.a'));
assert(html.includes('Pieza &lt;segura&gt;'));assert(html.includes('BIN-01'));assert(html.includes('BOBCAT'));
for(const unwanted of ['SECRET-','# OV','BL / AWB','Cliente','class="ov"','class="customer"'])assert(!html.includes(unwanted));
assert.equal(labels.inventoryItem(item).np,item.item_code);
assert.equal(labels.inventoryItem({...item,stock_qty:0}).location,'');
assert.equal(labels.inventoryItem({...item,stock_qty:-1}).location,'');
assert.equal(labels.inventoryItem({...item,brand_logo_url:'javascript:bad()'}).logo,'');
assert.throws(()=>labels.inventoryItem({}),/NP/);
assert(!('printOvStickers' in global));assert(!('emEntryCard' in global));
""")

    def test_shared_reception_profile_keeps_ov_customer_and_bl(self):
        self.run_js("""
const html=labels.documentHtml({bl_awb:'BL001'},[{np:'NP001',ov:'OV001',customer:'Cliente uno',
 location:'A-01',description:'Filtro',brand:'BOBCAT',logo:'',companyLogo:''}]);
assert(html.includes('# OV'));assert(html.includes('OV001'));assert(html.includes('Cliente uno'));
assert(html.includes('BL001'));assert(!html.includes('inventory-sticker'));
""")


if __name__ == '__main__':
    unittest.main()
