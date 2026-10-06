// Buchungskalender: Monatsansicht mit Verfügbarkeit je Tag (frei / teilweise frei / belegt / geschlossen).
// Ganze Tage: ersten und letzten Tag antippen (Spanne). Zeitblöcke und Stunden: Tag antippen, darunter die Zeiten.
// Schreibt in die vorhandenen Felder (date_from/date_to bzw. date) und löst „change“ aus – Preis und freie
// Zeiten aktualisiert resource-book.js.
(function () {
  'use strict';
  var box = document.getElementById('res-pick');
  var form = document.getElementById('res-form');
  if (!box || !form || !window.fetch) return;

  var MONTHS = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'];
  var DAYS = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
  var LONG = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag'];
  var LABEL = { free: 'frei', partial: 'teilweise frei', busy: 'belegt', closed: 'geschlossen', off: 'nicht buchbar' };
  var cache = {}, data = null, seq = 0;
  var month = null;   // 'YYYY-MM'

  function mode() {
    var r = form.querySelector('input[name="mode"]:checked') || form.querySelector('input[name="mode"]');
    return r ? r.value : 'day';
  }
  function units() {
    return Array.prototype.map.call(form.querySelectorAll('.js-unit:checked'), function (u) { return u.value; });
  }
  function field(name) { return form.querySelector('.res-when[data-mode="' + mode() + '"] [name="' + name + '"]'); }
  function iso(y, m, d) { return y + '-' + ('0' + m).slice(-2) + '-' + ('0' + d).slice(-2); }
  function parse(s) { var p = s.split('-'); return new Date(+p[0], +p[1] - 1, +p[2]); }
  function addDays(s, n) { var d = parse(s); d.setDate(d.getDate() + n); return iso(d.getFullYear(), d.getMonth() + 1, d.getDate()); }
  function nice(s) { var d = parse(s); return DAYS[(d.getDay() + 6) % 7] + ' ' + ('0' + d.getDate()).slice(-2) + '.' + ('0' + (d.getMonth() + 1)).slice(-2) + '.'; }
  function shift(m, n) { var p = m.split('-'), d = new Date(+p[0], +p[1] - 1 + n, 1); return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2); }

  function selected() {
    if (mode() === 'day') {
      var f = field('date_from'), t = field('date_to');
      return { from: f && f.value || '', to: (t && t.value) || (f && f.value) || '' };
    }
    var d = field('date');
    return { from: d && d.value || '', to: d && d.value || '' };
  }
  function set(name, value) {
    var el = field(name);
    if (!el) return;
    el.value = value;
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function load() {
    var key = month + '|' + mode() + '|' + units().join(',');
    if (cache[key]) { data = cache[key]; render(); return; }
    var my = ++seq;
    var params = new URLSearchParams({ m: month, mode: mode() });
    units().forEach(function (u) { params.append('units', u); });
    box.setAttribute('aria-busy', 'true');
    fetch(box.dataset.month + (box.dataset.month.indexOf('?') >= 0 ? '&' : '?') + params, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (my !== seq || !d) return;
        cache[key] = data = d;
        box.removeAttribute('aria-busy');
        render();
      }).catch(function () {});
  }

  function pick(day, status) {
    if (status === 'off' || status === 'closed') return;
    if (mode() !== 'day') { set('date', day); render(); return; }
    var s = selected();
    if (s.from && s.from === s.to && day > s.from) {
      // zweiter Tag: Spanne, sofern keine geschlossenen Tage dazwischen und nicht länger als erlaubt
      var n = (parse(day) - parse(s.from)) / 864e5 + 1, ok = n <= (data ? data.max_days : 1);
      for (var d = s.from; ok && d <= day; d = addDays(d, 1)) {
        var st = data && data.days[d];
        if (st === 'closed' || st === 'off') ok = false;
      }
      if (ok) { set('date_to', day); render(); return; }
    }
    set('date_from', day);
    set('date_to', day);
    render();
  }

  function render() {
    if (!data) return;
    var p = month.split('-'), y = +p[0], m = +p[1];
    var first = new Date(y, m - 1, 1), offset = (first.getDay() + 6) % 7, n = new Date(y, m, 0).getDate();
    var s = selected(), dayMode = mode() === 'day';
    var canPrev = month > data.first.slice(0, 7), canNext = month < data.last.slice(0, 7);
    var h = '<div class="res-pick-head"><button type="button" class="btn btn-sm btn-light js-prev" ' + (canPrev ? '' : 'disabled') + ' aria-label="Voriger Monat"><i class="fa-solid fa-chevron-left"></i></button>' +
      '<strong aria-live="polite">' + MONTHS[m - 1] + ' ' + y + '</strong>' +
      '<button type="button" class="btn btn-sm btn-light js-next" ' + (canNext ? '' : 'disabled') + ' aria-label="Nächster Monat"><i class="fa-solid fa-chevron-right"></i></button></div>';
    h += '<div class="res-pick-grid" role="grid">' + DAYS.map(function (d) { return '<div class="res-pick-dow" role="columnheader">' + d + '</div>'; }).join('');
    for (var i = 0; i < offset; i++) h += '<div></div>';
    for (var d = 1; d <= n; d++) {
      var key = iso(y, m, d), st = data.days[key] || 'off';
      var inRange = s.from && key >= s.from && key <= s.to;
      var cls = 'res-pick-day st-' + st + (inRange ? ' sel' : '') + (key === s.from ? ' sel-start' : '') + (key === s.to ? ' sel-end' : '');
      var wd = LONG[(new Date(y, m - 1, d).getDay() + 6) % 7];
      h += '<button type="button" class="' + cls + '" data-day="' + key + '" data-st="' + st + '" ' + (st === 'off' || st === 'closed' ? 'disabled' : '') +
        ' aria-pressed="' + (inRange ? 'true' : 'false') + '" aria-label="' + wd + ', ' + d + '. ' + MONTHS[m - 1] + ': ' + LABEL[st] + '">' + d + '</button>';
    }
    h += '</div><div class="res-pick-legend"><span><i class="st-free"></i>frei</span>' + (dayMode ? '' : '<span><i class="st-partial"></i>teilweise frei</span>') +
      '<span><i class="st-busy"></i>belegt</span><span><i class="st-closed"></i>nicht buchbar</span></div>';
    var hint;
    if (!s.from) hint = dayMode ? 'Ersten Tag antippen – bei mehreren Tagen danach den letzten.' : 'Tag antippen – danach die Zeit wählen.';
    else if (dayMode) hint = '<strong>' + nice(s.from) + (s.to !== s.from ? ' – ' + nice(s.to) : '') + '</strong>' +
      (s.to === s.from && data.max_days > 1 ? ' · Für mehrere Tage jetzt den letzten Tag antippen.' : '');
    else hint = '<strong>' + nice(s.from) + '</strong> · Zeit unten wählen.';
    h += '<div class="res-pick-hint small" aria-live="polite">' + hint + '</div>';
    box.innerHTML = h;
    box.querySelector('.js-prev').addEventListener('click', function () { month = shift(month, -1); load(); });
    box.querySelector('.js-next').addEventListener('click', function () { month = shift(month, 1); load(); });
    box.querySelectorAll('.res-pick-day').forEach(function (b) {
      b.addEventListener('click', function () { pick(b.dataset.day, b.dataset.st); });
    });
  }

  function start() {
    var s = selected();
    month = (s.from || box.dataset.first || new Date().toISOString().slice(0, 10)).slice(0, 7);
    load();
  }
  form.addEventListener('change', function (e) {
    if (e.target.name === 'mode' || e.target.classList.contains('js-unit')) { data = null; load(); }
    else if (e.target.closest && e.target.closest('.res-when') && e.target.type === 'date') {
      var v = e.target.value;
      if (v && v.slice(0, 7) !== month) { month = v.slice(0, 7); load(); } else render();
    }
  });
  start();
})();
