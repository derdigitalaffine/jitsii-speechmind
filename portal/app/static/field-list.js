/* Kompakter Feld-Editor für Nachforderungen (Vorgang, Prozesseditor, Vorlagen).
   FieldList.mount(container, {types, subtypes, items, onChange}) → {get(), set(items)} */
(function () {
  'use strict';
  var uid = function () { return Math.random().toString(16).slice(2, 10); };
  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  var CHOICE = { radio: 1, checkbox: 1, dropdown: 1 };

  function blank(type) {
    var it = { id: uid(), type: type, title: '', description: '', required: type !== 'text' };
    if (type === 'short') { it.subtype = 'text'; }
    if (CHOICE[type]) { it.options = [{ id: uid(), label: 'Ja' }, { id: uid(), label: 'Nein' }]; }
    if (type === 'file') { it.title = 'Unterlagen'; it.file_types = ['pdf', 'jpg', 'png']; it.max_files = 3; it.max_size_mb = 10; }
    if (type === 'geo') { it.title = 'Ort'; it.allow_gps = true; it.show_inputs = true; it.geometries = ['point']; }
    if (type === 'table') { it.columns = [{id:'description',label:'Beschreibung',type:'text',required:true},{id:'amount',label:'Betrag (€)',type:'amount',required:true,min:'0'}]; it.max_rows=30; }
    if (type === 'period') {it.with_time=true;}
    if (type === 'calculation') {it.operation='sum';it.sources=[];it.precision=2;}
    if (type === 'declaration' || type === 'signature') {it.statement='Ich bestätige ausdrücklich die Richtigkeit und Vollständigkeit meiner Angaben.';}
    if (type === 'text') { it.required = false; }
    return it;
  }

  function mount(root, opts) {
    var items = (opts.items || []).map(function (x) { return JSON.parse(JSON.stringify(x)); });
    var types = opts.types, subtypes = opts.subtypes || {}, order = opts.order || {};
    var typeKeys = order.types || Object.keys(types), subKeys = order.subtypes || Object.keys(subtypes);
    var changed = function () { if (opts.onChange) { opts.onChange(items); } };

    function row(it, i) {
      var t = types[it.type] || [it.type, 'fa-circle'];
      var h = '<div class="card fl-row mb-2" data-i="' + i + '"><div class="card-body p-2">' +
        '<div class="d-flex align-items-center gap-2 mb-2"><span class="small text-secondary text-nowrap"><i class="fa-solid ' + t[1] + ' me-1"></i>' + esc(t[0]) + '</span>' +
        '<input class="form-control form-control-sm" data-k="title" value="' + esc(it.title) + '" placeholder="' + (it.type === 'text' ? 'Überschrift des Hinweises (optional)' : 'Bezeichnung, z. B. „Lageplan“') + '" aria-label="Bezeichnung">' +
        '<div class="btn-group btn-group-sm flex-none">' +
        '<button type="button" class="btn btn-outline-secondary" data-mv="-1" title="Nach oben" aria-label="Nach oben"><i class="fa-solid fa-arrow-up"></i></button>' +
        '<button type="button" class="btn btn-outline-secondary" data-mv="1" title="Nach unten" aria-label="Nach unten"><i class="fa-solid fa-arrow-down"></i></button>' +
        '<button type="button" class="btn btn-outline-danger" data-del title="Entfernen" aria-label="Entfernen"><i class="fa-regular fa-trash-can"></i></button></div></div>' +
        '<div class="row g-2 small">' +
        '<div class="col-12"><input class="form-control form-control-sm" data-k="description" value="' + esc(it.description) + '" placeholder="' + (it.type === 'text' ? 'Hinweistext' : 'Erläuterung (optional), z. B. „Maßstab 1:1000, nicht älter als 3 Monate“') + '" aria-label="Erläuterung"></div>';
      if (it.type === 'declaration' || it.type === 'signature') {h += '<div class="col-12"><label>Wortlaut der Erklärung<textarea class="form-control" data-k="statement" maxlength="2000">'+esc(it.statement || '')+'</textarea></label></div>';}
      if (it.type === 'expense_accounting') {
        h += '<label class="col-12">Satzprofil<input class="form-control" data-k="profile" value="'+esc(it.profile || 'rlp')+'"></label>';
        [['period_source','Tatsächlicher Zeitraum'],['route_source','Fahrtstrecken'],['costs_source','Kostenpositionen'],['days_source','Verpflegung je Tag'],['advance_source','Vorschuss'],['reason_source','Triftige Gründe'],['special_source','Besonderheiten'],['year_km_source','Bisherige Jahreskilometer']].forEach(function(pair){h += '<label class="col-sm-6">'+pair[1]+'<select class="form-select" data-k="'+pair[0]+'"><option value="">Bitte wählen …</option>'+items.filter(function(q){return q.id!==it.id;}).map(function(q){return '<option value="'+esc(q.id)+'"'+(it[pair[0]]===q.id?' selected':'')+'>'+esc(q.title || 'Unbenanntes Feld')+'</option>';}).join('')+'</select></label>';});
      }
      if (it.type === 'route') {h += '<label class="col-12">Höchstens Fahrtabschnitte<input class="form-control" data-k="max_legs" type="number" min="1" max="30" value="'+(it.max_legs || 10)+'"></label>';}
      if (it.type === 'period') {h += '<label class="col-12"><input type="checkbox" data-k="with_time"'+(it.with_time !== false?' checked':'')+'> Mit Uhrzeit</label>';}
      if (it.type === 'table') {
        h += '<div class="col-12 d-grid gap-2">'+(it.columns || []).map(function(c,n){return '<div class="border rounded p-2" data-fl-column="'+n+'"><label>Spaltenüberschrift<input class="form-control" data-fl-column-key="label" value="'+esc(c.label)+'"></label><label>Eingabe<select class="form-select" data-fl-column-key="type">'+[['text','Text'],['number','Zahl'],['amount','Betrag'],['date','Datum'],['time','Uhrzeit'],['datetime','Datum mit Uhrzeit'],['select','Auswahl'],['checkbox','Ja / Nein']].map(function(o){return '<option value="'+o[0]+'"'+(c.type===o[0]?' selected':'')+'>'+o[1]+'</option>';}).join('')+'</select></label>'+(c.type==='select'?'<label>Antwortmöglichkeiten (eine je Zeile)<textarea class="form-control" data-fl-column-key="options">'+esc((c.options || []).join('\n'))+'</textarea></label>':'')+'<label class="d-block"><input type="checkbox" data-fl-column-key="required"'+(c.required?' checked':'')+'> Pflichtangabe</label><button class="btn btn-sm btn-outline-danger" type="button" data-fl-column-remove="'+n+'">Spalte entfernen</button></div>';}).join('')+'<button type="button" class="btn btn-sm btn-outline-primary" data-fl-column-add>Spalte hinzufügen</button></div>';
        h += '<label class="col-sm-6">Höchstens Positionen<input class="form-control" type="number" min="1" max="100" data-k="max_rows" value="'+esc(it.max_rows || 30)+'"></label>';
      }
      if (it.type === 'calculation') {
        h += '<label class="col-sm-6">Berechnung<select class="form-select" data-k="operation">'+[['sum','Summe'],['difference','Erster Wert minus weitere'],['product','Produkt'],['table_total','Tabellensumme']].map(function(o){return '<option value="'+o[0]+'"'+(it.operation===o[0]?' selected':'')+'>'+o[1]+'</option>';}).join('')+'</select></label>';
        h += '<div class="col-12">Quellfelder'+items.filter(function(q){return q.id!==it.id && (q.type==='table' || q.type==='calculation' || (q.type==='short' && q.subtype==='number'));}).map(function(q){return '<label class="d-block"><input type="checkbox" data-fl-source="'+esc(q.id)+'"'+((it.sources || []).indexOf(q.id)>=0?' checked':'')+'> '+esc(q.title || 'Unbenanntes Feld')+'</label>';}).join('')+'</div><label class="col-sm-6">Tabellenspalte<input class="form-control" data-k="column" value="'+esc(it.column || 'amount')+'"></label><label class="col-sm-6">Einheit<input class="form-control" data-k="unit" value="'+esc(it.unit || '')+'"></label>';
      }
      if (it.type === 'short') {
        h += '<div class="col-sm-6"><select class="form-select form-select-sm" data-k="subtype" aria-label="Art der Eingabe">' + subKeys.filter(function (k) { return k !== 'regex'; }).map(function (k) {
          return '<option value="' + k + '"' + (it.subtype === k ? ' selected' : '') + '>' + esc(subtypes[k]) + '</option>'; }).join('') + '</select></div>';
      }
      if (CHOICE[it.type]) {
        h += '<div class="col-12"><textarea class="form-control form-control-sm" data-k="options" rows="2" placeholder="Eine Option je Zeile" aria-label="Optionen">' +
          esc((it.options || []).map(function (o) { return o.label; }).join('\n')) + '</textarea></div>';
      }
      if (it.type === 'file') {
        h += '<div class="col-sm-6"><input class="form-control form-control-sm" data-k="file_types" value="' + esc((it.file_types || []).join(', ')) + '" placeholder="Dateiendungen, leer = alle" aria-label="Erlaubte Dateiendungen"></div>' +
          '<div class="col-sm-4"><div class="input-group input-group-sm"><span class="input-group-text">max.</span><input class="form-control" type="number" min="1" max="10" data-k="max_files" value="' + esc(it.max_files || 1) + '" aria-label="Höchstzahl Dateien"><span class="input-group-text">Dateien</span></div></div>';
      }
      if (it.type === 'geo') {
        var gsel = (it.geometries || [it.geometry || 'point']).length > 1 ? 'any' : (it.geometries || [it.geometry || 'point'])[0];
        h += '<div class="col-sm-6"><select class="form-select form-select-sm" data-k="geometries" aria-label="Was darf eingezeichnet werden">' +
          [['point', 'Punkt'], ['line', 'Linie'], ['polygon', 'Fläche'], ['any', 'Punkt, Linie oder Fläche']].map(function (g) {
            return '<option value="' + g[0] + '"' + (gsel === g[0] ? ' selected' : '') + '>' + g[1] + '</option>'; }).join('') + '</select></div>' +
          '<div class="col-sm-6 d-flex align-items-center"><div class="form-check mb-0"><input class="form-check-input" type="checkbox" id="fl-loc-' + it.id + '" data-k="capture_location"' + (it.capture_location ? ' checked' : '') + '>' +
          '<label class="form-check-label" for="fl-loc-' + it.id + '">eigenen Standort erfassen</label></div></div>';
      }
      if (it.type !== 'text') {
        h += '<div class="col-sm-3 d-flex align-items-center"><div class="form-check form-switch mb-0"><input class="form-check-input" type="checkbox" role="switch" id="fl-req-' + it.id + '" data-k="required"' + (it.required ? ' checked' : '') + '>' +
          '<label class="form-check-label" for="fl-req-' + it.id + '">Pflicht</label></div></div>';
      }
      return h + '</div></div></div>';
    }

    function render() {
      root.innerHTML = '<div class="fl-items">' + (items.length ? items.map(row).join('') :
        '<div class="text-secondary small border rounded p-3 text-center mb-2">Noch keine Felder. Wählen Sie unten aus, was nachgereicht werden soll.</div>') + '</div>' +
        '<div class="d-flex flex-wrap gap-1">' + typeKeys.map(function (k) {
          return '<button type="button" class="btn btn-sm btn-outline-primary" data-add="' + k + '"><i class="fa-solid ' + types[k][1] + ' me-1"></i>' + esc(types[k][0]) + '</button>';
        }).join('') + '</div>';
    }

    root.addEventListener('input', function (ev) {
      var r = ev.target.closest('.fl-row'), k = ev.target.dataset.k;
      if (!r) {return;}
      var currentItem=items[+r.dataset.i];
      if (ev.target.dataset.flColumnKey) {var col=currentItem.columns[Number(ev.target.closest('[data-fl-column]').dataset.flColumn)];col[ev.target.dataset.flColumnKey]=ev.target.type==='checkbox'?ev.target.checked:ev.target.dataset.flColumnKey==='options'?ev.target.value.split('\n').filter(Boolean):ev.target.value;changed();if(ev.target.tagName==='SELECT'){render();}return;}
      if(ev.target.dataset.flSource){currentItem.sources=(currentItem.sources || []).filter(function(id){return id!==ev.target.dataset.flSource;});if(ev.target.checked){currentItem.sources.push(ev.target.dataset.flSource);}changed();return;}
      if (!k) {return;}
      var it = items[+r.dataset.i];
      if (k === 'geometries' || k === 'capture_location' || k === 'subtype') { return; }   // über „change“
      if (k === 'required' || k === 'with_time') { it[k] = ev.target.checked; }
      else if (k === 'options') {
        it.options = ev.target.value.split('\n').map(function (l) { return l.trim(); }).filter(Boolean).map(function (l) { return { id: uid(), label: l }; });
      } else if (k === 'file_types') {
        it.file_types = ev.target.value.split(/[,;\s]+/).map(function (x) { return x.replace(/^\./, '').toLowerCase(); }).filter(Boolean);
      } else if (k === 'max_files') { it.max_files = parseInt(ev.target.value, 10) || 1; }
      else { it[k] = ev.target.value; }
      changed();
    });
    root.addEventListener('change', function (ev) {
      var k = ev.target.dataset.k, row = ev.target.closest('.fl-row');
      if (!row) { return; }
      var it = items[+row.dataset.i];
      if (k === 'subtype') { it.subtype = ev.target.value; changed(); }
      if (k === 'geometries') { it.geometries = ev.target.value === 'any' ? ['point', 'line', 'polygon'] : [ev.target.value]; delete it.geometry; changed(); }
      if (k === 'capture_location') { it.capture_location = ev.target.checked; changed(); }
    });
    root.addEventListener('click', function (ev) {
      var b = ev.target.closest('button');
      if (!b || !root.contains(b)) { return; }
      var r = b.closest('.fl-row'), i = r ? +r.dataset.i : -1;
      if (b.hasAttribute('data-fl-column-add')) {(items[i].columns=items[i].columns || []).push({id:uid(),label:'Neue Spalte',type:'text',required:false});render();changed();return;}
      if (b.hasAttribute('data-fl-column-remove')) {items[i].columns.splice(Number(b.dataset.flColumnRemove),1);render();changed();return;}
      if (b.dataset.add) {
        items.push(blank(b.dataset.add));
        render(); changed();
        var rows = root.querySelectorAll('.fl-row');
        var input = rows[rows.length - 1] && rows[rows.length - 1].querySelector('[data-k="title"]');
        if (input) { input.focus(); input.select(); }
      } else if (b.hasAttribute('data-del')) { items.splice(i, 1); render(); changed(); }
      else if (b.dataset.mv) {
        var j = i + parseInt(b.dataset.mv, 10);
        if (j >= 0 && j < items.length) { var x = items[i]; items[i] = items[j]; items[j] = x; render(); changed(); }
      }
    });
    render();
    return {
      get: function () { return items; },
      set: function (list) { items = (list || []).map(function (x) { var c = JSON.parse(JSON.stringify(x)); c.id = c.id || uid(); return c; }); render(); changed(); }
    };
  }

  window.FieldList = { mount: mount };

  /* Formulare mit [data-field-list]: Editor einhängen und vor dem Absenden als JSON übergeben */
  document.querySelectorAll('[data-field-list]').forEach(function (box) {
    var cfg = JSON.parse(document.getElementById(box.dataset.fieldList).textContent);
    var target = document.getElementById(box.dataset.target);
    var initial = box.dataset.items ? JSON.parse(box.dataset.items) : [];
    var editor = mount(box, { types: cfg.types, subtypes: cfg.subtypes, order: cfg.order, items: initial,
      onChange: function (list) { target.value = JSON.stringify(list); } });
    target.value = JSON.stringify(editor.get());
    box.fieldList = editor;
  });
})();
