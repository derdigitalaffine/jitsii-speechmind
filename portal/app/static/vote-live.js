// Live-Modus: Ergebnis alle 3 Sekunden neu laden und als Balken zeigen (für Beamer).
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
  var charts = {};
  var labels = { draft: 'angehalten', open: 'läuft', closed: 'beendet' };
  var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); };
  function draw(data) {
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
        card.innerHTML = '<div class="card-body"><div class="fs-4 fw-semibold mb-2">' + (i + 1) + '. ' + esc(q.title) + '</div><div class="small text-secondary mb-2 meta"></div><div style="height:' + Math.max(140, 44 * q.items.length + 40) + 'px"><canvas></canvas></div></div>';
        box.appendChild(card);
        charts[id] = new Chart(card.querySelector('canvas'), {
          type: 'bar', data: { labels: [], datasets: [{ data: [], backgroundColor: primary, borderRadius: 4 }] },
          options: { indexAxis: 'y', maintainAspectRatio: false, animation: { duration: 400 }, plugins: { legend: { display: false } },
                     scales: { x: { beginAtZero: true, ticks: { precision: 0 } } } }
        });
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
  load();
  setInterval(load, 3000);
})();
