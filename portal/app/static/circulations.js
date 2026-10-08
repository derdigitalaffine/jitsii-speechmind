(() => {
  'use strict';
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => Array.from(root.querySelectorAll(s));
  const fold = value => String(value || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('de');
  const el = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; };
  const form = $('#cl-editor');
  const data = $('#cl-editor-data') ? JSON.parse($('#cl-editor-data').textContent) : {};
  let dirty = false, submitting = false;
  const changed = event => {
    // Searching and editor view controls do not change the saved draft.
    if (event && (!event.target.name || event.target.type === 'search')) return;
    dirty = true;
  };
  function saveError(message) {
    let error=$('#cl-save-error');
    if(!error){error=el('div','alert alert-danger');error.id='cl-save-error';error.tabIndex=-1;error.setAttribute('role','alert');form.prepend(error);}
    error.textContent=message;error.hidden=false;error.focus();
    return error;
  }
  if (form) {
    form.addEventListener('input', changed); form.addEventListener('change', changed);
    window.addEventListener('beforeunload', event => { if (dirty && !submitting) { event.preventDefault(); event.returnValue = ''; } });
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (!form.checkValidity()) {form.reportValidity();return;}
      const buttons=$$('button[type="submit"],button:not([type])',form);buttons.forEach(button=>button.disabled=true);
      const error=$('#cl-save-error');if(error)error.hidden=true;
      try {
        const response=await fetch(form.action,{method:'POST',body:new FormData(form)});
        if(response.ok && response.redirected){
          const expected=new URL(form.action).pathname.replace(/\/save$/, '/edit');
          if(new URL(response.url).pathname!==expected)throw new Error('Die Anmeldung oder Weiterleitung hat sich geändert. Ihre Eingaben bleiben erhalten; bitte die Anmeldung prüfen.');
          dirty=false;submitting=true;window.location.assign(response.url);return;
        }
        let message='Speichern fehlgeschlagen. Ihre Eingaben bleiben erhalten.';
        try{const json=await response.json();if(typeof json.detail==='string')message=json.detail;}catch(_){}
        throw new Error(message);
      } catch(problem){submitting=false;saveError(problem.message || 'Verbindung fehlgeschlagen. Bitte erneut speichern.');dirty=true;}
      finally{buttons.forEach(button=>button.disabled=false);}
    });
  }
  // Publishing and copying use the saved draft; never submit them with unsaved edits.
  $$('[data-cl-saved-action]').forEach(actionForm => actionForm.addEventListener('submit', event => {
    if(event.defaultPrevented || !actionForm.checkValidity()) return;
    if(dirty){event.preventDefault();saveError('Bitte zuerst den Entwurf speichern. Danach können Sie ihn veröffentlichen oder als Sammelmappe sichern.');return;}
    submitting=true;
  }));
  // Native checkbox/radio lists remain usable without JavaScript. Search never hides selections from submission.
  $$('.cl-picker').forEach(picker => {
    let limit = 40, kind = '';
    const rows = $$('[data-pick-row]', picker), search = $('[data-picker-search]', picker);
    function filter() {
      const query = fold(search?.value), matches = rows.filter(row => (!kind || row.dataset.kind === kind) && fold(row.dataset.search).includes(query));
      const visible = new Set(matches.slice(0, limit)); rows.forEach(row => { row.hidden = !visible.has(row); });
      $('[data-picker-count]', picker).textContent = matches.length ? `${matches.length} Treffer · ${Math.min(limit, matches.length)} angezeigt` : 'Keine Treffer';
      $('[data-picker-empty]', picker).hidden = matches.length !== 0;
      $('[data-picker-more]', picker).hidden = matches.length <= limit;
    }
    search?.addEventListener('input', () => { limit = 40; filter(); });
    $('[data-picker-more]', picker)?.addEventListener('click', () => { limit += 40; filter(); });
    $$('[data-picker-filter]', picker).forEach(button => button.addEventListener('click', () => {
      kind = button.dataset.pickerFilter; limit = 40;
      $$('[data-picker-filter]', picker).forEach(b => { const active = b === button; b.setAttribute('aria-pressed', String(active)); b.classList.toggle('btn-primary', active); b.classList.toggle('btn-outline-secondary', !active); }); filter();
    }));
    filter();
  });
  function action(label, icon, callback, disabled = false) {
    const button = el('button', 'btn btn-sm btn-outline-secondary'); button.type = 'button'; button.title = label; button.setAttribute('aria-label', label); button.disabled = disabled;
    const i = el('i', 'fa-solid ' + icon); i.setAttribute('aria-hidden', 'true'); button.append(i); button.addEventListener('click', callback); return button;
  }
  function refocus(container, ref, actionName) {
    const row = Array.from(container.children).find(n => n.dataset.ref === ref);
    const preferred=row?.querySelector(`[data-action="${actionName}"]`);
    (preferred && !preferred.disabled ? preferred : row?.querySelector('button:not(:disabled)'))?.focus();
  }
  // Selection order is explicit, including keyboard and touch controls for sequential recipients.
  const selected = {};
  ['users', 'groups'].forEach(name => {
    const picker = $(`[data-picker="${name}"]`), list = $(`[data-selected-list="${name}"]`);
    if (!picker || !list) return;
    const boxes = $$('input[type="checkbox"]', picker), map = new Map(boxes.map(box => [box.value, box]));
    selected[name] = (data[name] || []).map(String);
    boxes.forEach(box => { box.removeAttribute('name'); });
    function render() {
      list.replaceChildren();
      selected[name].forEach((value, index) => {
        const box = map.get(value), title = box?.dataset.pickTitle || `Nicht mehr verfügbar (#${value})`, card = el('div', 'cl-selected-person'); card.dataset.ref = value;
        const label = el('span', 'cl-selected-title'); label.append(el('strong', '', title)); if (box?.dataset.pickDetail) label.append(el('small', '', box.dataset.pickDetail)); card.append(label);
        const hidden = el('input'); hidden.type = 'hidden'; hidden.name = name; hidden.value = value; card.append(hidden);
        if (name === 'users') [-1, 1].forEach(delta => {
          const key = delta < 0 ? 'up' : 'down', button = action(`${title} ${delta < 0 ? 'nach oben' : 'nach unten'}`, delta < 0 ? 'fa-arrow-up' : 'fa-arrow-down', () => {
            const target = index + delta; [selected[name][index], selected[name][target]] = [selected[name][target], selected[name][index]]; changed(); render(); summary(); refocus(list, value, key);
          }, index + delta < 0 || index + delta >= selected[name].length); button.dataset.action = key; card.append(button);
        });
        card.append(action(`${title} entfernen`, 'fa-xmark', () => { selected[name] = selected[name].filter(v => v !== value); if (box) box.checked = false; changed(); render(); summary(); $('[data-picker-search]', picker)?.focus(); })); list.append(card);
      });
      $(`[data-selected-count="${name}"]`).textContent = selected[name].length;
    }
    boxes.forEach(box => box.addEventListener('change', () => {
      selected[name] = selected[name].filter(v => v !== box.value); if (box.checked) selected[name].push(box.value); changed(); render(); summary();
    })); render();
  });
  const documents = $('#cl-documents'), status = $('#cl-editor-status');
  let entries = (data.items || []).map(item => ({ref:'item:'+item.key, item, existing:true}));
  const removed = new Set();
  let uploads = [];
  const input = $('#files');
  let canTransfer = false;
  try { if (input) { input.files = new DataTransfer().files; canTransfer = true; } } catch (_) { /* Native file input still works. */ }
  const sequence = form && documents ? el('input') : null;
  if (sequence) { sequence.type = 'hidden'; sequence.name = 'item_sequence'; form.append(sequence); }
  const removalFields = el('div'); if (form && documents) form.append(removalFields);
  function announce(message) { if (status) status.textContent = message; }
  function reconcile() {
    const objects=$$('[data-object-ref]:checked:not(:disabled)').map(box=>({ref:box.dataset.objectRef,item:{title:box.dataset.pickTitle,kind:box.dataset.objectRef.split(':')[0],id:Number(box.value)},box}));
    const bundles=$$('[data-bundle-id]:checked').map(box=>({id:box.value,bundle:data.bundles[box.value],box}));
    const md=$('[name="new_markdown_body"]');
    entries=window.CirculationEditorState.reconcileDocuments(entries,{objects,bundles,uploads,markdown:md?.value.trim()?{title:$('[name="new_markdown_title"]').value}:null});
    renderDocuments();
  }
  function renderDocuments() {
    if (!documents) return;
    documents.replaceChildren(); removalFields.replaceChildren();
    removed.forEach(key => { const field = el('input'); field.type = 'hidden'; field.name = 'remove_item'; field.value = key; removalFields.append(field); });
    entries.forEach((entry,index) => {
      const item = entry.item, card = el('li', 'cl-selected-card'); card.dataset.ref = entry.ref;
      const icon = el('div','cl-doc-icon'); icon.append(el('i', 'fa-solid '+(item.mime==='application/pdf'?'fa-file-pdf':item.kind==='markdown'?'fa-file-lines':item.kind==='file'?'fa-file':'fa-link'))); card.append(icon);
      const title = el('span','cl-selected-title'); title.append(el('strong','',item.title));
      const kinds = {law:'Rechtstext',form:'Formular',dms:'DMS-Dokument',file:'Datei',markdown:'Markdown'};
      title.append(el('small','', [kinds[item.kind] || item.kind, item.bundle_title ? 'aus „'+item.bundle_title+'“' : '', entry.existing?'Gespeichert':'Wird beim Speichern hinzugefügt'].filter(Boolean).join(' · '))); card.append(title);
      const controls = el('div','cl-card-controls');
      [-1,1].forEach(delta => {
        const key = delta < 0 ? 'up' : 'down', button = action(`${item.title} ${delta < 0?'nach oben':'nach unten'}`,delta < 0?'fa-arrow-up':'fa-arrow-down', () => {
          const target = index+delta; [entries[index],entries[target]]=[entries[target],entries[index]]; changed(); renderDocuments(); refocus(documents,entry.ref,key);
        }, index+delta<0 || index+delta>=entries.length); button.dataset.action = key; controls.append(button);
      });
      const removeLabel = entry.bundle ? 'Gesamte Mappe abwählen; einzelne Dokumente nach dem Speichern bearbeiten' : `${item.title} entfernen`;
      controls.append(action(removeLabel,'fa-xmark', () => {
        if (entry.existing) {
          removed.add(item.key); entries=entries.filter(e => e!==entry);
          const box=$$('[data-object-ref]').find(b => b.dataset.objectRef===item.kind+':'+item.id); if (box) {box.disabled=false;box.checked=false;}
        } else if (entry.box) entry.box.checked=false;
        else if (entry.upload !== undefined) {
          if (!canTransfer) {announce('Bitte Dateien erneut auswählen, um die Auswahl zu ändern.'); return;}
          uploads.splice(entry.upload,1); syncFiles(); entries=entries.filter(e => e.upload===undefined);
        } else if (entry.ref==='markdown:new') { $('[name="new_markdown_body"]').value=''; $('[name="new_markdown_body"]').dispatchEvent(new Event('input',{bubbles:true})); }
        changed(); reconcile(); announce(entry.bundle?'Mappe abgewählt.':'Dokument entfernt.'); $('#search-bundles')?.focus();
      },entry.upload!==undefined && !canTransfer)); card.append(controls); documents.append(card);
    });
    sequence.value = JSON.stringify(entries.map(e=>e.ref));
    if(input){const invalid=uploads.some(file=>file.size>25*1024*1024 || (file.name.toLowerCase().endsWith('.md') && file.size>100000));input.setCustomValidity(invalid?'Dateien dürfen höchstens 25 MB, Markdown 100 kB groß sein.':'');if(invalid)announce('Eine Datei ist zu groß: maximal 25 MB, Markdown maximal 100 kB.');}
    $('#cl-documents-empty').hidden = entries.length !== 0;
    $('#cl-document-count').textContent = entries.length;
    const tooMany=entries.length>100; if (tooMany) announce('Maximal 100 Dokumente: Bitte die Auswahl verkleinern.');
    const titleInput=$('#title'); titleInput?.setCustomValidity(tooMany?'Maximal 100 Dokumente pro Mappe.':''); summary();
  }
  function syncFiles() { const transfer=new DataTransfer(); uploads.forEach(file=>transfer.items.add(file)); input.files=transfer.files; }
  input?.addEventListener('change', () => {
    const incoming=Array.from(input.files);
    uploads=canTransfer ? uploads.concat(incoming) : incoming;
    if (canTransfer) syncFiles();
    reconcile(); announce(`${incoming.length} Datei(en) zur Auswahl hinzugefügt.`);
  });
  const dropzone=$('#cl-dropzone');
  if (dropzone && canTransfer) {
    dropzone.addEventListener('dragover',event=>{event.preventDefault();dropzone.classList.add('cl-dragover');});
    dropzone.addEventListener('dragleave',()=>dropzone.classList.remove('cl-dragover'));
    dropzone.addEventListener('drop',event=>{event.preventDefault();dropzone.classList.remove('cl-dragover');uploads.push(...Array.from(event.dataTransfer.files));syncFiles();changed();reconcile();});
  }
  $$('[data-object-ref],[data-bundle-id]').forEach(box=>box.addEventListener('change',()=>{reconcile();announce(box.checked?'Inhalt zur Mappe hinzugefügt.':'Auswahl entfernt.');}));
  $$('[name="new_markdown_title"],[name="new_markdown_body"]').forEach(node=>node.addEventListener('input',reconcile));
  if (documents) {reconcile();if($$('[data-bundle-id]:checked').length)dirty=true;}
  function summary() {
    const title=$('#cl-summary-title'); if(title)title.textContent=$('#title')?.value || 'Noch ohne Titel';
    const doc=$('#cl-summary-documents');if(doc)doc.textContent=entries.length+' Dokumente'+($('#cl-audience')?' + Einleitung':'');
    const mode=$('[name="mode"]:checked')?.value;
    if($('#cl-summary-mode'))$('#cl-summary-mode').textContent=({info:'Information',ack:'Kenntnisnahme',approval:'Freigabe'})[mode] || '';
    const actionOptions=$('[data-action-options]');if(actionOptions)actionOptions.hidden=mode==='info';
    const audience=$('#cl-summary-audience');
    if(audience){
      const ids=new Set((selected.users || []).map(Number));(selected.groups || []).forEach(g=>(data.group_members[g] || []).forEach(id=>ids.add(id)));
      const count=$('#cl-all-users').checked ? data.user_count : ids.size;
      const guests=new Set(($('[name="guests"]').value || '').split('\n').map(line=>line.trim().split(';').pop().trim().toLowerCase()).filter(Boolean));
      audience.textContent=`${count} Portalpersonen${guests.size?' + '+guests.size+' Gäste':''}`;
      if($('[name="distributor"]:checked')?.value)audience.textContent+=' + gespeicherter Verteiler';
    }
    const warning=$('#cl-compatibility');if(!warning)return;
    const messages=[];
    if($('[name="public"]').checked && (mode!=='info' || entries.some(e=>e.item.kind==='dms' || ['law','form'].includes(e.item.kind)) || $('[name="guests"]').value.trim()))messages.push('Öffentliche Aushänge erlauben nur Information, öffentliche Portalobjekte und keine Gastempfänger. Die Veröffentlichung prüft die Auswahl.');
    if($('[name="sequential"]').checked && $('[name="dynamic"]').checked)messages.push('Bei Stationsfolgen werden neue Gruppenmitglieder nicht automatisch aufgenommen.');
    warning.hidden=!messages.length;warning.textContent=messages.join(' ');
  }
  form?.addEventListener('input',summary);form?.addEventListener('change',summary);summary();
  $$('[name="kind"]').forEach(radio=>radio.addEventListener('change',()=>{
    const mode=$(`[name="mode"][value="${radio.value==='circulation'?'ack':'info'}"]`);if(mode){mode.checked=true;summary();}
  }));
  // Markdown editor: safe server rendering, debounced live preview, formatting and shortcuts.
  $$('[data-markdown-editor]').forEach(editor=>{
    const textarea=$('[data-md-input]',editor),preview=$('[data-md-preview]',editor),panes=$('.cl-md-panes',editor),link=$('[data-md-link]',editor);
    let view='edit',timer,controller,requestId=0,range;
    function words(){const value=textarea.value.trim();$('[data-md-wordcount]',editor).textContent=(value?value.split(/\s+/).length:0)+' Wörter · '+textarea.value.length+' Zeichen';}
    async function refreshPreview(){
      const id=++requestId;controller?.abort();controller=new AbortController();preview.setAttribute('aria-busy','true');
      try{const body=new FormData();body.set('body',textarea.value);body.set('csrf',$('meta[name="csrf"]').content);
        const response=await fetch('/umlaeufe/preview',{method:'POST',body,signal:controller.signal});if(!response.ok)throw new Error();const html=await response.text();if(id===requestId)preview.innerHTML=html || '<p class="text-secondary">Ihre Textvorschau erscheint hier.</p>';
      }catch(error){if(error.name!=='AbortError' && id===requestId)preview.textContent='Vorschau konnte nicht geladen werden. Schreiben und Speichern sind weiterhin möglich.';}
      finally{if(id===requestId)preview.setAttribute('aria-busy','false');}
    }
    function update(){words();if(view!=='edit'){clearTimeout(timer);timer=setTimeout(refreshPreview,450);}}
    function insert(action){
      const start=textarea.selectionStart,end=textarea.selectionEnd,value=textarea.value.slice(start,end);let replacement;
      if(action==='link'){range={start,end};$('[data-md-link-text]',editor).value=value || '';$('[data-md-link-url]',editor).value='';link.hidden=false;$('[data-md-link-text]',editor).focus();return;}
      const wraps={bold:['**','**'],italic:['*','*'],code:['`','`']};
      if(wraps[action])replacement=wraps[action][0]+(value || 'Text')+wraps[action][1];
      else if(action==='table')replacement='\n| Spalte 1 | Spalte 2 |\n| --- | --- |\n| Inhalt | Inhalt |\n';
      else {const marks={heading:'## ',list:'- ',numbered:'1. ',quote:'> '};const lineStart=textarea.value.lastIndexOf('\n',start-1)+1;const lineEnd=end===start?textarea.value.indexOf('\n',end):end;const stop=lineEnd<0?textarea.value.length:lineEnd;const lines=textarea.value.slice(lineStart,stop);textarea.setRangeText(lines.split('\n').map((line,index)=>(action==='numbered'?(index+1)+'. ':marks[action])+line).join('\n'),lineStart,stop,'select');textarea.focus();textarea.dispatchEvent(new Event('input',{bubbles:true}));return;}
      textarea.setRangeText(replacement,start,end,'select');textarea.focus();textarea.dispatchEvent(new Event('input',{bubbles:true}));
    }
    $$('[data-md-action]',editor).forEach(button=>button.addEventListener('click',()=>insert(button.dataset.mdAction)));
    $$('[data-md-view]',editor).forEach(button=>button.addEventListener('click',()=>{
      view=button.dataset.mdView;preview.hidden=view==='edit';textarea.hidden=view==='preview';panes.classList.toggle('cl-md-split',view==='split');
      $$('[data-md-view]',editor).forEach(b=>{const active=b===button;b.setAttribute('aria-pressed',String(active));b.classList.toggle('btn-primary',active);b.classList.toggle('btn-outline-primary',!active);});
      if(view!=='edit')refreshPreview();else textarea.focus();
    }));
    $('[data-md-link-cancel]',editor).addEventListener('click',()=>{link.hidden=true;textarea.focus();});
    $('[data-md-link-insert]',editor).addEventListener('click',()=>{
      const url=$('[data-md-link-url]',editor).value.trim(),text=$('[data-md-link-text]',editor).value.trim() || url;let valid=false;
      try{valid=['http:','https:'].includes(new URL(url).protocol);}catch(_){}
      $('[data-md-link-error]',editor).hidden=valid;if(!valid)return;
      const safeText=text.replace(/([\\\[\]])/g,'\\$1'),safeUrl=url.replace(/\(/g,'%28').replace(/\)/g,'%29');textarea.setRangeText(`[${safeText}](${safeUrl})`,range.start,range.end,'select');link.hidden=true;textarea.focus();textarea.dispatchEvent(new Event('input',{bubbles:true}));
    });
    textarea.addEventListener('keydown',event=>{if((event.ctrlKey || event.metaKey) && ['b','i'].includes(event.key.toLowerCase())){event.preventDefault();insert(event.key.toLowerCase()==='b'?'bold':'italic');}});
    textarea.addEventListener('input',update);words();
  });
})();
