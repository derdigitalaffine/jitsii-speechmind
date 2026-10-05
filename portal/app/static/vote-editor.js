// Abstimmung bearbeiten: Fragen mit Antwortmöglichkeiten (eine, mehrere, Rangfolge, Punkte).
(function () {
  'use strict';
  var root = document.getElementById('vote-questions');
  var form = document.getElementById('vote-form');
  if (!root || !form) return;
  var kinds = JSON.parse(root.dataset.kinds);
  var order = JSON.parse(root.dataset.kindOrder);
  var locked = root.dataset.locked === '1';
  var items = JSON.parse(root.dataset.items || '[]');
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  var uid = function () { return Math.random().toString(36).slice(2, 8); };

  function blank() {
    return { id: null, title: '', description: '', kind: 'single', options: [{ id: uid(), label: 'Ja' }, { id: uid(), label: 'Nein' }],
             min: 1, max: 1, points: 10, abstain: true };
  }
  if (!items.length && !locked) items.push(blank());

  function limits(q) {
    var n = q.options.length;
    if (q.kind === 'multi') {
      return '<div class="row g-2 mt-1"><div class="col-6 col-md-3"><label class="form-label small mb-0">mindestens</label><input class="form-control form-control-sm" type="number" min="0" max="' + n + '" data-f="min" value="' + esc(q.min) + '"></div>' +
        '<div class="col-6 col-md-3"><label class="form-label small mb-0">höchstens</label><input class="form-control form-control-sm" type="number" min="1" max="' + n + '" data-f="max" value="' + esc(q.max || n) + '"></div></div>';
    }
    if (q.kind === 'rank') {
      return '<div class="row g-2 mt-1"><div class="col-12 col-md-6"><label class="form-label small mb-0">Plätze vergeben (höchstens)</label><input class="form-control form-control-sm" type="number" min="1" max="' + n + '" data-f="max" value="' + esc(q.max || n) + '">' +
        '<div class="form-text">Wertung nach Borda: Platz 1 bekommt so viele Punkte, wie es Antworten gibt, jeder weitere Platz einen weniger.</div></div></div>';
    }
    if (q.kind === 'points') {
      return '<div class="row g-2 mt-1"><div class="col-6 col-md-4"><label class="form-label small mb-0">Punkte je Person</label><input class="form-control form-control-sm" type="number" min="1" max="1000" data-f="points" value="' + esc(q.points || 10) + '"></div>' +
        '<div class="col-12 col-md-8 form-text align-self-end">Jede Person verteilt höchstens so viele Punkte – z. B. für einen Bürgerhaushalt.</div></div>';
    }
    return '';
  }

  function render() {
    root.innerHTML = items.map(function (q, i) {
      var opts = q.options.map(function (o, j) {
        return '<div class="input-group input-group-sm mb-1" data-o="' + j + '"><span class="input-group-text">' + (j + 1) + '</span>' +
          '<input class="form-control" data-of="label" value="' + esc(o.label) + '" placeholder="Antwort" aria-label="Antwort ' + (j + 1) + '" ' + (locked ? 'disabled' : '') + '>' +
          '<input class="form-control d-none d-md-block" data-of="info" value="' + esc(o.info || '') + '" placeholder="Erläuterung (optional)" aria-label="Erläuterung" ' + (locked ? 'disabled' : '') + '>' +
          (locked ? '' : '<button class="btn btn-outline-secondary" type="button" data-oup="' + j + '" title="nach oben" aria-label="nach oben"><i class="fa-solid fa-arrow-up"></i></button>' +
          '<button class="btn btn-outline-danger" type="button" data-odel="' + j + '" title="entfernen" aria-label="Antwort entfernen"><i class="fa-solid fa-xmark"></i></button>') + '</div>';
      }).join('');
      return '<div class="card mb-3" data-q="' + i + '"><div class="card-body">' +
        '<div class="d-flex gap-2 align-items-start mb-2"><span class="badge text-bg-primary mt-2">' + (i + 1) + '</span>' +
        '<div class="flex-grow-1"><input class="form-control fw-semibold" data-f="title" value="' + esc(q.title) + '" placeholder="Frage, z. B. „Soll der Spielplatz am Weiher erneuert werden?“" aria-label="Frage" ' + (locked ? 'disabled' : '') + '>' +
        '<textarea class="form-control form-control-sm mt-1" rows="1" data-f="description" placeholder="Erläuterung (optional)" aria-label="Erläuterung zur Frage" ' + (locked ? 'disabled' : '') + '>' + esc(q.description) + '</textarea></div>' +
        (locked ? '' : '<div class="btn-group btn-group-sm"><button class="btn btn-outline-secondary" type="button" data-qup="' + i + '" title="nach oben" aria-label="Frage nach oben"><i class="fa-solid fa-arrow-up"></i></button>' +
        '<button class="btn btn-outline-danger" type="button" data-qdel="' + i + '" title="Frage löschen" aria-label="Frage löschen"><i class="fa-regular fa-trash-can"></i></button></div>') + '</div>' +
        '<div class="d-flex flex-wrap gap-2 align-items-center mb-2"><select class="form-select form-select-sm w-auto" data-f="kind" aria-label="Art der Frage" ' + (locked ? 'disabled' : '') + '>' +
        order.map(function (k) { return '<option value="' + k + '"' + (q.kind === k ? ' selected' : '') + '>' + esc(kinds[k][0]) + '</option>'; }).join('') + '</select>' +
        '<div class="form-check form-switch mb-0"><input class="form-check-input" type="checkbox" role="switch" id="abs-' + i + '" data-f="abstain" ' + (q.abstain ? 'checked' : '') + ' ' + (locked ? 'disabled' : '') + '><label class="form-check-label small" for="abs-' + i + '">Enthaltung anbieten</label></div></div>' +
        opts + (locked ? '' : '<button class="btn btn-sm btn-link px-0" type="button" data-oadd="1"><i class="fa-solid fa-plus me-1"></i>Antwort hinzufügen</button>' +
        '<button class="btn btn-sm btn-link" type="button" data-opaste="1"><i class="fa-solid fa-paste me-1"></i>Liste einfügen</button>') +
        (locked ? '' : limits(q)) + '</div></div>';
    }).join('') || '<div class="text-secondary">Noch keine Fragen.</div>';
  }

  // Bei Rangfolge/Mehrfachauswahl wächst „höchstens“ mit, solange es auf „alle“ stand
  function grow(q, change) {
    var all = q.max >= q.options.length;
    change();
    if (all && (q.kind === 'rank' || q.kind === 'multi')) q.max = q.options.length;
  }

  function qOf(el) { var c = el.closest('[data-q]'); return c ? items[+c.dataset.q] : null; }

  root.addEventListener('input', function (e) {
    var q = qOf(e.target); if (!q) return;
    var f = e.target.dataset.f, of = e.target.dataset.of;
    if (of) { q.options[+e.target.closest('[data-o]').dataset.o][of] = e.target.value; return; }
    if (f === 'title' || f === 'description') q[f] = e.target.value;
    if (f === 'min' || f === 'max' || f === 'points') q[f] = parseInt(e.target.value, 10) || 0;
  });
  root.addEventListener('change', function (e) {
    var q = qOf(e.target); if (!q) return;
    if (e.target.dataset.f === 'kind') {
      q.kind = e.target.value;
      q.min = q.kind === 'multi' ? 0 : 1;
      q.max = q.kind === 'single' ? 1 : q.options.length;
      render();
    }
    if (e.target.dataset.f === 'abstain') q.abstain = e.target.checked;
  });
  root.addEventListener('click', function (e) {
    var b = e.target.closest('button'); if (!b) return;
    var q = qOf(b);
    if (b.dataset.qdel) { items.splice(+b.dataset.qdel, 1); render(); }
    else if (b.dataset.qup) { var i = +b.dataset.qup; if (i > 0) { items.splice(i - 1, 0, items.splice(i, 1)[0]); render(); } }
    else if (b.dataset.odel && q) { if (q.options.length > 2) { q.options.splice(+b.dataset.odel, 1); q.max = Math.min(q.max, q.options.length); render(); } }
    else if (b.dataset.oup && q) { var j = +b.dataset.oup; if (j > 0) { q.options.splice(j - 1, 0, q.options.splice(j, 1)[0]); render(); } }
    else if (b.dataset.oadd && q) { grow(q, function () { q.options.push({ id: uid(), label: '' }); }); render(); var ins = root.querySelectorAll('[data-q="' + items.indexOf(q) + '"] [data-of="label"]'); ins[ins.length - 1].focus(); }
    else if (b.dataset.opaste && q) {
      var text = window.prompt('Eine Antwort je Zeile (z. B. aus Excel kopiert):');
      if (text) {
        var lines = text.split(/\r?\n/).map(function (s) { return s.trim(); }).filter(Boolean);
        grow(q, function () { q.options = q.options.filter(function (o) { return o.label.trim(); }).concat(lines.map(function (l) { return { id: uid(), label: l }; })); });
        render();
      }
    }
  });
  var add = document.getElementById('vote-add-q');
  if (add) add.addEventListener('click', function () { items.push(blank()); render(); root.querySelector('[data-q="' + (items.length - 1) + '"] [data-f="title"]').focus(); });
  form.addEventListener('submit', function () {
    document.getElementById('questions-json').value = locked ? '' : JSON.stringify(items);
    if (locked) document.getElementById('questions-json').removeAttribute('name');
  });
  render();
})();
