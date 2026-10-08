// Startseite: Kacheln anpassen (Reihenfolge per Ziehen, aus-/einblenden), wird sofort gespeichert.
(function () {
  var grid = document.getElementById('dash-tiles');
  var btn = document.getElementById('dash-edit');
  if (!grid || !btn) return;
  var help = document.getElementById('dash-help');
  var meta = document.querySelector('meta[name="csrf"]');
  var csrf = meta ? meta.getAttribute('content') : '';
  var sortable = null, editing = false, changed = false, failed = false;
  var status = document.getElementById('dash-save-status');
  var saveQueue = Promise.resolve();
  var retry = document.getElementById('dash-retry');

  function tiles() { return Array.prototype.slice.call(grid.querySelectorAll('.dash-tile')); }

  function save() {
    var body = new URLSearchParams();
    body.set('csrf', csrf);
    body.set('order', tiles().map(function (t) { return t.dataset.key; }).join(','));
    body.set('hidden', tiles().filter(function (t) { return t.classList.contains('is-hidden'); })
      .map(function (t) { return t.dataset.key; }).join(','));
    if (status) status.textContent = 'Einstellungen werden gespeichert …';
    saveQueue = saveQueue.then(function () {
      return fetch('/dashboard/layout', { method: 'POST', body: body, credentials: 'same-origin',
        headers: { 'X-CSRF-Token': csrf } }).then(function (response) {
          if (!response.ok) throw new Error('save');
          changed = true;
          failed = false;
          if (retry) retry.classList.add('d-none');
          if (status) status.textContent = 'Einstellungen gespeichert.';
        }).catch(function () {
          failed = true;
          if (retry) retry.classList.remove('d-none');
          if (status) status.textContent = 'Speichern fehlgeschlagen. Ihre Auswahl bleibt auf dieser Seite erhalten; bitte wiederholen Sie das Speichern.';
        });
    });
  }

  function setEditing(on) {
    editing = on;
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.innerHTML = on ? '<i class="fa-solid fa-check me-1"></i>Fertig' : '<i class="fa-solid fa-sliders me-1"></i>Anpassen';
    btn.classList.toggle('btn-primary', on);
    btn.classList.toggle('btn-outline-secondary', !on);
    grid.classList.toggle('dash-editing', on);
    if (help) help.classList.toggle('d-none', !on);
    grid.querySelectorAll('.dash-handle, .dash-toggle, .dash-move').forEach(function (el) { el.classList.toggle('d-none', !on); });
    if (on && window.Sortable && !sortable) {
      sortable = Sortable.create(grid, { handle: '.dash-handle', animation: 150, onEnd: save });
    }
    if (sortable) sortable.option('disabled', !on);
    // Wieder eingeblendete Kacheln brauchen ihre Daten: nach dem Bearbeiten neu laden.
    if (!on) {
      btn.disabled = true;
      saveQueue.then(function () {
        btn.disabled = false;
        if (changed && !failed) window.location.reload();
      });
    }
  }

  if (retry) retry.addEventListener('click', function () {
    save();
    saveQueue.then(function () { if (!editing && !failed) window.location.reload(); });
  });

  btn.addEventListener('click', function () { setEditing(!editing); });
  grid.addEventListener('click', function (e) {
    var move = e.target.closest('[data-dash-move]');
    if (move) {
      var current = move.closest('.dash-tile');
      var neighbor = move.dataset.dashMove === 'up' ? current.previousElementSibling : current.nextElementSibling;
      if (neighbor) {
        if (move.dataset.dashMove === 'up') grid.insertBefore(current, neighbor);
        else grid.insertBefore(neighbor, current);
        move.focus();
        save();
      }
      return;
    }
    var tog = e.target.closest('.dash-toggle');
    if (!tog) return;
    var tile = tog.closest('.dash-tile');
    var hidden = tile.classList.toggle('is-hidden');
    var icon = tog.querySelector('i');
    if (icon) { icon.classList.toggle('fa-eye', hidden); icon.classList.toggle('fa-eye-slash', !hidden); }
    save();
  });
})();
