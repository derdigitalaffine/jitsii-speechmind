/* Formular-Baukasten: Elemente hinzufügen, bearbeiten, verschieben (SortableJS), speichern als JSON. */
(function () {
  'use strict';
  var dataEl = document.getElementById('builder-data');
  if (!dataEl) { return; }
  var data = JSON.parse(dataEl.textContent);
  var items = data.items || [];
  var TYPES = data.types;
  var SUBTYPES = data.subtypes;
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
  function questionLabel(q) {
    var n = items.filter(function (x) { return isQuestion(x.type); }).indexOf(q) + 1;
    return 'Frage ' + n + ': ' + (q.title || TYPES[q.type][0]);
  }
  function condRules(it, key) {
    var c = it[key];
    var before = items.slice(0, items.indexOf(it)).filter(function (x) { return isQuestion(x.type); });
    if (!before.length) { return '<div class="small text-secondary">Bedingungen beziehen sich auf Fragen <em>oberhalb</em> dieses Elements – davor gibt es noch keine.</div>'; }
    var h = '<div class="d-flex flex-wrap align-items-center gap-2 small mb-1">' + (key === 'show_if' ? 'Anzeigen, wenn' : 'Pflicht, wenn') +
      ' <select class="form-select form-select-sm w-auto" data-ckey="' + key + '" data-cmode>' +
      '<option value="all"' + (c.mode !== 'any' ? ' selected' : '') + '>alle Regeln</option><option value="any"' + (c.mode === 'any' ? ' selected' : '') + '>eine der Regeln</option></select> zutreffen:</div>';
    c.rules.forEach(function (r, i) {
      var q = items.filter(function (x) { return x.id === r.q; })[0];
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
        before.map(function (b) { return '<option value="' + esc(b.id) + '"' + (b.id === r.q ? ' selected' : '') + '>' + esc(questionLabel(b)) + '</option>'; }).join('') + '</select></div>' +
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
    if (['pagebreak', 'divider', 'heading'].indexOf(it.type) < 0) {
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
    var titlePh = { heading: 'Überschrift', subheading: 'Zwischenüberschrift', text: 'Titel des Hinweises (optional)',
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
      return h + '<div class="builder-compact" role="button" tabindex="0" title="Klicken zum Bearbeiten"><div class="fw-semibold">' + (esc(it.title) || '<span class="text-secondary fw-normal">' + esc(titlePh || 'ohne Titel') + '</span>') + '</div>' +
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
    var before = items.slice(0, items.indexOf(it)).filter(function (x) { return isQuestion(x.type); });
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
  document.querySelectorAll('[data-add]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var it = blank(btn.dataset.add);
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
    if (el.dataset.ckey) { if (el.tagName === 'INPUT') { condChange(f, el); } return; }
    if (el.dataset.ctoggle || el.hasAttribute('data-reqmode')) { return; }
    if (el.dataset.key) {
      var key = el.dataset.key, val = el.value;
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
