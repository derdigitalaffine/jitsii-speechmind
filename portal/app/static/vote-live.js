// Live-Modus: Ergebnis alle 3 Sekunden neu laden und als Balken zeigen (für Beamer) – liegend oder stehend.
(function () {
  'use strict';
  var root = document.getElementById('vote-live');
  if (!root || !window.Chart) return;
  var box = document.getElementById('live-results');
  var hidden = document.getElementById('live-hidden');
  var hide = document.getElementById('live-hide');
  var css = getComputedStyle(document.documentElement);
  var primary = css.getPropertyValue('--bs-primary').trim() || '#1f5fa8';
  Chart.defaults.color = css.getPropertyValue('--bs-body-color').trim();
  Chart.defaults.font.size = 16;
  var charts = {}, last = null;
  // Balken liegend (bar) oder stehend (column): Voreinstellung der Abstimmung, Umschalten wird je Abstimmung gemerkt
  var key = 'jsm-vote-chart-' + root.dataset.vote, mode = root.dataset.chart === 'column' ? 'column' : 'bar';
  try { mode = localStorage.getItem(key) || mode; } catch (e) { /* privat */ }
  function setMode(m) {
    mode = m;
    root.querySelectorAll('[data-chart]').forEach(function (b) {
      if (b === root) return;
      var on = b.dataset.chart === mode;
      b.classList.toggle('active', on); b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    try { localStorage.setItem(key, mode); } catch (e) { /* privat */ }
    if (last) draw(last);
  }
  var labels = { draft: 'angehalten', open: 'läuft', closed: 'beendet' };
  var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); };
  function draw(data) {
    last = data;
    document.getElementById('live-count').textContent = data.turnout.ballots;
    var st = document.getElementById('live-status');
    st.textContent = labels[data.status] || data.status;
    st.className = 'badge ' + (data.status === 'open' ? 'text-bg-primary' : data.status === 'closed' ? 'text-bg-success' : 'text-bg-secondary');
    var t = data.turnout;
    document.getElementById('live-turnout').textContent = t.eligible ? ('Beteiligung ' + t.voted + ' / ' + t.eligible + (t.percent != null ? ' (' + t.percent + ' %)' : '')) : '';
    data.results.forEach(function (q, i) {
      var id = 'live-q-' + q.id;
      var card = document.getElementById(id);
      if (!card) {
        card = document.createElement('div');
        card.className = 'card mb-3'; card.id = id;
        card.innerHTML = '<div class="card-body"><div class="fs-4 fw-semibold mb-2">' + (i + 1) + '. ' + esc(q.title) + '</div><div class="small text-secondary mb-2 meta"></div><div class="live-chart"><canvas></canvas></div></div>';
        box.appendChild(card);
      }
      card.querySelector('.live-chart').style.height = (mode === 'column' ? Math.max(260, Math.min(420, 60 + 30 * q.items.length)) : Math.max(140, 44 * q.items.length + 40)) + 'px';
      if (!charts[id] || charts[id].$mode !== mode) {
        if (charts[id]) charts[id].destroy();
        var axis = mode === 'column' ? 'x' : 'y', value = mode === 'column' ? 'y' : 'x';
        var scales = {};
        scales[value] = { beginAtZero: true, ticks: { precision: 0 } };
        charts[id] = new Chart(card.querySelector('canvas'), {
          type: 'bar', data: { labels: [], datasets: [{ data: [], backgroundColor: primary, borderRadius: 4, maxBarThickness: mode === 'column' ? 120 : 60 }] },
          options: { indexAxis: axis, maintainAspectRatio: false, animation: { duration: 400 }, plugins: { legend: { display: false } }, scales: scales }
        });
        charts[id].$mode = mode;
      }
      card.querySelector('.meta').textContent = q.valid + ' gültig' + (q.abstain ? ' · ' + q.abstain + ' Enthaltungen' : '') + ' · ' + q.unit[1];
      var c = charts[id];
      c.data.labels = q.chart.labels; c.data.datasets[0].data = q.chart.values; c.update();
    });
  }
  function load() {
    fetch(root.dataset.src, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) draw(d); }).catch(function () {});
  }
  hide.addEventListener('change', function () { box.classList.toggle('d-none', hide.checked); hidden.classList.toggle('d-none', !hide.checked); });
  document.getElementById('live-full').addEventListener('click', function () {
    if (document.fullscreenElement) document.exitFullscreen(); else root.requestFullscreen && root.requestFullscreen();
  });
  root.querySelectorAll('button[data-chart]').forEach(function (b) { b.addEventListener('click', function () { setMode(b.dataset.chart); }); });
  setMode(mode);
  load();
  setInterval(load, 3000);
})();
