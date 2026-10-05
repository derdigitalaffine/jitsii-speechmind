/* Krankmelder: Formularlogik (Bemerkungsfeld je Arbeitgeber, Folgebescheinigung, privat versichert). */
(function () {
  'use strict';
  var form = document.getElementById('krank-form');
  if (!form) { return; }
  var employer = document.getElementById('kf-employer');
  var remarks = document.getElementById('kf-remarks-box');
  var syncRemarks = function () {
    var opt = employer && employer.options[employer.selectedIndex];
    if (remarks) { remarks.classList.toggle('d-none', !(opt && opt.dataset.remarks === '1')); }
  };
  if (employer) { employer.addEventListener('change', syncRemarks); syncRemarks(); }

  var first = document.getElementById('kf-first');
  var from = form.querySelector('input[name="from"][data-first-required]');
  var syncFirst = function () {
    if (!first || !from) { return; }
    var isFirst = first.value === '1';
    from.required = isFirst;
    var star = form.querySelector('label[for="kf-from"] .text-danger');
    if (star) { star.classList.toggle('d-none', !isFirst); }
  };
  if (first) { first.addEventListener('change', syncFirst); syncFirst(); }

  var hint = document.getElementById('kf-private-hint');
  var syncInsured = function () {
    var priv = form.querySelector('input[name="insured"][value="private"]');
    var on = !!(priv && priv.checked);
    if (hint) { hint.classList.toggle('d-none', !on); }
    var btn = form.querySelector('button[type="submit"]');
    if (btn && form.dataset.kind === 'eau') { btn.disabled = on; }
  };
  form.querySelectorAll('input[name="insured"]').forEach(function (el) { el.addEventListener('change', syncInsured); });
  syncInsured();

  var to = form.querySelector('input[name="to"]');
  if (from && to) {
    from.addEventListener('change', function () { if (from.value) { to.min = from.value; } });
  }
  form.addEventListener('submit', function () {
    var btn = form.querySelector('button[type="submit"]');
    if (btn) { setTimeout(function () { btn.disabled = true; }, 0); }
  });
})();
