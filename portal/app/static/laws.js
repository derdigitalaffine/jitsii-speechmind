/* Rechtstexte: Inhaltsverzeichnis filtern, aktuellen Abschnitt markieren, Suchbegriffe hervorheben. */
(function () {
  'use strict';
  var toc = document.querySelector('.lex-toc');
  var catalogFilters = document.querySelector('[data-catalog-filters]');
  if (catalogFilters && window.matchMedia && window.matchMedia('(max-width: 575.98px)').matches) { catalogFilters.open = false; }

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
        var suggestionUrl = new URL(input.dataset.suggest, location.href); suggestionUrl.searchParams.set('q', q);
        fetch(suggestionUrl.toString(), { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (items) {
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

(function(){var picker=document.querySelector('.law-topic-picker');if(picker){var selected=picker.querySelector('[data-topic-selected]');function update(){selected.replaceChildren();picker.querySelectorAll('[data-topic-label]').forEach(function(row){row.classList.toggle('is-selected',row.querySelector('input').checked);if(row.querySelector('input').checked){var badge=document.createElement('span');badge.className='badge text-bg-primary';badge.textContent=row.dataset.topicLabel;selected.appendChild(badge);}});if(!selected.children.length)selected.textContent='Noch keine Themen ausgewählt.';}picker.addEventListener('change',update);picker.querySelector('[data-topic-search]').addEventListener('input',function(){var q=this.value.toLocaleLowerCase('de');picker.querySelectorAll('[data-topic-label]').forEach(function(row){row.hidden=!row.dataset.topicLabel.toLocaleLowerCase('de').includes(q);});});update();}
var form=document.querySelector('#law-form,#plan-form');if(form){var key='law-editor-scroll:'+location.pathname;form.addEventListener('submit',function(e){try{if(!e.submitter||e.submitter.value==='stay')sessionStorage.setItem(key,String(window.scrollY));else sessionStorage.removeItem(key);}catch(_){} });if(new URLSearchParams(location.search).get('saved')==='1'){try{var scroll=sessionStorage.getItem(key);sessionStorage.removeItem(key);if(scroll)requestAnimationFrame(()=>window.scrollTo(0,Number(scroll)));}catch(_){} }}})();

(function(){var browser=document.querySelector('[data-law-browser]');if(!browser)return;var pref='law-catalog-view';function setView(v){browser.dataset.view=v;browser.querySelectorAll('[data-law-view]').forEach(function(a){a.setAttribute('aria-pressed',a.dataset.lawView===v?'true':'false');a.classList.toggle('btn-primary',a.dataset.lawView===v);});browser.querySelector('input[name=ansicht]').value=v;browser.querySelectorAll('a[href]').forEach(function(a){if(a.hasAttribute('data-law-view'))return;var u=new URL(a.href,location.href);if(u.hash==='#catalog-results'){u.searchParams.set('ansicht',v);a.href=u.toString();}});}try{if(!new URLSearchParams(location.search).has('ansicht'))setView(localStorage.getItem(pref)==='bloecke'?'bloecke':'tabelle');}catch(_){}browser.querySelectorAll('[data-law-view]').forEach(function(a){a.addEventListener('click',function(e){e.preventDefault();setView(this.dataset.lawView);try{localStorage.setItem(pref,this.dataset.lawView);}catch(_){}history.replaceState(null,'',this.href);});});var panel=browser.querySelector('.law-org-panel');if(matchMedia('(max-width:991px)').matches)panel.open=false;var details=Array.from(browser.querySelectorAll('[data-org-detail]'));var treePref='law-catalog-tree',savedTree={};try{savedTree=JSON.parse(localStorage.getItem(treePref)||'{}');}catch(_){}details.forEach(function(d){if(!d.open&&Object.prototype.hasOwnProperty.call(savedTree,d.dataset.orgDetail))d.open=!!savedTree[d.dataset.orgDetail];d.addEventListener('toggle',function(){if(browser.querySelector('#law-org-search').value.trim())return;savedTree[d.dataset.orgDetail]=d.open;try{localStorage.setItem(treePref,JSON.stringify(savedTree));}catch(_){} });});browser.querySelectorAll('[data-org-expand]').forEach(function(b){b.addEventListener('click',function(){details.forEach(d=>d.open=b.dataset.orgExpand==='1');});});var before=null;browser.querySelector('#law-org-search').addEventListener('input',function(){var q=this.value.trim().toLocaleLowerCase('de');if(q&&!before)before=details.map(d=>d.open);browser.querySelectorAll('[data-org-node]').forEach(function(node){var own=node.dataset.orgName.includes(q),child=Array.from(node.querySelectorAll('[data-org-node]')).some(n=>n.dataset.orgName.includes(q));node.hidden=!!q&&!own&&!child;if(q&&child){var d=node.querySelector(':scope>details');if(d)d.open=true;}});if(!q&&before){details.forEach((d,i)=>d.open=before[i]);before=null;}});})();

(function(){if(!document.querySelector('.lex'))return;if(new URLSearchParams(location.search).get('druck')==='1')window.addEventListener('load',()=>setTimeout(()=>window.print(),100));if(location.hash==='#fassungen'){var button=document.querySelector('#fassungen [data-bs-toggle=dropdown]');if(button&&window.bootstrap)bootstrap.Dropdown.getOrCreateInstance(button).show();}})();
