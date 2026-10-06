// Karten der Ressourcen: Punkte in der Farbe ihrer Art. Im Katalog öffnet ein Klick ein Info-Fenster mit Foto,
// Anbieter, Eckdaten und „Ansehen & buchen“; auf der Ressourcenseite zeigt die Karte nur die Lage.
(function () {
  'use strict';
  var el = document.getElementById('geo-bundle');
  if (!el || !window.MapKit) return;
  var bundle = JSON.parse(el.textContent);
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };

  function info(p) {
    var modal = document.getElementById('res-map-modal');
    if (!modal || !window.bootstrap) { if (p.url) location.href = p.url; return; }
    var body = modal.querySelector('.js-body');
    var photo = p.photo ? '<img class="res-map-photo" src="' + esc(p.photo) + '" alt="">' :
      '<div class="res-map-photo res-map-photo-empty" style="--cat:' + esc(p.color) + '"><i class="fa-solid fa-building"></i></div>';
    var facts = [];
    if (p.capacity) facts.push('<span><i class="fa-solid fa-users me-1"></i>bis ' + esc(p.capacity) + ' Personen</span>');
    if (p.rooms) facts.push('<span><i class="fa-solid fa-door-open me-1"></i>' + esc(p.rooms) + ' Räume</span>');
    facts.push('<span><i class="fa-solid fa-euro-sign me-1"></i>' + esc(p.price || 'kostenlos') + '</span>');
    if (p.free) facts.push('<span class="badge ' + (p.free === 'frei' ? 'text-bg-success' : p.free.indexOf('teilweise') >= 0 ? 'text-bg-warning' : 'text-bg-danger') + '">' + esc(p.free) + '</span>');
    body.innerHTML = photo +
      '<div class="p-3"><div class="d-flex align-items-center gap-2 mb-1"><span class="res-dot" style="background:' + esc(p.color) + '"></span><span class="small text-secondary">' + esc(p.category || '') + '</span></div>' +
      '<h2 class="h5 mb-1" id="res-map-title">' + esc(p.name) + '</h2>' +
      (p.location ? '<div class="small text-secondary mb-2"><i class="fa-solid fa-location-dot me-1"></i>' + esc(p.location) + '</div>' : '') +
      (p.provider ? '<div class="small mb-2 d-flex align-items-center gap-1">' + (p.logo ? '<img class="org-logo org-logo-sm" src="' + esc(p.logo) + '" alt="">' : '<i class="fa-solid fa-landmark-flag text-secondary"></i>') + '<span>' + esc(p.provider) + '</span></div>' : '') +
      '<div class="small d-flex flex-wrap gap-3 mb-3">' + facts.join('') + '</div>' +
      (p.teaser ? '<p class="small mb-3">' + esc(p.teaser) + '</p>' : '') +
      '<a class="btn btn-primary w-100" href="' + esc(p.url) + '">Ansehen &amp; buchen <i class="fa-solid fa-arrow-right ms-1"></i></a></div>';
    bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  document.querySelectorAll('.js-res-map').forEach(function (box) {
    var feats = JSON.parse(box.dataset.features || '[]').filter(Boolean);
    if (!feats.length) return;
    var single = box.dataset.single === '1';
    var kit = MapKit.create(box, JSON.parse(JSON.stringify(bundle)), {});
    var map = kit.map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    if (!single) map.addControl(new maplibregl.FullscreenControl(), 'top-right');
    var bounds = new maplibregl.LngLatBounds();
    feats.forEach(function (f) { bounds.extend(f.geometry.coordinates); });
    function add() {
      if (map.getSource('res')) return;
      map.addSource('res', { type: 'geojson', data: { type: 'FeatureCollection', features: feats } });
      map.addLayer({ id: 'res-halo', type: 'circle', source: 'res', paint: { 'circle-radius': 13, 'circle-color': ['get', 'color'], 'circle-opacity': 0.18 } });
      map.addLayer({ id: 'res-pt', type: 'circle', source: 'res', paint: { 'circle-radius': 8, 'circle-color': ['get', 'color'], 'circle-stroke-color': '#fff', 'circle-stroke-width': 2.5 } });
    }
    map.on('style.load', add);
    map.on('load', function () {
      add();
      if (feats.length === 1) map.jumpTo({ center: feats[0].geometry.coordinates, zoom: single ? 15 : 14 });
      else map.fitBounds(bounds, { padding: 48, maxZoom: 15, duration: 0 });
    });
    if (single) return;
    map.on('click', 'res-pt', function (ev) { if (ev.features.length) info(ev.features[0].properties); });
    map.on('mouseenter', 'res-pt', function () { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'res-pt', function () { map.getCanvas().style.cursor = ''; });
    // Tastatur: Legenden-/Listeneinträge mit data-res-feature öffnen dasselbe Info-Fenster
    document.querySelectorAll('[data-res-feature]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var f = feats.filter(function (x) { return String(x.properties.id) === btn.dataset.resFeature; })[0];
        if (f) info(f.properties);
      });
    });
  });
})();
