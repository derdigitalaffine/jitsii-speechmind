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

  // Wortwolke: je häufiger desto größer und fetter, bunt; Reihenfolge gemischt (stabil je Begriff), damit die
  // großen Begriffe nicht alle vorn stehen
  function hash(s) { var h = 0; for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return h; }
  function cloud(box, q, big) {
    var rows = q.results.rows || [];
    if (!rows.length) { box.innerHTML = '<p class="text-secondary">Noch keine Begriffe.</p>'; return; }
    var top = rows[0].count, colors = palette(12);
    var items = rows.slice(0, big ? 80 : 50).map(function (r, i) {
      var f = Math.pow(r.count / top, 0.75);
      return { r: r, size: (big ? 1.1 : 0.9) + f * (big ? 4.4 : 2.4), weight: 400 + Math.round(f * 5) * 100, color: colors[i % colors.length], h: hash(r.key || r.label) };
    });
    items.sort(function (a, b) { return (a.h % 997) - (b.h % 997); });
    var biggest = items.reduce(function (m, x) { return x.size > m.size ? x : m; }, items[0]);
    items.splice(items.indexOf(biggest), 1);
    items.splice(Math.floor(items.length / 2), 0, biggest);
    box.innerHTML = '<div class="live-cloud ' + (big ? 'is-big' : '') + '" role="list" aria-label="Wortwolke">' + items.map(function (x) {
      return '<span role="listitem" style="font-size:' + x.size.toFixed(2) + 'rem;font-weight:' + x.weight + ';color:' + x.color + '" title="' + esc(x.r.label) + ': ' + x.r.count + '">' + esc(x.r.label) + '<span class="visually-hidden"> (' + x.r.count + ')</span></span>';
    }).join(' ') + '</div>';
  }
  function table(box, q) {
    var rows = q.results.rows || [];
    box.innerHTML = rows.length ? '<div class="table-responsive live-table"><table class="table table-sm align-middle mb-0"><thead><tr><th>' + (q.kind === 'words' ? 'Begriff' : 'Antwort') + '</th><th class="text-end">Nennungen</th><th class="text-end">%</th></tr></thead><tbody>' +
      rows.map(function (r) { return '<tr><td>' + esc(r.label) + '</td><td class="text-end fw-semibold">' + r.count + '</td><td class="text-end text-secondary">' + r.pct + '</td></tr>'; }).join('') +
      '</tbody></table></div>' : '<p class="text-secondary">Noch keine Antworten.</p>';
  }

  function render(box, q, opts) {
    opts = opts || {};
    var r = q.results;
    if (!r) { box.innerHTML = ''; return; }
    var type = q.chart || 'bar';
    if (type === 'number') { destroy(box); numbers(box, q, opts.big); return; }
    if (type === 'cloud') { destroy(box); cloud(box, q, opts.big); return; }
    if (type === 'table') { destroy(box); table(box, q); return; }
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
