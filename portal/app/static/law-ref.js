// Verweise auf Rechtstexte (a.law-ref, z. B. aus [[HStS § 4]] oder „§ 5 GemO“): beim Zeigen oder Antippen eine
// Vorschau des Paragrafen; ein zweites Antippen bzw. Klick öffnet den Text.
(function () {
  'use strict';
  if (!document.querySelector('a.law-ref')) return;
  var pop = null, timer = null, cache = {}, current = null;
  function close() { if (pop) { pop.remove(); pop = null; current = null; } }
  function place(a) {
    var r = a.getBoundingClientRect();
    var top = window.scrollY + r.bottom + 6, left = window.scrollX + Math.max(8, Math.min(r.left, window.innerWidth - pop.offsetWidth - 16));
    pop.style.top = top + 'px'; pop.style.left = left + 'px';
  }
  function show(a) {
    var url = a.dataset.preview;
    if (!url) return;
    current = a;
    var render = function (d) {
      if (current !== a) return;
      close(); current = a;
      pop = document.createElement('div');
      pop.className = 'law-pop';
      pop.setAttribute('role', 'tooltip');
      var head = document.createElement('div');
      head.className = 'law-pop-head';
      head.textContent = d.label + (d.short_title && d.label !== d.short_title ? ' ' + d.short_title : '');
      pop.appendChild(head);
      var body = document.createElement('div');
      body.innerHTML = d.html || '<p class="text-secondary mb-1">' + (d.title || '').replace(/[&<>]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; }) + '</p>';
      pop.appendChild(body);
      var more = document.createElement('a');
      more.href = d.url; more.target = '_blank'; more.rel = 'noopener'; more.className = 'small';
      more.textContent = 'Ganzen Text öffnen →';
      pop.appendChild(more);
      pop.addEventListener('mouseenter', function () { clearTimeout(timer); });
      pop.addEventListener('mouseleave', function () { timer = setTimeout(close, 250); });
      document.body.appendChild(pop);
      place(a);
    };
    if (cache[url]) { render(cache[url]); return; }
    fetch(url + (url.indexOf('?') < 0 ? '?' : '&') + 'format=json', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) { cache[url] = d; render(d); } })
      .catch(function () {});
  }
  document.addEventListener('mouseover', function (e) {
    var a = e.target.closest && e.target.closest('a.law-ref');
    if (!a || a === current) return;
    clearTimeout(timer);
    timer = setTimeout(function () { show(a); }, 250);
  });
  document.addEventListener('mouseout', function (e) {
    var a = e.target.closest && e.target.closest('a.law-ref');
    if (a) { clearTimeout(timer); timer = setTimeout(close, 300); }
  });
  document.addEventListener('focusin', function (e) { var a = e.target.closest && e.target.closest('a.law-ref'); if (a) show(a); });
  // Touch: erstes Antippen zeigt die Vorschau, zweites folgt dem Link
  document.addEventListener('touchstart', function (e) {
    var a = e.target.closest && e.target.closest('a.law-ref');
    if (!a) { if (pop && !(e.target.closest && e.target.closest('.law-pop'))) close(); return; }
    if (current !== a) { e.preventDefault(); show(a); }
  }, { passive: false });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
})();
