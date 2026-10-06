// Ressource bearbeiten: Listen-Editoren (Zeitblöcke, Buchungszeiten, Teilräume, Tarife, Zusatzleistungen, Angaben).
(function () {
  'use strict';
  var form = document.getElementById('res-main');
  var dataEl = document.getElementById('res-editor');
  if (!form || !dataEl) return;
  var D = JSON.parse(dataEl.textContent);
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  var uid = function () { return Math.random().toString(36).slice(2, 8); };
  var DAYS = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag'];

  // Generischer Zeilen-Editor: cols = [{key, label, type, cls, placeholder, options, show(row), rerender, help}]
  // show: Spalte nur anzeigen, wenn show(row) wahr ist; rerender: nach Änderung neu zeichnen (abhängige Spalten)
  function table(el, rows, cols, blank, addLabel) {
    function render() {
      el.innerHTML = (rows.length ? rows.map(function (r, i) {
        return '<div class="row g-2 align-items-end mb-2 pb-2 border-bottom" data-i="' + i + '">' + cols.map(function (c) {
          var v = r[c.key];
          var input;
          if (c.show && !c.show(r)) return '';
          if (c.type === 'check') {
            input = '<div class="form-check mb-1"><input class="form-check-input" type="checkbox" data-k="' + c.key + '" id="' + el.id + i + c.key + '"' + (v ? ' checked' : '') + '><label class="form-check-label small" for="' + el.id + i + c.key + '">' + esc(c.label) + '</label></div>';
            return '<div class="' + (c.cls || 'col-auto') + '">' + input + '</div>';
          }
          if (c.type === 'select') {
            input = '<select class="form-select form-select-sm" data-k="' + c.key + '">' + c.options.map(function (o) { return '<option value="' + o[0] + '"' + (String(v) === String(o[0]) ? ' selected' : '') + '>' + esc(o[1]) + '</option>'; }).join('') + '</select>';
          } else {
            input = '<input class="form-control form-control-sm" data-k="' + c.key + '" type="' + (c.type || 'text') + '" value="' + esc(v == null ? '' : v) + '" placeholder="' + esc(c.placeholder || '') + '"' + (c.type === 'time' ? '' : '') + '>';
          }
          var id = el.id + i + c.key;
          input = input.replace(' data-k="', ' id="' + id + '"' + (c.help ? ' title="' + esc(c.help) + '"' : '') + ' data-k="');
          return '<div class="' + (c.cls || 'col') + '"><label class="form-label small mb-0" for="' + id + '">' + esc(c.label) + '</label>' + input + '</div>';
        }).join('') + '<div class="col-auto"><button class="btn btn-sm btn-outline-secondary" type="button" data-up="' + i + '" aria-label="nach oben"><i class="fa-solid fa-arrow-up"></i></button> <button class="btn btn-sm btn-outline-danger" type="button" data-del="' + i + '" aria-label="entfernen"><i class="fa-solid fa-xmark"></i></button></div></div>';
      }).join('') : '<div class="small text-secondary mb-2">Noch keine Einträge.</div>') +
        '<button class="btn btn-sm btn-outline-primary" type="button" data-add="1"><i class="fa-solid fa-plus me-1"></i>' + esc(addLabel) + '</button>';
    }
    el.addEventListener('input', function (e) {
      var row = e.target.closest('[data-i]'); if (!row || !e.target.dataset.k) return;
      rows[+row.dataset.i][e.target.dataset.k] = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
    });
    el.addEventListener('change', function (e) {
      var row = e.target.closest('[data-i]'); if (!row || !e.target.dataset.k) return;
      rows[+row.dataset.i][e.target.dataset.k] = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
      var col = cols.filter(function (c) { return c.key === e.target.dataset.k; })[0];
      if (col && col.rerender) { render(); var again = el.querySelector('[data-i="' + row.dataset.i + '"] [data-k="' + col.key + '"]'); if (again) again.focus(); }
    });
    el.addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b) return;
      if (b.dataset.add) { rows.push(blank()); render(); }
      else if (b.dataset.del) { rows.splice(+b.dataset.del, 1); render(); }
      else if (b.dataset.up) { var i = +b.dataset.up; if (i > 0) { rows.splice(i - 1, 0, rows.splice(i, 1)[0]); render(); } }
    });
    render();
    return rows;
  }

  // Preisspalten der Teilräume: nur eingeschaltete Buchungsarten (pm-…), Wochenendpreise nur bei Bedarf (pw)
  var priceCols = [
    { key: 'price_day', label: 'je Tag €', cls: 'col-4 col-md-2 pm pm-day' }, { key: 'wkd_day', label: 'Tag WE/FT €', cls: 'col-4 col-md-2 pm pm-day pw' },
    { key: 'price_block', label: 'je Block €', cls: 'col-4 col-md-2 pm pm-block' }, { key: 'wkd_block', label: 'Block WE/FT €', cls: 'col-4 col-md-2 pm pm-block pw' },
    { key: 'price_hour', label: 'je Std. €', cls: 'col-4 col-md-2 pm pm-hour' }, { key: 'wkd_hour', label: 'Std. WE/FT €', cls: 'col-4 col-md-2 pm pm-hour pw' }];
  var units = table(document.getElementById('ed-units'), D.units, [
    { key: 'name', label: 'Name', cls: 'col-12 col-md-4', placeholder: 'z. B. Großer Saal' },
    { key: 'capacity', label: 'Personen', type: 'number', cls: 'col-4 col-md-2' },
    { key: 'description', label: 'Beschreibung', cls: 'col-8 col-md-5' }].concat(priceCols),
    function () { return { name: '', capacity: '', description: '' }; }, 'Teilraum hinzufügen');
  var tariffs = table(document.getElementById('ed-tariffs'), D.tariffs, [
    { key: 'name', label: 'Tarif', cls: 'col-12 col-md-3', placeholder: 'z. B. Vereine' },
    { key: 'percent', label: '% der Miete', type: 'number', cls: 'col-4 col-md-2' },
    { key: 'description', label: 'Hinweis', cls: 'col-8 col-md-4', placeholder: 'z. B. eingetragene Vereine aus der VG' },
    { key: 'needs_proof', label: 'Nachweis hochladen', type: 'check', cls: 'col-auto' }],
    function () { return { name: '', percent: 100, description: '', needs_proof: false }; }, 'Tarif hinzufügen');
  var PERSON = ['person', 'persons', 'tier'];
  var extras = table(document.getElementById('ed-extras'), D.extras, [
    { key: 'name', label: 'Leistung / Preisbestandteil', cls: 'col-12 col-md-3', placeholder: 'z. B. Wasser, Kanal, Strom' },
    { key: 'per', label: 'Abrechnung', type: 'select', cls: 'col-6 col-md-3', rerender: true, options: Object.keys(D.per).map(function (k) { return [k, D.per[k]]; }) },
    { key: 'price', label: 'Preis €', cls: 'col-3 col-md-1', show: function (r) { return r.per !== 'tier'; } },
    { key: 'per_n', label: 'je N Pers.', type: 'number', cls: 'col-3 col-md-1', placeholder: '25', show: function (r) { return r.per === 'persons'; } },
    { key: 'tiers', label: 'Staffel (bis Personen: €)', cls: 'col-12 col-md-4', placeholder: 'bis 50: 20; bis 100: 35; darüber: 50', show: function (r) { return r.per === 'tier'; },
      help: 'Je Stufe „bis Personenzahl: Betrag“, getrennt durch Semikolon; „darüber: Betrag“ für alles Größere' },
    { key: 'max_qty', label: 'max. Anzahl', type: 'number', cls: 'col-3 col-md-1', show: function (r) { return PERSON.indexOf(r.per) < 0 && r.per !== 'once'; } },
    { key: 'stock', label: 'Bestand', type: 'number', cls: 'col-3 col-md-1', placeholder: '∞', show: function (r) { return PERSON.indexOf(r.per) < 0; } },
    { key: 'min', label: 'Min. €', cls: 'col-3 col-md-1', placeholder: '–', help: 'Mindestbetrag' },
    { key: 'max', label: 'Max. €', cls: 'col-3 col-md-1', placeholder: '–', help: 'Höchstbetrag' },
    { key: 'cancel_rule', label: 'Bei Absage', type: 'select', cls: 'col-6 col-md-3', rerender: true, options: Object.keys(D.cancelRules).map(function (k) { return [k, D.cancelRules[k]]; }) },
    { key: 'cancel_days', label: 'Frist (Tage)', type: 'number', cls: 'col-3 col-md-2', placeholder: '0', show: function (r) { return r.cancel_rule === 'keep' || r.cancel_rule === 'only'; },
      help: 'Gilt bei Absage weniger als so viele Tage vor Beginn (0 = immer)' },
    { key: 'description', label: 'Hinweis', cls: 'col-12 col-md-3' },
    { key: 'mandatory', label: 'Pflicht', type: 'check', cls: 'col-auto', show: function (r) { return r.cancel_rule !== 'only'; } },
    { key: 'active', label: 'aktiv', type: 'check', cls: 'col-auto' }],
    function () { return { name: '', price: '', per: 'once', max_qty: 1, stock: '', description: '', mandatory: false, active: true, per_n: '', tiers: '', min: '', max: '', cancel_rule: '', cancel_days: '' }; },
    'Preisbestandteil hinzufügen');
  var blocks = table(document.getElementById('ed-blocks'), D.blocks, [
    { key: 'label', label: 'Bezeichnung', cls: 'col-12 col-md-5', placeholder: 'z. B. Vormittag' },
    { key: 'start', label: 'von', type: 'time', cls: 'col-6 col-md-3' }, { key: 'end', label: 'bis', type: 'time', cls: 'col-6 col-md-3' }],
    function () { return { id: uid(), label: '', start: '08:00', end: '13:00' }; }, 'Zeitblock hinzufügen');

  // Buchungszeiten je Wochentag
  var hoursEl = document.getElementById('ed-hours');
  var hours = D.hours || {};
  function renderHours() {
    hoursEl.innerHTML = DAYS.map(function (name, d) {
      var r = hours[String(d)];
      var state = r === undefined ? 'all' : (r.length ? 'range' : 'closed');
      var range = r && r[0] ? r[0] : ['08:00', '22:00'];
      return '<div class="row g-2 align-items-center mb-1" data-d="' + d + '"><div class="col-4 col-md-3 small fw-semibold">' + name + '</div>' +
        '<div class="col-8 col-md-4"><select class="form-select form-select-sm" data-h="state"><option value="all"' + (state === 'all' ? ' selected' : '') + '>ganztags</option><option value="range"' + (state === 'range' ? ' selected' : '') + '>von – bis</option><option value="closed"' + (state === 'closed' ? ' selected' : '') + '>geschlossen</option></select></div>' +
        '<div class="col-6 col-md-2' + (state === 'range' ? '' : ' d-none') + '"><input class="form-control form-control-sm" type="time" data-h="from" value="' + range[0] + '" aria-label="von"></div>' +
        '<div class="col-6 col-md-2' + (state === 'range' ? '' : ' d-none') + '"><input class="form-control form-control-sm" type="time" data-h="to" value="' + (range[1] === '24:00' ? '23:59' : range[1]) + '" aria-label="bis"></div></div>';
    }).join('');
  }
  hoursEl.addEventListener('change', function (e) {
    var row = e.target.closest('[data-d]'); if (!row) return;
    var d = row.dataset.d, st = row.querySelector('[data-h="state"]').value;
    if (st === 'all') delete hours[d];
    else if (st === 'closed') hours[d] = [];
    else hours[d] = [[row.querySelector('[data-h="from"]').value || '08:00', (row.querySelector('[data-h="to"]').value === '23:59' ? '24:00' : row.querySelector('[data-h="to"]').value) || '22:00']];
    if (e.target.dataset.h === 'state') renderHours();
  });
  renderHours();

  var fields = D.fields;
  if (window.FieldList) {
    FieldList.mount(document.getElementById('ed-fields'), { types: D.requestTypes, subtypes: D.subtypes, items: fields,
      onChange: function (list) { fields = list; } });
  }

  // Koordinaten aus der Anschrift
  var geo = document.getElementById('e-geocode');
  if (geo) geo.addEventListener('click', function () {
    var q = document.getElementById('e-loc').value.trim(), msg = document.getElementById('e-geocode-msg');
    if (!q) { msg.textContent = 'Bitte zuerst die Anschrift eintragen.'; return; }
    msg.textContent = 'Suche …';
    fetch('/geo/search?q=' + encodeURIComponent(q), { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (d) {
      var hit = d.results && d.results[0];
      if (!hit) { msg.textContent = 'Nichts gefunden.'; return; }
      document.getElementById('e-lat').value = hit.lat; document.getElementById('e-lon').value = hit.lon;
      msg.textContent = 'Übernommen: ' + hit.label;
    }).catch(function () { msg.textContent = 'Adresssuche nicht erreichbar.'; });
  });

  // Reiter merken (#anker) und beim Speichern mitgeben
  var hash = location.hash.slice(1);
  if (hash) { var btn = document.querySelector('[data-bs-target="#' + hash + '"]'); if (btn && window.bootstrap) bootstrap.Tab.getOrCreateInstance(btn).show(); }
  document.querySelectorAll('#res-tabs [data-bs-toggle="tab"]').forEach(function (b) {
    b.addEventListener('shown.bs.tab', function () {
      var id = b.dataset.bsTarget.slice(1);
      history.replaceState(null, '', '#' + id);
      document.getElementById('res-savebar').classList.toggle('d-none', id === 'sperren' || id === 'fotos');
    });
  });
  // Ungespeicherte Änderungen: Hinweis in der Speicherleiste und Warnung beim Verlassen
  var dirty = false, note = document.getElementById('res-dirty');
  function markDirty() {
    if (dirty) return;
    dirty = true;
    if (note) { note.textContent = 'Ungespeicherte Änderungen'; note.className = 'small text-warning-emphasis fw-semibold'; }
  }
  form.addEventListener('input', markDirty);
  form.addEventListener('change', markDirty);
  form.addEventListener('click', function (e) { if (e.target.closest('[data-del], [data-up], [data-add], .btn-add')) markDirty(); });
  document.querySelectorAll('textarea[form="res-main"]').forEach(function (t) { t.addEventListener('input', markDirty); });
  window.addEventListener('beforeunload', function (e) { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
  document.querySelectorAll('.js-tab-link').forEach(function (a) {
    a.addEventListener('click', function (e) {
      var btn = document.querySelector('[data-bs-target="#' + a.dataset.tab + '"]');
      if (btn && window.bootstrap) { e.preventDefault(); bootstrap.Tab.getOrCreateInstance(btn).show(); btn.scrollIntoView({ block: 'nearest' }); }
    });
  });
  form.addEventListener('submit', function () {
    dirty = false;
    document.getElementById('h-units_json').value = JSON.stringify(units);
    document.getElementById('h-tariffs_json').value = JSON.stringify(tariffs);
    document.getElementById('h-extras_json').value = JSON.stringify(extras.map(function (x) { return Object.assign({}, x, { stock: x.stock === '' || x.stock == null ? '' : String(x.stock) }); }));
    document.getElementById('h-blocks_json').value = JSON.stringify(blocks);
    document.getElementById('h-hours_json').value = JSON.stringify(hours);
    document.getElementById('h-fields_json').value = JSON.stringify(fields);
    document.getElementById('h-tab').value = location.hash.slice(1);
  });

  // --- Preise: Spalten nach Buchungsart, Wochenend-Schalter, Vorschau ------------------------------
  var main = document.getElementById('res-main'), wkdOn = document.getElementById('p-wkd-on'), preview = document.getElementById('p-preview');
  function euro(v) { var n = parseFloat(String(v || '').replace(/\./g, '').replace(',', '.')); return isNaN(n) ? 0 : n; }
  function fmt(n) { return n.toFixed(2).replace('.', ',').replace(/\B(?=(\d{3})+(?!\d))/g, '.') + ' €'; }
  function priceSync() {
    if (!main) return;
    var on = Array.prototype.map.call(document.querySelectorAll('input[name="units"]:checked'), function (c) { return c.value; });
    ['day', 'block', 'hour'].forEach(function (m) { main.classList.toggle('m-' + m, on.indexOf(m) >= 0); });
    if (wkdOn) main.classList.toggle('wkd', wkdOn.checked);
    if (!preview) return;
    var unit = { day: 'Tag', block: 'Zeitblock', hour: 'Stunde' }, best = null;
    on.forEach(function (m) {
      main.querySelectorAll('[name="price_' + m + '"], #ed-units [data-k="price_' + m + '"]').forEach(function (inp) {
        var v = euro(inp.value);
        if (v > 0 && (!best || v < best.v)) best = { v: v, m: m };
      });
    });
    var dep = euro((document.getElementById('z-dep') || {}).value);
    preview.innerHTML = '<div class="fs-5 fw-semibold">' + (best ? 'ab ' + fmt(best.v) + ' <span class="fs-6 fw-normal">je ' + unit[best.m] + '</span>' : 'kostenlos') + '</div>' +
      (dep ? '<div><i class="fa-solid fa-rotate-left me-1 text-secondary"></i>Kaution ' + fmt(dep) + ' (wird erstattet)</div>' : '') +
      '<div class="text-secondary mt-1">Buchbar: ' + (on.map(function (m) { return { day: 'tageweise', block: 'in Zeitblöcken', hour: 'stundenweise' }[m]; }).join(', ') || '–') + '</div>';
  }
  document.addEventListener('change', function (e) { if (e.target.name === 'units' || e.target === wkdOn) priceSync(); });
  document.addEventListener('input', function (e) { if (e.target.closest && e.target.closest('#preise')) priceSync(); });
  priceSync();
})();
