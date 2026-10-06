// Fotos einer Ressource verwalten, ohne die Seite zu verlassen: mehrere Fotos auf einmal hochladen (Ziehen oder
// Auswählen, mit Fortschritt), Reihenfolge per Ziehen oder Pfeiltasten, erstes Foto = Titelbild, Bildunterschrift,
// Löschen. Alles läuft per fetch – ungespeicherte Änderungen in den anderen Reitern bleiben erhalten.
(function () {
  'use strict';
  var box = document.getElementById('res-photos');
  var list = document.getElementById('ph-list');
  if (!box || !list || !window.fetch) return;
  var base = box.dataset.base, csrf = box.dataset.csrf, max = +box.dataset.max || 40;
  var input = document.getElementById('ph-file'), drop = document.getElementById('ph-drop');
  var progress = document.getElementById('ph-progress');
  var photos = [];
  try { photos = JSON.parse(document.getElementById('ph-data').textContent) || []; } catch (e) { photos = []; }

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function say(html, kind) { progress.innerHTML = html ? '<span class="' + (kind === 'error' ? 'text-danger' : kind === 'ok' ? 'text-success' : 'text-secondary') + '">' + html + '</span>' : ''; }

  function post(url, data) {
    var fd = data instanceof FormData ? data : new FormData();
    if (!(data instanceof FormData)) Object.keys(data || {}).forEach(function (k) { fd.append(k, data[k]); });
    fd.append('csrf', csrf);
    return fetch(url, { method: 'POST', body: fd, credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }
  function apply(d) { if (d && d.photos) { photos = d.photos; render(); } return d; }

  function render() {
    list.innerHTML = photos.map(function (p, i) {
      return '<li class="res-photo-item" draggable="true" data-id="' + p.id + '">' +
        '<div class="res-photo-thumb"><img src="' + esc(p.thumb) + '" alt="" loading="lazy">' +
        (i === 0 ? '<span class="badge text-bg-primary res-photo-badge"><i class="fa-solid fa-star me-1"></i>Titelbild</span>' : '') + '</div>' +
        '<div class="res-photo-body">' +
        '<label class="visually-hidden" for="ph-cap-' + p.id + '">Bildunterschrift Foto ' + (i + 1) + '</label>' +
        '<input class="form-control form-control-sm js-cap" id="ph-cap-' + p.id + '" maxlength="300" placeholder="Bildunterschrift (optional)" value="' + esc(p.caption) + '">' +
        '<div class="d-flex flex-wrap gap-1 mt-1 align-items-center">' +
        '<button type="button" class="btn btn-sm btn-light js-move" data-dir="-1" ' + (i === 0 ? 'disabled' : '') + ' aria-label="Foto ' + (i + 1) + ' nach vorn"><i class="fa-solid fa-arrow-left"></i></button>' +
        '<button type="button" class="btn btn-sm btn-light js-move" data-dir="1" ' + (i === photos.length - 1 ? 'disabled' : '') + ' aria-label="Foto ' + (i + 1) + ' nach hinten"><i class="fa-solid fa-arrow-right"></i></button>' +
        (i > 0 ? '<button type="button" class="btn btn-sm btn-light js-cover"><i class="fa-regular fa-star me-1"></i>Titelbild</button>' : '') +
        '<button type="button" class="btn btn-sm btn-link text-danger ms-auto js-del" aria-label="Foto ' + (i + 1) + ' löschen"><i class="fa-regular fa-trash-can"></i></button>' +
        '</div></div></li>';
    }).join('');
    if (!photos.length) list.innerHTML = '<li class="text-secondary small">Noch keine Fotos.</li>';
  }

  // --- Hochladen: eine Datei je Anfrage (Fortschritt, große Handyfotos, keine Größengrenze der Gesamtanfrage) ---
  function upload(files) {
    files = Array.prototype.filter.call(files, function (f) { return /^image\/(jpeg|png|webp)$/.test(f.type) || /\.(jpe?g|png|webp)$/i.test(f.name); });
    if (!files.length) { say('Bitte JPG-, PNG- oder WebP-Dateien wählen.', 'error'); return; }
    var done = 0, added = 0, problems = [];
    function next() {
      if (done >= files.length) {
        say((added ? added + ' Foto' + (added === 1 ? '' : 's') + ' hinzugefügt.' : '') +
          (problems.length ? ' <br>Übersprungen: ' + problems.map(esc).join('<br>') : ''), problems.length ? 'error' : 'ok');
        input.value = '';
        return;
      }
      var f = files[done];
      say('<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Foto ' + (done + 1) + ' von ' + files.length + ' wird hochgeladen und verkleinert …');
      var fd = new FormData();
      fd.append('photos', f, f.name);
      post(base, fd).then(function (d) {
        apply(d); added += d.added || 0; problems = problems.concat(d.skipped || []);
      }).catch(function () { problems.push('„' + f.name + '“: Hochladen fehlgeschlagen'); })
        .then(function () { done++; next(); });
    }
    if (photos.length + files.length > max) say('Höchstens ' + max + ' Fotos je Ressource – überzählige werden übersprungen.', 'error');
    next();
  }
  input.addEventListener('change', function () { upload(input.files); });
  ['dragenter', 'dragover'].forEach(function (t) {
    drop.addEventListener(t, function (e) { if (e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types, 'Files') >= 0) { e.preventDefault(); drop.classList.add('is-over'); } });
  });
  ['dragleave', 'drop'].forEach(function (t) { drop.addEventListener(t, function () { drop.classList.remove('is-over'); }); });
  drop.addEventListener('drop', function (e) { if (e.dataTransfer && e.dataTransfer.files.length) { e.preventDefault(); upload(e.dataTransfer.files); } });

  // --- Reihenfolge, Titelbild, Löschen, Bildunterschrift ---------------------------------------------
  function saveOrder(ids, focusId, focusSel) {
    return post(base + '/order', { ids: ids.join(',') }).then(apply).then(function () {
      var li = list.querySelector('[data-id="' + focusId + '"]'), el = li && li.querySelector(focusSel);
      if (el && !el.disabled) el.focus(); else if (li) { var any = li.querySelector('button:not([disabled])'); if (any) any.focus(); }
    }).catch(function () { say('Reihenfolge konnte nicht gespeichert werden.', 'error'); });
  }
  function ids() { return photos.map(function (p) { return p.id; }); }
  list.addEventListener('click', function (e) {
    var li = e.target.closest('.res-photo-item'); if (!li) return;
    var id = +li.dataset.id, order = ids(), i = order.indexOf(id);
    if (e.target.closest('.js-move')) {
      var btn = e.target.closest('.js-move'), j = i + (+btn.dataset.dir);
      if (j < 0 || j >= order.length) return;
      order.splice(i, 1); order.splice(j, 0, id);
      saveOrder(order, id, '.js-move[data-dir="' + btn.dataset.dir + '"]');
    } else if (e.target.closest('.js-cover')) {
      order.splice(i, 1); order.unshift(id);
      saveOrder(order, id, '.js-move').then(function () { say('Titelbild geändert.', 'ok'); });
    } else if (e.target.closest('.js-del')) {
      var go = function () {
        post(base + '/' + id + '/delete', {}).then(apply).then(function () { say('Foto gelöscht.', 'ok'); })
          .catch(function () { say('Löschen fehlgeschlagen.', 'error'); });
      };
      if (window.Swal) {
        Swal.fire({ title: 'Foto löschen?', icon: 'warning', showCancelButton: true, confirmButtonText: 'Löschen', cancelButtonText: 'Abbrechen',
          reverseButtons: true, buttonsStyling: false, customClass: { confirmButton: 'btn btn-danger ms-2', cancelButton: 'btn btn-outline-secondary' } })
          .then(function (r) { if (r.isConfirmed) go(); });
      } else if (window.confirm('Foto löschen?')) go();
    }
  });
  list.addEventListener('change', function (e) {
    if (!e.target.classList.contains('js-cap')) return;
    var li = e.target.closest('.res-photo-item'), field = e.target;
    post(base + '/' + li.dataset.id + '/caption', { caption: field.value }).then(function (d) {
      photos = d.photos || photos;
      field.classList.add('is-valid'); setTimeout(function () { field.classList.remove('is-valid'); }, 1200);
    }).catch(function () { field.classList.add('is-invalid'); });
  });
  list.addEventListener('keydown', function (e) { if (e.key === 'Enter' && e.target.classList.contains('js-cap')) { e.preventDefault(); e.target.blur(); } });

  // Ziehen mit der Maus
  var dragId = null;
  list.addEventListener('dragstart', function (e) {
    var li = e.target.closest && e.target.closest('.res-photo-item');
    if (!li || e.target.closest('input')) return;
    dragId = +li.dataset.id; li.classList.add('is-dragging');
    e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(dragId));
  });
  list.addEventListener('dragover', function (e) {
    if (dragId == null) return;
    e.preventDefault();
    var over = e.target.closest('.res-photo-item'), dragged = list.querySelector('.is-dragging');
    if (!over || !dragged || over === dragged) return;
    var r = over.getBoundingClientRect(), after = (e.clientX - r.left) > r.width / 2;
    list.insertBefore(dragged, after ? over.nextSibling : over);
  });
  list.addEventListener('dragend', function () {
    if (dragId == null) return;
    var order = Array.prototype.map.call(list.querySelectorAll('.res-photo-item'), function (li) { return +li.dataset.id; });
    var id = dragId; dragId = null;
    if (order.join() !== ids().join()) saveOrder(order, id, '.js-move'); else render();
  });

  render();
})();
