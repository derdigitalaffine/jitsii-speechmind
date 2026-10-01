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
    new DataTable(table, {
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
    new Tagify(input, {
      pattern: /^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+$/,
      delimiters: ',|;|\\s',
      editTags: 1,
      keepInvalidTags: false,
      trim: true,
      originalInputValueFormat: function (v) { return v.map(function (x) { return x.value; }).join(','); },
      texts: { empty: 'Bitte ausfüllen', pattern: 'Ungültige E-Mail-Adresse', duplicate: 'Schon eingetragen' },
      dropdown: { enabled: 0 }
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
