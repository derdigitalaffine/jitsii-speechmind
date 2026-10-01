/* Diagramme (Chart.js): Kurzlink-Aufrufe und Formular-Auswertungen. */
(function () {
  'use strict';
  if (!window.Chart) { return; }
  var css = getComputedStyle(document.documentElement);
  var primary = css.getPropertyValue('--bs-primary').trim() || '#1f5fa8';
  var text = css.getPropertyValue('--bs-body-color').trim() || '#212529';
  var grid = css.getPropertyValue('--bs-border-color').trim() || '#dee2e6';
  var palette = [primary, '#0f766e', '#b45309', '#7e22ce', '#be185d', '#15803d', '#334155', '#b91c1c', '#0369a1', '#a16207'];
  Chart.defaults.color = text;
  Chart.defaults.borderColor = grid;
  Chart.defaults.font.family = css.getPropertyValue('--bs-body-font-family');

  var visits = document.getElementById('visits-data');
  var canvas = document.getElementById('visits-chart');
  if (visits && canvas) {
    var data = JSON.parse(visits.textContent);
    new Chart(canvas, {
      type: 'bar',
      data: { labels: data.labels, datasets: [{ label: 'Aufrufe', data: data.values, backgroundColor: primary, borderRadius: 3 }] },
      options: {
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } }, x: { grid: { display: false } } }
      }
    });
  }

  /* Formular-Auswertung: <canvas data-chart='{"type":"bar","labels":[..],"values":[..]}'> */
  document.querySelectorAll('canvas[data-chart]').forEach(function (el) {
    var cfg = JSON.parse(el.dataset.chart);
    var round = cfg.type === 'doughnut';
    new Chart(el, {
      type: cfg.type || 'bar',
      data: {
        labels: cfg.labels,
        datasets: [{ data: cfg.values, backgroundColor: round ? palette : primary, borderRadius: round ? 0 : 3 }]
      },
      options: {
        indexAxis: cfg.horizontal ? 'y' : 'x',
        maintainAspectRatio: false,
        plugins: { legend: { display: round, position: 'right' } },
        scales: round ? {} : { x: { beginAtZero: true, ticks: { precision: 0 } }, y: { beginAtZero: true, ticks: { precision: 0 } } }
      }
    });
  });
})();
