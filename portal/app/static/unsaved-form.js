/* Native protection for edits that have not been submitted yet. */
(function () {
  'use strict';
  var dirty = new Set();
  document.querySelectorAll('form[data-unsaved]').forEach(function (form) {
    form.addEventListener('input', function () { dirty.add(form); });
    form.addEventListener('change', function () { dirty.add(form); });
    form.addEventListener('submit', function () { dirty.delete(form); });
  });
  window.addEventListener('beforeunload', function (event) {
    if (!dirty.size) return;
    event.preventDefault();
    event.returnValue = '';
  });
})();
