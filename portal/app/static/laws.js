/* Rechtstexte: Inhaltsverzeichnis filtern, aktuellen Abschnitt markieren, Suchbegriffe hervorheben. */
(function () {
  'use strict';
  var toc = document.querySelector('.lex-toc');

  /* Inhaltsverzeichnis filtern (Treffer bleiben samt übergeordneter Ebenen sichtbar) */
  var filter = document.getElementById('toc-filter');
  if (filter && toc) {
    filter.addEventListener('input', function () {
      var q = filter.value.trim().toLowerCase();
      var items = toc.querySelectorAll('li');
      items.forEach(function (li) { li.classList.toggle('toc-hidden', !!q); });
      if (!q) { return; }
      items.forEach(function (li) {
        var a = li.querySelector('a');
        if (a && a.textContent.toLowerCase().indexOf(q) !== -1) {
          var node = li;
          while (node && node !== toc) {
            if (node.tagName === 'LI') { node.classList.remove('toc-hidden'); }
            if (node.tagName === 'DETAILS') { node.open = true; }
            node = node.parentElement;
          }
          li.querySelectorAll('li').forEach(function (c) { c.classList.remove('toc-hidden'); });
        }
      });
    });
  }

  /* Volltext: beim Scrollen den sichtbaren Abschnitt im Verzeichnis markieren */
  if (toc && toc.dataset.mode === 'full' && 'IntersectionObserver' in window) {
    var links = {};
    toc.querySelectorAll('a[href^="#"]').forEach(function (a) { links[a.getAttribute('href').slice(1)] = a; });
    var active = null;
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) { return; }
        var a = links[e.target.id];
        if (!a || a === active) { return; }
        if (active) { active.classList.remove('active'); }
        active = a;
        a.classList.add('active');
        var box = toc.querySelector('.lex-toc-scroll');
        if (box && (a.offsetTop < box.scrollTop || a.offsetTop > box.scrollTop + box.clientHeight - 40)) {
          box.scrollTop = a.offsetTop - box.clientHeight / 3;
        }
      });
    }, { rootMargin: '-80px 0px -70% 0px' });
    document.querySelectorAll('.lex-unit[id]').forEach(function (el) { observer.observe(el); });
  }

  /* Suchbegriffe im Text markieren */
  var body = document.querySelector('.lex[data-q]');
  var words = body ? (body.dataset.q || '').split(/\s+/).filter(function (w) { return w.length > 1; }) : [];
  if (body && words.length) {
    var esc = function (s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); };
    var re = new RegExp('(' + words.map(esc).join('|') + ')', 'gi');
    var walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, null);
    var nodes = [];
    while (walker.nextNode()) { if (re.test(walker.currentNode.nodeValue)) { nodes.push(walker.currentNode); } re.lastIndex = 0; }
    nodes.forEach(function (n) {
      var frag = document.createDocumentFragment();
      n.nodeValue.split(re).forEach(function (part, i) {
        if (i % 2) { var m = document.createElement('mark'); m.textContent = part; frag.appendChild(m); }
        else if (part) { frag.appendChild(document.createTextNode(part)); }
      });
      n.parentNode.replaceChild(frag, n);
    });
    var first = body.querySelector('mark');
    if (first && !location.hash) { first.scrollIntoView({ block: 'center' }); }
  }
})();
