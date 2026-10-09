/* Public parcel information, reusable in the map browser and form geography fields. */
(function(){'use strict';
  function create(map, host, options){
    options=options||{};var active=null,browserMode=!!options.browserMode,lookupAbort=null,lookupSeq=0,boundaries=true,numbers=true;var esc=MapKit.esc,selected=(options.initial||[]).slice(0,50),results=[],abort=null,seq=0,id='parcel-'+Math.random().toString(36).slice(2),max=options.max||50,numberLabels=browserMode?MapKit.parcelLabels(map):null;
    host.innerHTML='<details class="parcel-search" open><summary class="fw-semibold">Flurstücke suchen</summary><div class="mt-2" data-parcel-search><label class="form-label small">Gemarkung<input name="gemarkung" class="form-control form-control-sm" placeholder="Zum Beispiel Otterbach"></label><div class="d-flex gap-2">'+['flur','zaehler','nenner'].map(function(k){return '<label class="form-label small flex-fill">'+({flur:'Flur',zaehler:'Zähler',nenner:'Nenner'}[k])+'<input class="form-control form-control-sm" name="'+k+'" inputmode="numeric" pattern="[0-9]{1,5}"></label>';}).join('')+'</div><details><summary class="small">Vollständiges Kennzeichen</summary><input name="kennzeichen" class="form-control form-control-sm mt-2" aria-label="Flurstückskennzeichen"></details><button type="button" class="btn btn-sm btn-primary mt-2" data-parcel-search-button>Flurstücke suchen</button></div><label class="d-flex gap-2 small mt-3"><input type="checkbox" class="form-check-input" data-parcel-click checked>Flurstücksauskunft beim Kartenklick</label></details><p class="small mt-2" data-parcel-status role="status"></p><div data-parcel-results></div><details class="parcel-selection mt-3" open><summary>Ausgewählte Flurstücke <span data-parcel-count>0</span></summary><div data-parcel-selected></div><div class="d-flex flex-wrap gap-2 mt-2"><button type="button" class="btn btn-sm btn-outline-secondary" data-parcel-export="csv">CSV</button><button type="button" class="btn btn-sm btn-outline-secondary" data-parcel-export="json">JSON</button><button type="button" class="btn btn-sm btn-outline-secondary" data-parcel-export="print">Drucken / PDF</button></div></details><p class="small text-secondary mt-3">Öffentliche ALKIS-Auskunft ohne Eigentümerdaten. Amtliche Fläche und gemessene Fläche können abweichen. ©GeoBasis-DE / LVermGeoRP, dl-de/by-2-0.</p>';
    var status=host.querySelector('[data-parcel-status]'),form=host.querySelector('[data-parcel-search]');
    function modeActive(){if(!browserMode)return true;var node=host.querySelector('.parcel-search');while(node){if(node.tagName==='DETAILS'&&!node.open)return false;node=node.parentElement;}return true;}
    function key(f){return String(f.id||f.properties.flstkennz);}
    function title(f){var p=f.properties||{};return (p.gemarkung||'Flurstück')+' · '+(p.flur||'')+' · '+(p.flstnrzae||'')+(p.flstnrnen&&String(p.flstnrnen)!=='0'?'/'+p.flstnrnen:'');}
    function highlight(){
      if(!map.isStyleLoaded())return;
      var features=selected.map(function(f){return Object.assign({},f,{properties:Object.assign({},f.properties,{_active:active&&key(f)===key(active)?1:0})});});
      if(active&&!selected.some(function(f){return key(f)===key(active);}))features.push(Object.assign({},active,{properties:Object.assign({},active.properties,{_active:1})}));
      var data={type:'FeatureCollection',features:features};
      if(map.getSource(id))map.getSource(id).setData(data);else{
        map.addSource(id,{type:'geojson',data:data});
        map.addLayer({id:id+'-fill',type:'fill',source:id,paint:{'fill-color':['case',['==',['get','_active'],1],'#1565c0','#e85d04'],'fill-opacity':browserMode?['case',['==',['get','_active'],1],.12,.08]:.25}});
        map.addLayer({id:id+'-line',type:'line',source:id,paint:{'line-color':['case',['==',['get','_active'],1],'#1565c0','#e85d04'],'line-width':browserMode?['case',['==',['get','_active'],1],3,1.5]:3}});

      }
      map.setLayoutProperty(id+'-line','visibility',boundaries?'visible':'none');
      if(numberLabels)numberLabels.update(features,numbers);
    }
    function activeInfo(f){
      active=f||null;highlight();
      if(options.onActive)options.onActive(active);
      if(!options.infoHost)return;
      var info=options.infoHost;
      if(!f){info.replaceChildren();return;}
      var p=f.properties||{},fields={gemarkung:'Gemarkung',flur:'Flur',flstnrzae:'Nummer',flaeche:'Amtliche Fläche',lagebeztxt:'Lage'},more={gemeinde:'Gemeinde',flstkennz:'Kennzeichen',tntxt:'Nutzung',aktualit:'Datenstand'};
      function rows(labels){return Object.keys(labels).filter(function(k){return p[k]!=null&&p[k]!=='';}).map(function(k){var value=p[k];if(k==='flaeche')value=Number(value).toLocaleString('de-DE')+' m²';if(k==='flstnrzae'&&p.flstnrnen&&String(p.flstnrnen)!=='0')value+='/'+p.flstnrnen;return '<dt>'+esc(labels[k])+'</dt><dd>'+esc(value)+'</dd>';}).join('');}
      info.innerHTML='<h3 class="h6 mt-3">'+esc(title(f))+'</h3><dl>'+rows(fields)+'</dl><div class="d-flex flex-wrap gap-2"><button type="button" class="btn btn-sm btn-primary" data-active-add><i class="fa-solid fa-plus me-1"></i>Zur Sammlung hinzufügen</button><button type="button" class="btn btn-sm btn-outline-secondary" data-active-zoom><i class="fa-solid fa-magnifying-glass-location me-1"></i>Hinzoomen</button></div><details><summary>Weitere Angaben und Quelle</summary><dl class="mt-2">'+rows(more)+'</dl><p class="small text-secondary mb-0">'+esc(f.attribution||'Öffentliche ALKIS-Auskunft ohne Eigentümerdaten')+'<br>Abruf: '+esc(f.retrieved_at?new Date(f.retrieved_at).toLocaleString('de-DE'):'nicht verfügbar')+'</p></details>';
      info.querySelector('[data-active-add]').addEventListener('click',function(){add(f);});info.querySelector('[data-active-zoom]').addEventListener('click',function(){zoom(f);});
    }
    function add(f){
      if(!f)return;if(selected.some(function(x){return key(x)===key(f);})){status.textContent='Dieses Flurstück ist bereits in Ihrer Sammlung.';return;}
      if(selected.length>=max){status.textContent='Maximal '+max+' Flurstücke auswählen.';return;}
      if(options.validateSelection&&!options.validateSelection(selected.concat([f]))){status.textContent='Diese Auswahl überschreitet die erlaubte Zahl oder Größe der Teilflächen. Auswahl reduzieren.';return;}
      selected.push(f);render();if(!browserMode)zoom(f);status.textContent='Flurstück zur Sammlung hinzugefügt.';
    }
    function zoom(f){var points=[];function collect(c){if(typeof c[0]==='number')points.push(c);else c.forEach(collect);}if(!f.geometry)return;collect(f.geometry.coordinates);if(!points.length)return;var b=new maplibregl.LngLatBounds();points.forEach(function(p){b.extend(p);});map.fitBounds(b,{padding:45,maxZoom:19});}
    function render(){host.querySelector('[data-parcel-count]').textContent=selected.length;host.querySelector('[data-parcel-selected]').innerHTML=selected.map(function(f,i){return '<div class="parcel-selected"><button type="button" class="btn btn-sm btn-link text-start" data-parcel-zoom="'+i+'">'+esc(title(f))+'</button><button type="button" class="btn btn-sm btn-outline-danger" data-parcel-remove="'+i+'" aria-label="'+esc(title(f))+' entfernen">Entfernen</button><div class="small">Amtliche Fläche: '+esc(f.properties.flaeche==null?'Nicht verfügbar':f.properties.flaeche+' m²')+' · '+esc(f.properties.flstkennz)+'</div><div class="small text-secondary">Abruf: '+esc(new Date(f.retrieved_at).toLocaleString('de-DE'))+'</div></div>';}).join('');highlight();if(options.onChange)options.onChange(selected.slice());}
    function query(params,fit){
      if(abort)abort.abort();abort=new AbortController();var revision=++seq;
      status.textContent='Amtliche Flurstücksdaten werden geladen …';
      if(browserMode)activeInfo(null);
      fetch('/map/parcels?'+new URLSearchParams(params),{signal:abort.signal,headers:{Accept:'application/json'}}).then(function(r){return r.json().then(function(d){if(!r.ok)throw new Error(d.detail||'Auskunft fehlgeschlagen');return d;});}).then(function(d){
        if(revision!==seq)return;results=d.features||[];
        status.textContent=results.length?results.length+' Flurstück'+(results.length===1?'':'e')+' gefunden.'+(d.truncated?' Weitere Treffer vorhanden; Suche genauer eingrenzen.':''):'Keine passenden Flurstücke gefunden. Eingabe prüfen oder auf eine Fläche klicken.';
        host.querySelector('[data-parcel-results]').innerHTML=results.map(function(f,i){var p=f.properties;
          if(browserMode)return '<article class="parcel-result"><h3 class="h6">'+esc(title(f))+'</h3><p class="small mb-2">'+esc(p.flaeche==null?'Fläche nicht verfügbar':Number(p.flaeche).toLocaleString('de-DE')+' m²')+(p.lagebeztxt?' · '+esc(p.lagebeztxt):'')+'</p><button type="button" class="btn btn-sm btn-outline-primary" data-parcel-view="'+i+'">Anzeigen</button></article>';
          return '<article class="parcel-result"><h3 class="h6">'+esc(title(f))+'</h3><dl class="small">'+Object.keys(d.fields).filter(function(k){return p[k]!=null&&p[k]!=='';}).map(function(k){return '<dt>'+esc(d.fields[k])+'</dt><dd>'+esc(p[k])+'</dd>';}).join('')+'</dl><button type="button" class="btn btn-sm btn-outline-primary" data-parcel-add="'+i+'">Auswählen und markieren</button></article>';
        }).join('');
        if(browserMode&&results.length){activeInfo(results[0]);if(options.show)options.show();}
        if(fit&&results.length)zoom(results[0]);
      }).catch(function(e){if(e.name!=='AbortError'&&revision===seq){status.textContent=e.message;host.querySelector('[data-parcel-results]').replaceChildren();}});
    }
    function search(){var params={};if(browserMode)params.scope=host.querySelector('[data-parcel-scope]').value;form.querySelectorAll('input[name]').forEach(function(input){params[input.name]=input.value;});query(params,true);}form.querySelector('[data-parcel-search-button]').addEventListener('click',search);form.addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();search();}});
    map.on('click',function(e){if(browserMode&&!modeActive()||!host.querySelector('[data-parcel-click]').checked||options.isDrawing&&options.isDrawing())return;if(e.lngLat.lng<5.5||e.lngLat.lng>9||e.lngLat.lat<48.5||e.lngLat.lat>51.5)return;query({lon:e.lngLat.lng,lat:e.lngLat.lat},false);if(options.show)options.show();});
    host.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;if(b.hasAttribute('data-parcel-view')){activeInfo(results[Number(b.dataset.parcelView)]);if(options.show)options.show();}if(b.hasAttribute('data-parcel-add'))add(results[Number(b.dataset.parcelAdd)]);if(b.hasAttribute('data-parcel-remove')){selected.splice(Number(b.dataset.parcelRemove),1);render();}if(b.hasAttribute('data-parcel-zoom'))zoom(selected[Number(b.dataset.parcelZoom)]);if(b.dataset.parcelExport)exportSelection(b.dataset.parcelExport);});
    function exportSelection(format){if(!selected.length){status.textContent='Zuerst Flurstücke auswählen.';return;}if(format==='print'){var w=window.open('','_blank');if(!w){status.textContent='Bitte das Druckfenster im Browser erlauben.';return;}var image='';try{image=map.getCanvas().toDataURL('image/png');}catch(e){}w.document.write('<!doctype html><html lang="de"><title>Flurstücksauskunft</title><style>body{font:14px system-ui;margin:20px}img{max-width:100%}article{break-inside:avoid;border-bottom:1px solid #ccc;padding:12px 0}@media print{button{display:none}}</style><button onclick="window.print()">Drucken / als PDF speichern</button><h1>Flurstücksauskunft</h1>'+(image?'<img alt="Kartenausschnitt" src="'+image+'">':'<p>Kartenbild konnte nicht exportiert werden. Bitte die Quelle über den Kartenproxy laden.</p>')+selected.map(function(f){return '<article><h2>'+esc(title(f))+'</h2><p>Kennzeichen: '+esc(f.properties.flstkennz)+' · Amtliche Fläche: '+esc(f.properties.flaeche)+' m²</p><p>Quelle: '+esc(f.source)+' · Abruf: '+esc(f.retrieved_at)+'</p></article>';}).join('')+'<p>©GeoBasis-DE / LVermGeoRP, dl-de/by-2-0. Informationsausgabe des Portals, kein amtlich beglaubigter Auszug. Orange markierte Flächen: ausgewählte Flurstücke. Kartenausschnitt dient der Orientierung; nicht maßstäblich drucken.</p></html>');w.document.close();return;}
      var text,mime;if(format==='json'){text=JSON.stringify({source:'Öffentliche ALKIS-Daten RP',features:selected},null,2);mime='application/json';}else{var cols=['gemarkung','flur','flstnrzae','flstnrnen','flstkennz','flaeche','lagebeztxt','tntxt','aktualit','source','retrieved_at'];function cell(v){var s=String(v==null?'':v);if(/^[=+@\-\t\r]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';}text='\ufeff'+cols.map(cell).join(';')+'\r\n'+selected.map(function(f){return cols.map(function(k){return cell(f.properties[k]==null?f[k]:f.properties[k]);}).join(';');}).join('\r\n');mime='text/csv;charset=utf-8';}var a=document.createElement('a'),u=URL.createObjectURL(new Blob([text],{type:mime}));a.href=u;a.download='flurstuecke.'+format;a.click();setTimeout(function(){URL.revokeObjectURL(u);},1000);}
    if(browserMode){
      var details=host.querySelector('.parcel-search');details.open=false;
      var after=[];for(var node=details.nextSibling;node;node=node.nextSibling)after.push(node);after.forEach(function(node){details.append(node);});
      var outer=host.closest('.map-tools');if(outer)outer.addEventListener('toggle',function(){if(!outer.open){seq++;if(abort)abort.abort();activeInfo(null);}});
      details.querySelector('summary').innerHTML='<i class="fa-solid fa-vector-square me-1"></i>Flurstücke';
      host.querySelector('[data-parcel-click]').closest('label').hidden=true;
      form.insertAdjacentHTML('afterbegin','<label class="form-label small">Suchgebiet<select class="form-select form-select-sm" data-parcel-scope><option value="preferred">Bevorzugtes Gebiet</option><option value="rlp">Ganz Rheinland-Pfalz</option></select></label><p class="parcel-guidance" data-lookup-status>Gemarkung eingeben, dann Flur und Nummer eingrenzen. Alternativ oben nach Ort oder Adresse suchen und auf ein Flurstück klicken.</p>');
      var gemark=form.querySelector('[name="gemarkung"]'),flur=form.querySelector('[name="flur"]'),num=form.querySelector('[name="zaehler"]'),scope=form.querySelector('[data-parcel-scope]');
      [gemark,flur,num].forEach(function(input,i){var list=document.createElement('datalist');list.id=id+'-suggest-'+i;input.setAttribute('list',list.id);input.autocomplete='off';form.append(list);});
      function guides(){flur.disabled=gemark.value.trim().length<2;num.disabled=flur.disabled;form.querySelector('[name="nenner"]').disabled=flur.disabled;}
      function lookups(){
        guides();if(lookupAbort)lookupAbort.abort();lookupAbort=new AbortController();var rev=++lookupSeq,params={scope:scope.value,gemarkung:gemark.value.trim(),flur:flur.value.trim(),zaehler:num.value.trim()};
        if(scope.value==='rlp'&&params.gemarkung.length<2)return;
        fetch('/map/parcels/options?'+new URLSearchParams(params),{signal:lookupAbort.signal}).then(function(r){return r.json().then(function(d){if(!r.ok)throw new Error(d.detail||'Vorschläge derzeit nicht verfügbar');return d;});}).then(function(d){if(rev!==lookupSeq)return;
          scope.options[0].textContent=d.preferred_label||'Bevorzugtes Gebiet';
          [d.gemarkungen||[],d.fluren||[],d.nummern||[]].forEach(function(values,i){var list=form.querySelector('#'+id+'-suggest-'+i);list.replaceChildren();values.forEach(function(v){var option=document.createElement('option');option.value=typeof v==='string'?v:i===0?v.name:i===2?v.label:v.name;option.label=typeof v==='string'?v:v.label||v.name||'';list.append(option);});});
          form.querySelector('[data-lookup-status]').textContent=d.message||(d.complete?'Vorschläge geladen. Freie Eingabe bleibt möglich.':'Vorschläge sind unvollständig. Bitte die Suche eingrenzen; freie Eingabe bleibt möglich.');
        }).catch(function(e){if(e.name!=='AbortError'&&rev===lookupSeq)form.querySelector('[data-lookup-status]').textContent=e.message+' · Freie Eingabe und Kartenklick bleiben möglich.';});
      }
      var timer;[gemark,flur,num].forEach(function(input){input.addEventListener('input',function(){if(input===num){var fraction=num.value.trim().match(/^(\d{1,5})\/(\d{1,5})$/);if(fraction){num.value=fraction[1];form.querySelector('[name="nenner"]').value=fraction[2];}}clearTimeout(timer);timer=setTimeout(lookups,450);});});scope.addEventListener('change',lookups);
      details.addEventListener('toggle',function(){if(details.open){lookups();if(options.onMode)options.onMode(true);}else{seq++;if(abort)abort.abort();activeInfo(null);if(options.onMode)options.onMode(false);}});
      details.insertAdjacentHTML('beforeend','<div class="d-flex flex-wrap gap-3 small mt-3"><label><input class="form-check-input me-1" type="checkbox" data-parcel-boundaries checked>Grenzen</label><label><input class="form-check-input me-1" type="checkbox" data-parcel-numbers checked>Nummern ab Vergrößerung 16</label></div><div class="parcel-presets mt-2"><button type="button" class="btn btn-sm btn-outline-secondary" data-parcel-preset>Flurstücksebene ergänzen</button></div>');
      host.querySelector('[data-parcel-boundaries]').addEventListener('change',function(e){boundaries=e.target.checked;highlight();if(options.onStyle)options.onStyle({boundaries:boundaries,numbers:numbers});});
      host.querySelector('[data-parcel-numbers]').addEventListener('change',function(e){numbers=e.target.checked;highlight();if(options.onStyle)options.onStyle({boundaries:boundaries,numbers:numbers});});
      host.querySelector('[data-parcel-preset]').addEventListener('click',function(){if(options.onPreset)options.onPreset();});guides();
    }
    map.on('load',render);map.on('style.load',highlight);render();return {features:function(){return selected.slice();},active:function(){return active;},activeMode:modeActive,clearActive:function(){activeInfo(null);},cancelInspect:function(){seq++;if(abort)abort.abort();activeInfo(null);},inspect:function(point){query({lon:point.lng,lat:point.lat},false);}};
  }
  window.MapParcels={create:create};
})();
