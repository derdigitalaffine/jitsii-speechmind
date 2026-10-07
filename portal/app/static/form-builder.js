/* Formular-Baukasten: Elemente hinzufügen, bearbeiten, verschieben (SortableJS), speichern als JSON. */
(function () {
  'use strict';
  var dataEl = document.getElementById('builder-data');
  if (!dataEl) { return; }
  var data = JSON.parse(dataEl.textContent);
  var items = data.items || [];
  var TYPES = data.types;
  var SUBTYPES = data.subtypes;
  var BLOCKS = data.blocks || {};
  var QTYPES = { short: 1, long: 1, radio: 1, checkbox: 1, dropdown: 1, date: 1, time: 1, datetime: 1, scale: 1, color: 1, file: 1, geo: 1, address: 1 };
  var list = document.getElementById('builder-items');
  var empty = document.getElementById('builder-empty');
  var form = document.getElementById('builder-form');
  var savebar = form.querySelector('.builder-savebar');
  var selected = null;
  var dirty = false;

  var uid = function () { return Math.random().toString(16).slice(2, 10); };
  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  var isQuestion = function (t) { return TYPES[t] && TYPES[t][2]; };
  var markDirty = function () {
    dirty = true;
    savebar.classList.add('dirty');
    document.getElementById('builder-state').textContent = 'Ungespeicherte Änderungen';
  };

  function blank(type) {
    var it = { id: uid(), type: type, title: '', description: '' };
    if (isQuestion(type)) { it.required = false; }
    if (type === 'short') { it.subtype = 'text'; it.placeholder = ''; }
    if (type === 'radio' || type === 'checkbox' || type === 'dropdown') {
      it.options = [{ id: uid(), label: 'Option 1' }, { id: uid(), label: 'Option 2' }];
    }
    if (type === 'scale') { it.min = 1; it.max = 5; it.low_label = ''; it.high_label = ''; }
    if (type === 'file') { it.file_types = []; it.max_size_mb = Math.min(10, data.maxFileMb); it.max_files = 1; }
    if (type === 'geo') { it.title = 'Ort'; it.geometries = ['point']; it.max_features = 1; it.allow_gps = true; it.show_inputs = true; it.capture_location = false; }
    if (type === 'address') { it.title = 'Anschrift'; it.mode = 'full'; it.search = true; it.locate = true; it.district = false; it.coords = true; }
    if (type === 'table') { it.columns = [{id: 'description', label: 'Beschreibung', type: 'text', required: true}, {id: 'amount', label: 'Betrag (€)', type: 'amount', required: true, min: '0'}]; it.max_rows = 30; it.min_rows = 0; }
    if (type === 'period') { it.with_time = true; }
    if (type === 'calculation') { it.operation = 'sum'; it.sources = []; it.precision = 2; }
    if (type === 'declaration' || type === 'signature') { it.statement = 'Ich bestätige ausdrücklich die Richtigkeit und Vollständigkeit meiner Angaben.'; }
    if (type === 'heading') { it.title = 'Abschnitt'; }
    if (type === 'pagebreak') { it.title = ''; }
    return it;
  }

  /* --- Bausteine für die Einstellungen je Typ ---------------------------- */
  function field(label, html, cols) {
    return '<div class="col-' + (cols || 'md-6') + '"><label class="form-label small mb-1">' + label + '</label>' + html + '</div>';
  }
  function input(key, value, attrs) {
    return '<input class="form-control form-control-sm" data-key="' + key + '" value="' + esc(value) + '" ' + (attrs || '') + '>';
  }
  function settingsHtml(it) {
    var h = '';
    switch (it.type) {
      case 'table':
        h += '<div class="col-12"><div class="d-grid gap-2">' + (it.columns || []).map(function (c, n) {
          return '<div class="border rounded p-2" data-column-index="' + n + '"><div class="row g-2">' +
            field('Spaltenüberschrift', '<input class="form-control form-control-sm" data-column-key="label" value="' + esc(c.label) + '">') +
            field('Eingabe', '<select class="form-select form-select-sm" data-column-key="type">' + [['text','Text'],['number','Zahl'],['amount','Betrag'],['date','Datum'],['time','Uhrzeit'],['datetime','Datum und Uhrzeit'],['select','Auswahl'],['checkbox','Ja / Nein']].map(function (o) {return '<option value="'+o[0]+'"'+(c.type === o[0] ? ' selected' : '')+'>'+o[1]+'</option>';}).join('')+'</select>') +
            (c.type === 'select' ? field('Antwortmöglichkeiten (eine je Zeile)', '<textarea class="form-control form-control-sm" data-column-key="options">'+esc((c.options || []).join('\n'))+'</textarea>', '12') : '') +
            '<div class="col-12 d-flex gap-3 align-items-center"><label><input type="checkbox" data-column-key="required"'+(c.required ? ' checked' : '')+'> Pflichtangabe</label><button type="button" class="btn btn-sm btn-outline-danger" data-column-remove="'+n+'">Spalte entfernen</button></div></div></div>';
        }).join('') + '</div><button type="button" class="btn btn-sm btn-outline-primary mt-2" data-column-add>Spalte hinzufügen</button></div>';
        h += field('Mindestens Positionen', input('min_rows', it.min_rows || 0, 'type="number" min="0" max="100"'));
        h += field('Höchstens Positionen', input('max_rows', it.max_rows || 30, 'type="number" min="1" max="100"'));
        break;
      case 'expense_accounting':
        h += field('Satzprofil', input('profile', it.profile || 'rlp'));
        [['period_source','Tatsächlicher Zeitraum'],['route_source','Fahrtstrecken'],['costs_source','Kostenpositionen'],['days_source','Verpflegung je Tag'],['advance_source','Vorschuss'],['reason_source','Triftige Gründe'],['special_source','Besonderheiten'],['year_km_source','Bisherige Jahreskilometer']].forEach(function(pair){h += field(pair[1],'<select class="form-select" data-key="'+pair[0]+'"><option value="">Bitte wählen …</option>'+items.filter(function(q){return q.id!==it.id;}).map(function(q){return '<option value="'+esc(q.id)+'"'+(it[pair[0]]===q.id?' selected':'')+'>'+esc(q.title || 'Unbenanntes Feld')+'</option>';}).join('')+'</select>');});
        break;
      case 'route':
        h += field('Höchstens Fahrtabschnitte', input('max_legs', it.max_legs || 10, 'type="number" min="1" max="30"'));
        ['allow_roundtrip','allow_deviation'].forEach(function (key) {h += '<div class="col-12"><label><input type="checkbox" data-flag="'+key+'"'+(it[key] !== false ? ' checked' : '')+'> '+(key === 'allow_roundtrip' ? 'Rückfahrt anbieten' : 'Begründete Kilometerabweichungen ermöglichen')+'</label></div>';});
        break;
      case 'period':
        h += '<div class="col-12 form-check"><input class="form-check-input" type="checkbox" data-flag="with_time"' + (it.with_time !== false ? ' checked' : '') + '><label class="form-check-label">Mit Uhrzeit</label></div>';
        break;
      case 'declaration': case 'signature':
        h += field('Wortlaut der Erklärung', '<textarea class="form-control" data-key="statement" maxlength="2000">' + esc(it.statement || '') + '</textarea>', '12');
        break;
      case 'calculation':
        h += field('Berechnung', '<select class="form-select" data-key="operation">' + [['sum','Summe'],['difference','Erster Wert minus weitere'],['product','Produkt'],['table_total','Summe einer Tabellenspalte']].map(function (o) {return '<option value="'+o[0]+'"'+(it.operation === o[0] ? ' selected' : '')+'>'+o[1]+'</option>';}).join('')+'</select>');
        h += '<div class="col-12"><span class="form-label small">Quellfelder</span><div class="d-grid gap-1">' + items.filter(function (q) {return q.id !== it.id && (q.type === 'table' || q.type === 'calculation' || (q.type === 'short' && q.subtype === 'number'));}).map(function (q) { var selectedSources = Array.isArray(it.sources) ? it.sources : String(it.sources || '').split(','); return '<label class="border rounded p-2"><input type="checkbox" data-calculation-source="'+esc(q.id)+'"'+(selectedSources.indexOf(q.id)>=0 ? ' checked' : '')+'> '+esc(q.title || 'Unbenanntes Feld')+'</label>'; }).join('')+'</div></div>';
        h += field('Tabellenspalte (ID)', input('column', it.column || 'amount'));
        h += field('Mengen-Spalte (optional)', input('quantity_column', it.quantity_column || ''));
        h += field('Einheit', input('unit', it.unit || ''));
        h += field('Nachkommastellen', input('precision', it.precision == null ? 2 : it.precision, 'type="number" min="0" max="4"'));
        break;
      case 'short':
        h += field('Art der Eingabe', '<select class="form-select form-select-sm" data-key="subtype">' +
          Object.keys(SUBTYPES).map(function (k) {
            return '<option value="' + k + '"' + (it.subtype === k ? ' selected' : '') + '>' + SUBTYPES[k] + '</option>';
          }).join('') + '</select>');
        h += field('Platzhalter', input('placeholder', it.placeholder, 'maxlength="200"'));
        if (it.subtype === 'number') {
          h += field('Kleinster Wert', input('min', it.min == null ? '' : it.min, 'type="number" step="any"'), 'md-3');
          h += field('Größter Wert', input('max', it.max == null ? '' : it.max, 'type="number" step="any"'), 'md-3');
        }
        if (it.subtype === 'regex') {
          h += field('Muster (regulärer Ausdruck)', input('pattern', it.pattern, 'placeholder="z. B. [0-9]{5} für eine PLZ"'));
          h += field('Hinweis bei falscher Eingabe', input('pattern_hint', it.pattern_hint, 'placeholder="z. B. Bitte fünfstellige PLZ angeben"'));
        }
        break;
      case 'long':
        h += field('Platzhalter', input('placeholder', it.placeholder, 'maxlength="200"'));
        h += field('Höchstens Zeichen', input('max_length', it.max_length || '', 'type="number" min="1" max="20000" placeholder="unbegrenzt"'), 'md-3');
        break;
      case 'radio': case 'checkbox': case 'dropdown':
        h += '<div class="col-12"><div class="options-list d-flex flex-column gap-1">' + (it.options || []).map(function (o) {
          return '<div class="option-row input-group input-group-sm" data-oid="' + esc(o.id) + '">' +
            '<span class="input-group-text drag-handle" title="Verschieben"><i class="fa-solid fa-grip-vertical"></i></span>' +
            '<span class="input-group-text"><i class="fa-regular ' + (it.type === 'checkbox' ? 'fa-square' : it.type === 'radio' ? 'fa-circle' : 'fa-rectangle-list') + '"></i></span>' +
            '<input class="form-control" data-option value="' + esc(o.label) + '" maxlength="500" aria-label="Option">' +
            '<button class="btn btn-outline-secondary" type="button" data-remove-option title="Option entfernen"><i class="fa-solid fa-xmark"></i></button></div>';
        }).join('') + '</div>' +
          '<div class="input-group input-group-sm mt-2"><input class="form-control" data-new-option placeholder="Neue Option eingeben und Enter drücken – mehrere Zeilen einfügen legt mehrere an">' +
          '<button class="btn btn-outline-primary" type="button" data-add-option><i class="fa-solid fa-plus"></i></button></div></div>';
        h += '<div class="col-12 d-flex flex-wrap gap-3 small">';
        if (it.type !== 'dropdown') {
          h += switchHtml('other', 'Feld „Sonstiges“ mit Freitext', it.other);
        }
        h += switchHtml('shuffle', 'Optionen in zufälliger Reihenfolge', it.shuffle) + '</div>';
        if (it.type === 'checkbox') {
          h += field('Mindestens wählen', input('min', it.min || '', 'type="number" min="0" placeholder="beliebig"'), 'md-3');
          h += field('Höchstens wählen', input('max', it.max || '', 'type="number" min="1" placeholder="beliebig"'), 'md-3');
        }
        break;
      case 'date':
        h += field('Frühestes Datum', input('min', it.min, 'type="date"'), 'md-3');
        h += field('Spätestes Datum', input('max', it.max, 'type="date"'), 'md-3');
        h += '<div class="col-md-6 d-flex align-items-end small">' + switchHtml('with_time', 'mit Uhrzeit', it.with_time) + '</div>';
        break;
      case 'datetime':
        h += field('Frühestens am', input('min', it.min, 'type="date"'), 'md-3');
        h += field('Spätestens am', input('max', it.max, 'type="date"'), 'md-3');
        break;
      case 'scale':
        h += field('Von', '<select class="form-select form-select-sm" data-key="min">' + [0, 1].map(function (n) {
          return '<option' + (Number(it.min) === n ? ' selected' : '') + '>' + n + '</option>'; }).join('') + '</select>', 'md-2');
        h += field('Bis', '<select class="form-select form-select-sm" data-key="max">' + [2, 3, 4, 5, 6, 7, 8, 9, 10].map(function (n) {
          return '<option' + (Number(it.max) === n ? ' selected' : '') + '>' + n + '</option>'; }).join('') + '</select>', 'md-2');
        h += field('Beschriftung links', input('low_label', it.low_label, 'placeholder="z. B. gar nicht zufrieden"'), 'md-4');
        h += field('Beschriftung rechts', input('high_label', it.high_label, 'placeholder="z. B. sehr zufrieden"'), 'md-4');
        break;
      case 'geo':
        var geoms = it.geometries || [it.geometry || 'point'];
        h += '<div class="col-12"><div class="form-label small mb-1">Was darf eingezeichnet werden?</div><div class="d-flex flex-wrap gap-3 small">' +
          [['point', 'Punkt', 'z. B. Standort, Fundort'], ['line', 'Linie', 'z. B. Trasse, Wegstrecke'], ['polygon', 'Fläche', 'z. B. Baufläche']].map(function (g) {
            var id = 'geo-' + g[0] + '-' + uid();
            return '<div class="form-check"><input class="form-check-input" type="checkbox" id="' + id + '" data-geom="' + g[0] + '"' + (geoms.indexOf(g[0]) >= 0 ? ' checked' : '') + '>' +
              '<label class="form-check-label" for="' + id + '"><strong>' + g[1] + '</strong> <span class="text-secondary">(' + g[2] + ')</span></label></div>';
          }).join('') + '</div></div>';
        h += field('Wie viele Objekte höchstens?', input('max_features', it.max_features || 1, 'type="number" min="1" max="50"'), 'md-3');
        h += '<div class="col-12 d-flex flex-wrap gap-3 small">' +
          switchHtml('allow_gps', 'GPS-Knöpfe beim Einzeichnen („Punkt an meinem Standort“, „Standort als Eckpunkt“)', it.allow_gps !== false) +
          (geoms.length === 1 && geoms[0] === 'point' && Number(it.max_features || 1) === 1 ? switchHtml('show_inputs', 'Felder für Breite und Länge anzeigen', it.show_inputs !== false) : '') + '</div>';
        h += '<div class="col-12"><div class="border rounded p-2 small"><div class="d-flex flex-wrap gap-3">' +
          switchHtml('capture_location', '<strong>Eigenen Standort zusätzlich erfassen</strong> – Knopf „Meinen Standort erfassen“, unabhängig vom Eingezeichneten (z. B. wo die meldende Person steht)', it.capture_location) +
          (it.capture_location ? switchHtml('location_required', 'Standort ist Pflicht', it.location_required) : '') + '</div></div></div>' +
          '<div class="col-12 small text-secondary"><i class="fa-solid fa-ruler me-1"></i>Länge und Fläche werden automatisch berechnet. Die Karte zeigt die Grundkarten, die unter Verwaltung › Kartenlayer für Formulare freigegeben sind.</div>';
        break;
      case 'block':
        var bd = BLOCKS[it.block_id];
        h += '<div class="col-12 small">' + (bd ? '<div class="text-secondary mb-1">Felder aus der Bibliothek (Änderungen am Block gelten für alle Formulare):</div><div class="d-flex flex-wrap gap-1">' +
          bd.items.map(function (c) { return '<span class="badge text-bg-light border fw-normal"><i class="fa-solid ' + ((TYPES[c.type] || [0, 'fa-circle'])[1]) + ' me-1"></i>' + esc(c.title || (TYPES[c.type] || [''])[0]) + '</span>'; }).join('') + '</div>' +
          (data.canBlocks ? '<a class="small d-inline-block mt-2" href="/forms/blocks/' + it.block_id + '" target="_blank"><i class="fa-solid fa-pen me-1"></i>Datenblock bearbeiten</a>' : '')
          : '<span class="text-danger">Dieser Datenblock existiert nicht mehr.</span>') + '</div>';
        break;
      case 'address':
        h += field('Umfang', '<select class="form-select form-select-sm" data-key="mode"><option value="full"' + (it.mode !== 'zip_city' ? ' selected' : '') + '>Straße, Hausnummer, PLZ, Ort</option>' +
          '<option value="zip_city"' + (it.mode === 'zip_city' ? ' selected' : '') + '>nur PLZ und Ort</option></select>');
        h += '<div class="col-12 d-flex flex-wrap gap-3 small">' + switchHtml('search', 'Suchfeld „Adresse suchen“ (OpenStreetMap)', it.search !== false) +
          switchHtml('locate', 'Knopf „Meinen Standort übernehmen“', it.locate !== false) + switchHtml('district', 'Feld „Ortsteil“', it.district) +
          switchHtml('coords', 'Koordinate mitspeichern (Karte, Ortsfilter in der Ablage)', it.coords !== false) + '</div>' +
          '<div class="col-12 small text-secondary">Die PLZ ergänzt den Ort automatisch; alle Felder bleiben von Hand änderbar.</div>';
        break;
      case 'file':
        h += field('Erlaubte Dateiendungen', input('file_types', (it.file_types || []).join(', '), 'placeholder="leer = alle, z. B. pdf, jpg, png, docx"'));
        h += field('Max. Größe je Datei (MB)', input('max_size_mb', it.max_size_mb, 'type="number" min="1" max="' + data.maxFileMb + '"'), 'md-3');
        h += field('Max. Anzahl Dateien', input('max_files', it.max_files, 'type="number" min="1" max="10"'), 'md-3');
        break;
    }
    return h ? '<div class="row g-2 mt-1">' + h + '</div>' : '';
  }
  function switchHtml(key, label, on) {
    var id = 'sw-' + key + '-' + uid();
    return '<div class="form-check form-switch"><input class="form-check-input" type="checkbox" role="switch" id="' + id +
      '" data-flag="' + key + '"' + (on ? ' checked' : '') + '><label class="form-check-label" for="' + id + '">' + label + '</label></div>';
  }

  /* --- Darstellung und Bedingungen ------------------------------------- */
  var OPS = {}, OPS_KEYS = [], WIDTHS = data.widths || [['full', 'ganze Zeile']];
  (data.ops || []).forEach(function (o) { OPS[o[0]] = o[1]; OPS_KEYS.push(o[0]); });
  function sources(upTo) {   // Fragen (auch Felder aus Datenblöcken) oberhalb eines Elements
    var out = [], n = 0;
    items.slice(0, upTo < 0 ? items.length : upTo).forEach(function (x) {
      if (isQuestion(x.type)) { n++; out.push({ id: x.id, label: 'Frage ' + n + ': ' + (x.title || TYPES[x.type][0]), options: x.options }); }
      if (x.type === 'block' && BLOCKS[x.block_id]) {
        var b = BLOCKS[x.block_id];
        b.items.forEach(function (c) { if (QTYPES[c.type]) { out.push({ id: x.id + '_' + c.id, label: (x.title || b.name) + ' › ' + (c.title || TYPES[c.type][0]), options: c.options }); } });
      }
    });
    return out;
  }
  function condRules(it, key) {
    var c = it[key];
    var before = sources(items.indexOf(it));
    if (!before.length) { return '<div class="small text-secondary">Bedingungen beziehen sich auf Fragen <em>oberhalb</em> dieses Elements – davor gibt es noch keine.</div>'; }
    var h = '<div class="d-flex flex-wrap align-items-center gap-2 small mb-1">' + (key === 'show_if' ? 'Anzeigen, wenn' : 'Pflicht, wenn') +
      ' <select class="form-select form-select-sm w-auto" data-ckey="' + key + '" data-cmode>' +
      '<option value="all"' + (c.mode !== 'any' ? ' selected' : '') + '>alle Regeln</option><option value="any"' + (c.mode === 'any' ? ' selected' : '') + '>eine der Regeln</option></select> zutreffen:</div>';
    c.rules.forEach(function (r, i) {
      var q = before.filter(function (x) { return x.id === r.q; })[0];
      var valueHtml = '';
      if (r.op !== 'filled' && r.op !== 'empty') {
        if (q && q.options && q.options.length) {
          valueHtml = '<select class="form-select form-select-sm" data-ckey="' + key + '" data-ri="' + i + '" data-cfield="value"><option value="">– wählen –</option>' +
            q.options.map(function (o) { return '<option' + (o.label === r.value ? ' selected' : '') + '>' + esc(o.label) + '</option>'; }).join('') + '</select>';
        } else {
          valueHtml = '<input class="form-control form-control-sm" data-ckey="' + key + '" data-ri="' + i + '" data-cfield="value" value="' + esc(r.value) + '" placeholder="Wert">';
        }
      }
      h += '<div class="row g-1 mb-1 align-items-center"><div class="col-md-5"><select class="form-select form-select-sm" data-ckey="' + key + '" data-ri="' + i + '" data-cfield="q">' +
        before.map(function (b) { return '<option value="' + esc(b.id) + '"' + (b.id === r.q ? ' selected' : '') + '>' + esc(b.label) + '</option>'; }).join('') + '</select></div>' +
        '<div class="col-md-3"><select class="form-select form-select-sm" data-ckey="' + key + '" data-ri="' + i + '" data-cfield="op">' +
        OPS_KEYS.map(function (k) { return '<option value="' + k + '"' + (k === r.op ? ' selected' : '') + '>' + OPS[k] + '</option>'; }).join('') + '</select></div>' +
        '<div class="col-md-3">' + valueHtml + '</div>' +
        '<div class="col-md-1 text-end"><button type="button" class="btn btn-sm btn-link text-danger" data-ckey="' + key + '" data-cdel="' + i + '" title="Regel entfernen" aria-label="Regel entfernen"><i class="fa-solid fa-xmark"></i></button></div></div>';
    });
    return h + '<button type="button" class="btn btn-sm btn-outline-secondary" data-ckey="' + key + '" data-cadd><i class="fa-solid fa-plus me-1"></i>Regel</button>';
  }
  function logicHtml(it) {
    var q = isQuestion(it.type);
    var h = '<div class="border-top mt-3 pt-2"><div class="row g-2 align-items-end small">';
    if (q) {
      var mode = it.required_if ? 'if' : (it.required ? 'yes' : 'no');
      h += '<div class="col-md-4"><label class="form-label small mb-1">Pflichtfeld</label><select class="form-select form-select-sm" data-reqmode>' +
        [['no', 'Nein'], ['yes', 'Ja'], ['if', 'Nur unter Bedingung …']].map(function (o) { return '<option value="' + o[0] + '"' + (o[0] === mode ? ' selected' : '') + '>' + o[1] + '</option>'; }).join('') + '</select></div>';
    }
    if (['pagebreak', 'divider', 'heading', 'block'].indexOf(it.type) < 0) {
      h += '<div class="col-md-4"><label class="form-label small mb-1">Breite (am Bildschirm)</label><select class="form-select form-select-sm" data-key="width">' +
        WIDTHS.map(function (w) { return '<option value="' + w[0] + '"' + ((it.width || 'full') === w[0] ? ' selected' : '') + '>' + w[1] + '</option>'; }).join('') + '</select></div>';
    }
    h += '<div class="col-md-4">' + '<div class="form-check form-switch mb-1"><input class="form-check-input" type="checkbox" role="switch" id="cs-' + it.id + '" data-ctoggle="show_if"' + (it.show_if ? ' checked' : '') + '>' +
      '<label class="form-check-label" for="cs-' + it.id + '">' + (it.type === 'pagebreak' ? 'Seite nur unter Bedingung zeigen' : 'Nur unter Bedingung anzeigen') + '</label></div></div></div>';
    if (it.show_if) { h += '<div class="cond-box mt-2">' + condRules(it, 'show_if') + '</div>'; }
    if (it.required_if) { h += '<div class="cond-box mt-2">' + condRules(it, 'required_if') + '</div>'; }
    return h + '</div>';
  }
  function badges(it) {
    var b = [];
    if (it.required && !it.required_if) { b.push('<span class="badge text-bg-danger-subtle text-danger-emphasis">Pflicht</span>'); }
    if (it.required_if) { b.push('<span class="badge text-bg-danger-subtle text-danger-emphasis">Pflicht unter Bedingung</span>'); }
    if (it.show_if) { b.push('<span class="badge text-bg-warning-subtle text-warning-emphasis"><i class="fa-solid fa-code-branch me-1"></i>bedingt sichtbar</span>'); }
    if (it.width && it.width !== 'full') { b.push('<span class="badge text-bg-light border">' + esc((WIDTHS.filter(function (w) { return w[0] === it.width; })[0] || [0, ''])[1]) + '</span>'); }
    if (it.with_time) { b.push('<span class="badge text-bg-light border">mit Uhrzeit</span>'); }
    if (it.options && it.options.length) { b.push('<span class="badge text-bg-light border">' + it.options.length + ' Optionen</span>'); }
    return b.join(' ');
  }

  function cardHtml(it, index) {
    var t = TYPES[it.type];
    var q = isQuestion(it.type);
    var titlePh = { block: (BLOCKS[it.block_id] || {}).name || 'Datenblock', heading: 'Überschrift', subheading: 'Zwischenüberschrift', text: 'Titel des Hinweises (optional)',
      pagebreak: 'Titel der neuen Seite (optional)', divider: '' }[it.type] || 'Frage';
    var number = q ? items.slice(0, index + 1).filter(function (x) { return isQuestion(x.type); }).length : 0;
    var page = items.slice(0, index + 1).filter(function (x) { return x.type === 'pagebreak'; }).length + 1;
    var h = '<div class="card-body">' +
      '<div class="d-flex align-items-center gap-2 mb-2">' +
      '<span class="drag-handle px-1" title="Ziehen zum Verschieben"><i class="fa-solid fa-grip-vertical"></i></span>' +
      '<span class="item-type"><i class="fa-solid ' + t[1] + ' me-1"></i>' + t[0] + (q ? ' · Frage ' + number : '') +
      (it.type === 'pagebreak' ? ' · ab hier Seite ' + page : '') + '</span>' +
      '<div class="ms-auto btn-group btn-group-sm">' +
      '<button type="button" class="btn btn-outline-secondary" data-move="-1" title="Nach oben" aria-label="Nach oben"><i class="fa-solid fa-arrow-up"></i></button>' +
      '<button type="button" class="btn btn-outline-secondary" data-move="1" title="Nach unten" aria-label="Nach unten"><i class="fa-solid fa-arrow-down"></i></button>' +
      '<button type="button" class="btn btn-outline-secondary" data-duplicate title="Duplizieren" aria-label="Duplizieren"><i class="fa-regular fa-clone"></i></button>' +
      '<button type="button" class="btn btn-outline-danger" data-delete title="Entfernen" aria-label="Entfernen"><i class="fa-regular fa-trash-can"></i></button>' +
      '</div></div>';
    if (selected !== it.id) {   // kompakte Ansicht – Klick öffnet die Einstellungen
      if (it.type === 'divider') { return h + '<hr class="my-2"></div>'; }
      var bdesc = it.type === 'block' && BLOCKS[it.block_id] ? '<div class="small text-secondary text-truncate">' + BLOCKS[it.block_id].items.map(function (c) { return esc(c.title); }).join(' · ') + '</div>' : '';
      return h + '<div class="builder-compact" role="button" tabindex="0" title="Klicken zum Bearbeiten"><div class="fw-semibold">' + (esc(it.title) || (it.type === 'block' && BLOCKS[it.block_id] ? '<i class="fa-solid ' + esc(BLOCKS[it.block_id].icon) + ' me-1 text-primary"></i>' + esc(BLOCKS[it.block_id].name) : '<span class="text-secondary fw-normal">' + esc(titlePh || 'ohne Titel') + '</span>')) + '</div>' + bdesc +
        (it.description ? '<div class="small text-secondary text-truncate">' + esc(it.description) + '</div>' : '') +
        '<div class="d-flex flex-wrap gap-1 mt-1">' + badges(it) + '</div></div></div>';
    }
    if (it.type === 'divider') {
      h += '<hr class="my-2">';
    } else {
      h += '<input class="form-control title-input mb-2" data-key="title" value="' + esc(it.title) + '" maxlength="500" placeholder="' + titlePh + '">';
      h += '<textarea class="form-control form-control-sm" data-key="description" rows="' + (it.type === 'text' ? 3 : 1) + '" maxlength="5000" placeholder="' +
        (it.type === 'text' ? 'Text des Hinweises' : 'Beschreibung oder Hilfetext (optional)') + '">' + esc(it.description) + '</textarea>';
      h += settingsHtml(it);
    }
    h += logicHtml(it);
    return h + '</div>';
  }

  function render() {
    list.innerHTML = '';
    items.forEach(function (it, i) {
      var card = document.createElement('div');
      card.className = 'card builder-item type-' + it.type + (isQuestion(it.type) ? '' : ' is-layout') + (selected === it.id ? ' is-selected' : '');
      card.dataset.id = it.id;
      card.innerHTML = cardHtml(it, i);
      list.appendChild(card);
      var opts = card.querySelector('.options-list');
      if (opts && window.Sortable) {
        Sortable.create(opts, { handle: '.drag-handle', animation: 150, onEnd: function () { readOptions(it, card); markDirty(); } });
      }
    });
    empty.classList.toggle('d-none', items.length > 0);
    var qs = items.filter(function (x) { return isQuestion(x.type); }).length;
    var pages = items.filter(function (x) { return x.type === 'pagebreak'; }).length + 1;
    document.getElementById('builder-count').textContent = qs + ' Fragen · ' + pages + (pages === 1 ? ' Seite' : ' Seiten');
  }

  var find = function (el) {
    var card = el.closest('.builder-item');
    if (!card) { return null; }
    for (var i = 0; i < items.length; i++) { if (items[i].id === card.dataset.id) { return { item: items[i], index: i, card: card }; } }
    return null;
  };
  function readOptions(it, card) {
    it.options = Array.prototype.map.call(card.querySelectorAll('.option-row'), function (row) {
      return { id: row.dataset.oid, label: row.querySelector('[data-option]').value };
    });
  }
  function addOptions(it, card, text) {
    readOptions(it, card);
    text.split(/\r?\n/).map(function (s) { return s.trim(); }).filter(Boolean).forEach(function (label) {
      it.options.push({ id: uid(), label: label });
    });
    render();
    markDirty();
    var c = list.querySelector('[data-id="' + it.id + '"] [data-new-option]');
    if (c) { c.focus(); }
  }
  function select(id, focus) {
    if (selected === id) { return; }
    selected = id;
    render();
    if (focus) {
      var t = list.querySelector('[data-id="' + id + '"] .title-input');
      if (t) { t.focus(); }
    }
  }

  function firstQuestionBefore(it) {
    var before = sources(items.indexOf(it));
    return before.length ? before[before.length - 1] : null;
  }
  function newRule(it) {
    var q = firstQuestionBefore(it);
    return { q: q ? q.id : '', op: q && q.options && q.options.length ? 'eq' : 'filled', value: q && q.options && q.options.length ? q.options[0].label : '' };
  }
  function condClick(f, btn) {
    var key = btn.dataset.ckey, c = f.item[key];
    if (btn.hasAttribute('data-cadd')) { c.rules.push(newRule(f.item)); }
    else if (btn.dataset.cdel) {
      c.rules.splice(+btn.dataset.cdel, 1);
      if (!c.rules.length) { delete f.item[key]; if (key === 'required_if') { f.item.required = false; } }
    }
    render(); markDirty();
  }
  function condChange(f, el) {
    var key = el.dataset.ckey, c = f.item[key];
    if (el.hasAttribute('data-cmode')) { c.mode = el.value; }
    else {
      var r = c.rules[+el.dataset.ri];
      r[el.dataset.cfield] = el.value;
      if (el.dataset.cfield === 'q') { r.value = ''; }
    }
    markDirty();
    if (el.tagName === 'SELECT') { render(); }
  }

  /* --- Ereignisse --------------------------------------------------------- */
  document.querySelectorAll('[data-add], [data-add-block]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var it = btn.dataset.addBlock ? { id: uid(), type: 'block', block_id: parseInt(btn.dataset.addBlock, 10), title: '', description: '' } : blank(btn.dataset.add);
      var at = items.length;
      for (var i = 0; i < items.length; i++) { if (items[i].id === selected) { at = i + 1; } }
      items.splice(at, 0, it);
      selected = it.id;
      render();
      markDirty();
      var card = list.querySelector('[data-id="' + it.id + '"]');
      card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      var t = card.querySelector('.title-input');
      if (t) { t.focus(); t.select(); }
    });
  });
  list.addEventListener('keydown', function (ev) {
    if ((ev.key === 'Enter' || ev.key === ' ') && ev.target.classList.contains('builder-compact')) { ev.preventDefault(); var f = find(ev.target); if (f) { select(f.item.id, true); } }
  });
  list.addEventListener('click', function (ev) {
    var columnButton = ev.target.closest('[data-column-add], [data-column-remove]');
    if (columnButton) { var columnItem = find(columnButton); if (columnItem) { if (columnButton.hasAttribute('data-column-add')) { (columnItem.item.columns = columnItem.item.columns || []).push({id:uid(), label:'Neue Spalte', type:'text', required:false}); } else {columnItem.item.columns.splice(Number(columnButton.dataset.columnRemove),1);} markDirty(); render(); } return; }

    var f = find(ev.target);
    if (!f) { return; }
    var btn = ev.target.closest('button');
    if (!btn) { select(f.item.id, !!ev.target.closest('.builder-compact')); return; }
    if (btn.dataset.ckey) { condClick(f, btn); return; }
    if (btn.dataset.move) {
      var to = f.index + Number(btn.dataset.move);
      if (to < 0 || to >= items.length) { return; }
      items.splice(to, 0, items.splice(f.index, 1)[0]);
    } else if (btn.hasAttribute('data-duplicate')) {
      var copy = JSON.parse(JSON.stringify(f.item));
      copy.id = uid();
      (copy.options || []).forEach(function (o) { o.id = uid(); });
      items.splice(f.index + 1, 0, copy);
      selected = copy.id;
    } else if (btn.hasAttribute('data-delete')) {
      items.splice(f.index, 1);
    } else if (btn.hasAttribute('data-remove-option')) {
      readOptions(f.item, f.card);
      var oid = btn.closest('.option-row').dataset.oid;
      f.item.options = f.item.options.filter(function (o) { return o.id !== oid; });
    } else if (btn.hasAttribute('data-add-option')) {
      var field = f.card.querySelector('[data-new-option]');
      addOptions(f.item, f.card, field.value);
      return;
    } else { return; }
    render();
    markDirty();
  });
  list.addEventListener('input', function (ev) {
    var f = find(ev.target);
    if (!f) { return; }
    var el = ev.target;
    if (el.dataset.columnKey) { var column = f.item.columns[Number(el.closest('[data-column-index]').dataset.columnIndex)]; column[el.dataset.columnKey] = el.type === 'checkbox' ? el.checked : el.dataset.columnKey === 'options' ? el.value.split('\n').filter(Boolean) : el.value; markDirty(); if (el.tagName === 'SELECT') { render(); } return; }
    if (el.dataset.calculationSource) { var selectedSources = Array.isArray(f.item.sources) ? f.item.sources : []; f.item.sources = selectedSources.filter(function (id) {return id !== el.dataset.calculationSource;}); if (el.checked) {f.item.sources.push(el.dataset.calculationSource);} markDirty(); return; }
    if (el.dataset.ckey) { if (el.tagName === 'INPUT') { condChange(f, el); } return; }
    if (el.dataset.ctoggle || el.hasAttribute('data-reqmode')) { return; }
    if (el.dataset.key) {
      var key = el.dataset.key, val = el.value;
      if (key === 'columns_json') { try { val = JSON.parse(val); if (!Array.isArray(val)) { throw new Error('columns'); } f.item.columns = val; el.setCustomValidity(''); } catch (e) { el.setCustomValidity('Bitte gültige Spalten angeben.'); return; } }
      if (key === 'file_types') { val = val.split(/[\s,;]+/).filter(Boolean); }
      f.item[key] = val;
      if (key === 'subtype' || el.tagName === 'SELECT') { render(); }
      if (key === 'max_features') { f.item.max_features = parseInt(val, 10) || 1; }
    } else if (el.hasAttribute('data-option')) {
      readOptions(f.item, f.card);
    } else if (el.dataset.flag) {
      f.item[el.dataset.flag] = el.checked;
    }
    if (!el.hasAttribute('data-new-option')) { markDirty(); }
  });
  list.addEventListener('change', function (ev) {
    var f = find(ev.target);
    if (f && ev.target.dataset.ckey) { condChange(f, ev.target); return; }
    if (f && ev.target.dataset.ctoggle) {
      if (ev.target.checked) { f.item.show_if = { mode: 'all', rules: [newRule(f.item)] }; } else { delete f.item.show_if; }
      markDirty(); render(); return;
    }
    if (f && ev.target.hasAttribute('data-reqmode')) {
      var m = ev.target.value;
      f.item.required = m === 'yes';
      if (m === 'if') { f.item.required_if = f.item.required_if || { mode: 'all', rules: [newRule(f.item)] }; } else { delete f.item.required_if; }
      markDirty(); render(); return;
    }
    if (f && ev.target.dataset.geom) {
      var boxes = f.card.querySelectorAll('[data-geom]');
      var chosen = Array.prototype.filter.call(boxes, function (b) { return b.checked; }).map(function (b) { return b.dataset.geom; });
      if (!chosen.length) { ev.target.checked = true; return; }   // mindestens eine Art
      f.item.geometries = chosen; delete f.item.geometry;
      markDirty(); render(); return;
    }
    if (f && (ev.target.dataset.flag === 'capture_location')) { f.item.capture_location = ev.target.checked; markDirty(); render(); return; }
    if (f && ev.target.dataset.flag) { f.item[ev.target.dataset.flag] = ev.target.checked; markDirty(); }
    if (f && ev.target.tagName === 'SELECT' && ev.target.dataset.key) { f.item[ev.target.dataset.key] = ev.target.value; render(); markDirty(); }
  });
  list.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter' && ev.target.hasAttribute('data-new-option')) {
      ev.preventDefault();
      var f = find(ev.target);
      addOptions(f.item, f.card, ev.target.value);
    } else if (ev.key === 'Enter' && ev.target.tagName === 'INPUT') {
      ev.preventDefault(); // Enter speichert nicht versehentlich das ganze Formular
    }
  });
  list.addEventListener('paste', function (ev) {
    if (!ev.target.hasAttribute('data-new-option')) { return; }
    var text = (ev.clipboardData || window.clipboardData).getData('text');
    if (text.indexOf('\n') >= 0) {
      ev.preventDefault();
      var f = find(ev.target);
      addOptions(f.item, f.card, text);
    }
  });
  form.querySelectorAll('[name="title"], [name="description"]').forEach(function (el) { el.addEventListener('input', markDirty); });

  if (window.Sortable) {
    Sortable.create(list, {
      handle: '.drag-handle', animation: 150, draggable: '.builder-item', filter: '.options-list',
      onEnd: function (ev) {
        if (ev.oldIndex === ev.newIndex) { return; }
        items.splice(ev.newIndex, 0, items.splice(ev.oldIndex, 1)[0]);
        render();
        markDirty();
      }
    });
  }

  form.addEventListener('submit', function () {
    // Offene Eingaben in „Neue Option“ nicht verlieren
    list.querySelectorAll('[data-new-option]').forEach(function (el) {
      if (el.value.trim()) { var f = find(el); readOptions(f.item, f.card); f.item.options.push({ id: uid(), label: el.value.trim() }); }
    });
    document.getElementById('schema-json').value = JSON.stringify(items);
    dirty = false;
  });
  window.addEventListener('beforeunload', function (ev) { if (dirty) { ev.preventDefault(); ev.returnValue = ''; } });

  render();
})();
