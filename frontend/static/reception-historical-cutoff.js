/* Explicit historical cutoff. Opening the view cannot close a shipment. */
(() => {
  window.showHistoricalCutoff=function(){
    if(!isAdmin())return;
    if(window.WmsNpScan?.hasPending?.()||window.WmsTruckScan?.hasPending?.()){notify('Resuelve las lecturas pendientes antes de continuar.','warning');return;}
    if(receptionHasUnsavedFields()&&!confirmLeaveActiveReceptionWork('el cierre historico'))return;
    clearSelection();closeQueue();setActiveNav('more');
    const root=$('content');
    root.innerHTML=`<section class="attention-work"><h1>Cierre historico</h1>
      <div class="form-grid"><div class="field"><label for="historicalCutoffDate">Fecha prevista hasta</label>
      <input class="control" type="date" id="historicalCutoffDate" value="2026-07-31" max="2026-07-31"></div>
      <div class="field"><button class="ghost" type="button" id="historicalCutoffPreview">Revisar BL</button></div></div>
      <p id="historicalCutoffStatus" role="status"></p><div id="historicalCutoffResults"></div>
      <form id="historicalCutoffForm" hidden><p>Es un cierre historico por instruccion del propietario. No acredita FR, EM ni transferencia en SAP.</p>
      <div class="field"><label for="historicalCutoffReason">Motivo del cierre</label><textarea class="control" id="historicalCutoffReason" required minlength="8" maxlength="500" rows="3"></textarea></div>
      <label class="check-row"><input type="checkbox" id="historicalCutoffConfirm" required>Confirmo cerrar solo las BL de esta vista previa, conservando los documentos y el historial.</label>
      <div class="actions"><button class="primary" type="submit" id="historicalCutoffApply">Cerrar BL historicas</button></div></form>
      <p id="historicalCutoffError" role="alert" hidden></p></section>`;
    const view=root.firstElementChild;let preview=null,busy=false;
    const current=()=>view.isConnected;
    const controls=()=>[...view.querySelectorAll('input,textarea,button')];
    const lock=value=>controls().forEach(control=>{control.disabled=value;});
    const fail=error=>{if(current()){$('historicalCutoffError').textContent=error.message;$('historicalCutoffError').hidden=false;}};
    $('historicalCutoffDate').addEventListener('change',()=>{preview=null;$('historicalCutoffForm').hidden=true;$('historicalCutoffResults').innerHTML='';});
    $('historicalCutoffPreview').addEventListener('click',async()=>{
      if(busy)return;busy=true;lock(true);$('historicalCutoffError').hidden=true;
      $('historicalCutoffStatus').textContent='Revisando BL...';
      try{
        const response=await api('/api/receptions/historical-cutoff?cutoff='+encodeURIComponent($('historicalCutoffDate').value),{cache:'no-store'});
        const data=await response.json();if(!response.ok)throw Error(data.error||'No se pudo revisar el corte');if(!current())return;
        preview=data;
        $('historicalCutoffStatus').textContent=`${data.counts.eligible} BL para cierre · ${data.counts.by_reason.ALREADY_CLOSED||0} ya cerradas · ${data.counts.excluded-(data.counts.by_reason.ALREADY_CLOSED||0)} excluidas`;
        $('historicalCutoffResults').innerHTML=`<div class="tablewrap"><table><thead><tr><th>BL/AWB</th><th>Fecha prevista</th><th>Estado contable conservado</th></tr></thead><tbody>${data.eligible.slice(0,50).map(row=>`<tr><td>${esc(row.bl_awb)}</td><td>${esc(row.scheduled_day)}</td><td>${esc(row.accounting_status||'Sin informar')}</td></tr>`).join('')||'<tr><td colspan="3">No hay BL elegibles.</td></tr>'}</tbody></table></div>${data.eligible.length>50?`<p>50 de ${data.eligible.length} BL elegibles. La confirmacion incluye todas las BL elegibles del corte.</p>`:''}`;
        $('historicalCutoffForm').hidden=!data.counts.eligible;$('historicalCutoffConfirm').checked=false;
      }catch(error){fail(error);if(current())$('historicalCutoffStatus').textContent='Corte no comprobado.';}
      finally{busy=false;if(current())lock(false);}
    });
    $('historicalCutoffForm').addEventListener('submit',async event=>{
      event.preventDefault();if(busy||!preview||!$('historicalCutoffConfirm').checked)return;
      const reason=$('historicalCutoffReason').value.trim();if(reason.length<8)return;
      const body={cutoff:preview.cutoff,token:preview.token,reason,confirmed:true};busy=true;lock(true);$('historicalCutoffError').hidden=true;
      try{
        const response=await api('/api/receptions/historical-cutoff',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        const data=await response.json();if(!response.ok)throw Error(data.error||'No se pudo aplicar. Revisa el estado antes de repetir.');if(!current())return;
        preview=null;$('historicalCutoffForm').hidden=true;$('historicalCutoffResults').innerHTML='';
        $('historicalCutoffStatus').textContent=`${data.applied_count} BL cerradas como historicas. Historial conservado.`;
      }catch(error){fail(error);}
      finally{busy=false;if(current())lock(false);}
    });
  };
})();
