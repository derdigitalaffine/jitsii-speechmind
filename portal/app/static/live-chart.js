// Live-Umfragen: Ergebnisdarstellung für Teilnehmende und Beamer – Balken, Säulen, Torte, Ring (Chart.js) und
// Kennzahlen. Farben aus dem Design des Portals (CSS-Variablen), lesbar in hell und dunkel.
(function () {
  'use strict';
  var charts = new WeakMap();

  function css(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }
  function palette(n) {
    var base = [css('--bs-primary', '#0d6efd'), '#f59f00', '#2fb344', '#d63939', '#ae3ec9', '#17a2b8', '#fd7e14',
      '#6c757d', '#e83e8c', '#20c997', '#6610f2', '#795548'];
    var out = [];
    for (var i = 0; i < n; i++) out.push(base[i % base.length]);
    return out;
  }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function fmt(n) { return (Math.round(n * 100) / 100).toLocaleString('de-DE'); }

  function numbers(box, q, big) {
    var r = q.results, s = r.stats || {};
    var unit = s.unit ? ' ' + esc(s.unit) : '';
    if (!r.total) { box.innerHTML = '<p class="text-secondary">Noch keine Antworten.</p>'; return; }
    var star = q.kind === 'stars';
    box.innerHTML = '<div class="live-numbers ' + (big ? 'is-big' : '') + '">' +
      '<div><span class="live-num">' + fmt(s.avg) + unit + '</span><span class="live-num-label">Durchschnitt' + (star ? ' (Sterne)' : '') + '</span></div>' +
      '<div><span class="live-num">' + fmt(s.median) + unit + '</span><span class="live-num-label">Median</span></div>' +
      '<div><span class="live-num">' + r.total + '</span><span class="live-num-label">Antworten</span></div>' +
      (q.kind === 'slider' ? '<div><span class="live-num">' + fmt(s.min) + '–' + fmt(s.max) + unit + '</span><span class="live-num-label">Spanne</span></div>' : '') +
      '</div>' + (star ? '<div class="live-stars" aria-hidden="true">' + stars(s.avg) + '</div>' : '');
  }
  function stars(avg) {
    var out = '';
    for (var i = 1; i <= 5; i++) {
      var cls = avg >= i - 0.25 ? 'fa-solid fa-star' : (avg >= i - 0.75 ? 'fa-solid fa-star-half-stroke' : 'fa-regular fa-star');
      out += '<i class="' + cls + '"></i>';
    }
    return out;
  }

  function render(box, q, opts) {
    opts = opts || {};
    var r = q.results;
    if (!r) { box.innerHTML = ''; return; }
    var type = q.chart || 'bar';
    if (type === 'number') { destroy(box); numbers(box, q, opts.big); return; }
    if (!window.Chart) { box.textContent = r.rows.map(function (x) { return x.label + ': ' + x.count; }).join(', '); return; }
    var labels = r.rows.map(function (x) { return x.label; });
    var data = r.rows.map(function (x) { return x.count; });
    var round = type === 'pie' || type === 'donut';
    var key = type + '|' + labels.join('\u0001');
    var existing = charts.get(box);
    if (existing && existing.key === key) {
      existing.chart.data.datasets[0].data = data;
      existing.chart.update();
      return;
    }
    destroy(box);
    box.innerHTML = '<div class="live-chart-wrap ' + (round ? 'is-round' : '') + '"><canvas role="img" aria-label="' + esc(q.title) + ': ' +
      esc(r.rows.map(function (x) { return x.label + ' ' + x.count; }).join(', ')) + '"></canvas></div>';
    var fg = css('--bs-body-color', '#222'), grid = css('--bs-border-color', '#ddd');
    var size = opts.big ? 22 : 13;
    var colors = palette(labels.length);
    var chart = new Chart(box.querySelector('canvas'), {
      type: round ? (type === 'pie' ? 'pie' : 'doughnut') : 'bar',
      data: { labels: labels, datasets: [{ data: data, backgroundColor: round ? colors : (q.kind === 'yesno' ? colors : colors[0]), borderWidth: round ? 2 : 0, borderColor: css('--bs-body-bg', '#fff'), borderRadius: round ? 0 : 6 }] },
      options: {
        responsive: true, maintainAspectRatio: false, animation: { duration: 400 },
        indexAxis: type === 'bar' ? 'y' : 'x',
        plugins: { legend: { display: round, position: 'bottom', labels: { color: fg, font: { size: size } } },
          tooltip: { callbacks: { label: function (c) { var t = r.total || 1; return ' ' + c.raw + ' (' + Math.round(100 * c.raw / t) + ' %)'; } } } },
        scales: round ? {} : {
          x: { ticks: { color: fg, font: { size: size }, precision: 0 }, grid: { color: type === 'bar' ? grid : 'transparent' }, beginAtZero: true },
          y: { ticks: { color: fg, font: { size: size }, precision: 0 }, grid: { color: type === 'column' ? grid : 'transparent' }, beginAtZero: true }
        }
      }
    });
    charts.set(box, { key: key, chart: chart });
  }
  function destroy(box) {
    var existing = charts.get(box);
    if (existing) { existing.chart.destroy(); charts.delete(box); }
  }

  window.LiveChart = { render: render, destroy: destroy, esc: esc };
})();
