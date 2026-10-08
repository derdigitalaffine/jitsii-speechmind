/* Kartenbrowser: Ebenenliste, Transparenz, Zeit (WMS-T), Legende, Sachinformation, Messen, Export,
   Koordinatensuche, eigene Layer (WMS/WFS/WMTS) und Speichern. */
(function () {
  'use strict';
  var bundle = JSON.parse(document.getElementById('map-bundle').textContent);
  var publicGeocoder = true;
  GeoSearch.policy.then(function(d){publicGeocoder=d.public_only;var hint=document.createElement('div');hint.className='small text-secondary';hint.textContent=publicGeocoder?'Öffentliche Orte: neue Suche mit Enter, gespeicherte Treffer beim Tippen.':'Adresse suchen – Live-Suche gemäß Einstellungen.';document.getElementById('coord-search').append(hint);}).catch(function(){});
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
  var searchBox = document.getElementById('place-results'), searchMarker = null;
  function jump(lngLat, label, bbox) {
    if (bbox && bbox.length === 4) {
      map.fitBounds([[parseFloat(bbox[2]), parseFloat(bbox[0])], [parseFloat(bbox[3]), parseFloat(bbox[1])]], { padding: 40, maxZoom: 18 });
    } else { map.flyTo({ center: lngLat, zoom: Math.max(map.getZoom(), 16) }); }
    if (searchMarker) { searchMarker.remove(); }
    searchMarker = new maplibregl.Marker({ color: '#1f5fa8' }).setLngLat(lngLat)
      .setPopup(new maplibregl.Popup({ offset: 24 }).setText(label)).addTo(map);
    searchMarker.togglePopup();
    if (window.innerWidth < 768) { shell.classList.add('panel-hidden'); setTimeout(function () { map.resize(); }, 50); }
  }
  function coordsFrom(text) {
    var t = text.replace(/utm\s*32[nN]?/i, '').trim();
    if (/[a-zäöüß]{3,}/i.test(t)) { return null; }   // enthält Wörter → Ortssuche
    var nums = t.match(/-?\d+(?:[.,]\d+)?/g);
    if (!nums || nums.length !== 2) { return null; }
    var a = parseFloat(nums[0].replace(',', '.')), b = parseFloat(nums[1].replace(',', '.'));
    if (Math.abs(a) > 1000 || Math.abs(b) > 1000) { return utmToLngLat(a, b); }
    if (Math.abs(a) <= 90) { return (a < 20 && b > 40) ? [a, b] : [b, a]; }   // üblich: Breite, Länge
    return [a, b];
  }
  var searchInput=document.getElementById('coord-input');
  function mapResults(res,live) {
      if (!res.length) { searchBox.innerHTML = live ? '' : '<div class="small text-secondary py-1">Nichts gefunden.</div>'; return; }
      searchBox.replaceChildren();res.filter(function(r){return r.lat!=null&&r.lon!=null;}).forEach(function(r){var b=document.createElement('button');b.type='button';b.className='list-group-item list-group-item-action small';b.textContent=r.label;b.onclick=function(){jump([r.lon,r.lat],r.label,r.type==='house'?null:r.bbox);};searchBox.append(b);});
      if(!live&&res.length===1&&res[0].lat!=null&&res[0].lon!=null){jump([res[0].lon,res[0].lat],res[0].label,res[0].type==='house'?null:res[0].bbox);}
  }
  var runMapSearch=GeoSearch.bind(searchInput,mapResults,function(){searchBox.textContent='Suche gerade nicht möglich.';});
  document.getElementById('coord-search').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var text = document.getElementById('coord-input').value.trim();
    if (!text) { return; }
    var lngLat = coordsFrom(text);
    if (lngLat) { searchBox.innerHTML = ''; jump(lngLat, lngLat[1].toFixed(6) + ', ' + lngLat[0].toFixed(6)); return; }
    runMapSearch();
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

  var parcelKit=MapParcels.create(map,document.getElementById('parcel-browser'),{initial:bundle.state.parcels||[],isDrawing:function(){return draw&&draw.mode();},show:function(){shell.classList.remove('panel-hidden');}});
  var advanced=document.getElementById('map-advanced');
  try{advanced.checked=localStorage.getItem('map-advanced')==='1';}catch(e){}
  function advancedMode(){shell.classList.toggle('is-advanced',advanced.checked);try{localStorage.setItem('map-advanced',advanced.checked?'1':'0');}catch(e){}}
  advanced.addEventListener('change',advancedMode);advancedMode();
  map.on('map-service-error',function(e){document.getElementById('map-service-status').textContent=e.message;});
  map.on('error',function(e){if(e.sourceId)document.getElementById('map-service-status').textContent='Ein Kartendienst konnte nicht geladen werden. Quelle und Layerauswahl im erweiterten Modus prüfen.';});
  /* --- Klick: Sachinformation (WMS) und Objekte (WFS/GeoJSON) ----------------------- */
  map.on('click', function (ev) {
    if (draw.mode()) { return; }
    var mine = draw.layerIds().filter(function (id) { return map.getLayer(id); });
    if (mine.length && map.queryRenderedFeatures(ev.point, { layers: mine }).length) { return; }   // Klick wählt eine Zeichnung
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

  /* --- Zeichnen und Messen ------------------------------------------------------------- */
  var measureBox = document.getElementById('map-measure'), drawList = document.getElementById('draw-list');
  var KIND = { point: ['Punkt', 'fa-location-dot'], line: ['Linie', 'fa-route'], polygon: ['Fläche', 'fa-draw-polygon'] };
  var kindOf = function (f) { return f.properties.kind || { Point: 'point', LineString: 'line', Polygon: 'polygon' }[f.geometry.type]; };
  var draw = MapDraw.create(map, {
    onChange: renderDrawings,
    onSelect: function (id) {
      drawList.querySelectorAll('[data-fid]').forEach(function (r) { r.classList.toggle('active', r.dataset.fid === id); });
      var row = id && drawList.querySelector('[data-fid="' + id + '"]');
      if (row) { shell.classList.remove('panel-hidden'); row.scrollIntoView({ block: 'nearest' }); }
    },
    onSketch: function (info) {
      document.querySelectorAll('[data-draw]').forEach(function (b) { b.classList.toggle('active', !!info && b.dataset.draw === info.mode); });
      if (!info) { measureBox.hidden = true; return; }
      measureBox.hidden = false;
      var hint = info.mode === 'point' ? 'In die Karte klicken' :
        info.count < info.min ? (info.mode === 'polygon' ? 'Eckpunkte setzen (mind. 3)' : 'Punkte setzen (mind. 2)') :
        (info.mode === 'polygon' ? 'Ersten Punkt oder doppelt klicken zum Schließen' : 'Doppelklick oder „Fertig“ beendet');
      measureBox.innerHTML = '<i class="fa-solid ' + KIND[info.mode][1] + ' me-1"></i>' + (info.text ? '<strong>' + esc(info.text) + '</strong> · ' : '') + esc(hint) +
        '<span class="ms-2 text-nowrap">' + (info.count >= info.min && info.mode !== 'point' ? '<button class="btn btn-sm btn-primary py-0" type="button" data-sk="finish">Fertig</button> ' : '') +
        (info.count ? '<button class="btn btn-sm btn-outline-secondary py-0" type="button" data-sk="undo" title="Letzten Punkt entfernen (Rücktaste)"><i class="fa-solid fa-rotate-left"></i></button> ' : '') +
        '<button class="btn btn-sm btn-outline-secondary py-0" type="button" data-sk="cancel">Abbrechen</button></span>';
    }
  });
  measureBox.addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-sk]');
    if (b) { draw[b.dataset.sk](); }
  });
  document.querySelectorAll('[data-draw]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (draw.mode() === btn.dataset.draw) { draw.cancel(); return; }
      draw.start(btn.dataset.draw);
      if (window.innerWidth < 768) { shell.classList.add('panel-hidden'); setTimeout(function () { map.resize(); }, 50); }
    });
  });
  function renderDrawings(list) {
    if (typing) { return; }
    list = list || draw.features();
    document.getElementById('draw-actions').hidden = !list.length;
    drawList.innerHTML = list.length ? list.map(function (f, i) {
      var k = kindOf(f);
      return '<div class="draw-row" data-fid="' + esc(f.id) + '">' +
        '<input type="color" class="form-control form-control-color form-control-sm flex-none" value="' + esc(f.properties.color || '#d62828') + '" data-dc title="Farbe" aria-label="Farbe">' +
        '<div class="flex-grow-1 min-w-0"><input class="form-control form-control-sm" value="' + esc(f.properties.name || '') + '" placeholder="' + KIND[k][0] + ' ' + (i + 1) + '" data-dn aria-label="Bezeichnung">' +
        '<div class="small text-secondary text-truncate mt-1"><i class="fa-solid ' + KIND[k][1] + ' me-1"></i>' + esc(MapDraw.describe(f)) + '</div></div>' +
        '<div class="btn-group-vertical btn-group-sm flex-none"><button class="btn btn-link py-0" type="button" data-dz title="Hinzoomen" aria-label="Hinzoomen"><i class="fa-solid fa-magnifying-glass-location"></i></button>' +
        '<button class="btn btn-link text-danger py-0" type="button" data-dd title="Löschen" aria-label="Löschen"><i class="fa-regular fa-trash-can"></i></button></div></div>';
    }).join('') : '<div class="small text-secondary">Noch nichts gezeichnet. Wählen Sie oben Punkt, Linie oder Fläche – Länge und Fläche werden dabei gemessen.</div>';
    var sel = draw.selected();
    if (sel) { var r = drawList.querySelector('[data-fid="' + sel + '"]'); if (r) { r.classList.add('active'); } }
  }
  var typing = false;
  drawList.addEventListener('input', function (ev) {
    var row = ev.target.closest('[data-fid]');
    if (!row) { return; }
    typing = true;   // Liste beim Tippen nicht neu aufbauen (Fokus bleibt im Feld)
    draw.update(row.dataset.fid, ev.target.hasAttribute('data-dc') ? { color: ev.target.value } : { name: ev.target.value.slice(0, 200) });
    typing = false;
  });
  drawList.addEventListener('click', function (ev) {
    var row = ev.target.closest('[data-fid]');
    if (!row) { return; }
    if (ev.target.closest('[data-dd]')) { draw.remove(row.dataset.fid); return; }
    if (ev.target.closest('[data-dz]')) { draw.zoomTo(row.dataset.fid); draw.select(row.dataset.fid); return; }
    if (!ev.target.closest('input')) { draw.select(row.dataset.fid); }
  });
  document.getElementById('draw-export').addEventListener('click', function () {
    var data = { type: 'FeatureCollection', features: draw.features().map(function (f) {
      var m = MapDraw.measure(f);
      return { type: 'Feature', geometry: f.geometry, properties: { name: f.properties.name || '', farbe: f.properties.color, laenge_m: Math.round(m.length * 10) / 10, flaeche_m2: Math.round(m.area) } };
    }) };
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/geo+json' }));
    a.download = 'zeichnungen.geojson';
    a.click();
  });
  document.getElementById('draw-import').addEventListener('change', function (ev) {
    var file = ev.target.files[0];
    if (!file) { return; }
    file.text().then(function (text) {
      var data = JSON.parse(text), list = data.type === 'FeatureCollection' ? data.features : [data];
      var ok = list.filter(function (f) { return f && f.geometry && /^(Point|LineString|Polygon)$/.test(f.geometry.type); }).slice(0, 500).map(function (f, i) {
        var p = f.properties || {};
        return { type: 'Feature', geometry: f.geometry, properties: { name: String(p.name || p.bezeichnung || '').slice(0, 200), color: /^#[0-9a-f]{6}$/i.test(p.farbe || p.color || '') ? (p.farbe || p.color) : MapDraw.COLORS[i % MapDraw.COLORS.length] } };
      });
      draw.setFeatures(draw.features().concat(ok));
      if (ok.length) { draw.zoomTo(draw.features()[draw.features().length - 1].id); }
      toast(ok.length + ' Objekt(e) übernommen', !ok.length);
    }).catch(function () { toast('Die Datei ist kein gültiges GeoJSON.', true); });
    ev.target.value = '';
  });
  document.getElementById('draw-clear').addEventListener('click', function () {
    var go = function () { draw.clear(); };
    if (window.Swal) { Swal.fire({ title: 'Alle Zeichnungen löschen?', icon: 'warning', showCancelButton: true, confirmButtonText: 'Löschen', cancelButtonText: 'Abbrechen' }).then(function (r) { if (r.isConfirmed) { go(); } }); }
    else if (confirm('Alle Zeichnungen löschen?')) { go(); }
  });
  draw.setFeatures((bundle.state && bundle.state.drawings) || []);
  renderDrawings();

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
    return fetch(url, { method: 'POST', body: body, headers: { 'X-Requested-With': 'fetch', 'Accept':'application/json' }, credentials: 'same-origin' }).then(function (r) { return r.json(); });
  }
  var result = document.getElementById('al-result'), status = document.getElementById('al-status'), caps = null;
  ['al-url','al-kind'].forEach(function(id){document.getElementById(id).addEventListener('input',function(){caps=null;result.replaceChildren();});});
  document.getElementById('map-catalog-load').addEventListener('click',function(){
    var key=document.getElementById('map-catalog').value;status.textContent='Amtliche Quelle wird geprüft …';
    post('/maps/catalog/'+key,{}).then(function(d){if(!d.ok){status.textContent=d.error;return;}document.getElementById('al-url').value=d.url;document.getElementById('al-kind').value=d.type==='wmts'?'xyz':d.type;showCaps(d,d.url);}).catch(function(){status.textContent='Quelle derzeit nicht erreichbar. Bitte später erneut versuchen.';});
  });
  document.getElementById('al-query').addEventListener('click', function () {
    var url = document.getElementById('al-url').value.trim(), kind = document.getElementById('al-kind').value;
    status.textContent = 'Frage Dienst ab …';
    result.innerHTML = '';
    post('/maps/capabilities', { url: url, kind: kind }).then(function (d) {
      showCaps(d,url);
    }).catch(function () { status.textContent = 'Abfrage fehlgeschlagen.'; });
  });
  function showCaps(d,url) {
      if (!d.ok) { status.textContent = ''; result.innerHTML = '<div class="alert alert-danger py-2">' + esc(d.error) + '</div>'; return; }
      caps = d;
      caps.url = d.url || url;
      status.textContent = (d.title || 'Dienst') + ' · ' + d.layers.length + ' Layer';
      result.innerHTML = d.layers.length ? '<input class="form-control form-control-sm mb-2" id="al-filter" placeholder="Layer filtern …">' +
        '<div class="list-group" style="max-height:22rem;overflow:auto">' + d.layers.map(function (l, i) {
          return '<label class="list-group-item d-flex gap-2" style="padding-left:' + (0.75 + (l.depth || 0) * 0.8) + 'rem" data-name="' + esc((l.title + ' ' + l.name).toLowerCase()) + '">' +
            '<input class="form-check-input flex-none" type="checkbox" value="' + i + '"' + (l.supported === false ? ' disabled' : '') + '>' +
            '<span><span class="fw-semibold">' + esc(l.title) + '</span> <code class="small">' + esc(l.name) + '</code>' +
            (l.times && l.times.length ? ' <span class="badge text-bg-info">Zeit: ' + l.times.length + ' Werte</span>' : '') +
            (l.supported === false ? ' <span class="badge text-bg-secondary">nicht in Web-Mercator</span>' : '') +
            (l.abstract ? '<div class="small text-secondary">' + esc(l.abstract) + '</div>' : '') + '</span></label>';
        }).join('') + '</div>' : '<div class="text-secondary">Der Dienst enthält keine abrufbaren Layer.</div>';
      var f = document.getElementById('al-filter');
      if (f) { f.addEventListener('input', function () { var q = f.value.toLowerCase(); result.querySelectorAll('[data-name]').forEach(function (r) { r.classList.toggle('d-none', r.dataset.name.indexOf(q) < 0); }); }); }
  }
  document.getElementById('al-add').addEventListener('click', function () {
    var defs = [];
    var kind = document.getElementById('al-kind').value, url = document.getElementById('al-url').value.trim();
    var chosen = result.querySelectorAll('input[type=checkbox]:checked');
    if (caps && chosen.length) {
      chosen.forEach(function (c) {
        var l = caps.layers[parseInt(c.value, 10)];
        if (caps.type === 'wmts') { defs.push({kind:'wmts',url:l.template,layers:l.name,name:l.title,styles:l.styles,format:l.format,service:l.service,attribution:l.attribution||caps.attribution||''}); }
        else if (caps.type === 'xyz') { defs.push({ kind: 'xyz', url: l.template, name: l.title }); }
        else { defs.push({ kind: caps.type, url: caps.url, layers: l.name, name: l.title, version: caps.version, times: l.times || [], time: l.time || '', service:l.service || {},attribution:l.attribution||caps.attribution||'' }); }
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
      public: document.getElementById('sm-public').checked ? '1' : '0', state: JSON.stringify(Object.assign(kit.state(), { drawings: draw.features(), parcels:parcelKit.features() })) }).then(function (d) {
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
