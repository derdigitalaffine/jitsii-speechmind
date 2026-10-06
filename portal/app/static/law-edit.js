// Rechtstext bearbeiten: geteilte Ansicht mit Live-Vorschau, erkannte Gliederung mit Hinweisen, Werkzeugleiste
// (Abschnitt, § mit fortlaufender Nummer, Absatz), Word/PDF laden, Warnung bei ungespeicherten Änderungen.
(function () {
  'use strict';
  var form = document.getElementById('law-form');
  if (!form) return;
  var text = document.getElementById('body_md');
  var box = document.getElementById('law-toc');
  var prev = document.getElementById('law-preview');
  var status = document.getElementById('law-status');
  var file = document.getElementById('law-file');
  var split = form.querySelector('.law-split');
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }

  // --- Ansicht ---------------------------------------------------------------------------------
  function view(mode) {
    split.querySelector('.law-src').classList.toggle('d-none', mode === 'preview');
    split.querySelector('.law-prev').classList.toggle('d-none', mode === 'edit');
    try { localStorage.setItem('law-view', mode); } catch (e) { /* privat */ }
  }
  var saved = 'split';
  try { saved = localStorage.getItem('law-view') || 'split'; } catch (e) { saved = 'split'; }
  if (window.matchMedia('(max-width: 991.98px)').matches && saved === 'split') saved = 'edit';
  var radio = document.querySelector('input[name="law-view"][value="' + saved + '"]');
  if (radio) radio.checked = true;
  view(saved);
  document.querySelectorAll('input[name="law-view"]').forEach(function (r) { r.addEventListener('change', function () { view(r.value); if (r.value !== 'edit') check(false); }); });

  // --- Stammdaten aus dem Kopf: Formularfelder gleich mitfüllen (beim Speichern gilt ohnehin der Kopf) --------
  function fillMeta(meta) {
    var on = document.getElementById('read_meta');
    if (!on || !on.checked) return;
    Object.keys(meta).forEach(function (k) {
      var el = form.querySelector('[name="' + k + '"]');
      if (!el) return;
      if (el.type === 'checkbox') el.checked = meta[k] === '1';
      else if (el.value !== meta[k]) el.value = meta[k];
    });
  }
  var insertBtn = document.getElementById('law-insert-template');
  if (insertBtn) insertBtn.addEventListener('click', function () {
    if (text.value.trim() && !window.confirm('Den vorhandenen Text durch das Muster ersetzen?')) return;
    fetch('/laws/muster.md', { credentials: 'same-origin' }).then(function (r) { return r.text(); }).then(function (t) {
      text.value = t; dirty = true; check(false);
    });
  });
  var promptBox = document.getElementById('law-prompt-box');
  if (promptBox) promptBox.addEventListener('show.bs.collapse', function () {
    var ta = document.getElementById('law-prompt');
    if (ta.value) return;
    fetch('/laws/prompt.txt', { credentials: 'same-origin' }).then(function (r) { return r.text(); }).then(function (t) { ta.value = t; });
  });

  // --- Vorschau und Gliederung --------------------------------------------------------------
  var timer = null, seq = 0;
  function check(withFile) {
    var my = ++seq;
    var body = new FormData();
    body.append('csrf', form.querySelector('[name=csrf]').value);
    body.append('body_md', text.value);
    body.append('html', '1');
    if (withFile && file.files.length) body.append('file', file.files[0]);
    if (status) status.textContent = 'prüfe …';
    fetch('/laws/preview', { method: 'POST', body: body, headers: { 'X-Requested-With': 'fetch' }, credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (my !== seq) return;
        if (!d.ok) { box.innerHTML = '<div class="text-danger">' + esc(d.error) + '</div>'; if (status) status.textContent = ''; return; }
        if (d.body_md !== null && d.body_md !== undefined) {
          text.value = d.body_md; file.value = ''; dirty = true;
          document.getElementById('law-file-note').textContent = 'Datei ins Textfeld übernommen – bitte prüfen und speichern.';
        }
        var title = document.getElementById('title');
        if (d.title && !title.value) title.placeholder = d.title;
        var metaHtml = '';
        var metaKeys = Object.keys(d.meta || {});
        if (metaKeys.length || (d.meta_notes && d.meta_notes.length)) {
          metaHtml = '<div class="border rounded p-2 mb-2 bg-body-tertiary"><div class="fw-semibold mb-1"><i class="fa-solid fa-tags me-1"></i>Stammdaten im Kopf erkannt</div>' +
            (metaKeys.length ? '<dl class="row mb-1 small">' + metaKeys.map(function (k) { return '<dt class="col-5 fw-normal text-secondary">' + esc(k) + '</dt><dd class="col-7 mb-0">' + esc(d.meta[k] || '–') + '</dd>'; }).join('') + '</dl>' : '') +
            (d.meta_notes && d.meta_notes.length ? '<ul class="mb-0 ps-3 text-warning-emphasis small">' + d.meta_notes.map(function (w) { return '<li>' + esc(w) + '</li>'; }).join('') + '</ul>' : '') + '</div>';
          fillMeta(d.meta_raw || {});
        }
        var html = metaHtml + '<div class="mb-2">' + (d.title ? 'Titel: <strong>' + esc(d.title) + '</strong><br>' : '') +
          '<span class="badge text-bg-primary">' + d.norms + ' §§ / Artikel</span> <span class="badge text-bg-secondary">' + d.groups + ' Gliederungseinheiten</span></div>';
        if (d.warnings && d.warnings.length) {
          html += '<div class="alert alert-warning py-1 px-2 small mb-2"><ul class="mb-0 ps-3">' + d.warnings.map(function (w) { return '<li>' + esc(w) + '</li>'; }).join('') + '</ul></div>';
        }
        html += '<ul class="list-unstyled mb-0" style="max-height: 28rem; overflow:auto">';
        d.toc.forEach(function (n) {
          var icon = n.kind === 'norm' ? 'fa-section' : (n.kind === 'intro' ? 'fa-feather-pointed' : 'fa-folder-open');
          html += '<li style="padding-left:' + (n.depth * 1.1) + 'rem"' + (n.kind === 'group' ? ' class="fw-semibold mt-1"' : '') + '><a class="text-reset text-decoration-none" href="#pv-' + esc(n.anchor) + '"><i class="fa-solid ' + icon + ' fa-fw text-secondary me-1"></i>' + esc(n.label) + '</a>' +
            (n.kind !== 'group' && !n.chars ? ' <span class="badge text-bg-warning">leer</span>' : '') + '</li>';
        });
        box.innerHTML = html + '</ul>';
        // Vorschau: die Abschnitte wie auf der öffentlichen Seite (HTML kommt aus Markdown ohne eingebettetes HTML)
        prev.innerHTML = (d.title ? '<h2 class="h5 text-center mb-3">' + esc(d.title) + '</h2>' : '') + d.toc.map(function (n) {
          var head = n.kind === 'intro' ? '' : '<div class="lex-head" style="margin-top:1.2rem"><span class="lex-nr">' + esc(n.label) + '</span></div>';
          return '<section class="lex-unit lex-' + n.kind + '" id="pv-' + esc(n.anchor) + '">' + head + (n.html || '') + '</section>';
        }).join('') || '<p class="text-secondary">Noch kein Text.</p>';
        if (status) status.textContent = d.norms + ' §§ · ' + (d.warnings && d.warnings.length ? d.warnings.length + ' Hinweis(e)' : 'keine Hinweise');
      })
      .catch(function () { box.innerHTML = '<div class="text-danger">Prüfung fehlgeschlagen.</div>'; });
  }
  text.addEventListener('input', function () { dirty = true; clearTimeout(timer); timer = setTimeout(function () { check(false); }, 600); });
  file.addEventListener('change', function () { if (file.files.length) check(true); });
  box.addEventListener('click', function (e) {
    var a = e.target.closest('a[href^="#pv-"]');
    if (!a) return;
    e.preventDefault();
    var el = document.getElementById(a.getAttribute('href').slice(1));
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  // --- Werkzeugleiste ------------------------------------------------------------------------
  function nextNorm(before) {
    var nums = before.match(/(?:^|\n)\s*#*\s*§\s*(\d+)/g) || [];
    var last = nums.length ? parseInt(nums[nums.length - 1].replace(/\D+/g, ''), 10) : 0;
    return last + 1;
  }
  function nextAbs(before) {
    var lastNorm = before.lastIndexOf('§');
    var tail = lastNorm >= 0 ? before.slice(lastNorm) : before;
    var m = tail.match(/(?:^|\n)\((\d+)\)/g) || [];
    return m.length ? parseInt(m[m.length - 1].replace(/\D+/g, ''), 10) + 1 : 1;
  }
  document.querySelectorAll('.law-toolbar [data-insert], .law-toolbar [data-wrap]').forEach(function (b) {
    b.addEventListener('click', function () {
      var s = text.selectionStart, e = text.selectionEnd, before = text.value.slice(0, s);
      var ins;
      if (b.dataset.wrap) {
        ins = b.dataset.wrap + (text.value.slice(s, e) || 'Text') + b.dataset.wrap;
      } else {
        ins = b.dataset.insert.replace(/\\n/g, '\n').replace('{n}', nextNorm(before)).replace('{a}', nextAbs(before));
      }
      text.setRangeText(ins, s, e, 'end');
      text.focus();
      text.dispatchEvent(new Event('input'));
    });
  });

  // --- Ungespeichert --------------------------------------------------------------------------
  var dirty = false;
  form.addEventListener('change', function (e) { if (e.target.name !== 'law-view') dirty = true; });
  form.addEventListener('submit', function () { dirty = false; });
  window.addEventListener('beforeunload', function (e) { if (dirty) { e.preventDefault(); e.returnValue = ''; } });

  if (text.value.trim()) check(false);
})();
