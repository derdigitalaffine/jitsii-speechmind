/* Formular ausfüllen: Seiten mit Schrittleiste und Prüfung je Seite, Bedingungen (anzeigen/Pflicht),
   Übersicht vor dem Absenden, Entwurf im Browser, „Sonstiges“, Dateigrößen. Ohne JS: alle Seiten untereinander. */
(function () {
  'use strict';
  var form = document.querySelector('form.js-fill');
  if (!form) { return; }
  var pages = Array.prototype.slice.call(form.querySelectorAll('.fill-page'));
  var prev = form.querySelector('.js-prev'), next = form.querySelector('.js-next'), submit = form.querySelector('.js-submit');
  var reviewBox = form.querySelector('.fill-review'), hasReview = !!reviewBox && form.dataset.review === '1';
  var steps = Array.prototype.slice.call(form.querySelectorAll('.fill-step'));
  var current = Math.min(parseInt(form.dataset.start || '0', 10), pages.length - 1);
  var reached = current, inReview = false;
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };

  function focusQuestion(qid) {
    var question = document.getElementById('frage-' + qid);
    if (!question) { return; }
    var page = question.closest('.fill-page'), index = pages.indexOf(page);
    if (index >= 0 && !page._hidden) { show(index); }
    var target = Array.prototype.slice.call(question.querySelectorAll('input, select, textarea, button')).find(function (el) {
      return !el.disabled && el.type !== 'hidden' && !el.closest('.d-none') && el.getClientRects().length;
    }) || question;
    target.focus();
    target.scrollIntoView({block: 'center', behavior: 'smooth'});
  }
  form.querySelectorAll('[data-server-error]').forEach(function (question) {
    question.querySelectorAll('input, select, textarea').forEach(function (el) {
      if (el.type === 'hidden') { return; }
      el.setAttribute('aria-invalid', 'true');
      var ids = (el.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
      if (ids.indexOf(question.dataset.serverError) < 0) { ids.push(question.dataset.serverError); }
      el.setAttribute('aria-describedby', ids.join(' '));
    });
  });
  form.addEventListener('click', function (ev) {
    var link = ev.target.closest('[data-form-error]');
    if (link) { ev.preventDefault(); focusQuestion(link.dataset.formError); }
  });

  /* --- Bedingungen ------------------------------------------------------------ */
  function valueOf(qid) {
    var els = form.querySelectorAll('[name="q_' + qid + '"]');
    var vals = [];
    Array.prototype.forEach.call(els, function (el) {
      if (el.disabled) { return; }
      if (el.type === 'checkbox' || el.type === 'radio') {
        if (el.checked) { vals.push(el.value === '__other__' ? (form.querySelector('[name="q_' + qid + '__other"]') || {}).value || '' : el.value); }
      } else if (el.type === 'file') {
        Array.prototype.forEach.call(el.files || [], function (f) { vals.push(f.name); });
      } else if (el.value) { vals.push(el.value); }
    });
    var addr = form.querySelector('.fill-item[data-qid="' + qid + '"] .js-address');
    if (addr) {   // Adresse: alle Teilfelder als Text
      Array.prototype.forEach.call(addr.querySelectorAll('input[name^="q_' + qid + '__"]'), function (el) { if (el.value && el.type !== 'hidden') { vals.push(el.value); } });
    }
    return vals.map(function (v) { return String(v).trim().toLowerCase(); }).filter(Boolean);
  }
  function met(cond) {
    if (!cond) { return true; }
    var res = cond.rules.map(function (r) {
      var texts = valueOf(r.q), t = String(r.value || '').trim().toLowerCase();
      switch (r.op) {
        case 'filled': return texts.length > 0;
        case 'empty': return texts.length === 0;
        case 'eq': return texts.indexOf(t) >= 0;
        case 'ne': return texts.indexOf(t) < 0;
        case 'contains': return texts.some(function (x) { return x.indexOf(t) >= 0; });
        default:
          var a = parseFloat((texts[0] || '').replace(',', '.')), b = parseFloat(t.replace(',', '.'));
          if (isNaN(a) || isNaN(b)) { return false; }
          return r.op === 'gt' ? a > b : a < b;
      }
    });
    return cond.mode === 'any' ? res.some(Boolean) : res.every(Boolean);
  }
  function setRequired(item, on) {
    item.querySelectorAll('input, select, textarea').forEach(function (el) {
      if (el.type === 'hidden' || el.classList.contains('js-other')) { return; }
      if (el.type === 'checkbox') { return; }   // Mehrfachauswahl prüft die Gruppe
      if (el.type === 'radio') { el.required = on; return; }
      if (el.closest('.js-table')) { return; }
      if (!el.closest('.js-address') || el.dataset.partRequired) { el.required = on; }
    });
    var table = item.querySelector('.js-table');
    if (table) { table.dataset.required = on ? '1' : ''; }
    var group = item.querySelector('.js-check-group');
    if (group) { if (on) { group.dataset.required = '1'; } else { delete group.dataset.required; } }
    var geo = item.querySelector('.js-geo-value');
    if (geo) { if (on) { geo.dataset.required = '1'; } else { delete geo.dataset.required; } }
    var label = item.querySelector('.form-label');
    if (label) {
      var star = label.querySelector('.req');
      if (on && !star) { label.insertAdjacentHTML('beforeend', ' <span class="req" title="Pflichtfeld">*</span>'); }
      if (!on && star) { star.remove(); }
    }
  }
  var condItems = Array.prototype.slice.call(form.querySelectorAll('.fill-item[data-show-if], .fill-item[data-show-if2], .fill-item[data-required-if]'));
  var condPages = pages.filter(function (p) { return p.dataset.showIf; });
  function parse(s) { try { return JSON.parse(s); } catch (e) { return null; } }
  condItems.forEach(function (el) { el._show = parse(el.dataset.showIf); el._show2 = parse(el.dataset.showIf2); el._req = parse(el.dataset.requiredIf); });
  condPages.forEach(function (p) { p._show = parse(p.dataset.showIf); });
  function applyConditions() {
    condPages.forEach(function (p) { p._hidden = !met(p._show); });
    condItems.forEach(function (el) {
      if (el._show || el._show2) {
        var show = met(el._show) && met(el._show2);
        el.classList.toggle('d-none', !show);
        el.querySelectorAll('input, select, textarea').forEach(function (x) { x.disabled = !show; });
      }
      if (el._req) { setRequired(el, met(el._req)); }
    });
    pages.forEach(function (p) {   // ganze Seite ausgeblendet: Felder nicht absenden
      if (p._show) { p.querySelectorAll('input, select, textarea').forEach(function (x) { if (!x.closest('.fill-item.d-none')) { x.disabled = !!p._hidden; } }); }
    });
    updateSteps();
  }
  var visiblePages = function () { return pages.map(function (p, i) { return i; }).filter(function (i) { return !pages[i]._hidden; }); };

  /* --- Seiten und Schrittleiste -------------------------------------------------- */
  function updateSteps() {
    var vis = visiblePages();
    steps.forEach(function (li) {
      var s = li.dataset.step, btn = li.querySelector('button');
      if (s === 'review') { li.classList.toggle('is-current', inReview); return; }
      var i = parseInt(s, 10);
      li.classList.toggle('d-none', !!pages[i]._hidden);
      li.classList.toggle('is-current', !inReview && i === current);
      li.classList.toggle('is-done', i < current || inReview);
      btn.disabled = i > reached || i === current && !inReview;
      var label = li.querySelector('.fill-step-no');
      if (label) { label.textContent = vis.indexOf(i) + 1; }
    });
  }
  function nextIndex(from, dir) {
    for (var i = from + dir; i >= 0 && i < pages.length; i += dir) { if (!pages[i]._hidden) { return i; } }
    return -1;
  }
  function show(i) {
    inReview = false;
    current = i;
    reached = Math.max(reached, i);
    if (reviewBox) { reviewBox.classList.add('d-none'); }
    pages.forEach(function (p, n) { p.classList.toggle('d-none', n !== i); });
    var last = nextIndex(i, 1) < 0;
    prev.classList.toggle('d-none', nextIndex(i, -1) < 0);
    next.classList.toggle('d-none', last && !hasReview);
    submit.classList.toggle('d-none', !last || hasReview);
    next.innerHTML = last && hasReview ? 'Weiter zur Übersicht<i class="fa-solid fa-arrow-right ms-1"></i>' : 'Weiter<i class="fa-solid fa-arrow-right ms-1"></i>';
    updateSteps();
  }
  function fieldText(item) {
    var parts = [];
    item.querySelectorAll('input, select, textarea').forEach(function (el) {
      if (el.disabled || el.type === 'hidden' || el.type === 'button') { return; }
      if ((el.type === 'checkbox' || el.type === 'radio') && !el.checked) { return; }
      if (el.type === 'checkbox' || el.type === 'radio') {
        if (el.value === '__other__') { return; }
        var l = form.querySelector('label[for="' + el.id + '"]');
        parts.push(l ? l.textContent.trim() : el.value);
      } else if (el.type === 'file') {
        Array.prototype.forEach.call(el.files, function (f) { parts.push('📎 ' + f.name); });
      } else if (el.tagName === 'SELECT') {
        if (el.value) { parts.push(el.options[el.selectedIndex].text); }
      } else if (el.value) {
        if (el.type === 'date') { var d = el.value.split('-'); parts.push(d[2] + '.' + d[1] + '.' + d[0]); }
        else if (el.type === 'datetime-local') { var dt = el.value.split('T'), dd = dt[0].split('-'); parts.push(dd[2] + '.' + dd[1] + '.' + dd[0] + ', ' + dt[1] + ' Uhr'); }
        else if (el.type === 'color') { parts.push(el.value); }
        else { parts.push(el.value); }
      }
    });
    var computed = item.querySelector('.js-calculation output');
    if (computed) { parts.push(computed.textContent); }
    var geoList = item.querySelector('.js-geo-list');
    if (geoList) {
      parts = Array.prototype.map.call(geoList.querySelectorAll('[data-fid] .flex-grow-1'), function (x) { return x.textContent; });
      var pos = item.querySelector('.js-geo-pos');
      if (pos && pos.value) { parts.push('Standort: ' + item.querySelector('.js-geo-pos-text').textContent); }
    }
    return parts;
  }
  function showReview() {
    var vis = visiblePages();
    for (var k = 0; k < vis.length; k++) { if (!valid(pages[vis[k]])) { show(vis[k]); valid(pages[vis[k]]); return; } }
    var html = '';
    vis.forEach(function (i) {
      var p = pages[i], title = p.getAttribute('aria-label') || '', rows = '';
      p.querySelectorAll('.fill-item').forEach(function (item) {
        if (item.classList.contains('d-none') || !item.querySelector('.question')) { return; }
        var label = item.querySelector('.form-label');
        var txt = fieldText(item);
        rows += '<dt class="col-sm-5">' + esc(label ? label.textContent.replace('*', '').trim() : '') + '</dt><dd class="col-sm-7 text-break">' +
          (txt.length ? txt.map(esc).join('<br>') : '<span class="text-secondary">–</span>') + '</dd>';
      });
      if (!rows) { return; }
      html += '<div class="review-page mb-3"><div class="d-flex align-items-center border-bottom mb-2"><strong class="flex-grow-1">' + esc(title || 'Angaben') + '</strong>' +
        '<button type="button" class="btn btn-sm btn-link" data-goto="' + i + '"><i class="fa-solid fa-pen me-1"></i>ändern</button></div><dl class="row mb-0">' + rows + '</dl></div>';
    });
    reviewBox.querySelector('.js-review-body').innerHTML = html;
    pages.forEach(function (p) { p.classList.add('d-none'); });
    reviewBox.classList.remove('d-none');
    inReview = true;
    reached = pages.length;
    prev.classList.remove('d-none');
    next.classList.add('d-none');
    submit.classList.remove('d-none');
    updateSteps();
  }

  /* --- Prüfungen ---------------------------------------------------------------- */
  var originalDates = {};
  try {originalDates = JSON.parse(form.dataset.originalDates || '{}');} catch(e) { /* New forms do not carry a baseline. */ }
  function updateDateRules(scope) {
    scope.querySelectorAll('[data-date-rules]').forEach(function(input) {
      var rules; try {rules = JSON.parse(input.dataset.dateRules);} catch(e) {return;}
      var item = input.closest('[data-qid]'), qid = item && item.dataset.qid;
      var unchanged = qid && Object.prototype.hasOwnProperty.call(originalDates,qid) && input.value === originalDates[qid];
      var low = unchanged ? '' : rules.min || '', high = unchanged ? '' : rules.max || '';
      var reference = rules.date_reference && form.querySelector('[name="q_'+rules.date_reference+'"]');
      var referenceValue = reference ? reference.value : originalDates[rules.date_reference] || '';
      var referenceChanged = reference && Object.prototype.hasOwnProperty.call(originalDates,rules.date_reference) && reference.value !== originalDates[rules.date_reference];
      function addDays(iso,n) {var d = new Date(iso.slice(0,10)+'T12:00:00Z'); if (isNaN(d.getTime())) {return ''; } d.setUTCDate(d.getUTCDate()+Number(n)); return d.toISOString().slice(0,10);}
      if (referenceValue && (!unchanged || referenceChanged)) {
        var refMin = addDays(referenceValue,rules.date_gap_min || 0);
        if (refMin && (!low || refMin > low)) {low = refMin;}
        if (rules.date_gap_max != null) {var refMax=addDays(referenceValue,rules.date_gap_max); if (refMax && (!high || refMax < high)) {high=refMax;}}
      }
      var withTime = input.type === 'datetime-local' || input.dataset.dateKind === 'datetime-local';
      input.min = low ? low+(withTime?'T00:00':'') : '';
      input.max = high ? high+(withTime?'T23:59':'') : '';
      var value = input.value.slice(0,10), message = '';
      if (value && low && value < low) {message='Das Datum liegt vor dem erlaubten Zeitraum.';}
      if (value && high && value > high) {message='Das Datum liegt nach dem erlaubten Zeitraum.';}
      input.setCustomValidity(message ? rules.validation_message || message : '');
      input.dispatchEvent(new CustomEvent('dateconstraintschange'));
    });
  }
  form.addEventListener('input', function() {updateDateRules(form);});
  updateDateRules(form);
  function checkCustom(scope) {
    updateDateRules(scope);
    var ok = true;
    scope.querySelectorAll('.js-check-group').forEach(function (g) {
      var boxes = g.querySelectorAll('input[type="checkbox"]');
      if (boxes[0] && boxes[0].disabled) { return; }
      var n = Array.prototype.filter.call(boxes, function (b) { return b.checked; }).length;
      var min = parseInt(g.dataset.min || (g.dataset.required ? '1' : '0'), 10);
      var max = parseInt(g.dataset.max || '0', 10);
      var msg = '';
      if (n < min) { msg = min === 1 ? 'Bitte mindestens eine Option wählen.' : 'Bitte mindestens ' + min + ' Optionen wählen.'; }
      if (max && n > max) { msg = 'Bitte höchstens ' + max + ' Optionen wählen.'; }
      if (boxes[0]) { boxes[0].setCustomValidity(msg); }
      if (msg) { ok = false; }
    });
    scope.querySelectorAll('.js-other').forEach(function (input) {
      var box = document.getElementById(input.dataset.for);
      input.setCustomValidity(box && box.checked && !input.value.trim() ? 'Bitte den Text für „Sonstiges“ angeben.' : '');
    });
    scope.querySelectorAll('input[type="file"][data-max-mb]').forEach(function (input) {
      var maxBytes = parseInt(input.dataset.maxMb, 10) * 1024 * 1024, maxFiles = parseInt(input.dataset.maxFiles, 10);
      var msg = '';
      if (input.files.length > maxFiles) { msg = 'Höchstens ' + maxFiles + ' Datei(en).'; }
      Array.prototype.forEach.call(input.files, function (f) { if (f.size > maxBytes) { msg = '„' + f.name + '“ ist größer als ' + input.dataset.maxMb + ' MB.'; } });
      var allowed = (input.accept || '').toLowerCase().split(',').filter(Boolean);
      Array.prototype.forEach.call(input.files, function(f) {var dot=f.name.lastIndexOf('.'), ext=dot >= 0 ? f.name.slice(dot).toLowerCase() : ''; if (allowed.length && allowed.indexOf(ext)<0) {msg='Erlaubte Dateitypen: '+allowed.join(', ');}});
      input.setCustomValidity(msg);
    });
    // Kartenfragen: Pflicht = etwas eingezeichnet bzw. Standort erfasst
    scope.querySelectorAll('.js-geo').forEach(function (box) {
      var v = box.querySelector('.js-geo-value'), pos = box.querySelector('.js-geo-pos'), lat = box.querySelector('.js-geo-lat');
      if (v && v.disabled) { return; }
      var missing = (v && v.dataset.required && !v.value) || (pos && pos.dataset.required && !pos.value);
      if (lat) { lat.setCustomValidity(v && v.dataset.required && !v.value ? 'Bitte einen Ort in der Karte wählen oder Koordinaten eingeben.' : ''); }
      if (missing) {
        ok = false;
        box.closest('.question').classList.add('has-error');
        var t = box.querySelector('.js-geo-pos-text');
        if (t && pos && pos.dataset.required && !pos.value) { t.textContent = 'Bitte „Meinen Standort erfassen“ antippen.'; t.classList.add('text-danger'); }
        if (!lat) { box.scrollIntoView({ block: 'center' }); }
      }
    });
    return ok;
  }
  function valid(scope) {
    if (!checkCustom(scope) && !scope.querySelector('.js-geo-lat:invalid, input:invalid, select:invalid, textarea:invalid')) { return false; }
    var fields = scope.querySelectorAll('input, select, textarea');
    for (var i = 0; i < fields.length; i++) {
      if (fields[i].disabled) { continue; }
      if (!fields[i].checkValidity()) {
        fields[i].reportValidity();
        var q = fields[i].closest('.question');
        if (q) { q.classList.add('has-error'); }
        fields[i].setAttribute('aria-invalid', 'true');
        return false;
      }
    }
    return true;
  }

  /* --- Entwurf im Browser ----------------------------------------------------------- */
  var draftKey = form.dataset.draftKey ? 'jsm-draft-' + form.dataset.draftKey + '-' + location.pathname : '';
  var draftState = form.querySelector('.js-draft-state'), saveTimer = null;
  function store() { try { return window.localStorage; } catch (e) { return null; } }
  function collect() {
    var data = {};
    form.querySelectorAll('input, select, textarea').forEach(function (el) {
      if (el.classList.contains('js-declaration') || el.closest('.js-signature') || !el.name || el.name === 'csrf' || el.name === 'website' || el.type === 'file') { return; }
      if (el.type === 'checkbox' || el.type === 'radio') { if (el.checked) { (data[el.name] = data[el.name] || []).push(el.value); } return; }
      if (el.value) { data[el.name] = el.value; }
    });
    return data;
  }
  function saveDraft() {
    var s = store();
    if (!s || !draftKey) { return; }
    try {
      s.setItem(draftKey, JSON.stringify({ at: Date.now(), page: current, data: collect() }));
      if (draftState) { draftState.innerHTML = '<i class="fa-solid fa-check me-1"></i>Entwurf gespeichert (nur in diesem Browser, ohne Dateien)'; }
    } catch (e) { /* Speicher voll oder gesperrt */ }
  }
  function restoreDraft(d) {
    Object.keys(d.data).forEach(function (name) {
      var els = form.querySelectorAll('[name="' + CSS.escape(name) + '"]');
      var val = d.data[name];
      els.forEach(function (el) {
        if (el.classList.contains('js-declaration') || el.closest('.js-signature')) { return; }
        if (el.type === 'checkbox' || el.type === 'radio') { el.checked = Array.isArray(val) && val.indexOf(el.value) >= 0; }
        else if (el.type !== 'file') { el.value = Array.isArray(val) ? val[0] : val; el.dispatchEvent(new Event('change', { bubbles: true })); }
      });
    });
    applyConditions();
  }
  if (draftKey && store()) {
    try {
      var saved = JSON.parse(store().getItem(draftKey) || 'null');
      var banner = form.querySelector('.js-draft-banner');
      if (saved && saved.data && Object.keys(saved.data).length && banner) {
        banner.classList.remove('d-none');
        form.querySelector('.js-draft-time').textContent = new Date(saved.at).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' });
        form.querySelector('.js-draft-restore').addEventListener('click', function () { restoreDraft(saved); banner.remove(); });
        form.querySelector('.js-draft-discard').addEventListener('click', function () { store().removeItem(draftKey); banner.remove(); });
      }
    } catch (e) { /* defekter Entwurf */ }
  }

  /* --- Ereignisse ------------------------------------------------------------------- */
  form.addEventListener('input', function (ev) {
    if (ev.target.classList.contains('js-other')) {
      var box = document.getElementById(ev.target.dataset.for);
      if (box && ev.target.value.trim()) { box.checked = true; }
    }
    var q = ev.target.closest('.question');
    if (q) { q.classList.remove('has-error'); }
    ev.target.removeAttribute('aria-invalid');
    if (condItems.length || condPages.length) { applyConditions(); }
    if (draftKey) { clearTimeout(saveTimer); saveTimer = setTimeout(saveDraft, 800); }
  });
  form.addEventListener('change', function (ev) {
    if (ev.target.type === 'checkbox' || ev.target.type === 'file') { checkCustom(form); }
    if (condItems.length || condPages.length) { applyConditions(); }
    if (draftKey) { clearTimeout(saveTimer); saveTimer = setTimeout(saveDraft, 400); }
  });
  next.addEventListener('click', function () {
    if (!valid(pages[current])) { return; }
    var n = nextIndex(current, 1);
    if (n < 0 && hasReview) { showReview(); } else if (n >= 0) { show(n); }
    window.scrollTo({ top: form.getBoundingClientRect().top + window.scrollY - 80, behavior: 'smooth' });
  });
  prev.addEventListener('click', function () {
    if (inReview) { var vis = visiblePages(); show(vis[vis.length - 1]); } else { show(nextIndex(current, -1)); }
    window.scrollTo({ top: form.getBoundingClientRect().top + window.scrollY - 80, behavior: 'smooth' });
  });
  form.addEventListener('click', function (ev) {
    var go = ev.target.closest('[data-goto]');
    if (go && !go.disabled) { show(parseInt(go.dataset.goto, 10)); window.scrollTo({ top: form.getBoundingClientRect().top + window.scrollY - 80, behavior: 'smooth' }); }
  });
  form.addEventListener('submit', function (ev) {
    var vis = visiblePages();
    for (var k = 0; k < vis.length; k++) {
      if (!valid(pages[vis[k]])) { ev.preventDefault(); show(vis[k]); valid(pages[vis[k]]); return; }
    }
    if (hasReview && !inReview && pages.length) { ev.preventDefault(); showReview(); return; }
    // Seiten wieder einblenden, damit alle (nicht deaktivierten) Felder mitgeschickt werden
    submit.disabled = true;
    submit.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Wird gesendet …';
    if (draftKey && store()) { try { store().removeItem(draftKey); } catch (e) { /* egal */ } }
  });
  form.addEventListener('keydown', function (ev) {
    // Enter in einem Textfeld blättert weiter statt vorzeitig abzusenden
    if (ev.key === 'Enter' && ev.target.tagName === 'INPUT' && ['submit', 'button', 'checkbox', 'radio', 'file', 'search'].indexOf(ev.target.type) < 0 && !inReview) {
      ev.preventDefault();
      if (!next.classList.contains('d-none')) { next.click(); }
    }
  });
  applyConditions();
  show(pages[current] && pages[current]._hidden ? (nextIndex(current, 1) >= 0 ? nextIndex(current, 1) : 0) : current);
  var errorSummary = form.querySelector('.js-form-errors');
  if (errorSummary) { errorSummary.focus(); }
})();
