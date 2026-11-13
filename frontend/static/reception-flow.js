/* Task, documents and related records remain separate; the server owns transitions. */
window.WmsReceptionFlow = (() => {
  'use strict';
  const tasks = {PROGRAMADO:'Llegada pendiente',ARRIBADO:'Zona de recepción',
    'REVISION SISTEMA':'Inicio de conteo',EM:'EM y etiquetas',UBICACION:'Ubicación',
    VALIDACION:'Validación', 'SOLICITUD TRANSFERENCIA':'Transferencia SAP',CERRADO:'Recepción cerrada'};
  const panelNames = {bultos:'Llegada',zona:'Zona de recepción',admin:'Asignación',
    sistema:'Inicio de conteo',em:'EM y etiquetas',ubicacion:'Ubicación',
    validacion:'Validación',transferencia:'Transferencia SAP',fuente:'Consulta SAP'};
  let lastContext='';
  function model(shipment) {
    const status=shipment.accounting_status || 'PENDIENTE CONTABILIDAD';
    const documents={'PENDIENTE CONTABILIDAD':['FR pendiente','warning'],
      'PENDIENTE FR':['FR pendiente','warning'],'PENDIENTE EM':['EM pendiente','warning'],
      'CONFLICTO IP':['Referencias por revisar','error'],'EM REGISTRADA':['EM registrada','success'],
      'FR/EM COMPLETAS':['FR y EM completas','success']};
    const [document,documentTone]=documents[status] || [status,'neutral'];
    const sequence=shipment.attention_sequence || shipment.active_attention_sequence;
    return {task:tasks[shipment.app_status] || 'Estado por revisar',document,documentTone,
      delivery:sequence?'Entrega '+sequence:'Recepción general',closed:shipment.app_status==='CERRADO'};
  }
  function saveState(error='') {
    const status=document.getElementById('receptionSaveState');if(!status)return;
    const pending=typeof receptionMutationPending!=='undefined' && receptionMutationPending;
    status.hidden=!pending&&!error;
    status.textContent=error || (pending?'Guardando. Espera la confirmación.':'');
    status.setAttribute('role',error?'alert':'status');
    status.classList.toggle('error',Boolean(error));
    if(error){status.tabIndex=-1;status.focus();}
  }
  function openRelated(id) {
    const target=document.getElementById(id);if(!target)return;
    for(let node=target;node;node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;
    target.scrollIntoView({block:'start',behavior:'auto'});
    const focus=target.querySelector('summary') || target;
    if(focus===target)focus.tabIndex=-1;
    focus.focus({preventScroll:true});
  }
  function relatedSection(id,title,node) {
    if(!node)return null;
    const details=document.createElement('details');details.id=id;details.className='reception-related';
    const summary=document.createElement('summary');summary.textContent=title;
    details.append(summary,node);return details;
  }
  function syncStage() {
    const title=document.getElementById('receptionTaskTitle');if(!title)return;
    const panel=document.querySelector('[data-reception-panel][data-stage-active]');
    const label=panelNames[panel?.dataset.receptionPanel];
    const historical=panel?.classList.contains('historical-readonly');
    title.textContent=label ? (historical?'Consulta: ':'')+label : model(selected).task;
  }
  function mount() {
    const content=document.getElementById('content'),hero=content?.querySelector('.hero');
    if(!hero||!selected)return;
    content.classList.add('reception-record');
    content.querySelectorAll('.back-btn').forEach(button=>button.classList.add('ghost'));
    const shipment=selected,view=model(shipment);
    hero.classList.add('reception-record-header');
    const context=document.createElement('p');context.className='reception-delivery-context';
    context.textContent=view.delivery;
    hero.querySelector('h1')?.after(context);
    const status=document.createElement('div');status.className='reception-record-status';
    status.innerHTML=`<span><span class="reception-status-label">Trabajo</span><strong>${esc(view.task)}</strong></span>
      <span data-document-tone="${view.documentTone}"><span class="reception-status-label">Documentos</span><strong>${esc(view.document)}</strong></span>`;
    hero.append(status);
    hero.querySelector('.badges .badge:first-child')?.remove();
    const task=document.createElement('div');task.className='reception-task-heading';
    task.innerHTML='<h2 id="receptionTaskTitle"></h2>';
    const stages=content.querySelector('.scan-stage-picker');
    const firstPanel=content.querySelector('[data-reception-panel]');
    if(firstPanel)firstPanel.before(task);
    if(stages){stages.id='receptionStages';stages.querySelector('summary').textContent='Etapas de esta entrega';
      stages.querySelectorAll('[data-reception-tab]').forEach(button=>{button.textContent=panelNames[button.dataset.receptionTab] || button.textContent;});}
    const related=document.createElement('nav');related.className='reception-record-links';
    related.setAttribute('aria-label','Consultas de esta recepción');
    const sections=document.createElement('section');sections.className='reception-record-related';
    sections.setAttribute('aria-label','Información relacionada');
    function add(id,label,node) {
      if(!node)return;
      sections.append(node);
      const button=document.createElement('button');button.type='button';button.className='ghost';button.textContent=label;
      button.setAttribute('aria-controls',id);button.onclick=()=>openRelated(id);related.append(button);
    }
    const deliveries=content.querySelector('.attention-work,.attention-summary');
    add('receptionDeliveries','Entregas',relatedSection('receptionDeliveries','Entregas de la BL',deliveries));
    const docs=content.querySelector('.reception-relations');
    if(docs){docs.id='receptionDocuments';docs.classList.add('reception-related');
      docs.querySelector('summary').textContent='Documentos y referencias';add(docs.id,'Documentos',docs);}
    const timeline=document.createElement('ol');timeline.className='reception-timeline';
    timeline.innerHTML=(shipment.attentions || []).map(attention=>`<li><strong>${esc(attention.label || 'Entrega')}</strong>
      <span>${esc(tasks[attention.app_status] || attention.app_status || 'Sin estado')}</span>
      <span>Recepción: ${esc(attention.received_at || 'Sin fecha física registrada')}</span>
      ${attention.completed_at?`<span>Cierre: ${esc(attention.completed_at)}</span>`:''}</li>`).join('');
    if(timeline.childElementCount)add('receptionTimeline','Historial',relatedSection('receptionTimeline','Historial de entregas',timeline));
    if(isAdmin()){
      const nodes=[...content.querySelectorAll('.admin-rewind,.admin-closure-entry')];
      if(nodes.length){const controls=document.createElement('div');controls.append(...nodes);
        add('receptionAdministration','Administración',relatedSection('receptionAdministration','Administración de la recepción',controls));}
    }
    hero.after(related);
    const actions=content.querySelector('.scan-bl-next');
    if(actions){
      const alerts=[...actions.children].filter(node=>!node.classList.contains('stage-advance'));
      if(alerts.length){const warnings=document.createElement('div');warnings.className='reception-record-warnings';warnings.append(...alerts);related.after(warnings);}
    }
    const frPending=content.querySelector('#frPendingNotice');
    if(frPending)frPending.textContent='Factura de reserva pendiente. Falta regularizar el documento de esta entrega.';
    const saving=document.createElement('p');saving.id='receptionSaveState';saving.className='reception-save-state';saving.hidden=true;
    related.after(saving);
    content.append(sections);
    window.WmsMobileWorkspace?.refresh();
    const contextKey=[shipment.id,shipment.attention_id,shipment.app_status].join(':');
    if(contextKey!==lastContext){content.scrollTop=0;lastContext=contextKey;}
    syncStage();saveState();
  }
  if(typeof renderDetail==='function'){
    const base=renderDetail;
    renderDetail=function(){document.getElementById('content')?.classList.remove('reception-record');base();mount();};
    const activate=activateReceptionTab;
    activateReceptionTab=function(id){activate(id);syncStage();};
  }
  return {model,mount,saveState};
})();
