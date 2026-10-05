// Formular-Einstellungen: Gebühr mit Zuschlägen nach Antworten.
(function () {
  'use strict';
  var data = document.getElementById('fee-data');
  var out = document.getElementById('fee-json');
  if (!data || !out) return;
  var D = JSON.parse(data.textContent);
  var rules = D.rules.map(function (r) { return Object.assign({}, r, { amount: (r.cents / 100).toFixed(2).replace('.', ',') }); });
  var box = document.getElementById('fee-rules');
  var on = document.getElementById('fee-on'), body = document.getElementById('fee-body');
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); };
  function qOpts(sel) { return D.questions.map(function (q) { return '<option value="' + esc(q.id) + '"' + (q.id === sel ? ' selected' : '') + '>' + esc(q.title) + '</option>'; }).join(''); }
  function render() {
    box.innerHTML = rules.map(function (r, i) {
      var q = D.questions.find(function (x) { return x.id === r.q; }) || {};
      var val = r.op === 'each' ? '' : (q.options && q.options.length
        ? '<select class="form-select form-select-sm" data-k="value">' + q.options.map(function (o) { return '<option' + (o === r.value ? ' selected' : '') + '>' + esc(o) + '</option>'; }).join('') + '</select>'
        : '<input class="form-control form-control-sm" data-k="value" value="' + esc(r.value) + '" placeholder="Antwort">');
      return '<div class="row g-2 align-items-center mb-1" data-i="' + i + '">' +
        '<div class="col-md-4"><select class="form-select form-select-sm" data-k="q" aria-label="Frage">' + qOpts(r.q) + '</select></div>' +
        '<div class="col-md-2"><select class="form-select form-select-sm" data-k="op" aria-label="Art"><option value="eq"' + (r.op !== 'each' ? ' selected' : '') + '>ist gleich</option><option value="each"' + (r.op === 'each' ? ' selected' : '') + '>je Anzahl</option></select></div>' +
        '<div class="col-md-2">' + val + '</div>' +
        '<div class="col-6 col-md-2"><div class="input-group input-group-sm"><span class="input-group-text">+</span><input class="form-control" data-k="amount" value="' + esc(r.amount) + '" inputmode="decimal" aria-label="Betrag"><span class="input-group-text">€</span></div></div>' +
        '<div class="col-5 col-md-1"><input class="form-control form-control-sm" data-k="label" value="' + esc(r.label) + '" placeholder="Text" aria-label="Bezeichnung"></div>' +
        '<div class="col-1"><button class="btn btn-sm btn-outline-danger" type="button" data-del="' + i + '" aria-label="Regel entfernen"><i class="fa-solid fa-xmark"></i></button></div></div>';
    }).join('') + (D.questions.length ? '<button class="btn btn-sm btn-outline-primary" type="button" id="fee-add"><i class="fa-solid fa-plus me-1"></i>Zuschlag hinzufügen</button>' : '<div class="small text-secondary">Keine passenden Fragen im Formular.</div>');
  }
  box.addEventListener('change', function (e) {
    var row = e.target.closest('[data-i]'); if (!row) return;
    var r = rules[+row.dataset.i]; r[e.target.dataset.k] = e.target.value;
    if (e.target.dataset.k === 'q' || e.target.dataset.k === 'op') { var q = D.questions.find(function (x) { return x.id === r.q; }); r.value = q && q.options && q.options[0] || ''; render(); }
  });
  box.addEventListener('input', function (e) { var row = e.target.closest('[data-i]'); if (row) rules[+row.dataset.i][e.target.dataset.k] = e.target.value; });
  box.addEventListener('click', function (e) {
    if (e.target.closest('#fee-add')) { var q = D.questions[0]; rules.push({ q: q.id, op: 'eq', value: q.options[0] || '', amount: '', label: '' }); render(); }
    var d = e.target.closest('[data-del]'); if (d) { rules.splice(+d.dataset.del, 1); render(); }
  });
  function toggle() { body.classList.toggle('d-none', !on.checked); }
  on.addEventListener('change', toggle);
  out.form.addEventListener('submit', function () {
    var req = document.getElementById('fee-req');
    out.value = JSON.stringify({ enabled: on.checked, label: document.getElementById('fee-label').value, base: document.getElementById('fee-base').value,
      days: document.getElementById('fee-days').value, cost_center: document.getElementById('fee-cc').value, require: req ? req.checked : false,
      methods: Array.from(document.querySelectorAll('.fee-method:checked')).map(function (x) { return x.value; }), rules: rules });
  });
  render(); toggle();
})();
