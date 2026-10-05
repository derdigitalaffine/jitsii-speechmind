/* Kartenbrowser: Ebenenliste, Transparenz, Zeit (WMS-T), Legende, Sachinformation, Messen, Export,
   Koordinatensuche, eigene Layer (WMS/WFS/WMTS) und Speichern. */
(function () {
  'use strict';
  var bundle = JSON.parse(document.getElementById('map-bundle').textContent);
  var meta = JSON.parse(document.getElementById('map-meta').textContent);
  var csrf = (document.querySelector('meta[name="csrf"]') || {}).content || '';
  var esc = MapKit.esc;
  var params = new URLSearchParams(location.search);

  // Ebenen und Grundkarte aus dem Link (?base=s1&layers=s3,s4)
  if (params.get('base')) { bundle.state.base = params.get('base'); }
  if (params.get('layers')) {
    var wanted = params.get('layers').split(',');
    bundle.state.layers = bundle.layers.filter(function (l) { return l.role !== 'base'; }).map(function (l) {
      return { id: l.id, visible: wanted.indexOf(l.id) >= 0, opacity: l.opacity };
    });
  }
  var kit = MapKit.create('map', bundle, { hash: true, exportable: true });
  var map = kit.map;
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
  map.addControl(new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: true }, trackUserLocation: false }), 'top-right');
  map.addControl(new maplibregl.FullscreenControl({ container: document.getElementById('map-shell') }), 'top-right');
  map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right');

  /* --- Seitenleiste ------------------------------------------------------------------ */
  var shell = document.getElementById('map-shell');
  document.getElementById('panel-close').addEventListener('click', function () { shell.classList.add('panel-hidden'); setTimeout(function () { map.resize(); }, 50); });
  document.getElementById('panel-open').addEventListener('click', function () { shell.classList.remove('panel-hidden'); setTimeout(function () { map.resize(); }, 50); });
  if (window.innerWidth < 768) { shell.classList.add('panel-hidden'); }

  function renderBases() {
    var box = document.getElementById('base-list');
    box.innerHTML = kit.bases.map(function (b) {
      return '<label class="base-option"><input class="form-check-input mt-0" type="radio" name="base" value="' + esc(b.id) + '"' + (b.id === kit.baseId ? ' checked' : '') + '>' +
        '<span class="flex-grow-1">' + esc(b.name) + '</span>' + (b.description ? '<i class="fa-regular fa-circle-question text-secondary" title="' + esc(b.description) + '"></i>' : '') + '</label>';
    }).join('') + '<label class="base-option"><input class="form-check-input mt-0" type="radio" name="base" value=""' + (!kit.baseId ? ' checked' : '') + '><span class="text-secondary">ohne Grundkarte</span></label>';
  }
  document.getElementById('base-list').addEventListener('change', function (ev) { if (ev.target.name === 'base') { kit.setBase(ev.target.value); } });

  var filterText = '';
  function renderOverlays() {
    var box = document.getElementById('overlay-list');
    var cats = [], byCat = {};
    kit.overlays.forEach(function (l) {
      if (filterText && (l.name + ' ' + (l.category || '') + ' ' + (l.description || '')).toLowerCase().indexOf(filterText) < 0) { return; }
      var c = l.category || 'Fachdaten';
      if (!byCat[c]) { byCat[c] = []; cats.push(c); }
      byCat[c].push(l);
    });
    document.getElementById('overlay-empty').hidden = kit.overlays.length > 0;
    box.innerHTML = cats.map(function (c) {
      return '<div class="layer-cat">' + esc(c) + '</div><div class="layer-group" data-cat="' + esc(c) + '">' + byCat[c].map(rowHtml).join('') + '</div>';
    }).join('');
    if (window.Sortable) {
      box.querySelectorAll('.layer-group').forEach(function (g) {
        Sortable.create(g, { handle: '.drag', animation: 150, onEnd: function () {
          var ids = Array.prototype.map.call(box.querySelectorAll('.layer-row'), function (r) { return r.dataset.id; });
          kit.reorder(ids);
        } });
      });
    }
  }
  function rowHtml(l) {
    var swatch = (l.kind === 'wfs' || l.kind === 'geojson') ? '<span class="layer-swatch" style="background:' + esc(l.color) + '"></span>' : '';
    var times = l.times && l.times.length ? '<div class="d-flex align-items-center gap-2 mt-1"><i class="fa-regular fa-clock text-secondary small" title="Zeit (WMS-T)"></i>' +
      '<input type="range" class="form-range flex-grow-1" data-time-range min="0" max="' + (l.times.length - 1) + '" value="' + Math.max(0, l.times.indexOf(l.time)) + '" aria-label="Zeitpunkt">' +
      '<span class="small text-nowrap" data-time-label>' + esc(l.time) + '</span></div>' : '';
    return '<div class="layer-row' + (l.visible ? ' is-on' : '') + '" data-id="' + esc(l.id) + '">' +
      '<div class="layer-head"><i class="fa-solid fa-grip-vertical drag small" title="Reihenfolge ändern"></i>' +
      '<input class="form-check-input mt-0" type="checkbox" data-toggle' + (l.visible ? ' checked' : '') + ' aria-label="' + esc(l.name) + ' anzeigen">' + swatch +
      '<span class="layer-name" title="' + esc(l.description || l.name) + '">' + esc(l.name) + '</span>' +
      (l.legend ? '<button class="btn-icon" type="button" data-legend title="Legende"><i class="fa-solid fa-list-ul"></i></button>' : '') +
      (l.custom ? '<button class="btn-icon" type="button" data-remove title="Entfernen"><i class="fa-solid fa-xmark"></i></button>' : '') + '</div>' +
      '<div class="layer-tools"><div class="d-flex align-items-center gap-2"><i class="fa-solid fa-circle-half-stroke text-secondary small" title="Deckkraft"></i>' +
      '<input type="range" class="form-range flex-grow-1" min="0" max="100" value="' + Math.round(l.opacity * 100) + '" data-opacity aria-label="Deckkraft">' +
      '<span class="small text-nowrap" style="width:2.6rem" data-opacity-label>' + Math.round(l.opacity * 100) + ' %</span></div>' + times +
      (l.attribution ? '<div class="small text-secondary mt-1 text-truncate">' + esc(l.attribution.replace(/<[^>]*>/g, '')) + '</div>' : '') + '</div></div>';
  }
  var list = document.getElementById('overlay-list');
  list.addEventListener('change', function (ev) {
    var row = ev.target.closest('.layer-row');
    if (!row) { return; }
    if (ev.target.hasAttribute('data-toggle')) { kit.setVisible(row.dataset.id, ev.target.checked); row.classList.toggle('is-on', ev.target.checked); }
    if (ev.target.hasAttribute('data-time-range')) {
      var l = kit.overlays.find(function (x) { return x.id === row.dataset.id; });
      kit.setTime(l.id, l.times[parseInt(ev.target.value, 10)]);
    }
  });
  list.addEventListener('input', function (ev) {
    var row = ev.target.closest('.layer-row');
    if (!row) { return; }
    if (ev.target.hasAttribute('data-opacity')) {
      kit.setOpacity(row.dataset.id, ev.target.value / 100);
      row.querySelector('[data-opacity-label]').textContent = ev.target.value + ' %';
    }
    if (ev.target.hasAttribute('data-time-range')) {
      var l = kit.overlays.find(function (x) { return x.id === row.dataset.id; });
      row.querySelector('[data-time-label]').textContent = l.times[parseInt(ev.target.value, 10)];
    }
  });
  list.addEventListener('click', function (ev) {
    var row = ev.target.closest('.layer-row');
    if (!row) { return; }
    var l = kit.overlays.find(function (x) { return x.id === row.dataset.id; });
    if (ev.target.closest('[data-legend]')) {
      document.getElementById('legend-title').textContent = 'Legende: ' + l.name;
      document.getElementById('legend-body').innerHTML = '<img src="' + esc(l.legend) + '" alt="Legende ' + esc(l.name) + '" style="max-width:100%">';
      bootstrap.Modal.getOrCreateInstance(document.getElementById('legend-modal')).show();
    }
    if (ev.target.closest('[data-remove]')) { kit.removeOverlay(l.id); renderOverlays(); }
  });
  document.getElementById('layer-filter').addEventListener('input', function (ev) { filterText = ev.target.value.trim().toLowerCase(); renderOverlays(); });
  renderBases();
  renderOverlays();

  /* --- Koordinaten anzeigen und suchen ---------------------------------------------- */
  var coords = document.getElementById('map-coords');
  map.on('mousemove', function (ev) {
    var u = MapKit.toUtm32(ev.lngLat.lng, ev.lngLat.lat);
    coords.textContent = MapKit.fmtLatLon(ev.lngLat) + '  ·  UTM 32: ' + Math.round(u[0]) + ' ' + Math.round(u[1]);
  });
  document.getElementById('coord-search').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var t = document.getElementById('coord-input').value.replace(/utm\s*32[nN]?/i, '').trim();
    var nums = t.match(/-?\d+(?:[.,]\d+)?/g);
    if (!nums || nums.length < 2) { return; }
    var a = parseFloat(nums[0].replace(',', '.')), b = parseFloat(nums[1].replace(',', '.'));
    var lngLat;
    if (Math.abs(a) > 1000 || Math.abs(b) > 1000) { lngLat = utmToLngLat(a, b); }
    else if (Math.abs(a) <= 90) { lngLat = (a < 20 && b > 40) ? [a, b] : [b, a]; }   // üblich: Breite, Länge
    else { lngLat = [a, b]; }
    if (!lngLat) { return; }
    map.flyTo({ center: lngLat, zoom: Math.max(map.getZoom(), 15) });
    new maplibregl.Popup({ closeOnClick: true }).setLngLat(lngLat).setHTML('<strong>' + lngLat[1].toFixed(6) + ', ' + lngLat[0].toFixed(6) + '</strong>').addTo(map);
  });
  /* UTM 32N → WGS84 (Näherung ausreichend für die Suche) */
  function utmToLngLat(e, n) {
    var a = 6378137, f = 1 / 298.257222101, k0 = 0.9996, e2 = f * (2 - f), ep2 = e2 / (1 - e2);
    var e1 = (1 - Math.sqrt(1 - e2)) / (1 + Math.sqrt(1 - e2)), x = e - 500000, M = n / k0;
    var mu = M / (a * (1 - e2 / 4 - 3 * e2 * e2 / 64 - 5 * e2 * e2 * e2 / 256));
    var p1 = mu + (3 * e1 / 2 - 27 * Math.pow(e1, 3) / 32) * Math.sin(2 * mu) + (21 * e1 * e1 / 16 - 55 * Math.pow(e1, 4) / 32) * Math.sin(4 * mu) + (151 * Math.pow(e1, 3) / 96) * Math.sin(6 * mu);
    var N1 = a / Math.sqrt(1 - e2 * Math.sin(p1) * Math.sin(p1)), T1 = Math.tan(p1) * Math.tan(p1), C1 = ep2 * Math.cos(p1) * Math.cos(p1);
    var R1 = a * (1 - e2) / Math.pow(1 - e2 * Math.sin(p1) * Math.sin(p1), 1.5), D = x / (N1 * k0);
    var lat = p1 - (N1 * Math.tan(p1) / R1) * (D * D / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * ep2) * Math.pow(D, 4) / 24);
    var lon = 9 * Math.PI / 180 + (D - (1 + 2 * T1 + C1) * Math.pow(D, 3) / 6) / Math.cos(p1);
    return [lon * 180 / Math.PI, lat * 180 / Math.PI];
  }

  /* --- Klick: Sachinformation (WMS) und Objekte (WFS/GeoJSON) ----------------------- */
  var tool = null;
  map.on('click', function (ev) {
    if (tool) { return; }
    var html = '';
    var feats = map.queryRenderedFeatures(ev.point, { layers: kit.vectorLayerIds() });
    if (feats.length) {
      var props = feats[0].properties || {};
      html += '<div class="fw-semibold mb-1">Objekt</div><table class="table table-sm mb-2">' + Object.keys(props).slice(0, 30).map(function (k) {
        return '<tr><th>' + esc(k) + '</th><td>' + esc(props[k]) + '</td></tr>';
      }).join('') + '</table>';
    }
    var popup = new maplibregl.Popup({ maxWidth: '380px' }).setLngLat(ev.lngLat)
      .setHTML(html + '<div class="small text-secondary">' + MapKit.fmtLatLon(ev.lngLat) + '</div><div data-info></div>').addTo(map);
    kit.featureInfo(ev.point).then(function (rows) {
      var target = popup.getElement() && popup.getElement().querySelector('[data-info]');
      if (!target) { return; }
      rows.forEach(function (r) {
        var head = document.createElement('div');
        head.className = 'fw-semibold mt-2';
        head.textContent = r.layer.name;
        var frame = document.createElement('iframe');
        frame.setAttribute('sandbox', '');   // fremdes HTML ohne Skripte und ohne Zugriff aufs Portal
        frame.setAttribute('title', 'Sachinformation ' + r.layer.name);
        frame.srcdoc = '<base target="_blank"><style>body{font:12px sans-serif;margin:4px}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:2px 4px}</style>' + r.html;
        target.appendChild(head);
        target.appendChild(frame);
      });
    });
  });

  /* --- Messen -------------------------------------------------------------------------- */
  var pts = [], measureBox = document.getElementById('map-measure');
  function measureData() {
    var feats = [];
    if (pts.length > 1) { feats.push({ type: 'Feature', geometry: { type: tool === 'area' && pts.length > 2 ? 'Polygon' : 'LineString', coordinates: tool === 'area' && pts.length > 2 ? [pts.concat([pts[0]])] : pts } }); }
    pts.forEach(function (p) { feats.push({ type: 'Feature', geometry: { type: 'Point', coordinates: p } }); });
    return { type: 'FeatureCollection', features: feats };
  }
  function ensureMeasureLayer() {
    if (map.getSource('measure')) { return; }
    map.addSource('measure', { type: 'geojson', data: measureData() });
    map.addLayer({ id: 'measure-fill', type: 'fill', source: 'measure', filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'fill-color': '#1f5fa8', 'fill-opacity': 0.15 } });
    map.addLayer({ id: 'measure-line', type: 'line', source: 'measure', paint: { 'line-color': '#1f5fa8', 'line-width': 2.5, 'line-dasharray': [2, 1] } });
    map.addLayer({ id: 'measure-pt', type: 'circle', source: 'measure', filter: ['==', ['geometry-type'], 'Point'], paint: { 'circle-radius': 4, 'circle-color': '#fff', 'circle-stroke-color': '#1f5fa8', 'circle-stroke-width': 2 } });
  }
  function updateMeasure() {
    ensureMeasureLayer();
    map.getSource('measure').setData(measureData());
    var len = 0;
    for (var i = 1; i < pts.length; i++) { len += MapKit.haversine(pts[i - 1], pts[i]); }
    var text = tool === 'area' ? (pts.length > 2 ? 'Fläche: ' + MapKit.fmtArea(MapKit.ringArea(pts)) + ' · Umfang: ' + MapKit.fmtLen(len + MapKit.haversine(pts[pts.length - 1], pts[0])) : 'Mindestens drei Punkte setzen')
      : (pts.length > 1 ? 'Strecke: ' + MapKit.fmtLen(len) : 'Punkte in die Karte klicken');
    measureBox.innerHTML = '<i class="fa-solid ' + (tool === 'area' ? 'fa-draw-polygon' : 'fa-ruler') + ' me-1"></i>' + text +
      ' <button class="btn btn-sm btn-link py-0" type="button" data-measure-end>Beenden</button>';
  }
  function endMeasure() {
    tool = null; pts = [];
    measureBox.hidden = true;
    if (map.getSource('measure')) { map.getSource('measure').setData(measureData()); }
    map.getCanvas().style.cursor = '';
    document.querySelectorAll('[data-tool]').forEach(function (b) { b.classList.remove('active'); });
  }
  document.querySelectorAll('[data-tool]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var t = btn.dataset.tool;
      if (tool === t) { endMeasure(); return; }
      endMeasure();
      tool = t;
      btn.classList.add('active');
      measureBox.hidden = false;
      map.getCanvas().style.cursor = 'crosshair';
      updateMeasure();
    });
  });
  measureBox.addEventListener('click', function (ev) { if (ev.target.closest('[data-measure-end]')) { endMeasure(); } });
  map.on('click', function (ev) { if (tool) { pts.push([ev.lngLat.lng, ev.lngLat.lat]); updateMeasure(); } });
  map.on('style.load', function () { if (tool) { updateMeasure(); } });

  /* --- Export und Link ------------------------------------------------------------------ */
  function toast(text, error) {
    if (window.Swal) { Swal.fire({ toast: true, position: 'top-end', timer: error ? 5000 : 2200, showConfirmButton: false, icon: error ? 'error' : 'success', title: text }); }
  }
  document.getElementById('btn-export').addEventListener('click', function () {
    map.once('render', function () {
      try {
        var a = document.createElement('a');
        a.download = 'karte.png';
        a.href = map.getCanvas().toDataURL('image/png');
        a.click();
      } catch (e) { toast('Bild nicht möglich: Ein direkt geladener Dienst erlaubt keinen Export.', true); }
    });
    map.triggerRepaint();
  });
  document.getElementById('btn-link').addEventListener('click', function () {
    var on = kit.overlays.filter(function (l) { return l.visible && !l.custom; }).map(function (l) { return l.id; });
    var url = location.origin + location.pathname + '?base=' + encodeURIComponent(kit.baseId || '') + '&layers=' + on.join(',') + location.hash;
    (navigator.clipboard && window.isSecureContext ? navigator.clipboard.writeText(url) : Promise.reject()).then(function () { toast('Link kopiert'); })
      .catch(function () { window.prompt('Link zu diesem Ausschnitt:', url); });
  });

  if (!meta.canEdit) { return; }

  /* --- Eigene Layer hinzufügen ---------------------------------------------------------- */
  function post(url, fields) {
    var body = new FormData();
    body.append('csrf', csrf);
    Object.keys(fields).forEach(function (k) { body.append(k, fields[k]); });
    return fetch(url, { method: 'POST', body: body, headers: { 'X-Requested-With': 'fetch' }, credentials: 'same-origin' }).then(function (r) { return r.json(); });
  }
  var result = document.getElementById('al-result'), status = document.getElementById('al-status'), caps = null;
  document.getElementById('al-query').addEventListener('click', function () {
    var url = document.getElementById('al-url').value.trim(), kind = document.getElementById('al-kind').value;
    status.textContent = 'Frage Dienst ab …';
    result.innerHTML = '';
    post('/maps/capabilities', { url: url, kind: kind }).then(function (d) {
      if (!d.ok) { status.textContent = ''; result.innerHTML = '<div class="alert alert-danger py-2">' + esc(d.error) + '</div>'; return; }
      caps = d;
      caps.url = url.split('?')[0];
      status.textContent = (d.title || 'Dienst') + ' · ' + d.layers.length + ' Layer';
      result.innerHTML = d.layers.length ? '<input class="form-control form-control-sm mb-2" id="al-filter" placeholder="Layer filtern …">' +
        '<div class="list-group" style="max-height:22rem;overflow:auto">' + d.layers.map(function (l, i) {
          return '<label class="list-group-item d-flex gap-2" style="padding-left:' + (0.75 + (l.depth || 0) * 0.8) + 'rem" data-name="' + esc((l.title + ' ' + l.name).toLowerCase()) + '">' +
            '<input class="form-check-input flex-none" type="checkbox" value="' + i + '"' + (d.type === 'xyz' && !l.mercator ? ' disabled' : '') + '>' +
            '<span><span class="fw-semibold">' + esc(l.title) + '</span> <code class="small">' + esc(l.name) + '</code>' +
            (l.times && l.times.length ? ' <span class="badge text-bg-info">Zeit: ' + l.times.length + ' Werte</span>' : '') +
            (d.type === 'xyz' && !l.mercator ? ' <span class="badge text-bg-secondary">nicht in Web-Mercator</span>' : '') +
            (l.abstract ? '<div class="small text-secondary">' + esc(l.abstract) + '</div>' : '') + '</span></label>';
        }).join('') + '</div>' : '<div class="text-secondary">Der Dienst enthält keine abrufbaren Layer.</div>';
      var f = document.getElementById('al-filter');
      if (f) { f.addEventListener('input', function () { var q = f.value.toLowerCase(); result.querySelectorAll('[data-name]').forEach(function (r) { r.classList.toggle('d-none', r.dataset.name.indexOf(q) < 0); }); }); }
    }).catch(function () { status.textContent = 'Abfrage fehlgeschlagen.'; });
  });
  document.getElementById('al-add').addEventListener('click', function () {
    var defs = [];
    var kind = document.getElementById('al-kind').value, url = document.getElementById('al-url').value.trim();
    var chosen = result.querySelectorAll('input[type=checkbox]:checked');
    if (caps && chosen.length) {
      chosen.forEach(function (c) {
        var l = caps.layers[parseInt(c.value, 10)];
        if (caps.type === 'xyz') { defs.push({ kind: 'xyz', url: l.template, name: l.title }); }
        else { defs.push({ kind: caps.type, url: caps.url, layers: l.name, name: l.title, version: caps.version, times: l.times || [], time: l.time || '' }); }
      });
    } else if (kind === 'xyz' && url.indexOf('{z}') >= 0) {
      defs.push({ kind: 'xyz', url: url, name: 'Kacheln: ' + url.split('/')[2] });
    } else { status.textContent = 'Bitte zuerst „Dienst abfragen“ und Layer auswählen.'; return; }
    var done = 0;
    defs.forEach(function (def) {
      post('/maps/sign', { layer: JSON.stringify(def) }).then(function (d) {
        if (d.ok) { kit.addOverlay(d.layer); renderOverlays(); done++; status.textContent = done + ' Layer hinzugefügt'; }
        else { status.textContent = d.error; }
      });
    });
  });

  /* --- Speichern -------------------------------------------------------------------------- */
  function save(asNew) {
    var title = document.getElementById('sm-title').value.trim();
    var out = document.getElementById('sm-result');
    if (!title) { out.innerHTML = '<div class="text-danger small">Bitte einen Titel angeben.</div>'; return; }
    post('/maps/save', { id: asNew ? '' : (meta.mapId || ''), title: title, description: document.getElementById('sm-desc').value,
      public: document.getElementById('sm-public').checked ? '1' : '0', state: JSON.stringify(kit.state()) }).then(function (d) {
      if (!d.ok) { out.innerHTML = '<div class="text-danger small">' + esc(d.error) + '</div>'; return; }
      meta.mapId = d.id;
      var pub = d.public ? location.origin + d.public : '';
      out.innerHTML = '<div class="alert alert-success small mb-0"><i class="fa-solid fa-check me-1"></i>Gespeichert. <a href="' + esc(d.link) + '">Karte öffnen</a>' +
        (pub ? '<div class="mt-2">Öffentlicher Link:<input class="form-control form-control-sm mt-1" readonly value="' + esc(pub) + '"></div>' +
          '<div class="mt-2">Einbetten:<textarea class="form-control form-control-sm font-monospace mt-1" rows="3" readonly>' +
          esc('<iframe src="' + location.origin + d.public.replace('/karte/', '/karte-embed/') + '" title="Karte" style="width:100%;height:600px;border:0" allow="geolocation; fullscreen" loading="lazy"></iframe>') + '</textarea></div>' : '') + '</div>';
    });
  }
  document.getElementById('sm-save').addEventListener('click', function () { save(false); });
  var copyBtn = document.getElementById('sm-copy');
  if (copyBtn) { copyBtn.addEventListener('click', function () { save(true); }); }
})();
