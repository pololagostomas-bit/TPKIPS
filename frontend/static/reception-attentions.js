/* Physical arrivals and administrative package audit, independent of NP count. */
(() => {
  let busy=false, context=null, review=null, action=null;
  const hasReads=()=>window.WmsNpScan?.hasPending?.()||window.WmsTruckScan?.hasPending?.();
  attentionSummary=function(shipment){
    const attentions=shipment.attentions||[], p=shipment.package_progress||{};
    if(!attentions.length)return '';
    return `<section class="attention-work" aria-label="Atenciones de la BL"><h2>Recepciones de la BL</h2>
      <p><strong>${Number(p.received||0)}${p.expected!=null?'/'+Number(p.expected):''} bultos recibidos</strong>
      ${p.pending!=null?` · ${Number(p.pending)} por llegar · ${esc(p.source||'')}`:' · Total por confirmar'}</p>
      ${attentions.map(a=>`<div class="attention-task"><div><strong>${esc(a.label)}</strong>
      <span>${esc(stateLabel(a.app_status))}</span><span>${esc(a.truck_guide||'Sin camion asociado')}</span></div>
      <div><strong>${a.received_packages==null?'Sin recibo':Number(a.received_packages)+' bultos recibidos'}</strong>
      <span>${Number(a.scanned_packages||0)} lecturas unicas</span></div><button class="ghost" type="button"
      data-attention-open="${Number(a.id)}" ${Number(a.id)===Number(shipment.attention_id)?'disabled aria-current="true"':''}>
      ${Number(a.id)===Number(shipment.attention_id)?'Atencion actual':'Abrir atencion'}</button></div>`).join('')}
      ${isAdmin()&&shipment.attention_id?'<div class="actions"><button class="ghost" type="button" id="packageReviewOpen">Regularizar bultos de esta llegada</button></div>':''}</section>`;
  };
  const renderBase=renderDetail;
  renderDetail=function(){
    renderBase();
    document.querySelectorAll('[data-attention-open]').forEach(button=>button.addEventListener('click',async()=>{
      if(busy||hasReads()){notify('Resuelve las lecturas pendientes antes de cambiar de atencion.','warning');return;}
      if(receptionHasUnsavedFields()&&!confirmLeaveActiveReceptionWork('la otra atencion'))return;
      busy=true;try{await loadDetail(selectedId,false,Number(button.dataset.attentionOpen));}finally{busy=false;}
    }));
    $('packageReviewOpen')?.addEventListener('click',()=>openReview({shipmentId:Number(selectedId),attentionId:Number(selectedAttentionId)}));
  };
  const truckBase=renderTruckGuideWorkspace;
  renderTruckGuideWorkspace=function(summary){
    truckBase(summary);if(!isAdmin())return;
    const target=$('scanTruckWorkspace')?.querySelector('.scan-task')||$('manualTruckWorkspace');if(!target)return;
    target.insertAdjacentHTML('beforeend',`<details class="package-admin-tools"><summary>Control administrativo de bultos</summary>
      ${(summary.bls||[]).filter(bl=>Number(bl.package_scan_count||bl.received_this_truck||0)>0).map(bl=>`<button class="ghost" type="button" data-package-review="${Number(bl.id)}">Revisar bultos ${esc(bl.bl_awb)}</button>`).join('')}</details>`);
    target.querySelectorAll('[data-package-review]').forEach(button=>button.addEventListener('click',()=>openReview({shipmentId:Number(button.dataset.packageReview),truckGuide:summary.truck_guide})));
  };
  const dialog=document.createElement('dialog');dialog.id='packageReviewDialog';dialog.className='read-correction-dialog';
  dialog.setAttribute('aria-labelledby','packageReviewTitle');
  dialog.innerHTML=`<h2 id="packageReviewTitle">Regularizar bultos</h2><p id="packageReviewContext"></p>
    <p id="packageReviewBalance"></p><div id="packageReviewItems"></div><div id="packageReviewPending"></div>
    <form id="packageCorrectionForm" hidden><h3 id="packageCorrectionTitle"></h3>
    <div class="field" id="packageCorrectionCodeField"><label for="packageCorrectionCode">Codigo unico correcto</label><input id="packageCorrectionCode" class="control" autocomplete="off"></div>
    <div class="field" id="packageCorrectionQtyField"><label for="packageCorrectionQty">Bultos realmente recibidos</label><input id="packageCorrectionQty" class="control" type="number" min="0" max="100000" step="1"></div>
    <p id="packageCorrectionEffect"></p><div class="field"><label for="packageCorrectionReason">Motivo de la regularizacion</label><textarea class="control" id="packageCorrectionReason" required minlength="8" maxlength="500" rows="3"></textarea></div>
    <div class="actions"><button class="ghost" type="button" id="packageCorrectionCancel">Cancelar correccion</button><button class="primary" type="submit" id="packageCorrectionSubmit">Confirmar correccion</button></div></form>
    <p id="packageReviewError" role="alert" hidden></p><div class="actions"><button class="ghost" type="button" id="packageReviewClose">Cerrar</button></div>`;
  document.body.append(dialog);
  const params=ctx=>ctx.attentionId?'attention_id='+ctx.attentionId:'truck_guide='+encodeURIComponent(ctx.truckGuide);
  function display(){
    $('packageReviewContext').textContent=`${review.bl_awb} · ${review.truck_guide||'Sin camion asociado'}`;
    $('packageReviewBalance').textContent=`Esta llegada: ${review.received_this_arrival} bultos · Recibidos confirmados BL: ${review.received_confirmed}`;
    $('packageReviewItems').innerHTML=review.items.map(item=>`<div class="package-read"><strong>${esc(item.code)}</strong><span>${esc(item.scanned_by||'')} · ${esc(item.scanned_at||'')}</span><div class="actions"><button type="button" class="ghost" data-package-replace="${Number(item.id)}">Corregir codigo</button><button type="button" class="ghost" data-package-remove="${Number(item.id)}">Quitar bulto</button></div></div>`).join('')||'<p>Esta llegada no tiene lecturas unicas registradas.</p>';
    if(review.can_adjust_receipt)$('packageReviewItems').insertAdjacentHTML('beforeend','<button class="ghost" type="button" id="packageReceiptAdjust">Regularizar cantidad del recibo</button>');
    const pending=review.pending_codes||[];
    $('packageReviewPending').innerHTML=`<details><summary>Bultos pendientes de DHL${review.pending_count!=null?' · '+review.pending_count:''}</summary>${pending.length?'<ul>'+pending.map(code=>'<li>'+esc(code)+'</li>').join('')+'</ul>':'<p>Sin codigos pendientes disponibles en el cache.</p>'}</details>`;
    dialog.querySelectorAll('[data-package-replace]').forEach(button=>button.addEventListener('click',()=>choose('replace',Number(button.dataset.packageReplace))));
    dialog.querySelectorAll('[data-package-remove]').forEach(button=>button.addEventListener('click',()=>choose('remove',Number(button.dataset.packageRemove))));
    $('packageReceiptAdjust')?.addEventListener('click',()=>choose('receipt_quantity'));
  }
  function choose(kind,id){
    if(busy)return;const item=review.items.find(row=>row.id===id);
    action={kind,id,token:review.token};$('packageCorrectionForm').reset();$('packageCorrectionForm').hidden=false;
    $('packageCorrectionTitle').textContent=kind==='replace'?'Corregir '+item.code:kind==='remove'?'Quitar '+item.code:'Regularizar cantidad sin codigos unicos';
    $('packageCorrectionCodeField').hidden=kind!=='replace';$('packageCorrectionCode').required=kind==='replace';
    $('packageCorrectionQtyField').hidden=kind!=='receipt_quantity';$('packageCorrectionQty').required=kind==='receipt_quantity';$('packageCorrectionQty').value=review.received_this_arrival;
    $('packageCorrectionEffect').textContent=kind==='replace'?'La lectura original quedara anulada en el historial. No cambia la cantidad recibida.':'Se corregira solo esta llegada. Al cambiar sus bultos, se debe confirmar nuevamente su ubicacion temporal. No modifica los NP ni las otras llegadas.';
    $('packageReviewError').hidden=true;$('packageCorrectionReason').focus();
  }
  async function openReview(ctx){
    if(!isAdmin()||busy||hasReads())return;
    if(receptionHasUnsavedFields()&&!confirmLeaveActiveReceptionWork('la revision administrativa'))return;
    busy=true;
    try{
      const response=await api(`/api/receptions/${ctx.shipmentId}/package-review?${params(ctx)}`,{cache:'no-store'});
      const data=await response.json();if(!response.ok)throw Error(data.error||'No se pudieron consultar los bultos');
      context={...ctx};review=data;action=null;display();$('packageCorrectionForm').hidden=true;$('packageReviewError').hidden=true;dialog.showModal();
    }catch(error){notify(error.message,'error');}finally{busy=false;}
  }
  $('packageCorrectionCancel').addEventListener('click',()=>{if(!busy){action=null;$('packageCorrectionForm').hidden=true;}});
  $('packageReviewClose').addEventListener('click',()=>{if(!busy)dialog.close();});
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  $('packageCorrectionForm').addEventListener('submit',async event=>{
    event.preventDefault();if(busy||!action||!context)return;const reason=$('packageCorrectionReason').value.trim();if(reason.length<8)return;
    const body={attention_id:context.attentionId,truck_guide:context.truckGuide,scan_id:action.id,action:action.kind,token:action.token,confirmed:true,reason,package_code:$('packageCorrectionCode').value.trim(),received_packages:$('packageCorrectionQty').value};
    const controls=[...dialog.querySelectorAll('input,textarea,button')];controls.forEach(control=>control.disabled=true);busy=true;
    try{
      const response=await api(`/api/receptions/${context.shipmentId}/package-correction`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const data=await response.json();if(!response.ok)throw Error(data.error||'No se pudo corregir. Revisa el historial antes de repetir.');
      review=data;action=null;display();$('packageCorrectionForm').hidden=true;$('packageReviewError').hidden=true;
      if(Number(selectedId)===context.shipmentId&&(!context.attentionId||Number(selectedAttentionId)===context.attentionId)){
        if(data.received_this_arrival===0)selectedAttentionId=null;await loadDetail(context.shipmentId,false,selectedAttentionId);
      }else if(activeTruckGuideSummary?.truck_guide===context.truckGuide)await showTruckGuideWorkspace();
      notify('Bulto regularizado con historial de auditoria.');
    }catch(error){$('packageReviewError').textContent=error.message;$('packageReviewError').hidden=false;}
    finally{busy=false;controls.forEach(control=>control.disabled=false);}
  });
  window.WmsPackageReview={open:openReview,hasPending:()=>busy};
  if(selected)renderDetail();
})();
