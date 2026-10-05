/* Adressfeld: Suche (Nominatim über das Portal), Standort des Geräts als Adresse, PLZ ergänzt den Ort. */
(function () {
  'use strict';
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  var getJSON = function (url) { return fetch(url, { credentials: 'same-origin' }).then(function (r) { if (!r.ok) { throw new Error(r.status); } return r.json(); }); };

  document.querySelectorAll('.js-address').forEach(function (box) {
    var name = box.dataset.name, full = !!box.dataset.full;
    var f = function (part) { return box.querySelector('[name="' + name + '__' + part + '"]'); };
    var info = box.querySelector('.js-addr-info'), help = info ? info.textContent : '';
    var search = box.querySelector('.js-addr-search'), results = box.querySelector('.js-addr-results');
    var cities = document.getElementById(name + '__cities');
    var found = [], active = -1, timer = null, lastQuery = '';

    function say(text, error) { if (info) { info.textContent = text || help; info.classList.toggle('text-danger', !!error); } }
    function fill(a) {
      ['street', 'house_no', 'zip', 'city', 'district'].forEach(function (k) {
        var el = f(k);
        if (el && (a[k] || k === 'house_no' || k === 'district')) { el.value = a[k] || ''; el.dispatchEvent(new Event('input', { bubbles: true })); }
      });
      if (f('lat') && a.lat != null) { f('lat').value = a.lat; f('lon').value = a.lon; }
      var q = box.closest('.question'); if (q) { q.classList.remove('has-error'); }
      say((a.label ? '„' + a.label + '“ übernommen. ' : '') + (full && !a.house_no ? 'Bitte die Hausnummer prüfen.' : 'Bitte kurz prüfen.'));
    }
    function close() { if (results) { results.classList.add('d-none'); results.innerHTML = ''; } active = -1; }
    function render() {
      if (!found.length) { results.innerHTML = '<div class="list-group-item small text-secondary">Nichts gefunden – Eingabe prüfen oder Felder selbst ausfüllen.</div>'; results.classList.remove('d-none'); return; }
      results.innerHTML = found.map(function (r, i) {
        return '<button type="button" class="list-group-item list-group-item-action small' + (i === active ? ' active' : '') + '" role="option" data-i="' + i + '">' +
          '<i class="fa-solid fa-location-dot me-2 text-secondary"></i>' + esc(r.label) + (r.district && r.label.indexOf(r.district) < 0 ? ' <span class="text-secondary">(' + esc(r.district) + ')</span>' : '') + '</button>';
      }).join('');
      results.classList.remove('d-none');
    }
    function run() {
      var q = search.value.trim();
      if (q.length < 3 || q === lastQuery) { return; }
      lastQuery = q;
      results.innerHTML = '<div class="list-group-item small text-secondary"><span class="spinner-border spinner-border-sm me-2"></span>Suche …</div>';
      results.classList.remove('d-none');
      getJSON('/geo/search?q=' + encodeURIComponent(q)).then(function (d) { found = d.results || []; active = -1; render(); })
        .catch(function () { results.innerHTML = '<div class="list-group-item small text-danger">Suche gerade nicht möglich – bitte Felder selbst ausfüllen.</div>'; });
    }
    if (search) {
      search.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(run, 700); });   // kurze Tipp-Pause (schont den Dienst)
      search.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); ev.stopPropagation(); if (active >= 0 && found[active]) { fill(found[active]); close(); } else { clearTimeout(timer); lastQuery = ''; run(); } }
        else if (ev.key === 'ArrowDown' && found.length) { ev.preventDefault(); active = Math.min(active + 1, found.length - 1); render(); }
        else if (ev.key === 'ArrowUp' && found.length) { ev.preventDefault(); active = Math.max(active - 1, 0); render(); }
        else if (ev.key === 'Escape') { close(); }
      });
      results.addEventListener('click', function (ev) {
        var b = ev.target.closest('[data-i]');
        if (b) { fill(found[+b.dataset.i]); close(); search.value = ''; lastQuery = ''; }
      });
      document.addEventListener('click', function (ev) { if (!box.contains(ev.target)) { close(); } });
    }

    var locate = box.querySelector('.js-addr-locate');
    if (locate) {
      locate.addEventListener('click', function () {
        if (!navigator.geolocation) { say('Ihr Browser kann den Standort nicht ermitteln.', true); return; }
        var old = locate.innerHTML;
        locate.disabled = true; locate.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Standort wird ermittelt …';
        navigator.geolocation.getCurrentPosition(function (pos) {
          getJSON('/geo/reverse?lat=' + pos.coords.latitude + '&lon=' + pos.coords.longitude).then(function (d) {
            locate.disabled = false; locate.innerHTML = old;
            if (d.result) { fill(d.result); } else { say('Zu Ihrem Standort wurde keine Adresse gefunden.', true); }
          }).catch(function () { locate.disabled = false; locate.innerHTML = old; say('Adresse konnte gerade nicht ermittelt werden.', true); });
        }, function (err) {
          locate.disabled = false; locate.innerHTML = old;
          say(err.code === 1 ? 'Der Zugriff auf den Standort wurde nicht erlaubt.' : 'Der Standort konnte nicht ermittelt werden.', true);
        }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 });
      });
    }

    var zip = f('zip'), city = f('city'), lastZip = '';
    if (zip) {
      zip.addEventListener('input', function () {
        zip.value = zip.value.replace(/\D/g, '').slice(0, 5);
        if (zip.value.length !== 5 || zip.value === lastZip) { return; }
        lastZip = zip.value;
        getJSON('/geo/postcode?plz=' + zip.value).then(function (d) {
          var list = d.results || [];
          if (cities) { cities.innerHTML = list.map(function (r) { return '<option value="' + esc(r.city) + '">' + esc(r.district ? r.city + ' – ' + r.district : r.city) + '</option>'; }).join(''); }
          if (!list.length) { say('Zu dieser PLZ ist kein Ort bekannt – bitte selbst eintragen.'); return; }
          var names = list.map(function (r) { return r.city; }).filter(function (v, i, a) { return a.indexOf(v) === i; });
          if (names.length === 1 && (!city.value || names.indexOf(city.value) < 0)) {
            city.value = names[0];
            city.dispatchEvent(new Event('input', { bubbles: true }));
            say('Ort zur PLZ ergänzt.');
          } else if (names.length > 1) {
            say('Mehrere Orte zu dieser PLZ: ' + names.join(', ') + ' – bitte im Feld „Ort“ auswählen.');
            if (names.indexOf(city.value) < 0) { city.value = ''; city.focus(); }
          }
        }).catch(function () { /* ohne Ortsvorschlag weiter */ });
      });
    }
    // Manuelle Änderung der Adresse: gespeicherte Koordinate passt nicht mehr
    ['street', 'house_no', 'zip', 'city'].forEach(function (k) {
      var el = f(k);
      if (el && f('lat')) { el.addEventListener('change', function (ev) { if (ev.isTrusted) { f('lat').value = ''; f('lon').value = ''; } }); }
    });
  });
})();
