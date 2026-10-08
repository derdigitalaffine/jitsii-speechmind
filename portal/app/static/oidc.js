(() => {
  'use strict';
  const rows=document.querySelector('[data-oidc-maps]');
  document.querySelector('[data-oidc-add]')?.addEventListener('click',()=>{
    const fragment=document.querySelector('#oidc-map-template').content.cloneNode(true);
    rows.append(fragment);rows.lastElementChild.querySelector('input').focus();
  });
  rows?.addEventListener('click',event=>{const button=event.target.closest('[data-oidc-remove]');if(button)button.closest('[data-oidc-map]').remove();});
  document.querySelectorAll('[data-oidc-copy]').forEach(button=>button.addEventListener('click',async()=>{
    const field=document.getElementById(button.dataset.oidcCopy);
    try{await navigator.clipboard.writeText(field.value);button.textContent='Kopiert';}catch(_){field.focus();field.select();}
  }));
})();
