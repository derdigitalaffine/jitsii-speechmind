/* Vorgang: Nachforderung zusammenstellen, Arbeitsschritt erst nach allen Prüfpunkten erledigen. */
(function () {
  'use strict';
  var bundleEl = document.getElementById('req-bundle');
  if (bundleEl && window.FieldList) {
    var bundle = JSON.parse(bundleEl.textContent);
    var target = document.getElementById('req-items');
    var editor = FieldList.mount(document.getElementById('req-fields'), {
      types: bundle.types, subtypes: bundle.subtypes, order: bundle.order, items: [],
      onChange: function (list) { target.value = JSON.stringify(list); }
    });
    target.value = '[]';
    var due = document.getElementById('req-due');
    var setDue = function (days) {
      var d = new Date(); d.setDate(d.getDate() + days);
      due.value = d.toISOString().slice(0, 10);
    };
    setDue(14);
    var sel = document.getElementById('req-tpl');
    (bundle.templates || []).forEach(function (t) {
      var o = document.createElement('option'); o.value = t.id; o.textContent = t.name; sel.appendChild(o);
    });
    if (!bundle.templates || !bundle.templates.length) { sel.closest('.col-md-5').classList.add('d-none'); }
    sel.addEventListener('change', function () {
      var t = (bundle.templates || []).filter(function (x) { return String(x.id) === sel.value; })[0];
      if (!t) { return; }
      document.getElementById('req-name').value = t.name;
      document.getElementById('req-msg').value = t.message || '';
      editor.set(t.items || []);
      setDue(t.due_days || 14);
    });
    // Prozessschritt „Nachforderung – Sachbearbeitung wählt“: Vorschlag aus dem Prozess vorbelegen
    var composeEl = document.getElementById('req-compose');
    if (composeEl) {
      var c = JSON.parse(composeEl.textContent);
      document.querySelectorAll('.js-compose').forEach(function (btn) {
        btn.addEventListener('click', function () {
          document.getElementById('req-task').value = c.task_id;
          document.getElementById('req-name').value = c.title || 'Bitte ergänzen Sie Ihren Antrag';
          document.getElementById('req-msg').value = c.message || '';
          editor.set(c.items || []);
          document.querySelectorAll('#req-form input[name="reopen"]').forEach(function (x) { x.checked = (c.reopen || []).indexOf(x.value) >= 0; });
          setDue(c.due_days || 14);
        });
      });
      document.querySelectorAll('[data-bs-target="#req-modal"]:not(.js-compose)').forEach(function (btn) {
        btn.addEventListener('click', function () { document.getElementById('req-task').value = ''; });
      });
    }
    document.getElementById('req-form').addEventListener('submit', function (ev) {
      var reopen = this.querySelectorAll('input[name="reopen"]:checked').length;
      var fields = editor.get().filter(function (x) { return x.type !== 'text'; });
      var untitled = fields.filter(function (x) { return !String(x.title || '').trim(); });
      if (!fields.length && !reopen) {
        ev.preventDefault();
        (window.Swal ? Swal.fire.bind(Swal) : alert)('Bitte mindestens ein Feld hinzufügen oder eine Angabe zur Korrektur auswählen.');
      } else if (untitled.length) {
        ev.preventDefault();
        (window.Swal ? Swal.fire.bind(Swal) : alert)('Bitte jedem Feld eine Bezeichnung geben – sonst weiß die antragstellende Person nicht, was gemeint ist.');
      }
    });
  }

  document.querySelectorAll('.js-task-form').forEach(function (form) {
    var checks = form.querySelectorAll('.js-check'), done = form.querySelector('.js-done'), hint = form.querySelector('.js-check-hint');
    function update() {
      var open = Array.prototype.filter.call(checks, function (c) { return !c.checked; }).length;
      if (done) { done.disabled = open > 0; }
      if (hint) { hint.textContent = open ? 'Noch ' + open + ' Prüfpunkt(e) offen.' : ''; }
    }
    checks.forEach(function (c) { c.addEventListener('change', update); });
    update();
    var reject = form.querySelector('.js-reject');
    if (reject) {
      reject.addEventListener('click', function (ev) {
        var c = form.querySelector('[name="comment"]');
        if (!c.value.trim()) { ev.preventDefault(); c.setCustomValidity('Bitte begründen.'); c.reportValidity(); c.setCustomValidity(''); c.focus(); }
      });
      form.querySelectorAll('[required]').forEach(function (x) { x.removeAttribute('required'); });
    }
  });
})();
