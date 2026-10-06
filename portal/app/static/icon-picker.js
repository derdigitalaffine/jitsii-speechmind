// Symbolauswahl mit Suche: Liste aus #icon-list ([Symbol, Stichwörter]), Auswahl landet im versteckten Feld.
(function () {
  'use strict';
  var data = document.getElementById('icon-list');
  if (!data) return;
  var ICONS = JSON.parse(data.textContent);
  function norm(t) { return (t || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/ß/g, 'ss'); }

  document.querySelectorAll('.js-icon-picker').forEach(function (box) {
    var value = box.querySelector('.js-icon-value'), toggle = box.querySelector('.js-icon-toggle');
    var panel = box.querySelector('.icon-picker-panel'), search = box.querySelector('.js-icon-search');
    var grid = box.querySelector('.js-icon-grid'), label = box.querySelector('.js-icon-label');
    var current = box.querySelector('.icon-picker-current i');

    function render() {
      var q = norm(search.value.trim());
      var rows = ICONS.filter(function (r) { return !q || norm(r[1]).indexOf(q) >= 0 || r[0].indexOf(q) >= 0; });
      grid.innerHTML = rows.map(function (r) {
        var sel = r[0] === value.value;
        return '<button type="button" class="btn btn-sm ' + (sel ? 'btn-primary' : 'btn-light') + '" role="option" aria-selected="' + sel +
          '" data-icon="' + r[0] + '" title="' + r[1].split(' ').slice(0, 4).join(', ') + '"><i class="fa-solid ' + r[0] + '" aria-hidden="true"></i><span class="visually-hidden">' + r[1].split(' ')[0] + '</span></button>';
      }).join('') || '<div class="small text-secondary p-2">Kein Symbol gefunden.</div>';
    }
    function open(on) {
      panel.classList.toggle('d-none', !on);
      toggle.setAttribute('aria-expanded', on ? 'true' : 'false');
      if (on) { render(); search.focus(); }
    }
    function pick(icon) {
      value.value = icon;
      current.className = 'fa-solid ' + (icon || box.dataset.auto || 'fa-file-signature');
      label.textContent = icon ? icon.replace('fa-', '') : 'automatisch';
      value.dispatchEvent(new Event('change', { bubbles: true }));
      open(false);
      toggle.focus();
    }
    toggle.addEventListener('click', function () { open(panel.classList.contains('d-none')); });
    search.addEventListener('input', render);
    search.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); var f = grid.querySelector('[data-icon]'); if (f) pick(f.dataset.icon); }
      if (e.key === 'Escape') { open(false); toggle.focus(); }
    });
    grid.addEventListener('click', function (e) { var b = e.target.closest('[data-icon]'); if (b) pick(b.dataset.icon); });
    grid.addEventListener('keydown', function (e) { if (e.key === 'Escape') { open(false); toggle.focus(); } });
    box.querySelector('.js-icon-auto').addEventListener('click', function () { pick(''); });
    document.addEventListener('click', function (e) { if (!box.contains(e.target)) open(false); });
  });
})();
