/* Kartenfrage im Formular: Punkte, Linien und/oder Flächen einzeichnen (je nach Einstellung, auch mehrere),
   Punkt am GPS-Standort, Eingabe von Breite/Länge – und unabhängig davon den eigenen Standort erfassen. */
(function () {
  'use strict';
  var el = document.getElementById('geo-bundle');
  if (!el || !window.MapKit || !window.MapDraw) { return; }
  var bundle = JSON.parse(el.textContent);
  var esc = MapKit.esc;
  var KIND = { point: ['Punkt', 'fa-location-dot'], line: ['Linie', 'fa-route'], polygon: ['Fläche', 'fa-draw-polygon'] };
  var kindOf = function (f) { return { Point: 'point', LineString: 'line', Polygon: 'polygon' }[f.geometry.type]; };

  function baseSelect(kit, box) {
    if (kit.bases.length < 2) { return; }
    var sel = document.createElement('select');   // kleine Auswahl der Grundkarte
    sel.className = 'form-select form-select-sm';
    sel.setAttribute('aria-label', 'Grundkarte');
    sel.style.cssText = 'position:absolute;left:.5rem;top:.5rem;z-index:2;width:auto;max-width:60%';
    sel.innerHTML = kit.bases.map(function (x) { return '<option value="' + esc(x.id) + '"' + (x.id === kit.baseId ? ' selected' : '') + '>' + esc(x.name) + '</option>'; }).join('');
    sel.addEventListener('change', function () { kit.setBase(sel.value); });
    box.querySelector('.js-geo-map').appendChild(sel);
  }
  function locate(button, done, fail) {
    if (!navigator.geolocation) { fail('Ihr Browser kann den Standort nicht ermitteln.'); return; }
    var old = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Standort wird ermittelt …';
    navigator.geolocation.getCurrentPosition(function (pos) {
      button.disabled = false; button.innerHTML = old;
      done(pos);
    }, function (err) {
      button.disabled = false; button.innerHTML = old;
      fail(err.code === 1 ? 'Der Zugriff auf den Standort wurde nicht erlaubt (Einstellungen des Browsers).' : 'Der Standort konnte nicht ermittelt werden.');
    }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 10000 });
  }
  function parseStart(raw) {
    raw = (raw || '').trim();
    if (!raw) { return []; }
    if (raw.charAt(0) !== '{' && raw.charAt(0) !== '[') {   // „Breite, Länge“
      var p = raw.split(/[,;\s]+/).map(parseFloat);
      return p.length === 2 && !isNaN(p[0]) && !isNaN(p[1]) ? [{ type: 'Feature', geometry: { type: 'Point', coordinates: [p[1], p[0]] }, properties: { src: 'manual' } }] : [];
    }
    try {
      var d = JSON.parse(raw);
      if (d.type === 'LineString' || d.type === 'Polygon' || d.type === 'Point') { return [{ type: 'Feature', geometry: d, properties: {} }]; }
      return (d.features || []).filter(function (f) { return f && f.geometry; });
    } catch (e) { return []; }
  }

  document.querySelectorAll('.js-geo').forEach(function (box) {
    var kinds = (box.dataset.kinds || 'point').split(','), max = parseInt(box.dataset.max || '1', 10);
    var value = box.querySelector('.js-geo-value'), info = box.querySelector('.js-geo-info'), help = info.textContent;
    var list = box.querySelector('.js-geo-list');
    var lat = box.querySelector('.js-geo-lat'), lon = box.querySelector('.js-geo-lon');
    var singlePoint = kinds.length === 1 && kinds[0] === 'point' && max === 1;
    var q = function (sel) { return box.querySelector(sel); };
    var start = parseStart(value.value);
    var b = JSON.parse(JSON.stringify(bundle));
    if (start.length && start[0].geometry.type === 'Point') { b.state = { center: start[0].geometry.coordinates, zoom: 16 }; }
    var kit = MapKit.create(q('.js-geo-map'), b, {});
    var map = kit.map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    baseSelect(kit, box);

    function sync(feats) {
      value.value = feats.length ? JSON.stringify({ features: feats.map(function (f) {
        return { type: 'Feature', geometry: f.geometry, properties: { acc: f.properties.acc, src: f.properties.src } };
      }) }) : '';
      if (feats.length) { var qq = box.closest('.question'); if (qq) { qq.classList.remove('has-error'); } if (lat) { lat.setCustomValidity(''); } }
      if (lat && singlePoint) {
        var p = feats[0] && feats[0].geometry.coordinates;
        if (p && document.activeElement !== lat && document.activeElement !== lon) { lat.value = p[1].toFixed(6); lon.value = p[0].toFixed(6); }
        if (!p) { lat.value = lon.value = ''; }
      }
      renderList(feats);
    }
    function full() { return draw.features().length >= max; }
    function renderList(feats) {
      var multi = max > 1 || kinds.length > 1;
      list.innerHTML = feats.map(function (f, i) {
        var k = kindOf(f), extra = f.properties.acc ? ' (±' + f.properties.acc + ' m' + (f.properties.src === 'gps' ? ', GPS' : '') + ')' : '';
        return '<div class="d-flex align-items-center gap-2 small border rounded px-2 py-1" data-fid="' + esc(f.id) + '">' +
          '<i class="fa-solid ' + KIND[k][1] + ' text-danger"></i><span class="flex-grow-1">' + (multi ? '<strong>' + KIND[k][0] + ' ' + (i + 1) + ':</strong> ' : '') + esc(MapDraw.describe(f)) + esc(extra) + '</span>' +
          '<button type="button" class="btn btn-sm btn-link py-0" data-zoom title="Hinzoomen" aria-label="Hinzoomen"><i class="fa-solid fa-magnifying-glass-location"></i></button>' +
          '<button type="button" class="btn btn-sm btn-link text-danger py-0" data-del title="Entfernen" aria-label="Entfernen"><i class="fa-regular fa-trash-can"></i></button></div>';
      }).join('');
      box.querySelectorAll('.js-geo-draw, .js-geo-gps-point').forEach(function (btn) {
        btn.disabled = !singlePoint && max > 1 && feats.length >= max;
        btn.title = btn.disabled ? 'Höchstzahl erreicht – zuerst ein Objekt entfernen' : '';
      });
    }
    var draw = MapDraw.create(map, {
      single: max === 1, color: '#d62828',
      onChange: sync,
      onSketch: function (s) {
        var drawing = !!s && s.mode !== 'point';
        box.querySelectorAll('.js-geo-draw').forEach(function (btn) { btn.classList.toggle('active', !!s && btn.dataset.kind === s.mode); });
        q('.js-geo-finish').classList.toggle('d-none', !drawing);
        q('.js-geo-finish').disabled = !s || s.count < s.min;
        q('.js-geo-undo').classList.toggle('d-none', !drawing);
        q('.js-geo-undo').disabled = !s || !s.count;
        if (q('.js-geo-gps-vertex')) { q('.js-geo-gps-vertex').classList.toggle('d-none', !drawing); }
        if (!s) { info.textContent = help; return; }
        if (s.mode === 'point') { info.textContent = singlePoint ? help : 'In die Karte klicken, um den Punkt zu setzen.'; return; }
        info.textContent = (s.text ? s.text + ' · ' : '') + (s.count < s.min ? 'Noch ' + (s.min - s.count) + ' Punkt(e) setzen.' : 'Weitere Punkte setzen, Doppelklick oder „Fertig“ beendet.');
      },
      onFinish: function (f) {
        if (f) { f.properties.src = f.properties.src || 'map'; draw.update(f.id, { src: f.properties.src }); }
        if (singlePoint) { setTimeout(function () { draw.start('point'); }, 0); }   // Punkt jederzeit per Klick versetzen
        else if (f) { draw.select(f.id); }
      }
    });
    map.on('load', function () {
      if (start.length) {
        draw.setFeatures(start);
        if (!singlePoint) { var all = draw.features(); draw.zoomTo(all[all.length - 1].id); }
      }
      if (singlePoint) { draw.start('point'); }
      else if (kinds.length === 1 && !start.length) { draw.start(kinds[0]); }   // gleich losklicken können
      sync(draw.features());
    });

    box.querySelectorAll('.js-geo-draw').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (draw.mode() === btn.dataset.kind && !singlePoint) { draw.cancel(); return; }
        draw.start(btn.dataset.kind);
      });
    });
    q('.js-geo-finish').addEventListener('click', function () { draw.finish(); });
    q('.js-geo-undo').addEventListener('click', function () { draw.undo(); });
    var gpsVertex = q('.js-geo-gps-vertex');
    if (gpsVertex) {
      gpsVertex.addEventListener('click', function () {
        locate(gpsVertex, function (pos) {
          draw.addPoint([pos.coords.longitude, pos.coords.latitude]);
          map.flyTo({ center: [pos.coords.longitude, pos.coords.latitude], zoom: Math.max(map.getZoom(), 17) });
        }, function (msg) { info.textContent = msg; });
      });
    }
    var gpsPoint = q('.js-geo-gps-point');
    if (gpsPoint) {
      gpsPoint.addEventListener('click', function () {
        locate(gpsPoint, function (pos) {
          var p = { type: 'Feature', geometry: { type: 'Point', coordinates: [Math.round(pos.coords.longitude * 1e6) / 1e6, Math.round(pos.coords.latitude * 1e6) / 1e6] },
            properties: { acc: Math.round(pos.coords.accuracy), src: 'gps', color: '#d62828' } };
          draw.cancel();
          draw.setFeatures(max === 1 ? [p] : draw.features().concat([p]));
          map.flyTo({ center: p.geometry.coordinates, zoom: Math.max(map.getZoom(), 17) });
          if (singlePoint) { draw.start('point'); }
        }, function (msg) { info.textContent = msg + ' Bitte in die Karte klicken.'; });
      });
    }
    if (lat) {
      var fromInputs = function () {
        var a = parseFloat((lat.value || '').replace(',', '.')), o = parseFloat((lon.value || '').replace(',', '.'));
        if (!isNaN(a) && !isNaN(o) && Math.abs(a) <= 90 && Math.abs(o) <= 180) {
          draw.setFeatures([{ type: 'Feature', geometry: { type: 'Point', coordinates: [o, a] }, properties: { src: 'manual', color: '#d62828' } }]);
          map.flyTo({ center: [o, a], zoom: Math.max(map.getZoom(), 16) });
          draw.start('point');
        }
      };
      lat.addEventListener('change', fromInputs); lon.addEventListener('change', fromInputs);
    }
    list.addEventListener('click', function (ev) {
      var row = ev.target.closest('[data-fid]');
      if (!row) { return; }
      if (ev.target.closest('[data-del]')) { draw.remove(row.dataset.fid); }
      if (ev.target.closest('[data-zoom]')) { draw.zoomTo(row.dataset.fid); if (!draw.mode()) { draw.select(row.dataset.fid); } }
    });
    q('.js-geo-clear').addEventListener('click', function () {
      draw.cancel(); draw.clear();
      if (singlePoint) { draw.start('point'); } else if (kinds.length === 1) { draw.start(kinds[0]); }
    });

    /* --- Eigener Standort, unabhängig von den Zeichnungen ----------------------------- */
    var posInput = q('.js-geo-pos'), locBtn = q('.js-geo-locate');
    if (posInput && locBtn) {
      var posText = q('.js-geo-pos-text'), posClear = q('.js-geo-pos-clear'), marker = null;
      var showPos = function (p) {
        if (!p) {
          posInput.value = ''; posText.textContent = 'noch nicht erfasst'; posClear.classList.add('d-none');
          if (marker) { marker.remove(); marker = null; }
          return;
        }
        posInput.value = JSON.stringify(p);
        var t = p.at ? new Date(p.at) : null;
        posText.textContent = p.lat.toFixed(6) + ', ' + p.lon.toFixed(6) + (p.acc ? ' (±' + p.acc + ' m)' : '') + (t && !isNaN(t) ? ' · erfasst ' + t.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' }) + ' Uhr' : '');
        posText.classList.remove('text-danger');
        posClear.classList.remove('d-none');
        if (!marker) {
          var dot = document.createElement('div');
          dot.className = 'geo-me'; dot.title = 'Ihr Standort';
          marker = new maplibregl.Marker({ element: dot }).setLngLat([p.lon, p.lat]).addTo(map);
        } else { marker.setLngLat([p.lon, p.lat]); }
        var qq = box.closest('.question'); if (qq) { qq.classList.remove('has-error'); }
      };
      try { if (posInput.value) { showPos(JSON.parse(posInput.value)); } } catch (e) { posInput.value = ''; }
      locBtn.addEventListener('click', function () {
        locate(locBtn, function (pos) {
          showPos({ lat: Math.round(pos.coords.latitude * 1e6) / 1e6, lon: Math.round(pos.coords.longitude * 1e6) / 1e6,
            acc: Math.round(pos.coords.accuracy), at: new Date(pos.timestamp || Date.now()).toISOString() });
          if (!draw.features().length) { map.flyTo({ center: [pos.coords.longitude, pos.coords.latitude], zoom: Math.max(map.getZoom(), 16) }); }
        }, function (msg) { posText.textContent = msg; posText.classList.add('text-danger'); });
      });
      posClear.addEventListener('click', function () { showPos(null); });
    }
    new ResizeObserver(function () { map.resize(); }).observe(q('.js-geo-map'));
  });
})();
