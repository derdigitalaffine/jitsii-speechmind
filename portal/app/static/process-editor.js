/* Prozesseditor: Schritte als Liste (Ziehen zum Sortieren), Einstellungen des gewählten Schritts rechts. */
(function () {
  'use strict';
  var D = JSON.parse(document.getElementById('pe-data').textContent);
  var def = D.definition;
  var csrf = (document.querySelector('meta[name="csrf"]') || {}).content || document.querySelector('input[name="csrf"]').value;
  var listEl = document.getElementById('pe-steps'), panel = document.getElementById('pe-panel-body');
  var stateEl = document.getElementById('pe-state'), savebar = document.getElementById('pe-savebar');
  var selected = def.steps.length ? def.steps[0].id : 'end';
  var dirty = false, fieldEditor = null;

  var uid = function () { return Math.random().toString(16).slice(2, 10); };
  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  var keys = function (name) { return (D.order && D.order[name]) || Object.keys(D[name]); };
  var byId = function (list, id) { return (list || []).filter(function (x) { return String(x.id) === String(id); })[0]; };
  var stepIndex = function (id) { for (var i = 0; i < def.steps.length; i++) { if (def.steps[i].id === id) { return i; } } return -1; };
  var current = function () { return byId(def.steps, selected); };

  function markDirty() {
    dirty = true;
    savebar.classList.add('dirty');
    stateEl.textContent = 'Ungespeicherte Änderungen';
  }

  /* --- Neue Schritte ----------------------------------------------------- */
  function blank(type) {
    var s = { id: uid(), type: type, name: D.types[type][0], public_name: '', description: '', condition: null, status: '' };
    if (type === 'task' || type === 'approval') {
      s.assign = { mode: 'case' }; s.due_days = 5; s.escalate = { after_days: 0 }; s.goto = '';
    }
    if (type === 'task') { s.name = 'Prüfen'; s.checklist = ['Angaben vollständig']; s.fields = []; }
    if (type === 'approval') { s.name = 'Freigabe'; s.four_eyes = true; s.on_reject = 'end'; s.reject_status = 'rejected'; }
    if (type === 'request') {
      s.name = 'Unterlagen nachfordern'; s.public_name = 'Ergänzung Ihrer Angaben'; s.message = ''; s.due_days = 14;
      s.items = [{ id: uid(), type: 'file', title: 'Unterlagen', description: '', required: true, file_types: [], max_files: 3, max_size_mb: 10 }];
      s.reopen = []; s.status = 'query';
    }
    if (type === 'confirm') {
      s.name = 'E-Mail-Adresse bestätigen'; s.public_name = 'Bestätigung Ihrer E-Mail-Adresse'; s.message = '';
      s.due_days = 7; s.remind = true; s.on_expire = 'notify';
    }
    if (type === 'auto') {
      s.name = 'Antragsteller:in informieren';
      s.actions = [{ type: 'mail', to: 'applicant', subject: 'Ihr Antrag {aktenzeichen}', body: 'Guten Tag {name},\n\n…', attach: '' }];
    }
    return s;
  }

  /* --- Zusammenfassung je Schritt (linke Liste) ----------------------------- */
  function assignText(s) {
    var a = s.assign || {};
    if (s.type === 'confirm') { return 'Antragsteller:in (Link in der Mail)'; }
    if (s.type === 'request' && s.compose !== 'clerk') { return 'Antragsteller:in'; }
    if (s.type === 'auto') { return 'automatisch'; }
    if (a.mode === 'user') { var u = byId(D.users, a.user_id); return u ? u.name : 'Person fehlt!'; }
    if (a.mode === 'group') { var g = byId(D.groups, a.group_id); return g ? 'Gruppe ' + g.name : 'Gruppe fehlt!'; }
    return D.assignModes[a.mode || 'case'];
  }
  function condText(c) {
    if (!c) { return ''; }
    var key = c.source === 'step' ? ((byId(def.steps, c.key) || {}).name || '?') : c.key;
    var src = { q: '„' + key + '“', f: 'Feld „' + key + '“', step: 'Ergebnis „' + key + '“' }[c.source];
    return 'nur wenn ' + src + ' ' + D.ops[c.op] + (c.op === 'filled' || c.op === 'empty' ? '' : ' „' + c.value + '“');
  }
  function renderList() {
    var h = '<div class="pe-connector"><i class="fa-solid fa-inbox me-1"></i>Antrag geht ein</div><div class="pe-connector"><i class="fa-solid fa-arrow-down"></i></div><div id="pe-sortable">';
    def.steps.forEach(function (s, i) {
      var t = D.types[s.type];
      var chips = [];
      chips.push('<span><i class="fa-solid fa-user me-1"></i>' + esc(assignText(s)) + '</span>');
      if (s.due_days && s.type !== 'auto') { chips.push('<span><i class="fa-regular fa-clock me-1"></i>' + s.due_days + ' Tage</span>'); }
      if (s.public_name) { chips.push('<span title="Für Antragsteller:in sichtbar"><i class="fa-solid fa-eye me-1"></i>' + esc(s.public_name) + '</span>'); }
      if (s.type === 'task' && (s.checklist || []).length) { chips.push('<span><i class="fa-solid fa-list-check me-1"></i>' + s.checklist.length + '</span>'); }
      if (s.type === 'auto') { chips.push('<span><i class="fa-solid fa-bolt me-1"></i>' + (s.actions || []).map(function (a) { return D.actionTypes[a.type]; }).join(', ') + '</span>'); }
      var jump = '';
      if (s.goto) { jump = '<div class="small text-primary mt-1"><i class="fa-solid fa-turn-up me-1"></i>danach weiter mit „' + esc((byId(def.steps, s.goto) || {}).name) + '“</div>'; }
      if (s.type === 'approval' && s.on_reject && s.on_reject !== 'end') { jump += '<div class="small text-danger mt-1"><i class="fa-solid fa-rotate-left me-1"></i>bei Ablehnung zurück zu „' + esc((byId(def.steps, s.on_reject) || {}).name) + '“</div>'; }
      if (s.type === 'approval' && s.on_reject === 'end') { jump += '<div class="small text-danger mt-1"><i class="fa-solid fa-ban me-1"></i>bei Ablehnung: Ende (' + esc(D.statuses[s.reject_status || 'rejected']) + ')</div>'; }
      h += '<div class="card pe-step pe-' + s.type + (s.id === selected ? ' active' : '') + ' mb-0" data-id="' + esc(s.id) + '" tabindex="0" role="button" aria-pressed="' + (s.id === selected) + '">' +
        '<div class="card-body py-2 px-3 d-flex gap-2 align-items-start">' +
        '<span class="pe-icon"><i class="fa-solid ' + t[1] + '"></i></span>' +
        '<div class="flex-grow-1 min-w-0"><div class="d-flex align-items-center gap-2"><span class="small text-secondary">' + (i + 1) + '. ' + esc(t[0]) + '</span>' +
        '<span class="ms-auto drag-handle text-secondary px-1" title="Ziehen zum Verschieben"><i class="fa-solid fa-grip-vertical"></i></span></div>' +
        '<div class="fw-semibold text-truncate">' + esc(s.name) + '</div>' +
        (s.condition ? '<div class="small"><span class="badge text-bg-warning-subtle text-warning-emphasis border border-warning-subtle fw-normal text-wrap text-start"><i class="fa-solid fa-code-branch me-1"></i>' + esc(condText(s.condition)) + '</span></div>' : '') +
        '<div class="small text-secondary d-flex flex-wrap gap-3 mt-1">' + chips.join('') + '</div>' + jump +
        '</div></div></div><div class="pe-connector"><i class="fa-solid fa-arrow-down"></i></div>';
    });
    h += '</div>';
    h += '<div class="dropdown text-center mb-2"><button class="btn btn-sm btn-outline-primary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false"><i class="fa-solid fa-plus me-1"></i>Schritt hinzufügen</button><ul class="dropdown-menu"><li><h6 class="dropdown-header">' + (selected !== 'end' && current() ? 'wird nach „' + esc(current().name) + '“ eingefügt' : 'wird am Ende eingefügt') + '</h6></li>' +
      keys('types').map(function (k) {
        return '<li><button class="dropdown-item" type="button" data-add-step="' + k + '"><i class="fa-solid ' + D.types[k][1] + ' fa-fw me-2"></i><strong>' + D.types[k][0] + '</strong><div class="small text-secondary text-wrap" style="max-width: 20rem">' + esc(D.types[k][2]) + '</div></button></li>';
      }).join('') + '</ul></div><div class="pe-connector"><i class="fa-solid fa-arrow-down"></i></div>';
    h += '<div class="card pe-step' + (selected === 'end' ? ' active' : '') + '" data-id="end" tabindex="0" role="button" style="border-left-color: var(--bs-dark)"><div class="card-body py-2 px-3 d-flex gap-2 align-items-center">' +
      '<span class="pe-icon"><i class="fa-solid fa-flag-checkered"></i></span><div><div class="fw-semibold">Ende</div><div class="small text-secondary">Status: ' + esc(D.statuses[def.end_status]) + (def.end_inform ? ' · Antragsteller:in wird informiert' : '') + '</div></div></div></div>';
    listEl.innerHTML = h;
    if (window.Sortable) {
      Sortable.create(document.getElementById('pe-sortable'), {
        handle: '.drag-handle', draggable: '.pe-step', animation: 150,
        onEnd: function () {
          var ids = Array.prototype.map.call(document.querySelectorAll('#pe-sortable .pe-step'), function (el) { return el.dataset.id; });
          def.steps.sort(function (a, b) { return ids.indexOf(a.id) - ids.indexOf(b.id); });
          markDirty(); renderList();
        }
      });
    }
  }

  /* --- Einstellungen (rechts) -------------------------------------------- */
  function opt(value, label, sel) { return '<option value="' + esc(value) + '"' + (String(sel) === String(value) ? ' selected' : '') + '>' + esc(label) + '</option>'; }
  function sel(path, options, value, extra) {
    return '<select class="form-select form-select-sm" data-p="' + path + '" ' + (extra || '') + '>' + options.map(function (o) { return opt(o[0], o[1], value); }).join('') + '</select>';
  }
  function inp(path, value, attrs) { return '<input class="form-control form-control-sm" data-p="' + path + '" value="' + esc(value) + '" ' + (attrs || '') + '>'; }
  function area(path, value, rows, attrs) { return '<textarea class="form-control form-control-sm" data-p="' + path + '" rows="' + (rows || 3) + '" ' + (attrs || '') + '>' + esc(value) + '</textarea>'; }
  function sw(path, label, on, id) {
    id = id || 'sw-' + path.replace(/\W/g, '') + uid();
    return '<div class="form-check form-switch"><input class="form-check-input" type="checkbox" role="switch" id="' + id + '" data-p="' + path + '" data-bool="1"' + (on ? ' checked' : '') + '><label class="form-check-label" for="' + id + '">' + label + '</label></div>';
  }
  function lbl(text, html, cls, help) {
    return '<div class="' + (cls || 'col-12') + '"><label class="form-label small mb-1 fw-semibold">' + text + '</label>' + html + (help ? '<div class="form-text mt-0">' + help + '</div>' : '') + '</div>';
  }
  function section(title, icon, body) { return '<h3 class="h6 mt-4 mb-2 pb-1 border-bottom"><i class="fa-solid ' + icon + ' me-2 text-secondary"></i>' + title + '</h3>' + body; }
  var users = function () { return [['', '– Person wählen –']].concat(D.users.map(function (u) { return [u.id, u.name]; })); };
  var groups = function () { return [['', '– Gruppe wählen –']].concat(D.groups.map(function (g) { return [g.id, g.name]; })); };
  var statusOpts = function (empty) { return (empty ? [['', empty]] : []).concat(keys('statuses').map(function (k) { return [k, D.statuses[k]]; })); };
  var otherSteps = function (s, first) {
    return [['', first]].concat(def.steps.filter(function (x) { return x.id !== s.id; }).map(function (x) { return [x.id, (stepIndex(x.id) + 1) + '. ' + x.name]; }));
  };
  var placeholderHelp = '<details class="small mt-1"><summary class="text-secondary">Platzhalter</summary><div class="d-flex flex-wrap gap-1 mt-1">' +
    ['{aktenzeichen}', '{titel}', '{name}', '{eingang}', '{datum}', '{status}', '{bearbeiter}', '{statuslink}', '{gebuehr}', '{feld:schluessel}', '{frage:Titel der Frage}'].map(function (p) {
      return '<button type="button" class="btn btn-sm btn-light border font-monospace py-0" data-insert="' + esc(p) + '">' + esc(p) + '</button>';
    }).join('') + '</div><div class="text-secondary mt-1">Klick fügt den Platzhalter an der Cursorposition ein. {feld:…} sind interne Felder aus Aufgaben, {frage:…} Antworten aus dem Antrag.</div></details>';

  function fieldsBefore(s) {
    var out = [], idx = stepIndex(s.id);
    def.steps.slice(0, idx < 0 ? def.steps.length : idx).forEach(function (x) { (x.fields || []).forEach(function (f) { out.push([f.key, f.label + ' (' + x.name + ')']); }); });
    return out;
  }

  function conditionHtml(s) {
    var c = s.condition;
    var h = sw('cond_on', 'Nur unter einer Bedingung ausführen (sonst wird der Schritt übersprungen)', !!c, 'cond-on');
    if (!c) { return h; }
    var keyHtml;
    if (c.source === 'q') {
      keyHtml = '<input class="form-control form-control-sm" data-p="condition.key" value="' + esc(c.key) + '" list="pe-questions" placeholder="Titel der Frage">' +
        '<datalist id="pe-questions">' + D.questions.map(function (q) { return '<option value="' + esc(q) + '">'; }).join('') + '</datalist>';
    } else if (c.source === 'f') {
      var fs = fieldsBefore(s);
      keyHtml = fs.length ? sel('condition.key', [['', '– Feld wählen –']].concat(fs), c.key) : '<div class="small text-danger">Kein früherer Schritt erfasst interne Felder.</div>';
    } else {
      keyHtml = sel('condition.key', [['', '– Schritt wählen –']].concat(def.steps.slice(0, Math.max(stepIndex(s.id), 0)).filter(function (x) { return x.type !== 'auto'; }).map(function (x) { return [x.id, x.name]; })), c.key);
    }
    h += '<div class="row g-2 mt-1">' +
      lbl('Wenn', sel('condition.source', [['q', 'Antwort auf Antragsfrage'], ['f', 'Internes Feld'], ['step', 'Ergebnis eines Schritts']], c.source), 'col-sm-4') +
      lbl('&nbsp;', keyHtml, 'col-sm-8') +
      lbl('', sel('condition.op', keys('ops').map(function (k) { return [k, D.ops[k]]; }), c.op), 'col-sm-4') +
      (c.op === 'filled' || c.op === 'empty' ? '' : lbl('', c.source === 'step' ? sel('condition.value', [['genehmigt', 'genehmigt'], ['abgelehnt', 'abgelehnt'], ['erledigt', 'erledigt']], c.value) :
        inp('condition.value', c.value, 'placeholder="Wert, z. B. Ja oder 500"'), 'col-sm-8')) + '</div>';
    if (c.source === 'q' && !D.questions.length) { h += '<div class="form-text">Ordnen Sie den Prozess einem Antragsformular zu, dann werden dessen Fragen hier vorgeschlagen.</div>'; }
    return h;
  }

  function assignHtml(s, dueKey) {
    dueKey = dueKey || 'due_days';
    var a = s.assign || {}, e = s.escalate || {};
    var h = '<div class="row g-2">' + lbl('Zuständig', sel('assign.mode', keys('assignModes').map(function (k) { return [k, D.assignModes[k]]; }), a.mode || 'case'), 'col-sm-6');
    if (a.mode === 'user') { h += lbl('Person', sel('assign.user_id', users(), a.user_id || ''), 'col-sm-6'); }
    if (a.mode === 'group') { h += lbl('Gruppe', sel('assign.group_id', groups(), a.group_id || ''), 'col-sm-6', 'Alle Mitglieder sehen die Aufgabe und können sie übernehmen.'); }
    h += lbl('Bearbeitungsfrist', '<div class="input-group input-group-sm"><input class="form-control" type="number" min="0" max="365" data-p="' + dueKey + '" data-num="1" value="' + esc(s[dueKey] || 0) + '"><span class="input-group-text">Tage</span></div>', 'col-sm-6', '0 = keine Frist. Bei Überschreitung wird erinnert.');
    h += '</div><div class="row g-2 mt-1"><div class="col-12 small fw-semibold">Eskalation bei Fristüberschreitung (optional)</div>' +
      lbl('', sel('escalate.user_id', [['', '– Person –']].concat(D.users.map(function (u) { return [u.id, u.name]; })), e.user_id || ''), 'col-sm-4') +
      lbl('', sel('escalate.group_id', [['', '– Gruppe –']].concat(D.groups.map(function (g) { return [g.id, g.name]; })), e.group_id || ''), 'col-sm-4') +
      lbl('', '<div class="input-group input-group-sm"><span class="input-group-text">nach</span><input class="form-control" type="number" min="0" max="90" data-p="escalate.after_days" data-num="1" value="' + esc(e.after_days || 0) + '"><span class="input-group-text">Tagen</span></div>', 'col-sm-4') +
      '<div class="col-12">' + sw('escalate.reassign', 'Aufgabe dabei an die Vertretung übertragen (statt nur zu informieren)', e.reassign) + '</div></div>';
    return h;
  }

  function fieldsHtml(s) {
    var rows = (s.fields || []).map(function (f, i) {
      return '<div class="row g-1 align-items-center mb-1" data-field="' + i + '">' +
        '<div class="col-sm-4">' + inp('fields.' + i + '.label', f.label, 'placeholder="Bezeichnung, z. B. Gebühr"') + '</div>' +
        '<div class="col-sm-3">' + sel('fields.' + i + '.type', keys('fieldTypes').map(function (k) { return [k, D.fieldTypes[k]]; }), f.type) + '</div>' +
        '<div class="col-sm-3"><div class="input-group input-group-sm" title="Platzhalter in Mails und Bescheiden: {feld:' + esc(f.key) + '}"><span class="input-group-text font-monospace px-1">{feld:</span>' +
          '<input class="form-control font-monospace px-1" data-p="fields.' + i + '.key" value="' + esc(f.key) + '" maxlength="40" aria-label="Schlüssel des Feldes"><span class="input-group-text font-monospace px-1">}</span></div>' +
          (f.type === 'select' ? inp('fields.' + i + '.options', (f.options || []).join('; '), 'placeholder="Optionen; getrennt" class="mt-1"') : '') + '</div>' +
        '<div class="col-sm-1">' + sw('fields.' + i + '.required', '<span class="visually-hidden">Pflicht</span>', f.required) + '</div>' +
        '<div class="col-sm-1 text-end"><button type="button" class="btn btn-sm btn-link text-danger" data-del-field="' + i + '" title="Feld entfernen" aria-label="Feld entfernen"><i class="fa-solid fa-xmark"></i></button></div></div>';
    }).join('');
    var head = rows ? '<div class="row g-1 small text-secondary"><div class="col-sm-4">Bezeichnung</div><div class="col-sm-3">Art</div><div class="col-sm-3">Platzhalter / Optionen</div><div class="col-sm-2">Pflicht</div></div>' : '';
    return head + (rows || '<div class="small text-secondary mb-1">Keine internen Felder.</div>') +
      '<button type="button" class="btn btn-sm btn-outline-secondary" data-add-field><i class="fa-solid fa-plus me-1"></i>Feld</button>' +
      '<div class="form-text">Werte stehen im Vorgang, in Bedingungen späterer Schritte und als {feld:…} in Mails und Bescheiden zur Verfügung. Der Platzhalter ist frei wählbar (Kleinbuchstaben, Ziffern, _); vorgeschlagen wird die nächste freie Nummer. Schalter = Pflichtfeld.</div>';
  }

  function actionsHtml(s) {
    var h = (s.actions || []).map(function (a, i) {
      var p = 'actions.' + i + '.', body = '';
      if (a.type === 'mail') {
        body = '<div class="row g-2">' + lbl('An', sel(p + 'to', keys('mailTargets').map(function (k) { return [k, D.mailTargets[k]]; }), a.to), 'col-sm-5') +
          (a.to === 'email' ? lbl('Adresse', inp(p + 'email', a.email, 'type="email" placeholder="poststelle@…"'), 'col-sm-7') : '') +
          lbl('Betreff', inp(p + 'subject', a.subject), 'col-12') + lbl('Text', area(p + 'body', a.body, 5, 'data-ph="1"'), 'col-12') +
          lbl('Anhang', sel(p + 'attach', [['', 'kein Anhang'], ['application', 'Antrag als PDF'], ['documents', 'Alle erzeugten Dokumente']], a.attach || ''), 'col-sm-6') + '</div>';
      } else if (a.type === 'status') {
        body = '<div class="row g-2">' + lbl('Neuer Status', sel(p + 'status', statusOpts(), a.status), 'col-sm-6') +
          '<div class="col-sm-6 d-flex align-items-end">' + sw(p + 'inform', 'Antragsteller:in per Mail informieren', a.inform) + '</div>' +
          lbl('Mitteilung', area(p + 'message', a.message, 2, 'data-ph="1"'), 'col-12') + '</div>';
      } else if (a.type === 'pdf') {
        body = '<div class="row g-2">' + lbl('Titel', inp(p + 'title', a.title, 'placeholder="z. B. Bescheid"'), 'col-sm-6') +
          '<div class="col-sm-6 d-flex flex-column justify-content-end">' + sw(p + 'public', 'Auf der Statusseite abrufbar', a.public) + sw(p + 'send', 'Per Mail an Antragsteller:in', a.send) + '</div>' +
          lbl('Text des Dokuments', area(p + 'body', a.body, 8, 'data-ph="1"'), 'col-12', 'Leerzeile = neuer Absatz. Briefkopf, Anschrift, Datum und Aktenzeichen setzt das Portal selbst.') + '</div>';
      } else if (a.type === 'assign') {
        body = '<div class="row g-2">' + lbl('Person', sel(p + 'user_id', users(), a.user_id || ''), 'col-sm-6') + lbl('Gruppe', sel(p + 'group_id', groups(), a.group_id || ''), 'col-sm-6') + '</div>';
      }
      return '<div class="card mb-2"><div class="card-header py-1 d-flex align-items-center small"><strong>' + (i + 1) + '. ' + esc(D.actionTypes[a.type]) + '</strong>' +
        '<button type="button" class="btn btn-sm btn-link text-danger ms-auto" data-del-action="' + i + '">Entfernen</button></div><div class="card-body py-2">' + body + '</div></div>';
    }).join('');
    return h + '<div class="d-flex flex-wrap gap-1">' + keys('actionTypes').map(function (k) {
      return '<button type="button" class="btn btn-sm btn-outline-success" data-add-action="' + k + '"><i class="fa-solid fa-plus me-1"></i>' + esc(D.actionTypes[k]) + '</button>';
    }).join('') + '</div>' + placeholderHelp;
  }

  function renderPanel() {
    fieldEditor = null;
    if (selected === 'end') {
      panel.innerHTML = '<h2 class="h5"><i class="fa-solid fa-flag-checkered me-2"></i>Ende des Prozesses</h2><p class="small text-secondary">Wenn alle Schritte durchlaufen sind (und der Vorgang nicht schon vorher, z. B. durch eine Ablehnung, abgeschlossen wurde).</p>' +
        '<div class="row g-2">' + lbl('Abschluss-Status', sel('end_status', D.closed.map(function (k) { return [k, D.statuses[k]]; }), def.end_status), 'col-sm-6') +
        '<div class="col-sm-6 d-flex align-items-end">' + sw('end_inform', 'Antragsteller:in per Mail informieren', def.end_inform) + '</div>' +
        lbl('Mitteilung', area('end_message', def.end_message, 3, 'data-ph="1" placeholder="z. B. Ihr Antrag ist abschließend bearbeitet. Den Bescheid finden Sie auf Ihrer Antragsseite."'), 'col-12') + '</div>' + placeholderHelp;
      return;
    }
    var s = current();
    if (!s) { panel.innerHTML = '<p class="text-secondary">Fügen Sie links den ersten Schritt hinzu.</p>'; return; }
    var t = D.types[s.type];
    var h = '<div class="d-flex align-items-start gap-2 mb-2"><span class="pe-icon fs-5"><i class="fa-solid ' + t[1] + '"></i></span><div class="flex-grow-1"><div class="small text-secondary">Schritt ' + (stepIndex(s.id) + 1) + ' · ' + esc(t[0]) + '</div><div class="small text-secondary">' + esc(t[2]) + '</div></div>' +
      '<div class="btn-group btn-group-sm"><button type="button" class="btn btn-outline-secondary" data-dup-step title="Duplizieren" aria-label="Duplizieren"><i class="fa-regular fa-clone"></i></button>' +
      '<button type="button" class="btn btn-outline-danger" data-del-step title="Schritt löschen" aria-label="Schritt löschen"><i class="fa-regular fa-trash-can"></i></button></div></div>';
    h += '<div class="row g-2">' + lbl('Name (intern)', inp('name', s.name, 'maxlength="200"'), 'col-sm-6') +
      lbl('Name für Antragsteller:in', inp('public_name', s.public_name, 'maxlength="200" placeholder="leer = Schritt nicht anzeigen"'), 'col-sm-6', 'Erscheint im Fortschritt auf der Statusseite.') +
      (s.type === 'auto' ? '' : lbl(s.type === 'request' ? 'Interner Hinweis' : 'Anleitung für die Bearbeitung', area('description', s.description, 2, 'placeholder="Was ist in diesem Schritt zu tun? Worauf achten?"'), 'col-12')) +
      lbl('Status beim Start des Schritts', sel('status', statusOpts('– unverändert –'), s.status), 'col-sm-6') + '</div>';

    if (s.type === 'task') {
      h += section('Prüfpunkte', 'fa-list-check', area('checklist', (s.checklist || []).join('\n'), 4, 'placeholder="Ein Prüfpunkt je Zeile"') + '<div class="form-text">Ein Punkt je Zeile. Erst wenn alle abgehakt sind, lässt sich der Schritt erledigen.</div>');
      h += section('Interne Felder', 'fa-table-list', fieldsHtml(s));
    }
    if (s.type === 'approval') {
      h += section('Freigabe', 'fa-stamp', sw('four_eyes', 'Vier-Augen-Prinzip: wer den vorigen Schritt erledigt hat, darf nicht freigeben', s.four_eyes) +
        '<div class="row g-2 mt-1">' + lbl('Bei Ablehnung', sel('on_reject', [['end', 'Vorgang beenden']].concat(def.steps.filter(function (x) { return x.id !== s.id; }).map(function (x) { return [x.id, 'zurück zu: ' + (stepIndex(x.id) + 1) + '. ' + x.name]; })), s.on_reject || 'end'), 'col-sm-6') +
        (s.on_reject === 'end' ? lbl('Status bei Ablehnung', sel('reject_status', statusOpts(), s.reject_status || 'rejected'), 'col-sm-6') : '') + '</div>');
    }
    if (s.type === 'task' || s.type === 'approval') {
      h += section('Zuständigkeit & Frist', 'fa-user-tie', assignHtml(s));
      h += section('Danach', 'fa-arrow-right', sel('goto', otherSteps(s, 'weiter mit dem nächsten Schritt'), s.goto || '') + '<div class="form-text">Für Schleifen oder um Schritte zu überspringen' + (s.type === 'approval' ? ' (nach der Genehmigung)' : '') + '.</div>');
    }
    if (s.type === 'request') {
      h += section('Wer legt fest, was nachgefordert wird?', 'fa-user-pen', sel('compose', [['auto', 'Fest im Prozess – wird automatisch verschickt'], ['clerk', 'Sachbearbeitung wählt beim Erreichen des Schritts']], s.compose || 'auto') +
        '<div class="form-text">Bei „Sachbearbeitung wählt“ bekommt die zuständige Person eine Aufgabe mit dem Nachforderungs-Dialog: die Felder unten sind vorgeschlagen, Vorlagen und eigene Felder lassen sich ergänzen.</div>' +
        (s.compose === 'clerk' ? '<div class="mt-2">' + assignHtml(s, 'compose_days').replace('Bearbeitungsfrist', 'Frist zum Zusammenstellen') + '</div>' : ''));
      h += section('Nachforderung', 'fa-file-circle-question', '<div class="row g-2">' +
        lbl('Nachricht an die antragstellende Person', area('message', s.message, 3, 'data-ph="1" placeholder="z. B. Bitte reichen Sie einen aktuellen Lageplan ein."'), 'col-12') +
        lbl('Frist zum Nachreichen', '<div class="input-group input-group-sm"><input class="form-control" type="number" min="1" max="365" data-p="due_days" data-num="1" value="' + esc(s.due_days || 14) + '"><span class="input-group-text">Tage</span></div>', 'col-sm-5', 'Nach Ablauf wird einmal erinnert.') + '</div>' +
        (D.templates.length ? '<div class="mt-2"><select class="form-select form-select-sm w-auto d-inline-block" data-load-template aria-label="Vorlage übernehmen"><option value="">Felder aus Vorlage übernehmen …</option>' + D.templates.map(function (x) { return '<option value="' + x.id + '">' + esc(x.name) + '</option>'; }).join('') + '</select></div>' : '') +
        '<div class="d-flex align-items-center mt-3 mb-1"><span class="fw-semibold small">' + (s.compose === 'clerk' ? 'Vorgeschlagene Felder' : 'Abgefragte Felder') + '</span>' +
        '<button type="button" class="btn btn-sm btn-link ms-auto" data-save-template title="Felder und Nachricht als Vorlage für Nachforderungen speichern"><i class="fa-regular fa-bookmark me-1"></i>Als Vorlage speichern</button></div><div id="pe-req-fields"></div>' +
        '<div class="fw-semibold small mt-3 mb-1">Antragsfragen zur Korrektur öffnen</div>' +
        (D.questions.length ? '<div class="row row-cols-1 row-cols-sm-2 g-1">' + D.questions.map(function (q, i) {
          return '<div class="col"><div class="form-check"><input class="form-check-input" type="checkbox" id="ro' + i + '" data-reopen value="' + esc(q) + '"' + ((s.reopen || []).indexOf(q) >= 0 ? ' checked' : '') + '><label class="form-check-label small" for="ro' + i + '">' + esc(q) + '</label></div></div>';
        }).join('') + '</div>' : '<div class="small text-secondary">Sobald ein Antragsformular den Prozess nutzt, erscheinen hier seine Fragen.</div>') +
        '<div class="form-text">Der Prozess wartet, bis die Angaben eingehen; der Status steht währenddessen auf „Rückfrage“.</div>' + placeholderHelp);
    }
    if (s.type === 'confirm') {
      h += section('Double-Opt-in', 'fa-envelope-circle-check', '<div class="row g-2">' +
        lbl('Zusätzlicher Hinweis in der Mail (optional)', area('message', s.message, 2, 'data-ph="1"'), 'col-12', 'Die Mail enthält immer den Bestätigungslink, Aktenzeichen und Frist.') +
        lbl('Frist zum Bestätigen', '<div class="input-group input-group-sm"><input class="form-control" type="number" min="1" max="60" data-p="due_days" data-num="1" value="' + esc(s.due_days || 7) + '"><span class="input-group-text">Tage</span></div>', 'col-sm-5') +
        '<div class="col-sm-7 d-flex align-items-end">' + sw('remind', 'Nach der Hälfte der Frist einmal erinnern', s.remind !== false) + '</div>' +
        lbl('Wenn nicht bestätigt wird', sel('on_expire', keys('expireActions').map(function (k) { return [k, D.expireActions[k]]; }), s.on_expire || 'notify'), 'col-12') + '</div>' +
        '<div class="form-text">Der Prozess hält an, bis der Link angeklickt wurde. Die Sachbearbeitung kann im Vorgang den Link erneut senden oder ohne Bestätigung fortfahren.</div>');
    }
    if (s.type === 'auto') {
      h += section('Aktionen', 'fa-bolt', actionsHtml(s));
    }
    h += section('Bedingung', 'fa-code-branch', conditionHtml(s));
    panel.innerHTML = h;
    if (s.type === 'request' && window.FieldList) {
      fieldEditor = FieldList.mount(document.getElementById('pe-req-fields'), {
        types: D.requestTypes, subtypes: D.subtypes, order: { types: D.order.requestTypes, subtypes: D.order.subtypes }, items: s.items || [],
        onChange: function (list) { s.items = list; markDirty(); renderList(); }
      });
    }
  }

  function render() { renderList(); renderPanel(); }

  /* --- Werte übernehmen ---------------------------------------------------- */
  function setPath(obj, path, value) {
    var parts = path.split('.'), o = obj;
    for (var i = 0; i < parts.length - 1; i++) {
      var k = /^\d+$/.test(parts[i]) ? +parts[i] : parts[i];
      if (o[k] == null) { o[k] = {}; }
      o = o[k];
    }
    o[parts[parts.length - 1]] = value;
  }
  function readValue(el) {
    if (el.dataset.bool) { return el.checked; }
    if (el.dataset.num) { return parseInt(el.value, 10) || 0; }
    return el.value;
  }
  // Änderungen, die den Aufbau des Panels verändern → neu zeichnen
  var STRUCTURAL = /^(compose|assign\.mode|condition\.source|condition\.op|on_reject|cond_on|actions\.\d+\.to|fields\.\d+\.type)$/;

  function onInput(ev) {
    var el = ev.target, p = el.dataset.p;
    if (el.hasAttribute('data-reopen')) {
      var s0 = current();
      s0.reopen = Array.prototype.filter.call(panel.querySelectorAll('[data-reopen]'), function (x) { return x.checked; }).map(function (x) { return x.value; });
      markDirty(); return;
    }
    if (!p) { return; }
    var target = selected === 'end' ? def : current();
    var value = readValue(el);
    if (p === 'cond_on') {
      target.condition = value ? { source: D.questions.length ? 'q' : 'f', key: D.questions[0] || '', op: 'eq', value: '' } : null;
    } else if (p === 'checklist') {
      target.checklist = el.value.split('\n').map(function (x) { return x.trim(); }).filter(Boolean);
    } else if (/^fields\.\d+\.options$/.test(p)) {
      setPath(target, p, el.value.split(';').map(function (x) { return x.trim(); }).filter(Boolean));
    } else if (/^fields\.\d+\.key$/.test(p)) {
      setPath(target, p, value.toLowerCase().replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss').replace(/[^a-z0-9_]/g, '').slice(0, 40));
    } else if (/^fields\.\d+\.label$/.test(p)) {
      setPath(target, p, value);
      var f = target.fields[+p.split('.')[1]];
      if (!f.key) { var u2 = {}; def.steps.forEach(function (x) { (x.fields || []).forEach(function (g) { u2[g.key] = 1; }); }); var m = 1; while (u2[String(m)]) { m++; } f.key = String(m); }
    } else if (/(user_id|group_id)$/.test(p)) {
      setPath(target, p, value ? parseInt(value, 10) : null);
    } else {
      setPath(target, p, value);
    }
    if (p === 'condition.source' && target.condition) { target.condition.key = ''; target.condition.value = ''; }
    markDirty();
    if (ev.type === 'change' && STRUCTURAL.test(p)) { renderPanel(); }
    renderList();
  }
  panel.addEventListener('input', onInput);
  panel.addEventListener('change', function (ev) {
    if (ev.target.hasAttribute('data-load-template')) {
      var tpl = byId(D.templates, ev.target.value);
      if (tpl && fieldEditor) {
        var s = current();
        if (!s.message) { s.message = tpl.message; }
        s.due_days = tpl.due_days || s.due_days;
        fieldEditor.set((s.items || []).concat(tpl.items));
        renderPanel();
      }
      return;
    }
    if (ev.target.tagName === 'SELECT' || ev.target.type === 'checkbox') { onInput(ev); }
  });

  var lastText = null;
  panel.addEventListener('focusin', function (ev) { if (ev.target.matches('textarea, input[type="text"], input:not([type])')) { lastText = ev.target; } });
  panel.addEventListener('click', function (ev) {
    var b = ev.target.closest('button');
    if (!b) { return; }
    var s = current();
    if (b.dataset.insert) {
      var t = lastText && panel.contains(lastText) ? lastText : panel.querySelector('[data-ph]');
      if (t) {
        var pos = t.selectionStart || t.value.length;
        t.value = t.value.slice(0, pos) + b.dataset.insert + t.value.slice(t.selectionEnd || pos);
        t.focus(); t.selectionStart = t.selectionEnd = pos + b.dataset.insert.length;
        t.dispatchEvent(new Event('input', { bubbles: true }));
      }
    } else if (b.hasAttribute('data-save-template')) {
      var nm = window.prompt('Name der Vorlage:', s.public_name || s.name);
      if (!nm) { return; }
      var body = new URLSearchParams();
      body.append('csrf', csrf); body.append('action', 'save'); body.append('name', nm); body.append('message', s.message || '');
      body.append('due_days', s.due_days || 14); body.append('items_json', JSON.stringify(s.items || []));
      fetch('/processes/templates', { method: 'POST', body: body, credentials: 'same-origin' }).then(function (r) {
        if (r.ok) { D.templates.push({ id: 'neu', name: nm, message: s.message, items: s.items, due_days: s.due_days }); stateEl.textContent = 'Vorlage „' + nm + '“ gespeichert'; renderPanel(); }
      });
    } else if (b.hasAttribute('data-add-field')) {
      var used = {};
      def.steps.forEach(function (x) { (x.fields || []).forEach(function (f) { used[f.key] = 1; }); });
      var n = 1; while (used[String(n)]) { n++; }
      s.fields = s.fields || []; s.fields.push({ key: String(n), label: '', type: 'text', options: [], required: false, _fixed: true });
      markDirty(); renderPanel();
      var inputs = panel.querySelectorAll('[data-p$=".label"]'); if (inputs.length) { inputs[inputs.length - 1].focus(); }
    } else if (b.dataset.delField) {
      s.fields.splice(+b.dataset.delField, 1); markDirty(); renderPanel(); renderList();
    } else if (b.dataset.addAction) {
      var k = b.dataset.addAction, a = { type: k };
      if (k === 'mail') { a.to = 'applicant'; a.subject = 'Ihr Antrag {aktenzeichen}'; a.body = 'Guten Tag {name},\n\n'; a.attach = ''; }
      if (k === 'status') { a.status = 'in_progress'; a.inform = false; a.message = ''; }
      if (k === 'pdf') { a.title = 'Bescheid'; a.public = true; a.send = true; a.body = 'Sehr geehrte/r {name},\n\nzu Ihrem Antrag „{titel}“ vom {eingang} …\n\nMit freundlichen Grüßen\n{bearbeiter}'; }
      s.actions = s.actions || []; s.actions.push(a); markDirty(); render();
    } else if (b.dataset.delAction) {
      s.actions.splice(+b.dataset.delAction, 1); markDirty(); render();
    } else if (b.hasAttribute('data-del-step')) {
      var go = function () {
        var i = stepIndex(s.id);
        def.steps.splice(i, 1);
        def.steps.forEach(function (x) {   // Verweise auf den gelöschten Schritt aufräumen
          if (x.goto === s.id) { x.goto = ''; }
          if (x.on_reject === s.id) { x.on_reject = 'end'; }
          if (x.condition && x.condition.source === 'step' && x.condition.key === s.id) { x.condition = null; }
        });
        selected = def.steps.length ? def.steps[Math.min(i, def.steps.length - 1)].id : 'end';
        markDirty(); render();
      };
      if (window.Swal) {
        Swal.fire({ title: 'Schritt löschen?', text: '„' + s.name + '“ wird aus dem Entwurf entfernt.', icon: 'warning', showCancelButton: true,
          confirmButtonText: 'Löschen', cancelButtonText: 'Abbrechen', confirmButtonColor: '#dc3545' }).then(function (r) { if (r.isConfirmed) { go(); } });
      } else if (confirm('Schritt löschen?')) { go(); }
    } else if (b.hasAttribute('data-dup-step')) {
      var copy = JSON.parse(JSON.stringify(s)); copy.id = uid(); copy.name = s.name + ' (Kopie)';
      def.steps.splice(stepIndex(s.id) + 1, 0, copy); selected = copy.id; markDirty(); render();
    }
  });

  listEl.addEventListener('click', function (ev) {
    var add = ev.target.closest('[data-add-step]');
    if (add) {
      var s = blank(add.dataset.addStep), at = stepIndex(selected);
      def.steps.splice(at < 0 ? def.steps.length : at + 1, 0, s); selected = s.id; markDirty(); render();
      var name = panel.querySelector('[data-p="name"]'); if (name) { name.focus(); name.select(); }
      return;
    }
    var card = ev.target.closest('.pe-step');
    if (card && !ev.target.closest('.drag-handle')) { selected = card.dataset.id; render(); if (window.innerWidth < 992) { document.getElementById('pe-panel').scrollIntoView({ behavior: 'smooth' }); } }
  });
  listEl.addEventListener('keydown', function (ev) {
    var card = ev.target.closest('.pe-step');
    if (card && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); selected = card.dataset.id; render(); }
  });

  /* --- Speichern, Veröffentlichen ------------------------------------------ */
  ['pe-name', 'pe-desc'].forEach(function (id) { document.getElementById(id).addEventListener('input', markDirty); });

  function showHints(hints) {
    var box = document.getElementById('pe-hints'), ul = document.getElementById('pe-hint-list');
    ul.innerHTML = hints.map(function (h) { return '<li>' + esc(h) + '</li>'; }).join('');
    box.classList.toggle('d-none', !hints.length);
    return hints;
  }
  function save() {
    var body = new URLSearchParams();
    body.append('csrf', csrf);
    body.append('name', document.getElementById('pe-name').value);
    body.append('description', document.getElementById('pe-desc').value);
    body.append('definition', JSON.stringify(def, function (k, v) { return k === '_fixed' ? undefined : v; }));
    stateEl.textContent = 'Speichere …';
    return fetch(location.pathname + '/save', { method: 'POST', body: body, credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.ok) { throw new Error(data.error || 'Fehler'); }
        // Schlüssel der internen Felder kommen bereinigt zurück – übernehmen und festhalten
        data.definition.steps.forEach(function (srv) {
          var mine = byId(def.steps, srv.id);
          if (mine && srv.fields) { mine.fields = srv.fields.map(function (f) { f._fixed = true; return f; }); }
        });
        dirty = false; savebar.classList.remove('dirty');
        stateEl.textContent = data.changed ? 'Gespeichert – noch nicht veröffentlicht' : 'Gespeichert';
        showHints(data.hints);
        renderList();
        return data;
      })
      .catch(function (e) { stateEl.textContent = 'Speichern fehlgeschlagen: ' + e.message; throw e; });
  }
  document.getElementById('pe-save').addEventListener('click', function () { save(); });
  document.addEventListener('keydown', function (ev) {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === 's') { ev.preventDefault(); save(); }
  });
  var modal = document.getElementById('pe-publish');
  document.getElementById('pe-publish-open').addEventListener('click', function () {
    save().then(function (data) {
      var hb = document.getElementById('pe-publish-hints');
      hb.innerHTML = data.hints.length ? '<strong>Bitte vorher prüfen:</strong><ul class="mb-0 ps-3">' + data.hints.map(function (h) { return '<li>' + esc(h) + '</li>'; }).join('') + '</ul>' : '';
      hb.classList.toggle('d-none', !data.hints.length);
      bootstrap.Modal.getOrCreateInstance(modal).show();
    });
  });
  window.addEventListener('beforeunload', function (ev) { if (dirty) { ev.preventDefault(); ev.returnValue = ''; } });
  document.getElementById('pe-publish-form').addEventListener('submit', function () { dirty = false; });

  (def.steps || []).forEach(function (s) { (s.fields || []).forEach(function (f) { f._fixed = true; }); });
  render();
})();
