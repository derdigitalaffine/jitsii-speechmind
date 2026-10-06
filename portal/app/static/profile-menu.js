// Menü anpassen: Reihenfolge der Favoriten per Ziehen oder Pfeilknöpfen.
(function () {
  'use strict';
  var list = document.getElementById('pm-favs');
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
})();
