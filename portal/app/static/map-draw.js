/* Zeichnen und Messen auf MapLibre-Karten: Punkt, Linie, Fläche. Stützpunkte lassen sich verschieben,
   ein Klick auf eine Zeichnung wählt sie aus. Verwendet vom Kartenbrowser und von Formularfragen.

   var draw = MapDraw.create(map, { single: false, color: '#d62828', onChange: fn(features), onSketch: fn(info) });
   draw.start('line'|'polygon'|'point'), draw.finish(), draw.cancel(), draw.undo(), draw.features(),
   draw.setFeatures(list), draw.remove(id), draw.select(id), draw.update(id, props), draw.measure(feature) */
(function () {
  'use strict';
  var uid = function () { return Math.random().toString(16).slice(2, 10); };
  var COLORS = ['#d62828', '#1f5fa8', '#2a9d8f', '#e76f51', '#7b2cbf', '#f4a261', '#264653'];

  function measure(f) {
    var g = f.geometry, out = { length: 0, area: 0, points: 0 };
    if (!g) { return out; }
    var c = g.type === 'Polygon' ? g.coordinates[0].slice(0, -1) : g.type === 'LineString' ? g.coordinates : [g.coordinates];
    out.points = c.length;
    for (var i = 1; i < c.length; i++) { out.length += MapKit.haversine(c[i - 1], c[i]); }
    if (g.type === 'Polygon' && c.length > 2) {
      out.length += MapKit.haversine(c[c.length - 1], c[0]);
      out.area = MapKit.ringArea(c);
    }
    return out;
  }
  function describe(f) {
    var m = measure(f), g = f.geometry;
    if (!g) { return ''; }
    if (g.type === 'Point') { return g.coordinates[1].toFixed(6) + ', ' + g.coordinates[0].toFixed(6); }
    if (g.type === 'LineString') { return 'Länge ' + MapKit.fmtLen(m.length) + ' · ' + m.points + ' Punkte'; }
    return 'Fläche ' + MapKit.fmtArea(m.area) + ' · Umfang ' + MapKit.fmtLen(m.length);
  }
  function verticesOf(g) {
    return g.type === 'Polygon' ? g.coordinates[0].slice(0, -1) : g.type === 'LineString' ? g.coordinates : [g.coordinates];
  }
  function geometry(mode, pts) {
    if (mode === 'point') { return { type: 'Point', coordinates: pts[0] }; }
    if (mode === 'line') { return { type: 'LineString', coordinates: pts.slice() }; }
    return { type: 'Polygon', coordinates: [pts.concat([pts[0]])] };
  }
  var MIN = { point: 1, line: 2, polygon: 3 };

  function create(map, opts) {
    opts = opts || {};
    var feats = [], mode = null, pts = [], hover = null, selected = null, drag = null, lastClick = 0, lastPt = null;
    var src = 'draw-' + uid();
    var L = { fill: src + '-fill', line: src + '-line', pt: src + '-pt', vx: src + '-vx', sk: src + '-sk', skpt: src + '-skpt' };

    function fc(list) { return { type: 'FeatureCollection', features: list }; }
    function data() {
      return fc(feats.map(function (f) {
        return { type: 'Feature', id: f.id, geometry: f.geometry, properties: { id: f.id, color: f.properties.color || COLORS[0], sel: f.id === selected ? 1 : 0 } };
      }));
    }
    function sketchData() {
      var list = [], all = hover ? pts.concat([hover]) : pts;
      if (mode && all.length > 1) {
        list.push({ type: 'Feature', geometry: mode === 'polygon' && all.length > 2 ? geometry('polygon', all) : { type: 'LineString', coordinates: all }, properties: {} });
      }
      pts.forEach(function (p, i) { list.push({ type: 'Feature', geometry: { type: 'Point', coordinates: p }, properties: { first: i === 0 ? 1 : 0 } }); });
      var f = selected && byId(selected);
      if (f && !mode) {
        verticesOf(f.geometry).forEach(function (p, i) { list.push({ type: 'Feature', geometry: { type: 'Point', coordinates: p }, properties: { vx: i, color: f.properties.color } }); });
      }
      return fc(list);
    }
    function byId(id) { return feats.filter(function (f) { return f.id === id; })[0]; }
    function ensure() {
      if (!map.getSource(src)) {
        map.addSource(src, { type: 'geojson', data: data() });
        map.addSource(src + '-s', { type: 'geojson', data: sketchData() });
        var color = ['get', 'color'];
        map.addLayer({ id: L.fill, type: 'fill', source: src, filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'fill-color': color, 'fill-opacity': ['case', ['==', ['get', 'sel'], 1], 0.3, 0.18] } });
        map.addLayer({ id: L.line, type: 'line', source: src, filter: ['!=', ['geometry-type'], 'Point'], layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': color, 'line-width': ['case', ['==', ['get', 'sel'], 1], 4, 3] } });
        map.addLayer({ id: L.pt, type: 'circle', source: src, filter: ['==', ['geometry-type'], 'Point'],
          paint: { 'circle-radius': ['case', ['==', ['get', 'sel'], 1], 8, 6.5], 'circle-color': color, 'circle-stroke-color': '#fff', 'circle-stroke-width': 2 } });
        map.addLayer({ id: L.sk, type: 'line', source: src + '-s', filter: ['!=', ['geometry-type'], 'Point'], paint: { 'line-color': opts.color || '#1f5fa8', 'line-width': 2.5, 'line-dasharray': [2, 1] } });
        map.addLayer({ id: L.skpt, type: 'circle', source: src + '-s', filter: ['all', ['==', ['geometry-type'], 'Point'], ['!', ['has', 'vx']]],
          paint: { 'circle-radius': ['case', ['==', ['get', 'first'], 1], 7, 5], 'circle-color': '#fff', 'circle-stroke-color': opts.color || '#1f5fa8', 'circle-stroke-width': 2.5 } });
        map.addLayer({ id: L.vx, type: 'circle', source: src + '-s', filter: ['has', 'vx'],
          paint: { 'circle-radius': 6, 'circle-color': '#fff', 'circle-stroke-color': ['get', 'color'], 'circle-stroke-width': 3 } });
      }
    }
    function refresh() {
      if (!map.isStyleLoaded() && !map.getSource(src)) { return; }
      ensure();
      map.getSource(src).setData(data());
      map.getSource(src + '-s').setData(sketchData());
    }
    function changed() { refresh(); if (opts.onChange) { opts.onChange(api.features()); } }
    function sketch() {
      refresh();
      if (!opts.onSketch) { return; }
      if (!mode) { opts.onSketch(null); return; }
      var all = hover ? pts.concat([hover]) : pts;
      var info = { mode: mode, count: pts.length, min: MIN[mode], text: '' };
      if (all.length >= 2 && mode !== 'point') { info.text = describe({ geometry: mode === 'polygon' && all.length > 2 ? geometry('polygon', all) : { type: 'LineString', coordinates: all } }); }
      opts.onSketch(info);
    }

    if (map.isStyleLoaded()) { ensure(); }
    map.on('load', refresh);
    map.on('style.load', function () { refresh(); });   // nach Wechsel der Grundkarte neu anlegen

    function finish() {
      if (!mode) { return null; }
      var m = mode, done = null;
      if (pts.length >= MIN[m]) {
        if (opts.single) { feats = []; }
        done = { id: uid(), type: 'Feature', geometry: geometry(m, pts), properties: { name: '', color: opts.color || COLORS[feats.length % COLORS.length], kind: m } };
        feats.push(done);
        selected = done.id;
      }
      mode = null; pts = []; hover = null;
      map.getCanvas().style.cursor = '';
      map.doubleClickZoom.enable();
      changed(); sketch();
      if (opts.onFinish) { opts.onFinish(done); }
      return done;
    }

    map.on('click', function (ev) {
      if (drag && drag.moved) { return; }
      if (mode) {
        var now = Date.now(), p = [ev.lngLat.lng, ev.lngLat.lat];
        var near = lastPt && Math.hypot(lastPt.x - ev.point.x, lastPt.y - ev.point.y) < 8;
        if (now - lastClick < 400 && near && pts.length >= MIN[mode]) { lastClick = 0; finish(); return; }   // Doppelklick beendet
        lastClick = now; lastPt = ev.point;
        // Klick auf den ersten Punkt schließt die Fläche
        if (mode === 'polygon' && pts.length >= 3) {
          var first = map.project(pts[0]);
          if (Math.hypot(first.x - ev.point.x, first.y - ev.point.y) < 12) { finish(); return; }
        }
        pts.push(p);
        if (mode === 'point') { finish(); return; }
        sketch();
        return;
      }
      var hit = map.queryRenderedFeatures(ev.point, { layers: [L.pt, L.line, L.fill].filter(function (id) { return map.getLayer(id); }) });
      var id = hit.length ? hit[0].properties.id : null;
      if (id || selected) { api.select(id); }
    });
    map.on('mousemove', function (ev) {
      if (drag) { return; }
      if (mode) { hover = [ev.lngLat.lng, ev.lngLat.lat]; sketch(); return; }
      if (selected && map.getLayer(L.vx)) {
        var over = map.queryRenderedFeatures(ev.point, { layers: [L.vx] }).length;
        map.getCanvas().style.cursor = over ? 'move' : '';
      }
    });
    function startDrag(ev) {
      if (mode || !selected || !map.getLayer(L.vx)) { return; }
      var hit = map.queryRenderedFeatures(ev.point, { layers: [L.vx] });
      if (!hit.length) { return; }
      ev.preventDefault();
      drag = { index: hit[0].properties.vx, moved: false };
      map.dragPan.disable();
    }
    function moveDrag(ev) {
      if (!drag) { return; }
      var f = byId(selected), p = [ev.lngLat.lng, ev.lngLat.lat], g = f.geometry;
      drag.moved = true;
      if (g.type === 'Point') { g.coordinates = p; }
      else if (g.type === 'LineString') { g.coordinates[drag.index] = p; }
      else {
        g.coordinates[0][drag.index] = p;
        if (drag.index === 0) { g.coordinates[0][g.coordinates[0].length - 1] = p; }
      }
      refresh();
    }
    function endDrag() {
      if (!drag) { return; }
      var moved = drag.moved;
      map.dragPan.enable();
      setTimeout(function () { drag = null; }, 0);
      if (moved) { changed(); }
    }
    map.on('mousedown', startDrag);
    map.on('touchstart', function (ev) { if (ev.points && ev.points.length === 1) { startDrag(ev); } });
    map.on('mousemove', moveDrag);
    map.on('touchmove', moveDrag);
    map.on('mouseup', endDrag);
    map.on('touchend', endDrag);
    document.addEventListener('keydown', function (ev) {
      if (!mode || /INPUT|TEXTAREA|SELECT/.test((ev.target || {}).tagName || '')) { return; }
      if (ev.key === 'Escape') { api.cancel(); }
      if (ev.key === 'Enter') { finish(); }
      if (ev.key === 'Backspace') { ev.preventDefault(); api.undo(); }
    });

    var api = {
      start: function (m) {
        api.cancel();
        mode = m; pts = []; hover = null; selected = null;
        map.getCanvas().style.cursor = 'crosshair';
        map.doubleClickZoom.disable();
        sketch(); refresh();
      },
      mode: function () { return mode; },
      finish: finish,
      cancel: function () {
        if (!mode) { return; }
        mode = null; pts = []; hover = null;
        map.getCanvas().style.cursor = '';
        map.doubleClickZoom.enable();
        sketch();
      },
      undo: function () { if (mode && pts.length) { pts.pop(); sketch(); } },
      addPoint: function (lngLat) {   // z. B. aktueller GPS-Standort als nächster Stützpunkt
        if (!mode) { return; }
        pts.push(lngLat);
        if (mode === 'point') { finish(); } else { sketch(); }
      },
      features: function () { return feats.map(function (f) { return JSON.parse(JSON.stringify(f)); }); },
      setFeatures: function (list) {
        feats = (list || []).filter(function (f) { return f && f.geometry; }).map(function (f) {
          var c = JSON.parse(JSON.stringify(f));
          c.id = c.id || (c.properties && c.properties.id) || uid();
          c.type = 'Feature';
          c.properties = c.properties || {};
          return c;
        });
        selected = null;
        changed();
      },
      remove: function (id) { feats = feats.filter(function (f) { return f.id !== id; }); if (selected === id) { selected = null; } changed(); sketch(); },
      clear: function () { feats = []; selected = null; changed(); sketch(); },
      update: function (id, props) { var f = byId(id); if (f) { Object.assign(f.properties, props); changed(); } },
      select: function (id) {
        selected = id && byId(id) ? id : null;
        refresh();
        if (opts.onSelect) { opts.onSelect(selected); }
      },
      selected: function () { return selected; },
      zoomTo: function (id) {
        var f = byId(id);
        if (!f) { return; }
        var c = verticesOf(f.geometry);
        if (c.length === 1) { map.flyTo({ center: c[0], zoom: Math.max(map.getZoom(), 16) }); return; }
        var b = new maplibregl.LngLatBounds(c[0], c[0]);
        c.forEach(function (p) { b.extend(p); });
        map.fitBounds(b, { padding: 60, maxZoom: 18 });
      },
      layerIds: function () { return [L.fill, L.line, L.pt]; }
    };
    return api;
  }

  window.MapDraw = { create: create, measure: measure, describe: describe, COLORS: COLORS };
})();
