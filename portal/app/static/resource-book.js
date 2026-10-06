// Ressource buchen: Buchungsart umschalten, Preis und Verfügbarkeit live vom Server, freie Zeiten des Tages
// zum Antippen, öffentlich in drei Schritten (Wann → Angaben → Prüfen) und Warteliste bei belegtem Zeitraum.
(function () {
  'use strict';
  var form = document.getElementById('res-form');
  if (!form) return;
  var out = document.getElementById('res-quote');
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); };
  var last = null;   // letzte Antwort von /quote

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

  // --- Preis und Verfügbarkeit ---------------------------------------------------------
  var timer = null, seq = 0;
  function quote() {
    clearTimeout(timer);
    timer = setTimeout(function () {
      var my = ++seq;
      var body = new FormData(form);
      ['proof', 'website', 'action'].forEach(function (k) { body.delete(k); });
      Array.from(body.keys()).forEach(function (k) { if (k.indexOf('q_') === 0) body.delete(k); });
      fetch(form.dataset.quote, { method: 'POST', body: body, credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } })
        .then(function (r) { return r.json(); }).then(function (q) {
          if (my !== seq) return;
          last = q;
          var h = '';
          if (!q.when) {   // noch kein Zeitraum gewählt: keine Fehlermeldung, nur ein Hinweis
            out.innerHTML = '<div class="text-secondary small">Zeitraum wählen – Verfügbarkeit und Preis erscheinen hier.</div>';
            var off = document.getElementById('res-wait-offer');
            if (off) off.classList.add('d-none');
            updateSteps();
            return;
          }
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
          var offer = document.getElementById('res-wait-offer');
          if (offer) offer.classList.toggle('d-none', !q.waitlist);
          updateSteps();
        }).catch(function () {});
    }, 300);
  }

  // --- Freie Zeiten des Tages ------------------------------------------------------------
  var freeBox = document.getElementById('res-free');
  function addMinutes(hm, mins) {
    var p = hm.split(':'), t = Math.min(24 * 60, (+p[0]) * 60 + (+p[1]) + mins);
    return ('0' + Math.floor(t / 60)).slice(-2) + ':' + ('0' + (t % 60)).slice(-2);
  }
  function minutes(hm) { var p = hm.split(':'); return (+p[0]) * 60 + (+p[1]); }
  function loadDay() {
    var m = mode();
    if (m !== 'hour' && m !== 'block') return;
    var input = form.querySelector('.res-when[data-mode="' + m + '"] .js-day');
    if (!input || !input.value || !form.dataset.day) { if (freeBox) freeBox.innerHTML = ''; return; }
    var params = new URLSearchParams({ date: input.value });
    form.querySelectorAll('.js-unit:checked').forEach(function (u) { params.append('units', u.value); });
    var wt = form.querySelector('input[name="wait_token"]');
    if (wt) params.set('wait', wt.value);
    fetch(form.dataset.day + '?' + params, { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
      if (!d) return;
      if (m === 'block') {
        form.querySelectorAll('.res-block').forEach(function (row) {
          var cb = row.querySelector('input'), info = d.blocks.find(function (b) { return String(b.id) === cb.value; });
          var busy = info && !info.free;
          row.querySelector('.js-busy').classList.toggle('d-none', !busy);
        });
        return;
      }
      if (!freeBox) return;
      if (d.closed) { freeBox.innerHTML = '<span class="text-danger"><i class="fa-solid fa-ban me-1"></i>An diesem Tag kann nicht gebucht werden.</span>'; return; }
      if (!d.free.length) { freeBox.innerHTML = '<span class="text-danger"><i class="fa-solid fa-circle-xmark me-1"></i>An diesem Tag ist nichts mehr frei.</span>'; return; }
      var slot = +form.dataset.slot || 60, min = Math.max(+form.dataset.min || 0, slot), max = +form.dataset.max || 0;
      freeBox.innerHTML = '<span class="text-secondary me-1">Frei – Beginn antippen, Ende dann anpassen:</span>' + d.free.map(function (f) {
        return '<button type="button" class="btn btn-sm btn-outline-success me-1 mb-1 js-free" data-from="' + f[0] + '" data-to="' + f[1] + '">' + esc(f[0]) + '–' + esc(f[1]) + '</button>';
      }).join('') + (d.busy.length ? '<div class="text-secondary mt-1">Belegt: ' + d.busy.map(function (b) { return esc(b[0]) + '–' + esc(b[1]); }).join(', ') + '</div>' : '');
      freeBox.querySelectorAll('.js-free').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var from = btn.dataset.from, to = btn.dataset.to;
          // Beginn auf das Raster runden, Ende = Beginn + Mindestdauer (mind. 1 Std.) – höchstens bis zum Ende der Lücke
          var start = Math.ceil(minutes(from) / slot) * slot, gap = minutes(to);
          var end = start + Math.max(min, Math.ceil(60 / slot) * slot);
          if (max && end - start > max) end = start + max;
          if (end > gap) end = start + Math.floor((gap - start) / slot) * slot;
          var t1 = form.querySelector('#r-t1'), t2 = form.querySelector('#r-t2');
          t1.value = addMinutes('00:00', start); t2.value = addMinutes('00:00', end);
          quote();
        });
      });
    }).catch(function () {});
  }

  // --- Schritte (nur öffentlich) ------------------------------------------------------------
  var stepped = form.classList.contains('res-public') && window.matchMedia;
  var step = 1;
  var steps = form.querySelectorAll('.res-step');
  var nav = form.querySelector('.res-steps');
  var next = document.getElementById('res-next'), back = document.getElementById('res-back');
  var submit = document.getElementById('res-submit'), add = document.getElementById('res-add');
  function invalidIn(n) {
    var bad = null;
    form.querySelectorAll('.res-step[data-step="' + n + '"] input, .res-step[data-step="' + n + '"] select, .res-step[data-step="' + n + '"] textarea').forEach(function (el) {
      if (!bad && !el.disabled && el.offsetParent !== null && el.willValidate && !el.checkValidity()) bad = el;
    });
    return bad;
  }
  function review() {
    var box = document.getElementById('res-review');
    if (!box) return;
    var get = function (n) { var el = form.querySelector('[name="' + n + '"]'); return el ? el.value.trim() : ''; };
    var who = [get('name'), get('email'), get('phone')].filter(Boolean).join(' · ');
    var addr = [get('street'), (get('zip') + ' ' + get('city')).trim()].filter(Boolean).join(', ');
    box.innerHTML = '<h3 class="h6">Bitte prüfen</h3><dl class="row small mb-0">' +
      '<dt class="col-sm-4">Wann</dt><dd class="col-sm-8">' + esc(last && last.when || '–') + '</dd>' +
      '<dt class="col-sm-4">Anlass</dt><dd class="col-sm-8">' + esc(get('title') || '–') + (get('persons') ? ', ' + esc(get('persons')) + ' Personen' : '') + '</dd>' +
      (who ? '<dt class="col-sm-4">Kontakt</dt><dd class="col-sm-8">' + esc(who) + (addr ? '<br>' + esc(addr) : '') + '</dd>' : '') +
      '</dl><div class="small text-secondary mt-1"><button type="button" class="btn btn-link btn-sm p-0 js-goto" data-step="1">Zeitraum ändern</button> · <button type="button" class="btn btn-link btn-sm p-0 js-goto" data-step="2">Angaben ändern</button></div>';
    box.querySelectorAll('.js-goto').forEach(function (b) { b.addEventListener('click', function () { show(+b.dataset.step); }); });
  }
  function updateSteps() {
    if (!stepped) return;
    if (next) next.disabled = step === 1 && !(last && last.ok);
  }
  function show(n, initial) {
    if (!stepped) return;
    step = n;
    form.classList.remove('step-1', 'step-2', 'step-3');
    form.classList.add('step-' + n);
    steps.forEach(function (s) { s.classList.toggle('d-none', +s.dataset.step !== n); });
    if (nav) nav.querySelectorAll('li').forEach(function (li) {
      li.classList.toggle('active', +li.dataset.step === n);
      li.classList.toggle('done', +li.dataset.step < n);
    });
    if (back) back.classList.toggle('d-none', n === 1);
    if (next) next.classList.toggle('d-none', n === 3);
    if (submit) submit.classList.toggle('d-none', n !== 3);
    if (add) add.classList.toggle('d-none', n !== 3);
    out.classList.toggle('d-none', n === 2);
    if (n === 3) review();
    updateSteps();
    // Nur beim Weiterblättern und nur, wenn der Formularanfang nicht mehr zu sehen ist – sonst springt die Seite
    if (!initial && form.getBoundingClientRect().top < 0) form.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  if (stepped && steps.length === 3) {
    form.classList.add('stepped');
    if (nav) nav.classList.remove('d-none');
    if (nav) nav.querySelectorAll('li').forEach(function (li) {
      li.addEventListener('click', function () { var n = +li.dataset.step; if (n < step) show(n); });
    });
    if (next) next.addEventListener('click', function () {
      if (step === 1 && !(last && last.ok)) return;
      var bad = invalidIn(step);
      if (bad) { bad.reportValidity(); bad.focus(); return; }
      show(step + 1);
    });
    if (back) back.addEventListener('click', function () { show(step - 1); });
    form.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && step < 3 && e.target.tagName === 'INPUT' && e.target.type !== 'submit') { e.preventDefault(); next.click(); }
    });
    // Nach einer Rückmeldung des Servers (Fehler) die Seite mit allen Angaben zeigen: Schritt 2
    show(document.querySelector('.alert-danger, .has-error, .is-invalid') && form.querySelector('[name="title"]').value ? 2 : 1, true);
  } else {
    stepped = false;
  }
  // Warteliste: Name und E-Mail braucht es auch ohne Schritt 2
  var waitBtn = document.getElementById('res-wait-btn');
  if (waitBtn) waitBtn.addEventListener('click', function (e) {
    var missing = ['name', 'email'].map(function (n) { return form.querySelector('[name="' + n + '"]'); })
      .filter(function (el) { return el && !el.value.trim(); });
    if (missing.length) {
      e.preventDefault();
      if (stepped) show(2);
      missing[0].focus();
      missing[0].reportValidity && missing[0].reportValidity();
    }
  });

  // --- Ereignisse ------------------------------------------------------------------------------
  form.addEventListener('change', function (e) {
    sync();
    quote();
    if (e.target.classList.contains('js-day') || e.target.classList.contains('js-unit') || e.target.name === 'mode') loadDay();
  });
  form.addEventListener('input', function (e) { if (e.target.type === 'number' || e.target.type === 'time') quote(); });
  var from = form.querySelector('#r-from'), to = form.querySelector('#r-to');
  if (from && to) from.addEventListener('change', function () { if (!to.value || to.value < from.value) to.value = from.value; });
  var target = form.querySelector('#r-target');
  if (target) target.addEventListener('change', function () { location.href = target.dataset.reload + target.value; });
  sync();
  quote();
  loadDay();
})();
