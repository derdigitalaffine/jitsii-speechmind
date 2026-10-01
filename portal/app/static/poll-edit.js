/* Terminvorschläge bearbeiten: Generator (Tage × Uhrzeiten) und Einzelliste. */
(function () {
  'use strict';
  var form = document.getElementById('poll-form');
  if (!form) { return; }
  var options = JSON.parse(document.getElementById('poll-options').textContent || '[]');
  var days = [], times = [];
  var list = document.getElementById('opt-list');
  var WD = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];
  var esc = function (s) { return String(s || '').replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); };
  var label = function (d) { var x = new Date(d + 'T12:00'); return isNaN(x) ? d : WD[x.getDay()] + ', ' + d.slice(8, 10) + '.' + d.slice(5, 7) + '.'; };
  var key = function (o) { return o.date + '|' + (o.start || '') + '|' + (o.end || ''); };

  function chips(el, arr, fmt) {
    el.innerHTML = arr.map(function (v, i) {
      return '<span class="badge text-bg-primary d-inline-flex align-items-center gap-1">' + esc(fmt(v)) +
        '<button type="button" class="btn-close btn-close-white" style="font-size:.55rem" data-i="' + i + '" aria-label="Entfernen"></button></span>';
    }).join('');
    el.querySelectorAll('[data-i]').forEach(function (b) {
      b.addEventListener('click', function () { arr.splice(Number(b.dataset.i), 1); chips(el, arr, fmt); hint(); });
    });
  }
  function hint() {
    var n = days.length * Math.max(times.length, 1);
    document.getElementById('gen-hint').textContent = days.length ? n + ' Vorschläge werden erzeugt' : '';
  }
  function render() {
    options.sort(function (a, b) { return key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0; });
    list.innerHTML = options.map(function (o, i) {
      return '<div class="input-group input-group-sm" data-i="' + i + '">' +
        '<span class="input-group-text" style="min-width:5.5rem">' + esc(label(o.date)) + '</span>' +
        '<input class="form-control" type="date" data-k="date" value="' + esc(o.date) + '" aria-label="Datum" required>' +
        '<input class="form-control" type="time" data-k="start" value="' + esc(o.start) + '" aria-label="Beginn (leer = ganztägig)">' +
        '<span class="input-group-text">–</span>' +
        '<input class="form-control" type="time" data-k="end" value="' + esc(o.end) + '" aria-label="Ende">' +
        '<input class="form-control d-none d-md-block" data-k="note" value="' + esc(o.note) + '" maxlength="120" placeholder="Notiz" aria-label="Notiz">' +
        '<button class="btn btn-outline-danger" type="button" data-del title="Entfernen" aria-label="Entfernen"><i class="fa-solid fa-xmark"></i></button></div>';
    }).join('');
    document.getElementById('opt-count').textContent = options.length;
    document.getElementById('opt-empty').classList.toggle('d-none', options.length > 0);
  }
  list.addEventListener('change', function (ev) {
    var row = ev.target.closest('[data-i]'); if (!row || !ev.target.dataset.k) { return; }
    options[Number(row.dataset.i)][ev.target.dataset.k] = ev.target.value;
    if (ev.target.dataset.k === 'date') { render(); }
  });
  list.addEventListener('input', function (ev) {
    var row = ev.target.closest('[data-i]'); if (!row || !ev.target.dataset.k) { return; }
    options[Number(row.dataset.i)][ev.target.dataset.k] = ev.target.value;
  });
  list.addEventListener('click', function (ev) {
    if (!ev.target.closest('[data-del]')) { return; }
    options.splice(Number(ev.target.closest('[data-i]').dataset.i), 1); render();
  });
  document.getElementById('gen-add-day').addEventListener('click', function () {
    var v = document.getElementById('gen-day').value;
    if (v && days.indexOf(v) < 0) { days.push(v); days.sort(); }
    var next = new Date(v + 'T12:00'); if (!isNaN(next)) { next.setDate(next.getDate() + 1); document.getElementById('gen-day').value = next.toISOString().slice(0, 10); }
    chips(document.getElementById('gen-days'), days, label); hint();
  });
  document.getElementById('gen-add-time').addEventListener('click', function () {
    var s = document.getElementById('gen-start').value, e = document.getElementById('gen-end').value;
    if (!s) { return; }
    var t = s + (e ? '–' + e : '');
    if (times.indexOf(t) < 0) { times.push(t); times.sort(); }
    chips(document.getElementById('gen-times'), times, function (x) { return x; }); hint();
  });
  document.getElementById('gen-run').addEventListener('click', function () {
    if (!days.length) { document.getElementById('gen-hint').textContent = 'Bitte zuerst Tage hinzufügen.'; return; }
    var have = {}; options.forEach(function (o) { have[key(o)] = true; });
    days.forEach(function (d) {
      (times.length ? times : ['']).forEach(function (t) {
        var parts = t.split('–'), o = { date: d, start: parts[0] || '', end: parts[1] || '', note: '' };
        if (!have[key(o)]) { options.push(o); have[key(o)] = true; }
      });
    });
    render();
  });
  document.getElementById('opt-add').addEventListener('click', function () {
    var last = options.length ? options[options.length - 1] : null;
    options.push({ date: last ? last.date : new Date().toISOString().slice(0, 10), start: last ? last.start : '', end: last ? last.end : '', note: '' });
    render();
  });
  form.addEventListener('submit', function (ev) {
    if (!options.length) { ev.preventDefault(); document.getElementById('gen-hint').textContent = 'Bitte mindestens einen Terminvorschlag anlegen.'; return; }
    document.getElementById('options-json').value = JSON.stringify(options);
  });
  render();
})();
