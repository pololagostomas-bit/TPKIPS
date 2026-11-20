/* Photograph transport only; the existing guide form owns signatures and saving. */
window.WmsGuidePhoto = (() => {
  let active = null;
  async function open(input, opener) {
    if (!input.isConnected || input.disabled || active) return;
    await window.WmsCamera?.close(false);
    if (!input.isConnected || active) return;
    const modal=document.createElement('dialog');modal.id='guidePhotoCamera';modal.className='dispatch-dialog guide-photo-camera';
    modal.setAttribute('aria-labelledby','guidePhotoTitle');
    modal.innerHTML='<h2 id="guidePhotoTitle">Foto de la guía firmada</h2><p role="status">Abriendo cámara…</p><p role="alert"></p><video autoplay playsinline muted aria-label="Vista de la cámara"></video><footer><button type="button" data-close-photo>Cancelar</button><button type="button" data-take-photo class="primary" disabled>Tomar foto</button></footer>';
    let stream=null;active=modal;document.body.append(modal);modal.showModal();
    const video=modal.querySelector('video'),take=modal.querySelector('[data-take-photo]');
    const close=()=>{stream?.getTracks().forEach(track=>track.stop());modal.close();};
    const hidden=()=>{if(document.hidden)close();};
    const observer=new MutationObserver(()=>{if(!input.isConnected)close();});
    observer.observe(document.body,{childList:true,subtree:true});
    document.addEventListener('visibilitychange',hidden);window.addEventListener('pagehide',close);
    modal.addEventListener('close',()=>{
      stream?.getTracks().forEach(track=>track.stop());observer.disconnect();
      document.removeEventListener('visibilitychange',hidden);window.removeEventListener('pagehide',close);
      if(active===modal)active=null;modal.remove();if(opener.isConnected)opener.focus();
    },{once:true});
    modal.querySelector('[data-close-photo]').onclick=close;
    modal.addEventListener('cancel',event=>{event.preventDefault();close();});
    video.onloadeddata=()=>{if(video.videoWidth&&video.videoHeight){take.disabled=false;modal.querySelector('[role=status]').textContent='Comprueba que se vean las dos firmas.';}};
    take.onclick=()=>{
      if(!input.isConnected||!video.videoWidth||!video.videoHeight)return;
      take.disabled=true;
      const canvas=document.createElement('canvas'),scale=Math.min(1,2048/Math.max(video.videoWidth,video.videoHeight));
      canvas.width=Math.round(video.videoWidth*scale);canvas.height=Math.round(video.videoHeight*scale);
      canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);
      canvas.toBlob(blob=>{
        if(!modal.open||!input.isConnected)return;
        if(!blob||blob.size>8*1024*1024){modal.querySelector('[role=alert]').textContent='No se pudo preparar la foto. Intenta otra vez o adjunta un archivo.';take.disabled=false;return;}
        const transfer=new DataTransfer();transfer.items.add(new File([blob],'guia-firmada.jpg',{type:'image/jpeg'}));
        input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}));close();
      },'image/jpeg',0.9);
    };
    try {
      if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia)throw Error('unsupported');
      stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:1920}},audio:false});
      if(!modal.open||!input.isConnected){stream.getTracks().forEach(track=>track.stop());return;}
      video.srcObject=stream;await video.play();
    } catch(error) {
      stream?.getTracks().forEach(track=>track.stop());
      if(!modal.open)return;
      modal.querySelector('[role=status]').textContent='Puedes cancelar y adjuntar una foto desde el formulario.';
      modal.querySelector('[role=alert]').textContent=error.name==='NotAllowedError'?'Falta permiso para usar la cámara.':'No se pudo abrir la cámara. Usa HTTPS y comprueba que el equipo tenga cámara.';
    }
  }
  function mount(root) {
    for(const input of root.querySelectorAll('[data-guide-photo]')) {
      if(input.dataset.guidePhotoReady)continue;input.dataset.guidePhotoReady='1';
      const label=input.closest('label'),button=document.createElement('button');
      button.type='button';button.dataset.guidePhotoCamera='';button.textContent='Tomar foto con cámara';
      button.className='guide-photo-button';button.onclick=()=>open(input,button);label.after(button);
      const preview=document.createElement('img');preview.className='delivery-photo-preview';preview.hidden=true;
      preview.alt='Foto de la guía: comprueba las firmas del receptor y del almacén';button.after(preview);
      const error=document.createElement('p');error.setAttribute('role','alert');error.className='dispatch-error';preview.after(error);
      input.addEventListener('change',()=>{
        const file=input.files?.[0];preview.hidden=true;preview.removeAttribute('src');error.textContent='';
        if(!file)return;
        if(file.size>8*1024*1024||!['image/jpeg','image/png','image/webp'].includes(file.type)){
          error.textContent='Elige una foto JPEG, PNG o WebP de hasta 8 MB.';return;
        }
        const reader=new FileReader();reader.onload=()=>{if(input.isConnected&&input.files?.[0]===file){preview.src=reader.result;preview.hidden=false;}};
        reader.onerror=()=>{error.textContent='No se pudo leer la foto. Elige otra vez el archivo.';};reader.readAsDataURL(file);
      });
    }
  }
  return {mount};
})();
