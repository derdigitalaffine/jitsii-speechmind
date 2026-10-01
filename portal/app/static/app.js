/* Oberfläche des Portals: Tabellen, Dialoge, Eingabehilfen.
   Verwendet die lokal mitgelieferten Bibliotheken unter /static/vendor. */
(function () {
  'use strict';
  var $ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  /* ---- Hell/Dunkel ---------------------------------------------------- */
  function applyTheme(mode) {
    var t = mode === 'auto' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : mode;
    document.documentElement.setAttribute('data-bs-theme', t);
  }
  $('[data-theme-set]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var mode = btn.dataset.themeSet;
      try { localStorage.setItem('theme', mode); } catch (e) { /* privater Modus */ }
      applyTheme(mode);
    });
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () {
    var saved = null;
    try { saved = localStorage.getItem('theme'); } catch (e) { /* ignorieren */ }
    if ((saved || document.documentElement.dataset.defaultTheme) === 'auto') applyTheme('auto');
  });

  /* ---- Bestätigungsdialoge (SweetAlert2) ------------------------------ */
  document.addEventListener('click', function (ev) {
    var el = ev.target.closest('[data-confirm]');
    if (!el || el.dataset.confirmed) { return; }
    ev.preventDefault();
    var form = el.form || el.closest('form');
    Swal.fire({
      title: el.dataset.confirmTitle || 'Sind Sie sicher?',
      text: el.dataset.confirm,
      icon: 'warning',
      showCancelButton: true,
      confirmButtonText: el.dataset.confirmButton || 'Ja, ausführen',
      cancelButtonText: 'Abbrechen',
      reverseButtons: true,
      buttonsStyling: false,
      customClass: { confirmButton: 'btn btn-danger ms-2', cancelButton: 'btn btn-outline-secondary' }
    }).then(function (res) {
      if (res.isConfirmed && form) { el.dataset.confirmed = '1'; form.requestSubmit(el); }
    });
  }, true);

  /* ---- Tabellen (DataTables) ------------------------------------------ */
  var DE = {
    search: '', searchPlaceholder: 'Suchen …', lengthMenu: '_MENU_ pro Seite',
    info: '_START_–_END_ von _TOTAL_', infoEmpty: 'Keine Einträge', infoFiltered: '(gefiltert aus _MAX_)',
    zeroRecords: 'Keine passenden Einträge gefunden', emptyTable: 'Noch keine Einträge',
    paginate: { first: '«', previous: '‹', next: '›', last: '»' }
  };
  $('table.js-table').forEach(function (table) {
    var heads = $('thead th', table);
    var plain = [];
    heads.forEach(function (th, i) { if (th.classList.contains('no-sort')) { plain.push(i); } });
    var order = [];
    try { order = JSON.parse(table.dataset.order || '[]'); } catch (e) { order = []; }
    table.dtApi = new DataTable(table, {
      language: DE,
      responsive: true,
      stateSave: true,
      order: order,
      pageLength: parseInt(table.dataset.pageLength || '10', 10),
      lengthMenu: [10, 25, 50, 100],
      columnDefs: [{ targets: plain, orderable: false, searchable: false }],
      layout: {
        topStart: 'search', topEnd: 'pageLength',
        bottomStart: 'info', bottomEnd: 'paging'
      }
    });
  });

  /* ---- Aufnahmen löschen (einzeln und mehrere) ---------------------- */
  var csrfToken = (document.querySelector('meta[name="csrf"]') || {}).content || '';
  var DELETE_OPTIONS = {
    media: 'Nur Video und MP3 löschen, <strong>Transkript und Chatprotokoll behalten</strong>',
    keep_link: 'Alles hier löschen, Protokoll <strong>bei SpeechMind später wieder abrufbar</strong>',
    all: '<strong>Alles löschen</strong> (Video, MP3, Transkript, Chatprotokoll)'
  };
  function postForm(url, fields) {
    var f = document.createElement('form');
    f.method = 'post'; f.action = url; f.hidden = true;
    fields.push(['csrf', csrfToken]);
    fields.forEach(function (kv) {
      var i = document.createElement('input'); i.type = 'hidden'; i.name = kv[0]; i.value = kv[1]; f.appendChild(i);
    });
    document.body.appendChild(f); f.submit();
  }
  function askDeleteMode(title, keys, text) {
    var html = '<div class="text-start">' + (text ? '<p class="small text-secondary">' + text + '</p>' : '') +
      keys.map(function (k, i) {
        return '<div class="form-check mb-2"><input class="form-check-input" type="radio" name="dmode" id="dm-' + k +
          '" value="' + k + '"' + (i === 0 ? ' checked' : '') + '><label class="form-check-label" for="dm-' + k + '">' +
          DELETE_OPTIONS[k] + '</label></div>';
      }).join('') + '</div>';
    return Swal.fire({
      title: title, html: html, icon: 'warning', showCancelButton: true,
      confirmButtonText: 'Löschen', cancelButtonText: 'Abbrechen', reverseButtons: true, buttonsStyling: false,
      customClass: { confirmButton: 'btn btn-danger ms-2', cancelButton: 'btn btn-outline-secondary' },
      preConfirm: function () {
        var c = Swal.getPopup().querySelector('input[name="dmode"]:checked');
        return c ? c.value : 'all';
      }
    });
  }
  document.addEventListener('click', function (ev) {
    var btn = ev.target.closest('[data-delete-url]');
    if (!btn) { return; }
    var keys = [];
    if (btn.dataset.hasTranscript === '1' || btn.dataset.hasLink === '1') {
      if (btn.dataset.hasMedia === '1') { keys.push('media'); }
    }
    if (btn.dataset.hasLink === '1') { keys.push('keep_link'); }
    keys.push('all');
    askDeleteMode(btn.dataset.title + ' löschen?', keys,
      keys.length === 1 ? 'Video, MP3 und Transkript werden vom Server gelöscht.' : 'Was soll gelöscht werden?')
      .then(function (res) { if (res.isConfirmed) { postForm(btn.dataset.deleteUrl, [['mode', res.value]]); } });
  });
  $('[data-bulk-delete]').forEach(function (btn) {
    var table = document.querySelector(btn.dataset.bulkDelete);
    if (!table) { return; }
    var rows = function () { return table.dtApi ? table.dtApi.rows().nodes().toArray() : $('tbody tr', table); };
    var checked = function () {
      var ids = [];
      rows().forEach(function (tr) { var c = tr.querySelector('[data-select]'); if (c && c.checked) { ids.push(c.value); } });
      return ids;
    };
    var update = function () {
      var n = checked().length;
      btn.disabled = n === 0;
      btn.querySelector('[data-bulk-count]').textContent = n;
    };
    table.addEventListener('change', function (ev) {
      if (ev.target.matches('[data-select-all]')) {
        var nodes = table.dtApi ? table.dtApi.rows({ search: 'applied' }).nodes().toArray() : rows();
        nodes.forEach(function (tr) { var c = tr.querySelector('[data-select]'); if (c && !c.disabled) { c.checked = ev.target.checked; } });
      }
      update();
    });
    btn.addEventListener('click', function () {
      var ids = checked();
      if (!ids.length) { return; }
      askDeleteMode(ids.length + ' Aufnahme(n) löschen?', ['media', 'keep_link', 'all'],
        'Gilt für jede ausgewählte Aufnahme, soweit möglich. Was danach nichts mehr enthält, wird ganz entfernt.')
        .then(function (res) {
          if (!res.isConfirmed) { return; }
          postForm('/recordings/bulk-delete', ids.map(function (id) { return ['ids', id]; })
            .concat([['mode', res.value], ['next', location.pathname]]));
        });
    });
    update();
  });

  /* ---- E-Mail-Vorlagen: Platzhalter einfügen, Live-Vorschau ---------- */
  var sampleEl = document.getElementById('tpl-sample');
  if (sampleEl) {
    var sample = {};
    try { sample = JSON.parse(sampleEl.textContent); } catch (e) { sample = {}; }
    var fill = function (text) {
      return text.replace(/\{([a-z_]+)\}/g, function (m, k) { return Object.prototype.hasOwnProperty.call(sample, k) ? sample[k] : m; });
    };
    $('form.js-template').forEach(function (form) {
      var subj = form.elements.subject, body = form.elements.body, last = body;
      var render = function () {
        form.querySelector('.js-preview-subject').textContent = fill(subj.value).replace(/\s+/g, ' ');
        form.querySelector('.js-preview-body').textContent = fill(body.value).replace(/\n{3,}/g, '\n\n');
      };
      [subj, body].forEach(function (el) {
        el.addEventListener('input', render);
        el.addEventListener('focus', function () { last = el; });
      });
      $('[data-insert]', form).forEach(function (btn) {
        btn.addEventListener('click', function () {
          var el = last, start = el.selectionStart || 0, end = el.selectionEnd || 0, text = btn.dataset.insert;
          el.value = el.value.slice(0, start) + text + el.value.slice(end);
          el.focus();
          el.selectionStart = el.selectionEnd = start + text.length;
          render();
        });
      });
      render();
    });
  }

  /* ---- Kopieren ------------------------------------------------------- */
  $('[data-copy]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var field = document.querySelector(btn.dataset.copy);
      if (!field) { return; }
      field.select();
      var done = function () {
        var old = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-check"></i> Kopiert';
        setTimeout(function () { btn.innerHTML = old; }, 2000);
      };
      if (navigator.clipboard) { navigator.clipboard.writeText(field.value).then(done); }
      else { document.execCommand('copy'); done(); }
    });
  });

  /* Text direkt aus dem Attribut kopieren (z. B. Kurzlinks in Tabellen) */
  document.addEventListener('click', function (ev) {
    var btn = ev.target.closest('[data-copy-text]');
    if (!btn) { return; }
    ev.preventDefault();
    var text = btn.dataset.copyText;
    var done = function () {
      var old = btn.innerHTML;
      btn.innerHTML = '<i class="fa-solid fa-check"></i>';
      setTimeout(function () { btn.innerHTML = old; }, 1500);
    };
    if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(text).then(done); return; }
    var ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); done(); } finally { ta.remove(); }
  });

  /* ---- QR-Codes: Vorschau und Download --------------------------------- */
  $('.js-qr').forEach(function (box) {
    var img = box.querySelector('.js-qr-img');
    var textField = box.dataset.qrText ? document.querySelector(box.dataset.qrText) : null;
    var timer = null;
    var url = function (fmt, download) {
      var params = new URLSearchParams();
      $('.js-qr-opt', box).forEach(function (el) { params.set(el.name, el.value); });
      if (textField) { params.set('text', textField.value.trim()); }
      if (download) { params.set('download', '1'); }
      var base = box.dataset.qrUrl.replace('{fmt}', fmt);
      return base + (base.indexOf('?') >= 0 ? '&' : '?') + params.toString();
    };
    var update = function () {
      var empty = textField && !textField.value.trim();
      img.style.visibility = empty ? 'hidden' : 'visible';
      if (!empty) { img.src = url('svg', false); }
      $('.js-qr-dl', box).forEach(function (a) {
        a.classList.toggle('disabled', !!empty);
        a.href = empty ? '#' : url(a.dataset.fmt, true);
      });
      var size = box.querySelector('[name="size"]');
      var px = box.querySelector('.js-qr-px');
      if (size && px) { px.textContent = size.value; }
    };
    var later = function () { clearTimeout(timer); timer = setTimeout(update, 250); };
    $('.js-qr-opt', box).forEach(function (el) { el.addEventListener('input', later); el.addEventListener('change', later); });
    if (textField) { textField.addEventListener('input', later); }
    update();
  });

  /* ---- Passwort anzeigen --------------------------------------------- */
  $('[data-toggle-password]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var input = document.querySelector(btn.dataset.togglePassword);
      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.innerHTML = '<i class="fa-solid ' + (show ? 'fa-eye-slash' : 'fa-eye') + '"></i>';
    });
  });

  /* ---- E-Mail-Adressen als Tags (Tagify) ------------------------------ */
  $('input.js-emails').forEach(function (input) {
    var whitelist = [];
    try { whitelist = JSON.parse(input.dataset.suggest || '[]'); } catch (e) { whitelist = []; }
    new Tagify(input, {
      whitelist: whitelist,
      enforceWhitelist: false,
      pattern: /^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+$/,
      delimiters: ',|;|\\s',
      editTags: 1,
      keepInvalidTags: false,
      trim: true,
      originalInputValueFormat: function (v) { return v.map(function (x) { return x.value; }).join(','); },
      texts: { empty: 'Bitte ausfüllen', pattern: 'Ungültige E-Mail-Adresse', duplicate: 'Schon eingetragen' },
      dropdown: whitelist.length ? {
        enabled: 1, maxItems: 8, searchKeys: ['value', 'name'], closeOnSelect: true,
        mapValueTo: function (item) { return item.name ? item.name + ' <' + item.value + '>' : item.value; }
      } : { enabled: 0 }
    });
  });

  /* ---- Auswahlfelder (Tom Select) ------------------------------------- */
  $('select.js-select').forEach(function (sel) {
    new TomSelect(sel, {
      allowEmptyOption: true,
      create: false,
      controlInput: sel.dataset.search === '1' ? undefined : null,
      plugins: sel.multiple ? ['remove_button'] : [],
      render: { no_results: function () { return '<div class="no-results">Keine Treffer</div>'; } }
    });
  });

  /* ---- Farbwähler (Coloris) ------------------------------------------- */
  if (window.Coloris && $('.js-color').length) {
    Coloris({
      el: '.js-color', themeMode: 'auto', alpha: false, format: 'hex', wrap: true,
      closeButton: true, closeLabel: 'Übernehmen', clearButton: false,
      swatches: ['#1f5fa8', '#0f766e', '#15803d', '#b45309', '#b91c1c', '#7e22ce', '#be185d', '#334155']
    });
  }

  /* ---- Live-Vorschau im Design-Editor --------------------------------- */
  var form = document.getElementById('design-form');
  if (form) {
    var pv = document.getElementById('design-preview');
    var mix = function (hex, t, to) {
      var c = [1, 3, 5].map(function (i) { return parseInt(hex.substr(i, 2), 16); });
      return '#' + c.map(function (v) { return Math.round(v + (to - v) * t).toString(16).padStart(2, '0'); }).join('');
    };
    var lum = function (hex) {
      var c = [1, 3, 5].map(function (i) {
        var v = parseInt(hex.substr(i, 2), 16) / 255;
        return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
      });
      return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    };
    var on = function (hex) { return lum(hex) > 0.33 ? '#000' : '#fff'; };
    var update = function () {
      var p = form.elements.ui_primary.value;
      if (!/^#[0-9a-fA-F]{6}$/.test(p)) { return; }
      var nav = form.elements.ui_navbar.value;
      var navBg = nav === 'primary' ? p : nav === 'dark' ? '#1b2430' : 'var(--bs-tertiary-bg)';
      var navFg = nav === 'light' ? 'var(--bs-body-color)' : on(navBg.charAt(0) === '#' ? navBg : '#ffffff');
      pv.querySelector('.pv-nav').style.background = navBg;
      pv.querySelector('.pv-nav').style.color = navFg;
      var btn = pv.querySelector('.pv-btn');
      btn.style.background = p; btn.style.borderColor = p; btn.style.color = on(p);
      var out = pv.querySelector('.pv-out');
      out.style.color = p; out.style.borderColor = p;
      var r = form.elements.ui_radius.value;
      pv.style.borderRadius = r; btn.style.borderRadius = r; out.style.borderRadius = r;
      var logo = pv.querySelector('.pv-logo');
      if (logo) { logo.style.height = (form.elements.ui_logo_height.value || 32) + 'px'; }
      var name = pv.querySelector('.pv-name');
      name.textContent = form.elements.ui_brand_name.value || name.dataset.default;
      name.hidden = !form.elements.ui_show_name.checked && !!logo;
    };
    var master = form.elements.ui_custom;
    var designFields = ['ui_primary', 'ui_navbar', 'ui_theme', 'ui_radius', 'ui_logo_height', 'ui_show_name', 'logo', 'favicon', 'ui_jitsi'];
    var autoEnable = function (ev) {
      if (!master || master.checked || !ev.target || designFields.indexOf(ev.target.name) < 0) { return; }
      master.checked = true;
      var note = document.getElementById('design-autoenabled');
      if (note) { note.hidden = false; }
    };
    form.addEventListener('input', autoEnable);
    form.addEventListener('change', autoEnable);
    form.addEventListener('input', update);
    form.addEventListener('change', update);
    document.addEventListener('coloris:pick', update);
    var file = form.elements.logo;
    if (file) {
      file.addEventListener('change', function () {
        if (!file.files[0]) { return; }
        var img = pv.querySelector('.pv-logo');
        if (!img) { img = document.createElement('img'); img.className = 'pv-logo'; pv.querySelector('.pv-nav').prepend(img); }
        img.src = URL.createObjectURL(file.files[0]);
        update();
      });
    }
    update();
  }

  /* ---- Hinweise automatisch ausblenden -------------------------------- */
  $('.alert[data-autohide]').forEach(function (el) {
    setTimeout(function () { bootstrap.Alert.getOrCreateInstance(el).close(); }, 6000);
  });

  /* ---- Tooltips ------------------------------------------------------- */
  $('[data-bs-toggle="tooltip"]').forEach(function (el) { new bootstrap.Tooltip(el); });

  /* ---- Verarbeitende Aufnahmen: Seite regelmäßig auffrischen ---------- */
  var refresh = document.querySelector('[data-autorefresh]');
  if (refresh) {
    setTimeout(function () {
      if (!document.hidden && !document.querySelector('input:focus, textarea:focus')) { location.reload(); }
    }, parseInt(refresh.dataset.autorefresh, 10) * 1000);
  }
})();
