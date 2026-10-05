/* Formular ausfüllen: Seiten blättern mit Prüfung je Seite, „Sonstiges“, Dateigrößen. Ohne JS: alle Seiten untereinander. */
(function () {
  'use strict';
  var form = document.querySelector('form.js-fill');
  if (!form) { return; }
  var pages = Array.prototype.slice.call(form.querySelectorAll('.fill-page'));
  var prev = form.querySelector('.js-prev'), next = form.querySelector('.js-next'), submit = form.querySelector('.js-submit');
  var bar = form.querySelector('.js-progress'), label = form.querySelector('.js-page-label');
  var current = Math.min(parseInt(form.dataset.start || '0', 10), pages.length - 1);

  function show(i) {
    current = i;
    pages.forEach(function (p, n) { p.classList.toggle('d-none', n !== i); p.classList.toggle('d-flex', n === i); });
    if (pages.length > 1) {
      prev.classList.toggle('d-none', i === 0);
      next.classList.toggle('d-none', i === pages.length - 1);
      submit.classList.toggle('d-none', i !== pages.length - 1);
      if (bar) { bar.style.width = Math.round(((i + 1) / pages.length) * 100) + '%'; }
      if (label) { label.textContent = 'Seite ' + (i + 1) + ' von ' + pages.length; }
    }
  }

  /* Eigene Prüfungen: Mehrfachauswahl (Pflicht, min/max), „Sonstiges“, Dateien */
  function checkCustom(scope) {
    var ok = true;
    scope.querySelectorAll('.js-check-group').forEach(function (g) {
      var boxes = g.querySelectorAll('input[type="checkbox"]');
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
      input.setCustomValidity(msg);
    });
    // GPS-Fragen: Pflicht = ein Punkt muss gesetzt sein
    scope.querySelectorAll('.js-geo-value[data-required]').forEach(function (v) {
      var box = v.closest('.js-geo'), lat = box.querySelector('.js-geo-lat');
      var missing = !v.value;
      if (lat) { lat.setCustomValidity(missing ? 'Bitte einen Ort in der Karte wählen oder Koordinaten eingeben.' : ''); }
      if (missing) {
        ok = false;
        if (!lat) { box.closest('.question').classList.add('has-error'); box.scrollIntoView({ block: 'center' }); }
      }
    });
    return ok;
  }
  function valid(scope) {
    if (!checkCustom(scope) && !scope.querySelector('.js-geo-lat:invalid, input:invalid, select:invalid, textarea:invalid')) { return false; }
    var fields = scope.querySelectorAll('input, select, textarea');
    for (var i = 0; i < fields.length; i++) {
      if (!fields[i].checkValidity()) {
        fields[i].reportValidity();
        var q = fields[i].closest('.question');
        if (q) { q.classList.add('has-error'); }
        return false;
      }
    }
    return true;
  }

  // Sonstiges: Tippen wählt die Option automatisch aus
  form.addEventListener('input', function (ev) {
    if (ev.target.classList.contains('js-other')) {
      var box = document.getElementById(ev.target.dataset.for);
      if (box && ev.target.value.trim()) { box.checked = true; }
    }
    var q = ev.target.closest('.question');
    if (q) { q.classList.remove('has-error'); }
  });
  form.addEventListener('change', function (ev) { if (ev.target.type === 'checkbox' || ev.target.type === 'file') { checkCustom(form); } });

  next.addEventListener('click', function () {
    if (valid(pages[current])) { show(current + 1); window.scrollTo({ top: 0, behavior: 'smooth' }); }
  });
  prev.addEventListener('click', function () { show(current - 1); window.scrollTo({ top: 0, behavior: 'smooth' }); });
  form.addEventListener('submit', function (ev) {
    for (var i = 0; i < pages.length; i++) {
      if (!valid(pages[i])) { ev.preventDefault(); show(i); valid(pages[i]); return; }
    }
    submit.disabled = true;
    submit.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Wird gesendet …';
  });
  form.addEventListener('keydown', function (ev) {
    // Enter in einem Textfeld blättert weiter statt vorzeitig abzusenden
    if (ev.key === 'Enter' && ev.target.tagName === 'INPUT' && ev.target.type !== 'submit' && current < pages.length - 1) {
      ev.preventDefault();
      next.click();
    }
  });
  show(current);
})();
