const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../frontend/static/reception-transfer.js'), 'utf8');

function fixture(profile='ASISTENTE_RECEPCION', changes={}) {
  const saved=[], errors=[], button={disabled:false,isConnected:true};
  const context={console, selected:{id:1,attention_id:3,app_status:'SOLICITUD TRANSFERENCIA',
    current_assistant:'qa.receiver',current_auxiliary:'qa.auxiliary',...changes},
    states:['PROGRAMADO','ARRIBADO','REVISION SISTEMA','EM','UBICACION','VALIDACION','SOLICITUD TRANSFERENCIA','CERRADO'],
    role:()=>profile,userName:()=> 'qa.receiver',isAdmin:()=>profile==='ADMINISTRADOR',esc:v=>String(v??''),
    confirm:()=>true,prompt:()=> 'SAP transfer verified',notify:(message)=>errors.push(message),
    $:()=>button,shipmentUrl:suffix=>'/api/receptions/1'+suffix,
    mutate:async(url,data)=>{saved.push({url,data});},document:{getElementById:()=>button}};
  context.window=context;vm.createContext(context);vm.runInContext(source,context);
  return {context,saved,errors,button,html:()=>context.transferCard(context.selected)};
}

test('assigned assistant sees SAP confirmation but no administrator actions',()=>{
  const f=fixture(), html=f.html();
  assert.match(html,/Confirmar transferencia en SAP/);
  assert.doesNotMatch(html,/Reenviar aviso|Confirmación administrativa|Ver aviso en Correos/);
});
test('auxiliary, another assignee, wrong stage and completed delivery cannot confirm',()=>{
  for(const [role,changes] of [['AUXILIAR_RECEPCION',{}],['ASISTENTE_RECEPCION',{current_assistant:'other',current_auxiliary:'qa.receiver'}],
      ['ASISTENTE_RECEPCION',{app_status:'VALIDACION'}],['ASISTENTE_RECEPCION',{transfer_assistant_checked:1}],
      ['ASISTENTE_RECEPCION',{condition_status:'ANULADA QA'}],
      ['ASISTENTE_RECEPCION',{attention_id:0}]]) {
    assert.doesNotMatch(fixture(role,changes).html(),/onclick="saveTransferCheck\(\)"/);
  }
});
test('assistant explicitly confirms current delivery and concurrent clicks do not repeat',async()=>{
  const f=fixture();let resolve;
  f.context.mutate=async(url,data)=>{f.saved.push({url,data});await new Promise(done=>resolve=done);};
  const first=f.context.saveTransferCheck();await f.context.saveTransferCheck();
  assert.equal(f.saved.length,1);assert.equal(f.saved[0].data.checked,true);
  assert.equal(f.saved[0].data.attention_id,3);assert.equal(f.button.disabled,true);
  resolve();await first;assert.equal(f.button.disabled,false);
});
test('cancel and insufficient observation do not write; errors preserve retry',async()=>{
  const f=fixture();f.context.confirm=()=>false;await f.context.saveTransferCheck();assert.equal(f.saved.length,0);
  f.context.confirm=()=>true;f.context.prompt=()=>null;await f.context.saveTransferCheck();assert.equal(f.saved.length,0);
  f.context.prompt=()=> 'x';await f.context.saveTransferCheck();assert.equal(f.saved.length,0);assert.equal(f.errors.length,1);
  f.context.prompt=()=> 'SAP transfer verified';f.context.mutate=async()=>{throw Error('QA unavailable');};
  await f.context.saveTransferCheck();assert.equal(f.errors.at(-1),'QA unavailable');assert.equal(f.button.disabled,false);
  f.context.mutate=async(url,data)=>{f.saved.push({url,data});};await f.context.saveTransferCheck();assert.equal(f.saved.length,1);
});
test('administrator keeps administrative confirmation and mail controls',()=>{
  assert.match(fixture('ADMINISTRADOR').html(),/Confirmación administrativa/);
  assert.match(fixture('ADMINISTRADOR').html(),/Reenviar aviso/);
});
