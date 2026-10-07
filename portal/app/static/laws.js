/* Rechtstexte: Inhaltsverzeichnis filtern, aktuellen Abschnitt markieren, Suchbegriffe hervorheben. */
(function () {
  'use strict';
  var toc = document.querySelector('.lex-toc');

  /* Overview filter keeps matching documents and their complete hierarchy visible. */
  var browser = document.querySelector('[data-law-browser]');
  if (browser) {
    var treeFilter = browser.querySelector('#law-tree-filter'), tools = browser.querySelector('.lex-browser-tools');
    var branches = Array.from(browser.querySelectorAll('.lex-branch')), documents = Array.from(browser.querySelectorAll('.lex-doc'));
    var disclosures = Array.from(browser.querySelectorAll('details')), beforeFilter = null, filtering = false;
    var storageKey = 'law-tree:' + location.pathname, stored = {};
    try { stored = JSON.parse(sessionStorage.getItem(storageKey) || '{}'); } catch (e) {}
    if (!stored || typeof stored !== 'object') { stored = {}; }
    branches.forEach(function (branch) { if (typeof stored[branch.dataset.level] === 'boolean') { branch.open = stored[branch.dataset.level]; } });
    function remember() {
      if (filtering) { return; }
      var states = {}; branches.forEach(function (branch) { states[branch.dataset.level] = branch.open; });
      try { sessionStorage.setItem(storageKey, JSON.stringify(states)); } catch (e) {}
    }
    branches.forEach(function (branch) { branch.addEventListener('toggle', remember); });
    var expandButtons = browser.querySelectorAll('[data-law-expand]');
    expandButtons.forEach(function (button) { button.addEventListener('click', function () { disclosures.forEach(function (d) { d.open = button.dataset.lawExpand === '1'; }); remember(); }); });
    if (tools && treeFilter) {
      tools.hidden = false;
      var count = browser.querySelector('[data-law-count]');
      function filterTree() {
        var q = treeFilter.value.trim().toLocaleLowerCase('de');
        if (q && !filtering) { beforeFilter = disclosures.map(function (d) { return d.open; }); }
        filtering = !!q;
        documents.forEach(function (doc) {
          var matches = !q || doc.textContent.toLocaleLowerCase('de').includes(q), ancestor = doc.parentElement;
          while (!matches && ancestor && ancestor !== browser) {
            if (ancestor.classList.contains('lex-branch')) { matches = ancestor.querySelector('summary').textContent.toLocaleLowerCase('de').includes(q); }
            ancestor = ancestor.parentElement;
          }
          doc.hidden = !matches;
          if (q && matches) { ancestor = doc.parentElement; while (ancestor && ancestor !== browser) { if (ancestor.tagName === 'DETAILS') { ancestor.open = true; } ancestor = ancestor.parentElement; } }
        });
        branches.slice().reverse().forEach(function (branch) {
          var ownMatch = branch.querySelector('summary').textContent.toLocaleLowerCase('de').includes(q);
          var children = Array.from(branch.querySelectorAll('.lex-doc'));
          branch.hidden = !!q && !ownMatch && !children.some(function (doc) { return !doc.hidden; }) && !Array.from(branch.querySelectorAll('.lex-branch')).some(function (child) { return !child.hidden; });
          if (q && ownMatch) { var node = branch; while (node && node !== browser) { if (node.tagName === 'DETAILS') { node.open = true; node.hidden = false; } node = node.parentElement; } }
        });
        if (!q && beforeFilter) { disclosures.forEach(function (d, i) { d.open = beforeFilter[i]; }); beforeFilter = null; }
        expandButtons.forEach(function (button) { button.disabled = !!q; });
        var visible = documents.filter(function (doc) { return !doc.hidden; }).length;
        count.textContent = q ? (visible ? visible + ' passende Rechtstexte. Treffer können in der Übersicht geöffnet werden.' : 'Keine passenden Titel oder Ebenen. Nutzen Sie die Volltextsuche für Inhalte.') : documents.length + ' Rechtstexte in der Übersicht. Ebenen lassen sich auf- und zuklappen.';
      }
      treeFilter.addEventListener('input', filterTree);
      browser.querySelector('[data-law-filter-clear]').addEventListener('click', function () { treeFilter.value = ''; filterTree(); treeFilter.focus(); });
      filterTree();
    }
    if (location.hash) { try { var target = document.getElementById(decodeURIComponent(location.hash.slice(1))); if (target && target.closest('[data-law-browser]') === browser) { var node = target; while (node && node !== browser) { if (node.tagName === 'DETAILS') { node.open = true; } node = node.parentElement; } var branch = target.querySelector('.lex-branch'); if (branch) { branch.open = true; } } } catch (e) {} }
    var printedStates;
    window.addEventListener('beforeprint', function () { printedStates = disclosures.map(function (d) { return d.open; }); disclosures.forEach(function (d) { d.open = true; }); });
    window.addEventListener('afterprint', function () { if (printedStates) { disclosures.forEach(function (d, i) { d.open = printedStates[i]; }); printedStates = null; } });
  }

  /* Table of contents: fold whole branches, filter without losing the prior state. */
  var filter = document.getElementById('toc-filter');
  if (toc) {
    var panel = toc.querySelector('.lex-toc-panel');
    if (panel && window.matchMedia) { panel.open = !window.matchMedia('(max-width: 991.98px)').matches; }
    var tocDetails = Array.from(toc.querySelectorAll('.lex-toc-scroll details')), tocBeforeFilter = null;
    var tocControls = toc.querySelector('.lex-toc-controls'); if (tocControls) { tocControls.hidden = false; }
    var tocButtons = toc.querySelectorAll('[data-toc-expand]');
    tocButtons.forEach(function (button) { button.addEventListener('click', function () { tocDetails.forEach(function (d) { d.open = button.dataset.tocExpand === '1'; }); }); });
    if (filter) {
      filter.addEventListener('input', function () {
        var q = filter.value.trim().toLowerCase(), items = toc.querySelectorAll('li');
        if (q && !tocBeforeFilter) { tocBeforeFilter = tocDetails.map(function (d) { return d.open; }); }
        items.forEach(function (li) { li.classList.toggle('toc-hidden', !!q); });
        tocButtons.forEach(function (button) { button.disabled = !!q; });
        if (!q) { if (tocBeforeFilter) { tocDetails.forEach(function (d, i) { d.open = tocBeforeFilter[i]; }); tocBeforeFilter = null; } return; }
        items.forEach(function (li) {
          var label = li.querySelector('.lex-toc-label') || li.querySelector('a');
          if (label && label.textContent.toLowerCase().includes(q)) {
            var node = li;
            while (node && node !== toc) { if (node.tagName === 'LI') { node.classList.remove('toc-hidden'); } if (node.tagName === 'DETAILS') { node.open = true; } node = node.parentElement; }
            li.querySelectorAll('li').forEach(function (c) { c.classList.remove('toc-hidden'); });
            li.querySelectorAll('details').forEach(function (d) { d.open = true; });
          }
        });
      });
    }
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
      ++seq;
      var q = input.value.trim();
      list.classList.add('d-none');
      if (q.length < 2) { list.classList.add('d-none'); return; }
      t = setTimeout(function () {
        var my = ++seq;
        fetch(input.dataset.suggest + '?q=' + encodeURIComponent(q), { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (items) {
          if (my !== seq || input.value.trim() !== q) return;
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
