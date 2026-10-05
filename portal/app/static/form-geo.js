/* GPS-Frage im Formular: Punkt per Klick in die Karte, per Standort des Geräts oder per Eingabe setzen. */
(function () {
  'use strict';
  var el = document.getElementById('geo-bundle');
  if (!el || !window.MapKit) { return; }
  var bundle = JSON.parse(el.textContent);

  document.querySelectorAll('.js-geo').forEach(function (box) {
    var value = box.querySelector('.js-geo-value'), acc = box.querySelector('.js-geo-acc'), src = box.querySelector('.js-geo-src');
    var lat = box.querySelector('.js-geo-lat'), lon = box.querySelector('.js-geo-lon');
    var info = box.querySelector('.js-geo-info');
    var start = (value.value || '').split(',').map(parseFloat);
    var has = start.length === 2 && !isNaN(start[0]) && !isNaN(start[1]);
    var b = JSON.parse(JSON.stringify(bundle));
    if (has) { b.state = { center: [start[1], start[0]], zoom: 16 }; }
    var kit = MapKit.create(box.querySelector('.js-geo-map'), b, {});
    var map = kit.map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    if (kit.bases.length > 1) {
      // kleine Auswahl der Grundkarte
      var sel = document.createElement('select');
      sel.className = 'form-select form-select-sm';
      sel.setAttribute('aria-label', 'Grundkarte');
      sel.style.cssText = 'position:absolute;left:.5rem;top:.5rem;z-index:2;width:auto;max-width:60%';
      sel.innerHTML = kit.bases.map(function (x) { return '<option value="' + MapKit.esc(x.id) + '"' + (x.id === kit.baseId ? ' selected' : '') + '>' + MapKit.esc(x.name) + '</option>'; }).join('');
      sel.addEventListener('change', function () { kit.setBase(sel.value); });
      box.querySelector('.js-geo-map').appendChild(sel);
    }
    var marker = null;
    function set(lngLat, source, accuracy, fly) {
      var la = Math.round(lngLat.lat * 1e6) / 1e6, lo = Math.round(lngLat.lng * 1e6) / 1e6;
      value.value = la + ',' + lo;
      acc.value = accuracy ? Math.round(accuracy) : '';
      src.value = source;
      if (lat) { lat.value = la.toFixed(6); lon.value = lo.toFixed(6); }
      if (!marker) {
        marker = new maplibregl.Marker({ draggable: true, color: '#d62828' }).setLngLat([lo, la]).addTo(map);
        marker.on('dragend', function () { set(marker.getLngLat(), 'map', null, false); });
      } else { marker.setLngLat([lo, la]); }
      if (fly) { map.flyTo({ center: [lo, la], zoom: Math.max(map.getZoom(), 16) }); }
      var u = MapKit.toUtm32(lo, la);
      info.textContent = 'Gewählt: ' + la.toFixed(6) + ', ' + lo.toFixed(6) + ' (UTM 32: ' + Math.round(u[0]) + ' ' + Math.round(u[1]) + ')' +
        (accuracy ? ' · Genauigkeit etwa ±' + Math.round(accuracy) + ' m' : '');
      var q = box.closest('.question');
      if (q) { q.classList.remove('has-error'); }
      if (lat) { lat.setCustomValidity(''); }
    }
    if (has) { set({ lat: start[0], lng: start[1] }, src.value || 'map', parseFloat(acc.value) || null, false); }
    map.on('click', function (ev) { set(ev.lngLat, 'map', null, false); });
    var gps = box.querySelector('.js-geo-gps');
    if (gps) {
      gps.addEventListener('click', function () {
        if (!navigator.geolocation) { info.textContent = 'Ihr Browser kann den Standort nicht ermitteln.'; return; }
        var old = gps.innerHTML;
        gps.disabled = true;
        gps.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Standort wird ermittelt …';
        navigator.geolocation.getCurrentPosition(function (pos) {
          gps.disabled = false; gps.innerHTML = old;
          set({ lat: pos.coords.latitude, lng: pos.coords.longitude }, 'gps', pos.coords.accuracy, true);
        }, function (err) {
          gps.disabled = false; gps.innerHTML = old;
          info.textContent = err.code === 1 ? 'Der Zugriff auf den Standort wurde nicht erlaubt. Bitte in die Karte klicken oder die Koordinaten eingeben.'
            : 'Der Standort konnte nicht ermittelt werden. Bitte in die Karte klicken oder die Koordinaten eingeben.';
        }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 });
      });
    }
    function fromInputs() {
      var a = parseFloat((lat.value || '').replace(',', '.')), o = parseFloat((lon.value || '').replace(',', '.'));
      if (!isNaN(a) && !isNaN(o) && Math.abs(a) <= 90 && Math.abs(o) <= 180) { set({ lat: a, lng: o }, 'manual', null, true); }
    }
    if (lat) { lat.addEventListener('change', fromInputs); lon.addEventListener('change', fromInputs); }
    box.querySelector('.js-geo-clear').addEventListener('click', function () {
      value.value = acc.value = src.value = '';
      if (lat) { lat.value = lon.value = ''; }
      if (marker) { marker.remove(); marker = null; }
      info.textContent = 'Auswahl gelöscht.';
    });
    // Karte auf späteren Seiten erst beim Anzeigen richtig vermessen
    new ResizeObserver(function () { map.resize(); }).observe(box.querySelector('.js-geo-map'));
  });
})();
