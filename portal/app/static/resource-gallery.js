// Fotogalerie der Ressourcenseite: Klick auf ein Foto öffnet die Vollbildansicht beim gewählten Bild.
(function () {
  'use strict';
  var modal = document.getElementById('res-lightbox');
  if (!modal || !window.bootstrap) return;
  var carousel = bootstrap.Carousel.getOrCreateInstance(document.getElementById('res-lightbox-carousel'), { ride: false, interval: false });
  document.querySelectorAll('.res-gallery-item').forEach(function (btn) {
    btn.addEventListener('click', function () { carousel.to(+btn.dataset.index || 0); });
  });
  modal.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowLeft') carousel.prev();
    if (e.key === 'ArrowRight') carousel.next();
  });
})();
