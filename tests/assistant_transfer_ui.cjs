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

const diagnosed={costing:{ready:false,detail:'Pendiente de fecha de costeo en Facturas',issues:[
  {code:'IP_NOT_IN_FACTURAS',field:'IP en Facturas',message:'La IP QA-IP falta en Facturas.',
    action:'Revisa Facturas; no inventes un vínculo.',ip_reference:'QA-IP',source_sheet:'QA-SHEET',source_row:23,
    fr_number:'QA-FR',em_number:'QA-EM'}]}};
test('admin transfer diagnosis identifies field, source, action and refresh without generic false cause',()=>{
  const html=fixture('ADMINISTRADOR',diagnosed).html();
  assert.match(html,/Qué falta para cerrar esta entrega/);
  assert.match(html,/IP en Facturas/);assert.match(html,/QA-SHEET/);assert.match(html,/23/);
  assert.match(html,/Revisa Facturas; no inventes un vínculo/);
  assert.match(html,/Actualizar diagnóstico/);
  assert.doesNotMatch(html,/Pendiente de fecha de costeo en Facturas/);
});
test('diagnosis is admin-only even if a worker receives it; earlier stages remain compact',()=>{
  for(const role of ['ASISTENTE_RECEPCION','AUXILIAR_RECEPCION']){
    assert.doesNotMatch(fixture(role,diagnosed).html(),/QA-SHEET|QA-IP|Actualizar diagnóstico/);
  }
  assert.doesNotMatch(fixture('ADMINISTRADOR',{...diagnosed,app_status:'REVISION SISTEMA'}).html(),/QA-SHEET|Actualizar diagnóstico/);
});
test('source text in diagnosis is escaped and ready data removes the blocker panel',()=>{
  const f=fixture('ADMINISTRADOR',diagnosed);
  f.context.esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  f.context.selected={...f.context.selected,costing:{ready:false,issues:[{...diagnosed.costing.issues[0],
    message:'<img src=x onerror=alert(1)>',source_sheet:'<script>bad</script>'}]}};
  assert.doesNotMatch(f.html(),/<img|<script>/);
  assert.match(f.html(),/&lt;img/);
  assert.doesNotMatch(fixture('ADMINISTRADOR',{costing:{ready:true,issues:[]}}).html(),/Qué falta para cerrar/);
  const closed=fixture('ADMINISTRADOR',{...diagnosed,app_status:'CERRADO'}).html();
  assert.match(closed,/El cierre operativo se conserva/);
  assert.doesNotMatch(closed,/Qué falta para cerrar/);
});

test('diagnosis refresh preserves data on failure, suppresses duplicates and ignores a changed delivery',async()=>{
  const f=fixture('ADMINISTRADOR',diagnosed);let complete, renders=0;
  f.context.receptionHasUnsavedFields=()=>false;
  f.context.activeShipmentId=()=>1;f.context.selectedAttentionId=3;
  f.context.loadDetail=async()=>{f.context.selected=null;};
  f.context.renderDetail=()=>{renders++;};f.context.loadReceptionAssignees=async()=>{};
  f.context.api=async()=>{throw Error('QA connection failed');};
  const initial=f.context.selected;
  f.context.receptionHasUnsavedFields=()=>true;f.context.confirm=()=>false;
  await f.context.refreshTransfer();assert.equal(f.context.selected,initial);assert.equal(f.errors.length,0);
  f.context.receptionHasUnsavedFields=()=>false;
  await f.context.refreshTransfer();assert.equal(f.context.selected,initial);
  assert.equal(f.errors.at(-1),'QA connection failed');assert.equal(renders,0);
  f.context.api=()=>new Promise(resolve=>{complete=resolve;});
  const first=f.context.refreshTransfer();await f.context.refreshTransfer();
  const next={...f.context.selected,costing:{ready:true,issues:[]}};
  complete({ok:true,json:async()=>next});await first;
  assert.equal(renders,1);assert.equal(f.context.selected.costing.ready,true);
  const pending=f.context.refreshTransfer();
  f.context.selected={id:99,attention_id:101};
  complete({ok:true,json:async()=>next});await pending;
  assert.equal(f.context.selected.id,99);assert.equal(renders,1);
  f.context.api=async()=>({ok:true,json:async()=>next});
  await f.context.refreshTransfer();assert.equal(f.context.selected.id,99);
  assert.match(f.errors.at(-1),/no corresponde/);
});

