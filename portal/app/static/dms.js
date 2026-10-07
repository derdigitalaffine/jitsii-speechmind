// Open the edited folder and its parent folders after server redirects to an anchor.
(function () {
  function reveal() {
    const target = document.getElementById(location.hash.slice(1));
    if (!target) return;
    let node = target;
    while (node) { if (node.tagName === 'DETAILS') node.open = true; node = node.parentElement; }
  }
  reveal(); window.addEventListener('hashchange', reveal);
})();
// Ablage: Einträge markieren und gesammelt verschieben.
(function () {
  var all = document.getElementById('bulk-all');
  var go = document.getElementById('bulk-go');
  if (!go) return;
  var boxes = function () { return Array.prototype.slice.call(document.querySelectorAll('.js-bulk')); };
  var update = function () {
    var n = boxes().filter(function (b) { return b.checked; }).length;
    go.disabled = n === 0;
    go.innerHTML = '<i class="fa-solid fa-right-left me-1"></i>' + (n ? n + ' verschieben' : 'Verschieben');
  };
  document.addEventListener('change', function (e) {
    if (e.target === all) { boxes().forEach(function (b) { b.checked = all.checked; }); }
    if (e.target === all || e.target.classList.contains('js-bulk')) update();
  });
})();
