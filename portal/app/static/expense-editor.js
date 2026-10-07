(function () {
  'use strict';
  var filter = document.getElementById('rate-profile-filter');
  if (filter) filter.addEventListener('change', function () {
    document.querySelectorAll('[data-rule-profile]').forEach(function (card) {
      card.hidden = !!filter.value && card.dataset.ruleProfile !== filter.value;
    });
  });
  var form = document.getElementById('expense-editor');
  if (!form) return;
  var original = JSON.parse(document.getElementById('expense-original').textContent);
  var changes = document.getElementById('rate-changes');
  var from = form.elements.valid_from, until = form.elements.valid_until;
  function refresh() {
    until.min = from.value;
    until.setCustomValidity(from.value && until.value && until.value < from.value ? 'Das Ende darf nicht vor dem Beginn liegen.' : '');
    if (!changes) return;
    changes.replaceChildren();
    form.querySelectorAll('[data-rate-label]').forEach(function (input) {
      if (Number(input.value) === Number(original[input.name]) && input.value !== '') return;
      var li = document.createElement('li');
      li.textContent = input.dataset.rateLabel + ': ' + (original[input.name] || '—') + ' → ' + (input.value || '—') + ' ' + input.dataset.rateUnit;
      changes.appendChild(li);
    });
    if (!changes.children.length) {
      var li = document.createElement('li'); li.textContent = 'Keine Sätze geändert. Bezeichnung, Zeitraum und Quelle separat prüfen.'; changes.appendChild(li);
    }
  }
  form.addEventListener('input', refresh); refresh();
})();
