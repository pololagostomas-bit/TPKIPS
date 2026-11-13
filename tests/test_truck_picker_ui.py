"""Selection must survive a filtered or stale truck-list response."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('node'),'Node required')
class TruckPickerUiTests(unittest.TestCase):
    def run_js(self,name,scenario):
        source=(ROOT/'frontend/templates/reception.html').read_text(encoding='utf-8')
        line=next(line for line in source.splitlines() if 'function '+name+'(' in line)
        result=subprocess.run(['node','-e',"const assert=require('node:assert/strict');\n"+scenario.replace('FUNCTION',line)],
            cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr)

    def test_filter_does_not_drop_the_working_truck(self):
        self.run_js('updateTruckGuideFilter','''
const select={value:'WORKING',selectedOptions:[{textContent:'Camión guardado'}],options:[],
 set innerHTML(v){this.value='ALL';this.options=[{value:'ALL'}]},add(option){this.options.push(option)}};
const $=()=>select,esc=String,truckGuideLabel=String,truckGuides=[{truck_guide:'OTHER'}];
const Option=function(text,value){this.textContent=text;this.value=value};
FUNCTION
updateTruckGuideFilter();assert.equal(select.value,'WORKING');
assert(select.options.some(o=>o.value==='WORKING'));
''')

    def test_old_list_response_cannot_replace_new_search(self):
        self.run_js('loadTruckGuides','''
let query='old',truckGuides=[],renders=0,truckGuideRequest=0,showAllTruckGuides=false;
const $=()=>({value:query}),applyPermissions=()=>true,isAdmin=()=>true;
const notify=()=>{},updateTruckGuideFilter=()=>{},renderQueue=()=>{renders++};
const window={WmsTruckPicker:{loading(){},sync(){},error(){}}};
const finish={};const api=async url=>new Promise(resolve=>{finish[url]=data=>resolve({ok:true,json:async()=>data})});
FUNCTION
(async()=>{const a=loadTruckGuides();query='new';const b=loadTruckGuides();
finish['/api/truck-guides?search=new&all=0']([{truck_guide:'NEW',active_bl_count:1}]);await b;
finish['/api/truck-guides?search=old&all=0']([{truck_guide:'OLD',active_bl_count:1}]);await a;
assert.equal(truckGuides[0].truck_guide,'NEW');assert.equal(renders,1);
})().catch(e=>{console.error(e);process.exit(1)});
''')
