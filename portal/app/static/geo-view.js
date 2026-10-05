/* Kleine Karten, die Antworten von Kartenfragen zeigen (Punkte, Linien, Flächen): Auswertung und Vorgang. */
(function () {
  'use strict';
  var el = document.getElementById('geo-bundle');
  if (!el || !window.MapKit) { return; }
  var bundle = JSON.parse(el.textContent);
  document.querySelectorAll('.js-geo-view').forEach(function (box) {
    var feats = JSON.parse(box.dataset.features || '[]').filter(Boolean);
    if (!feats.length) { return; }
    var kit = MapKit.create(box, JSON.parse(JSON.stringify(bundle)), {});
    var map = kit.map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    var data = { type: 'FeatureCollection', features: feats };
    var bounds = new maplibregl.LngLatBounds();
    feats.forEach(function (f) {
      var g = f.geometry, c = g.type === 'Point' ? [g.coordinates] : g.type === 'LineString' ? g.coordinates : g.coordinates[0];
      c.forEach(function (p) { bounds.extend(p); });
    });
    function add() {
      if (map.getSource('answers')) { return; }
      map.addSource('answers', { type: 'geojson', data: data });
      map.addLayer({ id: 'ans-fill', type: 'fill', source: 'answers', filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'fill-color': '#d62828', 'fill-opacity': 0.2 } });
      map.addLayer({ id: 'ans-line', type: 'line', source: 'answers', filter: ['!=', ['geometry-type'], 'Point'], paint: { 'line-color': '#d62828', 'line-width': 3 } });
      map.addLayer({ id: 'ans-pt', type: 'circle', source: 'answers', filter: ['==', ['geometry-type'], 'Point'], paint: { 'circle-radius': 6.5, 'circle-color': '#d62828', 'circle-stroke-color': '#fff', 'circle-stroke-width': 2 } });
    }
    map.on('style.load', add);
    map.on('load', function () { add(); map.fitBounds(bounds, { padding: 40, maxZoom: 17, duration: 0 }); });
    map.on('click', function (ev) {
      var hit = map.queryRenderedFeatures(ev.point, { layers: ['ans-pt', 'ans-line', 'ans-fill'] });
      if (!hit.length) { return; }
      var f = hit[0], text = (f.properties.label || 'Antwort');
      var m = window.MapDraw ? MapDraw.describe({ geometry: feats.filter(function (x) { return x.properties.label === f.properties.label; })[0].geometry }) : '';
      new maplibregl.Popup({ offset: 10 }).setLngLat(ev.lngLat).setText(text + (m ? ': ' + m : '')).addTo(map);
    });
    ['ans-pt', 'ans-line', 'ans-fill'].forEach(function (id) {
      map.on('mouseenter', id, function () { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', id, function () { map.getCanvas().style.cursor = ''; });
    });
  });
})();
