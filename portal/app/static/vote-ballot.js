// Stimmzettel: Enthaltung sperrt die übrigen Antworten der Frage, Punktezähler, Plätze nicht doppelt.
(function () {
  'use strict';
  document.querySelectorAll('.vote-q').forEach(function (fs) {
    var abstain = fs.querySelector('.vote-abstain');
    var inputs = fs.querySelectorAll('.vote-opts input, .vote-opts select');
    var left = fs.querySelector('.vote-left');
    var total = parseInt(fs.dataset.points, 10) || 0;
    function sync() {
      var off = abstain && abstain.checked;
      inputs.forEach(function (el) { el.disabled = off; });
      fs.querySelector('.vote-opts').classList.toggle('opacity-50', !!off);
      if (left) {
        var used = 0;
        fs.querySelectorAll('.vote-pts').forEach(function (el) { used += parseInt(el.value, 10) || 0; });
        left.textContent = total - used;
        left.classList.toggle('text-danger', used > total);
      }
      if (fs.dataset.kind === 'rank') {
        var taken = {};
        fs.querySelectorAll('.vote-opts select').forEach(function (s) { if (s.value) taken[s.value] = (taken[s.value] || 0) + 1; });
        fs.querySelectorAll('.vote-opts select').forEach(function (s) { s.classList.toggle('is-invalid', !!s.value && taken[s.value] > 1); });
      }
    }
    fs.addEventListener('input', sync);
    fs.addEventListener('change', sync);
    sync();
  });
})();
