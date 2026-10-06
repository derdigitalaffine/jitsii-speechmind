// Verwaltung › Öffentliches Menü: Reihenfolge per Ziehen oder Pfeilknöpfen, weitere Linkzeilen einblenden.
(function () {
  'use strict';
  var list = document.getElementById('pn-list');
  if (!list) return;
  if (window.Sortable) Sortable.create(list, { handle: '.drag-handle', animation: 150 });
  list.addEventListener('click', function (e) {
    var btn = e.target.closest('.js-up, .js-down');
    if (!btn) return;
    var li = btn.closest('li');
    if (btn.classList.contains('js-up') && li.previousElementSibling) list.insertBefore(li, li.previousElementSibling);
    else if (btn.classList.contains('js-down') && li.nextElementSibling) list.insertBefore(li.nextElementSibling, li);
    btn.focus();
  });
  var more = document.getElementById('pn-more');
  if (more) more.addEventListener('click', function () {
    var spare = document.querySelector('.js-spare.d-none');
    if (spare) { spare.classList.remove('d-none'); spare.querySelector('input').focus(); }
    if (!document.querySelector('.js-spare.d-none')) more.hidden = true;
  });
})();
