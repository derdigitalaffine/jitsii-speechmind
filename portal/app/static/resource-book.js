// Ressource buchen: Buchungsart umschalten, Preis und Verfügbarkeit live vom Server holen.
(function () {
  'use strict';
  var form = document.getElementById('res-form');
  if (!form) return;
  var out = document.getElementById('res-quote');
  var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); };
  function mode() {
    var r = form.querySelector('input[name="mode"]:checked') || form.querySelector('input[name="mode"]');
    return r ? r.value : 'day';
  }
  function sync() {
    var m = mode();
    form.querySelectorAll('.res-when').forEach(function (box) {
      var on = box.dataset.mode === m;
      box.classList.toggle('d-none', !on);
      box.querySelectorAll('input, select').forEach(function (el) { el.disabled = !on; });
    });
    var t = form.querySelector('#r-tariff'), proof = document.getElementById('r-proof-box');
    if (t && proof) {
      var need = t.selectedOptions[0] && t.selectedOptions[0].dataset.proof === '1';
      proof.classList.toggle('d-none', !need);
    }
  }
  var timer = null, seq = 0;
  function quote() {
    clearTimeout(timer);
    timer = setTimeout(function () {
      var my = ++seq;
      var body = new FormData(form);
      ['proof', 'website'].forEach(function (k) { body.delete(k); });
      Array.from(body.keys()).forEach(function (k) { if (k.indexOf('q_') === 0) body.delete(k); });
      fetch(form.dataset.quote, { method: 'POST', body: body, credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } })
        .then(function (r) { return r.json(); }).then(function (q) {
          if (my !== seq) return;
          var h = '';
          if (q.when) h += '<div class="fw-semibold mb-1"><i class="fa-regular fa-calendar me-1"></i>' + esc(q.when) + '</div>';
          if (q.errors.length) {
            h += '<div class="alert alert-warning py-2 small mb-2"><ul class="mb-0 ps-3">' + q.errors.map(function (e) { return '<li>' + esc(e) + '</li>'; }).join('') + '</ul></div>';
          } else if (q.ok) {
            h += '<div class="alert alert-success py-1 small mb-2"><i class="fa-solid fa-circle-check me-1"></i>frei</div>';
          }
          q.warnings.forEach(function (w) { h += '<div class="small text-warning-emphasis mb-1"><i class="fa-solid fa-triangle-exclamation me-1"></i>' + esc(w) + '</div>'; });
          if (q.lines.length) {
            h += '<table class="table table-sm small mb-0"><tbody>' + q.lines.map(function (l) {
              return '<tr' + (l.kind === 'deposit' ? ' class="text-secondary"' : '') + '><td>' + esc(l.label) + (l.qty !== 1 && l.kind === 'rent' ? ' <span class="text-secondary">× ' + esc(l.qty) + '</span>' : '') + '</td><td class="text-end text-nowrap">' + esc(l.money) + '</td></tr>';
            }).join('') + '</tbody><tfoot><tr class="fw-semibold"><td>Summe</td><td class="text-end text-nowrap">' + esc(q.total) + '</td></tr></tfoot></table>';
          }
          out.innerHTML = h || '<div class="text-secondary small">Zeitraum wählen – der Preis erscheint hier.</div>';
        }).catch(function () {});
    }, 350);
  }
  form.addEventListener('change', function () { sync(); quote(); });
  form.addEventListener('input', function (e) { if (e.target.type === 'number' || e.target.type === 'time') quote(); });
  // „Bis“ folgt „Von“, solange es leer oder früher ist
  var from = form.querySelector('#r-from'), to = form.querySelector('#r-to');
  if (from && to) from.addEventListener('change', function () { if (!to.value || to.value < from.value) to.value = from.value; });
  sync();
  quote();
})();
