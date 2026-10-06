// Planer: Buchungen per Drag & Drop auf einen anderen Tag bzw. eine andere Ressource verschieben.
(function () {
  'use strict';
  var table = document.getElementById('planner');
  if (!table || !window.bootstrap) return;
  var modalEl = document.getElementById('move-modal'), modal = bootstrap.Modal.getOrCreateInstance(modalEl);
  var text = document.getElementById('mv-text'), err = document.getElementById('mv-error'), ok = document.getElementById('mv-ok');
  var drag = null, target = null;
  table.addEventListener('dragstart', function (e) {
    var chip = e.target.closest('.res-chip[draggable="true"]');
    if (!chip) return;
    drag = chip;
    chip.classList.add('moving');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', chip.dataset.id);
  });
  table.addEventListener('dragend', function () {
    if (drag) drag.classList.remove('moving');
    table.querySelectorAll('.res-drop').forEach(function (td) { td.classList.remove('res-drop'); });
  });
  table.addEventListener('dragover', function (e) {
    var td = e.target.closest('td[data-can="1"]');
    if (!drag || !td) return;
    e.preventDefault();
    table.querySelectorAll('.res-drop').forEach(function (x) { if (x !== td) x.classList.remove('res-drop'); });
    td.classList.add('res-drop');
  });
  table.addEventListener('drop', function (e) {
    var td = e.target.closest('td[data-can="1"]');
    if (!drag || !td) return;
    e.preventDefault();
    var from = drag.closest('td');
    if (from === td) return;
    target = td;
    var resName = td.parentElement.querySelector('th a').textContent;
    var d = td.dataset.date.split('-');
    text.textContent = drag.dataset.ref + ' → ' + d[2] + '.' + d[1] + '.' + d[0] + (from.dataset.resource !== td.dataset.resource ? ' · ' + resName : '');
    err.classList.add('d-none');
    ok.disabled = false;
    modal.show();
  });
  ok.addEventListener('click', function () {
    if (!drag || !target) return;
    ok.disabled = true;
    var body = new FormData();
    body.append('csrf', table.dataset.csrf);
    body.append('date', target.dataset.date);
    body.append('resource', target.dataset.resource);
    body.append('notify', document.getElementById('mv-notify').checked ? '1' : '0');
    body.append('keep_price', document.getElementById('mv-keep').checked ? '1' : '0');
    body.append('reason', document.getElementById('mv-reason').value);
    fetch('/resources/bookings/' + drag.dataset.id + '/move', { method: 'POST', body: body, credentials: 'same-origin' })
      .then(function (r) { return r.json(); }).then(function (res) {
        if (res.ok) { location.reload(); return; }
        err.textContent = res.error || 'Nicht möglich.';
        err.classList.remove('d-none');
        ok.disabled = false;
      }).catch(function () { err.textContent = 'Verbindung fehlgeschlagen.'; err.classList.remove('d-none'); ok.disabled = false; });
  });
})();
