/* Isolated preview, using the same server palette as the rendered portal. */
(function () {
  'use strict';
  var form = document.getElementById('design-form');
  if (!form) return;
  var frame = document.getElementById('design-preview'), values = document.getElementById('contrast-values');
  var ack = document.getElementById('contrast-ack'), summary = document.getElementById('contrast-summary');
  var suggest = document.getElementById('contrast-suggest'), theme = 'light', cached, key = '', timer, generation = 0, cachedKey = '', logo = frame.dataset.logo || '', blob;
  function escape(s) { return String(s).replace(/[&<>"']/g, function (c) { return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]; }); }
  function preview() {
    if (!cached) return;
    var name = form.elements.ui_brand_name.value || frame.dataset.brand;
    var product = form.elements.ui_product.value || frame.dataset.product;
    var height = Math.max(20, Math.min(80, Number(form.elements.ui_logo_height.value) || 32));
    var visibleLogo = form.elements.remove_logo && form.elements.remove_logo.checked ? '' : logo;
    var brandMarkup = (visibleLogo ? '<img alt="" src="'+escape(visibleLogo)+'" style="height:'+height+'px;max-width:160px">' : '') + (form.elements.ui_show_name.checked || !visibleLogo ? '<span>'+escape(name)+'<small>'+escape(product)+'</small></span>' : '');
    var radius = form.elements.ui_radius.value;
    if (!/^(0|0\.375rem|0\.75rem)$/.test(radius)) radius = '.375rem';
    frame.srcdoc = '<!doctype html><html lang="de" data-bs-theme="'+theme+'"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/static/vendor/bootstrap/bootstrap.min.css"><link rel="stylesheet" href="/static/app.css"><style>'+cached.css+' .btn,.form-control {border-radius:'+radius+'} body {display:block;min-height:0} .app-sidebar {position:static;height:auto;border:0} .preview-focus {outline:3px solid var(--app-focus);outline-offset:3px}</style></head><body><nav class="app-navbar p-3" aria-label="Vorschau-Kopfzeile"><a class="navbar-brand" aria-label="'+escape(name)+'" href="#preview-content">'+brandMarkup+'</a><a class="nav-link" href="#preview-content">Zum Formular</a></nav><main id="preview-content" class="p-3"><div class="app-sidebar"><a class="nav-link active mb-3" href="#preview-field" aria-current="page">Aktive Navigation</a></div><p>Weitere Informationen stehen <a href="#preview-field">in diesem Link</a>.</p><button type="button" class="btn btn-primary preview-focus me-2 mb-3">Primäraktion mit Fokus</button><span class="badge text-bg-primary">Ausgewählt</span><label class="form-label d-block" for="preview-field">Name</label><input id="preview-field" class="form-control is-invalid" aria-invalid="true" aria-describedby="preview-error"><div id="preview-error" class="invalid-feedback d-block">Bitte einen Namen eingeben.</div><div class="form-check mt-3"><input class="form-check-input" id="preview-check" type="checkbox" checked><label class="form-check-label" for="preview-check">Bestätigung</label></div></main></body></html>';
  }
  function show(result, resultKey) {
    cachedKey = resultKey; cached = result; preview();
    values.replaceChildren();
    result.report.rows.forEach(function (r) {
      var line = document.createElement('div'); line.className = 'small mb-2';
      line.textContent = (r.theme === 'light' ? 'Hell' : 'Dunkel')+' · '+r.label+': '+r.ratio.toFixed(2)+':1 – '+r.rating;
      if (!r.ok) line.classList.add('fw-bold');
      values.appendChild(line);
    });
    var warnings = result.report.warnings.length;
    summary.textContent = warnings ? warnings+' Kontrastwarnungen: Die markierten Elemente sind schlechter lesbar. Farbe anpassen oder bewusst bestätigen.' : 'Alle geprüften Farbkontraste erfüllen die Mindestwerte.';
    document.getElementById('contrast-confirm').hidden = !warnings;
    suggest.hidden = !warnings || !result.report.suggestion;
    suggest.dataset.color = result.report.suggestion || '';
    if (!suggest.hidden) suggest.textContent = 'Ähnliche besser lesbare Farbe '+result.report.suggestion+' übernehmen';
  }
  function refresh() {
    var p = form.elements.ui_primary.value.toLowerCase(), nav = form.elements.ui_navbar.value, next = p+'|'+nav;
    if (next !== key) { ack.checked = false; key = next; }
    form.elements.contrast_key.value = next;
    var own = ++generation;
    clearTimeout(timer);
    if (!/^#[0-9a-f]{6}$/.test(p)) { summary.textContent = 'Bitte eine gültige Hauptfarbe eingeben.'; return; }
    timer = setTimeout(function () {
      fetch('/admin/design/contrast?'+new URLSearchParams({primary:p,navbar:nav}), {credentials:'same-origin'})
        .then(function (r) { if (!r.ok) throw Error(); return r.json(); })
        .then(function (r) { if (own === generation) show(r, next); })
        .catch(function () { if (own === generation) summary.textContent = 'Liveprüfung derzeit nicht erreichbar. Beim Speichern wird das Design erneut geprüft.'; });
    }, 150);
  }
  function change(ev) {
    if (['ui_primary','ui_navbar','ui_theme','ui_radius','ui_logo_height','ui_show_name','logo','favicon','ui_jitsi'].includes(ev.target.name) && !form.elements.ui_custom.checked) {
      form.elements.ui_custom.checked = true; document.getElementById('design-autoenabled').hidden = false;
    }
    if (['ui_primary','ui_navbar'].includes(ev.target.name)) refresh(); else preview();
  }
  if (form.elements.logo) form.elements.logo.addEventListener('change', function () {
    if (blob) URL.revokeObjectURL(blob);
    blob = form.elements.logo.files[0] ? URL.createObjectURL(form.elements.logo.files[0]) : null;
    logo = blob || frame.dataset.logo || ''; preview();
  });
  form.addEventListener('input', change); form.addEventListener('change', change);
  document.addEventListener('coloris:pick', refresh);
  document.querySelectorAll('[data-preview-theme]').forEach(function (button) {
    button.addEventListener('click', function () { theme = button.dataset.previewTheme; document.querySelectorAll('[data-preview-theme]').forEach(function(b) {b.setAttribute('aria-pressed',String(b === button));}); preview(); });
  });
  suggest.addEventListener('click', function () { form.elements.ui_primary.value = suggest.dataset.color; form.elements.ui_primary.dispatchEvent(new Event('input',{bubbles:true})); });
  form.addEventListener('submit', function (ev) {
    if (form.elements.ui_custom.checked && cached && cachedKey === key && cached.report.warnings.length && !ack.checked) {
      ev.preventDefault(); summary.textContent = 'Bitte Kontrastwarnungen prüfen und ausdrücklich bestätigen, oder eine besser lesbare Hauptfarbe wählen.'; ack.focus();
    }
  });
  refresh();
})();
