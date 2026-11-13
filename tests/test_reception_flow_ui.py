"""Reception presentation and transaction boundaries, synthetic data only."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'),'Node required')
class ReceptionFlowUiTests(unittest.TestCase):
    def test_workspace_height_does_not_grow_after_outer_page_scroll(self):
        source=(ROOT/'frontend/static/management.js').read_text(encoding='utf-8')
        start=source.index('  function fitWorkspace()')
        end=source.index('\n  const observer',start)
        setup='''const assert=require('node:assert/strict');
let rectTop=70;const layout={style:{},getBoundingClientRect:()=>({top:rectTop})};
const window={innerHeight:873,scrollY:0,visualViewport:{height:873,offsetTop:0}};
const document={getElementById:()=>({getBoundingClientRect:()=>({height:72})}),
 body:{classList:{toggle(){}}},documentElement:{style:{setProperty(){}}}};
'''+source[start:end]+'''
fitWorkspace();assert.equal(layout.style.height,'731px');
rectTop=-130;window.scrollY=200;fitWorkspace();assert.equal(layout.style.height,'731px');
'''
        result=subprocess.run(['node','-e',setup],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr)

    def run_js(self,scenario,mutation=False):
        setup="""const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
global.window={};global.document={getElementById:()=>null};vm.runInThisContext(fs.readFileSync('frontend/static/reception-flow.js','utf8'));
"""
        if mutation:
            template=(ROOT/'frontend/templates/reception.html').read_text(encoding='utf-8')
            start=template.index('    async function mutate(')
            end=template.index('\n    }',start)+6
            setup+='''let selected={id:1},selectedId=1,selectedAttentionId=10;
let receptionMutationPending=false,loads=0,posts=0,messages=[];
const activeShipmentId=()=>selectedId;
const notify=(...args)=>messages.push(args);
const loadReceptions=async()=>{loads++};
const controls=[{disabled:false,isConnected:true},{disabled:true,isConnected:true}];
const root={querySelectorAll:()=>controls,setAttribute(){},removeAttribute(){}};
const $=id=>id==='content'?root:null;
'''+template[start:end]+'\n'
        result=subprocess.run(['node','-e',setup+'\n(async()=>{'+scenario+'})().catch(e=>{console.error(e);process.exit(1)})'],
            cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr or result.stdout)

    def test_document_and_physical_states_are_independent(self):
        self.run_js('''
const model=window.WmsReceptionFlow.model;
let v=model({app_status:'UBICACION',accounting_status:'PENDIENTE FR',attention_id:4,active_attention_sequence:2});
assert.equal(v.task,'Ubicación');assert.equal(v.document,'FR pendiente');assert.equal(v.documentTone,'warning');
assert.equal(v.delivery,'Entrega 2');assert.equal(v.closed,false);
v=model({app_status:'CERRADO',accounting_status:'PENDIENTE CONTABILIDAD'});
assert.equal(v.closed,true);assert.equal(v.task,'Recepción cerrada');assert.equal(v.documentTone,'warning');
assert.equal(model({app_status:'EM',accounting_status:'CONFLICTO IP'}).documentTone,'error');
assert.equal(model({app_status:'PROGRAMADO'}).task,'Llegada pendiente');
assert.equal(model({app_status:'NUEVO',accounting_status:'DESCONOCIDO'}).documentTone,'neutral');
assert.equal(model({app_status:'EM',accounting_status:'EM REGISTRADA'}).document,'EM registrada');
''')

    def test_mutation_is_single_flight_and_keeps_scope(self):
        self.run_js('''
let finish;global.api=async(url,options)=>{posts++;assert.equal(options.body.attention_id,10);
 return new Promise(resolve=>{finish=()=>resolve({ok:true,json:async()=>({id:1,attention_id:10})})})};
const pending=mutate('/api/receptions/1/status',{status:'EM'});
assert.equal(receptionMutationPending,true);assert(controls.every(c=>c.disabled));
await assert.rejects(mutate('/api/receptions/1/status',{status:'EM'}),/guardado/);
assert.equal(posts,1);finish();await pending;assert.equal(loads,1);
assert.equal(receptionMutationPending,false);assert.deepEqual(controls.map(c=>c.disabled),[false,true]);
''',mutation=True)

    def test_mutation_preserves_fields_on_error_and_discards_late_response(self):
        self.run_js('''
let fail=true,finish;
global.api=async()=>{if(fail)return {ok:false,json:async()=>({error:'Conflicto sintético'})};
 return new Promise(resolve=>{finish=()=>resolve({ok:true,json:async()=>({id:1,attention_id:10})})})};
await assert.rejects(mutate('/api/receptions/1/status',{}),/Conflicto sintético/);
assert.equal(loads,0);assert.equal(selected.id,1);assert.equal(receptionMutationPending,false);
fail=false;const pending=mutate('/api/receptions/1/status',{});
selected={id:2};selectedId=2;selectedAttentionId=20;finish();await pending;
assert.equal(selected.id,2);assert.equal(selectedAttentionId,20);assert.equal(loads,0);
assert(messages.some(m=>m[0].includes('otra')));
const errors=[];window.WmsReceptionFlow.saveState=error=>{if(error)errors.push(error)};
let rejectPost;global.api=async()=>new Promise((_,reject)=>rejectPost=reject);
const lateError=mutate('/api/receptions/2/status',{});selectedId=3;selectedAttentionId=30;
rejectPost(new Error('QA sin red'));await assert.rejects(lateError,/QA sin red/);
assert.deepEqual(errors,[]);assert.equal(selectedId,3);
''',mutation=True)
