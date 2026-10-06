// Live-Umfrage, Präsentationsmodus (Beamer): Frage groß, Ergebnis live (alle 2 Sekunden), QR-Code zur Teilnahme.
// Tasten: ← → (bzw. Bild ↑/↓, Leertaste) Fragen, R Ergebnis ein/aus, Q QR-Code ein/aus, F Vollbild.
(function () {
  'use strict';
  var root = document.getElementById('live-present');
  if (!root || !window.fetch) return;
  var id = root.dataset.poll, csrf = root.dataset.csrf, moderated = root.dataset.pacing === 'moderated';
  var chartNames = JSON.parse(document.getElementById('lp-chartnames').textContent);
  var kinds = JSON.parse(document.getElementById('lp-kinds').textContent);
  var titleEl = document.getElementById('lp-title'), resultEl = document.getElementById('lp-result');
  var countEl = document.getElementById('lp-count'), posEl = document.getElementById('lp-pos');
  var chartsEl = document.getElementById('lp-charts');
  var state = null, index = 0;

  function post(url, data) {
    var fd = new FormData();
    fd.append('csrf', csrf);
    Object.keys(data || {}).forEach(function (k) { fd.append(k, data[k]); });
    return fetch(url, { method: 'POST', body: fd, credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }
  function current() {
    if (!state || !state.questions.length) return null;
    if (moderated) {
      var i = state.questions.findIndex(function (q) { return q.id === state.current; });
      index = i >= 0 ? i : 0;
    }
    index = Math.max(0, Math.min(state.questions.length - 1, index));
    return state.questions[index];
  }
  function draw() {
    var q = current();
    if (!q) { titleEl.textContent = 'Noch keine Fragen'; resultEl.innerHTML = ''; countEl.textContent = '0'; return; }
    if (titleEl.textContent !== q.title) titleEl.textContent = q.title;
    posEl.textContent = 'Frage ' + (index + 1) + ' von ' + state.questions.length + ' · ' + (kinds[q.kind] ? kinds[q.kind][0] : '');
    countEl.textContent = q.results ? q.results.total : 0;
    var allowed = kinds[q.kind] ? kinds[q.kind][2] : [];
    var html = allowed.map(function (c) {
      return '<button type="button" class="btn btn-outline-secondary ' + (c === q.chart ? 'active' : '') + '" data-chart="' + c + '" aria-pressed="' + (c === q.chart) + '">' + chartNames[c] + '</button>';
    }).join('');
    if (chartsEl.innerHTML !== html) chartsEl.innerHTML = html;
    if (window.LiveChart) LiveChart.render(resultEl, q, { big: true });
  }
  function load() {
    fetch('/votes/live/' + id + '/state.json', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { return r.json(); }).then(function (s) { state = s; draw(); }).catch(function () {});
  }
  function go(dir) {
    if (moderated) {
      post('/votes/live/' + id + '/schritt', { dir: dir > 0 ? 'next' : 'prev' }).then(function (s) { state = s; draw(); });
    } else {
      index += dir;
      draw();
    }
  }
  function toggle(cls, btn) {
    var on = root.classList.toggle(cls);
    btn.setAttribute('aria-pressed', on ? 'false' : 'true');
  }
  document.getElementById('lp-prev').addEventListener('click', function () { go(-1); });
  document.getElementById('lp-next').addEventListener('click', function () { go(1); });
  document.getElementById('lp-results').addEventListener('click', function () { toggle('hide-results', this); });
  document.getElementById('lp-qr').addEventListener('click', function () { toggle('no-qr', this); });
  document.getElementById('lp-full').addEventListener('click', function () {
    if (document.fullscreenElement) document.exitFullscreen(); else if (root.requestFullscreen) root.requestFullscreen();
  });
  chartsEl.addEventListener('click', function (e) {
    var b = e.target.closest('[data-chart]'), q = current();
    if (!b || !q) return;
    post('/votes/live/' + id + '/fragen/' + q.id + '/chart', { chart: b.dataset.chart }).then(function (s) { state = s; draw(); });
  });
  document.addEventListener('keydown', function (e) {
    if (e.target.closest && e.target.closest('input, textarea, select')) return;
    var k = e.key;
    if (k === 'ArrowRight' || k === 'PageDown' || k === ' ') { e.preventDefault(); go(1); }
    else if (k === 'ArrowLeft' || k === 'PageUp') { e.preventDefault(); go(-1); }
    else if (k === 'r' || k === 'R') toggle('hide-results', document.getElementById('lp-results'));
    else if (k === 'q' || k === 'Q') toggle('no-qr', document.getElementById('lp-qr'));
    else if (k === 'f' || k === 'F') document.getElementById('lp-full').click();
  });
  root.focus();
  load();
  setInterval(load, 2000);
})();
