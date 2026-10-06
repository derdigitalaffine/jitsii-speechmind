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

  /* Zu einer Einzelvorschrift springen: „5“, „5a“, „Art 3“, „Ziffer 4“, „3.2“ */
  document.querySelectorAll('.js-jump').forEach(function (f) {
    var known = (f.dataset.anchors || '').split(' ').filter(Boolean);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var v = f.nr.value.trim().toLowerCase().replace(/\s+/g, '');
      if (!v) return;
      var cands;
      if (/^(art|artikel)/.test(v)) cands = ['art' + v.replace(/^(artikel|art)\.?/, '')];
      else {
        var m = v.replace(/^§+/, '').match(/^([a-zäöü]*)\.?(\d+(?:\.\d+)*[a-z]?)\.?$/);
        if (!m) return;
        var num = m[2].replace(/\./g, '-'), word = { ziff: 'ziffer', nummer: 'nr' }[m[1]] || m[1];
        cands = (word ? [word + '-' + num] : []).concat(['p' + num, 'n' + num, 'ziffer-' + num, 'nr-' + num, 'punkt-' + num,
          'regel-' + num, 'klausel-' + num, 'abschnitt-' + num]);
      }
      var anchor = cands.filter(function (a) { return known.indexOf(a) >= 0; })[0] ||
        known.filter(function (a) { return cands.some(function (c) { return a.slice(-c.length - 1) === '-' + c; }); })[0] || cands[0];
      var el = document.getElementById(anchor);
      if (f.dataset.full === '1' && el) { el.scrollIntoView({ behavior: 'smooth', block: 'start' }); history.replaceState(null, '', '#' + anchor); return; }
      location.href = f.dataset.base + '/' + anchor;
    });
  });

  /* Schriftgröße (wird in diesem Browser gemerkt) */
  var lex = document.querySelector('.lex');
  var size = 0;
  try { size = parseInt(localStorage.getItem('lex-size') || '0', 10) || 0; } catch (e) { size = 0; }
  function applySize() { if (!lex) return; lex.classList.remove('lex-size--1', 'lex-size-1', 'lex-size-2'); if (size) lex.classList.add('lex-size-' + size); }
  applySize();
  document.querySelectorAll('.js-font').forEach(function (b) {
    b.addEventListener('click', function () {
      size = Math.max(-1, Math.min(2, size + parseInt(b.dataset.step, 10)));
      applySize();
      try { localStorage.setItem('lex-size', String(size)); } catch (e) { /* privat */ }
    });
  });

  /* Vorschläge beim Tippen in Suchfeldern mit data-suggest */
  document.querySelectorAll('input[data-suggest]').forEach(function (input) {
    var wrap = input.closest('.input-group') || input.parentElement;
    wrap.style.position = 'relative';
    var list = document.createElement('div');
    list.className = 'list-group lex-suggest shadow-sm d-none';
    list.setAttribute('role', 'listbox');
    wrap.appendChild(list);
    var t = null, seq = 0;
    input.setAttribute('autocomplete', 'off');
    input.addEventListener('input', function () {
      clearTimeout(t);
      var q = input.value.trim();
      if (q.length < 2) { list.classList.add('d-none'); return; }
      t = setTimeout(function () {
        var my = ++seq;
        fetch(input.dataset.suggest + '?q=' + encodeURIComponent(q), { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (items) {
          if (my !== seq) return;
          list.innerHTML = '';
          items.forEach(function (it) {
            var a = document.createElement('a');
            a.className = 'list-group-item list-group-item-action small';
            a.href = it.url; a.textContent = it.label; a.setAttribute('role', 'option');
            list.appendChild(a);
          });
          list.classList.toggle('d-none', !items.length);
        }).catch(function () {});
      }, 200);
    });
    input.addEventListener('keydown', function (e) {
      var items = Array.from(list.querySelectorAll('a'));
      if (e.key === 'ArrowDown' && items.length) { e.preventDefault(); items[0].focus(); }
      if (e.key === 'Escape') list.classList.add('d-none');
    });
    list.addEventListener('keydown', function (e) {
      var items = Array.from(list.querySelectorAll('a')), i = items.indexOf(document.activeElement);
      if (e.key === 'ArrowDown' && i < items.length - 1) { e.preventDefault(); items[i + 1].focus(); }
      if (e.key === 'ArrowUp') { e.preventDefault(); (i > 0 ? items[i - 1] : input).focus(); }
      if (e.key === 'Escape') { list.classList.add('d-none'); input.focus(); }
    });
    document.addEventListener('click', function (e) { if (!wrap.contains(e.target)) list.classList.add('d-none'); });
  });
})();
