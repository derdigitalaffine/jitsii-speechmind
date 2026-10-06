/* Kartenkern auf Basis von MapLibre GL: Grundkarten, Überlagerungen (Kacheln, WMS/WMS-T, WFS, GeoJSON),
   Transparenz, Reihenfolge, Zeit, Sachinformation, Koordinaten (WGS84/UTM32), Messen.
   Verwendet von Kartenbrowser, Layerverwaltung und GPS-Fragen in Formularen. */
(function () {
  'use strict';

  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  var abs = function (u) { return u && u.charAt(0) === '/' ? location.origin + u : u; };

  /* --- Koordinaten ------------------------------------------------------------------ */
  function toMerc(lon, lat) {
    var x = lon * 20037508.34 / 180;
    var y = Math.log(Math.tan((90 + lat) * Math.PI / 360)) * 6378137;
    return [x, y];
  }
  /* WGS84 → UTM Zone 32N (ETRS89, EPSG:25832) – übliche Behördenkoordinaten in Deutschland */
  function toUtm32(lon, lat) {
    var a = 6378137, f = 1 / 298.257222101, k0 = 0.9996, lon0 = 9 * Math.PI / 180;
    var e2 = f * (2 - f), ep2 = e2 / (1 - e2);
    var phi = lat * Math.PI / 180, lam = lon * Math.PI / 180;
    var N = a / Math.sqrt(1 - e2 * Math.sin(phi) * Math.sin(phi));
    var T = Math.tan(phi) * Math.tan(phi), C = ep2 * Math.cos(phi) * Math.cos(phi), A = (lam - lon0) * Math.cos(phi);
    var M = a * ((1 - e2 / 4 - 3 * e2 * e2 / 64 - 5 * e2 * e2 * e2 / 256) * phi - (3 * e2 / 8 + 3 * e2 * e2 / 32 + 45 * e2 * e2 * e2 / 1024) * Math.sin(2 * phi)
      + (15 * e2 * e2 / 256 + 45 * e2 * e2 * e2 / 1024) * Math.sin(4 * phi) - (35 * e2 * e2 * e2 / 3072) * Math.sin(6 * phi));
    var x = k0 * N * (A + (1 - T + C) * Math.pow(A, 3) / 6 + (5 - 18 * T + T * T + 72 * C - 58 * ep2) * Math.pow(A, 5) / 120) + 500000;
    var y = k0 * (M + N * Math.tan(phi) * (A * A / 2 + (5 - T + 9 * C + 4 * C * C) * Math.pow(A, 4) / 24 + (61 - 58 * T + T * T + 600 * C - 330 * ep2) * Math.pow(A, 6) / 720));
    return [x, y];
  }
  function fmtLatLon(lngLat) { return lngLat.lat.toFixed(6) + ', ' + lngLat.lng.toFixed(6); }
  function haversine(a, b) {
    var R = 6371008.8, p1 = a[1] * Math.PI / 180, p2 = b[1] * Math.PI / 180;
    var dp = p2 - p1, dl = (b[0] - a[0]) * Math.PI / 180;
    var h = Math.sin(dp / 2) * Math.sin(dp / 2) + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) * Math.sin(dl / 2);
    return 2 * R * Math.asin(Math.sqrt(h));
  }
  function ringArea(coords) {
    var R = 6371008.8, area = 0;
    for (var i = 0; i < coords.length; i++) {
      var p1 = coords[i], p2 = coords[(i + 1) % coords.length];
      area += (p2[0] - p1[0]) * Math.PI / 180 * (2 + Math.sin(p1[1] * Math.PI / 180) + Math.sin(p2[1] * Math.PI / 180));
    }
    return Math.abs(area * R * R / 2);
  }
  function fmtLen(m) { return m >= 1000 ? (m / 1000).toFixed(2).replace('.', ',') + ' km' : Math.round(m) + ' m'; }
  function fmtArea(m2) { return m2 >= 1e6 ? (m2 / 1e6).toFixed(3).replace('.', ',') + ' km²' : m2 >= 1e4 ? (m2 / 1e4).toFixed(2).replace('.', ',') + ' ha' : Math.round(m2) + ' m²'; }

  /* --- Karte ------------------------------------------------------------------------- */
  function create(container, bundle, opts) {
    opts = opts || {};
    var layers = (bundle.layers || []).map(function (l) {
      return Object.assign({}, l, { visible: !!l.visible, opacity: l.opacity == null ? 1 : l.opacity, time: l.time || (l.times && l.times.length ? l.times[l.times.length - 1] : '') });
    });
    var state = bundle.state || {};
    var view = bundle.view || { center: [10, 51], zoom: 5 };
    // gespeicherten Zustand anwenden
    (state.layers || []).forEach(function (s) {
      var l = layers.find(function (x) { return x.id === s.id; });
      if (l) { l.visible = s.visible; l.opacity = s.opacity; if (s.time) { l.time = s.time; } }
    });
    var bases = layers.filter(function (l) { return l.role === 'base'; });
    var overlays = layers.filter(function (l) { return l.role !== 'base'; });
    // Reihenfolge aus dem gespeicherten Zustand
    if (state.layers && state.layers.length) {
      var order = state.layers.map(function (s) { return s.id; });
      overlays.sort(function (a, b) { var ia = order.indexOf(a.id), ib = order.indexOf(b.id); return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib); });
    }
    var baseId = (state.base && bases.some(function (b) { return b.id === state.base; })) ? state.base
      : opts.base || ((bases.find(function (b) { return b.visible; }) || bases[0] || {}).id);
    var listeners = [];
    var emit = function () { listeners.forEach(function (fn) { fn(); }); };

    function blankStyle() {
      return { version: 8, sources: {}, layers: [{ id: 'jsm-bg', type: 'background', paint: { 'background-color': '#eef0f2' } }] };
    }
    var baseCfg = function () { return bases.find(function (b) { return b.id === baseId; }); };
    var startStyle = baseCfg() && baseCfg().kind === 'style' ? baseCfg().style : blankStyle();

    var map = new maplibregl.Map({
      container: container, style: startStyle,
      center: state.center || view.center, zoom: state.zoom != null ? state.zoom : view.zoom,
      bearing: state.bearing || 0, pitch: state.pitch || 0,
      hash: opts.hash || false, attributionControl: { compact: true },
      canvasContextAttributes: { preserveDrawingBuffer: !!opts.exportable },
      maxZoom: 22, renderWorldCopies: false, locale: {
        'NavigationControl.ZoomIn': 'Vergrößern', 'NavigationControl.ZoomOut': 'Verkleinern',
        'NavigationControl.ResetBearing': 'Nach Norden ausrichten', 'GeolocateControl.FindMyLocation': 'Meinen Standort zeigen',
        'GeolocateControl.LocationNotAvailable': 'Standort nicht verfügbar', 'FullscreenControl.Enter': 'Vollbild',
        'FullscreenControl.Exit': 'Vollbild beenden', 'ScaleControl.Meters': 'm', 'ScaleControl.Kilometers': 'km',
        'Popup.Close': 'Schließen', 'AttributionControl.ToggleAttribution': 'Quellenangaben'
      }
    });

    function tileUrl(l) {
      var u = abs(l.tiles);
      if (l.kind === 'wms' && l.time) { u += (u.indexOf('?') < 0 ? '?' : '&') + (u.indexOf('/map/') >= 0 ? 'time=' : 'TIME=') + encodeURIComponent(l.time); }
      return u;
    }
    function addRaster(l, isBase) {
      var sid = 'src-' + l.id;
      if (!map.getSource(sid)) {
        map.addSource(sid, { type: 'raster', tiles: [tileUrl(l)], tileSize: l.tileSize || 256, attribution: l.attribution || '',
          minzoom: l.minzoom || 0, maxzoom: Math.min(l.maxzoom || 22, 22) });
      }
      map.addLayer({ id: 'lyr-' + l.id, type: 'raster', source: sid,
        layout: { visibility: (isBase ? l.id === baseId : l.visible) ? 'visible' : 'none' },
        paint: { 'raster-opacity': isBase ? 1 : l.opacity, 'raster-fade-duration': 150 } });
    }
    function addVector(l) {
      var sid = 'src-' + l.id;
      if (!map.getSource(sid)) {
        map.addSource(sid, { type: 'geojson', data: { type: 'FeatureCollection', features: [] }, attribution: l.attribution || '' });
      }
      var vis = l.visible ? 'visible' : 'none', c = l.color || '#e4572e';
      map.addLayer({ id: 'lyr-' + l.id + '-fill', type: 'fill', source: sid, filter: ['==', ['geometry-type'], 'Polygon'],
        layout: { visibility: vis }, paint: { 'fill-color': c, 'fill-opacity': 0.25 * l.opacity } });
      map.addLayer({ id: 'lyr-' + l.id + '-line', type: 'line', source: sid, filter: ['in', ['geometry-type'], ['literal', ['LineString', 'Polygon']]],
        layout: { visibility: vis }, paint: { 'line-color': c, 'line-width': 2, 'line-opacity': l.opacity } });
      map.addLayer({ id: 'lyr-' + l.id + '-point', type: 'circle', source: sid, filter: ['==', ['geometry-type'], 'Point'],
        layout: { visibility: vis }, paint: { 'circle-color': c, 'circle-radius': 5, 'circle-stroke-color': '#fff', 'circle-stroke-width': 1.5, 'circle-opacity': l.opacity } });
      l._loaded = '';
      if (l.visible) { loadVector(l); }
    }
    var vectorIds = function (l) { return ['lyr-' + l.id + '-fill', 'lyr-' + l.id + '-line', 'lyr-' + l.id + '-point']; };
    function layerIds(l) { return (l.kind === 'wfs' || l.kind === 'geojson') ? vectorIds(l) : ['lyr-' + l.id]; }

    function loadVector(l) {
      var src = map.getSource('src-' + l.id);
      if (!src) { return; }
      var url;
      if (l.kind === 'geojson') {
        if (l._loaded) { return; }
        url = abs(l.data);
      } else {
        var b = map.getBounds(), sw = toMerc(b.getWest(), b.getSouth()), ne = toMerc(b.getEast(), b.getNorth());
        var bbox = [sw[0], sw[1], ne[0], ne[1]].map(function (n) { return n.toFixed(1); }).join(',');
        if (l._loaded === bbox) { return; }
        l._loaded = bbox;
        url = l.data ? abs(l.data) + '?bbox=' + bbox : l.wfsDirect + '&BBOX=' + bbox + ',EPSG:3857';
      }
      // Beim Zoomen/Verschieben nur die letzte Anfrage zählt – ältere abbrechen
      if (l._abort) { l._abort.abort(); }
      l._abort = window.AbortController ? new AbortController() : null;
      fetch(url, { credentials: 'same-origin', signal: l._abort ? l._abort.signal : undefined }).then(function (r) { return r.ok ? r.json() : null; }).then(function (data) {
        if (data && map.getSource('src-' + l.id)) { map.getSource('src-' + l.id).setData(data); l._loaded = l._loaded || 'x'; }
      }).catch(function () { /* abgebrochen oder Dienst nicht erreichbar */ });
    }
    var vectorTimer = null;
    function loadVectorsSoon() {
      clearTimeout(vectorTimer);
      vectorTimer = setTimeout(function () {
        overlays.forEach(function (l) { if (l.visible && l.kind === 'wfs') { loadVector(l); } });
      }, 350);
    }

    function build() {
      var b = baseCfg();
      bases.forEach(function (l) { if (l.kind !== 'style') { addRaster(l, true); } });
      overlays.forEach(function (l) {
        if (l.kind === 'wfs' || l.kind === 'geojson') { addVector(l); } else if (l.tiles) { addRaster(l, false); }
      });
      if (b && b.kind === 'style') { /* Vektorgrundkarte liegt bereits im Stil */ }
      emit();
    }
    map.on('style.load', build);
    map.on('moveend', loadVectorsSoon);

    function setVis(l, on) {
      layerIds(l).forEach(function (id) { if (map.getLayer(id)) { map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none'); } });
    }
    var api = {
      map: map, bases: bases, overlays: overlays,
      get baseId() { return baseId; },
      on: function (fn) { listeners.push(fn); },
      setBase: function (id) {
        var prev = baseCfg(), next = bases.find(function (b) { return b.id === id; });
        if (!next) { return; }
        baseId = id;
        if ((prev && prev.kind === 'style') || next.kind === 'style') {
          map.setStyle(next.kind === 'style' ? next.style : blankStyle());   // style.load baut alles neu auf
        } else {
          bases.forEach(function (b) { setVis(b, b.id === id); });
        }
        emit();
      },
      setVisible: function (id, on) {
        var l = overlays.find(function (x) { return x.id === id; });
        if (!l) { return; }
        l.visible = on;
        setVis(l, on);
        if (on && (l.kind === 'wfs' || l.kind === 'geojson')) { loadVector(l); }
        emit();
      },
      setOpacity: function (id, value) {
        var l = overlays.find(function (x) { return x.id === id; });
        if (!l) { return; }
        l.opacity = value;
        if (map.getLayer('lyr-' + id)) { map.setPaintProperty('lyr-' + id, 'raster-opacity', value); }
        if (map.getLayer('lyr-' + id + '-fill')) {
          map.setPaintProperty('lyr-' + id + '-fill', 'fill-opacity', 0.25 * value);
          map.setPaintProperty('lyr-' + id + '-line', 'line-opacity', value);
          map.setPaintProperty('lyr-' + id + '-point', 'circle-opacity', value);
        }
        emit();
      },
      setTime: function (id, t) {
        var l = overlays.find(function (x) { return x.id === id; });
        if (!l) { return; }
        l.time = t;
        var src = map.getSource('src-' + id);
        if (src && src.setTiles) { src.setTiles([tileUrl(l)]); }
        emit();
      },
      reorder: function (ids) {
        overlays.sort(function (a, b) { return ids.indexOf(a.id) - ids.indexOf(b.id); });
        // ids: oben zuerst → von unten nach oben an die Spitze schieben
        overlays.slice().reverse().forEach(function (l) {
          layerIds(l).forEach(function (lid) { if (map.getLayer(lid)) { map.moveLayer(lid); } });
        });
        emit();
      },
      addOverlay: function (cfg) {
        var l = Object.assign({ visible: true, opacity: 1, time: '' }, cfg);
        if (!l.time && l.times && l.times.length) { l.time = l.times[l.times.length - 1]; }
        overlays.unshift(l);
        if (l.kind === 'wfs' || l.kind === 'geojson') { addVector(l); } else { addRaster(l, false); }
        emit();
        return l;
      },
      removeOverlay: function (id) {
        var i = overlays.findIndex(function (x) { return x.id === id; });
        if (i < 0) { return; }
        var l = overlays[i];
        layerIds(l).forEach(function (lid) { if (map.getLayer(lid)) { map.removeLayer(lid); } });
        if (map.getSource('src-' + id)) { map.removeSource('src-' + id); }
        overlays.splice(i, 1);
        emit();
      },
      state: function () {
        var c = map.getCenter();
        return {
          center: [c.lng, c.lat], zoom: map.getZoom(), bearing: map.getBearing(), pitch: map.getPitch(), base: baseId,
          layers: overlays.filter(function (l) { return !l.custom; }).map(function (l) { return { id: l.id, visible: l.visible, opacity: l.opacity, time: l.time || '' }; }),
          custom: overlays.filter(function (l) { return l.custom; }).map(function (l) { return { def: Object.assign({}, l.custom, { time: l.time || '' }), opacity: l.opacity }; })
        };
      },
      vectorLayerIds: function () {
        var ids = [];
        overlays.forEach(function (l) { if (l.visible && (l.kind === 'wfs' || l.kind === 'geojson')) { ids = ids.concat(vectorIds(l)); } });
        return ids.filter(function (id) { return map.getLayer(id); });
      },
      /* Sachinformation (WMS GetFeatureInfo über den Proxy) für einen Klickpunkt */
      featureInfo: function (point) {
        var canvas = map.getCanvas(), b = map.getBounds();
        var sw = toMerc(b.getWest(), b.getSouth()), ne = toMerc(b.getEast(), b.getNorth());
        var w = canvas.clientWidth, h = canvas.clientHeight;
        var jobs = overlays.filter(function (l) { return l.visible && l.info; }).map(function (l) {
          var q = '?bbox=' + [sw[0], sw[1], ne[0], ne[1]].join(',') + '&i=' + Math.round(point.x * 256 / w) + '&j=' + Math.round(point.y * 256 / h) + (l.time ? '&time=' + encodeURIComponent(l.time) : '');
          // Für die Abfrage wird der sichtbare Ausschnitt auf 256 × 256 Bildpunkte abgebildet
          return fetch(abs(l.info) + q, { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) { return d && d.html && d.html.replace(/<[^>]*>/g, '').trim() ? { layer: l, html: d.html } : null; })
            .catch(function () { return null; });
        });
        return Promise.all(jobs).then(function (rows) { return rows.filter(Boolean); });
      }
    };
    return api;
  }

  window.MapKit = { create: create, esc: esc, toUtm32: toUtm32, toMerc: toMerc, fmtLatLon: fmtLatLon, haversine: haversine,
    ringArea: ringArea, fmtLen: fmtLen, fmtArea: fmtArea };
})();
