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

  // Generischer Zeilen-Editor: cols = [{key, label, type, cls, placeholder, options}]
  function table(el, rows, cols, blank, addLabel) {
    function render() {
      el.innerHTML = (rows.length ? rows.map(function (r, i) {
        return '<div class="row g-2 align-items-end mb-2 pb-2 border-bottom" data-i="' + i + '">' + cols.map(function (c) {
          var v = r[c.key];
          var input;
          if (c.type === 'check') {
            input = '<div class="form-check mb-1"><input class="form-check-input" type="checkbox" data-k="' + c.key + '" id="' + el.id + i + c.key + '"' + (v ? ' checked' : '') + '><label class="form-check-label small" for="' + el.id + i + c.key + '">' + esc(c.label) + '</label></div>';
            return '<div class="' + (c.cls || 'col-auto') + '">' + input + '</div>';
          }
          if (c.type === 'select') {
            input = '<select class="form-select form-select-sm" data-k="' + c.key + '">' + c.options.map(function (o) { return '<option value="' + o[0] + '"' + (String(v) === String(o[0]) ? ' selected' : '') + '>' + esc(o[1]) + '</option>'; }).join('') + '</select>';
          } else {
            input = '<input class="form-control form-control-sm" data-k="' + c.key + '" type="' + (c.type || 'text') + '" value="' + esc(v == null ? '' : v) + '" placeholder="' + esc(c.placeholder || '') + '"' + (c.type === 'time' ? '' : '') + '>';
          }
          return '<div class="' + (c.cls || 'col') + '"><label class="form-label small mb-0">' + esc(c.label) + '</label>' + input + '</div>';
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

  var priceCols = [
    { key: 'price_day', label: 'Tag €', cls: 'col-4 col-md-2' }, { key: 'price_block', label: 'Block €', cls: 'col-4 col-md-2' },
    { key: 'price_hour', label: 'Stunde €', cls: 'col-4 col-md-2' }, { key: 'wkd_day', label: 'Tag WE/FT €', cls: 'col-4 col-md-2' },
    { key: 'wkd_block', label: 'Block WE/FT €', cls: 'col-4 col-md-2' }, { key: 'wkd_hour', label: 'Std. WE/FT €', cls: 'col-4 col-md-2' }];
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
  var extras = table(document.getElementById('ed-extras'), D.extras, [
    { key: 'name', label: 'Leistung', cls: 'col-12 col-md-3', placeholder: 'z. B. Endreinigung' },
    { key: 'price', label: 'Preis €', cls: 'col-4 col-md-1' },
    { key: 'per', label: 'Abrechnung', type: 'select', cls: 'col-4 col-md-2', options: Object.keys(D.per).map(function (k) { return [k, D.per[k]]; }) },
    { key: 'max_qty', label: 'max. Anzahl', type: 'number', cls: 'col-4 col-md-1' },
    { key: 'stock', label: 'Bestand', type: 'number', cls: 'col-4 col-md-1', placeholder: '∞' },
    { key: 'description', label: 'Hinweis', cls: 'col-8 col-md-2' },
    { key: 'mandatory', label: 'Pflicht', type: 'check', cls: 'col-auto' }, { key: 'active', label: 'aktiv', type: 'check', cls: 'col-auto' }],
    function () { return { name: '', price: '', per: 'once', max_qty: 1, stock: '', description: '', mandatory: false, active: true }; }, 'Zusatzleistung hinzufügen');
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
})();