const unassigned={accounting_refs:[{id:4,fr_number:'QA-FR',ip_reference_key:'IP260001',
  em_entries:[{id:31,em_number:'70001 -',attention_id:null},{id:32,em_number:'70001',attention_id:null}]}]};
test('only admin can associate an existing EM and numeric aliases have one choice',()=>{
  const admin=fixture('ADMINISTRADOR',unassigned).html();
  assert.match(admin,/Vincular EM a esta entrega/);
  assert.equal((admin.match(/EM 70001/g)||[]).length,1);
  assert.doesNotMatch(fixture('ASISTENTE_RECEPCION',unassigned).html(),/Vincular EM a esta entrega/);
});
test('EM association captures exact entry and attention and requires an explicit choice',async()=>{
  const f=fixture('ADMINISTRADOR',unassigned),select={value:''};
  f.context.$=id=>id==='emScopeSelect'?select:f.button;
  await f.context.bindExistingEmToAttention();assert.equal(f.saved.length,0);
  select.value='0';f.context.confirm=()=>false;await f.context.bindExistingEmToAttention();assert.equal(f.saved.length,0);
  f.context.confirm=()=>true;await f.context.bindExistingEmToAttention();
  assert.equal(f.saved.length,1);assert.equal(f.saved[0].data.attention_id,3);
  assert.equal(f.saved[0].data.reference_updates[0].em_id,32);
  assert.equal(f.saved[0].data.reference_updates[0].bind_to_attention,true);
  assert.equal(f.saved[0].data.reference_updates[0].confirmed,true);
});

const combined={attention_id:1,attentions:[{id:1,sequence_no:1},{id:2,sequence_no:2},{id:3,sequence_no:3}],
  accounting_refs:[{id:4,fr_number:'QA-FR',ip_reference_key:'IP260001',em_eligible_attention_ids:[1,2,3],
    em_entries:[{id:32,em_number:'70001',attention_id:3,shared_attention_ids:[]}]}]};
test('combined EM exception is an optional admin tool, never worker data entry',()=>{
  assert.match(fixture('ADMINISTRADOR',combined).html(),/Una EM para varias entregas/);
  assert.doesNotMatch(fixture('ASISTENTE_RECEPCION',combined).html(),/Guardar cobertura/);
});
test('combined coverage submits only selected arrivals, cancel preserves it, and duplicate clicks wait',async()=>{
  const f=fixture('ADMINISTRADOR',combined),select={value:'4:32:IP260001'},targets={innerHTML:''};
  f.context.$=id=>id==='sharedEmSelect'?select:id==='sharedEmAttentions'?targets:f.button;
  f.context.document.querySelectorAll=()=>[{value:'1'},{value:'3'}];
  f.context.renderSharedEmAttentions();assert.match(targets.innerHTML,/Entrega 2/);
  assert.equal((targets.innerHTML.match(/ checked/g)||[]).length,1,'only EM origin selected automatically');
  f.context.confirm=()=>false;await f.context.saveSharedEmCoverage();assert.equal(f.saved.length,0);
  f.context.confirm=()=>true;let resolve;
  f.context.mutate=async(url,data)=>{f.saved.push({url,data});await new Promise(done=>resolve=done);};
  const first=f.context.saveSharedEmCoverage();await f.context.saveSharedEmCoverage();assert.equal(f.saved.length,1);
  assert.deepEqual(Array.from(f.saved[0].data.reference_updates[0].coverage_attention_ids),[1,3]);
  assert.equal(f.saved[0].data.reference_updates[0].em_id,32);resolve();await first;
});
