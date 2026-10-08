(() => {
  'use strict';
  const search=document.querySelector('[data-sem-bundle-search]');
  if(search)search.addEventListener('input',()=>{const value=search.value.trim().toLocaleLowerCase('de');document.querySelectorAll('[data-sem-bundle-name]').forEach(item=>item.hidden=!item.dataset.semBundleName.includes(value));});
  const settings=document.querySelector('#sem-settings');
  if(!settings)return;
  let dirty=false,navigating=false,saving=false,generation=0;
  const changed=()=>{dirty=true;++generation;};
  settings.addEventListener('input',changed);settings.addEventListener('change',changed);
  function message(text,error=false){
    let box=document.querySelector('#sem-save-message');
    if(!box){box=document.createElement('div');box.id='sem-save-message';box.tabIndex=-1;box.setAttribute('role','status');settings.prepend(box);}
    box.className='alert '+(error?'alert-danger':'alert-success');box.textContent=text;
    if(error)box.focus();
  }
  async function save(action){
    const snapshot=generation;
    const data=new FormData(settings);data.set('save_action',action);
    const response=await fetch(settings.action,{method:'POST',body:data,headers:{Accept:'application/json'},credentials:'same-origin'});
    if(!response.ok){let error='Speichern fehlgeschlagen. Ihre Eingaben bleiben erhalten.';try{const body=await response.json();if(typeof body.detail==='string')error=body.detail;}catch(_){}throw new Error(error);}
    const result=await response.json();settings.querySelector('[name=revision]').value=result.revision;dirty=generation!==snapshot;message(dirty?'Seminar gespeichert. Neuere Eingaben sind noch nicht gespeichert.':'Seminar gespeichert.');return result;
  }
  window.addEventListener('beforeunload',event=>{if(dirty&&!navigating){event.preventDefault();event.returnValue='';}});
  document.addEventListener('submit',async event=>{
    const form=event.target;if(event.defaultPrevented||!(form instanceof HTMLFormElement))return;
    if(form!==settings&&!dirty){navigating=true;return;}
    event.preventDefault();if(saving)return;saving=true;
    try{
      if(!settings.reportValidity())return;
      const result=await save(form===settings?(event.submitter?.value||'save'):'save');
      if(dirty)throw new Error('Eingaben wurden während des Speicherns geändert. Bitte erneut speichern.');
      if(form===settings){if(result.redirect){navigating=true;location.assign(result.redirect);}}
      else {navigating=true;form.requestSubmit(event.submitter);}
    }catch(error){message(error.message,true);navigating=false;}
    finally{saving=false;}
  });
})();
