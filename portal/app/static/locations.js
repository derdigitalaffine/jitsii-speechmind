(function () {
  'use strict';
  GeoSearch.policy.then(function (info) {
    document.querySelectorAll('.js-poi-search').forEach(function (box) {
      var form = box.closest('form'), input = document.createElement('input'), button = document.createElement('button'), results = document.createElement('div');
      button.type = 'button'; button.className = 'btn btn-outline-secondary'; button.textContent = info.public_only ? 'Öffentlichen Ort suchen' : 'Adresse suchen';
      results.className = 'list-group mt-2'; box.append(button, results);
      var run = GeoSearch.bind(input, function (items, live) {
        results.replaceChildren();
        items.forEach(function (p) {
          if (p.lat == null || p.lon == null) { return; }
          var choice = document.createElement('button'); choice.type = 'button'; choice.className = 'list-group-item list-group-item-action'; choice.textContent = p.label + ' – Koordinaten übernehmen';
          choice.onclick = function () { form.elements.lat.value = p.lat; form.elements.lon.value = p.lon; results.textContent = 'Koordinaten übernommen. Bitte prüfen und Änderungen speichern.'; };
          results.append(choice);
        });
        if (!live && !items.length) { results.textContent = 'Kein Ort gefunden. Anschrift prüfen.'; }
      }, function (e) { results.textContent = e.message; });
      function update() { input.value = ['street', 'zip', 'city'].map(function (k) { return form.elements[k].value; }).join(' ').trim(); }
      ['street', 'zip', 'city'].forEach(function (k) { form.elements[k].addEventListener('input', function () { update(); input.dispatchEvent(new Event('input')); }); });
      button.onclick = function () {
        if (info.public_only && !form.elements.public.checked) { results.textContent = 'Persönliche Orte benötigen einen geeigneten eigenen Adressdienst. Die Eigenschaft „Öffentlicher Ort“ gilt für den gespeicherten Ort.'; return; }
        update(); run();
      };
    });
  }).catch(function () {});
}());
